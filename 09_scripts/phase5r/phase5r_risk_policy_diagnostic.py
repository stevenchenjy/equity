#!/usr/bin/env python3
"""Offline cap arithmetic and simultaneous-shock diagnostics; never trade signals.

This module does not load account files, download prices, activate policy, or
create orders. Supplied caps are preference scenarios, not optimized parameters.
Cash must be explicit and reconcile to supplied NAV and all marked holdings.
Even confirmed-cash capacity is only arithmetic: research, evidence, pending
orders, settlement, fees, and human review remain outside this diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
from typing import Mapping, Sequence


def _decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be a finite number")
    result = Decimal(str(value))
    if not result.is_finite() or not math.isfinite(float(result)):
        raise ValueError(f"{name} must be finite")
    if result < 0 or (positive and result == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return result


def _number(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("calculated amount exceeds finite output range")
    return result


def _ticker(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ticker must be a nonempty string")
    return value.strip().upper()


@dataclass(frozen=True)
class Holding:
    ticker: str
    shares: float
    price: float
    sleeve: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _ticker(self.ticker))
        _decimal(self.shares, "shares", positive=True)
        _decimal(self.price, "price", positive=True)
        if self.sleeve not in {"active", "core"}:
            raise ValueError("sleeve must be explicitly active or core")

    @property
    def value(self) -> Decimal:
        return _decimal(self.shares, "shares") * _decimal(self.price, "price")


@dataclass(frozen=True)
class Snapshot:
    nav: float
    cash: float
    cash_reserve: float
    cash_confirmed: bool
    holdings: tuple[Holding, ...]

    def __post_init__(self) -> None:
        nav = _decimal(self.nav, "nav", positive=True)
        cash = _decimal(self.cash, "cash")
        reserve = _decimal(self.cash_reserve, "cash_reserve")
        if type(self.cash_confirmed) is not bool:
            raise ValueError("cash_confirmed must explicitly be true or false")
        if reserve > cash:
            raise ValueError("cash reserve cannot exceed entered cash")
        holdings = tuple(self.holdings)
        if any(not isinstance(item, Holding) for item in holdings):
            raise ValueError("holdings must contain Holding records")
        if len({item.ticker for item in holdings}) != len(holdings):
            raise ValueError("duplicate holding ticker")
        object.__setattr__(self, "holdings", holdings)
        marked_nav = cash + sum((item.value for item in holdings), Decimal(0))
        if abs(marked_nav - nav) > Decimal("0.01"):
            raise ValueError("NAV must reconcile to explicit cash plus marked holdings within $0.01")

    @property
    def active_value(self) -> Decimal:
        return sum((item.value for item in self.holdings if item.sleeve == "active"), Decimal(0))

    @property
    def deployable_cash(self) -> Decimal:
        return _decimal(self.cash, "cash") - _decimal(self.cash_reserve, "cash_reserve")


@dataclass(frozen=True)
class RiskPolicy:
    name: str
    active_cap_pct: float
    new_position_cap_pct: float
    held_position_cap_pct: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("policy name must be nonempty")
        active = _decimal(self.active_cap_pct, "active_cap_pct", positive=True)
        entry = _decimal(self.new_position_cap_pct, "new_position_cap_pct", positive=True)
        held = _decimal(self.held_position_cap_pct, "held_position_cap_pct", positive=True)
        if not entry <= held <= active <= 100:
            raise ValueError("caps must satisfy 0 < new position <= held position <= active <= 100")


# These scenarios are owner preference choices for comparison only. Importing
# this module cannot change the production account/configuration or its gates.
PREFERENCE_SCENARIOS = (
    RiskPolicy("existing_30_6_8", 30, 6, 8),
    RiskPolicy("moderate_50_15", 50, 15, 15),
    RiskPolicy("aggressive_70_20", 70, 20, 20),
)


def compare_policies(
    snapshot: Snapshot,
    new_candidate_prices: Mapping[str, float],
    policies: Sequence[RiskPolicy] = PREFERENCE_SCENARIOS,
) -> dict[str, object]:
    """Compare capacities independently, never sum candidate share counts.

