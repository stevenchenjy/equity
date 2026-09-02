#!/usr/bin/env python3
"""Closed deterministic validation for the Phase 5R evidence packet.

The legacy wire schema identifier is retained so existing audit artifacts remain
readable. This module has no model, provider, network, email, account-write,
broker, or execution capability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from phase5r_daily_common import (
    canonical_sha256,
    expected_market_session,
    latest_published_market_session,
)
from phase5r_evidence_freshness import (
    EvidenceFreshnessError,
    validate_evidence_freshness_receipt,
)
from phase5r_return_objective import validate_return_objective_payload
from phase5r_valuation_evidence_v1 import (
    ValuationEvidenceError,
    validate_valuation_evidence_v1,
    valuation_packet_calculations,
)

PACKET_SCHEMA_VERSION = "phase5r_llm_evidence_packet_v1"

_ROLE_ALLOWED_CLASSIFICATIONS = {
    "held": {
        "hold_existing",
        "paper_trade_candidate",
        "real_trade_candidate",
        "trim_review",
        "exit_review",
        "abstain",
    },
    "candidate": {
        "reject",
        "watchlist",
        "paper_trade_candidate",
        "real_trade_candidate",
        "abstain",
    },
}

_SENSITIVE_MARKERS = (
    "smtp",
    "app_password",
    "api_key",
    "authorization: bearer",
    "broker_login",
    "bank_account",
    "credit_card",
    "account_total_value",
    "cash_available",
    "cash_reserved",
    "current_shares",
    "target_shares",
    "entry_price",
    "/users/",
    "file://",
)

_FORBIDDEN_PACKET_KEYS = {
    "api_key",
    "app_password",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "email_address",
    "account_number",
    "routing_number",
    "account_balance",
    "account_total_value",
    "cash_available",
    "cash_reserved",
    "current_shares",
    "target_shares",
    "entry_price",
    "order_quantity",
}

_FORBIDDEN_PACKET_KEY_TOKENS = {
    re.sub(r"[^a-z0-9]+", "", key.lower()) for key in _FORBIDDEN_PACKET_KEYS
}

_EMAIL_PATTERN = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)

_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"password|secret|credential|smtp[_ -]?password|broker[_ -]?token)"
    r"[A-Z0-9_-]*\s*[:=]\s*[^\s,;]+"
)

_SECRET_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:sk-proj-[A-Z0-9_-]{6,}|"
    r"sk-svcacct-[A-Z0-9_-]{6,}|"
    r"gh[opusr]_[A-Z0-9]{12,}|"
    r"xox[baprs]-[A-Z0-9-]{10,})\b"
)

_LOCAL_PATH_PATTERN = re.compile(
    r"(?i)(?:file://|/Users/[^/\s]+/|[A-Z]:\\Users\\[^\\\s]+\\)"
)

_PRIVATE_CURRENCY_PATTERN = re.compile(
    r"(?i)(?:[$€£]\s*\d[\d,]*(?:\.\d+)?|"
    r"\b\d[\d,]*(?:\.\d+)?\s*(?:USD|dollars?)\b)"
)

class ContractError(ValueError):
    """A structured response or evidence packet violated a closed contract."""

def _assert_no_sensitive_markers(payload: Any, label: str) -> None:
    serialized_original = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    serialized = serialized_original.lower()
    found = [marker for marker in _SENSITIVE_MARKERS if marker in serialized]
    if found:
        raise ContractError(f"{label}: sensitive/local marker present: {','.join(found)}")
    if _EMAIL_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: email address is prohibited")
    if _SECRET_ASSIGNMENT_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: secret-like assignment is prohibited")
    if _SECRET_TOKEN_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: secret-like token is prohibited")
    if _LOCAL_PATH_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: local path is prohibited")

def _assert_no_forbidden_packet_keys(value: Any, path: str = "packet") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(
                r"[^a-z0-9]+",
                "",
                str(key).strip().lower(),
            )
            if normalized in _FORBIDDEN_PACKET_KEY_TOKENS:
                raise ContractError(f"{path}: forbidden field {key}")
            _assert_no_forbidden_packet_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden_packet_keys(child, f"{path}[{index}]")

def _assert_no_private_currency(packet: dict[str, Any]) -> None:
    private_context = {
        "entities": packet.get("entities", []),
        "portfolio_constraints": packet.get("portfolio_constraints", {}),
        "research_context": packet.get("research_context", []),
    }
    serialized = json.dumps(private_context, ensure_ascii=False, sort_keys=True)
    if _PRIVATE_CURRENCY_PATTERN.search(serialized):
        raise ContractError("packet: exact local/account currency value is prohibited")

def _tickers(packet: dict[str, Any]) -> set[str]:
    return {
        str(row.get("ticker", "")).upper()
        for row in packet.get("entities", [])
        if row.get("ticker")
    }

def _normalized_utc_or_empty(value: Any) -> str:
    if value in {"", None}:
        return ""
    try:
        parsed = datetime.fromisoformat(
            str(value)[:-1] + "+00:00"
            if str(value).endswith("Z")
            else str(value)
        )
    except ValueError as exc:
        raise ContractError(
            "packet: freshness-bound timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise ContractError(
            "packet: freshness-bound timestamp must include a timezone"
        )
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _date_from_period(value: Any) -> str:
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", str(value or ""))
    return match.group(0) if match else ""

def _expected_verified_close_session(
    cycle_date: Any,
    as_of_et: Any | None = None,
) -> str:
    """Return the canonical provider-published session for a packet cycle date.

    A Saturday, Sunday, or US market holiday may legitimately use the most
    recent published session. Keeping this calculation aligned with the
    daily decision builder prevents a calendar-date mismatch from weakening
    the separate freshness or shadow-transition gates.
    """

    if (
        not isinstance(cycle_date, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", cycle_date) is None
    ):
        raise ContractError("packet: cycle_date is invalid")
    try:
        cycle_day = datetime.strptime(cycle_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ContractError("packet: cycle_date is invalid") from exc
    if as_of_et is None:
        return expected_market_session(cycle_day - timedelta(days=1)).isoformat()
    try:
        as_of = datetime.fromisoformat(str(as_of_et))
    except ValueError as exc:
        raise ContractError("packet: as_of_et must be an ISO timestamp") from exc
    if as_of.tzinfo is None:
        raise ContractError("packet: as_of_et must include a timezone")
    return latest_published_market_session(as_of).isoformat()

def validate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "packet_id",
        "generated_at",
        "as_of_et",
        "cycle_date",
        "decision_fingerprint",
        "entities",
        "portfolio_constraints",
        "gates",
        "market_observations",
        "fundamental_observations",
        "filing_evidence",
        "research_context",
        "valuation_evidence",
        "calculations",
        "source_catalog",
        "boundaries",
    }
    optional = {"evidence_freshness"}
    missing = sorted(required - set(packet))
    extras = sorted(set(packet) - required - optional)
    if missing:
        raise ContractError(f"packet: missing fields {','.join(missing)}")
    if extras:
        raise ContractError(f"packet: unexpected fields {','.join(extras)}")
    if packet["schema_version"] != PACKET_SCHEMA_VERSION:
        raise ContractError("packet: schema version mismatch")
    unsigned = copy.deepcopy(packet)
    supplied_id = str(unsigned.pop("packet_id", ""))
    expected_id = canonical_sha256(unsigned)
    if supplied_id != expected_id:
        raise ContractError("packet: packet_id does not match canonical content")
    if not isinstance(packet["boundaries"], dict):
        raise ContractError("packet: boundaries must be an object")
    required_boundaries = {
        "research_only": True,
        "canonical_effect": False,
        "email_eligible": False,
        "automatic_action_allowed": False,
        "broker_connected": False,
        "order_code_available": False,
        "exact_account_dollars_included": False,
    }
    for key, expected in required_boundaries.items():
        if packet["boundaries"].get(key) is not expected:
            raise ContractError(f"packet: boundary {key} is not fail-closed")
    ids = [row.get("source_id") for row in packet["source_catalog"]]
    if any(not isinstance(value, str) or not value for value in ids):
        raise ContractError("packet: source_id must be a non-empty string")
    if len(ids) != len(set(ids)):
        raise ContractError("packet: source_ids must be unique")
    try:
        as_of = datetime.fromisoformat(str(packet["as_of_et"]))
    except ValueError as exc:
        raise ContractError("packet: as_of_et must be an ISO timestamp") from exc
    if as_of.tzinfo is None:
        raise ContractError("packet: as_of_et must include a timezone")
    source_fields = {
        "source_id",
        "source_type",
        "ticker",
        "accepted_at",
        "source_url",
        "content_sha256",
        "locator",
        "authority",
        "excerpt_text",
    }
    for index, source in enumerate(packet["source_catalog"]):
        if not isinstance(source, dict) or set(source) != source_fields:
            raise ContractError(f"packet.source_catalog[{index}]: field mismatch")
        digest = str(source["content_sha256"])
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ContractError(
                f"packet.source_catalog[{index}]: invalid content sha256"
            )
        accepted_at = str(source["accepted_at"])
        if accepted_at:
            try:
                accepted = datetime.fromisoformat(accepted_at)
            except ValueError as exc:
                raise ContractError(
                    f"packet.source_catalog[{index}]: invalid accepted_at"
                ) from exc
            if accepted.tzinfo is None or accepted > as_of:
                raise ContractError(
                    f"packet.source_catalog[{index}]: future or naive source time"
                )
        url = str(source["source_url"])
        if url and not url.startswith("https://"):
            raise ContractError(
                f"packet.source_catalog[{index}]: source URL is not HTTPS"
            )
        if source["source_type"].startswith("sec_") and url:
            if not (
                url.startswith("https://www.sec.gov/")
                or url.startswith("https://data.sec.gov/")
            ):
                raise ContractError(
                    f"packet.source_catalog[{index}]: SEC source host mismatch"
                )
        excerpt = str(source["excerpt_text"])
        if (
            excerpt
            and hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != digest
        ):
            raise ContractError(
                f"packet.source_catalog[{index}]: excerpt digest mismatch"
            )
    tickers = _tickers(packet)
    if not tickers or any(ticker != ticker.upper() for ticker in tickers):
        raise ContractError("packet: entity tickers must be non-empty uppercase values")
    entity_rows = packet["entities"]
    if not isinstance(entity_rows, list):
        raise ContractError("packet: entities must be an array")
    entity_tickers = [
        str(row.get("ticker", "")).upper()
        for row in entity_rows
        if isinstance(row, dict)
    ]
    if (
        len(entity_tickers) != len(entity_rows)
        or len(entity_tickers) != len(set(entity_tickers))
    ):
        raise ContractError("packet: entities must have unique ticker identities")
    for index, entity in enumerate(entity_rows):
        role = str(entity.get("role", ""))
        if role not in _ROLE_ALLOWED_CLASSIFICATIONS:
            raise ContractError(
                f"packet.entities[{index}]: role must be held or candidate"
            )
    constraints = packet["portfolio_constraints"]
    required_constraint_fields = {
        "account_size_band",
        "active_stock_hard_cap_pct",
        "active_stock_target_pct",
        "cash_target_pct",
        "core_allocation_target_pct",
        "investment_horizon_years",
        "manual_execution_only",
        "return_objective",
        "single_stock_default_cap_pct",
        "single_stock_hard_cap_pct",
    }
    if (
        not isinstance(constraints, dict)
        or set(constraints) != required_constraint_fields
    ):
        raise ContractError(
            "packet: portfolio constraint fields do not match policy"
        )
    if (
        not isinstance(constraints["account_size_band"], str)
        or not constraints["account_size_band"].strip()
    ):
        raise ContractError(
            "packet: account size band must be non-empty"
        )
    horizon = constraints["investment_horizon_years"]
    if (
        not isinstance(horizon, int)
        or isinstance(horizon, bool)
        or not 1 <= horizon <= 30
    ):
        raise ContractError(
            "packet: investment horizon must be 1..30 years"
        )
    if constraints["manual_execution_only"] is not True:
        raise ContractError(
            "packet: portfolio execution must remain manual"
        )
    percentage_fields = (
        "active_stock_hard_cap_pct",
        "active_stock_target_pct",
        "cash_target_pct",
        "core_allocation_target_pct",
        "single_stock_default_cap_pct",
        "single_stock_hard_cap_pct",
    )
    parsed_percentages: dict[str, Decimal] = {}
    for field in percentage_fields:
        raw = constraints[field]
        if isinstance(raw, bool):
            raise ContractError(
                f"packet: portfolio constraint {field} is invalid"
            )
        try:
            parsed = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise ContractError(
                f"packet: portfolio constraint {field} is invalid"
            ) from exc
        if not parsed.is_finite() or not Decimal("0") <= parsed <= Decimal("100"):
            raise ContractError(
                f"packet: portfolio constraint {field} is out of range"
            )
        parsed_percentages[field] = parsed
    if (
        parsed_percentages["active_stock_hard_cap_pct"] <= 0
        or parsed_percentages["single_stock_hard_cap_pct"] <= 0
        or parsed_percentages["single_stock_default_cap_pct"] <= 0
        or parsed_percentages["active_stock_target_pct"]
        > parsed_percentages["active_stock_hard_cap_pct"]
        or parsed_percentages["single_stock_default_cap_pct"]
        > parsed_percentages["single_stock_hard_cap_pct"]
        or parsed_percentages["single_stock_hard_cap_pct"]
        > parsed_percentages["active_stock_hard_cap_pct"]
    ):
        raise ContractError(
            "packet: portfolio cap ordering or positive-cap policy failed"
        )
    target_total = sum(
        (
            parsed_percentages["core_allocation_target_pct"],
            parsed_percentages["active_stock_target_pct"],
            parsed_percentages["cash_target_pct"],
        ),
        Decimal("0"),
    )
    if target_total != Decimal("100"):
        raise ContractError(
            "packet: core, active, and cash targets must sum to 100"
        )
    try:
        validate_return_objective_payload(
            constraints.get("return_objective")
        )
    except ValueError as exc:
        raise ContractError(
            "packet: return objective must remain a non-guaranteed "
            "long-horizon objective with no risk-gate override"
        ) from exc
    gates = packet["gates"]
    allowed_classifications_by_ticker = gates.get(
        "allowed_classifications_by_ticker"
    )
    if (
        not isinstance(allowed_classifications_by_ticker, dict)
        or set(allowed_classifications_by_ticker) != set(tickers)
    ):
        raise ContractError(
            "packet: allowed classifications must exactly match entities"
        )
    role_by_ticker = {
        str(entity["ticker"]).upper(): str(entity["role"])
        for entity in entity_rows
    }
    for ticker in tickers:
        values = allowed_classifications_by_ticker.get(ticker)
        role_allowed = _ROLE_ALLOWED_CLASSIFICATIONS[role_by_ticker[ticker]]
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(value, str) or value not in role_allowed
                for value in values
            )
            or len(values) != len(set(values))
            or "abstain" not in values
        ):
            raise ContractError(
                f"packet: allowed classifications are invalid for {ticker}"
            )
    market_data_action_grade = gates.get("market_data_action_grade")
    if not isinstance(market_data_action_grade, bool):
        raise ContractError("packet: market_data_action_grade must be boolean")
    close_count = gates.get("deterministic_action_stability_distinct_closes", 0)
    if (
        not isinstance(close_count, int)
        or isinstance(close_count, bool)
        or close_count < 0
    ):
        raise ContractError("packet: deterministic close count is invalid")
    for gate_name in (
        "market_data_action_grade_tickers",
        "valuation_action_grade_tickers",
        "deterministic_transition_pending_tickers",
        "deterministic_transition_eligible_tickers",
    ):
        values = gates.get(gate_name, [])
        if (
            not isinstance(values, list)
            or any(
                not isinstance(value, str)
                or value != value.upper()
                or value not in tickers
                for value in values
            )
            or len(values) != len(set(values))
        ):
            raise ContractError(f"packet: {gate_name} is invalid")
    market_data_action_grade_tickers = gates.get(
        "market_data_action_grade_tickers",
        [],
    )
    if market_data_action_grade is not bool(market_data_action_grade_tickers):
        raise ContractError(
            "packet: market_data_action_grade must equal per-ticker eligibility"
        )
    verified_session = gates.get("verified_close_session", "")
    if not isinstance(verified_session, str):
        raise ContractError("packet: verified close session is invalid")
    if verified_session and (
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified_session) is None
        or verified_session
        != _expected_verified_close_session(
            packet["cycle_date"],
            packet["as_of_et"],
        )
    ):
        raise ContractError("packet: verified close session is invalid")
    known_sources = set(ids)
    calculation_ids: list[str] = []
    for index, calculation in enumerate(packet["calculations"]):
        if not isinstance(calculation, dict):
            raise ContractError(f"packet.calculations[{index}]: expected object")
        calculation_id = str(calculation.get("calculation_id", ""))
        if not calculation_id:
            raise ContractError(f"packet.calculations[{index}]: missing id")
        calculation_ids.append(calculation_id)
        unknown = sorted(set(calculation.get("source_ids", [])) - known_sources)
        if unknown:
            raise ContractError(
                f"packet.calculations[{index}]: unknown sources {','.join(unknown)}"
            )
        if not calculation.get("unit") or not calculation.get("period"):
            raise ContractError(
                f"packet.calculations[{index}]: missing unit or period"
            )
    if len(calculation_ids) != len(set(calculation_ids)):
        raise ContractError("packet: calculation_ids must be unique")
    valuation_evidence = packet["valuation_evidence"]
    if not isinstance(valuation_evidence, list):
        raise ContractError("packet: valuation_evidence must be an array")
    valuation_tickers: list[str] = []
    valuation_action_grade_tickers: list[str] = []
    validated_valuation_by_ticker: dict[str, dict[str, Any]] = {}
    calculation_map = {
        str(row["calculation_id"]): row for row in packet["calculations"]
    }
    source_map = {
        str(row["source_id"]): row for row in packet["source_catalog"]
    }
    for index, receipt in enumerate(valuation_evidence):
        try:
            validated_receipt = validate_valuation_evidence_v1(receipt)
        except ValuationEvidenceError as exc:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: invalid receipt"
            ) from exc
        ticker = validated_receipt["ticker"]
        if ticker not in tickers:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: unknown ticker"
            )
        valuation_tickers.append(ticker)
        validated_valuation_by_ticker[ticker] = validated_receipt
        try:
            receipt_as_of = datetime.fromisoformat(
                validated_receipt["as_of_utc"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: invalid as-of"
            ) from exc
        if receipt_as_of != as_of.astimezone(receipt_as_of.tzinfo):
            raise ContractError(
                f"packet.valuation_evidence[{index}]: as-of mismatch"
            )
        receipt_source_ids = {
            str(source_id)
            for input_receipt in validated_receipt["input_receipts"]
            for source_id in input_receipt["source_ids"]
        }
        unknown_receipt_sources = sorted(receipt_source_ids - known_sources)
        if unknown_receipt_sources:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: unknown sources "
                + ",".join(unknown_receipt_sources)
            )
        wrong_ticker_sources = sorted(
            source_id
            for source_id in receipt_source_ids
            if str(source_map[source_id].get("ticker", "")).upper() != ticker
        )
        if wrong_ticker_sources:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: cross-ticker sources "
                + ",".join(wrong_ticker_sources)
            )
        for projected in valuation_packet_calculations(validated_receipt):
            if calculation_map.get(projected["calculation_id"]) != projected:
                raise ContractError(
                    f"packet.valuation_evidence[{index}]: projected "
                    f"calculation mismatch {projected['calculation_id']}"
                )
        if (
            validated_receipt["sufficiency"]["decision_sufficient"] is True
            and validated_receipt["guardrails"][
                "action_grade_valuation_permitted"
            ]
            is True
        ):
            valuation_action_grade_tickers.append(ticker)
    if len(valuation_tickers) != len(set(valuation_tickers)):
        raise ContractError(
            "packet: valuation evidence must have at most one receipt per ticker"
        )
    if gates.get("valuation_action_grade_tickers", []) != sorted(
        valuation_action_grade_tickers
    ):
        raise ContractError(
            "packet: valuation action-grade tickers must equal validated receipts"
        )
    evidence_freshness = packet.get("evidence_freshness", [])
    if not isinstance(evidence_freshness, list):
        raise ContractError("packet: evidence_freshness must be an array")
    freshness_tickers: list[str] = []
    market_by_ticker = {
        str(row.get("ticker", "")).upper(): row
        for row in packet["market_observations"]
        if isinstance(row, dict) and row.get("ticker")
    }
    packet_as_of_utc = as_of.astimezone(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    for index, raw_receipt in enumerate(evidence_freshness):
        try:
            freshness_receipt = validate_evidence_freshness_receipt(
                raw_receipt
            )
        except EvidenceFreshnessError as exc:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: invalid receipt"
            ) from exc
        ticker = freshness_receipt["ticker"]
        if ticker not in tickers:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: unknown ticker"
            )
        freshness_tickers.append(ticker)
        if freshness_receipt["as_of_utc"] != packet_as_of_utc:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: as-of mismatch"
            )

        durable_source_ids = set(
            freshness_receipt["durable_sec_source_ids"]
        )
        unknown_durable_sources = sorted(
            durable_source_ids - known_sources
        )
        if unknown_durable_sources:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: unknown durable SEC "
                f"sources {','.join(unknown_durable_sources)}"
            )
        cross_ticker_durable_sources = sorted(
            source_id
            for source_id in durable_source_ids
            if str(source_map[source_id].get("ticker", "")).upper()
            != ticker
        )
        if cross_ticker_durable_sources:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: cross-ticker source "
                f"in durable SEC receipt "
                f"{','.join(cross_ticker_durable_sources)}"
            )
        non_primary_durable_sources = sorted(
            source_id
            for source_id in durable_source_ids
            if (
                not str(
                    source_map[source_id].get("source_type", "")
                ).startswith("sec_")
                or source_map[source_id].get("authority")
                != "primary_official"
            )
        )
        if non_primary_durable_sources:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: durable evidence "
                f"requires a primary source "
                f"{','.join(non_primary_durable_sources)}"
            )

        market_row = market_by_ticker.get(ticker, {})
        market_freshness = freshness_receipt["market"]
        market_binding_mismatch = (
            market_freshness["observed_at_utc"]
            != _normalized_utc_or_empty(
                market_row.get("data_timestamp", "")
            )
            or market_freshness["market_session_date"]
            != str(market_row.get("market_session_date", ""))
            or market_freshness["expected_market_session_date"]
            != verified_session
            or market_freshness["complete_close"]
            is not (market_row.get("bar_state") == "complete_close")
        )
        if (
            market_binding_mismatch
            and gates.get("market_data_current") is True
            and bool(verified_session)
        ):
            raise ContractError(
                f"packet.evidence_freshness[{index}]: market binding mismatch"
            )

        valuation_receipt = validated_valuation_by_ticker.get(ticker)
        valuation_freshness = freshness_receipt["valuation"]
        if valuation_receipt is None:
            expected_valuation = {
                "valuation_receipt_sha256": "",
                "receipt_as_of_utc": "",
                "market_input_at_utc": "",
                "market_session_date": "",
                "expected_market_session_date": verified_session,
                "scenario_refreshed_at_utc": "",
                "complete": False,
            }
        else:
            valuation_inputs = {
                str(row["input_id"]): row
                for row in valuation_receipt["input_receipts"]
            }
            share_price = valuation_inputs.get("share_price", {})
            scenario_times = sorted(
                {
                    _normalized_utc_or_empty(
                        valuation_inputs.get(input_id, {}).get(
                            "available_at_utc",
                            "",
                        )
                    )
                    for input_id in (
                        "target_price_assumption",
                        "downside_price_assumption",
                    )
                    if valuation_inputs.get(input_id, {}).get(
                        "available_at_utc"
                    )
                }
            )
            expected_valuation = {
                "valuation_receipt_sha256": valuation_receipt[
                    "receipt_sha256"
                ],
                "receipt_as_of_utc": valuation_receipt["as_of_utc"],
                "market_input_at_utc": _normalized_utc_or_empty(
                    share_price.get("available_at_utc", "")
                ),
                "market_session_date": _date_from_period(
                    share_price.get("period", "")
                ),
                "expected_market_session_date": verified_session,
                "scenario_refreshed_at_utc": (
                    scenario_times[-1] if scenario_times else ""
                ),
                "complete": (
                    valuation_receipt["sufficiency"][
                        "decision_sufficient"
                    ]
                    is True
                    and valuation_receipt["guardrails"][
                        "action_grade_valuation_permitted"
                    ]
                    is True
                ),
            }
        supplied_valuation = {
            key: valuation_freshness[key]
            for key in expected_valuation
        }
        if (
            supplied_valuation != expected_valuation
            and ticker
            in set(gates.get("valuation_action_grade_tickers", []))
            and bool(verified_session)
        ):
            raise ContractError(
                f"packet.evidence_freshness[{index}]: valuation binding mismatch"
            )
    if len(freshness_tickers) != len(set(freshness_tickers)):
        raise ContractError(
            "packet: evidence freshness must have at most one receipt per ticker"
        )
    _assert_no_forbidden_packet_keys(packet)
    _assert_no_private_currency(packet)
    _assert_no_sensitive_markers(packet, "packet")
    return packet

__all__ = [
    "ContractError",
    "PACKET_SCHEMA_VERSION",
    "validate_packet",
]
