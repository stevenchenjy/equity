from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR, PROJECT_ROOT  # noqa: F401
import build_phase5r_current_research_baseline as baseline
from phase5r_long_horizon_research import (
    build_long_horizon_report, fundamentals_candidate_queue, review_signals,
    scenario_math, source_facts,
)

POLICY = json.loads((PROJECT_ROOT / "01_policies/phase5r_long_horizon_research_policy.json").read_text())
AS_OF = "2026-09-20T20:00:00+00:00"


def fundamental(ticker="ABC"):
    values = {"revenue_latest": 300, "revenue_yoy_pct": 20, "ttm_revenue": 1000,
        "ttm_revenue_yoy_pct": 25, "net_margin_pct": 10, "ttm_free_cash_flow": 100,
        "ttm_free_cash_flow_margin_pct": 10, "cash_latest": 100, "debt_latest": 50,
        "diluted_shares_latest": 100, "share_dilution_pct": 2}
    receipts = {key: {"status": "available", "val": value, "end": "2026-06-30",
        "available_at_utc": "2026-08-01T20:00:00+00:00", "accn": "test"} for key, value in values.items()}
    return {"ticker": ticker, "source_url": "https://data.sec.gov/test", "data_quality": "ok",
        "latest_period_end": "2026-06-30", "financial_period_type": "quarter",
        "field_provenance_json": json.dumps(receipts), **values}


