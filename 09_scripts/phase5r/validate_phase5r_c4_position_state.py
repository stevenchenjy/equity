from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_c4_run_log.csv"
LOCAL_PATH = POSITION_DIR / "current_positions.local.csv"
REPORT_PATH = POSITION_DIR / "phase5r_c4_portfolio_state_report.csv"

POSITION_FIELDS = [
    "ticker", "entry_date", "entry_price", "position_pct", "shares_optional", "thesis",
    "horizon_class", "planned_review_date", "max_loss_pct_of_account", "invalidation_rule",
    "current_action", "notes",
]
HORIZONS = {"short_swing", "medium_conviction", "core_compounder", "watch_only"}
ACTIONS = {"hold_existing", "add_review", "trim_review", "exit_review", "new_candidate", "watch_only"}
STATE_FIELDS = [
    "generated_at", "status", "positions_file_present", "position_count", "active_position_count",
    "watch_only_count", "total_position_pct", "estimated_cash_reserve_pct", "cash_reserve_target_pct",
    "cash_reserve_target_met", "single_stock_default_cap_pct", "single_stock_default_cap_breaches",
    "single_stock_hard_cap_pct", "single_stock_hard_cap_breaches", "active_stock_sleeve_cap_pct",
    "active_stock_sleeve_cap_breached", "technology_exposure_cap_pct", "technology_exposure_status",
    "ai_infrastructure_theme_cap_pct", "ai_infrastructure_exposure_status", "validation_error_count",
    "validation_errors", "notes",
]
LOG_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "positions_file_present", "position_count", "validation_error_count", "safety_notes"]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_report(row: dict[str, str]) -> None:
    with REPORT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATE_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def append_log(status: str, present: str, count: int, error_count: int) -> None:
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "script_name": Path(__file__).name, "action": "validate_phase5r_c4_position_state",
            "input_path": str(LOCAL_PATH.relative_to(ROOT)), "output_path": str(REPORT_PATH.relative_to(ROOT)),
            "status": status, "positions_file_present": present, "position_count": str(count),
            "validation_error_count": str(error_count),
            "safety_notes": "local_file_only=yes; broker_used=no; orders_created=no; email_sent=no; scheduler_used=no; archived_legacy_used=no",
        })


def as_number(value: str, row_number: int, field: str, errors: list[str], allow_blank: bool = True) -> float | None:
    if value.strip() == "":
        if not allow_blank:
            errors.append(f"row {row_number}: {field} is required for an active position")
        return None
    try:
        number = float(value)
    except ValueError:
        errors.append(f"row {row_number}: {field} must be numeric when provided")
        return None
    if number < 0:
        errors.append(f"row {row_number}: {field} cannot be negative")
        return None
    return number


def blank_report() -> dict[str, str]:
    return {
        "generated_at": timestamp(), "status": "no_positions_file_yet", "positions_file_present": "no",
        "position_count": "0", "active_position_count": "0", "watch_only_count": "0", "total_position_pct": "0.00",
        "estimated_cash_reserve_pct": "100.00", "cash_reserve_target_pct": "10.00", "cash_reserve_target_met": "yes",
        "single_stock_default_cap_pct": "6.00", "single_stock_default_cap_breaches": "0",
        "single_stock_hard_cap_pct": "8.00", "single_stock_hard_cap_breaches": "0",
        "active_stock_sleeve_cap_pct": "30.00", "active_stock_sleeve_cap_breached": "no",
        "technology_exposure_cap_pct": "60.00", "technology_exposure_status": "not_evaluable_no_positions_file",
        "ai_infrastructure_theme_cap_pct": "35.00", "ai_infrastructure_exposure_status": "not_evaluable_no_positions_file",
        "validation_error_count": "0", "validation_errors": "", "notes": "No private positions file exists; blank state is valid for Phase 5R-C4.",
    }


def main() -> None:
    if not LOCAL_PATH.exists():
        write_report(blank_report())
        append_log("no_positions_file_yet", "no", 0, 0)
        print("Phase 5R-C4 position state: no_positions_file_yet")
        return

    with LOCAL_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        rows = list(reader)
    errors: list[str] = []
    missing = [field for field in POSITION_FIELDS if field not in header]
    if missing:
        errors.append(f"missing required columns: {','.join(missing)}")

    active_count = 0
    watch_count = 0
    total_pct = 0.0
    default_breaches = 0
    hard_breaches = 0
    for index, row in enumerate(rows, start=2):
        ticker = row.get("ticker", "").strip().upper()
        horizon = row.get("horizon_class", "").strip()
        action = row.get("current_action", "").strip()
        if not ticker:
            errors.append(f"row {index}: ticker cannot be empty")
        if horizon not in HORIZONS:
            errors.append(f"row {index}: horizon_class is not allowed")
        if action not in ACTIONS:
            errors.append(f"row {index}: current_action is not allowed")
        position_pct = as_number(row.get("position_pct", ""), index, "position_pct", errors, allow_blank=horizon == "watch_only")
        if horizon == "watch_only":
            watch_count += 1
            if position_pct not in {None, 0.0}:
                errors.append(f"row {index}: watch_only ideas must have position_pct 0")
            if action != "watch_only":
                errors.append(f"row {index}: watch_only horizon must use current_action watch_only")
        else:
            active_count += 1
            if position_pct is not None:
                total_pct += position_pct
                default_breaches += int(position_pct > 6.0)
                hard_breaches += int(position_pct > 8.0)

    status = "valid_position_state" if not errors else "validation_failed"
    cash_estimate = max(0.0, 100.0 - total_pct)
    report = {
        "generated_at": timestamp(), "status": status, "positions_file_present": "yes",
        "position_count": str(len(rows)), "active_position_count": str(active_count), "watch_only_count": str(watch_count),
        "total_position_pct": f"{total_pct:.2f}", "estimated_cash_reserve_pct": f"{cash_estimate:.2f}",
        "cash_reserve_target_pct": "10.00", "cash_reserve_target_met": "yes" if cash_estimate >= 10.0 else "no",
        "single_stock_default_cap_pct": "6.00", "single_stock_default_cap_breaches": str(default_breaches),
        "single_stock_hard_cap_pct": "8.00", "single_stock_hard_cap_breaches": str(hard_breaches),
        "active_stock_sleeve_cap_pct": "30.00", "active_stock_sleeve_cap_breached": "yes" if total_pct > 30.0 else "no",
        "technology_exposure_cap_pct": "60.00", "technology_exposure_status": "not_evaluable_from_minimum_schema",
        "ai_infrastructure_theme_cap_pct": "35.00", "ai_infrastructure_exposure_status": "not_evaluable_from_minimum_schema",
        "validation_error_count": str(len(errors)), "validation_errors": "; ".join(errors),
        "notes": "Local private position state validated without broker or archived inputs.",
    }
    write_report(report)
    append_log(status, "yes", len(rows), len(errors))
    print(f"Phase 5R-C4 position state: {status}; rows={len(rows)}; errors={len(errors)}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
