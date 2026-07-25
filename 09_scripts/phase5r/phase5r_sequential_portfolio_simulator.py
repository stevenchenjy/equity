#!/usr/bin/env python3
"""Deterministic point-in-time paper portfolio simulation for Phase 5R.

The simulator accepts only caller-supplied, hash-bound decision snapshots and
market-period receipts.  It is an offline research measurement: it cannot
connect to a broker, create executable instructions, send email, call a model,
or access the network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any, Mapping, Sequence

from phase5r_daily_common import canonical_sha256
from phase5r_point_in_time_performance import (
    build_monthly_performance_ledger_row,
)


_MONTH_ID_PATTERN = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DECISION_ACTIONS = frozenset({"rebalance", "hold", "abstain"})
_TERMINAL_REASONS = frozenset(
    {"none", "delisting", "bankruptcy", "liquidation"}
)
_WEIGHT_TOLERANCE = Decimal("0.000000000001")


class SequentialSimulationError(ValueError):
    """Raised when simulation evidence or policy is unsafe or inconsistent."""


def _decimal(value: Any, *, label: str) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise SequentialSimulationError(
            f"{label} must be a decimal string, integer, or Decimal"
        )
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise SequentialSimulationError(
            f"{label} is not a valid decimal"
        ) from exc
    if not parsed.is_finite():
        raise SequentialSimulationError(f"{label} must be finite")
    return parsed


def _decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    rendered = format(normalized, "f")
    return "0" if rendered in {"-0", ""} else rendered


def _rounded(value: Decimal, quantum: str = "0.00000001") -> str:
    return format(
        value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP),
        "f",
    )


def _parse_utc(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SequentialSimulationError(
            f"{label} must be a non-empty UTC timestamp"
        )
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(
            raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        )
    except ValueError as exc:
        raise SequentialSimulationError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SequentialSimulationError(f"{label} must use UTC")
    return parsed.astimezone(timezone.utc)


def _utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _month_index(period_id: str) -> int:
    match = _MONTH_ID_PATTERN.fullmatch(period_id)
    if match is None:
        raise SequentialSimulationError("period_id must use YYYY-MM")
    return int(match.group(1)) * 12 + int(match.group(2)) - 1


def _validate_month_period(
    *,
    period_id: Any,
    period_start_utc: Any,
    period_end_utc: Any,
) -> tuple[str, datetime, datetime]:
    if not isinstance(period_id, str):
        raise SequentialSimulationError("period_id must be a string")
    normalized_period_id = period_id.strip()
    _month_index(normalized_period_id)
    start = _parse_utc(period_start_utc, label="period_start_utc")
    end = _parse_utc(period_end_utc, label="period_end_utc")
    if start >= end:
        raise SequentialSimulationError("period start must precede period end")
    year, month = (int(part) for part in normalized_period_id.split("-"))
    if (
        (start.year, start.month) != (year, month)
        or (end.year, end.month) != (year, month)
    ):
        raise SequentialSimulationError(
            "period_id must match start and end calendar month"
        )
    return normalized_period_id, start, end


def _nonempty_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SequentialSimulationError(f"{label} must be non-empty")
    return value.strip()


def _sha256(value: Any, *, label: str) -> str:
    normalized = _nonempty_string(value, label=label)
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise SequentialSimulationError(
            f"{label} must be a lowercase SHA-256"
        )
    return normalized


def _source_ids(value: Any, *, label: str) -> list[str]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise SequentialSimulationError(
            f"{label} must contain non-empty source identifiers"
        )
    normalized = sorted({item.strip() for item in value})
    if len(normalized) != len(value):
        raise SequentialSimulationError(f"{label} must not contain duplicates")
    return normalized


def _safety_payload() -> dict[str, bool]:
    return {
        "simulation_only": True,
        "broker_or_execution_capability": False,
        "network_or_model_access": False,
        "email_capability": False,
    }


def build_sequential_simulation_policy(
    *,
    policy_id: str,
    fixed_cost_per_changed_asset: Any = "0",
    spread_bps: Any = "0",
    slippage_bps: Any = "0",
    max_position_weight: Any = "0.25",
    max_gross_exposure: Any = "0.90",
    min_cash_weight: Any = "0.10",
    max_one_way_turnover: Any = "0.50",
    max_positions: int = 10,
    modeled_cash_return_pct: Any = "0",
) -> dict[str, Any]:
    """Build an immutable long-only paper-simulation policy."""

    normalized_policy_id = _nonempty_string(policy_id, label="policy_id")
    fixed_cost = _decimal(
        fixed_cost_per_changed_asset,
        label="fixed_cost_per_changed_asset",
    )
    spread = _decimal(spread_bps, label="spread_bps")
    slippage = _decimal(slippage_bps, label="slippage_bps")
    max_position = _decimal(
        max_position_weight,
        label="max_position_weight",
    )
    max_exposure = _decimal(
        max_gross_exposure,
        label="max_gross_exposure",
    )
    min_cash = _decimal(min_cash_weight, label="min_cash_weight")
    max_turnover = _decimal(
        max_one_way_turnover,
        label="max_one_way_turnover",
    )
    cash_return = _decimal(
        modeled_cash_return_pct,
        label="modeled_cash_return_pct",
    )
    if any(value < 0 for value in (fixed_cost, spread, slippage)):
        raise SequentialSimulationError(
            "modeled cost and basis-point inputs must be non-negative"
        )
    if not Decimal("0") <= max_position <= Decimal("1"):
        raise SequentialSimulationError("max_position_weight must be in [0, 1]")
    if not Decimal("0") <= max_exposure <= Decimal("1"):
        raise SequentialSimulationError("max_gross_exposure must be in [0, 1]")
    if not Decimal("0") <= min_cash <= Decimal("1"):
        raise SequentialSimulationError("min_cash_weight must be in [0, 1]")
    if not Decimal("0") <= max_turnover <= Decimal("1"):
        raise SequentialSimulationError(
            "max_one_way_turnover must be in [0, 1]"
        )
    if max_position > max_exposure:
        raise SequentialSimulationError(
            "max_position_weight cannot exceed max_gross_exposure"
        )
    if max_exposure > Decimal("1") - min_cash:
        raise SequentialSimulationError(
            "max_gross_exposure must preserve min_cash_weight"
        )
    if (
        not isinstance(max_positions, int)
        or isinstance(max_positions, bool)
        or max_positions < 1
    ):
        raise SequentialSimulationError(
            "max_positions must be a positive integer"
        )
    if cash_return <= Decimal("-100"):
        raise SequentialSimulationError(
            "modeled_cash_return_pct must exceed -100%"
        )
    payload = {
        "schema_version": "phase5r_sequential_simulation_policy_v1",
        "policy_id": normalized_policy_id,
        "fixed_cost_per_changed_asset": _decimal_string(fixed_cost),
        "spread_bps": _decimal_string(spread),
        "slippage_bps": _decimal_string(slippage),
        "max_position_weight": _decimal_string(max_position),
        "max_gross_exposure": _decimal_string(max_exposure),
        "min_cash_weight": _decimal_string(min_cash),
        "max_one_way_turnover": _decimal_string(max_turnover),
        "max_positions": max_positions,
        "modeled_cash_return_pct": _decimal_string(cash_return),
        **_safety_payload(),
    }
    return {**payload, "policy_sha256": canonical_sha256(payload)}


def _normalize_evidence_receipts(
    value: Any,
    *,
    decided_at: datetime,
) -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise SequentialSimulationError(
            "evidence_receipts must contain at least one receipt"
        )
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    required = {"evidence_id", "available_at_utc", "content_sha256"}
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise SequentialSimulationError(
                f"evidence_receipts[{index}] keys must equal {sorted(required)}"
            )
        evidence_id = _nonempty_string(
            raw["evidence_id"],
            label=f"evidence_receipts[{index}].evidence_id",
        )
        available_at = _parse_utc(
            raw["available_at_utc"],
            label=f"evidence_receipts[{index}].available_at_utc",
        )
        content_hash = _sha256(
            raw["content_sha256"],
            label=f"evidence_receipts[{index}].content_sha256",
        )
        if available_at > decided_at:
            raise SequentialSimulationError(
                "decision evidence was not available by decided_at_utc"
            )
        if evidence_id in seen_ids or content_hash in seen_hashes:
            raise SequentialSimulationError(
                "decision evidence ids and hashes must be unique"
            )
        seen_ids.add(evidence_id)
        seen_hashes.add(content_hash)
        normalized.append(
            {
                "evidence_id": evidence_id,
                "available_at_utc": _utc_string(available_at),
                "content_sha256": content_hash,
            }
        )
    return sorted(normalized, key=lambda row: row["evidence_id"])


def _normalize_target_weights(
    value: Any,
    *,
    action: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SequentialSimulationError("target_weights must be an object")
    if action in {"hold", "abstain"}:
        if value:
            raise SequentialSimulationError(
                "hold and abstain must not contain target weights"
            )
        return {}
    if not value:
        raise SequentialSimulationError(
            "rebalance requires explicit target weights"
        )
    normalized: dict[str, Decimal] = {}
    for raw_asset, raw_weight in value.items():
        asset = _nonempty_string(raw_asset, label="target weight asset").upper()
        if asset in normalized:
            raise SequentialSimulationError(
                "target weight assets must be unique after normalization"
            )
        weight = _decimal(
            raw_weight,
            label=f"target_weights[{asset!r}]",
        )
        if weight < 0 or weight > 1:
            raise SequentialSimulationError(
                "target weights must be in [0, 1]"
            )
        if asset != "CASH" and weight == 0:
            raise SequentialSimulationError(
                "zero non-cash target weights must be omitted"
            )
        normalized[asset] = weight
    if "CASH" not in normalized:
        raise SequentialSimulationError(
            "rebalance target weights must explicitly include CASH"
        )
    if abs(sum(normalized.values(), Decimal("0")) - Decimal("1")) > (
        _WEIGHT_TOLERANCE
    ):
        raise SequentialSimulationError("target weights must sum to one")
    return {
        asset: _decimal_string(normalized[asset])
        for asset in sorted(normalized)
    }


def build_decision_snapshot(
    *,
    decision_id: str,
    decided_at_utc: str,
    period_id: str,
    period_start_utc: str,
    period_end_utc: str,
    action: str,
    action_reason: str,
    target_weights: Mapping[str, Any],
    evidence_receipts: Sequence[Mapping[str, Any]],
    source_ids: Sequence[str],
) -> dict[str, Any]:
    """Build a hash-bound decision that is effective for one later period."""

    normalized_decision_id = _nonempty_string(
        decision_id,
        label="decision_id",
    )
    decided_at = _parse_utc(decided_at_utc, label="decided_at_utc")
    normalized_period_id, period_start, period_end = _validate_month_period(
        period_id=period_id,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
    )
    if decided_at >= period_start:
        raise SequentialSimulationError(
            "decision must occur strictly before its effective period"
        )
    normalized_action = _nonempty_string(action, label="action").lower()
    if normalized_action not in _DECISION_ACTIONS:
        raise SequentialSimulationError(
            f"action must be one of {sorted(_DECISION_ACTIONS)}"
        )
    payload = {
        "schema_version": "phase5r_sequential_decision_snapshot_v1",
        "decision_id": normalized_decision_id,
        "decided_at_utc": _utc_string(decided_at),
        "period_id": normalized_period_id,
        "period_start_utc": _utc_string(period_start),
        "period_end_utc": _utc_string(period_end),
        "action": normalized_action,
        "action_reason": _nonempty_string(
            action_reason,
            label="action_reason",
        ),
        "target_weights": _normalize_target_weights(
            target_weights,
            action=normalized_action,
        ),
        "evidence_receipts": _normalize_evidence_receipts(
            evidence_receipts,
            decided_at=decided_at,
        ),
        "source_ids": _source_ids(source_ids, label="source_ids"),
        **_safety_payload(),
    }
    return {**payload, "snapshot_sha256": canonical_sha256(payload)}


def build_market_period_receipt(
    *,
    receipt_id: str,
    ticker: str,
    period_id: str,
    period_start_utc: str,
    period_end_utc: str,
    available_at_utc: str,
    start_price: Any,
    end_price: Any,
    terminal_event: bool = False,
    terminal_reason: str = "none",
    terminal_cash_recovery_per_unit: Any = "0",
    source_ids: Sequence[str],
) -> dict[str, Any]:
    """Build an immutable price-derived monthly return receipt."""

    normalized_receipt_id = _nonempty_string(
        receipt_id,
        label="receipt_id",
    )
    normalized_ticker = _nonempty_string(ticker, label="ticker").upper()
    if normalized_ticker == "CASH":
        raise SequentialSimulationError("CASH cannot be a market ticker")
    normalized_period_id, period_start, period_end = _validate_month_period(
        period_id=period_id,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
    )
    available_at = _parse_utc(
        available_at_utc,
        label="available_at_utc",
    )
    if available_at < period_end:
        raise SequentialSimulationError(
            "market-period receipt cannot be available before period end"
        )
    start = _decimal(start_price, label="start_price")
    end = _decimal(end_price, label="end_price")
    recovery = _decimal(
        terminal_cash_recovery_per_unit,
        label="terminal_cash_recovery_per_unit",
    )
    if start <= 0 or end < 0 or recovery < 0:
        raise SequentialSimulationError(
            "start price must be positive; end price and recovery non-negative"
        )
    if not isinstance(terminal_event, bool):
        raise SequentialSimulationError("terminal_event must be boolean")
    normalized_reason = _nonempty_string(
        terminal_reason,
        label="terminal_reason",
    ).lower()
    if normalized_reason not in _TERMINAL_REASONS:
        raise SequentialSimulationError(
            f"terminal_reason must be one of {sorted(_TERMINAL_REASONS)}"
        )
    if terminal_event:
        if normalized_reason == "none":
            raise SequentialSimulationError(
                "terminal event requires a terminal reason"
            )
        if end != 0:
            raise SequentialSimulationError(
                "terminal event requires zero end_price"
            )
        ending_value_per_unit = recovery
    else:
        if normalized_reason != "none" or recovery != 0:
            raise SequentialSimulationError(
                "non-terminal receipt cannot contain terminal recovery"
            )
        if end <= 0:
            raise SequentialSimulationError(
                "non-terminal receipt requires positive end_price"
            )
        ending_value_per_unit = end
    period_return_pct = (
        ending_value_per_unit / start - Decimal("1")
    ) * Decimal("100")
    payload = {
        "schema_version": "phase5r_market_period_receipt_v1",
        "receipt_id": normalized_receipt_id,
        "ticker": normalized_ticker,
        "period_id": normalized_period_id,
        "period_start_utc": _utc_string(period_start),
        "period_end_utc": _utc_string(period_end),
        "available_at_utc": _utc_string(available_at),
        "start_price": _decimal_string(start),
        "end_price": _decimal_string(end),
        "terminal_event": terminal_event,
        "terminal_reason": normalized_reason,
        "terminal_cash_recovery_per_unit": _decimal_string(recovery),
        "period_return_pct": _rounded(period_return_pct, "0.00000001"),
        "source_ids": _source_ids(source_ids, label="source_ids"),
        **_safety_payload(),
    }
    return {**payload, "receipt_sha256": canonical_sha256(payload)}


def _validate_policy(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "policy_id",
        "fixed_cost_per_changed_asset",
        "spread_bps",
        "slippage_bps",
        "max_position_weight",
        "max_gross_exposure",
        "min_cash_weight",
        "max_one_way_turnover",
        "max_positions",
        "modeled_cash_return_pct",
        "simulation_only",
        "broker_or_execution_capability",
        "network_or_model_access",
        "email_capability",
        "policy_sha256",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise SequentialSimulationError(
            f"policy keys must equal {sorted(required)}"
        )
    expected = build_sequential_simulation_policy(
        policy_id=raw["policy_id"],
        fixed_cost_per_changed_asset=raw["fixed_cost_per_changed_asset"],
        spread_bps=raw["spread_bps"],
        slippage_bps=raw["slippage_bps"],
        max_position_weight=raw["max_position_weight"],
        max_gross_exposure=raw["max_gross_exposure"],
        min_cash_weight=raw["min_cash_weight"],
        max_one_way_turnover=raw["max_one_way_turnover"],
        max_positions=raw["max_positions"],
        modeled_cash_return_pct=raw["modeled_cash_return_pct"],
    )
    if dict(raw) != expected:
        raise SequentialSimulationError("policy hash or canonical payload mismatch")
    return expected


def _validate_decision(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "decision_id",
        "decided_at_utc",
        "period_id",
        "period_start_utc",
        "period_end_utc",
        "action",
        "action_reason",
        "target_weights",
        "evidence_receipts",
        "source_ids",
        "simulation_only",
        "broker_or_execution_capability",
        "network_or_model_access",
        "email_capability",
        "snapshot_sha256",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise SequentialSimulationError(
            f"decision snapshot keys must equal {sorted(required)}"
        )
    expected = build_decision_snapshot(
        decision_id=raw["decision_id"],
        decided_at_utc=raw["decided_at_utc"],
        period_id=raw["period_id"],
        period_start_utc=raw["period_start_utc"],
        period_end_utc=raw["period_end_utc"],
        action=raw["action"],
        action_reason=raw["action_reason"],
        target_weights=raw["target_weights"],
        evidence_receipts=raw["evidence_receipts"],
        source_ids=raw["source_ids"],
    )
    if dict(raw) != expected:
        raise SequentialSimulationError(
            "decision snapshot hash or canonical payload mismatch"
        )
    return expected


def _validate_market_receipt(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "receipt_id",
        "ticker",
        "period_id",
        "period_start_utc",
        "period_end_utc",
        "available_at_utc",
        "start_price",
        "end_price",
        "terminal_event",
        "terminal_reason",
        "terminal_cash_recovery_per_unit",
        "period_return_pct",
        "source_ids",
        "simulation_only",
        "broker_or_execution_capability",
        "network_or_model_access",
        "email_capability",
        "receipt_sha256",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise SequentialSimulationError(
            f"market receipt keys must equal {sorted(required)}"
        )
    expected = build_market_period_receipt(
        receipt_id=raw["receipt_id"],
        ticker=raw["ticker"],
        period_id=raw["period_id"],
        period_start_utc=raw["period_start_utc"],
        period_end_utc=raw["period_end_utc"],
        available_at_utc=raw["available_at_utc"],
        start_price=raw["start_price"],
        end_price=raw["end_price"],
        terminal_event=raw["terminal_event"],
        terminal_reason=raw["terminal_reason"],
        terminal_cash_recovery_per_unit=raw[
            "terminal_cash_recovery_per_unit"
        ],
        source_ids=raw["source_ids"],
    )
    if dict(raw) != expected:
        raise SequentialSimulationError(
            "market receipt hash or canonical payload mismatch"
        )
    return expected


def _state_payload(
    *,
    cash: Decimal,
    positions: Mapping[str, Decimal],
) -> dict[str, Any]:
    positive_positions = {
        ticker: value
        for ticker, value in positions.items()
        if value > 0
    }
    nav = cash + sum(positive_positions.values(), Decimal("0"))
    if nav < 0 or cash < 0:
        raise SequentialSimulationError("portfolio state cannot be negative")
    rows = []
    for ticker in sorted(positive_positions):
        value = positive_positions[ticker]
        rows.append(
            {
                "ticker": ticker,
                "paper_value": _rounded(value),
                "weight": (
                    None if nav == 0 else _rounded(value / nav, "0.0000000001")
                ),
            }
        )
    return {
        "total_paper_nav": _rounded(nav),
        "cash_value": _rounded(cash),
        "cash_weight": (
            None if nav == 0 else _rounded(cash / nav, "0.0000000001")
        ),
        "gross_exposure": (
            None
            if nav == 0
            else _rounded(
                sum(positive_positions.values(), Decimal("0")) / nav,
                "0.0000000001",
            )
        ),
        "position_count": len(rows),
        "positions": rows,
    }


def _constraint_breaches(
    *,
    cash: Decimal,
    positions: Mapping[str, Decimal],
    policy: Mapping[str, Any],
) -> list[str]:
    nav = cash + sum(positions.values(), Decimal("0"))
    if nav <= 0:
        return ["non_positive_nav_terminal_state"]
    max_position = _decimal(
        policy["max_position_weight"],
        label="policy.max_position_weight",
    )
    max_exposure = _decimal(
        policy["max_gross_exposure"],
        label="policy.max_gross_exposure",
    )
    min_cash = _decimal(
        policy["min_cash_weight"],
        label="policy.min_cash_weight",
    )
    max_positions = policy["max_positions"]
    breaches: list[str] = []
    positive = {ticker: value for ticker, value in positions.items() if value > 0}
    if len(positive) > max_positions:
        breaches.append("max_positions_exceeded")
    for ticker in sorted(positive):
        if positive[ticker] / nav > max_position + _WEIGHT_TOLERANCE:
            breaches.append(f"max_position_weight_exceeded:{ticker}")
    exposure = sum(positive.values(), Decimal("0")) / nav
    if exposure > max_exposure + _WEIGHT_TOLERANCE:
        breaches.append("max_gross_exposure_exceeded")
    if cash / nav + _WEIGHT_TOLERANCE < min_cash:
        breaches.append("min_cash_weight_breached")
    return breaches


def _validate_target_constraints(
    *,
    weights: Mapping[str, str],
    policy: Mapping[str, Any],
) -> None:
    max_position = _decimal(
        policy["max_position_weight"],
        label="policy.max_position_weight",
    )
    max_exposure = _decimal(
        policy["max_gross_exposure"],
        label="policy.max_gross_exposure",
    )
    min_cash = _decimal(
        policy["min_cash_weight"],
        label="policy.min_cash_weight",
    )
    non_cash = {
        ticker: _decimal(value, label=f"target_weights[{ticker!r}]")
        for ticker, value in weights.items()
        if ticker != "CASH"
    }
    if len(non_cash) > policy["max_positions"]:
        raise SequentialSimulationError("target exceeds max_positions")
    if any(value > max_position for value in non_cash.values()):
        raise SequentialSimulationError("target exceeds max_position_weight")
    if sum(non_cash.values(), Decimal("0")) > max_exposure:
        raise SequentialSimulationError("target exceeds max_gross_exposure")
    if _decimal(weights["CASH"], label="target CASH weight") < min_cash:
        raise SequentialSimulationError("target breaches min_cash_weight")


def simulate_sequential_portfolio(
    *,
    simulation_id: str,
    evaluation_as_of_utc: str,
    initial_cash: Any,
    policy: Mapping[str, Any],
    decision_snapshots: Sequence[Mapping[str, Any]],
    market_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Run a chronological, long-only, offline paper portfolio simulation."""

    normalized_simulation_id = _nonempty_string(
        simulation_id,
        label="simulation_id",
    )
    evaluation_as_of = _parse_utc(
        evaluation_as_of_utc,
        label="evaluation_as_of_utc",
    )
    starting_cash = _decimal(initial_cash, label="initial_cash")
    if starting_cash <= 0:
        raise SequentialSimulationError("initial_cash must be positive")
    validated_policy = _validate_policy(policy)
    if not isinstance(decision_snapshots, (list, tuple)) or not decision_snapshots:
        raise SequentialSimulationError(
            "decision_snapshots must not be empty"
        )
    if not isinstance(market_receipts, (list, tuple)):
        raise SequentialSimulationError("market_receipts must be a sequence")

    decisions = [_validate_decision(raw) for raw in decision_snapshots]
    receipts = [_validate_market_receipt(raw) for raw in market_receipts]

    decision_ids: set[str] = set()
    decision_hashes: set[str] = set()
    period_ids: set[str] = set()
    previous_decided_at: datetime | None = None
    previous_period_end: datetime | None = None
    previous_month: int | None = None
    period_bindings: dict[str, tuple[str, str]] = {}
    for decision in decisions:
        decision_id = decision["decision_id"]
        decision_hash = decision["snapshot_sha256"]
        period_id = decision["period_id"]
        decided_at = _parse_utc(
            decision["decided_at_utc"],
            label=f"{decision_id}.decided_at_utc",
        )
        period_start = _parse_utc(
            decision["period_start_utc"],
            label=f"{decision_id}.period_start_utc",
        )
        period_end = _parse_utc(
            decision["period_end_utc"],
            label=f"{decision_id}.period_end_utc",
        )
        if decided_at > evaluation_as_of or period_end > evaluation_as_of:
            raise SequentialSimulationError(
                "decision period extends beyond evaluation_as_of_utc"
            )
        if (
            decision_id in decision_ids
            or decision_hash in decision_hashes
            or period_id in period_ids
        ):
            raise SequentialSimulationError(
                "decision ids, hashes, and effective periods must be unique"
            )
        if previous_decided_at is not None and decided_at <= previous_decided_at:
            raise SequentialSimulationError(
                "decision snapshots must be strictly chronological"
            )
        if previous_period_end is not None and period_start <= previous_period_end:
            raise SequentialSimulationError(
                "decision periods must be chronological and non-overlapping"
            )
        month = _month_index(period_id)
        if previous_month is not None and month != previous_month + 1:
            raise SequentialSimulationError(
                "decision periods must be consecutive calendar months"
            )
        decision_ids.add(decision_id)
        decision_hashes.add(decision_hash)
        period_ids.add(period_id)
        period_bindings[period_id] = (
            decision["period_start_utc"],
            decision["period_end_utc"],
        )
        previous_decided_at = decided_at
        previous_period_end = period_end
        previous_month = month

    receipt_ids: set[str] = set()
    receipt_hashes: set[str] = set()
    receipt_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    receipt_by_id: dict[str, dict[str, Any]] = {}
    receipt_by_hash: dict[str, dict[str, Any]] = {}
    previous_market_key: tuple[int, str] | None = None
    for receipt in receipts:
        receipt_id = receipt["receipt_id"]
        receipt_hash = receipt["receipt_sha256"]
        period_id = receipt["period_id"]
        key = (period_id, receipt["ticker"])
        if period_id not in period_bindings:
            raise SequentialSimulationError(
                "market receipt period has no decision snapshot"
            )
        expected_start, expected_end = period_bindings[period_id]
        if (
            receipt["period_start_utc"] != expected_start
            or receipt["period_end_utc"] != expected_end
        ):
            raise SequentialSimulationError(
                "market receipt period boundary mismatch"
            )
        available_at = _parse_utc(
            receipt["available_at_utc"],
            label=f"{receipt_id}.available_at_utc",
        )
        if available_at > evaluation_as_of:
            raise SequentialSimulationError(
                "market receipt was not available by evaluation_as_of_utc"
            )
        if (
            receipt_id in receipt_ids
            or receipt_hash in receipt_hashes
            or key in receipt_by_key
        ):
            raise SequentialSimulationError(
                "market receipt ids, hashes, and ticker-period keys must be unique"
            )
        market_key = (_month_index(period_id), receipt["ticker"])
        if previous_market_key is not None and market_key <= previous_market_key:
            raise SequentialSimulationError(
                "market receipts must be chronological then ticker-sorted"
            )
        previous_market_key = market_key
        receipt_ids.add(receipt_id)
        receipt_hashes.add(receipt_hash)
        receipt_by_key[key] = receipt
        receipt_by_id[receipt_id] = receipt
        receipt_by_hash[receipt_hash] = receipt

    for decision in decisions:
        for evidence in decision["evidence_receipts"]:
            by_id = receipt_by_id.get(evidence["evidence_id"])
            by_hash = receipt_by_hash.get(evidence["content_sha256"])
            if by_id is not None or by_hash is not None:
                if by_id is None or by_hash is None or by_id is not by_hash:
                    raise SequentialSimulationError(
                        "decision evidence market-receipt id/hash mismatch"
                    )
                if evidence["available_at_utc"] != by_id["available_at_utc"]:
                    raise SequentialSimulationError(
                        "decision evidence market-receipt availability mismatch"
                    )

    cash = starting_cash
    positions: dict[str, Decimal] = {}
    terminal_tickers: set[str] = set()
    period_outputs: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    prior_period_hash = canonical_sha256(
        {
            "simulation_id": normalized_simulation_id,
            "policy_sha256": validated_policy["policy_sha256"],
            "initial_cash": _decimal_string(starting_cash),
        }
    )
    fixed_cost = _decimal(
        validated_policy["fixed_cost_per_changed_asset"],
        label="policy.fixed_cost_per_changed_asset",
    )
    variable_cost_bps = (
        _decimal(validated_policy["spread_bps"], label="policy.spread_bps")
        + _decimal(
            validated_policy["slippage_bps"],
            label="policy.slippage_bps",
        )
    )
    max_turnover = _decimal(
        validated_policy["max_one_way_turnover"],
        label="policy.max_one_way_turnover",
    )
    cash_factor = Decimal("1") + (
        _decimal(
            validated_policy["modeled_cash_return_pct"],
            label="policy.modeled_cash_return_pct",
        )
        / Decimal("100")
    )

    for period_index, decision in enumerate(decisions):
        period_id = decision["period_id"]
        opening_nav = cash + sum(positions.values(), Decimal("0"))
        if opening_nav <= 0:
            raise SequentialSimulationError(
                "non-positive NAV cannot continue into another period"
            )
        opening_state = _state_payload(cash=cash, positions=positions)
        opening_breaches = _constraint_breaches(
            cash=cash,
            positions=positions,
            policy=validated_policy,
        )
        action = decision["action"]
        if action in {"hold", "abstain"} and opening_breaches:
            raise SequentialSimulationError(
                "hold/abstain cannot silently carry an opening constraint breach"
            )

        changed_assets: list[str] = []
        absolute_change_notional = Decimal("0")
        turnover = Decimal("0")
        modeled_cost = Decimal("0")
        if action == "rebalance":
            target_weights = decision["target_weights"]
            _validate_target_constraints(
                weights=target_weights,
                policy=validated_policy,
            )
            for ticker, raw_weight in target_weights.items():
                if (
                    ticker != "CASH"
                    and _decimal(raw_weight, label=f"target {ticker}") > 0
                    and ticker in terminal_tickers
                ):
                    raise SequentialSimulationError(
                        f"terminal ticker cannot re-enter simulation: {ticker}"
                    )
            target_positions = {
                ticker: opening_nav
                * _decimal(raw_weight, label=f"target {ticker}")
                for ticker, raw_weight in target_weights.items()
                if ticker != "CASH"
            }
            allocation_l1_change = abs(
                _decimal(target_weights["CASH"], label="target CASH")
                - cash / opening_nav
            )
            for ticker in sorted(set(positions) | set(target_positions)):
                change = abs(
                    target_positions.get(ticker, Decimal("0"))
                    - positions.get(ticker, Decimal("0"))
                )
                absolute_change_notional += change
                allocation_l1_change += change / opening_nav
                if change > _WEIGHT_TOLERANCE:
                    changed_assets.append(ticker)
            turnover = allocation_l1_change / Decimal("2")
            if turnover > max_turnover + _WEIGHT_TOLERANCE:
                raise SequentialSimulationError(
                    "rebalance exceeds max_one_way_turnover"
                )
            modeled_cost = (
                fixed_cost * Decimal(len(changed_assets))
                + absolute_change_notional
                * variable_cost_bps
                / Decimal("10000")
            )
            cash = (
                opening_nav
                * _decimal(target_weights["CASH"], label="target CASH")
                - modeled_cost
            )
            positions = {
                ticker: value
                for ticker, value in target_positions.items()
                if value > 0
            }
            if cash < 0:
                raise SequentialSimulationError(
                    "modeled costs would make cash negative"
                )
            post_change_nav = cash + sum(positions.values(), Decimal("0"))
            if post_change_nav <= 0:
                raise SequentialSimulationError(
                    "modeled costs exhaust paper NAV"
                )
            post_change_breaches = _constraint_breaches(
                cash=cash,
                positions=positions,
                policy=validated_policy,
            )
            if post_change_breaches:
                raise SequentialSimulationError(
                    "post-cost allocation violates policy: "
                    + ",".join(post_change_breaches)
                )
            action_semantics = (
                "apply_explicit_long_only_target_weights_before_period_return"
            )
        elif action == "hold":
            action_semantics = (
                "affirmatively_preserve_opening_allocations_with_zero_change"
            )
        else:
            action_semantics = (
                "non_actionable_decision_preserves_opening_allocations_with_zero_change"
            )

        post_action_state = _state_payload(cash=cash, positions=positions)
        market_results: list[dict[str, Any]] = []
        terminal_events: list[dict[str, Any]] = []
        used_receipt_hashes: list[str] = []
        cash *= cash_factor
        for ticker in sorted(list(positions)):
            receipt = receipt_by_key.get((period_id, ticker))
            if receipt is None:
                raise SequentialSimulationError(
                    f"missing market receipt for held ticker {ticker} in {period_id}"
                )
            used_receipt_hashes.append(receipt["receipt_sha256"])
            opening_value = positions[ticker]
            start_price = _decimal(
                receipt["start_price"],
                label=f"{ticker}.start_price",
            )
            if receipt["terminal_event"]:
                recovery = _decimal(
                    receipt["terminal_cash_recovery_per_unit"],
                    label=f"{ticker}.terminal_cash_recovery_per_unit",
                )
                ending_value = opening_value * recovery / start_price
                cash += ending_value
                del positions[ticker]
                terminal_events.append(
                    {
                        "ticker": ticker,
                        "terminal_reason": receipt["terminal_reason"],
                        "opening_paper_value": _rounded(opening_value),
                        "terminal_cash_recovery": _rounded(ending_value),
                        "terminal_total_loss": ending_value == 0,
                        "receipt_sha256": receipt["receipt_sha256"],
                    }
                )
            else:
                end_price = _decimal(
                    receipt["end_price"],
                    label=f"{ticker}.end_price",
                )
                ending_value = opening_value * end_price / start_price
                positions[ticker] = ending_value
            market_results.append(
                {
                    "ticker": ticker,
                    "opening_paper_value": _rounded(opening_value),
                    "ending_paper_value": _rounded(ending_value),
                    "period_return_pct": receipt["period_return_pct"],
                    "terminal_event": receipt["terminal_event"],
                    "receipt_sha256": receipt["receipt_sha256"],
                }
            )

        for receipt in receipts:
            if receipt["period_id"] == period_id and receipt["terminal_event"]:
                terminal_tickers.add(receipt["ticker"])

        closing_nav = cash + sum(positions.values(), Decimal("0"))
        net_return_pct = (
            closing_nav / opening_nav - Decimal("1")
        ) * Decimal("100")
        closing_state = _state_payload(cash=cash, positions=positions)
        closing_breaches = _constraint_breaches(
            cash=cash,
            positions=positions,
            policy=validated_policy,
        )
        if closing_nav == 0 and period_index != len(decisions) - 1:
            raise SequentialSimulationError(
                "terminal total loss must be the final simulated period"
            )
        ledger_source_ids = sorted(
            {
                f"policy:{validated_policy['policy_sha256']}",
                f"decision:{decision['snapshot_sha256']}",
                *(
                    f"market:{receipt_hash}"
                    for receipt_hash in used_receipt_hashes
                ),
            }
        )
        monthly_row = build_monthly_performance_ledger_row(
            period_id=period_id,
            start_utc=decision["period_start_utc"],
            end_utc=decision["period_end_utc"],
            net_return_pct=net_return_pct,
            source_ids=ledger_source_ids,
        )
        monthly_rows.append(monthly_row)
        period_payload = {
            "period_id": period_id,
            "period_start_utc": decision["period_start_utc"],
            "period_end_utc": decision["period_end_utc"],
            "decision_id": decision["decision_id"],
            "decision_snapshot_sha256": decision["snapshot_sha256"],
            "action": action,
            "action_semantics": action_semantics,
            "opening_state": opening_state,
            "opening_constraint_breaches": opening_breaches,
            "changed_assets": changed_assets,
            "absolute_paper_allocation_change": _rounded(
                absolute_change_notional
            ),
            "one_way_turnover": _rounded(turnover, "0.0000000001"),
            "modeled_cost": _rounded(modeled_cost),
            "post_action_state": post_action_state,
            "market_results": market_results,
            "terminal_events": terminal_events,
            "closing_state": closing_state,
            "closing_constraint_breaches": closing_breaches,
            "net_return_pct": monthly_row["net_return_pct"],
            "monthly_ledger_row_sha256": monthly_row["row_sha256"],
            "prior_period_sha256": prior_period_hash,
        }
        period_hash = canonical_sha256(period_payload)
        period_outputs.append(
            {**period_payload, "period_sha256": period_hash}
        )
        prior_period_hash = period_hash

    final_state = _state_payload(cash=cash, positions=positions)
    final_breaches = period_outputs[-1]["closing_constraint_breaches"]
    receipt_payload = {
        "schema_version": "phase5r_sequential_portfolio_simulation_v1",
        "simulation_id": normalized_simulation_id,
        "evaluation_as_of_utc": _utc_string(evaluation_as_of),
        "policy_id": validated_policy["policy_id"],
        "policy_sha256": validated_policy["policy_sha256"],
        "initial_cash": _decimal_string(starting_cash),
        "decision_set_sha256": canonical_sha256(decisions),
        "market_receipt_set_sha256": canonical_sha256(receipts),
        "periods": period_outputs,
        "monthly_ledger_rows": monthly_rows,
        "monthly_ledger_sha256": canonical_sha256(monthly_rows),
        "final_state": final_state,
        "terminal_tickers": sorted(terminal_tickers),
        "simulation_status": (
            "constraint_breach_pending_next_review"
            if final_breaches
            else "complete_within_policy"
        ),
        "cost_method": (
            "fixed_per_changed_asset_plus_spread_and_slippage_on_absolute_"
            "paper_allocation_change"
        ),
        "return_objective_used_as_decision_rule": False,
        "future_performance_claim": False,
        **_safety_payload(),
    }
    return {
        **receipt_payload,
        "receipt_sha256": canonical_sha256(receipt_payload),
    }


__all__ = [
    "SequentialSimulationError",
    "build_decision_snapshot",
    "build_market_period_receipt",
    "build_sequential_simulation_policy",
    "simulate_sequential_portfolio",
]
