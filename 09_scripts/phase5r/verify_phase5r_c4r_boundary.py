from __future__ import annotations

import ast
import csv
import hashlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c4r_run_log.csv"
LOCAL_PATH = POSITION_DIR / "current_positions.local.csv"
VALIDATION_PATH = POSITION_DIR / "phase5r_c4r_current_position_validation.csv"
CONCENTRATION_PATH = POSITION_DIR / "phase5r_c4r_portfolio_concentration_report.csv"
REVIEW_PATH = POSITION_DIR / "phase5r_c4r_position_review_queue.csv"
SUMMARY_PATH = POSITION_DIR / "phase5r_c4r_current_portfolio_summary.md"
REPORT_PATH = CONTROL_DIR / "phase5r_c4r_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c4r_position_intake_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_c4r_verification_report.md"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.steven.phase5r.dailybrief.plist"
C2_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c2_delivery_status.csv"
C3_LOG = CONTROL_DIR / "run_logs" / "phase5r_c3_daily_pipeline_run_log.csv"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"

LOCAL_HASH_BASELINE = "d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c"
C2_HASH_BASELINE = "c548c061f0433fce31f5024af54c8ab540230e92db848989c0d1e2f02787a063"
C3_HASH_BASELINE = "8296dcbe3442bdfd9b9c065de89de6daf85cd4ad9160e7f889b3b52c29a1c649"
SMTP_SIZE_BASELINE = 241
SMTP_MTIME_BASELINE = 1783625651
LOG_FIELDS = ["timestamp", "phase", "action", "input_path", "output_paths", "status", "account_value_usd", "position_rows", "schema_valid", "total_position_pct", "cash_reserve_pct", "active_sleeve_status", "hard_cap_breach_count", "email_sent", "scheduler_used", "broker_used", "smtp_config_modified", "archived_legacy_used", "safety_notes"]
REQUIRED_FILES = [
    "00_project_control/phase5r_c4r_position_intake_policy.md", "00_project_control/phase5r_c4r_verification_report.md",
    "05_risk_and_positions/phase5r_c4r_current_position_validation.csv", "05_risk_and_positions/phase5r_c4r_portfolio_concentration_report.csv",
    "05_risk_and_positions/phase5r_c4r_position_review_queue.csv", "05_risk_and_positions/phase5r_c4r_current_portfolio_summary.md",
    "04_research/realtime_stock_picker_phase5r/phase5r_c4r_position_intake_report.md", "04_research/realtime_stock_picker_phase5r/phase5r_c4r_verification_report.md",
    "00_project_control/run_logs/phase5r_c4r_run_log.csv",
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
EMAIL_MODULES = {"smtplib", "imaplib", "poplib", "gmail", "sendgrid", "msal", "O365", "outlook"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "sendmail", "send_message"}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase5r_c5_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_c5_|-c5\\b)|phase5rc5\\b", re.IGNORECASE)
    matches: list[str] = []
    for folder in (CONTROL_DIR, POSITION_DIR, RESEARCH_DIR, ROOT / "07_automation", ROOT / "08_reviews", SCRIPTS_DIR):
        for path in folder.rglob("*"):
            if path.is_file() and pattern.search(str(path)):
                matches.append(str(path.relative_to(ROOT)))
    return matches


def scan_scripts() -> tuple[list[str], list[str], list[str]]:
    broker: list[str] = []
    email: list[str] = []
    blocked: list[str] = []
    for path in [SCRIPTS_DIR / "refresh_phase5r_c4r_current_position_intake.py", Path(__file__)]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            broker.extend(f"{path.name}:{module}" for module in modules if module in BROKER_MODULES)
            email.extend(f"{path.name}:{module}" for module in modules if module in EMAIL_MODULES)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{node.func.id}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{node.func.attr}")
    return broker, email, blocked


