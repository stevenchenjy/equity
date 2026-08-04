"""Offline handoff verification for the future Phase 5R evidence-contract v2.

This module verifies a set of future-v2 sidecar artifacts by SHA-256 over their
exact raw file bytes; it does not make their directory immutable. It verifies
only a noncanonical internal handoff: the
verifier constructs no provider or repository-initiated provider request, uses
no network, accepts no blind-key parameter, and creates no promotion, trade,
broker, or execution authority. A disclosed interactive-AI session is passive
provenance only, not a provider-call authorization or proof of independence.
It opens only fixed filenames inside a caller-designated handoff directory.

It deliberately does not read historical pilot completion records or alter any
existing v1/v10 or replacement-pilot runner.  A future execution workflow
would still require separately authorized planning, its own packet/runtime
validation gates, and a fresh verification immediately before consuming a
handoff.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
import stat
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from phase5r_llm_evidence_contract_v2 import (
    EvidenceContractV2Error,
    validate_analyst_evidence_bindings_v2,
    validate_critic_coverage_v2,
    validate_evidence_metadata_v2,
)


FUTURE_V2_HANDOFF_SCHEMA_VERSION = "phase5r_llm_evidence_contract_v2_handoff_v1"
FUTURE_V2_OWNER_APPROVAL_REFERENCE_SCHEMA_VERSION = (
    "phase5r_future_v2_owner_approval_reference_v1"
)
RAW_BYTES_HASH_RULE = "sha256_exact_raw_file_bytes"
_OS_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_JSON_NESTING_DEPTH = 100
_MAX_JSON_NUMBER_DIGITS = 1024
_MAX_JSON_DECIMAL_EXPONENT = 4096

_ARTIFACT_LABELS = (
    "packet",
    "source_texts",
    "analyst_response",
    "metadata",
    "analyst_bindings",
    "committee_response",
    "committee_ticker_decisions",
    "critic_coverage",
)
_HANDOFF_FILENAMES = {
    "manifest": "future_v2_handoff_manifest.json",
    "packet": "packet.json",
    "source_texts": "evidence_source_texts_v2.json",
    "analyst_response": "analyst_response.json",
    "metadata": "evidence_metadata_v2.json",
    "analyst_bindings": "analyst_evidence_bindings_v2.json",
    "committee_response": "committee_response.json",
    "committee_ticker_decisions": "committee_ticker_decisions.json",
    "critic_coverage": "critic_coverage_v2.json",
}
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "hash_rule",
        "packet_id",
        "artifact_sha256",
        "metadata_provenance",
        "generation_provenance",
        "review_status",
        "boundaries",
    }
)
_PROVENANCE_FIELDS = frozenset(
    {
        "attested_method",
        "attested_packet_local_excerpt_only",
        "attested_external_evidence_used",
        "attested_independent_human_review_satisfied",
        "attested_repository_initiated_provider_call_made",
    }
)
_GENERATION_PROVENANCE_FIELDS = frozenset(
    {
        "generation_mode",
        "repository_initiated_provider_call_made",
        "repository_initiated_provider_call_authorized",
        "external_evidence_used",
        "tools_or_browse_used",
        "interactive_ai_session",
        "independence_status",
    }
)
_INTERACTIVE_AI_SESSION_FIELDS = frozenset(
    {
        "provider",
        "model_family",
        "review_date",
        "reasoning_configuration",
    }
)
_REVIEW_STATUS_FIELDS = frozenset(
    {
        "human_review_status",
        "counts_toward_original_human_review_requirement",
        "reviewer_independence_status",
    }
)
_OWNER_APPROVAL_REFERENCE_FIELDS = frozenset(
    {
        "schema_version",
        "record_type",
        "policy_owner",
        "authority",
        "decision",
        "scope",
        "effective_at_et",
        "manifest_sha256",
        "packet_id",
        "human_review_requirement_waived",
        "independent_human_review_satisfied",
        "canonical_authority_created",
        "blind_key_access_authorized",
        "unblinding_authorized",
        "repository_provider_call_authorized",
        "runtime_execution_authorized",
        "automatic_action_authorized",
        "broker_access_authorized",
        "email_effect_authorized",
        "revocation_authority",
    }
)
_BOUNDARY_FIELDS = frozenset(
    {
        "execution_prohibited",
        "provider_use_authorized",
        "network_use_authorized",
        "canonical_effect_authorized",
        "automatic_action_authorized",
        "broker_use_authorized",
        "email_effect_authorized",
        "blind_key_access_authorized",
        "unblinding_authorized",
    }
)


class EvidenceContractV2HandoffError(ValueError):
    """A proposed future-v2 handoff failed a local integrity or boundary gate."""


class _StrictJsonError(ValueError):
    """A raw handoff artifact is not unambiguous standards-conforming JSON."""


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate keys.

    Python's default decoder silently keeps the last duplicate key.  That is
    unsafe for a frozen handoff because another consumer may display or parse a
    different occurrence.  Reject it before any schema validation instead.
    """

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> Any:
    """Reject Python's permissive NaN/Infinity JSON extension."""

    raise _StrictJsonError("nonstandard JSON numeric constant")


