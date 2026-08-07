from __future__ import annotations

import csv
import hashlib
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from phase5r_c9_common import (
    ACCOUNT_STATE,
    C9_INHIBIT,
    CURRENT_POSITIONS,
    MARKET_SNAPSHOT,
    ROOT,
    as_float,
    csv_fields,
    load_account_state,
    load_active_inhibit,
    load_market_rows,
    read_csv,
    timestamp,
    write_csv,
    write_text,
)


CONTROL_DIR = ROOT / "00_project_control"
EXECUTION_DIR = ROOT / "06_execution_records"
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"

EXECUTION_FILE = EXECUTION_DIR / "manual_executions.local.csv"
EXECUTION_TEMPLATE = EXECUTION_DIR / "manual_executions.local.csv.template"
EXECUTION_EXAMPLE = EXECUTION_DIR / "manual_executions.local.csv.example"
PENDING_REPORT = EXECUTION_DIR / "phase5r_c9b_pending_execution_report.csv"
CONFIRMED_REPORT = EXECUTION_DIR / "phase5r_c9b_confirmed_execution_report.csv"
RECONCILIATION_REPORT = EXECUTION_DIR / "phase5r_c9b_reconciliation_report.csv"
POST_EXECUTION_WEIGHTS = POSITION_DIR / "phase5r_c9b_post_execution_weights.csv"
POST_EXECUTION_SUMMARY = POSITION_DIR / "phase5r_c9b_post_execution_account_summary.md"
PRICE_AWARE_ACTION_PLAN = POSITION_DIR / "phase5r_c9b_price_aware_action_plan.csv"
EXECUTION_RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c9b_execution_report.md"
C9B_RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c9b_run_log.csv"

