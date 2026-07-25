from __future__ import annotations

from pathlib import Path

from phase5r_c9_common import EXACT_ACTION_PLAN, load_positions
from phase5r_c9b_common import (
    ACCOUNT_STATE,
    CURRENT_POSITIONS,
    EXECUTION_EXAMPLE,
    EXECUTION_FIELDS,
    EXECUTION_FILE,
    EXECUTION_TEMPLATE,
    PENDING_REPORT,
    append_c9b_log,
    load_active_inhibit,
    load_execution_rows,
    read_csv,
    sha256,
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


def blank_row() -> dict[str, str]:
    return {field: "" for field in EXECUTION_FIELDS}


def pending_iot_row() -> dict[str, str]:
    row = blank_row()
    row.update(
        {
            "execution_id": "C9B-IOT-PENDING-001",
            "ticker": "IOT",
            "side": "sell",
            "shares": "3",
            "order_type": "user_confirmed_order_type_or_pending",
            "order_submitted_at": "",
            "order_status": "pending_fill",
            "shares_before": "8",
            "shares_after": "5",
            "source": "user_reported_pending_order",
            "notes": (
                "Order reported submitted; exact order type, submission timestamp, fill date, fill price, fees, "
                "cash, and account total are not yet confirmed."
            ),
        }
    )
    return row


def write_support_files() -> None:
    write_csv(EXECUTION_TEMPLATE, [blank_row()], EXECUTION_FIELDS)
    example = blank_row()
    example.update(
        {
            "execution_id": "EXAMPLE-ONLY",
            "ticker": "EXAMPLE",
            "side": "sell",
            "shares": "1",
            "order_type": "limit_review",
            "order_submitted_at": "",
            "order_status": "pending_fill",
            "shares_before": "2",
            "shares_after": "1",
            "source": "example_only_not_an_execution",
            "notes": "Example only. Unknown fill and account fields remain blank while pending.",
        }
    )
    write_csv(EXECUTION_EXAMPLE, [example], EXECUTION_FIELDS)


def assert_c9_source_scenario() -> None:
    positions = {str(row["ticker"]): row for row in load_positions()}
    iot = positions.get("IOT")
    if iot is None or float(iot["shares"]) != 8.0:
        raise ValueError("pending C9B intake requires the unmodified 8-share IOT source position")
    actions = {row["ticker"]: row for row in read_csv(EXACT_ACTION_PLAN)}
    action = actions.get("IOT")
    if action is None or action["whole_shares_to_change"] != "3" or float(action["target_shares"]) != 5.0:
        raise ValueError("pending C9B intake requires the verified C9 IOT 3-share review scenario")


def main() -> None:
    load_active_inhibit()
    write_support_files()
    created = False
    if not EXECUTION_FILE.exists():
        assert_c9_source_scenario()
        write_private_execution_rows([pending_iot_row()])
        created = True
    rows = load_execution_rows()

    prior: dict[str, dict[str, str]] = {}
    if PENDING_REPORT.exists():
        prior = {row["execution_id"]: row for row in read_csv(PENDING_REPORT)}
    position_hash = sha256(CURRENT_POSITIONS)
    account_hash = sha256(ACCOUNT_STATE)
    pending_rows: list[dict[str, str]] = []
    for row in rows:
        if row["order_status"] != "pending_fill":
            continue
        previous = prior.get(row["execution_id"], {})
        pending_rows.append(
            {
                **row,
                "validation_status": "valid_pending_fill",
                "fill_price_known": "no",
                "positions_sha256_at_intake": previous.get("positions_sha256_at_intake", position_hash),
                "account_state_sha256_at_intake": previous.get("account_state_sha256_at_intake", account_hash),
                "position_mutation_allowed": "no",
                "account_mutation_allowed": "no",
            }
        )
    write_csv(PENDING_REPORT, pending_rows, PENDING_FIELDS)
    append_c9b_log(
        Path(__file__).name,
        "create_or_validate_execution_intake",
        "complete",
        [CURRENT_POSITIONS, ACCOUNT_STATE, EXACT_ACTION_PLAN],
        [EXECUTION_FILE, EXECUTION_TEMPLATE, EXECUTION_EXAMPLE, PENDING_REPORT],
        execution_id="C9B-IOT-PENDING-001" if created else "",
        execution_status="pending_fill" if pending_rows else "no_pending_rows",
        notes=f"local_execution_created={'yes' if created else 'no'}; fill_price_invented=no",
    )
    print(f"Phase 5R-C9B execution intake ready; created={created}; pending_rows={len(pending_rows)}")


if __name__ == "__main__":
    main()
