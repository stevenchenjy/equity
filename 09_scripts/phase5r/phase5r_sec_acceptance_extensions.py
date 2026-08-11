#!/usr/bin/env python3
"""Versioned, append-only SEC acceptance-index extensions for Phase 5R.

The retained historical acceptance index is immutable.  This module creates a
separate, hash-bound extension artifact only for a newly observed official SEC
accession that passes the same identity and provenance checks.  It never edits
or rewrites the historical index.
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from phase5r_daily_common import (
    ROOT,
    append_csv_durable,
    atomic_write_json,
    canonical_sha256,
    read_json,
)
from phase5r_sec_acceptance import (
    BOUNDARIES,
    RECORD_FIELDS,
    AcceptanceReconciliationError,
    make_acceptance_record,
    normalize_acceptance_timestamp,
    validate_acceptance_record,
)


SEC_ACCEPTANCE_EXTENSION_DIR = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_acceptance_extensions"
)
SEC_ACCEPTANCE_EXTENSION_AUDIT_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_acceptance_extension_admission_audit.csv"
)
SEC_ACCEPTANCE_EXTENSION_LOCK_PATH = (
    ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_sec_acceptance_extension.lock"
)
EXTENSION_SCHEMA_VERSION = "phase5r_sec_acceptance_extension_artifact_v1"
EXTENSION_FILE_PREFIX = "phase5r_sec_acceptance_extension_"
EXTENSION_VERSION_PATTERN = re.compile(r"v([1-9]\d*)")
FORM_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9 .-]{0,31}")
HEX_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ADMISSION_DECISION = "admitted"
MAX_ENTITY_NAME_CHARS = 256

EXTENSION_RECORD_FIELDS = {
    *RECORD_FIELDS,
    "form",
    "entity_name",
    "extension_version",
    "admitted_at",
    "admission_decision",
    "prior_immutable_index_sha256",
    "extension_record_sha256",
}
EXTENSION_ARTIFACT_FIELDS = {
    "schema_version",
    "extension_version",
    "prior_immutable_index_sha256",
    "prior_extension_set_sha256",
    "admitted_at",
    "records",
    "boundaries",
    "artifact_sha256",
}
EXTENSION_AUDIT_FIELDS = [
    "audit_id",
    "extension_version",
    "accession_number",
    "ticker",
    "cik",
    "entity_name",
    "form",
    "filing_date",
    "accepted_at",
    "source_url",
    "validation_decision",
    "admitted_at",
    "prior_immutable_index_sha256",
    "extension_artifact_sha256",
]


class ExtensionValidationError(AcceptanceReconciliationError):
    """A current or retained extension cannot join the effective set."""


def raw_file_sha256(path: Path) -> str:
    """Bind an extension to exact immutable historical-index bytes."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def extension_artifact_path(
    extension_version: str,
    directory: Path = SEC_ACCEPTANCE_EXTENSION_DIR,
) -> Path:
    _extension_number(extension_version)
    return directory / f"{EXTENSION_FILE_PREFIX}{extension_version}.json"


def _extension_number(extension_version: object) -> int:
    match = EXTENSION_VERSION_PATTERN.fullmatch(str(extension_version or ""))
    if match is None:
        raise ExtensionValidationError("SEC acceptance extension version is invalid")
    return int(match.group(1))


def _normal_timestamp(value: object, label: str) -> str:
    try:
        normalized = normalize_acceptance_timestamp(value)
    except Exception as exc:  # normalize maps only malformed public metadata.
        raise ExtensionValidationError(f"SEC acceptance extension {label} is invalid") from exc
    if not normalized:
        raise ExtensionValidationError(f"SEC acceptance extension {label} is missing")
    return normalized


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and HEX_SHA256_PATTERN.fullmatch(value) is not None


def _normalized_entity_name(value: object) -> str:
    """Retain a bounded official issuer name without normalizing its meaning."""

    entity_name = str(value or "").strip()
    if (
        not entity_name
        or len(entity_name) > MAX_ENTITY_NAME_CHARS
        or any(ord(character) < 32 for character in entity_name)
    ):
        raise ExtensionValidationError("SEC acceptance extension entity identity is invalid")
    return entity_name