EXECUTION_FIELDS = [
    "execution_id",
    "ticker",
    "side",
    "shares",
    "order_type",
    "order_submitted_at",
    "order_status",
    "limit_price_optional",
    "fill_date",
    "fill_price",
    "fees",
    "shares_before",
    "shares_after",
    "cash_before",
    "cash_after",
    "account_total_after",
    "source",
    "notes",
]
ALLOWED_STATUSES = {"pending_fill", "filled", "cancelled", "partial_fill"}
ALLOWED_SIDES = {"buy", "sell"}
RUN_LOG_FIELDS = [
    "timestamp",
    "phase",
    "script_name",
    "action",
    "status",
    "execution_id",
    "execution_status",
    "input_paths",
    "output_paths",
    "positions_modified",
    "account_state_modified",
    "email_sent",
    "d3_inhibit_active",
    "broker_used",
    "order_code_created",
    "smtp_config_modified",
    "archived_legacy_used",
    "notes",
]

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_APPLIED_RECONCILIATION_ACCEPTED_STATES = frozenset(
    {
        "historical_account_hash_match",
        "owner_account_snapshot_after_reconciliation",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def applied_reconciliation_current_state_status(
    reconciliation: Mapping[str, object],
    *,
    current_positions_sha256: str,
    current_account_sha256: str,
    current_account_last_updated: object,
) -> str:
    """Classify whether a current C9 state remains consistent with one fill.

    C9B reconciliation hashes are historical raw-byte evidence and must never
    be rewritten merely because the Project Owner later confirms a current
    account snapshot.  A later snapshot is compatible only when the reconciled
    position bytes remain exact, the current account state has already passed
    the C9 schema validator, and its timestamp is strictly after the
    reconciliation's public-price reference.  This is not a fill replay or a
    waiver of C9 arithmetic checks.
    """

    expected_positions = str(reconciliation.get("positions_sha256_after", "")).strip()
    expected_account = str(reconciliation.get("account_sha256_after", "")).strip()
    if (
        _SHA256_PATTERN.fullmatch(expected_positions) is None
        or _SHA256_PATTERN.fullmatch(expected_account) is None
        or _SHA256_PATTERN.fullmatch(current_positions_sha256) is None
        or _SHA256_PATTERN.fullmatch(current_account_sha256) is None
    ):
        return "reconciliation_hash_invalid"
    if current_positions_sha256 != expected_positions:
        return "positions_hash_mismatch"
    if current_account_sha256 == expected_account:
        return "historical_account_hash_match"

    reference_timestamp = str(
        reconciliation.get("reference_price_timestamp", "")
    ).strip()
    if not isinstance(current_account_last_updated, str):
        return "account_refresh_timestamp_invalid"
    try:
        reference_at = datetime.fromisoformat(reference_timestamp)
        updated_at = datetime.fromisoformat(current_account_last_updated)
    except ValueError:
        return "account_refresh_timestamp_invalid"
    if reference_at.tzinfo is None or updated_at.tzinfo is None:
        return "account_refresh_timestamp_invalid"
    if updated_at <= reference_at:
        return "account_refresh_timestamp_not_newer"
    return "owner_account_snapshot_after_reconciliation"


def applied_reconciliation_matches_current_state(
    reconciliation: Mapping[str, object],
    *,
    current_positions_sha256: str,
    current_account_sha256: str,
    current_account_last_updated: object,
) -> bool:
    """Return the closed accepted subset of reconciliation-state statuses."""

    return (
        applied_reconciliation_current_state_status(
            reconciliation,
            current_positions_sha256=current_positions_sha256,
            current_account_sha256=current_account_sha256,
            current_account_last_updated=current_account_last_updated,
        )
        in _APPLIED_RECONCILIATION_ACCEPTED_STATES
    )


def optional_float(value: object, field: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return as_float(value, field)


def parse_iso(value: str, field: str, *, date_only: bool = False) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")
    try:
        if date_only:
            datetime.strptime(value, "%Y-%m-%d")
        else:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError
    except ValueError as exc:
        kind = "YYYY-MM-DD" if date_only else "timezone-aware ISO timestamp"
        raise ValueError(f"{field} must be a {kind}") from exc


def write_private_execution_rows(rows: list[dict[str, str]]) -> None:
    write_csv(EXECUTION_FILE, rows, EXECUTION_FIELDS)
    os.chmod(EXECUTION_FILE, 0o600)


def load_execution_rows() -> list[dict[str, str]]:
    if not EXECUTION_FILE.exists():
        raise FileNotFoundError("manual_executions.local.csv is required")
    if csv_fields(EXECUTION_FILE) != EXECUTION_FIELDS:
        raise ValueError("manual execution columns do not match the C9B contract")
    rows = read_csv(EXECUTION_FILE)
    if not rows:
        raise ValueError("manual execution file must contain at least one record")
    seen: set[str] = set()
    for row in rows:
        execution_id = row["execution_id"].strip()
        if not execution_id or execution_id in seen:
            raise ValueError("execution_id values must be non-empty and unique")
        seen.add(execution_id)
        validate_execution_row(row)
    return rows


def validate_execution_row(row: dict[str, str]) -> None:
    execution_id = row["execution_id"].strip()
    ticker = row["ticker"].strip().upper()
    side = row["side"].strip()
    status = row["order_status"].strip()
    if not execution_id or not ticker:
        raise ValueError("execution_id and ticker are required")
    if side not in ALLOWED_SIDES:
        raise ValueError(f"{execution_id}.side must be buy or sell")
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"{execution_id}.order_status is unsupported")
    if not row["order_type"].strip() or not row["source"].strip():
        raise ValueError(f"{execution_id}.order_type and source are required")
    shares = as_float(row["shares"], f"{execution_id}.shares")
    before = as_float(row["shares_before"], f"{execution_id}.shares_before")
    after = as_float(row["shares_after"], f"{execution_id}.shares_after")
    if shares <= 0 or before < 0 or after < 0:
        raise ValueError(f"{execution_id} share values are invalid")
    if not all(math.isclose(value, round(value), abs_tol=1e-9) for value in (shares, before, after)):
        raise ValueError(f"{execution_id} uses whole shares only")
    expected_after = before - shares if side == "sell" else before + shares
    if not math.isclose(after, expected_after, abs_tol=1e-9):
        raise ValueError(f"{execution_id}.shares_after does not reconcile with side and shares")
    if row["order_submitted_at"].strip():
        parse_iso(row["order_submitted_at"], f"{execution_id}.order_submitted_at")
    limit_price = optional_float(row["limit_price_optional"], f"{execution_id}.limit_price_optional")
    if limit_price is not None and limit_price <= 0:
        raise ValueError(f"{execution_id}.limit_price_optional must be positive")

    fill_price = optional_float(row["fill_price"], f"{execution_id}.fill_price")
    fees = optional_float(row["fees"], f"{execution_id}.fees")
    cash_before = optional_float(row["cash_before"], f"{execution_id}.cash_before")
    cash_after = optional_float(row["cash_after"], f"{execution_id}.cash_after")
    account_total_after = optional_float(row["account_total_after"], f"{execution_id}.account_total_after")
    if any(value is not None and value < 0 for value in (fees, cash_before, cash_after, account_total_after)):
        raise ValueError(f"{execution_id} financial values cannot be negative")

    if status == "pending_fill":
        unknowns = {
            "fill_date": row["fill_date"].strip(),
            "fill_price": row["fill_price"].strip(),
            "fees": row["fees"].strip(),
            "cash_before": row["cash_before"].strip(),
            "cash_after": row["cash_after"].strip(),
            "account_total_after": row["account_total_after"].strip(),
        }
        present = [field for field, value in unknowns.items() if value]
        if present:
            raise ValueError(f"{execution_id} pending_fill must leave unknown fields blank: {','.join(present)}")
    elif status in {"filled", "partial_fill"}:
        parse_iso(row["fill_date"], f"{execution_id}.fill_date", date_only=True)
        if fill_price is None or fill_price <= 0:
            raise ValueError(f"{execution_id}.fill_price must be a confirmed positive number")
        if fees is None:
            raise ValueError(f"{execution_id}.fees must be entered explicitly, including 0 when confirmed")
        if status == "partial_fill" and "actual filled shares" not in row["notes"].lower():
            raise ValueError(f"{execution_id} partial_fill notes must identify shares as actual filled shares")
    elif status == "cancelled":
        if any((row["fill_date"].strip(), row["fill_price"].strip(), row["cash_after"].strip(), row["account_total_after"].strip())):
            raise ValueError(f"{execution_id} cancelled record cannot contain fill or reconciled account values")


def select_execution(rows: list[dict[str, str]], execution_id: str) -> dict[str, str]:
    matches = [row for row in rows if row["execution_id"] == execution_id]
    if len(matches) != 1:
        raise ValueError(f"execution_id not found uniquely: {execution_id}")
    return matches[0]


def execution_cash(row: dict[str, str], account: dict[str, object]) -> tuple[float, float, float, str]:
    execution_id = row["execution_id"]
    shares = as_float(row["shares"], f"{execution_id}.shares")
    fill_price = as_float(row["fill_price"], f"{execution_id}.fill_price")
    fees = as_float(row["fees"], f"{execution_id}.fees")
    supplied_before = optional_float(row["cash_before"], f"{execution_id}.cash_before")
    cash_before = supplied_before if supplied_before is not None else as_float(account["cash_available"], "cash_available")
    expected = cash_before + shares * fill_price - fees if row["side"] == "sell" else cash_before - shares * fill_price - fees
    supplied_after = optional_float(row["cash_after"], f"{execution_id}.cash_after")
    if supplied_after is None:
        return cash_before, expected, 0.0, "calculated_from_validated_fill"
    difference = supplied_after - expected
    if abs(difference) > 0.01:
        raise ValueError(f"{execution_id}.cash_after differs from fill arithmetic by {difference:.2f}")
    return cash_before, supplied_after, difference, "user_confirmed_cash_after"


def intraday_range_pct(market_row: dict[str, str]) -> float:
    price = as_float(market_row["last_price"], "last_price")
    high = as_float(market_row["day_high"], "day_high")
    low = as_float(market_row["day_low"], "day_low")
    return max(0.0, (high - low) / price * 100.0)


def slippage_review_pct(market_row: dict[str, str]) -> float:
    range_pct = intraday_range_pct(market_row)
    dollar_volume = as_float(market_row["dollar_volume"], "dollar_volume")
    if dollar_volume >= 5_000_000_000 and range_pct <= 2.0:
        return 0.15
    if dollar_volume >= 1_000_000_000:
        return 0.25
    if range_pct >= 5.0:
        return round(min(1.0, max(0.50, range_pct * 0.10)), 2)
    if range_pct >= 3.0:
        return round(min(0.75, max(0.40, range_pct * 0.10)), 2)
    return 0.30


def append_c9b_log(
    script_name: str,
    action: str,
    status: str,
    inputs: Iterable[Path],
    outputs: Iterable[Path],
    *,
    execution_id: str = "",
    execution_status: str = "",
    positions_modified: str = "no",
    account_state_modified: str = "no",
    notes: str = "",
) -> None:
    inhibit_state = "invalid"
    try:
        inhibit_state = "yes" if load_active_inhibit().get("active") is True else "no"
    except ValueError:
        pass
    C9B_RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = C9B_RUN_LOG.exists() and C9B_RUN_LOG.stat().st_size > 0
    with C9B_RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp(),
                "phase": "phase5r_c9b",
                "script_name": script_name,
                "action": action,
                "status": status,
                "execution_id": execution_id,
                "execution_status": execution_status,
                "input_paths": ";".join(str(path.relative_to(ROOT)) for path in inputs),
                "output_paths": ";".join(str(path.relative_to(ROOT)) for path in outputs),
                "positions_modified": positions_modified,
                "account_state_modified": account_state_modified,
                "email_sent": "no",
                "d3_inhibit_active": inhibit_state,
                "broker_used": "no",
                "order_code_created": "no",
                "smtp_config_modified": "no",
                "archived_legacy_used": "no",
                "notes": notes,
            }
        )


__all__ = [
    "ACCOUNT_STATE",
    "applied_reconciliation_current_state_status",
    "applied_reconciliation_matches_current_state",
    "C9B_RUN_LOG",
    "C9_INHIBIT",
    "CONFIRMED_REPORT",
    "CURRENT_POSITIONS",
    "EXECUTION_EXAMPLE",
    "EXECUTION_FIELDS",
    "EXECUTION_FILE",
    "EXECUTION_RESEARCH_REPORT",
    "EXECUTION_TEMPLATE",
    "MARKET_SNAPSHOT",
    "PENDING_REPORT",
    "POST_EXECUTION_SUMMARY",
    "POST_EXECUTION_WEIGHTS",
    "PRICE_AWARE_ACTION_PLAN",
    "RECONCILIATION_REPORT",
    "ROOT",
    "append_c9b_log",
    "as_float",
    "execution_cash",
    "intraday_range_pct",
    "load_account_state",
    "load_active_inhibit",
    "load_execution_rows",
    "load_market_rows",
    "optional_float",
    "read_csv",
    "select_execution",
    "sha256",
    "slippage_review_pct",
    "timestamp",
    "validate_execution_row",
    "write_csv",
    "write_private_execution_rows",
    "write_text",
]
