from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from phase5r_active_config import load_active_config
from phase5r_c9_common import (
    ACCOUNT_STATE,
    CASH_DEPLOYMENT_PLAN,
    DYNAMIC_WEIGHTS,
    EXACT_ACTION_PLAN,
    MARKET_SNAPSHOT,
    PORTFOLIO_SUMMARY,
    POST_ACTION_PORTFOLIO,
    TARGET_ALLOCATION_REPORT,
    append_run_log,
    as_float,
    load_account_state,
    load_active_inhibit,
    load_market_rows,
    load_packets,
    load_portfolio_summary,
    read_csv,
    write_csv,
)
from phase5r_portfolio_construction import core_starter_decision


PLAN_FIELDS = [
    "plan_id", "asset_role", "ticker_or_category", "tranche_number",
    "planned_shares", "planned_amount", "sizing_tier",
    "maximum_entry_condition", "planned_review_date", "estimated_cash_released",
    "cash_remaining_after", "core_weight_after", "active_stock_weight_after",
    "fifty_two_week_range_percentile", "status", "cash_rationale", "reason",
    "human_confirmation_required",
]
ALLOCATION_FIELDS = [
    "asset_role", "current_value", "current_weight_pct", "target_weight_pct",
    "target_value", "allocation_gap_value", "policy_status", "calculation_basis",
]
POST_ACTION_FIELDS = [
    "scenario", "current_cash", "estimated_released_cash", "proposed_core_ticker",
    "proposed_core_shares", "proposed_core_value", "resulting_active_value",
    "resulting_core_value", "resulting_cash", "active_weight_pct",
    "core_weight_pct", "cash_weight_pct", "retained_cash_reason", "status",
    "automatic_action_allowed",
]


def _post_action_row(
    *, scenario: str, account_total: float, current_cash: float,
    released_cash: float, core_ticker: str, core_shares: int, core_price: float,
    active_value: float, status: str, retained_cash_reason: str,
) -> dict[str, str]:
    core_value = core_shares * core_price
    resulting_cash = current_cash + released_cash - core_value
    if resulting_cash < -1e-9:
        raise ValueError("post-action scenario cannot use more cash than available")
    return {
        "scenario": scenario,
        "current_cash": f"{current_cash:.2f}",
        "estimated_released_cash": f"{released_cash:.2f}",
        "proposed_core_ticker": core_ticker,
        "proposed_core_shares": str(core_shares),
        "proposed_core_value": f"{core_value:.2f}",
        "resulting_active_value": f"{active_value:.2f}",
        "resulting_core_value": f"{core_value:.2f}",
        "resulting_cash": f"{resulting_cash:.2f}",
        "active_weight_pct": f"{active_value / account_total * 100.0:.4f}",
        "core_weight_pct": f"{core_value / account_total * 100.0:.4f}",
        "cash_weight_pct": f"{resulting_cash / account_total * 100.0:.4f}",
        "retained_cash_reason": retained_cash_reason,
        "status": status,
        "automatic_action_allowed": "no",
    }


