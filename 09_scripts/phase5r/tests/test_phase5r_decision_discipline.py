from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import calculate_phase5r_c9_dynamic_weights as weights
import create_phase5r_c9_exact_action_plan as action_plan
import create_phase5r_daily_decision_and_brief as decision
from phase5r_c9_common import score_from_packet
import phase5r_daily_common as common


class LongHorizonDecisionDisciplineTests(unittest.TestCase):
    def assessment(self) -> dict[str, object]:
        return {
            "ticker": "RBRK", "status": "confirmed_thesis_break",
            "source_type": "sec_filing",
            "source_url": "https://www.sec.gov/Archives/edgar/data/1/filing.htm",
            "evidence_date": "2026-09-18", "reviewed_at": "2026-09-20T10:00:00-04:00",
            "reviewer": "research_analyst", "reason": "Filing confirms the documented revenue thesis is invalidated.",
            "invalidation_rule": "Reassess if durable revenue growth thesis is invalidated.",
        }

    def test_rbrk_daily_technical_decline_cannot_create_full_exit(self) -> None:
        packet = {
            "business_quality_score": "6.5", "earnings_revenue_trend_score": "7.5",
            "valuation_reasonableness_score": "4", "catalyst_news_quality_score": "5",
            "technical_entry_discipline_score": "5",
        }
        before = score_from_packet(packet, 8.0)
        packet["technical_entry_discipline_score"] = "0"  # held-stock proxy after a 10% down day
        after = score_from_packet(packet, 8.0)
        self.assertGreaterEqual(before, 5.5)
        self.assertLess(after, 5.5)
        label = weights.held_recommendation_label(
            is_core=False, current_weight=7.2, hard_cap=15, score=after,
            thesis_break_confirmed=False,
        )
        self.assertEqual(label, "hold_pending_research")
        result = self.exact_action(label, score=after)
        self.assertEqual(result["recommended_action"], "hold_pending_research")
        self.assertEqual(result["whole_shares_to_change"], "0")
        self.assertEqual(result["target_shares"], "2.0000")
        self.assertEqual(result["human_confirmation_required"], "no")

    def exact_action(self, label: str, *, score: float = 5.2, weight: float = 7.2,
                     assessment: dict[str, object] | None = None) -> dict[str, str]:
        position = {"ticker": "RBRK", "horizon_class": "long_term_research",
                    "invalidation_rule": self.assessment()["invalidation_rule"]}
        rows = [{"ticker": "RBRK", "asset_role": "active_stock", "current_shares": "2",
                 "latest_price": "72", "current_value": "144", "current_weight_pct": str(weight),
                 "current_recommendation_label": label, "current_research_score": str(score),
                 "concentration_status": "above_hard_cap" if weight > 15 else "within_default_cap"}]
        written: dict[Path, list[dict[str, str]]] = {}
        with tempfile.TemporaryDirectory() as directory:
            valuation = Path(directory) / "valuation.json"
            valuation.write_text(json.dumps({"records": []}))
            policy = Path(directory) / "policy.json"
            policy.write_text(json.dumps({"held_position_review": {}}))
            with (
                patch.object(action_plan, "VALUATION_SCENARIO_PATH", valuation),
                patch.object(action_plan, "VALUATION_POLICY_PATH", policy),
                patch.object(action_plan, "load_active_inhibit", return_value={"active": False}),
                patch.object(action_plan, "load_research_account_state", return_value={
                    "single_stock_default_cap_pct": 15, "single_stock_hard_cap_pct": 15}),
                patch.object(action_plan, "load_positions", return_value=[position]),
                patch.object(action_plan, "load_packets", return_value={"RBRK": {"recommendation_confidence": "medium_high"}}),
                patch.object(action_plan, "load_thesis_reviews", return_value={"RBRK": assessment} if assessment else {}),
                patch.object(weights, "date") as clock,
                patch.object(action_plan, "read_csv", return_value=rows),
                patch.object(action_plan, "load_portfolio_summary", return_value={"account_total_value": str(144 / weight * 100)}),
                patch.object(action_plan, "append_run_log"),
                patch.object(action_plan, "write_csv", side_effect=lambda path, value, _f: written.__setitem__(path, value)),
            ):
                clock.today.return_value = date(2026, 9, 20)
                clock.fromisoformat.side_effect = date.fromisoformat
                action_plan.main()
        return written[action_plan.EXACT_ACTION_PLAN][0]

    def test_reviewed_primary_thesis_break_preserves_exit_review(self) -> None:
        result = self.exact_action("exit_review", score=7.5, assessment=self.assessment())
        self.assertEqual(result["recommended_action"], "exit_review")
        self.assertEqual(result["whole_shares_to_change"], "2")
        self.assertEqual(result["human_confirmation_required"], "yes")
        self.assertIn("sec.gov", result["reason"])

    def test_unverified_old_exit_label_cannot_bypass_thesis_contract(self) -> None:
        for change in ({"source_url": ""}, {"status": "unconfirmed"},
                       {"invalidation_rule": "unrelated condition"}, {"reviewed_at": "2026-07-01T10:00:00-04:00"},
                       {"evidence_date": "2026-09-21"}, {"reviewer": ""},
                       {"source_url": "https://random.example/filing"},
                       {"source_url": "https://www.sec.gov.attacker.example/Archives/edgar/data/1/filing"},
                       {"source_url": "https://user:password@www.sec.gov/Archives/edgar/data/1/filing"},
                       {"source_url": "https://www.sec.gov/Archives/edgar/data/1/filing", "ticker": "OTHER"}):
            with self.subTest(change=change):
                assessment = self.assessment() | change
                result = self.exact_action("exit_review", assessment=assessment)
                self.assertEqual(result["recommended_action"], "hold_pending_research")
                self.assertEqual(result["whole_shares_to_change"], "0")

    def test_hard_concentration_cap_is_still_enforced(self) -> None:
        self.assertEqual(weights.held_recommendation_label(
            is_core=False, current_weight=18, hard_cap=15, score=4,
            thesis_break_confirmed=False,
        ), "trim_review")
        result = self.exact_action("hold_pending_research", weight=18)
        self.assertEqual(result["recommended_action"], "trim_specific_shares_review")
        self.assertEqual(result["whole_shares_to_change"], "1")

    def test_pending_long_horizon_research_never_replaces_a_confirmed_exit(self) -> None:
        held = [
            {"ticker": "RBRK", "asset_role": "active_stock", "action": "exit_review"},
            {"ticker": "IOT", "asset_role": "active_stock", "action": "hold"},
            {"ticker": "SPY", "asset_role": "core_allocation", "action": "hold"},
        ]
        context = decision.held_research_context({"market_session_date": "2026-09-18", "companies": {
            ticker: {"readiness": "pending_research", "missing_evidence": ["growth_case"], "review_signals": []}
            for ticker in ("RBRK", "IOT")
        }}, held, "2026-09-18")
        self.assertEqual(held[0]["action"], "exit_review")
        self.assertEqual(held[1]["action"], "hold_pending_research")
        self.assertEqual(held[1]["human_confirmation_required"], "no")
        self.assertEqual(held[2]["action"], "hold")
        self.assertFalse(context["action_authority"])

    def test_stale_research_report_does_not_clear_pending_thesis(self) -> None:
        held = [{"ticker": "RBRK", "asset_role": "active_stock", "action": "hold"}]
        context = decision.held_research_context({"market_session_date": "2026-09-17", "companies": {
            "RBRK": {"readiness": "source_complete_sensitivity_only"},
        }}, held, "2026-09-18")
        self.assertEqual(context["status"], "unavailable_or_stale")
        self.assertEqual(held[0]["action"], "hold_pending_research")

    def test_report_exposes_dilution_value_period_source_and_research_boundary(self) -> None:
        text = decision.research_warning_lines({"warnings": [{"ticker": "RBRK", "review_signals": [{
            "code": "elevated_share_dilution", "observations": {"share_dilution_pct": 5.75},
            "evidence_date": "2026-07-31", "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001943896.json",
        }]}]})
        for expected in ("RBRK", "5.75%", "2026-07-31", "https://data.sec.gov/", "尚未确认投资逻辑失效"):
            self.assertIn(expected, text)

    def test_configured_news_success_does_not_claim_unconfigured_holding_coverage(self) -> None:
        source_status = {"status": "ok", "required_coverage_complete": True,
                         "sources": [{"ticker": "IOT"}, {"ticker": "RBRK"}]}
        with patch.object(decision, "read_official_news_status", return_value=source_status):
            result = decision.official_news_context(datetime(2026, 9, 20, tzinfo=timezone.utc), ["IOT", "RBRK", "NEW"])
        self.assertEqual(result["unconfigured_held_tickers"], ["NEW"])
        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["required_coverage_complete"])


