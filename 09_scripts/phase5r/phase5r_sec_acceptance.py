#!/usr/bin/env python3
"""Validated SEC submission-acceptance timestamps for Phase 5R.

The SEC submissions feed is the authority for ``acceptanceDateTime``.  This
module is offline and dependency-free: it validates and merges records but
never performs a network request.
"""

from __future__ import annotations

import copy
import csv
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from phase5r_daily_common import (
    ROOT,
    append_csv_durable,
    atomic_write_json,
    canonical_sha256,
    read_json,
)


SEC_ACCEPTANCE_INDEX_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_submission_acceptance_index.json"
)
SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_acceptance_time_reconciliation_log.csv"
)
SCHEMA_VERSION = "phase5r_sec_submission_acceptance_index_v1"
ACCESSION_PATTERN = re.compile(r"\d{10}-\d{2}-\d{6}")
TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")
RECORD_FIELDS = {
    "accession_number",
    "ticker",
    "cik",
    "filing_date",
    "accepted_at",
    "source_url",
    "record_sha256",
}
INDEX_FIELDS = {
    "schema_version",
    "generated_at",
    "source_authority",
    "record_count",
    "records",
    "boundaries",
}
BOUNDARIES = {
    "public_sec_only": True,
    "model_used": False,
    "email_used": False,
    "smtp_used": False,
    "broker_used": False,
    "order_code_created": False,
}
RECONCILIATION_FIELDS = [
    "reconciliation_id",
    "reconciled_at",
    "accession_number",
    "original_timestamp",
    "normalized_timestamp",
    "detected_offset_seconds",
    "reconciliation_decision",
]
RECONCILIATION_DECISIONS = {
    "canonical_utc_equivalent",
    "eastern_wall_clock_representation_equivalent",
}
IDENTITY_FIELDS = (
    "accession_number",
    "ticker",
    "cik",
    "filing_date",
    "source_url",
)
EASTERN = ZoneInfo("America/New_York")


class AcceptanceIndexError(ValueError):
    """The SEC acceptance index failed its closed validation contract."""


class AcceptanceReconciliationError(AcceptanceIndexError):
    """A current SEC record cannot be reconciled to the immutable index."""


