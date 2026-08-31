from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c4r_run_log.csv"

LOCAL_PATH = POSITION_DIR / "current_positions.local.csv"
SCHEMA_PATH = POSITION_DIR / "phase5r_c4_position_schema.csv"
VALIDATION_PATH = POSITION_DIR / "phase5r_c4r_current_position_validation.csv"
CONCENTRATION_PATH = POSITION_DIR / "phase5r_c4r_portfolio_concentration_report.csv"
REVIEW_QUEUE_PATH = POSITION_DIR / "phase5r_c4r_position_review_queue.csv"
SUMMARY_PATH = POSITION_DIR / "phase5r_c4r_current_portfolio_summary.md"
INTAKE_REPORT_PATH = RESEARCH_DIR / "phase5r_c4r_position_intake_report.md"

ACCOUNT_VALUE_USD = 1000.0
POSITION_FIELDS = [
    "ticker", "entry_date", "entry_price", "position_pct", "shares_optional", "thesis",
    "horizon_class", "planned_review_date", "max_loss_pct_of_account", "invalidation_rule",
    "current_action", "notes",
]
HORIZONS = {"short_swing", "medium_conviction", "core_compounder", "watch_only"}
ACTIONS = {"hold_existing", "add_review", "trim_review", "exit_review", "new_candidate", "watch_only"}
VALIDATION_FIELDS = [
    "row_number", "ticker", "required_columns_present", "ticker_non_empty", "entry_price_numeric",
    "position_pct_numeric", "shares_optional_numeric_or_blank", "horizon_class_allowed",
    "current_action_allowed", "row_validation_status", "validation_errors",
]
CONCENTRATION_FIELDS = [
    "record_type", "ticker", "position_pct", "estimated_value_usd", "single_stock_default_cap_pct",
    "single_stock_hard_cap_pct", "concentration_status", "portfolio_active_stock_sleeve_pct",
    "active_stock_sleeve_cap_pct", "active_stock_sleeve_status", "estimated_cash_reserve_pct",
    "estimated_cash_reserve_usd", "cash_reserve_target_pct", "cash_status",
    "technology_exposure_cap_pct", "technology_exposure_status",
    "ai_infrastructure_theme_cap_pct", "ai_infrastructure_exposure_status", "notes",
]
REVIEW_FIELDS = [
    "priority", "ticker", "horizon_class", "current_action", "planned_review_date", "position_pct",
    "estimated_value_usd", "concentration_status", "review_label", "review_reason",
    "manual_review_only", "broker_action_allowed",
]
LOG_FIELDS = [
    "timestamp", "phase", "action", "input_path", "output_paths", "status", "account_value_usd",
    "position_rows", "schema_valid", "total_position_pct", "cash_reserve_pct", "active_sleeve_status",
    "hard_cap_breach_count", "email_sent", "scheduler_used", "broker_used", "smtp_config_modified",
    "archived_legacy_used", "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_number(value: str, required: bool) -> tuple[float | None, bool]:
    text = value.strip()
    if not text:
        return None, not required
    try:
        number = float(text)
    except ValueError:
        return None, False
    return (number, math.isfinite(number) and number >= 0)


def concentration_status(position_pct: float) -> str:
    if position_pct > 8.0:
        return "above_hard_cap"
    if position_pct > 6.0:
        return "above_default_cap"
    return "within_default_cap"


def append_log(status: str, row_count: int, total_pct: float, cash_pct: float, hard_breaches: int) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c4r", "action": "refresh_current_position_intake",
            "input_path": str(LOCAL_PATH.relative_to(ROOT)),
            "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [VALIDATION_PATH, CONCENTRATION_PATH, REVIEW_QUEUE_PATH, SUMMARY_PATH, INTAKE_REPORT_PATH]),
            "status": status, "account_value_usd": f"{ACCOUNT_VALUE_USD:.2f}", "position_rows": str(row_count),
            "schema_valid": "yes" if status == "complete" else "no", "total_position_pct": f"{total_pct:.2f}",
            "cash_reserve_pct": f"{cash_pct:.2f}", "active_sleeve_status": "above_target" if total_pct > 30.0 else "within_target",
            "hard_cap_breach_count": str(hard_breaches), "email_sent": "no", "scheduler_used": "no",
            "broker_used": "no", "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "local_positions_only=yes; reports_sanitized=yes; manual_review_only=yes; order_code=no; phase5r_c5_created=no",
        })


