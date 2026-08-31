#!/usr/bin/env python3
"""Deterministic, budget-aware routing for optional Phase 5R model review."""

from __future__ import annotations

from typing import Any

from phase5r_active_config import load_active_config


def route_model(
    decision: dict[str, Any],
    *,
    completed_shadow_observations: int,
    deterministic_refresh_passed: bool,
    api_authorized: bool,
    prior_terra_disagreement: bool = False,
) -> dict[str, Any]:
    config = load_active_config()
    if not deterministic_refresh_passed:
        return {"action": "no_call", "reason": "deterministic_refresh_not_passed", "model": None, "reasoning_effort": None}
    if not api_authorized:
        return {"action": "no_call", "reason": "api_authorization_absent", "model": None, "reasoning_effort": None}
    if completed_shadow_observations < 10:
        return {
            "action": "shadow_evaluation",
            "reason": "ten_observation_evaluation_window",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "maximum_output_tokens": config["model_policy"]["maximum_output_tokens"],
        }
    material_events = decision.get("material_events", [])
    conflicts = decision.get("account_conflicts", [])
    weakening = decision.get("fundamental_gate", {}).get("weakening_tickers", [])
    action_candidates = (
        decision.get("eligible_action_review_candidates", [])
        or decision.get("eligible_new_position_review_candidates", [])
    )
    if prior_terra_disagreement and action_candidates:
        return {
            "action": "shadow_escalation",
            "reason": "rare_high_impact_action_after_measured_terra_disagreement",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "maximum_output_tokens": config["model_policy"]["maximum_output_tokens"],
        }
    if weakening or conflicts:
        return {
            "action": "shadow_critic",
            "reason": "complex_fundamental_or_account_conflict",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "high",
            "maximum_output_tokens": config["model_policy"]["maximum_output_tokens"],
        }
    if material_events or action_candidates:
        return {
            "action": "shadow_critic",
            "reason": "material_filing_or_action_candidate",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "maximum_output_tokens": config["model_policy"]["maximum_output_tokens"],
        }
    return {
        "action": "no_call",
        "reason": "unchanged_or_insufficient_incremental_value",
        "model": None,
        "reasoning_effort": None,
    }


__all__ = ["route_model"]
