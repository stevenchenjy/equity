from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
AUTOMATION_DIR = ROOT / "07_automation"

STATE_PATH = CONTROL_DIR / "active_decision_state.yaml"
ALLOWED_PATH = CONTROL_DIR / "phase5r_c8_allowed_active_inputs.csv"
DEPRECATED_PATH = CONTROL_DIR / "phase5r_c8_deprecated_workflows.csv"
STALE_REPORT = CONTROL_DIR / "phase5r_c8_stale_file_guard_report.csv"
POLICY_PATH = CONTROL_DIR / "phase5r_c8_active_state_policy.md"
CONTROL_REPORT = CONTROL_DIR / "phase5r_c8_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c8_active_state_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_c8_verification_report.md"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c8_run_log.csv"
C7_RUNNER = SCRIPTS_DIR / "run_phase5r_c7_weekly_conviction_pipeline.py"
LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
C6_STATUS = AUTOMATION_DIR / "email_delivery" / "phase5r_c6_delivery_status.csv"
SMTP_CONFIG = AUTOMATION_DIR / "email_delivery" / "phase5r_email_config.local.json"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.steven.phase5r.dailybrief.plist"

C6_STATUS_HASH_BASELINE = "336550f5ff5eac1c01a18d31553ac493cab0144062ed65a50063ac648bc2c5e0"
LOCAL_HASH_BASELINE = "d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c"
SMTP_SIZE_BASELINE = 241
SMTP_MTIME_BASELINE = 1783625651
REQUIRED_STATE = {
    "current_workflow": "weekly_conviction",
    "active_pipeline": "phase5r_c7",
    "primary_decision": "no_action_until_next_review",
    "next_review_date": "2026-07-16",
    "daily_pipeline_status": "parked",
    "d1_scheduler_status": "parked_uninstalled",
    "email_delivery_allowed_from": "phase5r_c7_only",
    "current_positions_source": "05_risk_and_positions/current_positions.local.csv",
    "archived_folders_allowed_as_input": "no",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
}
REQUIRED_FILES = [
    POLICY_PATH, STATE_PATH, ALLOWED_PATH, DEPRECATED_PATH, STALE_REPORT,
    C7_RUNNER, Path(__file__),
]
LOG_FIELDS = [
    "timestamp", "phase", "action", "input_paths", "output_paths", "status",
    "active_pipeline", "primary_decision", "allowed_input_rows", "deprecated_workflow_rows",
    "guard_check_rows", "email_sent", "scheduler_used", "broker_used",
    "smtp_config_modified", "archive_contents_read", "phase5r_d2_created", "safety_notes",
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
EMAIL_MODULES = {"smtplib", "imaplib", "poplib", "gmail", "sendgrid"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "send_message", "sendmail"}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_state() -> dict[str, str]:
    with STATE_PATH.open(encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise RuntimeError("active state must be an object")
    return {str(key): str(value) for key, value in state.items()}


def scheduler_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/com.steven.phase5r.dailybrief"],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def gitignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path.relative_to(ROOT))],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def script_scan() -> tuple[list[str], list[str], list[str]]:
    broker: list[str] = []
    email: list[str] = []
    blocked: list[str] = []
    for path in (C7_RUNNER, Path(__file__)):
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
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{name}")
    return broker, email, blocked


def d2_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_d2_|-d2\b)|phase5rd2\b", re.IGNORECASE)
    roots = [CONTROL_DIR, POSITION_DIR, ROOT / "03_source_data", RESEARCH_DIR, AUTOMATION_DIR, ROOT / "08_reviews", SCRIPTS_DIR]
    return sorted(str(path.relative_to(ROOT)) for folder in roots for path in folder.rglob("*") if path.is_file() and pattern.search(path.name))


def append_log(state: dict[str, str], allowed_count: int, deprecated_count: int, guard_count: int, status: str) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c8", "action": "verify_active_state_guard",
            "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [STATE_PATH, ALLOWED_PATH, DEPRECATED_PATH, STALE_REPORT, C7_RUNNER]),
            "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [CONTROL_REPORT, RESEARCH_REPORT, RESEARCH_VERIFICATION, RUN_LOG]),
            "status": status, "active_pipeline": state.get("active_pipeline", ""),
            "primary_decision": state.get("primary_decision", ""),
            "allowed_input_rows": str(allowed_count), "deprecated_workflow_rows": str(deprecated_count),
            "guard_check_rows": str(guard_count), "email_sent": "no", "scheduler_used": "no",
            "broker_used": "no", "smtp_config_modified": "no", "archive_contents_read": "no",
            "phase5r_d2_created": "no", "safety_notes": "registry_only=yes; active_state_read_first=yes; files_moved=no; files_deleted=no",
        })


