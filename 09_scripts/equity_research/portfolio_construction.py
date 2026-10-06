#!/usr/bin/env python3
"""Deterministic whole-portfolio sizing helpers for Phase 5R.

Uncertainty may reduce a research allocation, but it never bypasses the
minimum valuation, reward/risk, data-quality, cash-reserve, or concentration
requirements.  All results remain research scenarios for human review.
"""

from __future__ import annotations

import math
from typing import Any


def _passed_confidence(value: str, allowed: list[str]) -> bool:
    return value.strip().lower() in {item.lower() for item in allowed}


def remaining_core_floor_cost(*, account_total: float, current_core_value: float,
                              core_minimum_pct: float, core_unit_price: float | None = None) -> float:
    """Capital needed to reach the core floor at the canonical whole-share mark.

    The cash remains undeployed planning capacity, not a mandatory cash reserve.
    A missing unit price is retained only for legacy callers' dollar-gap math;
    production passes the validated SPY mark explicitly.
    """
    if any(not math.isfinite(value) or value < 0 for value in
           (account_total, current_core_value, core_minimum_pct)):
        raise ValueError("core_floor_inputs_invalid")
    gap = max(0.0, account_total * core_minimum_pct / 100.0 - current_core_value)
    if core_unit_price is None:
        return gap
    if type(core_unit_price) not in (int, float) or not math.isfinite(core_unit_price) or core_unit_price <= 0:
        raise ValueError("core_unit_price_invalid")
    return max(0, math.ceil(gap / core_unit_price - 1e-12)) * core_unit_price


def individual_sizing_decision(
    *,
    policy: dict[str, Any],
    valuation_complete: bool,
    score: float,
    confidence: str,
    expected_upside_pct: float,
    reward_to_risk: float,
    entry_score: float,
    portfolio_fit_score: float,
    current_price: float,
    account_total: float,
    deployable_cash: float,
    active_weight_pct: float,
    active_hard_cap_pct: float,
    single_stock_default_cap_pct: float | None,
    reviewed_target_pct: float | None = None,
    current_position_value: float = 0.0,
    current_core_value: float | None = None,
    core_unit_price: float | None = None,
) -> dict[str, Any]:
    """Return the highest supported sizing tier and a feasible share count."""

    tiers = policy["candidate_sizing_tiers"]
    selected: dict[str, Any] | None = None
    for tier in tiers:
        if (
            valuation_complete
            and score >= float(tier["minimum_score"])
            and _passed_confidence(confidence, list(tier["allowed_confidence"]))
            and expected_upside_pct >= float(tier["minimum_expected_upside_pct"])
            and reward_to_risk >= float(tier["minimum_reward_to_risk"])
            and entry_score >= float(tier["minimum_entry_score"])
            and portfolio_fit_score >= float(tier["minimum_portfolio_fit_score"])
        ):
            selected = tier
            break

    minimum = tiers[-1]
    gate_results = {
        "valuation": valuation_complete,
        "score": score >= float(minimum["minimum_score"]),
        "confidence": _passed_confidence(
            confidence, list(minimum["allowed_confidence"])
        ),
        "upside": expected_upside_pct
        >= float(minimum["minimum_expected_upside_pct"]),
        "reward_to_risk": reward_to_risk
        >= float(minimum["minimum_reward_to_risk"]),
        "entry": entry_score >= float(minimum["minimum_entry_score"]),
        "portfolio_fit": portfolio_fit_score
        >= float(minimum["minimum_portfolio_fit_score"]),
    }
    failed = [name for name, passed in gate_results.items() if not passed]
    if selected is None:
        return {
            "sizing_tier": "no_allocation",
            "target_position_pct": 0.0,
            "suggested_whole_shares": 0,
            "suggested_position_pct": 0.0,
            "maximum_position_value": 0.0,
            "small_account_exception_used": False,
            "concentration_limited": False,
            "failed_gates": failed,
            "gate_results": gate_results,
        }

    sourced = policy.get("sizing_method") == "source_bound_company_allocation"
    if sourced and reviewed_target_pct is None:
        return {"sizing_tier": "no_allocation", "target_position_pct": 0.0,
                "suggested_whole_shares": 0, "suggested_position_pct": 0.0,
                "maximum_position_value": 0.0, "small_account_exception_used": False,
                "concentration_limited": False, "failed_gates": ["source_bound_allocation_review_required"],
                "gate_results": {**gate_results, "allocation_review": False}}
    requested_pct = float(reviewed_target_pct if sourced else selected["target_position_pct"])
    if not math.isfinite(requested_pct) or not 0 < requested_pct <= 100:
        raise ValueError("reviewed_allocation_target_invalid")
    tier_pct = min(requested_pct, single_stock_default_cap_pct) if single_stock_default_cap_pct is not None else requested_pct
    active_headroom_value = max(
        0.0, account_total * (active_hard_cap_pct - active_weight_pct) / 100.0
    )
    core_gap = remaining_core_floor_cost(account_total=account_total,
        current_core_value=float(current_core_value or 0),
        core_minimum_pct=float(policy.get("core_minimum_pct", 0)),
        core_unit_price=core_unit_price) if sourced else 0.0
    maximum_position_value = max(0.0, min(
        max(0.0, deployable_cash - core_gap),
        max(0.0, account_total * tier_pct / 100.0 - current_position_value),
        active_headroom_value,
    ))
    shares = (
        math.floor(maximum_position_value / current_price + 1e-12)
        if current_price > 0
        else 0
    )
    small_account_exception_used = False
    one_share_pct = (
        current_price / account_total * 100.0
        if current_price > 0 and account_total > 0
        else math.inf
    )
    exception_overshoot = float(
        policy["small_account_whole_share_exception_max_overshoot_pct"]
    )
    if (
        not sourced
        and shares == 0
        and current_price > 0
        and current_price <= deployable_cash + 1e-9
        and current_price <= active_headroom_value + 1e-9
        and (single_stock_default_cap_pct is None or one_share_pct <= single_stock_default_cap_pct + 1e-9)
        and one_share_pct <= tier_pct + exception_overshoot + 1e-9
    ):
        shares = 1
        small_account_exception_used = True

    resulting_pct = (
        shares * current_price / account_total * 100.0
        if account_total > 0
        else 0.0
    )
    if shares == 0:
        failed = ["whole_share_affordability"]
    concentration_limited = (
        active_headroom_value + 1e-9 < account_total * tier_pct / 100.0
        or tier_pct + 1e-9 < requested_pct
    )
    return {
        "sizing_tier": ("source_bound_company_allocation" if sourced else selected["name"]) if shares else "no_allocation",
        "target_position_pct": tier_pct if shares else 0.0,
        "suggested_whole_shares": shares,
        "suggested_position_pct": resulting_pct,
        "maximum_position_value": maximum_position_value,
        "small_account_exception_used": small_account_exception_used,
        "concentration_limited": concentration_limited,
        "failed_gates": failed,
        "gate_results": gate_results,
    }


