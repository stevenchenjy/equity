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
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c4_run_log.csv"
REPORT_PATH = CONTROL_DIR / "phase5r_c4_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c4_portfolio_framework_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_c4_verification_report.md"
LOCAL_PATH = POSITION_DIR / "current_positions.local.csv"
TEMPLATE_PATH = POSITION_DIR / "current_positions.local.csv.template"
EXAMPLE_PATH = POSITION_DIR / "current_positions.local.csv.example"
SCHEMA_PATH = POSITION_DIR / "phase5r_c4_position_schema.csv"
STATE_PATH = POSITION_DIR / "phase5r_c4_portfolio_state_report.csv"
D1_TEMPLATE = ROOT / "07_automation" / "scheduler" / "com.steven.phase5r.dailybrief.plist.template"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.steven.phase5r.dailybrief.plist"
C2_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c2_delivery_status.csv"
C3_LOG = CONTROL_DIR / "run_logs" / "phase5r_c3_daily_pipeline_run_log.csv"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"

C2_STATUS_BASELINE = "c548c061f0433fce31f5024af54c8ab540230e92db848989c0d1e2f02787a063"
C3_LOG_BASELINE = "8296dcbe3442bdfd9b9c065de89de6daf85cd4ad9160e7f889b3b52c29a1c649"
SMTP_CONFIG_SIZE_BASELINE = 241
SMTP_CONFIG_MTIME_BASELINE = 1783625651
POSITION_FIELDS = ["ticker", "entry_date", "entry_price", "position_pct", "shares_optional", "thesis", "horizon_class", "planned_review_date", "max_loss_pct_of_account", "invalidation_rule", "current_action", "notes"]
ALLOWED_HORIZONS = {"short_swing", "medium_conviction", "core_compounder", "watch_only"}
ALLOWED_ACTIONS = {"hold_existing", "add_review", "trim_review", "exit_review", "new_candidate", "watch_only"}
LOG_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "positions_file_present", "position_count", "validation_error_count", "safety_notes"]
REQUIRED_FILES = [
    "00_project_control/phase5r_c4_weekly_reframe_policy.md", "00_project_control/phase5r_c4_portfolio_policy.md",
    "00_project_control/phase5r_c4_holding_horizon_policy.md", "00_project_control/phase5r_c4_trade_cadence_policy.md",
    "00_project_control/phase5r_c4_concentration_policy.md", "00_project_control/phase5r_c4_d1_scheduler_parked_status.md",
    "00_project_control/phase5r_c4_verification_report.md", "05_risk_and_positions/current_positions.local.csv.template",
    "05_risk_and_positions/current_positions.local.csv.example", "05_risk_and_positions/phase5r_c4_position_schema.csv",
    "05_risk_and_positions/phase5r_c4_portfolio_state_report.csv", "05_risk_and_positions/phase5r_c4_blank_position_review.md",
    "09_scripts/phase5r/create_phase5r_c4_position_template.py", "09_scripts/phase5r/validate_phase5r_c4_position_state.py",
    "09_scripts/phase5r/verify_phase5r_c4_portfolio_boundary.py", "04_research/realtime_stock_picker_phase5r/phase5r_c4_portfolio_framework_report.md",
    "04_research/realtime_stock_picker_phase5r/phase5r_c4_verification_report.md", "00_project_control/run_logs/phase5r_c4_run_log.csv",
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
EMAIL_MODULES = {"smtplib", "imaplib", "poplib", "gmail", "sendgrid", "msal", "O365", "outlook"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "sendmail", "send_message"}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


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
    for path in [SCRIPTS_DIR / "create_phase5r_c4_position_template.py", SCRIPTS_DIR / "validate_phase5r_c4_position_state.py", Path(__file__)]:
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
    generated_reports = {str(REPORT_PATH.relative_to(ROOT)), str(RESEARCH_REPORT.relative_to(ROOT)), str(RESEARCH_VERIFICATION.relative_to(ROOT))}
    missing = [name for name in REQUIRED_FILES if name not in generated_reports and not (ROOT / name).exists()]
    template_header = csv_header(TEMPLATE_PATH)
    example_header = csv_header(EXAMPLE_PATH)
    schema_rows = read_csv(SCHEMA_PATH)
    schema_columns = {row["column_name"] for row in schema_rows}
    state_rows = read_csv(STATE_PATH)
    state = state_rows[0] if len(state_rows) == 1 else {}
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    local_ignored = "05_risk_and_positions/current_positions.local.csv" in gitignore
    d1_loaded = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{subprocess.run(['/usr/bin/id', '-u'], capture_output=True, text=True, check=True).stdout.strip()}/com.steven.phase5r.dailybrief"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0
    broker, email, blocked = scan_scripts()
    scripts_text = "\n".join(path.read_text(encoding="utf-8") for path in [SCRIPTS_DIR / "create_phase5r_c4_position_template.py", SCRIPTS_DIR / "validate_phase5r_c4_position_state.py"])
    archive_references = "11_archive" in scripts_text
    legacy_examples = [row.get("ticker", "") for row in read_csv(EXAMPLE_PATH) if row.get("ticker", "").upper() in {"IOT", "RBRK"}]
    smtp_stat = SMTP_CONFIG.stat() if SMTP_CONFIG.exists() else None
    smtp_unchanged = bool(smtp_stat) and smtp_stat.st_size == SMTP_CONFIG_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_CONFIG_MTIME_BASELINE
    c2_unchanged = digest(C2_STATUS) == C2_STATUS_BASELINE
    c3_unchanged = digest(C3_LOG) == C3_LOG_BASELINE
    phase_c5 = phase5r_c5_paths()
    checks = [
        ("weekly reframe policy created", (CONTROL_DIR / "phase5r_c4_weekly_reframe_policy.md").exists(), "policy exists"),
        ("portfolio policy created", (CONTROL_DIR / "phase5r_c4_portfolio_policy.md").exists(), "policy exists"),
        ("holding horizon policy created", (CONTROL_DIR / "phase5r_c4_holding_horizon_policy.md").exists(), "policy exists"),
        ("trade cadence policy created", (CONTROL_DIR / "phase5r_c4_trade_cadence_policy.md").exists(), "policy exists"),
        ("concentration policy created", (CONTROL_DIR / "phase5r_c4_concentration_policy.md").exists(), "policy exists"),
        ("D1 parked status created", D1_TEMPLATE.exists() and not D1_INSTALLED.exists() and not d1_loaded, f"template={D1_TEMPLATE.exists()}, installed={D1_INSTALLED.exists()}, loaded={d1_loaded}"),
        ("current_positions.local.csv.template exists", TEMPLATE_PATH.exists() and template_header == POSITION_FIELDS, f"header_ok={template_header == POSITION_FIELDS}"),
        ("current_positions.local.csv.example exists", EXAMPLE_PATH.exists() and example_header == POSITION_FIELDS, f"header_ok={example_header == POSITION_FIELDS}"),
        ("current_positions.local.csv is gitignored", local_ignored, f"gitignored={local_ignored}"),
        ("position schema contains all required columns and enums", schema_columns == set(POSITION_FIELDS) and all(value in SCHEMA_PATH.read_text(encoding="utf-8") for value in ALLOWED_HORIZONS | ALLOWED_ACTIONS), f"schema_columns={sorted(schema_columns)}"),
        ("no real positions are required in this phase", not LOCAL_PATH.exists() and state.get("status") == "no_positions_file_yet", f"local_exists={LOCAL_PATH.exists()}, state_status={state.get('status')}"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not blocked, f"violations={blocked}"),
        ("no email sent", not email and c2_unchanged and c3_unchanged, f"email_imports={email}, c2_log_unchanged={c2_unchanged}, c3_log_unchanged={c3_unchanged}"),
        ("no scheduler installed or loaded", not D1_INSTALLED.exists() and not d1_loaded, f"installed={D1_INSTALLED.exists()}, loaded={d1_loaded}"),
        ("no archived legacy data used", not archive_references, f"archive_references={archive_references}"),
        ("old IOT/RBRK holding files are not read", not legacy_examples and not archive_references, f"legacy_examples={legacy_examples}"),
        ("SMTP config was not modified", smtp_unchanged and "phase5r_email_config.local.json" not in scripts_text, f"metadata_unchanged={smtp_unchanged}, config_path_in_c4_scripts={'phase5r_email_config.local.json' in scripts_text}"),
        ("Phase 5R-C5 was not created", not phase_c5, f"paths={phase_c5}"),
        ("all required C4 files were created", not missing, f"missing={missing}"),
    ]
    lines = ["# Phase 5R-C4 Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    for label, passed, detail in checks:
        lines.append(f"- **{'PASS' if passed else 'FAIL'}** - {label}: {detail}.")
    lines.extend(["", "## State", "", f"- Private positions file present: `{'yes' if LOCAL_PATH.exists() else 'no'}`.", f"- Portfolio-state status: `{state.get('status', 'missing')}`.", "- D1 scheduler status: `parked / inactive`.", "- Position data, broker accounts, SMTP configuration, archived legacy files, and the daily email pipeline were not read or invoked by C4.", "", "## Boundary", "", "C4 creates a weekly research and local portfolio-state framework only. It does not send email, schedule work, connect to a broker, place orders, require private position data, or create Phase 5R-C5."])
    report_text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(report_text, encoding="utf-8")
    research_lines = [
        "# Phase 5R-C4 Portfolio Framework Report", "", f"Generated: `{timestamp()}`", "", "## Framework", "",
        "C4 reframes Phase 5R around weekly conviction research, explicit holding horizons, a private local position-state schema, concentration controls, and manual review decisions.", "",
        "## Current State", "", f"- Private positions file present: `{'yes' if LOCAL_PATH.exists() else 'no'}`.",
        f"- Validation status: `{state.get('status', 'missing')}`.", "- D1 scheduler: `parked / inactive`.",
        "- New buy-review candidate cadence: `0 to 2 per week`.", "- Portfolio review cadence: `weekly`.", "- Rebalance review cadence: `monthly`.", "",
        "## Safety Boundary", "", "Manual execution only. No daily scheduler, email send, broker connection, order placement, archived legacy input, old holding data, SMTP configuration change, cloud deployment, or Phase 5R-C5.",
    ]
    RESEARCH_REPORT.write_text("\n".join(research_lines) + "\n", encoding="utf-8")
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=LOG_FIELDS).writerow({
            "timestamp": timestamp(), "script_name": Path(__file__).name, "action": "verify_phase5r_c4_portfolio_boundary",
            "input_path": "05_risk_and_positions/current_positions.local.csv (optional)",
            "output_path": f"{REPORT_PATH.relative_to(ROOT)};{RESEARCH_REPORT.relative_to(ROOT)};{RESEARCH_VERIFICATION.relative_to(ROOT)}",
            "status": "complete" if all(passed for _, passed, _ in checks) else "failed",
            "positions_file_present": "yes" if LOCAL_PATH.exists() else "no", "position_count": state.get("position_count", "0"),
            "validation_error_count": state.get("validation_error_count", "0"),
            "safety_notes": "weekly_reframe=yes; d1_parked=yes; broker_used=no; orders_created=no; email_sent=no; config_modified=no; archived_legacy_used=no",
        })
    if not all(passed for _, passed, _ in checks):
        raise RuntimeError("Phase 5R-C4 verification failed; see verification report")
    print("Wrote Phase 5R-C4 verification reports; D1 remains parked and no private positions file was required.")


if __name__ == "__main__":
    main()
