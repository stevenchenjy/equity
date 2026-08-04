from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from phase5r_llm_contract import ContractError
from phase5r_llm_provider import ProviderResult
from phase5r_model_pilot_v6_contract import (
    hydrate_source_locked_assessment_v6,
    source_locked_assessment_schema_v6,
    source_locked_input_view_v6,
    strict_schema_for_stage_v6,
)
import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v6 as v6


class _V6FixtureProvider:
    offline_test_provider = True
    max_output_tokens = v1.MAXIMUM_OUTPUT_TOKENS

    def count_input_tokens(self, **kwargs: object) -> int:
        schema = kwargs["schema"]
        self._assert_min_length(schema)
        return 37

    def generate(self, **kwargs: object) -> ProviderResult:
        schema = kwargs["schema"]
        self._assert_min_length(schema)
        role = str(kwargs["role"])
        model = str(kwargs["model"])
        input_payload = kwargs["input_payload"]
        payload = self._payload(role, input_payload)
        return ProviderResult(
            payload=payload,
            metadata={
                "transport": "test_fixture",
                "model": model,
                "resolved_model": model,
                "requested_service_tier": "default",
                "resolved_service_tier": "default",
                "request_timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS,
                "billing_scope_attestation": "global_standard_no_regional_processing",
                "client_library_name": "fixture",
                "client_library_version": "fixture",
                "python_runtime_version": "fixture",
                "credential_read": False,
                "tools_enabled": False,
                "store": False,
                "provider_response_id": "fixture-response-id",
                "usage": {
                    "input_tokens": 37,
                    "output_tokens": 19,
                    "cached_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )

    @classmethod
    def _assert_min_length(cls, schema: object) -> None:
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "string":
            assert schema.get("minLength") == 1
        for child in schema.get("properties", {}).values():
            cls._assert_min_length(child)
        cls._assert_min_length(schema.get("items"))

    @staticmethod
    def _classification(input_payload: dict[str, object]) -> str:
        if "source_locked_evidence_view" in input_payload:
            entity = input_payload["source_locked_evidence_view"]["entity"]
        else:
            entity = input_payload["packet_evidence"]["entities"][0]
        return "hold_existing" if entity["role"] == "held" else "watchlist"

    def _payload(self, role: str, input_payload: dict[str, object]) -> dict[str, object]:
        classification = self._classification(input_payload)
        if role == "analyst":
            return {
                "claims": [
                    {
                        "claim": "Primary evidence supports a cautious long horizon view.",
                        "stance": "neutral",
                        "time_horizon": "long_term",
                        "materiality": "medium",
                        "rationale": "The visible source supports a research-only conclusion.",
                        "fact_type": "fact",
                        "evidence_origin": "management_reported",
                        "unit": "qualitative",
                        "period": "long horizon",
                    }
                ],
                "ticker_coverage": [
                    {
                        "official_evidence_sufficient": True,
                        "contradictory_evidence": False,
                        "missing_evidence": [],
                    }
                ],
                "unresolved_questions": [],
                "evidence_direction": "stable",
                "research_classification": classification,
                "decisive_advice": "Keep the research classification conservative.",
                "long_term_case": "Primary evidence supports further diligence.",
                "confidence_pct": 50,
            }
        evidence = input_payload["packet_evidence"]
        packet_id = evidence["packet_id"]
        source_id = evidence["source_catalog"][0]["source_id"]
        if role == "committee":
            return {
                "schema_version": "phase5r_model_pilot_committee_v1",
                "packet_id": packet_id,
                "assessment_agreement": "agree",
                "preferred_assessment": "tie",
                "research_classification": classification,
                "thesis_direction": "stable",
                "decisive_advice": "Maintain a conservative research view.",
                "long_term_case": "Frozen evidence supports continued diligence.",
                "confidence_pct": 50,
                "supporting_claim_refs": [
                    {"assessment_label": "A", "claim_id": "v6_claim_1"},
                    {"assessment_label": "B", "claim_id": "v6_claim_1"},
                ],
                "source_ids": [source_id],
                "dissent": [],
                "automatic_action_allowed": False,
                "canonical_effect": False,
                "email_eligible": False,
            }
        control = input_payload["control_probe"]
        verdict = (
            "unsupported"
            if "guarantees" in control["claim"]
            else "supported"
        )
        return {
            "schema_version": "phase5r_model_pilot_critic_v1",
            "packet_id": packet_id,
            "committee_verdict": "approve",
            "downgrade_to": classification,
            "factual_grounding_pass": True,
            "citation_integrity_pass": True,
            "long_term_reasoning_pass": True,
            "action_proportionality_pass": True,
            "policy_boundary_pass": True,
            "claim_reviews": [
                {
                    "assessment_label": label,
                    "claim_id": "v6_claim_1",
                    "semantic_support": "supported",
                    "citation_accuracy": "accurate",
                    "issue": "No material issue identified.",
                    "supporting_source_ids": [source_id],
                }
                for label in ("A", "B")
            ],
            "issues": [],
            "control_probe": {
                "probe_id": control["probe_id"],
                "verdict": verdict,
                "explanation": "The frozen source supports the stated verdict.",
                "source_ids": [source_id],
            },
            "automatic_action_allowed": False,
            "canonical_effect": False,
            "email_eligible": False,
        }


class _V6PostParseContractFailureProvider(_V6FixtureProvider):
    """Return parsed, schema-shaped data that fails only local validation."""

    def generate(self, **kwargs: object) -> ProviderResult:
        result = super().generate(**kwargs)
        payload = copy.deepcopy(result.payload)
        if kwargs["role"] == "analyst":
            # The v6 source-locked schema permits an integer here.  The
            # unchanged local assessment validator enforces the 0..100 bound.
            payload["confidence_pct"] = 101
        return ProviderResult(payload=payload, metadata=result.metadata)


class ReplacementPilotV6Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.contexts, _ = v1._load_packet_contexts()
        self.context = self.contexts[0]

    def _analyst_payload(self) -> dict[str, object]:
        return _V6FixtureProvider()._payload(
            "analyst",
            {
                "source_locked_evidence_view": source_locked_input_view_v6(
                    self.context.runtime_packet
                )
            },
        )

    def test_contract_enforces_nonempty_text_and_hydrates_one_source(self) -> None:
        payload = self._analyst_payload()
        hydrated = hydrate_source_locked_assessment_v6(
            self.context.runtime_packet, payload
        )
        self.assertEqual(
            hydrated["packet_id"], self.context.runtime_packet["packet_id"]
        )
        self.assertEqual(hydrated["claims"][0]["claim_id"], "v6_claim_1")
        self.assertEqual(len(hydrated["claims"][0]["source_ids"]), 1)
        view = source_locked_input_view_v6(self.context.runtime_packet)
        self.assertNotIn("source_id", view["primary_source"])
        self.assertNotIn("content_sha256", view["primary_source"])
        schema = source_locked_assessment_schema_v6()
        self.assertEqual(
            schema["properties"]["claims"]["items"]["properties"]["claim"][
                "minLength"
            ],
            1,
        )
        invalid = copy.deepcopy(payload)
        invalid["claims"][0]["claim"] = ""
        with self.assertRaises(ContractError):
            hydrate_source_locked_assessment_v6(self.context.runtime_packet, invalid)

    def test_all_v6_stage_schemas_are_strict_and_capability_gated(self) -> None:
        for stage in (
            "luna_assessment",
            "terra_assessment",
            "sol_committee",
            "sol_critic",
        ):
            schema = strict_schema_for_stage_v6(stage)
            self.assertEqual(schema["additionalProperties"], False)

    def test_readiness_is_offline_and_freshly_sealed(self) -> None:
        report = v6.check_v6_readiness()
        self.assertTrue(report["passed"])
        self.assertEqual(report["planned_model_calls"], 30)
        self.assertEqual(report["maximum_usd"], "5")
        self.assertFalse(report["provider_constructed"])
        self.assertFalse(report["network_used"])
        self.assertEqual(report["model_calls"], 0)

    def test_post_parse_contract_failure_records_only_a_phase_code(self) -> None:
        """Regression: future terminal records distinguish this from transport."""

        with tempfile.TemporaryDirectory() as temporary:
            quarantine = Path(temporary) / "quarantine"
            output = quarantine / "v6"
            quarantine.mkdir()
            with self.assertRaises(v1.PilotStop):
                v6.execute_model_pilot_v6(
                    provider_factory=_V6PostParseContractFailureProvider,
                    explicit_user_authorization=True,
                    output_root=output,
                    allow_test_provider=True,
                    test_quarantine_root=quarantine,
                )
            execution = v1._read_json_object(
                output / "phase5r_model_pilot_v6_execution_plan.json",
                label="v6 fixture execution plan",
            )
            events = v1._load_journal(
                output / "phase5r_model_pilot_v6_journal.jsonl",
                plan_sha256=execution["plan_sha256"],
            )
            failures = [
                event for event in events if event["event_kind"] == "call_failed"
            ]
            self.assertEqual(len(failures), 1)
            details = failures[0]["details"]
            self.assertEqual(details["failure_phase"], "post_parse_contract_validation")
            self.assertEqual(details["failure_type"], "PilotStop")
            self.assertNotIn("raw_failed_response", details)
            self.assertNotIn("provider_response_id", details)
            self.assertNotIn("exception_message", details)

    def test_v7_plan_is_sealed_and_limited_to_v6_budget_remainder(self) -> None:
        plan = v1._read_json_object(
            v1.ROOT
            / "08_reviews/phase5r_model_pilot/replacement_v7"
            / "phase5r_model_pilot_v7_plan.json",
            label="v7 replacement plan",
        )
        asserted_hash = plan.pop("plan_sha256")
        self.assertEqual(asserted_hash, v1._canonical_sha256(plan))
        self.assertFalse(
            plan["execution_prohibited_without_explicit_runtime_authorization"]
        )
        self.assertEqual(plan["remaining_approved_budget"]["maximum_new_model_calls"], 19)
        self.assertEqual(plan["remaining_approved_budget"]["maximum_new_usd"], "4.8240310")
        self.assertFalse(plan["boundaries"]["canonical_effect"])
        self.assertFalse(plan["boundaries"]["email_effect"])
        self.assertFalse(plan["boundaries"]["trading"])

    def test_complete_fixture_collection_never_persists_provider_response_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            quarantine = Path(temporary) / "quarantine"
            output = quarantine / "v6"
            quarantine.mkdir()
            provider = _V6FixtureProvider()
            completion = v6.execute_model_pilot_v6(
                provider_factory=lambda: provider,
                explicit_user_authorization=True,
                output_root=output,
                allow_test_provider=True,
                test_quarantine_root=quarantine,
            )
            self.assertEqual(completion["physical_model_calls"], 30)
            self.assertFalse(completion["boundaries"]["canonical_effect"])
            response_files = sorted((output / v1.RESPONSE_DIRECTORY_NAME).glob("*.json"))
            self.assertEqual(len(response_files), 30)
            for path in response_files:
                receipt = v1._read_json_object(path, label="v6 fixture receipt")
                self.assertNotIn("provider_response_id", receipt["provider_metadata"])
                self.assertNotIn("provider_response_id_sha256", receipt["provider_metadata"])
            repeated = v6.execute_model_pilot_v6(
                provider_factory=lambda: provider,
                explicit_user_authorization=True,
                output_root=output,
                allow_test_provider=True,
                test_quarantine_root=quarantine,
            )
            self.assertEqual(repeated["completion_sha256"], completion["completion_sha256"])


if __name__ == "__main__":
    unittest.main()
