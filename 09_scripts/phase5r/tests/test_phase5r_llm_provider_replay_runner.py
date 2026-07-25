from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from phase5r_llm_contract import (
    ANALYST_SCHEMA_VERSION,
    COMMITTEE_SCHEMA_VERSION,
    CRITIC_SCHEMA_VERSION,
)
from phase5r_llm_provider import ProviderError, ProviderResult
from run_phase5r_llm_provider_replay_evaluation import (
    CallBudget,
    ReplayInputs,
    ReplayPlan,
    ReplayRunError,
    check_replay_readiness,
    execute_provider_replay,
)
from verify_phase5r_llm_provider_replay_gate import (
    PacketBinding,
    canonical_sha256,
)


class RecordingProvider:
    def __init__(self, registry: dict[str, Any], *, fail_at: int = 0) -> None:
        self.registry = registry
        self.fail_at = fail_at
        self.calls: list[tuple[str, str]] = []

    def _metadata(
        self,
        *,
        role: str,
        model: str,
        reasoning_effort: str,
        input_payload: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "transport": "codex_cli",
            "role": role,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "input_sha256": canonical_sha256(input_payload),
            "output_sha256": canonical_sha256(payload),
            "credential_read": False,
            "tools_enabled": False,
            "executable_sha256": self.registry[
                "provider_executable_sha256"
            ],
        }

    def generate(
        self,
        *,
        role: str,
        model: str,
        reasoning_effort: str,
        schema: dict[str, Any],
        instructions: str,
        input_payload: dict[str, Any],
    ) -> ProviderResult:
        del schema, instructions
        self.calls.append((role, model))
        if self.fail_at and len(self.calls) == self.fail_at:
            raise ProviderError("injected provider failure")
        if role in {"transition_pair", "stability_transition_pair"}:
            case = input_payload["case"]
            sources = sorted(
                {
                    input_payload["prior"]["packet"]["source_catalog"][0][
                        "source_id"
                    ],
                    input_payload["current"]["packet"]["source_catalog"][0][
                        "source_id"
                    ],
                }
            )
            payload = {
                "schema_version": "phase5r_llm_transition_pair_decision_v1",
                "case_id": case["case_id"],
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "ticker": case["ticker"],
                "classification": "paper_trade_candidate",
                "thesis_direction": "strengthening",
                "material_transition_detected": True,
                "rationale": "The two official filings support a material research change.",
                "evidence_source_ids": sources,
                "confidence_pct": 80,
                "automatic_action_allowed": False,
            }
        elif role == "adversarial_probe":
            case = input_payload["case"]
            packet = input_payload["base"]["packet"]
            payload = {
                "schema_version": (
                    "phase5r_llm_adversarial_safety_decision_v1"
                ),
                "case_id": case["case_id"],
                "base_packet_id": case["base_packet_id"],
                "ticker": case["ticker"],
                "mutation_detected": True,
                "safety_outcome": "reject",
                "classification": "reject",
                "rationale": "The synthetic mutation invalidates safe use.",
                "evidence_source_ids": [
                    packet["source_catalog"][0]["source_id"]
                ],
                "automatic_action_allowed": False,
            }
        else:
            packet = input_payload["packet"]
            packet_id = packet["packet_id"]
            ticker = packet["ticker"]
            source_id = packet["source_catalog"][0]["source_id"]
            if role == "analyst":
                payload = {
                    "schema_version": ANALYST_SCHEMA_VERSION,
                    "packet_id": packet_id,
                    "as_of_et": packet["as_of_et"],
                    "prompt_injection_detected": False,
                    "claims": [
                        {
                            "claim_id": f"claim:{packet_id[:12]}",
                            "ticker": ticker,
                            "claim": (
                                "Official evidence supports a material "
                                "long-term research change."
                            ),
                            "stance": "supports",
                            "time_horizon": "long_term",
                            "materiality": "high",
                            "source_ids": [source_id],
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
                }
            elif role == "committee":
                payload = {
                    "schema_version": COMMITTEE_SCHEMA_VERSION,
                    "packet_id": packet_id,
                    "portfolio_classification": "paper_trade_candidate",
                    "headline": "Material research transition identified.",
                    "decisive_advice": (
                        "Escalate the research classification for human review."
                    ),
                    "long_term_portfolio_case": (
                        "Official evidence supports the long-horizon thesis."
                    ),
                    "data_sufficiency": "sufficient",
                    "material_thesis_break": False,
                    "confidence_pct": 80,
                    "ticker_decisions": [
                        {
                            "ticker": ticker,
                            "classification": "paper_trade_candidate",
                            "thesis_direction": "strengthening",
                            "rationale": "Official evidence is materially stronger.",
                            "long_term_case": "The long-horizon case improved.",
                            "risks": ["Evidence may change."],
                            "invalidation_conditions": [
                                "A later primary filing reverses the evidence."
                            ],
                            "source_ids": [source_id],
                            "calculation_ids": [],
                            "confidence_pct": 80,
                            "human_review_needed": True,
                        }
                    ],
                    "dissent": [],
                    "automatic_action_allowed": False,
                }
            else:
                committee = input_payload["committee"]
                payload = {
                    "schema_version": CRITIC_SCHEMA_VERSION,
                    "packet_id": packet_id,
                    "verdict": "approve",
                    "downgrade_to": committee["portfolio_classification"],
                    "factual_grounding_pass": True,
                    "citation_integrity_pass": True,
                    "numeric_reconciliation_pass": True,
                    "long_term_reasoning_pass": True,
                    "action_proportionality_pass": True,
                    "policy_boundary_pass": True,
                    "issues": [],
                    "approved_source_ids": [source_id],
                    "automatic_action_allowed": False,
                }
        return ProviderResult(
            payload=payload,
            metadata=self._metadata(
                role=role,
                model=model,
                reasoning_effort=reasoning_effort,
                input_payload=input_payload,
                payload=payload,
            ),
        )


class ProviderReplayRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="phase5r-provider-replay-runner-"
        )
        self.root = Path(self.temporary.name)
        self.registry = {
            "schema_version": "phase5r_llm_model_registry_v1",
            "provider": "codex_cli_external_auth",
            "provider_executable": "/opt/homebrew/bin/codex",
            "provider_executable_sha256": "a" * 64,
            "roles": {
                "analyst": {
                    "model": "analyst-model",
                    "reasoning_effort": "medium",
                    "prompt_version": "analyst-prompt",
                },
                "committee": {
                    "model": "committee-model",
                    "reasoning_effort": "high",
                    "prompt_version": "committee-prompt",
                },
                "critic": {
                    "model": "critic-model",
                    "reasoning_effort": "high",
                    "prompt_version": "critic-prompt",
                },
            },
        }
        accepted = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.prior = self._binding("1" * 64, "0000000001-26-000001", accepted)
        self.current = self._binding(
            "2" * 64,
            "0000000002-26-000002",
            accepted + timedelta(days=2),
        )
        fingerprint = "3" * 64
        self.case_id = f"transition:{fingerprint[:24]}"
        transition = {
            "case_id": self.case_id,
            "case_kind": "material_transition_detection_probe",
            "ticker": "TST",
            "prior_packet_id": self.prior.payload["packet_id"],
            "current_packet_id": self.current.payload["packet_id"],
            "transition_fingerprint": fingerprint,
        }
        adversarial_id = (
            f"adversarial:untrusted_instruction_overlay:"
            f"{self.current.payload['packet_id'][:16]}"
        )
        adversarial = {
            "case_id": adversarial_id,
            "case_kind": "adversarial_safety_probe",
            "ticker": "TST",
            "base_packet_id": self.current.payload["packet_id"],
            "synthetic_mutation": "untrusted_instruction_overlay",
            "expected_safety_outcome": "reject_or_abstain",
        }
        corpus = type(
            "Corpus",
            (),
            {
                "manifest": {},
                "manifest_sha256": "b" * 64,
                "packets": {
                    self.prior.payload["packet_id"]: self.prior,
                    self.current.payload["packet_id"]: self.current,
                },
                "transitions": {self.case_id: transition},
                "adversarial_probes": {adversarial_id: adversarial},
                "source_identity_count": 2,
                "accession_count": 2,
            },
        )()
        annotation = {
            "annotation_id": f"annotation:{fingerprint[:24]}",
            "annotation_sha256": "c" * 64,
            "case_id": self.case_id,
            "transition_fingerprint": fingerprint,
            "prior_packet_id": self.prior.payload["packet_id"],
            "current_packet_id": self.current.payload["packet_id"],
            "is_material_transition": True,
            "reference_classification": "paper_trade_candidate",
            "reference_thesis_direction": "strengthening",
            "rubric_version": "phase5r_material_transition_reference_v1",
            "annotation_method": "independent_dual_review",
            "independent_reviewer_count": 2,
            "reviewer_agreement": True,
            "evidence_source_ids": sorted(
                [self.prior.primary_source_id, self.current.primary_source_id]
            ),
            "rationale_sha256": "d" * 64,
            "provider_quality_scoring_eligible": True,
        }
        self.inputs = ReplayInputs(
            registry=self.registry,
            registry_sha256="e" * 64,
            corpus=corpus,
            annotations=[annotation],
            annotation_metadata={
                "annotation_file_sha256": "f" * 64,
                "annotation_set_sha256": "0" * 64,
            },
            plan=ReplayPlan(
                packet_count=2,
                annotation_count=1,
                adversarial_probe_count=1,
                stability_transition_count=1,
                stability_trials_per_transition=2,
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _binding(
        packet_id: str,
        accession: str,
        accepted_at: datetime,
    ) -> PacketBinding:
        as_of = accepted_at + timedelta(days=1)
        source_id = f"sec-primary:{accession}"
        packet = {
            "schema_version": "phase5r_llm_replay_packet_v1",
            "packet_id": packet_id,
            "ticker": "TST",
            "as_of_et": as_of.isoformat(),
            "source_catalog": [
                {
                    "source_id": source_id,
                    "accepted_at_et": accepted_at.isoformat(),
                }
            ],
            "calculations": [],
        }
        return PacketBinding(
            payload=packet,
            accession=accession,
            ticker="TST",
            accepted_at_et=accepted_at,
            source_ids=frozenset({source_id}),
            primary_source_id=source_id,
            evidence_excerpts=(
                {
                    "source_id": source_id,
                    "chunk_index": 0,
                    "char_start": 0,
                    "char_end": 8,
                    "excerpt_text": "evidence",
                    "excerpt_sha256": canonical_sha256("evidence"),
                },
            ),
        )

    def _execute(
        self,
        provider: RecordingProvider,
        *,
        exact_calls: int = 10,
        verifier: Any = None,
    ) -> dict[str, Any]:
        output = self.root / "published"
        captured: dict[str, Any] = {}

        def accepting_verifier(**kwargs: Any) -> dict[str, Any]:
            report = json.loads(
                Path(kwargs["provider_report_path"]).read_text(
                    encoding="utf-8"
                )
            )
            captured["report"] = report
            return {"passed": True, "issues": []}

        with patch(
            "run_phase5r_llm_provider_replay_evaluation.load_replay_inputs",
            return_value=self.inputs,
        ):
            result = execute_provider_replay(
                manifest_path=self.root / "manifest.json",
                annotation_path=self.root / "annotations.json",
                model_registry_path=self.root / "registry.json",
                output_root=output,
                acknowledge_external_inference=True,
                annotation_file_sha256="f" * 64,
                exact_maximum_calls=exact_calls,
                max_estimated_usd=Decimal("1.00"),
                estimated_usd_per_call=Decimal("0.01"),
                provider=provider,
                allow_test_provider=True,
                allow_test_path=True,
                minimum_packets=2,
                minimum_transitions=1,
                stability_transition_count=1,
                stability_trials_per_transition=2,
                verifier=verifier or accepting_verifier,
            )
        result["_captured"] = captured
        return result

    def test_fake_provider_exact_calls_roles_and_report_contract(self) -> None:
        provider = RecordingProvider(self.registry)
        result = self._execute(provider)
        self.assertTrue(result["passed"])
        self.assertEqual(result["provider_calls"], 10)
        roles = [role for role, _ in provider.calls]
        self.assertEqual(roles.count("analyst"), 2)
        self.assertEqual(roles.count("committee"), 2)
        self.assertEqual(roles.count("critic"), 2)
        self.assertEqual(roles.count("transition_pair"), 1)
        self.assertEqual(roles.count("adversarial_probe"), 1)
        self.assertEqual(roles.count("stability_transition_pair"), 2)
        report = result["_captured"]["report"]
        self.assertEqual(report["summary"]["total_provider_call_count"], 10)
        self.assertEqual(len(report["results"]), 6)
        self.assertEqual(len(report["transition_pair_results"]), 1)
        self.assertEqual(len(report["adversarial_probe_results"]), 1)
        self.assertEqual(len(report["stability_trials"]), 2)
        self.assertFalse(report["boundaries"]["canonical_effect"])

    def test_exact_call_budget_mismatch_fails_before_provider(self) -> None:
        provider = RecordingProvider(self.registry)
        with self.assertRaisesRegex(ReplayRunError, "maximum-call"):
            self._execute(provider, exact_calls=9)
        self.assertEqual(provider.calls, [])
        self.assertFalse((self.root / "published").exists())

    def test_provider_failure_removes_stage_and_writes_no_report(self) -> None:
        provider = RecordingProvider(self.registry, fail_at=3)
        with self.assertRaises(ProviderError):
            self._execute(provider)
        self.assertFalse((self.root / "published").exists())
        self.assertEqual(
            list(self.root.glob(".phase5r-provider-replay-stage-*")),
            [],
        )

    def test_check_failure_is_read_only_and_never_constructs_provider(self) -> None:
        before = set(self.root.iterdir())
        with patch(
            "run_phase5r_llm_provider_replay_evaluation.load_replay_inputs",
            side_effect=ReplayRunError("missing frozen annotations"),
        ):
            result = check_replay_readiness(
                manifest_path=self.root / "manifest.json",
                annotation_path=self.root / "annotations.json",
                model_registry_path=self.root / "registry.json",
            )
        self.assertFalse(result["ready"])
        self.assertFalse(result["provider_invoked"])
        self.assertFalse(result["network_invoked"])
        self.assertFalse(result["files_written"])
        self.assertEqual(set(self.root.iterdir()), before)

    def test_usd_budget_fails_before_any_call(self) -> None:
        budget = CallBudget(
            exact_maximum_calls=10,
            max_estimated_usd=Decimal("0.09"),
            estimated_usd_per_call=Decimal("0.01"),
            planned_calls=10,
        )
        with self.assertRaisesRegex(ReplayRunError, "USD ceiling"):
            budget.validate()
        self.assertEqual(budget.used_calls, 0)


if __name__ == "__main__":
    unittest.main()
