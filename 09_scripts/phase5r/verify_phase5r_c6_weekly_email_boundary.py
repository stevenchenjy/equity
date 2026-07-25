from __future__ import annotations

import ast
import csv
import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
BRIEF_DIR = ROOT / "07_automation" / "email_briefs"
DELIVERY_DIR = ROOT / "07_automation" / "email_delivery"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c6_run_log.csv"

LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
SUBJECT_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_subject.txt"
TEXT_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_body.txt"
HTML_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_body.html"
METADATA_PATH = BRIEF_DIR / "phase5r_c6_email_metadata.csv"
STATUS_PATH = DELIVERY_DIR / "phase5r_c6_delivery_status.csv"
PREVIEW_EML = DELIVERY_DIR / "phase5r_c6_last_email_preview.eml"
PREVIEW_MD = REVIEWS_DIR / "latest_phase5r_c6_weekly_email_preview.md"
COMPOSER = SCRIPTS_DIR / "create_phase5r_c6_weekly_email_brief.py"
SENDER = SCRIPTS_DIR / "send_phase5r_c6_weekly_email.py"
CONFIG_PATH = DELIVERY_DIR / "phase5r_email_config.local.json"
CONTROL_REPORT = CONTROL_DIR / "phase5r_c6_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c6_verification_report.md"
C2_STATUS = DELIVERY_DIR / "phase5r_c2_delivery_status.csv"
C3_LOG = CONTROL_DIR / "run_logs" / "phase5r_c3_daily_pipeline_run_log.csv"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.steven.phase5r.dailybrief.plist"

LOCAL_HASH_BASELINE = "d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c"
C2_HASH_BASELINE = "c548c061f0433fce31f5024af54c8ab540230e92db848989c0d1e2f02787a063"
C3_HASH_BASELINE = "8296dcbe3442bdfd9b9c065de89de6daf85cd4ad9160e7f889b3b52c29a1c649"
SMTP_SIZE_BASELINE = 241
SMTP_MTIME_BASELINE = 1783625651

PRIMARY_SCENARIO = "no_action_until_next_review"
REQUIRED_MAIN_WORDING = (
    "This week\u2019s primary plan is no action until the next weekly review. "
    "IOT and RBRK remain concentration risks, so they stay on trim review, "
    "but this brief does not recommend a portfolio change today."
)
REQUIRED_SECTIONS = [
    "1. Header", "2. This Week's Main Decision", "3. Current Position Review",
    "4. Why No Action This Week", "5. Backup Trim Scenarios", "6. New Candidate Review",
    "7. Next Review Triggers", "8. Safety Boundary",
]
REQUIRED_FILES = [
    CONTROL_DIR / "phase5r_c6_weekly_email_policy.md", CONTROL_DIR / "phase5r_c6_delivery_policy.md",
    SUBJECT_PATH, TEXT_PATH, HTML_PATH, METADATA_PATH, STATUS_PATH, PREVIEW_EML, PREVIEW_MD,
    COMPOSER, SENDER, Path(__file__), RESEARCH_DIR / "phase5r_c6_weekly_email_report.md", RUN_LOG,
]
STATUS_FIELDS = [
    "timestamp", "mode", "subject", "smtp_username", "recipient_email", "sent", "message_count",
    "error_type", "error_message_redacted", "primary_scenario", "source_subject_path",
    "source_text_path", "source_html_path", "attachments",
]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "mode", "status", "subject",
    "smtp_username", "recipient_email", "sent", "message_count", "input_paths",
    "output_paths", "error_type", "error_message_redacted", "broker_used",
    "scheduler_used", "archived_legacy_used", "safety_notes",
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
SCHEDULER_MODULES = {"schedule", "apscheduler", "croniter"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "add_attachment"}
FORBIDDEN_CONTENT = [r"\bbuy now\b", r"\bsell now\b", r"\bexecute\b", r"\border\b", r"\bguaranteed\b", r"\bcertain profit\b"]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def source_scan() -> tuple[list[str], list[str], list[str], int, list[str], bool]:
    broker: list[str] = []
    scheduler: list[str] = []
    blocked: list[str] = []
    send_calls = 0
    archive_refs: list[str] = []
    config_referenced_only_by_sender = True
    for path in (COMPOSER, SENDER):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        if "11_archive" in source:
            archive_refs.append(path.name)
        if path == COMPOSER and "phase5r_email_config.local.json" in source:
            config_referenced_only_by_sender = False
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            broker.extend(f"{path.name}:{module}" for module in modules if module in BROKER_MODULES)
            scheduler.extend(f"{path.name}:{module}" for module in modules if module in SCHEDULER_MODULES)
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if path == SENDER and name == "send_message":
                    send_calls += 1
                if name in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{name}")
    return broker, scheduler, blocked, send_calls, archive_refs, config_referenced_only_by_sender


