from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from _support import SCRIPT_DIR, materialized  # noqa: F401
from phase5r_llm_contract import (
    ANALYST_SCHEMA_VERSION,
    COMMITTEE_SCHEMA_VERSION,
    CRITIC_SCHEMA_VERSION,
)
from phase5r_llm_provider import ProviderError, ProviderResult
from run_phase5r_llm_provider_replay_evaluation import (
    CallBudget,
    CollectionCallStore,
    FINAL_CITATION_REVIEW_NAME,
    ReplayInputs,
    ReplayPlan,
    ReplayRunError,
    _read_private_json,
    _write_json_exclusive,
    _write_json_atomic,
    check_replay_readiness,
    execute_provider_replay,
    finalize_provider_replay,
)
from verify_phase5r_llm_provider_replay_gate import (
    CITATION_REVIEW_SET_PATH,
    PacketBinding,
    canonical_sha256,
    deterministic_replay_evaluation_context,
)


class RecordingProvider:
    def __init__(
        self,
        registry: dict[str, Any],
        runtime_packets: dict[str, dict[str, Any]],
        *,
        fail_at: int = 0,
        transport_fail_at: int = 0,
        semantic_invalid_first: bool = False,
        insufficient_coverage: bool = False,
        abstain_committee: bool = False,
    ) -> None:
        self.registry = registry
        self.runtime_packets = runtime_packets
        self.fail_at = fail_at
        self.transport_fail_at = transport_fail_at
        self.semantic_invalid_first = semantic_invalid_first
        self.semantic_invalid_emitted = False
        self.insufficient_coverage = insufficient_coverage
        self.abstain_committee = abstain_committee
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
        if (
            self.transport_fail_at
            and len(self.calls) == self.transport_fail_at
        ):
            raise ProviderError(f"{role} model call timed out")
        if role == "negative_control":
            case = input_payload["case"]
            payload = {
                "schema_version": "phase5r_llm_transition_pair_decision_v1",
                "case_id": case["case_id"],
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "ticker": case["ticker"],
                "classification": "abstain",
                "thesis_direction": "unchanged",
                "material_transition_detected": False,
                "rationale": "The same frozen packet appears on both sides.",
                "evidence_source_ids": [],
                "confidence_pct": 100,
                "automatic_action_allowed": False,
            }
        elif role in {"transition_pair", "stability_transition_pair"}:
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
            packet = input_payload["base"]["mutated_packet"]
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
        elif role == "critic_control":
            control = input_payload["control"]
            proposal = input_payload["committee_proposal"]
            packet_id = proposal["packet_id"]
            faulty = (
                proposal["ticker_decisions"][0]["source_ids"]
                == ["synthetic:unknown-citation"]
            )
            payload = {
                "schema_version": "phase5r_llm_critic_control_review_v1",
                "control_id": control["control_id"],
                "packet_id": packet_id,
                "verdict": "reject" if faulty else "approve",
                "issues": (
                    ["The proposal contains a forged citation."]
                    if faulty
                    else []
                ),
                "approved_source_ids": (
                    []
                    if faulty
                    else proposal["ticker_decisions"][0]["source_ids"]
                ),
                "automatic_action_allowed": False,
            }
        elif role == "counterfactual_transition_pair":
            case = input_payload["case"]
            payload = {
                "schema_version": "phase5r_llm_transition_pair_decision_v1",
                "case_id": case["case_id"],
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "ticker": case["ticker"],
                "classification": "abstain",
                "thesis_direction": "unchanged",
                "material_transition_detected": False,
                "rationale": "Decisive current-period evidence was removed.",
                "evidence_source_ids": [],
                "confidence_pct": 100,
                "automatic_action_allowed": False,
            }
        else:
            if role == "analyst":
                packet_id = input_payload["packet_view"]["packet_identity"][
                    "packet_id"
                ]
                packet = self.runtime_packets[packet_id]
            else:
                packet = self.runtime_packets[
                    input_payload["validated_analyst"]["packet_id"]
                ]
            packet_id = packet["packet_id"]
            ticker = packet["entities"][0]["ticker"]
            source_id = packet["source_catalog"][0]["source_id"]
            source_content_sha = packet["source_catalog"][0][
                "content_sha256"
            ]
            claim_id = f"claim:{packet_id[:12]}"
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
                            "rationale": (
                                "The primary filing excerpt directly supports "
                                "the research claim."
                            ),
                            "fact_type": "fact",
                            "evidence_origin": "management_reported",
                            "unit": "not_applicable",
                            "period": "current_filing_period",
                            "source_ids": [source_id],
                            "cited_excerpt_sha256": [
                                source_content_sha
                            ],
                            "calculation_ids": [],
                        }
                    ],
                    "ticker_coverage": [
                        {
                            "ticker": ticker,
                            "official_evidence_sufficient": (
                                not self.insufficient_coverage
                            ),
                            "contradictory_evidence": False,
                            "missing_evidence": (
                                ["Additional official evidence is required."]
                                if self.insufficient_coverage
                                else []
                            ),
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
                    "confidence_pct": 0,
                    "confidence_components": {
                        "evidence_coverage_pct": 80,
                        "thesis_clarity_pct": 80,
                        "valuation_clarity_pct": 0,
                        "portfolio_fit_pct": 80,
                    },
                    "supporting_facts": [
                        {
                            "ticker": ticker,
                            "fact": (
                                "Primary evidence supports durable demand."
                            ),
                            "source_ids": [source_id],
                            "calculation_ids": [],
                        },
                        {
                            "ticker": ticker,
                            "fact": (
                                "Primary evidence supports the long-term case."
                            ),
                            "source_ids": [source_id],
                            "calculation_ids": [],
                        },
                        {
                            "ticker": ticker,
                            "fact": (
                                "Primary evidence supports strategic progress."
                            ),
                            "source_ids": [source_id],
                            "calculation_ids": [],
                        },
                    ],
                    "disconfirming_facts": [
                        {
                            "ticker": ticker,
                            "fact": (
                                "Primary evidence leaves demand uncertainty."
                            ),
                            "source_ids": [source_id],
                            "calculation_ids": [],
                        },
                        {
                            "ticker": ticker,
                            "fact": (
                                "Primary evidence leaves execution uncertainty."
                            ),
                            "source_ids": [source_id],
                            "calculation_ids": [],
                        },
                        {
                            "ticker": ticker,
                            "fact": (
                                "Primary evidence leaves competitive uncertainty."
                            ),
                            "source_ids": [source_id],
                            "calculation_ids": [],
                        },
                    ],
                    "scenarios": {
                        "bull": "Durable evidence strengthens.",
                        "base": "The thesis develops gradually.",
                        "bear": "Primary evidence weakens.",
                    },
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
                            "claim_ids": [claim_id],
                            "source_ids": [source_id],
                            "calculation_ids": [],
                            "confidence_pct": 80,
                            "human_review_needed": True,
                        }
                    ],
                    "dissent": [],
                    "automatic_action_allowed": False,
                }
                if self.abstain_committee:
                    payload.update(
                        {
                            "portfolio_classification": "abstain",
                            "headline": (
                                "Official evidence is currently insufficient."
                            ),
                            "decisive_advice": (
                                "The research classification remains abstain."
                            ),
                            "long_term_portfolio_case": (
                                "The long-term case cannot be established from "
                                "the available official evidence."
                            ),
                            "data_sufficiency": "insufficient",
                            "confidence_pct": 0,
                            "confidence_components": {
                                "evidence_coverage_pct": 0,
                                "thesis_clarity_pct": 0,
                                "valuation_clarity_pct": 0,
                                "portfolio_fit_pct": 0,
                            },
                            "supporting_facts": [],
                            "disconfirming_facts": [],
                            "scenarios": {
                                "bull": "Additional evidence could strengthen.",
                                "base": "Evidence remains insufficient.",
                                "bear": "Later evidence could weaken the case.",
                            },
                            "ticker_decisions": [
                                {
                                    "ticker": ticker,
                                    "classification": "abstain",
                                    "thesis_direction": "unclear",
                                    "rationale": (
                                        "Official evidence is insufficient."
                                    ),
                                    "long_term_case": (
                                        "No long-term conclusion is supported."
                                    ),
                                    "risks": [
                                        "The evidence set is incomplete."
                                    ],
                                    "invalidation_conditions": [
                                        "New official evidence changes the "
                                        "assessment."
                                    ],
                                    "claim_ids": [],
                                    "source_ids": [],
                                    "calculation_ids": [],
                                    "confidence_pct": 0,
                                    "human_review_needed": True,
                                }
                            ],
                        }
                    )
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
                    "ticker_reviews": [
                        {
                            "ticker": ticker,
                            "verdict": "approve",
                            "downgrade_to": committee[
                                "portfolio_classification"
                            ],
                            "factual_grounding_pass": True,
                            "citation_integrity_pass": True,
                            "numeric_reconciliation_pass": True,
                            "long_term_reasoning_pass": True,
                            "action_proportionality_pass": True,
                            "policy_boundary_pass": True,
                            "issues": [],
                            "approved_source_ids": [source_id],
                        }
                    ],
                    "issues": [],
                    "approved_source_ids": [source_id],
                    "automatic_action_allowed": False,
                }
        if (
            self.semantic_invalid_first
            and not self.semantic_invalid_emitted
            and role == "analyst"
        ):
            payload["packet_id"] = "9" * 64
            self.semantic_invalid_emitted = True
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
            "successful_role_results_reused": True,
            "maximum_live_attempts_per_role": 2,
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
        self.runtime_packets = {
            self.prior.runtime_packet["packet_id"]: self.prior.runtime_packet,
            self.current.runtime_packet["packet_id"]: self.current.runtime_packet,
        }
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
        control_fingerprint = canonical_sha256(
            {
                "case_kind": "deterministic_no_change_control",
                "ticker": "TST",
                "prior_packet_id": self.prior.payload["packet_id"],
                "current_packet_id": self.prior.payload["packet_id"],
            }
        )
        negative_control = {
            "case_id": f"nochange:{control_fingerprint[:24]}",
            "case_kind": "deterministic_no_change_control",
            "ticker": "TST",
            "prior_packet_id": self.prior.payload["packet_id"],
            "current_packet_id": self.prior.payload["packet_id"],
            "transition_fingerprint": control_fingerprint,
            "human_label": None,
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
            negative_controls=[negative_control],
            annotation_metadata={
                "annotation_file_sha256": "f" * 64,
                "annotation_set_sha256": "0" * 64,
            },
            plan=ReplayPlan(
                packet_count=2,
                annotation_count=1,
            negative_control_count=1,
            adversarial_probe_count=1,
            critic_control_count=1,
            counterfactual_count=1,
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
        runtime_packet, _, _ = materialized("g01_stable_hold")
        runtime_packet = copy.deepcopy(runtime_packet)
        runtime_packet["decision_fingerprint"] = f"runner:{packet_id[:16]}"
        unsigned_runtime = copy.deepcopy(runtime_packet)
        unsigned_runtime.pop("packet_id", None)
        runtime_packet["packet_id"] = canonical_sha256(unsigned_runtime)
        source_id = runtime_packet["source_catalog"][0]["source_id"]
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
            runtime_packet=runtime_packet,
            evaluation_context=deterministic_replay_evaluation_context("TST"),
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
        provider: RecordingProvider | None,
        *,
        exact_calls: int = 13,
        maximum_new_calls: int = 13,
        global_physical_calls: int = 20,
        max_estimated_usd: Decimal = Decimal("1.00"),
        estimated_usd_per_call: Decimal = Decimal("0.01"),
        verifier: Any = None,
    ) -> dict[str, Any]:
        del verifier
        output = self.root / "collection"
        split = {
            "algorithm": "test_single_holdout_v1",
            "dev_case_ids": [],
            "holdout_case_ids": [self.case_id],
        }
        split["split_sha256"] = canonical_sha256(split)
        critic_control = {
            "control_id": "critic-control:faulty:test",
            "case_id": self.case_id,
            "packet_id": self.current.payload["packet_id"],
            "proposal_kind": "faulty",
        }
        with (
            patch(
                "run_phase5r_llm_provider_replay_evaluation.load_replay_inputs",
                return_value=self.inputs,
            ),
            patch(
                "run_phase5r_llm_provider_replay_evaluation."
                "frozen_transition_split",
                return_value=split,
            ),
            patch(
                "run_phase5r_llm_provider_replay_evaluation."
                "critic_control_cases",
                return_value=[critic_control],
            ),
            patch(
                "run_phase5r_llm_provider_replay_evaluation."
                "_validate_primary_response_semantics",
                return_value={},
            ),
            patch(
                "run_phase5r_llm_provider_replay_evaluation."
                "_runtime_committee_quality",
                return_value={"passed": True},
            ),
        ):
            result = execute_provider_replay(
                manifest_path=self.root / "manifest.json",
                annotation_path=self.root / "annotations.json",
                model_registry_path=self.root / "registry.json",
                output_root=output,
                acknowledge_external_inference=True,
                annotation_file_sha256="f" * 64,
                exact_maximum_calls=exact_calls,
                global_maximum_physical_calls=global_physical_calls,
                maximum_new_calls=maximum_new_calls,
                max_estimated_usd=max_estimated_usd,
                estimated_usd_per_call=estimated_usd_per_call,
                provider=provider,
                allow_test_provider=True,
                allow_test_path=True,
                minimum_packets=2,
                minimum_transitions=1,
                stability_transition_count=1,
                stability_trials_per_transition=2,
            )
        return result

    def test_fake_provider_exact_calls_roles_and_report_contract(self) -> None:
        provider = RecordingProvider(self.registry, self.runtime_packets)
        result = self._execute(provider)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "pending_human_review")
        self.assertEqual(result["provider_calls_this_invocation"], 13)
        roles = [role for role, _ in provider.calls]
        self.assertEqual(roles.count("analyst"), 2)
        self.assertEqual(roles.count("committee"), 2)
        self.assertEqual(roles.count("critic"), 2)
        self.assertEqual(roles.count("transition_pair"), 1)
        self.assertEqual(roles.count("negative_control"), 1)
        self.assertEqual(roles.count("adversarial_probe"), 1)
        self.assertEqual(roles.count("stability_transition_pair"), 2)
        self.assertEqual(roles.count("critic_control"), 1)
        self.assertEqual(roles.count("counterfactual_transition_pair"), 1)
        candidate = json.loads(
            (self.root / "collection" / "phase5r_llm_provider_replay_candidate.json")
            .read_text(encoding="utf-8")
        )
        base = candidate["base_report"]
        self.assertEqual(len(base["results"]), 6)
        self.assertEqual(len(base["transition_pair_results"]), 1)
        self.assertEqual(len(base["negative_control_results"]), 1)
        self.assertEqual(len(base["adversarial_probe_results"]), 1)
        self.assertEqual(len(base["stability_trials"]), 2)
        self.assertFalse(candidate["activation_eligible"])
        template = json.loads(
            (self.root / "collection" / "phase5r_llm_citation_review_template.json")
            .read_text(encoding="utf-8")
        )
        self.assertFalse(template["frozen"])
        self.assertIsNone(template["records"][0]["entailment_pass"])
        self.assertFalse(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_evaluation_report.json"
            ).exists()
        )

    def test_exact_call_budget_mismatch_fails_before_provider(self) -> None:
        provider = RecordingProvider(self.registry, self.runtime_packets)
        with self.assertRaisesRegex(ReplayRunError, "maximum-call"):
            self._execute(provider, exact_calls=12)
        self.assertEqual(provider.calls, [])
        self.assertFalse((self.root / "collection").exists())

    def test_collection_resumes_without_repeating_successful_calls(self) -> None:
        first = RecordingProvider(self.registry, self.runtime_packets)
        partial = self._execute(first, maximum_new_calls=3)
        self.assertEqual(partial["status"], "collection_in_progress")
        self.assertEqual(partial["completed_calls"], 3)
        self.assertEqual(len(first.calls), 3)

        second = RecordingProvider(self.registry, self.runtime_packets)
        completed = self._execute(second, maximum_new_calls=10)
        self.assertEqual(completed["status"], "pending_human_review")
        self.assertEqual(completed["completed_calls"], 13)
        self.assertEqual(len(second.calls), 10)
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(progress["successful_calls"]), 13)
        self.assertTrue(progress["complete"])

    def test_crash_after_response_write_recovers_without_provider_recall(
        self,
    ) -> None:
        first = RecordingProvider(self.registry, self.runtime_packets)
        original_save = CollectionCallStore._save
        injected = {"raised": False}

        def crash_before_success_state_save(
            store: CollectionCallStore,
        ) -> None:
            if (
                not injected["raised"]
                and store.progress["events"]
                and store.progress["events"][-1]["event_kind"] == "success"
            ):
                injected["raised"] = True
                raise RuntimeError("injected crash after response write")
            original_save(store)

        with patch.object(
            CollectionCallStore,
            "_save",
            crash_before_success_state_save,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                self._execute(first, maximum_new_calls=1)
        self.assertEqual(len(first.calls), 1)

        second = RecordingProvider(self.registry, self.runtime_packets)
        completed = self._execute(second, maximum_new_calls=12)
        self.assertEqual(completed["status"], "pending_human_review")
        self.assertEqual(len(second.calls), 12)
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        first_packet_id = sorted(self.inputs.corpus.packets)[0]
        first_call_id = f"primary:{first_packet_id}:analyst"
        first_call_events = [
            event
            for event in progress["events"]
            if event["provider_call_id"] == first_call_id
        ]
        self.assertEqual(
            [event["event_kind"] for event in first_call_events],
            ["attempt_started", "success"],
        )
        self.assertEqual(
            {event["attempt_number"] for event in first_call_events},
            {1},
        )

    def test_crash_after_receipt_link_recovers_without_provider_recall(
        self,
    ) -> None:
        first = RecordingProvider(self.registry, self.runtime_packets)
        actual_unlink = os.unlink
        injected = {"raised": False}

        def crash_before_publisher_temp_unlink(
            target: Any,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            name = os.fsdecode(target)
            if (
                not injected["raised"]
                and "-attempt-1.json.publish-" in name
            ):
                injected["raised"] = True
                raise RuntimeError(
                    "injected crash after receipt no-clobber link"
                )
            actual_unlink(target, *args, **kwargs)

        with patch(
            "run_phase5r_llm_provider_replay_evaluation.os.unlink",
            side_effect=crash_before_publisher_temp_unlink,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "after receipt no-clobber link",
            ):
                self._execute(first, maximum_new_calls=1)
        self.assertEqual(len(first.calls), 1)

        second = RecordingProvider(self.registry, self.runtime_packets)
        completed = self._execute(second, maximum_new_calls=12)
        self.assertEqual(completed["status"], "pending_human_review")
        self.assertEqual(len(second.calls), 12)
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        first_packet_id = sorted(self.inputs.corpus.packets)[0]
        first_call_id = f"primary:{first_packet_id}:analyst"
        self.assertEqual(
            progress["successful_calls"][first_call_id][
                "attempt_number"
            ],
            1,
        )

    def test_missing_receipt_marks_interrupted_then_retries_safely(
        self,
    ) -> None:
        first = RecordingProvider(self.registry, self.runtime_packets)
        with patch.object(
            CollectionCallStore,
            "persist_attempt_receipt",
            side_effect=RuntimeError("injected crash before receipt"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "before receipt",
            ):
                self._execute(first, maximum_new_calls=1)
        second = RecordingProvider(self.registry, self.runtime_packets)
        completed = self._execute(second, maximum_new_calls=13)
        self.assertEqual(completed["status"], "pending_human_review")
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        first_packet_id = sorted(self.inputs.corpus.packets)[0]
        first_call_id = f"primary:{first_packet_id}:analyst"
        first_events = [
            event
            for event in progress["events"]
            if event["provider_call_id"] == first_call_id
        ]
        self.assertEqual(
            [event["event_kind"] for event in first_events],
            [
                "attempt_started",
                "interrupted",
                "attempt_started",
                "success",
            ],
        )
        self.assertEqual(
            first_events[1]["outcome_category"],
            "process_interrupted",
        )
        self.assertTrue(first_events[1]["retryable"])

    def test_exclusive_publication_completes_short_writes(self) -> None:
        trusted = self.root / "exclusive-publication"
        trusted.mkdir(mode=0o700)
        artifact = trusted / "nested" / "artifact.json"
        payload = {"schema_version": "test_v1", "value": "x" * 1024}
        actual_write = os.write

        def short_write(descriptor: int, data: Any) -> int:
            view = memoryview(data)
            return actual_write(
                descriptor,
                view[: min(7, len(view))],
            )

        with patch(
            "run_phase5r_llm_provider_replay_evaluation.os.write",
            side_effect=short_write,
        ):
            claimed_sha = _write_json_exclusive(
                artifact,
                payload,
                trusted_root=trusted,
            )
        recovered, raw = _read_private_json(
            artifact,
            label="short-write test artifact",
            trusted_root=trusted,
        )
        self.assertEqual(recovered, payload)
        self.assertEqual(claimed_sha, hashlib.sha256(raw).hexdigest())

    def test_exclusive_publication_rejects_parent_symlink_escape(
        self,
    ) -> None:
        trusted = self.root / "trusted-publication"
        outside = self.root / "outside-publication"
        trusted.mkdir(mode=0o700)
        outside.mkdir(mode=0o700)
        (trusted / "responses").symlink_to(
            outside,
            target_is_directory=True,
        )
        with self.assertRaisesRegex(
            ReplayRunError,
            "parent must not be linked",
        ):
            _write_json_exclusive(
                trusted / "responses" / "primary" / "escaped.json",
                {"schema_version": "test_v1"},
                trusted_root=trusted,
            )
        self.assertEqual(list(outside.iterdir()), [])

    def test_completion_commit_crash_resumes_without_provider_recall(
        self,
    ) -> None:
        first = RecordingProvider(self.registry, self.runtime_packets)
        injected = {"raised": False}

        def crash_before_completion_commit(
            path: Path,
            payload: dict[str, Any],
        ) -> str:
            if (
                not injected["raised"]
                and path.name
                == "phase5r_llm_provider_replay_progress.json"
                and payload.get("complete") is True
            ):
                injected["raised"] = True
                raise RuntimeError("injected crash before completion commit")
            return _write_json_atomic(path, payload)

        with patch(
            "run_phase5r_llm_provider_replay_evaluation._write_json_atomic",
            side_effect=crash_before_completion_commit,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "before completion commit",
            ):
                self._execute(first)
        self.assertEqual(len(first.calls), 13)
        progress_path = (
            self.root
            / "collection"
            / "phase5r_llm_provider_replay_progress.json"
        )
        interrupted_progress = json.loads(
            progress_path.read_text(encoding="utf-8")
        )
        self.assertFalse(interrupted_progress["complete"])

        with patch(
            "run_phase5r_llm_provider_replay_evaluation."
            "_build_external_provider",
            side_effect=AssertionError(
                "external provider constructed during artifact recovery"
            ),
        ):
            completed = self._execute(None, maximum_new_calls=1)
        self.assertEqual(completed["status"], "pending_human_review")
        self.assertEqual(completed["provider_calls_this_invocation"], 0)
        committed_progress = json.loads(
            progress_path.read_text(encoding="utf-8")
        )
        self.assertTrue(committed_progress["complete"])
        self.assertTrue(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_collection_manifest.json"
            ).exists()
        )
        self.assertTrue(
            (
                self.root
                / "collection"
                / "phase5r_llm_citation_review_template.json"
            ).exists()
        )
        with patch(
            "run_phase5r_llm_provider_replay_evaluation."
            "_build_external_provider",
            side_effect=AssertionError(
                "external provider constructed for completed collection"
            ),
        ):
            resumed = self._execute(None, maximum_new_calls=1)
        self.assertEqual(resumed["status"], "pending_human_review")
        self.assertEqual(resumed["provider_calls_this_invocation"], 0)

    def test_semantic_invalid_response_is_terminal_and_not_retried(
        self,
    ) -> None:
        provider = RecordingProvider(
            self.registry,
            self.runtime_packets,
            semantic_invalid_first=True,
        )
        with self.assertRaisesRegex(Exception, "packet_id mismatch"):
            self._execute(provider, maximum_new_calls=1)
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(progress["successful_calls"], {})
        self.assertEqual(
            [event["event_kind"] for event in progress["events"]],
            ["attempt_started", "failure"],
        )

        with self.assertRaisesRegex(
            ReplayRunError,
            "terminal invalid evaluation response",
        ):
            self._execute(provider, maximum_new_calls=13)
        self.assertEqual(len(provider.calls), 1)
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            progress["events"][-1]["outcome_category"],
            "semantic_invalid",
        )
        receipt_path = next(
            (
                self.root / "collection" / "attempt_receipts"
            ).glob("*.json")
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertIsNone(receipt["payload"])
        self.assertFalse(receipt["retryable"])

    def test_insufficient_evidence_committee_must_abstain_before_cache(
        self,
    ) -> None:
        provider = RecordingProvider(
            self.registry,
            self.runtime_packets,
            insufficient_coverage=True,
        )
        with self.assertRaisesRegex(
            ReplayRunError,
            "must abstain when official evidence is insufficient",
        ):
            self._execute(provider, maximum_new_calls=2)
        self.assertEqual(
            [role for role, _ in provider.calls],
            ["analyst", "committee"],
        )
        progress_path = (
            self.root
            / "collection"
            / "phase5r_llm_provider_replay_progress.json"
        )
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        first_packet_id = sorted(self.inputs.corpus.packets)[0]
        analyst_call_id = f"primary:{first_packet_id}:analyst"
        committee_call_id = f"primary:{first_packet_id}:committee"
        self.assertIn(analyst_call_id, progress["successful_calls"])
        self.assertNotIn(committee_call_id, progress["successful_calls"])
        self.assertEqual(
            [
                event["event_kind"]
                for event in progress["events"]
                if event["provider_call_id"] == committee_call_id
            ],
            ["attempt_started", "failure"],
        )

        provider.abstain_committee = True
        with self.assertRaisesRegex(
            ReplayRunError,
            "terminal invalid evaluation response",
        ):
            self._execute(provider, maximum_new_calls=1)
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertNotIn(committee_call_id, progress["successful_calls"])
        self.assertEqual(
            [
                event["event_kind"]
                for event in progress["events"]
                if event["provider_call_id"] == committee_call_id
            ],
            [
                "attempt_started",
                "failure",
            ],
        )
        self.assertEqual(
            progress["events"][-1]["safe_outcome"],
            "policy_invalid",
        )
        self.assertNotIn(
            "injected provider failure",
            json.dumps(progress),
        )

    def test_transport_failure_retries_once_and_is_physically_counted(
        self,
    ) -> None:
        first = RecordingProvider(
            self.registry,
            self.runtime_packets,
            transport_fail_at=1,
        )
        with self.assertRaisesRegex(ProviderError, "timed out"):
            self._execute(first, maximum_new_calls=1)
        progress_path = (
            self.root
            / "collection"
            / "phase5r_llm_provider_replay_progress.json"
        )
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [event["event_kind"] for event in progress["events"]],
            ["attempt_started", "failure"],
        )
        self.assertTrue(progress["events"][-1]["retryable"])
        self.assertEqual(
            progress["events"][-1]["outcome_category"],
            "transport_timeout",
        )

        second = RecordingProvider(self.registry, self.runtime_packets)
        completed = self._execute(second, maximum_new_calls=13)
        self.assertEqual(completed["status"], "pending_human_review")
        self.assertEqual(len(second.calls), 13)
        ledger = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_execution_ledger.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            ledger["budget"]["logical_successful_call_count"],
            13,
        )
        self.assertEqual(ledger["budget"]["physical_attempt_count"], 14)
        self.assertEqual(
            ledger["attempt_metrics"][
                "retryable_transport_or_process_failure_count"
            ],
            1,
        )
        self.assertEqual(
            ledger["attempt_metrics"][
                "first_attempt_valid_logical_call_count"
            ],
            12,
        )
        self.assertEqual(
            ledger["attempt_metrics"]["invalid_attempt_count"],
            0,
        )

    def test_resume_cannot_reset_frozen_global_physical_ceiling(
        self,
    ) -> None:
        first = RecordingProvider(
            self.registry,
            self.runtime_packets,
            transport_fail_at=1,
        )
        with self.assertRaisesRegex(ProviderError, "timed out"):
            self._execute(
                first,
                maximum_new_calls=1,
                global_physical_calls=14,
            )
        second = RecordingProvider(self.registry, self.runtime_packets)
        with self.assertRaisesRegex(
            ReplayRunError,
            "frozen global budget changed",
        ):
            self._execute(
                second,
                maximum_new_calls=13,
                global_physical_calls=20,
            )
        self.assertEqual(second.calls, [])
        completed = self._execute(
            second,
            maximum_new_calls=13,
            global_physical_calls=14,
        )
        self.assertEqual(completed["status"], "pending_human_review")
        self.assertEqual(
            completed["cumulative_physical_provider_calls"],
            14,
        )

    def test_transport_retries_are_bounded_by_physical_attempts(
        self,
    ) -> None:
        providers: list[RecordingProvider] = []
        for _ in range(3):
            provider = RecordingProvider(
                self.registry,
                self.runtime_packets,
                transport_fail_at=1,
            )
            providers.append(provider)
            with self.assertRaisesRegex(ProviderError, "timed out"):
                self._execute(provider, maximum_new_calls=1)
        blocked = RecordingProvider(self.registry, self.runtime_packets)
        with self.assertRaisesRegex(
            ReplayRunError,
            "exhausted bounded transport retries",
        ):
            self._execute(blocked, maximum_new_calls=1)
        self.assertEqual(blocked.calls, [])
        with patch(
            "run_phase5r_llm_provider_replay_evaluation.load_replay_inputs",
            return_value=self.inputs,
        ):
            readiness = check_replay_readiness(
                manifest_path=self.root / "manifest.json",
                annotation_path=self.root / "annotations.json",
                model_registry_path=self.root / "registry.json",
                collection_root=self.root / "collection",
                allow_test_path=True,
            )
        self.assertFalse(readiness["ready"])
        self.assertIn(
            "exhausted bounded transport retries",
            readiness["issues"][0],
        )
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            sum(
                event["event_kind"] == "attempt_started"
                for event in progress["events"]
            ),
            3,
        )

    def test_max_attempt_success_receipt_recovers_before_exhaustion_check(
        self,
    ) -> None:
        for _ in range(2):
            provider = RecordingProvider(
                self.registry,
                self.runtime_packets,
                transport_fail_at=1,
            )
            with self.assertRaisesRegex(ProviderError, "timed out"):
                self._execute(provider, maximum_new_calls=1)

        third = RecordingProvider(self.registry, self.runtime_packets)
        with patch.object(
            CollectionCallStore,
            "persist_success",
            side_effect=RuntimeError(
                "injected crash after max-attempt receipt"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "after max-attempt receipt",
            ):
                self._execute(third, maximum_new_calls=1)
        self.assertEqual(len(third.calls), 1)

        resumed = RecordingProvider(self.registry, self.runtime_packets)
        completed = self._execute(resumed, maximum_new_calls=12)
        self.assertEqual(completed["status"], "pending_human_review")
        self.assertEqual(len(resumed.calls), 12)
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        first_packet_id = sorted(self.inputs.corpus.packets)[0]
        first_call_id = f"primary:{first_packet_id}:analyst"
        first_events = [
            event
            for event in progress["events"]
            if event["provider_call_id"] == first_call_id
        ]
        self.assertEqual(
            [event["event_kind"] for event in first_events],
            [
                "attempt_started",
                "failure",
                "attempt_started",
                "failure",
                "attempt_started",
                "success",
            ],
        )
        self.assertEqual(
            progress["successful_calls"][first_call_id]["attempt_number"],
            3,
        )

    def test_max_attempt_without_receipt_becomes_interrupted_not_fourth_call(
        self,
    ) -> None:
        for _ in range(2):
            provider = RecordingProvider(
                self.registry,
                self.runtime_packets,
                transport_fail_at=1,
            )
            with self.assertRaisesRegex(ProviderError, "timed out"):
                self._execute(provider, maximum_new_calls=1)

        third = RecordingProvider(self.registry, self.runtime_packets)
        with patch.object(
            CollectionCallStore,
            "persist_attempt_receipt",
            side_effect=RuntimeError(
                "injected crash before max-attempt receipt"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "before max-attempt receipt",
            ):
                self._execute(third, maximum_new_calls=1)
        self.assertEqual(len(third.calls), 1)

        blocked = RecordingProvider(self.registry, self.runtime_packets)
        with self.assertRaisesRegex(
            ReplayRunError,
            "bounded retry limit",
        ):
            self._execute(blocked, maximum_new_calls=1)
        self.assertEqual(blocked.calls, [])
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        first_packet_id = sorted(self.inputs.corpus.packets)[0]
        first_call_id = f"primary:{first_packet_id}:analyst"
        first_events = [
            event
            for event in progress["events"]
            if event["provider_call_id"] == first_call_id
        ]
        self.assertEqual(
            [event["event_kind"] for event in first_events],
            [
                "attempt_started",
                "failure",
                "attempt_started",
                "failure",
                "attempt_started",
                "interrupted",
            ],
        )
        self.assertEqual(
            first_events[-1]["outcome_category"],
            "process_interrupted",
        )
        self.assertTrue(first_events[-1]["retryable"])
        self.assertEqual(
            sum(
                event["event_kind"] == "attempt_started"
                for event in first_events
            ),
            3,
        )

    def test_resume_cannot_reset_frozen_operator_cost_policy(
        self,
    ) -> None:
        first = RecordingProvider(self.registry, self.runtime_packets)
        partial = self._execute(first, maximum_new_calls=1)
        self.assertEqual(partial["status"], "collection_in_progress")
        second = RecordingProvider(self.registry, self.runtime_packets)
        with self.assertRaisesRegex(
            ReplayRunError,
            "frozen global budget changed",
        ):
            self._execute(
                second,
                maximum_new_calls=12,
                max_estimated_usd=Decimal("2.00"),
            )
        self.assertEqual(second.calls, [])

    def test_provider_free_finalize_uses_exact_frozen_reviews(self) -> None:
        provider = RecordingProvider(self.registry, self.runtime_packets)
        collected = self._execute(provider)
        template_path = Path(collected["citation_review_template"])
        review = json.loads(template_path.read_text(encoding="utf-8"))
        record = review["records"][0]
        rationale_a = (
            "The cited official excerpt directly entails the material claim."
        )
        rationale_b = (
            "Independent inspection confirms the claim is supported by the "
            "identified filing excerpt."
        )
        record["reviewed_source_ids"] = list(record["cited_source_ids"])
        record["entailment_pass"] = True
        record["reviewers"] = [
            {
                "reviewer_id_sha256": "1" * 64,
                "reviewer_kind": "human",
                "entailed": True,
                "rationale": rationale_a,
                "rationale_sha256": hashlib.sha256(
                    rationale_a.encode("utf-8")
                ).hexdigest(),
            },
            {
                "reviewer_id_sha256": "2" * 64,
                "reviewer_kind": "human",
                "entailed": True,
                "rationale": rationale_b,
                "rationale_sha256": hashlib.sha256(
                    rationale_b.encode("utf-8")
                ).hexdigest(),
            },
        ]
        unsigned_record = dict(record)
        unsigned_record.pop("review_sha256")
        record["review_sha256"] = canonical_sha256(unsigned_record)
        review["frozen"] = True
        unsigned_review = dict(review)
        unsigned_review.pop("review_set_sha256")
        review["review_set_sha256"] = canonical_sha256(unsigned_review)
        review_path = self.root / "completed-reviews.json"
        review_path.write_text(
            json.dumps(review, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        review_path.chmod(0o400)
        review_file_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()
        captured: dict[str, Any] = {}

        def accepting_verifier(**kwargs: Any) -> dict[str, Any]:
            captured["report"] = json.loads(
                Path(kwargs["provider_report_path"]).read_text(
                    encoding="utf-8"
                )
            )
            return {"passed": True, "issues": []}

        with patch(
            "run_phase5r_llm_provider_replay_evaluation.load_replay_inputs",
            return_value=self.inputs,
        ):
            result = finalize_provider_replay(
                collection_root=self.root / "collection",
                citation_review_path=review_path,
                citation_review_file_sha256=review_file_sha,
                manifest_path=self.root / "manifest.json",
                annotation_path=self.root / "annotations.json",
                model_registry_path=self.root / "registry.json",
                output_root=self.root / "final",
                allow_test_path=True,
                minimum_packets=2,
                minimum_transitions=1,
                stability_transition_count=1,
                stability_trials_per_transition=2,
                verifier=accepting_verifier,
            )
        self.assertTrue(result["passed"])
        self.assertEqual(result["provider_calls_this_invocation"], 0)
        self.assertEqual(len(provider.calls), 13)
        self.assertEqual(
            FINAL_CITATION_REVIEW_NAME,
            CITATION_REVIEW_SET_PATH.name,
        )
        self.assertTrue(
            (self.root / "final" / CITATION_REVIEW_SET_PATH.name).exists()
        )
        self.assertTrue(
            (
                self.root
                / "final"
                / "phase5r_llm_provider_replay_execution_ledger.json"
            ).exists()
        )
        self.assertTrue(
            (
                self.root
                / "final"
                / "phase5r_llm_provider_replay_progress.json"
            ).exists()
        )
        self.assertEqual(
            len(
                list(
                    (
                        self.root / "final" / "attempt_receipts"
                    ).glob("*.json")
                )
            ),
            13,
        )
        report = captured["report"]
        self.assertEqual(
            report["extended_quality"]["citation_entailment_reviews"],
            review["records"],
        )
        self.assertEqual(report["summary"]["total_provider_call_count"], 13)

    def test_provider_failure_is_auditable_and_writes_no_report(self) -> None:
        provider = RecordingProvider(
            self.registry,
            self.runtime_packets,
            fail_at=3,
        )
        with self.assertRaises(ProviderError):
            self._execute(provider)
        progress = json.loads(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_progress.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [event["event_kind"] for event in progress["events"]],
            [
                "attempt_started",
                "success",
                "attempt_started",
                "success",
                "attempt_started",
                "failure",
            ],
        )
        self.assertFalse(
            (
                self.root
                / "collection"
                / "phase5r_llm_provider_replay_evaluation_report.json"
            ).exists()
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
            maximum_new_calls=11,
            global_maximum_physical_calls=11,
            max_estimated_usd=Decimal("0.10"),
            estimated_usd_per_call=Decimal("0.01"),
            cumulative_physical_calls_before=0,
        )
        with self.assertRaisesRegex(ReplayRunError, "USD ceiling"):
            budget.validate()
        self.assertEqual(budget.used_calls, 0)


if __name__ == "__main__":
    unittest.main()
