from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import track_phase5r_recommendation_outcomes as outcomes
from phase5r_portfolio_construction import core_starter_decision
from create_phase5r_research_questions import reverse_expectations, whole_share_diagnostics


class ReassessmentReportingTests(unittest.TestCase):
    def test_cash_affordability_and_target_gap_are_separate(self):
        result = core_starter_decision(
            policy={"core_starter_review": {"minimum_entry_score": 5, "maximum_52_week_range_percentile": 95, "maximum_whole_shares_per_review": 1}},
            market_quality="ok", technical_score=7, current_price=773.17,
            fifty_two_week_high=850, fifty_two_week_low=400,
            account_total=2429.84, deployable_cash=909.53,
            current_core_value=773.17, core_target_pct=60, maintenance_active=False,
        )
        self.assertFalse(result["selected"])
        self.assertEqual(result["suggested_whole_shares"], 0)
        self.assertTrue(result["gate_results"]["whole_share_affordability"])
        self.assertFalse(result["gate_results"]["whole_share_target_gap"])
        self.assertEqual(result["failed_gates"], ["whole_share_target_gap"])

    def test_origin_never_uses_close_before_creation(self):
        snapshot = {"market_session": "2026-09-02", "created_at": "2026-09-04T22:36:13-04:00"}
        self.assertIsNone(outcomes.forecast_origin(snapshot, ["2026-09-02", "2026-09-03", "2026-09-04"]))
        self.assertEqual(outcomes.forecast_origin(snapshot, ["2026-09-02", "2026-09-04", "2026-09-08"]), "2026-09-08")
        self.assertIsNone(outcomes.forecast_origin({"market_session": "2026-09-02"}, ["2026-09-03"]))
        self.assertIsNone(outcomes.forecast_origin({"created_at": "2026-09-02T12:00:00"}, ["2026-09-03"]))
        self.assertEqual(outcomes.observation_id({"ticker": "IOT", "role": "held"}, "2026-09-03"), outcomes.observation_id({"ticker": "IOT", "role": "candidate"}, "2026-09-03"))

    def test_forward_evaluation_preserves_legacy_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outcomes.local.csv"
            snapshots = root / "snapshots.local.jsonl"
            output.write_text("snapshot_id,ticker\nold,IOT\n")
            sample = {"ticker": "IOT", "role": "held", "market_session": "2026-09-01", "created_at": "2026-09-02T12:00:00-04:00", "classification": "HOLD"}
            snapshots.write_text("\n".join(json.dumps({**sample, "snapshot_id": sid}) for sid in ("a", "b")))
            history = [{"ticker": ticker, "market_session": day, "close": str(price)} for ticker in ("IOT", "SPY", "QQQ") for day, price in (("2026-09-02", 100), ("2026-09-03", 110), ("2026-09-04", 121))]
            with patch.object(outcomes, "SNAPSHOT_PATH", snapshots), patch.object(outcomes, "OUTCOME_PATH", output):
                rows = outcomes.evaluate(history)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["entry_close"], "110.0000")
                self.assertEqual(rows[0]["absolute_return_pct"], "10.0000")
                self.assertEqual(rows[0]["maximum_adverse_excursion_pct"], "0.0000")
                self.assertEqual(sum(row["primary_observation"] == "yes" for row in rows), 1)
                self.assertEqual(outcomes.evaluate(history), rows)
            archive = root / "outcomes.local.pre_forward_v2.csv"
            self.assertEqual(archive.read_text(), "snapshot_id,ticker\nold,IOT\n")

    def test_no_new_or_ineligible_are_not_adds(self):
        self.assertEqual(outcomes.classification("no_new_buy"), "NO_NEW_POSITION")
        self.assertEqual(outcomes.classification("ineligible_buy_review"), "WATCH")
        self.assertIsNone(outcomes.number("inf"))

    def test_reverse_expectations_are_explicit_and_missing_debt_stays_unknown(self):
        scenario = {"status": "complete", "current_price": 10, "diluted_shares": 100, "cash": 0, "debt": 0, "revenue_ttm_or_proxy": 100, "scenario_multiples": {"base": 10}}
        rows = reverse_expectations(scenario)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["required_revenue_cagr_pct"], 0)
        self.assertAlmostEqual(rows[1]["required_revenue_cagr_pct"], 12)
        self.assertEqual(reverse_expectations({**scenario, "debt": None}), [])
        self.assertEqual(reverse_expectations({**scenario, "status": "incomplete"}), [])

    def test_whole_share_scenarios_do_not_change_account(self):
        summary = {"account_total_value": 2429.84, "deployable_cash": 909.53}
        account = {"single_stock_default_cap_pct": 6, "single_stock_hard_cap_pct": 8}
        weights = [{"ticker": "IOT", "asset_role": "active_stock", "current_shares": 4, "latest_price": 38.75}]
        before = json.dumps([summary, weights, account], sort_keys=True)
        row = whole_share_diagnostics(summary, weights, account)[0]
        self.assertEqual(row["above_target_dollars"], 9.21)
        self.assertEqual(row["one_share_reduction_fraction_pct"], 25)
        self.assertTrue(row["not_a_trade_plan"])
        self.assertEqual(json.dumps([summary, weights, account], sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
