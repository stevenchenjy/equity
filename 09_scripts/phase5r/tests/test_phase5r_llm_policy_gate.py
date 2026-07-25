from __future__ import annotations

import copy
import unittest

from _support import evaluated, materialized
from phase5r_llm_contract import (
    ContractError,
    adjudicate,
    validate_critic,
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

    def test_second_close_transition_requires_human_review(self) -> None:
        result = evaluated("g08_add_second_close")
        self.assertEqual(
            result["actual"]["raw_classification"], "paper_trade_candidate"
        )
        self.assertTrue(result["actual"]["human_review_required"])

    def test_critic_can_downgrade_transition(self) -> None:
        result = evaluated("g09_critic_disagreement")
        self.assertEqual(result["actual"]["raw_classification"], "hold_existing")
        self.assertTrue(result["actual"]["human_review_required"])

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


if __name__ == "__main__":
    unittest.main()
