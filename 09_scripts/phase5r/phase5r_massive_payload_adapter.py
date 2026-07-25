#!/usr/bin/env python3
"""Normalize a synthetic Massive-shaped payload into the Phase 5R contract.

The adapter is deliberately pure: callers provide an in-memory JSON value and
receive an in-memory normalized bundle.  It does not fetch, authenticate,
persist provider payloads, connect to a broker, create orders, or send email.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from phase5r_market_data_contract import (
    BUNDLE_SCHEMA_VERSION,
    MarketDataContractError,
    canonical_sha256,
    load_provider_registry,
    seal_bundle,
    validate_market_data_bundle,
    validate_provider_registry,
)


FIXTURE_SCHEMA_VERSION = "phase5r_massive_synthetic_fixture_v1"
ET = ZoneInfo("America/New_York")

_TOP_FIELDS = {
    "fixture_schema_version",
    "synthetic_fixture",
    "provider_id",
    "dataset_id",
    "expected_session_date",
    "previous_session_date",
    "retrieved_at",
    "responses",
}
_RESPONSE_NAMES = {
    "ticker_overview",
    "current_open_close",
    "previous_open_close",
    "current_adjusted_aggregate",
    "current_unadjusted_aggregate",
    "previous_adjusted_aggregate",
    "previous_unadjusted_aggregate",
    "splits",
    "dividends",
}
_SECTION_FIELDS = {
    "endpoint_path",
    "status",
    "request_id",
    "next_url",
    "results",
}
_OVERVIEW_FIELDS = {
    "ticker",
    "name",
    "market",
    "locale",
    "primary_exchange",
    "type",
    "active",
    "currency_name",
    "cik",
    "composite_figi",
    "share_class_figi",
}
_OPEN_CLOSE_FIELDS = {
    "symbol",
    "from",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "afterHours",
    "preMarket",
}
_AGGREGATE_FIELDS = {"T", "t", "o", "h", "l", "c", "v", "n", "vw"}
_SPLIT_FIELDS = {
    "id",
    "ticker",
    "execution_date",
    "split_from",
    "split_to",
}
_DIVIDEND_FIELDS = {
    "id",
    "ticker",
    "ex_dividend_date",
    "cash_amount",
    "currency",
}


def _exact(value: Any, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        missing = sorted(fields - set(value)) if isinstance(value, dict) else []
        extra = sorted(set(value) - fields) if isinstance(value, dict) else []
        raise MarketDataContractError(
            f"{path}: field mismatch; missing={missing}; extra={extra}"
        )
    return value


def _iso_date(value: Any, path: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise MarketDataContractError(f"{path}: invalid ISO date") from exc
    if parsed.isoformat() != value:
        raise MarketDataContractError(f"{path}: invalid ISO date")
    return parsed


def _timestamp(value: Any, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise MarketDataContractError(f"{path}: invalid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise MarketDataContractError(f"{path}: timezone is required")
    return parsed


def _decimal(value: Any, path: str) -> Decimal:
    if isinstance(value, bool):
        raise MarketDataContractError(f"{path}: finite numeric value required")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MarketDataContractError(
            f"{path}: finite numeric value required"
        ) from exc
    if not parsed.is_finite():
        raise MarketDataContractError(f"{path}: finite numeric value required")
    return parsed


def _section(
    responses: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    section = _exact(responses[name], _SECTION_FIELDS, f"fixture.responses.{name}")
    if section["status"] != "OK":
        raise MarketDataContractError(
            f"fixture.responses.{name}.status: provider response was not OK"
        )
    endpoint = section["endpoint_path"]
    if (
        not isinstance(endpoint, str)
        or not endpoint.startswith("/")
        or "?" in endpoint
        or "://" in endpoint
    ):
        raise MarketDataContractError(
            f"fixture.responses.{name}.endpoint_path: path-only endpoint required"
        )
    if section["request_id"] != "":
        raise MarketDataContractError(
            f"fixture.responses.{name}.request_id: synthetic value must be blank"
        )
    if section["next_url"] != "":
        raise MarketDataContractError(
            f"fixture.responses.{name}: incomplete pagination"
        )
    return section


def _source_id(ticker: str, name: str) -> str:
    return f"massive-fixture:{ticker}:{name}"


def _receipt(
    ticker: str,
    name: str,
    section: dict[str, Any],
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "source_id": _source_id(ticker, name),
        "endpoint_path": section["endpoint_path"],
        "provider_request_id": "",
        "retrieved_at": retrieved_at,
        "raw_sha256": canonical_sha256(section),
        "status": "OK",
        "pagination_complete": True,
        "synthetic_fixture": True,
    }


def _open_close(
    section: dict[str, Any],
    *,
    ticker: str,
    session: str,
    path: str,
) -> dict[str, Any]:
    value = _exact(section["results"], _OPEN_CLOSE_FIELDS, f"{path}.results")
    if value["symbol"] != ticker or value["from"] != session:
        raise MarketDataContractError(f"{path}.results: ticker/session mismatch")
    for field in ("open", "high", "low", "close", "volume"):
        _decimal(value[field], f"{path}.results.{field}")
    for field in ("afterHours", "preMarket"):
        raw = value[field]
        if raw is not None:
            _decimal(raw, f"{path}.results.{field}")
    return value


def _aggregate_bar(
    section: dict[str, Any],
    *,
    ticker: str,
    session: str,
    adjusted: bool,
    source_id: str,
    name: str,
) -> dict[str, Any]:
    result = _exact(
        section["results"],
        _AGGREGATE_FIELDS,
        f"fixture.responses.{name}.results",
    )
    if result["T"] != ticker:
        raise MarketDataContractError(
            f"fixture.responses.{name}.results.T: ticker mismatch"
        )
    epoch = result["t"]
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch <= 0:
        raise MarketDataContractError(
            f"fixture.responses.{name}.results.t: positive integer required"
        )
    observed_session = datetime.fromtimestamp(epoch / 1000, tz=ET).date().isoformat()
    if observed_session != session:
        raise MarketDataContractError(
            f"fixture.responses.{name}.results.t: session mismatch"
        )
    if (
        not isinstance(result["n"], int)
        or isinstance(result["n"], bool)
        or result["n"] < 0
    ):
        raise MarketDataContractError(
            f"fixture.responses.{name}.results.n: non-negative integer required"
        )
    for field in ("o", "h", "l", "c", "v", "vw"):
        _decimal(result[field], f"fixture.responses.{name}.results.{field}")
    return {
        "bar_id": f"{source_id}:{session}:{'adjusted' if adjusted else 'unadjusted'}",
        "session_date": session,
        "open": result["o"],
        "high": result["h"],
        "low": result["l"],
        "close": result["c"],
        "volume": result["v"],
        "trade_count": result["n"],
        "vwap": result["vw"],
        "window_start_epoch_ms": epoch,
        "adjusted": adjusted,
        "regular_session": True,
        "finality_basis": "provider_eod_aggregate",
        "source_id": source_id,
    }


def _same_ohlcv(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(
        _decimal(left[field], f"bar.{field}")
        == _decimal(right[field], f"bar.{field}")
        for field in ("open", "high", "low", "close", "volume")
    )


def _open_close_matches_bar(
    open_close: dict[str, Any],
    bar: dict[str, Any],
) -> bool:
    mapping = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    return all(
        _decimal(open_close[left], f"open_close.{left}")
        == _decimal(bar[right], f"bar.{right}")
        for left, right in mapping.items()
    )


def _corporate_action_ids(
    section: dict[str, Any],
    *,
    kind: str,
    ticker: str,
    previous_session: date,
    expected_session: date,
) -> list[str]:
    rows = section["results"]
    if not isinstance(rows, list):
        raise MarketDataContractError(
            f"fixture.responses.{kind}.results: array required"
        )
    fields = _SPLIT_FIELDS if kind == "splits" else _DIVIDEND_FIELDS
    date_field = "execution_date" if kind == "splits" else "ex_dividend_date"
    event_ids: list[str] = []
    for index, raw in enumerate(rows):
        path = f"fixture.responses.{kind}.results[{index}]"
        event = _exact(raw, fields, path)
        if event["ticker"] != ticker:
            raise MarketDataContractError(f"{path}.ticker: ticker mismatch")
        event_date = _iso_date(event[date_field], f"{path}.{date_field}")
        if previous_session <= event_date <= expected_session:
            raise MarketDataContractError(
                f"{path}: comparison-window corporate action requires explicit reconciliation"
            )
        event_id = event["id"]
        if not isinstance(event_id, str) or not event_id:
            raise MarketDataContractError(f"{path}.id: required")
        event_ids.append(event_id)
    if len(event_ids) != len(set(event_ids)):
        raise MarketDataContractError(
            f"fixture.responses.{kind}: duplicate event id"
        )
    return event_ids


def normalize_massive_fixture(
    payload: Any,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Normalize and validate one synthetic Massive-shaped response bundle."""

    checked_registry = validate_provider_registry(
        registry if registry is not None else load_provider_registry()
    )
    fixture = _exact(payload, _TOP_FIELDS, "fixture")
    if fixture["fixture_schema_version"] != FIXTURE_SCHEMA_VERSION:
        raise MarketDataContractError("fixture: unsupported schema version")
    if fixture["synthetic_fixture"] is not True:
        raise MarketDataContractError("fixture: synthetic_fixture must be true")
    if fixture["provider_id"] != checked_registry["provider_id"]:
        raise MarketDataContractError("fixture.provider_id: registry mismatch")
    if fixture["dataset_id"] != checked_registry["dataset_id"]:
        raise MarketDataContractError("fixture.dataset_id: registry mismatch")

    expected_session = _iso_date(
        fixture["expected_session_date"],
        "fixture.expected_session_date",
    )
    previous_session = _iso_date(
        fixture["previous_session_date"],
        "fixture.previous_session_date",
    )
    if previous_session >= expected_session:
        raise MarketDataContractError(
            "fixture: previous session must precede expected session"
        )
    retrieved_at = _timestamp(fixture["retrieved_at"], "fixture.retrieved_at")
    if retrieved_at.astimezone(ET).date() < expected_session:
        raise MarketDataContractError(
            "fixture.retrieved_at: retrieval precedes expected session"
        )

    responses = fixture["responses"]
    if not isinstance(responses, dict) or set(responses) != _RESPONSE_NAMES:
        raise MarketDataContractError("fixture.responses: response set mismatch")
    sections = {name: _section(responses, name) for name in sorted(_RESPONSE_NAMES)}

    overview = _exact(
        sections["ticker_overview"]["results"],
        _OVERVIEW_FIELDS,
        "fixture.responses.ticker_overview.results",
    )
    ticker = overview["ticker"]
    if not isinstance(ticker, str) or ticker != ticker.upper() or not ticker:
        raise MarketDataContractError("fixture: uppercase ticker required")
    if any(ticker not in sections[name]["endpoint_path"] for name in _RESPONSE_NAMES):
        raise MarketDataContractError("fixture: endpoint ticker mismatch")
    if (
        overview["currency_name"] != "usd"
        or overview["locale"] != "us"
        or overview["market"] != "stocks"
        or overview["active"] is not True
        or overview["primary_exchange"] not in {"XNAS", "XNYS", "ARCX"}
        or overview["type"] not in {"CS", "ADRC", "ETF"}
    ):
        raise MarketDataContractError("fixture: unsupported security identity")

    current_open_close = _open_close(
        sections["current_open_close"],
        ticker=ticker,
        session=expected_session.isoformat(),
        path="fixture.responses.current_open_close",
    )
    previous_open_close = _open_close(
        sections["previous_open_close"],
        ticker=ticker,
        session=previous_session.isoformat(),
        path="fixture.responses.previous_open_close",
    )

    bar_specs = (
        ("current_adjusted_aggregate", expected_session.isoformat(), True),
        ("current_unadjusted_aggregate", expected_session.isoformat(), False),
        ("previous_adjusted_aggregate", previous_session.isoformat(), True),
        ("previous_unadjusted_aggregate", previous_session.isoformat(), False),
    )
    bars = [
        _aggregate_bar(
            sections[name],
            ticker=ticker,
            session=session,
            adjusted=adjusted,
            source_id=_source_id(ticker, name),
            name=name,
        )
        for name, session, adjusted in bar_specs
    ]
    bars_by_key = {
        (bar["session_date"], bar["adjusted"]): bar for bar in bars
    }
    for session, open_close in (
        (expected_session.isoformat(), current_open_close),
        (previous_session.isoformat(), previous_open_close),
    ):
        adjusted_bar = bars_by_key[(session, True)]
        unadjusted_bar = bars_by_key[(session, False)]
        if not _same_ohlcv(adjusted_bar, unadjusted_bar):
            raise MarketDataContractError(
                f"fixture: adjusted/unadjusted mismatch for {session}"
            )
        if not _open_close_matches_bar(open_close, adjusted_bar):
            raise MarketDataContractError(
                f"fixture: open-close/aggregate mismatch for {session}"
            )

    split_ids = _corporate_action_ids(
        sections["splits"],
        kind="splits",
        ticker=ticker,
        previous_session=previous_session,
        expected_session=expected_session,
    )
    dividend_ids = _corporate_action_ids(
        sections["dividends"],
        kind="dividends",
        ticker=ticker,
        previous_session=previous_session,
        expected_session=expected_session,
    )
    receipts = [
        _receipt(ticker, name, sections[name], fixture["retrieved_at"])
        for name in sorted(_RESPONSE_NAMES)
    ]
    source_ids = [receipt["source_id"] for receipt in receipts]
    unsigned = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "provider_id": checked_registry["provider_id"],
        "dataset_id": checked_registry["dataset_id"],
        "feed_class": checked_registry["feed_class"],
        "mode": checked_registry["mode"],
        "synthetic_fixture": True,
        "action_grade_enabled": False,
        "canonical_influence_enabled": False,
        "expected_session_date": expected_session.isoformat(),
        "previous_session_date": previous_session.isoformat(),
        "retrieved_at": fixture["retrieved_at"],
        "license_activation_receipt_sha256": "",
        "source_receipts": receipts,
        "records": [
            {
                "ticker": ticker,
                "identity": {
                    "ticker": ticker,
                    "cik": overview["cik"],
                    "composite_figi": overview["composite_figi"],
                    "share_class_figi": overview["share_class_figi"],
                    "currency": "USD",
                    "locale": overview["locale"],
                    "market": overview["market"],
                    "primary_exchange": overview["primary_exchange"],
                    "active": overview["active"],
                    "otc": False,
                    "security_type": overview["type"],
                },
                "bars": bars,
                "corporate_actions": {
                    "checked_from": previous_session.isoformat(),
                    "checked_through": expected_session.isoformat(),
                    "unresolved": False,
                    "event_ids": sorted(split_ids + dividend_ids),
                    "source_ids": [
                        _source_id(ticker, "dividends"),
                        _source_id(ticker, "splits"),
                    ],
                },
                "source_ids": source_ids,
                "contract_checks_passed": True,
                "action_grade_eligible": False,
                "rejection_reasons": [
                    "registry_action_grade_disabled",
                    "synthetic_fixture_not_action_grade",
                ],
            }
        ],
        "action_grade_tickers": [],
        "network_used": False,
        "credentials_read": False,
        "broker_connected": False,
        "order_code_created": False,
        "email_attempted": False,
    }
    bundle = seal_bundle({"bundle_id": "", **copy.deepcopy(unsigned)})
    return validate_market_data_bundle(bundle, checked_registry)