def core_starter_decision(
    *,
    policy: dict[str, Any],
    market_quality: str,
    technical_score: float,
    current_price: float,
    fifty_two_week_high: float,
    fifty_two_week_low: float,
    account_total: float,
    deployable_cash: float,
    current_core_value: float,
    core_target_pct: float,
    maintenance_active: bool,
) -> dict[str, Any]:
    """Size one staged broad-market core review without using stock valuation."""

    core_policy = policy["core_starter_review"]
    range_width = max(0.0, fifty_two_week_high - fifty_two_week_low)
    range_percentile = (
        (current_price - fifty_two_week_low) / range_width * 100.0
        if range_width > 0
        else 100.0
    )
    target_value = account_total * core_target_pct / 100.0
    allocation_gap = max(0.0, target_value - current_core_value)
    affordable_shares = (
        math.floor(deployable_cash / current_price + 1e-12)
        if current_price > 0
        else 0
    )
    target_gap_shares = (
        (math.ceil(allocation_gap / current_price - 1e-12) if policy.get("core_minimum_pct") is not None else math.floor(allocation_gap / current_price + 1e-12))
        if current_price > 0
        else 0
    )
    shares = min(
        int(core_policy["maximum_whole_shares_per_review"]),
        affordable_shares,
        target_gap_shares,
    )
    gate_results = {
        "market_quality": market_quality == "ok",
        "entry": technical_score >= float(core_policy["minimum_entry_score"]),
        "price_range": range_percentile
        <= float(core_policy["maximum_52_week_range_percentile"]),
        "whole_share_affordability": affordable_shares >= 1,
        "whole_share_target_gap": target_gap_shares >= 1,
        "review_capacity": int(core_policy["maximum_whole_shares_per_review"]) >= 1,
        "maintenance": not maintenance_active,
    }
    failed = [name for name, passed in gate_results.items() if not passed]
    selected = not failed
    blocked_only_by_maintenance = failed == ["maintenance"]
    return {
        "selected": selected,
        "blocked_only_by_maintenance": blocked_only_by_maintenance,
        "suggested_whole_shares": shares,
        "planned_amount": shares * current_price,
        "suggested_position_pct": (
            shares * current_price / account_total * 100.0
            if account_total > 0
            else 0.0
        ),
        "cash_after": deployable_cash - shares * current_price,
        "fifty_two_week_range_percentile": range_percentile,
        "allocation_gap_value": allocation_gap,
        "cash_affordable_shares": affordable_shares,
        "target_gap_whole_shares": target_gap_shares,
        "one_share_weight_pct": (
            current_price / account_total * 100.0 if account_total > 0 else None
        ),
        "core_weight_after_one_share_pct": (
            (current_core_value + current_price) / account_total * 100.0
            if account_total > 0 else None
        ),
        "failed_gates": failed,
        "gate_results": gate_results,
    }


__all__ = ["core_starter_decision", "individual_sizing_decision", "remaining_core_floor_cost"]
