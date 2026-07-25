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
import copy
import fcntl
import json
import os
import secrets
import shutil
import stat
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

from phase5r_daily_common import ROOT, iso_now
from phase5r_llm_citation_reviews import (
    CitationReviewError,
    build_citation_review_template,
    validate_citation_review_set,
)
from phase5r_llm_contract import (
    ContractError,
    response_schema,
    validate_analyst,
    validate_committee,
    validate_critic,
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
    CITATION_REVIEW_SET_PATH,
    CORPUS_MANIFEST_PATH,
    COUNTERFACTUAL_PROMPT_VERSION,
    CRITIC_CONTROL_INSTRUCTIONS,
    CRITIC_CONTROL_PROMPT_VERSION,
    CRITIC_CONTROL_SCHEMA,
    CRITIC_CONTROL_SCHEMA_VERSION,
    EXTENDED_QUALITY_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MAXIMUM_HIGH_CONFIDENCE_ERROR_PCT,
    MAXIMUM_HOLDOUT_BRIER_SCORE,
    MAXIMUM_HOLDOUT_ECE_PCT,
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
    PacketBinding,
    PROVIDER_REPORT_PATH,
    REQUIRED_CITATION_REVIEW_COUNT,
    REQUIRED_COUNTERFACTUAL_COUNT,
    REQUIRED_CRITIC_CONTROL_COUNT,
    REQUIRED_NEGATIVE_CONTROL_COUNT,
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
    _wilson_interval_pct,
    adversarial_probe_input,
    canonical_sha256,
    counterfactual_transition_input,
    critic_control_cases,
    critic_control_input,
    frozen_transition_split,
    negative_control_cases,
    replay_primary_inputs,
    replay_runtime_code_hashes,
    sha256_bytes,
    transition_pair_input,
    verify_provider_replay_gate,
)


DEFAULT_OUTPUT_ROOT = PROVIDER_REPORT_PATH.parent
DEFAULT_COLLECTION_ROOT = (
    PROVIDER_REPORT_PATH.parents[1] / "quarantine" / "v1"
)
REPORT_NAME = PROVIDER_REPORT_PATH.name
EXECUTION_LEDGER_NAME = "phase5r_llm_provider_replay_execution_ledger.json"
COLLECTION_MANIFEST_NAME = "phase5r_llm_provider_replay_collection_manifest.json"
COLLECTION_PROGRESS_NAME = "phase5r_llm_provider_replay_progress.json"
CANDIDATE_NAME = "phase5r_llm_provider_replay_candidate.json"
CITATION_REVIEW_TEMPLATE_NAME = "phase5r_llm_citation_review_template.json"
FINAL_CITATION_REVIEW_NAME = CITATION_REVIEW_SET_PATH.name
OUTPUT_PARENT = ROOT / "08_reviews" / "phase5r_llm_provider_replay"
TRANSPORT = "codex_cli"
COLLECTION_SCHEMA_VERSION = "phase5r_llm_provider_replay_collection_v1"
CANDIDATE_SCHEMA_VERSION = "phase5r_llm_provider_replay_candidate_v1"


class ReplayRunError(RuntimeError):
    """A replay preflight, call, validation, budget, or publication failed."""


class CollectionPaused(ReplayRunError):
    """The explicit per-invocation call ceiling was reached safely."""


class _ProviderMustNotRun:
    """Fail closed if artifact-only recovery unexpectedly needs inference."""

    def generate(self, **_: Any) -> ProviderResult:
        raise ReplayRunError(
            "provider invocation is forbidden during artifact-only recovery"
        )


class _LazyExternalProvider:
    """Construct and verify the external bridge only at the first real call."""

    def __init__(self, registry: dict[str, Any]) -> None:
        self.registry = copy.deepcopy(registry)
        self.provider: CodexCliProvider | None = None

    def generate(self, **kwargs: Any) -> ProviderResult:
        if self.provider is None:
            self.provider = _build_external_provider(self.registry)
        return self.provider.generate(**kwargs)


MAXIMUM_ATTEMPTS_PER_CALL = 3
PROGRESS_SCHEMA_VERSION = "phase5r_llm_provider_replay_progress_v3"
ATTEMPT_RECEIPT_SCHEMA_VERSION = "phase5r_llm_provider_attempt_receipt_v2"
EXECUTION_LEDGER_SCHEMA_VERSION = (
    "phase5r_llm_provider_replay_execution_ledger_v2"
)
RETRYABLE_ATTEMPT_CATEGORIES = frozenset(
    {
        "transport_timeout",
        "transport_missing_response",
        "process_interrupted",
    }
)
INVALID_ATTEMPT_CATEGORIES = frozenset(
    {
        "schema_invalid",
        "semantic_invalid",
        "policy_invalid",
        "provider_metadata_invalid",
        "artifact_integrity_invalid",
    }
)
ATTEMPT_OUTCOME_CATEGORIES = frozenset(
    {
        "invocation_started",
        "valid_response",
        *RETRYABLE_ATTEMPT_CATEGORIES,
        *INVALID_ATTEMPT_CATEGORIES,
    }
)


@dataclass(frozen=True)
class ReplayPlan:
    packet_count: int
    annotation_count: int
    negative_control_count: int
    adversarial_probe_count: int
    critic_control_count: int
    counterfactual_count: int
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
    def negative_control_call_count(self) -> int:
        return self.negative_control_count

    @property
    def stability_call_count(self) -> int:
        return (
            self.stability_transition_count
            * self.stability_trials_per_transition
        )

    @property
    def extended_quality_call_count(self) -> int:
        return self.critic_control_count + self.counterfactual_count

    @property
    def total_call_count(self) -> int:
        return (
            self.primary_call_count
            + self.transition_pair_call_count
            + self.negative_control_call_count
            + self.adversarial_call_count
            + self.stability_call_count
            + self.extended_quality_call_count
        )


@dataclass
class CallBudget:
    maximum_new_calls: int
    global_maximum_physical_calls: int
    max_estimated_usd: Decimal
    estimated_usd_per_call: Decimal
    cumulative_physical_calls_before: int
    used_calls: int = 0

    def validate(self) -> None:
        if (
            isinstance(self.maximum_new_calls, bool)
            or not isinstance(self.maximum_new_calls, int)
            or self.maximum_new_calls < 0
            or isinstance(self.global_maximum_physical_calls, bool)
            or not isinstance(self.global_maximum_physical_calls, int)
            or self.global_maximum_physical_calls <= 0
            or isinstance(self.cumulative_physical_calls_before, bool)
            or not isinstance(self.cumulative_physical_calls_before, int)
            or self.cumulative_physical_calls_before < 0
            or self.cumulative_physical_calls_before
            > self.global_maximum_physical_calls
            or self.maximum_new_calls
            > (
                self.global_maximum_physical_calls
                - self.cumulative_physical_calls_before
            )
        ):
            raise ReplayRunError(
                "physical provider-call ceilings are invalid or exceed the "
                "frozen cumulative ceiling"
            )
        if (
            not self.max_estimated_usd.is_finite()
            or not self.estimated_usd_per_call.is_finite()
            or self.max_estimated_usd <= 0
            or self.estimated_usd_per_call <= 0
        ):
            raise ReplayRunError("estimated USD budget values must be finite and positive")
        if self.estimated_global_ceiling_usd > self.max_estimated_usd:
            raise ReplayRunError(
                "frozen physical-call ceiling exceeds the operator-estimated "
                "USD ceiling"
            )

    @property
    def estimated_invocation_ceiling_usd(self) -> Decimal:
        return self.estimated_usd_per_call * self.maximum_new_calls

    @property
    def estimated_global_ceiling_usd(self) -> Decimal:
        return (
            self.estimated_usd_per_call
            * self.global_maximum_physical_calls
        )

    @property
    def cumulative_physical_calls(self) -> int:
        return self.cumulative_physical_calls_before + self.used_calls

    @property
    def cumulative_estimated_usd(self) -> Decimal:
        return (
            self.estimated_usd_per_call
            * self.cumulative_physical_calls
        )

    def consume(self) -> int:
        if self.used_calls >= self.maximum_new_calls:
            raise CollectionPaused(
                "per-invocation provider call ceiling reached"
            )
        if (
            self.cumulative_physical_calls
            >= self.global_maximum_physical_calls
        ):
            raise ReplayRunError(
                "frozen global physical provider-call ceiling reached"
            )
        self.used_calls += 1
        return self.used_calls


@dataclass(frozen=True)
class ReplayInputs:
    registry: dict[str, Any]
    registry_sha256: str
    corpus: Any
    annotations: list[dict[str, Any]]
    negative_controls: list[dict[str, Any]]
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


def _provider_failure_category(exc: Exception) -> tuple[str, bool]:
    """Classify only a narrow, stable set of transport/process failures."""

    rendered = str(exc).lower()
    if isinstance(exc, ProviderError):
        if "model call timed out" in rendered:
            return "transport_timeout", True
        if "model process produced no final response" in rendered:
            return "transport_missing_response", True
        if (
            "response was not valid json" in rendered
            or "response must be one json object" in rendered
            or "response exceeded size limit" in rendered
        ):
            return "schema_invalid", False
    return "policy_invalid", False


def _semantic_failure_category(exc: Exception) -> str:
    rendered = str(exc).lower()
    policy_markers = (
        "policy",
        "imperative",
        "automatic action",
        "automatic_action",
        "broker",
        "order",
        "credential",
        "sensitive",
        "must abstain",
    )
    if any(marker in rendered for marker in policy_markers):
        return "policy_invalid"
    return "semantic_invalid"


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
    required_issuers = int(promotion["minimum_replay_issuers"])
    required_transitions = max(
        (
            MINIMUM_MATERIAL_TRANSITIONS
            if minimum_transitions is None
            else minimum_transitions
        ),
        int(promotion["minimum_material_transition_cases"]),
    )
    corpus = _load_corpus(
        manifest_path,
        minimum_packets=required_packets,
        minimum_issuers=required_issuers,
    )
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
    frozen_transition_split(selected, corpus.packets)
    if len(corpus.adversarial_probes) < required_transitions:
        raise ReplayRunError("real corpus adversarial safety-probe minimum is unmet")
    controls = negative_control_cases(corpus.packets)
    if len(controls) != REQUIRED_NEGATIVE_CONTROL_COUNT:
        raise ReplayRunError("exactly 50 deterministic no-change controls are required")
    critic_controls = critic_control_cases(selected)
    if len(critic_controls) != REQUIRED_CRITIC_CONTROL_COUNT:
        raise ReplayRunError("exactly 50 critic controls are required")
    if len(selected) < REQUIRED_COUNTERFACTUAL_COUNT:
        raise ReplayRunError(
            "decisive-evidence-removal counterfactual minimum is unmet"
        )
    if (
        stability_transition_count < 1
        or stability_trials_per_transition < 2
        or len(selected) < stability_transition_count
    ):
        raise ReplayRunError("stability replay sample is below its frozen minimum")
    plan = ReplayPlan(
        packet_count=len(corpus.packets),
        annotation_count=len(selected),
        negative_control_count=len(controls),
        adversarial_probe_count=len(corpus.adversarial_probes),
        critic_control_count=len(critic_controls),
        counterfactual_count=len(selected),
        stability_transition_count=stability_transition_count,
        stability_trials_per_transition=stability_trials_per_transition,
    )
    return ReplayInputs(
        registry=registry,
        registry_sha256=registry_sha,
        corpus=corpus,
        annotations=selected,
        negative_controls=controls,
        annotation_metadata=annotation_metadata,
        plan=plan,
    )


def check_replay_readiness(
    *,
    manifest_path: Path = CORPUS_MANIFEST_PATH,
    annotation_path: Path = DEFAULT_ANNOTATION_PATH,
    model_registry_path: Path = MODEL_REGISTRY_PATH,
    collection_root: Path = DEFAULT_COLLECTION_ROOT,
    allow_test_path: bool = False,
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
            "negative_control_count": 0,
            "adversarial_probe_count": 0,
            "critic_control_count": 0,
            "counterfactual_count": 0,
            "planned_provider_calls": 0,
            "completed_provider_calls": 0,
            "remaining_provider_calls": 0,
            "collection_complete": False,
            "suggested_new_call_caps": {
                "smoke": 0,
                "pilot": 0,
                "full_remaining": 0,
            },
            "provider_invoked": False,
            "network_invoked": False,
            "files_written": False,
            "email_invoked": False,
            "c7_invoked": False,
            "broker_invoked": False,
            "order_invoked": False,
            "canonical_effect": False,
        }
    resolved_collection = _resolve_collection_root(
        collection_root,
        allow_test_path=allow_test_path,
    )
    completed = 0
    physical_attempts = 0
    frozen_budget_policy: dict[str, Any] = {}
    collection_complete = False
    if resolved_collection.exists():
        try:
            progress, _ = _read_private_json(
                resolved_collection
                / COLLECTION_PROGRESS_NAME,
                label="provider replay collection progress",
                trusted_root=resolved_collection,
            )
            _validate_progress(progress)
            _validate_collection_input_binding(
                progress["collection_config"],
                inputs,
            )
            if _terminal_invalid_call_ids(progress):
                raise ReplayRunError(
                    "collection contains a terminal invalid evaluation response"
                )
            if _exhausted_retry_call_ids(progress):
                raise ReplayRunError(
                    "collection contains a provider call with exhausted "
                    "bounded transport retries"
                )
            completed = len(progress["successful_calls"])
            physical_attempts = _physical_attempt_count(progress)
            frozen_budget_policy = copy.deepcopy(
                progress["collection_config"]["budget_policy"]
            )
            collection_complete = progress["complete"] is True
        except (
            ReplayRunError,
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
        ) as exc:
            return {
                "ready": False,
                "issues": [_safe_error(exc)],
                "packet_count": inputs.plan.packet_count,
                "annotation_count": inputs.plan.annotation_count,
                "negative_control_count": inputs.plan.negative_control_count,
                "adversarial_probe_count": inputs.plan.adversarial_probe_count,
                "critic_control_count": inputs.plan.critic_control_count,
                "counterfactual_count": inputs.plan.counterfactual_count,
                "planned_provider_calls": inputs.plan.total_call_count,
                "completed_provider_calls": 0,
                "remaining_provider_calls": inputs.plan.total_call_count,
                "collection_complete": False,
                "suggested_new_call_caps": {
                    "smoke": 0,
                    "pilot": 0,
                    "full_remaining": 0,
                },
                "provider_invoked": False,
                "network_invoked": False,
                "files_written": False,
                "email_invoked": False,
                "c7_invoked": False,
                "broker_invoked": False,
                "order_invoked": False,
                "canonical_effect": False,
            }
    remaining = inputs.plan.total_call_count - completed
    if remaining < 0 or (collection_complete and remaining != 0):
        raise ReplayRunError("collection progress exceeds the frozen call plan")
    return {
        "ready": True,
        "issues": [],
        "packet_count": inputs.plan.packet_count,
        "annotation_count": inputs.plan.annotation_count,
        "negative_control_count": inputs.plan.negative_control_count,
        "adversarial_probe_count": inputs.plan.adversarial_probe_count,
        "critic_control_count": inputs.plan.critic_control_count,
        "counterfactual_count": inputs.plan.counterfactual_count,
        "planned_provider_calls": inputs.plan.total_call_count,
        "completed_provider_calls": completed,
        "completed_physical_provider_attempts": physical_attempts,
        "remaining_provider_calls": remaining,
        "frozen_budget_policy": frozen_budget_policy,
        "collection_complete": collection_complete,
        "suggested_new_call_caps": {
            "smoke": min(30, remaining),
            "pilot": min(200, remaining),
            "full_remaining": remaining,
        },
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


def _validate_output_root(
    path: Path,
    *,
    allow_test_path: bool,
    quarantine_required: bool | None = None,
) -> Path:
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
    if not allow_test_path and quarantine_required is not None:
        quarantine_root = (OUTPUT_PARENT / "quarantine").resolve()
        try:
            resolved.relative_to(quarantine_root)
            inside_quarantine = True
        except ValueError:
            inside_quarantine = False
        if quarantine_required and not inside_quarantine:
            raise ReplayRunError(
                "collection output must remain under the quarantine root"
            )
        if not quarantine_required and inside_quarantine:
            raise ReplayRunError(
                "final passing output must be outside the quarantine root"
            )
    return resolved


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_all(descriptor: int, raw: bytes) -> None:
    remaining = memoryview(raw)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except InterruptedError:
            continue
        if written <= 0:
            raise ReplayRunError("replay artifact write made no progress")
        remaining = remaining[written:]


def _validate_private_directory(
    metadata: os.stat_result,
    *,
    label: str,
) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise ReplayRunError(f"{label} is not a private owned directory")


@contextmanager
def _trusted_parent(
    trusted_root: Path,
    path: Path,
    *,
    create_parents: bool,
):
    """Yield an anchored parent dirfd and leaf without following child links."""

    if not hasattr(os, "O_NOFOLLOW"):
        raise ReplayRunError("O_NOFOLLOW is required for replay artifacts")
    root = Path(os.path.abspath(trusted_root.expanduser()))
    target = Path(os.path.abspath(path.expanduser()))
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ReplayRunError(
            "replay artifact path escapes its trusted root"
        ) from exc
    if not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ReplayRunError("replay artifact path is not a safe leaf")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        current = os.open(root, directory_flags)
    except OSError as exc:
        raise ReplayRunError(
            "trusted replay root is unavailable or linked"
        ) from exc
    try:
        _validate_private_directory(
            os.fstat(current),
            label="trusted replay root",
        )
        for component in relative.parts[:-1]:
            try:
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=current,
                )
            except FileNotFoundError:
                if not create_parents:
                    raise ReplayRunError(
                        "replay artifact parent directory is unavailable"
                    )
                try:
                    os.mkdir(component, 0o700, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=current,
                )
            except OSError as exc:
                raise ReplayRunError(
                    "replay artifact parent must not be linked"
                ) from exc
            _validate_private_directory(
                os.fstat(next_descriptor),
                label="replay artifact parent",
            )
            os.close(current)
            current = next_descriptor
        yield current, relative.parts[-1]
    finally:
        os.close(current)


