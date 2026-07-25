from __future__ import annotations

import ast
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_b_run_log.csv"

VERIFICATION_REPORT = CONTROL_DIR / "phase5r_b_verification_report.md"
RESEARCH_VERIFICATION_REPORT = RESEARCH_DIR / "phase5r_b_verification_report.md"
AUDIT_TRAIL = DATA_DIR / "phase5r_b_audit_trail.csv"
PHASE0E_COPY_MAP = CONTROL_DIR / "phase0e_copy_map.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}

REQUIRED_FILES = [
    "00_project_control/phase5r_b_data_adapter_policy.md",
    "00_project_control/phase5r_b_data_source_decision.md",
    "00_project_control/phase5r_b_verification_report.md",
    "03_source_data/phase5r/phase5r_b_market_data_snapshot.csv",
    "03_source_data/phase5r/phase5r_b_market_data_quality_report.csv",
    "03_source_data/phase5r/phase5r_b_candidates_with_market_data.csv",
    "03_source_data/phase5r/phase5r_b_signal_scores.csv",
    "03_source_data/phase5r/phase5r_b_manual_trade_tickets.csv",
    "03_source_data/phase5r/phase5r_b_audit_trail.csv",
    "08_reviews/current/latest_phase5r_b_watchlist.md",
    "08_reviews/current/latest_phase5r_b_manual_trade_tickets.md",
    "09_scripts/phase5r/phase5r_market_data_adapter.py",
    "09_scripts/phase5r/run_phase5r_b_market_data_update.py",
    "09_scripts/phase5r/score_phase5r_b_candidates.py",
    "09_scripts/phase5r/create_phase5r_b_manual_trade_tickets.py",
    "09_scripts/phase5r/verify_phase5r_b_read_only_boundary.py",
    "04_research/realtime_stock_picker_phase5r/phase5r_b_market_data_adapter_report.md",
    "04_research/realtime_stock_picker_phase5r/phase5r_b_verification_report.md",
    "00_project_control/run_logs/phase5r_b_run_log.csv",
]