def _strict_json_decimal(value: str) -> Decimal:
    """Parse a bounded finite JSON decimal without relying on runtime defaults.

    The limits apply to the raw JSON numeric lexeme before ``Decimal`` can
    normalize a long run of zeroes or fold a supplied exponent into its tuple.
    """

    numeric_digit_count = sum(character.isdigit() for character in value)
    if numeric_digit_count > _MAX_JSON_NUMBER_DIGITS:
        raise _StrictJsonError("JSON numeric value has too many digits")
    normalized_value = value.lower()
    if "e" in normalized_value:
        raw_exponent = normalized_value.rsplit("e", 1)[1].lstrip("+-")
        maximum_exponent_digits = len(str(_MAX_JSON_DECIMAL_EXPONENT))
        if (
            len(raw_exponent) > maximum_exponent_digits
            or int(raw_exponent) > _MAX_JSON_DECIMAL_EXPONENT
        ):
            raise _StrictJsonError("JSON numeric exponent exceeds maximum")

    try:
        decimal_value = Decimal(value)
    except InvalidOperation as exc:
        raise _StrictJsonError("invalid JSON numeric value") from exc
    if not decimal_value.is_finite():
        raise _StrictJsonError("non-finite JSON numeric value")
    _, _, exponent = decimal_value.as_tuple()
    if abs(exponent) > _MAX_JSON_DECIMAL_EXPONENT:
        raise _StrictJsonError("JSON numeric exponent exceeds maximum")
    return decimal_value


def _strict_json_int(value: str) -> int:
    """Parse an integer only after enforcing the handoff's digit limit."""

    if sum(character.isdigit() for character in value) > _MAX_JSON_NUMBER_DIGITS:
        raise _StrictJsonError("JSON numeric value has too many digits")
    try:
        return int(value)
    except ValueError as exc:
        raise _StrictJsonError("invalid JSON numeric value") from exc


def _strict_json_float(value: str) -> float:
    """Allow only finite decimals that round-trip via Python's shortest repr.

    This is deliberately a decimal round-trip policy, not a claim that every
    accepted decimal is represented exactly by binary IEEE-754. Exact raw
    bytes remain the handoff identity rule.
    """

    decimal_value = _strict_json_decimal(value)
    try:
        parsed = float(value)
    except (ValueError, OverflowError) as exc:
        raise _StrictJsonError("invalid JSON numeric value") from exc
    if not math.isfinite(parsed):
        raise _StrictJsonError("non-finite JSON numeric value")
    if Decimal(repr(parsed)) != decimal_value:
        raise _StrictJsonError("non-round-tripping JSON numeric value")
    return parsed