def _recover_owned_publication_link(
    parent_descriptor: int,
    leaf: str,
    descriptor: int,
) -> os.stat_result:
    metadata = os.fstat(descriptor)
    if metadata.st_nlink <= 1:
        return metadata
    prefix = f".{leaf}.publish-"
    owned_links: list[str] = []
    for entry in os.listdir(parent_descriptor):
        if not entry.startswith(prefix) or not entry.endswith(".tmp"):
            continue
        try:
            candidate = os.stat(
                entry,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        if (
            stat.S_ISREG(candidate.st_mode)
            and candidate.st_dev == metadata.st_dev
            and candidate.st_ino == metadata.st_ino
        ):
            owned_links.append(entry)
    for entry in owned_links:
        os.unlink(entry, dir_fd=parent_descriptor)
    if owned_links:
        os.fsync(parent_descriptor)
    return os.fstat(descriptor)


def _read_json_descriptor(
    descriptor: int,
    *,
    label: str,
    maximum_bytes: int,
    parent_descriptor: int | None = None,
    leaf: str = "",
    recover_owned_publication: bool = False,
) -> tuple[dict[str, Any], bytes]:
    metadata = os.fstat(descriptor)
    if recover_owned_publication and parent_descriptor is not None:
        metadata = _recover_owned_publication_link(
            parent_descriptor,
            leaf,
            descriptor,
        )
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > maximum_bytes
        or metadata.st_mode & 0o022
    ):
        raise ReplayRunError(f"{label} is not a private regular file")
    chunks: list[bytes] = []
    remaining = metadata.st_size
    while remaining:
        chunk = os.read(descriptor, min(remaining, 1024 * 1024))
        if not chunk:
            raise ReplayRunError(f"{label} ended before its stated size")
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayRunError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ReplayRunError(f"{label} must contain one JSON object")
    return payload, raw


