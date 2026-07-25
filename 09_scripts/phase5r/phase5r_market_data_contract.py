#!/usr/bin/env python3
"""Provider-neutral, fail-closed market-data ingestion contract.

This module validates already-imported JSON.  It contains no network client,
credential access, broker integration, order logic, or email capability.
The committed registry deliberately permits synthetic offline fixtures only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = (
    ROOT / "00_project_control" / "phase5r_market_data_provider_registry.json"
)

REGISTRY_SCHEMA_VERSION = "phase5r_market_data_provider_registry_v1"
BUNDLE_SCHEMA_VERSION = "phase5r_market_data_bundle_v1"

_REGISTRY_FIELDS = {
    "schema_version",
    "mode",
    "provider_id",
    "dataset_id",
    "feed_class",
    "action_grade_enabled",
    "canonical_influence_enabled",
    "network_enabled",
    "repository_credentials_allowed",
    "external_import_only",
    "synthetic_fixture_only",
    "license_activation_receipt_sha256",
    "raw_licensed_data_committable",
    "broker_connection_allowed",
    "order_code_allowed",
    "email_allowed",
}
_BUNDLE_FIELDS = {
    "schema_version",
    "bundle_id",
    "provider_id",
    "dataset_id",
    "feed_class",
    "mode",
    "synthetic_fixture",
    "action_grade_enabled",
    "canonical_influence_enabled",
    "expected_session_date",
    "previous_session_date",
    "retrieved_at",
    "license_activation_receipt_sha256",
    "source_receipts",
    "records",
    "action_grade_tickers",
    "network_used",
    "credentials_read",
    "broker_connected",
    "order_code_created",
    "email_attempted",
}
_RECEIPT_FIELDS = {
    "source_id",
    "endpoint_path",
    "provider_request_id",
    "retrieved_at",
    "raw_sha256",
    "status",
    "pagination_complete",
    "synthetic_fixture",
}
_RECORD_FIELDS = {
    "ticker",
    "identity",
    "bars",
    "corporate_actions",
    "source_ids",
    "contract_checks_passed",
    "action_grade_eligible",
    "rejection_reasons",
}
_IDENTITY_FIELDS = {
    "ticker",
    "cik",
    "composite_figi",
    "share_class_figi",
    "currency",
    "locale",
    "market",
    "primary_exchange",
    "active",
    "otc",
    "security_type",
}
_BAR_FIELDS = {
    "bar_id",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "vwap",
    "window_start_epoch_ms",
    "adjusted",
    "regular_session",
    "finality_basis",
    "source_id",
}
_CORPORATE_ACTION_FIELDS = {
    "checked_from",
    "checked_through",
    "unresolved",
    "event_ids",
    "source_ids",
}
_SAFETY_FIELDS = (
    "network_used",
    "credentials_read",
    "broker_connected",
    "order_code_created",
    "email_attempted",
)
_REGISTRY_FALSE_FIELDS = (
    "action_grade_enabled",
    "canonical_influence_enabled",
    "network_enabled",
    "repository_credentials_allowed",
    "raw_licensed_data_committable",
    "broker_connection_allowed",
    "order_code_allowed",
    "email_allowed",
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")


class MarketDataContractError(ValueError):
    """Raised when imported market data is unsafe or internally inconsistent."""


def canonical_sha256(value: Any) -> str:
    """Hash a JSON value with stable ordering and no non-finite numbers."""

    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MarketDataContractError(
            "market data contains a non-canonical JSON value"
        ) from exc
    return hashlib.sha256(payload).hexdigest()


def _require_exact_fields(
    value: Any,
    fields: set[str],
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        missing = sorted(fields - set(value)) if isinstance(value, dict) else []
        extra = sorted(set(value) - fields) if isinstance(value, dict) else []
        raise MarketDataContractError(
            f"{path}: field mismatch; missing={missing}; extra={extra}"
        )
    return value


def _parse_date(value: Any, path: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise MarketDataContractError(f"{path}: invalid ISO date") from exc
    if parsed.isoformat() != value:
        raise MarketDataContractError(f"{path}: invalid ISO date")
    return parsed


def _parse_timestamp(value: Any, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise MarketDataContractError(f"{path}: invalid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise MarketDataContractError(f"{path}: timezone is required")
    return parsed


def _finite_decimal(value: Any, path: str) -> Decimal:
    if isinstance(value, bool):
        raise MarketDataContractError(f"{path}: expected a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise MarketDataContractError(f"{path}: expected a finite number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MarketDataContractError(
            f"{path}: expected a finite number"
        ) from exc
    if not parsed.is_finite():
        raise MarketDataContractError(f"{path}: expected a finite number")
    return parsed


def validate_provider_registry(registry: Any) -> dict[str, Any]:
    """Validate the committed Phase 1 offline-only provider registry."""

    checked = _require_exact_fields(registry, _REGISTRY_FIELDS, "registry")
    if checked["schema_version"] != REGISTRY_SCHEMA_VERSION:
        raise MarketDataContractError("registry: unsupported schema version")
    for field in ("mode", "provider_id", "dataset_id", "feed_class"):
        if not isinstance(checked[field], str) or not checked[field].strip():
            raise MarketDataContractError(f"registry.{field}: non-empty string required")
    if checked["mode"] != "offline_fixture":
        raise MarketDataContractError(
            "registry.mode: Phase 1 permits offline_fixture only"
        )
    if checked["synthetic_fixture_only"] is not True:
        raise MarketDataContractError(
            "registry.synthetic_fixture_only: must remain true in Phase 1"
        )
    if checked["external_import_only"] is not True:
        raise MarketDataContractError(
            "registry.external_import_only: must remain true"
        )
    for field in _REGISTRY_FALSE_FIELDS:
        if checked[field] is not False:
            raise MarketDataContractError(
                f"registry.{field}: must remain false in Phase 1"
            )
    if checked["license_activation_receipt_sha256"] != "":
        raise MarketDataContractError(
            "registry: activation receipt must be empty while action grade is disabled"
        )
    return copy.deepcopy(checked)


def load_provider_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Load the local registry without consulting environment variables."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataContractError(
            f"registry: cannot load {path}"
        ) from exc
    return validate_provider_registry(value)


def unsigned_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(bundle)
    value.pop("bundle_id", None)
    return value


def seal_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return a copied bundle with a deterministic content identifier."""

    sealed = copy.deepcopy(bundle)
    sealed["bundle_id"] = canonical_sha256(unsigned_bundle(sealed))
    return sealed


