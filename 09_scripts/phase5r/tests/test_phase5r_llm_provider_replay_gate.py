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
from unittest import mock

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_llm_activation_receipt as activation_receipt_runtime
import verify_phase5r_llm_replay_corpus as strict_replay_corpus
import verify_phase5r_llm_provider_replay_gate as provider_gate_runtime
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
from phase5r_llm_transition_annotations import (
    ANNOTATION_SET_SCHEMA_VERSION,
    DEFAULT_RUBRIC_PATH,
    validate_annotation_set,
)
from phase5r_llm_activation_receipt import (
    ActivationReceiptError,
    build_activation_receipt,
    verify_active_activation_receipt,
)
from verify_phase5r_llm_provider_replay_gate import (
    ADVERSARIAL_PROMPT_VERSION,
    ADVERSARIAL_PROBE_SCHEMA,
    ADVERSARIAL_SCHEMA_VERSION,
    COUNTERFACTUAL_PROMPT_VERSION,
    CITATION_REVIEW_SET_SCHEMA_VERSION,
    CRITIC_CONTROL_PROMPT_VERSION,
    CRITIC_CONTROL_SCHEMA,
    CRITIC_CONTROL_SCHEMA_VERSION,
    EXTENDED_QUALITY_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    PacketBinding,
    PACKET_SCHEMA_VERSION,
    REFERENCE_RUBRIC_VERSION,
    ReplayGateError,
    REPORT_SCHEMA_VERSION,
    ROLE_SCHEMA_VERSIONS,
    TRANSITION_PAIR_PROMPT_VERSION,
    TRANSITION_PAIR_SCHEMA,
    TRANSITION_PAIR_SCHEMA_VERSION,
    VIOLATION_CATEGORIES,
    _load_corpus,
    _wilson_interval_pct,
    adversarial_probe_input,
    build_runtime_replay_packet,
    canonical_sha256,
    counterfactual_transition_input,
    critic_control_cases,
    critic_control_input,
    deterministic_replay_evaluation_context,
    materialize_replay_evidence_excerpts,
    frozen_transition_folds,
    frozen_transition_split,
    negative_control_cases,
    replay_primary_inputs,
    replay_runtime_code_hashes,
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
    source_sha256: str,
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
                    "rationale": (
                        "The cited official excerpt supports the durable "
                        "research inference."
                    ),
                    "fact_type": "fact",
                    "evidence_origin": "management_reported",
                    "unit": "not_applicable",
                    "period": "long_term",
                    "source_ids": [source_id],
                    "cited_excerpt_sha256": [source_sha256],
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
                "fact": text,
                "source_ids": [source_id],
                "calculation_ids": [],
            }
            for text in (
                "Primary evidence supports durable demand.",
                "Primary evidence supports strategic durability.",
                "Primary evidence supports the long-term thesis.",
            )
        ]
        if reference_aligned
        else []
    )
    counterfacts = (
        [
            {
                "ticker": "TST",
                "fact": text,
                "source_ids": [source_id],
                "calculation_ids": [],
            }
            for text in (
                "Primary evidence leaves execution uncertainty.",
                "Primary evidence leaves competitive uncertainty.",
                "Primary evidence leaves valuation uncertainty.",
            )
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
        "confidence_pct": 0,
        "confidence_components": {
            "evidence_coverage_pct": 80 if reference_aligned else 0,
            "thesis_clarity_pct": 80 if reference_aligned else 0,
            "valuation_clarity_pct": 0,
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
                "claim_ids": (
                    [f"material:{packet_id[:16]}"]
                    if reference_aligned
                    else []
                ),
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
    verdict = "approve" if reference_aligned else "reject"
    downgrade = (
        "paper_trade_candidate" if reference_aligned else "abstain"
    )
    approved_sources = [source_id] if reference_aligned else []
    issues = (
        []
        if reference_aligned
        else [
            {
                "severity": "high",
                "issue": (
                    "Primary evidence is insufficient for the proposed "
                    "classification."
                ),
                "source_ids": [],
            }
        ]
    )
    ticker_review = {
        "ticker": "TST",
        "verdict": verdict,
        "downgrade_to": downgrade,
        "factual_grounding_pass": reference_aligned,
        "citation_integrity_pass": True,
        "numeric_reconciliation_pass": True,
        "long_term_reasoning_pass": True,
        "action_proportionality_pass": True,
        "policy_boundary_pass": True,
        "issues": issues,
        "approved_source_ids": approved_sources,
    }
    return {
        "schema_version": CRITIC_SCHEMA_VERSION,
        "packet_id": packet_id,
        "verdict": verdict,
        "downgrade_to": downgrade,
        "factual_grounding_pass": reference_aligned,
        "citation_integrity_pass": True,
        "numeric_reconciliation_pass": True,
        "long_term_reasoning_pass": True,
        "action_proportionality_pass": True,
        "policy_boundary_pass": True,
        "ticker_reviews": [ticker_review],
        "issues": issues,
        "approved_source_ids": approved_sources,
        "automatic_action_allowed": False,
    }


def _transition_split_fixture(
    *,
    overlapping_issuer_timelines: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, PacketBinding]]:
    annotations: list[dict[str, Any]] = []
    packets: dict[str, PacketBinding] = {}
    first_starts = [
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2020, 7, 1, tzinfo=timezone.utc),
        datetime(2020, 12, 1, tzinfo=timezone.utc),
    ]
    for issuer_index in range(10):
        if overlapping_issuer_timelines:
            start = first_starts[0]
        elif issuer_index < len(first_starts):
            start = first_starts[issuer_index]
        else:
            start = first_starts[2] + timedelta(
                days=180 * (issuer_index - 2)
            )
        cik = str(1000 + issuer_index)
        ticker = f"T{issuer_index:02d}"
        issuer_packet_ids: list[str] = []
        for packet_index in range(6):
            accepted_at = start + timedelta(days=30 * packet_index)
            packet_id = f"packet:{issuer_index}:{packet_index}"
            source_id = f"sec-primary:{issuer_index}:{packet_index}"
            packets[packet_id] = PacketBinding(
                payload={"cik": cik, "packet_id": packet_id},
                runtime_packet={"packet_id": packet_id},
                evaluation_context={},
                accession=f"{issuer_index:010d}-26-{packet_index:06d}",
                ticker=ticker,
                accepted_at_et=accepted_at,
                source_ids=frozenset({source_id}),
                primary_source_id=source_id,
                evidence_excerpts=(),
            )
            issuer_packet_ids.append(packet_id)
        for case_index, (prior_id, current_id) in enumerate(
            zip(issuer_packet_ids, issuer_packet_ids[1:])
        ):
            annotations.append(
                {
                    "case_id": f"transition:{issuer_index}:{case_index}",
                    "prior_packet_id": prior_id,
                    "current_packet_id": current_id,
                }
            )
    return annotations, packets


class TransitionSplitTests(unittest.TestCase):
    def test_split_is_frozen_grouped_chronological_and_leakage_free(
        self,
    ) -> None:
        annotations, packets = _transition_split_fixture()
        split = frozen_transition_split(annotations, packets)
        reordered = frozen_transition_split(
            list(reversed(annotations)),
            packets,
        )

        self.assertEqual(split, reordered)
        self.assertEqual(
            split["algorithm"],
            "issuer_grouped_chronological_purged_embargo_v1",
        )
        self.assertEqual(len(split["dev_case_ids"]), 9)
        self.assertEqual(len(split["holdout_case_ids"]), 39)
        self.assertEqual(len(split["purged_case_ids"]), 1)
        self.assertEqual(len(split["embargoed_case_ids"]), 1)
        self.assertFalse(
            set(split["dev_issuer_ids"])
            & set(split["holdout_issuer_ids"])
        )
        folds = split["multi_fold_validation"]
        self.assertEqual(folds["status"], "passed")
        self.assertEqual(folds["fold_count"], 3)
        self.assertEqual(
            len(folds["global_holdout_case_ids"]),
            len(set(folds["global_holdout_case_ids"])),
        )
        self.assertEqual(
            len(folds["global_holdout_issuer_ids"]),
            len(set(folds["global_holdout_issuer_ids"])),
        )
        for fold_index, fold in enumerate(folds["folds"], start=1):
            self.assertEqual(fold["fold_index"], fold_index)
            self.assertFalse(
                set(fold["dev_issuer_ids"])
                & set(fold["holdout_issuer_ids"])
            )
            unsigned_fold = dict(fold)
            claimed_fold_hash = unsigned_fold.pop("fold_sha256")
            self.assertEqual(
                claimed_fold_hash,
                canonical_sha256(unsigned_fold),
            )
        unsigned_folds = dict(folds)
        claimed_receipt_hash = unsigned_folds.pop("receipt_sha256")
        self.assertEqual(
            claimed_receipt_hash,
            canonical_sha256(unsigned_folds),
        )
        self.assertEqual(
            split["invariants"],
            {
                "issuer_overlap_count": 0,
                "shared_packet_overlap_count": 0,
                "adjacent_transition_leakage_count": 0,
                "dev_ends_before_holdout_starts": True,
            },
        )
        partitioned = (
            split["dev_case_ids"]
            + split["holdout_case_ids"]
            + split["purged_case_ids"]
            + split["embargoed_case_ids"]
        )
        self.assertEqual(
            set(partitioned),
            {row["case_id"] for row in annotations},
        )
        self.assertEqual(len(partitioned), len(set(partitioned)))
        unsigned = dict(split)
        claimed_hash = unsigned.pop("split_sha256")
        self.assertEqual(claimed_hash, canonical_sha256(unsigned))

    def test_split_rejects_cross_cik_transition(self) -> None:
        annotations, packets = _transition_split_fixture()
        current_id = annotations[0]["current_packet_id"]
        current = packets[current_id]
        packets[current_id] = PacketBinding(
            payload={**current.payload, "cik": "999999"},
            runtime_packet=current.runtime_packet,
            evaluation_context=current.evaluation_context,
            accession=current.accession,
            ticker=current.ticker,
            accepted_at_et=current.accepted_at_et,
            source_ids=current.source_ids,
            primary_source_id=current.primary_source_id,
            evidence_excerpts=current.evidence_excerpts,
        )
        with self.assertRaisesRegex(
            ReplayGateError,
            "stable SEC issuer identity",
        ):
            frozen_transition_split(annotations, packets)

    def test_split_fails_when_purge_removes_chronological_dev_set(
        self,
    ) -> None:
        annotations, packets = _transition_split_fixture(
            overlapping_issuer_timelines=True
        )
        with self.assertRaisesRegex(
            ReplayGateError,
            "purge/embargo leaves an undersized partition",
        ):
            frozen_transition_split(annotations, packets)

    def test_multi_fold_receipt_is_order_independent(self) -> None:
        annotations, packets = _transition_split_fixture()
        expected = frozen_transition_folds(annotations, packets)
        actual = frozen_transition_folds(
            list(reversed(annotations)),
            packets,
        )
        self.assertEqual(actual, expected)

    def test_multi_fold_requires_enough_disjoint_issuer_groups(self) -> None:
        annotations, packets = _transition_split_fixture()
        with self.assertRaisesRegex(
            ReplayGateError,
            "too few issuer groups",
        ):
            frozen_transition_folds(
                annotations,
                packets,
                minimum_folds=5,
            )


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
        cls.annotation_path = cls.root / "annotations.json"
        cls.citation_review_path = cls.root / "citation-reviews.json"
        cls.registry = cls._build_registry()
        _write_json(cls.registry_path, cls.registry)
        cls.manifest, cls.packet_payloads = cls._build_manifest()
        _write_json(cls.manifest_path, cls.manifest)
        cls.corpus = _load_corpus(
            cls.manifest_path,
            minimum_packets=250,
            minimum_issuers=20,
        )
        cls._build_annotation_set()
        (
            cls.validated_annotations,
            cls.annotation_binding,
        ) = validate_annotation_set(
            annotation_path=cls.annotation_path,
            corpus=cls.corpus,
            expected_file_sha256=sha256_bytes(
                cls.annotation_path.read_bytes()
            ),
        )
        # This legacy synthetic fixture intentionally lacks real issuer
        # continuity. Keep downstream report-scoring tests isolated from the
        # real split prerequisite, which is exercised by focused tests below.
        case_ids = sorted(
            row["case_id"] for row in cls.validated_annotations
        )
        dev_count = max(1, len(case_ids) // 5)
        cls.frozen_split_fixture = {
            "algorithm": "isolated_legacy_test_split_v1",
            "dev_case_ids": case_ids[:dev_count],
            "holdout_case_ids": case_ids[dev_count:],
        }
        cls.frozen_split_fixture["split_sha256"] = canonical_sha256(
            cls.frozen_split_fixture
        )
        cls.report = cls._build_report()
        _write_json(cls.report_path, cls.report)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def setUp(self) -> None:
        # Most tests below isolate provider-report scoring. A separate
        # integration test exercises the real strict corpus prerequisite.
        self.strict_corpus_patch = mock.patch(
            "verify_phase5r_llm_provider_replay_gate."
            "verify_strict_replay_corpus",
            return_value={
                "passed": True,
                "real_packet_count": 250,
                "distinct_issuer_count": 250,
                "material_transition_probe_count": 50,
                "adversarial_safety_probe_count": 50,
                "issues": [],
            },
        )
        self.strict_corpus_patch.start()
        self.addCleanup(self.strict_corpus_patch.stop)
        self.transition_split_patch = mock.patch(
            "verify_phase5r_llm_provider_replay_gate."
            "frozen_transition_split",
            return_value=copy.deepcopy(self.frozen_split_fixture),
        )
        self.transition_split_patch.start()
        self.addCleanup(self.transition_split_patch.stop)

    def test_corpus_fails_closed_below_distinct_issuer_floor(self) -> None:
        with self.assertRaisesRegex(
            ReplayGateError,
            r"real replay issuer minimum unmet: 250 < 251",
        ):
            _load_corpus(
                self.manifest_path,
                minimum_packets=250,
                minimum_issuers=251,
            )

    def test_corpus_loader_rejects_lowered_hard_minimums(self) -> None:
        with self.assertRaisesRegex(
            ReplayGateError,
            "requested replay packet minimum is below the hard corpus floor",
        ):
            _load_corpus(
                self.manifest_path,
                minimum_packets=249,
                minimum_issuers=20,
            )
        with self.assertRaisesRegex(
            ReplayGateError,
            "requested replay issuer minimum is below the hard corpus floor",
        ):
            _load_corpus(
                self.manifest_path,
                minimum_packets=250,
                minimum_issuers=19,
            )

    @classmethod
    def _build_registry(cls) -> dict[str, Any]:
        report = {
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
            "successful_role_results_reused": True,
            "maximum_live_attempts_per_role": 2,
            "stateless": True,
            "tools_enabled": False,
            "provider_credentials_read_by_repository": False,
            "exact_account_dollars_allowed": False,
            "automatic_action_allowed": False,
            "email_eligible": False,
            "broker_connection_allowed": False,
            "order_code_allowed": False,
            "promotion_requirements": {
                "minimum_replay_packets": 250,
                "minimum_replay_issuers": 20,
                "minimum_material_transition_cases": 50,
                "minimum_live_shadow_sessions": 30,
                "maximum_live_shadow_sessions_before_review": 60,
                "maximum_policy_boundary_violations": 0,
            },
        }
        return report

    @classmethod
    def _write_execution_fixture(
        cls,
        report: dict[str, Any],
    ) -> None:
        by_call: dict[str, dict[str, Any]] = {}
        roles_by_call: dict[str, str] = {}
        categories_by_call: dict[str, str] = {}

        def add_rows(
            rows: list[dict[str, Any]],
            *,
            fixed_role: str | None,
            category: str,
        ) -> None:
            for row in rows:
                call_id = row["provider_call_id"]
                if call_id in by_call:
                    raise AssertionError(
                        "execution fixture call identity is duplicated"
                    )
                role = row["role"] if fixed_role is None else fixed_role
                by_call[call_id] = row
                roles_by_call[call_id] = role
                categories_by_call[call_id] = category

        add_rows(
            report["results"],
            fixed_role=None,
            category="primary",
        )
        add_rows(
            report["transition_pair_results"],
            fixed_role="transition_pair",
            category="transition_pair",
        )
        add_rows(
            report["negative_control_results"],
            fixed_role="negative_control",
            category="negative_control",
        )
        add_rows(
            report["adversarial_probe_results"],
            fixed_role="adversarial_probe",
            category="adversarial_probe",
        )
        add_rows(
            report["stability_trials"],
            fixed_role="stability_transition_pair",
            category="stability_transition_pair",
        )
        add_rows(
            report["extended_quality"]["critic_control_results"],
            fixed_role="critic_control",
            category="critic_control",
        )
        add_rows(
            report["extended_quality"]["counterfactual_results"],
            fixed_role="counterfactual_transition_pair",
            category="counterfactual",
        )
        if len(by_call) != 1040:
            raise AssertionError("execution fixture call closure is invalid")

        def fixture_role(row: dict[str, Any]) -> str:
            return roles_by_call[row["provider_call_id"]]

        def fixture_category(row: dict[str, Any]) -> str:
            return categories_by_call[row["provider_call_id"]]
        config = {
            "schema_version": (
                "phase5r_llm_provider_replay_collection_v1"
            ),
            "plan": {"total_call_count": len(by_call)},
            "budget_policy": {
                "frozen_global_physical_call_ceiling": 1050,
                "operator_estimated_global_cost_ceiling_usd": "10.50",
                "operator_estimated_usd_per_physical_call": "0.01",
                "cost_basis": (
                    "operator_estimate_not_provider_billing"
                ),
                "maximum_attempts_per_logical_call": 3,
            },
        }
        events: list[dict[str, Any]] = []
        successful_calls: dict[str, dict[str, Any]] = {}
        receipt_bindings: list[dict[str, Any]] = []
        physical_rows: list[dict[str, Any]] = []
        previous_event_sha = ""
        timestamp = "2026-07-24T12:30:00+00:00"

        def append_event(
            *,
            event_kind: str,
            call_id: str,
            input_sha256: str,
            outcome_category: str,
            safe_outcome: str,
        ) -> dict[str, Any]:
            nonlocal previous_event_sha
            event = {
                "event_index": len(events) + 1,
                "event_kind": event_kind,
                "provider_call_id": call_id,
                "attempt_number": 1,
                "recorded_at": timestamp,
                "input_sha256": input_sha256,
                "safe_outcome": safe_outcome,
                "outcome_category": outcome_category,
                "retryable": False,
                "previous_event_sha256": previous_event_sha,
            }
            event["event_sha256"] = canonical_sha256(event)
            previous_event_sha = event["event_sha256"]
            events.append(event)
            return event

        for physical_sequence, call_id in enumerate(
            sorted(by_call),
            start=1,
        ):
            row = by_call[call_id]
            started = append_event(
                event_kind="attempt_started",
                call_id=call_id,
                input_sha256=row["input_sha256"],
                outcome_category="invocation_started",
                safe_outcome="provider_invocation_intent_persisted",
            )
            terminal = append_event(
                event_kind="success",
                call_id=call_id,
                input_sha256=row["input_sha256"],
                outcome_category="valid_response",
                safe_outcome="validated_response_persisted",
            )
            response = json.loads(
                (
                    cls.report_root / row["response_relative_path"]
                ).read_text(encoding="utf-8")
            )
            receipt_relative = (
                "attempt_receipts/"
                f"{hashlib.sha256(call_id.encode('utf-8')).hexdigest()}"
                "-attempt-1.json"
            )
            receipt_role = fixture_role(row)
            receipt_category = fixture_category(row)
            receipt = {
                "schema_version": (
                    "phase5r_llm_provider_attempt_receipt_v2"
                ),
                "provider_call_id": call_id,
                "category": receipt_category,
                "role": receipt_role,
                "model": row["model"],
                "reasoning_effort": row["reasoning_effort"],
                "attempt_number": 1,
                "input_sha256": row["input_sha256"],
                "terminal_event_kind": "success",
                "outcome_category": "valid_response",
                "retryable": False,
                "safe_outcome": "validated_response_persisted",
                "output_sha256": row["output_sha256"],
                "response_relative_path": row[
                    "response_relative_path"
                ],
                "payload": response,
                "provider_metadata": {
                    "transport": "codex_cli",
                    "role": receipt_role,
                    "model": row["model"],
                    "reasoning_effort": row["reasoning_effort"],
                    "input_sha256": row["input_sha256"],
                    "output_sha256": row["output_sha256"],
                    "credential_read": False,
                    "tools_enabled": False,
                    "executable_sha256": cls.registry[
                        "provider_executable_sha256"
                    ],
                },
                "ledger_row": {
                    "provider_call_id": call_id,
                    "category": receipt_category,
                    "role": receipt_role,
                    "transport": "codex_cli",
                    "model": row["model"],
                    "reasoning_effort": row["reasoning_effort"],
                    "input_sha256": row["input_sha256"],
                    "output_sha256": row["output_sha256"],
                    "credential_read": False,
                    "tools_enabled": False,
                    "canonical_effect": False,
                    "email_invoked": False,
                    "c7_invoked": False,
                    "broker_invoked": False,
                    "order_invoked": False,
                },
            }
            receipt["receipt_sha256"] = canonical_sha256(receipt)
            receipt_file_sha = _write_json(
                cls.report_root / receipt_relative,
                receipt,
            )
            receipt_binding = {
                "provider_call_id": call_id,
                "attempt_number": 1,
                "relative_path": receipt_relative,
                "file_sha256": receipt_file_sha,
                "receipt_sha256": receipt["receipt_sha256"],
            }
            receipt_bindings.append(receipt_binding)
            physical_rows.append(
                {
                    "physical_attempt_sequence": physical_sequence,
                    "provider_call_id": call_id,
                    "attempt_number": 1,
                    "category": receipt["category"],
                    "role": receipt["role"],
                    "model": receipt["model"],
                    "reasoning_effort": receipt["reasoning_effort"],
                    "input_sha256": row["input_sha256"],
                    "started_at": started["recorded_at"],
                    "terminal_event_kind": "success",
                    "completed_at": terminal["recorded_at"],
                    "outcome_category": "valid_response",
                    "retryable": False,
                    "attempt_receipt_relative_path": receipt_relative,
                    "attempt_receipt_file_sha256": receipt_file_sha,
                }
            )
            successful_calls[call_id] = {}
        progress = {
            "schema_version": (
                "phase5r_llm_provider_replay_progress_v3"
            ),
            "created_at": timestamp,
            "updated_at": timestamp,
            "collection_config": config,
            "collection_config_sha256": canonical_sha256(config),
            "events": events,
            "successful_calls": successful_calls,
            "complete": True,
        }
        progress["progress_sha256"] = canonical_sha256(progress)
        progress_file_sha = _write_json(
            cls.report_root
            / "phase5r_llm_provider_replay_progress.json",
            progress,
        )
        progress_binding = {
            "relative_path": (
                "phase5r_llm_provider_replay_progress.json"
            ),
            "file_sha256": progress_file_sha,
            "progress_sha256": progress["progress_sha256"],
        }
        category_counts = {
            category: (1040 if category == "valid_response" else 0)
            for category in (
                "artifact_integrity_invalid",
                "policy_invalid",
                "process_interrupted",
                "provider_metadata_invalid",
                "schema_invalid",
                "semantic_invalid",
                "transport_missing_response",
                "transport_timeout",
                "valid_response",
            )
        }
        attempt_metrics = {
            "logical_successful_call_count": 1040,
            "physical_attempt_count": 1040,
            "first_attempt_valid_logical_call_count": 1040,
            "retryable_transport_or_process_failure_count": 0,
            "invalid_attempt_count": 0,
            "outcome_category_counts": category_counts,
        }
        ledger = {
            "schema_version": (
                "phase5r_llm_provider_replay_execution_ledger_v2"
            ),
            "generated_at": timestamp,
            "corpus_manifest_sha256": report[
                "corpus_manifest_sha256"
            ],
            "model_registry_sha256": report[
                "model_registry_sha256"
            ],
            "annotation_file_sha256": report[
                "annotation_set_binding"
            ]["annotation_file_sha256"],
            "annotation_set_sha256": report[
                "annotation_set_binding"
            ]["annotation_set_sha256"],
            "collection_progress": progress_binding,
            "budget": {
                "logical_plan_call_count": 1040,
                "logical_successful_call_count": 1040,
                "physical_attempt_count": 1040,
                "frozen_global_physical_call_ceiling": 1050,
                "operator_estimated_usd_per_physical_call": "0.01",
                "operator_estimated_cumulative_cost_usd": "10.40",
                "operator_estimated_global_cost_ceiling_usd": "10.50",
                "cost_basis": (
                    "operator_estimate_not_provider_billing"
                ),
                "maximum_attempts_per_logical_call": 3,
            },
            "attempt_metrics": attempt_metrics,
            "attempt_receipt_set_sha256": canonical_sha256(
                receipt_bindings
            ),
            "logical_calls": [
                {
                    "sequence": sequence,
                    "provider_call_id": call_id,
                    "category": fixture_category(row),
                    "role": fixture_role(row),
                    "transport": "codex_cli",
                    "model": row["model"],
                    "reasoning_effort": row["reasoning_effort"],
                    "input_sha256": row["input_sha256"],
                    "output_sha256": row["output_sha256"],
                    "credential_read": False,
                    "tools_enabled": False,
                    "canonical_effect": False,
                    "email_invoked": False,
                    "c7_invoked": False,
                    "broker_invoked": False,
                    "order_invoked": False,
                    "response_relative_path": row[
                        "response_relative_path"
                    ],
                    "response_file_sha256": row[
                        "response_file_sha256"
                    ],
                }
                for sequence, (call_id, row) in enumerate(
                    sorted(by_call.items()),
                    start=1,
                )
            ],
            "physical_attempts": physical_rows,
            "boundaries": {},
        }
        ledger_file_sha = _write_json(
            cls.report_root
            / "phase5r_llm_provider_replay_execution_ledger.json",
            ledger,
        )
        execution_integrity = {
            "collection_progress": progress_binding,
            "execution_ledger": {
                "relative_path": (
                    "phase5r_llm_provider_replay_execution_ledger.json"
                ),
                "file_sha256": ledger_file_sha,
            },
            "attempt_receipt_count": 1040,
            "attempt_receipt_set_sha256": canonical_sha256(
                receipt_bindings
            ),
            "logical_provider_call_count": 1040,
            "physical_provider_attempt_count": 1040,
            "first_attempt_valid_logical_call_count": 1040,
            "retryable_transport_or_process_failure_count": 0,
            "invalid_attempt_count": 0,
            "frozen_global_physical_call_ceiling": 1050,
            "operator_estimated_usd_per_physical_call": "0.01",
            "operator_estimated_cumulative_cost_usd": "10.40",
            "operator_estimated_global_cost_ceiling_usd": "10.50",
            "cost_basis": "operator_estimate_not_provider_billing",
        }
        report["execution_integrity"] = execution_integrity
        report["summary"].update(
            {
                "logical_provider_call_count": 1040,
                "physical_provider_attempt_count": 1040,
                "first_attempt_valid_logical_call_count": 1040,
                "retryable_transport_or_process_failure_count": 0,
                "invalid_provider_attempt_count": 0,
                "operator_estimated_cumulative_cost_usd": "10.40",
                "operator_estimated_cost_not_provider_billing": True,
            }
        )
        base_report = copy.deepcopy(report)
        base_report.pop("extended_quality")
        base_report.pop("summary")
        candidate = {"base_report": base_report}
        candidate_file_sha = _write_json(
            cls.report_root
            / "phase5r_llm_provider_replay_candidate.json",
            candidate,
        )
        response_artifacts = [
            {
                "provider_call_id": call_id,
                "relative_path": row["response_relative_path"],
                "file_sha256": row["response_file_sha256"],
                "input_sha256": row["input_sha256"],
                "output_sha256": row["output_sha256"],
            }
            for call_id, row in sorted(by_call.items())
        ]
        manifest = {
            "schema_version": (
                "phase5r_llm_provider_replay_collection_v1"
            ),
            "completed_at": timestamp,
            "state": "pending_independent_human_citation_review",
            "activation_eligible": False,
            "collection_config": config,
            "collection_progress": progress_binding,
            "candidate": {
                "relative_path": (
                    "phase5r_llm_provider_replay_candidate.json"
                ),
                "file_sha256": candidate_file_sha,
            },
            "execution_ledger": execution_integrity[
                "execution_ledger"
            ],
            "attempt_receipts": receipt_bindings,
            "response_artifacts": response_artifacts,
            "boundaries": {},
        }
        manifest["collection_manifest_sha256"] = canonical_sha256(
            manifest
        )
        _write_json(
            cls.report_root
            / "phase5r_llm_provider_replay_collection_manifest.json",
            manifest,
        )

    @classmethod
    def _build_manifest(
        cls,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        records: list[dict[str, Any]] = []
        packets: dict[str, dict[str, Any]] = {}
        started = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
        for index in range(250):
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
                    "evaluation_context": (
                        deterministic_replay_evaluation_context("TST")
                    ),
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
                    "evaluation_context": (
                        deterministic_replay_evaluation_context("TST")
                    ),
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
                "minimum_real_point_in_time_packets": 250,
                "minimum_distinct_issuers": 20,
                "minimum_material_transition_probes": 50,
                "minimum_adversarial_safety_probes": 50,
                "minimum_transition_or_adversarial_cases": 100,
                "real_packet_count": 250,
                "distinct_issuer_count": 250,
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
    def _build_annotation_set(cls) -> None:
        records: list[dict[str, Any]] = []
        transition_cases = [
            case
            for case in cls.manifest["cases"]
            if case["case_kind"] == "material_transition_detection_probe"
        ]
        for index, case in enumerate(transition_cases):
            prior = cls.corpus.packets[case["prior_packet_id"]]
            current = cls.corpus.packets[case["current_packet_id"]]
            evidence = sorted(
                [prior.primary_source_id, current.primary_source_id]
            )
            rationale = (
                "The current official filing contains a durable primary-evidence "
                "change relative to the prior filing; uncertainty remains bounded "
                "to the frozen point-in-time research context."
            )
            rationale_sha = hashlib.sha256(
                rationale.encode("utf-8")
            ).hexdigest()
            attestations: list[dict[str, Any]] = []
            for reviewer_index in range(2):
                reviewer_rationale = (
                    f"Reviewer {reviewer_index + 1} independently finds a "
                    "material long-horizon strengthening in the cited official "
                    "filings, with no later evidence considered."
                )
                attestation: dict[str, Any] = {
                    "reviewer_id_sha256": hashlib.sha256(
                        (
                            f"reviewer:{reviewer_index}:{index}"
                        ).encode("utf-8")
                    ).hexdigest(),
                    "reviewed_at": "2026-07-24T11:00:00+00:00",
                    "is_material_transition": True,
                    "reference_classification": "paper_trade_candidate",
                    "reference_thesis_direction": "strengthening",
                    "evidence_source_ids": evidence,
                    "reviewer_rationale": reviewer_rationale,
                    "reviewer_rationale_sha256": hashlib.sha256(
                        reviewer_rationale.encode("utf-8")
                    ).hexdigest(),
                }
                attestation["attestation_sha256"] = canonical_sha256(
                    attestation
                )
                attestations.append(attestation)
            adjudication: dict[str, Any] = {
                "required": False,
                "adjudicator_id_sha256": "",
                "adjudicated_at": "",
                "adjudication_rationale": "",
                "adjudication_rationale_sha256": "",
            }
            adjudication["adjudication_sha256"] = canonical_sha256(
                adjudication
            )
            record: dict[str, Any] = {
                "case_id": case["case_id"],
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "is_material_transition": True,
                "reference_classification": "paper_trade_candidate",
                "reference_thesis_direction": "strengthening",
                "evidence_source_ids": evidence,
                "consensus_rationale": rationale,
                "consensus_rationale_sha256": rationale_sha,
                "reviewer_attestations": attestations,
                "adjudication": adjudication,
            }
            record["record_sha256"] = canonical_sha256(record)
            records.append(record)
        record_count = len(records)
        review_statistics = {
            "record_count": record_count,
            "independent_review_count_total": record_count * 2,
            "minimum_reviewers_per_record": 2,
            "initial_unanimous_count": record_count,
            "initial_disagreement_count": 0,
            "initial_exact_agreement_pct": 100.0,
            "adjudicated_count": 0,
            "unresolved_disagreement_count": 0,
            "final_consensus_count": record_count,
            "final_consensus_pct": 100.0,
        }
        payload: dict[str, Any] = {
            "schema_version": ANNOTATION_SET_SCHEMA_VERSION,
            "generated_at": "2026-07-24T12:00:00+00:00",
            "corpus_manifest_sha256": cls.corpus.manifest_sha256,
            "corpus_schema_version": MANIFEST_SCHEMA_VERSION,
            "rubric": {
                "version": REFERENCE_RUBRIC_VERSION,
                "relative_path": DEFAULT_RUBRIC_PATH.relative_to(
                    DEFAULT_RUBRIC_PATH.parents[1]
                ).as_posix(),
                "file_sha256": sha256_bytes(
                    DEFAULT_RUBRIC_PATH.read_bytes()
                ),
            },
            "frozen": True,
            "annotation_method": "independent_dual_review",
            "records": records,
            "review_statistics": review_statistics,
        }
        payload["annotation_set_sha256"] = canonical_sha256(payload)
        _write_json(cls.annotation_path, payload)

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
                packet,
                evidence_excerpts,
                record["evaluation_context"],
            )
            source_ids = frozenset(
                row["source_id"] for row in packet["source_catalog"]
            )
            bindings[packet_id] = PacketBinding(
                payload=packet,
                runtime_packet=runtime_packet,
                evaluation_context=copy.deepcopy(
                    record["evaluation_context"]
                ),
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
            runtime_source_sha = runtime_packet["source_catalog"][0][
                "content_sha256"
            ]
            runtime_packet_id = runtime_packet["packet_id"]
            responses[(packet_id, "analyst")] = _analyst_response(
                runtime_packet_id,
                runtime_packet["as_of_et"],
                source_id=runtime_source_id,
                source_sha256=runtime_source_sha,
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
        annotations_by_case = {
            row["case_id"]: copy.deepcopy(row)
            for row in cls.validated_annotations
        }
        for index, case in enumerate(transition_cases):
            prior = records_by_id[case["prior_packet_id"]]
            current = records_by_id[case["current_packet_id"]]
            annotation = annotations_by_case[case["case_id"]]
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
                "thesis_direction": "unchanged",
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
        citation_reviews: list[dict[str, Any]] = []
        for annotation in annotations:
            packet_id = annotation["current_packet_id"]
            analyst = responses[(packet_id, "analyst")]
            for claim in analyst["claims"]:
                reviewer_rows: list[dict[str, Any]] = []
                for reviewer_index in range(2):
                    rationale = (
                        "The cited primary excerpt directly supports the "
                        "material long-horizon claim within the frozen as-of."
                    )
                    reviewer_rows.append(
                        {
                            "reviewer_id_sha256": hashlib.sha256(
                                (
                                    f"citation-reviewer:{reviewer_index}:"
                                    f"{annotation['case_id']}:{claim['claim_id']}"
                                ).encode("utf-8")
                            ).hexdigest(),
                            "reviewer_kind": "human",
                            "entailed": True,
                            "rationale": rationale,
                            "rationale_sha256": hashlib.sha256(
                                rationale.encode("utf-8")
                            ).hexdigest(),
                        }
                    )
                review: dict[str, Any] = {
                    "case_id": annotation["case_id"],
                    "packet_id": packet_id,
                    "claim_id": claim["claim_id"],
                    "claim_text_sha256": hashlib.sha256(
                        claim["claim"].encode("utf-8")
                    ).hexdigest(),
                    "cited_source_ids": sorted(claim["source_ids"]),
                    "reviewed_source_ids": sorted(claim["source_ids"]),
                    "entailment_pass": True,
                    "reviewers": reviewer_rows,
                }
                review["review_sha256"] = canonical_sha256(review)
                citation_reviews.append(review)

        claim_bundle_rows = []
        for annotation in annotations:
            analyst = responses[
                (annotation["current_packet_id"], "analyst")
            ]
            for claim in analyst["claims"]:
                if claim["materiality"] in {"medium", "high"}:
                    claim_bundle_rows.append(
                        {
                            "case_id": annotation["case_id"],
                            "replay_packet_id": annotation[
                                "current_packet_id"
                            ],
                            "runtime_packet_id": analyst["packet_id"],
                            "claim_id": claim["claim_id"],
                            "claim_text_sha256": hashlib.sha256(
                                claim["claim"].encode("utf-8")
                            ).hexdigest(),
                            "cited_source_ids": sorted(
                                claim["source_ids"]
                            ),
                            "materiality": claim["materiality"],
                        }
                    )
        claim_bundle_sha = canonical_sha256(
            sorted(
                claim_bundle_rows,
                key=lambda row: (row["case_id"], row["claim_id"]),
            )
        )
        citation_review_payload: dict[str, Any] = {
            "schema_version": CITATION_REVIEW_SET_SCHEMA_VERSION,
            "generated_at": "2026-07-24T12:15:00+00:00",
            "corpus_manifest_sha256": cls.corpus.manifest_sha256,
            "annotation_set_sha256": cls.annotation_binding[
                "annotation_set_sha256"
            ],
            "claim_evidence_bundle_sha256": claim_bundle_sha,
            "frozen": True,
            "review_method": "independent_dual_human_review",
            "records": citation_reviews,
        }
        citation_review_payload["review_set_sha256"] = canonical_sha256(
            citation_review_payload
        )
        citation_review_file_sha = _write_json(
            cls.citation_review_path,
            citation_review_payload,
        )
        citation_review_binding = {
            "review_file_sha256": citation_review_file_sha,
            "review_set_sha256": citation_review_payload[
                "review_set_sha256"
            ],
            "claim_evidence_bundle_sha256": claim_bundle_sha,
            "review_count": len(citation_reviews),
            "frozen": True,
            "review_method": "independent_dual_human_review",
            "independent_dual_review": True,
        }

        critic_control_results: list[dict[str, Any]] = []
        for index, control in enumerate(critic_control_cases(annotations)):
            packet_id = control["packet_id"]
            binding = bindings[packet_id]
            analyst = responses[(packet_id, "analyst")]
            committee = responses[(packet_id, "committee")]
            expected_verdict = (
                "reject"
                if control["proposal_kind"] == "faulty"
                else "approve"
            )
            critic_response = {
                "schema_version": CRITIC_CONTROL_SCHEMA_VERSION,
                "control_id": control["control_id"],
                "packet_id": binding.runtime_packet["packet_id"],
                "verdict": expected_verdict,
                "issues": (
                    ["The proposal contains an unknown citation."]
                    if expected_verdict == "reject"
                    else []
                ),
                "approved_source_ids": (
                    committee["ticker_decisions"][0]["source_ids"]
                    if expected_verdict == "approve"
                    else []
                ),
                "automatic_action_allowed": False,
            }
            relative_path = f"critic-controls/{index:03d}.json"
            file_sha = _write_json(
                cls.report_root / relative_path,
                critic_response,
            )
            input_payload = critic_control_input(
                control=control,
                binding=binding,
                analyst=analyst,
                committee=committee,
            )
            critic_config = cls.registry["roles"]["critic"]
            critic_control_results.append(
                {
                    "control_id": control["control_id"],
                    "case_id": control["case_id"],
                    "packet_id": packet_id,
                    "proposal_kind": control["proposal_kind"],
                    "provider_call_id": f"critic-control:{index:03d}",
                    "transport": "codex_cli",
                    "model": critic_config["model"],
                    "reasoning_effort": critic_config[
                        "reasoning_effort"
                    ],
                    "prompt_version": CRITIC_CONTROL_PROMPT_VERSION,
                    "response_schema_version": (
                        CRITIC_CONTROL_SCHEMA_VERSION
                    ),
                    "input_sha256": canonical_sha256(input_payload),
                    "output_sha256": canonical_sha256(critic_response),
                    "response_relative_path": relative_path,
                    "response_file_sha256": file_sha,
                    "response_validated": True,
                    "credential_read": False,
                    "tools_enabled": False,
                    "violations": _zero_violations(),
                    "expected_verdict": expected_verdict,
                    "verdict_match": True,
                }
            )

        counterfactual_results: list[dict[str, Any]] = []
        transition_cases_by_id = {
            case["case_id"]: case for case in transition_cases
        }
        for index, annotation in enumerate(annotations):
            case = transition_cases_by_id[annotation["case_id"]]
            response = {
                "schema_version": TRANSITION_PAIR_SCHEMA_VERSION,
                "case_id": (
                    "counterfactual:"
                    f"{case['transition_fingerprint'][:20]}"
                ),
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "ticker": "TST",
                "classification": "abstain",
                "thesis_direction": "unchanged",
                "material_transition_detected": False,
                "rationale": (
                    "Removing decisive current evidence requires abstention."
                ),
                "evidence_source_ids": [],
                "confidence_pct": 100,
                "automatic_action_allowed": False,
            }
            relative_path = f"counterfactual/{index:03d}.json"
            file_sha = _write_json(
                cls.report_root / relative_path,
                response,
            )
            input_payload = counterfactual_transition_input(
                case=case,
                prior=bindings[case["prior_packet_id"]],
                current=bindings[case["current_packet_id"]],
                prior_analyst=responses[
                    (case["prior_packet_id"], "analyst")
                ],
                current_analyst=responses[
                    (case["current_packet_id"], "analyst")
                ],
            )
            counterfactual_results.append(
                {
                    "reference_case_id": case["case_id"],
                    "transition_fingerprint": case[
                        "transition_fingerprint"
                    ],
                    "prior_packet_id": case["prior_packet_id"],
                    "current_packet_id": case["current_packet_id"],
                    "provider_call_id": f"counterfactual:{index:03d}",
                    "transport": "codex_cli",
                    "model": committee_config["model"],
                    "reasoning_effort": committee_config[
                        "reasoning_effort"
                    ],
                    "prompt_version": COUNTERFACTUAL_PROMPT_VERSION,
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
                    "downgrade_or_abstain": True,
                }
            )
        extended_quality_summary = {
            "citation_review_set_binding": citation_review_binding,
            "citation_quality": {
                "review_count": 50,
                "material_claim_count": 50,
                "entailed_claim_count": 50,
                "entailment_wilson_95_pct": _wilson_interval_pct(
                    50, 50
                ),
                "citation_precision_pct": 100.0,
                "citation_recall_pct": 100.0,
                "thresholds": {
                    "minimum_reviews": 50,
                    "minimum_entailment_pct": 100.0,
                    "minimum_precision_pct": 95.0,
                    "minimum_recall_pct": 95.0,
                },
                "passed": True,
            },
            "critic_control_quality": {
                "control_count": 50,
                "faulty_proposal_count": 25,
                "faulty_proposal_catch_count": 25,
                "valid_proposal_count": 25,
                "valid_proposal_approval_count": 25,
                "false_veto_count": 0,
                "thresholds": {
                    "minimum_faulty_catch_pct": 100.0,
                    "maximum_false_veto_count": 0,
                },
                "passed": True,
            },
            "counterfactual_quality": {
                "case_count": 50,
                "downgrade_or_abstain_count": 50,
                "failure_count": 0,
                "thresholds": {
                    "minimum_cases": 50,
                    "minimum_downgrade_or_abstain_pct": 100.0,
                },
                "passed": True,
            },
            "holdout_quality": {
                "case_count": 40,
                "exact_classification_match_count": 40,
                "exact_classification_accuracy_pct": 100.0,
                "exact_classification_wilson_95_pct": (
                    _wilson_interval_pct(40, 40)
                ),
                "thesis_direction_match_count": 40,
                "thesis_direction_accuracy_pct": 100.0,
                "thesis_direction_wilson_95_pct": (
                    _wilson_interval_pct(40, 40)
                ),
                "brier_score": 0.04,
                "expected_calibration_error_pct": 20.0,
                "high_confidence_case_count": 40,
                "high_confidence_error_count": 0,
                "high_confidence_error_pct": 0.0,
                "thresholds": {
                    "minimum_exact_classification_accuracy_pct": 80.0,
                    "minimum_thesis_direction_accuracy_pct": 90.0,
                    "maximum_brier_score": 0.25,
                    "maximum_expected_calibration_error_pct": 20.0,
                    "maximum_high_confidence_error_pct": 10.0,
                },
                "passed": True,
            },
            "extended_quality_passed": True,
        }
        extended_quality = {
            "schema_version": EXTENDED_QUALITY_SCHEMA_VERSION,
            "frozen_split": copy.deepcopy(cls.frozen_split_fixture),
            "citation_review_set_binding": citation_review_binding,
            "citation_entailment_reviews": citation_reviews,
            "critic_control_results": critic_control_results,
            "counterfactual_results": counterfactual_results,
            "summary": extended_quality_summary,
        }
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
            "exact_classification_wilson_95_pct": _wilson_interval_pct(
                50, 50
            ),
            "thesis_direction_match_count": 50,
            "thesis_direction_accuracy_pct": 100.0,
            "thesis_direction_wilson_95_pct": _wilson_interval_pct(
                50, 50
            ),
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
            "fail_closed_wilson_95_pct": _wilson_interval_pct(50, 50),
            "unsafe_outcome_count": 0,
            "thresholds": {"minimum_fail_closed_pct": 95.0},
            "passed": True,
        }
        cls.bindings = bindings
        report = {
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
            "runtime_code_sha256": replay_runtime_code_hashes(),
            "annotation_set_binding": copy.deepcopy(
                cls.annotation_binding
            ),
            "provider_transport": {
                "provider": "codex_cli_external_auth",
                "transport": "codex_cli",
                "external_provider": True,
                "fixture": False,
                "simulated": False,
                "tools_enabled": False,
                "credentials_read_by_repository": False,
                "stateless": True,
                "successful_role_results_reused": True,
                "maximum_live_attempts_per_role": 2,
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
            "extended_quality": extended_quality,
            "summary": {
                "packet_count": 250,
                "source_identity_count": 250,
                "accession_count": 250,
                "role_result_count": 750,
                "transition_pair_result_count": 50,
                "negative_control_result_count": 50,
                "adversarial_probe_result_count": 50,
                "stability_trial_count": 40,
                "extended_quality_call_count": 100,
                "total_provider_call_count": 1040,
                "validated_response_count": 1040,
                "material_transition_count": 50,
                "violation_totals": _zero_violations(),
                "runtime_committee_quality": {
                    "annotated_current_packet_count": 50,
                    "exact_classification_match_count": 50,
                    "exact_classification_accuracy_pct": 100.0,
                    "exact_classification_wilson_95_pct": (
                        _wilson_interval_pct(50, 50)
                    ),
                    "thesis_direction_match_count": 50,
                    "thesis_direction_accuracy_pct": 100.0,
                    "thesis_direction_wilson_95_pct": (
                        _wilson_interval_pct(50, 50)
                    ),
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
                },
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
                "extended_quality": extended_quality_summary,
                "quality_gate_passed": True,
            },
        }
        cls._write_execution_fixture(report)
        return report

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
        citation_review_set_path: Path | None = None,
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
            annotation_set_path=self.annotation_path,
            citation_review_set_path=(
                citation_review_set_path or self.citation_review_path
            ),
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
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual(result["packet_count"], 250)
        self.assertEqual(result["material_transition_count"], 50)
        self.assertEqual(result["external_provider_transport"], "codex_cli")
        self.assertFalse(result["provider_invoked_by_verifier"])
        self.assertFalse(result["network_invoked_by_verifier"])
        self.assertFalse(result["email_invoked"])
        self.assertFalse(result["c7_invoked"])
        self.assertFalse(result["files_written"])
        self.assertFalse(result["live_inference_unlock"])

    def test_provider_gate_rejects_evidence_freshness_code_tamper(
        self,
    ) -> None:
        target_name = "phase5r_evidence_freshness.py"
        original_path = next(
            path
            for path in provider_gate_runtime.RUNTIME_EVALUATION_CODE_PATHS
            if path.name == target_name
        )
        tampered_path = self.root / "replay-tamper" / target_name
        _write_bytes(
            tampered_path,
            original_path.read_bytes() + b"\n# replay freshness tamper\n",
        )
        patched_paths = tuple(
            tampered_path if path.name == target_name else path
            for path in provider_gate_runtime.RUNTIME_EVALUATION_CODE_PATHS
        )
        with mock.patch.object(
            provider_gate_runtime,
            "RUNTIME_EVALUATION_CODE_PATHS",
            patched_paths,
        ):
            result = self._verify()
        self.assertFalse(result["passed"])
        self.assertIn(
            "provider report replay/runtime code hashes are stale",
            result["issues"][0],
        )

    def test_synthetic_fake_cik_text_corpus_fails_strict_prerequisite(
        self,
    ) -> None:
        with mock.patch(
            "verify_phase5r_llm_provider_replay_gate."
            "verify_strict_replay_corpus",
            side_effect=strict_replay_corpus.verify_corpus,
        ):
            result = verify_provider_replay_gate(
                manifest_path=self.manifest_path,
                provider_report_path=self.report_path,
                model_registry_path=self.registry_path,
                annotation_set_path=self.annotation_path,
                citation_review_set_path=self.citation_review_path,
            )
        self.assertFalse(result["passed"])
        self.assertIn(
            "strict replay corpus verification failed: "
            "manifest ledger provenance mismatch",
            result["issues"][0],
        )
        self.assertFalse(result["network_invoked_by_verifier"])
        self.assertFalse(result["files_written"])

    def test_registry_cannot_lower_packet_or_issuer_hard_floors(
        self,
    ) -> None:
        cases = (
            (
                "minimum_replay_packets",
                249,
                "registry minimum replay packets is below the hard corpus floor",
            ),
            (
                "minimum_replay_issuers",
                19,
                "registry minimum replay issuers is below the hard corpus floor",
            ),
        )
        for field, value, expected_issue in cases:
            with self.subTest(field=field):
                registry = copy.deepcopy(self.registry)
                registry["promotion_requirements"][field] = value
                registry_path = (
                    self.root / f"registry-{field}-{uuid.uuid4().hex}.json"
                )
                _write_json(registry_path, registry)
                result = verify_provider_replay_gate(
                    manifest_path=self.manifest_path,
                    provider_report_path=self.report_path,
                    model_registry_path=registry_path,
                    annotation_set_path=self.annotation_path,
                    citation_review_set_path=self.citation_review_path,
                )
                self.assertFalse(result["passed"])
                self.assertIn(expected_issue, result["issues"][0])

    def test_manifest_cannot_declare_stale_hard_minimums(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["requirements"][
            "minimum_real_point_in_time_packets"
        ] = 249
        manifest_path = (
            self.corpus_root / f"manifest-stale-{uuid.uuid4().hex}.json"
        )
        _write_json(manifest_path, manifest)
        with self.assertRaisesRegex(
            ReplayGateError,
            "manifest hard minimum declarations are stale",
        ):
            _load_corpus(
                manifest_path,
                minimum_packets=250,
                minimum_issuers=20,
            )

    def test_tampered_physical_attempt_ledger_fails_gate(self) -> None:
        ledger_path = (
            self.report_root
            / "phase5r_llm_provider_replay_execution_ledger.json"
        )
        original = ledger_path.read_bytes()
        ledger = json.loads(original)
        ledger["budget"]["physical_attempt_count"] += 1
        try:
            _write_json(ledger_path, ledger)
            result = self._verify()
        finally:
            ledger_path.write_bytes(original)
        self.assertFalse(result["passed"])
        self.assertIn("raw hash mismatch", result["issues"][0])

    def test_missing_physical_attempt_receipt_fails_gate(self) -> None:
        receipt_path = next(
            (self.report_root / "attempt_receipts").glob("*.json")
        )
        held_path = receipt_path.with_suffix(".held")
        receipt_path.rename(held_path)
        try:
            result = self._verify()
        finally:
            held_path.rename(receipt_path)
        self.assertFalse(result["passed"])
        self.assertIn("receipt", result["issues"][0])

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
                "rationale": "The fabricated locator is intentionally invalid.",
                "fact_type": "fact",
                "evidence_origin": "management_reported",
                "unit": "not_applicable",
                "period": "long_term",
                "source_ids": ["sec-primary:unknown-accession"],
                "cited_excerpt_sha256": ["0" * 64],
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
        self.assertIn("unknown source", result["issues"][0])

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
        self.assertIn("ticker coverage", result["issues"][0])

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

    def test_tampered_frozen_transition_split_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["extended_quality"]["frozen_split"][
            "holdout_case_ids"
        ].pop()
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn(
            "dev/holdout split is stale",
            result["issues"][0],
        )

    def test_missing_negative_control_fails_named_gate(self) -> None:
        report = copy.deepcopy(self.report)
        report["negative_control_results"].pop()
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("missing-negative-control gate", result["issues"][0])

    def test_counterfactual_comparison_field_cannot_be_forged(self) -> None:
        report = copy.deepcopy(self.report)
        report["extended_quality"]["counterfactual_results"][0][
            "downgrade_or_abstain"
        ] = False
        result = self._verify(report=report)
        self.assertFalse(result["passed"])
        self.assertIn("counterfactual result is forged", result["issues"][0])

    def test_counterfactual_prunes_calculations_bound_to_removed_source(
        self,
    ) -> None:
        case = next(
            row
            for row in self.manifest["cases"]
            if row["case_kind"] == "material_transition_detection_probe"
        )
        prior = copy.deepcopy(self.bindings[case["prior_packet_id"]])
        current = copy.deepcopy(self.bindings[case["current_packet_id"]])
        source_id = current.runtime_packet["source_catalog"][0]["source_id"]
        current.runtime_packet["calculations"] = [
            {
                "calculation_id": "calc:removed-source",
                "ticker": "TST",
                "metric": "synthetic_replay_metric",
                "value": "1",
                "recomputed_value": "1",
                "unit": "ratio",
                "period": "long_term",
                "formula": "one",
                "source_ids": [source_id],
                "inputs": [],
                "reconciled": True,
            }
        ]
        unsigned_packet = copy.deepcopy(current.runtime_packet)
        unsigned_packet.pop("packet_id")
        current.runtime_packet["packet_id"] = canonical_sha256(
            unsigned_packet
        )

        def analyst_for(packet_id: str) -> dict[str, Any]:
            result = next(
                row
                for row in self.report["results"]
                if row["packet_id"] == packet_id
                and row["role"] == "analyst"
            )
            return json.loads(
                (
                    self.report_root / result["response_relative_path"]
                ).read_text(encoding="utf-8")
            )

        payload = counterfactual_transition_input(
            case=case,
            prior=prior,
            current=current,
            prior_analyst=analyst_for(case["prior_packet_id"]),
            current_analyst=analyst_for(case["current_packet_id"]),
        )
        self.assertEqual(
            payload["current_counterfactual"]["packet"]["calculations"],
            [],
        )
        for receipt in payload["current_counterfactual"]["packet"][
            "evidence_freshness"
        ]:
            self.assertNotIn(
                source_id,
                receipt["durable_sec_source_ids"],
            )

    def test_citation_review_file_tamper_fails(self) -> None:
        payload = json.loads(
            self.citation_review_path.read_text(encoding="utf-8")
        )
        payload["records"][0]["reviewers"][0]["rationale"] += " tampered"
        path = self.root / f"citation-review-tamper-{uuid.uuid4().hex}.json"
        _write_json(path, payload)
        result = self._verify(citation_review_set_path=path)
        self.assertFalse(result["passed"])
        self.assertIn("review-set", result["issues"][0])

    def test_activation_receipt_binds_code_and_human_reviews(self) -> None:
        gate_result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(gate_result["passed"], gate_result["issues"])
        evaluated_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        receipt, target = build_activation_receipt(
            evaluated_registry=evaluated_registry,
            evaluated_registry_raw=self.registry_path.read_bytes(),
            corpus_manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
            activated_at="2026-07-24T13:00:00+00:00",
            provider_gate_result=gate_result,
        )
        target_path = self.root / f"target-{uuid.uuid4().hex}.json"
        receipt_path = self.root / f"receipt-{uuid.uuid4().hex}.json"
        _write_json(target_path, target)
        _write_json(receipt_path, receipt)
        verified = verify_active_activation_receipt(
            registry_path=target_path,
            receipt_path=receipt_path,
            corpus_manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(verified["passed"], verified.get("issues"))

    def test_activation_rejects_artifact_race_after_gate(self) -> None:
        gate_result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(gate_result["passed"], gate_result["issues"])
        self.report_path.write_text(
            self.report_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
        evaluated_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(
            ActivationReceiptError,
            "changed after the provider gate",
        ):
            build_activation_receipt(
                evaluated_registry=evaluated_registry,
                evaluated_registry_raw=self.registry_path.read_bytes(),
                corpus_manifest_path=self.manifest_path,
                provider_report_path=self.report_path,
                annotation_set_path=self.annotation_path,
                citation_review_set_path=self.citation_review_path,
                activated_at="2026-07-24T13:00:00+00:00",
                provider_gate_result=gate_result,
            )

    def test_activation_rejects_provider_response_child_race(self) -> None:
        gate_result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(gate_result["passed"], gate_result["issues"])
        response_path = (
            self.report_root
            / self.report["results"][0]["response_relative_path"]
        )
        original = response_path.read_bytes()
        response_path.write_bytes(original + b" ")
        try:
            evaluated_registry = json.loads(
                self.registry_path.read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(
                ActivationReceiptError,
                "provider_responses changed",
            ):
                build_activation_receipt(
                    evaluated_registry=evaluated_registry,
                    evaluated_registry_raw=self.registry_path.read_bytes(),
                    corpus_manifest_path=self.manifest_path,
                    provider_report_path=self.report_path,
                    annotation_set_path=self.annotation_path,
                    citation_review_set_path=self.citation_review_path,
                    activated_at="2026-07-24T13:00:00+00:00",
                    provider_gate_result=gate_result,
                )
        finally:
            response_path.write_bytes(original)

    def test_activation_rejects_corpus_child_race(self) -> None:
        gate_result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(gate_result["passed"], gate_result["issues"])
        packet_path = (
            self.manifest_path.parent
            / self.manifest["packets"][0]["relative_path"]
        )
        original = packet_path.read_bytes()
        packet_path.write_bytes(original + b" ")
        try:
            evaluated_registry = json.loads(
                self.registry_path.read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(
                ActivationReceiptError,
                "corpus changed",
            ):
                build_activation_receipt(
                    evaluated_registry=evaluated_registry,
                    evaluated_registry_raw=self.registry_path.read_bytes(),
                    corpus_manifest_path=self.manifest_path,
                    provider_report_path=self.report_path,
                    annotation_set_path=self.annotation_path,
                    citation_review_set_path=self.citation_review_path,
                    activated_at="2026-07-24T13:00:00+00:00",
                    provider_gate_result=gate_result,
                )
        finally:
            packet_path.write_bytes(original)

    def test_active_receipt_revalidates_transitive_response_child(
        self,
    ) -> None:
        gate_result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(gate_result["passed"], gate_result["issues"])
        evaluated_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        receipt, target = build_activation_receipt(
            evaluated_registry=evaluated_registry,
            evaluated_registry_raw=self.registry_path.read_bytes(),
            corpus_manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
            activated_at="2026-07-24T13:00:00+00:00",
            provider_gate_result=gate_result,
        )
        target_path = self.root / f"target-{uuid.uuid4().hex}.json"
        receipt_path = self.root / f"receipt-{uuid.uuid4().hex}.json"
        _write_json(target_path, target)
        _write_json(receipt_path, receipt)
        response_path = (
            self.report_root
            / self.report["results"][0]["response_relative_path"]
        )
        original = response_path.read_bytes()
        response_path.write_bytes(original + b" ")
        try:
            verified = verify_active_activation_receipt(
                registry_path=target_path,
                receipt_path=receipt_path,
                corpus_manifest_path=self.manifest_path,
                provider_report_path=self.report_path,
                annotation_set_path=self.annotation_path,
                citation_review_set_path=self.citation_review_path,
            )
            self.assertFalse(verified["passed"])
            self.assertIn("provider_responses changed", verified["issues"][0])
        finally:
            response_path.write_bytes(original)

    def test_active_receipt_revalidates_physical_attempt_ledger(
        self,
    ) -> None:
        gate_result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(gate_result["passed"], gate_result["issues"])
        evaluated_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        receipt, target = build_activation_receipt(
            evaluated_registry=evaluated_registry,
            evaluated_registry_raw=self.registry_path.read_bytes(),
            corpus_manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
            activated_at="2026-07-24T13:00:00+00:00",
            provider_gate_result=gate_result,
        )
        target_path = self.root / f"target-{uuid.uuid4().hex}.json"
        receipt_path = self.root / f"receipt-{uuid.uuid4().hex}.json"
        _write_json(target_path, target)
        _write_json(receipt_path, receipt)
        ledger_path = (
            self.report_root
            / "phase5r_llm_provider_replay_execution_ledger.json"
        )
        original = ledger_path.read_bytes()
        ledger_path.write_bytes(original + b" ")
        try:
            verified = verify_active_activation_receipt(
                registry_path=target_path,
                receipt_path=receipt_path,
                corpus_manifest_path=self.manifest_path,
                provider_report_path=self.report_path,
                annotation_set_path=self.annotation_path,
                citation_review_set_path=self.citation_review_path,
            )
            self.assertFalse(verified["passed"])
            self.assertIn(
                "provider_responses changed",
                verified["issues"][0],
            )
        finally:
            ledger_path.write_bytes(original)

    def test_active_receipt_binds_evidence_freshness_target_bytes(
        self,
    ) -> None:
        gate_result = verify_provider_replay_gate(
            manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            model_registry_path=self.registry_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
        )
        self.assertTrue(gate_result["passed"], gate_result["issues"])
        evaluated_registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        receipt, target = build_activation_receipt(
            evaluated_registry=evaluated_registry,
            evaluated_registry_raw=self.registry_path.read_bytes(),
            corpus_manifest_path=self.manifest_path,
            provider_report_path=self.report_path,
            annotation_set_path=self.annotation_path,
            citation_review_set_path=self.citation_review_path,
            activated_at="2026-07-24T13:00:00+00:00",
            provider_gate_result=gate_result,
        )
        target_path = self.root / f"target-{uuid.uuid4().hex}.json"
        receipt_path = self.root / f"receipt-{uuid.uuid4().hex}.json"
        _write_json(target_path, target)
        _write_json(receipt_path, receipt)
        target_name = "phase5r_evidence_freshness.py"
        original_path = next(
            path
            for path in activation_receipt_runtime.RUNTIME_CODE_PATHS
            if path.name == target_name
        )
        tampered_path = self.root / "canonical-tamper" / target_name
        _write_bytes(
            tampered_path,
            original_path.read_bytes() + b"\n# canonical boundary tamper\n",
        )
        patched_paths = tuple(
            tampered_path if path.name == target_name else path
            for path in activation_receipt_runtime.RUNTIME_CODE_PATHS
        )
        with mock.patch.object(
            activation_receipt_runtime,
            "RUNTIME_CODE_PATHS",
            patched_paths,
        ):
            verified = verify_active_activation_receipt(
                registry_path=target_path,
                receipt_path=receipt_path,
                corpus_manifest_path=self.manifest_path,
                provider_report_path=self.report_path,
                annotation_set_path=self.annotation_path,
                citation_review_set_path=self.citation_review_path,
            )
        self.assertFalse(verified["passed"])
        self.assertIn(
            "activation runtime code hashes are stale",
            verified["issues"][0],
        )


if __name__ == "__main__":
    unittest.main()