def normalize_acceptance_timestamp(value: Any) -> str:
    """Return one timezone-aware ISO timestamp or fail closed."""

    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AcceptanceIndexError("SEC acceptance timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AcceptanceIndexError("SEC acceptance timestamp has no timezone")
    return parsed.isoformat(timespec="milliseconds")


def _normalize_generated_at(value: Any) -> str:
    normalized = normalize_acceptance_timestamp(value)
    if not normalized:
        raise AcceptanceIndexError("acceptance index generated_at is missing")
    return normalized


def make_acceptance_record(
    *,
    accession_number: Any,
    ticker: Any,
    cik: Any,
    filing_date: Any,
    accepted_at: Any,
    source_url: Any,
) -> dict[str, str]:
    accession = str(accession_number or "").strip()
    normalized_ticker = str(ticker or "").strip().upper()
    normalized_cik = str(cik or "").strip()
    normalized_filing_date = str(filing_date or "").strip()
    normalized_accepted_at = normalize_acceptance_timestamp(accepted_at)
    normalized_source_url = str(source_url or "").strip()
    if ACCESSION_PATTERN.fullmatch(accession) is None:
        raise AcceptanceIndexError("SEC acceptance record accession is invalid")
    if TICKER_PATTERN.fullmatch(normalized_ticker) is None:
        raise AcceptanceIndexError("SEC acceptance record ticker is invalid")
    if not normalized_cik.isdigit() or int(normalized_cik) <= 0:
        raise AcceptanceIndexError("SEC acceptance record CIK is invalid")
    try:
        filing_day = date.fromisoformat(normalized_filing_date)
    except ValueError as exc:
        raise AcceptanceIndexError("SEC acceptance record filing date is invalid") from exc
    if not normalized_accepted_at:
        raise AcceptanceIndexError("SEC acceptance record timestamp is missing")
    accepted_day = datetime.fromisoformat(normalized_accepted_at).date()
    if abs((accepted_day - filing_day).days) > 7:
        raise AcceptanceIndexError(
            "SEC acceptance timestamp is implausibly far from the filing date"
        )
    expected_url = (
        f"https://data.sec.gov/submissions/CIK{int(normalized_cik):010d}.json"
    )
    if normalized_source_url != expected_url:
        raise AcceptanceIndexError("SEC acceptance source URL is not allowlisted")
    unsigned = {
        "accession_number": accession,
        "ticker": normalized_ticker,
        "cik": str(int(normalized_cik)),
        "filing_date": normalized_filing_date,
        "accepted_at": normalized_accepted_at,
        "source_url": normalized_source_url,
    }
    return {**unsigned, "record_sha256": canonical_sha256(unsigned)}


def validate_acceptance_record(record: Any) -> dict[str, str]:
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        raise AcceptanceIndexError("SEC acceptance record fields do not match")
    rebuilt = make_acceptance_record(
        accession_number=record["accession_number"],
        ticker=record["ticker"],
        cik=record["cik"],
        filing_date=record["filing_date"],
        accepted_at=record["accepted_at"],
        source_url=record["source_url"],
    )
    if rebuilt != record:
        raise AcceptanceIndexError("SEC acceptance record hash or normalization mismatch")
    return rebuilt


def build_acceptance_index(
    *,
    prior_records: Iterable[dict[str, Any]] = (),
    new_records: Iterable[dict[str, Any]] = (),
    generated_at: Any,
) -> dict[str, Any]:
    normalized_generated_at = _normalize_generated_at(generated_at)
    generated_time = datetime.fromisoformat(normalized_generated_at)
    by_accession: dict[str, dict[str, str]] = {}
    for raw in [*prior_records, *new_records]:
        record = validate_acceptance_record(raw)
        if datetime.fromisoformat(record["accepted_at"]) > generated_time:
            raise AcceptanceIndexError(
                "SEC acceptance record is later than index generation time"
            )
        accession = record["accession_number"]
        existing = by_accession.get(accession)
        if existing is not None and existing != record:
            raise AcceptanceIndexError(
                "conflicting SEC acceptance records share one accession"
            )
        by_accession[accession] = record
    records = sorted(
        by_accession.values(),
        key=lambda row: (
            row["ticker"],
            row["accepted_at"],
            row["accession_number"],
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": normalized_generated_at,
        "source_authority": "SEC submissions acceptanceDateTime",
        "record_count": len(records),
        "records": records,
        "boundaries": copy.deepcopy(BOUNDARIES),
    }


def validate_acceptance_index(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != INDEX_FIELDS:
        raise AcceptanceIndexError("SEC acceptance index fields do not match")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise AcceptanceIndexError("SEC acceptance index schema mismatch")
    if payload["source_authority"] != "SEC submissions acceptanceDateTime":
        raise AcceptanceIndexError("SEC acceptance index authority mismatch")
    if payload["boundaries"] != BOUNDARIES:
        raise AcceptanceIndexError("SEC acceptance index boundary mismatch")
    if not isinstance(payload["records"], list):
        raise AcceptanceIndexError("SEC acceptance index records are not a list")
    rebuilt = build_acceptance_index(
        new_records=payload["records"],
        generated_at=payload["generated_at"],
    )
    if rebuilt != payload or payload["record_count"] != len(payload["records"]):
        raise AcceptanceIndexError("SEC acceptance index content mismatch")
    return rebuilt


def load_acceptance_index(
    path: Path = SEC_ACCEPTANCE_INDEX_PATH,
) -> dict[str, Any]:
    if not path.exists():
        return build_acceptance_index(generated_at=datetime.now().astimezone())
    return validate_acceptance_index(read_json(path))


def load_immutable_acceptance_index(
    path: Path = SEC_ACCEPTANCE_INDEX_PATH,
) -> dict[str, Any]:
    """Load the historical index only when the retained artifact exists.

    The timestamp-reconciliation policy may compare against an existing index,
    but it may not bootstrap, replace, or infer one when that artifact is
    missing.
    """

    if not path.exists():
        raise AcceptanceReconciliationError("immutable SEC acceptance index is missing")
    return load_acceptance_index(path)


def acceptance_map(
    path: Path = SEC_ACCEPTANCE_INDEX_PATH,
) -> dict[str, dict[str, str]]:
    payload = load_acceptance_index(path)
    return {
        record["accession_number"]: record
        for record in payload["records"]
    }


def write_acceptance_index(
    payload: dict[str, Any],
    path: Path = SEC_ACCEPTANCE_INDEX_PATH,
) -> None:
    atomic_write_json(path, validate_acceptance_index(payload))


def _reconciliation_id(
    *,
    accession_number: str,
    original_timestamp: str,
    normalized_timestamp: str,
    detected_offset_seconds: int,
    reconciliation_decision: str,
) -> str:
    """Return a stable identifier for one timestamp-only reconciliation."""

    return canonical_sha256(
        {
            "accession_number": accession_number,
            "original_timestamp": original_timestamp,
            "normalized_timestamp": normalized_timestamp,
            "detected_offset_seconds": detected_offset_seconds,
            "reconciliation_decision": reconciliation_decision,
        }
    )


def _make_reconciliation_row(
    *,
    historical: dict[str, str],
    current: dict[str, str],
    reconciled_at: str,
    decision: str,
) -> dict[str, str]:
    if decision not in RECONCILIATION_DECISIONS:
        raise AcceptanceReconciliationError("SEC reconciliation decision is invalid")
    original_time = datetime.fromisoformat(historical["accepted_at"])
    normalized_time = datetime.fromisoformat(current["accepted_at"])
    offset_seconds = int((normalized_time - original_time).total_seconds())
    return {
        "reconciliation_id": _reconciliation_id(
            accession_number=historical["accession_number"],
            original_timestamp=historical["accepted_at"],
            normalized_timestamp=current["accepted_at"],
            detected_offset_seconds=offset_seconds,
            reconciliation_decision=decision,
        ),
        "reconciled_at": reconciled_at,
        "accession_number": historical["accession_number"],
        "original_timestamp": historical["accepted_at"],
        "normalized_timestamp": current["accepted_at"],
        "detected_offset_seconds": str(offset_seconds),
        "reconciliation_decision": decision,
    }


def _validate_reconciliation_row(row: Any) -> dict[str, str]:
    """Validate one durable log row without mutating it."""

    if not isinstance(row, dict) or set(row) != set(RECONCILIATION_FIELDS):
        raise AcceptanceReconciliationError("SEC reconciliation log fields do not match")
    accession = str(row["accession_number"] or "").strip()
    if ACCESSION_PATTERN.fullmatch(accession) is None:
        raise AcceptanceReconciliationError("SEC reconciliation accession is invalid")
    original = normalize_acceptance_timestamp(row["original_timestamp"])
    normalized = normalize_acceptance_timestamp(row["normalized_timestamp"])
    reconciled_at = _normalize_generated_at(row["reconciled_at"])
    decision = str(row["reconciliation_decision"] or "").strip()
    if decision not in RECONCILIATION_DECISIONS:
        raise AcceptanceReconciliationError("SEC reconciliation decision is invalid")
    try:
        detected_offset_seconds = int(str(row["detected_offset_seconds"]).strip())
    except (TypeError, ValueError) as exc:
        raise AcceptanceReconciliationError("SEC reconciliation offset is invalid") from exc
    if detected_offset_seconds != int(
        (
            datetime.fromisoformat(normalized) - datetime.fromisoformat(original)
        ).total_seconds()
    ):
        raise AcceptanceReconciliationError("SEC reconciliation offset does not match timestamps")
    expected_id = _reconciliation_id(
        accession_number=accession,
        original_timestamp=original,
        normalized_timestamp=normalized,
        detected_offset_seconds=detected_offset_seconds,
        reconciliation_decision=decision,
    )
    if str(row["reconciliation_id"] or "").strip() != expected_id:
        raise AcceptanceReconciliationError("SEC reconciliation identifier mismatch")
    return {
        "reconciliation_id": expected_id,
        "reconciled_at": reconciled_at,
        "accession_number": accession,
        "original_timestamp": original,
        "normalized_timestamp": normalized,
        "detected_offset_seconds": str(detected_offset_seconds),
        "reconciliation_decision": decision,
    }


def _reconciliation_identity(row: dict[str, str]) -> tuple[str, ...]:
    """Fields that must remain fixed across an idempotent log retry."""

    return tuple(
        row[field]
        for field in (
            "reconciliation_id",
            "accession_number",
            "original_timestamp",
            "normalized_timestamp",
            "detected_offset_seconds",
            "reconciliation_decision",
        )
    )


def load_acceptance_reconciliation_log(
    path: Path = SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH,
) -> dict[str, dict[str, str]]:
    """Load the append-only reconciliation log or fail closed on corruption."""

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RECONCILIATION_FIELDS:
            raise AcceptanceReconciliationError("SEC reconciliation log header mismatch")
        rows = [_validate_reconciliation_row(row) for row in reader]
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        reconciliation_id = row["reconciliation_id"]
        if reconciliation_id in by_id:
            raise AcceptanceReconciliationError("SEC reconciliation log contains a duplicate identifier")
        by_id[reconciliation_id] = row
    return by_id


def write_acceptance_reconciliation_log(
    rows: Iterable[dict[str, Any]],
    path: Path = SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH,
) -> None:
    """Append only newly observed, validated timestamp reconciliations.

    The historical acceptance index is deliberately never read for write here.
    Re-running the same current SEC response is idempotent: its first durable
    audit timestamp is retained and no duplicate row is added.
    """

    existing = load_acceptance_reconciliation_log(path)
    candidates = [_validate_reconciliation_row(row) for row in rows]
    candidate_ids: set[str] = set()
    to_append: list[dict[str, str]] = []
    for row in candidates:
        reconciliation_id = row["reconciliation_id"]
        if reconciliation_id in candidate_ids:
            raise AcceptanceReconciliationError("SEC reconciliation input has a duplicate identifier")
        candidate_ids.add(reconciliation_id)
        prior = existing.get(reconciliation_id)
        if prior is not None:
            if _reconciliation_identity(prior) != _reconciliation_identity(row):
                raise AcceptanceReconciliationError("SEC reconciliation log conflicts with current input")
            continue
        to_append.append(row)
        existing[reconciliation_id] = row
    for row in to_append:
        append_csv_durable(path, RECONCILIATION_FIELDS, row)


def _same_eastern_wall_clock_representation(
    original: datetime,
    current: datetime,
) -> bool:
    """Recognize only the documented UTC-versus-US-Eastern representation shift.

    Historical records were persisted as an absolute UTC timestamp. Some
    current SEC responses represent the same US-Eastern wall-clock value as a
    UTC timestamp. This is accepted only when both the wall-clock components
    and the date-specific Eastern UTC offset prove that exact transformation.
    No tolerance window, rounding, or arbitrary offset is permitted.
    """

    original_eastern = original.astimezone(EASTERN)
    current_utc = current.astimezone(timezone.utc)
    original_to_current = (
        original_eastern.replace(tzinfo=None) == current_utc.replace(tzinfo=None)
        and original_eastern.utcoffset() is not None
        and int((current - original).total_seconds())
        == int(original_eastern.utcoffset().total_seconds())
    )
    # The SEC can later correct a previously served Eastern wall-clock value
    # that had been labelled UTC. Accept the exact inverse transformation too:
    # current absolute UTC -> its date-specific Eastern wall clock -> the
    # historical UTC-labelled wall clock. Identity fields remain exact.
    current_eastern = current.astimezone(EASTERN)
    original_utc = original.astimezone(timezone.utc)
    current_to_original = (
        current_eastern.replace(tzinfo=None) == original_utc.replace(tzinfo=None)
        and current_eastern.utcoffset() is not None
        and int((current - original).total_seconds())
        == -int(current_eastern.utcoffset().total_seconds())
    )
    return original_to_current or current_to_original


def reconcile_current_acceptance_records(
    *,
    historical_records: Iterable[dict[str, Any]],
    current_records: Iterable[dict[str, Any]],
    reconciled_at: Any,
) -> list[dict[str, str]]:
    """Compare current official SEC records to the immutable acceptance index.

    Accession and non-time identity fields must be exactly identical. A time
    difference is accepted only for a canonical UTC-equivalent representation
    or the documented date-specific US-Eastern wall-clock representation. All
    other changes fail closed and no historical artifact is modified.
    """

    normalized_reconciled_at = _normalize_generated_at(reconciled_at)
    reconciliation_time = datetime.fromisoformat(normalized_reconciled_at)
    historical_by_accession: dict[str, dict[str, str]] = {}
    for raw in historical_records:
        record = validate_acceptance_record(raw)
        accession = record["accession_number"]
        if accession in historical_by_accession:
            raise AcceptanceReconciliationError("immutable SEC index contains a duplicate accession")
        historical_by_accession[accession] = record

    current_by_accession: dict[str, dict[str, str]] = {}
    for raw in current_records:
        record = validate_acceptance_record(raw)
        if datetime.fromisoformat(record["accepted_at"]) > reconciliation_time:
            raise AcceptanceReconciliationError("current SEC acceptance timestamp is later than reconciliation time")
        accession = record["accession_number"]
        if accession in current_by_accession:
            raise AcceptanceReconciliationError("current SEC response contains a duplicate accession")
        current_by_accession[accession] = record

    rows: list[dict[str, str]] = []
    for accession, current in sorted(current_by_accession.items()):
        historical = historical_by_accession.get(accession)
        if historical is None:
            raise AcceptanceReconciliationError(
                "current SEC acceptance accession is absent from immutable index"
            )
        if any(historical[field] != current[field] for field in IDENTITY_FIELDS):
            raise AcceptanceReconciliationError(
                "SEC acceptance identity fields differ for existing accession"
            )
        if historical == current:
            continue

        original_time = datetime.fromisoformat(historical["accepted_at"])
        current_time = datetime.fromisoformat(current["accepted_at"])
        if original_time.astimezone(timezone.utc) == current_time.astimezone(timezone.utc):
            decision = "canonical_utc_equivalent"
        elif _same_eastern_wall_clock_representation(original_time, current_time):
            decision = "eastern_wall_clock_representation_equivalent"
        else:
            raise AcceptanceReconciliationError(
                "SEC acceptance timestamp is not a permitted representation difference"
            )
        rows.append(
            _make_reconciliation_row(
                historical=historical,
                current=current,
                reconciled_at=normalized_reconciled_at,
                decision=decision,
            )
        )
    return rows