def _require_unicode_scalars(value: Any) -> None:
    """Reject unpaired surrogates and excessively nested decoded JSON."""

    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > _MAX_JSON_NESTING_DEPTH:
            raise _StrictJsonError("JSON nesting exceeds maximum depth")
        if isinstance(current, str):
            try:
                current.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise _StrictJsonError("non-UTF-8 Unicode scalar") from exc
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            for key, item in current.items():
                pending.append((key, depth + 1))
                pending.append((item, depth + 1))


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceContractV2HandoffError(f"{label}: expected object")
    return value


def _require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceContractV2HandoffError(f"{label}: expected non-empty string")
    return value


def _require_closed_keys(value: Any, *, fields: frozenset[str], label: str) -> dict[str, Any]:
    row = _require_object(value, label=label)
    if set(row) != fields:
        missing = sorted(fields - set(row))
        extras = sorted(set(row) - fields)
        details: list[str] = []
        if missing:
            details.append("missing " + ",".join(missing))
        if extras:
            details.append("unexpected " + ",".join(extras))
        raise EvidenceContractV2HandoffError(
            f"{label}: field mismatch ({'; '.join(details)})"
        )
    return row


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise EvidenceContractV2HandoffError(f"{label}: invalid sha256")
    return value


def _open_handoff_root(handoff_root: Path) -> int:
    """Open the handoff directory once, without following its final symlink.

    Every artifact is subsequently opened by its fixed basename relative to
    this descriptor. That avoids re-resolving a mutable path between an
    initial containment check and the actual read.
    """

    if not isinstance(handoff_root, Path):
        raise EvidenceContractV2HandoffError("handoff_root: expected regular directory")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise EvidenceContractV2HandoffError(
            "handoff_root: O_NOFOLLOW and O_DIRECTORY are required"
        )
    try:
        descriptor = os.open(
            handoff_root,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY,
        )
    except OSError as exc:
        raise EvidenceContractV2HandoffError(
            "handoff_root: expected regular directory"
        ) from exc
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise EvidenceContractV2HandoffError(
                "handoff_root: expected regular directory"
            )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _read_json_artifact(
    handoff_root_descriptor: int,
    *,
    filename: str,
    label: str,
) -> tuple[Any, str]:
    if filename not in _HANDOFF_FILENAMES.values():
        raise EvidenceContractV2HandoffError(f"{label}: unrecognized fixed filename")
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_NONBLOCK")
        or not _OS_OPEN_SUPPORTS_DIR_FD
    ):
        raise EvidenceContractV2HandoffError(
            f"{label}: directory-descriptor no-follow opening is required"
        )
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=handoff_root_descriptor,
        )
    except OSError as exc:
        raise EvidenceContractV2HandoffError(f"{label}: expected regular file") from exc
    try:
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode):
            raise EvidenceContractV2HandoffError(f"{label}: expected regular file")
        if file_status.st_nlink != 1:
            raise EvidenceContractV2HandoffError(
                f"{label}: hard-linked artifacts are prohibited"
            )
        if file_status.st_size > _MAX_ARTIFACT_BYTES:
            raise EvidenceContractV2HandoffError(
                f"{label}: artifact exceeds maximum byte size"
            )
        chunks: list[bytes] = []
        bytes_read = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > _MAX_ARTIFACT_BYTES:
                raise EvidenceContractV2HandoffError(
                    f"{label}: artifact exceeds maximum byte size"
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise EvidenceContractV2HandoffError(
            f"{label}: text must be UTF-8 without BOM and LF-only"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
            parse_float=_strict_json_float,
            parse_int=_strict_json_int,
        )
        _require_unicode_scalars(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _StrictJsonError,
        RecursionError,
        ValueError,
        OverflowError,
    ) as exc:
        raise EvidenceContractV2HandoffError(
            f"{label}: expected strict UTF-8 JSON"
        ) from exc
    return value, _sha256(raw)


def _validate_generation_provenance(value: Any) -> dict[str, Any]:
    provenance = _require_closed_keys(
        value,
        fields=_GENERATION_PROVENANCE_FIELDS,
        label="future_v2_handoff.generation_provenance",
    )
    generation_mode = provenance["generation_mode"]
    if generation_mode not in {
        "human",
        "synthetic",
        "interactive_ai_session",
    }:
        raise EvidenceContractV2HandoffError(
            "future_v2_handoff.generation_provenance: invalid generation_mode"
        )
    for field in (
        "repository_initiated_provider_call_made",
        "repository_initiated_provider_call_authorized",
        "external_evidence_used",
        "tools_or_browse_used",
    ):
        if provenance[field] is not False:
            raise EvidenceContractV2HandoffError(
                f"future_v2_handoff.generation_provenance.{field}: must be False"
            )
    session = provenance["interactive_ai_session"]
    independence_status = provenance["independence_status"]
    if generation_mode == "interactive_ai_session":
        session = _require_closed_keys(
            session,
            fields=_INTERACTIVE_AI_SESSION_FIELDS,
            label="future_v2_handoff.generation_provenance.interactive_ai_session",
        )
        for field in ("provider", "model_family", "reasoning_configuration"):
            _require_text(
                session[field],
                label=(
                    "future_v2_handoff.generation_provenance."
                    f"interactive_ai_session.{field}"
                ),
            )
        review_date = _require_text(
            session["review_date"],
            label=(
                "future_v2_handoff.generation_provenance."
                "interactive_ai_session.review_date"
            ),
        )
        try:
            parsed_date = datetime.fromisoformat(review_date)
        except ValueError as exc:
            raise EvidenceContractV2HandoffError(
                "future_v2_handoff.generation_provenance.interactive_ai_session: "
                "invalid review_date"
            ) from exc
        if parsed_date.tzinfo is None:
            raise EvidenceContractV2HandoffError(
                "future_v2_handoff.generation_provenance.interactive_ai_session: "
                "review_date must include timezone"
            )
        if independence_status != "presumed_non_independent":
            raise EvidenceContractV2HandoffError(
                "future_v2_handoff.generation_provenance.independence_status: "
                "interactive AI must be presumed_non_independent"
            )
    else:
        if session is not None:
            raise EvidenceContractV2HandoffError(
                "future_v2_handoff.generation_provenance.interactive_ai_session: "
                "must be null outside interactive_ai_session mode"
            )
        if independence_status != "not_established":
            raise EvidenceContractV2HandoffError(
                "future_v2_handoff.generation_provenance.independence_status: "
                "must be not_established outside interactive_ai_session mode"
            )
    return provenance


def _validate_review_status(value: Any) -> dict[str, Any]:
    review_status = _require_closed_keys(
        value,
        fields=_REVIEW_STATUS_FIELDS,
        label="future_v2_handoff.review_status",
    )
    if review_status["human_review_status"] != "not_performed":
        raise EvidenceContractV2HandoffError(
            "future_v2_handoff.review_status.human_review_status: must be not_performed"
        )
    if review_status["counts_toward_original_human_review_requirement"] is not False:
        raise EvidenceContractV2HandoffError(
            "future_v2_handoff.review_status."
            "counts_toward_original_human_review_requirement: must be False"
        )
    if review_status["reviewer_independence_status"] != "not_established":
        raise EvidenceContractV2HandoffError(
            "future_v2_handoff.review_status.reviewer_independence_status: "
            "must be not_established"
        )
    return review_status


def validate_future_v2_owner_approval_reference(
    value: Any,
) -> dict[str, Any]:
    """Validate a noncanonical owner-approval reference without adopting it.

    This checks only a closed local record shape and fail-closed boundaries. It
    cannot verify a human identity, a signature, or real-world authority; a
    future process must retain that record outside the handoff directory.
    """

    record = _require_closed_keys(
        value,
        fields=_OWNER_APPROVAL_REFERENCE_FIELDS,
        label="future_v2_owner_approval_reference",
    )
    if record["schema_version"] != FUTURE_V2_OWNER_APPROVAL_REFERENCE_SCHEMA_VERSION:
        raise EvidenceContractV2HandoffError(
            "future_v2_owner_approval_reference: schema version mismatch"
        )
    expected_text = {
        "record_type": "project_owner_noncanonical_internal_quality_approval",
        "authority": "project_owner",
        "decision": "approved_noncanonical_internal_quality_only",
        "scope": "future_v2_noncanonical_internal_quality_only",
        "revocation_authority": "project_owner",
    }
    for field, expected in expected_text.items():
        if record[field] != expected:
            raise EvidenceContractV2HandoffError(
                f"future_v2_owner_approval_reference.{field}: must be {expected}"
            )
    _require_text(
        record["policy_owner"],
        label="future_v2_owner_approval_reference.policy_owner",
    )
    _require_text(
        record["packet_id"],
        label="future_v2_owner_approval_reference.packet_id",
    )
    _require_sha256(
        record["manifest_sha256"],
        label="future_v2_owner_approval_reference.manifest_sha256",
    )
    effective_at_et = _require_text(
        record["effective_at_et"],
        label="future_v2_owner_approval_reference.effective_at_et",
    )
    try:
        effective_at = datetime.fromisoformat(effective_at_et)
    except ValueError as exc:
        raise EvidenceContractV2HandoffError(
            "future_v2_owner_approval_reference.effective_at_et: invalid timestamp"
        ) from exc
    if effective_at.tzinfo is None:
        raise EvidenceContractV2HandoffError(
            "future_v2_owner_approval_reference.effective_at_et: timezone required"
        )
    try:
        eastern_offset = effective_at.astimezone(
            ZoneInfo("America/New_York")
        ).utcoffset()
    except ZoneInfoNotFoundError as exc:
        raise EvidenceContractV2HandoffError(
            "future_v2_owner_approval_reference.effective_at_et: "
            "America/New_York timezone data unavailable"
        ) from exc
    if effective_at.utcoffset() != eastern_offset:
        raise EvidenceContractV2HandoffError(
            "future_v2_owner_approval_reference.effective_at_et: "
            "must use America/New_York offset"
        )
    for field in (
        "human_review_requirement_waived",
        "independent_human_review_satisfied",
        "canonical_authority_created",
        "blind_key_access_authorized",
        "unblinding_authorized",
        "repository_provider_call_authorized",
        "runtime_execution_authorized",
        "automatic_action_authorized",
        "broker_access_authorized",
        "email_effect_authorized",
    ):
        if record[field] is not False:
            raise EvidenceContractV2HandoffError(
                f"future_v2_owner_approval_reference.{field}: must be False"
            )
    return record


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = _require_closed_keys(
        manifest, fields=_MANIFEST_FIELDS, label="future_v2_handoff"
    )
    if manifest["schema_version"] != FUTURE_V2_HANDOFF_SCHEMA_VERSION:
        raise EvidenceContractV2HandoffError("future_v2_handoff: schema version mismatch")
    if manifest["status"] != "validated_offline_noncanonical":
        raise EvidenceContractV2HandoffError("future_v2_handoff: invalid status")
    if manifest["hash_rule"] != RAW_BYTES_HASH_RULE:
        raise EvidenceContractV2HandoffError("future_v2_handoff: hash rule mismatch")
    _require_text(manifest["packet_id"], label="future_v2_handoff.packet_id")
    artifact_sha256 = _require_object(
        manifest["artifact_sha256"], label="future_v2_handoff.artifact_sha256"
    )
    if set(artifact_sha256) != set(_ARTIFACT_LABELS):
        raise EvidenceContractV2HandoffError(
            "future_v2_handoff.artifact_sha256: field mismatch"
        )
    for label in _ARTIFACT_LABELS:
        _require_sha256(
            artifact_sha256[label],
            label=f"future_v2_handoff.artifact_sha256.{label}",
        )
    provenance = _require_closed_keys(
        manifest["metadata_provenance"],
        fields=_PROVENANCE_FIELDS,
        label="future_v2_handoff.metadata_provenance",
    )
    if provenance["attested_method"] not in {
        "human_curation",
        "deterministic_curation",
    }:
        raise EvidenceContractV2HandoffError(
            "future_v2_handoff.metadata_provenance: invalid method"
        )
    expected_provenance = {
        "attested_packet_local_excerpt_only": True,
        "attested_external_evidence_used": False,
        "attested_independent_human_review_satisfied": False,
        "attested_repository_initiated_provider_call_made": False,
    }
    for field, expected in expected_provenance.items():
        if provenance[field] is not expected:
            raise EvidenceContractV2HandoffError(
                f"future_v2_handoff.metadata_provenance.{field}: must be {expected}"
            )
    _validate_generation_provenance(manifest["generation_provenance"])
    _validate_review_status(manifest["review_status"])
    boundaries = _require_closed_keys(
        manifest["boundaries"],
        fields=_BOUNDARY_FIELDS,
        label="future_v2_handoff.boundaries",
    )
    expected_boundaries = {
        "execution_prohibited": True,
        "provider_use_authorized": False,
        "network_use_authorized": False,
        "canonical_effect_authorized": False,
        "automatic_action_authorized": False,
        "broker_use_authorized": False,
        "email_effect_authorized": False,
        "blind_key_access_authorized": False,
        "unblinding_authorized": False,
    }
    for field, expected in expected_boundaries.items():
        if boundaries[field] is not expected:
            raise EvidenceContractV2HandoffError(
                f"future_v2_handoff.boundaries.{field}: must be {expected}"
            )
    return manifest


def verify_future_v2_handoff(
    *,
    handoff_root: Path,
    owner_approval_reference: dict[str, Any],
) -> dict[str, Any]:
    """Verify a hash-bound, noncanonical future-v2 handoff without side effects.

    The approval reference must be retained outside the handoff directory. This
    function validates only its closed shape and fail-closed boundaries; it
    cannot verify a human identity, signature, or real-world authority. It also
    cannot establish upstream packet validity, semantic truth, numeric
    reconciliation, reviewer independence, or historical runtime behavior.
    """

    # The closed record contains only scalars.  Snapshot it before opening any
    # handoff file so a mutable caller cannot alter the reference after shape
    # validation but before the manifest/packet comparisons.
    approval = dict(validate_future_v2_owner_approval_reference(owner_approval_reference))
    handoff_root_descriptor = _open_handoff_root(handoff_root)
    try:
        manifest_value, manifest_sha256 = _read_json_artifact(
            handoff_root_descriptor,
            filename=_HANDOFF_FILENAMES["manifest"],
            label="manifest",
        )
        if manifest_sha256 != approval["manifest_sha256"]:
            raise EvidenceContractV2HandoffError(
                "future_v2_handoff: manifest raw-byte hash mismatch"
            )
        manifest = _validate_manifest(_require_object(manifest_value, label="manifest"))
        if approval["packet_id"] != manifest["packet_id"]:
            raise EvidenceContractV2HandoffError(
                "future_v2_handoff: approval reference packet_id mismatch"
            )
        artifacts: dict[str, Any] = {}
        actual_hashes: dict[str, str] = {}
        for label in _ARTIFACT_LABELS:
            artifacts[label], actual_hashes[label] = _read_json_artifact(
                handoff_root_descriptor,
                filename=_HANDOFF_FILENAMES[label],
                label=label,
            )
        for label in _ARTIFACT_LABELS:
            if manifest["artifact_sha256"][label] != actual_hashes[label]:
                raise EvidenceContractV2HandoffError(
                    f"future_v2_handoff: raw artifact hash mismatch for {label}"
                )
        packet = _require_object(artifacts["packet"], label="packet")
        if packet.get("packet_id") != manifest["packet_id"]:
            raise EvidenceContractV2HandoffError("future_v2_handoff: packet_id mismatch")
        analyst_response = _require_object(
            artifacts["analyst_response"], label="analyst_response"
        )
        source_texts = _require_object(artifacts["source_texts"], label="source_texts")
        metadata = _require_object(artifacts["metadata"], label="metadata")
        analyst_bindings = _require_object(
            artifacts["analyst_bindings"], label="analyst_bindings"
        )
        committee_response = _require_object(
            artifacts["committee_response"], label="committee_response"
        )
        critic_coverage = _require_object(
            artifacts["critic_coverage"], label="critic_coverage"
        )
        committee_ticker_decisions = _require_object(
            artifacts["committee_ticker_decisions"],
            label="committee_ticker_decisions",
        )
        try:
            validate_evidence_metadata_v2(packet, metadata, source_texts=source_texts)
            validate_analyst_evidence_bindings_v2(
                packet,
                metadata,
                analyst_bindings,
                source_texts=source_texts,
                analyst_response=analyst_response,
            )
            validate_critic_coverage_v2(
                packet=packet,
                metadata=metadata,
                source_texts=source_texts,
                analyst_response=analyst_response,
                analyst_bindings=analyst_bindings,
                committee_response=committee_response,
                committee_ticker_decisions=committee_ticker_decisions,
                response=critic_coverage,
            )
        except EvidenceContractV2Error as exc:
            raise EvidenceContractV2HandoffError(
                f"future_v2_handoff: sidecar validation failed: {exc}"
            ) from exc
        return {
            "schema_version": FUTURE_V2_HANDOFF_SCHEMA_VERSION,
            "procedure_status": "completed",
            "integrity_status": "raw_bytes_and_contract_bindings_validated",
            "sidecar_integrity_validated": True,
            "substantive_status": "not_established",
            "substantive_recommendation": "not_established",
            "authority_status": "noncanonical_internal_quality_only",
            "metadata_provenance_status": "attested_not_verified",
            "generation_provenance_status": "attested_not_verified",
            "review_status_provenance": "attested_not_verified",
            "owner_approval_reference_schema_validated": True,
            "owner_identity_or_signature_verified": False,
            "upstream_validation_verified": False,
            "normalized_metadata_status": "hash_bound_but_not_semantically_verified",
            "semantic_validation_established": False,
            "numeric_reconciliation_established": False,
            "reviewer_independence_established": False,
            "reviewer_independence_status": manifest["generation_provenance"][
                "independence_status"
            ],
            "reviewer_independence_status_verified": False,
            "human_review_status": "not_performed",
            "counts_toward_original_human_review_requirement": False,
            "packet_id": manifest["packet_id"],
            "hash_rule": RAW_BYTES_HASH_RULE,
            "generation_mode": manifest["generation_provenance"]["generation_mode"],
            "interactive_ai_session_disclosure_validated": (
                manifest["generation_provenance"]["generation_mode"]
                == "interactive_ai_session"
            ),
            "manifest_sha256": manifest_sha256,
            "artifact_sha256": actual_hashes,
            "execution_prohibited": True,
            "verifier_provider_constructed": False,
            "verifier_network_used": False,
            "repository_initiated_provider_call_authorized": False,
            "repository_initiated_provider_call_made_attested": False,
            "repository_initiated_provider_call_made_verified": False,
            "canonical_effect_authorized": False,
            "automatic_action_authorized": False,
            "broker_use_authorized": False,
            "email_effect_authorized": False,
            "blind_key_access_authorized": False,
            "unblinding_authorized": False,
            "independent_human_review_satisfied": False,
        }
    finally:
        os.close(handoff_root_descriptor)
