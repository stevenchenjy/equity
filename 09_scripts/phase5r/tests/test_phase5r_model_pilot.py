from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from phase5r_llm_provider import ProviderResult
from run_phase5r_model_pilot import (
    DEFAULT_OUTPUT_ROOT,
    BLIND_ASSIGNMENT_NAME,
    COMPLETION_NAME,
    MAXIMUM_INPUT_TOKENS,
    MAXIMUM_OUTPUT_TOKENS,
    QUARANTINE_ROOT,
    REQUEST_TIMEOUT_SECONDS,
    PilotStop,
    _canonical_sha256,
    _decimal_text,
    _assert_model_identity_blind,
    execute_model_pilot,
    check_pilot_readiness,
)


class FakePilotProvider:
    offline_test_provider = True

    def __init__(
        self,
        state: dict[str, Any],
        *,
        input_tokens: int = 100,
        interrupt: bool = False,
        contract_failure_model_call: int | None = None,
    ) -> None:
        self.state = state
        self.input_tokens = input_tokens
        self.interrupt = interrupt
        self.contract_failure_model_call = contract_failure_model_call
        self.max_output_tokens = MAXIMUM_OUTPUT_TOKENS
        self.request_timeout_seconds = REQUEST_TIMEOUT_SECONDS
        self.billing_scope_attestation = (
            "global_standard_no_regional_processing"
        )

    def count_input_tokens(self, **kwargs: Any) -> int:
        self.state["count_calls"] += 1
        self.state["count_models"].append(kwargs["model"])
        return self.input_tokens

    @staticmethod
    def _assessment(
        *,
        model: str,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        view = input_payload["packet_view"]
        identity = view["packet_identity"]
        source = view["source_catalog"][0]
        entity = view["entities"][0]
        ticker = entity["ticker"]
        held = entity["role"] == "held"
        classification = "hold_existing" if held else "watchlist"
        return {
            "schema_version": "phase5r_llm_evidence_analysis_v1",
            "packet_id": identity["packet_id"],
            "as_of_et": identity["as_of_et"],
            "prompt_injection_detected": False,
            "claims": [
                {
                    "claim_id": "qualitative-claim",
                    "ticker": ticker,
                    "claim": (
                        "The filing describes a material long-term "
                        "operating condition."
                    ),
                    "stance": "neutral",
                    "time_horizon": "long_term",
                    "materiality": "medium",
                    "rationale": (
                        "The frozen primary excerpt supports continued "
                        "long-term review."
                    ),
                    "fact_type": "fact",
                    "evidence_origin": "management_reported",
                    "unit": "not applicable",
                    "period": "filing period",
                    "source_ids": [source["source_id"]],
                    "cited_excerpt_sha256": [
                        source["content_sha256"]
                    ],
                    "calculation_ids": [],
                }
            ],
            "ticker_coverage": [
                {
                    "ticker": ticker,
                    "official_evidence_sufficient": True,
                    "contradictory_evidence": False,
                    "missing_evidence": [],
                }
            ],
            "unresolved_questions": [],
            "evidence_direction": "stable",
            "research_classification": classification,
            "decisive_advice": (
                "Keep the current shadow research classification."
            ),
            "long_term_case": (
                "The frozen evidence supports continued monitoring of "
                "the long-term thesis."
            ),
            "confidence_pct": 60,
            "automatic_action_allowed": False,
            "canonical_effect": False,
            "email_eligible": False,
        }

    @staticmethod
    def _committee(input_payload: dict[str, Any]) -> dict[str, Any]:
        assessment = input_payload["assessment_A"]
        source = input_payload["packet_evidence"]["source_catalog"][0]
        return {
            "schema_version": "phase5r_model_pilot_committee_v1",
            "packet_id": input_payload["packet_evidence"]["packet_id"],
            "assessment_agreement": "agree",
            "preferred_assessment": "tie",
            "research_classification": assessment[
                "research_classification"
            ],
            "thesis_direction": "stable",
            "decisive_advice": (
                "Keep the evidence-bound shadow research classification."
            ),
            "long_term_case": (
                "The primary excerpt supports continued long-term review."
            ),
            "confidence_pct": 55,
            "supporting_claim_refs": [
                {
                    "assessment_label": "A",
                    "claim_id": assessment["claims"][0]["claim_id"],
                }
            ],
            "source_ids": [source["source_id"]],
            "dissent": [],
            "automatic_action_allowed": False,
            "canonical_effect": False,
            "email_eligible": False,
        }

    @staticmethod
    def _critic(input_payload: dict[str, Any]) -> dict[str, Any]:
        reviews = []
        for label in ("A", "B"):
            for claim in input_payload[f"assessment_{label}"]["claims"]:
                reviews.append(
                    {
                        "assessment_label": label,
                        "claim_id": claim["claim_id"],
                        "semantic_support": "supported",
                        "citation_accuracy": "accurate",
                        "issue": "No material issue found.",
                        "supporting_source_ids": claim["source_ids"],
                    }
                )
        control = input_payload["control_probe"]
        unsupported = "guarantees" in control["claim"]
        committee = input_payload["committee"]
        return {
            "schema_version": "phase5r_model_pilot_critic_v1",
            "packet_id": input_payload["packet_evidence"]["packet_id"],
            "committee_verdict": "approve",
            "downgrade_to": committee["research_classification"],
            "factual_grounding_pass": True,
            "citation_integrity_pass": True,
            "long_term_reasoning_pass": True,
            "action_proportionality_pass": True,
            "policy_boundary_pass": True,
            "claim_reviews": reviews,
            "issues": [],
            "control_probe": {
                "probe_id": control["probe_id"],
                "verdict": (
                    "unsupported" if unsupported else "supported"
                ),
                "explanation": (
                    "The probe was checked against the frozen excerpt."
                ),
                "source_ids": control["cited_source_ids"],
            },
            "automatic_action_allowed": False,
            "canonical_effect": False,
            "email_eligible": False,
        }

    def generate(self, **kwargs: Any) -> ProviderResult:
        self.state["model_calls"] += 1
        self.state["models"].append(kwargs["model"])
        if self.interrupt:
            raise KeyboardInterrupt("simulated process interruption")
        role = kwargs["role"]
        input_payload = kwargs["input_payload"]
        if role == "analyst":
            payload = self._assessment(
                model=kwargs["model"],
                input_payload=input_payload,
            )
        elif role == "committee":
            payload = self._committee(input_payload)
        else:
            payload = self._critic(input_payload)
        if (
            role == "analyst"
            and self.contract_failure_model_call
            == self.state["model_calls"]
        ):
            payload = deepcopy(payload)
            payload["as_of_et"] = "2099-01-01T00:00:00-05:00"
        return ProviderResult(
            payload=payload,
            metadata={
                "transport": "test_fixture",
                "role": role,
                "model": kwargs["model"],
                "resolved_model": kwargs["model"],
                "requested_service_tier": "default",
                "resolved_service_tier": "default",
                "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
                "billing_scope_attestation": (
                    "global_standard_no_regional_processing"
                ),
                "credential_read": False,
                "tools_enabled": False,
                "store": False,
                "provider_response_id": (
                    f"fixture-{self.state['model_calls']:02d}"
                ),
                "usage": {
                    "input_tokens": self.input_tokens,
                    "output_tokens": 50,
                    "cached_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )


def new_state() -> dict[str, Any]:
    return {
        "factory_calls": 0,
        "count_calls": 0,
        "count_models": [],
        "model_calls": 0,
        "models": [],
    }


class ModelPilotTests(unittest.TestCase):
    def test_readiness_freezes_ten_packets_thirty_calls_and_budget(
        self,
    ) -> None:
        report = check_pilot_readiness()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["packet_count"], 10)
        self.assertEqual(report["planned_model_calls"], 30)
        self.assertEqual(report["worst_case_reserved_usd"], "4.9368")
        self.assertEqual(report["maximum_usd"], "5")
        self.assertFalse(report["provider_constructed"])
        self.assertFalse(report["network_used"])
        self.assertTrue(report["daily_monitoring_preserved"])
        self.assertTrue(report["shadow_scheduler_absent"])

    def test_fake_metered_pilot_completes_exactly_thirty_calls(
        self,
    ) -> None:
        state = new_state()

        def factory() -> FakePilotProvider:
            state["factory_calls"] += 1
            return FakePilotProvider(state)

        with tempfile.TemporaryDirectory(
            prefix="phase5r-model-pilot-test-"
        ) as directory:
            quarantine = Path(directory) / "quarantine"
            output = quarantine / "case"
            completion = execute_model_pilot(
                provider_factory=factory,
                output_root=output,
                quarantine_root=quarantine,
                allow_test_provider=True,
            )
            self.assertEqual(state["factory_calls"], 30)
            self.assertEqual(state["count_calls"], 30)
            self.assertEqual(state["model_calls"], 30)
            self.assertEqual(
                state["models"].count("gpt-5.6-luna"), 10
            )
            self.assertEqual(
                state["models"].count("gpt-5.6-terra"), 10
            )
            self.assertEqual(state["models"].count("gpt-5.6-sol"), 10)
            self.assertEqual(completion["physical_model_calls"], 30)
            self.assertEqual(completion["execution_mode"], "test_fixture")
            self.assertEqual(completion["exact_model_cost_usd"], "0.034")
            self.assertEqual(
                completion["go_no_go"],
                "no_go_pending_independent_review",
            )
            metrics = json.loads(
                (output / "phase5r_model_pilot_metrics.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                metrics["critic_value"]["control_accuracy_pct"], 100.0
            )
            self.assertEqual(
                metrics["model_disagreement"][
                    "classification_disagreement_count"
                ],
                0,
            )
            review = json.loads(
                (
                    output
                    / "phase5r_model_pilot_anonymous_review.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(review["row_count"], 20)
            self.assertNotIn(
                "gpt-5.6",
                json.dumps(review, ensure_ascii=False),
            )
            rendered_review = json.dumps(review, ensure_ascii=False).lower()
            for identity in ("luna", "terra", "openai"):
                self.assertNotIn(identity, rendered_review)
            self.assertEqual(review["critic_row_count"], 5)
            calls_before_resume_checks = state["model_calls"]
            journal = output / "phase5r_model_pilot_journal.jsonl"
            hidden_journal = output / "journal.hidden"
            journal.rename(hidden_journal)
            with self.assertRaisesRegex(PilotStop, "durable journal"):
                execute_model_pilot(
                    provider_factory=factory,
                    output_root=output,
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            hidden_journal.rename(journal)
            completion_path = (
                output / "phase5r_model_pilot_completion.json"
            )
            tampered = json.loads(completion_path.read_text(encoding="utf-8"))
            tampered["boundaries"]["canonical_effect"] = True
            tampered.pop("completion_sha256")
            tampered["completion_sha256"] = _canonical_sha256(tampered)
            completion_path.write_text(
                json.dumps(
                    tampered,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PilotStop, "completion is invalid"):
                execute_model_pilot(
                    provider_factory=factory,
                    output_root=output,
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            self.assertEqual(state["model_calls"], calls_before_resume_checks)

    def test_exact_input_ceiling_stops_before_model_call(self) -> None:
        state = new_state()

        def factory() -> FakePilotProvider:
            state["factory_calls"] += 1
            return FakePilotProvider(
                state,
                input_tokens=MAXIMUM_INPUT_TOKENS + 1,
            )

        with tempfile.TemporaryDirectory(
            prefix="phase5r-model-pilot-token-stop-"
        ) as directory:
            quarantine = Path(directory) / "quarantine"
            with self.assertRaisesRegex(
                RuntimeError, "input token count"
            ):
                execute_model_pilot(
                    provider_factory=factory,
                    output_root=quarantine / "case",
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            self.assertEqual(state["count_calls"], 1)
            self.assertEqual(state["model_calls"], 0)

    def test_fourth_contract_failure_is_redacted_and_terminal(self) -> None:
        state = new_state()

        def factory() -> FakePilotProvider:
            state["factory_calls"] += 1
            return FakePilotProvider(
                state,
                contract_failure_model_call=4,
            )

        with tempfile.TemporaryDirectory(
            prefix="phase5r-model-pilot-contract-stop-"
        ) as directory:
            quarantine = Path(directory) / "quarantine"
            output = quarantine / "case"
            with self.assertRaisesRegex(PilotStop, "call_failed"):
                execute_model_pilot(
                    provider_factory=factory,
                    output_root=output,
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            self.assertEqual(state["model_calls"], 4)
            self.assertEqual(
                state["models"],
                [
                    "gpt-5.6-luna",
                    "gpt-5.6-terra",
                    "gpt-5.6-luna",
                    "gpt-5.6-terra",
                ],
            )
            journal = output / "phase5r_model_pilot_journal.jsonl"
            events = [
                json.loads(line)
                for line in journal.read_text(encoding="utf-8").splitlines()
            ]
            failed = [
                event for event in events if event["event_kind"] == "call_failed"
            ]
            self.assertEqual(len(failed), 1)
            self.assertTrue(failed[0]["call_id"].endswith("terra-assessment"))
            self.assertEqual(failed[0]["details"]["failure_type"], "ContractError")
            self.assertEqual(
                failed[0]["details"]["redacted_contract_diagnostic"],
                {
                    "schema_version": (
                        "phase5r_model_pilot_contract_diagnostic_v1"
                    ),
                    "stage": "terra_assessment",
                    "validator": "assessment",
                    "code": "analyst_as_of_et_mismatch",
                },
            )
            self.assertNotIn("2099-01-01", journal.read_text(encoding="utf-8"))
            self.assertFalse(
                (
                    output
                    / "responses"
                    / f"{failed[0]['call_id']}.json"
                ).exists()
            )
            calls_before_resume = state["model_calls"]
            with self.assertRaisesRegex(PilotStop, "durable stop"):
                execute_model_pilot(
                    provider_factory=factory,
                    output_root=output,
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            self.assertEqual(state["model_calls"], calls_before_resume)

    def test_first_completion_rejects_journal_receipt_cost_mismatch(
        self,
    ) -> None:
        state = new_state()

        def factory() -> FakePilotProvider:
            state["factory_calls"] += 1
            return FakePilotProvider(state)

        with tempfile.TemporaryDirectory(
            prefix="phase5r-model-pilot-first-publication-"
        ) as directory:
            quarantine = Path(directory) / "quarantine"
            output = quarantine / "case"
            completion = execute_model_pilot(
                provider_factory=factory,
                output_root=output,
                quarantine_root=quarantine,
                allow_test_provider=True,
            )
            calls_before_resume = state["model_calls"]
            (output / COMPLETION_NAME).unlink()
            for artifact_name in completion["artifacts"]:
                if artifact_name != BLIND_ASSIGNMENT_NAME:
                    (output / artifact_name).unlink()

            journal = output / "phase5r_model_pilot_journal.jsonl"
            events = [
                json.loads(line)
                for line in journal.read_text(encoding="utf-8").splitlines()
            ]
            for event in events:
                if event["event_kind"] == "call_completed":
                    event["details"]["actual_cost_usd"] = "0"
                    break
            exact_journal_cost = sum(
                (
                    Decimal(event["details"]["actual_cost_usd"])
                    for event in events
                    if event["event_kind"] == "call_completed"
                ),
                Decimal(0),
            )
            events[-1]["details"]["charged_usd"] = _decimal_text(
                exact_journal_cost
            )
            previous = "0" * 64
            rendered_events = []
            for index, event in enumerate(events):
                event["event_index"] = index
                event["previous_event_sha256"] = previous
                event.pop("event_sha256", None)
                event["event_sha256"] = _canonical_sha256(event)
                previous = event["event_sha256"]
                rendered_events.append(
                    json.dumps(
                        event,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            journal.write_text(
                "\n".join(rendered_events) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                PilotStop,
                "journal/receipt binding",
            ):
                execute_model_pilot(
                    provider_factory=factory,
                    output_root=output,
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            self.assertEqual(state["model_calls"], calls_before_resume)

    def test_orphaned_reservation_is_never_retried(self) -> None:
        state = new_state()

        def interrupting_factory() -> FakePilotProvider:
            state["factory_calls"] += 1
            return FakePilotProvider(state, interrupt=True)

        with tempfile.TemporaryDirectory(
            prefix="phase5r-model-pilot-recovery-"
        ) as directory:
            quarantine = Path(directory) / "quarantine"
            output = quarantine / "case"
            with self.assertRaises(KeyboardInterrupt):
                execute_model_pilot(
                    provider_factory=interrupting_factory,
                    output_root=output,
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            self.assertEqual(state["model_calls"], 1)
            factories_before = state["factory_calls"]
            with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
                execute_model_pilot(
                    provider_factory=interrupting_factory,
                    output_root=output,
                    quarantine_root=quarantine,
                    allow_test_provider=True,
                )
            self.assertEqual(state["factory_calls"], factories_before)
            self.assertEqual(state["model_calls"], 1)
            events = [
                json.loads(line)
                for line in (output / "phase5r_model_pilot_journal.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            unknown = [
                event
                for event in events
                if event["event_kind"] == "call_outcome_unknown"
            ]
            self.assertEqual(len(unknown), 1)
            self.assertEqual(
                unknown[0]["details"]["charged_reservation_usd"],
                "0.05808",
            )

    def test_model_identity_markers_are_rejected_from_blinded_output(
        self,
    ) -> None:
        for marker in ("Luna", "terra", "Sol", "OpenAI", "gpt-5.6"):
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(PilotStop, "model identity"):
                    _assert_model_identity_blind({"claim": marker})

    def test_fixture_mode_cannot_use_production_quarantine(self) -> None:
        state = new_state()

        def factory() -> FakePilotProvider:
            state["factory_calls"] += 1
            return FakePilotProvider(state)

        with self.assertRaisesRegex(
            PilotStop,
            "test providers cannot write",
        ):
            execute_model_pilot(
                provider_factory=factory,
                output_root=DEFAULT_OUTPUT_ROOT,
                quarantine_root=QUARANTINE_ROOT,
                allow_test_provider=True,
            )
        self.assertEqual(state["factory_calls"], 0)


if __name__ == "__main__":
    unittest.main()
