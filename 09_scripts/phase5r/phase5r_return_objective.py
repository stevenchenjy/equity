#!/usr/bin/env python3
"""Deterministic Phase 5R long-horizon return-objective constants.

This module defines a measurement objective only.  It has no market, model,
email, broker, account-write, order, or execution capability.
"""

from __future__ import annotations

from typing import Any


TARGET_ANNUALIZED_RETURN_PCT_LOW = 12.0
TARGET_ANNUALIZED_RETURN_PCT_HIGH = 15.0
EXCELLENT_CALENDAR_YEAR_PCT_LOW = 15.0
EXCELLENT_CALENDAR_YEAR_PCT_HIGH = 20.0


def annualized_to_monthly_compound_pct(annualized_pct: float) -> float:
    """Return the exact monthly compound equivalent, rounded to four decimals."""

    if annualized_pct <= -100:
        raise ValueError("annualized return must be greater than -100%")
    return round(
        ((1.0 + annualized_pct / 100.0) ** (1.0 / 12.0) - 1.0) * 100.0,
        4,
    )


def return_objective_payload() -> dict[str, Any]:
    """Return the closed, non-guaranteed objective embedded in model packets."""

    return {
        "measurement_horizon": "rolling_5_year_net_total_return",
        "target_annualized_return_pct_low": TARGET_ANNUALIZED_RETURN_PCT_LOW,
        "target_annualized_return_pct_high": TARGET_ANNUALIZED_RETURN_PCT_HIGH,
        "equivalent_monthly_compound_pct_low": annualized_to_monthly_compound_pct(
            TARGET_ANNUALIZED_RETURN_PCT_LOW
        ),
        "equivalent_monthly_compound_pct_high": annualized_to_monthly_compound_pct(
            TARGET_ANNUALIZED_RETURN_PCT_HIGH
        ),
        "excellent_calendar_year_pct_low": EXCELLENT_CALENDAR_YEAR_PCT_LOW,
        "excellent_calendar_year_pct_high": EXCELLENT_CALENDAR_YEAR_PCT_HIGH,
        "monthly_or_annual_quota": False,
        "return_guarantee": False,
        "risk_gates_override_allowed": False,
    }


def validate_return_objective_payload(value: Any) -> dict[str, Any]:
    """Reject any drift that turns the objective into a quota or guarantee."""

    expected = return_objective_payload()
    if not isinstance(value, dict) or value != expected:
        raise ValueError("return objective does not match the closed policy")
    return value
