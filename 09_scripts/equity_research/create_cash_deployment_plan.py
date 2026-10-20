from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from active_config import load_active_config
from account_common import (
    ACCOUNT_STATE,
    CASH_DEPLOYMENT_PLAN,
    DYNAMIC_WEIGHTS,
    EXACT_ACTION_PLAN,
    MARKET_SNAPSHOT,
    PORTFOLIO_SUMMARY,
    POST_ACTION_PORTFOLIO,
    TARGET_ALLOCATION_REPORT,
    append_run_log,
    approved_core_tickers,
    is_core_allocation_ticker,
    as_float,
    load_research_account_state,
    load_active_inhibit,
    load_market_rows,
    load_packets,
    load_portfolio_summary,
    read_csv,
    write_csv,
)
from portfolio_construction import core_starter_decision
from daily_common import latest_published_market_session, now_et


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
    current_core_value: float, active_value: float, status: str,
    retained_cash_reason: str,
) -> dict[str, str]:
    proposed_core_value = core_shares * core_price
    resulting_core_value = current_core_value + proposed_core_value
    resulting_cash = current_cash + released_cash - proposed_core_value
    if resulting_cash < -1e-9:
        raise ValueError("post-action scenario cannot use more cash than available")
    return {
        "scenario": scenario,
        "current_cash": f"{current_cash:.2f}",
        "estimated_released_cash": f"{released_cash:.2f}",
        "proposed_core_ticker": core_ticker,
        "proposed_core_shares": str(core_shares),
        "proposed_core_value": f"{proposed_core_value:.2f}",
        "resulting_active_value": f"{active_value:.2f}",
        "resulting_core_value": f"{resulting_core_value:.2f}",
        "resulting_cash": f"{resulting_cash:.2f}",
        "active_weight_pct": f"{active_value / account_total * 100.0:.4f}",
        "core_weight_pct": f"{resulting_core_value / account_total * 100.0:.4f}",
        "cash_weight_pct": f"{resulting_cash / account_total * 100.0:.4f}",
        "retained_cash_reason": retained_cash_reason,
        "status": status,
        "automatic_action_allowed": "no",
    }