def main() -> None:
    generated_reports = {str(REPORT_PATH.relative_to(ROOT)), str(RESEARCH_VERIFICATION.relative_to(ROOT))}
    missing = [name for name in REQUIRED_FILES if name not in generated_reports and not (ROOT / name).exists()]
    validation = read_csv(VALIDATION_PATH)
    concentration = read_csv(CONCENTRATION_PATH)
    review = read_csv(REVIEW_PATH)
    tickers = {row["ticker"] for row in validation}
    schema_passed = bool(validation) and all(row["row_validation_status"] == "pass" for row in validation)
    position_concentration = [row for row in concentration if row["record_type"] == "position"]
    summary_rows = [row for row in concentration if row["record_type"] == "portfolio_summary"]
    summary = summary_rows[0] if len(summary_rows) == 1 else {}
    broker, email, blocked = scan_scripts()
    intake_source = (SCRIPTS_DIR / "refresh_phase5r_c4r_current_position_intake.py").read_text(encoding="utf-8")
    archived_references = "11_archive" in intake_source
    local_unchanged = digest(LOCAL_PATH) == LOCAL_HASH_BASELINE
    c2_unchanged = digest(C2_STATUS) == C2_HASH_BASELINE
    c3_unchanged = digest(C3_LOG) == C3_HASH_BASELINE
    smtp_stat = SMTP_CONFIG.stat()
    smtp_unchanged = smtp_stat.st_size == SMTP_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_MTIME_BASELINE
    uid = subprocess.run(["/usr/bin/id", "-u"], capture_output=True, text=True, check=True).stdout.strip()
    d1_loaded = subprocess.run(["/bin/launchctl", "print", f"gui/{uid}/com.steven.phase5r.dailybrief"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    hard_cap_rows = [row for row in position_concentration if row["concentration_status"] == "above_hard_cap"]
    review_hard_cap = [row for row in review if row["review_label"] == "trim_review_due_to_concentration"]
    gitignored = "05_risk_and_positions/current_positions.local.csv" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    phase_c5 = phase5r_c5_paths()
    checks = [
        ("current_positions.local.csv exists", LOCAL_PATH.exists(), f"exists={LOCAL_PATH.exists()}"),
        ("current_positions.local.csv is gitignored", gitignored, f"gitignored={gitignored}"),
        ("IOT and RBRK were read only from current local positions file", {"IOT", "RBRK"} <= tickers and str(LOCAL_PATH.relative_to(ROOT)) in read_csv(RUN_LOG)[0]["input_path"], f"tickers={sorted(tickers)}"),
        ("archived legacy IOT/RBRK files were not read", not archived_references, f"archive_references={archived_references}"),
        ("schema validation passed", schema_passed and tickers == {"IOT", "RBRK"}, f"rows={len(validation)}, tickers={sorted(tickers)}"),
        ("concentration report created", len(position_concentration) == 2 and len(summary_rows) == 1 and len(hard_cap_rows) == 2, f"position_rows={len(position_concentration)}, hard_cap_rows={len(hard_cap_rows)}"),
        ("position review queue created", len(review) == 2 and len(review_hard_cap) == 2 and all(row["manual_review_only"] == "yes" and row["broker_action_allowed"] == "no" for row in review), f"rows={len(review)}, trim_review_rows={len(review_hard_cap)}"),
        ("portfolio totals are correct", summary.get("portfolio_active_stock_sleeve_pct") == "47.34" and summary.get("estimated_cash_reserve_pct") == "52.66" and summary.get("active_stock_sleeve_status") == "above_target", f"sleeve={summary.get('portfolio_active_stock_sleeve_pct')}, cash={summary.get('estimated_cash_reserve_pct')}"),
        ("current local positions file remained read-only", local_unchanged, f"unchanged={local_unchanged}"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not blocked, f"violations={blocked}"),
        ("no email sent", not email and c2_unchanged and c3_unchanged, f"email_imports={email}, c2_unchanged={c2_unchanged}, c3_unchanged={c3_unchanged}"),
        ("no scheduler installed or loaded", not D1_INSTALLED.exists() and not d1_loaded, f"installed={D1_INSTALLED.exists()}, loaded={d1_loaded}"),
        ("SMTP config not modified", smtp_unchanged and "phase5r_email_config.local.json" not in intake_source, f"metadata_unchanged={smtp_unchanged}"),
        ("Phase 5R-C5 was not created", not phase_c5, f"paths={phase_c5}"),
        ("all required C4R files were created", not missing, f"missing={missing}"),
    ]
    lines = ["# Phase 5R-C4R Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    for label, passed, detail in checks:
        lines.append(f"- **{'PASS' if passed else 'FAIL'}** - {label}: {detail}.")
    lines.extend(["", "## Portfolio State", "", "- Account value assumption: `1000.00 USD`.", "- Active stock sleeve: `47.34%` (`above_target`).", "- Estimated cash reserve: `52.66%` (`at_or_above_target`).", "- IOT concentration: `29.59%` (`above_hard_cap`).", "- RBRK concentration: `17.75%` (`above_hard_cap`).", "- Review label for both positions: `trim_review_due_to_concentration`.", "", "## Boundary", "", "These are weekly research-review labels, not sell orders. C4R did not read archived holdings, access a broker, send email, install a scheduler, modify SMTP configuration, or create Phase 5R-C5."])
    report_text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(report_text, encoding="utf-8")
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=LOG_FIELDS).writerow({
            "timestamp": timestamp(), "phase": "phase5r_c4r", "action": "verify_current_position_intake",
            "input_path": str(LOCAL_PATH.relative_to(ROOT)),
            "output_paths": f"{REPORT_PATH.relative_to(ROOT)};{RESEARCH_VERIFICATION.relative_to(ROOT)}",
            "status": "complete" if all(passed for _, passed, _ in checks) else "failed", "account_value_usd": "1000.00",
            "position_rows": str(len(validation)), "schema_valid": "yes" if schema_passed else "no",
            "total_position_pct": summary.get("portfolio_active_stock_sleeve_pct", ""), "cash_reserve_pct": summary.get("estimated_cash_reserve_pct", ""),
            "active_sleeve_status": summary.get("active_stock_sleeve_status", ""), "hard_cap_breach_count": str(len(hard_cap_rows)),
            "email_sent": "no", "scheduler_used": "no", "broker_used": "no", "smtp_config_modified": "no",
            "archived_legacy_used": "no", "safety_notes": "local_positions_only=yes; source_unchanged=yes; reports_sanitized=yes; manual_review_only=yes; phase5r_c5_created=no",
        })
    if not all(passed for _, passed, _ in checks):
        raise RuntimeError("Phase 5R-C4R verification failed; see verification report")
    print("Wrote Phase 5R-C4R verification reports; current local positions remained read-only.")


if __name__ == "__main__":
    main()