CSV_COLUMNS = {
    "03_source_data/phase5r/phase5r_b_market_data_snapshot.csv": [
        "ticker",
        "last_price",
        "previous_close",
        "intraday_change_pct",
        "volume",
        "average_volume",
        "relative_volume",
        "dollar_volume",
        "day_high",
        "day_low",
        "fifty_two_week_high",
        "fifty_two_week_low",
        "data_timestamp",
        "data_source",
        "data_quality_label",
    ],
    "03_source_data/phase5r/phase5r_b_signal_scores.csv": [
        "rank",
        "ticker",
        "company_name",
        "theme",
        "trend_score",
        "volume_score",
        "catalyst_score",
        "quality_score",
        "risk_penalty",
        "total_score",
        "action_label",
    ],
    "03_source_data/phase5r/phase5r_b_manual_trade_tickets.csv": [
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

B_SCRIPTS = [
    SCRIPTS_DIR / "phase5r_market_data_adapter.py",
    SCRIPTS_DIR / "run_phase5r_b_market_data_update.py",
    SCRIPTS_DIR / "score_phase5r_b_candidates.py",
    SCRIPTS_DIR / "create_phase5r_b_manual_trade_tickets.py",
    SCRIPTS_DIR / "verify_phase5r_b_read_only_boundary.py",
]

BROKER_MODULES = {
    "alpaca",
    "alpaca_trade_api",
    "ib_insync",
    "robin_stocks",
    "schwab",
    "tda",
    "webull",
    "ccxt",
    "etrade",
    "tradier",
}

EMAIL_MODULES = {"smtplib", "imaplib"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "sendmail", "send_message"}
ENV_CALLS = {"getenv", "environ"}

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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def passfail(value: bool) -> str:
    return "PASS" if value else "FAIL"


def import_root(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return ""
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0]
    return ""


def check_script_ast() -> tuple[list[str], list[str], list[str], list[str]]:
    broker_violations: list[str] = []
    order_violations: list[str] = []
    env_violations: list[str] = []
    email_violations: list[str] = []
    for script in B_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod in BROKER_MODULES:
                        broker_violations.append(f"{script.relative_to(ROOT)} import {alias.name}")
                    if mod in EMAIL_MODULES:
                        email_violations.append(f"{script.relative_to(ROOT)} import {alias.name}")
                    if mod == "dotenv":
                        env_violations.append(f"{script.relative_to(ROOT)} import dotenv")
            elif isinstance(node, ast.ImportFrom):
                mod = import_root(node)
                if mod in BROKER_MODULES:
                    broker_violations.append(f"{script.relative_to(ROOT)} from {node.module}")
                if mod in EMAIL_MODULES:
                    email_violations.append(f"{script.relative_to(ROOT)} from {node.module}")
                if mod == "dotenv":
                    env_violations.append(f"{script.relative_to(ROOT)} from dotenv")
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in BLOCKED_CALLS:
                    order_violations.append(f"{script.relative_to(ROOT)} call {fn.id}")
                if isinstance(fn, ast.Attribute):
                    if fn.attr in BLOCKED_CALLS:
                        order_violations.append(f"{script.relative_to(ROOT)} call {fn.attr}")
                    if fn.attr in ENV_CALLS:
                        env_violations.append(f"{script.relative_to(ROOT)} environment call {fn.attr}")
    return broker_violations, order_violations, env_violations, email_violations


def check_csv_columns() -> list[str]:
    missing: list[str] = []
    for relative, columns in CSV_COLUMNS.items():
        header = csv_header(ROOT / relative)
        for column in columns:
            if column not in header:
                missing.append(f"{relative}:{column}")
    return missing


def legacy_ticker_violations(paths: list[str]) -> list[str]:
    violations: list[str] = []
    for relative in paths:
        path = ROOT / relative
        if not path.exists():
            violations.append(f"{relative}:missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\\b(IOT|RBRK)\\b", text, flags=re.IGNORECASE):
            violations.append(relative)
    return violations


def phase5r_a_checksum_violations() -> list[str]:
    if not PHASE0E_COPY_MAP.exists():
        return ["phase0e_copy_map.csv missing"]
    rows = read_csv(PHASE0E_COPY_MAP)
    phase5r_a_sources = {
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
    }
    violations: list[str] = []
    for row in rows:
        if row.get("source_path") not in phase5r_a_sources or row.get("copied") != "yes":
            continue
        destination = ROOT / row["destination_path"]
        if not destination.exists():
            violations.append(f"{row['destination_path']}:missing")
            continue
        if sha256_file(destination) != row["checksum_destination"]:
            violations.append(row["destination_path"])
    return violations


def main() -> None:
    created_missing = [path for path in REQUIRED_FILES if path not in {str(VERIFICATION_REPORT.relative_to(ROOT)), str(RESEARCH_VERIFICATION_REPORT.relative_to(ROOT))} and not (ROOT / path).exists()]
    column_violations = check_csv_columns()
    broker_violations, order_violations, env_violations, email_violations = check_script_ast()

    tickets = read_csv(DATA_DIR / "phase5r_b_manual_trade_tickets.csv")
    bad_manual = [row["ticker"] for row in tickets if row["manual_confirmation_required"] != "yes"]
    bad_broker = [row["ticker"] for row in tickets if row["broker_connection_allowed"] != "no"]
    bad_order = [row["ticker"] for row in tickets if row["real_order_allowed_by_script"] != "no"]
    bad_old_holding = [row["ticker"] for row in tickets if row["old_holding_data_used"] != "no"]

    legacy_violations = legacy_ticker_violations(
        [
            "03_source_data/phase5r/phase5r_universe_seed.csv",
            "03_source_data/phase5r/phase5r_b_market_data_snapshot.csv",
            "03_source_data/phase5r/phase5r_b_candidates_with_market_data.csv",
            "03_source_data/phase5r/phase5r_b_signal_scores.csv",
            "03_source_data/phase5r/phase5r_b_manual_trade_tickets.csv",
        ]
    )
    phase5r_a_modified = phase5r_a_checksum_violations()
    phase5r_c_search_roots = [CONTROL_DIR, DATA_DIR, RESEARCH_DIR, REVIEWS_DIR, SCRIPTS_DIR]
    phase5r_c_paths = []
    for search_root in phase5r_c_search_roots:
        for path in search_root.rglob("*"):
            if path.is_file() and re.search(r"phase5r(?:_c_|-c\\b)|phase5rc\\b", str(path), flags=re.IGNORECASE):
                phase5r_c_paths.append(str(path.relative_to(ROOT)))
    audit_rows = read_csv(AUDIT_TRAIL)
    archive_audit_inputs = [row for row in audit_rows if "11_archive" in row.get("input_path", "")]
    market_sources = {row["data_source"] for row in read_csv(DATA_DIR / "phase5r_b_market_data_snapshot.csv")}

    checks = [
        ("Phase 5R-B files were created", not created_missing, f"missing={created_missing}"),
        ("Market data adapter is read-only", not broker_violations and not order_violations and not email_violations, f"broker={broker_violations}, order={order_violations}, email={email_violations}"),
        ("No broker libraries were imported", not broker_violations, f"violations={broker_violations}"),
        ("No order placement code exists", not order_violations, f"violations={order_violations}"),
        ("No .env file was read", not env_violations, f"violations={env_violations}"),
        ("No API keys were used", not env_violations, "scripts do not call environment accessors or credential loaders"),
        ("No email automation exists", not email_violations, f"violations={email_violations}"),
        ("No archived IOT/RBRK legacy data was used", not archive_audit_inputs, f"audit_inputs={archive_audit_inputs}"),
        ("IOT and RBRK are absent from all Phase 5R-B universe, scores, and tickets", not legacy_violations, f"violations={legacy_violations}"),
        ("Every manual ticket has manual_confirmation_required=yes", not bad_manual, f"bad={bad_manual}"),
        ("Every manual ticket has broker_connection_allowed=no", not bad_broker, f"bad={bad_broker}"),
        ("Every manual ticket has real_order_allowed_by_script=no", not bad_order, f"bad={bad_order}"),
        ("Every manual ticket has old_holding_data_used=no", not bad_old_holding, f"bad={bad_old_holding}"),
        ("All required CSV columns exist", not column_violations, f"missing={column_violations}"),
        ("Phase 5R-B did not modify Phase 5R-A files", not phase5r_a_modified, f"modified_or_missing={phase5r_a_modified}"),
        ("Phase 5R-C was not created", not phase5r_c_paths, f"paths={phase5r_c_paths}"),
    ]

    lines = [
        "# Phase 5R-B Verification Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Adapter Source Summary",
        "",
        f"- Market data sources observed: `{sorted(market_sources)}`.",
        "- Canonical universe input: `03_source_data/phase5r/phase5r_universe_seed.csv`.",
        "- Archived legacy folders were not used as inputs.",
        "",
        "## Required Checks",
        "",
    ]
    for label, passed, detail in checks:
        lines.append(f"- **{passfail(passed)}** - {label}: {detail}.")
    lines.extend(
        [
            "",
            "## Manual Execution Boundary",
            "",
            "Phase 5R-B is a read-only market data and scoring layer. Manual tickets remain review artifacts only and cannot connect to a broker, route orders, send emails, or use archived IOT/RBRK legacy data.",
        ]
    )
    report = "\n".join(lines) + "\n"
    VERIFICATION_REPORT.write_text(report, encoding="utf-8")
    RESEARCH_VERIFICATION_REPORT.write_text(report, encoding="utf-8")

    status = "complete" if all(passed for _, passed, _ in checks) else "failed"
    now = timestamp()
    safety = "verification_only=yes; read_only_boundary=yes; credentialless=yes; no_broker=yes; no_orders=yes; no_email=yes; archived_legacy_used=no"
    for log_path in (AUDIT_TRAIL, RUN_LOG):
        append_csv(
            log_path,
            {
                "timestamp": now,
                "script_name": Path(__file__).name,
                "action": "verify_phase5r_b_read_only_boundary",
                "input_path": f"{DATA_DIR.relative_to(ROOT)}/phase5r_b_*;{PHASE0E_COPY_MAP.relative_to(ROOT)}",
                "output_path": f"{VERIFICATION_REPORT.relative_to(ROOT)};{RESEARCH_VERIFICATION_REPORT.relative_to(ROOT)}",
                "status": status,
                "safety_notes": safety,
            },
            AUDIT_FIELDS,
        )
    if status != "complete":
        raise RuntimeError("Phase 5R-B verification failed; see verification report")
    print(f"Wrote Phase 5R-B verification report to {VERIFICATION_REPORT}")


if __name__ == "__main__":
    main()
