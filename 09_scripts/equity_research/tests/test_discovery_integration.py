from __future__ import annotations

import unittest
import copy
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import run_daily_refresh as refresh
import run_daily_refresh_scheduler as scheduler
import score_candidates as scoring
from account_common import dynamic_candidate_fit
from daily_common import recommendation_notification_fingerprint


class IndependentDiscoveryIntegrationTests(unittest.TestCase):
    def test_discovery_timeout_is_reported_without_suppressing_valid_account_review(self):
        writes = []
        def step(name, script, allowed, **kwargs):
            return {"name": name, "script": script, "allowed_to_fail": allowed,
                    "exit_code": 124 if name == "market_discovery" else 0}
        with (patch.object(refresh, "load_active_state"), patch.object(refresh, "load_inhibit"),
              patch.object(refresh, "log_daily_run"), patch.object(refresh, "run_step", side_effect=step),
              patch.object(refresh, "atomic_write_json", side_effect=lambda path, value: writes.append(copy.deepcopy(value)))):
            self.assertEqual(refresh.run_refresh(no_lock=True, market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE), 0)
        self.assertEqual(writes[-1]["advisory_failures"], ["market_discovery"])
        self.assertEqual(writes[-1]["soft_failures"], [])
        self.assertEqual(writes[-1]["hard_failures"], [])
        self.assertEqual(next(x for x in writes[-1]["steps"] if x["name"] == "market_discovery")["exit_code"], 124)

    def test_discovery_membership_changes_notify_but_prices_dates_and_rank_do_not(self):
        initial = {"independent_market_discovery": {
            "schema_version": "phase5r_market_discovery_v1", "status": "complete", "complete": True,
            "as_of_session": "2026-09-21", "top_etfs": [],
            "top_stocks": [{"ticker": ticker, "classification": "watchlist",
                            "research_status": "unresearched_discovery", "close": 100, "score": 10}
                           for ticker in ("C", "TJX")]}}
        same = copy.deepcopy(initial)
        same["independent_market_discovery"]["as_of_session"] = "2026-09-22"
        same["independent_market_discovery"]["top_stocks"].reverse()
        same["independent_market_discovery"]["top_stocks"][0].update(close=102, score=11)
        self.assertEqual(recommendation_notification_fingerprint(initial), recommendation_notification_fingerprint(same))
        same["independent_market_discovery"]["top_stocks"][0]["ticker"] = "EQT"
        self.assertNotEqual(recommendation_notification_fingerprint(initial), recommendation_notification_fingerprint(same))
        same = copy.deepcopy(initial)
        same["independent_market_discovery"].update(status="unavailable", complete=False, top_stocks=[])
        self.assertNotEqual(recommendation_notification_fingerprint(initial), recommendation_notification_fingerprint(same))

    def test_candidate_fit_uses_actual_allocation_not_theme(self):
        account = {"active_stock_target_pct": 50, "active_stock_hard_cap_pct": 60}
        for weight, expected in ((30, 7), (55, 5), (65, 1)):
            for theme in ("AI infrastructure", "Healthcare", "Energy"):
                self.assertEqual(dynamic_candidate_fit(theme, weight, account), expected)

    def test_theme_labels_cannot_change_legacy_score(self):
        row = dict(ticker="SYNTH", company_name="Synthetic", theme="AI infrastructure",
                   last_price="100", intraday_change_pct="2", relative_volume="1.2",
                   dollar_volume="200000000", data_source="synthetic",
                   data_quality_label="ok", market_data_usable="yes",
                   market_session_date="2026-09-21", liquidity_tier="large",
                   volatility_tier="medium", is_benchmark="no")
        scores = [scoring.score_row(row | {"theme": theme}, expected_market_session="2026-09-21")
                  for theme in ("AI infrastructure", "Healthcare", "Energy", "", "Cloud software")]
        self.assertEqual(len({x["total_score"] for x in scores}), 1)
        self.assertEqual({x["catalyst_score"] for x in scores}, {"5.00"})
        self.assertIn("no verified event", scores[0]["score_explanation"])

    def test_only_fetch_cycle_requests_discovery_network(self):
        with patch.object(refresh.subprocess, "run") as run:
            run.return_value.returncode = 0
            for mode, should_fetch in ((refresh.MARKET_SNAPSHOT_FETCH, True),
                                       (refresh.MARKET_SNAPSHOT_REUSE, False)):
                refresh.run_step("market_discovery", "market_discovery.py", True,
                                 market_snapshot_mode=mode)
                self.assertEqual("--refresh" in run.call_args.args[0], should_fetch)
                self.assertEqual(run.call_args.kwargs["timeout"], 360)

    def test_bootstrap_invokes_only_discovery(self):
        with patch.object(scheduler.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(scheduler._run_market_discovery_only(), 0)
        args = run.call_args.args[0]
        self.assertTrue(args[1].endswith("market_discovery.py"))
        self.assertEqual(args[2:], ["--refresh"])
        self.assertEqual(run.call_args.kwargs["timeout"], 900)
        self.assertEqual(run.call_args.kwargs["stdout"], scheduler.subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
