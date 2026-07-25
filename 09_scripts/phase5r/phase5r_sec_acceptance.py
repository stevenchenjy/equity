#!/usr/bin/env python3
"""Validated SEC submission-acceptance timestamps for Phase 5R.

The SEC submissions feed is the authority for ``acceptanceDateTime``.  This
module is offline and dependency-free: it validates and merges records but
never performs a network request.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from phase5r_daily_common import ROOT, atomic_write_json, canonical_sha256, read_json


SEC_ACCEPTANCE_INDEX_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_submission_acceptance_index.json"
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


class AcceptanceIndexError(ValueError):
    """The SEC acceptance index failed its closed validation contract."""


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
