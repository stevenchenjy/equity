from __future__ import annotations

import copy
import unittest

from _support import evaluated, materialized, rehash
from phase5r_llm_contract import (
    ContractError,
    adjudicate,
    validate_critic,
)
from phase5r_llm_provider import FixtureProvider
from run_phase5r_llm_shadow import (
    apply_verified_close_stability,
    execute_shadow,
    load_registry,
)


class PolicyGateTests(unittest.TestCase):
    def test_golden_policy_matrix(self) -> None:
        expected = {
            "g01_stable_hold": "hold_existing",
            "g07_add_first_close": "watchlist",
            "g08_add_second_close": "paper_trade_candidate",
            "g09_critic_disagreement": "hold_existing",
            "g10_material_thesis_break": "exit_review",
            "g11_stale_market_data": "abstain",
            "g12_prompt_injection": "abstain",
        }
        for case_id, classification in expected.items():
            with self.subTest(case_id=case_id):
                result = evaluated(case_id)
                self.assertTrue(result["passed"])
                self.assertEqual(
                    result["actual"]["safe_classification"], classification
                )

    def test_first_close_cannot_promote_candidate(self) -> None:
        result = evaluated("g07_add_first_close")
        self.assertEqual(result["actual"]["raw_classification"], "watchlist")
        self.assertFalse(result["actual"]["human_review_required"])
        packet, responses, closes = materialized("g07_add_first_close")
        adjudication = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(
            adjudication["ticker_decisions"][0]["classification"],
            "watchlist",
        )

    def test_second_close_transition_requires_human_review(self) -> None:
        result = evaluated("g08_add_second_close")
        self.assertEqual(
            result["actual"]["raw_classification"], "paper_trade_candidate"
        )
        self.assertTrue(result["actual"]["human_review_required"])

    def test_secondary_market_data_cannot_unlock_buy_transition(self) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        packet["gates"]["market_data_action_grade"] = False
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertIn(
            "transition_gate_failed:market_data_action_grade",
            result["reasons"],
        )

    def test_primary_source_thesis_break_can_reach_exit_review(self) -> None:
        packet, responses, closes = materialized("g10_material_thesis_break")
        packet["gates"]["market_data_action_grade"] = False
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "exit_review")
        self.assertNotIn(
            "transition_gate_failed:market_data_action_grade",
            result["reasons"],
        )

    def test_self_declared_thesis_break_without_high_primary_claim_abstains(
        self,
    ) -> None:
        packet, responses, closes = materialized("g10_material_thesis_break")
        responses["analyst"]["claims"][0]["stance"] = "supports"
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertIn(
            "material_thesis_break_lacks_high_primary_support",
            result["reasons"],
        )

    def test_transition_requires_resolved_official_analyst_coverage(self) -> None:
        for mutation, expected_reason in (
            (
                {"official_evidence_sufficient": False},
                "transition_official_evidence_insufficient:TST",
            ),
            (
                {"contradictory_evidence": True},
                "transition_contradictory_evidence_unresolved:TST",
            ),
        ):
            with self.subTest(mutation=mutation):
                packet, responses, closes = materialized(
                    "g08_add_second_close"
                )
                responses["analyst"]["ticker_coverage"][0].update(mutation)
                result = adjudicate(
                    packet,
                    responses["analyst"],
                    responses["committee"],
                    responses["critic"],
                    distinct_valid_closes=closes,
                )
                self.assertEqual(
                    result["effective_classification"],
                    "abstain",
                )
                self.assertIn(expected_reason, result["reasons"])

    def test_transition_with_unresolved_question_abstains(self) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        responses["analyst"]["unresolved_questions"] = [
            "A material long-term uncertainty is unresolved."
        ]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertIn(
            "transition_has_unresolved_analyst_questions",
            result["reasons"],
        )

    def test_critic_can_downgrade_transition(self) -> None:
        result = evaluated("g09_critic_disagreement")
        self.assertEqual(result["actual"]["raw_classification"], "hold_existing")
        self.assertTrue(result["actual"]["human_review_required"])
        packet, responses, closes = materialized("g09_critic_disagreement")
        adjudication = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(
            adjudication["ticker_decisions"][0]["classification"],
            "hold_existing",
        )
        self.assertEqual(
            adjudication["headline"],
            "明确研究结论：继续持有研究状态",
        )
        self.assertLessEqual(adjudication["confidence_pct"], 50)

    def test_critic_cannot_upgrade(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        critic = copy.deepcopy(responses["critic"])
        critic["downgrade_to"] = "exit_review"
        with self.assertRaisesRegex(ContractError, "cannot upgrade"):
            validate_critic(packet, responses["committee"], critic)

    def test_missing_required_critic_returns_safe_abstain(self) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            None,
            distinct_valid_closes=closes,
        )
        self.assertTrue(result["critic_required"])
        self.assertEqual(result["effective_classification"], "abstain")

    def test_core_prompt_injection_always_sets_effective_abstain(self) -> None:
        packet, responses, closes = materialized("g01_stable_hold")
        responses["analyst"]["prompt_injection_detected"] = True
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertTrue(
            all(
                row["classification"] == "abstain"
                for row in result["ticker_decisions"]
            )
        )

    def test_core_numeric_failure_always_sets_effective_abstain(self) -> None:
        packet, responses, closes = materialized("g05_numeric_mismatch")
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")

    def test_live_stability_comes_from_hashed_canonical_packet_only(self) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        packet["gates"].update(
            {
                "deterministic_action_stability_distinct_closes": 2,
                "deterministic_transition_pending_tickers": [],
                "deterministic_transition_eligible_tickers": ["TST"],
                "verified_close_session": packet["cycle_date"],
            }
        )
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=0,
        )
        result = apply_verified_close_stability(packet, bundle)
        self.assertEqual(
            result["adjudication"]["effective_classification"],
            "paper_trade_candidate",
        )
        self.assertEqual(
            result["stability"]["source"],
            "hashed_canonical_daily_decision_packet",
        )
        packet["gates"]["deterministic_transition_eligible_tickers"] = []
        packet["gates"]["deterministic_transition_pending_tickers"] = ["TST"]
        packet["gates"]["deterministic_action_stability_distinct_closes"] = 1
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=0,
        )
        result = apply_verified_close_stability(packet, bundle)
        self.assertEqual(
            result["adjudication"]["effective_classification"],
            "watchlist",
        )


if __name__ == "__main__":
    unittest.main()
