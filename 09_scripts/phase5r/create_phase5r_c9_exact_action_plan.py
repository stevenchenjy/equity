from __future__ import annotations

import math
from pathlib import Path

from phase5r_c9_common import (
    ACCOUNT_STATE,
    C5_PACKETS,
    CURRENT_POSITIONS,
    DYNAMIC_WEIGHTS,
    EXACT_ACTION_PLAN,
    REVIEW_QUEUE,
    append_run_log,
    as_float,
    load_account_state,
    load_active_inhibit,
    load_packets,
    load_positions,
    read_csv,
    write_csv,
)


ACTION_FIELDS = [
    "ticker",
    "asset_role",
    "current_shares",
    "current_price",
    "current_value",
    "current_weight_pct",
    "current_label",
    "recommended_action",
    "target_weight_pct",
    "target_value",
    "whole_shares_to_change",
    "target_shares",
    "estimated_cash_change",
    "resulting_weight_pct",
    "holding_horizon",
    "maximum_buy_price",
    "trim_price_or_condition",
    "invalidation_price_or_condition",
    "recommendation_confidence",
    "reason",
    "human_confirmation_required",
    "automatic_action_allowed",
]
REVIEW_FIELDS = [
    "priority",
    "ticker",
    "asset_role",
    "current_weight_pct",
    "concentration_status",
    "current_research_score",
    "current_label",
    "recommended_action",
    "whole_share_scenario",
    "next_review_condition",
    "human_confirmation_required",
    "automatic_action_allowed",
]
ALLOWED_ACTIONS = {
    "hold",
    "trim_specific_shares_review",
    "add_specific_dollars_review",
    "core_allocation_tranche_review",
    "wait_for_pullback",
    "watch_only",
    "reject",
    "exit_review",
}


def main() -> None:
    load_active_inhibit()
    account = load_account_state()
    positions = {str(row["ticker"]): row for row in load_positions()}
    packets = load_packets()
    weights = read_csv(DYNAMIC_WEIGHTS)
    account_total = as_float(account["account_total_value"], "account_total_value")
    hard_cap = as_float(account["single_stock_hard_cap_pct"], "single_stock_hard_cap_pct")
    cap_value = account_total * hard_cap / 100.0

    actions: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    for weight_row in weights:
        ticker = weight_row["ticker"]
        position = positions[ticker]
        packet = packets[ticker]
        shares = as_float(weight_row["current_shares"], f"{ticker}.current_shares")
        price = as_float(weight_row["latest_price"], f"{ticker}.latest_price")
        value = as_float(weight_row["current_value"], f"{ticker}.current_value")
        weight = as_float(weight_row["current_weight_pct"], f"{ticker}.current_weight_pct")
        label = weight_row["current_recommendation_label"]

        if label == "exit_review":
            recommended_action = "exit_review"
            change = math.ceil(shares - 1e-9)
            target_shares = 0.0
            target_weight = 0.0
            target_value = 0.0
            cash_change = value
            resulting_weight = 0.0
            reason = "Current research score requires an independent exit review; no automatic transaction is allowed."
            trim_condition = "Exit review only if the documented thesis or evidence is materially impaired and a human confirms."
        elif weight > hard_cap + 1e-9:
            maximum_whole_shares = max(0, math.floor(cap_value / price + 1e-12))
            change = max(0, math.ceil(shares - maximum_whole_shares - 1e-9))
            target_shares = max(0.0, shares - change)
            target_weight = hard_cap
            target_value = cap_value
            cash_change = change * price
            resulting_weight = target_shares * price / account_total * 100.0
            recommended_action = "trim_specific_shares_review"
            reason = (
                f"Dynamic weight {weight:.4f}% exceeds the {hard_cap:.2f}% hard cap; "
                f"reducing {change} whole share(s) is the minimum current-price scenario at or below the cap."
            )
            trim_condition = (
                f"Review only while refreshed weight remains above {hard_cap:.2f}%; "
                f"at ${price:.2f}, the minimum whole-share scenario reduces {change} share(s)."
            )
        else:
            recommended_action = "hold"
            change = 0
            target_shares = shares
            target_weight = weight
            target_value = value
            cash_change = 0.0
            resulting_weight = weight
            reason = (
                f"Dynamic weight {weight:.4f}% is at or below the {hard_cap:.2f}% hard cap; "
                "no concentration-only trim is recommended, and no add is recommended today."
            )
            trim_condition = (
                f"Reopen trim review only if refreshed weight rises above {hard_cap:.2f}% or independent research evidence weakens."
            )

        if recommended_action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported C9 action {recommended_action}")
        action_row = {
            "ticker": ticker,
            "asset_role": "active_stock",
            "current_shares": f"{shares:.4f}",
            "current_price": f"{price:.2f}",
            "current_value": f"{value:.2f}",
            "current_weight_pct": f"{weight:.4f}",
            "current_label": label,
            "recommended_action": recommended_action,
            "target_weight_pct": f"{target_weight:.4f}",
            "target_value": f"{target_value:.2f}",
            "whole_shares_to_change": str(change),
            "target_shares": f"{target_shares:.4f}",
            "estimated_cash_change": f"{cash_change:.2f}",
            "resulting_weight_pct": f"{resulting_weight:.4f}",
            "holding_horizon": str(position["horizon_class"]),
            "maximum_buy_price": "",
            "trim_price_or_condition": trim_condition,
            "invalidation_price_or_condition": str(position["invalidation_rule"]),
            "recommendation_confidence": packet["recommendation_confidence"],
            "reason": reason,
            "human_confirmation_required": (
                "yes" if recommended_action in {"exit_review", "trim_specific_shares_review", "add_specific_dollars_review"} else "no"
            ),
            "automatic_action_allowed": "no",
        }
        actions.append(action_row)
        reviews.append(
            {
                "priority": "1" if recommended_action in {"exit_review", "trim_specific_shares_review"} else "2",
                "ticker": ticker,
                "asset_role": "active_stock",
                "current_weight_pct": f"{weight:.4f}",
                "concentration_status": weight_row["concentration_status"],
                "current_research_score": weight_row["current_research_score"],
                "current_label": label,
                "recommended_action": recommended_action,
                "whole_share_scenario": (
                    f"change={change}; target_shares={target_shares:.4f}; resulting_weight_pct={resulting_weight:.4f}"
                ),
                "next_review_condition": trim_condition,
                "human_confirmation_required": (
                "yes" if recommended_action in {"exit_review", "trim_specific_shares_review", "add_specific_dollars_review"} else "no"
            ),
                "automatic_action_allowed": "no",
            }
        )

    actions.sort(key=lambda row: (row["recommended_action"] != "trim_specific_shares_review", -float(row["current_weight_pct"])))
    reviews.sort(key=lambda row: (int(row["priority"]), -float(row["current_weight_pct"])))
    write_csv(EXACT_ACTION_PLAN, actions, ACTION_FIELDS)
    write_csv(REVIEW_QUEUE, reviews, REVIEW_FIELDS)
    append_run_log(
        Path(__file__).name,
        "create_exact_action_plan",
        "complete",
        [ACCOUNT_STATE, CURRENT_POSITIONS, DYNAMIC_WEIGHTS, C5_PACKETS],
        [EXACT_ACTION_PLAN, REVIEW_QUEUE],
        position_count=len(actions),
        notes="whole_share_scenarios_dynamic=yes; adds_to_current_positions=no; manual_confirmation=action_transitions_only",
    )
    print(f"Phase 5R-C9 exact action plan complete; position_actions={len(actions)}")


if __name__ == "__main__":
    main()