class CandidateStabilityTests(unittest.TestCase):
    def proposal(self, ticker: str = "SPY") -> dict[str, str]:
        return {
            "ticker": ticker, "recommended_action": "core_allocation_tranche_review",
            "eligibility_label": "eligible_core_starter_review", "suggested_whole_shares": "1",
            "maximum_review_price": "760.00", "current_price": "760.00",
            "valuation_applicability": "not_applicable_broad_market_etf",
        }

    def advance(self, prior: dict, rows: list[dict], session: str, *, valid: bool = True) -> dict:
        return decision.candidate_stability(
            {"new_candidate_stability": prior}, rows, session, valid_close=valid,
        )

    def test_drifting_spy_price_does_not_reset_two_close_confirmation(self) -> None:
        row = self.proposal()
        first = self.advance({}, [row], "2026-09-14")
        row.update(current_price="759.00", maximum_review_price="759.00")
        second = self.advance(first, [row], "2026-09-15")
        self.assertEqual(second["proposals"]["SPY"]["distinct_closes"], 2)
        self.assertEqual(row["maximum_review_price"], "759.00")

    def test_unrelated_candidate_and_order_changes_do_not_reset_spy(self) -> None:
        spy, other = self.proposal(), self.proposal("AMD")
        first = self.advance({}, [spy, other], "2026-09-14")
        other["suggested_whole_shares"] = "2"
        second = self.advance(first, [other, spy], "2026-09-15")
        self.assertEqual(second["proposals"]["SPY"]["distinct_closes"], 2)
        self.assertEqual(second["proposals"]["AMD"]["distinct_closes"], 1)

    def test_material_evidence_or_action_changes_reset_only_that_proposal(self) -> None:
        row = self.proposal("AMD")
        first = self.advance({}, [row], "2026-09-14")
        for change in ({"suggested_whole_shares": "2"}, {"valuation_base_price": "200"},
                       {"valuation_source": "https://www.sec.gov/new-filing"},
                       {"recommended_action": "eligible_buy_review"}, {"invalidation_condition": "new condition"}):
            with self.subTest(change=change):
                second = self.advance(first, [row | change], "2026-09-15")
                self.assertEqual(second["proposals"]["AMD"]["distinct_closes"], 1)

    def test_reruns_invalid_closes_and_legacy_state_cannot_accelerate_confirmation(self) -> None:
        row = self.proposal()
        first = self.advance({}, [row], "2026-09-14")
        repeat = self.advance(first, [row], "2026-09-14")
        self.assertEqual(repeat["proposals"]["SPY"]["distinct_closes"], 1)
        invalid = self.advance(first, [row], "2026-09-15", valid=False)
        self.assertEqual(invalid["proposals"]["SPY"]["distinct_closes"], 0)
        resumed = self.advance(invalid, [row], "2026-09-16")
        self.assertEqual(resumed["proposals"]["SPY"]["distinct_closes"], 1)
        old = decision.candidate_stability({"new_candidate_proposal_distinct_closes": 100}, [row], "2026-09-15", valid_close=True)
        self.assertEqual(old["proposals"]["SPY"]["distinct_closes"], 1)
        older = self.advance(first, [row], "2026-09-11")
        self.assertEqual(older["proposals"]["SPY"]["distinct_closes"], 0)

    def test_candidate_disappearance_resets_and_numeric_format_does_not(self) -> None:
        row = self.proposal()
        first = self.advance({}, [row], "2026-09-14")
        formatted = copy.deepcopy(row)
        formatted["suggested_whole_shares"] = "1.0000"
        second = self.advance(first, [formatted], "2026-09-15")
        self.assertEqual(second["proposals"]["SPY"]["distinct_closes"], 2)
        absent = self.advance(second, [], "2026-09-16")
        returned = self.advance(absent, [row], "2026-09-17")
        self.assertEqual(returned["proposals"]["SPY"]["distinct_closes"], 1)