class LongHorizonResearchTests(unittest.TestCase):
    def test_forward_reverse_reconcile_with_dilution_and_margin(self):
        policy = deepcopy(POLICY)
        policy["sensitivities"] = [{"name": "test", "revenue_cagr_pct": 20,
            "terminal_fcf_margin_pct": 20, "annual_dilution_pct": 3,
            "terminal_price_to_fcf_multiple": 20}]
        policy["horizons_years"] = [5]
        facts = source_facts(fundamental(), AS_OF)
        result = scenario_math(facts, 10, policy)
        row = result["forward"][0]
        expected_revenue = 1000*1.2**5
        expected_shares = 100*1.03**5
        self.assertAlmostEqual(row["terminal_price"], (expected_revenue*.2*20)/expected_shares, places=4)
        self.assertAlmostEqual(row["terminal_cash_flow_per_share"], expected_revenue*.2/expected_shares, places=4)
        reverse = result["reverse_hurdles"][0]
        required_revenue = (10*2*expected_shares)/(.2*20)
        self.assertAlmostEqual(reverse["required_revenue"], required_revenue, places=2)
        policy["sensitivities"][0]["revenue_cagr_pct"] = ((required_revenue/1000)**.2-1)*100
        reconstructed = scenario_math(facts, 10, policy)["forward"][0]
        self.assertEqual(reconstructed["price_multiple"], 2.0)
        self.assertFalse(result["is_forecast"])
        self.assertIsNone(result["scenario_probabilities"])

    def test_missing_revenue_and_missing_assumptions_do_not_fill_zero(self):
        row = fundamental()
        row["ttm_revenue"] = ""
        result = scenario_math(source_facts(row, AS_OF), 10, POLICY)
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("ttm_revenue", result["missing_inputs"])
        self.assertFalse(result["forward"])
        policy = deepcopy(POLICY)
        policy["sensitivities"] = []
        result = scenario_math(source_facts(fundamental(), AS_OF), 10, policy)
        self.assertEqual(result["status"], "insufficient_assumptions")

    def test_equity_cash_flow_multiple_never_adds_cash_or_subtracts_debt(self):
        first = fundamental()
        second = fundamental()
        second["cash_latest"] = 100000
        second["debt_latest"] = ""
        original = scenario_math(source_facts(first, AS_OF), 10, POLICY)
        changed = scenario_math(source_facts(second, AS_OF), 10, POLICY)
        self.assertEqual(original["forward"], changed["forward"])
        self.assertEqual(original["reverse_hurdles"], changed["reverse_hurdles"])
        market = [{"ticker": "ABC", "last_price": "10", "market_session_date": "2026-09-18", "data_quality_label": "ok"}]
        report = build_long_horizon_report([second], [{"ticker": "ABC"}], market, POLICY, AS_OF)
        self.assertIn("unresolved_financial_evidence:debt_latest", report["companies"]["ABC"]["missing_evidence"])
        self.assertEqual(report["companies"]["ABC"]["readiness"], "pending_research")

    def test_verified_zero_debt_is_valid_but_future_or_unbound_is_not(self):
        row = fundamental()
        row["debt_latest"] = 0
        zero_receipts = json.loads(row["field_provenance_json"])
        zero_receipts["debt_latest"]["val"] = 0
        row["field_provenance_json"] = json.dumps(zero_receipts)
        self.assertEqual(source_facts(row, AS_OF)["debt_latest"]["value"], 0)
        receipts = json.loads(row["field_provenance_json"])
        receipts["ttm_revenue"]["available_at_utc"] = "2027-01-01T00:00:00+00:00"
        del receipts["debt_latest"]
        row["field_provenance_json"] = json.dumps(receipts)
        facts = source_facts(row, AS_OF)
        self.assertIsNone(facts["ttm_revenue"]["value"])
        self.assertIsNone(facts["debt_latest"]["value"])
        self.assertFalse(scenario_math(facts, 10, POLICY)["forward"])

    def test_slowdown_margin_and_dilution_flag_while_revenue_still_grows(self):
        current = {"latest_period_end": "2026-06-30", "financial_period_type": "quarterly",
            "revenue_yoy_pct": 16, "ttm_revenue_yoy_pct": 25, "net_margin_pct": 5,
            "share_dilution_pct": 6, "ttm_free_cash_flow_margin_pct": 3}
        previous = {"latest_period_end": "2026-03-31", "financial_period_type": "quarterly", "revenue_yoy_pct": 40,
            "net_margin_pct": 15, "ttm_free_cash_flow_margin_pct": 10}
        signals, missing = review_signals(current, previous, POLICY)
        self.assertEqual({r["code"] for r in signals}, {"latest_growth_below_ttm", "elevated_share_dilution",
            "revenue_growth_slowdown", "net_margin_deterioration", "fcf_margin_deterioration"})
        self.assertFalse(missing)
        self.assertTrue(all(r["confirmed_thesis_break"] is False for r in signals))

    def test_source_prior_quarter_works_on_first_run_and_annual_not_compared(self):
        current = {"latest_period_end": "2026-06-30", "financial_period_type": "quarterly",
            "revenue_yoy_pct": 16, "net_margin_pct": 5, "prior_quarter_period_end": "2026-03-31",
            "revenue_yoy_prior_quarter_pct": 40, "net_margin_prior_quarter_pct": 15}
        signals, _ = review_signals(current, None, POLICY)
        self.assertIn("revenue_growth_slowdown", {r["code"] for r in signals})
        current["financial_period_type"] = "annual"
        signals, missing = review_signals(current, None, POLICY)
        self.assertNotIn("revenue_growth_slowdown", {r["code"] for r in signals})
        self.assertIn("quarterly_financial_period_for_sequential_comparison", missing)

    def test_nonadjacent_periods_and_mismatched_receipts_are_not_evidence(self):
        current = {"latest_period_end": "2026-06-30", "financial_period_type": "quarterly", "revenue_yoy_pct": 5}
        old = {"latest_period_end": "2025-06-30", "financial_period_type": "quarterly", "revenue_yoy_pct": 40}
        signals, missing = review_signals(current, old, POLICY)
        self.assertNotIn("revenue_growth_slowdown", {r["code"] for r in signals})
        self.assertIn("adjacent_comparable_quarter_for_sequential_comparison", missing)
        row = fundamental()
        row["cash_latest"] = 1000
        facts = source_facts(row, AS_OF)
        self.assertIn("observation_provenance_value_mismatch", facts["cash_latest"]["issues"])
        self.assertIsNone(facts["cash_latest"]["value"])

    def test_fundamental_queue_ignores_daily_momentum_and_keeps_held_core(self):
        quiet = fundamental("QUIET")
        quiet.update({"ttm_revenue_yoy_pct": 50, "intraday_change_pct": -5, "total_score": 0})
        loud = fundamental("LOUD")
        loud.update({"ttm_revenue_yoy_pct": 5, "intraday_change_pct": 10, "total_score": 9})
        queue = fundamentals_candidate_queue([loud, quiet], set(), POLICY)
        self.assertEqual(queue[0]["ticker"], "QUIET")
        def inputs(path):
            if path == baseline.POSITIONS_PATH:
                return [{"ticker": "HELD"}]
            if path == baseline.FUNDAMENTALS_PATH:
                return [quiet, loud]
            if path == baseline.SIGNAL_SCORES_PATH:
                return [{"ticker": "LOUD", "total_score": "9", "data_quality_label": "ok"}]
            raise AssertionError(path)
        with patch.object(baseline, "read_csv", side_effect=inputs), patch.object(baseline, "read_json", return_value=POLICY):
            selected, held = baseline.selected_tickers()
        self.assertEqual(set(selected), {"QUIET", "LOUD", "HELD", "SPY"})
        self.assertEqual(held, {"HELD"})

    def test_new_adverse_material_filing_does_not_raise_score(self):
        quote = {"ticker": "ABC", "market_session_date": "2026-09-18", "data_quality_label": "ok", "last_price": "10", "data_source": "test"}
        def inputs(path):
            if path == baseline.MARKET_SNAPSHOT_PATH:
                return [quote]
            if path == baseline.FUNDAMENTALS_PATH:
                return [fundamental()]
            if path == baseline.EVIDENCE_LEDGER_PATH:
                return [{"ticker": "ABC", "cycle_date": "2026-09-20", "material_event": "yes", "is_new": "yes", "items": "4.02"}]
            return []
        with patch.object(baseline, "selected_tickers", return_value=(["ABC"], set())), \
             patch.object(baseline, "read_csv", side_effect=inputs), \
             patch.object(baseline, "cycle_date", return_value="2026-09-20"), \
             patch.object(baseline, "latest_published_market_session", return_value=date(2026, 9, 18)), \
             patch.object(baseline, "atomic_write_csv") as output:
            baseline.main()
        row = output.call_args.args[2][0]
        self.assertEqual(row["catalyst_news_quality_score"], "5.0")
        self.assertEqual(row["news_check"], "new_material_official_filing")
        self.assertNotEqual(row["recommendation_confidence"], "high")

    def test_report_remains_noncanonical_and_history_does_not_duplicate_daily(self):
        row = fundamental()
        market = [{"ticker": "ABC", "market_session_date": "2026-09-18", "last_price": "10", "data_quality_label": "ok"}]
        result = build_long_horizon_report([row], [{"ticker": "ABC"}], market, POLICY, AS_OF)
        repeated = build_long_horizon_report([row], [{"ticker": "ABC"}], market, POLICY, AS_OF, result)
        self.assertEqual(len(repeated["companies"]["ABC"]["quarterly_history"]), 1)
        self.assertEqual(repeated["market_session_date"], "2026-09-18")
        self.assertEqual(repeated["companies"]["ABC"]["readiness"], "pending_research")
        self.assertFalse(repeated["canonical_influence_allowed"])
        self.assertFalse(repeated["recommendation_authority"])
        self.assertFalse(repeated["automatic_action_allowed"])
        self.assertEqual(repeated["confidence_policy"]["high_conviction_tier_status"], "reserved_not_emitted_by_current_deterministic_generator")


if __name__ == "__main__":
    unittest.main()