def extension_set_sha256(artifacts: Iterable[dict[str, Any]]) -> str:
    """Stable chain binding for all earlier extension artifacts."""

    bindings = [
        {
            "extension_version": artifact["extension_version"],
            "artifact_sha256": artifact["artifact_sha256"],
        }
        for artifact in artifacts
    ]
    return canonical_sha256(
        sorted(
            bindings,
            key=lambda binding: _extension_number(binding["extension_version"]),
        )
    )


def _core_record(raw: dict[str, Any]) -> dict[str, str]:
    return validate_acceptance_record(
        {field: raw[field] for field in RECORD_FIELDS}
    )


def make_extension_record(
    *,
    acceptance_record: dict[str, Any],
    form: object,
    entity_name: object,
    extension_version: str,
    admitted_at: object,
    prior_immutable_index_sha256: str,
) -> dict[str, str]:
    """Create one auditable extension record from already official metadata."""

    core = validate_acceptance_record(acceptance_record)
    normalized_form = str(form or "").strip().upper()
    if FORM_PATTERN.fullmatch(normalized_form) is None:
        raise ExtensionValidationError("SEC acceptance extension form is invalid")
    normalized_entity_name = _normalized_entity_name(entity_name)
    version = f"v{_extension_number(extension_version)}"
    normalized_admitted_at = _normal_timestamp(admitted_at, "admitted_at")
    if not _is_sha256(prior_immutable_index_sha256):
        raise ExtensionValidationError("SEC acceptance extension prior-index binding is invalid")
    if datetime.fromisoformat(core["accepted_at"]) > datetime.fromisoformat(
        normalized_admitted_at
    ):
        raise ExtensionValidationError("SEC acceptance extension timestamp is in the future")
    unsigned = {
        **core,
        "form": normalized_form,
        "entity_name": normalized_entity_name,
        "extension_version": version,
        "admitted_at": normalized_admitted_at,
        "admission_decision": ADMISSION_DECISION,
        "prior_immutable_index_sha256": prior_immutable_index_sha256,
    }
    return {
        **unsigned,
        "extension_record_sha256": canonical_sha256(unsigned),
    }


def validate_extension_record(
    raw: Any,
    *,
    expected_version: str,
    expected_prior_index_sha256: str,
) -> dict[str, str]:
    """Validate one retained extension record without relaxing core rules."""

    if not isinstance(raw, dict) or set(raw) != EXTENSION_RECORD_FIELDS:
        raise ExtensionValidationError("SEC acceptance extension record fields do not match")
    core = _core_record(raw)
    form = str(raw["form"] or "").strip().upper()
    if FORM_PATTERN.fullmatch(form) is None:
        raise ExtensionValidationError("SEC acceptance extension form is invalid")
    entity_name = _normalized_entity_name(raw["entity_name"])
    version = f"v{_extension_number(raw['extension_version'])}"
    if version != expected_version:
        raise ExtensionValidationError("SEC acceptance extension record version differs")
    admitted_at = _normal_timestamp(raw["admitted_at"], "admitted_at")
    if datetime.fromisoformat(core["accepted_at"]) > datetime.fromisoformat(admitted_at):
        raise ExtensionValidationError("SEC acceptance extension timestamp is in the future")
    if raw["admission_decision"] != ADMISSION_DECISION:
        raise ExtensionValidationError("SEC acceptance extension decision is invalid")
    if raw["prior_immutable_index_sha256"] != expected_prior_index_sha256:
        raise ExtensionValidationError("SEC acceptance extension prior-index binding differs")
    unsigned = {
        **core,
        "form": form,
        "entity_name": entity_name,
        "extension_version": version,
        "admitted_at": admitted_at,
        "admission_decision": ADMISSION_DECISION,
        "prior_immutable_index_sha256": expected_prior_index_sha256,
    }
    if raw["extension_record_sha256"] != canonical_sha256(unsigned):
        raise ExtensionValidationError("SEC acceptance extension record hash differs")
    return {**unsigned, "extension_record_sha256": raw["extension_record_sha256"]}