def _publish_bytes_exclusive(
    path: Path,
    raw: bytes,
    *,
    trusted_root: Path,
) -> str:
    """Publish a complete fsynced inode atomically without replacing a leaf."""

    with _trusted_parent(
        trusted_root,
        path,
        create_parents=True,
    ) as (parent_descriptor, leaf):
        temporary_leaf = (
            f".{leaf}.publish-{secrets.token_hex(16)}.tmp"
        )
        descriptor = os.open(
            temporary_leaf,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        published = False
        temporary_exists = True
        try:
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, raw)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            try:
                os.link(
                    temporary_leaf,
                    leaf,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise ReplayRunError(
                    f"exclusive replay artifact already exists: {leaf}"
                ) from exc
            published = True
            os.fsync(parent_descriptor)
            os.unlink(temporary_leaf, dir_fd=parent_descriptor)
            temporary_exists = False
            os.fsync(parent_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_exists and not published:
                try:
                    os.unlink(
                        temporary_leaf,
                        dir_fd=parent_descriptor,
                    )
                    os.fsync(parent_descriptor)
                except FileNotFoundError:
                    pass
    return sha256_bytes(raw)


def _write_json_exclusive(
    path: Path,
    payload: dict[str, Any],
    *,
    trusted_root: Path | None = None,
) -> str:
    raw = _json_bytes(payload)
    return _publish_bytes_exclusive(
        path,
        raw,
        trusted_root=trusted_root or path.parent,
    )


def _read_private_json(
    path: Path,
    *,
    label: str,
    maximum_bytes: int = 64 * 1024 * 1024,
    trusted_root: Path | None = None,
    recover_owned_publication: bool = False,
) -> tuple[dict[str, Any], bytes]:
    if trusted_root is not None:
        with _trusted_parent(
            trusted_root,
            path,
            create_parents=False,
        ) as (parent_descriptor, leaf):
            try:
                descriptor = os.open(
                    leaf,
                    os.O_RDONLY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent_descriptor,
                )
            except OSError as exc:
                raise ReplayRunError(f"{label} is unavailable") from exc
            try:
                return _read_json_descriptor(
                    descriptor,
                    label=label,
                    maximum_bytes=maximum_bytes,
                    parent_descriptor=parent_descriptor,
                    leaf=leaf,
                    recover_owned_publication=(
                        recover_owned_publication
                    ),
                )
            finally:
                os.close(descriptor)
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise ReplayRunError(f"{label} is unavailable") from exc
    try:
        return _read_json_descriptor(
            descriptor,
            label=label,
            maximum_bytes=maximum_bytes,
        )
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> str:
    """Atomically replace one private mutable collection-state document."""

    raw = _json_bytes(payload)
    with _trusted_parent(
        path.parent,
        path,
        create_parents=False,
    ) as (parent_descriptor, leaf):
        temporary_leaf = (
            f".{leaf}.atomic-{secrets.token_hex(16)}.tmp"
        )
        descriptor = os.open(
            temporary_leaf,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_exists = True
        try:
            _write_all(descriptor, raw)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            try:
                existing = os.stat(
                    leaf,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing = None
            if existing is not None and (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_uid != os.geteuid()
                or existing.st_nlink != 1
                or existing.st_mode & 0o022
            ):
                raise ReplayRunError(
                    "mutable replay state leaf is not a private regular file"
                )
            os.rename(
                temporary_leaf,
                leaf,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_exists = False
            os.fsync(parent_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_exists:
                try:
                    os.unlink(
                        temporary_leaf,
                        dir_fd=parent_descriptor,
                    )
                except FileNotFoundError:
                    pass
    return sha256_bytes(raw)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        _validate_private_directory(
            os.fstat(descriptor),
            label="replay fsync directory",
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unsigned_progress(progress: dict[str, Any]) -> dict[str, Any]:
    unsigned = copy.deepcopy(progress)
    unsigned.pop("progress_sha256", None)
    return unsigned


def _validate_progress(progress: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "created_at",
        "updated_at",
        "collection_config",
        "collection_config_sha256",
        "events",
        "successful_calls",
        "complete",
        "progress_sha256",
    }
    if not isinstance(progress, dict) or set(progress) != expected:
        raise ReplayRunError("collection progress schema is invalid")
    if progress["schema_version"] != PROGRESS_SCHEMA_VERSION:
        raise ReplayRunError("collection progress version is stale")
    if (
        canonical_sha256(progress["collection_config"])
        != progress["collection_config_sha256"]
    ):
        raise ReplayRunError("collection configuration hash mismatch")
    if canonical_sha256(_unsigned_progress(progress)) != progress["progress_sha256"]:
        raise ReplayRunError("collection progress content hash mismatch")
    events = progress["events"]
    calls = progress["successful_calls"]
    if not isinstance(events, list) or not isinstance(calls, dict):
        raise ReplayRunError("collection progress events/calls are invalid")
    previous = ""
    successful_event_ids: set[str] = set()
    started_attempts: dict[str, int] = {}
    terminal_attempts: set[tuple[str, int]] = set()
    for index, event in enumerate(events):
        if (
            not isinstance(event, dict)
            or set(event)
            != {
                "event_index",
                "event_kind",
                "provider_call_id",
                "attempt_number",
                "recorded_at",
                "input_sha256",
                "safe_outcome",
                "outcome_category",
                "retryable",
                "previous_event_sha256",
                "event_sha256",
            }
            or event["event_index"] != index + 1
            or event["previous_event_sha256"] != previous
        ):
            raise ReplayRunError("collection event chain is invalid")
        unsigned_event = dict(event)
        event_hash = unsigned_event.pop("event_sha256")
        if canonical_sha256(unsigned_event) != event_hash:
            raise ReplayRunError("collection event content hash mismatch")
        previous = event_hash
        event_kind = str(event["event_kind"])
        call_id = str(event["provider_call_id"])
        attempt_number = event["attempt_number"]
        outcome_category = event["outcome_category"]
        retryable = event["retryable"]
        expected_safe_outcome = (
            "provider_invocation_intent_persisted"
            if event_kind == "attempt_started"
            else (
                "validated_response_persisted"
                if event_kind == "success"
                else (
                    "no_recoverable_provider_result"
                    if outcome_category == "process_interrupted"
                    else outcome_category
                )
            )
        )
        if (
            event_kind
            not in {"attempt_started", "success", "failure", "interrupted"}
            or isinstance(attempt_number, bool)
            or not isinstance(attempt_number, int)
            or attempt_number <= 0
            or attempt_number > MAXIMUM_ATTEMPTS_PER_CALL
            or outcome_category not in ATTEMPT_OUTCOME_CATEGORIES
            or not isinstance(retryable, bool)
            or event["safe_outcome"] != expected_safe_outcome
        ):
            raise ReplayRunError("collection event kind/attempt is invalid")
        if event_kind == "attempt_started":
            expected_attempt = started_attempts.get(call_id, 0) + 1
            previous_terminal = next(
                (
                    prior
                    for prior in reversed(events[:index])
                    if prior["provider_call_id"] == call_id
                    and prior["event_kind"]
                    in {"success", "failure", "interrupted"}
                ),
                None,
            )
            if (
                attempt_number != expected_attempt
                or call_id in successful_event_ids
                or outcome_category != "invocation_started"
                or retryable is not False
                or (
                    attempt_number > 1
                    and (
                        (call_id, attempt_number - 1)
                        not in terminal_attempts
                        or previous_terminal is None
                        or previous_terminal["retryable"] is not True
                    )
                )
            ):
                raise ReplayRunError(
                    "collection attempt-start sequence is invalid"
                )
            started_attempts[call_id] = attempt_number
            continue
        key = (call_id, attempt_number)
        if (
            started_attempts.get(call_id, 0) < attempt_number
            or key in terminal_attempts
        ):
            raise ReplayRunError(
                "collection attempt terminal event is invalid"
            )
        terminal_attempts.add(key)
        if event_kind == "success":
            if (
                outcome_category != "valid_response"
                or retryable is not False
            ):
                raise ReplayRunError(
                    "collection success outcome classification is invalid"
                )
            successful_event_ids.add(call_id)
        elif (
            outcome_category
            not in (
                RETRYABLE_ATTEMPT_CATEGORIES
                | INVALID_ATTEMPT_CATEGORIES
            )
            or retryable
            is not (outcome_category in RETRYABLE_ATTEMPT_CATEGORIES)
        ):
            raise ReplayRunError(
                "collection failure outcome classification is invalid"
            )
    if successful_event_ids != set(calls):
        raise ReplayRunError("collection success events/call records differ")


def _attempt_count(progress: dict[str, Any], call_id: str) -> int:
    return sum(
        1
        for event in progress["events"]
        if event["provider_call_id"] == call_id
        and event["event_kind"] == "attempt_started"
    )


def _physical_attempt_count(progress: dict[str, Any]) -> int:
    return sum(
        event["event_kind"] == "attempt_started"
        for event in progress["events"]
    )


def _terminal_invalid_call_ids(progress: dict[str, Any]) -> set[str]:
    return {
        str(event["provider_call_id"])
        for event in progress["events"]
        if event["event_kind"] in {"failure", "interrupted"}
        and event["retryable"] is False
    }


def _exhausted_retry_call_ids(progress: dict[str, Any]) -> set[str]:
    successful = set(progress["successful_calls"])
    started_counts: dict[str, int] = {}
    latest_terminal: dict[str, dict[str, Any]] = {}
    for event in progress["events"]:
        call_id = str(event["provider_call_id"])
        if event["event_kind"] == "attempt_started":
            started_counts[call_id] = started_counts.get(call_id, 0) + 1
        elif event["event_kind"] in {
            "success",
            "failure",
            "interrupted",
        }:
            latest_terminal[call_id] = event
    return {
        call_id
        for call_id, count in started_counts.items()
        if call_id not in successful
        and count >= MAXIMUM_ATTEMPTS_PER_CALL
        and latest_terminal.get(call_id, {}).get("attempt_number") == count
        and latest_terminal[call_id]["retryable"] is True
    }


class CollectionCallStore:
    """Content-hashed response cache with an auditable bounded retry chain."""

    def __init__(self, root: Path, progress: dict[str, Any]) -> None:
        self.root = root
        self.progress = progress
        _validate_progress(progress)

    def _save(self) -> None:
        self.progress["updated_at"] = iso_now()
        self.progress["progress_sha256"] = canonical_sha256(
            _unsigned_progress(self.progress)
        )
        _write_json_atomic(
            self.root / COLLECTION_PROGRESS_NAME,
            self.progress,
        )

    def _event(
        self,
        *,
        event_kind: str,
        call_id: str,
        attempt_number: int,
        input_sha256: str,
        safe_outcome: str,
        outcome_category: str,
        retryable: bool,
    ) -> None:
        previous = (
            self.progress["events"][-1]["event_sha256"]
            if self.progress["events"]
            else ""
        )
        event: dict[str, Any] = {
            "event_index": len(self.progress["events"]) + 1,
            "event_kind": event_kind,
            "provider_call_id": call_id,
            "attempt_number": attempt_number,
            "recorded_at": iso_now(),
            "input_sha256": input_sha256,
            "safe_outcome": safe_outcome,
            "outcome_category": outcome_category,
            "retryable": retryable,
            "previous_event_sha256": previous,
        }
        event["event_sha256"] = canonical_sha256(event)
        self.progress["events"].append(event)

    def _attempt_terminal_kind(
        self,
        call_id: str,
        attempt_number: int,
    ) -> str | None:
        terminals = [
            str(event["event_kind"])
            for event in self.progress["events"]
            if event["provider_call_id"] == call_id
            and event["attempt_number"] == attempt_number
            and event["event_kind"] in {"success", "failure", "interrupted"}
        ]
        if len(terminals) > 1:
            raise ReplayRunError("provider attempt has duplicate terminal events")
        return terminals[0] if terminals else None

    def _attempt_terminal_event(
        self,
        call_id: str,
        attempt_number: int,
    ) -> dict[str, Any] | None:
        terminals = [
            event
            for event in self.progress["events"]
            if event["provider_call_id"] == call_id
            and event["attempt_number"] == attempt_number
            and event["event_kind"] in {"success", "failure", "interrupted"}
        ]
        if len(terminals) > 1:
            raise ReplayRunError("provider attempt has duplicate terminal events")
        return terminals[0] if terminals else None

    def _receipt_relative_path(
        self,
        call_id: str,
        attempt_number: int,
    ) -> str:
        call_hash = sha256_bytes(call_id.encode("utf-8"))
        return (
            "attempt_receipts/"
            f"{call_hash}-attempt-{attempt_number}.json"
        )

    def begin_attempt(
        self,
        *,
        call_id: str,
        input_payload: dict[str, Any],
    ) -> int:
        attempt_number = _attempt_count(self.progress, call_id) + 1
        if (
            attempt_number > MAXIMUM_ATTEMPTS_PER_CALL
            or (
                attempt_number > 1
                and (
                    self._attempt_terminal_event(
                        call_id,
                        attempt_number - 1,
                    )
                    is None
                    or self._attempt_terminal_event(
                        call_id,
                        attempt_number - 1,
                    )["retryable"]
                    is not True
                )
            )
        ):
            raise ReplayRunError("provider attempt cannot be started safely")
        self._event(
            event_kind="attempt_started",
            call_id=call_id,
            attempt_number=attempt_number,
            input_sha256=canonical_sha256(input_payload),
            safe_outcome="provider_invocation_intent_persisted",
            outcome_category="invocation_started",
            retryable=False,
        )
        self._save()
        return attempt_number

    def _mark_interrupted(
        self,
        *,
        call_id: str,
        category: str,
        role: str,
        model: str,
        reasoning_effort: str,
        attempt_number: int,
        input_payload: dict[str, Any],
    ) -> None:
        if self._attempt_terminal_kind(call_id, attempt_number) is not None:
            return
        self.persist_failure_receipt(
            call_id=call_id,
            category=category,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            attempt_number=attempt_number,
            event_kind="interrupted",
            outcome_category="process_interrupted",
            safe_outcome="no_recoverable_provider_result",
            retryable=True,
        )
        self.persist_failure(
            call_id=call_id,
            event_kind="interrupted",
            attempt_number=attempt_number,
            input_payload=input_payload,
            safe_outcome="no_recoverable_provider_result",
            outcome_category="process_interrupted",
            retryable=True,
        )

    def persist_attempt_receipt(
        self,
        *,
        call_id: str,
        category: str,
        role: str,
        model: str,
        reasoning_effort: str,
        input_payload: dict[str, Any],
        payload: dict[str, Any],
        metadata: dict[str, Any],
        relative_path: str,
        ledger_row: dict[str, Any],
        attempt_number: int,
    ) -> tuple[str, str]:
        if self._attempt_terminal_kind(call_id, attempt_number) is not None:
            raise ReplayRunError(
                "provider result cannot attach to a terminal attempt"
            )
        receipt_relative_path = self._receipt_relative_path(
            call_id,
            attempt_number,
        )
        receipt: dict[str, Any] = {
            "schema_version": ATTEMPT_RECEIPT_SCHEMA_VERSION,
            "provider_call_id": call_id,
            "category": category,
            "role": role,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "attempt_number": attempt_number,
            "input_sha256": canonical_sha256(input_payload),
            "terminal_event_kind": "success",
            "outcome_category": "valid_response",
            "retryable": False,
            "safe_outcome": "validated_response_persisted",
            "output_sha256": canonical_sha256(payload),
            "response_relative_path": relative_path,
            "payload": copy.deepcopy(payload),
            "provider_metadata": copy.deepcopy(metadata),
            "ledger_row": copy.deepcopy(ledger_row),
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        receipt_file_sha = _write_json_exclusive(
            self.root / receipt_relative_path,
            receipt,
            trusted_root=self.root,
        )
        return receipt_relative_path, receipt_file_sha

    def persist_failure_receipt(
        self,
        *,
        call_id: str,
        category: str,
        role: str,
        model: str,
        reasoning_effort: str,
        input_payload: dict[str, Any],
        attempt_number: int,
        event_kind: str,
        outcome_category: str,
        safe_outcome: str,
        retryable: bool,
    ) -> tuple[str, str]:
        if (
            self._attempt_terminal_kind(call_id, attempt_number) is not None
            or event_kind not in {"failure", "interrupted"}
            or outcome_category
            not in (
                RETRYABLE_ATTEMPT_CATEGORIES
                | INVALID_ATTEMPT_CATEGORIES
            )
            or retryable
            is not (outcome_category in RETRYABLE_ATTEMPT_CATEGORIES)
            or safe_outcome
            != (
                "no_recoverable_provider_result"
                if outcome_category == "process_interrupted"
                else outcome_category
            )
        ):
            raise ReplayRunError(
                "provider failure receipt classification is invalid"
            )
        receipt_relative_path = self._receipt_relative_path(
            call_id,
            attempt_number,
        )
        receipt: dict[str, Any] = {
            "schema_version": ATTEMPT_RECEIPT_SCHEMA_VERSION,
            "provider_call_id": call_id,
            "category": category,
            "role": role,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "attempt_number": attempt_number,
            "input_sha256": canonical_sha256(input_payload),
            "terminal_event_kind": event_kind,
            "outcome_category": outcome_category,
            "retryable": retryable,
            "safe_outcome": safe_outcome,
            "output_sha256": "",
            "response_relative_path": "",
            "payload": None,
            "provider_metadata": None,
            "ledger_row": None,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        receipt_file_sha = _write_json_exclusive(
            self.root / receipt_relative_path,
            receipt,
            trusted_root=self.root,
        )
        return receipt_relative_path, receipt_file_sha

    def record_attempt_failure(
        self,
        *,
        call_id: str,
        category: str,
        role: str,
        model: str,
        reasoning_effort: str,
        input_payload: dict[str, Any],
        attempt_number: int,
        outcome_category: str,
        retryable: bool,
        event_kind: str = "failure",
    ) -> None:
        safe_outcome = outcome_category
        self.persist_failure_receipt(
            call_id=call_id,
            category=category,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            attempt_number=attempt_number,
            event_kind=event_kind,
            outcome_category=outcome_category,
            safe_outcome=safe_outcome,
            retryable=retryable,
        )
        self.persist_failure(
            call_id=call_id,
            input_payload=input_payload,
            attempt_number=attempt_number,
            event_kind=event_kind,
            safe_outcome=safe_outcome,
            outcome_category=outcome_category,
            retryable=retryable,
        )

    def recover_pending_result(
        self,
        *,
        call_id: str,
        category: str,
        role: str,
        model: str,
        reasoning_effort: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
        registry: dict[str, Any],
        response_relative_path: str,
        semantic_validator: Callable[[dict[str, Any]], None],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        attempt_number = _attempt_count(self.progress, call_id)
        if (
            attempt_number == 0
            or self._attempt_terminal_kind(call_id, attempt_number) is not None
        ):
            return None
        receipt_relative_path = self._receipt_relative_path(
            call_id,
            attempt_number,
        )
        receipt_path = self.root / receipt_relative_path
        if not receipt_path.exists():
            self._mark_interrupted(
                call_id=call_id,
                category=category,
                role=role,
                model=model,
                reasoning_effort=reasoning_effort,
                attempt_number=attempt_number,
                input_payload=input_payload,
            )
            return None
        try:
            receipt, receipt_raw = _read_private_json(
                receipt_path,
                label="provider attempt recovery receipt",
                maximum_bytes=4 * 1024 * 1024,
                trusted_root=self.root,
                recover_owned_publication=True,
            )
        except Exception as exc:
            self.persist_failure(
                call_id=call_id,
                input_payload=input_payload,
                attempt_number=attempt_number,
                event_kind="failure",
                safe_outcome="artifact_integrity_invalid",
                outcome_category="artifact_integrity_invalid",
                retryable=False,
            )
            raise
        expected_fields = {
            "schema_version",
            "provider_call_id",
            "category",
            "role",
            "model",
            "reasoning_effort",
            "attempt_number",
            "input_sha256",
            "terminal_event_kind",
            "outcome_category",
            "retryable",
            "safe_outcome",
            "output_sha256",
            "response_relative_path",
            "payload",
            "provider_metadata",
            "ledger_row",
            "receipt_sha256",
        }
        if not isinstance(receipt, dict) or set(receipt) != expected_fields:
            exc = ReplayRunError(
                "provider attempt receipt schema is invalid"
            )
            self.persist_failure(
                call_id=call_id,
                input_payload=input_payload,
                attempt_number=attempt_number,
                event_kind="failure",
                safe_outcome="artifact_integrity_invalid",
                outcome_category="artifact_integrity_invalid",
                retryable=False,
            )
            raise exc
        unsigned_receipt = dict(receipt)
        receipt_hash = unsigned_receipt.pop("receipt_sha256")
        expected_input_sha = canonical_sha256(input_payload)
        payload = receipt["payload"]
        metadata = receipt["provider_metadata"]
        ledger_row = receipt["ledger_row"]
        if (
            receipt["schema_version"] != ATTEMPT_RECEIPT_SCHEMA_VERSION
            or receipt["provider_call_id"] != call_id
            or receipt["category"] != category
            or receipt["role"] != role
            or receipt["model"] != model
            or receipt["reasoning_effort"] != reasoning_effort
            or receipt["attempt_number"] != attempt_number
            or receipt["input_sha256"] != expected_input_sha
            or canonical_sha256(unsigned_receipt) != receipt_hash
            or receipt["outcome_category"]
            not in ATTEMPT_OUTCOME_CATEGORIES
            or not isinstance(receipt["retryable"], bool)
            or not isinstance(receipt["safe_outcome"], str)
        ):
            exc = ReplayRunError(
                "provider attempt receipt binding is stale"
            )
            self.persist_failure(
                call_id=call_id,
                input_payload=input_payload,
                attempt_number=attempt_number,
                event_kind="failure",
                safe_outcome="artifact_integrity_invalid",
                outcome_category="artifact_integrity_invalid",
                retryable=False,
            )
            raise exc
        terminal_kind = receipt["terminal_event_kind"]
        outcome_category = receipt["outcome_category"]
        retryable = receipt["retryable"]
        if terminal_kind in {"failure", "interrupted"}:
            if (
                outcome_category
                not in (
                    RETRYABLE_ATTEMPT_CATEGORIES
                    | INVALID_ATTEMPT_CATEGORIES
                )
                or retryable
                is not (
                    outcome_category in RETRYABLE_ATTEMPT_CATEGORIES
                )
                or receipt["output_sha256"] != ""
                or receipt["response_relative_path"] != ""
                or payload is not None
                or metadata is not None
                or ledger_row is not None
            ):
                exc = ReplayRunError(
                    "provider failure receipt binding is stale"
                )
                self.persist_failure(
                    call_id=call_id,
                    input_payload=input_payload,
                    attempt_number=attempt_number,
                    event_kind="failure",
                    safe_outcome="artifact_integrity_invalid",
                    outcome_category="artifact_integrity_invalid",
                    retryable=False,
                )
                raise exc
            self.persist_failure(
                call_id=call_id,
                input_payload=input_payload,
                attempt_number=attempt_number,
                event_kind=terminal_kind,
                safe_outcome=receipt["safe_outcome"],
                outcome_category=outcome_category,
                retryable=retryable,
            )
            if retryable:
                return None
            raise ReplayRunError(
                "terminal invalid evaluation response cannot be retried"
            )
        if (
            terminal_kind != "success"
            or outcome_category != "valid_response"
            or retryable is not False
            or receipt["safe_outcome"]
            != "validated_response_persisted"
            or receipt["response_relative_path"] != response_relative_path
            or not isinstance(payload, dict)
            or receipt["output_sha256"] != canonical_sha256(payload)
            or not isinstance(metadata, dict)
            or not isinstance(ledger_row, dict)
        ):
            exc = ReplayRunError(
                "provider success receipt binding is stale"
            )
            self.persist_failure(
                call_id=call_id,
                input_payload=input_payload,
                attempt_number=attempt_number,
                event_kind="failure",
                safe_outcome="artifact_integrity_invalid",
                outcome_category="artifact_integrity_invalid",
                retryable=False,
            )
            raise exc
        try:
            validate_schema(payload, schema)
            _transport_metadata(
                metadata,
                role=role,
                model=model,
                reasoning_effort=reasoning_effort,
                input_payload=input_payload,
                output_payload=payload,
                registry=registry,
            )
            semantic_validator(payload)
        except Exception as exc:
            self.persist_failure(
                call_id=call_id,
                input_payload=input_payload,
                attempt_number=attempt_number,
                event_kind="failure",
                safe_outcome="artifact_integrity_invalid",
                outcome_category="artifact_integrity_invalid",
                retryable=False,
            )
            raise
        if (
            ledger_row.get("provider_call_id") != call_id
            or ledger_row.get("category") != category
            or ledger_row.get("role") != role
            or ledger_row.get("model") != model
            or ledger_row.get("reasoning_effort") != reasoning_effort
            or ledger_row.get("input_sha256") != expected_input_sha
            or ledger_row.get("output_sha256") != canonical_sha256(payload)
        ):
            exc = ReplayRunError(
                "provider attempt receipt ledger is stale"
            )
            self.persist_failure(
                call_id=call_id,
                input_payload=input_payload,
                attempt_number=attempt_number,
                event_kind="failure",
                safe_outcome="artifact_integrity_invalid",
                outcome_category="artifact_integrity_invalid",
                retryable=False,
            )
            raise exc
        receipt_file_sha = sha256_bytes(receipt_raw)
        self.persist_success(
            call_id=call_id,
            category=category,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            payload=payload,
            metadata=metadata,
            relative_path=response_relative_path,
            ledger_row=ledger_row,
            attempt_number=attempt_number,
            attempt_receipt_relative_path=receipt_relative_path,
            attempt_receipt_file_sha256=receipt_file_sha,
        )
        return payload, metadata, ledger_row

    def existing(
        self,
        *,
        call_id: str,
        category: str,
        role: str,
        model: str,
        reasoning_effort: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
        registry: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        record = self.progress["successful_calls"].get(call_id)
        if record is None:
            return None
        expected_input_sha = canonical_sha256(input_payload)
        if (
            record.get("category") != category
            or record.get("role") != role
            or record.get("model") != model
            or record.get("reasoning_effort") != reasoning_effort
            or record.get("input_sha256") != expected_input_sha
        ):
            raise ReplayRunError(
                "cached provider call binding differs from the current plan"
            )
        relative = str(record.get("response_relative_path", ""))
        response_path = (self.root / relative).resolve()
        try:
            response_path.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ReplayRunError("cached response path escapes quarantine") from exc
        payload, raw = _read_private_json(
            response_path,
            label="cached provider response",
            maximum_bytes=2 * 1024 * 1024,
            trusted_root=self.root,
            recover_owned_publication=True,
        )
        if (
            sha256_bytes(raw) != record.get("response_file_sha256")
            or canonical_sha256(payload) != record.get("output_sha256")
        ):
            raise ReplayRunError("cached provider response hash mismatch")
        validate_schema(payload, schema)
        metadata = record.get("provider_metadata")
        if not isinstance(metadata, dict):
            raise ReplayRunError("cached provider metadata is missing")
        receipt_relative = str(
            record.get("attempt_receipt_relative_path", "")
        )
        receipt_path = (self.root / receipt_relative).resolve()
        try:
            receipt_path.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ReplayRunError(
                "cached attempt receipt escapes quarantine"
            ) from exc
        _, receipt_raw = _read_private_json(
            receipt_path,
            label="cached provider attempt receipt",
            maximum_bytes=4 * 1024 * 1024,
            trusted_root=self.root,
            recover_owned_publication=True,
        )
        if (
            sha256_bytes(receipt_raw)
            != record.get("attempt_receipt_file_sha256")
        ):
            raise ReplayRunError("cached provider attempt receipt hash mismatch")
        _transport_metadata(
            metadata,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            output_payload=payload,
            registry=registry,
        )
        ledger = copy.deepcopy(record["ledger_row"])
        return payload, metadata, ledger

    def persist_success(
        self,
        *,
        call_id: str,
        category: str,
        role: str,
        model: str,
        reasoning_effort: str,
        input_payload: dict[str, Any],
        payload: dict[str, Any],
        metadata: dict[str, Any],
        relative_path: str,
        ledger_row: dict[str, Any],
        attempt_number: int,
        attempt_receipt_relative_path: str,
        attempt_receipt_file_sha256: str,
    ) -> None:
        if call_id in self.progress["successful_calls"]:
            raise ReplayRunError("provider call was already persisted")
        if (
            attempt_number != _attempt_count(self.progress, call_id)
            or self._attempt_terminal_kind(call_id, attempt_number) is not None
        ):
            raise ReplayRunError("provider success attempt binding is invalid")
        response_path = self.root / relative_path
        if response_path.exists():
            existing_payload, existing_raw = _read_private_json(
                response_path,
                label="orphaned provider response",
                maximum_bytes=2 * 1024 * 1024,
                trusted_root=self.root,
                recover_owned_publication=True,
            )
            if canonical_sha256(existing_payload) != canonical_sha256(payload):
                raise ReplayRunError(
                    "orphaned provider response differs from retried output"
                )
            response_sha = sha256_bytes(existing_raw)
        else:
            response_sha = _write_json_exclusive(
                response_path,
                payload,
                trusted_root=self.root,
            )
        ledger_row["response_relative_path"] = relative_path
        ledger_row["response_file_sha256"] = response_sha
        self.progress["successful_calls"][call_id] = {
            "category": category,
            "role": role,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "input_sha256": canonical_sha256(input_payload),
            "output_sha256": canonical_sha256(payload),
            "response_relative_path": relative_path,
            "response_file_sha256": response_sha,
            "attempt_number": attempt_number,
            "attempt_receipt_relative_path": attempt_receipt_relative_path,
            "attempt_receipt_file_sha256": (
                attempt_receipt_file_sha256
            ),
            "provider_metadata": copy.deepcopy(metadata),
            "ledger_row": copy.deepcopy(ledger_row),
        }
        self._event(
            event_kind="success",
            call_id=call_id,
            attempt_number=attempt_number,
            input_sha256=canonical_sha256(input_payload),
            safe_outcome="validated_response_persisted",
            outcome_category="valid_response",
            retryable=False,
        )
        self._save()

    def persist_failure(
        self,
        *,
        call_id: str,
        input_payload: dict[str, Any],
        attempt_number: int,
        event_kind: str,
        safe_outcome: str,
        outcome_category: str,
        retryable: bool,
    ) -> None:
        if (
            attempt_number != _attempt_count(self.progress, call_id)
            or self._attempt_terminal_kind(call_id, attempt_number) is not None
            or event_kind not in {"failure", "interrupted"}
            or outcome_category
            not in (
                RETRYABLE_ATTEMPT_CATEGORIES
                | INVALID_ATTEMPT_CATEGORIES
            )
            or retryable
            is not (outcome_category in RETRYABLE_ATTEMPT_CATEGORIES)
        ):
            raise ReplayRunError("provider failure attempt binding is invalid")
        self._event(
            event_kind=event_kind,
            call_id=call_id,
            attempt_number=attempt_number,
            input_sha256=canonical_sha256(input_payload),
            safe_outcome=safe_outcome,
            outcome_category=outcome_category,
            retryable=retryable,
        )
        self._save()

    def ensure_retry_allowed(self, call_id: str) -> None:
        attempts = _attempt_count(self.progress, call_id)
        if attempts:
            terminal = self._attempt_terminal_event(call_id, attempts)
            if terminal is not None and terminal["retryable"] is not True:
                raise ReplayRunError(
                    "terminal invalid evaluation response cannot be retried"
                )
        if _attempt_count(self.progress, call_id) >= MAXIMUM_ATTEMPTS_PER_CALL:
            raise ReplayRunError(
                "provider call reached the bounded retry limit"
            )


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
    if executable_hash != registry["provider_executable_sha256"]:
        raise ReplayRunError("provider executable metadata hash mismatch")


def _call_provider(
    provider: ModelProvider,
    budget: CallBudget,
    call_store: CollectionCallStore,
    *,
    call_id: str,
    category: str,
    response_relative_path: str,
    role: str,
    model: str,
    reasoning_effort: str,
    schema: dict[str, Any],
    instructions: str,
    input_payload: dict[str, Any],
    registry: dict[str, Any],
    semantic_validator: Callable[[dict[str, Any]], None],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cached = call_store.existing(
        call_id=call_id,
        category=category,
        role=role,
        model=model,
        reasoning_effort=reasoning_effort,
        input_payload=input_payload,
        schema=schema,
        registry=registry,
    )
    if cached is not None:
        return cached
    recovered = call_store.recover_pending_result(
        call_id=call_id,
        category=category,
        role=role,
        model=model,
        reasoning_effort=reasoning_effort,
        input_payload=input_payload,
        schema=schema,
        registry=registry,
        response_relative_path=response_relative_path,
        semantic_validator=semantic_validator,
    )
    if recovered is not None:
        return recovered
    call_store.ensure_retry_allowed(call_id)
    budget.consume()
    attempt_number = call_store.begin_attempt(
        call_id=call_id,
        input_payload=input_payload,
    )
    try:
        result: ProviderResult = provider.generate(
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            schema=schema,
            instructions=instructions,
            input_payload=input_payload,
        )
    except Exception as exc:
        outcome_category, retryable = _provider_failure_category(exc)
        call_store.record_attempt_failure(
            call_id=call_id,
            category=category,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            attempt_number=attempt_number,
            outcome_category=outcome_category,
            retryable=retryable,
        )
        raise
    try:
        validate_schema(result.payload, schema)
    except Exception:
        call_store.record_attempt_failure(
            call_id=call_id,
            category=category,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            attempt_number=attempt_number,
            outcome_category="schema_invalid",
            retryable=False,
        )
        raise
    try:
        _transport_metadata(
            result.metadata,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            output_payload=result.payload,
            registry=registry,
        )
    except Exception:
        call_store.record_attempt_failure(
            call_id=call_id,
            category=category,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            attempt_number=attempt_number,
            outcome_category="provider_metadata_invalid",
            retryable=False,
        )
        raise
    try:
        semantic_validator(result.payload)
    except Exception as exc:
        call_store.record_attempt_failure(
            call_id=call_id,
            category=category,
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
            input_payload=input_payload,
            attempt_number=attempt_number,
            outcome_category=_semantic_failure_category(exc),
            retryable=False,
        )
        raise
    sequence = len(call_store.progress["successful_calls"]) + 1
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
    (
        attempt_receipt_relative_path,
        attempt_receipt_file_sha256,
    ) = call_store.persist_attempt_receipt(
        call_id=call_id,
        category=category,
        role=role,
        model=model,
        reasoning_effort=reasoning_effort,
        input_payload=input_payload,
        payload=result.payload,
        metadata=result.metadata,
        relative_path=response_relative_path,
        ledger_row=ledger_row,
        attempt_number=attempt_number,
    )
    call_store.persist_success(
        call_id=call_id,
        category=category,
        role=role,
        model=model,
        reasoning_effort=reasoning_effort,
        input_payload=input_payload,
        payload=result.payload,
        metadata=result.metadata,
        relative_path=response_relative_path,
        ledger_row=ledger_row,
        attempt_number=attempt_number,
        attempt_receipt_relative_path=attempt_receipt_relative_path,
        attempt_receipt_file_sha256=attempt_receipt_file_sha256,
    )
    return result.payload, result.metadata, ledger_row


def _result_record(
    *,
    relative_path: str,
    response: dict[str, Any],
    response_file_sha256: str,
    call_id: str,
    model: str,
    reasoning_effort: str,
    prompt_version: str,
    response_schema_version: str,
    input_payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
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
        "response_file_sha256": response_file_sha256,
        "response_validated": True,
        "credential_read": False,
        "tools_enabled": False,
        "violations": _zero_violations(),
    }
    return common, response_file_sha256


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
        "exact_classification_wilson_95_pct": _wilson_interval_pct(
            classification_matches,
            count,
        ),
        "thesis_direction_match_count": direction_matches,
        "thesis_direction_accuracy_pct": direction_pct,
        "thesis_direction_wilson_95_pct": _wilson_interval_pct(
            direction_matches,
            count,
        ),
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
        "fail_closed_wilson_95_pct": _wilson_interval_pct(
            safe_count,
            total,
        ),
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
    call_store: CollectionCallStore,
    ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    responses: dict[tuple[str, str], dict[str, Any]] = {}
    for packet_id in sorted(inputs.corpus.packets):
        binding = inputs.corpus.packets[packet_id]
        analyst_placeholder: dict[str, Any] = {"claims": []}
        committee_placeholder: dict[str, Any] = {"ticker_decisions": []}
        for role in REQUIRED_ROLES:
            role_inputs = replay_primary_inputs(
                binding,
                analyst_placeholder,
                committee_placeholder,
            )
            input_payload = role_inputs[role]
            config = inputs.registry["roles"][role]
            call_id = f"primary:{packet_id}:{role}"
            relative = f"responses/primary/{packet_id}-{role}.json"
            if role == "analyst":
                def validate_primary(response: dict[str, Any]) -> None:
                    validate_analyst(binding.runtime_packet, response)
                    if (
                        response.get("packet_id")
                        != binding.runtime_packet["packet_id"]
                    ):
                        raise ReplayRunError(
                            "analyst response packet binding mismatch"
                        )
            elif role == "committee":
                def validate_primary(response: dict[str, Any]) -> None:
                    validate_committee(
                        binding.runtime_packet,
                        response,
                        analyst_placeholder,
                    )
                    if (
                        response.get("packet_id")
                        != binding.runtime_packet["packet_id"]
                    ):
                        raise ReplayRunError(
                            "committee response packet binding mismatch"
                        )
                    insufficient_tickers = {
                        str(row["ticker"]).upper()
                        for row in analyst_placeholder["ticker_coverage"]
                        if row["official_evidence_sufficient"] is not True
                    }
                    unsafe_tickers = sorted(
                        str(row["ticker"]).upper()
                        for row in response["ticker_decisions"]
                        if (
                            str(row["ticker"]).upper()
                            in insufficient_tickers
                            and row["classification"] != "abstain"
                        )
                    )
                    if unsafe_tickers:
                        raise ReplayRunError(
                            "committee must abstain when official evidence "
                            "is insufficient for "
                            + ",".join(unsafe_tickers)
                        )
            else:
                def validate_primary(response: dict[str, Any]) -> None:
                    validate_critic(
                        binding.runtime_packet,
                        committee_placeholder,
                        response,
                    )
                    _validate_primary_response_semantics(
                        binding,
                        analyst=analyst_placeholder,
                        committee=committee_placeholder,
                        critic=response,
                    )
            response, _, ledger_row = _call_provider(
                provider,
                budget,
                call_store,
                call_id=call_id,
                category="primary",
                response_relative_path=relative,
                role=role,
                model=config["model"],
                reasoning_effort=config["reasoning_effort"],
                schema=response_schema(role),
                instructions=ROLE_INSTRUCTIONS[role],
                input_payload=input_payload,
                registry=inputs.registry,
                semantic_validator=validate_primary,
            )
            if response.get("packet_id") != binding.runtime_packet["packet_id"]:
                raise ReplayRunError(f"{role} response packet binding mismatch")
            if role == "analyst":
                analyst_placeholder = response
            elif role == "committee":
                committee_placeholder = response
            common, _ = _result_record(
                relative_path=relative,
                response=response,
                response_file_sha256=ledger_row["response_file_sha256"],
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
    call_store: CollectionCallStore,
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
        relative = f"responses/transition_pairs/{case_id.replace(':', '-')}.json"
        def validate_transition(response: dict[str, Any]) -> None:
            _validate_transition_pair_response(
                response,
                case=case,
                prior=prior,
                current=current,
            )
        response, _, ledger_row = _call_provider(
            provider,
            budget,
            call_store,
            call_id=call_id,
            category="transition_pair",
            response_relative_path=relative,
            role="transition_pair",
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            schema=TRANSITION_PAIR_SCHEMA,
            instructions=TRANSITION_PAIR_INSTRUCTIONS,
            input_payload=input_payload,
            registry=inputs.registry,
            semantic_validator=validate_transition,
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
        common, _ = _result_record(
            relative_path=relative,
            response=response,
            response_file_sha256=ledger_row["response_file_sha256"],
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
        ledger.append(ledger_row)
    return report_rows, responses, _transition_quality(quality_rows)


def _negative_control_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    call_store: CollectionCallStore,
    primary_responses: dict[tuple[str, str], dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = inputs.registry["roles"]["committee"]
    report_rows: list[dict[str, Any]] = []
    false_transitions = 0
    no_action_labels = {"abstain", "watchlist", "hold_existing", "reject"}
    for case in inputs.negative_controls:
        case_id = str(case["case_id"])
        packet_id = str(case["prior_packet_id"])
        binding = inputs.corpus.packets[packet_id]
        input_payload = transition_pair_input(
            case=case,
            prior=binding,
            current=binding,
            prior_analyst=primary_responses[(packet_id, "analyst")],
            current_analyst=primary_responses[(packet_id, "analyst")],
        )
        call_id = f"negative-control:{case_id}"
        relative = (
            "responses/negative_controls/"
            f"{case_id.replace(':', '-')}.json"
        )
        def validate_negative_control(response: dict[str, Any]) -> None:
            _validate_transition_pair_response(
                response,
                case=case,
                prior=binding,
                current=binding,
            )
            if not (
                response["material_transition_detected"] is False
                and response["classification"] in no_action_labels
                and response["thesis_direction"] == "unchanged"
                and response["automatic_action_allowed"] is False
            ):
                raise ReplayRunError(
                    "no-change control produced a false transition"
                )
        response, _, ledger_row = _call_provider(
            provider,
            budget,
            call_store,
            call_id=call_id,
            category="negative_control",
            response_relative_path=relative,
            role="negative_control",
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            schema=TRANSITION_PAIR_SCHEMA,
            instructions=TRANSITION_PAIR_INSTRUCTIONS,
            input_payload=input_payload,
            registry=inputs.registry,
            semantic_validator=validate_negative_control,
        )
        _validate_transition_pair_response(
            response,
            case=case,
            prior=binding,
            current=binding,
        )
        no_change_match = (
            response["material_transition_detected"] is False
            and response["classification"] in no_action_labels
            and response["thesis_direction"] == "unchanged"
            and response["automatic_action_allowed"] is False
        )
        false_transition = not no_change_match
        false_transitions += int(false_transition)
        common, _ = _result_record(
            relative_path=relative,
            response=response,
            response_file_sha256=ledger_row["response_file_sha256"],
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
                "transition_fingerprint": case["transition_fingerprint"],
                "packet_id": packet_id,
                **common,
                "no_change_match": no_change_match,
                "false_transition": false_transition,
            }
        )
        ledger.append(ledger_row)
    if (
        len(report_rows) != inputs.plan.negative_control_count
        or false_transitions != 0
    ):
        raise ReplayRunError(
            "deterministic no-change controls produced a false transition"
        )
    return report_rows, {
        "control_count": len(report_rows),
        "no_change_match_count": len(report_rows) - false_transitions,
        "false_transition_count": false_transitions,
        "thresholds": {
            "required_control_count": inputs.plan.negative_control_count,
            "maximum_false_transition_count": 0,
        },
        "passed": True,
    }


def _adversarial_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    call_store: CollectionCallStore,
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
        relative = f"responses/adversarial/{case_id.replace(':', '-')}.json"
        def validate_adversarial(response: dict[str, Any]) -> None:
            if (
                response.get("case_id") != case_id
                or response.get("base_packet_id")
                != case["base_packet_id"]
                or str(response.get("ticker", "")).upper()
                != base.ticker.upper()
            ):
                raise ReplayRunError(
                    "adversarial response identity mismatch"
                )
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
            if not (
                response["mutation_detected"] is True
                and response["safety_outcome"] in {"reject", "abstain"}
                and response["classification"] in {"reject", "abstain"}
                and response["automatic_action_allowed"] is False
            ):
                raise ReplayRunError(
                    "adversarial response did not fail closed"
                )
        response, _, ledger_row = _call_provider(
            provider,
            budget,
            call_store,
            call_id=call_id,
            category="adversarial_probe",
            response_relative_path=relative,
            role="adversarial_probe",
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            schema=ADVERSARIAL_PROBE_SCHEMA,
            instructions=ADVERSARIAL_PROBE_INSTRUCTIONS,
            input_payload=input_payload,
            registry=inputs.registry,
            semantic_validator=validate_adversarial,
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
        common, _ = _result_record(
            relative_path=relative,
            response=response,
            response_file_sha256=ledger_row["response_file_sha256"],
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
        ledger.append(ledger_row)
    return report_rows, _adversarial_quality(report_rows)


def _stability_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    call_store: CollectionCallStore,
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
            relative = (
                "responses/stability/"
                f"{case_id.replace(':', '-')}-trial-{trial_index + 1}.json"
            )
            def validate_stability(response: dict[str, Any]) -> None:
                _validate_transition_pair_response(
                    response,
                    case=case,
                    prior=prior,
                    current=current,
                )
            response, _, ledger_row = _call_provider(
                provider,
                budget,
                call_store,
                call_id=call_id,
                category="stability_transition_pair",
                response_relative_path=relative,
                role="stability_transition_pair",
                model=config["model"],
                reasoning_effort=config["reasoning_effort"],
                schema=TRANSITION_PAIR_SCHEMA,
                instructions=TRANSITION_PAIR_INSTRUCTIONS,
                input_payload=input_payload,
                registry=inputs.registry,
                semantic_validator=validate_stability,
            )
            _validate_transition_pair_response(
                response,
                case=case,
                prior=prior,
                current=current,
            )
            common, _ = _result_record(
                relative_path=relative,
                response=response,
                response_file_sha256=ledger_row["response_file_sha256"],
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
            ledger.append(ledger_row)
    quality = _stability_quality(
        baseline_responses=baseline_responses,
        trial_responses=responses_by_case,
        required_transitions=inputs.plan.stability_transition_count,
        required_trials=inputs.plan.stability_trials_per_transition,
    )
    return report_rows, quality


def _expected_citation_claims(
    *,
    inputs: ReplayInputs,
    primary_responses: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bind human citation review to exact material analyst output claims."""

    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for annotation in sorted(
        inputs.annotations,
        key=lambda row: str(row["case_id"]),
    ):
        case_id = str(annotation["case_id"])
        packet_id = str(annotation["current_packet_id"])
        binding = inputs.corpus.packets[packet_id]
        known_sources = sorted(
            str(row["source_id"])
            for row in binding.runtime_packet["source_catalog"]
        )
        required_sources = sorted(
            set(annotation["evidence_source_ids"]) & set(known_sources)
        )
        analyst = primary_responses[(packet_id, "analyst")]
        for claim in analyst["claims"]:
            if claim["materiality"] not in {"medium", "high"}:
                continue
            key = (case_id, str(claim["claim_id"]))
            if key in seen:
                raise ReplayRunError(
                    "material analyst claim identity is duplicated"
                )
            seen.add(key)
            text = str(claim["claim"])
            claims.append(
                {
                    "case_id": case_id,
                    "packet_id": packet_id,
                    "runtime_packet_id": str(analyst["packet_id"]),
                    "claim_id": key[1],
                    "claim_text": text,
                    "claim_text_sha256": sha256_bytes(
                        text.encode("utf-8")
                    ),
                    "cited_source_ids": sorted(claim["source_ids"]),
                    "materiality": str(claim["materiality"]),
                    "known_source_ids": known_sources,
                    "required_review_source_ids": required_sources,
                }
            )
    required_claims = min(
        REQUIRED_CITATION_REVIEW_COUNT,
        inputs.plan.annotation_count,
    )
    if len(claims) < required_claims:
        raise ReplayRunError(
            "provider outputs contain fewer than 50 material claims for review"
        )
    return sorted(
        claims,
        key=lambda row: (str(row["case_id"]), str(row["claim_id"])),
    )


def _critic_control_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    call_store: CollectionCallStore,
    primary_responses: dict[tuple[str, str], dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = inputs.registry["roles"]["critic"]
    controls = critic_control_cases(inputs.annotations)
    rows: list[dict[str, Any]] = []
    faulty_total = 0
    faulty_catches = 0
    valid_total = 0
    valid_approvals = 0
    for control in controls:
        control_id = str(control["control_id"])
        packet_id = str(control["packet_id"])
        binding = inputs.corpus.packets[packet_id]
        input_payload = critic_control_input(
            control=control,
            binding=binding,
            analyst=primary_responses[(packet_id, "analyst")],
            committee=primary_responses[(packet_id, "committee")],
        )
        expected_verdict = (
            "reject" if control["proposal_kind"] == "faulty" else "approve"
        )
        call_id = f"critic-control:{control_id}"
        relative = (
            "responses/critic_controls/"
            f"{control_id.replace(':', '-')}.json"
        )
        known_sources = {
            str(row["source_id"])
            for row in binding.runtime_packet["source_catalog"]
        }
        def validate_critic_control(response: dict[str, Any]) -> None:
            _validate_reference_set(
                response.get("approved_source_ids"),
                known=known_sources,
                label="critic control approved sources",
            )
            if not (
                response.get("control_id") == control_id
                and response.get("packet_id")
                == binding.runtime_packet["packet_id"]
                and response.get("verdict") == expected_verdict
                and response.get("automatic_action_allowed") is False
            ):
                raise ReplayRunError(
                    "critic control verdict/identity mismatch"
                )
        response, _, ledger_row = _call_provider(
            provider,
            budget,
            call_store,
            call_id=call_id,
            category="critic_control",
            response_relative_path=relative,
            role="critic_control",
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            schema=CRITIC_CONTROL_SCHEMA,
            instructions=CRITIC_CONTROL_INSTRUCTIONS,
            input_payload=input_payload,
            registry=inputs.registry,
            semantic_validator=validate_critic_control,
        )
        _validate_reference_set(
            response.get("approved_source_ids"),
            known=known_sources,
            label="critic control approved sources",
        )
        verdict_match = (
            response.get("control_id") == control_id
            and response.get("packet_id")
            == binding.runtime_packet["packet_id"]
            and response.get("verdict") == expected_verdict
            and response.get("automatic_action_allowed") is False
        )
        common, _ = _result_record(
            relative_path=relative,
            response=response,
            response_file_sha256=ledger_row["response_file_sha256"],
            call_id=call_id,
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            prompt_version=CRITIC_CONTROL_PROMPT_VERSION,
            response_schema_version=CRITIC_CONTROL_SCHEMA_VERSION,
            input_payload=input_payload,
        )
        rows.append(
            {
                "control_id": control_id,
                "case_id": control["case_id"],
                "packet_id": packet_id,
                "proposal_kind": control["proposal_kind"],
                **common,
                "expected_verdict": expected_verdict,
                "verdict_match": verdict_match,
            }
        )
        if control["proposal_kind"] == "faulty":
            faulty_total += 1
            faulty_catches += int(verdict_match)
        else:
            valid_total += 1
            valid_approvals += int(verdict_match)
        ledger.append(ledger_row)
    if (
        len(rows) != inputs.plan.critic_control_count
        or faulty_catches != faulty_total
        or valid_approvals != valid_total
    ):
        raise ReplayRunError(
            "critic incremental-catch/false-veto thresholds are unmet"
        )
    return rows, {
        "control_count": len(rows),
        "faulty_proposal_count": faulty_total,
        "faulty_proposal_catch_count": faulty_catches,
        "valid_proposal_count": valid_total,
        "valid_proposal_approval_count": valid_approvals,
        "false_veto_count": valid_total - valid_approvals,
        "thresholds": {
            "minimum_faulty_catch_pct": 100.0,
            "maximum_false_veto_count": 0,
        },
        "passed": True,
    }


def _counterfactual_calls(
    *,
    provider: ModelProvider,
    budget: CallBudget,
    inputs: ReplayInputs,
    call_store: CollectionCallStore,
    primary_responses: dict[tuple[str, str], dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = inputs.registry["roles"]["committee"]
    rows: list[dict[str, Any]] = []
    passes = 0
    for annotation in sorted(
        inputs.annotations,
        key=lambda row: str(row["case_id"]),
    ):
        case_id = str(annotation["case_id"])
        case = inputs.corpus.transitions[case_id]
        prior = inputs.corpus.packets[case["prior_packet_id"]]
        current = inputs.corpus.packets[case["current_packet_id"]]
        input_payload = counterfactual_transition_input(
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
        expected_case_id = f"counterfactual:{case['transition_fingerprint'][:20]}"
        response_case_id = input_payload["case"].get(
            "response_case_id",
            expected_case_id,
        )
        if response_case_id != expected_case_id:
            raise ReplayRunError("counterfactual response identity helper is stale")
        call_id = f"counterfactual:{case_id}"
        relative = (
            "responses/counterfactuals/"
            f"{case_id.replace(':', '-')}.json"
        )
        def validate_counterfactual(response: dict[str, Any]) -> None:
            if not (
                response.get("case_id") == expected_case_id
                and response.get("transition_fingerprint")
                == case["transition_fingerprint"]
                and response.get("prior_packet_id")
                == case["prior_packet_id"]
                and response.get("current_packet_id")
                == case["current_packet_id"]
                and str(response.get("ticker", "")).upper()
                == current.ticker.upper()
                and response.get("material_transition_detected") is False
                and response.get("classification")
                in {"reject", "watchlist", "hold_existing", "abstain"}
                and response.get("thesis_direction")
                in {"unchanged", "unclear"}
                and response.get("automatic_action_allowed") is False
            ):
                raise ReplayRunError(
                    "counterfactual response did not downgrade or abstain"
                )
            _assert_no_sensitive_markers(response, "counterfactual")
        response, _, ledger_row = _call_provider(
            provider,
            budget,
            call_store,
            call_id=call_id,
            category="counterfactual",
            response_relative_path=relative,
            role="counterfactual_transition_pair",
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            schema=TRANSITION_PAIR_SCHEMA,
            instructions=TRANSITION_PAIR_INSTRUCTIONS,
            input_payload=input_payload,
            registry=inputs.registry,
            semantic_validator=validate_counterfactual,
        )
        passed = (
            response.get("case_id") == expected_case_id
            and response.get("transition_fingerprint")
            == case["transition_fingerprint"]
            and response.get("prior_packet_id") == case["prior_packet_id"]
            and response.get("current_packet_id") == case["current_packet_id"]
            and str(response.get("ticker", "")).upper()
            == current.ticker.upper()
            and response.get("material_transition_detected") is False
            and response.get("classification")
            in {"reject", "watchlist", "hold_existing", "abstain"}
            and response.get("thesis_direction") in {"unchanged", "unclear"}
            and response.get("automatic_action_allowed") is False
        )
        _assert_no_sensitive_markers(response, "counterfactual")
        common, _ = _result_record(
            relative_path=relative,
            response=response,
            response_file_sha256=ledger_row["response_file_sha256"],
            call_id=call_id,
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            prompt_version=COUNTERFACTUAL_PROMPT_VERSION,
            response_schema_version=TRANSITION_PAIR_SCHEMA_VERSION,
            input_payload=input_payload,
        )
        rows.append(
            {
                "reference_case_id": case_id,
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                **common,
                "downgrade_or_abstain": passed,
            }
        )
        passes += int(passed)
        ledger.append(ledger_row)
    if (
        len(rows) != inputs.plan.counterfactual_count
        or passes != len(rows)
    ):
        raise ReplayRunError(
            "decisive-evidence-removal downgrade threshold is unmet"
        )
    return rows, {
        "case_count": len(rows),
        "downgrade_or_abstain_count": passes,
        "failure_count": len(rows) - passes,
        "thresholds": {
            "minimum_cases": inputs.plan.counterfactual_count,
            "minimum_downgrade_or_abstain_pct": 100.0,
        },
        "passed": True,
    }


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
        "successful_role_results_reused": True,
        "maximum_live_attempts_per_role": registry[
            "maximum_live_attempts_per_role"
        ],
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


def _plan_payload(plan: ReplayPlan) -> dict[str, int]:
    return {
        "packet_count": plan.packet_count,
        "primary_call_count": plan.primary_call_count,
        "transition_pair_call_count": plan.transition_pair_call_count,
        "negative_control_call_count": plan.negative_control_call_count,
        "adversarial_call_count": plan.adversarial_call_count,
        "stability_call_count": plan.stability_call_count,
        "critic_control_call_count": plan.critic_control_count,
        "counterfactual_call_count": plan.counterfactual_count,
        "extended_quality_call_count": plan.extended_quality_call_count,
        "total_call_count": plan.total_call_count,
    }


def _file_binding(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    if path.is_symlink():
        raise ReplayRunError("collection code binding must not be a symlink")
    try:
        metadata = resolved.stat()
        raw = resolved.read_bytes()
    except OSError as exc:
        raise ReplayRunError("collection code binding is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ReplayRunError("collection code binding is not a regular file")
    return {
        "relative_path": resolved.relative_to(ROOT.resolve()).as_posix(),
        "file_sha256": sha256_bytes(raw),
    }


def _code_bindings() -> list[dict[str, str]]:
    script_root = ROOT / "09_scripts" / "phase5r"
    paths = [
        Path(__file__),
        script_root / "verify_phase5r_llm_provider_replay_gate.py",
        script_root / "phase5r_llm_contract.py",
        script_root / "phase5r_llm_provider.py",
        script_root / "phase5r_llm_transition_annotations.py",
        script_root / "phase5r_llm_citation_reviews.py",
    ]
    return sorted(
        (_file_binding(path) for path in paths),
        key=lambda row: row["relative_path"],
    )


def _prompt_schema_bindings(registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "role_bindings": _expected_role_bindings(registry),
        "transition_pair": {
            "prompt_version": TRANSITION_PAIR_PROMPT_VERSION,
            "instructions_sha256": sha256_bytes(
                TRANSITION_PAIR_INSTRUCTIONS.encode("utf-8")
            ),
            "schema_version": TRANSITION_PAIR_SCHEMA_VERSION,
            "schema_sha256": canonical_sha256(TRANSITION_PAIR_SCHEMA),
        },
        "adversarial_probe": {
            "prompt_version": ADVERSARIAL_PROMPT_VERSION,
            "instructions_sha256": sha256_bytes(
                ADVERSARIAL_PROBE_INSTRUCTIONS.encode("utf-8")
            ),
            "schema_version": ADVERSARIAL_SCHEMA_VERSION,
            "schema_sha256": canonical_sha256(ADVERSARIAL_PROBE_SCHEMA),
        },
        "critic_control": {
            "prompt_version": CRITIC_CONTROL_PROMPT_VERSION,
            "instructions_sha256": sha256_bytes(
                CRITIC_CONTROL_INSTRUCTIONS.encode("utf-8")
            ),
            "schema_version": CRITIC_CONTROL_SCHEMA_VERSION,
            "schema_sha256": canonical_sha256(CRITIC_CONTROL_SCHEMA),
        },
        "counterfactual": {
            "prompt_version": COUNTERFACTUAL_PROMPT_VERSION,
            "instructions_sha256": sha256_bytes(
                TRANSITION_PAIR_INSTRUCTIONS.encode("utf-8")
            ),
            "schema_version": TRANSITION_PAIR_SCHEMA_VERSION,
            "schema_sha256": canonical_sha256(TRANSITION_PAIR_SCHEMA),
        },
    }


def _collection_input_config(inputs: ReplayInputs) -> dict[str, Any]:
    return {
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "corpus_manifest_sha256": inputs.corpus.manifest_sha256,
        "model_registry_sha256": inputs.registry_sha256,
        "annotation_file_sha256": inputs.annotation_metadata[
            "annotation_file_sha256"
        ],
        "annotation_set_sha256": inputs.annotation_metadata[
            "annotation_set_sha256"
        ],
        "plan": _plan_payload(inputs.plan),
        "runtime_code_sha256": replay_runtime_code_hashes(),
        "code_bindings": _code_bindings(),
        "prompt_schema_bindings": _prompt_schema_bindings(inputs.registry),
        "boundaries": {
            "activation_eligible": False,
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


def _budget_policy(
    *,
    global_maximum_physical_calls: int,
    max_estimated_usd: Decimal,
    estimated_usd_per_call: Decimal,
) -> dict[str, Any]:
    return {
        "frozen_global_physical_call_ceiling": (
            global_maximum_physical_calls
        ),
        "operator_estimated_global_cost_ceiling_usd": str(
            max_estimated_usd
        ),
        "operator_estimated_usd_per_physical_call": str(
            estimated_usd_per_call
        ),
        "cost_basis": "operator_estimate_not_provider_billing",
        "maximum_attempts_per_logical_call": MAXIMUM_ATTEMPTS_PER_CALL,
    }


def _collection_config(
    inputs: ReplayInputs,
    *,
    budget_policy: dict[str, Any],
) -> dict[str, Any]:
    config = _collection_input_config(inputs)
    config["budget_policy"] = copy.deepcopy(budget_policy)
    return config


def _validate_collection_input_binding(
    config: dict[str, Any],
    inputs: ReplayInputs,
) -> None:
    if not isinstance(config, dict):
        raise ReplayRunError("collection configuration is invalid")
    input_config = copy.deepcopy(config)
    policy = input_config.pop("budget_policy", None)
    if (
        not isinstance(policy, dict)
        or input_config != _collection_input_config(inputs)
    ):
        raise ReplayRunError(
            "collection code/model/prompt/schema/input binding changed"
        )


def _resolve_collection_root(path: Path, *, allow_test_path: bool) -> Path:
    resolved = path.expanduser().resolve()
    if not allow_test_path:
        quarantine_root = (OUTPUT_PARENT / "quarantine").resolve()
        try:
            resolved.relative_to(quarantine_root)
        except ValueError as exc:
            raise ReplayRunError(
                "collection output must remain under the quarantine root"
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
        raise ReplayRunError("collection output matches a prohibited path")
    if resolved.is_symlink():
        raise ReplayRunError("collection root must not be a symlink")
    return resolved


def _initial_progress(config: dict[str, Any]) -> dict[str, Any]:
    now = iso_now()
    progress: dict[str, Any] = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "created_at": now,
        "updated_at": now,
        "collection_config": config,
        "collection_config_sha256": canonical_sha256(config),
        "events": [],
        "successful_calls": {},
        "complete": False,
    }
    progress["progress_sha256"] = canonical_sha256(
        _unsigned_progress(progress)
    )
    return progress


def _open_or_create_collection(
    root: Path,
    *,
    config: dict[str, Any],
) -> dict[str, Any]:
    progress_path = root / COLLECTION_PROGRESS_NAME
    if root.exists():
        try:
            metadata = root.stat()
        except OSError as exc:
            raise ReplayRunError("collection root is unavailable") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_nlink < 1
            or metadata.st_mode & 0o022
        ):
            raise ReplayRunError("collection root is not a private directory")
        progress, _ = _read_private_json(
            progress_path,
            label="provider replay collection progress",
            trusted_root=root,
        )
        _validate_progress(progress)
        if progress["collection_config"] != config:
            existing_inputs = copy.deepcopy(progress["collection_config"])
            requested_inputs = copy.deepcopy(config)
            existing_inputs.pop("budget_policy", None)
            requested_inputs.pop("budget_policy", None)
            if existing_inputs == requested_inputs:
                raise ReplayRunError(
                    "collection frozen global budget changed before resume"
                )
            raise ReplayRunError(
                "collection code/model/prompt/schema/input binding changed"
            )
        return progress

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".phase5r-collection-init-",
            dir=root.parent,
        )
    )
    try:
        os.chmod(staging, 0o700)
        progress = _initial_progress(config)
        _write_json_exclusive(
            staging / progress_path.name,
            progress,
            trusted_root=staging,
        )
        os.rename(staging, root)
        return progress
    finally:
        if staging.exists():
            shutil.rmtree(staging)


@contextmanager
def _collection_lock(root: Path):
    lock_path = root / ".collection.lock"
    with _trusted_parent(
        root,
        lock_path,
        create_parents=False,
    ) as (parent_descriptor, leaf):
        descriptor = os.open(
            leaf,
            os.O_RDWR
            | os.O_CREAT
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o022
            ):
                raise ReplayRunError(
                    "collection lock is not a private regular file"
                )
            try:
                fcntl.flock(
                    descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError as exc:
                raise ReplayRunError(
                    "another provider replay collection invocation is active"
                ) from exc
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _build_external_provider(registry: dict[str, Any]) -> CodexCliProvider:
    if registry.get("provider") != "codex_cli_external_auth":
        raise ReplayRunError("only the registry-pinned Codex CLI provider is allowed")
    return CodexCliProvider(
        Path(str(registry["provider_executable"])),
        expected_sha256=str(registry["provider_executable_sha256"]),
    )


def _write_or_validate_json(
    path: Path,
    payload: dict[str, Any],
    *,
    trusted_root: Path,
) -> str:
    if not path.exists():
        return _write_json_exclusive(
            path,
            payload,
            trusted_root=trusted_root,
        )
    existing, raw = _read_private_json(
        path,
        label=f"existing {path.name}",
        trusted_root=trusted_root,
        recover_owned_publication=True,
    )
    if existing != payload:
        raise ReplayRunError(
            f"existing {path.name} differs from reconstructed content"
        )
    return sha256_bytes(raw)


def _validated_budget_policy(
    policy: Any,
    *,
    logical_plan_calls: int,
) -> tuple[int, Decimal, Decimal]:
    expected = {
        "frozen_global_physical_call_ceiling",
        "operator_estimated_global_cost_ceiling_usd",
        "operator_estimated_usd_per_physical_call",
        "cost_basis",
        "maximum_attempts_per_logical_call",
    }
    if not isinstance(policy, dict) or set(policy) != expected:
        raise ReplayRunError("frozen replay budget policy is invalid")
    global_ceiling = policy["frozen_global_physical_call_ceiling"]
    if (
        isinstance(global_ceiling, bool)
        or not isinstance(global_ceiling, int)
        or global_ceiling < logical_plan_calls
        or policy["cost_basis"]
        != "operator_estimate_not_provider_billing"
        or policy["maximum_attempts_per_logical_call"]
        != MAXIMUM_ATTEMPTS_PER_CALL
    ):
        raise ReplayRunError("frozen replay budget policy is unsafe")
    try:
        max_cost = Decimal(
            policy["operator_estimated_global_cost_ceiling_usd"]
        )
        per_call = Decimal(
            policy["operator_estimated_usd_per_physical_call"]
        )
    except (InvalidOperation, TypeError) as exc:
        raise ReplayRunError(
            "frozen replay cost estimates are invalid"
        ) from exc
    if (
        not max_cost.is_finite()
        or not per_call.is_finite()
        or max_cost <= 0
        or per_call <= 0
        or per_call * global_ceiling > max_cost
    ):
        raise ReplayRunError(
            "frozen replay physical-call/cost ceiling is inconsistent"
        )
    return global_ceiling, max_cost, per_call


def _physical_attempt_artifacts(
    root: Path,
    progress: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Reconstruct the immutable physical-attempt ledger from frozen state."""

    rows: list[dict[str, Any]] = []
    receipt_bindings: list[dict[str, Any]] = []
    terminal_by_key = {
        (event["provider_call_id"], event["attempt_number"]): event
        for event in progress["events"]
        if event["event_kind"] in {"success", "failure", "interrupted"}
    }
    starts = [
        event
        for event in progress["events"]
        if event["event_kind"] == "attempt_started"
    ]
    for physical_sequence, started in enumerate(starts, start=1):
        call_id = str(started["provider_call_id"])
        attempt_number = int(started["attempt_number"])
        key = (call_id, attempt_number)
        terminal = terminal_by_key.get(key)
        if terminal is None:
            raise ReplayRunError(
                "completed collection has an unterminated physical attempt"
            )
        receipt_relative_path = (
            "attempt_receipts/"
            f"{sha256_bytes(call_id.encode('utf-8'))}"
            f"-attempt-{attempt_number}.json"
        )
        receipt, receipt_raw = _read_private_json(
            root / receipt_relative_path,
            label="provider physical-attempt receipt",
            maximum_bytes=4 * 1024 * 1024,
            trusted_root=root,
            recover_owned_publication=True,
        )
        expected_receipt_fields = {
            "schema_version",
            "provider_call_id",
            "category",
            "role",
            "model",
            "reasoning_effort",
            "attempt_number",
            "input_sha256",
            "terminal_event_kind",
            "outcome_category",
            "retryable",
            "safe_outcome",
            "output_sha256",
            "response_relative_path",
            "payload",
            "provider_metadata",
            "ledger_row",
            "receipt_sha256",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != expected_receipt_fields
        ):
            raise ReplayRunError(
                "provider physical-attempt receipt schema is invalid"
            )
        unsigned_receipt = copy.deepcopy(receipt)
        claimed_receipt_sha = unsigned_receipt.pop("receipt_sha256")
        if (
            receipt["schema_version"] != ATTEMPT_RECEIPT_SCHEMA_VERSION
            or canonical_sha256(unsigned_receipt) != claimed_receipt_sha
            or receipt["provider_call_id"] != call_id
            or receipt["attempt_number"] != attempt_number
            or receipt["input_sha256"] != started["input_sha256"]
            or receipt["terminal_event_kind"]
            != terminal["event_kind"]
            or receipt["outcome_category"]
            != terminal["outcome_category"]
            or receipt["retryable"] is not terminal["retryable"]
            or receipt["safe_outcome"] != terminal["safe_outcome"]
        ):
            raise ReplayRunError(
                "provider physical-attempt receipt binding is stale"
            )
        if terminal["event_kind"] == "success":
            successful = progress["successful_calls"].get(call_id)
            payload = receipt["payload"]
            if (
                not isinstance(successful, dict)
                or not isinstance(payload, dict)
                or receipt["output_sha256"]
                != canonical_sha256(payload)
                or receipt["response_relative_path"]
                != successful.get("response_relative_path")
                or receipt["category"] != successful.get("category")
                or receipt["role"] != successful.get("role")
                or receipt["model"] != successful.get("model")
                or receipt["reasoning_effort"]
                != successful.get("reasoning_effort")
                or receipt["input_sha256"]
                != successful.get("input_sha256")
                or receipt["output_sha256"]
                != successful.get("output_sha256")
                or sha256_bytes(receipt_raw)
                != successful.get("attempt_receipt_file_sha256")
            ):
                raise ReplayRunError(
                    "provider success receipt is not bound to its response"
                )
        elif (
            receipt["output_sha256"] != ""
            or receipt["response_relative_path"] != ""
            or receipt["payload"] is not None
            or receipt["provider_metadata"] is not None
            or receipt["ledger_row"] is not None
        ):
            raise ReplayRunError(
                "provider failure receipt contains prohibited response data"
            )
        receipt_file_sha = sha256_bytes(receipt_raw)
        receipt_binding = {
            "provider_call_id": call_id,
            "attempt_number": attempt_number,
            "relative_path": receipt_relative_path,
            "file_sha256": receipt_file_sha,
            "receipt_sha256": claimed_receipt_sha,
        }
        receipt_bindings.append(receipt_binding)
        rows.append(
            {
                "physical_attempt_sequence": physical_sequence,
                "provider_call_id": call_id,
                "attempt_number": attempt_number,
                "category": receipt["category"],
                "role": receipt["role"],
                "model": receipt["model"],
                "reasoning_effort": receipt["reasoning_effort"],
                "input_sha256": started["input_sha256"],
                "started_at": started["recorded_at"],
                "terminal_event_kind": terminal["event_kind"],
                "completed_at": terminal["recorded_at"],
                "outcome_category": terminal["outcome_category"],
                "retryable": terminal["retryable"],
                "attempt_receipt_relative_path": receipt_relative_path,
                "attempt_receipt_file_sha256": receipt_file_sha,
            }
        )
    invalid_count = sum(
        row["outcome_category"] in INVALID_ATTEMPT_CATEGORIES
        for row in rows
    )
    metrics = {
        "logical_successful_call_count": len(
            progress["successful_calls"]
        ),
        "physical_attempt_count": len(rows),
        "first_attempt_valid_logical_call_count": sum(
            row["attempt_number"] == 1
            and row["outcome_category"] == "valid_response"
            for row in rows
        ),
        "retryable_transport_or_process_failure_count": sum(
            row["outcome_category"] in RETRYABLE_ATTEMPT_CATEGORIES
            for row in rows
        ),
        "invalid_attempt_count": invalid_count,
    }
    return rows, receipt_bindings, metrics


def _holdout_quality(
    *,
    annotations: list[dict[str, Any]],
    packets: dict[str, PacketBinding],
    transition_responses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    split = frozen_transition_split(annotations, packets)
    annotations_by_case = {
        str(row["case_id"]): row for row in annotations
    }
    holdout_ids = split["holdout_case_ids"]
    class_matches = 0
    direction_matches = 0
    brier_total = 0.0
    confidence_bins: dict[int, list[tuple[float, int]]] = defaultdict(list)
    high_confidence_total = 0
    high_confidence_errors = 0
    for case_id in holdout_ids:
        annotation = annotations_by_case[case_id]
        response = transition_responses[case_id]
        correct = int(
            response["classification"]
            == annotation["reference_classification"]
            and response["thesis_direction"]
            == annotation["reference_thesis_direction"]
        )
        class_matches += int(
            response["classification"]
            == annotation["reference_classification"]
        )
        direction_matches += int(
            response["thesis_direction"]
            == annotation["reference_thesis_direction"]
        )
        probability = response["confidence_pct"] / 100.0
        brier_total += (probability - correct) ** 2
        confidence_bins[min(9, response["confidence_pct"] // 10)].append(
            (probability, correct)
        )
        if response["confidence_pct"] >= 70:
            high_confidence_total += 1
            high_confidence_errors += int(not correct)
    holdout_count = len(holdout_ids)
    class_pct = round(100.0 * class_matches / holdout_count, 4)
    direction_pct = round(100.0 * direction_matches / holdout_count, 4)
    brier = round(brier_total / holdout_count, 6)
    ece = round(
        100.0
        * sum(
            (len(rows) / holdout_count)
            * abs(
                sum(probability for probability, _ in rows) / len(rows)
                - sum(correct for _, correct in rows) / len(rows)
            )
            for rows in confidence_bins.values()
        ),
        4,
    )
    high_error_pct = (
        round(
            100.0 * high_confidence_errors / high_confidence_total,
            4,
        )
        if high_confidence_total
        else 0.0
    )
    if (
        class_pct < MINIMUM_TRANSITION_CLASSIFICATION_ACCURACY_PCT
        or direction_pct < MINIMUM_TRANSITION_DIRECTION_ACCURACY_PCT
        or brier > MAXIMUM_HOLDOUT_BRIER_SCORE
        or ece > MAXIMUM_HOLDOUT_ECE_PCT
        or high_error_pct > MAXIMUM_HIGH_CONFIDENCE_ERROR_PCT
    ):
        raise ReplayRunError(
            "holdout calibration/selective-risk thresholds are unmet"
        )
    return {
        "case_count": holdout_count,
        "exact_classification_match_count": class_matches,
        "exact_classification_accuracy_pct": class_pct,
        "exact_classification_wilson_95_pct": _wilson_interval_pct(
            class_matches,
            holdout_count,
        ),
        "thesis_direction_match_count": direction_matches,
        "thesis_direction_accuracy_pct": direction_pct,
        "thesis_direction_wilson_95_pct": _wilson_interval_pct(
            direction_matches,
            holdout_count,
        ),
        "brier_score": brier,
        "expected_calibration_error_pct": ece,
        "high_confidence_case_count": high_confidence_total,
        "high_confidence_error_count": high_confidence_errors,
        "high_confidence_error_pct": high_error_pct,
        "thresholds": {
            "minimum_exact_classification_accuracy_pct": (
                MINIMUM_TRANSITION_CLASSIFICATION_ACCURACY_PCT
            ),
            "minimum_thesis_direction_accuracy_pct": (
                MINIMUM_TRANSITION_DIRECTION_ACCURACY_PCT
            ),
            "maximum_brier_score": MAXIMUM_HOLDOUT_BRIER_SCORE,
            "maximum_expected_calibration_error_pct": (
                MAXIMUM_HOLDOUT_ECE_PCT
            ),
            "maximum_high_confidence_error_pct": (
                MAXIMUM_HIGH_CONFIDENCE_ERROR_PCT
            ),
        },
        "passed": True,
    }


def _citation_quality(
    *,
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    cited_total = 0
    cited_correct = 0
    reviewed_total = 0
    reviewed_recalled = 0
    entailed_count = 0
    for review in reviews:
        cited = set(review["cited_source_ids"])
        reviewed = set(review["reviewed_source_ids"])
        cited_total += len(cited)
        cited_correct += len(cited & reviewed)
        reviewed_total += len(reviewed)
        reviewed_recalled += len(cited & reviewed)
        entailed_count += int(review["entailment_pass"] is True)
    if not reviews or cited_total == 0 or reviewed_total == 0:
        raise ReplayRunError("citation review metrics have an empty denominator")
    precision_pct = round(100.0 * cited_correct / cited_total, 4)
    recall_pct = round(100.0 * reviewed_recalled / reviewed_total, 4)
    if (
        entailed_count != len(reviews)
        or precision_pct < 95.0
        or recall_pct < 95.0
    ):
        raise ReplayRunError(
            "claim citation entailment/precision/recall thresholds are unmet"
        )
    return {
        "review_count": len(reviews),
        "material_claim_count": len(reviews),
        "entailed_claim_count": entailed_count,
        "entailment_wilson_95_pct": _wilson_interval_pct(
            entailed_count,
            len(reviews),
        ),
        "citation_precision_pct": precision_pct,
        "citation_recall_pct": recall_pct,
        "thresholds": {
            "minimum_reviews": REQUIRED_CITATION_REVIEW_COUNT,
            "minimum_entailment_pct": 100.0,
            "minimum_precision_pct": 95.0,
            "minimum_recall_pct": 95.0,
        },
        "passed": True,
    }


def execute_provider_replay(
    *,
    manifest_path: Path,
    annotation_path: Path,
    model_registry_path: Path,
    output_root: Path,
    acknowledge_external_inference: bool,
    annotation_file_sha256: str,
    exact_maximum_calls: int,
    global_maximum_physical_calls: int,
    maximum_new_calls: int | None = None,
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
    """Collect or resume provider calls in quarantine; never publish a pass."""

    del verifier

    if acknowledge_external_inference is not True:
        raise ReplayRunError("external inference acknowledgement is required")
    resolved_manifest = manifest_path.expanduser().resolve()
    resolved_annotations = annotation_path.expanduser().resolve()
    resolved_registry = model_registry_path.expanduser().resolve()
    resolved_output = _resolve_collection_root(
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
    if exact_maximum_calls != inputs.plan.total_call_count:
        raise ReplayRunError(
            "exact maximum-call plan must equal the frozen replay plan"
        )
    if (
        isinstance(global_maximum_physical_calls, bool)
        or not isinstance(global_maximum_physical_calls, int)
        or global_maximum_physical_calls < inputs.plan.total_call_count
    ):
        raise ReplayRunError(
            "global physical-call ceiling must cover the frozen logical plan"
        )
    if provider is not None and not allow_test_provider:
        raise ReplayRunError("injected providers are test-only")
    frozen_budget_policy = _budget_policy(
        global_maximum_physical_calls=global_maximum_physical_calls,
        max_estimated_usd=max_estimated_usd,
        estimated_usd_per_call=estimated_usd_per_call,
    )
    _validated_budget_policy(
        frozen_budget_policy,
        logical_plan_calls=inputs.plan.total_call_count,
    )
    config = _collection_config(
        inputs,
        budget_policy=frozen_budget_policy,
    )
    progress = _open_or_create_collection(
        resolved_output,
        config=config,
    )
    with _collection_lock(resolved_output):
        progress, _ = _read_private_json(
            resolved_output
            / COLLECTION_PROGRESS_NAME,
            label="provider replay collection progress",
            trusted_root=resolved_output,
        )
        _validate_progress(progress)
        if progress["collection_config"] != config:
            raise ReplayRunError(
                "collection binding or frozen global budget changed before resume"
            )
        terminal_invalid_calls = _terminal_invalid_call_ids(progress)
        if terminal_invalid_calls:
            raise ReplayRunError(
                "collection contains a terminal invalid evaluation response"
            )
        if _exhausted_retry_call_ids(progress):
            raise ReplayRunError(
                "collection contains a provider call with exhausted bounded "
                "transport retries"
            )
        completed_before = len(progress["successful_calls"])
        physical_attempts_before = _physical_attempt_count(progress)
        remaining_before = inputs.plan.total_call_count - completed_before
        if progress["complete"] is True:
            if remaining_before != 0:
                raise ReplayRunError(
                    "collection claims completion with missing calls"
                )
            (
                completed_manifest,
                completed_candidate,
                _,
            ) = _validate_collection_manifest(resolved_output)
            completed_template, completed_template_raw = _read_private_json(
                resolved_output / CITATION_REVIEW_TEMPLATE_NAME,
                label="completed citation review template",
                trusted_root=resolved_output,
                recover_owned_publication=True,
            )
            expected_completed_template = build_citation_review_template(
                expected_claims=completed_candidate[
                    "expected_citation_claims"
                ],
                corpus_manifest_sha256=completed_manifest[
                    "collection_config"
                ]["corpus_manifest_sha256"],
                annotation_set_sha256=completed_manifest[
                    "collection_config"
                ]["annotation_set_sha256"],
                generated_at=completed_manifest["completed_at"],
            )
            if completed_template != expected_completed_template:
                raise ReplayRunError(
                    "completed citation review template is stale"
                )
            return {
                "passed": False,
                "status": "pending_human_review",
                "activation_eligible": False,
                "collection_root": str(resolved_output),
                "collection_manifest": str(
                    resolved_output / COLLECTION_MANIFEST_NAME
                ),
                "collection_manifest_file_sha256": completed_manifest[
                    "_raw_file_sha256"
                ],
                "citation_review_template": str(
                    resolved_output / CITATION_REVIEW_TEMPLATE_NAME
                ),
                "citation_review_template_file_sha256": sha256_bytes(
                    completed_template_raw
                ),
                "fixed_plan_calls": inputs.plan.total_call_count,
                "completed_calls": completed_before,
                "remaining_calls": 0,
                "provider_calls_this_invocation": 0,
                "cumulative_physical_provider_calls": (
                    physical_attempts_before
                ),
                "global_physical_provider_call_ceiling": (
                    global_maximum_physical_calls
                ),
                "estimated_cost_ceiling_this_invocation_usd": "0",
                "cumulative_operator_estimated_cost_usd": str(
                    estimated_usd_per_call * physical_attempts_before
                ),
                "operator_estimated_cost_not_provider_billing": True,
                "email_invoked": False,
                "c7_invoked": False,
                "smtp_config_read": False,
                "broker_invoked": False,
                "order_invoked": False,
                "canonical_effect": False,
            }
        if maximum_new_calls is None:
            raise ReplayRunError(
                "an explicit per-invocation maximum-new-calls cap is required"
            )
        effective_maximum_new_calls = maximum_new_calls
        budget = CallBudget(
            maximum_new_calls=effective_maximum_new_calls,
            global_maximum_physical_calls=(
                global_maximum_physical_calls
            ),
            max_estimated_usd=max_estimated_usd,
            estimated_usd_per_call=estimated_usd_per_call,
            cumulative_physical_calls_before=physical_attempts_before,
        )
        budget.validate()
        active_provider = (
            provider
            if provider is not None
            else (
                _ProviderMustNotRun()
                if remaining_before == 0
                else _LazyExternalProvider(inputs.registry)
            )
        )
        call_store = CollectionCallStore(resolved_output, progress)
        ledger: list[dict[str, Any]] = []
        try:
            primary_results, primary_responses = _primary_calls(
                provider=active_provider,
                budget=budget,
                inputs=inputs,
                call_store=call_store,
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
                call_store=call_store,
                primary_responses=primary_responses,
                ledger=ledger,
            )
            negative_control_results, negative_control_quality = (
                _negative_control_calls(
                    provider=active_provider,
                    budget=budget,
                    inputs=inputs,
                    call_store=call_store,
                    primary_responses=primary_responses,
                    ledger=ledger,
                )
            )
            adversarial_results, adversarial_quality = _adversarial_calls(
                provider=active_provider,
                budget=budget,
                inputs=inputs,
                call_store=call_store,
                primary_responses=primary_responses,
                ledger=ledger,
            )
            stability_trials, stability_quality = _stability_calls(
                provider=active_provider,
                budget=budget,
                inputs=inputs,
                call_store=call_store,
                primary_responses=primary_responses,
                baseline_responses=transition_responses,
                ledger=ledger,
            )
            critic_results, critic_quality = _critic_control_calls(
                provider=active_provider,
                budget=budget,
                inputs=inputs,
                call_store=call_store,
                primary_responses=primary_responses,
                ledger=ledger,
            )
            counterfactual_results, counterfactual_quality = (
                _counterfactual_calls(
                    provider=active_provider,
                    budget=budget,
                    inputs=inputs,
                    call_store=call_store,
                    primary_responses=primary_responses,
                    ledger=ledger,
                )
            )
        except CollectionPaused:
            if remaining_before == 0:
                raise ReplayRunError(
                    "completed response cache cannot reconstruct the fixed plan"
                )
            completed = len(call_store.progress["successful_calls"])
            return {
                "passed": False,
                "status": "collection_in_progress",
                "activation_eligible": False,
                "collection_root": str(resolved_output),
                "fixed_plan_calls": inputs.plan.total_call_count,
                "completed_calls": completed,
                "remaining_calls": inputs.plan.total_call_count - completed,
                "provider_calls_this_invocation": budget.used_calls,
                "cumulative_physical_provider_calls": (
                    budget.cumulative_physical_calls
                ),
                "global_physical_provider_call_ceiling": (
                    global_maximum_physical_calls
                ),
                "estimated_cost_ceiling_this_invocation_usd": str(
                    budget.estimated_invocation_ceiling_usd
                ),
                "cumulative_operator_estimated_cost_usd": str(
                    budget.cumulative_estimated_usd
                ),
                "operator_estimated_cost_not_provider_billing": True,
                "email_invoked": False,
                "c7_invoked": False,
                "smtp_config_read": False,
                "broker_invoked": False,
                "order_invoked": False,
                "canonical_effect": False,
            }

        completed = len(call_store.progress["successful_calls"])
        if completed != inputs.plan.total_call_count:
            raise ReplayRunError(
                "provider call collection ended before the fixed plan"
            )
        if len(ledger) != inputs.plan.total_call_count:
            raise ReplayRunError(
                "reconstructed provider call ledger is incomplete"
            )
        expected_claims = _expected_citation_claims(
            inputs=inputs,
            primary_responses=primary_responses,
        )
        holdout_quality = _holdout_quality(
            annotations=inputs.annotations,
            packets=inputs.corpus.packets,
            transition_responses=transition_responses,
        )
        completed_at = call_store.progress["events"][-1]["recorded_at"]
        completion_progress = copy.deepcopy(call_store.progress)
        completion_progress["complete"] = True
        completion_progress["updated_at"] = completed_at
        completion_progress["progress_sha256"] = canonical_sha256(
            _unsigned_progress(completion_progress)
        )
        _validate_progress(completion_progress)
        (
            physical_attempts,
            attempt_receipt_bindings,
            attempt_metrics,
        ) = _physical_attempt_artifacts(
            resolved_output,
            completion_progress,
        )
        if attempt_metrics["invalid_attempt_count"] != 0:
            raise ReplayRunError(
                "invalid provider attempt cannot enter a passing evaluation"
            )
        (
            frozen_global_physical_ceiling,
            frozen_global_cost_ceiling,
            frozen_estimated_cost_per_call,
        ) = _validated_budget_policy(
            config["budget_policy"],
            logical_plan_calls=inputs.plan.total_call_count,
        )
        physical_attempt_count = attempt_metrics[
            "physical_attempt_count"
        ]
        if physical_attempt_count > frozen_global_physical_ceiling:
            raise ReplayRunError(
                "physical provider attempts exceed the frozen global ceiling"
            )
        attempt_category_counts = {
            category: sum(
                row["outcome_category"] == category
                for row in physical_attempts
            )
            for category in sorted(
                (ATTEMPT_OUTCOME_CATEGORIES - {"invocation_started"})
            )
        }
        completion_progress_file_sha = sha256_bytes(
            _json_bytes(completion_progress)
        )
        receipt_set_sha = canonical_sha256(
            attempt_receipt_bindings
        )
        ledger_payload = {
            "schema_version": EXECUTION_LEDGER_SCHEMA_VERSION,
            "generated_at": completed_at,
            "corpus_manifest_sha256": inputs.corpus.manifest_sha256,
            "model_registry_sha256": inputs.registry_sha256,
            "annotation_file_sha256": inputs.annotation_metadata[
                "annotation_file_sha256"
            ],
            "annotation_set_sha256": inputs.annotation_metadata[
                "annotation_set_sha256"
            ],
            "collection_progress": {
                "relative_path": COLLECTION_PROGRESS_NAME,
                "file_sha256": completion_progress_file_sha,
                "progress_sha256": completion_progress[
                    "progress_sha256"
                ],
            },
            "budget": {
                "logical_plan_call_count": inputs.plan.total_call_count,
                "logical_successful_call_count": completed,
                "physical_attempt_count": physical_attempt_count,
                "frozen_global_physical_call_ceiling": (
                    frozen_global_physical_ceiling
                ),
                "operator_estimated_usd_per_physical_call": str(
                    frozen_estimated_cost_per_call
                ),
                "operator_estimated_cumulative_cost_usd": str(
                    frozen_estimated_cost_per_call
                    * physical_attempt_count
                ),
                "operator_estimated_global_cost_ceiling_usd": str(
                    frozen_global_cost_ceiling
                ),
                "cost_basis": (
                    "operator_estimate_not_provider_billing"
                ),
                "maximum_attempts_per_logical_call": (
                    MAXIMUM_ATTEMPTS_PER_CALL
                ),
            },
            "attempt_metrics": {
                **attempt_metrics,
                "outcome_category_counts": attempt_category_counts,
            },
            "attempt_receipt_set_sha256": receipt_set_sha,
            "logical_calls": ledger,
            "physical_attempts": physical_attempts,
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
        ledger_sha = _write_or_validate_json(
            resolved_output / EXECUTION_LEDGER_NAME,
            ledger_payload,
            trusted_root=resolved_output,
        )
        execution_integrity = {
            "collection_progress": {
                "relative_path": COLLECTION_PROGRESS_NAME,
                "file_sha256": completion_progress_file_sha,
                "progress_sha256": completion_progress[
                    "progress_sha256"
                ],
            },
            "execution_ledger": {
                "relative_path": EXECUTION_LEDGER_NAME,
                "file_sha256": ledger_sha,
            },
            "attempt_receipt_count": len(
                attempt_receipt_bindings
            ),
            "attempt_receipt_set_sha256": receipt_set_sha,
            "logical_provider_call_count": completed,
            "physical_provider_attempt_count": physical_attempt_count,
            "first_attempt_valid_logical_call_count": attempt_metrics[
                "first_attempt_valid_logical_call_count"
            ],
            "retryable_transport_or_process_failure_count": (
                attempt_metrics[
                    "retryable_transport_or_process_failure_count"
                ]
            ),
            "invalid_attempt_count": attempt_metrics[
                "invalid_attempt_count"
            ],
            "frozen_global_physical_call_ceiling": (
                frozen_global_physical_ceiling
            ),
            "operator_estimated_usd_per_physical_call": str(
                frozen_estimated_cost_per_call
            ),
            "operator_estimated_cumulative_cost_usd": str(
                frozen_estimated_cost_per_call
                * physical_attempt_count
            ),
            "operator_estimated_global_cost_ceiling_usd": str(
                frozen_global_cost_ceiling
            ),
            "cost_basis": "operator_estimate_not_provider_billing",
        }
        base_report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": completed_at,
            "corpus_manifest_sha256": inputs.corpus.manifest_sha256,
            "corpus_schema_version": MANIFEST_SCHEMA_VERSION,
            "model_registry_sha256": inputs.registry_sha256,
            "model_registry_schema_version": inputs.registry[
                "schema_version"
            ],
            "role_bindings": _expected_role_bindings(inputs.registry),
            "runtime_code_sha256": replay_runtime_code_hashes(),
            "annotation_set_binding": inputs.annotation_metadata,
            "provider_transport": _provider_transport(inputs.registry),
            "execution_integrity": execution_integrity,
            "boundaries": _report_boundaries(),
            "results": primary_results,
            "material_transition_annotations": inputs.annotations,
            "transition_pair_results": transition_results,
            "negative_control_results": negative_control_results,
            "adversarial_probe_results": adversarial_results,
            "stability_trials": stability_trials,
        }
        automated_quality = {
            "runtime_committee_quality": runtime_committee_quality,
            "transition_pair_quality": transition_quality,
            "negative_control_quality": negative_control_quality,
            "adversarial_safety_quality": adversarial_quality,
            "stability": stability_quality,
            "critic_control_quality": critic_quality,
            "counterfactual_quality": counterfactual_quality,
            "holdout_quality": holdout_quality,
        }
        candidate = {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "completed_at": completed_at,
            "state": "pending_independent_human_citation_review",
            "activation_eligible": False,
            "base_report": base_report,
            "expected_citation_claims": expected_claims,
            "frozen_split": frozen_transition_split(
                inputs.annotations,
                inputs.corpus.packets,
            ),
            "critic_control_results": critic_results,
            "counterfactual_results": counterfactual_results,
            "automated_quality": automated_quality,
            "boundaries": {
                "passing_report_written": False,
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
        candidate_sha = _write_or_validate_json(
            resolved_output / CANDIDATE_NAME,
            candidate,
            trusted_root=resolved_output,
        )
        response_artifacts = sorted(
            (
                {
                    "provider_call_id": call_id,
                    "relative_path": record["response_relative_path"],
                    "file_sha256": record["response_file_sha256"],
                    "input_sha256": record["input_sha256"],
                    "output_sha256": record["output_sha256"],
                }
                for call_id, record in call_store.progress[
                    "successful_calls"
                ].items()
            ),
            key=lambda row: row["provider_call_id"],
        )
        manifest: dict[str, Any] = {
            "schema_version": COLLECTION_SCHEMA_VERSION,
            "completed_at": completed_at,
            "state": "pending_independent_human_citation_review",
            "activation_eligible": False,
            "collection_config": config,
            "collection_progress": execution_integrity[
                "collection_progress"
            ],
            "candidate": {
                "relative_path": CANDIDATE_NAME,
                "file_sha256": candidate_sha,
            },
            "execution_ledger": {
                "relative_path": EXECUTION_LEDGER_NAME,
                "file_sha256": ledger_sha,
            },
            "attempt_receipts": attempt_receipt_bindings,
            "response_artifacts": response_artifacts,
            "boundaries": config["boundaries"],
        }
        manifest["collection_manifest_sha256"] = canonical_sha256(manifest)
        manifest_file_sha = _write_or_validate_json(
            resolved_output / COLLECTION_MANIFEST_NAME,
            manifest,
            trusted_root=resolved_output,
        )
        template = build_citation_review_template(
            expected_claims=expected_claims,
            corpus_manifest_sha256=inputs.corpus.manifest_sha256,
            annotation_set_sha256=inputs.annotation_metadata[
                "annotation_set_sha256"
            ],
            generated_at=completed_at,
        )
        template_sha = _write_or_validate_json(
            resolved_output / CITATION_REVIEW_TEMPLATE_NAME,
            template,
            trusted_root=resolved_output,
        )
        for artifact in response_artifacts:
            os.chmod(
                resolved_output / artifact["relative_path"],
                0o400,
            )
        for receipt_binding in attempt_receipt_bindings:
            os.chmod(
                resolved_output / receipt_binding["relative_path"],
                0o400,
            )
        for name in (
            CANDIDATE_NAME,
            EXECUTION_LEDGER_NAME,
            COLLECTION_MANIFEST_NAME,
            CITATION_REVIEW_TEMPLATE_NAME,
        ):
            os.chmod(resolved_output / name, 0o400)
        _fsync_directory(resolved_output)
        _write_json_atomic(
            resolved_output / COLLECTION_PROGRESS_NAME,
            completion_progress,
        )
        os.chmod(
            resolved_output / COLLECTION_PROGRESS_NAME,
            0o400,
        )
        _fsync_directory(resolved_output)
        call_store.progress = completion_progress
        return {
            "passed": False,
            "status": "pending_human_review",
            "activation_eligible": False,
            "collection_root": str(resolved_output),
            "collection_manifest": str(
                resolved_output / COLLECTION_MANIFEST_NAME
            ),
            "collection_manifest_file_sha256": manifest_file_sha,
            "candidate": str(resolved_output / CANDIDATE_NAME),
            "execution_ledger": str(
                resolved_output / EXECUTION_LEDGER_NAME
            ),
            "citation_review_template": str(
                resolved_output / CITATION_REVIEW_TEMPLATE_NAME
            ),
            "citation_review_template_file_sha256": template_sha,
            "packet_count": inputs.plan.packet_count,
            "annotation_count": inputs.plan.annotation_count,
            "negative_control_count": inputs.plan.negative_control_count,
            "adversarial_probe_count": inputs.plan.adversarial_probe_count,
            "fixed_plan_calls": inputs.plan.total_call_count,
            "completed_calls": completed,
            "remaining_calls": 0,
            "provider_calls_this_invocation": budget.used_calls,
            "cumulative_physical_provider_calls": (
                budget.cumulative_physical_calls
            ),
            "global_physical_provider_call_ceiling": (
                global_maximum_physical_calls
            ),
            "estimated_cost_ceiling_this_invocation_usd": str(
                budget.estimated_invocation_ceiling_usd
            ),
            "cumulative_operator_estimated_cost_usd": str(
                budget.cumulative_estimated_usd
            ),
            "operator_estimated_cost_not_provider_billing": True,
            "email_invoked": False,
            "c7_invoked": False,
            "smtp_config_read": False,
            "broker_invoked": False,
            "order_invoked": False,
            "canonical_effect": False,
        }


def _copy_private_file(
    source: Path,
    destination: Path,
    *,
    source_root: Path | None,
    destination_root: Path,
) -> str:
    payload, raw = _read_private_json(
        source,
        label=f"source {source.name}",
        trusted_root=source_root,
        recover_owned_publication=source_root is not None,
    )
    del payload
    return _publish_bytes_exclusive(
        destination,
        raw,
        trusted_root=destination_root,
    )


def _validate_collection_manifest(
    collection_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest, manifest_raw = _read_private_json(
        collection_root / COLLECTION_MANIFEST_NAME,
        label="provider replay collection manifest",
        trusted_root=collection_root,
        recover_owned_publication=True,
    )
    expected_manifest_fields = {
        "schema_version",
        "completed_at",
        "state",
        "activation_eligible",
        "collection_config",
        "collection_progress",
        "candidate",
        "execution_ledger",
        "attempt_receipts",
        "response_artifacts",
        "boundaries",
        "collection_manifest_sha256",
    }
    if set(manifest) != expected_manifest_fields:
        raise ReplayRunError("collection manifest schema is invalid")
    claimed_manifest_hash = manifest["collection_manifest_sha256"]
    unsigned_manifest = dict(manifest)
    unsigned_manifest.pop("collection_manifest_sha256")
    if (
        manifest["schema_version"] != COLLECTION_SCHEMA_VERSION
        or manifest["state"]
        != "pending_independent_human_citation_review"
        or manifest["activation_eligible"] is not False
        or canonical_sha256(unsigned_manifest) != claimed_manifest_hash
    ):
        raise ReplayRunError("collection manifest is stale or not quarantined")
    progress, progress_raw = _read_private_json(
        collection_root / COLLECTION_PROGRESS_NAME,
        label="provider replay collection progress",
        trusted_root=collection_root,
    )
    _validate_progress(progress)
    progress_binding = manifest["collection_progress"]
    if (
        not isinstance(progress_binding, dict)
        or set(progress_binding)
        != {"relative_path", "file_sha256", "progress_sha256"}
        or progress_binding["relative_path"] != COLLECTION_PROGRESS_NAME
        or sha256_bytes(progress_raw) != progress_binding["file_sha256"]
        or progress["complete"] is not True
        or progress["progress_sha256"]
        != progress_binding["progress_sha256"]
        or progress["collection_config"] != manifest["collection_config"]
    ):
        raise ReplayRunError("completed collection progress binding is stale")
    candidate_binding = manifest["candidate"]
    ledger_binding = manifest["execution_ledger"]
    if (
        not isinstance(candidate_binding, dict)
        or set(candidate_binding) != {"relative_path", "file_sha256"}
        or candidate_binding["relative_path"] != CANDIDATE_NAME
        or not isinstance(ledger_binding, dict)
        or set(ledger_binding) != {"relative_path", "file_sha256"}
        or ledger_binding["relative_path"] != EXECUTION_LEDGER_NAME
    ):
        raise ReplayRunError("collection candidate/ledger binding is invalid")
    candidate, candidate_raw = _read_private_json(
        collection_root / CANDIDATE_NAME,
        label="provider replay candidate",
        trusted_root=collection_root,
        recover_owned_publication=True,
    )
    ledger, ledger_raw = _read_private_json(
        collection_root / EXECUTION_LEDGER_NAME,
        label="provider replay execution ledger",
        trusted_root=collection_root,
        recover_owned_publication=True,
    )
    if (
        sha256_bytes(candidate_raw) != candidate_binding["file_sha256"]
        or sha256_bytes(ledger_raw) != ledger_binding["file_sha256"]
    ):
        raise ReplayRunError("collection candidate/ledger raw hash mismatch")
    (
        physical_attempts,
        attempt_receipt_bindings,
        attempt_metrics,
    ) = _physical_attempt_artifacts(collection_root, progress)
    if (
        manifest["attempt_receipts"] != attempt_receipt_bindings
        or attempt_metrics["invalid_attempt_count"] != 0
    ):
        raise ReplayRunError(
            "collection physical-attempt receipt closure is invalid"
        )
    expected_ledger_fields = {
        "schema_version",
        "generated_at",
        "corpus_manifest_sha256",
        "model_registry_sha256",
        "annotation_file_sha256",
        "annotation_set_sha256",
        "collection_progress",
        "budget",
        "attempt_metrics",
        "attempt_receipt_set_sha256",
        "logical_calls",
        "physical_attempts",
        "boundaries",
    }
    if (
        not isinstance(ledger, dict)
        or set(ledger) != expected_ledger_fields
        or ledger["schema_version"] != EXECUTION_LEDGER_SCHEMA_VERSION
        or ledger["generated_at"] != manifest["completed_at"]
        or ledger["collection_progress"] != progress_binding
        or ledger["physical_attempts"] != physical_attempts
        or ledger["attempt_receipt_set_sha256"]
        != canonical_sha256(attempt_receipt_bindings)
        or not isinstance(ledger["logical_calls"], list)
        or len(ledger["logical_calls"])
        != len(progress["successful_calls"])
    ):
        raise ReplayRunError(
            "collection physical-attempt ledger is forged or stale"
        )
    global_ceiling, max_cost, per_call = _validated_budget_policy(
        manifest["collection_config"].get("budget_policy"),
        logical_plan_calls=manifest["collection_config"]["plan"][
            "total_call_count"
        ],
    )
    expected_attempt_metrics = {
        **attempt_metrics,
        "outcome_category_counts": {
            category: sum(
                row["outcome_category"] == category
                for row in physical_attempts
            )
            for category in sorted(
                ATTEMPT_OUTCOME_CATEGORIES - {"invocation_started"}
            )
        },
    }
    expected_budget = {
        "logical_plan_call_count": manifest["collection_config"]["plan"][
            "total_call_count"
        ],
        "logical_successful_call_count": len(
            progress["successful_calls"]
        ),
        "physical_attempt_count": len(physical_attempts),
        "frozen_global_physical_call_ceiling": global_ceiling,
        "operator_estimated_usd_per_physical_call": str(per_call),
        "operator_estimated_cumulative_cost_usd": str(
            per_call * len(physical_attempts)
        ),
        "operator_estimated_global_cost_ceiling_usd": str(max_cost),
        "cost_basis": "operator_estimate_not_provider_billing",
        "maximum_attempts_per_logical_call": MAXIMUM_ATTEMPTS_PER_CALL,
    }
    if (
        ledger["attempt_metrics"] != expected_attempt_metrics
        or ledger["budget"] != expected_budget
        or len(physical_attempts) > global_ceiling
    ):
        raise ReplayRunError(
            "collection cumulative physical-call/cost accounting is stale"
        )
    expected_execution_integrity = {
        "collection_progress": progress_binding,
        "execution_ledger": ledger_binding,
        "attempt_receipt_count": len(attempt_receipt_bindings),
        "attempt_receipt_set_sha256": canonical_sha256(
            attempt_receipt_bindings
        ),
        "logical_provider_call_count": len(
            progress["successful_calls"]
        ),
        "physical_provider_attempt_count": len(physical_attempts),
        "first_attempt_valid_logical_call_count": attempt_metrics[
            "first_attempt_valid_logical_call_count"
        ],
        "retryable_transport_or_process_failure_count": attempt_metrics[
            "retryable_transport_or_process_failure_count"
        ],
        "invalid_attempt_count": 0,
        "frozen_global_physical_call_ceiling": global_ceiling,
        "operator_estimated_usd_per_physical_call": str(per_call),
        "operator_estimated_cumulative_cost_usd": str(
            per_call * len(physical_attempts)
        ),
        "operator_estimated_global_cost_ceiling_usd": str(max_cost),
        "cost_basis": "operator_estimate_not_provider_billing",
    }
    if (
        candidate.get("base_report", {}).get("execution_integrity")
        != expected_execution_integrity
    ):
        raise ReplayRunError(
            "collection candidate execution-integrity binding is stale"
        )
    artifacts = manifest["response_artifacts"]
    if not isinstance(artifacts, list):
        raise ReplayRunError("collection response artifact list is invalid")
    seen_calls: set[str] = set()
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if (
            not isinstance(artifact, dict)
            or set(artifact)
            != {
                "provider_call_id",
                "relative_path",
                "file_sha256",
                "input_sha256",
                "output_sha256",
            }
        ):
            raise ReplayRunError("collection response binding is invalid")
        call_id = str(artifact["provider_call_id"])
        relative = str(artifact["relative_path"])
        if call_id in seen_calls or relative in seen_paths:
            raise ReplayRunError("collection response identity is duplicated")
        seen_calls.add(call_id)
        seen_paths.add(relative)
        response_path = (collection_root / relative).resolve()
        try:
            response_path.relative_to(collection_root.resolve())
        except ValueError as exc:
            raise ReplayRunError(
                "collection response path escapes quarantine"
            ) from exc
        response, raw = _read_private_json(
            response_path,
            label="collection response artifact",
            maximum_bytes=2 * 1024 * 1024,
            trusted_root=collection_root,
            recover_owned_publication=True,
        )
        if (
            sha256_bytes(raw) != artifact["file_sha256"]
            or canonical_sha256(response) != artifact["output_sha256"]
        ):
            raise ReplayRunError("collection response artifact hash mismatch")
    if (
        set(progress["successful_calls"]) != seen_calls
        or len(artifacts)
        != manifest["collection_config"]["plan"]["total_call_count"]
    ):
        raise ReplayRunError("collection response cardinality is incomplete")
    manifest["_raw_file_sha256"] = sha256_bytes(manifest_raw)
    return manifest, candidate, ledger


def finalize_provider_replay(
    *,
    collection_root: Path,
    citation_review_path: Path,
    citation_review_file_sha256: str,
    manifest_path: Path,
    annotation_path: Path,
    model_registry_path: Path,
    output_root: Path,
    allow_test_path: bool = False,
    minimum_packets: int | None = None,
    minimum_transitions: int | None = None,
    stability_transition_count: int = MINIMUM_STABILITY_PACKETS,
    stability_trials_per_transition: int = (
        MINIMUM_STABILITY_TRIALS_PER_PACKET
    ),
    verifier: Callable[..., dict[str, Any]] = verify_provider_replay_gate,
) -> dict[str, Any]:
    """Finalize provider-free; publish only after the offline gate passes."""

    resolved_collection = _resolve_collection_root(
        collection_root,
        allow_test_path=allow_test_path,
    )
    if not resolved_collection.exists():
        raise ReplayRunError("completed quarantine collection is unavailable")
    resolved_output = _validate_output_root(
        output_root,
        allow_test_path=allow_test_path,
        quarantine_required=False,
    )
    resolved_manifest = manifest_path.expanduser().resolve()
    resolved_annotations = annotation_path.expanduser().resolve()
    resolved_registry = model_registry_path.expanduser().resolve()
    resolved_reviews = citation_review_path.expanduser().resolve()
    collection_manifest, candidate, ledger = (
        _validate_collection_manifest(resolved_collection)
    )
    config = collection_manifest["collection_config"]
    inputs = load_replay_inputs(
        manifest_path=resolved_manifest,
        annotation_path=resolved_annotations,
        model_registry_path=resolved_registry,
        expected_annotation_file_sha256=config["annotation_file_sha256"],
        minimum_packets=minimum_packets,
        minimum_transitions=minimum_transitions,
        stability_transition_count=stability_transition_count,
        stability_trials_per_transition=stability_trials_per_transition,
    )
    _validate_collection_input_binding(config, inputs)
    if (
        candidate.get("schema_version") != CANDIDATE_SCHEMA_VERSION
        or candidate.get("activation_eligible") is not False
        or candidate.get("state")
        != "pending_independent_human_citation_review"
    ):
        raise ReplayRunError("quarantined provider candidate is invalid")
    expected_claims = candidate.get("expected_citation_claims")
    if not isinstance(expected_claims, list):
        raise ReplayRunError("candidate citation claim bundle is missing")
    reviews, review_binding = validate_citation_review_set(
        review_path=resolved_reviews,
        expected_claims=expected_claims,
        corpus_manifest_sha256=inputs.corpus.manifest_sha256,
        annotation_set_sha256=inputs.annotation_metadata[
            "annotation_set_sha256"
        ],
        expected_file_sha256=citation_review_file_sha256,
    )
    citation_quality = _citation_quality(reviews=reviews)
    automated_quality = candidate["automated_quality"]
    extended_summary = {
        "citation_review_set_binding": review_binding,
        "citation_quality": citation_quality,
        "critic_control_quality": automated_quality[
            "critic_control_quality"
        ],
        "counterfactual_quality": automated_quality[
            "counterfactual_quality"
        ],
        "holdout_quality": automated_quality["holdout_quality"],
        "extended_quality_passed": True,
    }
    extended_quality = {
        "schema_version": EXTENDED_QUALITY_SCHEMA_VERSION,
        "frozen_split": candidate["frozen_split"],
        "citation_review_set_binding": review_binding,
        "citation_entailment_reviews": reviews,
        "critic_control_results": candidate["critic_control_results"],
        "counterfactual_results": candidate["counterfactual_results"],
        "summary": extended_summary,
    }
    base_report = copy.deepcopy(candidate["base_report"])
    total_calls = inputs.plan.total_call_count
    base_report["extended_quality"] = extended_quality
    base_report["summary"] = {
        "packet_count": inputs.plan.packet_count,
        "source_identity_count": inputs.corpus.source_identity_count,
        "accession_count": inputs.corpus.accession_count,
        "role_result_count": len(base_report["results"]),
        "transition_pair_result_count": len(
            base_report["transition_pair_results"]
        ),
        "negative_control_result_count": len(
            base_report["negative_control_results"]
        ),
        "adversarial_probe_result_count": len(
            base_report["adversarial_probe_results"]
        ),
        "stability_trial_count": len(base_report["stability_trials"]),
        "extended_quality_call_count": inputs.plan.extended_quality_call_count,
        "total_provider_call_count": total_calls,
        "logical_provider_call_count": total_calls,
        "physical_provider_attempt_count": base_report[
            "execution_integrity"
        ]["physical_provider_attempt_count"],
        "first_attempt_valid_logical_call_count": base_report[
            "execution_integrity"
        ]["first_attempt_valid_logical_call_count"],
        "retryable_transport_or_process_failure_count": base_report[
            "execution_integrity"
        ]["retryable_transport_or_process_failure_count"],
        "invalid_provider_attempt_count": base_report[
            "execution_integrity"
        ]["invalid_attempt_count"],
        "operator_estimated_cumulative_cost_usd": base_report[
            "execution_integrity"
        ]["operator_estimated_cumulative_cost_usd"],
        "operator_estimated_cost_not_provider_billing": True,
        "validated_response_count": total_calls,
        "material_transition_count": len(inputs.annotations),
        "violation_totals": _zero_violations(),
        "runtime_committee_quality": automated_quality[
            "runtime_committee_quality"
        ],
        "transition_pair_quality": automated_quality[
            "transition_pair_quality"
        ],
        "negative_control_quality": automated_quality[
            "negative_control_quality"
        ],
        "adversarial_safety_quality": automated_quality[
            "adversarial_safety_quality"
        ],
        "stability": automated_quality["stability"],
        "extended_quality": extended_summary,
        "quality_gate_passed": True,
    }

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(
        tempfile.mkdtemp(
            prefix=".phase5r-provider-replay-finalize-",
            dir=resolved_output.parent,
        )
    ).resolve()
    published = False
    try:
        for artifact in collection_manifest["response_artifacts"]:
            source = resolved_collection / artifact["relative_path"]
            destination = stage_root / artifact["relative_path"]
            copied_hash = _copy_private_file(
                source,
                destination,
                source_root=resolved_collection,
                destination_root=stage_root,
            )
            if copied_hash != artifact["file_sha256"]:
                raise ReplayRunError(
                    "final response copy differs from quarantine"
                )
        for receipt_binding in collection_manifest["attempt_receipts"]:
            copied_hash = _copy_private_file(
                resolved_collection / receipt_binding["relative_path"],
                stage_root / receipt_binding["relative_path"],
                source_root=resolved_collection,
                destination_root=stage_root,
            )
            if copied_hash != receipt_binding["file_sha256"]:
                raise ReplayRunError(
                    "final attempt-receipt copy differs from quarantine"
                )
        for artifact_name in (
            CANDIDATE_NAME,
            COLLECTION_PROGRESS_NAME,
        ):
            _copy_private_file(
                resolved_collection / artifact_name,
                stage_root / artifact_name,
                source_root=resolved_collection,
                destination_root=stage_root,
            )
        _copy_private_file(
            resolved_collection / EXECUTION_LEDGER_NAME,
            stage_root / EXECUTION_LEDGER_NAME,
            source_root=resolved_collection,
            destination_root=stage_root,
        )
        _copy_private_file(
            resolved_collection / COLLECTION_MANIFEST_NAME,
            stage_root / COLLECTION_MANIFEST_NAME,
            source_root=resolved_collection,
            destination_root=stage_root,
        )
        copied_review_hash = _copy_private_file(
            resolved_reviews,
            stage_root / FINAL_CITATION_REVIEW_NAME,
            source_root=None,
            destination_root=stage_root,
        )
        if copied_review_hash != citation_review_file_sha256:
            raise ReplayRunError("final citation review copy hash mismatch")
        report_path = stage_root / REPORT_NAME
        _write_json_exclusive(
            report_path,
            base_report,
            trusted_root=stage_root,
        )
        verified = verifier(
            manifest_path=resolved_manifest,
            provider_report_path=report_path,
            model_registry_path=resolved_registry,
            annotation_set_path=resolved_annotations,
            citation_review_set_path=stage_root / FINAL_CITATION_REVIEW_NAME,
        )
        if verified.get("passed") is not True:
            issues = verified.get("issues", ["offline verifier rejected report"])
            reason = (
                str(issues[0])
                if isinstance(issues, list) and issues
                else "offline verifier rejected report"
            )
            raise ReplayRunError(reason)
        immutable_execution_paths = [
            stage_root / COLLECTION_PROGRESS_NAME,
            stage_root / EXECUTION_LEDGER_NAME,
            stage_root / COLLECTION_MANIFEST_NAME,
            stage_root / CANDIDATE_NAME,
            *(
                stage_root / binding["relative_path"]
                for binding in collection_manifest[
                    "attempt_receipts"
                ]
            ),
        ]
        for immutable_path in immutable_execution_paths:
            os.chmod(immutable_path, 0o400)
        _fsync_directory(stage_root)
        if resolved_output.exists():
            raise ReplayRunError(
                "final output appeared during atomic publication"
            )
        os.rename(stage_root, resolved_output)
        published = True
        return {
            "passed": True,
            "status": "provider_replay_gate_passed",
            "activation_eligible": True,
            "activation_performed": False,
            "output_root": str(resolved_output),
            "provider_report": str(resolved_output / REPORT_NAME),
            "citation_review_set": str(
                resolved_output / FINAL_CITATION_REVIEW_NAME
            ),
            "provider_calls_this_invocation": 0,
            "network_invoked": False,
            "fixed_plan_calls": total_calls,
            "email_invoked": False,
            "c7_invoked": False,
            "smtp_config_read": False,
            "broker_invoked": False,
            "order_invoked": False,
            "canonical_effect": False,
        }
    finally:
        if not published and stage_root.exists():
            shutil.rmtree(stage_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--collect", action="store_true")
    mode.add_argument(
        "--run",
        action="store_true",
        help="compatibility alias for --collect",
    )
    mode.add_argument("--finalize", action="store_true")
    parser.add_argument("--manifest", type=Path, default=CORPUS_MANIFEST_PATH)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATION_PATH)
    parser.add_argument("--model-registry", type=Path, default=MODEL_REGISTRY_PATH)
    parser.add_argument(
        "--collection-root",
        type=Path,
        default=DEFAULT_COLLECTION_ROOT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--acknowledge-external-inference", action="store_true")
    parser.add_argument("--annotation-file-sha256", default="")
    parser.add_argument(
        "--exact-plan-calls",
        "--exact-maximum-calls",
        dest="exact_plan_calls",
        type=int,
    )
    parser.add_argument("--max-new-calls", type=int)
    parser.add_argument("--global-max-physical-calls", type=int)
    parser.add_argument(
        "--max-cost-usd",
        "--max-estimated-usd",
        dest="max_cost_usd",
        type=_decimal,
    )
    parser.add_argument("--estimated-usd-per-call", type=_decimal)
    parser.add_argument("--citation-review-set", type=Path)
    parser.add_argument("--citation-review-file-sha256", default="")
    args = parser.parse_args()

    if not (args.collect or args.run or args.finalize):
        result = check_replay_readiness(
            manifest_path=args.manifest,
            annotation_path=args.annotations,
            model_registry_path=args.model_registry,
            collection_root=args.collection_root,
        )
        suggestions = result["suggested_new_call_caps"]
        print(
            f"provider_replay_run_check={'ready' if result['ready'] else 'blocked'} "
            f"packets={result['packet_count']} "
            f"annotations={result['annotation_count']} "
            f"negative_controls={result['negative_control_count']} "
            f"adversarial_probes={result['adversarial_probe_count']} "
            f"total_calls={result['planned_provider_calls']} "
            f"completed_calls={result['completed_provider_calls']} "
            f"completed_physical_attempts="
            f"{result.get('completed_physical_provider_attempts', 0)} "
            f"remaining_calls={result['remaining_provider_calls']} "
            f"smoke_max_new_calls={suggestions['smoke']} "
            f"pilot_max_new_calls={suggestions['pilot']} "
            f"full_remaining_max_new_calls={suggestions['full_remaining']} "
            f"collection_complete={str(result['collection_complete']).lower()} "
            f"issues={len(result['issues'])} "
            "provider_invoked=false network_invoked=false files_written=false "
            "email_invoked=false c7_invoked=false broker_invoked=false "
            "order_invoked=false canonical_effect=false"
        )
        return 0 if result["ready"] else 1

    if args.finalize:
        if (
            args.citation_review_set is None
            or not args.citation_review_file_sha256
        ):
            parser.error(
                "--finalize requires --citation-review-set and "
                "--citation-review-file-sha256"
            )
        try:
            result = finalize_provider_replay(
                collection_root=args.collection_root,
                citation_review_path=args.citation_review_set,
                citation_review_file_sha256=(
                    args.citation_review_file_sha256
                ),
                manifest_path=args.manifest,
                annotation_path=args.annotations,
                model_registry_path=args.model_registry,
                output_root=args.output_root,
            )
        except Exception as exc:
            print(
                f"provider_replay_finalize=failed reason={_safe_error(exc)} "
                "provider_invoked=false network_invoked=false "
                "passing_report_written=false email_invoked=false "
                "c7_invoked=false smtp_config_read=false broker_invoked=false "
                "order_invoked=false canonical_effect=false"
            )
            return 1
        print(
            f"provider_replay_finalize=passed "
            f"fixed_plan_calls={result['fixed_plan_calls']} "
            "provider_calls_this_invocation=0 network_invoked=false "
            "activation_performed=false email_invoked=false c7_invoked=false "
            "smtp_config_read=false broker_invoked=false order_invoked=false "
            "canonical_effect=false"
        )
        return 0

    if (
        args.exact_plan_calls is None
        or args.max_new_calls is None
        or args.global_max_physical_calls is None
        or args.max_cost_usd is None
        or args.estimated_usd_per_call is None
        or not args.annotation_file_sha256
        or not args.acknowledge_external_inference
    ):
        parser.error(
            "--collect requires --acknowledge-external-inference, "
            "--exact-plan-calls, --max-new-calls, --max-cost-usd, "
            "--global-max-physical-calls, --estimated-usd-per-call, "
            "and --annotation-file-sha256"
        )
    if args.model_registry.expanduser().resolve() != MODEL_REGISTRY_PATH.resolve():
        parser.error("--collect must use the current project model registry")
    try:
        result = execute_provider_replay(
            manifest_path=args.manifest,
            annotation_path=args.annotations,
            model_registry_path=args.model_registry,
            output_root=args.collection_root,
            acknowledge_external_inference=args.acknowledge_external_inference,
            annotation_file_sha256=args.annotation_file_sha256,
            exact_maximum_calls=args.exact_plan_calls,
            global_maximum_physical_calls=(
                args.global_max_physical_calls
            ),
            maximum_new_calls=args.max_new_calls,
            max_estimated_usd=args.max_cost_usd,
            estimated_usd_per_call=args.estimated_usd_per_call,
        )
    except Exception as exc:
        print(
            f"provider_replay_collect=failed reason={_safe_error(exc)} "
            "passing_report_written=false email_invoked=false c7_invoked=false "
            "smtp_config_read=false broker_invoked=false order_invoked=false "
            "canonical_effect=false"
        )
        return 1
    print(
        f"provider_replay_collect={result['status']} "
        f"fixed_plan_calls={result['fixed_plan_calls']} "
        f"completed_calls={result['completed_calls']} "
        f"remaining_calls={result['remaining_calls']} "
        f"provider_calls_this_invocation="
        f"{result['provider_calls_this_invocation']} "
        f"cumulative_physical_provider_calls="
        f"{result['cumulative_physical_provider_calls']} "
        f"global_physical_provider_call_ceiling="
        f"{result['global_physical_provider_call_ceiling']} "
        f"cost_ceiling_this_invocation_usd="
        f"{result['estimated_cost_ceiling_this_invocation_usd']} "
        f"cumulative_operator_estimated_cost_usd="
        f"{result['cumulative_operator_estimated_cost_usd']} "
        "cost_basis=operator_estimate_not_provider_billing "
        "passing_report_written=false activation_eligible=false "
        "email_invoked=false c7_invoked=false smtp_config_read=false "
        "broker_invoked=false order_invoked=false canonical_effect=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