def main() -> None:
    inhibit = load_active_inhibit()
    account = load_research_account_state()
    summary = load_portfolio_summary()
    construction_policy = load_active_config()["account"]
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
    core_minimum = account.get("core_minimum_pct")
    core_threshold = as_float(core_minimum, "core_minimum_pct") if core_minimum is not None else core_target
    core_threshold_met = current_core + 1e-9 >= account_total * core_threshold / 100.0
    active_target = as_float(account["active_stock_target_pct"], "active_target")
    cash_target = as_float(account["cash_target_pct"], "cash_target")
    review_date = (
        datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    ).isoformat()
    maintenance_active = inhibit.get("active") is True
    # Evaluate each approved fund independently. A bad unheld alternative must
    # not block another fund, and alternatives never share the same buy quantity.
    options = []
    packets = load_packets()
    expected_session = latest_published_market_session(now_et()).isoformat()
    for ticker in approved_core_tickers():
        source_issue = ""
        price = 0.0
        try:
            if not is_core_allocation_ticker(ticker):
                raise ValueError("approved core fund metadata is unverified")
            market = load_market_rows([ticker])[ticker]
            if market.get("market_session_date") != expected_session:
                raise ValueError(f"completed close for {expected_session} is required")
            price = as_float(market["last_price"], f"{ticker}.last_price")
            high = as_float(market["fifty_two_week_high"], f"{ticker}.fifty_two_week_high")
            low = as_float(market["fifty_two_week_low"], f"{ticker}.fifty_two_week_low")
            technical = as_float(packets[ticker]["technical_entry_discipline_score"], f"{ticker}.technical")
            if price <= 0 or high <= 0 or low < 0 or high <= low:
                raise ValueError("positive price and ordered 52-week range required")
            review = core_starter_decision(
                policy=construction_policy, market_quality=market["data_quality_label"],
                technical_score=technical, current_price=price,
                fifty_two_week_high=high, fifty_two_week_low=low,
                account_total=account_total, deployable_cash=deployable_cash,
                current_core_value=current_core, core_target_pct=core_target,
                maintenance_active=maintenance_active,
            )
        except (KeyError, ValueError, OSError) as exc:
            source_issue = str(exc)
            review = {"selected": False, "blocked_only_by_maintenance": False,
                      "suggested_whole_shares": 0, "fifty_two_week_range_percentile": None,
                      "cash_affordable_shares": 0, "target_gap_whole_shares": 0,
                      "failed_gates": ["core_market_or_entry_evidence_unverified"]}
        options.append({"ticker": ticker, "price": price, "review": review, "source_issue": source_issue})
    # Configuration order retains the existing SPY-first starter preference.
    # Approval to count either fund does not imply an automatic rotation or a
    # second tranche when the combined floor is already satisfied.
    selected = next((option for option in options if option["review"]["selected"]
                     and not core_threshold_met), None)
    chosen = selected or options[0]
    core = chosen["review"]
    core_ticker = chosen["ticker"]
    core_price = chosen["price"]
    shares = int(core["suggested_whole_shares"]) if selected else 0
    core_status = ("minimum_satisfied" if core_minimum is not None and core_threshold_met else
                   "target_satisfied" if core_threshold_met else
                   "selected_review" if selected else "not_selected")
    cash_rationale = (
        f"${reserve:.2f} is the mandatory internal reserve; the remaining cash is available for qualified opportunities. "
        "Individual stocks must still pass source-bound valuation and reward/risk gates; "
        "whole-share constraints and the combined index-core floor are calculated explicitly."
    )
    failures = "; ".join(option["ticker"] + ":" + ",".join(option["review"]["failed_gates"])
                         for option in options if option["review"]["failed_gates"])
    plan_rows = [{
        "plan_id": "retain_cash_fallback", "asset_role": "cash",
        "ticker_or_category": "CASH", "tranche_number": "0",
        "planned_shares": "0", "planned_amount": "0.00", "sizing_tier": "no_allocation",
        "maximum_entry_condition": "Retain unassigned cash until a separate opportunity passes its current gates.",
        "planned_review_date": review_date, "estimated_cash_released": "0.00",
        "cash_remaining_after": f"{cash:.2f}",
        "core_weight_after": f"{current_core / account_total * 100.0:.4f}",
        "active_stock_weight_after": f"{active_weight:.4f}",
        "fifty_two_week_range_percentile": "",
        "status": "available_for_qualified_opportunities" if core_threshold_met else
                  "fallback_option" if selected else "selected_cash_retention",
        "cash_rationale": cash_rationale,
        "reason": (
            f"Combined index core already meets the {core_threshold:.0f}% "
            f"{'minimum' if core_minimum is not None else 'target'}. Remaining cash is available for "
            "independently qualified opportunities; no extra cash reserve is imposed by this status."
        ) if core_threshold_met else (
            "Each approved index fund is evaluated separately; only one starter can use the shared cash budget. "
            f"Current fund checks: {failures or 'none'}."
        ), "human_confirmation_required": "no",
    }]
    core_policy = construction_policy["core_starter_review"]
    for option in options:
        ticker, price, review = option["ticker"], option["price"], option["review"]
        status = ("minimum_satisfied" if core_minimum is not None and core_threshold_met else
                  "target_satisfied" if core_threshold_met else
                  "selected_review" if option is selected else
                  "alternative_not_selected" if review["selected"] else
                  "blocked_maintenance" if review["blocked_only_by_maintenance"] else "not_selected")
        quantity = int(review["suggested_whole_shares"]) if option is selected else 0
        amount = quantity * price
        failed = list(review["failed_gates"])
        if status == "alternative_not_selected":
            failed.append("shared_core_starter_alternative_not_selected")
        failed_text = ",".join(failed) or "none"
        percentile = review["fifty_two_week_range_percentile"]
        entry_condition = (
            f"{ticker} price <= ${price:.2f}; data_quality=ok; technical_score >= "
            f"{core_policy['minimum_entry_score']}; "
            f"52-week range percentile <= {core_policy['maximum_52_week_range_percentile']}%; "
            "maintenance_inhibit=false; reserve_preserved=true; independent_human_confirmation=yes"
        ) if not option["source_issue"] else f"{ticker}: restore validated market and entry evidence before evaluating any buy price."
        reason = (
            f"Combined index core weight {current_core / account_total * 100.0:.4f}% meets the "
            f"{core_threshold:.0f}% {'minimum' if core_minimum is not None else 'target'}. "
            "No additional core tranche is proposed; exceeding a core minimum is not a trim instruction."
        ) if core_threshold_met else (
            f"{ticker}: {quantity} whole-share(s) selected from a shared one-fund starter review. "
            f"Cash can fund {review['cash_affordable_shares']} share(s); the combined core gap needs "
            f"{review['target_gap_whole_shares']} whole-share(s) at this fund's reference price. "
            + (f"Evidence unavailable: {option['source_issue']}. " if option["source_issue"] else "")
            + f"Failed gates: {failed_text}."
        )
        # Even when the allocation task is complete, preserve a fund-local
        # missing-evidence observation rather than suggesting it was verified.
        if core_threshold_met and option["source_issue"]:
            reason += f" {ticker} evidence remains unverified: {option['source_issue']}."
        plan_rows.append({
            "plan_id": f"core_starter_whole_share_review:{ticker}",
            "asset_role": "core_allocation", "ticker_or_category": ticker,
            "tranche_number": "1", "planned_shares": str(quantity),
            "planned_amount": f"{amount:.2f}",
            "sizing_tier": "starter_allocation" if quantity else "no_allocation",
            "maximum_entry_condition": entry_condition,
            "planned_review_date": review_date, "estimated_cash_released": "0.00",
            "cash_remaining_after": f"{cash - amount:.2f}",
            "core_weight_after": f"{(current_core + amount) / account_total * 100.0:.4f}",
            "active_stock_weight_after": f"{active_weight:.4f}",
            "fifty_two_week_range_percentile": f"{percentile:.2f}" if percentile is not None else "",
            "status": status, "cash_rationale": cash_rationale, "reason": reason,
            "human_confirmation_required": "yes" if quantity else "no",
        })

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
        if row.get("asset_role") == "active_stock"
    )
    selected_core_shares = shares
    post_rows = [
        _post_action_row(
            scenario="current_portfolio", account_total=account_total,
            current_cash=cash, released_cash=0.0, core_ticker="", core_shares=0,
            core_price=core_price, current_core_value=current_core,
            active_value=active_value, status="current",
            retained_cash_reason=f"Current cash includes the ${reserve:.2f} mandatory internal reserve and capital not yet assigned by evidence-supported reviews.",
        ),
        _post_action_row(
            scenario="after_current_position_reviews", account_total=account_total,
            current_cash=cash, released_cash=released_cash, core_ticker="",
            core_shares=0, core_price=core_price, current_core_value=current_core,
            active_value=active_after_reviews,
            status="hypothetical_human_reviews_only",
            retained_cash_reason="Released capital remains cash unless a separate opportunity passes its own current gates.",
        ),
        _post_action_row(
            scenario="after_position_and_core_reviews", account_total=account_total,
            current_cash=cash, released_cash=released_cash,
            core_ticker=core_ticker if selected_core_shares else "",
            core_shares=selected_core_shares, core_price=core_price,
            current_core_value=current_core, active_value=active_after_reviews,
            status="hypothetical_selected_reviews" if selected_core_shares else "core_not_selected",
            retained_cash_reason=(
                f"Retains the ${reserve:.2f} mandatory internal reserve plus available cash because no individual-stock "
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
            "policy_status": ("minimum_satisfied" if core_minimum is not None else "target_satisfied") if core_threshold_met else
                             "below_minimum_starter_review" if core_minimum is not None and selected else
                             "below_minimum_unfunded" if core_minimum is not None else
                             "below_target_starter_review" if selected else "below_target_unfunded",
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
            f"core_candidates={','.join(approved_core_tickers())}; selected_core={core_ticker if selected else 'none'}; "
            f"core_status={core_status}; proposed_whole_shares={shares}; "
            f"estimated_released_cash={released_cash:.2f}; automatic_selection=no"
        ),
    )
    print(
        "Equity Research capital allocation complete; "
        f"dynamic_total={account_total:.2f}; core_status={core_status}; "
        f"core_shares={shares}; released_cash_scenario={released_cash:.2f}"
    )


if __name__ == "__main__":
    main()