class ResearchWarningNotificationTests(unittest.TestCase):
    def test_receipt_timestamp_is_quiet_but_new_financial_value_notifies(self) -> None:
        previous = {
            "decision_code": "hold_pending_research", "cycle_date": "2026-09-20",
            "held_positions": [{"ticker": "RBRK", "action": "hold_pending_research"}],
            "watch_candidates": [], "account": {},
            **{key: {"passed": True} for key in ("market_gate", "evidence_gate", "fundamental_gate")},
            "held_research_warnings": [{"ticker": "RBRK", "review_signals": [{
                "code": "elevated_share_dilution", "observations": {"dilution_pct": 5.75},
                "evidence_date": "2026-07-31", "available_at_utc": "2026-09-20T12:00:00+00:00",
            }]}],
        }
        refreshed = copy.deepcopy(previous)
        refreshed["generated_at"] = "2026-09-21T12:00:00+00:00"
        refreshed["held_research_warnings"][0]["review_signals"][0]["available_at_utc"] = "2026-09-21T12:00:00+00:00"
        self.assertFalse(common.notification_change_comparison(refreshed, {}, previous)["changed"])
        worsened = copy.deepcopy(refreshed)
        worsened["held_research_warnings"][0]["review_signals"][0]["observations"]["dilution_pct"] = 9.0
        comparison = common.notification_change_comparison(worsened, {}, previous)
        self.assertTrue(comparison["changed"])
        send, reason = common.notification_delivery_policy(
            is_weekend=False, weekly_summary_due=False, material_event=False,
            decision_changed=True, account_conflict=False, fundamental_weakening=False,
            first_material_baseline=False, regular_delivery_mode=common.WATCH_ACTION_NOTIFICATION_MODE,
            notification_changed=comparison["changed"],
        )
        self.assertTrue(send)
        self.assertEqual(reason, "watch_or_action_changed")


if __name__ == "__main__":
    unittest.main()
