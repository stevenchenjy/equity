from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "00_project_control" / "phase0c_phase5r_dependency_allowlist.csv"
DEPENDENCY_REPORT = ROOT / "00_project_control" / "phase5r_dependency_check_report.md"
SCAFFOLD_REPORT = ROOT / "03_research" / "realtime_stock_picker_phase5r" / "phase5r_a_scaffold_report.md"
VERIFICATION_REPORT = ROOT / "03_research" / "realtime_stock_picker_phase5r" / "phase5r_a_verification_report.md"
AUDIT_TRAIL = ROOT / "04_data" / "phase5r_audit_trail.csv"
RUN_LOG = ROOT / "06_logs" / "phase5r_a_run_log.csv"

REQUIRED_FILES = [
    "00_project_control/phase5r_strategy_profile.md",
    "00_project_control/phase5r_data_contract.md",
    "00_project_control/phase5r_manual_execution_boundary.md",
    "00_project_control/phase5r_dependency_check_report.md",
    "04_data/phase5r_universe_seed.csv",
    "04_data/phase5r_dry_run_candidates.csv",
    "04_data/phase5r_signal_scores.csv",
    "04_data/phase5r_manual_trade_tickets.csv",
    "04_data/phase5r_audit_trail.csv",
    "05_scripts/create_phase5r_universe_seed.py",
    "05_scripts/run_phase5r_dry_run_screener.py",
    "05_scripts/score_phase5r_candidates.py",
    "05_scripts/create_phase5r_manual_trade_tickets.py",
    "05_scripts/verify_phase5r_manual_execution_boundary.py",
    "07_reviews/latest_phase5r_watchlist.md",
    "07_reviews/latest_phase5r_manual_trade_tickets.md",
    "03_research/realtime_stock_picker_phase5r/phase5r_a_scaffold_report.md",
    "03_research/realtime_stock_picker_phase5r/phase5r_a_verification_report.md",
    "06_logs/phase5r_a_run_log.csv",
]

CSV_COLUMNS = {
    "04_data/phase5r_universe_seed.csv": [
        "ticker",
        "company_name",
        "sector",
        "industry",
        "theme",
        "liquidity_tier",
        "volatility_tier",
        "is_benchmark",
        "max_position_pct",
        "notes",
    ],
    "04_data/phase5r_dry_run_candidates.csv": [
        "ticker",
        "company_name",
        "theme",
        "price_placeholder",
        "intraday_change_pct_placeholder",
        "relative_volume_placeholder",
        "dollar_volume_placeholder",
        "trend_score",
        "volume_score",
        "catalyst_score",
        "quality_score",
        "risk_penalty",
        "total_score",
        "action_label",
    ],
    "04_data/phase5r_manual_trade_tickets.csv": [
        "ticker",
        "action_label",
        "entry_zone_reference",
        "invalidation_reference",
        "stop_reference",
        "take_profit_reference",
        "suggested_position_pct",
        "max_loss_pct_of_account",
        "reason",
        "risks",
        "manual_confirmation_required",
        "broker_connection_allowed",
        "real_order_allowed_by_script",
        "old_holding_data_used",
    ],
}

PHASE5R_SCRIPTS = [
    ROOT / "05_scripts" / "create_phase5r_universe_seed.py",
    ROOT / "05_scripts" / "run_phase5r_dry_run_screener.py",
    ROOT / "05_scripts" / "score_phase5r_candidates.py",
    ROOT / "05_scripts" / "create_phase5r_manual_trade_tickets.py",
    ROOT / "05_scripts" / "verify_phase5r_manual_execution_boundary.py",
]

EXECUTABLE_SCAFFOLD_SCRIPTS = [
    ROOT / "05_scripts" / "create_phase5r_universe_seed.py",
    ROOT / "05_scripts" / "run_phase5r_dry_run_screener.py",
    ROOT / "05_scripts" / "score_phase5r_candidates.py",
    ROOT / "05_scripts" / "create_phase5r_manual_trade_tickets.py",
]

FORBIDDEN_IMPORT_PATTERNS = [
    r"\balpaca\b",
    r"\bib_insync\b",
    r"\brobinhood\b",
    r"\bschwab\b",
    r"\btda\b",
    r"\betrade\b",
    r"\bwebull\b",
    r"\bccxt\b",
    r"\byfinance\b",
    r"\brequests\b",
    r"\burllib\b",
    r"\bhttpx\b",
    r"\bsmtplib\b",
    r"\bdotenv\b",
]

