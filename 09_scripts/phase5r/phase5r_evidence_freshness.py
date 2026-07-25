#!/usr/bin/env python3
"""Deterministic, ticker-scoped freshness receipts for Phase 5R evidence.

The module is pure and offline.  It does not fetch data or decide whether a
research thesis is correct.  It records whether a ticker received a complete,
current SEC scan and whether the market and valuation inputs needed for an
action review are current.  Durable SEC thesis evidence is intentionally not
expired merely because the underlying filing is old.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = "phase5r_evidence_freshness_v1"
SEC_SCAN_MAX_AGE_SECONDS = 48 * 60 * 60
VALUATION_SCENARIO_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SEC_SCAN_KEYS = {
    "status_artifact_sha256",
    "completed_through_utc",
    "ticker_scanned",
    "complete",
}
_MARKET_KEYS = {
    "observed_at_utc",
    "market_session_date",
    "expected_market_session_date",
    "complete_close",
}
_VALUATION_KEYS = {
    "valuation_receipt_sha256",
    "receipt_as_of_utc",
    "market_input_at_utc",
    "market_session_date",
    "expected_market_session_date",
    "scenario_refreshed_at_utc",
    "complete",
}


class EvidenceFreshnessError(ValueError):
    """Raised when a freshness receipt is malformed or not point-in-time safe."""


def _payload_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_ticker(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceFreshnessError("ticker must be non-empty")
    ticker = value.strip().upper()
    if not ticker.replace(".", "").replace("-", "").isalnum():
        raise EvidenceFreshnessError("ticker contains unsupported characters")
    return ticker


def _parse_utc(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceFreshnessError(f"{label} must be a non-empty UTC timestamp")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(
            raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        )
    except ValueError as exc:
        raise EvidenceFreshnessError(
            f"{label} is not an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise EvidenceFreshnessError(f"{label} must use UTC")
    return parsed.astimezone(timezone.utc)


def _optional_utc(
    value: Any,
    *,
    label: str,
    as_of: datetime,
) -> tuple[str, datetime | None]:
    if value == "":
        return "", None
    parsed = _parse_utc(value, label=label)
    if parsed > as_of:
        raise EvidenceFreshnessError(f"{label} is later than the receipt as-of")
    return _utc_string(parsed), parsed


def _utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_mapping(
    value: Any,
    *,
    label: str,
    keys: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceFreshnessError(f"{label} must be an object")
    missing = sorted(keys - set(value))
    extras = sorted(set(value) - keys)
    if missing or extras:
        raise EvidenceFreshnessError(
            f"{label} keys mismatch; missing={missing}, unknown={extras}"
        )
    return value


def _normalize_digest(value: Any, *, label: str) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise EvidenceFreshnessError(f"{label} must be empty or a lowercase sha256")
    return value


def _normalize_date(value: Any, *, label: str) -> str:
    if value == "":
        return ""
    if not isinstance(value, str):
        raise EvidenceFreshnessError(f"{label} must be a date string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise EvidenceFreshnessError(f"{label} must use YYYY-MM-DD") from exc
    return parsed.strftime("%Y-%m-%d")


def _normalize_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceFreshnessError(f"{label} must be boolean")
    return value


def _normalize_source_ids(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise EvidenceFreshnessError("durable_sec_source_ids must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise EvidenceFreshnessError(
            "durable_sec_source_ids must contain non-empty strings"
        )
    normalized = sorted(item.strip() for item in value)
    if len(normalized) != len(set(normalized)):
        raise EvidenceFreshnessError("durable_sec_source_ids must be unique")
    return normalized


def build_evidence_freshness_receipt(
    *,
    ticker: str,
    as_of_utc: str,
    sec_scan: Mapping[str, Any],
    market: Mapping[str, Any],
    valuation: Mapping[str, Any],
    durable_sec_source_ids: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Build a closed, deterministic freshness receipt from local observations."""

    normalized_ticker = _normalize_ticker(ticker)
    as_of = _parse_utc(as_of_utc, label="as_of_utc")
    normalized_as_of = _utc_string(as_of)

    sec_scan = _require_mapping(
        sec_scan,
        label="sec_scan",
        keys=_SEC_SCAN_KEYS,
    )
    sec_artifact_digest = _normalize_digest(
        sec_scan["status_artifact_sha256"],
        label="sec_scan.status_artifact_sha256",
    )
    sec_completed_text, sec_completed = _optional_utc(
        sec_scan["completed_through_utc"],
        label="sec_scan.completed_through_utc",
        as_of=as_of,
    )
    sec_ticker_scanned = _normalize_bool(
        sec_scan["ticker_scanned"],
        label="sec_scan.ticker_scanned",
    )
    sec_complete = _normalize_bool(
        sec_scan["complete"],
        label="sec_scan.complete",
    )
    sec_age_seconds = (
        int((as_of - sec_completed).total_seconds())
        if sec_completed is not None
        else None
    )
    sec_reasons: list[str] = []
    if not sec_artifact_digest:
        sec_reasons.append("sec_scan_status_artifact_missing")
    if sec_completed is None:
        sec_reasons.append("sec_scan_watermark_missing")
    elif sec_age_seconds is not None and sec_age_seconds > SEC_SCAN_MAX_AGE_SECONDS:
        sec_reasons.append("sec_scan_watermark_expired")
    if not sec_ticker_scanned:
        sec_reasons.append("sec_scan_ticker_not_scanned")
    if not sec_complete:
        sec_reasons.append("sec_scan_incomplete")
    normalized_sec_scan = {
        "status_artifact_sha256": sec_artifact_digest,
        "completed_through_utc": sec_completed_text,
        "ticker_scanned": sec_ticker_scanned,
        "complete": sec_complete,
        "max_age_seconds": SEC_SCAN_MAX_AGE_SECONDS,
        "age_seconds": sec_age_seconds,
        "current": not sec_reasons,
        "blocked_reasons": sec_reasons,
    }

    market = _require_mapping(
        market,
        label="market",
        keys=_MARKET_KEYS,
    )
    market_observed_text, market_observed = _optional_utc(
        market["observed_at_utc"],
        label="market.observed_at_utc",
        as_of=as_of,
    )
    market_session_date = _normalize_date(
        market["market_session_date"],
        label="market.market_session_date",
    )
    expected_market_session_date = _normalize_date(
        market["expected_market_session_date"],
        label="market.expected_market_session_date",
    )
    market_complete_close = _normalize_bool(
        market["complete_close"],
        label="market.complete_close",
    )
    market_reasons: list[str] = []
    if market_observed is None:
        market_reasons.append("market_observation_missing")
    if not market_session_date:
        market_reasons.append("market_session_missing")
    if not expected_market_session_date:
        market_reasons.append("expected_market_session_missing")
    elif (
        market_session_date
        and market_session_date != expected_market_session_date
    ):
        market_reasons.append("market_session_expired")
    if not market_complete_close:
        market_reasons.append("market_close_incomplete")
    normalized_market = {
        "observed_at_utc": market_observed_text,
        "market_session_date": market_session_date,
        "expected_market_session_date": expected_market_session_date,
        "complete_close": market_complete_close,
        "current": not market_reasons,
        "blocked_reasons": market_reasons,
    }

    valuation = _require_mapping(
        valuation,
        label="valuation",
        keys=_VALUATION_KEYS,
    )
    valuation_digest = _normalize_digest(
        valuation["valuation_receipt_sha256"],
        label="valuation.valuation_receipt_sha256",
    )
    valuation_as_of_text, valuation_as_of = _optional_utc(
        valuation["receipt_as_of_utc"],
        label="valuation.receipt_as_of_utc",
        as_of=as_of,
    )
    valuation_market_text, valuation_market_at = _optional_utc(
        valuation["market_input_at_utc"],
        label="valuation.market_input_at_utc",
        as_of=as_of,
    )
    valuation_market_session = _normalize_date(
        valuation["market_session_date"],
        label="valuation.market_session_date",
    )
    valuation_expected_session = _normalize_date(
        valuation["expected_market_session_date"],
        label="valuation.expected_market_session_date",
    )
    scenario_text, scenario_at = _optional_utc(
        valuation["scenario_refreshed_at_utc"],
        label="valuation.scenario_refreshed_at_utc",
        as_of=as_of,
    )
    valuation_complete = _normalize_bool(
        valuation["complete"],
        label="valuation.complete",
    )
    scenario_age_seconds = (
        int((as_of - scenario_at).total_seconds())
        if scenario_at is not None
        else None
    )
    valuation_reasons: list[str] = []
    if not valuation_digest:
        valuation_reasons.append("valuation_receipt_missing")
    if valuation_as_of is None:
        valuation_reasons.append("valuation_receipt_as_of_missing")
    elif valuation_as_of != as_of:
        valuation_reasons.append("valuation_receipt_as_of_mismatch")
    if valuation_market_at is None:
        valuation_reasons.append("valuation_market_input_missing")
    if not valuation_market_session:
        valuation_reasons.append("valuation_market_session_missing")
    if not valuation_expected_session:
        valuation_reasons.append("valuation_expected_market_session_missing")
    elif (
        valuation_market_session
        and valuation_market_session != valuation_expected_session
    ):
        valuation_reasons.append("valuation_market_input_expired")
    if scenario_at is None:
        valuation_reasons.append("valuation_scenario_missing")
    elif (
        scenario_age_seconds is not None
        and scenario_age_seconds > VALUATION_SCENARIO_MAX_AGE_SECONDS
    ):
        valuation_reasons.append("valuation_scenario_expired")
    if not valuation_complete:
        valuation_reasons.append("valuation_incomplete")
    normalized_valuation = {
        "valuation_receipt_sha256": valuation_digest,
        "receipt_as_of_utc": valuation_as_of_text,
        "market_input_at_utc": valuation_market_text,
        "market_session_date": valuation_market_session,
        "expected_market_session_date": valuation_expected_session,
        "scenario_refreshed_at_utc": scenario_text,
        "scenario_max_age_seconds": VALUATION_SCENARIO_MAX_AGE_SECONDS,
        "scenario_age_seconds": scenario_age_seconds,
        "complete": valuation_complete,
        "current": not valuation_reasons,
        "blocked_reasons": valuation_reasons,
    }

    all_blocked_reasons = (
        sec_reasons + market_reasons + valuation_reasons
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ticker": normalized_ticker,
        "as_of_utc": normalized_as_of,
        "sec_scan": normalized_sec_scan,
        "market": normalized_market,
        "valuation": normalized_valuation,
        "durable_sec_source_ids": _normalize_source_ids(
            durable_sec_source_ids
        ),
        "transition_freshness": {
            "sec_scan_current": normalized_sec_scan["current"],
            "market_current": normalized_market["current"],
            "valuation_current": normalized_valuation["current"],
            "all_current": not all_blocked_reasons,
            "blocked_reasons": all_blocked_reasons,
        },
        "guardrails": {
            "durable_sec_evidence_age_limit_applied": False,
            "current_sec_scan_required_for_transition": True,
            "missing_or_expired_blocks_action_review": True,
            "missing_or_expired_erases_research_classification": False,
            "broker_or_execution_capability": False,
        },
    }
    payload["receipt_sha256"] = _payload_digest(payload)
    return payload


