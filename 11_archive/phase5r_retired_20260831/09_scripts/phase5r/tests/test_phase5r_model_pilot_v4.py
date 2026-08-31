from __future__ import annotations

import json
import unittest
from decimal import Decimal

import run_phase5r_model_pilot as v1
from phase5r_llm_contract import ContractError
from run_phase5r_model_pilot_v4 import (
    V4_PLAN_PATH,
    _calls,
    _instructions,
    _redacted_provider_metadata,
    _schema,
    _selected_contexts,
    _validate_v3_state,
    execute_model_pilot_v4,
)


class ReplacementPilotV4Tests(unittest.TestCase):
    def test_calls_preserve_the_v4_cap_and_reservation(self) -> None:
        plan = json.loads(V4_PLAN_PATH.read_text(encoding="utf-8"))
        policy, contexts, _unused, _audit, _sentinels = v1._readiness_components()
        analysts, committees = _selected_contexts(plan, contexts)
        calls = _calls(analysts, committees, policy["prices"])
        self.assertEqual(len(calls), 8)
        self.assertEqual(len({call["call_id"] for call in calls}), 8)
        self.assertEqual(
            sum(
                (Decimal(call["reservation_usd"]) for call in calls),
                Decimal(0),
            ),
            Decimal("1.5681600"),
        )

    def test_analyst_request_uses_source_id_only_schema_and_prompt(self) -> None:
        schema = _schema("luna_assessment")
        claim = schema["properties"]["claims"]["items"]
        self.assertNotIn("cited_excerpt_sha256", claim["properties"])
        self.assertIn("Do not output cited_excerpt_sha256", _instructions("luna_assessment"))
        self.assertEqual(_schema("sol_committee"), v1.PILOT_COMMITTEE_SCHEMA)

    def test_v3_terminal_state_remains_a_required_precondition(self) -> None:
        plan = json.loads(V4_PLAN_PATH.read_text(encoding="utf-8"))
        state = _validate_v3_state(plan["source_v3"])
        self.assertRegex(state["execution_plan_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(state["journal_file_sha256"], r"^[0-9a-f]{64}$")

    def test_executor_refuses_before_constructing_a_provider(self) -> None:
        constructed = False

        def factory() -> object:
            nonlocal constructed
            constructed = True
            raise AssertionError("factory must not be called")

        with self.assertRaisesRegex(v1.PilotStop, "explicit interactive"):
            execute_model_pilot_v4(
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

    def test_analyst_claim_diagnostic_is_specific_and_content_free(self) -> None:
        call = {"stage": "luna_assessment"}
        cases = (
            (
                "analyst.claims[0]: unknown source ids source-private-123",
                "analyst_claim_unknown_source",
            ),
            (
                "analyst.claims[1]: numeric text requires a reconciled calculation",
                "analyst_claim_numeric_without_calculation",
            ),
            (
                "analyst.claims[2]: calculated evidence requires a reconciled calculation",
                "analyst_claim_calculated_without_calculation",
            ),
            (
                "analyst.claims[3]: rationale must be non-empty",
                "analyst_claim_rationale_empty",
            ),
        )
        for message, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                diagnostic = v1._redacted_contract_diagnostic(
                    call, ContractError(message)
                )
                self.assertEqual(diagnostic["code"], expected_code)
                self.assertNotIn("source-private-123", json.dumps(diagnostic))


if __name__ == "__main__":
    unittest.main()
