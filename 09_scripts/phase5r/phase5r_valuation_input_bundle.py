#!/usr/bin/env python3
"""Validate and import local, provenance-bound valuation inputs.

This module is offline and fail closed. It accepts only a sealed local bundle
whose source excerpts can be re-read and re-hashed inside approved current
project directories. It never fetches data, reads credentials, sends email,
connects to a broker, creates an order, or grants execution authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from phase5r_daily_common import ROOT
from phase5r_valuation_evidence_v1 import (
    INPUT_SPECS,
    ValuationEvidenceError,
    build_valuation_evidence_v1,
    valuation_packet_calculations,
)


SCHEMA_VERSION = "phase5r_valuation_input_bundle_v1"
DEFAULT_BUNDLE_PATH = (
    ROOT / "04_data" / "phase5r" / "phase5r_valuation_inputs.local.json"
)

_TOP_FIELDS = {
    "schema_version",
    "prepared_at_utc",
    "records",
    "boundaries",
    "bundle_sha256",
}
_RECORD_FIELDS = {"ticker", "inputs", "sources"}
_INPUT_FIELDS = {
    "value",
    "unit",
    "period",
    "available_at_utc",
    "source_ids",
    "evidence_kind",
}
_SOURCE_FIELDS = {
    "source_id",
    "ticker",
    "source_type",
    "accepted_at_utc",
    "source_url",
    "relative_path",
    "char_start",
    "char_end",
    "content_sha256",
    "field",
    "authority",
}
_BOUNDARY_FIELDS = {
    "research_only",
    "canonical_effect",
    "email_eligible",
    "automatic_action_allowed",
    "broker_connected",
    "broker_account_read",
    "order_code_created",
    "trade_placed",
    "network_used",
    "credentials_read",
    "smtp_config_read",
}
_FALSE_BOUNDARIES = _BOUNDARY_FIELDS - {"research_only"}
_SOURCE_POLICIES = {
    "sec_valuation_fact": (
        "primary_official",
        ("02_filings/phase5r_daily", "03_source_data/phase5r"),
    ),
    "public_market_valuation_observation": (
        "secondary_public_market_context",
        ("03_source_data/phase5r",),
    ),
    "human_valuation_scenario": (
        "human_research_scenario",
        ("04_data/phase5r",),
    ),
    "deterministic_valuation_policy": (
        "deterministic_policy",
        ("01_policies",),
    ),
}
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"password|secret|credential|smtp[_ -]?password|broker[_ -]?token)"
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_LOCAL_PATH = re.compile(r"(?i)(?:file://|/Users/[^/\s]+/|[A-Z]:\\Users\\)")


class ValuationInputBundleError(ValueError):
    """Raised when a local valuation bundle is unsafe or inconsistent."""


def _canonical_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValuationInputBundleError(
            "bundle contains a non-canonical JSON value"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValuationInputBundleError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValuationInputBundleError(
                    f"non-finite JSON constant is forbidden: {value}"
                )
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValuationInputBundleError(f"cannot read bundle: {path}") from exc
    if not isinstance(value, dict):
        raise ValuationInputBundleError("bundle must be an object")
    return value


def _require_exact_fields(
    value: Any,
    expected: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        missing = sorted(expected - set(value)) if isinstance(value, dict) else []
        extra = sorted(set(value) - expected) if isinstance(value, dict) else []
        raise ValuationInputBundleError(
            f"{label}: field mismatch; missing={missing}; extra={extra}"
        )
    return value


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValuationInputBundleError(f"{label}: UTC timestamp required")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ValuationInputBundleError(
            f"{label}: invalid ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValuationInputBundleError(f"{label}: timestamp must use UTC")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _packet_as_of(value: str) -> tuple[datetime, str]:
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError) as exc:
        raise ValuationInputBundleError(
            "packet as-of must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ValuationInputBundleError("packet as-of requires a timezone")
    parsed_utc = parsed.astimezone(timezone.utc)
    return parsed_utc, _utc_text(parsed_utc)


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _verified_source(
    raw: Any,
    *,
    ticker: str,
    packet_as_of: datetime,
    project_root: Path,
) -> tuple[dict[str, Any], str]:
    source = _require_exact_fields(raw, _SOURCE_FIELDS, "source")
    source_ticker = str(source["ticker"]).strip().upper()
    if source_ticker != ticker:
        raise ValuationInputBundleError("source: ticker mismatch")
    source_id = str(source["source_id"]).strip()
    if not source_id:
        raise ValuationInputBundleError("source: source_id is required")
    source_type = str(source["source_type"])
    if source_type not in _SOURCE_POLICIES:
        raise ValuationInputBundleError("source: unsupported source_type")
    expected_authority, allowed_relative_roots = _SOURCE_POLICIES[source_type]
    if source["authority"] != expected_authority:
        raise ValuationInputBundleError("source: authority mismatch")
    accepted_at = _parse_utc(source["accepted_at_utc"], "source.accepted_at_utc")
    if accepted_at > packet_as_of:
        raise ValuationInputBundleError("source: future evidence is forbidden")

    source_url = str(source["source_url"])
    if source_url and not source_url.startswith("https://"):
        raise ValuationInputBundleError("source: URL must use HTTPS")
    if source_type == "sec_valuation_fact" and not (
        source_url.startswith("https://www.sec.gov/")
        or source_url.startswith("https://data.sec.gov/")
    ):
        raise ValuationInputBundleError("source: SEC source URL is required")

    relative_path = str(source["relative_path"])
    candidate_input = Path(relative_path)
    if not relative_path or candidate_input.is_absolute() or ".." in candidate_input.parts:
        raise ValuationInputBundleError("source: unsafe relative_path")
    if "11_archive" in candidate_input.parts:
        raise ValuationInputBundleError("source: archived evidence is forbidden")
    candidate = (project_root / candidate_input).resolve()
    allowed_roots = [
        (project_root / relative_root).resolve()
        for relative_root in allowed_relative_roots
    ]
    if not any(_is_within(candidate, allowed_root) for allowed_root in allowed_roots):
        raise ValuationInputBundleError(
            "source: path is outside the allowed current-data root"
        )
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValuationInputBundleError(
            f"source: cannot read {relative_path}"
        ) from exc
    char_start = source["char_start"]
    char_end = source["char_end"]
    if (
        not isinstance(char_start, int)
        or isinstance(char_start, bool)
        or not isinstance(char_end, int)
        or isinstance(char_end, bool)
        or char_start < 0
        or char_end <= char_start
        or char_end > len(text)
    ):
        raise ValuationInputBundleError("source: invalid character range")
    excerpt = text[char_start:char_end]
    digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
    if source["content_sha256"] != digest or _HEX_64.fullmatch(digest) is None:
        raise ValuationInputBundleError("source: excerpt hash mismatch")
    if _SENSITIVE_TEXT.search(excerpt) or _EMAIL.search(excerpt) or _LOCAL_PATH.search(
        excerpt
    ):
        raise ValuationInputBundleError(
            "source: excerpt contains sensitive or local-identity text"
        )
    field = str(source["field"]).strip()
    if not field:
        raise ValuationInputBundleError("source: field locator is required")
    packet_source = {
        "source_id": source_id,
        "source_type": source_type,
        "ticker": ticker,
        "accepted_at": _utc_text(accepted_at),
        "source_url": source_url,
        "content_sha256": digest,
        "locator": {
            "relative_path": relative_path,
            "char_start": char_start,
            "char_end": char_end,
            "field": field,
        },
        "authority": expected_authority,
        "excerpt_text": excerpt,
    }
    return packet_source, source_id


def _unsigned_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": bundle.get("schema_version"),
        "prepared_at_utc": bundle.get("prepared_at_utc"),
        "records": bundle.get("records"),
        "boundaries": bundle.get("boundaries"),
    }


def seal_bundle(bundle: Any) -> dict[str, Any]:
    """Return a copy with a deterministic top-level bundle digest."""

    checked = _require_exact_fields(bundle, _TOP_FIELDS, "bundle")
    sealed = copy.deepcopy(checked)
    sealed["bundle_sha256"] = _canonical_sha256(_unsigned_bundle(sealed))
    return sealed


def _declared_tickers(bundle: Mapping[str, Any]) -> set[str]:
    records = bundle.get("records", [])
    if not isinstance(records, list):
        return set()
    return {
        str(record.get("ticker", "")).strip().upper()
        for record in records
        if isinstance(record, dict) and str(record.get("ticker", "")).strip()
    }


def validate_and_materialize_bundle(
    bundle: Any,
    *,
    packet_as_of: str,
    active_tickers: set[str],
    project_root: Path = ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate a sealed bundle and build valuation receipts plus packet sources."""

    checked = _require_exact_fields(bundle, _TOP_FIELDS, "bundle")
    if checked["schema_version"] != SCHEMA_VERSION:
        raise ValuationInputBundleError("bundle: unsupported schema_version")
    packet_time, packet_time_utc = _packet_as_of(packet_as_of)
    prepared_at = _parse_utc(checked["prepared_at_utc"], "bundle.prepared_at_utc")
    if prepared_at > packet_time:
        raise ValuationInputBundleError("bundle: future preparation is forbidden")
    expected_digest = _canonical_sha256(_unsigned_bundle(checked))
    if (
        not isinstance(checked["bundle_sha256"], str)
        or _HEX_64.fullmatch(checked["bundle_sha256"]) is None
        or checked["bundle_sha256"] != expected_digest
    ):
        raise ValuationInputBundleError("bundle: digest mismatch")

    boundaries = _require_exact_fields(
        checked["boundaries"],
        _BOUNDARY_FIELDS,
        "bundle.boundaries",
    )
    if boundaries["research_only"] is not True:
        raise ValuationInputBundleError("bundle: research_only must be true")
    for field in _FALSE_BOUNDARIES:
        if boundaries[field] is not False:
            raise ValuationInputBundleError(f"bundle: {field} must remain false")

    records = checked["records"]
    if not isinstance(records, list):
        raise ValuationInputBundleError("bundle.records must be an array")
    normalized_active = {str(ticker).strip().upper() for ticker in active_tickers}
    seen_tickers: set[str] = set()
    all_source_ids: set[str] = set()
    receipts: list[dict[str, Any]] = []
    packet_sources: list[dict[str, Any]] = []
    for index, raw_record in enumerate(records):
        record = _require_exact_fields(
            raw_record,
            _RECORD_FIELDS,
            f"bundle.records[{index}]",
        )
        ticker = str(record["ticker"]).strip().upper()
        if _TICKER.fullmatch(ticker) is None:
            raise ValuationInputBundleError("record: invalid ticker")
        if ticker in seen_tickers:
            raise ValuationInputBundleError("record: duplicate ticker")
        seen_tickers.add(ticker)

        raw_sources = record["sources"]
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValuationInputBundleError("record: sources must be non-empty")
        record_source_ids: set[str] = set()
        record_sources: list[dict[str, Any]] = []
        for raw_source in raw_sources:
            packet_source, source_id = _verified_source(
                raw_source,
                ticker=ticker,
                packet_as_of=packet_time,
                project_root=project_root,
            )
            if source_id in all_source_ids:
                raise ValuationInputBundleError("source: duplicate source_id")
            all_source_ids.add(source_id)
            record_source_ids.add(source_id)
            record_sources.append(packet_source)

        inputs = record["inputs"]
        if not isinstance(inputs, dict):
            raise ValuationInputBundleError("record.inputs must be an object")
        unknown_inputs = set(inputs) - set(INPUT_SPECS)
        if unknown_inputs:
            raise ValuationInputBundleError(
                f"record: unknown valuation inputs {sorted(unknown_inputs)}"
            )
        for input_id, raw_input in inputs.items():
            _require_exact_fields(
                raw_input,
                _INPUT_FIELDS,
                f"record.inputs.{input_id}",
            )
            source_ids = raw_input.get("source_ids")
            if not isinstance(source_ids, list) or not source_ids:
                raise ValuationInputBundleError(
                    f"record.inputs.{input_id}: source_ids required"
                )
            unknown_source_ids = sorted(set(source_ids) - record_source_ids)
            if unknown_source_ids:
                raise ValuationInputBundleError(
                    f"record.inputs.{input_id}: undeclared sources "
                    + ",".join(unknown_source_ids)
                )
        try:
            receipt = build_valuation_evidence_v1(
                ticker=ticker,
                as_of_utc=packet_time_utc,
                inputs=inputs,
            )
        except ValuationEvidenceError as exc:
            raise ValuationInputBundleError(
                f"record {ticker}: valuation evidence is invalid"
            ) from exc
        if ticker in normalized_active:
            receipts.append(receipt)
            packet_sources.extend(record_sources)

    return sorted(receipts, key=lambda row: row["ticker"]), sorted(
        packet_sources,
        key=lambda row: row["source_id"],
    )


