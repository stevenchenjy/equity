from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from phase5r_c9_common import (
    ACCOUNT_STATE,
    CASH_DEPLOYMENT_PLAN,
    DYNAMIC_WEIGHTS,
    MARKET_SNAPSHOT,
    PORTFOLIO_SUMMARY,
    TARGET_ALLOCATION_REPORT,
    append_run_log,
    as_float,
    load_account_state,
    load_active_inhibit,
    load_market_rows,
    read_csv,
    write_csv,
)


PLAN_FIELDS = [
    "plan_id",
    "asset_role",
    "ticker_or_category",
    "tranche_number",
    "planned_amount",
    "maximum_entry_condition",
    "planned_review_date",
    "cash_remaining_after",
    "core_weight_after",
    "active_stock_weight_after",
    "status",
    "reason",
    "human_confirmation_required",
]
ALLOCATION_FIELDS = [
    "asset_role",
    "current_value",
    "current_weight_pct",
    "target_weight_pct",
    "target_value",
    "allocation_gap_value",
    "policy_status",
    "calculation_basis",
]


def main() -> None:
    inhibit = load_active_inhibit()
    account = load_account_state()
    summary_rows = read_csv(PORTFOLIO_SUMMARY)
    if len(summary_rows) != 1:
        raise ValueError("C9 current portfolio summary must contain one row")
    summary = summary_rows[0]
    market = load_market_rows(["SPY"])
    spy = market["SPY"]
    spy_price = as_float(spy["last_price"], "SPY.last_price")
    account_total = as_float(account["account_total_value"], "account_total_value")
    cash = as_float(account["cash_available"], "cash_available")
    reserve = as_float(account["cash_reserved"], "cash_reserved")
    deployable_cash = cash - reserve
    active_value = as_float(summary["current_active_stock_value"], "current_active_stock_value")
    active_weight = as_float(summary["current_active_stock_weight_pct"], "current_active_stock_weight_pct")
    core_target = as_float(account["core_allocation_target_pct"], "core_allocation_target_pct")
    active_target = as_float(account["active_stock_target_pct"], "active_stock_target_pct")
    cash_target = as_float(account["cash_target_pct"], "cash_target_pct")
    review_date = (
        datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    ).isoformat()
    maintenance_active = inhibit.get("active") is True
    maintenance_status = "blocked_maintenance" if maintenance_active else "conditional_review"
    entry_condition = (
        f"SPY price <= ${spy_price:.2f}; benchmark data_quality=ok; maintenance_inhibit=false; "
        "current_account_state_valid=true; post_allocation_within_policy=true; independent_human_confirmation=yes"
    )

    plan_rows: list[dict[str, str]] = [
        {
            "plan_id": "no_deployment_until_next_review",
            "asset_role": "cash",
            "ticker_or_category": "CASH",
            "tranche_number": "0",
            "planned_amount": "0.00",
            "maximum_entry_condition": "No deployment; review fresh account and benchmark state on the planned review date.",
            "planned_review_date": review_date,
            "cash_remaining_after": f"{cash:.2f}",
            "core_weight_after": "0.0000",
            "active_stock_weight_after": f"{active_weight:.4f}",
            "status": "available_option",
            "reason": (
                "Preserves cash while maintenance is active; no purchase is selected merely because cash is available."
                if maintenance_active
                else "Preserves cash; no purchase is selected merely because cash is available."
            ),
            "human_confirmation_required": "no",
        }
    ]
    tranche_amount = 500.0
    if deployable_cash + 1e-9 < tranche_amount * 3:
        raise ValueError("confirmed deployable cash cannot support the documented three-tranche example")
    for tranche in range(1, 4):
        cumulative = tranche_amount * tranche
        cash_after = cash - cumulative
        core_weight_after = cumulative / account_total * 100.0
        plan_rows.append(
            {
                "plan_id": "three_tranche_core_plan",
                "asset_role": "core_allocation",
                "ticker_or_category": "SPY",
                "tranche_number": str(tranche),
                "planned_amount": f"{tranche_amount:.2f}",
                "maximum_entry_condition": entry_condition,
                "planned_review_date": review_date,
                "cash_remaining_after": f"{cash_after:.2f}",
                "core_weight_after": f"{core_weight_after:.4f}",
                "active_stock_weight_after": f"{active_weight:.4f}",
                "status": maintenance_status,
                "reason": (
                    (
                        "Optional broad-market core tranche; blocked while maintenance is active. "
                        if maintenance_active
                        else "Optional broad-market core tranche; not selected by the current daily decision. "
                    )
                    + "It is never automatically executable and requires a fresh independent human decision if selected."
                ),
                "human_confirmation_required": "no",
            }
        )
    partial_amount = min(1000.0, deployable_cash)
    plan_rows.append(
        {
            "plan_id": "partial_core_plus_cash_reserve",
            "asset_role": "core_allocation",
            "ticker_or_category": "SPY",
            "tranche_number": "1",
            "planned_amount": f"{partial_amount:.2f}",
            "maximum_entry_condition": entry_condition,
            "planned_review_date": review_date,
            "cash_remaining_after": f"{cash - partial_amount:.2f}",
            "core_weight_after": f"{partial_amount / account_total * 100.0:.4f}",
            "active_stock_weight_after": f"{active_weight:.4f}",
            "status": maintenance_status,
            "reason": (
                f"Optional partial core review while retaining at least the ${reserve:.2f} reserve; "
                "not a selected purchase or automatic instruction."
            ),
            "human_confirmation_required": "no",
        }
    )

    allocation_rows = [
        {
            "asset_role": "core_allocation",
            "current_value": "0.00",
            "current_weight_pct": "0.0000",
            "target_weight_pct": f"{core_target:.2f}",
            "target_value": f"{account_total * core_target / 100.0:.2f}",
            "allocation_gap_value": f"{account_total * core_target / 100.0:.2f}",
            "policy_status": "below_target_unfunded",
            "calculation_basis": "separate broad-market core sleeve; no current core holdings recorded",
        },
        {
            "asset_role": "active_stock",
            "current_value": f"{active_value:.2f}",
            "current_weight_pct": f"{active_weight:.4f}",
            "target_weight_pct": f"{active_target:.2f}",
            "target_value": f"{account_total * active_target / 100.0:.2f}",
            "allocation_gap_value": f"{account_total * active_target / 100.0 - active_value:.2f}",
            "policy_status": summary["active_stock_status"],
            "calculation_basis": "sum of held shares times canonical B2 prices divided by account total",
        },
        {
            "asset_role": "cash",
            "current_value": f"{cash:.2f}",
            "current_weight_pct": f"{cash / account_total * 100.0:.4f}",
            "target_weight_pct": f"{cash_target:.2f}",
            "target_value": f"{account_total * cash_target / 100.0:.2f}",
            "allocation_gap_value": f"{account_total * cash_target / 100.0 - cash:.2f}",
            "policy_status": summary["cash_status"],
            "calculation_basis": "reported cash_available from current_account_state.local.json",
        },
    ]
    write_csv(CASH_DEPLOYMENT_PLAN, plan_rows, PLAN_FIELDS)
    write_csv(TARGET_ALLOCATION_REPORT, allocation_rows, ALLOCATION_FIELDS)
    append_run_log(
        Path(__file__).name,
        "create_cash_deployment_and_target_allocation",
        "complete",
        [ACCOUNT_STATE, PORTFOLIO_SUMMARY, DYNAMIC_WEIGHTS, MARKET_SNAPSHOT],
        [CASH_DEPLOYMENT_PLAN, TARGET_ALLOCATION_REPORT],
        position_count=len(read_csv(DYNAMIC_WEIGHTS)),
        notes=(
            f"core_candidate=SPY; benchmark_quality={spy['data_quality_label']}; "
            f"automatic_selection=no; maintenance_blocks_deployment={'yes' if maintenance_active else 'no'}"
        ),
    )
    print(
        "Phase 5R-C9 cash deployment options complete; "
        f"deployable_cash={deployable_cash:.2f}; maintenance={maintenance_status}"
    )


if __name__ == "__main__":
    main()