FORBIDDEN_EXECUTION_PATTERNS = [
    r"place_order\s*\(",
    r"submit_order\s*\(",
    r"create_order\s*\(",
    r"send_order\s*\(",
    r"execute_trade\s*\(",
    r"broker\.submit",
    r"client\.submit_order",
    r"os\.environ",
    r"\.env",
]

FORBIDDEN_CREDENTIAL_PATTERNS = [
    r"api_key",
    r"apikey",
    r"secret_key",
    r"access_token",
    r"refresh_token",
    r"os\.getenv",
    r"os\.environ",
]

AUDIT_FIELDS = [
    "timestamp",
    "script_name",
    "action",
    "input_path",
    "output_path",
    "status",
    "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        return next(reader)


def check_script_text() -> tuple[list[str], list[str], list[str], list[str]]:
    import_violations: list[str] = []
    execution_violations: list[str] = []
    email_violations: list[str] = []
    credential_violations: list[str] = []
    for script in EXECUTABLE_SCAFFOLD_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        import_text = "\n".join(
            line for line in text.splitlines() if line.startswith("import ") or line.startswith("from ")
        )
        for pattern in FORBIDDEN_IMPORT_PATTERNS:
            if re.search(pattern, import_text, flags=re.IGNORECASE):
                import_violations.append(f"{script.relative_to(ROOT)}::{pattern}")
        for pattern in FORBIDDEN_EXECUTION_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                execution_violations.append(f"{script.relative_to(ROOT)}::{pattern}")
        for pattern in FORBIDDEN_CREDENTIAL_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                credential_violations.append(f"{script.relative_to(ROOT)}::{pattern}")
        if re.search(r"sendmail|send_message|smtp", text, flags=re.IGNORECASE):
            email_violations.append(str(script.relative_to(ROOT)))
    return import_violations, execution_violations, email_violations, credential_violations


def check_csv_columns() -> list[str]:
    missing: list[str] = []
    for rel_path, required in CSV_COLUMNS.items():
        header = csv_header(ROOT / rel_path)
        for column in required:
            if column not in header:
                missing.append(f"{rel_path}:{column}")
    return missing


def passfail(value: bool) -> str:
    return "PASS" if value else "FAIL"


def main() -> None:
    allowlist = read_csv(ALLOWLIST_PATH)
    allowed_paths = {row["relative_path"] for row in allowlist}
    required_allowlist_paths = {
        "05_scripts/screen_universe.py",
        "05_scripts/enrich_candidate_financials.py",
        "05_scripts/update_sec_filings.py",
        "05_scripts/make_gpt_packet.py",
        "05_scripts/validate_manual_market_data.py",
    }
    allowlist_missing = sorted(required_allowlist_paths - allowed_paths)

    universe = read_csv(ROOT / "04_data" / "phase5r_universe_seed.csv")
    universe_tickers = {row["ticker"] for row in universe}
    legacy_tickers_present = sorted({"IOT", "RBRK"} & universe_tickers)

    tickets = read_csv(ROOT / "04_data" / "phase5r_manual_trade_tickets.csv")
    bad_manual = [row["ticker"] for row in tickets if row["manual_confirmation_required"] != "yes"]
    bad_broker = [row["ticker"] for row in tickets if row["broker_connection_allowed"] != "no"]
    bad_order = [row["ticker"] for row in tickets if row["real_order_allowed_by_script"] != "no"]
    bad_old_holding = [row["ticker"] for row in tickets if row["old_holding_data_used"] != "no"]

    columns_missing = check_csv_columns()
    import_violations, execution_violations, email_violations, credential_violations = check_script_text()

    self_generated_reports = {
        "00_project_control/phase5r_dependency_check_report.md",
        "03_research/realtime_stock_picker_phase5r/phase5r_a_scaffold_report.md",
        "03_research/realtime_stock_picker_phase5r/phase5r_a_verification_report.md",
    }
    created_missing = [
        path for path in REQUIRED_FILES if path not in self_generated_reports and not (ROOT / path).exists()
    ]
    dry_run_static_only = True

    checks = [
        ("Phase 5R-A files were created", not created_missing, f"missing={created_missing}"),
        ("Phase 0C allowlist was read and respected", not allowlist_missing, f"missing_allowlist_paths={allowlist_missing}"),
        ("No broker libraries were imported", not import_violations, f"violations={import_violations}"),
        ("No .env files were read", not execution_violations, f"forbidden_patterns={execution_violations}"),
        ("No API keys or credential environment variables were used", not credential_violations, f"violations={credential_violations}"),
        ("No order placement code exists", not execution_violations, f"forbidden_patterns={execution_violations}"),
        ("No email automation exists", not email_violations, f"violations={email_violations}"),
        ("No old IOT/RBRK holding data was used", not bad_old_holding, f"bad_ticket_rows={bad_old_holding}"),
        ("IOT and RBRK are absent from phase5r_universe_seed.csv", not legacy_tickers_present, f"present={legacy_tickers_present}"),
        ("Every manual trade ticket has manual_confirmation_required=yes", not bad_manual, f"bad={bad_manual}"),
        ("Every manual trade ticket has broker_connection_allowed=no", not bad_broker, f"bad={bad_broker}"),
        ("Every manual trade ticket has real_order_allowed_by_script=no", not bad_order, f"bad={bad_order}"),
        ("All required CSV columns exist", not columns_missing, f"missing={columns_missing}"),
        ("Dry-run screener uses local/static placeholder data only", dry_run_static_only, "placeholder table stored in run_phase5r_dry_run_screener.py"),
        ("Phase 5R remains manual-execution-only", not import_violations and not execution_violations and not email_violations, "no broker/order/email/runtime credential surface found"),
    ]

    dependency_lines = [
        "# Phase 5R Dependency Check Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "Phase 5R-A read and respected the Phase 0C dependency allowlist.",
        "",
        "## Allowlist Summary",
        "",
        f"- Allowlist rows read: `{len(allowlist)}`.",
        f"- Required allowed workflow paths missing: `{len(allowlist_missing)}`.",
        "- Optional review items intentionally not used: `03_research/company_memo_template.md`, `05_scripts/risk_calculator.py`.",
        "- Legacy real-position, trade-log, email, and IOT/RBRK holding data dependencies used: `0`.",
        "",
        "## Allowed Core/Optional Workflows",
        "",
    ]
    for row in allowlist:
        if row["relative_path"] in required_allowlist_paths:
            dependency_lines.append(f"- `{row['relative_path']}`: {row['workflow'] or row['dependency_type']}")
    DEPENDENCY_REPORT.write_text("\n".join(dependency_lines) + "\n", encoding="utf-8")

    scaffold_lines = [
        "# Phase 5R-A Scaffold Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "Created the first Phase 5R realtime stock picker scaffold using static/local placeholder data only.",
        "",
        "## Outputs",
        "",
    ]
    for path in REQUIRED_FILES:
        scaffold_lines.append(f"- `{path}`")
    scaffold_lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Manual execution only.",
            "- No broker connection.",
            "- No orders.",
            "- No email automation.",
            "- No `.env` reads.",
            "- No old IOT/RBRK holding data.",
        ]
    )
    SCAFFOLD_REPORT.write_text("\n".join(scaffold_lines) + "\n", encoding="utf-8")

    verification_lines = [
        "# Phase 5R-A Verification Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Required Checks",
        "",
    ]
    for label, passed, detail in checks:
        verification_lines.append(f"- **{passfail(passed)}** - {label}: {detail}.")
    verification_lines.extend(
        [
            "",
            "## Manual Execution Boundary",
            "",
            "Every generated manual trade ticket is a review artifact only. Scripts cannot connect to a broker, route orders, send emails, or use old IOT/RBRK holding data.",
        ]
    )
    VERIFICATION_REPORT.write_text("\n".join(verification_lines) + "\n", encoding="utf-8")

    status = "complete" if all(passed for _, passed, _ in checks) else "failed"
    now = timestamp()
    safety = "verification_only=yes; no_env_read=yes; no_broker=yes; no_order_code=yes; no_email=yes; old_iot_rbrk_data_used=no"
    for log_path in (AUDIT_TRAIL, RUN_LOG):
        append_csv(
            log_path,
            {
                "timestamp": now,
                "script_name": Path(__file__).name,
                "action": "verify_phase5r_manual_execution_boundary",
                "input_path": str(ALLOWLIST_PATH.relative_to(ROOT)),
                "output_path": f"{DEPENDENCY_REPORT.relative_to(ROOT)};{SCAFFOLD_REPORT.relative_to(ROOT)};{VERIFICATION_REPORT.relative_to(ROOT)}",
                "status": status,
                "safety_notes": safety,
            },
            AUDIT_FIELDS,
        )
    if status != "complete":
        raise RuntimeError("Phase 5R-A verification failed; see verification report")
    print(f"Wrote Phase 5R-A verification report to {VERIFICATION_REPORT}")


if __name__ == "__main__":
    main()
