from __future__ import annotations

from pathlib import Path

from phase5r_c9_common import (
    DYNAMIC_WEIGHTS,
    EXACT_ACTION_PLAN,
    PORTFOLIO_SUMMARY,
    load_portfolio_summary,
    load_positions,
)
from phase5r_c9b_common import (
    ACCOUNT_STATE,
    EXECUTION_FILE,
    EXECUTION_RESEARCH_REPORT,
    MARKET_SNAPSHOT,
    PRICE_AWARE_ACTION_PLAN,
    append_c9b_log,
    as_float,
    intraday_range_pct,
    load_account_state,
    load_active_inhibit,
    load_execution_rows,
    load_market_rows,
    read_csv,
    slippage_review_pct,
    timestamp,
    write_csv,
    write_text,
)


ACTION_FIELDS = [
    "ticker",
    "action",
    "shares_under_review",
    "target_shares",
    "reference_price",
    "reference_price_timestamp",
    "minimum_sell_price_or_condition",
    "maximum_buy_price_or_condition",
    "suggested_order_style",
    "maximum_slippage_pct",
    "validity_window",
    "cancellation_condition",
    "target_weight_after",
    "reason",
    "human_confirmation_required",
    "automatic_action_allowed",
]
ALLOWED_SELL_STYLES = {"limit_review", "wait_for_market_open_review", "staged_limit_review", "no_action"}


