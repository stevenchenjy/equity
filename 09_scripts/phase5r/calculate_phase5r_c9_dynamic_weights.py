from __future__ import annotations

from pathlib import Path

from phase5r_c9_common import (
    ACCOUNT_STATE,
    C5_PACKETS,
    CURRENT_POSITIONS,
    DYNAMIC_WEIGHTS,
    MARKET_SNAPSHOT,
    PORTFOLIO_SUMMARY,
    append_run_log,
    as_float,
    concentration_status,
    dynamic_position_fit,
    load_account_state,
    load_active_inhibit,
    load_market_rows,
    load_packets,
    load_positions,
    score_from_packet,
    write_csv,
)


DYNAMIC_FIELDS = [
    "ticker",
    "current_shares",
    "latest_price",
    "current_value",
    "current_weight_pct",
    "stored_historical_position_pct",
    "weight_difference_pct",
    "single_stock_default_cap_pct",
    "single_stock_hard_cap_pct",
    "concentration_status",
    "current_research_score",
    "current_recommendation_label",
    "portfolio_fit_score",
    "price_timestamp",
    "price_source",
    "price_quality_label",
    "account_total_value",
    "account_state_updated",
    "weight_formula",
]
SUMMARY_FIELDS = [
    "account_total_value",
    "prior_account_value",
    "new_external_cash",
    "cash_available",
    "cash_reserved",
    "deployable_cash",
    "current_holdings_value",
    "cash_plus_holdings_value",
    "reconciliation_difference",
    "reconciliation_status",
    "current_cash_pct",
    "current_core_value",
    "current_core_weight_pct",
    "current_active_stock_value",
    "current_active_stock_weight_pct",
    "active_stock_target_pct",
    "active_stock_hard_cap_pct",
    "active_stock_status",
    "cash_target_pct",
    "cash_status",
    "position_count",
    "account_state_updated",
    "latest_price_timestamp",
    "calculation_basis",
]