def build_extension_artifact(
    *,
    extension_version: str,
    prior_immutable_index_sha256: str,
    prior_artifacts: list[dict[str, Any]],
    records: list[dict[str, Any]],
    admitted_at: object,
) -> dict[str, Any]:
    """Build one immutable versioned extension artifact in memory."""

    version = f"v{_extension_number(extension_version)}"
    if not _is_sha256(prior_immutable_index_sha256):
        raise ExtensionValidationError("SEC acceptance extension prior-index binding is invalid")
    normalized_admitted_at = _normal_timestamp(admitted_at, "admitted_at")
    if not records:
        raise ExtensionValidationError("SEC acceptance extension artifact has no records")
    normalized_records = [
        validate_extension_record(
            record,
            expected_version=version,
            expected_prior_index_sha256=prior_immutable_index_sha256,
        )
        for record in records
    ]
    if len({record["accession_number"] for record in normalized_records}) != len(
        normalized_records
    ):
        raise ExtensionValidationError("SEC acceptance extension contains duplicate accession")
    unsigned = {
        "schema_version": EXTENSION_SCHEMA_VERSION,
        "extension_version": version,
        "prior_immutable_index_sha256": prior_immutable_index_sha256,
        "prior_extension_set_sha256": extension_set_sha256(prior_artifacts),
        "admitted_at": normalized_admitted_at,
        "records": sorted(
            normalized_records,
            key=lambda record: record["accession_number"],
        ),
        "boundaries": dict(BOUNDARIES),
    }
    return {**unsigned, "artifact_sha256": canonical_sha256(unsigned)}


def validate_extension_artifact(
    raw: Any,
    *,
    expected_version: str,
    expected_prior_index_sha256: str,
    expected_prior_extension_set_sha256: str,
) -> dict[str, Any]:
    """Validate an immutable extension and its chain bindings."""

    if not isinstance(raw, dict) or set(raw) != EXTENSION_ARTIFACT_FIELDS:
        raise ExtensionValidationError("SEC acceptance extension artifact fields do not match")
    version = f"v{_extension_number(raw['extension_version'])}"
    if version != expected_version:
        raise ExtensionValidationError("SEC acceptance extension artifact version differs")
    if raw["schema_version"] != EXTENSION_SCHEMA_VERSION:
        raise ExtensionValidationError("SEC acceptance extension artifact schema differs")
    if raw["boundaries"] != BOUNDARIES:
        raise ExtensionValidationError("SEC acceptance extension boundary differs")
    if raw["prior_immutable_index_sha256"] != expected_prior_index_sha256:
        raise ExtensionValidationError("SEC acceptance extension prior-index binding differs")
    if raw["prior_extension_set_sha256"] != expected_prior_extension_set_sha256:
        raise ExtensionValidationError("SEC acceptance extension chain binding differs")
    admitted_at = _normal_timestamp(raw["admitted_at"], "admitted_at")
    if not isinstance(raw["records"], list) or not raw["records"]:
        raise ExtensionValidationError("SEC acceptance extension records are invalid")
    records = [
        validate_extension_record(
            record,
            expected_version=version,
            expected_prior_index_sha256=expected_prior_index_sha256,
        )
        for record in raw["records"]
    ]
    if any(record["admitted_at"] != admitted_at for record in records):
        raise ExtensionValidationError("SEC acceptance extension admission timestamps differ")
    if len({record["accession_number"] for record in records}) != len(records):
        raise ExtensionValidationError("SEC acceptance extension contains duplicate accession")
    unsigned = {
        "schema_version": EXTENSION_SCHEMA_VERSION,
        "extension_version": version,
        "prior_immutable_index_sha256": expected_prior_index_sha256,
        "prior_extension_set_sha256": expected_prior_extension_set_sha256,
        "admitted_at": admitted_at,
        "records": sorted(records, key=lambda record: record["accession_number"]),
        "boundaries": dict(BOUNDARIES),
    }
    if raw["artifact_sha256"] != canonical_sha256(unsigned):
        raise ExtensionValidationError("SEC acceptance extension artifact hash differs")
    return {**unsigned, "artifact_sha256": raw["artifact_sha256"]}


