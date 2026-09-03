from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import build_phase5r_current_research_baseline as baseline
import calculate_phase5r_c9_dynamic_weights as weights
import create_phase5r_c9_cash_deployment_plan as cash_plan
import create_phase5r_c9_exact_action_plan as action_plan
import phase5r_c9_common as c9
import refresh_phase5r_daily_evidence as evidence


class HeldCorePositionTests(unittest.TestCase):
    def test_policy_core_ticker_uses_benchmark_metadata(self) -> None:
        self.assertTrue(c9.is_core_allocation_ticker("spy"))
        self.assertFalse(c9.is_core_allocation_ticker("QQQ"))
        self.assertFalse(c9.is_core_allocation_ticker("IOT"))

    def test_company_fundamentals_are_not_required_for_spy(self) -> None:
        self.assertFalse(evidence.company_fundamentals_required("SPY"))
        self.assertTrue(evidence.company_fundamentals_required("IOT"))

    def test_held_benchmark_does_not_require_company_fundamentals(self) -> None:
        captured: list[dict[str, str]] = []

        def fake_read(path: Path) -> list[dict[str, str]]:
            if path == baseline.MARKET_SNAPSHOT_PATH:
                return [{
                    "ticker": "SPY",
                    "market_session_date": "2026-09-02",
                    "data_quality_label": "ok",
                    "last_price": "765.00",
                    "intraday_change_pct": "0.1",
                    "data_source": "test",
                }]
            if path == baseline.SIGNAL_SCORES_PATH:
                return [{"ticker": "SPY", "total_score": "5.5"}]
            if path == baseline.FUNDAMENTALS_PATH:
                return []
            if path == baseline.UNIVERSE_PATH:
                return [{
                    "ticker": "SPY",
                    "theme": "Benchmark ETF",
                    "is_benchmark": "yes",
                }]
            if path == baseline.POSITIONS_PATH:
                return [{
                    "ticker": "SPY",
                    "current_action": "review_required",
                    "horizon_class": "long_term_research",
                    "invalidation_rule": "Review core thesis.",
                }]
            if path == baseline.EVIDENCE_LEDGER_PATH:
                return []
            raise AssertionError(path)

        with (
            patch.object(baseline, "selected_tickers", return_value=(["SPY"], {"SPY"})),
            patch.object(baseline, "read_csv", side_effect=fake_read),
            patch.object(baseline, "latest_published_market_session", return_value=date(2026, 9, 2)),
            patch.object(baseline, "now_et"),
            patch.object(baseline, "cycle_date", return_value="2026-09-03"),
            patch.object(baseline, "iso_now", return_value="2026-09-03T12:00:00-04:00"),
            patch.object(baseline, "atomic_write_csv", side_effect=lambda _p, _f, rows: captured.extend(rows)),
        ):
            self.assertEqual(baseline.main(), 0)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["research_role"], "current_position")
        self.assertEqual(captured[0]["recommendation_label"], "hold_existing")
        self.assertEqual(captured[0]["recommendation_confidence"], "medium_high")
        self.assertEqual(captured[0]["primary_source_url"], "")

    def test_dynamic_summary_separates_spy_core_from_active_stock(self) -> None:
        account = {
            "account_total_value": 2400.0,
            "prior_account_value": 1000.0,
            "new_external_cash": 1500.0,
            "cash_available": 1200.0,
            "cash_reserved": 500.0,
            "active_stock_target_pct": 20.0,
            "active_stock_hard_cap_pct": 30.0,
            "cash_target_pct": 20.0,
            "single_stock_default_cap_pct": 6.0,
            "single_stock_hard_cap_pct": 8.0,
            "last_updated": "2026-09-03T12:00:00-04:00",
        }
        positions = [
            {"ticker": "SPY", "shares": 1.0, "stored_historical_position_pct": 30.0},
            {"ticker": "IOT", "shares": 4.0, "stored_historical_position_pct": 7.0},
        ]
        market = {
            "SPY": {"last_price": "765", "data_timestamp": "2026-09-02", "data_source": "test", "data_quality_label": "ok"},
            "IOT": {"last_price": "39", "data_timestamp": "2026-09-02", "data_source": "test", "data_quality_label": "ok"},
        }
        packets = {"SPY": {}, "IOT": {}}
        written: dict[Path, list[dict[str, str]]] = {}

        with (
            patch.object(weights, "load_active_inhibit", return_value={"active": False}),
            patch.object(weights, "load_account_state", return_value=account),
            patch.object(weights, "load_positions", return_value=positions),
            patch.object(weights, "load_market_rows", return_value=market),
            patch.object(weights, "load_packets", return_value=packets),
            patch.object(weights, "is_core_allocation_ticker", side_effect=lambda ticker: ticker == "SPY"),
            patch.object(weights, "score_from_packet", return_value=6.0),
            patch.object(weights, "append_run_log"),
            patch.object(weights, "write_csv", side_effect=lambda path, rows, _fields: written.__setitem__(path, rows)),
        ):
            weights.main()

        dynamic = {row["ticker"]: row for row in written[weights.DYNAMIC_WEIGHTS]}
        summary = written[weights.PORTFOLIO_SUMMARY][0]
        self.assertEqual(dynamic["SPY"]["asset_role"], "core_allocation")
        self.assertEqual(dynamic["SPY"]["concentration_status"], "core_sleeve")
        self.assertEqual(dynamic["SPY"]["current_recommendation_label"], "hold_existing")
        self.assertEqual(dynamic["IOT"]["asset_role"], "active_stock")
        self.assertEqual(summary["current_core_value"], "765.00")
        self.assertEqual(summary["current_active_stock_value"], "156.00")

    def test_exact_action_does_not_apply_single_stock_cap_to_spy(self) -> None:
        written: dict[Path, list[dict[str, str]]] = {}
        account = {
            "single_stock_default_cap_pct": 6.0,
            "single_stock_hard_cap_pct": 8.0,
        }
        positions = {
            "SPY": {
                "ticker": "SPY",
                "horizon_class": "long_term_research",
                "invalidation_rule": "Review core thesis.",
            }
        }
        weight_rows = [{
            "ticker": "SPY",
            "asset_role": "core_allocation",
            "current_shares": "1",
            "latest_price": "765",
            "current_value": "765",
            "current_weight_pct": "31.0",
            "current_recommendation_label": "hold_existing",
            "concentration_status": "core_sleeve",
            "current_research_score": "6.0",
        }]
        with tempfile.TemporaryDirectory() as directory:
            valuation_path = Path(directory) / "valuations.json"
            policy_path = Path(directory) / "policy.json"
            valuation_path.write_text(json.dumps({"records": []}))
            policy_path.write_text(json.dumps({"held_position_review": {}}))
            with (
                patch.object(action_plan, "VALUATION_SCENARIO_PATH", valuation_path),
                patch.object(action_plan, "VALUATION_POLICY_PATH", policy_path),
                patch.object(action_plan, "load_active_inhibit", return_value={"active": False}),
                patch.object(action_plan, "load_account_state", return_value=account),
                patch.object(action_plan, "load_positions", return_value=list(positions.values())),
                patch.object(action_plan, "load_packets", return_value={"SPY": {"recommendation_confidence": "medium_high"}}),
                patch.object(action_plan, "read_csv", return_value=weight_rows),
                patch.object(action_plan, "load_portfolio_summary", return_value={"account_total_value": "2467"}),
                patch.object(action_plan, "append_run_log"),
                patch.object(action_plan, "write_csv", side_effect=lambda path, rows, _fields: written.__setitem__(path, rows)),
            ):
                action_plan.main()

        action = written[action_plan.EXACT_ACTION_PLAN][0]
        self.assertEqual(action["asset_role"], "core_allocation")
        self.assertEqual(action["recommended_action"], "hold")
        self.assertEqual(action["whole_shares_to_change"], "0")
        self.assertEqual(action["human_confirmation_required"], "no")

    def test_post_action_scenario_preserves_existing_core_value(self) -> None:
        row = cash_plan._post_action_row(
            scenario="test",
            account_total=2500.0,
            current_cash=1200.0,
            released_cash=0.0,
            core_ticker="SPY",
            core_shares=1,
            core_price=765.0,
            current_core_value=765.0,
            active_value=535.0,
            status="hypothetical",
            retained_cash_reason="test",
        )
        self.assertEqual(row["proposed_core_value"], "765.00")
        self.assertEqual(row["resulting_core_value"], "1530.00")
        self.assertEqual(row["resulting_cash"], "435.00")


if __name__ == "__main__":
    unittest.main()