def _validate_receipts(
    receipts: Any,
    retrieved_at: datetime,
) -> set[str]:
    if not isinstance(receipts, list) or not receipts:
        raise MarketDataContractError("bundle.source_receipts: non-empty array required")
    source_ids: list[str] = []
    for index, raw in enumerate(receipts):
        path = f"bundle.source_receipts[{index}]"
        receipt = _require_exact_fields(raw, _RECEIPT_FIELDS, path)
        source_id = receipt["source_id"]
        if not isinstance(source_id, str) or not source_id:
            raise MarketDataContractError(f"{path}.source_id: required")
        source_ids.append(source_id)
        endpoint = receipt["endpoint_path"]
        if (
            not isinstance(endpoint, str)
            or not endpoint.startswith("/")
            or "?" in endpoint
            or "://" in endpoint
        ):
            raise MarketDataContractError(
                f"{path}.endpoint_path: path-only endpoint required"
            )
        if receipt["provider_request_id"] != "":
            raise MarketDataContractError(
                f"{path}.provider_request_id: synthetic receipts must be blank"
            )
        receipt_time = _parse_timestamp(receipt["retrieved_at"], f"{path}.retrieved_at")
        if receipt_time != retrieved_at:
            raise MarketDataContractError(
                f"{path}.retrieved_at: must equal bundle retrieval time"
            )
        if not isinstance(receipt["raw_sha256"], str) or _HEX_64.fullmatch(
            receipt["raw_sha256"]
        ) is None:
            raise MarketDataContractError(f"{path}.raw_sha256: invalid digest")
        if receipt["status"] != "OK":
            raise MarketDataContractError(f"{path}.status: provider response was not OK")
        if receipt["pagination_complete"] is not True:
            raise MarketDataContractError(f"{path}: incomplete pagination")
        if receipt["synthetic_fixture"] is not True:
            raise MarketDataContractError(f"{path}: expected synthetic fixture receipt")
    if len(source_ids) != len(set(source_ids)):
        raise MarketDataContractError("bundle.source_receipts: duplicate source_id")
    return set(source_ids)