def main() -> None:
    if not LOCAL_PATH.exists():
        raise FileNotFoundError("Current local positions file is required for Phase 5R-C4R")
    with LOCAL_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        rows = list(reader)
    schema_columns = {row["column_name"] for row in csv.DictReader(SCHEMA_PATH.open(newline="", encoding="utf-8"))}
    missing_columns = [field for field in POSITION_FIELDS if field not in header or field not in schema_columns]
    required_columns_present = not missing_columns

    validation_rows: list[dict[str, str]] = []
    parsed_positions: list[dict[str, object]] = []
    all_valid = required_columns_present
    for row_number, row in enumerate(rows, start=2):
        ticker = row.get("ticker", "").strip().upper()
        entry_price, entry_price_valid = parse_number(row.get("entry_price", ""), required=True)
        position_pct, position_pct_valid = parse_number(row.get("position_pct", ""), required=True)
        shares, shares_valid = parse_number(row.get("shares_optional", ""), required=False)
        horizon = row.get("horizon_class", "").strip()
        action = row.get("current_action", "").strip()
        errors: list[str] = []
        if not required_columns_present:
            errors.append("required columns missing")
        if not ticker:
            errors.append("ticker is empty")
        if not entry_price_valid:
            errors.append("entry_price must be numeric")
        if not position_pct_valid or position_pct is None or position_pct > 100.0:
            errors.append("position_pct must be numeric between 0 and 100")
        if not shares_valid:
            errors.append("shares_optional must be numeric when present")
        if horizon not in HORIZONS:
            errors.append("horizon_class is not allowed")
        if action not in ACTIONS:
            errors.append("current_action is not allowed")
        row_valid = not errors
        all_valid = all_valid and row_valid
        validation_rows.append({
            "row_number": str(row_number), "ticker": ticker, "required_columns_present": "yes" if required_columns_present else "no",
            "ticker_non_empty": "yes" if ticker else "no", "entry_price_numeric": "yes" if entry_price_valid else "no",
            "position_pct_numeric": "yes" if position_pct_valid and position_pct is not None and position_pct <= 100.0 else "no",
            "shares_optional_numeric_or_blank": "yes" if shares_valid else "no", "horizon_class_allowed": "yes" if horizon in HORIZONS else "no",
            "current_action_allowed": "yes" if action in ACTIONS else "no", "row_validation_status": "pass" if row_valid else "fail",
            "validation_errors": "; ".join(errors),
        })
        if row_valid and position_pct is not None:
            parsed_positions.append({
                "ticker": ticker, "position_pct": position_pct, "horizon": horizon, "action": action,
                "planned_review_date": row.get("planned_review_date", "").strip(),
            })

    write_csv(VALIDATION_PATH, validation_rows, VALIDATION_FIELDS)
    if not all_valid:
        append_log("validation_failed", len(rows), 0.0, 100.0, 0)
        raise RuntimeError("Phase 5R-C4R schema validation failed")

    active_positions = [position for position in parsed_positions if position["horizon"] != "watch_only"]
    total_pct = sum(float(position["position_pct"]) for position in active_positions)
    cash_pct = max(0.0, 100.0 - total_pct)
    cash_usd = ACCOUNT_VALUE_USD * cash_pct / 100.0
    sleeve_status = "above_target" if total_pct > 30.0 else "within_target"
    cash_status = "below_target" if cash_pct < 10.0 else "at_or_above_target"
    hard_breaches = sum(float(position["position_pct"]) > 8.0 for position in active_positions)
    concentration_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    for position in active_positions:
        pct = float(position["position_pct"])
        status = concentration_status(pct)
        estimated_value = ACCOUNT_VALUE_USD * pct / 100.0
        review_label = "trim_review_due_to_concentration" if status == "above_hard_cap" else "concentration_review" if status == "above_default_cap" else "weekly_position_review"
        concentration_rows.append({
            "record_type": "position", "ticker": str(position["ticker"]), "position_pct": f"{pct:.2f}",
            "estimated_value_usd": f"{estimated_value:.2f}", "single_stock_default_cap_pct": "6.00",
            "single_stock_hard_cap_pct": "8.00", "concentration_status": status,
            "portfolio_active_stock_sleeve_pct": f"{total_pct:.2f}", "active_stock_sleeve_cap_pct": "30.00",
            "active_stock_sleeve_status": sleeve_status, "estimated_cash_reserve_pct": f"{cash_pct:.2f}",
            "estimated_cash_reserve_usd": f"{cash_usd:.2f}", "cash_reserve_target_pct": "10.00",
            "cash_status": cash_status, "technology_exposure_cap_pct": "60.00",
            "technology_exposure_status": "not_evaluable_from_position_schema",
            "ai_infrastructure_theme_cap_pct": "35.00",
            "ai_infrastructure_exposure_status": "not_evaluable_from_position_schema",
            "notes": "Current local position; weekly concentration review only.",
        })
        review_rows.append({
            "priority": "1" if status == "above_hard_cap" else "2" if status == "above_default_cap" else "3",
            "ticker": str(position["ticker"]), "horizon_class": str(position["horizon"]),
            "current_action": str(position["action"]), "planned_review_date": str(position["planned_review_date"]),
            "position_pct": f"{pct:.2f}", "estimated_value_usd": f"{estimated_value:.2f}",
            "concentration_status": status, "review_label": review_label,
            "review_reason": f"Position is {pct:.2f}% versus 8.00% hard cap." if status == "above_hard_cap" else "Weekly concentration and thesis review.",
            "manual_review_only": "yes", "broker_action_allowed": "no",
        })
    concentration_rows.append({
        "record_type": "portfolio_summary", "ticker": "PORTFOLIO", "position_pct": "", "estimated_value_usd": "",
        "single_stock_default_cap_pct": "6.00", "single_stock_hard_cap_pct": "8.00", "concentration_status": "portfolio_summary",
        "portfolio_active_stock_sleeve_pct": f"{total_pct:.2f}", "active_stock_sleeve_cap_pct": "30.00",
        "active_stock_sleeve_status": sleeve_status, "estimated_cash_reserve_pct": f"{cash_pct:.2f}",
        "estimated_cash_reserve_usd": f"{cash_usd:.2f}", "cash_reserve_target_pct": "10.00",
        "cash_status": cash_status, "technology_exposure_cap_pct": "60.00",
        "technology_exposure_status": "not_evaluable_from_position_schema",
        "ai_infrastructure_theme_cap_pct": "35.00",
        "ai_infrastructure_exposure_status": "not_evaluable_from_position_schema",
        "notes": "Account value assumption 1000 USD; current local positions only.",
    })
    review_rows.sort(key=lambda item: (int(item["priority"]), -float(item["position_pct"]), item["ticker"]))
    write_csv(CONCENTRATION_PATH, concentration_rows, CONCENTRATION_FIELDS)
    write_csv(REVIEW_QUEUE_PATH, review_rows, REVIEW_FIELDS)

    summary_lines = [
        "# Phase 5R-C4R Current Portfolio Summary", "", f"Generated: `{timestamp()}`", "",
        "## Assumptions", "", "- Account value: `1000.00 USD`.", "- Position source: private Git-ignored current local positions file only.",
        "- Technology and AI-infrastructure exposure: `not evaluable from minimum position schema`.", "",
        "## Concentration", "", f"- Active position count: `{len(active_positions)}`.", f"- Active stock sleeve: `{total_pct:.2f}%` (`{sleeve_status}`).",
        f"- Estimated cash reserve: `{cash_pct:.2f}%` / `{cash_usd:.2f} USD` (`{cash_status}`).",
        f"- Positions above the 8% hard cap: `{hard_breaches}`.", "",
        "| Ticker | Position % | Estimated Value USD | Concentration | Weekly Review Label |", "| --- | ---: | ---: | --- | --- |",
    ]
    for item in review_rows:
        summary_lines.append(f"| {item['ticker']} | {item['position_pct']}% | {item['estimated_value_usd']} | {item['concentration_status']} | {item['review_label']} |")
    summary_lines.extend(["", "## Manual Boundary", "", "`trim_review_due_to_concentration` is a weekly research-review label, not a sell order. No broker or automated execution path is present."])
    SUMMARY_PATH.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    report_lines = [
        "# Phase 5R-C4R Position Intake Report", "", f"Generated: `{timestamp()}`", "", "## Outcome", "",
        f"- Local position rows validated: `{len(rows)}`.", "- Schema validation: `passed`.",
        f"- Active stock sleeve: `{total_pct:.2f}%`.", f"- Estimated cash reserve: `{cash_pct:.2f}%`.",
        f"- Hard-cap review rows: `{hard_breaches}`.", "- IOT and RBRK were read only from the current local positions file.", "",
        "## Privacy", "", "Generated artifacts exclude thesis text, invalidation text, share counts, raw entry prices, and free-form notes.", "",
        "## Boundary", "", "No archived holdings, broker, order path, email, scheduler, SMTP configuration, or Phase 5R-C5 was used or created.",
    ]
    INTAKE_REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    append_log("complete", len(rows), total_pct, cash_pct, hard_breaches)
    print(f"Phase 5R-C4R intake complete; rows={len(rows)}; total_position_pct={total_pct:.2f}; hard_cap_breaches={hard_breaches}")


if __name__ == "__main__":
    main()
