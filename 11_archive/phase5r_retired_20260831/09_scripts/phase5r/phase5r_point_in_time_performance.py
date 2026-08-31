#!/usr/bin/env python3
"""Offline, read-only Phase 5R paper walk-forward measurements.

Every function operates only on caller-supplied synthetic or point-in-time
records.  The module has no file writes, network access, broker integration,
credentials, executable instructions, or live-trading capability.  It measures
paper assumptions; it does not establish that a strategy will perform well.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import random
import re
from typing import Any, Mapping, Sequence

from phase5r_daily_common import canonical_sha256
from phase5r_return_objective import return_objective_payload


REQUIRED_BASELINE_SERIES = ("SPY", "QQQ", "XLK", "C9")
_MONTH_ID_PATTERN = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")


class PerformanceEvidenceError(ValueError):
    """Raised when a performance input is incomplete or internally unsafe."""


def _decimal(value: Any, *, label: str) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise PerformanceEvidenceError(
            f"{label} must be a decimal string, integer, or Decimal"
        )
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PerformanceEvidenceError(f"{label} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise PerformanceEvidenceError(f"{label} must be finite")
    return parsed


def _rounded(value: Decimal, quantum: str = "0.0001") -> str:
    return format(
        value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP),
        "f",
    )


def _parse_utc(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PerformanceEvidenceError(f"{label} must be a non-empty UTC timestamp")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise PerformanceEvidenceError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PerformanceEvidenceError(f"{label} must use UTC")
    return parsed.astimezone(timezone.utc)


def _utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_ids(value: Any, *, label: str) -> list[str]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise PerformanceEvidenceError(
            f"{label} must contain non-empty source identifiers"
        )
    result = sorted({item.strip() for item in value})
    if len(result) != len(value):
        raise PerformanceEvidenceError(f"{label} must not contain duplicates")
    return result


def _twr_fraction(returns: Sequence[Decimal]) -> Decimal:
    wealth = Decimal("1")
    for index, period_return in enumerate(returns):
        if period_return < Decimal("-1"):
            raise PerformanceEvidenceError(
                f"period return at index {index} cannot be below -100%"
            )
        wealth *= Decimal("1") + period_return
    return wealth - Decimal("1")


def select_next_session_paper_fill(
    *,
    decision_id: str,
    ticker: str,
    decided_at_utc: str,
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Select the first supplied market-session open strictly after a decision.

    The output is a paper measurement receipt, not an order or an instruction.
    """

    if not isinstance(decision_id, str) or not decision_id.strip():
        raise PerformanceEvidenceError("decision_id must be non-empty")
    if not isinstance(ticker, str) or not ticker.strip():
        raise PerformanceEvidenceError("ticker must be non-empty")
    decision_time = _parse_utc(decided_at_utc, label="decided_at_utc")
    validated: list[tuple[datetime, dict[str, Any]]] = []
    for index, raw in enumerate(sessions):
        if not isinstance(raw, Mapping):
            raise PerformanceEvidenceError(f"sessions[{index}] must be an object")
        required = {
            "session_date",
            "open_utc",
            "open_price",
            "currency",
            "source_ids",
        }
        if set(raw) != required:
            raise PerformanceEvidenceError(
                f"sessions[{index}] keys must equal {sorted(required)}"
            )
        open_time = _parse_utc(raw["open_utc"], label=f"sessions[{index}].open_utc")
        price = _decimal(raw["open_price"], label=f"sessions[{index}].open_price")
        if price <= 0:
            raise PerformanceEvidenceError("session open price must be positive")
        session_date = raw["session_date"]
        currency = raw["currency"]
        if not isinstance(session_date, str) or not session_date.strip():
            raise PerformanceEvidenceError("session_date must be non-empty")
        if not isinstance(currency, str) or not currency.strip():
            raise PerformanceEvidenceError("currency must be non-empty")
        validated.append(
            (
                open_time,
                {
                    "session_date": session_date.strip(),
                    "open_utc": _utc_string(open_time),
                    "open_price": _rounded(price, "0.0001"),
                    "currency": currency.strip().upper(),
                    "source_ids": _source_ids(
                        raw["source_ids"],
                        label=f"sessions[{index}].source_ids",
                    ),
                },
            )
        )
    future_sessions = sorted(
        (item for item in validated if item[0] > decision_time),
        key=lambda item: item[0],
    )
    if not future_sessions:
        raise PerformanceEvidenceError(
            "no supplied market-session open occurs after the decision"
        )
    _, selected = future_sessions[0]
    return {
        "schema_version": "phase5r_next_session_paper_fill_v1",
        "decision_id": decision_id.strip(),
        "ticker": ticker.strip().upper(),
        "decided_at_utc": _utc_string(decision_time),
        "fill_assumption": "first_supplied_session_open_strictly_after_decision",
        "selected_session": selected,
        "simulation_only": True,
        "broker_or_execution_capability": False,
    }