def validate_evidence_freshness_receipt(value: Any) -> dict[str, Any]:
    """Recompute and validate an entire freshness receipt."""

    if not isinstance(value, dict):
        raise EvidenceFreshnessError("evidence freshness must be an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceFreshnessError("unsupported evidence freshness schema")
    sec_scan = value.get("sec_scan")
    market = value.get("market")
    valuation = value.get("valuation")
    if not isinstance(sec_scan, Mapping):
        raise EvidenceFreshnessError("sec_scan must be an object")
    if not isinstance(market, Mapping):
        raise EvidenceFreshnessError("market must be an object")
    if not isinstance(valuation, Mapping):
        raise EvidenceFreshnessError("valuation must be an object")
    reconstructed_sec_scan = {
        key: sec_scan.get(key) for key in _SEC_SCAN_KEYS
    }
    reconstructed_market = {
        key: market.get(key) for key in _MARKET_KEYS
    }
    reconstructed_valuation = {
        key: valuation.get(key) for key in _VALUATION_KEYS
    }
    expected = build_evidence_freshness_receipt(
        ticker=value.get("ticker"),
        as_of_utc=value.get("as_of_utc"),
        sec_scan=reconstructed_sec_scan,
        market=reconstructed_market,
        valuation=reconstructed_valuation,
        durable_sec_source_ids=value.get("durable_sec_source_ids"),
    )
    if value != expected:
        raise EvidenceFreshnessError(
            "evidence freshness does not match deterministic recomputation"
        )
    return value


def freshness_action_review_reasons(
    receipt: dict[str, Any] | None,
    *,
    ticker: str,
    require_market_and_valuation: bool,
) -> list[str]:
    """Return action-only reasons; this function never changes research labels."""

    normalized_ticker = _normalize_ticker(ticker)
    if receipt is None:
        return [f"transition_freshness_receipt_missing:{normalized_ticker}"]
    validated = validate_evidence_freshness_receipt(receipt)
    if validated["ticker"] != normalized_ticker:
        raise EvidenceFreshnessError("freshness receipt ticker mismatch")
    transition = validated["transition_freshness"]
    reasons: list[str] = []
    if transition["sec_scan_current"] is not True:
        reasons.append(
            f"transition_sec_scan_not_current:{normalized_ticker}"
        )
    if (
        require_market_and_valuation
        and transition["market_current"] is not True
    ):
        reasons.append(
            f"transition_market_not_current:{normalized_ticker}"
        )
    if (
        require_market_and_valuation
        and transition["valuation_current"] is not True
    ):
        reasons.append(
            f"transition_valuation_not_current:{normalized_ticker}"
        )
    return reasons


__all__ = [
    "EvidenceFreshnessError",
    "SCHEMA_VERSION",
    "SEC_SCAN_MAX_AGE_SECONDS",
    "VALUATION_SCENARIO_MAX_AGE_SECONDS",
    "build_evidence_freshness_receipt",
    "freshness_action_review_reasons",
    "validate_evidence_freshness_receipt",
]
