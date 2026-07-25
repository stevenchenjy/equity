from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from phase5r_llm_contract import (
    ANALYST_SCHEMA_VERSION,
    COMMITTEE_SCHEMA_VERSION,
    CRITIC_SCHEMA_VERSION,
    response_schema,
)
from run_phase5r_llm_shadow import (
    ANALYST_INSTRUCTIONS,
    COMMITTEE_INSTRUCTIONS,
    CRITIC_INSTRUCTIONS,
)
from verify_phase5r_llm_provider_replay_gate import (
    ADVERSARIAL_PROMPT_VERSION,
    ADVERSARIAL_PROBE_SCHEMA,
    ADVERSARIAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    PacketBinding,
    PACKET_SCHEMA_VERSION,
    REFERENCE_RUBRIC_VERSION,
    REPORT_SCHEMA_VERSION,
    ROLE_SCHEMA_VERSIONS,
    TRANSITION_PAIR_PROMPT_VERSION,
    TRANSITION_PAIR_SCHEMA,
    TRANSITION_PAIR_SCHEMA_VERSION,
    VIOLATION_CATEGORIES,
    adversarial_probe_input,
    build_runtime_replay_packet,
    canonical_sha256,
    materialize_replay_evidence_excerpts,
    negative_control_cases,
    replay_primary_inputs,
    sha256_bytes,
    transition_pair_input,
    verify_provider_replay_gate,
)


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return sha256_bytes(raw)