def main() -> None:
    inhibit = load_active_inhibit()
    account = load_account_state()
    summary = load_portfolio_summary()
    construction_policy = load_active_config()["account"]
    spy = load_market_rows(["SPY"])["SPY"]
    spy_price = as_float(spy["last_price"], "SPY.last_price")
    spy_high = as_float(spy["fifty_two_week_high"], "SPY.fifty_two_week_high")
    spy_low = as_float(spy["fifty_two_week_low"], "SPY.fifty_two_week_low")
    spy_packet = load_packets()["SPY"]
    spy_technical = as_float(
        spy_packet["technical_entry_discipline_score"], "SPY.technical"
    )
    account_total = as_float(summary["account_total_value"], "account_total_value")
    cash = as_float(summary["cash_available"], "cash_available")
    reserve = as_float(summary["cash_reserved"], "cash_reserved")
    deployable_cash = as_float(summary["deployable_cash"], "deployable_cash")
    active_value = as_float(
        summary["current_active_stock_value"], "current_active_stock_value"
    )
    active_weight = as_float(
        summary["current_active_stock_weight_pct"], "current_active_stock_weight_pct"
    )
    current_core = as_float(summary["current_core_value"], "current_core_value")
    core_target = as_float(account["core_allocation_target_pct"], "core_target")
    active_target = as_float(account["active_stock_target_pct"], "active_target")
    cash_target = as_float(account["cash_target_pct"], "cash_target")
    review_date = (
        datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    ).isoformat()
    maintenance_active = inhibit.get("active") is True
    core = core_starter_decision(
        policy=construction_policy,
        market_quality=spy["data_quality_label"],
        technical_score=spy_technical,
        current_price=spy_price,
        fifty_two_week_high=spy_high,
        fifty_two_week_low=spy_low,
        account_total=account_total,
        deployable_cash=deployable_cash,
        current_core_value=current_core,
        core_target_pct=core_target,
        maintenance_active=maintenance_active,
    )
    shares = int(core["suggested_whole_shares"])
    planned_amount = shares * spy_price
    core_status = (
        "selected_review" if core["selected"] else
        "blocked_maintenance" if core["blocked_only_by_maintenance"] else
        "not_selected"
    )
    cash_rationale = (
        f"${reserve:.2f} is the strategic reserve; the remaining cash is staged capital. "
        "Individual stocks must still pass source-bound valuation and reward/risk gates; "
        "whole-share constraints are calculated explicitly rather than leaving an accidental residual."
    )
    failed_text = ",".join(core["failed_gates"]) or "none"
    core_policy = construction_policy["core_starter_review"]
    entry_condition = (
        f"SPY price <= ${spy_price:.2f}; data_quality=ok; technical_score >= "
        f"{core_policy['minimum_entry_score']}; "
        f"52-week range percentile <= {core_policy['maximum_52_week_range_percentile']}%; "
        "maintenance_inhibit=false; reserve_preserved=true; independent_human_confirmation=yes"
    )
    core_pct = planned_amount / account_total * 100.0

    plan_rows = [
        {
            "plan_id": "retain_cash_fallback", "asset_role": "cash",
            "ticker_or_category": "CASH", "tranche_number": "0",
            "planned_shares": "0", "planned_amount": "0.00",
            "sizing_tier": "no_allocation",
            "maximum_entry_condition": "Retain cash if any core or individual evidence gate fails before review.",
            "planned_review_date": review_date, "estimated_cash_released": "0.00",
            "cash_remaining_after": f"{cash:.2f}",
            "core_weight_after": f"{current_core / account_total * 100.0:.4f}",
            "active_stock_weight_after": f"{active_weight:.4f}",
            "fifty_two_week_range_percentile": f"{core['fifty_two_week_range_percentile']:.2f}",
            "status": "fallback_option" if core["selected"] else "selected_cash_retention",
            "cash_rationale": cash_rationale,
            "reason": (
                "Fail-closed cash alternative. It becomes the selected conclusion whenever refreshed "
                f"core gates fail (current failed gates: {failed_text})."
            ),
            "human_confirmation_required": "no",
        },
        {
            "plan_id": "core_starter_whole_share_review",
            "asset_role": "core_allocation", "ticker_or_category": "SPY",
            "tranche_number": "1", "planned_shares": str(shares),
            "planned_amount": f"{planned_amount:.2f}",
            "sizing_tier": "starter_allocation" if shares else "no_allocation",
            "maximum_entry_condition": entry_condition,
            "planned_review_date": review_date, "estimated_cash_released": "0.00",
            "cash_remaining_after": f"{cash - planned_amount:.2f}",
            "core_weight_after": f"{(current_core + planned_amount) / account_total * 100.0:.4f}",
            "active_stock_weight_after": f"{active_weight:.4f}",
            "fifty_two_week_range_percentile": f"{core['fifty_two_week_range_percentile']:.2f}",
            "status": core_status, "cash_rationale": cash_rationale,
            "reason": (
                f"One feasible whole-share core starter is {core_pct:.2f}% of the dynamic account. "
                f"SPY is at the {core['fifty_two_week_range_percentile']:.2f}th percentile of its "
                "52-week range, so the proposal is staged rather than sized to the full "
                f"{core_target:.0f}% policy target. Failed gates: {failed_text}."
            ),
            "human_confirmation_required": (
                "yes" if core_status == "selected_review" else "no"
            ),
        },
    ]

    actions = read_csv(EXACT_ACTION_PLAN)
    released_cash = sum(
        as_float(row["estimated_cash_change"], f"{row['ticker']}.estimated_cash_change")
        for row in actions
        if row["recommended_action"] in {"trim_specific_shares_review", "exit_review"}
    )
    active_after_reviews = sum(
        as_float(row["target_shares"], f"{row['ticker']}.target_shares")
        * as_float(row["current_price"], f"{row['ticker']}.current_price")
        for row in actions
    )
    selected_core_shares = shares if core["selected"] else 0
    post_rows = [
        _post_action_row(
            scenario="current_portfolio", account_total=account_total,
            current_cash=cash, released_cash=0.0, core_ticker="", core_shares=0,
            core_price=spy_price, active_value=active_value, status="current",
            retained_cash_reason="Current cash includes the strategic reserve and capital not yet assigned by evidence-supported reviews.",
        ),
        _post_action_row(
            scenario="after_current_position_reviews", account_total=account_total,
            current_cash=cash, released_cash=released_cash, core_ticker="",
            core_shares=0, core_price=spy_price, active_value=active_after_reviews,
            status="hypothetical_human_reviews_only",
            retained_cash_reason="Released capital remains cash unless a separate opportunity passes its own current gates.",
        ),
        _post_action_row(
            scenario="after_position_and_core_reviews", account_total=account_total,
            current_cash=cash, released_cash=released_cash,
            core_ticker="SPY" if selected_core_shares else "",
            core_shares=selected_core_shares, core_price=spy_price,
            active_value=active_after_reviews,
            status="hypothetical_selected_reviews" if selected_core_shares else "core_not_selected",
            retained_cash_reason=(
                f"Retains the ${reserve:.2f} strategic reserve plus staged cash because no individual-stock "
                "candidate may receive capital without independent valuation and reward/risk support."
            ),
        ),
    ]

    allocation_rows = [
        {
            "asset_role": "core_allocation", "current_value": f"{current_core:.2f}",
            "current_weight_pct": f"{current_core / account_total * 100.0:.4f}",
            "target_weight_pct": f"{core_target:.2f}",
            "target_value": f"{account_total * core_target / 100.0:.2f}",
            "allocation_gap_value": f"{account_total * core_target / 100.0 - current_core:.2f}",
            "policy_status": "below_target_starter_review" if core["selected"] else "below_target_unfunded",
            "calculation_basis": "dynamic effective total; whole-share core review is staged and never automatic",
        },
        {
            "asset_role": "active_stock", "current_value": f"{active_value:.2f}",
            "current_weight_pct": f"{active_weight:.4f}",
            "target_weight_pct": f"{active_target:.2f}",
            "target_value": f"{account_total * active_target / 100.0:.2f}",
            "allocation_gap_value": f"{account_total * active_target / 100.0 - active_value:.2f}",
            "policy_status": summary["active_stock_status"],
            "calculation_basis": "current shares times canonical close divided by dynamic effective total",
        },
        {
            "asset_role": "cash", "current_value": f"{cash:.2f}",
            "current_weight_pct": f"{cash / account_total * 100.0:.4f}",
            "target_weight_pct": f"{cash_target:.2f}",
            "target_value": f"{account_total * cash_target / 100.0:.2f}",
            "allocation_gap_value": f"{account_total * cash_target / 100.0 - cash:.2f}",
            "policy_status": summary["cash_status"],
            "calculation_basis": "manual cash divided by dynamic cash-plus-current-holdings total",
        },
    ]
    write_csv(CASH_DEPLOYMENT_PLAN, plan_rows, PLAN_FIELDS)
    write_csv(TARGET_ALLOCATION_REPORT, allocation_rows, ALLOCATION_FIELDS)
    write_csv(POST_ACTION_PORTFOLIO, post_rows, POST_ACTION_FIELDS)
    append_run_log(
        Path(__file__).name, "create_cash_deployment_and_target_allocation", "complete",
        [ACCOUNT_STATE, PORTFOLIO_SUMMARY, DYNAMIC_WEIGHTS, MARKET_SNAPSHOT, EXACT_ACTION_PLAN],
        [CASH_DEPLOYMENT_PLAN, TARGET_ALLOCATION_REPORT, POST_ACTION_PORTFOLIO],
        position_count=len(read_csv(DYNAMIC_WEIGHTS)),
        notes=(
            f"core_candidate=SPY; core_status={core_status}; proposed_whole_shares={shares}; "
            f"estimated_released_cash={released_cash:.2f}; automatic_selection=no"
        ),
    )
    print(
        "Phase 5R-C9 capital allocation complete; "
        f"dynamic_total={account_total:.2f}; core_status={core_status}; "
        f"core_shares={shares}; released_cash_scenario={released_cash:.2f}"
    )


if __name__ == "__main__":
    main()