def load_extension_artifacts(
    *,
    historical_index_sha256: str,
    directory: Path = SEC_ACCEPTANCE_EXTENSION_DIR,
) -> list[dict[str, Any]]:
    """Load every contiguous extension version and verify the full chain."""

    if not _is_sha256(historical_index_sha256):
        raise ExtensionValidationError("SEC acceptance extension historical binding is invalid")
    if not directory.exists():
        return []
    candidates: list[tuple[int, Path]] = []
    for path in directory.glob(f"{EXTENSION_FILE_PREFIX}v*.json"):
        suffix = path.stem.removeprefix(EXTENSION_FILE_PREFIX)
        candidates.append((_extension_number(suffix), path))
    candidates.sort()
    if [number for number, _ in candidates] != list(range(1, len(candidates) + 1)):
        raise ExtensionValidationError("SEC acceptance extension versions are not contiguous")
    artifacts: list[dict[str, Any]] = []
    seen_accessions: set[str] = set()
    for number, path in candidates:
        version = f"v{number}"
        if path != extension_artifact_path(version, directory):
            raise ExtensionValidationError("SEC acceptance extension filename differs")
        try:
            raw = read_json(path)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ExtensionValidationError("SEC acceptance extension artifact is unreadable") from exc
        artifact = validate_extension_artifact(
            raw,
            expected_version=version,
            expected_prior_index_sha256=historical_index_sha256,
            expected_prior_extension_set_sha256=extension_set_sha256(artifacts),
        )
        accessions = {record["accession_number"] for record in artifact["records"]}
        if seen_accessions & accessions:
            raise ExtensionValidationError("SEC acceptance extensions share a duplicate accession")
        seen_accessions.update(accessions)
        artifacts.append(artifact)
    return artifacts


def write_extension_artifact(
    artifact: dict[str, Any],
    *,
    directory: Path = SEC_ACCEPTANCE_EXTENSION_DIR,
) -> Path:
    """Write exactly one new extension version; existing versions never change."""

    version = f"v{_extension_number(artifact.get('extension_version'))}"
    path = extension_artifact_path(version, directory)
    if path.exists():
        raise ExtensionValidationError("SEC acceptance extension version already exists")
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, artifact)
    return path