def main() -> None:
    load_active_inhibit()
    load_account_state()
    summary = load_portfolio_summary()
    account_total = as_float(summary["account_total_value"], "account_total_value")
    actions = read_csv(EXACT_ACTION_PLAN)
    weights = {row["ticker"]: row for row in read_csv(DYNAMIC_WEIGHTS)}
    executions = load_execution_rows()
    execution_by_ticker = {row["ticker"]: row for row in executions}
    canonical_shares = {str(row["ticker"]): as_float(row["shares"], f"{row['ticker']}.shares") for row in load_positions()}
    markets = load_market_rows([row["ticker"] for row in actions])
    output: list[dict[str, str]] = []

    for action in actions:
        ticker = action["ticker"]
        market = markets[ticker]
        price = as_float(market["last_price"], f"{ticker}.last_price")
        slip = slippage_review_pct(market)
        range_pct = intraday_range_pct(market)
        dollar_volume = as_float(market["dollar_volume"], f"{ticker}.dollar_volume")
        sell_floor = price * (1.0 - slip / 100.0)
        buy_ceiling = price * (1.0 + slip / 100.0)
        execution = execution_by_ticker.get(ticker)
        c9_action = action["recommended_action"]

        if execution is not None and execution["order_status"] == "pending_fill":
            output_action = "pending_fill_confirmation"
            shares_under_review = execution["shares"]
            target_shares = as_float(execution["shares_after"], f"{ticker}.shares_after")
            minimum_sell = (
                f"${sell_floor:.2f} derived reference-floor review ({slip:.2f}% below ${price:.2f}); "
                "not a fill assumption and not a request to modify the existing order"
            )
            maximum_buy = "not_applicable_pending_sell"
            style = "no_action"
            validity = "Until fill/cancellation is confirmed or the B2 reference is refreshed, whichever occurs first"
            cancellation = (
                "Invalidate this guidance if the order status changes, the public reference becomes stale/invalid, "
                "or material company/market news occurs; never infer a fill"
            )
            reason = (
                "A user-submitted order is already pending, so C9B provides no order-change instruction. "
                f"The review tolerance uses a {range_pct:.2f}% daily range and ${dollar_volume:,.0f} dollar volume. "
                "Limit orders may not execute or may fill only partially."
            )
        elif (
            execution is not None
            and execution["order_status"] in {"filled", "partial_fill"}
            and not abs(canonical_shares[ticker] - as_float(execution["shares_after"], f"{ticker}.shares_after")) < 1e-9
        ):
            output_action = "confirmed_fill_awaiting_reconciliation"
            shares_under_review = "0"
            target_shares = as_float(execution["shares_after"], f"{ticker}.shares_after")
            minimum_sell = "not_applicable_confirmed_fill"
            maximum_buy = "not_applicable_confirmed_fill"
            style = "no_action"
            validity = "Until the confirmed fill is reconciled into canonical state"
            cancellation = "Do not create additional transaction guidance before reconciliation validates and is explicitly applied"
            reason = (
                "A human-confirmed fill is recorded but canonical shares/account state are not yet reconciled. "
                "C9B provides no additional action or assumed account values."
            )
        elif c9_action in {"trim_specific_shares_review", "exit_review"}:
            output_action = c9_action
            shares_under_review = action["whole_shares_to_change"]
            target_shares = as_float(action["target_shares"], f"{ticker}.target_shares")
            minimum_sell = f"${sell_floor:.2f} reference floor ({slip:.2f}% below ${price:.2f}); refresh before review"
            maximum_buy = "not_applicable_sell_review"
            style = "staged_limit_review" if c9_action == "exit_review" else "limit_review"
            validity = "One market session or until a new B2 snapshot/material event, whichever comes first"
            cancellation = "Cancel the guidance if weight falls within policy, thesis changes, data quality is not ok, or price moves beyond the review tolerance"
            reason = (
                f"C9 action={c9_action}; slippage review uses a {range_pct:.2f}% daily range and "
                f"${dollar_volume:,.0f} dollar volume. Limit orders may not execute or may fill only partially."
            )
        elif c9_action in {"add_specific_dollars_review", "core_allocation_tranche_review"}:
            output_action = c9_action
            shares_under_review = action["whole_shares_to_change"]
            target_shares = as_float(action["target_shares"], f"{ticker}.target_shares")
            minimum_sell = "not_applicable_buy_review"
            maximum_buy = f"${buy_ceiling:.2f} reference ceiling ({slip:.2f}% above ${price:.2f}); refresh before review"
            style = "limit_review"
            validity = "One market session or until a new B2 snapshot/material event, whichever comes first"
            cancellation = "Cancel the guidance if allocation or entry discipline fails, data quality is not ok, or price exceeds the review ceiling"
            reason = (
                f"C9 action={c9_action}; slippage review uses a {range_pct:.2f}% daily range and "
                f"${dollar_volume:,.0f} dollar volume. Limit orders may not execute or may fill only partially."
            )
        else:
            output_action = c9_action
            shares_under_review = "0"
            target_shares = as_float(action["target_shares"], f"{ticker}.target_shares")
            minimum_sell = "not_applicable_no_sell_review"
            maximum_buy = "not_applicable_no_buy_review"
            style = "no_action"
            validity = "Until the next daily evidence review or a material thesis/weight change"
            cancellation = "No transaction guidance exists; reopen only after a fresh account, research, and market-data review"
            reason = (
                f"C9 action={c9_action}; no transaction is under review. The {slip:.2f}% liquidity/volatility "
                "tolerance is recorded for future consistency, not for execution."
            )
        if style not in ALLOWED_SELL_STYLES:
            raise ValueError(f"unsupported price-aware order style: {style}")
        target_weight = target_shares * price / account_total * 100.0
        confirmation_required = output_action in {
            "pending_fill_confirmation",
            "confirmed_fill_awaiting_reconciliation",
            "trim_specific_shares_review",
            "exit_review",
            "add_specific_dollars_review",
            "core_allocation_tranche_review",
        }
        output.append(
            {
                "ticker": ticker,
                "action": output_action,
                "shares_under_review": shares_under_review,
                "target_shares": f"{target_shares:.4f}",
                "reference_price": f"{price:.2f}",
                "reference_price_timestamp": market["data_timestamp"],
                "minimum_sell_price_or_condition": minimum_sell,
                "maximum_buy_price_or_condition": maximum_buy,
                "suggested_order_style": style,
                "maximum_slippage_pct": f"{slip:.2f}",
                "validity_window": validity,
                "cancellation_condition": cancellation,
                "target_weight_after": f"{target_weight:.4f}",
                "reason": reason,
                "human_confirmation_required": "yes" if confirmation_required else "no",
                "automatic_action_allowed": "no",
            }
        )
    write_csv(PRICE_AWARE_ACTION_PLAN, output, ACTION_FIELDS)

    execution_state = ", ".join(
        f"{row['execution_id']}={row['order_status']}" for row in executions
    )
    lines = [
        "# Phase 5R-C9B Execution Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Execution State",
        "",
        f"- Records: `{execution_state}`.",
        "- A pending fill does not change current positions or account state.",
        "- No fill price, cash proceeds, or post-fill account total has been inferred.",
        "",
        "## Price-Aware Review",
        "",
        "| Ticker | Action | Shares | Target shares | Reference | Max slippage | Style | Target weight |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for row in output:
        lines.append(
            f"| {row['ticker']} | {row['action']} | {row['shares_under_review']} | {row['target_shares']} | "
            f"${row['reference_price']} | {row['maximum_slippage_pct']}% | {row['suggested_order_style']} | "
            f"{row['target_weight_after']}% |"
        )
    lines.extend(
        [
            "",
            "Reference prices are public B2 observations, not broker quotes or assumed fills. Market-at-open is not the default. Limit orders may not execute or may fill only partially. HOLD rows require no routine human review; only action-transition or reconciliation rows require review. No automatic action is permitted.",
        ]
    )
    write_text(EXECUTION_RESEARCH_REPORT, "\n".join(lines) + "\n")
    append_c9b_log(
        Path(__file__).name,
        "create_price_aware_action_plan",
        "complete",
        [ACCOUNT_STATE, PORTFOLIO_SUMMARY, EXACT_ACTION_PLAN, DYNAMIC_WEIGHTS, MARKET_SNAPSHOT, EXECUTION_FILE],
        [PRICE_AWARE_ACTION_PLAN, EXECUTION_RESEARCH_REPORT],
        execution_status=";".join(sorted({row["order_status"] for row in executions})),
        notes="market_at_open_default=no; limit_non_execution_risk=yes; fill_price_invented=no",
    )
    print(f"Phase 5R-C9B price-aware action plan complete; rows={len(output)}")


if __name__ == "__main__":
    main()