def main() -> None:
    load_active_inhibit()
    account = load_account_state()
    positions = load_positions()
    market = load_market_rows([str(row["ticker"]) for row in positions])
    packets = load_packets()
    reported_account_total = as_float(
        account["account_total_value"], "account_total_value"
    )
    cash = as_float(account["cash_available"], "cash_available")
    estimated_holdings_value = sum(
        as_float(position["shares"], f"{position['ticker']}.shares")
        * as_float(market[str(position["ticker"])]["last_price"], f"{position['ticker']}.last_price")
        for position in positions
    )
    # Manually maintained cash and share counts are the current account truth.
    # The last reported total is only a reconciliation reference because close
    # prices change between manual account updates.
    account_total = cash + estimated_holdings_value
    if account_total <= 0:
        raise ValueError("cash plus current holdings must be positive")
    default_cap = as_float(account["single_stock_default_cap_pct"], "single_stock_default_cap_pct")
    hard_cap = as_float(account["single_stock_hard_cap_pct"], "single_stock_hard_cap_pct")

    dynamic_rows: list[dict[str, str]] = []
    for position in positions:
        ticker = str(position["ticker"])
        packet = packets.get(ticker)
        if packet is None:
            raise ValueError(f"controlled C5 research packet is missing for held ticker {ticker}")
        price_row = market[ticker]
        shares = as_float(position["shares"], f"{ticker}.shares")
        price = as_float(price_row["last_price"], f"{ticker}.last_price")
        current_value = shares * price
        current_weight = current_value / account_total * 100.0
        historical_weight = as_float(position["stored_historical_position_pct"], f"{ticker}.historical_weight")
        status = concentration_status(current_weight, account)
        fit = dynamic_position_fit(current_weight, account)
        score = score_from_packet(packet, fit)
        if current_weight > hard_cap + 1e-9:
            label = "trim_review"
        elif score < 5.5:
            label = "exit_review"
        else:
            label = "hold_existing"
        dynamic_rows.append(
            {
                "ticker": ticker,
                "current_shares": f"{shares:.4f}",
                "latest_price": f"{price:.2f}",
                "current_value": f"{current_value:.2f}",
                "current_weight_pct": f"{current_weight:.4f}",
                "stored_historical_position_pct": f"{historical_weight:.2f}",
                "weight_difference_pct": f"{current_weight - historical_weight:.4f}",
                "single_stock_default_cap_pct": f"{default_cap:.2f}",
                "single_stock_hard_cap_pct": f"{hard_cap:.2f}",
                "concentration_status": status,
                "current_research_score": f"{score:.2f}",
                "current_recommendation_label": label,
                "portfolio_fit_score": f"{fit:.1f}",
                "price_timestamp": price_row["data_timestamp"],
                "price_source": price_row["data_source"],
                "price_quality_label": price_row["data_quality_label"],
                "account_total_value": f"{account_total:.2f}",
                "account_state_updated": str(account["last_updated"]),
                "weight_formula": "current_shares*latest_price/account_total_value*100",
            }
        )

    dynamic_rows.sort(key=lambda row: -float(row["current_weight_pct"]))
    holdings_value = sum(float(row["current_value"]) for row in dynamic_rows)
    active_weight = holdings_value / account_total * 100.0
    cash_reserved = as_float(account["cash_reserved"], "cash_reserved")
    cash_plus_holdings = cash + holdings_value
    reconciliation_difference = reported_account_total - cash_plus_holdings
    tolerance = max(25.0, reported_account_total * 0.01)
    reconciliation_status = (
        "reported_total_within_price_drift_tolerance"
        if abs(reconciliation_difference) <= tolerance
        else "reported_total_stale_effective_total_derived_from_cash_and_holdings"
    )
    active_target = as_float(account["active_stock_target_pct"], "active_stock_target_pct")
    active_hard = as_float(account["active_stock_hard_cap_pct"], "active_stock_hard_cap_pct")
    if active_weight <= active_target + 1e-9:
        active_status = "within_target"
    elif active_weight <= active_hard + 1e-9:
        active_status = "above_target_within_hard_cap"
    else:
        active_status = "above_hard_cap"
    cash_pct = cash / account_total * 100.0
    cash_target = as_float(account["cash_target_pct"], "cash_target_pct")
    summary = {
        "account_total_value": f"{account_total:.2f}",
        "prior_account_value": f"{as_float(account['prior_account_value'], 'prior_account_value'):.2f}",
        "new_external_cash": f"{as_float(account['new_external_cash'], 'new_external_cash'):.2f}",
        "cash_available": f"{cash:.2f}",
        "cash_reserved": f"{cash_reserved:.2f}",
        "deployable_cash": f"{cash - cash_reserved:.2f}",
        "current_holdings_value": f"{holdings_value:.2f}",
        "cash_plus_holdings_value": f"{cash_plus_holdings:.2f}",
        "reconciliation_difference": f"{reconciliation_difference:.2f}",
        "reconciliation_status": reconciliation_status,
        "current_cash_pct": f"{cash_pct:.4f}",
        "current_core_value": "0.00",
        "current_core_weight_pct": "0.0000",
        "current_active_stock_value": f"{holdings_value:.2f}",
        "current_active_stock_weight_pct": f"{active_weight:.4f}",
        "active_stock_target_pct": f"{active_target:.2f}",
        "active_stock_hard_cap_pct": f"{active_hard:.2f}",
        "active_stock_status": active_status,
        "cash_target_pct": f"{cash_target:.2f}",
        "cash_status": "above_target" if cash_pct > cash_target + 1e-9 else "within_or_below_target",
        "position_count": str(len(dynamic_rows)),
        "account_state_updated": str(account["last_updated"]),
        "latest_price_timestamp": max(row["price_timestamp"] for row in dynamic_rows),
        "calculation_basis": "current_cash_plus_current_shares_at_canonical_b2_close; reported_account_total_reconciliation_only; stored_position_pct_historical_only",
    }
    write_csv(DYNAMIC_WEIGHTS, dynamic_rows, DYNAMIC_FIELDS)
    write_csv(PORTFOLIO_SUMMARY, [summary], SUMMARY_FIELDS)
    append_run_log(
        Path(__file__).name,
        "calculate_dynamic_weights",
        "complete",
        [ACCOUNT_STATE, CURRENT_POSITIONS, MARKET_SNAPSHOT, C5_PACKETS],
        [DYNAMIC_WEIGHTS, PORTFOLIO_SUMMARY],
        position_count=len(dynamic_rows),
        notes=(
            f"active_weight_pct={active_weight:.4f}; reconciliation_difference={reconciliation_difference:.2f}; "
            "effective_total_basis=cash_plus_current_holdings; stored_position_pct_used_for_current_truth=no"
        ),
    )
    print(
        "Phase 5R-C9 dynamic weights complete; "
        f"positions={len(dynamic_rows)}; active_weight={active_weight:.4f}%; cash={cash:.2f}"
    )


if __name__ == "__main__":
    main()
