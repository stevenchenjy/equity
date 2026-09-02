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
    single_stock_default_cap_pct: float,
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

    tier_pct = min(
        float(selected["target_position_pct"]),
        single_stock_default_cap_pct,
    )
    active_headroom_value = max(
        0.0, account_total * (active_hard_cap_pct - active_weight_pct) / 100.0
    )
    maximum_position_value = min(
        deployable_cash,
        account_total * tier_pct / 100.0,
        active_headroom_value,
    )
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
        shares == 0
        and current_price > 0
        and current_price <= deployable_cash + 1e-9
        and current_price <= active_headroom_value + 1e-9
        and one_share_pct <= single_stock_default_cap_pct + 1e-9
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
        or tier_pct + 1e-9 < float(selected["target_position_pct"])
    )
    return {
        "sizing_tier": selected["name"] if shares else "no_allocation",
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
    score: float,
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
        math.floor(allocation_gap / current_price + 1e-12)
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
        "score": score >= float(core_policy["minimum_score"]),
        "entry": technical_score >= float(core_policy["minimum_entry_score"]),
        "price_range": range_percentile
        <= float(core_policy["maximum_52_week_range_percentile"]),
        "whole_share_affordability": shares >= 1,
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
        "failed_gates": failed,
        "gate_results": gate_results,
    }


__all__ = ["core_starter_decision", "individual_sizing_decision"]