def load_valuation_input_bundle(
    *,
    path: Path = DEFAULT_BUNDLE_PATH,
    packet_as_of: str,
    active_tickers: set[str],
    project_root: Path = ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load a local bundle, returning an empty result only when it is absent."""

    if not path.exists():
        return [], []
    return validate_and_materialize_bundle(
        _read_json(path),
        packet_as_of=packet_as_of,
        active_tickers=active_tickers,
        project_root=project_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--seal", action="store_true")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--ticker", action="append", default=[])
    args = parser.parse_args()
    raw = _read_json(args.input)
    if args.seal:
        sealed = seal_bundle(raw)
        validate_and_materialize_bundle(
            sealed,
            packet_as_of=args.as_of,
            active_tickers=_declared_tickers(sealed),
        )
        output = args.output or args.input
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_text(
            json.dumps(
                sealed,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
        print(
            f"bundle_sealed=true output={output} "
            f"bundle_sha256={sealed['bundle_sha256']} network_used=false"
        )
        return 0
    selected_tickers = {
        ticker.upper() for ticker in args.ticker
    } or _declared_tickers(raw)
    receipts, sources = validate_and_materialize_bundle(
        raw,
        packet_as_of=args.as_of,
        active_tickers=selected_tickers,
    )
    calculations = sum(
        (valuation_packet_calculations(receipt) for receipt in receipts),
        [],
    )
    print(
        f"bundle_valid=true active_receipts={len(receipts)} "
        f"sources={len(sources)} calculations={len(calculations)} "
        "network_used=false credentials_read=false email_attempted=false "
        "broker_connected=false order_code_created=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BUNDLE_PATH",
    "SCHEMA_VERSION",
    "ValuationInputBundleError",
    "load_valuation_input_bundle",
    "seal_bundle",
    "validate_and_materialize_bundle",
]