def modeled_transaction_cost_receipt(
    *,
    absolute_paper_notional: Any,
    fixed_fee: Any = "0",
    spread_bps: Any = "0",
    slippage_bps: Any = "0",
) -> dict[str, Any]:
    """Return an explicit modeled cost for a paper notional."""

    notional = _decimal(absolute_paper_notional, label="absolute_paper_notional")
    fee = _decimal(fixed_fee, label="fixed_fee")
    spread = _decimal(spread_bps, label="spread_bps")
    slippage = _decimal(slippage_bps, label="slippage_bps")
    if any(value < 0 for value in (notional, fee, spread, slippage)):
        raise PerformanceEvidenceError("cost inputs must be non-negative")
    variable_cost = notional * (spread + slippage) / Decimal("10000")
    total_cost = fee + variable_cost
    return {
        "schema_version": "phase5r_modeled_transaction_cost_v1",
        "absolute_paper_notional": _rounded(notional, "0.01"),
        "fixed_fee": _rounded(fee, "0.01"),
        "spread_bps": _rounded(spread, "0.0001"),
        "slippage_bps": _rounded(slippage, "0.0001"),
        "variable_cost": _rounded(variable_cost, "0.01"),
        "total_modeled_cost": _rounded(total_cost, "0.01"),
        "simulation_only": True,
    }


def split_adjustment_receipt(
    *,
    shares_before: Any,
    reference_price_before: Any,
    split_numerator: Any,
    split_denominator: Any,
    effective_at_utc: str,
    source_ids: Sequence[str],
) -> dict[str, Any]:
    """Apply a supplied split ratio while proving value preservation."""

    shares = _decimal(shares_before, label="shares_before")
    price = _decimal(reference_price_before, label="reference_price_before")
    numerator = _decimal(split_numerator, label="split_numerator")
    denominator = _decimal(split_denominator, label="split_denominator")
    if min(shares, price, numerator, denominator) <= 0:
        raise PerformanceEvidenceError("split inputs must be positive")
    effective_at = _parse_utc(effective_at_utc, label="effective_at_utc")
    ratio = numerator / denominator
    shares_after = shares * ratio
    reference_price_after = price / ratio
    value_before = shares * price
    value_after = shares_after * reference_price_after
    if value_before != value_after:
        raise PerformanceEvidenceError("split adjustment failed value preservation")
    return {
        "schema_version": "phase5r_split_adjustment_v1",
        "effective_at_utc": _utc_string(effective_at),
        "split_ratio": f"{_rounded(numerator, '0.0001')}:{_rounded(denominator, '0.0001')}",
        "shares_before": _rounded(shares, "0.00000001"),
        "shares_after": _rounded(shares_after, "0.00000001"),
        "reference_price_before": _rounded(price, "0.0001"),
        "reference_price_after": _rounded(reference_price_after, "0.0001"),
        "market_value_before": _rounded(value_before, "0.01"),
        "market_value_after": _rounded(value_after, "0.01"),
        "source_ids": _source_ids(source_ids, label="source_ids"),
        "simulation_only": True,
    }


def cash_dividend_receipt(
    *,
    shares_eligible: Any,
    dividend_per_share: Any,
    announced_at_utc: str,
    ex_date_utc: str,
    pay_date_utc: str,
    source_ids: Sequence[str],
) -> dict[str, Any]:
    """Calculate supplied dividend cash with chronological validation."""

    shares = _decimal(shares_eligible, label="shares_eligible")
    dividend = _decimal(dividend_per_share, label="dividend_per_share")
    if shares < 0 or dividend < 0:
        raise PerformanceEvidenceError("dividend inputs must be non-negative")
    announced = _parse_utc(announced_at_utc, label="announced_at_utc")
    ex_date = _parse_utc(ex_date_utc, label="ex_date_utc")
    pay_date = _parse_utc(pay_date_utc, label="pay_date_utc")
    if not announced <= ex_date <= pay_date:
        raise PerformanceEvidenceError(
            "dividend timestamps must satisfy announced <= ex-date <= pay-date"
        )
    return {
        "schema_version": "phase5r_cash_dividend_v1",
        "announced_at_utc": _utc_string(announced),
        "ex_date_utc": _utc_string(ex_date),
        "pay_date_utc": _utc_string(pay_date),
        "shares_eligible": _rounded(shares, "0.00000001"),
        "dividend_per_share": _rounded(dividend, "0.0001"),
        "cash_amount": _rounded(shares * dividend, "0.01"),
        "source_ids": _source_ids(source_ids, label="source_ids"),
        "simulation_only": True,
    }


def delisting_recovery_receipt(
    *,
    shares: Any,
    recovery_per_share: Any,
    effective_at_utc: str,
    recovery_available_at_utc: str,
    evaluation_as_of_utc: str,
    source_ids: Sequence[str],
) -> dict[str, Any]:
    """Value a supplied delisting recovery without assuming a zero or par value."""

    position_shares = _decimal(shares, label="shares")
    recovery = _decimal(recovery_per_share, label="recovery_per_share")
    if position_shares < 0 or recovery < 0:
        raise PerformanceEvidenceError("delisting inputs must be non-negative")
    effective_at = _parse_utc(effective_at_utc, label="effective_at_utc")
    recovery_available_at = _parse_utc(
        recovery_available_at_utc,
        label="recovery_available_at_utc",
    )
    evaluation_as_of = _parse_utc(
        evaluation_as_of_utc,
        label="evaluation_as_of_utc",
    )
    if effective_at > evaluation_as_of or recovery_available_at > evaluation_as_of:
        raise PerformanceEvidenceError(
            "delisting outcome was not available by evaluation as-of"
        )
    return {
        "schema_version": "phase5r_delisting_recovery_v1",
        "effective_at_utc": _utc_string(effective_at),
        "recovery_available_at_utc": _utc_string(recovery_available_at),
        "evaluation_as_of_utc": _utc_string(evaluation_as_of),
        "shares": _rounded(position_shares, "0.00000001"),
        "recovery_per_share": _rounded(recovery, "0.0001"),
        "terminal_value": _rounded(position_shares * recovery, "0.01"),
        "source_ids": _source_ids(source_ids, label="source_ids"),
        "recovery_was_explicit_input": True,
        "simulation_only": True,
    }