def scheduler_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/com.steven.phase5r.dailybrief"],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def c7_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_c7_|-c7\b)|phase5rc7\b", re.IGNORECASE)
    roots = [CONTROL_DIR, POSITION_DIR, RESEARCH_DIR, ROOT / "07_automation", ROOT / "08_reviews", SCRIPTS_DIR]
    return sorted(str(path.relative_to(ROOT)) for folder in roots for path in folder.rglob("*") if path.is_file() and pattern.search(path.name))


def append_log(status: str) -> None:
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c6", "script_name": Path(__file__).name,
            "action": "verify_weekly_email_boundary", "mode": "verify", "status": status,
            "subject": "", "smtp_username": "", "recipient_email": "", "sent": "no",
            "message_count": "0", "input_paths": "phase5r_c6_generated_outputs",
            "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [CONTROL_REPORT, RESEARCH_REPORT]),
            "error_type": "", "error_message_redacted": "", "broker_used": "no",
            "scheduler_used": "no", "archived_legacy_used": "no",
            "safety_notes": "verification_only=yes; config_content_read=no; live_send=no",
        })


def main() -> None:
    subject = SUBJECT_PATH.read_text(encoding="utf-8").strip()
    text_body = TEXT_PATH.read_text(encoding="utf-8")
    html_body = HTML_PATH.read_text(encoding="utf-8")
    metadata_rows = read_csv(METADATA_PATH)
    metadata = metadata_rows[0] if len(metadata_rows) == 1 else {}
    status_rows = read_csv(STATUS_PATH)
    logs = read_csv(RUN_LOG)
    local_positions = read_csv(LOCAL_POSITIONS)
    broker, scheduler, blocked, send_calls, archive_refs, config_sender_only = source_scan()
    dry_rows = [row for row in status_rows if row["mode"] == "dry_run"]
    check_rows = [row for row in status_rows if row["mode"] == "check_config"]
    send_rows = [row for row in status_rows if row["mode"] == "send"]
    smtp_stat = CONFIG_PATH.stat()
    smtp_unchanged = smtp_stat.st_size == SMTP_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_MTIME_BASELINE
    language_hits = [pattern for pattern in FORBIDDEN_CONTENT if re.search(pattern, text_body + "\n" + html_body, re.IGNORECASE)]
    all_scenario_ids = {
        "no_action_until_next_review", "light_trim_review_25pct_of_each_position",
        "trim_to_active_stock_sleeve_target_30pct", "trim_each_position_to_8pct_hard_cap",
        "trim_each_position_to_6pct_default_cap", "whole_share_practical_scenario",
    }
    scenario_ids_in_body = {scenario for scenario in all_scenario_ids if scenario in text_body}
    email_message = BytesParser(policy=policy.default).parsebytes(PREVIEW_EML.read_bytes())
    attachment_count = sum(1 for part in email_message.walk() if part.get_content_disposition() == "attachment")
    archive_log_refs = [row["input_paths"] for row in logs if "11_archive" in row["input_paths"]]
    allowed_canonical_sources = {
        "04_research/realtime_stock_picker_phase5r/phase5r_c5_weekly_conviction_memo.md",
        "04_research/realtime_stock_picker_phase5r/phase5r_c5_weekly_conviction_scores.csv",
        "04_research/realtime_stock_picker_phase5r/phase5r_c5_position_review_recommendations.csv",
        "04_research/realtime_stock_picker_phase5r/phase5r_c5_new_candidate_recommendations.csv",
        "05_risk_and_positions/phase5r_c5t_manual_action_plan.md",
        "05_risk_and_positions/phase5r_c5t_trim_scenario_table.csv",
        "05_risk_and_positions/phase5r_c5t_next_review_triggers.csv",
        "05_risk_and_positions/current_positions.local.csv",
    }
    composer_logs = [row for row in logs if row["script_name"] == COMPOSER.name]
    composer_sources = set(composer_logs[-1]["input_paths"].split(";")) if composer_logs else set()
    secret_output_guard = "ensure_secret_absent" in SENDER.read_text(encoding="utf-8") and all(
        "smtp_app_password" not in path.read_text(encoding="utf-8", errors="replace")
        for path in [STATUS_PATH, RUN_LOG, PREVIEW_EML, SUBJECT_PATH, TEXT_PATH, HTML_PATH]
    )
    checks = [
        ("C6 files were created", all(path.exists() for path in REQUIRED_FILES), f"missing={[str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]}"),
        ("weekly email subject was created", subject.startswith("Weekly AI Equity Conviction Brief \u2014") and "No Action / 2 Trim Reviews / 0 New Eligible" in subject, f"subject={subject}"),
        ("plain-text and HTML bodies were created", bool(text_body.strip()) and bool(html_body.strip()), "both bodies are non-empty"),
        ("primary scenario is no_action_until_next_review", metadata.get("primary_scenario") == PRIMARY_SCENARIO and f"Primary scenario: {PRIMARY_SCENARIO}." in text_body, f"metadata={metadata.get('primary_scenario')}"),
        ("email body states no portfolio action until next review", REQUIRED_MAIN_WORDING in text_body, "required main-decision wording present"),
        ("email body keeps IOT/RBRK as trim_review due to concentration", all(f"{ticker}: current local position" in text_body for ticker in ("IOT", "RBRK")) and text_body.count("trim_review because concentration") == 2, "both current positions checked"),
        ("email body does not include all C5/C5T rows", scenario_ids_in_body == {PRIMARY_SCENARIO} and len(text_body.splitlines()) < 55, f"explicit_scenario_ids={sorted(scenario_ids_in_body)}; lines={len(text_body.splitlines())}"),
        ("email body uses weekly conviction sections", all(section in text_body for section in REQUIRED_SECTIONS), f"sections={len(REQUIRED_SECTIONS)}"),
        ("email content avoids prohibited language", not language_hits, f"violations={language_hits}"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not blocked, f"violations={blocked}"),
        ("no scheduler installed or loaded", not D1_INSTALLED.exists() and not scheduler_loaded(), f"installed={D1_INSTALLED.exists()}"),
        ("no intraday alert logic created", "intraday" not in COMPOSER.read_text(encoding="utf-8").lower() + SENDER.read_text(encoding="utf-8").lower(), "no intraday source logic"),
        ("no daily email scheduler created", not scheduler and "launchd" not in COMPOSER.read_text(encoding="utf-8").lower() + SENDER.read_text(encoding="utf-8").lower(), f"violations={scheduler}"),
        ("no archived legacy files were read", not archive_refs and not archive_log_refs, f"source_refs={archive_refs}; log_refs={archive_log_refs}"),
        ("IOT/RBRK use current local and C5/C5T sources", {row["ticker"] for row in local_positions} == {"IOT", "RBRK"} and composer_sources == allowed_canonical_sources, f"sources_checked={len(composer_sources)}"),
        ("SMTP config was read only by sender and not modified", config_sender_only and smtp_unchanged, "metadata unchanged; verifier did not read config content"),
        ("smtp_app_password is never printed or logged", secret_output_guard, "sender runtime guard present; output field scan passed"),
        ("--dry-run sends no email", bool(dry_rows) and all(row["sent"] == "no" and row["message_count"] == "0" for row in dry_rows), f"dry_run_rows={len(dry_rows)}"),
        ("--check-config sends no email", bool(check_rows) and all(row["sent"] == "no" and row["message_count"] == "0" for row in check_rows), f"check_config_rows={len(check_rows)}"),
        ("default mode sends at most one email", send_calls == 1 and all(row["message_count"] in {"0", "1"} for row in status_rows), f"send_message_calls={send_calls}"),
        ("no live email sent during C6 build", not send_rows and digest(C2_STATUS) == C2_HASH_BASELINE and digest(C3_LOG) == C3_HASH_BASELINE, f"c6_send_rows={len(send_rows)}"),
        ("no attachments", attachment_count == 0 and all(row["attachments"] == "none" for row in status_rows), f"attachment_count={attachment_count}"),
        ("Phase 5R-C7 was not created", not c7_paths(), f"paths={c7_paths()}"),
        ("current local positions remained read-only", digest(LOCAL_POSITIONS) == LOCAL_HASH_BASELINE, "hash unchanged"),
        ("delivery status has required columns", csv_header(STATUS_PATH) == STATUS_FIELDS, "status header checked"),
    ]
    passed = all(ok for _, ok, _ in checks)
    lines = ["# Phase 5R-C6 Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    lines.extend(f"- **{'PASS' if ok else 'FAIL'}** - {label}: {detail}." for label, ok, detail in checks)
    lines.extend(["", "## Test Scope", "", "The composer, config-check mode, and dry-run mode were exercised. Default delivery mode was inspected but not run, so no live weekly email was sent during Phase 5R-C6 construction.", "", "## Weekly Decision", "", f"- Primary scenario: `{PRIMARY_SCENARIO}`.", "- Current reviews: `IOT=trim_review`, `RBRK=trim_review`.", "- New eligible candidates: `0`.", "- Next review date: `2026-07-16`.", "", "## Boundary", "", "C6 remains a weekly, manual-delivery research workflow. It has no broker access, portfolio-change capability, scheduler, time-sensitive alert logic, attachments, archived holding input, or Phase 5R-C7 artifact."])
    report = "\n".join(lines) + "\n"
    CONTROL_REPORT.write_text(report, encoding="utf-8")
    RESEARCH_REPORT.write_text(report, encoding="utf-8")
    append_log("complete" if passed else "failed")
    if not passed:
        raise RuntimeError("Phase 5R-C6 verification failed")
    print("Phase 5R-C6 verification passed; live_send=no")


if __name__ == "__main__":
    main()