def _validate_bar(
    raw: Any,
    path: str,
    expected_sessions: set[str],
    known_sources: set[str],
) -> tuple[str, bool]:
    bar = _require_exact_fields(raw, _BAR_FIELDS, path)
    if not isinstance(bar["bar_id"], str) or not bar["bar_id"]:
        raise MarketDataContractError(f"{path}.bar_id: required")
    session = _parse_date(bar["session_date"], f"{path}.session_date").isoformat()
    if session not in expected_sessions:
        raise MarketDataContractError(f"{path}.session_date: unexpected session")
    prices = {
        field: _finite_decimal(bar[field], f"{path}.{field}")
        for field in ("open", "high", "low", "close", "vwap")
    }
    if any(value <= 0 for value in prices.values()):
        raise MarketDataContractError(f"{path}: prices must be positive")
    if prices["high"] < prices["low"]:
        raise MarketDataContractError(f"{path}: high is below low")
    for field in ("open", "close", "vwap"):
        if not prices["low"] <= prices[field] <= prices["high"]:
            raise MarketDataContractError(
                f"{path}.{field}: outside low/high range"
            )
    volume = _finite_decimal(bar["volume"], f"{path}.volume")
    if volume < 0:
        raise MarketDataContractError(f"{path}.volume: must be non-negative")
    if (
        not isinstance(bar["trade_count"], int)
        or isinstance(bar["trade_count"], bool)
        or bar["trade_count"] < 0
    ):
        raise MarketDataContractError(
            f"{path}.trade_count: non-negative integer required"
        )
    if (
        not isinstance(bar["window_start_epoch_ms"], int)
        or isinstance(bar["window_start_epoch_ms"], bool)
        or bar["window_start_epoch_ms"] <= 0
    ):
        raise MarketDataContractError(
            f"{path}.window_start_epoch_ms: positive integer required"
        )
    if not isinstance(bar["adjusted"], bool):
        raise MarketDataContractError(f"{path}.adjusted: boolean required")
    if bar["regular_session"] is not True:
        raise MarketDataContractError(f"{path}: regular-session bar required")
    if bar["finality_basis"] != "provider_eod_aggregate":
        raise MarketDataContractError(f"{path}: unsupported finality basis")
    if bar["source_id"] not in known_sources:
        raise MarketDataContractError(f"{path}.source_id: unknown source")
    return session, bar["adjusted"]


def _validate_record(
    raw: Any,
    index: int,
    expected_sessions: set[str],
    known_sources: set[str],
) -> str:
    path = f"bundle.records[{index}]"
    record = _require_exact_fields(raw, _RECORD_FIELDS, path)
    ticker = record["ticker"]
    if not isinstance(ticker, str) or _TICKER.fullmatch(ticker) is None:
        raise MarketDataContractError(f"{path}.ticker: invalid ticker")
    identity = _require_exact_fields(record["identity"], _IDENTITY_FIELDS, f"{path}.identity")
    if identity["ticker"] != ticker:
        raise MarketDataContractError(f"{path}.identity: ticker mismatch")
    for field in ("cik", "composite_figi", "share_class_figi", "primary_exchange"):
        if not isinstance(identity[field], str) or not identity[field]:
            raise MarketDataContractError(f"{path}.identity.{field}: required")
    if (
        identity["currency"] != "USD"
        or identity["locale"] != "us"
        or identity["market"] != "stocks"
        or identity["active"] is not True
        or identity["otc"] is not False
        or identity["security_type"] not in {"CS", "ADRC", "ETF"}
    ):
        raise MarketDataContractError(f"{path}.identity: unsupported security identity")

    bars = record["bars"]
    if not isinstance(bars, list) or len(bars) != 4:
        raise MarketDataContractError(f"{path}.bars: four comparison bars required")
    combinations = [
        _validate_bar(bar, f"{path}.bars[{bar_index}]", expected_sessions, known_sources)
        for bar_index, bar in enumerate(bars)
    ]
    if set(combinations) != {
        (session, adjusted)
        for session in expected_sessions
        for adjusted in (False, True)
    }:
        raise MarketDataContractError(
            f"{path}.bars: adjusted/unadjusted pair required for both sessions"
        )
    if len({bar["bar_id"] for bar in bars}) != len(bars):
        raise MarketDataContractError(f"{path}.bars: duplicate bar_id")

    corporate_actions = _require_exact_fields(
        record["corporate_actions"],
        _CORPORATE_ACTION_FIELDS,
        f"{path}.corporate_actions",
    )
    checked_from = _parse_date(
        corporate_actions["checked_from"],
        f"{path}.corporate_actions.checked_from",
    )
    checked_through = _parse_date(
        corporate_actions["checked_through"],
        f"{path}.corporate_actions.checked_through",
    )
    session_dates = sorted(date.fromisoformat(value) for value in expected_sessions)
    if checked_from > session_dates[0] or checked_through < session_dates[-1]:
        raise MarketDataContractError(
            f"{path}.corporate_actions: comparison window is not covered"
        )
    if corporate_actions["unresolved"] is not False:
        raise MarketDataContractError(
            f"{path}.corporate_actions: unresolved event blocks ingestion"
        )
    if not isinstance(corporate_actions["event_ids"], list) or any(
        not isinstance(value, str) or not value
        for value in corporate_actions["event_ids"]
    ):
        raise MarketDataContractError(
            f"{path}.corporate_actions.event_ids: invalid array"
        )
    corporate_sources = corporate_actions["source_ids"]
    if (
        not isinstance(corporate_sources, list)
        or not corporate_sources
        or set(corporate_sources) - known_sources
    ):
        raise MarketDataContractError(
            f"{path}.corporate_actions.source_ids: invalid sources"
        )
    source_ids = record["source_ids"]
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or len(source_ids) != len(set(source_ids))
        or set(source_ids) - known_sources
    ):
        raise MarketDataContractError(f"{path}.source_ids: invalid sources")
    if record["contract_checks_passed"] is not True:
        raise MarketDataContractError(f"{path}: contract checks did not pass")
    if record["action_grade_eligible"] is not False:
        raise MarketDataContractError(
            f"{path}: Phase 1 records cannot be action grade"
        )
    rejection_reasons = record["rejection_reasons"]
    if (
        not isinstance(rejection_reasons, list)
        or "registry_action_grade_disabled" not in rejection_reasons
        or "synthetic_fixture_not_action_grade" not in rejection_reasons
        or any(not isinstance(value, str) or not value for value in rejection_reasons)
    ):
        raise MarketDataContractError(f"{path}.rejection_reasons: fail-closed reasons missing")
    return ticker