def extension_acceptance_records(
    artifacts: Iterable[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return core acceptance records for the effective reconciliation set."""

    return [
        {field: record[field] for field in RECORD_FIELDS}
        for artifact in artifacts
        for record in artifact["records"]
    ]


def _audit_row(
    record: dict[str, str],
    artifact: dict[str, Any],
    *,
    artifact_file_sha256: str,
) -> dict[str, str]:
    unsigned = {
        "extension_version": artifact["extension_version"],
        "accession_number": record["accession_number"],
        "ticker": record["ticker"],
        "cik": record["cik"],
        "entity_name": record["entity_name"],
        "form": record["form"],
        "filing_date": record["filing_date"],
        "accepted_at": record["accepted_at"],
        "source_url": record["source_url"],
        "validation_decision": record["admission_decision"],
        "admitted_at": record["admitted_at"],
        "prior_immutable_index_sha256": record["prior_immutable_index_sha256"],
        "extension_artifact_sha256": artifact_file_sha256,
    }
    return {"audit_id": canonical_sha256(unsigned), **unsigned}


def _validate_audit_row(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != set(EXTENSION_AUDIT_FIELDS):
        raise ExtensionValidationError("SEC acceptance extension audit fields do not match")
    accession = str(raw["accession_number"] or "").strip()
    version = f"v{_extension_number(raw['extension_version'])}"
    form = str(raw["form"] or "").strip().upper()
    if FORM_PATTERN.fullmatch(form) is None:
        raise ExtensionValidationError("SEC acceptance extension audit form is invalid")
    entity_name = _normalized_entity_name(raw["entity_name"])
    try:
        core = make_acceptance_record(
            accession_number=accession,
            ticker=raw["ticker"],
            cik=raw["cik"],
            filing_date=raw["filing_date"],
            accepted_at=raw["accepted_at"],
            source_url=raw["source_url"],
        )
    except Exception as exc:
        raise ExtensionValidationError(
            "SEC acceptance extension audit identity is invalid"
        ) from exc
    admitted_at = _normal_timestamp(raw["admitted_at"], "admitted_at")
    if raw["validation_decision"] != ADMISSION_DECISION:
        raise ExtensionValidationError("SEC acceptance extension audit decision is invalid")
    if not _is_sha256(raw["prior_immutable_index_sha256"]) or not _is_sha256(
        raw["extension_artifact_sha256"]
    ):
        raise ExtensionValidationError("SEC acceptance extension audit binding is invalid")
    unsigned = {
        "extension_version": version,
        "accession_number": core["accession_number"],
        "ticker": core["ticker"],
        "cik": core["cik"],
        "entity_name": entity_name,
        "form": form,
        "filing_date": core["filing_date"],
        "accepted_at": core["accepted_at"],
        "source_url": core["source_url"],
        "validation_decision": ADMISSION_DECISION,
        "admitted_at": admitted_at,
        "prior_immutable_index_sha256": raw["prior_immutable_index_sha256"],
        "extension_artifact_sha256": raw["extension_artifact_sha256"],
    }
    if raw["audit_id"] != canonical_sha256(unsigned):
        raise ExtensionValidationError("SEC acceptance extension audit hash differs")
    return {"audit_id": raw["audit_id"], **unsigned}


def load_extension_audit(
    path: Path = SEC_ACCEPTANCE_EXTENSION_AUDIT_PATH,
) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != EXTENSION_AUDIT_FIELDS:
                raise ExtensionValidationError("SEC acceptance extension audit header differs")
            rows = [_validate_audit_row(row) for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ExtensionValidationError("SEC acceptance extension audit is unreadable") from exc
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["audit_id"] in indexed:
            raise ExtensionValidationError("SEC acceptance extension audit contains duplicate identifier")
        indexed[row["audit_id"]] = row
    return indexed


def write_extension_admission_audit(
    artifacts: Iterable[dict[str, Any]],
    *,
    path: Path = SEC_ACCEPTANCE_EXTENSION_AUDIT_PATH,
    directory: Path = SEC_ACCEPTANCE_EXTENSION_DIR,
) -> None:
    """Append any missing artifact-bound admission entries, never rewrites."""

    existing = load_extension_audit(path)
    expected: dict[str, dict[str, str]] = {}
    for artifact in artifacts:
        artifact_path = extension_artifact_path(artifact["extension_version"], directory)
        if not artifact_path.exists():
            raise ExtensionValidationError("SEC acceptance extension artifact is missing")
        artifact_file_sha256 = raw_file_sha256(artifact_path)
        for record in artifact["records"]:
            row = _audit_row(
                record,
                artifact,
                artifact_file_sha256=artifact_file_sha256,
            )
            expected[row["audit_id"]] = row
    if set(existing) - set(expected):
        raise ExtensionValidationError("SEC acceptance extension audit has unknown entry")
    for audit_id, row in expected.items():
        previous = existing.get(audit_id)
        if previous is not None:
            if previous != row:
                raise ExtensionValidationError("SEC acceptance extension audit conflicts")
            continue
        append_csv_durable(path, EXTENSION_AUDIT_FIELDS, row)


def plan_unindexed_current_records(
    *,
    historical_records: list[dict[str, str]],
    extension_artifacts: list[dict[str, Any]],
    current_records: list[dict[str, str]],
    forms_by_accession: dict[str, str],
    expected_cik_by_ticker: dict[str, str],
    expected_entity_by_ticker: dict[str, str],
    permitted_forms: set[str],
    historical_index_sha256: str,
    admitted_at: object,
) -> tuple[list[dict[str, Any]], int]:
    """Build, but do not write, one extension for valid unseen accessions."""

    normalized_admitted_at = _normal_timestamp(admitted_at, "admitted_at")
    if not _is_sha256(historical_index_sha256):
        raise ExtensionValidationError("SEC acceptance extension historical binding is invalid")
    historical_by_accession = {
        record["accession_number"]: validate_acceptance_record(record)
        for record in historical_records
    }
    if len(historical_by_accession) != len(historical_records):
        raise ExtensionValidationError("immutable SEC index contains a duplicate accession")
    extension_records = extension_acceptance_records(extension_artifacts)
    extension_by_accession = {
        record["accession_number"]: validate_acceptance_record(record)
        for record in extension_records
    }
    if len(extension_by_accession) != len(extension_records):
        raise ExtensionValidationError("SEC acceptance extensions share a duplicate accession")

    current_by_accession: dict[str, dict[str, str]] = {}
    unknown: list[dict[str, str]] = []
    for raw in current_records:
        current = validate_acceptance_record(raw)
        accession = current["accession_number"]
        if accession in current_by_accession:
            raise ExtensionValidationError("SEC current response contains duplicate accession")
        current_by_accession[accession] = current
        existing = historical_by_accession.get(accession) or extension_by_accession.get(accession)
        if existing is not None:
            # The timestamp-only reconciliation policy remains responsible for
            # validating a current representation of an already effective row.
            continue
        form = str(forms_by_accession.get(accession, "")).strip().upper()
        if form not in permitted_forms:
            raise ExtensionValidationError("SEC acceptance extension filing form is invalid")
        expected_cik = str(expected_cik_by_ticker.get(current["ticker"], "")).strip()
        if expected_cik != current["cik"]:
            raise ExtensionValidationError("SEC acceptance extension ticker identity conflict")
        entity_name = _normalized_entity_name(
            expected_entity_by_ticker.get(current["ticker"], "")
        )
        if datetime.fromisoformat(current["accepted_at"]) > datetime.fromisoformat(
            normalized_admitted_at
        ):
            raise ExtensionValidationError("SEC acceptance extension timestamp is in the future")
        unknown.append(
            make_extension_record(
                acceptance_record=current,
                form=form,
                entity_name=entity_name,
                extension_version=f"v{len(extension_artifacts) + 1}",
                admitted_at=normalized_admitted_at,
                prior_immutable_index_sha256=historical_index_sha256,
            )
        )
    if not unknown:
        return extension_artifacts, 0
    version = f"v{len(extension_artifacts) + 1}"
    artifact = build_extension_artifact(
        extension_version=version,
        prior_immutable_index_sha256=historical_index_sha256,
        prior_artifacts=extension_artifacts,
        records=unknown,
        admitted_at=normalized_admitted_at,
    )
    return [*extension_artifacts, artifact], len(unknown)


def admit_unindexed_current_records(
    *,
    historical_records: list[dict[str, str]],
    extension_artifacts: list[dict[str, Any]],
    current_records: list[dict[str, str]],
    forms_by_accession: dict[str, str],
    expected_cik_by_ticker: dict[str, str],
    expected_entity_by_ticker: dict[str, str],
    permitted_forms: set[str],
    historical_index_sha256: str,
    admitted_at: object,
    directory: Path = SEC_ACCEPTANCE_EXTENSION_DIR,
) -> tuple[list[dict[str, Any]], int]:
    """Persist a planned extension only after the caller validates the batch."""

    artifacts, count = plan_unindexed_current_records(
        historical_records=historical_records,
        extension_artifacts=extension_artifacts,
        current_records=current_records,
        forms_by_accession=forms_by_accession,
        expected_cik_by_ticker=expected_cik_by_ticker,
        expected_entity_by_ticker=expected_entity_by_ticker,
        permitted_forms=permitted_forms,
        historical_index_sha256=historical_index_sha256,
        admitted_at=admitted_at,
    )
    if count:
        write_extension_artifact(artifacts[-1], directory=directory)
    return artifacts, count
