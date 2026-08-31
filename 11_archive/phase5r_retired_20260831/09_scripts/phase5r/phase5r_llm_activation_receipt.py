#!/usr/bin/env python3
"""Build and verify the local Phase 5R live-shadow activation receipt.

The provider replay report is bound to the *pre-activation* registry bytes.
After activation, that hash must not be compared with the current registry.
Instead, this receipt preserves the evaluated registry snapshot and hash,
derives the only permitted target shadow registry, and binds that target to the
current registry plus the exact corpus and provider-report bytes.

Receipt verification is offline and read-only.  It never invokes a model,
network client, email path, C7, a broker, or order code.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from phase5r_daily_common import ROOT, canonical_sha256
from verify_phase5r_llm_provider_replay_gate import (
    CORPUS_MANIFEST_PATH,
    ANNOTATION_SET_PATH,
    CITATION_REVIEW_SET_PATH,
    MANIFEST_SCHEMA_VERSION,
    MODEL_REGISTRY_PATH,
    PROVIDER_REPORT_PATH,
    REPORT_SCHEMA_VERSION,
    REQUIRED_ROLES,
    VIOLATION_CATEGORIES,
    _expected_role_bindings,
    replay_runtime_code_hashes,
)


ACTIVATION_RECEIPT_PATH = (
    ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_llm_activation_receipt.local.json"
)
RECEIPT_SCHEMA_VERSION = "phase5r_llm_activation_receipt_v2"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_BOUND_ARTIFACT_BYTES = 128 * 1024 * 1024
RUNTIME_CODE_PATHS = (
    ROOT / "09_scripts" / "phase5r" / "phase5r_daily_common.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_evidence_freshness.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "build_phase5r_decision_evidence_packet.py",
    ROOT / "09_scripts" / "phase5r" / "enable_phase5r_llm_live_shadow.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_llm_activation_receipt.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_llm_citation_reviews.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_llm_contract.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "phase5r_llm_cost_aware_router.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "phase5r_llm_role_execution_ledger.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_llm_provider.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "phase5r_llm_shadow_router_gate.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_return_objective.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_sec_acceptance.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "refresh_phase5r_sec_filing_artifacts.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "phase5r_valuation_input_bundle.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "prepare_phase5r_llm_replay_corpus.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "phase5r_strict_replay_artifacts.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "inventory_phase5r_llm_replay_corpus.py",
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_llm_shadow.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "run_phase5r_llm_provider_replay_evaluation.py",
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_llm_shadow_scheduler.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "verify_phase5r_llm_provider_replay_gate.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "phase5r_llm_transition_annotations.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "verify_phase5r_llm_shadow_boundary.py",
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_daily_refresh.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "run_phase5r_daily_decision_pipeline.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "run_phase5r_daily_refresh_scheduler.py",
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_daily_scheduler.py",
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_runtime_scheduler.py",
    ROOT / "09_scripts" / "phase5r" / "send_phase5r_daily_email.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "run_phase5r_b2_full_universe_market_data.py",
    ROOT / "09_scripts" / "phase5r" / "score_phase5r_b2_candidates.py",
    ROOT / "09_scripts" / "phase5r" / "refresh_phase5r_daily_evidence.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "regenerate_phase5r_c9_portfolio_outputs.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "create_phase5r_c9b_price_aware_action_plan.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "create_phase5r_daily_decision_and_brief.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_c9_common.py",
    ROOT / "09_scripts" / "phase5r" / "phase5r_c9b_common.py",
    ROOT / "09_scripts" / "phase5r" / "create_phase5r_c9_account_state.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "calculate_phase5r_c9_dynamic_weights.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "create_phase5r_c9_exact_action_plan.py",
    ROOT
    / "09_scripts"
    / "phase5r"
    / "create_phase5r_c9_cash_deployment_plan.py",
)


class ActivationReceiptError(ValueError):
    """Activation evidence is missing, stale, or internally inconsistent."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json_bytes(payload: Any) -> bytes:
    """Return the exact bytes produced by phase5r_daily_common.atomic_write_json."""

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


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ActivationReceiptError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> Any:
    raise ActivationReceiptError(f"JSON contains non-finite number: {value}")


