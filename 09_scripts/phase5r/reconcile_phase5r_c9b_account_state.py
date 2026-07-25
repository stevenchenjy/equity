from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from phase5r_c9_common import csv_fields, load_positions
from phase5r_c9b_common import (
    ACCOUNT_STATE,
    CONFIRMED_REPORT,
    CURRENT_POSITIONS,
    EXECUTION_FILE,
    EXECUTION_RESEARCH_REPORT,
    MARKET_SNAPSHOT,
    POST_EXECUTION_SUMMARY,
    POST_EXECUTION_WEIGHTS,
    PRICE_AWARE_ACTION_PLAN,
    RECONCILIATION_REPORT,
    ROOT,
    append_c9b_log,
    as_float,
    execution_cash,
    load_account_state,
    load_active_inhibit,
    load_execution_rows,
    load_market_rows,
    optional_float,
    read_csv,
    select_execution,
    sha256,
    timestamp,
    write_csv,
    write_text,
)


RECONCILIATION_FIELDS = [
    "execution_id",
    "ticker",
    "execution_status",
    "reconciliation_status",
    "canonical_state_applied",
    "shares_before",
    "actual_shares_filled",
    "shares_after",
    "fill_price",
    "fees",
    "cash_before",
    "cash_before_source",
    "calculated_cash_after",
    "selected_cash_after",
    "cash_reconciliation_difference",
    "estimated_public_price_account_total",
    "selected_account_total_after",
    "account_total_source",
    "account_total_reconciliation_difference",
    "rbrk_shares_before",
    "rbrk_shares_after",
    "positions_sha256_before",
    "positions_sha256_after",
    "account_sha256_before",
    "account_sha256_after",
    "reference_price_timestamp",
    "notes",
]
POST_WEIGHT_FIELDS = [
    "execution_id",
    "reconciliation_state",
    "ticker",
    "shares_after",
    "reference_price",
    "post_execution_value",
    "account_total_after",
    "post_execution_weight_pct",
    "reference_price_timestamp",
    "price_source",
    "price_quality_label",
    "account_total_source",
    "canonical_state_applied",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or apply a validated Phase 5R-C9B reconciliation.")
    parser.add_argument("--execution-id")
    parser.add_argument("--apply", action="store_true", help="Apply one validated filled/partial_fill record to canonical state.")
    return parser.parse_args()


def select_default(rows: list[dict[str, str]], execution_id: str | None) -> dict[str, str]:
    if execution_id:
        return select_execution(rows, execution_id)
    if len(rows) != 1:
        raise ValueError("--execution-id is required when more than one execution record exists")
    return rows[0]


def update_confirmed_applied(execution_id: str) -> None:
    if not CONFIRMED_REPORT.exists():
        return
    fields = csv_fields(CONFIRMED_REPORT)
    rows = read_csv(CONFIRMED_REPORT)
    for row in rows:
        if row["execution_id"] == execution_id:
            row["canonical_state_applied"] = "yes"
    write_csv(CONFIRMED_REPORT, rows, fields)


def write_pending_outputs(row: dict[str, str]) -> None:
    position_hash = sha256(CURRENT_POSITIONS)
    account_hash = sha256(ACCOUNT_STATE)
    report_row = {field: "" for field in RECONCILIATION_FIELDS}
    report_row.update(
        {
            "execution_id": row["execution_id"],
            "ticker": row["ticker"],
            "execution_status": row["order_status"],
            "reconciliation_status": "pending_no_mutation" if row["order_status"] == "pending_fill" else "cancelled_no_mutation",
            "canonical_state_applied": "no",
            "shares_before": row["shares_before"],
            "actual_shares_filled": "",
            "shares_after": row["shares_after"],
            "rbrk_shares_before": "2" if any(str(p["ticker"]) == "RBRK" and float(p["shares"]) == 2.0 for p in load_positions()) else "",
            "rbrk_shares_after": "2" if any(str(p["ticker"]) == "RBRK" and float(p["shares"]) == 2.0 for p in load_positions()) else "",
            "positions_sha256_before": position_hash,
            "positions_sha256_after": position_hash,
            "account_sha256_before": account_hash,
            "account_sha256_after": account_hash,
            "notes": "No fill is confirmed; post-execution financial values and weights are intentionally unavailable.",
        }
    )
    write_csv(RECONCILIATION_REPORT, [report_row], RECONCILIATION_FIELDS)
    write_csv(POST_EXECUTION_WEIGHTS, [], POST_WEIGHT_FIELDS)
    status_label = "pending fill" if row["order_status"] == "pending_fill" else "cancelled"
    summary = "\n".join(
        [
            "# Phase 5R-C9B Post-Execution Account Summary",
            "",
            f"Generated: `{timestamp()}`",
            "",
            f"## Status: `{status_label.replace(' ', '_')}`",
            "",
            f"Execution `{row['execution_id']}` is {status_label}. No fill price, proceeds, post-execution account total, or post-execution weight is inferred.",
            "",
            "Current positions and current account state remain unchanged. Final portfolio recommendations are not regenerated until a confirmed fill is validated and explicitly applied.",
            "",
            "D3 maintenance remains active. No broker, order, or email action occurred.",
        ]
    ) + "\n"
    write_text(POST_EXECUTION_SUMMARY, summary)
    research = summary.replace("# Phase 5R-C9B Post-Execution Account Summary", "# Phase 5R-C9B Execution Report")
    write_text(EXECUTION_RESEARCH_REPORT, research)


def reconcile_fill(row: dict[str, str], apply_state: bool) -> tuple[str, bool]:
    if row["order_status"] not in {"filled", "partial_fill"}:
        raise ValueError("only filled or partial_fill records can be reconciled")
    account = load_account_state()
    parsed_positions = {str(position["ticker"]): position for position in load_positions()}
    ticker = row["ticker"]
    if ticker not in parsed_positions:
        raise ValueError(f"current positions do not contain {ticker}")
    canonical_shares = as_float(parsed_positions[ticker]["shares"], f"{ticker}.shares")
    shares_before = as_float(row["shares_before"], "shares_before")
    shares_after = as_float(row["shares_after"], "shares_after")
    if not math.isclose(canonical_shares, shares_before, abs_tol=1e-9):
        if math.isclose(canonical_shares, shares_after, abs_tol=1e-9):
            raise ValueError("execution appears already applied; replay is blocked")
        raise ValueError("execution shares_before does not match canonical position")
    cash_before, cash_after, cash_difference, cash_source = execution_cash(row, account)
    if cash_after < as_float(account["cash_reserved"], "cash_reserved"):
        raise ValueError("reconciled cash would fall below the confirmed reserve")

    post_shares = {name: as_float(position["shares"], f"{name}.shares") for name, position in parsed_positions.items()}
    post_shares[ticker] = shares_after
    markets = load_market_rows(post_shares)
    estimated_total = cash_after + sum(post_shares[name] * as_float(markets[name]["last_price"], f"{name}.last_price") for name in post_shares)
    supplied_total = optional_float(row["account_total_after"], "account_total_after")
    selected_total = supplied_total if supplied_total is not None else estimated_total
    total_source = "user_confirmed" if supplied_total is not None else "estimated_public_prices"
    total_difference = selected_total - estimated_total
    if selected_total <= 0:
        raise ValueError("reconciled account total must be positive")

    positions_hash_before = sha256(CURRENT_POSITIONS)
    account_hash_before = sha256(ACCOUNT_STATE)
    positions_modified = False
    if apply_state:
        raw_positions = read_csv(CURRENT_POSITIONS)
        fields = csv_fields(CURRENT_POSITIONS)
        for position in raw_positions:
            if position["ticker"].strip().upper() == ticker:
                position["shares_optional"] = str(int(round(shares_after)))
        new_account = dict(account)
        new_account["cash_available"] = round(cash_after, 2)
        new_account["account_total_value"] = round(selected_total, 2)
        new_account["last_updated"] = timestamp()
        original_positions = CURRENT_POSITIONS.read_bytes()
        original_account = ACCOUNT_STATE.read_bytes()
        try:
            write_csv(CURRENT_POSITIONS, raw_positions, fields)
            write_text(ACCOUNT_STATE, json.dumps(new_account, indent=2) + "\n")
            os.chmod(CURRENT_POSITIONS, 0o600)
            os.chmod(ACCOUNT_STATE, 0o600)
            regeneration = ROOT / "09_scripts" / "phase5r" / "regenerate_phase5r_c9_portfolio_outputs.py"
            price_plan = ROOT / "09_scripts" / "phase5r" / "create_phase5r_c9b_price_aware_action_plan.py"
            for script in (regeneration, price_plan):
                result = subprocess.run([sys.executable, str(script)], cwd=ROOT, check=False)
                if result.returncode != 0:
                    raise RuntimeError(f"post-reconciliation regeneration failed: {script.name}")
            positions_modified = True
            update_confirmed_applied(row["execution_id"])
        except Exception:
            CURRENT_POSITIONS.write_bytes(original_positions)
            ACCOUNT_STATE.write_bytes(original_account)
            os.chmod(CURRENT_POSITIONS, 0o600)
            os.chmod(ACCOUNT_STATE, 0o600)
            for script in (regeneration, price_plan):
                subprocess.run(
                    [sys.executable, str(script)],
                    cwd=ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            raise

    positions_hash_after = sha256(CURRENT_POSITIONS)
    account_hash_after = sha256(ACCOUNT_STATE)
    reconciliation_state = "applied" if positions_modified else "validated_preview_not_applied"
    weight_rows: list[dict[str, str]] = []
    for name in sorted(post_shares):
        market = markets[name]
        price = as_float(market["last_price"], f"{name}.last_price")
        value = post_shares[name] * price
        weight_rows.append(
            {
                "execution_id": row["execution_id"],
                "reconciliation_state": reconciliation_state,
                "ticker": name,
                "shares_after": f"{post_shares[name]:.4f}",
                "reference_price": f"{price:.2f}",
                "post_execution_value": f"{value:.2f}",
                "account_total_after": f"{selected_total:.2f}",
                "post_execution_weight_pct": f"{value / selected_total * 100.0:.4f}",
                "reference_price_timestamp": market["data_timestamp"],
                "price_source": market["data_source"],
                "price_quality_label": market["data_quality_label"],
                "account_total_source": total_source,
                "canonical_state_applied": "yes" if positions_modified else "no",
            }
        )
    write_csv(POST_EXECUTION_WEIGHTS, weight_rows, POST_WEIGHT_FIELDS)
    rbrk_before = parsed_positions.get("RBRK", {}).get("shares", "")
    rbrk_after = post_shares.get("RBRK", "")
    reference_timestamp = max(market["data_timestamp"] for market in markets.values())
    report_row = {
        "execution_id": row["execution_id"],
        "ticker": ticker,
        "execution_status": row["order_status"],
        "reconciliation_status": reconciliation_state,
        "canonical_state_applied": "yes" if positions_modified else "no",
        "shares_before": f"{shares_before:.4f}",
        "actual_shares_filled": row["shares"],
        "shares_after": f"{shares_after:.4f}",
        "fill_price": row["fill_price"],
        "fees": row["fees"],
        "cash_before": f"{cash_before:.2f}",
        "cash_before_source": "execution_record" if row["cash_before"].strip() else "canonical_account_state",
        "calculated_cash_after": f"{cash_after - cash_difference:.2f}",
        "selected_cash_after": f"{cash_after:.2f}",
        "cash_reconciliation_difference": f"{cash_difference:.2f}",
        "estimated_public_price_account_total": f"{estimated_total:.2f}",
        "selected_account_total_after": f"{selected_total:.2f}",
        "account_total_source": total_source,
        "account_total_reconciliation_difference": f"{total_difference:.2f}",
        "rbrk_shares_before": f"{float(rbrk_before):.4f}" if rbrk_before != "" else "",
        "rbrk_shares_after": f"{float(rbrk_after):.4f}" if rbrk_after != "" else "",
        "positions_sha256_before": positions_hash_before,
        "positions_sha256_after": positions_hash_after,
        "account_sha256_before": account_hash_before,
        "account_sha256_after": account_hash_after,
        "reference_price_timestamp": reference_timestamp,
        "notes": f"cash_source={cash_source}; account total source={total_source}; no broker or email used",
    }
    write_csv(RECONCILIATION_REPORT, [report_row], RECONCILIATION_FIELDS)
    summary = "\n".join(
        [
            "# Phase 5R-C9B Post-Execution Account Summary",
            "",
            f"Generated: `{timestamp()}`",
            "",
            f"## Status: `{reconciliation_state}`",
            "",
            f"- Execution: `{row['execution_id']}` (`{row['order_status']}`).",
            f"- {ticker} shares: `{shares_before:.0f}` to `{shares_after:.0f}` using the confirmed `{row['shares']}`-share fill.",
            f"- Confirmed fill price: `${as_float(row['fill_price'], 'fill_price'):.4f}`; fees: `${as_float(row['fees'], 'fees'):.2f}`.",
            f"- Reconciled cash after: `${cash_after:.2f}` (`{cash_source}`).",
            f"- Account total after: `${selected_total:.2f}` (`{total_source}`).",
            f"- Difference from public-price estimate: `${total_difference:.2f}`.",
            f"- RBRK shares remain `{float(rbrk_after):.0f}`.",
            "",
            "Public prices are references, not broker quotes. The maintenance inhibit remains required; no email or automatic transaction is authorized.",
        ]
    ) + "\n"
    write_text(POST_EXECUTION_SUMMARY, summary)
    write_text(EXECUTION_RESEARCH_REPORT, summary.replace("# Phase 5R-C9B Post-Execution Account Summary", "# Phase 5R-C9B Execution Report"))
    return reconciliation_state, positions_modified


def main() -> None:
    args = parse_args()
    load_active_inhibit()
    rows = load_execution_rows()
    row = select_default(rows, args.execution_id)
    if args.apply and not args.execution_id:
        raise ValueError("--apply requires an explicit --execution-id")
    if row["order_status"] in {"pending_fill", "cancelled"}:
        if args.apply:
            raise ValueError(f"cannot apply an execution with status {row['order_status']}")
        write_pending_outputs(row)
        state = "pending_no_mutation" if row["order_status"] == "pending_fill" else "cancelled_no_mutation"
        modified = False
    else:
        position_map = {str(position["ticker"]): position for position in load_positions()}
        current_shares = as_float(position_map.get(row["ticker"], {}).get("shares"), f"{row['ticker']}.shares")
        recorded_after = as_float(row["shares_after"], "shares_after")
        if math.isclose(current_shares, recorded_after, abs_tol=1e-9):
            if args.apply:
                raise ValueError("execution is already reflected in canonical shares; replay is blocked")
            prior_rows = read_csv(RECONCILIATION_REPORT) if RECONCILIATION_REPORT.exists() else []
            prior = next((item for item in prior_rows if item.get("execution_id") == row["execution_id"]), {})
            if (
                prior.get("canonical_state_applied") != "yes"
                or prior.get("reconciliation_status") != "applied"
                or prior.get("positions_sha256_after") != sha256(CURRENT_POSITIONS)
                or prior.get("account_sha256_after") != sha256(ACCOUNT_STATE)
            ):
                raise ValueError("canonical shares match shares_after but no verified applied reconciliation exists")
            state = "already_applied_no_replay"
            modified = False
        else:
            state, modified = reconcile_fill(row, args.apply)
    append_c9b_log(
        Path(__file__).name,
        "apply_account_reconciliation" if args.apply else "preview_account_reconciliation",
        "complete",
        [EXECUTION_FILE, CURRENT_POSITIONS, ACCOUNT_STATE, MARKET_SNAPSHOT],
        [RECONCILIATION_REPORT, POST_EXECUTION_WEIGHTS, POST_EXECUTION_SUMMARY, EXECUTION_RESEARCH_REPORT],
        execution_id=row["execution_id"],
        execution_status=row["order_status"],
        positions_modified="yes" if modified else "no",
        account_state_modified="yes" if modified else "no",
        notes=f"reconciliation_state={state}; fill_price_invented=no",
    )
    print(f"Phase 5R-C9B reconciliation status={state}; canonical_state_modified={modified}")


if __name__ == "__main__":
    main()