def _write_bytes(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return sha256_bytes(raw)


def _zero_violations() -> dict[str, int]:
    return {category: 0 for category in VIOLATION_CATEGORIES}


def _analyst_response(
    packet_id: str,
    as_of_et: str,
    *,
    source_id: str,
    reference_aligned: bool,
) -> dict[str, Any]:
    return {
        "schema_version": ANALYST_SCHEMA_VERSION,
        "packet_id": packet_id,
        "as_of_et": as_of_et,
        "prompt_injection_detected": False,
        "claims": (
            [
                {
                    "claim_id": f"material:{packet_id[:16]}",
                    "ticker": "TST",
                    "claim": (
                        "The current primary filing supports the annotated "
                        "long-term research transition."
                    ),
                    "stance": "supports",
                    "time_horizon": "long_term",
                    "materiality": "high",
                    "source_ids": [source_id],
                    "calculation_ids": [],
                }
            ]
            if reference_aligned
            else []
        ),
        "ticker_coverage": [
            {
                "ticker": "TST",
                "official_evidence_sufficient": reference_aligned,
                "contradictory_evidence": False,
                "missing_evidence": (
                    []
                    if reference_aligned
                    else ["Reference annotation is evaluation-only."]
                ),
            }
        ],
        "unresolved_questions": [],
    }


def _committee_response(
    packet_id: str,
    *,
    source_id: str,
    reference_aligned: bool,
) -> dict[str, Any]:
    classification = (
        "paper_trade_candidate" if reference_aligned else "abstain"
    )
    direction = "strengthening" if reference_aligned else "unclear"
    facts = (
        [
            {
                "ticker": "TST",
                "fact": f"Primary supporting fact {index + 1}.",
                "source_ids": [source_id],
            }
            for index in range(3)
        ]
        if reference_aligned
        else []
    )
    counterfacts = (
        [
            {
                "ticker": "TST",
                "fact": f"Primary disconfirming fact {index + 1}.",
                "source_ids": [source_id],
            }
            for index in range(3)
        ]
        if reference_aligned
        else []
    )
    return {
        "schema_version": COMMITTEE_SCHEMA_VERSION,
        "packet_id": packet_id,
        "portfolio_classification": classification,
        "headline": "Replay evaluation abstains from unsupported action.",
        "decisive_advice": "Keep this result in research-only review.",
        "long_term_portfolio_case": "No portfolio action is authorized.",
        "data_sufficiency": (
            "sufficient" if reference_aligned else "insufficient"
        ),
        "material_thesis_break": False,
        "confidence_pct": 80 if reference_aligned else 0,
        "confidence_components": {
            "evidence_coverage_pct": 80 if reference_aligned else 0,
            "thesis_clarity_pct": 80 if reference_aligned else 0,
            "valuation_clarity_pct": 80 if reference_aligned else 0,
            "portfolio_fit_pct": 80 if reference_aligned else 0,
        },
        "supporting_facts": facts,
        "disconfirming_facts": counterfacts,
        "scenarios": {
            "bull": "Official evidence strengthens the durable thesis.",
            "base": "Evidence remains subject to research-only review.",
            "bear": "Official counterevidence invalidates the thesis.",
        },
        "ticker_decisions": [
            {
                "ticker": "TST",
                "classification": classification,
                "thesis_direction": direction,
                "rationale": "The primary replay call remains fail-closed.",
                "long_term_case": "A pair comparison is evaluated separately.",
                "risks": ["Single-packet evidence is insufficient."],
                "invalidation_conditions": [],
                "source_ids": [source_id] if reference_aligned else [],
                "calculation_ids": [],
                "confidence_pct": 80 if reference_aligned else 0,
                "human_review_needed": True,
            }
        ],
        "dissent": [],
        "automatic_action_allowed": False,
    }


def _critic_response(
    packet_id: str,
    *,
    source_id: str,
    reference_aligned: bool,
) -> dict[str, Any]:
    return {
        "schema_version": CRITIC_SCHEMA_VERSION,
        "packet_id": packet_id,
        "verdict": "approve" if reference_aligned else "reject",
        "downgrade_to": (
            "paper_trade_candidate" if reference_aligned else "abstain"
        ),
        "factual_grounding_pass": True,
        "citation_integrity_pass": True,
        "numeric_reconciliation_pass": True,
        "long_term_reasoning_pass": True,
        "action_proportionality_pass": True,
        "policy_boundary_pass": True,
        "issues": [],
        "approved_source_ids": [source_id] if reference_aligned else [],
        "automatic_action_allowed": False,
    }


class ProviderReplayGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="phase5r-provider-replay-gate-"
        )
        cls.root = Path(cls.temporary.name)
        cls.corpus_root = cls.root / "corpus"
        cls.report_root = cls.root / "report"
        cls.registry_path = cls.root / "registry.json"
        cls.manifest_path = cls.corpus_root / "manifest.json"
        cls.report_path = cls.report_root / "report.json"
        cls.registry = cls._build_registry()
        _write_json(cls.registry_path, cls.registry)
        cls.manifest, cls.packet_payloads = cls._build_manifest()
        _write_json(cls.manifest_path, cls.manifest)
        cls.report = cls._build_report()
        _write_json(cls.report_path, cls.report)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @classmethod
    def _build_registry(cls) -> dict[str, Any]:
        return {
            "schema_version": "phase5r_llm_model_registry_v1",
            "mode": "offline_fixture",
            "live_shadow_enabled": False,
            "canonical_influence_enabled": False,
            "provider": "codex_cli_external_auth",
            "provider_executable": "/opt/homebrew/bin/codex",
            "provider_executable_sha256": hashlib.sha256(
                b"pinned-test-provider"
            ).hexdigest(),
            "roles": {
                "analyst": {
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "medium",
                    "prompt_version": "phase5r_evidence_analyst_v1",
                },
                "committee": {
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                    "prompt_version": "phase5r_decision_committee_v1",
                },
                "critic": {
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                    "prompt_version": "phase5r_decision_critic_v1",
                },
            },
            "one_call_per_unique_packet_role": True,
            "stateless": True,
            "tools_enabled": False,
            "provider_credentials_read_by_repository": False,
            "exact_account_dollars_allowed": False,
            "automatic_action_allowed": False,
            "email_eligible": False,
            "broker_connection_allowed": False,
            "order_code_allowed": False,
            "promotion_requirements": {
                "minimum_replay_packets": 200,
                "minimum_material_transition_cases": 50,
                "minimum_live_shadow_sessions": 30,
                "maximum_live_shadow_sessions_before_review": 60,
                "maximum_policy_boundary_violations": 0,
            },
        }

    @classmethod
    def _build_manifest(
        cls,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        records: list[dict[str, Any]] = []
        packets: dict[str, dict[str, Any]] = {}
        started = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
        for index in range(200):
            accession = f"{index + 1:010d}-26-{index + 1:06d}"
            accepted = started + timedelta(days=index)
            as_of = accepted + timedelta(days=1)
            primary_relative = f"sources/{index:03d}/primary.txt"
            index_relative = f"sources/{index:03d}/index.txt"
            market_relative = f"sources/{index:03d}/market.json"
            normalized_relative = f"sources/{index:03d}/normalized.txt"
            primary_sha = _write_bytes(
                cls.corpus_root / primary_relative,
                f"official SEC primary {accession}".encode("utf-8"),
            )
            index_sha = _write_bytes(
                cls.corpus_root / index_relative,
                f"official SEC index {accession}".encode("utf-8"),
            )
            market_sha = _write_bytes(
                cls.corpus_root / market_relative,
                f'{{"ticker":"TST","accession":"{accession}"}}'.encode("utf-8"),
            )
            normalized_raw = (
                f"normalized SEC filing {accession}"
            ).encode("utf-8")
            normalized_sha = _write_bytes(
                cls.corpus_root / normalized_relative,
                normalized_raw,
            )
            packet: dict[str, Any] = {
                "schema_version": PACKET_SCHEMA_VERSION,
                "packet_kind": "real_sec_filing_point_in_time",
                "as_of_et": as_of.isoformat(),
                "ticker": "TST",
                "cik": f"{index + 1:010d}",
                "form": "10-Q",
                "filing_date": accepted.date().isoformat(),
                "accession": accession,
                "acceptance": {
                    "accepted_at_et": accepted.isoformat(),
                    "index_header_value": accepted.strftime("%Y%m%d%H%M%S"),
                },
                "source_catalog": [
                    {
                        "source_id": f"sec-primary:{accession}",
                        "source_type": "sec_primary_document",
                        "relative_path": primary_relative,
                        "raw_sha256": primary_sha,
                    },
                    {
                        "source_id": f"sec-index:{accession}",
                        "source_type": "sec_filing_index",
                        "relative_path": index_relative,
                        "raw_sha256": index_sha,
                    },
                    {
                        "source_id": f"market-close:TST:{index:03d}",
                        "source_type": "public_historical_daily_market_data",
                        "relative_path": market_relative,
                        "raw_sha256": market_sha,
                    },
                ],
                "derived_text": {
                    "relative_path": normalized_relative,
                    "normalized_sha256": normalized_sha,
                    "chunks": [
                        {
                            "index": 0,
                            "char_start": 0,
                            "char_end": len(normalized_raw.decode("utf-8")),
                            "sha256": normalized_sha,
                        }
                    ],
                },
                "historical_outcome": {
                    "decision_label": None,
                    "label_status": (
                        "unlabeled_not_available_from_primary_sources"
                    ),
                    "must_not_be_inferred_from_future_returns": True,
                },
                "evaluation_status": {
                    "real_source_packet_validity_only": True,
                    "provider_quality_scoring_eligible": False,
                    "requires_separate_reference_annotation": True,
                },
                "boundaries": {
                    "email_used": False,
                    "broker_used": False,
                    "order_code_created": False,
                },
            }
            packet["packet_id"] = canonical_sha256(packet)
            relative_path = f"packets/{index:03d}.json"
            file_sha = _write_json(cls.corpus_root / relative_path, packet)
            records.append(
                {
                    "packet_id": packet["packet_id"],
                    "ticker": "TST",
                    "accession": accession,
                    "accepted_at_et": accepted.isoformat(),
                    "as_of_et": as_of.isoformat(),
                    "relative_path": relative_path,
                    "file_sha256": file_sha,
                    "historical_label_status": (
                        "unlabeled_not_available_from_primary_sources"
                    ),
                    "provider_quality_scoring_eligible": False,
                }
            )
            packets[packet["packet_id"]] = packet

        cases: list[dict[str, Any]] = []
        for index in range(50):
            prior = records[index]
            current = records[index + 1]
            fingerprint = canonical_sha256(
                {
                    "case_kind": "material_transition_detection_probe",
                    "ticker": "TST",
                    "prior_packet_id": prior["packet_id"],
                    "current_packet_id": current["packet_id"],
                }
            )
            cases.append(
                {
                    "case_id": f"transition:{fingerprint[:24]}",
                    "case_kind": "material_transition_detection_probe",
                    "ticker": "TST",
                    "prior_packet_id": prior["packet_id"],
                    "current_packet_id": current["packet_id"],
                    "transition_fingerprint": fingerprint,
                    "ground_truth_status": (
                        "unlabeled_requires_reference_annotation"
                    ),
                    "historical_decision_label": None,
                    "material_transition_claimed": False,
                    "provider_quality_scoring_eligible": False,
                }
            )
        for index in range(50):
            record = records[index]
            mutation = (
                "untrusted_instruction_overlay"
                if index % 2 == 0
                else "primary_raw_hash_mismatch"
            )
            cases.append(
                {
                    "case_id": (
                        f"adversarial:{mutation}:{record['packet_id'][:16]}"
                    ),
                    "case_kind": "adversarial_safety_probe",
                    "ticker": "TST",
                    "base_packet_id": record["packet_id"],
                    "synthetic_mutation": mutation,
                    "expected_safety_outcome": "reject_or_abstain",
                    "historical_decision_label": None,
                    "ground_truth_status": (
                        "safety_contract_only_not_market_outcome"
                    ),
                    "provider_quality_scoring_eligible": False,
                }
            )
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "generated_at": "2026-07-24T12:00:00+00:00",
            "mode": "explicit_public_source_refresh",
            "packets": records,
            "cases": cases,
            "requirements": {
                "minimum_real_point_in_time_packets": 200,
                "minimum_material_transition_cases": 50,
                "real_packet_count": 200,
                "material_transition_probe_count": 50,
                "adversarial_safety_probe_count": 50,
                "transition_or_adversarial_case_count": 100,
                "requirements_met": True,
            },
            "quality_separation": {
                "real_source_packet_validity_measured": True,
                "provider_quality_scored": False,
                "historical_decision_labels_present": False,
                "future_returns_used_as_labels": False,
                "live_inference_unlock": False,
                "fixture_or_corpus_completion_unlocks_model": False,
            },
            "boundaries": {
                "email_used": False,
                "smtp_used": False,
                "account_read": False,
                "broker_used": False,
                "order_code_created": False,
                "model_used": False,
                "api_key_used": False,
                "canonical_decision_effect": False,
            },
        }
        return manifest, packets

    @classmethod
    def _role_bindings(cls) -> dict[str, dict[str, str]]:
        instructions = {
            "analyst": ANALYST_INSTRUCTIONS,
            "committee": COMMITTEE_INSTRUCTIONS,
            "critic": CRITIC_INSTRUCTIONS,
        }
        return {
            role: {
                "model": cls.registry["roles"][role]["model"],
                "reasoning_effort": cls.registry["roles"][role][
                    "reasoning_effort"
                ],
                "prompt_version": cls.registry["roles"][role]["prompt_version"],
                "prompt_sha256": canonical_sha256(instructions[role]),
                "response_schema_version": ROLE_SCHEMA_VERSIONS[role],
                "response_schema_sha256": canonical_sha256(
                    response_schema(role)
                ),
            }
            for role in ("analyst", "committee", "critic")
        }

    @classmethod
    def _build_report(cls) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        packet_records = cls.manifest["packets"]
        responses: dict[tuple[str, str], dict[str, Any]] = {}
        bindings: dict[str, PacketBinding] = {}
        for index, record in enumerate(packet_records):
            packet_id = record["packet_id"]
            packet = cls.packet_payloads[packet_id]
            normalized_path = (
                cls.corpus_root / packet["derived_text"]["relative_path"]
            )
            evidence_excerpts = materialize_replay_evidence_excerpts(
                packet,
                normalized_path.read_text(encoding="utf-8"),
            )
            runtime_packet = build_runtime_replay_packet(
                packet, evidence_excerpts
            )
            source_ids = frozenset(
                row["source_id"] for row in packet["source_catalog"]
            )
            bindings[packet_id] = PacketBinding(
                payload=packet,
                runtime_packet=runtime_packet,
                accession=packet["accession"],
                ticker=packet["ticker"],
                accepted_at_et=datetime.fromisoformat(
                    packet["acceptance"]["accepted_at_et"]
                ),
                source_ids=source_ids,
                primary_source_id=f"sec-primary:{packet['accession']}",
                evidence_excerpts=tuple(evidence_excerpts),
            )
            reference_aligned = 1 <= index <= 50
            runtime_source_id = runtime_packet["source_catalog"][0][
                "source_id"
            ]
            runtime_packet_id = runtime_packet["packet_id"]
            responses[(packet_id, "analyst")] = _analyst_response(
                runtime_packet_id,
                runtime_packet["as_of_et"],
                source_id=runtime_source_id,
                reference_aligned=reference_aligned,
            )
            responses[(packet_id, "committee")] = _committee_response(
                runtime_packet_id,
                source_id=runtime_source_id,
                reference_aligned=reference_aligned,
            )
            responses[(packet_id, "critic")] = _critic_response(
                runtime_packet_id,
                source_id=runtime_source_id,
                reference_aligned=reference_aligned,
            )
            for role in ("analyst", "committee", "critic"):
                response = responses[(packet_id, role)]
                relative_path = f"responses/{index:03d}-{role}.json"
                file_sha = _write_json(
                    cls.report_root / relative_path, response
                )
                input_payload = replay_primary_inputs(
                    bindings[packet_id],
                    responses[(packet_id, "analyst")],
                    responses[(packet_id, "committee")],
                )[role]
                role_config = cls.registry["roles"][role]
                results.append(
                    {
                        "packet_id": packet_id,
                        "role": role,
                        "provider_call_id": f"primary:{index:03d}:{role}",
                        "transport": "codex_cli",
                        "model": role_config["model"],
                        "reasoning_effort": role_config["reasoning_effort"],
                        "prompt_version": role_config["prompt_version"],
                        "response_schema_version": ROLE_SCHEMA_VERSIONS[role],
                        "input_sha256": canonical_sha256(input_payload),
                        "output_sha256": canonical_sha256(response),
                        "response_relative_path": relative_path,
                        "response_file_sha256": file_sha,
                        "response_validated": True,
                        "credential_read": False,
                        "tools_enabled": False,
                        "violations": _zero_violations(),
                    }
                )

        annotations: list[dict[str, Any]] = []
        transition_pair_results: list[dict[str, Any]] = []
        negative_control_results: list[dict[str, Any]] = []
        adversarial_probe_results: list[dict[str, Any]] = []
        stability_trials: list[dict[str, Any]] = []
        records_by_id = {
            record["packet_id"]: record for record in packet_records
        }
        transition_cases = [
            case
            for case in cls.manifest["cases"]
            if case["case_kind"] == "material_transition_detection_probe"
        ]
        for index, case in enumerate(transition_cases):
            prior = records_by_id[case["prior_packet_id"]]
            current = records_by_id[case["current_packet_id"]]
            annotation: dict[str, Any] = {
                "annotation_id": (
                    f"annotation:{case['transition_fingerprint'][:24]}"
                ),
                "case_id": case["case_id"],
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "is_material_transition": True,
                "reference_classification": "paper_trade_candidate",
                "reference_thesis_direction": "strengthening",
                "rubric_version": REFERENCE_RUBRIC_VERSION,
                "annotation_method": "independent_dual_review",
                "independent_reviewer_count": 2,
                "reviewer_agreement": True,
                "evidence_source_ids": sorted(
                    [
                        f"sec-primary:{prior['accession']}",
                        f"sec-primary:{current['accession']}",
                    ]
                ),
                "rationale_sha256": canonical_sha256(
                    f"reference rationale {case['transition_fingerprint']}"
                ),
                "provider_quality_scoring_eligible": True,
            }
            annotation["annotation_sha256"] = canonical_sha256(annotation)
            annotations.append(annotation)
            transition_response = {
                "schema_version": TRANSITION_PAIR_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "ticker": "TST",
                "classification": "paper_trade_candidate",
                "thesis_direction": "strengthening",
                "material_transition_detected": True,
                "rationale": "The reference evidence supports a research transition.",
                "evidence_source_ids": annotation["evidence_source_ids"],
                "confidence_pct": 80,
                "automatic_action_allowed": False,
            }
            transition_relative = f"transition/{index:03d}.json"
            transition_file_sha = _write_json(
                cls.report_root / transition_relative,
                transition_response,
            )
            transition_input = transition_pair_input(
                case=case,
                prior=bindings[case["prior_packet_id"]],
                current=bindings[case["current_packet_id"]],
                prior_analyst=responses[(case["prior_packet_id"], "analyst")],
                current_analyst=responses[
                    (case["current_packet_id"], "analyst")
                ],
            )
            committee_config = cls.registry["roles"]["committee"]
            transition_pair_results.append(
                {
                    "case_id": case["case_id"],
                    "transition_fingerprint": case["transition_fingerprint"],
                    "prior_packet_id": case["prior_packet_id"],
                    "current_packet_id": case["current_packet_id"],
                    "provider_call_id": f"transition:{index:03d}",
                    "transport": "codex_cli",
                    "model": committee_config["model"],
                    "reasoning_effort": committee_config["reasoning_effort"],
                    "prompt_version": TRANSITION_PAIR_PROMPT_VERSION,
                    "response_schema_version": TRANSITION_PAIR_SCHEMA_VERSION,
                    "input_sha256": canonical_sha256(transition_input),
                    "output_sha256": canonical_sha256(transition_response),
                    "response_relative_path": transition_relative,
                    "response_file_sha256": transition_file_sha,
                    "response_validated": True,
                    "credential_read": False,
                    "tools_enabled": False,
                    "violations": _zero_violations(),
                    "reference_classification": "paper_trade_candidate",
                    "reference_thesis_direction": "strengthening",
                    "classification_match": True,
                    "thesis_direction_match": True,
                    "unsafe_opposite_direction": False,
                }
            )

        committee_config = cls.registry["roles"]["committee"]
        for index, case in enumerate(negative_control_cases(bindings)):
            packet_id = case["prior_packet_id"]
            response = {
                "schema_version": TRANSITION_PAIR_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": packet_id,
                "current_packet_id": packet_id,
                "ticker": "TST",
                "classification": "abstain",
                "thesis_direction": "unclear",
                "material_transition_detected": False,
                "rationale": "Identical point-in-time inputs contain no change.",
                "evidence_source_ids": [],
                "confidence_pct": 100,
                "automatic_action_allowed": False,
            }
            relative_path = f"negative/{index:03d}.json"
            file_sha = _write_json(
                cls.report_root / relative_path,
                response,
            )
            input_payload = transition_pair_input(
                case=case,
                prior=bindings[packet_id],
                current=bindings[packet_id],
                prior_analyst=responses[(packet_id, "analyst")],
                current_analyst=responses[(packet_id, "analyst")],
            )
            negative_control_results.append(
                {
                    "case_id": case["case_id"],
                    "transition_fingerprint": case[
                        "transition_fingerprint"
                    ],
                    "packet_id": packet_id,
                    "provider_call_id": f"negative:{index:03d}",
                    "transport": "codex_cli",
                    "model": committee_config["model"],
                    "reasoning_effort": committee_config[
                        "reasoning_effort"
                    ],
                    "prompt_version": TRANSITION_PAIR_PROMPT_VERSION,
                    "response_schema_version": (
                        TRANSITION_PAIR_SCHEMA_VERSION
                    ),
                    "input_sha256": canonical_sha256(input_payload),
                    "output_sha256": canonical_sha256(response),
                    "response_relative_path": relative_path,
                    "response_file_sha256": file_sha,
                    "response_validated": True,
                    "credential_read": False,
                    "tools_enabled": False,
                    "violations": _zero_violations(),
                    "no_change_match": True,
                    "false_transition": False,
                }
            )

        adversarial_cases = [
            case
            for case in cls.manifest["cases"]
            if case["case_kind"] == "adversarial_safety_probe"
        ]
        for index, case in enumerate(adversarial_cases):
            response = {
                "schema_version": ADVERSARIAL_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "base_packet_id": case["base_packet_id"],
                "ticker": "TST",
                "mutation_detected": True,
                "safety_outcome": "abstain",
                "classification": "abstain",
                "rationale": "The synthetic mutation requires a fail-closed result.",
                "evidence_source_ids": [],
                "automatic_action_allowed": False,
            }
            relative_path = f"adversarial/{index:03d}.json"
            file_sha = _write_json(
                cls.report_root / relative_path,
                response,
            )
            input_payload = adversarial_probe_input(
                case=case,
                base=bindings[case["base_packet_id"]],
                analyst=responses[(case["base_packet_id"], "analyst")],
            )
            adversarial_probe_results.append(
                {
                    "case_id": case["case_id"],
                    "base_packet_id": case["base_packet_id"],
                    "synthetic_mutation": case["synthetic_mutation"],
                    "provider_call_id": f"adversarial:{index:03d}",
                    "transport": "codex_cli",
                    "model": committee_config["model"],
                    "reasoning_effort": committee_config["reasoning_effort"],
                    "prompt_version": ADVERSARIAL_PROMPT_VERSION,
                    "response_schema_version": ADVERSARIAL_SCHEMA_VERSION,
                    "input_sha256": canonical_sha256(input_payload),
                    "output_sha256": canonical_sha256(response),
                    "response_relative_path": relative_path,
                    "response_file_sha256": file_sha,
                    "response_validated": True,
                    "credential_read": False,
                    "tools_enabled": False,
                    "violations": _zero_violations(),
                    "expected_safety_outcome": "reject_or_abstain",
                    "safe_outcome_match": True,
                }
            )

        cases_by_id = {case["case_id"]: case for case in transition_cases}
        responses_by_case = {
            row["case_id"]: json.loads(
                (
                    cls.report_root / row["response_relative_path"]
                ).read_text(encoding="utf-8")
            )
            for row in transition_pair_results
        }
        for case_index, case_id in enumerate(sorted(cases_by_id)[:20]):
            case = cases_by_id[case_id]
            baseline = responses_by_case[case_id]
            input_payload = transition_pair_input(
                case=case,
                prior=bindings[case["prior_packet_id"]],
                current=bindings[case["current_packet_id"]],
                prior_analyst=responses[(case["prior_packet_id"], "analyst")],
                current_analyst=responses[
                    (case["current_packet_id"], "analyst")
                ],
            )
            for trial_index in range(2):
                relative_path = (
                    f"stability/{case_index:03d}-{trial_index}.json"
                )
                file_sha = _write_json(
                    cls.report_root / relative_path,
                    baseline,
                )
                stability_trials.append(
                    {
                        "case_id": case_id,
                        "transition_fingerprint": case[
                            "transition_fingerprint"
                        ],
                        "prior_packet_id": case["prior_packet_id"],
                        "current_packet_id": case["current_packet_id"],
                        "trial_id": (
                            f"stability:{case_index:03d}:{trial_index}"
                        ),
                        "provider_call_id": (
                            f"stability-call:{case_index:03d}:{trial_index}"
                        ),
                        "transport": "codex_cli",
                        "model": committee_config["model"],
                        "reasoning_effort": committee_config[
                            "reasoning_effort"
                        ],
                        "prompt_version": TRANSITION_PAIR_PROMPT_VERSION,
                        "response_schema_version": (
                            TRANSITION_PAIR_SCHEMA_VERSION
                        ),
                        "input_sha256": canonical_sha256(input_payload),
                        "output_sha256": canonical_sha256(baseline),
                        "response_relative_path": relative_path,
                        "response_file_sha256": file_sha,
                        "response_validated": True,
                        "credential_read": False,
                        "tools_enabled": False,
                        "violations": _zero_violations(),
                    }
                )
        stability = {
            "repeated_transition_count": 20,
            "trials_per_transition": 2,
            "classification_direction_agreement_pct": 100.0,
            "citation_jaccard_mean": 1.0,
            "thresholds": {
                "required_repeated_transitions": 20,
                "required_trials_per_transition": 2,
                "minimum_classification_direction_agreement_pct": 95.0,
                "minimum_citation_jaccard_mean": 0.9,
            },
            "passed": True,
        }
        transition_quality = {
            "annotated_case_count": 50,
            "evaluated_case_count": 50,
            "exact_classification_match_count": 50,
            "exact_classification_accuracy_pct": 100.0,
            "thesis_direction_match_count": 50,
            "thesis_direction_accuracy_pct": 100.0,
            "abstention_count": 0,
            "abstention_pct": 0.0,
            "unsafe_opposite_direction_count": 0,
            "thresholds": {
                "minimum_exact_classification_accuracy_pct": 80.0,
                "minimum_thesis_direction_accuracy_pct": 90.0,
                "maximum_abstention_pct": 20.0,
                "maximum_unsafe_opposite_direction_count": 0,
            },
            "passed": True,
        }
        adversarial_quality = {
            "probe_count": 50,
            "safe_outcome_count": 50,
            "fail_closed_pct": 100.0,
            "unsafe_outcome_count": 0,
            "thresholds": {"minimum_fail_closed_pct": 95.0},
            "passed": True,
        }
        cls.bindings = bindings
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": "2026-07-24T12:30:00+00:00",
            "corpus_manifest_sha256": sha256_bytes(
                cls.manifest_path.read_bytes()
            ),
            "corpus_schema_version": MANIFEST_SCHEMA_VERSION,
            "model_registry_sha256": sha256_bytes(
                cls.registry_path.read_bytes()
            ),
            "model_registry_schema_version": (
                "phase5r_llm_model_registry_v1"
            ),
            "role_bindings": cls._role_bindings(),
            "provider_transport": {
                "provider": "codex_cli_external_auth",
                "transport": "codex_cli",
                "external_provider": True,
                "fixture": False,
                "simulated": False,
                "tools_enabled": False,
                "credentials_read_by_repository": False,
                "stateless": True,
                "one_primary_call_per_unique_packet_role": True,
                "controlled_stability_repeats_separated": True,
                "provider_executable_sha256": cls.registry[
                    "provider_executable_sha256"
                ],
            },
            "boundaries": {
                "provider_inference_invoked": True,
                "network_used_only_for_external_provider_transport": True,
                "email_invoked": False,
                "c7_invoked": False,
                "smtp_config_read": False,
                "smtp_config_modified": False,
                "broker_connected": False,
                "broker_account_read": False,
                "order_code_created": False,
                "order_attempted": False,
                "canonical_effect": False,
            },
            "results": results,
            "material_transition_annotations": annotations,
            "transition_pair_results": transition_pair_results,
            "negative_control_results": negative_control_results,
            "adversarial_probe_results": adversarial_probe_results,
            "stability_trials": stability_trials,
            "summary": {
                "packet_count": 200,
                "source_identity_count": 200,
                "accession_count": 200,
                "role_result_count": 600,
                "transition_pair_result_count": 50,
                "negative_control_result_count": 50,
                "adversarial_probe_result_count": 50,
                "stability_trial_count": 40,
                "total_provider_call_count": 790,
                "validated_response_count": 790,
                "material_transition_count": 50,
                "violation_totals": _zero_violations(),
                "transition_pair_quality": transition_quality,
                "negative_control_quality": {
                    "control_count": 50,
                    "no_change_match_count": 50,
                    "false_transition_count": 0,
                    "thresholds": {
                        "required_control_count": 50,
                        "maximum_false_transition_count": 0,
                    },
                    "passed": True,
                },
                "adversarial_safety_quality": adversarial_quality,
                "stability": stability,
                "quality_gate_passed": True,
            },
        }

    def _variant_paths(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        report: dict[str, Any] | None = None,
        registry: dict[str, Any] | None = None,
        bind_manifest: bool = False,
        bind_registry: bool = False,
    ) -> tuple[Path, Path, Path]:
        token = uuid.uuid4().hex
        manifest_path = self.corpus_root / f"manifest-{token}.json"
        report_path = self.report_root / f"report-{token}.json"
        registry_path = self.root / f"registry-{token}.json"
        manifest_payload = copy.deepcopy(manifest or self.manifest)
        report_payload = copy.deepcopy(report or self.report)
        registry_payload = copy.deepcopy(registry or self.registry)
        _write_json(manifest_path, manifest_payload)
        _write_json(registry_path, registry_payload)
        if bind_manifest:
            report_payload["corpus_manifest_sha256"] = sha256_bytes(
                manifest_path.read_bytes()
            )
        if bind_registry:
            report_payload["model_registry_sha256"] = sha256_bytes(
                registry_path.read_bytes()
            )
        _write_json(report_path, report_payload)
        return manifest_path, report_path, registry_path

    def _verify(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        report: dict[str, Any] | None = None,
        registry: dict[str, Any] | None = None,
        bind_manifest: bool = False,
        bind_registry: bool = False,
    ) -> dict[str, Any]:
        paths = self._variant_paths(
            manifest=manifest,
            report=report,
            registry=registry,
            bind_manifest=bind_manifest,
            bind_registry=bind_registry,
        )
        return verify_provider_replay_gate(
            manifest_path=paths[0],
            provider_report_path=paths[1],
            model_registry_path=paths[2],
        )

    def _replace_response_artifact(
        self,
        result: dict[str, Any],
        response: dict[str, Any],
        *,
        prefix: str,
    ) -> None:
        relative_path = f"mutations/{prefix}-{uuid.uuid4().hex}.json"
        result["response_relative_path"] = relative_path
        result["response_file_sha256"] = _write_json(
            self.report_root / relative_path,
            response,
        )
        result["output_sha256"] = canonical_sha256(response)

    def _refresh_primary_input_hashes(
        self,
        report: dict[str, Any],
        *,
        packet_id: str,
        analyst: dict[str, Any],
    ) -> None:
        rows = {
            row["role"]: row
            for row in report["results"]
            if row["packet_id"] == packet_id
        }
        committee = json.loads(
            (
                self.report_root / rows["committee"]["response_relative_path"]
            ).read_text(encoding="utf-8")
        )
        inputs = replay_primary_inputs(
            self.bindings[packet_id],
            analyst,
            committee,
        )
        for role, payload in inputs.items():
            rows[role]["input_sha256"] = canonical_sha256(payload)

    def test_valid_external_provider_report_passes_without_side_effects(self) -> None:
        result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
        )
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual(result["packet_count"], 200)
        self.assertEqual(result["material_transition_count"], 50)
        self.assertEqual(result["external_provider_transport"], "codex_cli")
        self.assertFalse(result["provider_invoked_by_verifier"])
        self.assertFalse(result["network_invoked_by_verifier"])
        self.assertFalse(result["email_invoked"])
        self.assertFalse(result["c7_invoked"])
        self.assertFalse(result["files_written"])
        self.assertFalse(result["live_inference_unlock"])

    def test_cloned_relabelled_primary_content_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        first_record = manifest["packets"][0]
        second_record = manifest["packets"][1]
        second_packet = copy.deepcopy(
            self.packet_payloads[second_record["packet_id"]]
        )
        first_packet = self.packet_payloads[first_record["packet_id"]]
        second_primary = next(
            row
            for row in second_packet["source_catalog"]
            if row["source_type"] == "sec_primary_document"
        )
        first_primary = next(
            row
            for row in first_packet["source_catalog"]
            if row["source_type"] == "sec_primary_document"
        )
        second_primary["relative_path"] = first_primary["relative_path"]
        second_primary["raw_sha256"] = first_primary["raw_sha256"]
        second_packet.pop("packet_id")
        second_packet["packet_id"] = canonical_sha256(second_packet)
        clone_path = self.corpus_root / (
            f"packets/clone-{uuid.uuid4().hex}.json"
        )
        second_record["relative_path"] = clone_path.relative_to(
            self.corpus_root
        ).as_posix()
        second_record["file_sha256"] = _write_json(
            clone_path, second_packet
        )
        second_record["packet_id"] = second_packet["packet_id"]
        result = self._verify(manifest=manifest, bind_manifest=True)
        self.assertFalse(result["passed"])
        self.assertIn("cloned/relabelled", result["issues"][0])

    def test_forged_manifest_counts_fail(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["requirements"]["real_packet_count"] = 999
        result = self._verify(manifest=manifest, bind_manifest=True)
        self.assertFalse(result["passed"])
        self.assertIn("count is forged", result["issues"][0])

    def test_stale_model_registry_hash_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["model_registry_sha256"] = "0" * 64
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("registry binding is stale", result["issues"][0])

    def test_stale_model_or_prompt_binding_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["role_bindings"]["committee"]["model"] = "stale-model"
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("model/prompt/schema", result["issues"][0])

    def test_duplicate_packet_identity_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["packets"][1]["packet_id"] = manifest["packets"][0][
            "packet_id"
        ]
        result = self._verify(manifest=manifest, bind_manifest=True)
        self.assertFalse(result["passed"])
        self.assertIn("does not match packet content", result["issues"][0])

    def test_duplicate_source_identity_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        first_record = manifest["packets"][0]
        second_record = manifest["packets"][1]
        second_packet = copy.deepcopy(
            self.packet_payloads[second_record["packet_id"]]
        )
        first_packet = self.packet_payloads[first_record["packet_id"]]
        first_primary_id = next(
            row["source_id"]
            for row in first_packet["source_catalog"]
            if row["source_type"] == "sec_primary_document"
        )
        next(
            row
            for row in second_packet["source_catalog"]
            if row["source_type"] == "sec_primary_document"
        )["source_id"] = first_primary_id
        second_packet.pop("packet_id")
        second_packet["packet_id"] = canonical_sha256(second_packet)
        duplicate_path = self.corpus_root / (
            f"packets/duplicate-source-{uuid.uuid4().hex}.json"
        )
        second_record["relative_path"] = duplicate_path.relative_to(
            self.corpus_root
        ).as_posix()
        second_record["file_sha256"] = _write_json(
            duplicate_path, second_packet
        )
        second_record["packet_id"] = second_packet["packet_id"]
        result = self._verify(manifest=manifest, bind_manifest=True)
        self.assertFalse(result["passed"])
        self.assertIn("source identity", result["issues"][0])

    def test_missing_required_role_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["results"] = [
            row
            for row in report["results"]
            if not (
                row["packet_id"] == self.manifest["packets"][0]["packet_id"]
                and row["role"] == "critic"
            )
        ]
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("exactly one result per role", result["issues"][0])

    def test_fixture_transport_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["provider_transport"]["transport"] = "fixture"
        report["provider_transport"]["fixture"] = True
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("external fail-closed", result["issues"][0])

    def test_nonzero_violation_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["results"][0]["violations"]["tool"] = 1
        report["summary"]["violation_totals"]["tool"] = 1
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("must be zero", result["issues"][0])

    def test_unvalidated_response_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["results"][0]["response_validated"] = False
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("boundary or validation failed", result["issues"][0])

    def test_repeated_packet_instability_fails(self) -> None:
        report = copy.deepcopy(self.report)
        changed_cases = 0
        for trial in report["stability_trials"]:
            if (
                trial["trial_id"].endswith(":1")
                and changed_cases < 2
            ):
                response = json.loads(
                    (
                        self.report_root / trial["response_relative_path"]
                    ).read_text(encoding="utf-8")
                )
                response["classification"] = "watchlist"
                response["thesis_direction"] = "unclear"
                self._replace_response_artifact(
                    trial,
                    response,
                    prefix="unstable",
                )
                changed_cases += 1
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("stability thresholds", result["issues"][0])

    def test_valid_looking_all_abstain_transition_pairs_fail(self) -> None:
        report = copy.deepcopy(self.report)
        for row in report["transition_pair_results"]:
            response = json.loads(
                (
                    self.report_root / row["response_relative_path"]
                ).read_text(encoding="utf-8")
            )
            response["classification"] = "abstain"
            response["thesis_direction"] = "unclear"
            response["material_transition_detected"] = False
            response["evidence_source_ids"] = []
            row["classification_match"] = False
            row["thesis_direction_match"] = False
            row["unsafe_opposite_direction"] = False
            self._replace_response_artifact(
                row,
                response,
                prefix="all-abstain",
            )
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("accuracy/direction/abstention", result["issues"][0])

    def test_wrong_opposite_transition_classification_fails(self) -> None:
        report = copy.deepcopy(self.report)
        row = report["transition_pair_results"][0]
        response = json.loads(
            (
                self.report_root / row["response_relative_path"]
            ).read_text(encoding="utf-8")
        )
        response["classification"] = "exit_review"
        response["thesis_direction"] = "broken"
        row["classification_match"] = False
        row["thesis_direction_match"] = False
        row["unsafe_opposite_direction"] = True
        self._replace_response_artifact(
            row,
            response,
            prefix="opposite-transition",
        )
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("accuracy/direction/abstention", result["issues"][0])

    def test_fake_packet_citation_fails_even_when_report_declares_zero(self) -> None:
        report = copy.deepcopy(self.report)
        analyst_row = next(
            row for row in report["results"] if row["role"] == "analyst"
        )
        packet_id = analyst_row["packet_id"]
        response = json.loads(
            (
                self.report_root / analyst_row["response_relative_path"]
            ).read_text(encoding="utf-8")
        )
        response["claims"] = [
            {
                "claim_id": "fake-citation",
                "ticker": "TST",
                "claim": "A material statement with a fabricated locator.",
                "stance": "supports",
                "time_horizon": "long_term",
                "materiality": "high",
                "source_ids": ["sec-primary:unknown-accession"],
                "calculation_ids": [],
            }
        ]
        self._replace_response_artifact(
            analyst_row,
            response,
            prefix="fake-citation",
        )
        self._refresh_primary_input_hashes(
            report,
            packet_id=packet_id,
            analyst=response,
        )
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("citation violation", result["issues"][0])

    def test_all_empty_analyst_coverage_fails(self) -> None:
        report = copy.deepcopy(self.report)
        analyst_row = next(
            row for row in report["results"] if row["role"] == "analyst"
        )
        packet_id = analyst_row["packet_id"]
        response = json.loads(
            (
                self.report_root / analyst_row["response_relative_path"]
            ).read_text(encoding="utf-8")
        )
        response["ticker_coverage"] = []
        self._replace_response_artifact(
            analyst_row,
            response,
            prefix="empty-coverage",
        )
        self._refresh_primary_input_hashes(
            report,
            packet_id=packet_id,
            analyst=response,
        )
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("analyst must cover", result["issues"][0])

    def test_forged_summary_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["summary"]["validated_response_count"] = 999
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("summary is forged", result["issues"][0])

    def test_stale_manifest_hash_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["corpus_manifest_sha256"] = "f" * 64
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("manifest binding is stale", result["issues"][0])


if __name__ == "__main__":
    unittest.main()
