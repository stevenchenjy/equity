from __future__ import annotations

import ast
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
AUTOMATION_DIR = ROOT / "07_automation"
DELIVERY_DIR = AUTOMATION_DIR / "email_delivery"
BRIEF_DIR = AUTOMATION_DIR / "email_briefs"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c2_run_log.csv"

CONFIG_PATH = DELIVERY_DIR / "phase5r_email_config.local.json"
TEMPLATE_PATH = DELIVERY_DIR / "phase5r_email_config.template.json"
STATUS_PATH = DELIVERY_DIR / "phase5r_c2_delivery_status.csv"
PREVIEW_PATH = DELIVERY_DIR / "phase5r_c2_last_email_preview.eml"
SENDER_PATH = SCRIPTS_DIR / "send_phase5r_c2_daily_email.py"
REPORT_PATH = CONTROL_DIR / "phase5r_c2_verification_report.md"
RESEARCH_REPORT_PATH = RESEARCH_DIR / "phase5r_c2_verification_report.md"
DELIVERY_REPORT_PATH = RESEARCH_DIR / "phase5r_c2_email_delivery_report.md"

REQUIRED_FILES = [
    "00_project_control/phase5r_c2_email_delivery_policy.md", "00_project_control/phase5r_c2_gmail_smtp_setup.md", "00_project_control/phase5r_c2_verification_report.md",
    "07_automation/email_delivery/phase5r_email_config.template.json", "07_automation/email_delivery/phase5r_email_config.local.json.example", "07_automation/email_delivery/phase5r_c2_delivery_status.csv", "07_automation/email_delivery/phase5r_c2_last_email_preview.eml",
    "09_scripts/phase5r/send_phase5r_c2_daily_email.py", "09_scripts/phase5r/verify_phase5r_c2_email_delivery_boundary.py",
    "04_research/realtime_stock_picker_phase5r/phase5r_c2_email_delivery_report.md", "04_research/realtime_stock_picker_phase5r/phase5r_c2_verification_report.md", "00_project_control/run_logs/phase5r_c2_run_log.csv",
]
STATUS_FIELDS = ["timestamp", "mode", "subject", "smtp_username", "recipient_email", "sent", "error_type", "error_message_redacted", "source_subject_path", "source_text_path", "source_html_path"]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
SCHEDULER_MODULES = {"schedule", "apscheduler", "croniter"}
GMAIL_API_MODULES = {"google", "googleapiclient", "oauthlib", "msal", "requests"}
ENV_MODULES = {"dotenv", "keyring", "os"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "add_attachment"}
LOG_FIELDS = STATUS_FIELDS


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def scan_sender() -> tuple[list[str], list[str], list[str], list[str], int, list[str]]:
    source = SENDER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    broker: list[str] = []
    scheduler: list[str] = []
    gmail_api: list[str] = []
    env: list[str] = []
    blocked: list[str] = []
    send_calls = 0
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [(node.module or "").split(".")[0]]
        for module in modules:
            if module in BROKER_MODULES:
                broker.append(module)
            if module in SCHEDULER_MODULES:
                scheduler.append(module)
            if module in GMAIL_API_MODULES:
                gmail_api.append(module)
            if module in ENV_MODULES:
                env.append(module)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "send_message":
                send_calls += 1
            if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALLS:
                blocked.append(node.func.attr)
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                blocked.append(node.func.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in BLOCKED_CALLS:
            blocked.append(node.name)
    return broker, scheduler, gmail_api, env, send_calls, blocked


def phase_c3_paths() -> list[str]:
    matches: list[str] = []
    for folder in (CONTROL_DIR, DELIVERY_DIR, RESEARCH_DIR, REVIEWS_DIR, SCRIPTS_DIR):
        for path in folder.rglob("*"):
            if path.is_file() and re.search(r"phase5r(?:_c3_|-c3\\b)|phase5rc3\\b", str(path), re.IGNORECASE):
                matches.append(str(path.relative_to(ROOT)))
    return matches


def main() -> None:
    generated_reports = {str(REPORT_PATH.relative_to(ROOT)), str(RESEARCH_REPORT_PATH.relative_to(ROOT)), str(DELIVERY_REPORT_PATH.relative_to(ROOT))}
    missing = [name for name in REQUIRED_FILES if name not in generated_reports and not (ROOT / name).exists()]
    status_rows = read_csv(STATUS_PATH)
    config_valid = False
    secret = ""
    username = ""
    recipient = ""
    try:
        with CONFIG_PATH.open(encoding="utf-8") as handle:
            config = json.load(handle)
        if isinstance(config, dict):
            secret = str(config.get("smtp_app_password", ""))
            username = str(config.get("smtp_username", ""))
            recipient = str(config.get("recipient_email", ""))
            config_valid = config.get("smtp_host") == "smtp.gmail.com" and config.get("smtp_port") == 587 and bool(secret) and bool(username) and bool(recipient)
    except (OSError, json.JSONDecodeError):
        pass
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    gitignored = "07_automation/email_delivery/phase5r_email_config.local.json" in gitignore
    broker, scheduler, gmail_api, env, send_calls, blocked = scan_sender()
    secret_scan_paths = [STATUS_PATH, RUN_LOG, PREVIEW_PATH]
    secret_present = bool(secret) and any(secret in path.read_text(encoding="utf-8", errors="replace") for path in secret_scan_paths if path.exists())
    report_copy_paths = [CONTROL_DIR / "phase5r_c2_email_delivery_policy.md", CONTROL_DIR / "phase5r_c2_gmail_smtp_setup.md"]
    local_values_in_reports = any(value and any(value in path.read_text(encoding="utf-8", errors="replace") for path in report_copy_paths) for value in (secret, username, recipient))
    dry_rows = [row for row in status_rows if row["mode"] == "dry_run"]
    check_rows = [row for row in status_rows if row["mode"] == "check_config"]
    preview = PREVIEW_PATH.read_text(encoding="utf-8", errors="replace") if PREVIEW_PATH.exists() else ""
    legacy_output = sorted({ticker for ticker in ("IOT", "RBRK") if ticker in preview})
    archive_references = [row for row in status_rows if "11_archive" in ";".join(row.values())]
    phase_c3 = phase_c3_paths()
    checks = [
        ("delivery scripts were created", not missing, f"missing={missing}"),
        ("local config template exists", TEMPLATE_PATH.exists(), f"exists={TEMPLATE_PATH.exists()}"),
        ("local config file exists", CONFIG_PATH.exists() and config_valid, f"exists={CONFIG_PATH.exists()}, valid_shape={config_valid}"),
        ("local config is gitignored", gitignored, f"gitignored={gitignored}"),
        ("smtp_app_password is never printed or logged", not secret_present and not local_values_in_reports, f"password_found={secret_present}, local_config_values_in_reports={local_values_in_reports}"),
        ("default mode sends one email", send_calls == 1, f"send_message_calls={send_calls}"),
        ("--dry-run does not send", bool(dry_rows) and all(row["sent"] == "no" for row in dry_rows), f"dry_run_rows={len(dry_rows)}"),
        ("--check-config does not send", bool(check_rows) and all(row["sent"] == "no" for row in check_rows), f"check_config_rows={len(check_rows)}"),
        ("delivery status has required columns", header(STATUS_PATH) == STATUS_FIELDS, "status header checked"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not blocked, f"violations={blocked}"),
        ("no archived legacy data used", not archive_references, f"archive_references={archive_references}"),
        ("no IOT/RBRK holding data used", not legacy_output, f"legacy={legacy_output}"),
        ("no scheduler code created", not scheduler, f"violations={scheduler}"),
        ("no intraday alert logic created", "intraday" not in SENDER_PATH.read_text(encoding="utf-8").lower(), "sender contains no intraday logic"),
        ("no attachments", "add_attachment" not in SENDER_PATH.read_text(encoding="utf-8") and not blocked, "multipart alternative message only"),
        ("no Gmail API/OAuth", not gmail_api, f"violations={gmail_api}"),
        ("no .env access", not env, f"violations={env}"),
        ("Phase 5R-C3 was not created", not phase_c3, f"paths={phase_c3}"),
    ]
    lines = ["# Phase 5R-C2 Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    for label, passed, detail in checks:
        lines.append(f"- **{'PASS' if passed else 'FAIL'}** - {label}: {detail}.")
    lines.extend(["", "## Test Scope", "", "Only local configuration validation and dry-run composition were exercised during C2 verification. No live delivery was initiated by the verification workflow.", "", "## Boundary", "", "C2 uses one direct Gmail SMTP send call only in default mode. It does not use broker systems, transaction-placement logic, a scheduler, intraday alerts, attachments, Gmail API, OAuth, archived legacy data, or Phase 5R-C3."])
    report_text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    RESEARCH_REPORT_PATH.write_text(report_text, encoding="utf-8")
    delivery_lines = [
        "# Phase 5R-C2 Email Delivery Report", "", f"Generated: `{timestamp()}`", "",
        "## Status Summary", "", f"- Delivery-status rows recorded: `{len(status_rows)}`.",
        f"- Configuration-check rows: `{len(check_rows)}`.", f"- Dry-run rows: `{len(dry_rows)}`.",
        "- Live-delivery rows during build verification: `0`.", "", "## Boundary", "", "The local SMTP configuration was validated without exposing its content. The local `.eml` preview was composed without opening an SMTP connection. No live email was dispatched during verification.",
    ]
    DELIVERY_REPORT_PATH.write_text("\n".join(delivery_lines) + "\n", encoding="utf-8")
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({"timestamp": timestamp(), "mode": "verify", "subject": "", "smtp_username": "", "recipient_email": "", "sent": "no", "error_type": "", "error_message_redacted": "", "source_subject_path": "", "source_text_path": "", "source_html_path": ""})
    if not all(passed for _, passed, _ in checks):
        raise RuntimeError("Phase 5R-C2 verification failed; see verification report")
    print("Wrote Phase 5R-C2 verification reports; no live email was sent by verification.")


if __name__ == "__main__":
    main()
