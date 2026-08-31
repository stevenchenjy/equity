from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
CONTROL_DIR = ROOT / "00_project_control"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c4_run_log.csv"

LOCAL_POSITION_PATH = POSITION_DIR / "current_positions.local.csv"
TEMPLATE_PATH = POSITION_DIR / "current_positions.local.csv.template"
EXAMPLE_PATH = POSITION_DIR / "current_positions.local.csv.example"
SCHEMA_PATH = POSITION_DIR / "phase5r_c4_position_schema.csv"
STATE_REPORT_PATH = POSITION_DIR / "phase5r_c4_portfolio_state_report.csv"
BLANK_REVIEW_PATH = POSITION_DIR / "phase5r_c4_blank_position_review.md"

POSITION_FIELDS = [
    "ticker", "entry_date", "entry_price", "position_pct", "shares_optional", "thesis",
    "horizon_class", "planned_review_date", "max_loss_pct_of_account", "invalidation_rule",
    "current_action", "notes",
]
STATE_FIELDS = [
    "generated_at", "status", "positions_file_present", "position_count", "active_position_count",
    "watch_only_count", "total_position_pct", "estimated_cash_reserve_pct", "cash_reserve_target_pct",
    "cash_reserve_target_met", "single_stock_default_cap_pct", "single_stock_default_cap_breaches",
    "single_stock_hard_cap_pct", "single_stock_hard_cap_breaches", "active_stock_sleeve_cap_pct",
    "active_stock_sleeve_cap_breached", "technology_exposure_cap_pct", "technology_exposure_status",
    "ai_infrastructure_theme_cap_pct", "ai_infrastructure_exposure_status", "validation_error_count",
    "validation_errors", "notes",
]
LOG_FIELDS = [
    "timestamp", "script_name", "action", "input_path", "output_path", "status",
    "positions_file_present", "position_count", "validation_error_count", "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_log(output_paths: list[Path]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "script_name": Path(__file__).name, "action": "create_phase5r_c4_position_templates",
            "input_path": "none", "output_path": ";".join(str(path.relative_to(ROOT)) for path in output_paths),
            "status": "complete", "positions_file_present": "yes" if LOCAL_POSITION_PATH.exists() else "no",
            "position_count": "0", "validation_error_count": "0",
            "safety_notes": "template_only=yes; local_positions_created=no; broker_used=no; orders_created=no; email_sent=no; scheduler_used=no; archived_legacy_used=no",
        })


