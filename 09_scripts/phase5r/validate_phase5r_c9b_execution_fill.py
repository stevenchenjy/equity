from __future__ import annotations

import argparse
from pathlib import Path

from phase5r_c9b_common import (
    ACCOUNT_STATE,
    CONFIRMED_REPORT,
    CURRENT_POSITIONS,
    EXECUTION_FIELDS,
    EXECUTION_FILE,
    PENDING_REPORT,
    append_c9b_log,
    as_float,
    load_active_inhibit,
    load_execution_rows,
    optional_float,
    read_csv,
    select_execution,
    sha256,
    validate_execution_row,
    write_csv,
    write_private_execution_rows,
)


PENDING_FIELDS = [
    *EXECUTION_FIELDS,
    "validation_status",
    "fill_price_known",
    "positions_sha256_at_intake",
    "account_state_sha256_at_intake",
    "position_mutation_allowed",
    "account_mutation_allowed",
]
CONFIRMED_FIELDS = [
    *EXECUTION_FIELDS,
    "validation_status",
    "reconciliation_eligible",
    "canonical_state_applied",
    "financial_values_source",
    "positions_sha256_at_intake",
    "account_state_sha256_at_intake",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate or record a human-confirmed Phase 5R-C9B fill.")
    parser.add_argument("--execution-id")
    parser.add_argument("--record-status", choices=["filled", "partial_fill", "cancelled"])
    parser.add_argument("--fill-date")
    parser.add_argument("--fill-price", type=float)
    parser.add_argument("--filled-shares", type=int)
    parser.add_argument("--fees", type=float)
    parser.add_argument("--cash-after", type=float)
    parser.add_argument("--account-total-after", type=float)
    parser.add_argument("--order-type")
    parser.add_argument("--order-submitted-at")
    return parser.parse_args()


def record_confirmation(rows: list[dict[str, str]], args: argparse.Namespace) -> tuple[str, str]:
    if not args.execution_id or not args.record_status:
        raise ValueError("--execution-id and --record-status are both required to record a confirmation")
    row = select_execution(rows, args.execution_id)
    if row["order_status"] != "pending_fill":
        raise ValueError("only a pending_fill record can receive a new confirmation")
    status = args.record_status
    if args.order_type:
        row["order_type"] = args.order_type
    if args.order_submitted_at:
        row["order_submitted_at"] = args.order_submitted_at
    if status == "cancelled":
        row["order_status"] = "cancelled"
        row["fill_date"] = ""
        row["fill_price"] = ""
        row["fees"] = ""
        row["cash_before"] = ""
        row["cash_after"] = ""
        row["account_total_after"] = ""
        row["notes"] = (row["notes"].rstrip(". ") + ". User confirmed cancellation; canonical state was not changed.").strip()
    else:
        required = {
            "--fill-date": args.fill_date,
            "--fill-price": args.fill_price,
            "--fees": args.fees,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError("confirmed fill is missing " + ",".join(missing))
        if status == "partial_fill" and args.filled_shares is None:
            raise ValueError("--filled-shares is required for partial_fill")
        actual_shares = args.filled_shares if args.filled_shares is not None else int(round(as_float(row["shares"], "shares")))
        if actual_shares <= 0:
            raise ValueError("actual filled shares must be positive")
        before = int(round(as_float(row["shares_before"], "shares_before")))
        after = before - actual_shares if row["side"] == "sell" else before + actual_shares
        if after < 0:
            raise ValueError("actual fill would make shares negative")
        row["shares"] = str(actual_shares)
        row["shares_after"] = str(after)
        row["order_status"] = status
        row["fill_date"] = args.fill_date
        row["fill_price"] = f"{args.fill_price:.4f}"
        row["fees"] = f"{args.fees:.2f}"
        row["cash_after"] = "" if args.cash_after is None else f"{args.cash_after:.2f}"
        row["account_total_after"] = "" if args.account_total_after is None else f"{args.account_total_after:.2f}"
        note = "Actual filled shares recorded" if status == "partial_fill" else "Human-confirmed full fill recorded"
        row["notes"] = (row["notes"].rstrip(". ") + f". {note}; canonical state not yet applied.").strip()
    validate_execution_row(row)
    write_private_execution_rows(rows)
    return row["execution_id"], row["order_status"]


def write_reports(rows: list[dict[str, str]]) -> tuple[int, int]:
    old_pending = {row["execution_id"]: row for row in read_csv(PENDING_REPORT)} if PENDING_REPORT.exists() else {}
    old_confirmed = {row["execution_id"]: row for row in read_csv(CONFIRMED_REPORT)} if CONFIRMED_REPORT.exists() else {}
    position_hash = sha256(CURRENT_POSITIONS)
    account_hash = sha256(ACCOUNT_STATE)
    pending: list[dict[str, str]] = []
    confirmed: list[dict[str, str]] = []
    for row in rows:
        if row["order_status"] == "pending_fill":
            prior = old_pending.get(row["execution_id"], {})
            pending.append(
                {
                    **row,
                    "validation_status": "valid_pending_fill",
                    "fill_price_known": "no",
                    "positions_sha256_at_intake": prior.get("positions_sha256_at_intake", position_hash),
                    "account_state_sha256_at_intake": prior.get("account_state_sha256_at_intake", account_hash),
                    "position_mutation_allowed": "no",
                    "account_mutation_allowed": "no",
                }
            )
        else:
            previous = old_pending.get(row["execution_id"], old_confirmed.get(row["execution_id"], {}))
            is_fill = row["order_status"] in {"filled", "partial_fill"}
            supplied_cash = optional_float(row["cash_after"], f"{row['execution_id']}.cash_after") is not None
            supplied_total = optional_float(row["account_total_after"], f"{row['execution_id']}.account_total_after") is not None
            source = "cancelled_no_financial_values" if not is_fill else (
                "user_confirmed_cash_and_total" if supplied_cash and supplied_total else "fill_plus_reconciliation_required"
            )
            confirmed.append(
                {
                    **row,
                    "validation_status": "valid_" + row["order_status"],
                    "reconciliation_eligible": "yes" if is_fill else "no",
                    "canonical_state_applied": old_confirmed.get(row["execution_id"], {}).get("canonical_state_applied", "no"),
                    "financial_values_source": source,
                    "positions_sha256_at_intake": previous.get("positions_sha256_at_intake", position_hash),
                    "account_state_sha256_at_intake": previous.get("account_state_sha256_at_intake", account_hash),
                }
            )
    write_csv(PENDING_REPORT, pending, PENDING_FIELDS)
    write_csv(CONFIRMED_REPORT, confirmed, CONFIRMED_FIELDS)
    return len(pending), len(confirmed)


def main() -> None:
    args = parse_args()
    load_active_inhibit()
    rows = load_execution_rows()
    execution_id = ""
    execution_status = "validation_only"
    if args.record_status:
        execution_id, execution_status = record_confirmation(rows, args)
        rows = load_execution_rows()
    elif any(
        value is not None
        for value in (
            args.execution_id,
            args.fill_date,
            args.fill_price,
            args.filled_shares,
            args.fees,
            args.cash_after,
            args.account_total_after,
            args.order_type,
            args.order_submitted_at,
        )
    ):
        raise ValueError("fill-entry arguments require --record-status")
    pending_count, confirmed_count = write_reports(rows)
    append_c9b_log(
        Path(__file__).name,
        "record_and_validate_execution" if args.record_status else "validate_execution_intake",
        "complete",
        [EXECUTION_FILE, CURRENT_POSITIONS, ACCOUNT_STATE],
        [PENDING_REPORT, CONFIRMED_REPORT],
        execution_id=execution_id,
        execution_status=execution_status,
        notes=f"pending_rows={pending_count}; confirmed_rows={confirmed_count}; canonical_state_modified=no",
    )
    print(f"Phase 5R-C9B execution validation complete; pending={pending_count}; confirmed={confirmed_count}")


if __name__ == "__main__":
    main()
