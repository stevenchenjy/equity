"""The adopted index core reaches research without becoming a company model."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from _support import PROJECT_ROOT, SCRIPT_DIR  # noqa: F401
import build_current_research_baseline as baseline
import long_horizon_research as long_research
import refresh_daily_evidence as evidence
import refresh_valuation_scenarios as valuation


CORE = ("SPY", "QQQM")


class IndexCoreResearchRoutingTests(unittest.TestCase):
    def test_core_funds_do_not_consume_three_company_signal_slots(self):
        def rows(path):
            if path == baseline.SIGNAL_SCORES_PATH:
                return [dict(ticker=t, total_score="9", data_quality_label="ok")
                        for t in ("QQQM", "SPY", "AAA", "BBB", "CCC", "DDD")]
            return []

        with (patch.object(baseline, "read_csv", side_effect=rows),
              patch.object(baseline, "approved_core_tickers", return_value=CORE),
              patch.object(baseline, "requested_coverage_tickers", return_value=set()),
              patch.object(baseline, "retained_company_tickers", return_value=set())):
            selected, held = baseline.selected_tickers()
        self.assertEqual(set(selected), {*CORE, "AAA", "BBB", "CCC"})
        self.assertFalse(held)

    def test_baseline_routes_both_approved_funds_and_keeps_other_funds_separate(self):
        tickers = [*CORE, "XLI"]

        def rows(path):
            if path == baseline.MARKET_SNAPSHOT_PATH:
                return [dict(ticker=t, market_session_date="2026-10-16", last_price="100",
                             data_quality_label="ok", data_source="fixture") for t in tickers]
            if path == baseline.UNIVERSE_PATH:
                return [dict(ticker=t, is_benchmark="yes") for t in tickers]
            return []

        with (patch.object(baseline, "read_csv", side_effect=rows),
              patch.object(baseline, "selected_tickers", return_value=(tickers, set())),
              patch.object(baseline, "is_core_allocation_ticker", side_effect=lambda t: t in CORE),
              patch.object(baseline, "latest_published_market_session", return_value=date(2026, 10, 16)),
              patch.object(baseline, "atomic_write_csv") as output):
            self.assertEqual(baseline.main(), 0)
        by = {r["ticker"]: r for r in output.call_args.args[2]}
        for ticker in CORE:
            self.assertEqual(by[ticker]["research_role"], "core_allocation_candidate")
            self.assertEqual(by[ticker]["recommendation_label"], "core_allocation_candidate")
            self.assertEqual(by[ticker]["human_action_required"], "no")
        self.assertEqual(by["XLI"]["research_role"], "etf_research_candidate")
        self.assertEqual(by["XLI"]["recommendation_label"], "watch_for_allocation_review")

    def test_both_core_funds_remain_in_evidence_scope_without_company_xbrl(self):
        with (patch.object(evidence, "read_csv", return_value=[]),
              patch.object(evidence, "approved_core_tickers", return_value=CORE)):
            held, watched = evidence.researched_tickers()
        self.assertEqual(held, [])
        self.assertEqual(set(watched), set(CORE))
        self.assertFalse(evidence.company_fundamentals_required("QQQM"))
        self.assertTrue(evidence.company_fundamentals_required("MSFT"))

    def test_valuation_does_not_construct_company_scenarios_for_any_fund(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / name for name in ("BASELINE_PATH", "FUNDAMENTALS_PATH",
                     "MARKET_SNAPSHOT_PATH", "SCENARIO_PATH", "POLICY_PATH", "DEFAULT_BUNDLE_PATH")}
            paths["POLICY_PATH"].write_text(valuation.POLICY_PATH.read_text())
            with paths["BASELINE_PATH"].open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["ticker", "valuation_check", "valuation_reasonableness_score"])
                writer.writeheader()
                writer.writerows(dict(ticker=t, valuation_check="", valuation_reasonableness_score="")
                                 for t in (*CORE, "QQQ", "XLI"))
            for name in ("FUNDAMENTALS_PATH", "MARKET_SNAPSHOT_PATH"):
                paths[name].write_text("ticker\n")
            with (patch.multiple(valuation, ROOT=root, **paths),
                  patch.object(valuation, "is_core_allocation_ticker", side_effect=lambda t: t in CORE),
                  patch.object(valuation, "valuation_input_issues", side_effect=AssertionError("fund is not company"))):
                self.assertEqual(valuation.main(), 0)
            with paths["BASELINE_PATH"].open() as handle:
                rows = {r["ticker"]: r for r in csv.DictReader(handle)}
            self.assertTrue(all(rows[t]["valuation_check"].startswith("index_core_candidate;") for t in CORE))
            self.assertTrue(rows["XLI"]["valuation_check"].startswith("etf_research_candidate;"))
            self.assertEqual(json.loads(paths["SCENARIO_PATH"].read_text())["records"], [])
            self.assertEqual(json.loads(paths["DEFAULT_BUNDLE_PATH"].read_text())["records"], [])

    def test_held_long_horizon_fund_status_respects_adopted_policy(self):
        policy = json.loads((PROJECT_ROOT / "01_policies/long_horizon_research_policy.json").read_text())
        with patch.object(long_research, "is_core_allocation_ticker", side_effect=lambda t: t in CORE):
            report = long_research.build_long_horizon_report([], [dict(ticker=t) for t in (*CORE, "XLI")],
                [], policy, "2026-10-19T20:00:00-04:00")
        for ticker in CORE:
            self.assertEqual(report["companies"][ticker]["readiness"], "not_applicable_core")
        self.assertEqual(report["companies"]["XLI"]["readiness"], "not_applicable_etf")
        self.assertFalse(report["recommendation_authority"])
        self.assertFalse(report["automatic_action_allowed"])


if __name__ == "__main__":
    unittest.main()