def maximum_drawdown_pct(period_returns_pct: Sequence[Any]) -> str:
    """Return positive peak-to-trough drawdown percentage."""

    wealth = Decimal("1")
    peak = wealth
    maximum_drawdown = Decimal("0")
    for index, raw in enumerate(period_returns_pct):
        period_return_pct = _decimal(raw, label=f"period_returns_pct[{index}]")
        period_return = period_return_pct / Decimal("100")
        if period_return < Decimal("-1"):
            raise PerformanceEvidenceError("period return cannot be below -100%")
        wealth *= Decimal("1") + period_return
        peak = max(peak, wealth)
        drawdown = (peak - wealth) / peak
        maximum_drawdown = max(maximum_drawdown, drawdown)
    return _rounded(maximum_drawdown * Decimal("100"), "0.0001")


def evaluate_time_weighted_periods(
    periods: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate gross and net TWR with after-close external-flow boundaries.

    Each period supplies opening NAV, gross closing NAV, modeled cost, and an
    external flow applied only after the return subperiod closes.  The next
    opening NAV must reconcile to the previous net close plus that flow.
    """

    if not periods:
        raise PerformanceEvidenceError("at least one TWR period is required")
    gross_returns: list[Decimal] = []
    net_returns: list[Decimal] = []
    normalized_periods: list[dict[str, Any]] = []
    previous_end: datetime | None = None
    expected_opening: Decimal | None = None
    total_cost = Decimal("0")
    total_external_flow = Decimal("0")
    for index, raw in enumerate(periods):
        if not isinstance(raw, Mapping):
            raise PerformanceEvidenceError(f"periods[{index}] must be an object")
        required = {
            "period_id",
            "start_utc",
            "end_utc",
            "opening_nav",
            "gross_closing_nav",
            "modeled_cost",
            "external_flow_after_close",
            "source_ids",
        }
        if set(raw) != required:
            raise PerformanceEvidenceError(
                f"periods[{index}] keys must equal {sorted(required)}"
            )
        period_id = raw["period_id"]
        if not isinstance(period_id, str) or not period_id.strip():
            raise PerformanceEvidenceError("period_id must be non-empty")
        start = _parse_utc(raw["start_utc"], label=f"periods[{index}].start_utc")
        end = _parse_utc(raw["end_utc"], label=f"periods[{index}].end_utc")
        if start >= end:
            raise PerformanceEvidenceError("TWR period start must precede end")
        if previous_end is not None and start < previous_end:
            raise PerformanceEvidenceError("TWR periods must not overlap")
        opening = _decimal(raw["opening_nav"], label=f"periods[{index}].opening_nav")
        gross_close = _decimal(
            raw["gross_closing_nav"],
            label=f"periods[{index}].gross_closing_nav",
        )
        cost = _decimal(raw["modeled_cost"], label=f"periods[{index}].modeled_cost")
        flow = _decimal(
            raw["external_flow_after_close"],
            label=f"periods[{index}].external_flow_after_close",
        )
        if opening <= 0 or gross_close < 0 or cost < 0:
            raise PerformanceEvidenceError(
                "opening NAV must be positive and close/cost non-negative"
            )
        net_close = gross_close - cost
        if net_close < 0:
            raise PerformanceEvidenceError("modeled cost exceeds gross closing NAV")
        if expected_opening is not None and opening != expected_opening:
            raise PerformanceEvidenceError(
                "opening NAV does not reconcile to prior net close plus external flow"
            )
        if net_close + flow <= 0 and index < len(periods) - 1:
            raise PerformanceEvidenceError(
                "external flow leaves no positive NAV for the next period"
            )
        gross_return = gross_close / opening - Decimal("1")
        net_return = net_close / opening - Decimal("1")
        gross_returns.append(gross_return)
        net_returns.append(net_return)
        total_cost += cost
        total_external_flow += flow
        normalized_periods.append(
            {
                "period_id": period_id.strip(),
                "start_utc": _utc_string(start),
                "end_utc": _utc_string(end),
                "opening_nav": _rounded(opening, "0.01"),
                "gross_closing_nav": _rounded(gross_close, "0.01"),
                "modeled_cost": _rounded(cost, "0.01"),
                "net_closing_nav_before_external_flow": _rounded(net_close, "0.01"),
                "external_flow_after_close": _rounded(flow, "0.01"),
                "gross_return_pct": _rounded(
                    gross_return * Decimal("100"),
                    "0.0001",
                ),
                "net_return_pct": _rounded(
                    net_return * Decimal("100"),
                    "0.0001",
                ),
                "source_ids": _source_ids(
                    raw["source_ids"],
                    label=f"periods[{index}].source_ids",
                ),
            }
        )
        expected_opening = net_close + flow
        previous_end = end

    net_returns_pct = [value * Decimal("100") for value in net_returns]
    return {
        "schema_version": "phase5r_time_weighted_performance_v1",
        "flow_timing_assumption": "external_flow_after_subperiod_close",
        "periods": normalized_periods,
        "gross_twr_pct": _rounded(
            _twr_fraction(gross_returns) * Decimal("100"),
            "0.0001",
        ),
        "net_twr_pct": _rounded(
            _twr_fraction(net_returns) * Decimal("100"),
            "0.0001",
        ),
        "maximum_drawdown_pct": maximum_drawdown_pct(net_returns_pct),
        "total_modeled_cost": _rounded(total_cost, "0.01"),
        "total_external_flow": _rounded(total_external_flow, "0.01"),
        "measurement_only": True,
        "future_performance_claim": False,
    }


def cash_drag_receipt(
    periods: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare supplied cash-weight returns with a fully invested counterfactual."""

    if not periods:
        raise PerformanceEvidenceError("at least one cash-drag period is required")
    actual_returns: list[Decimal] = []
    fully_invested_returns: list[Decimal] = []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(periods):
        if not isinstance(raw, Mapping):
            raise PerformanceEvidenceError(f"periods[{index}] must be an object")
        required = {
            "period_id",
            "cash_weight",
            "invested_sleeve_return_pct",
            "cash_return_pct",
        }
        if set(raw) != required:
            raise PerformanceEvidenceError(
                f"periods[{index}] keys must equal {sorted(required)}"
            )
        cash_weight = _decimal(
            raw["cash_weight"],
            label=f"periods[{index}].cash_weight",
        )
        sleeve_return = _decimal(
            raw["invested_sleeve_return_pct"],
            label=f"periods[{index}].invested_sleeve_return_pct",
        ) / Decimal("100")
        cash_return = _decimal(
            raw["cash_return_pct"],
            label=f"periods[{index}].cash_return_pct",
        ) / Decimal("100")
        if not Decimal("0") <= cash_weight <= Decimal("1"):
            raise PerformanceEvidenceError("cash_weight must be between zero and one")
        actual_return = (
            (Decimal("1") - cash_weight) * sleeve_return
            + cash_weight * cash_return
        )
        if min(actual_return, sleeve_return) < Decimal("-1"):
            raise PerformanceEvidenceError("period return cannot be below -100%")
        actual_returns.append(actual_return)
        fully_invested_returns.append(sleeve_return)
        normalized.append(
            {
                "period_id": str(raw["period_id"]),
                "cash_weight": _rounded(cash_weight, "0.0001"),
                "invested_sleeve_return_pct": _rounded(
                    sleeve_return * Decimal("100"),
                    "0.0001",
                ),
                "cash_return_pct": _rounded(
                    cash_return * Decimal("100"),
                    "0.0001",
                ),
                "portfolio_return_with_cash_pct": _rounded(
                    actual_return * Decimal("100"),
                    "0.0001",
                ),
            }
        )
    actual_twr = _twr_fraction(actual_returns)
    fully_invested_twr = _twr_fraction(fully_invested_returns)
    return {
        "schema_version": "phase5r_cash_drag_v1",
        "periods": normalized,
        "portfolio_twr_with_cash_pct": _rounded(
            actual_twr * Decimal("100"),
            "0.0001",
        ),
        "fully_invested_counterfactual_twr_pct": _rounded(
            fully_invested_twr * Decimal("100"),
            "0.0001",
        ),
        "cash_drag_pct": _rounded(
            (fully_invested_twr - actual_twr) * Decimal("100"),
            "0.0001",
        ),
        "cash_drag_sign_note": "negative means supplied cash return helped",
        "measurement_only": True,
    }


def turnover_receipt(
    weight_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Calculate one-way turnover as half the L1 change in all weights."""

    if not weight_snapshots:
        raise PerformanceEvidenceError("at least one weight snapshot is required")
    validated: list[tuple[str, dict[str, Decimal]]] = []
    tolerance = Decimal("0.000001")
    for index, raw in enumerate(weight_snapshots):
        if not isinstance(raw, Mapping) or set(raw) != {"as_of", "weights"}:
            raise PerformanceEvidenceError(
                f"weight_snapshots[{index}] requires as_of and weights"
            )
        as_of = raw["as_of"]
        weights = raw["weights"]
        if not isinstance(as_of, str) or not as_of.strip():
            raise PerformanceEvidenceError("weight snapshot as_of must be non-empty")
        if not isinstance(weights, Mapping) or not weights:
            raise PerformanceEvidenceError("weight snapshot weights must be non-empty")
        parsed: dict[str, Decimal] = {}
        for asset, raw_weight in weights.items():
            if not isinstance(asset, str) or not asset.strip():
                raise PerformanceEvidenceError("weight asset must be non-empty")
            weight = _decimal(
                raw_weight,
                label=f"weight_snapshots[{index}].weights[{asset!r}]",
            )
            if weight < 0 or weight > 1:
                raise PerformanceEvidenceError("asset weights must be in [0, 1]")
            parsed[asset.strip().upper()] = weight
        if abs(sum(parsed.values(), Decimal("0")) - Decimal("1")) > tolerance:
            raise PerformanceEvidenceError("weights must sum to one")
        validated.append((as_of.strip(), parsed))

    transitions: list[dict[str, Any]] = []
    total_turnover = Decimal("0")
    for index in range(1, len(validated)):
        prior_as_of, prior = validated[index - 1]
        current_as_of, current = validated[index]
        assets = sorted(set(prior) | set(current))
        one_way = (
            sum(
                (
                    abs(current.get(asset, Decimal("0")) - prior.get(asset, Decimal("0")))
                    for asset in assets
                ),
                Decimal("0"),
            )
            / Decimal("2")
        )
        total_turnover += one_way
        transitions.append(
            {
                "from_as_of": prior_as_of,
                "to_as_of": current_as_of,
                "one_way_turnover_pct": _rounded(
                    one_way * Decimal("100"),
                    "0.0001",
                ),
            }
        )
    average_turnover = (
        total_turnover / Decimal(len(transitions)) if transitions else Decimal("0")
    )
    return {
        "schema_version": "phase5r_turnover_v1",
        "method": "one_way_half_l1_including_cash",
        "transitions": transitions,
        "total_turnover_pct": _rounded(
            total_turnover * Decimal("100"),
            "0.0001",
        ),
        "average_turnover_per_transition_pct": _rounded(
            average_turnover * Decimal("100"),
            "0.0001",
        ),
        "measurement_only": True,
    }


def _normalize_return_series(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> tuple[list[str], list[Decimal]]:
    if not rows:
        raise PerformanceEvidenceError(f"{label} must not be empty")
    period_ids: list[str] = []
    returns: list[Decimal] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or set(raw) != {"period_id", "return_pct"}:
            raise PerformanceEvidenceError(
                f"{label}[{index}] requires period_id and return_pct"
            )
        period_id = raw["period_id"]
        if not isinstance(period_id, str) or not period_id.strip():
            raise PerformanceEvidenceError(f"{label}[{index}].period_id is empty")
        if period_id in period_ids:
            raise PerformanceEvidenceError(f"{label} period ids must be unique")
        period_return = _decimal(
            raw["return_pct"],
            label=f"{label}[{index}].return_pct",
        )
        if period_return < Decimal("-100"):
            raise PerformanceEvidenceError("period return cannot be below -100%")
        period_ids.append(period_id.strip())
        returns.append(period_return / Decimal("100"))
    return period_ids, returns


def compare_required_baselines(
    *,
    strategy_returns: Sequence[Mapping[str, Any]],
    baseline_returns: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Compare aligned strategy returns with caller-supplied baseline series."""

    if not isinstance(baseline_returns, Mapping):
        raise PerformanceEvidenceError("baseline_returns must be an object")
    if set(baseline_returns) != set(REQUIRED_BASELINE_SERIES):
        raise PerformanceEvidenceError(
            "baseline series must be exactly SPY, QQQ, XLK, and C9"
        )
    period_ids, strategy = _normalize_return_series(
        strategy_returns,
        label="strategy_returns",
    )
    strategy_twr = _twr_fraction(strategy)
    baselines: dict[str, Any] = {}
    for name in REQUIRED_BASELINE_SERIES:
        baseline_periods, values = _normalize_return_series(
            baseline_returns[name],
            label=f"baseline_returns[{name}]",
        )
        if baseline_periods != period_ids:
            raise PerformanceEvidenceError(
                f"{name} baseline periods do not align with strategy periods"
            )
        baseline_twr = _twr_fraction(values)
        baselines[name] = {
            "twr_pct": _rounded(baseline_twr * Decimal("100"), "0.0001"),
            "maximum_drawdown_pct": maximum_drawdown_pct(
                [value * Decimal("100") for value in values]
            ),
            "strategy_minus_baseline_pct": _rounded(
                (strategy_twr - baseline_twr) * Decimal("100"),
                "0.0001",
            ),
        }
    return {
        "schema_version": "phase5r_required_baseline_comparison_v1",
        "required_baselines": list(REQUIRED_BASELINE_SERIES),
        "period_ids": period_ids,
        "strategy": {
            "twr_pct": _rounded(strategy_twr * Decimal("100"), "0.0001"),
            "maximum_drawdown_pct": maximum_drawdown_pct(
                [value * Decimal("100") for value in strategy]
            ),
        },
        "baselines": baselines,
        "measurement_only": True,
        "future_performance_claim": False,
    }


def _quantile(sorted_values: Sequence[Decimal], probability: Decimal) -> Decimal:
    if not sorted_values:
        raise PerformanceEvidenceError("cannot calculate an empty quantile")
    rank = Decimal(len(sorted_values) - 1) * probability
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = rank - Decimal(lower_index)
    return (
        sorted_values[lower_index]
        + (sorted_values[upper_index] - sorted_values[lower_index]) * fraction
    )


def block_bootstrap_twr_ci(
    period_returns_pct: Sequence[Any],
    *,
    iterations: int = 1000,
    block_size: int = 5,
    confidence_pct: Any = "95",
    seed: int = 20260725,
) -> dict[str, Any]:
    """Return a reproducible circular-block-bootstrap TWR interval."""

    values = [
        _decimal(value, label=f"period_returns_pct[{index}]") / Decimal("100")
        for index, value in enumerate(period_returns_pct)
    ]
    if len(values) < 2:
        raise PerformanceEvidenceError("bootstrap requires at least two returns")
    if any(value < Decimal("-1") for value in values):
        raise PerformanceEvidenceError("period return cannot be below -100%")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations < 100:
        raise PerformanceEvidenceError("iterations must be an integer of at least 100")
    if (
        not isinstance(block_size, int)
        or isinstance(block_size, bool)
        or block_size < 1
        or block_size > len(values)
    ):
        raise PerformanceEvidenceError(
            "block_size must be between one and the series length"
        )
    confidence = _decimal(confidence_pct, label="confidence_pct")
    if confidence <= 0 or confidence >= 100:
        raise PerformanceEvidenceError("confidence_pct must be between 0 and 100")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise PerformanceEvidenceError("seed must be an integer")

    generator = random.Random(seed)
    samples: list[Decimal] = []
    for _ in range(iterations):
        sample: list[Decimal] = []
        while len(sample) < len(values):
            start = generator.randrange(len(values))
            for offset in range(block_size):
                sample.append(values[(start + offset) % len(values)])
                if len(sample) == len(values):
                    break
        samples.append(_twr_fraction(sample))
    samples.sort()
    alpha = (Decimal("1") - confidence / Decimal("100")) / Decimal("2")
    lower = _quantile(samples, alpha)
    upper = _quantile(samples, Decimal("1") - alpha)
    return {
        "schema_version": "phase5r_block_bootstrap_twr_ci_v1",
        "method": "circular_block_bootstrap",
        "observations": len(values),
        "iterations": iterations,
        "block_size": block_size,
        "confidence_pct": _rounded(confidence, "0.01"),
        "seed": seed,
        "point_estimate_twr_pct": _rounded(
            _twr_fraction(values) * Decimal("100"),
            "0.0001",
        ),
        "lower_twr_pct": _rounded(lower * Decimal("100"), "0.0001"),
        "upper_twr_pct": _rounded(upper * Decimal("100"), "0.0001"),
        "measurement_only": True,
        "future_performance_claim": False,
    }


def _month_index(period_id: str) -> int:
    match = _MONTH_ID_PATTERN.fullmatch(period_id)
    if match is None:
        raise PerformanceEvidenceError(
            "monthly period_id must use YYYY-MM"
        )
    return int(match.group(1)) * 12 + int(match.group(2)) - 1


def _monthly_row_payload(
    *,
    period_id: str,
    start_utc: str,
    end_utc: str,
    net_return_pct: Any,
    source_ids: Sequence[str],
) -> dict[str, Any]:
    if not isinstance(period_id, str):
        raise PerformanceEvidenceError("monthly period_id must be a string")
    normalized_period_id = period_id.strip()
    _month_index(normalized_period_id)
    period_match = _MONTH_ID_PATTERN.fullmatch(normalized_period_id)
    assert period_match is not None
    period_year = int(period_match.group(1))
    period_month = int(period_match.group(2))
    start = _parse_utc(start_utc, label="monthly start_utc")
    end = _parse_utc(end_utc, label="monthly end_utc")
    if start >= end:
        raise PerformanceEvidenceError(
            "monthly performance period start must precede end"
        )
    if (
        (start.year, start.month) != (period_year, period_month)
        or (end.year, end.month) != (period_year, period_month)
    ):
        raise PerformanceEvidenceError(
            "monthly period_id must match start and end calendar month"
        )
    period_return = _decimal(
        net_return_pct,
        label="monthly net_return_pct",
    )
    if period_return < Decimal("-100"):
        raise PerformanceEvidenceError(
            "monthly return cannot be below -100%"
        )
    return {
        "period_id": normalized_period_id,
        "start_utc": _utc_string(start),
        "end_utc": _utc_string(end),
        "net_return_pct": _rounded(period_return, "0.000001"),
        "source_ids": _source_ids(
            source_ids,
            label="monthly source_ids",
        ),
    }


def build_monthly_performance_ledger_row(
    *,
    period_id: str,
    start_utc: str,
    end_utc: str,
    net_return_pct: Any,
    source_ids: Sequence[str],
) -> dict[str, Any]:
    """Build one immutable, source-bound monthly paper-ledger row."""

    payload = _monthly_row_payload(
        period_id=period_id,
        start_utc=start_utc,
        end_utc=end_utc,
        net_return_pct=net_return_pct,
        source_ids=source_ids,
    )
    return {
        **payload,
        "row_sha256": canonical_sha256(payload),
    }


def _annualized_cagr(
    returns: Sequence[Decimal],
) -> Decimal:
    if not returns:
        raise PerformanceEvidenceError(
            "annualized return requires at least one month"
        )
    wealth = Decimal("1") + _twr_fraction(returns)
    if wealth == 0:
        return Decimal("-1")
    exponent = Decimal("12") / Decimal(len(returns))
    return (wealth.ln() * exponent).exp() - Decimal("1")


def _rolling_window_metrics(
    *,
    period_ids: Sequence[str],
    returns: Sequence[Decimal],
    window_months: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for end_index in range(window_months - 1, len(returns)):
        start_index = end_index - window_months + 1
        window = returns[start_index : end_index + 1]
        rows.append(
            {
                "start_period_id": period_ids[start_index],
                "end_period_id": period_ids[end_index],
                "months": str(window_months),
                "twr_pct": _rounded(
                    _twr_fraction(window) * Decimal("100"),
                    "0.0001",
                ),
                "annualized_cagr_pct": _rounded(
                    _annualized_cagr(window) * Decimal("100"),
                    "0.0001",
                ),
            }
        )
    return rows


def _annualized_dispersion(
    returns: Sequence[Decimal],
    *,
    minimum_acceptable_monthly_return: Decimal,
) -> dict[str, str | None]:
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = (
        sum(
            ((value - mean) ** 2 for value in returns),
            Decimal("0"),
        )
        / Decimal(len(returns))
    )
    annualized_volatility = variance.sqrt() * Decimal("12").sqrt()
    downside_squares = [
        min(
            value - minimum_acceptable_monthly_return,
            Decimal("0"),
        )
        ** 2
        for value in returns
    ]
    annualized_downside = (
        (
            sum(downside_squares, Decimal("0"))
            / Decimal(len(downside_squares))
        ).sqrt()
        * Decimal("12").sqrt()
    )
    annualized_return = _annualized_cagr(returns)
    annualized_minimum = (
        (Decimal("1") + minimum_acceptable_monthly_return)
        ** Decimal("12")
        - Decimal("1")
    )
    sortino = (
        None
        if annualized_downside == 0
        else _rounded(
            (annualized_return - annualized_minimum)
            / annualized_downside,
            "0.0001",
        )
    )
    return {
        "annualized_volatility_pct": _rounded(
            annualized_volatility * Decimal("100"),
            "0.0001",
        ),
        "annualized_downside_deviation_pct": _rounded(
            annualized_downside * Decimal("100"),
            "0.0001",
        ),
        "sortino_ratio": sortino,
        "sortino_status": (
            "undefined_no_downside_deviation"
            if sortino is None
            else "defined"
        ),
    }


def _drawdown_recovery_metrics(
    returns: Sequence[Decimal],
) -> dict[str, Any]:
    wealth = Decimal("1")
    peak = wealth
    underwater_start: int | None = None
    max_underwater_months = 0
    maximum_drawdown = Decimal("0")
    for index, value in enumerate(returns):
        wealth *= Decimal("1") + value
        if wealth >= peak:
            if underwater_start is not None:
                max_underwater_months = max(
                    max_underwater_months,
                    index - underwater_start + 1,
                )
                underwater_start = None
            peak = wealth
        else:
            if underwater_start is None:
                underwater_start = index
            maximum_drawdown = max(
                maximum_drawdown,
                (peak - wealth) / peak,
            )
    current_underwater_months = (
        0
        if underwater_start is None
        else len(returns) - underwater_start
    )
    max_underwater_months = max(
        max_underwater_months,
        current_underwater_months,
    )
    return {
        "maximum_drawdown_pct": _rounded(
            maximum_drawdown * Decimal("100"),
            "0.0001",
        ),
        "maximum_underwater_months": max_underwater_months,
        "ending_peak_recovered": underwater_start is None,
        "ending_underwater_months": current_underwater_months,
    }


def rolling_monthly_performance_receipt(
    *,
    ledger_id: str,
    policy_id: str,
    policy_sha256: str,
    evaluation_as_of_utc: str,
    monthly_rows: Sequence[Mapping[str, Any]],
    minimum_acceptable_monthly_return_pct: Any = "0",
) -> dict[str, Any]:
    """Measure a hash-bound chronological monthly paper ledger.

    The receipt calculates rolling 12/36/60-month evidence and never uses the
    return objective as a label, trade trigger, or optimization target.
    """

    if not isinstance(ledger_id, str) or not ledger_id.strip():
        raise PerformanceEvidenceError("ledger_id must be non-empty")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise PerformanceEvidenceError("policy_id must be non-empty")
    if (
        not isinstance(policy_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", policy_sha256) is None
    ):
        raise PerformanceEvidenceError(
            "policy_sha256 must be lowercase SHA-256"
        )
    evaluation_as_of = _parse_utc(
        evaluation_as_of_utc,
        label="evaluation_as_of_utc",
    )
    if not monthly_rows:
        raise PerformanceEvidenceError(
            "monthly performance ledger must not be empty"
        )
    minimum_acceptable = _decimal(
        minimum_acceptable_monthly_return_pct,
        label="minimum_acceptable_monthly_return_pct",
    )
    if minimum_acceptable <= Decimal("-100"):
        raise PerformanceEvidenceError(
            "minimum acceptable monthly return must exceed -100%"
        )
    minimum_acceptable /= Decimal("100")

    normalized_rows: list[dict[str, Any]] = []
    returns: list[Decimal] = []
    period_ids: list[str] = []
    previous_month_index: int | None = None
    previous_end: datetime | None = None
    for index, raw in enumerate(monthly_rows):
        if not isinstance(raw, Mapping):
            raise PerformanceEvidenceError(
                f"monthly_rows[{index}] must be an object"
            )
        required = {
            "period_id",
            "start_utc",
            "end_utc",
            "net_return_pct",
            "source_ids",
            "row_sha256",
        }
        if set(raw) != required:
            raise PerformanceEvidenceError(
                f"monthly_rows[{index}] keys must equal {sorted(required)}"
            )
        payload = _monthly_row_payload(
            period_id=raw["period_id"],
            start_utc=raw["start_utc"],
            end_utc=raw["end_utc"],
            net_return_pct=raw["net_return_pct"],
            source_ids=raw["source_ids"],
        )
        if raw["row_sha256"] != canonical_sha256(payload):
            raise PerformanceEvidenceError(
                "monthly ledger row hash mismatch"
            )
        month_index = _month_index(payload["period_id"])
        start = _parse_utc(
            payload["start_utc"],
            label=f"monthly_rows[{index}].start_utc",
        )
        end = _parse_utc(
            payload["end_utc"],
            label=f"monthly_rows[{index}].end_utc",
        )
        if end > evaluation_as_of:
            raise PerformanceEvidenceError(
                "monthly ledger contains future-available performance"
            )
        if previous_month_index is not None and month_index != (
            previous_month_index + 1
        ):
            raise PerformanceEvidenceError(
                "monthly ledger periods must be consecutive"
            )
        if previous_end is not None and start < previous_end:
            raise PerformanceEvidenceError(
                "monthly ledger periods must not overlap"
            )
        period_return = (
            _decimal(
                payload["net_return_pct"],
                label=f"monthly_rows[{index}].net_return_pct",
            )
            / Decimal("100")
        )
        normalized_rows.append(
            {**payload, "row_sha256": raw["row_sha256"]}
        )
        returns.append(period_return)
        period_ids.append(payload["period_id"])
        previous_month_index = month_index
        previous_end = end

    rolling = {
        str(window): _rolling_window_metrics(
            period_ids=period_ids,
            returns=returns,
            window_months=window,
        )
        for window in (12, 36, 60)
    }
    objective = return_objective_payload()
    latest_60 = rolling["60"][-1] if rolling["60"] else None
    if latest_60 is None:
        objective_status = "insufficient_60_month_history"
        latest_60_cagr = None
    else:
        latest_60_cagr = (
            _annualized_cagr(returns[-60:]) * Decimal("100")
        )
        low = Decimal(
            str(objective["target_annualized_return_pct_low"])
        )
        high = Decimal(
            str(objective["target_annualized_return_pct_high"])
        )
        objective_status = (
            "below_aspirational_range"
            if latest_60_cagr < low
            else "above_aspirational_range"
            if latest_60_cagr > high
            else "within_aspirational_range"
        )

    total_twr = _twr_fraction(returns)
    receipt_without_hash = {
        "schema_version": "phase5r_rolling_monthly_performance_v1",
        "ledger_id": ledger_id.strip(),
        "policy_id": policy_id.strip(),
        "policy_sha256": policy_sha256,
        "evaluation_as_of_utc": _utc_string(evaluation_as_of),
        "ledger_row_count": len(normalized_rows),
        "ledger_sha256": canonical_sha256(normalized_rows),
        "first_period_id": period_ids[0],
        "last_period_id": period_ids[-1],
        "total_twr_pct": _rounded(
            total_twr * Decimal("100"),
            "0.0001",
        ),
        "full_period_annualized_cagr_pct": (
            _rounded(
                _annualized_cagr(returns) * Decimal("100"),
                "0.0001",
            )
            if len(returns) >= 12
            else None
        ),
        "rolling_windows": rolling,
        "dispersion": _annualized_dispersion(
            returns,
            minimum_acceptable_monthly_return=minimum_acceptable,
        ),
        "drawdown_and_recovery": _drawdown_recovery_metrics(returns),
        "return_objective_assessment": {
            "measurement_horizon": objective["measurement_horizon"],
            "latest_60_month_annualized_cagr_pct": (
                None
                if latest_60_cagr is None
                else _rounded(latest_60_cagr, "0.0001")
            ),
            "status": objective_status,
            "monthly_or_annual_quota": False,
            "return_guarantee": False,
            "risk_gates_override_allowed": False,
        },
        "measurement_only": True,
        "future_performance_claim": False,
        "broker_or_execution_capability": False,
    }
    return {
        **receipt_without_hash,
        "receipt_sha256": canonical_sha256(receipt_without_hash),
    }


__all__ = [
    "PerformanceEvidenceError",
    "REQUIRED_BASELINE_SERIES",
    "block_bootstrap_twr_ci",
    "build_monthly_performance_ledger_row",
    "cash_dividend_receipt",
    "cash_drag_receipt",
    "compare_required_baselines",
    "delisting_recovery_receipt",
    "evaluate_time_weighted_periods",
    "maximum_drawdown_pct",
    "modeled_transaction_cost_receipt",
    "rolling_monthly_performance_receipt",
    "select_next_session_paper_fill",
    "split_adjustment_receipt",
    "turnover_receipt",
]