These are upper bounds before production score/tier/evidence gates. No assumed
sale releases cash or headroom. Core holdings contribute to NAV and stress but
are not tested against individual active-stock caps. No allocations are made.
"""
    if not isinstance(snapshot, Snapshot):
        raise ValueError("snapshot must be a validated Snapshot")
    nav = _decimal(snapshot.nav, "nav")
    quotes: dict[str, Decimal] = {}
    held_tickers = {item.ticker for item in snapshot.holdings}
    for raw_ticker, value in new_candidate_prices.items():
        ticker = _ticker(raw_ticker)
        if ticker in quotes or ticker in held_tickers:
            raise ValueError("candidate tickers must be unique and not already held")
        quotes[ticker] = _decimal(value, f"{ticker} price", positive=True)
    policies = tuple(policies)
    if not policies or any(not isinstance(item, RiskPolicy) for item in policies):
        raise ValueError("at least one validated RiskPolicy is required")
    if len({item.name for item in policies}) != len(policies):
        raise ValueError("policy names must be unique")

    comparisons = []
    for policy in policies:
        active_limit = nav * _decimal(policy.active_cap_pct, "active cap") / 100
        active_headroom = max(Decimal(0), active_limit - snapshot.active_value)
        entry_limit = nav * _decimal(policy.new_position_cap_pct, "entry cap") / 100
        held_limit = nav * _decimal(policy.held_position_cap_pct, "held cap") / 100
        positions = []
        for item in snapshot.holdings:
            excess = max(Decimal(0), item.value - held_limit) if item.sleeve == "active" else Decimal(0)
            integral = _decimal(item.shares, "shares") % 1 == 0
            trim_math = int((excess / _decimal(item.price, "price")).to_integral_value(rounding=ROUND_CEILING)) if integral else None
            positions.append({
                "ticker": item.ticker,
                "sleeve": item.sleeve,
                "weight_pct": _number(item.value / nav * 100),
                "active_single_stock_cap_applies": item.sleeve == "active",
                "held_cap_excess_value": _number(excess),
                "minimum_whole_share_reduction_for_cap_math_only": trim_math,
                "action": "none_diagnostic_only",
            })
        candidates = []
        budgets = {
            "cash_after_reserve": snapshot.deployable_cash,
            "active_sleeve_headroom": active_headroom,
            "new_position_cap": entry_limit,
        }
        capacity = min(budgets.values())
        for ticker, price in quotes.items():
            shares = int((capacity / price).to_integral_value(rounding=ROUND_FLOOR))
            candidates.append({
                "ticker": ticker,
                "price": _number(price),
                "one_share_weight_pct": _number(price / nav * 100),
                "maximum_value_before_evidence_and_tier_gates": _number(capacity),
                "independent_hypothetical_whole_share_capacity": shares,
                "confirmed_cash_arithmetic_capacity": shares if snapshot.cash_confirmed else 0,
                "one_share_blockers": [name for name, budget in budgets.items() if price > budget]
                + ([] if snapshot.cash_confirmed else ["cash_unconfirmed"]),
                "limiting_budget_constraints": [name for name, budget in budgets.items() if budget == capacity],
                "order_eligible": False,
            })
        comparisons.append({
            "name": policy.name,
            "active_cap_pct": policy.active_cap_pct,
            "new_position_cap_pct": policy.new_position_cap_pct,
            "held_position_cap_pct": policy.held_position_cap_pct,
            "active_headroom_value": _number(active_headroom),
            "active_cap_excess_value": _number(max(Decimal(0), snapshot.active_value - active_limit)),
            "positions": positions,
            "new_candidates_independent_not_joint": candidates,
        })
    return {
        "status": "diagnostic_only_no_policy_activation_no_orders",
        "nav": _number(nav),
        "nav_denominator": "explicit_cash_plus_all_marked_holdings",
        "nav_reconciliation_difference": _number(nav - _decimal(snapshot.cash, "cash") - sum((item.value for item in snapshot.holdings), Decimal(0))),
        "cash_confirmed": snapshot.cash_confirmed,
        "deployable_cash_entered_basis": _number(snapshot.deployable_cash),
        "active_value": _number(snapshot.active_value),
        "active_weight_pct": _number(snapshot.active_value / nav * 100),
        "comparisons": comparisons,
        "limitations": [
            "Caps are preference scenarios, not empirically optimal or forecasts of returns.",
            "Candidate capacities are alternatives, not jointly fundable orders or buy recommendations.",
            "Evidence, tier, fees, settlement and pending-order checks are not evaluated; no hypothetical sales are assumed.",
            "Unconfirmed cash remains an entered estimate; planned funding is never inferred.",
            "Changing caps alone does not change holdings or portfolio stress losses.",
        ],
    }


def simultaneous_stress(snapshot: Snapshot, shocks_pct: Mapping[str, float]) -> dict[str, object]:
    """Apply explicit per-ticker price shocks simultaneously, keeping cash fixed.

Every holding needs a supplied shock (zero must be explicit); losses cannot
exceed 100% of a long holding. This models coincident shocks, not an estimated
correlation matrix, VaR, probability, backtest, realized drawdown, or forecast.
No leverage, rebalancing, tax, fills, costs, or future cash inflows are assumed.
"""
    if not isinstance(snapshot, Snapshot):
        raise ValueError("snapshot must be a validated Snapshot")
    shocks: dict[str, Decimal] = {}
    for raw_ticker, value in shocks_pct.items():
        ticker = _ticker(raw_ticker)
        if ticker in shocks:
            raise ValueError("duplicate normalized shock ticker")
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError("shock must be a finite number")
        shock = Decimal(str(value))
        if not shock.is_finite() or not math.isfinite(float(shock)) or shock < -100:
            raise ValueError("shock must be finite and at least -100 percent")
        shocks[ticker] = shock
    if set(shocks) != {item.ticker for item in snapshot.holdings}:
        raise ValueError("supply exactly one shock for every holding; do not omit core holdings")
    effects = []
    total_pnl = Decimal(0)
    for item in snapshot.holdings:
        pnl = item.value * shocks[item.ticker] / 100
        total_pnl += pnl
        effects.append({
            "ticker": item.ticker,
            "starting_value": _number(item.value),
            "shock_pct": _number(shocks[item.ticker]),
            "pnl": _number(pnl),
            "ending_value": _number(item.value + pnl),
        })
    nav = _decimal(snapshot.nav, "nav")
    return {
        "status": "hypothetical_simultaneous_shocks_not_var_backtest_or_forecast",
        "cash_confirmed": snapshot.cash_confirmed,
        "starting_nav_including_cash": _number(nav),
        "cash_unchanged": snapshot.cash,
        "total_pnl": _number(total_pnl),
        "ending_nav": _number(nav + total_pnl),
        "loss_pct_of_starting_nav": _number(max(Decimal(0), -total_pnl) / nav * 100),
        "pnl_pct_of_starting_nav": _number(total_pnl / nav * 100),
        "positions": effects,
        "assumptions": [
            "All supplied shocks occur at the same time; no diversification credit is inferred.",
            "Cash including reserve is unchanged and included in the NAV denominator.",
            "No shock probability, correlation estimate, expected return, trading cost, or transaction is modeled.",
            "Unconfirmed cash makes the account-level result an estimated-input scenario.",
        ],
    }
