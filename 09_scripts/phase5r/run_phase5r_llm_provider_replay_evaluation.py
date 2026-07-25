#!/usr/bin/env python3
"""Run the controlled external-provider replay evaluation.

The default mode is a read-only readiness check.  External inference requires
an explicit acknowledgement, an exact call ceiling, an explicit estimated USD
ceiling, and the raw SHA-256 of a separately frozen dual-review annotation
file.  Responses are staged outside every canonical/email path and are
published only after the offline provider replay verifier accepts the complete
report.

This program cannot send email, run C7, read SMTP configuration, connect to a
broker, create an order, or affect a canonical decision.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

from phase5r_daily_common import ROOT, iso_now
from phase5r_llm_contract import (
    ContractError,
    RESEARCH_CLASSIFICATIONS,
    response_schema,
    validate_schema,
)
from phase5r_llm_provider import (
    CodexCliProvider,
    ModelProvider,
    ProviderError,
    ProviderResult,
)
from phase5r_llm_transition_annotations import (
    DEFAULT_ANNOTATION_PATH,
    AnnotationError,
    validate_annotation_set,
)
from verify_phase5r_llm_provider_replay_gate import (
    ADVERSARIAL_PROBE_INSTRUCTIONS,
    ADVERSARIAL_PROBE_SCHEMA,
    ADVERSARIAL_PROMPT_VERSION,
    ADVERSARIAL_SCHEMA_VERSION,
    CORPUS_MANIFEST_PATH,
    MANIFEST_SCHEMA_VERSION,
    MINIMUM_ADVERSARIAL_FAIL_CLOSED_PCT,
    MINIMUM_CITATION_JACCARD,
    MINIMUM_CLASSIFICATION_AGREEMENT_PCT,
    MINIMUM_MATERIAL_TRANSITIONS,
    MINIMUM_REAL_PACKETS,
    MINIMUM_STABILITY_PACKETS,
    MINIMUM_STABILITY_TRIALS_PER_PACKET,
    MINIMUM_TRANSITION_CLASSIFICATION_ACCURACY_PCT,
    MINIMUM_TRANSITION_DIRECTION_ACCURACY_PCT,
    MAXIMUM_TRANSITION_ABSTENTION_PCT,
    MODEL_REGISTRY_PATH,
    PROVIDER_REPORT_PATH,
    REPORT_SCHEMA_VERSION,
    REQUIRED_ROLES,
    ROLE_INSTRUCTIONS,
    ROLE_SCHEMA_VERSIONS,
    TRANSITION_PAIR_INSTRUCTIONS,
    TRANSITION_PAIR_PROMPT_VERSION,
    TRANSITION_PAIR_SCHEMA,
    TRANSITION_PAIR_SCHEMA_VERSION,
    VIOLATION_CATEGORIES,
    ReplayGateError,
    _assert_no_imperative_action_language,
    _assert_no_sensitive_markers,
    _expected_role_bindings,
    _load_corpus,
    _load_registry,
    _runtime_committee_quality,
    _unsafe_opposite_direction,
    _validate_primary_response_semantics,
    _validate_reference_set,
    _validate_transition_pair_response,
    adversarial_probe_input,
    canonical_sha256,
    replay_primary_inputs,
    sha256_bytes,
    transition_pair_input,
    verify_provider_replay_gate,
)


DEFAULT_OUTPUT_ROOT = PROVIDER_REPORT_PATH.parent
REPORT_NAME = PROVIDER_REPORT_PATH.name
EXECUTION_LEDGER_NAME = "phase5r_llm_provider_replay_execution_ledger.json"
OUTPUT_PARENT = ROOT / "08_reviews" / "phase5r_llm_provider_replay"
TRANSPORT = "codex_cli"


class ReplayRunError(RuntimeError):
    """A replay preflight, call, validation, budget, or publication failed."""


@dataclass(frozen=True)
class ReplayPlan:
    packet_count: int
    annotation_count: int
    adversarial_probe_count: int
    stability_transition_count: int
    stability_trials_per_transition: int

    @property
    def primary_call_count(self) -> int:
        return self.packet_count * len(REQUIRED_ROLES)

    @property
    def transition_pair_call_count(self) -> int:
        return self.annotation_count

    @property
    def adversarial_call_count(self) -> int:
        return self.adversarial_probe_count

    @property
    def stability_call_count(self) -> int:
        return (
            self.stability_transition_count
            * self.stability_trials_per_transition
        )

    @property
    def total_call_count(self) -> int:
        return (
            self.primary_call_count
            + self.transition_pair_call_count
            + self.adversarial_call_count
            + self.stability_call_count
        )


@dataclass
class CallBudget:
    exact_maximum_calls: int
    max_estimated_usd: Decimal
    estimated_usd_per_call: Decimal
    planned_calls: int
    used_calls: int = 0

    def validate(self) -> None:
        if (
            isinstance(self.exact_maximum_calls, bool)
            or self.exact_maximum_calls <= 0
            or self.exact_maximum_calls != self.planned_calls
        ):
            raise ReplayRunError(
                "exact maximum-call budget must equal the frozen replay plan"
            )
        if (
            not self.max_estimated_usd.is_finite()
            or not self.estimated_usd_per_call.is_finite()
            or self.max_estimated_usd <= 0
            or self.estimated_usd_per_call <= 0
        ):
            raise ReplayRunError("estimated USD budget values must be finite and positive")
        if self.estimated_total_usd > self.max_estimated_usd:
            raise ReplayRunError("estimated replay cost exceeds the explicit USD ceiling")

    @property
    def estimated_total_usd(self) -> Decimal:
        return self.estimated_usd_per_call * self.planned_calls

    def consume(self) -> int:
        if self.used_calls >= self.exact_maximum_calls:
            raise ReplayRunError("provider call budget exhausted before invocation")
        self.used_calls += 1
        return self.used_calls


@dataclass(frozen=True)
class ReplayInputs:
    registry: dict[str, Any]
    registry_sha256: str
    corpus: Any
    annotations: list[dict[str, Any]]
    annotation_metadata: dict[str, Any]
    plan: ReplayPlan


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("expected a decimal value") from exc
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("decimal value must be finite")
    return parsed


def _zero_violations() -> dict[str, int]:
    return {category: 0 for category in VIOLATION_CATEGORIES}


def _safe_error(exc: Exception) -> str:
    """Return only a non-sensitive failure class and closed reason token."""

    if isinstance(
        exc,
        (
            ReplayRunError,
            AnnotationError,
            ReplayGateError,
            ContractError,
            ProviderError,
        ),
    ):
        rendered = str(exc)
        if rendered and len(rendered) <= 240 and "\n" not in rendered:
            return rendered
    return f"{type(exc).__name__}:fail_closed"


def _selected_annotations(
    annotations: list[dict[str, Any]],
    *,
    required_count: int,
) -> list[dict[str, Any]]:
    ordered = sorted(annotations, key=lambda row: str(row["case_id"]))
    if len(ordered) < required_count:
        raise ReplayRunError("frozen dual-review annotation minimum is unmet")
    return ordered[:required_count]


def load_replay_inputs(
    *,
    manifest_path: Path,
    annotation_path: Path,
    model_registry_path: Path,
    expected_annotation_file_sha256: str | None = None,
    minimum_packets: int | None = None,
    minimum_transitions: int | None = None,
    stability_transition_count: int = MINIMUM_STABILITY_PACKETS,
    stability_trials_per_transition: int = (
        MINIMUM_STABILITY_TRIALS_PER_PACKET
    ),
) -> ReplayInputs:
    registry, registry_sha = _load_registry(model_registry_path)
    promotion = registry["promotion_requirements"]
    required_packets = max(
        MINIMUM_REAL_PACKETS if minimum_packets is None else minimum_packets,
        int(promotion["minimum_replay_packets"]),
    )
    required_transitions = max(
        (
            MINIMUM_MATERIAL_TRANSITIONS
            if minimum_transitions is None
            else minimum_transitions
        ),
        int(promotion["minimum_material_transition_cases"]),
    )
    corpus = _load_corpus(manifest_path, minimum_packets=required_packets)
    annotations, annotation_metadata = validate_annotation_set(
        annotation_path=annotation_path,
        corpus=corpus,
        expected_file_sha256=expected_annotation_file_sha256,
        minimum_transitions=required_transitions,
    )
    selected = _selected_annotations(
        annotations,
        required_count=required_transitions,
    )
    if len(corpus.adversarial_probes) < required_transitions:
        raise ReplayRunError("real corpus adversarial safety-probe minimum is unmet")
    if (
        stability_transition_count < 1
        or stability_trials_per_transition < 2
        or len(selected) < stability_transition_count
    ):
        raise ReplayRunError("stability replay sample is below its frozen minimum")
    plan = ReplayPlan(
        packet_count=len(corpus.packets),
        annotation_count=len(selected),
        adversarial_probe_count=len(corpus.adversarial_probes),
        stability_transition_count=stability_transition_count,
        stability_trials_per_transition=stability_trials_per_transition,
    )
    return ReplayInputs(
        registry=registry,
        registry_sha256=registry_sha,
        corpus=corpus,
        annotations=selected,
        annotation_metadata=annotation_metadata,
        plan=plan,
    )


def check_replay_readiness(
    *,
    manifest_path: Path = CORPUS_MANIFEST_PATH,
    annotation_path: Path = DEFAULT_ANNOTATION_PATH,
    model_registry_path: Path = MODEL_REGISTRY_PATH,
) -> dict[str, Any]:
    """Read-only check: no provider, network, authentication, or writes."""

    try:
        inputs = load_replay_inputs(
            manifest_path=manifest_path.expanduser().resolve(),
            annotation_path=annotation_path.expanduser().resolve(),
            model_registry_path=model_registry_path.expanduser().resolve(),
        )
    except (
        ReplayRunError,
        AnnotationError,
        ReplayGateError,
        ContractError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as exc:
        return {
            "ready": False,
            "issues": [_safe_error(exc)],
            "packet_count": 0,
            "annotation_count": 0,
            "adversarial_probe_count": 0,
            "planned_provider_calls": 0,
            "provider_invoked": False,
            "network_invoked": False,
            "files_written": False,
            "email_invoked": False,
            "c7_invoked": False,
            "broker_invoked": False,
            "order_invoked": False,
            "canonical_effect": False,
        }
    return {
        "ready": True,
        "issues": [],
        "packet_count": inputs.plan.packet_count,
        "annotation_count": inputs.plan.annotation_count,
        "adversarial_probe_count": inputs.plan.adversarial_probe_count,
        "planned_provider_calls": inputs.plan.total_call_count,
        "annotation_file_sha256": inputs.annotation_metadata[
            "annotation_file_sha256"
        ],
        "provider_invoked": False,
        "network_invoked": False,
        "files_written": False,
        "email_invoked": False,
        "c7_invoked": False,
        "broker_invoked": False,
        "order_invoked": False,
        "canonical_effect": False,
    }


def _validate_output_root(path: Path, *, allow_test_path: bool) -> Path:
    resolved = path.expanduser().resolve()
    if not allow_test_path:
        try:
            resolved.relative_to(OUTPUT_PARENT.resolve())
        except ValueError as exc:
            raise ReplayRunError(
                "provider replay output must stay under its isolated review root"
            ) from exc
    lowered = str(resolved).lower()
    if any(
        marker in lowered
        for marker in (
            "smtp",
            "email_delivery",
            "email_briefs",
            "launchagents",
            "broker",
            "orders",
        )
    ):
        raise ReplayRunError("provider replay output matches a prohibited path")
    if resolved.exists():
        raise ReplayRunError("provider replay output already exists; refusing overwrite")
    return resolved


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not hasattr(os, "O_NOFOLLOW"):
        raise ReplayRunError("O_NOFOLLOW is required for replay artifacts")
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
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
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha256_bytes(raw)


def _transport_metadata(
    metadata: dict[str, Any],
    *,
    role: str,
    model: str,
    reasoning_effort: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    registry: dict[str, Any],
) -> None:
    expected = {
        "transport": TRANSPORT,
        "role": role,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "input_sha256": canonical_sha256(input_payload),
        "output_sha256": canonical_sha256(output_payload),
        "credential_read": False,
        "tools_enabled": False,
    }
    for field, value in expected.items():
        if metadata.get(field) != value:
            raise ReplayRunError(f"provider metadata mismatch: {field}")
    executable_hash = metadata.get("executable_sha256")
    if (
        executable_hash is not None
        and executable_hash != registry["provider_executable_sha256"]
    ):
        raise ReplayRunError("provider executable metadata hash mismatch")


def _call_provider(
    provider: ModelProvider,
    budget: CallBudget,
    *,
    call_id: str,
    category: str,
    role: str,
    model: str,
    reasoning_effort: str,
    schema: dict[str, Any],
    instructions: str,
    input_payload: dict[str, Any],
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sequence = budget.consume()
    result: ProviderResult = provider.generate(
        role=role,
        model=model,
        reasoning_effort=reasoning_effort,
        schema=schema,
        instructions=instructions,
        input_payload=input_payload,
    )
    validate_schema(result.payload, schema)
    _transport_metadata(
        result.metadata,
        role=role,
        model=model,
        reasoning_effort=reasoning_effort,
        input_payload=input_payload,
        output_payload=result.payload,
        registry=registry,
    )
    ledger_row = {
        "sequence": sequence,
        "provider_call_id": call_id,
        "category": category,
        "role": role,
        "transport": TRANSPORT,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "input_sha256": canonical_sha256(input_payload),
        "output_sha256": canonical_sha256(result.payload),
        "credential_read": False,
        "tools_enabled": False,
        "canonical_effect": False,
        "email_invoked": False,
        "c7_invoked": False,
        "broker_invoked": False,
        "order_invoked": False,
    }
    return result.payload, result.metadata, ledger_row


def _result_record(
    *,
    response_root: Path,
    relative_path: str,
    response: dict[str, Any],
    call_id: str,
    model: str,
    reasoning_effort: str,
    prompt_version: str,
    response_schema_version: str,
    input_payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    response_file_sha = _write_json_exclusive(
        response_root / relative_path,
        response,
    )
    common = {
        "provider_call_id": call_id,
        "transport": TRANSPORT,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "prompt_version": prompt_version,
        "response_schema_version": response_schema_version,
        "input_sha256": canonical_sha256(input_payload),
        "output_sha256": canonical_sha256(response),
        "response_relative_path": relative_path,
        "response_file_sha256": response_file_sha,
        "response_validated": True,
        "credential_read": False,
        "tools_enabled": False,
        "violations": _zero_violations(),
    }
    return common, response_file_sha


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def _transition_quality(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    count = len(rows)
    classification_matches = sum(
        1 for row in rows if row["classification_match"]
    )
    direction_matches = sum(
        1 for row in rows if row["thesis_direction_match"]
    )
    abstentions = sum(
        1 for row in rows if row["_response_classification"] == "abstain"
    )
    unsafe = sum(1 for row in rows if row["unsafe_opposite_direction"])
    classification_pct = round(100.0 * classification_matches / count, 4)
    direction_pct = round(100.0 * direction_matches / count, 4)
    abstention_pct = round(100.0 * abstentions / count, 4)
    passed = (
        classification_pct
        >= MINIMUM_TRANSITION_CLASSIFICATION_ACCURACY_PCT
        and direction_pct >= MINIMUM_TRANSITION_DIRECTION_ACCURACY_PCT
        and abstention_pct <= MAXIMUM_TRANSITION_ABSTENTION_PCT
        and unsafe == 0
    )
    if not passed:
        raise ReplayRunError("transition-pair quality thresholds are unmet")
    return {
        "annotated_case_count": count,
        "evaluated_case_count": count,
        "exact_classification_match_count": classification_matches,
        "exact_classification_accuracy_pct": classification_pct,
        "thesis_direction_match_count": direction_matches,
        "thesis_direction_accuracy_pct": direction_pct,
        "abstention_count": abstentions,
        "abstention_pct": abstention_pct,
        "unsafe_opposite_direction_count": unsafe,
        "thresholds": {
            "minimum_exact_classification_accuracy_pct": (
                MINIMUM_TRANSITION_CLASSIFICATION_ACCURACY_PCT
            ),
            "minimum_thesis_direction_accuracy_pct": (
                MINIMUM_TRANSITION_DIRECTION_ACCURACY_PCT
            ),
            "maximum_abstention_pct": MAXIMUM_TRANSITION_ABSTENTION_PCT,
            "maximum_unsafe_opposite_direction_count": 0,
        },
        "passed": True,
    }


def _adversarial_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    safe_count = sum(1 for row in rows if row["safe_outcome_match"])
    safe_pct = round(100.0 * safe_count / total, 4)
    if safe_pct < MINIMUM_ADVERSARIAL_FAIL_CLOSED_PCT:
        raise ReplayRunError("adversarial fail-closed threshold is unmet")
    return {
        "probe_count": total,
        "safe_outcome_count": safe_count,
        "fail_closed_pct": safe_pct,
        "unsafe_outcome_count": total - safe_count,
        "thresholds": {
            "minimum_fail_closed_pct": MINIMUM_ADVERSARIAL_FAIL_CLOSED_PCT,
        },
        "passed": True,
    }


def _stability_quality(
    *,
    baseline_responses: dict[str, dict[str, Any]],
    trial_responses: dict[str, list[dict[str, Any]]],
    required_transitions: int,
    required_trials: int,
) -> dict[str, Any]:
    if (
        len(trial_responses) != required_transitions
        or any(len(rows) != required_trials for rows in trial_responses.values())
    ):
        raise ReplayRunError("stability call cardinality is incomplete")
    stable_groups = 0
    citation_scores: list[float] = []
    for case_id, rows in trial_responses.items():
        compared = [baseline_responses[case_id], *rows]
        outcomes = {
            (row["classification"], row["thesis_direction"])
            for row in compared
        }
        if len(outcomes) == 1:
            stable_groups += 1
        for left, right in combinations(compared, 2):
            citation_scores.append(
                _jaccard(
                    set(left["evidence_source_ids"]),
                    set(right["evidence_source_ids"]),
                )
            )
    agreement_pct = round(
        100.0 * stable_groups / required_transitions,
        4,
    )
    citation_mean = round(sum(citation_scores) / len(citation_scores), 4)
    if (
        agreement_pct < MINIMUM_CLASSIFICATION_AGREEMENT_PCT
        or citation_mean < MINIMUM_CITATION_JACCARD
    ):
        raise ReplayRunError("repeated transition stability thresholds are unmet")
    return {
        "repeated_transition_count": required_transitions,
        "trials_per_transition": required_trials,
        "classification_direction_agreement_pct": agreement_pct,
        "citation_jaccard_mean": citation_mean,
        "thresholds": {
            "required_repeated_transitions": required_transitions,
            "required_trials_per_transition": required_trials,
            "minimum_classification_direction_agreement_pct": (
                MINIMUM_CLASSIFICATION_AGREEMENT_PCT
            ),
            "minimum_citation_jaccard_mean": MINIMUM_CITATION_JACCARD,
        },
        "passed": True,
    }


def _primary_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    stage_root: Path,
    ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    responses: dict[tuple[str, str], dict[str, Any]] = {}
    for packet_id in sorted(inputs.corpus.packets):
        binding = inputs.corpus.packets[packet_id]
        analyst_placeholder: dict[str, Any] = {}
        committee_placeholder: dict[str, Any] = {}
        for role in REQUIRED_ROLES:
            role_inputs = replay_primary_inputs(
                binding,
                analyst_placeholder,
                committee_placeholder,
            )
            input_payload = role_inputs[role]
            config = inputs.registry["roles"][role]
            call_id = f"primary:{packet_id}:{role}"
            response, _, ledger_row = _call_provider(
                provider,
                budget,
                call_id=call_id,
                category="primary",
                role=role,
                model=config["model"],
                reasoning_effort=config["reasoning_effort"],
                schema=response_schema(role),
                instructions=ROLE_INSTRUCTIONS[role],
                input_payload=input_payload,
                registry=inputs.registry,
            )
            if response.get("packet_id") != binding.runtime_packet["packet_id"]:
                raise ReplayRunError(f"{role} response packet binding mismatch")
            if role == "analyst":
                analyst_placeholder = response
            elif role == "committee":
                committee_placeholder = response
            relative = f"responses/primary/{packet_id}-{role}.json"
            common, _ = _result_record(
                response_root=stage_root,
                relative_path=relative,
                response=response,
                call_id=call_id,
                model=config["model"],
                reasoning_effort=config["reasoning_effort"],
                prompt_version=config["prompt_version"],
                response_schema_version=ROLE_SCHEMA_VERSIONS[role],
                input_payload=input_payload,
            )
            results.append(
                {
                    "packet_id": packet_id,
                    "role": role,
                    **common,
                }
            )
            ledger_row["response_relative_path"] = relative
            ledger.append(ledger_row)
            responses[(packet_id, role)] = response
        _validate_primary_response_semantics(
            binding,
            analyst=responses[(packet_id, "analyst")],
            committee=responses[(packet_id, "committee")],
            critic=responses[(packet_id, "critic")],
        )
    return results, responses


def _transition_pair_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    stage_root: Path,
    primary_responses: dict[tuple[str, str], dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    config = inputs.registry["roles"]["committee"]
    annotations_by_case = {
        str(row["case_id"]): row for row in inputs.annotations
    }
    report_rows: list[dict[str, Any]] = []
    responses: dict[str, dict[str, Any]] = {}
    quality_rows: list[dict[str, Any]] = []
    for case_id in sorted(annotations_by_case):
        annotation = annotations_by_case[case_id]
        case = inputs.corpus.transitions[case_id]
        prior = inputs.corpus.packets[case["prior_packet_id"]]
        current = inputs.corpus.packets[case["current_packet_id"]]
        input_payload = transition_pair_input(
            case=case,
            prior=prior,
            current=current,
            prior_analyst=primary_responses[
                (case["prior_packet_id"], "analyst")
            ],
            current_analyst=primary_responses[
                (case["current_packet_id"], "analyst")
            ],
        )
        call_id = f"transition-pair:{case_id}"
        response, _, ledger_row = _call_provider(
            provider,
            budget,
            call_id=call_id,
            category="transition_pair",
            role="transition_pair",
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            schema=TRANSITION_PAIR_SCHEMA,
            instructions=TRANSITION_PAIR_INSTRUCTIONS,
            input_payload=input_payload,
            registry=inputs.registry,
        )
        _validate_transition_pair_response(
            response,
            case=case,
            prior=prior,
            current=current,
        )
        classification_match = (
            response["classification"]
            == annotation["reference_classification"]
        )
        direction_match = (
            response["thesis_direction"]
            == annotation["reference_thesis_direction"]
        )
        unsafe = _unsafe_opposite_direction(
            reference_classification=annotation["reference_classification"],
            reference_direction=annotation["reference_thesis_direction"],
            observed_classification=response["classification"],
            observed_direction=response["thesis_direction"],
        )
        relative = f"responses/transition_pairs/{case_id.replace(':', '-')}.json"
        common, _ = _result_record(
            response_root=stage_root,
            relative_path=relative,
            response=response,
            call_id=call_id,
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            prompt_version=TRANSITION_PAIR_PROMPT_VERSION,
            response_schema_version=TRANSITION_PAIR_SCHEMA_VERSION,
            input_payload=input_payload,
        )
        row = {
            "case_id": case_id,
            "transition_fingerprint": case["transition_fingerprint"],
            "prior_packet_id": case["prior_packet_id"],
            "current_packet_id": case["current_packet_id"],
            **common,
            "reference_classification": annotation[
                "reference_classification"
            ],
            "reference_thesis_direction": annotation[
                "reference_thesis_direction"
            ],
            "classification_match": classification_match,
            "thesis_direction_match": direction_match,
            "unsafe_opposite_direction": unsafe,
        }
        report_rows.append(row)
        quality_rows.append(
            {
                **row,
                "_response_classification": response["classification"],
            }
        )
        responses[case_id] = response
        ledger_row["response_relative_path"] = relative
        ledger.append(ledger_row)
    return report_rows, responses, _transition_quality(quality_rows)


def _adversarial_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    stage_root: Path,
    primary_responses: dict[tuple[str, str], dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = inputs.registry["roles"]["committee"]
    report_rows: list[dict[str, Any]] = []
    for case_id in sorted(inputs.corpus.adversarial_probes):
        case = inputs.corpus.adversarial_probes[case_id]
        base = inputs.corpus.packets[case["base_packet_id"]]
        input_payload = adversarial_probe_input(
            case=case,
            base=base,
            analyst=primary_responses[(case["base_packet_id"], "analyst")],
        )
        call_id = f"adversarial:{case_id}"
        response, _, ledger_row = _call_provider(
            provider,
            budget,
            call_id=call_id,
            category="adversarial_probe",
            role="adversarial_probe",
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            schema=ADVERSARIAL_PROBE_SCHEMA,
            instructions=ADVERSARIAL_PROBE_INSTRUCTIONS,
            input_payload=input_payload,
            registry=inputs.registry,
        )
        if (
            response.get("case_id") != case_id
            or response.get("base_packet_id") != case["base_packet_id"]
            or str(response.get("ticker", "")).upper()
            != base.ticker.upper()
        ):
            raise ReplayRunError("adversarial response identity mismatch")
        _validate_reference_set(
            response.get("evidence_source_ids"),
            known=set(base.source_ids),
            label="adversarial probe evidence",
        )
        _assert_no_sensitive_markers(response, "adversarial_probe")
        _assert_no_imperative_action_language(
            {
                "headline": response.get("rationale", ""),
                "decisive_advice": "",
                "long_term_portfolio_case": "",
                "dissent": [],
                "ticker_decisions": [],
            }
        )
        safe = (
            response["mutation_detected"] is True
            and response["safety_outcome"] in {"reject", "abstain"}
            and response["classification"] in {"reject", "abstain"}
        )
        relative = f"responses/adversarial/{case_id.replace(':', '-')}.json"
        common, _ = _result_record(
            response_root=stage_root,
            relative_path=relative,
            response=response,
            call_id=call_id,
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            prompt_version=ADVERSARIAL_PROMPT_VERSION,
            response_schema_version=ADVERSARIAL_SCHEMA_VERSION,
            input_payload=input_payload,
        )
        row = {
            "case_id": case_id,
            "base_packet_id": case["base_packet_id"],
            "synthetic_mutation": case["synthetic_mutation"],
            **common,
            "expected_safety_outcome": case["expected_safety_outcome"],
            "safe_outcome_match": safe,
        }
        report_rows.append(row)
        ledger_row["response_relative_path"] = relative
        ledger.append(ledger_row)
    return report_rows, _adversarial_quality(report_rows)


def _stability_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    stage_root: Path,
    primary_responses: dict[tuple[str, str], dict[str, Any]],
    baseline_responses: dict[str, dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = inputs.registry["roles"]["committee"]
    selected_case_ids = sorted(
        str(row["case_id"]) for row in inputs.annotations
    )[: inputs.plan.stability_transition_count]
    report_rows: list[dict[str, Any]] = []
    responses_by_case: dict[str, list[dict[str, Any]]] = {}
    for case_id in selected_case_ids:
        case = inputs.corpus.transitions[case_id]
        prior = inputs.corpus.packets[case["prior_packet_id"]]
        current = inputs.corpus.packets[case["current_packet_id"]]
        input_payload = transition_pair_input(
            case=case,
            prior=prior,
            current=current,
            prior_analyst=primary_responses[
                (case["prior_packet_id"], "analyst")
            ],
            current_analyst=primary_responses[
                (case["current_packet_id"], "analyst")
            ],
        )
        for trial_index in range(inputs.plan.stability_trials_per_transition):
            trial_id = f"stability:{case_id}:{trial_index + 1}"
            call_id = f"stability-call:{case_id}:{trial_index + 1}"
            response, _, ledger_row = _call_provider(
                provider,
                budget,
                call_id=call_id,
                category="stability_transition_pair",
                role="stability_transition_pair",
                model=config["model"],
                reasoning_effort=config["reasoning_effort"],
                schema=TRANSITION_PAIR_SCHEMA,
                instructions=TRANSITION_PAIR_INSTRUCTIONS,
                input_payload=input_payload,
                registry=inputs.registry,
            )
            _validate_transition_pair_response(
                response,
                case=case,
                prior=prior,
                current=current,
            )
            relative = (
                "responses/stability/"
                f"{case_id.replace(':', '-')}-trial-{trial_index + 1}.json"
            )
            common, _ = _result_record(
                response_root=stage_root,
                relative_path=relative,
                response=response,
                call_id=call_id,
                model=config["model"],
                reasoning_effort=config["reasoning_effort"],
                prompt_version=TRANSITION_PAIR_PROMPT_VERSION,
                response_schema_version=TRANSITION_PAIR_SCHEMA_VERSION,
                input_payload=input_payload,
            )
            report_rows.append(
                {
                    "case_id": case_id,
                    "transition_fingerprint": case[
                        "transition_fingerprint"
                    ],
                    "prior_packet_id": case["prior_packet_id"],
                    "current_packet_id": case["current_packet_id"],
                    "trial_id": trial_id,
                    **common,
                }
            )
            responses_by_case.setdefault(case_id, []).append(response)
            ledger_row["response_relative_path"] = relative
            ledger.append(ledger_row)
    quality = _stability_quality(
        baseline_responses=baseline_responses,
        trial_responses=responses_by_case,
        required_transitions=inputs.plan.stability_transition_count,
        required_trials=inputs.plan.stability_trials_per_transition,
    )
    return report_rows, quality


def _provider_transport(registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": registry["provider"],
        "transport": TRANSPORT,
        "external_provider": True,
        "fixture": False,
        "simulated": False,
        "tools_enabled": False,
        "credentials_read_by_repository": False,
        "stateless": True,
        "one_primary_call_per_unique_packet_role": True,
        "controlled_stability_repeats_separated": True,
        "provider_executable_sha256": registry[
            "provider_executable_sha256"
        ],
    }


def _report_boundaries() -> dict[str, bool]:
    return {
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
    }


def _build_external_provider(registry: dict[str, Any]) -> CodexCliProvider:
    if registry.get("provider") != "codex_cli_external_auth":
        raise ReplayRunError("only the registry-pinned Codex CLI provider is allowed")
    return CodexCliProvider(
        Path(str(registry["provider_executable"])),
        expected_sha256=str(registry["provider_executable_sha256"]),
    )


def execute_provider_replay(
    *,
    manifest_path: Path,
    annotation_path: Path,
    model_registry_path: Path,
    output_root: Path,
    acknowledge_external_inference: bool,
    annotation_file_sha256: str,
    exact_maximum_calls: int,
    max_estimated_usd: Decimal,
    estimated_usd_per_call: Decimal,
    provider: ModelProvider | None = None,
    allow_test_provider: bool = False,
    allow_test_path: bool = False,
    minimum_packets: int | None = None,
    minimum_transitions: int | None = None,
    stability_transition_count: int = MINIMUM_STABILITY_PACKETS,
    stability_trials_per_transition: int = (
        MINIMUM_STABILITY_TRIALS_PER_PACKET
    ),
    verifier: Callable[..., dict[str, Any]] = verify_provider_replay_gate,
) -> dict[str, Any]:
    """Run and atomically publish one hash-bound provider replay evaluation."""

    if acknowledge_external_inference is not True:
        raise ReplayRunError("external inference acknowledgement is required")
    resolved_manifest = manifest_path.expanduser().resolve()
    resolved_annotations = annotation_path.expanduser().resolve()
    resolved_registry = model_registry_path.expanduser().resolve()
    resolved_output = _validate_output_root(
        output_root,
        allow_test_path=allow_test_path,
    )
    inputs = load_replay_inputs(
        manifest_path=resolved_manifest,
        annotation_path=resolved_annotations,
        model_registry_path=resolved_registry,
        expected_annotation_file_sha256=annotation_file_sha256,
        minimum_packets=minimum_packets,
        minimum_transitions=minimum_transitions,
        stability_transition_count=stability_transition_count,
        stability_trials_per_transition=stability_trials_per_transition,
    )
    budget = CallBudget(
        exact_maximum_calls=exact_maximum_calls,
        max_estimated_usd=max_estimated_usd,
        estimated_usd_per_call=estimated_usd_per_call,
        planned_calls=inputs.plan.total_call_count,
    )
    budget.validate()
    if provider is not None and not allow_test_provider:
        raise ReplayRunError("injected providers are test-only")
    active_provider = provider or _build_external_provider(inputs.registry)

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(
        tempfile.mkdtemp(
            prefix=".phase5r-provider-replay-stage-",
            dir=resolved_output.parent,
        )
    ).resolve()
    published = False
    try:
        ledger: list[dict[str, Any]] = []
        primary_results, primary_responses = _primary_calls(
            provider=active_provider,
            budget=budget,
            inputs=inputs,
            stage_root=stage_root,
            ledger=ledger,
        )
        runtime_committee_quality = _runtime_committee_quality(
            annotations=inputs.annotations,
            primary_responses=primary_responses,
        )
        (
            transition_results,
            transition_responses,
            transition_quality,
        ) = _transition_pair_calls(
            provider=active_provider,
            budget=budget,
            inputs=inputs,
            stage_root=stage_root,
            primary_responses=primary_responses,
            ledger=ledger,
        )
        adversarial_results, adversarial_quality = _adversarial_calls(
            provider=active_provider,
            budget=budget,
            inputs=inputs,
            stage_root=stage_root,
            primary_responses=primary_responses,
            ledger=ledger,
        )
        stability_trials, stability_quality = _stability_calls(
            provider=active_provider,
            budget=budget,
            inputs=inputs,
            stage_root=stage_root,
            primary_responses=primary_responses,
            baseline_responses=transition_responses,
            ledger=ledger,
        )
        if (
            budget.used_calls != budget.planned_calls
            or len(ledger) != budget.planned_calls
        ):
            raise ReplayRunError("provider call ledger cardinality is incomplete")
        violation_totals = _zero_violations()
        total_calls = budget.used_calls
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": iso_now(),
            "corpus_manifest_sha256": inputs.corpus.manifest_sha256,
            "corpus_schema_version": MANIFEST_SCHEMA_VERSION,
            "model_registry_sha256": inputs.registry_sha256,
            "model_registry_schema_version": inputs.registry[
                "schema_version"
            ],
            "role_bindings": _expected_role_bindings(inputs.registry),
            "provider_transport": _provider_transport(inputs.registry),
            "boundaries": _report_boundaries(),
            "results": primary_results,
            "material_transition_annotations": inputs.annotations,
            "transition_pair_results": transition_results,
            "adversarial_probe_results": adversarial_results,
            "stability_trials": stability_trials,
            "summary": {
                "packet_count": inputs.plan.packet_count,
                "source_identity_count": inputs.corpus.source_identity_count,
                "accession_count": inputs.corpus.accession_count,
                "role_result_count": len(primary_results),
                "transition_pair_result_count": len(transition_results),
                "adversarial_probe_result_count": len(adversarial_results),
                "stability_trial_count": len(stability_trials),
                "total_provider_call_count": total_calls,
                "validated_response_count": total_calls,
                "material_transition_count": len(inputs.annotations),
                "violation_totals": violation_totals,
                "runtime_committee_quality": runtime_committee_quality,
                "transition_pair_quality": transition_quality,
                "adversarial_safety_quality": adversarial_quality,
                "stability": stability_quality,
                "quality_gate_passed": True,
            },
        }
        ledger_payload = {
            "schema_version": "phase5r_llm_provider_replay_execution_ledger_v1",
            "generated_at": iso_now(),
            "corpus_manifest_sha256": inputs.corpus.manifest_sha256,
            "model_registry_sha256": inputs.registry_sha256,
            "annotation_file_sha256": inputs.annotation_metadata[
                "annotation_file_sha256"
            ],
            "annotation_set_sha256": inputs.annotation_metadata[
                "annotation_set_sha256"
            ],
            "budget": {
                "exact_maximum_calls": budget.exact_maximum_calls,
                "planned_calls": budget.planned_calls,
                "used_calls": budget.used_calls,
                "estimated_usd_per_call": str(
                    budget.estimated_usd_per_call
                ),
                "estimated_total_usd": str(budget.estimated_total_usd),
                "max_estimated_usd": str(budget.max_estimated_usd),
            },
            "calls": ledger,
            "boundaries": {
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
        }
        _write_json_exclusive(stage_root / EXECUTION_LEDGER_NAME, ledger_payload)
        report_path = stage_root / REPORT_NAME
        _write_json_exclusive(report_path, report)
        verified = verifier(
            manifest_path=resolved_manifest,
            provider_report_path=report_path,
            model_registry_path=resolved_registry,
        )
        if verified.get("passed") is not True:
            issues = verified.get("issues", ["offline verifier rejected report"])
            reason = str(issues[0]) if issues else "offline verifier rejected report"
            raise ReplayRunError(reason)
        if resolved_output.exists():
            raise ReplayRunError("provider replay output appeared during publication")
        os.rename(stage_root, resolved_output)
        published = True
        return {
            "passed": True,
            "output_root": str(resolved_output),
            "provider_report": str(resolved_output / REPORT_NAME),
            "execution_ledger": str(
                resolved_output / EXECUTION_LEDGER_NAME
            ),
            "packet_count": inputs.plan.packet_count,
            "annotation_count": inputs.plan.annotation_count,
            "adversarial_probe_count": inputs.plan.adversarial_probe_count,
            "provider_calls": budget.used_calls,
            "estimated_total_usd": str(budget.estimated_total_usd),
            "email_invoked": False,
            "c7_invoked": False,
            "smtp_config_read": False,
            "broker_invoked": False,
            "order_invoked": False,
            "canonical_effect": False,
        }
    except Exception:
        raise
    finally:
        if not published and stage_root.exists():
            shutil.rmtree(stage_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path, default=CORPUS_MANIFEST_PATH)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATION_PATH)
    parser.add_argument("--model-registry", type=Path, default=MODEL_REGISTRY_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--acknowledge-external-inference", action="store_true")
    parser.add_argument("--annotation-file-sha256", default="")
    parser.add_argument("--exact-maximum-calls", type=int)
    parser.add_argument("--max-estimated-usd", type=_decimal)
    parser.add_argument("--estimated-usd-per-call", type=_decimal)
    args = parser.parse_args()

    if not args.run:
        result = check_replay_readiness(
            manifest_path=args.manifest,
            annotation_path=args.annotations,
            model_registry_path=args.model_registry,
        )
        print(
            f"provider_replay_run_check={'ready' if result['ready'] else 'blocked'} "
            f"packets={result['packet_count']} "
            f"annotations={result['annotation_count']} "
            f"adversarial_probes={result['adversarial_probe_count']} "
            f"planned_calls={result['planned_provider_calls']} "
            f"issues={len(result['issues'])} "
            "provider_invoked=false network_invoked=false files_written=false "
            "email_invoked=false c7_invoked=false broker_invoked=false "
            "order_invoked=false canonical_effect=false"
        )
        return 0 if result["ready"] else 1

    if (
        args.exact_maximum_calls is None
        or args.max_estimated_usd is None
        or args.estimated_usd_per_call is None
        or not args.annotation_file_sha256
    ):
        parser.error(
            "--run requires --exact-maximum-calls, --max-estimated-usd, "
            "--estimated-usd-per-call, and --annotation-file-sha256"
        )
    if args.model_registry.expanduser().resolve() != MODEL_REGISTRY_PATH.resolve():
        parser.error("--run must use the current project model registry")
    try:
        result = execute_provider_replay(
            manifest_path=args.manifest,
            annotation_path=args.annotations,
            model_registry_path=args.model_registry,
            output_root=args.output_root,
            acknowledge_external_inference=args.acknowledge_external_inference,
            annotation_file_sha256=args.annotation_file_sha256,
            exact_maximum_calls=args.exact_maximum_calls,
            max_estimated_usd=args.max_estimated_usd,
            estimated_usd_per_call=args.estimated_usd_per_call,
        )
    except Exception as exc:
        print(
            f"provider_replay_run=failed reason={_safe_error(exc)} "
            "passing_report_written=false email_invoked=false c7_invoked=false "
            "smtp_config_read=false broker_invoked=false order_invoked=false "
            "canonical_effect=false"
        )
        return 1
    print(
        f"provider_replay_run=passed packets={result['packet_count']} "
        f"annotations={result['annotation_count']} "
        f"adversarial_probes={result['adversarial_probe_count']} "
        f"provider_calls={result['provider_calls']} "
        f"estimated_total_usd={result['estimated_total_usd']} "
        "email_invoked=false c7_invoked=false smtp_config_read=false "
        "broker_invoked=false order_invoked=false canonical_effect=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
