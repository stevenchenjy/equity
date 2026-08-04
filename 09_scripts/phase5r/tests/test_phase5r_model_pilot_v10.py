from __future__ import annotations

import unittest

import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v6 as v6
import run_phase5r_model_pilot_v10 as v10


class V10ReadinessTests(unittest.TestCase):
    def test_v10_raises_only_the_critic_output_cap(self) -> None:
        readiness = v10.check_v10_readiness()

        self.assertTrue(readiness["passed"])
        self.assertEqual(readiness["planned_model_calls"], 30)
        self.assertEqual(readiness["new_collection_usd_cap"], "5.1348")
        self.assertEqual(readiness["critic_maximum_output_tokens"], 5_000)
        self.assertEqual(
            readiness["all_other_stage_maximum_output_tokens"], 3_800
        )
        self.assertFalse(readiness["v9_receipts_used_as_research"])
        self.assertFalse(readiness["provider_constructed"])
        self.assertFalse(readiness["network_used"])

    def test_v10_execution_plan_reserves_the_extra_tokens_only_for_critics(self) -> None:
        replacement = v10._load_v10_plan()
        policy, _contexts, base_plan, _audit, _sentinels = (
            v1._readiness_components()
        )
        predecessors = v6._validate_terminal_predecessors(replacement)
        execution = v10._build_execution_plan_v10(
            replacement,
            base_plan=base_plan,
            predecessor_journals=predecessors,
        )

        critic_calls = [
            call for call in execution["calls"] if call["stage"] == "sol_critic"
        ]
        non_critic_calls = [
            call for call in execution["calls"] if call["stage"] != "sol_critic"
        ]
        self.assertEqual(len(critic_calls), 5)
        self.assertTrue(
            all(call["maximum_output_tokens"] == 5_000 for call in critic_calls)
        )
        self.assertTrue(
            all(call["reservation_usd"] == "0.33" for call in critic_calls)
        )
        self.assertTrue(
            all(
                call["maximum_output_tokens"] == 3_800
                for call in non_critic_calls
            )
        )
        self.assertEqual(execution["budget"]["maximum_usd"], "5.1348")
        self.assertEqual(
            execution["budget"]["worst_case_reserved_usd"], "5.1348"
        )


if __name__ == "__main__":
    unittest.main()