def main() -> None:
    state = load_state()
    allowed = read_csv(ALLOWED_PATH)
    deprecated = read_csv(DEPRECATED_PATH)
    guards = read_csv(STALE_REPORT)
    broker_imports, email_imports, blocked_calls = script_scan()

    state_ok = all(state.get(key) == value for key, value in REQUIRED_STATE.items())
    archive_allowed_rows = [row for row in allowed if "11_archive" in row["path_spec"] or row["allowed_as_active_input"] != "yes"]
    exact_missing = [
        row["path_spec"] for row in allowed
        if row["path_kind"] == "exact" and not (ROOT / row["path_spec"]).exists()
    ]
    pattern_missing = [
        row["path_spec"] for row in allowed
        if row["path_kind"] == "pattern" and not list(ROOT.glob(row["path_spec"]))
    ]
    workflow_by_id = {row["workflow_id"]: row for row in deprecated}
    deprecated_ok = (
        workflow_by_id.get("DW-001", {}).get("status") == "deprecated"
        and workflow_by_id.get("DW-002", {}).get("status") == "deprecated"
        and workflow_by_id.get("DW-003", {}).get("status") == "parked_uninstalled"
        and workflow_by_id.get("DW-004", {}).get("status") == "archived_evidence_only"
        and workflow_by_id.get("DW-005", {}).get("status") == "parked_evidence"
        and workflow_by_id.get("DW-007", {}).get("email_send_allowed") == "via_phase5r_c7_only"
    )
    runner_source = C7_RUNNER.read_text(encoding="utf-8")
    guard_call = runner_source.find("validate_active_state()", runner_source.find("def main"))
    first_active_read = runner_source.find("live_before = live_send_row_count()", runner_source.find("def main"))
    runner_guarded = "ACTIVE_STATE" in runner_source and guard_call != -1 and first_active_read != -1 and guard_call < first_active_read
    c6_rows = read_csv(C6_STATUS)
    successful_sends = sum(row.get("mode") == "send" and row.get("sent") == "yes" for row in c6_rows)
    smtp_stat = SMTP_CONFIG.stat()
    smtp_unchanged = smtp_stat.st_size == SMTP_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_MTIME_BASELINE
    guards_ok = all(row["active_input_allowed"] in {"yes", "no"} for row in guards) and any(row["guard_decision"] == "exclude_all" for row in guards)
    broker_order_safe = not broker_imports and not blocked_calls
    checks = [
        ("active_decision_state.yaml exists", STATE_PATH.exists() and state_ok, f"active_pipeline={state.get('active_pipeline')}"),
        ("allowed active inputs registry exists", ALLOWED_PATH.exists() and bool(allowed), f"rows={len(allowed)}"),
        ("deprecated workflow registry exists", DEPRECATED_PATH.exists() and bool(deprecated), f"rows={len(deprecated)}"),
        ("archived folders are excluded from active inputs", not archive_allowed_rows and guards_ok, f"archive_allowed_rows={len(archive_allowed_rows)}"),
        ("all allowed active input paths resolve", not exact_missing and not pattern_missing, f"exact_missing={exact_missing}; pattern_missing={pattern_missing}"),
        ("C7 is marked active", state.get("active_pipeline") == "phase5r_c7" and state.get("email_delivery_allowed_from") == "phase5r_c7_only", "weekly C7 only"),
        ("C7 reads active state before active inputs", runner_guarded, f"guard_index={guard_call}; first_input_index={first_active_read}"),
        ("C2/C3/D1 are deprecated or parked", deprecated_ok, "C2=deprecated; C3=deprecated; D1=parked_uninstalled"),
        ("current_positions.local.csv is gitignored", gitignored(LOCAL_POSITIONS) and state.get("current_positions_source") == str(LOCAL_POSITIONS.relative_to(ROOT)), "only current holding source"),
        ("no scheduler installed or loaded", not D1_INSTALLED.exists() and not scheduler_loaded(), f"installed={D1_INSTALLED.exists()}"),
        ("no email sent", digest(C6_STATUS) == C6_STATUS_HASH_BASELINE and successful_sends == 2 and not email_imports, f"successful_send_rows={successful_sends}"),
        ("no broker/order code created", broker_order_safe, f"broker={broker_imports}; blocked_calls={blocked_calls}"),
        ("SMTP config not modified", smtp_unchanged, "metadata unchanged; config content not read"),
        ("current local positions remained read-only", digest(LOCAL_POSITIONS) == LOCAL_HASH_BASELINE, "hash unchanged"),
        ("Phase 5R-D2 was not created", not d2_paths(), f"paths={d2_paths()}"),
        ("all required C8 files exist", all(path.exists() for path in REQUIRED_FILES), f"missing={[str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]}"),
    ]
    passed = all(ok for _, ok, _ in checks)
    generated = timestamp()
    verification_lines = ["# Phase 5R-C8 Verification Report", "", f"Generated: `{generated}`", "", "## Required Checks", ""]
    verification_lines.extend(f"- **{'PASS' if ok else 'FAIL'}** - {label}: {detail}." for label, ok, detail in checks)
    verification_lines.extend(["", "## Active State", "", f"- Workflow: `{state.get('current_workflow')}`.", f"- Active pipeline: `{state.get('active_pipeline')}`.", f"- Primary decision: `{state.get('primary_decision')}`.", f"- Next review: `{state.get('next_review_date')}`.", f"- Allowed input rows: `{len(allowed)}`.", f"- Deprecated or parked workflow rows: `{len(deprecated)}`.", "", "## Boundary", "", "C8 created registries and verification artifacts only. It sent no email, activated no scheduler, accessed no broker, created no transaction code, modified no SMTP configuration, read no archive contents, moved no files, deleted no files, and created no Phase 5R-D2 artifact."])
    verification_text = "\n".join(verification_lines) + "\n"
    CONTROL_REPORT.write_text(verification_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(verification_text, encoding="utf-8")

    report_lines = [
        "# Phase 5R-C8 Active State Report", "", f"Generated: `{generated}`", "",
        "## Authoritative State", "", f"- Current workflow: `{state.get('current_workflow')}`.",
        f"- Active pipeline: `{state.get('active_pipeline')}`.",
        f"- Primary decision: `{state.get('primary_decision')}`.",
        f"- Next review date: `{state.get('next_review_date')}`.",
        f"- Current position source: `{state.get('current_positions_source')}`.",
        f"- Email delivery boundary: `{state.get('email_delivery_allowed_from')}`.", "",
        "## Registry Summary", "", f"- Allowed active input rows: `{len(allowed)}`.",
        f"- Deprecated or parked workflow rows: `{len(deprecated)}`.",
        f"- Stale-file guard checks: `{len(guards)}`.",
        "- Archived folders are excluded without reading their contents.",
        "- Historical daily files remain evidence only.", "",
        "## Enforcement", "", "C7 now validates the active state before reading other weekly inputs. A missing or conflicting state blocks pipeline execution.", "",
        "## Boundary", "", "The registry does not authorize scheduling, broker access, automatic portfolio action, standalone historical email workflows, archived inputs, or Phase 5R-D2.",
    ]
    RESEARCH_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    append_log(state, len(allowed), len(deprecated), len(guards), "complete" if passed else "failed")
    if not passed:
        raise RuntimeError("Phase 5R-C8 active-state verification failed")
    print(f"Phase 5R-C8 verification passed; active_pipeline={state.get('active_pipeline')}; email_sent=no")


if __name__ == "__main__":
    main()