def validate_market_data_bundle(
    bundle: Any,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Validate one normalized bundle against the offline provider registry."""

    checked_registry = validate_provider_registry(
        registry if registry is not None else load_provider_registry()
    )
    checked = _require_exact_fields(bundle, _BUNDLE_FIELDS, "bundle")
    if checked["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise MarketDataContractError("bundle: unsupported schema version")
    for field in ("provider_id", "dataset_id", "feed_class", "mode"):
        if checked[field] != checked_registry[field]:
            raise MarketDataContractError(f"bundle.{field}: registry mismatch")
    if checked["synthetic_fixture"] is not True:
        raise MarketDataContractError("bundle: Phase 1 requires a synthetic fixture")
    if (
        checked["action_grade_enabled"] is not False
        or checked["canonical_influence_enabled"] is not False
    ):
        raise MarketDataContractError("bundle: action and canonical influence are disabled")
    for field in _SAFETY_FIELDS:
        if checked[field] is not False:
            raise MarketDataContractError(f"bundle.{field}: prohibited side effect")
    if checked["license_activation_receipt_sha256"] != "":
        raise MarketDataContractError("bundle: activation receipt must remain empty")
    expected = _parse_date(
        checked["expected_session_date"],
        "bundle.expected_session_date",
    )
    previous = _parse_date(
        checked["previous_session_date"],
        "bundle.previous_session_date",
    )
    if previous >= expected:
        raise MarketDataContractError("bundle: previous session must precede expected session")
    retrieved_at = _parse_timestamp(checked["retrieved_at"], "bundle.retrieved_at")
    known_sources = _validate_receipts(checked["source_receipts"], retrieved_at)
    records = checked["records"]
    if not isinstance(records, list) or not records:
        raise MarketDataContractError("bundle.records: non-empty array required")
    tickers = [
        _validate_record(
            record,
            index,
            {previous.isoformat(), expected.isoformat()},
            known_sources,
        )
        for index, record in enumerate(records)
    ]
    if len(tickers) != len(set(tickers)):
        raise MarketDataContractError("bundle.records: duplicate ticker")
    if checked["action_grade_tickers"] != []:
        raise MarketDataContractError(
            "bundle.action_grade_tickers: must be empty while registry is disabled"
        )
    if checked["bundle_id"] != canonical_sha256(unsigned_bundle(checked)):
        raise MarketDataContractError("bundle.bundle_id: content hash mismatch")
    return copy.deepcopy(checked)
