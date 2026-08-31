from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

import run_phase5r_model_pilot as v1
from phase5r_model_pilot_v3_prompt import assessment_instructions
from run_phase5r_model_pilot_v3 import (
    V3_PLAN_PATH,
    _calls,
    _instructions,
    _redacted_provider_metadata,
    _selected_contexts,
    _validate_v2_state,
    check_v3_readiness,
    execute_model_pilot_v3,
)


class ReplacementPilotV3Tests(unittest.TestCase):
    def test_calls_preserve_the_v3_cap_and_reservation(self) -> None:
        plan = json.loads(V3_PLAN_PATH.read_text(encoding="utf-8"))
        policy, contexts, _unused, _audit, _sentinels = v1._readiness_components()
        analysts, committees = _selected_contexts(plan, contexts)
        calls = _calls(analysts, committees, policy["prices"])
        self.assertEqual(len(calls), 24)
        self.assertEqual(len({call["call_id"] for call in calls}), 24)
        self.assertEqual(
            sum(
                (Decimal(call["reservation_usd"]) for call in calls),
                Decimal(0),
            ),
            Decimal("3.9494400"),
        )
        self.assertEqual(
            sum(call["stage"].endswith("assessment") for call in calls),
            16,
        )
        self.assertEqual(
            sum(call["stage"] == "sol_committee" for call in calls),
            4,
        )
        self.assertEqual(
            sum(call["stage"] == "sol_critic" for call in calls),
            4,
        )

    def test_only_assessments_get_the_v3_citation_binding_prompt(self) -> None:
        self.assertEqual(_instructions("luna_assessment"), assessment_instructions())
        self.assertEqual(_instructions("terra_assessment"), assessment_instructions())
        self.assertEqual(_instructions("sol_committee"), v1.COMMITTEE_INSTRUCTIONS)
        self.assertIn("cited_excerpt_sha256", _instructions("luna_assessment"))

    def test_readiness_exposes_the_sealed_hashes_required_at_execution(self) -> None:
        report = check_v3_readiness()
        self.assertTrue(report["passed"])
        self.assertRegex(report["strict_audit_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(report["policy_file_sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(report["provider_constructed"])
        self.assertFalse(report["network_used"])
        self.assertFalse(report["files_written"])

    def test_v2_terminal_state_remains_a_required_precondition(self) -> None:
        plan = json.loads(V3_PLAN_PATH.read_text(encoding="utf-8"))
        state = _validate_v2_state(plan["source_v2"])
        self.assertRegex(state["execution_plan_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(state["journal_file_sha256"], r"^[0-9a-f]{64}$")

    def test_executor_refuses_before_constructing_a_provider(self) -> None:
        constructed = False

        def factory() -> object:
            nonlocal constructed
            constructed = True
            raise AssertionError("factory must not be called")

        with self.assertRaisesRegex(v1.PilotStop, "explicit interactive"):
            execute_model_pilot_v3(
                provider_factory=factory,  # type: ignore[arg-type]
                explicit_user_authorization=False,
            )
        self.assertFalse(constructed)

    def test_provider_identifier_is_hashed_before_any_persistence(self) -> None:
        metadata = _redacted_provider_metadata(
            {"provider_response_id": "resp_sensitive_identifier", "usage": {}}
        )
        self.assertNotIn("provider_response_id", metadata)
        self.assertRegex(metadata["provider_response_id_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