def main() -> None:
    write_csv(TEMPLATE_PATH, [], POSITION_FIELDS)
    example_rows = [
        {
            "ticker": "SAMPLECO", "entry_date": "2026-01-15", "entry_price": "100.00", "position_pct": "3.00",
            "shares_optional": "", "thesis": "Illustrative medium-conviction thesis; not a real holding.",
            "horizon_class": "medium_conviction", "planned_review_date": "2026-02-15",
            "max_loss_pct_of_account": "0.60", "invalidation_rule": "Illustrative thesis metric fails.",
            "current_action": "hold_existing", "notes": "Example row only.",
        },
        {
            "ticker": "WATCHEX", "entry_date": "", "entry_price": "", "position_pct": "0.00",
            "shares_optional": "", "thesis": "Illustrative research-only idea; not a real holding.",
            "horizon_class": "watch_only", "planned_review_date": "2026-02-15",
            "max_loss_pct_of_account": "0.00", "invalidation_rule": "Research thesis no longer merits monitoring.",
            "current_action": "watch_only", "notes": "Example row only.",
        },
    ]
    write_csv(EXAMPLE_PATH, example_rows, POSITION_FIELDS)
    schema_rows = [
        {"column_name": "ticker", "required": "yes", "data_type": "text", "allowed_values": "non-empty ticker", "description": "Security identifier.", "example": "SAMPLECO"},
        {"column_name": "entry_date", "required": "yes", "data_type": "date_or_blank_for_watch", "allowed_values": "YYYY-MM-DD or blank for watch_only", "description": "Manual entry date.", "example": "2026-01-15"},
        {"column_name": "entry_price", "required": "yes", "data_type": "number_or_blank_for_watch", "allowed_values": "non-negative", "description": "Manual reference entry price.", "example": "100.00"},
        {"column_name": "position_pct", "required": "yes", "data_type": "number", "allowed_values": "0 to 100", "description": "Percent of account represented by the position.", "example": "3.00"},
        {"column_name": "shares_optional", "required": "no", "data_type": "number_or_blank", "allowed_values": "non-negative", "description": "Optional private share count.", "example": ""},
        {"column_name": "thesis", "required": "yes", "data_type": "text", "allowed_values": "free text", "description": "Current investment thesis.", "example": "Illustrative thesis."},
        {"column_name": "horizon_class", "required": "yes", "data_type": "enum", "allowed_values": "short_swing;medium_conviction;core_compounder;watch_only", "description": "Expected research and holding horizon.", "example": "medium_conviction"},
        {"column_name": "planned_review_date", "required": "yes", "data_type": "date", "allowed_values": "YYYY-MM-DD", "description": "Next planned human review date.", "example": "2026-02-15"},
        {"column_name": "max_loss_pct_of_account", "required": "yes", "data_type": "number", "allowed_values": "non-negative", "description": "Maximum account-level loss reference for manual review.", "example": "0.60"},
        {"column_name": "invalidation_rule", "required": "yes", "data_type": "text", "allowed_values": "free text", "description": "Condition that would break or materially weaken the thesis.", "example": "Illustrative metric fails."},
        {"column_name": "current_action", "required": "yes", "data_type": "enum", "allowed_values": "hold_existing;add_review;trim_review;exit_review;new_candidate;watch_only", "description": "Current research action label.", "example": "hold_existing"},
        {"column_name": "notes", "required": "no", "data_type": "text", "allowed_values": "free text", "description": "Optional private notes.", "example": ""},
    ]
    write_csv(SCHEMA_PATH, schema_rows, ["column_name", "required", "data_type", "allowed_values", "description", "example"])
    blank_state = [{
        "generated_at": timestamp(), "status": "no_positions_file_yet", "positions_file_present": "no",
        "position_count": "0", "active_position_count": "0", "watch_only_count": "0", "total_position_pct": "0.00",
        "estimated_cash_reserve_pct": "100.00", "cash_reserve_target_pct": "10.00", "cash_reserve_target_met": "yes",
        "single_stock_default_cap_pct": "6.00", "single_stock_default_cap_breaches": "0",
        "single_stock_hard_cap_pct": "8.00", "single_stock_hard_cap_breaches": "0",
        "active_stock_sleeve_cap_pct": "30.00", "active_stock_sleeve_cap_breached": "no",
        "technology_exposure_cap_pct": "60.00", "technology_exposure_status": "not_evaluable_no_positions_file",
        "ai_infrastructure_theme_cap_pct": "35.00", "ai_infrastructure_exposure_status": "not_evaluable_no_positions_file",
        "validation_error_count": "0", "validation_errors": "", "notes": "Private positions file is optional and was not created in Phase 5R-C4.",
    }]
    write_csv(STATE_REPORT_PATH, blank_state, STATE_FIELDS)
    review_lines = [
        "# Phase 5R-C4 Blank Position Review", "", "Review date: `YYYY-MM-DD`", "",
        "## Portfolio State", "", "- Current positions file present: `no / yes`", "- Estimated cash reserve: `n/a`", "- Active stock sleeve: `n/a`", "",
        "## Position Reviews", "", "For each active position: thesis status, horizon, planned review date, invalidation changes, concentration, and current action.", "",
        "## New Candidates", "", "- Default weekly range: `0 to 2`", "- Candidate decisions: `eligible_buy_review / wait_for_pullback / reject / watch_only`", "",
        "## Concentration", "", "Check single-stock, active sleeve, technology, AI-infrastructure, and cash-reserve limits before any add review.", "",
        "## Monthly Rebalance", "", "Complete this section only during the monthly rebalance review.", "",
        "## Manual Boundary", "", "This review does not connect to a broker or authorize an automated transaction.",
    ]
    BLANK_REVIEW_PATH.write_text("\n".join(review_lines) + "\n", encoding="utf-8")
    append_log([TEMPLATE_PATH, EXAMPLE_PATH, SCHEMA_PATH, STATE_REPORT_PATH, BLANK_REVIEW_PATH])
    print("Created Phase 5R-C4 position templates without creating a private positions file.")


if __name__ == "__main__":
    main()