def _read_regular_bytes(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise ActivationReceiptError(f"{label} must not be a symlink")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise ActivationReceiptError(f"{label} is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > MAX_JSON_BYTES
    ):
        raise ActivationReceiptError(f"{label} is not an allowed regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ActivationReceiptError(f"{label} is unreadable") from exc


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular_bytes(path, label=label)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except ActivationReceiptError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActivationReceiptError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ActivationReceiptError(f"{label} must be a JSON object")
    return payload, raw


def _valid_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ActivationReceiptError(f"{label} must be a lowercase SHA-256")
    return value


def _read_bound_artifact(
    root: Path,
    relative_path: str,
    *,
    label: str,
) -> bytes:
    relative = Path(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ActivationReceiptError(f"{label} path is not a safe relative path")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ActivationReceiptError(f"{label} root is unavailable") from exc
    candidate = resolved_root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ActivationReceiptError(f"{label} must not use symlinks")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
        metadata = resolved.stat()
    except (OSError, ValueError) as exc:
        raise ActivationReceiptError(
            f"{label} escapes its artifact root or is unavailable"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > MAX_BOUND_ARTIFACT_BYTES
    ):
        raise ActivationReceiptError(f"{label} is not an allowed regular file")
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise ActivationReceiptError(f"{label} is unreadable") from exc


def _validate_transitive_artifact_hashes(
    value: Any,
    *,
    corpus_root: Path,
    report_root: Path,
) -> dict[str, dict[str, str]]:
    groups = _exact_keys(
        value,
        {"corpus", "provider_responses"},
        label="transitive artifact binding",
    )
    normalized: dict[str, dict[str, str]] = {}
    for group, root in (
        ("corpus", corpus_root),
        ("provider_responses", report_root),
    ):
        entries = groups[group]
        if not isinstance(entries, dict) or not entries:
            raise ActivationReceiptError(
                f"transitive artifact binding {group} must be non-empty"
            )
        normalized_entries: dict[str, str] = {}
        for relative_path, expected_hash_value in sorted(entries.items()):
            if not isinstance(relative_path, str):
                raise ActivationReceiptError(
                    f"transitive artifact binding {group} path must be a string"
                )
            expected_hash = _valid_sha256(
                expected_hash_value,
                label=f"transitive artifact binding {group} hash",
            )
            raw = _read_bound_artifact(
                root,
                relative_path,
                label=f"transitive artifact binding {group}",
            )
            if sha256_bytes(raw) != expected_hash:
                raise ActivationReceiptError(
                    f"transitive artifact binding {group} changed"
                )
            normalized_entries[relative_path] = expected_hash
        normalized[group] = normalized_entries
    return normalized


def _exact_keys(
    value: Any,
    expected: set[str],
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ActivationReceiptError(f"{label} fields do not match")
    return value


def _positive_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ActivationReceiptError(f"{label} must be a positive integer")
    return value


def _validate_timestamp(value: Any, *, label: str) -> None:
    if not isinstance(value, str):
        raise ActivationReceiptError(f"{label} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ActivationReceiptError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ActivationReceiptError(f"{label} must be timezone-aware")


def target_shadow_registry(evaluated_registry: dict[str, Any]) -> dict[str, Any]:
    """Derive the only registry state permitted by live-shadow activation."""

    if (
        evaluated_registry.get("schema_version")
        != "phase5r_llm_model_registry_v1"
        or evaluated_registry.get("mode") != "offline_fixture"
        or evaluated_registry.get("live_shadow_enabled") is not False
    ):
        raise ActivationReceiptError(
            "evaluated registry is not the disabled offline-fixture state"
        )
    if set(evaluated_registry.get("roles", {})) != set(REQUIRED_ROLES):
        raise ActivationReceiptError("evaluated registry roles do not match")
    false_fields = (
        "canonical_influence_enabled",
        "tools_enabled",
        "provider_credentials_read_by_repository",
        "exact_account_dollars_allowed",
        "automatic_action_allowed",
        "email_eligible",
        "broker_connection_allowed",
        "order_code_allowed",
    )
    if any(evaluated_registry.get(field) is not False for field in false_fields):
        raise ActivationReceiptError("evaluated registry is not fail-closed")
    if (
        evaluated_registry.get("successful_role_results_reused") is not True
        or evaluated_registry.get("maximum_live_attempts_per_role") != 2
        or evaluated_registry.get("stateless") is not True
    ):
        raise ActivationReceiptError("evaluated registry provider policy is unsafe")
    target = copy.deepcopy(evaluated_registry)
    target["mode"] = "shadow"
    target["live_shadow_enabled"] = True
    target["canonical_influence_enabled"] = False
    target["automatic_action_allowed"] = False
    target["email_eligible"] = False
    return target


def _quality_counts(summary: dict[str, Any]) -> dict[str, int]:
    positive_fields = {
        "packet_count",
        "source_identity_count",
        "accession_count",
        "role_result_count",
        "validated_response_count",
        "material_transition_count",
        "transition_pair_result_count",
        "negative_control_result_count",
        "adversarial_probe_result_count",
        "stability_trial_count",
        "extended_quality_call_count",
        "total_provider_call_count",
        "logical_provider_call_count",
        "physical_provider_attempt_count",
    }
    nonnegative_fields = {
        "first_attempt_valid_logical_call_count",
        "retryable_transport_or_process_failure_count",
        "invalid_provider_attempt_count",
    }
    counts: dict[str, int] = {}
    for key in positive_fields:
        counts[key] = _positive_int(summary.get(key), label=f"summary {key}")
    for key in nonnegative_fields:
        value = summary.get(key)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ActivationReceiptError(
                f"summary {key} must be a nonnegative integer"
            )
        counts[key] = value
    if counts["role_result_count"] != counts["packet_count"] * len(REQUIRED_ROLES):
        raise ActivationReceiptError("provider report role-result count is invalid")
    expected_total = (
        counts["role_result_count"]
        + counts["transition_pair_result_count"]
        + counts["negative_control_result_count"]
        + counts["adversarial_probe_result_count"]
        + counts["stability_trial_count"]
        + counts["extended_quality_call_count"]
    )
    if (
        counts["validated_response_count"]
        != counts["total_provider_call_count"]
        or counts["total_provider_call_count"] != expected_total
        or counts["logical_provider_call_count"] != expected_total
        or counts["physical_provider_attempt_count"] < expected_total
        or counts["retryable_transport_or_process_failure_count"]
        != counts["physical_provider_attempt_count"] - expected_total
        or counts["first_attempt_valid_logical_call_count"]
        > expected_total
        or counts["invalid_provider_attempt_count"] != 0
    ):
        raise ActivationReceiptError("provider responses were not all validated")
    return counts


def _runtime_code_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in RUNTIME_CODE_PATHS:
        raw = _read_regular_bytes(path, label=f"runtime code {path.name}")
        hashes[path.name] = sha256_bytes(raw)
    return hashes


def _zero_violations(value: Any) -> dict[str, int]:
    violations = _exact_keys(
        value,
        set(VIOLATION_CATEGORIES),
        label="violation totals",
    )
    normalized: dict[str, int] = {}
    for category in VIOLATION_CATEGORIES:
        count = violations[category]
        if not isinstance(count, int) or isinstance(count, bool) or count != 0:
            raise ActivationReceiptError(
                f"violation total must be zero: {category}"
            )
        normalized[category] = count
    return normalized


def _role_config_from_report(
    report: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, dict[str, str]]:
    bindings = report.get("role_bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(REQUIRED_ROLES):
        raise ActivationReceiptError("provider report role bindings are missing")
    expected_bindings = _expected_role_bindings(registry)
    if bindings != expected_bindings:
        raise ActivationReceiptError(
            "provider report prompt/schema/model hashes are stale"
        )
    role_config: dict[str, dict[str, str]] = {}
    for role in REQUIRED_ROLES:
        binding = bindings.get(role)
        expected = registry["roles"][role]
        if not isinstance(binding, dict) or any(
            binding.get(field) != expected.get(field)
            for field in ("model", "reasoning_effort", "prompt_version")
        ):
            raise ActivationReceiptError(
                f"provider report role binding is stale: {role}"
            )
        role_config[role] = {
            "model": str(binding["model"]),
            "reasoning_effort": str(binding["reasoning_effort"]),
            "prompt_version": str(binding["prompt_version"]),
        }
    return role_config


def _validate_report_boundaries(report: dict[str, Any]) -> None:
    boundaries = report.get("boundaries")
    if not isinstance(boundaries, dict):
        raise ActivationReceiptError("provider report boundaries are missing")
    if (
        boundaries.get("provider_inference_invoked") is not True
        or boundaries.get("network_used_only_for_external_provider_transport")
        is not True
    ):
        raise ActivationReceiptError(
            "provider report lacks external inference provenance"
        )
    prohibited = (
        "email_invoked",
        "c7_invoked",
        "smtp_config_read",
        "smtp_config_modified",
        "broker_connected",
        "broker_account_read",
        "order_code_created",
        "order_attempted",
        "canonical_effect",
    )
    if any(boundaries.get(key) is not False for key in prohibited):
        raise ActivationReceiptError("provider report contains a prohibited effect")


def build_activation_receipt(
    *,
    evaluated_registry: dict[str, Any],
    evaluated_registry_raw: bytes,
    corpus_manifest_path: Path,
    provider_report_path: Path,
    activated_at: str,
    provider_gate_result: dict[str, Any],
    annotation_set_path: Path = ANNOTATION_SET_PATH,
    citation_review_set_path: Path = CITATION_REVIEW_SET_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a receipt and its uniquely derived target registry in memory."""

    if provider_gate_result.get("passed") is not True:
        raise ActivationReceiptError("provider replay quality gate did not pass")
    _validate_timestamp(activated_at, label="activation timestamp")
    if sha256_bytes(atomic_json_bytes(evaluated_registry)) != sha256_bytes(
        evaluated_registry_raw
    ):
        raise ActivationReceiptError(
            "evaluated registry bytes are not the canonical atomic JSON form"
        )
    target_registry = target_shadow_registry(evaluated_registry)
    manifest, manifest_raw = _read_json(
        corpus_manifest_path, label="replay corpus manifest"
    )
    report, report_raw = _read_json(
        provider_report_path, label="provider replay report"
    )
    _, annotation_raw = _read_json(
        annotation_set_path, label="transition annotation set"
    )
    _, citation_review_raw = _read_json(
        citation_review_set_path, label="claim citation review set"
    )
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ActivationReceiptError("replay corpus manifest version mismatch")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ActivationReceiptError("provider replay report version mismatch")
    evaluated_registry_sha = sha256_bytes(evaluated_registry_raw)
    manifest_sha = sha256_bytes(manifest_raw)
    report_sha = sha256_bytes(report_raw)
    annotation_sha = sha256_bytes(annotation_raw)
    citation_review_sha = sha256_bytes(citation_review_raw)
    runtime_code_hashes = _runtime_code_hashes()
    gate_artifact_binding = provider_gate_result.get("artifact_binding")
    if not isinstance(gate_artifact_binding, dict):
        raise ActivationReceiptError(
            "provider gate artifact binding is missing"
        )
    transitive_artifact_hashes = _validate_transitive_artifact_hashes(
        gate_artifact_binding.get("transitive_artifact_sha256"),
        corpus_root=corpus_manifest_path.parent,
        report_root=provider_report_path.parent,
    )
    expected_gate_artifact_binding = {
        "model_registry_sha256": evaluated_registry_sha,
        "corpus_manifest_sha256": manifest_sha,
        "provider_report_sha256": report_sha,
        "annotation_set_sha256": annotation_sha,
        "citation_review_set_sha256": citation_review_sha,
        "runtime_code_sha256": runtime_code_hashes,
        "transitive_artifact_sha256": transitive_artifact_hashes,
    }
    if (
        provider_gate_result.get("artifact_binding")
        != expected_gate_artifact_binding
    ):
        raise ActivationReceiptError(
            "activation artifacts changed after the provider gate"
        )
    if report.get("model_registry_sha256") != evaluated_registry_sha:
        raise ActivationReceiptError(
            "provider report is not bound to the evaluated registry"
        )
    if report.get("corpus_manifest_sha256") != manifest_sha:
        raise ActivationReceiptError(
            "provider report is not bound to the replay corpus"
        )
    if (
        report.get("annotation_set_binding", {}).get(
            "annotation_file_sha256"
        )
        != annotation_sha
        or report.get("extended_quality", {})
        .get("citation_review_set_binding", {})
        .get("review_file_sha256")
        != citation_review_sha
    ):
        raise ActivationReceiptError(
            "provider report human-review artifact bindings are stale"
        )
    role_config = _role_config_from_report(report, evaluated_registry)
    if (
        report.get("runtime_code_sha256") != runtime_code_hashes
        or replay_runtime_code_hashes() != runtime_code_hashes
    ):
        raise ActivationReceiptError(
            "provider report replay/runtime code hashes are stale"
        )
    summary = report.get("summary")
    if not isinstance(summary, dict) or summary.get("quality_gate_passed") is not True:
        raise ActivationReceiptError("provider report quality summary did not pass")
    counts = _quality_counts(summary)
    for key, count in counts.items():
        gate_key = key
        if gate_key in provider_gate_result and provider_gate_result[gate_key] != count:
            raise ActivationReceiptError(
                f"provider gate/report count mismatch: {key}"
            )
    violations = _zero_violations(summary.get("violation_totals"))
    _validate_report_boundaries(report)
    transport = report.get("provider_transport")
    if (
        not isinstance(transport, dict)
        or transport.get("external_provider") is not True
        or transport.get("fixture") is not False
        or transport.get("simulated") is not False
        or transport.get("transport")
        != provider_gate_result.get("external_provider_transport")
    ):
        raise ActivationReceiptError("external provider transport is not bound")
    provider_binding = {
        "provider": evaluated_registry["provider"],
        "provider_executable": evaluated_registry["provider_executable"],
        "provider_executable_sha256": evaluated_registry[
            "provider_executable_sha256"
        ],
    }
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_status": "active",
        "active": True,
        "activated_at": activated_at,
        "corpus_manifest_sha256": manifest_sha,
        "provider_report_sha256": report_sha,
        "annotation_set_sha256": annotation_sha,
        "citation_review_set_sha256": citation_review_sha,
        "evaluated_registry_sha256": evaluated_registry_sha,
        "target_shadow_registry_canonical_sha256": canonical_sha256(
            target_registry
        ),
        "target_shadow_registry_file_sha256": sha256_bytes(
            atomic_json_bytes(target_registry)
        ),
        "evaluated_registry_snapshot": copy.deepcopy(evaluated_registry),
        "model_role_config": role_config,
        "role_bindings": copy.deepcopy(report["role_bindings"]),
        "runtime_code_sha256": runtime_code_hashes,
        "transitive_artifact_sha256": transitive_artifact_hashes,
        "provider_binding": provider_binding,
        "external_provider_transport": transport["transport"],
        "quality_counts": counts,
        "violation_totals": violations,
        "provider_gate_passed": True,
        "boundary_verification_passed": True,
        "external_auth_ready": True,
        "canonical_influence_enabled": False,
        "automatic_action_allowed": False,
        "email_eligible": False,
        "broker_connection_allowed": False,
        "order_code_allowed": False,
        "activation_scope": "exploratory_shadow_only",
    }
    receipt["receipt_id"] = canonical_sha256(receipt)
    return receipt, target_registry


def _verify_receipt(
    *,
    registry_path: Path,
    receipt_path: Path,
    corpus_manifest_path: Path,
    provider_report_path: Path,
    annotation_set_path: Path,
    citation_review_set_path: Path,
) -> dict[str, Any]:
    receipt, _ = _read_json(receipt_path, label="activation receipt")
    _exact_keys(
        receipt,
        {
            "schema_version",
            "receipt_id",
            "receipt_status",
            "active",
            "activated_at",
            "corpus_manifest_sha256",
            "provider_report_sha256",
            "annotation_set_sha256",
            "citation_review_set_sha256",
            "evaluated_registry_sha256",
            "target_shadow_registry_canonical_sha256",
            "target_shadow_registry_file_sha256",
            "evaluated_registry_snapshot",
            "model_role_config",
            "role_bindings",
            "runtime_code_sha256",
            "transitive_artifact_sha256",
            "provider_binding",
            "external_provider_transport",
            "quality_counts",
            "violation_totals",
            "provider_gate_passed",
            "boundary_verification_passed",
            "external_auth_ready",
            "canonical_influence_enabled",
            "automatic_action_allowed",
            "email_eligible",
            "broker_connection_allowed",
            "order_code_allowed",
            "activation_scope",
        },
        label="activation receipt",
    )
    if receipt["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise ActivationReceiptError("activation receipt version mismatch")
    claimed_receipt_id = _valid_sha256(
        receipt["receipt_id"], label="activation receipt ID"
    )
    unsigned_receipt = dict(receipt)
    unsigned_receipt.pop("receipt_id")
    if canonical_sha256(unsigned_receipt) != claimed_receipt_id:
        raise ActivationReceiptError("activation receipt ID does not match content")
    _validate_timestamp(receipt["activated_at"], label="activation timestamp")
    if (
        receipt["receipt_status"] != "active"
        or receipt["active"] is not True
        or receipt["provider_gate_passed"] is not True
        or receipt["boundary_verification_passed"] is not True
        or receipt["external_auth_ready"] is not True
    ):
        raise ActivationReceiptError("activation receipt is not active")
    if receipt["activation_scope"] != "exploratory_shadow_only":
        raise ActivationReceiptError("activation scope is not exploratory shadow")
    false_receipt_fields = (
        "canonical_influence_enabled",
        "automatic_action_allowed",
        "email_eligible",
        "broker_connection_allowed",
        "order_code_allowed",
    )
    if any(receipt[field] is not False for field in false_receipt_fields):
        raise ActivationReceiptError("activation receipt is not fail-closed")

    evaluated_registry = receipt["evaluated_registry_snapshot"]
    if not isinstance(evaluated_registry, dict):
        raise ActivationReceiptError("evaluated registry snapshot is missing")
    evaluated_raw = atomic_json_bytes(evaluated_registry)
    if (
        sha256_bytes(evaluated_raw)
        != _valid_sha256(
            receipt["evaluated_registry_sha256"],
            label="evaluated registry hash",
        )
    ):
        raise ActivationReceiptError("evaluated registry snapshot/hash mismatch")
    target_registry = target_shadow_registry(evaluated_registry)
    registry, registry_raw = _read_json(registry_path, label="current model registry")
    if registry != target_registry:
        raise ActivationReceiptError(
            "current registry is not the uniquely derived shadow target"
        )
    if (
        canonical_sha256(registry)
        != receipt["target_shadow_registry_canonical_sha256"]
        or sha256_bytes(registry_raw)
        != receipt["target_shadow_registry_file_sha256"]
    ):
        raise ActivationReceiptError("current registry target hashes do not match")
    if receipt["model_role_config"] != registry["roles"]:
        raise ActivationReceiptError("receipt model/role configuration is stale")
    if receipt["runtime_code_sha256"] != _runtime_code_hashes():
        raise ActivationReceiptError("activation runtime code hashes are stale")
    if receipt["provider_binding"] != {
        "provider": registry["provider"],
        "provider_executable": registry["provider_executable"],
        "provider_executable_sha256": registry["provider_executable_sha256"],
    }:
        raise ActivationReceiptError("receipt provider binding is stale")

    manifest, manifest_raw = _read_json(
        corpus_manifest_path, label="current replay corpus manifest"
    )
    report, report_raw = _read_json(
        provider_report_path, label="current provider replay report"
    )
    _, annotation_raw = _read_json(
        annotation_set_path, label="current transition annotation set"
    )
    _, citation_review_raw = _read_json(
        citation_review_set_path,
        label="current claim citation review set",
    )
    transitive_artifact_hashes = _validate_transitive_artifact_hashes(
        receipt["transitive_artifact_sha256"],
        corpus_root=corpus_manifest_path.parent,
        report_root=provider_report_path.parent,
    )
    if transitive_artifact_hashes != receipt["transitive_artifact_sha256"]:
        raise ActivationReceiptError(
            "current transitive artifact binding is stale"
        )
    manifest_sha = sha256_bytes(manifest_raw)
    report_sha = sha256_bytes(report_raw)
    annotation_sha = sha256_bytes(annotation_raw)
    citation_review_sha = sha256_bytes(citation_review_raw)
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest_sha != receipt["corpus_manifest_sha256"]
    ):
        raise ActivationReceiptError("current replay corpus hash is stale")
    if (
        report.get("schema_version") != REPORT_SCHEMA_VERSION
        or report_sha != receipt["provider_report_sha256"]
    ):
        raise ActivationReceiptError("current provider replay report hash is stale")
    if (
        annotation_sha != receipt["annotation_set_sha256"]
        or citation_review_sha != receipt["citation_review_set_sha256"]
        or report.get("annotation_set_binding", {}).get(
            "annotation_file_sha256"
        )
        != annotation_sha
        or report.get("extended_quality", {})
        .get("citation_review_set_binding", {})
        .get("review_file_sha256")
        != citation_review_sha
    ):
        raise ActivationReceiptError("current human-review artifact hashes are stale")
    if (
        report.get("corpus_manifest_sha256") != manifest_sha
        or report.get("model_registry_sha256")
        != receipt["evaluated_registry_sha256"]
    ):
        raise ActivationReceiptError("provider report pre-activation bindings are stale")
    if (
        _role_config_from_report(report, evaluated_registry)
        != receipt["model_role_config"]
    ):
        raise ActivationReceiptError("provider report model/role binding is stale")
    if receipt["role_bindings"] != report["role_bindings"]:
        raise ActivationReceiptError("receipt prompt/schema hash binding is stale")
    if report.get("runtime_code_sha256") != receipt["runtime_code_sha256"]:
        raise ActivationReceiptError("provider report runtime code binding is stale")
    summary = report.get("summary")
    if not isinstance(summary, dict) or summary.get("quality_gate_passed") is not True:
        raise ActivationReceiptError("provider report no longer records a pass")
    if (
        _quality_counts(summary) != receipt["quality_counts"]
        or _zero_violations(summary.get("violation_totals"))
        != receipt["violation_totals"]
    ):
        raise ActivationReceiptError("provider report counts/violations are stale")
    _validate_report_boundaries(report)
    transport = report.get("provider_transport")
    if (
        not isinstance(transport, dict)
        or transport.get("external_provider") is not True
        or transport.get("fixture") is not False
        or transport.get("simulated") is not False
        or transport.get("transport") != receipt["external_provider_transport"]
    ):
        raise ActivationReceiptError("provider report transport is stale")
    return {
        "passed": True,
        "receipt_id": receipt["receipt_id"],
        "registry_mode": registry["mode"],
        "live_shadow_enabled": registry["live_shadow_enabled"],
        "packet_count": receipt["quality_counts"]["packet_count"],
        "material_transition_count": receipt["quality_counts"][
            "material_transition_count"
        ],
        "external_provider_transport": receipt["external_provider_transport"],
        "provider_invoked": False,
        "network_invoked": False,
        "email_invoked": False,
        "c7_invoked": False,
        "broker_invoked": False,
        "order_invoked": False,
        "files_written": False,
    }


def verify_active_activation_receipt(
    *,
    registry_path: Path = MODEL_REGISTRY_PATH,
    receipt_path: Path = ACTIVATION_RECEIPT_PATH,
    corpus_manifest_path: Path = CORPUS_MANIFEST_PATH,
    provider_report_path: Path = PROVIDER_REPORT_PATH,
    annotation_set_path: Path = ANNOTATION_SET_PATH,
    citation_review_set_path: Path = CITATION_REVIEW_SET_PATH,
) -> dict[str, Any]:
    """Return a safe result instead of propagating receipt-validation details."""

    try:
        return _verify_receipt(
            registry_path=registry_path,
            receipt_path=receipt_path,
            corpus_manifest_path=corpus_manifest_path,
            provider_report_path=provider_report_path,
            annotation_set_path=annotation_set_path,
            citation_review_set_path=citation_review_set_path,
        )
    except (
        ActivationReceiptError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as exc:
        return {
            "passed": False,
            "issues": [str(exc)],
            "provider_invoked": False,
            "network_invoked": False,
            "email_invoked": False,
            "c7_invoked": False,
            "broker_invoked": False,
            "order_invoked": False,
            "files_written": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-active", action="store_true", required=True)
    parser.add_argument("--registry", type=Path, default=MODEL_REGISTRY_PATH)
    parser.add_argument("--receipt", type=Path, default=ACTIVATION_RECEIPT_PATH)
    parser.add_argument(
        "--corpus-manifest", type=Path, default=CORPUS_MANIFEST_PATH
    )
    parser.add_argument(
        "--provider-report", type=Path, default=PROVIDER_REPORT_PATH
    )
    parser.add_argument(
        "--annotation-set", type=Path, default=ANNOTATION_SET_PATH
    )
    parser.add_argument(
        "--citation-review-set",
        type=Path,
        default=CITATION_REVIEW_SET_PATH,
    )
    args = parser.parse_args()
    del args.check_active
    result = verify_active_activation_receipt(
        registry_path=args.registry.expanduser().resolve(),
        receipt_path=args.receipt.expanduser().resolve(),
        corpus_manifest_path=args.corpus_manifest.expanduser().resolve(),
        provider_report_path=args.provider_report.expanduser().resolve(),
        annotation_set_path=args.annotation_set.expanduser().resolve(),
        citation_review_set_path=(
            args.citation_review_set.expanduser().resolve()
        ),
    )
    print(
        f"llm_activation_receipt={'passed' if result['passed'] else 'failed'} "
        "provider_invoked=false network_invoked=false email_invoked=false "
        "c7_invoked=false broker_invoked=false order_invoked=false "
        "files_written=false"
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
