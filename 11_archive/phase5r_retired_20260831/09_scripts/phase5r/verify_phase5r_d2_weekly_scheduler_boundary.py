from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import plistlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
SCHEDULER_DIR = ROOT / "07_automation" / "scheduler"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
LOG_DIR = CONTROL_DIR / "run_logs"

STATE_PATH = CONTROL_DIR / "active_decision_state.yaml"
ALLOWED_PATH = CONTROL_DIR / "phase5r_c8_allowed_active_inputs.csv"
DEPRECATED_PATH = CONTROL_DIR / "phase5r_c8_deprecated_workflows.csv"
C8_VERIFICATION = CONTROL_DIR / "phase5r_c8_verification_report.md"
C7_POLICY = CONTROL_DIR / "phase5r_c7_weekly_pipeline_policy.md"
C7_VERIFICATION = CONTROL_DIR / "phase5r_c7_verification_report.md"
C7_RUNNER = SCRIPTS_DIR / "run_phase5r_c7_weekly_conviction_pipeline.py"

POLICY_PATH = CONTROL_DIR / "phase5r_d2_weekly_scheduler_policy.md"
INSTRUCTIONS_PATH = CONTROL_DIR / "phase5r_d2_install_instructions.md"
DECISION_PATH = CONTROL_DIR / "phase5r_d2_scheduler_decision.md"
CONTROL_REPORT = CONTROL_DIR / "phase5r_d2_verification_report.md"
PLIST_PATH = SCHEDULER_DIR / "com.steven.phase5r.weeklyconviction.plist.template"
INSTALL_PATH = SCHEDULER_DIR / "install_phase5r_d2_weekly_scheduler.sh"
UNINSTALL_PATH = SCHEDULER_DIR / "uninstall_phase5r_d2_weekly_scheduler.sh"
STATUS_PATH = SCHEDULER_DIR / "check_phase5r_d2_scheduler_status.sh"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_d2_scheduler_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_d2_verification_report.md"
RUN_LOG = LOG_DIR / "phase5r_d2_scheduler_setup_log.csv"
STDOUT_LOG = LOG_DIR / "phase5r_d2_launchd_stdout.log"
STDERR_LOG = LOG_DIR / "phase5r_d2_launchd_stderr.log"

LABEL = "com.steven.phase5r.weeklyconviction"
PYTHON_BIN = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
C7_ABSOLUTE = "/Users/messssi/Desktop/equity/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py"
ROOT_ABSOLUTE = "/Users/messssi/Desktop/equity"
STDOUT_ABSOLUTE = "/Users/messssi/Desktop/equity/00_project_control/run_logs/phase5r_d2_launchd_stdout.log"
STDERR_ABSOLUTE = "/Users/messssi/Desktop/equity/00_project_control/run_logs/phase5r_d2_launchd_stderr.log"
INSTALLED_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
D1_LABEL = "com.steven.phase5r.dailybrief"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / f"{D1_LABEL}.plist"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"
C6_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv"
C7_LOG = LOG_DIR / "phase5r_c7_weekly_pipeline_run_log.csv"

C6_STATUS_HASH_BASELINE = "336550f5ff5eac1c01a18d31553ac493cab0144062ed65a50063ac648bc2c5e0"
C7_LOG_HASH_BASELINE = "3310fcafe4fa615c9583e6e1b660d7fa3fe3eb920feae64b9c90119a8095a370"
SMTP_SIZE_BASELINE = 241
SMTP_MTIME_BASELINE = 1783625651
REQUIRED_STATE = {
    "current_workflow": "weekly_conviction",
    "active_pipeline": "phase5r_c7",
    "daily_pipeline_status": "parked",
    "d1_scheduler_status": "parked_uninstalled",
    "email_delivery_allowed_from": "phase5r_c7_only",
    "archived_folders_allowed_as_input": "no",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
}
STATIC_OUTPUTS = [
    POLICY_PATH, INSTRUCTIONS_PATH, DECISION_PATH, PLIST_PATH, INSTALL_PATH,
    UNINSTALL_PATH, STATUS_PATH, Path(__file__), STDOUT_LOG, STDERR_LOG,
]
INPUTS = [
    STATE_PATH, ALLOWED_PATH, DEPRECATED_PATH, C8_VERIFICATION,
    C7_POLICY, C7_VERIFICATION, C7_RUNNER,
]
LOG_FIELDS = [
    "timestamp", "phase", "action", "active_state_read", "active_workflow",
    "active_pipeline", "schedule", "plist_created", "scripts_created",
    "scheduler_installed", "scheduler_loaded", "d1_loaded", "c7_executed",
    "email_sent", "smtp_config_modified", "broker_used", "order_code_created",
    "archive_input_used", "phase5r_e_created", "status", "notes",
]
BROKER_MODULES = {
    "alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab",
    "tda", "webull", "ccxt", "etrade", "tradier",
}
BLOCKED_CALLS = {
    "place_order", "submit_order", "create_order", "send_order", "execute_trade",
}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def job_loaded(label: str) -> bool:
    result = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def scan_python_boundary() -> tuple[list[str], list[str]]:
    broker_imports: list[str] = []
    order_calls: list[str] = []
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [(node.module or "").split(".")[0]]
        broker_imports.extend(module for module in modules if module in BROKER_MODULES)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in BLOCKED_CALLS:
                order_calls.append(name)
    return broker_imports, order_calls


def phase5r_e_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_e_|-e\b)|phase5re\b", re.IGNORECASE)
    roots = [CONTROL_DIR, ROOT / "03_source_data", RESEARCH_DIR, ROOT / "05_risk_and_positions", ROOT / "07_automation", ROOT / "08_reviews", SCRIPTS_DIR]
    return sorted(
        str(path.relative_to(ROOT))
        for folder in roots
        for path in folder.rglob("*")
        if path.is_file() and pattern.search(path.name)
    )


def write_run_log(state: dict[str, object], status: str) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(),
            "phase": "phase5r_d2",
            "action": "prepare_and_verify_weekly_scheduler",
            "active_state_read": "yes",
            "active_workflow": str(state.get("current_workflow", "")),
            "active_pipeline": str(state.get("active_pipeline", "")),
            "schedule": "Thursday 09:05 local",
            "plist_created": "yes",
            "scripts_created": "yes",
            "scheduler_installed": "no",
            "scheduler_loaded": "no",
            "d1_loaded": "no",
            "c7_executed": "no",
            "email_sent": "no",
            "smtp_config_modified": "no",
            "broker_used": "no",
            "order_code_created": "no",
            "archive_input_used": "no",
            "phase5r_e_created": "no",
            "status": status,
            "notes": "preparation_only=yes; run_at_load=no; keep_alive=no; start_interval=no",
        })


def main() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    allowed = read_csv(ALLOWED_PATH)
    deprecated = {row["workflow_id"]: row for row in read_csv(DEPRECATED_PATH)}
    plist_bytes = PLIST_PATH.read_bytes()
    plist = plistlib.loads(plist_bytes)
    install_source = INSTALL_PATH.read_text(encoding="utf-8")
    uninstall_source = UNINSTALL_PATH.read_text(encoding="utf-8")
    status_source = STATUS_PATH.read_text(encoding="utf-8")
    executable_sources = "\n".join([plist_bytes.decode("utf-8"), install_source, uninstall_source, status_source])

    state_ok = isinstance(state, dict) and all(state.get(key) == value for key, value in REQUIRED_STATE.items())
    deprecated_ok = (
        deprecated.get("DW-001", {}).get("status") == "deprecated"
        and deprecated.get("DW-002", {}).get("status") == "deprecated"
        and deprecated.get("DW-003", {}).get("status") == "parked_uninstalled"
    )
    interval = plist.get("StartCalendarInterval")
    weekly_only = isinstance(interval, dict) and interval == {"Weekday": 5, "Hour": 9, "Minute": 5}
    program_arguments = plist.get("ProgramArguments")
    c7_only = program_arguments == [PYTHON_BIN, C7_ABSOLUTE]
    old_refs = [marker for marker in ("phase5r_c2", "phase5r_c3", "dailybrief", "phase5r_d1") if marker in plist_bytes.decode("utf-8").lower()]
    archive_refs = [marker for marker in ("11_archive", "legacy_pre_5r") if marker in executable_sources.lower()]
    forbidden_installer_actions = [marker for marker in (" kickstart ", " launchctl start ", " launchctl load ") if marker in install_source.lower()]
    broker_imports, order_calls = scan_python_boundary()
    successful_sends = sum(row.get("mode") == "send" and row.get("sent") == "yes" for row in read_csv(C6_STATUS))
    smtp_stat = SMTP_CONFIG.stat()
    smtp_unchanged = smtp_stat.st_size == SMTP_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_MTIME_BASELINE
    installed = INSTALLED_PLIST.exists()
    loaded = job_loaded(LABEL)
    d1_installed = D1_INSTALLED.exists()
    d1_loaded = job_loaded(D1_LABEL)
    secret_markers = []
    for path in [POLICY_PATH, INSTRUCTIONS_PATH, DECISION_PATH, STDOUT_LOG, STDERR_LOG, INSTALL_PATH, UNINSTALL_PATH, STATUS_PATH, PLIST_PATH]:
        text = path.read_text(encoding="utf-8").lower()
        if "smtp_app_password" in text or "phase5r_email_config.local.json" in text:
            secret_markers.append(str(path.relative_to(ROOT)))
    phase_e = phase5r_e_paths()

    checks = [
        ("active_decision_state.yaml was read", state_ok, f"workflow={state.get('current_workflow')}; pipeline={state.get('active_pipeline')}"),
        ("active workflow is weekly_conviction", state.get("current_workflow") == "weekly_conviction", "source=active_decision_state.yaml"),
        ("C7 is marked as the active pipeline", state.get("active_pipeline") == "phase5r_c7", "active_pipeline=phase5r_c7"),
        ("C2/C3/D1 remain deprecated or parked", deprecated_ok and not d1_installed and not d1_loaded, f"D1 installed={d1_installed}; loaded={d1_loaded}"),
        ("plist template was created", PLIST_PATH.exists() and plist.get("Label") == LABEL, f"label={plist.get('Label')}"),
        ("install script was created", INSTALL_PATH.exists() and os.access(INSTALL_PATH, os.X_OK) and "launchctl bootstrap" in install_source, "manual bootstrap only"),
        ("uninstall script was created", UNINSTALL_PATH.exists() and os.access(UNINSTALL_PATH, os.X_OK) and "launchctl bootout" in uninstall_source, "preserves project artifacts"),
        ("status script was created", STATUS_PATH.exists() and os.access(STATUS_PATH, os.X_OK) and "launchctl print" in status_source, "read-only status check"),
        ("scheduler points only to C7 weekly pipeline", c7_only and plist.get("WorkingDirectory") == ROOT_ABSOLUTE, f"ProgramArguments={program_arguments}"),
        ("scheduler excludes C2/C3/D1 references", not old_refs, f"old_refs={old_refs}"),
        ("scheduler has weekly timing only", weekly_only, f"StartCalendarInterval={interval}"),
        ("scheduler has no StartInterval", "StartInterval" not in plist, "StartInterval absent"),
        ("scheduler has RunAtLoad=false", plist.get("RunAtLoad") is False, f"RunAtLoad={plist.get('RunAtLoad')}"),
        ("scheduler has KeepAlive=false", plist.get("KeepAlive") is False, f"KeepAlive={plist.get('KeepAlive')}"),
        ("scheduler log paths are absolute", plist.get("StandardOutPath") == STDOUT_ABSOLUTE and plist.get("StandardErrorPath") == STDERR_ABSOLUTE, "stdout/stderr paths match policy"),
        ("scheduler was not installed", not installed, f"installed={installed}"),
        ("scheduler was not loaded", not loaded, f"loaded={loaded}"),
        ("C7 pipeline was not executed", digest(C7_LOG) == C7_LOG_HASH_BASELINE, "C7 run log hash unchanged"),
        ("no email was sent", digest(C6_STATUS) == C6_STATUS_HASH_BASELINE and successful_sends == 2, f"successful_send_rows={successful_sends}"),
        ("no broker libraries imported", not broker_imports, f"broker_imports={broker_imports}"),
        ("no order code created", not order_calls, f"order_calls={order_calls}"),
        ("no archived legacy input used", not archive_refs and bool(allowed), f"archive_refs={archive_refs}"),
        ("SMTP config was not modified", smtp_unchanged, "metadata unchanged; config content not read"),
        ("no SMTP secret value appears in artifacts", not secret_markers, f"secret_markers={secret_markers}"),
        ("installer has no immediate-run action", not forbidden_installer_actions, f"forbidden_actions={forbidden_installer_actions}"),
        ("Phase 5R-E was not created", not phase_e, f"paths={phase_e}"),
        ("all static D2 outputs exist", all(path.exists() for path in STATIC_OUTPUTS), f"missing={[str(path.relative_to(ROOT)) for path in STATIC_OUTPUTS if not path.exists()]}"),
        ("all declared D2 inputs exist", all(path.exists() for path in INPUTS), f"missing={[str(path.relative_to(ROOT)) for path in INPUTS if not path.exists()]}"),
    ]
    passed = all(ok for _, ok, _ in checks)
    generated = timestamp()
    verification_lines = [
        "# Phase 5R-D2 Verification Report", "", f"Generated: `{generated}`", "",
        "## Required Checks", "",
    ]
    verification_lines.extend(f"- **{'PASS' if ok else 'FAIL'}** - {label}: {detail}." for label, ok, detail in checks)
    verification_lines.extend([
        "", "## Schedule", "",
        "- Label: `com.steven.phase5r.weeklyconviction`.",
        "- Schedule: Thursday at 09:05 local time.",
        "- Pipeline: `phase5r_c7` only.",
        "- Installation status: not installed.",
        "- Load status: not loaded.",
        "", "## Boundary", "",
        "D2 prepared scheduler artifacts only. It did not run C7, send email, install or load launchd, access a broker, create transaction code, read archived inputs, modify SMTP configuration, expose an SMTP secret value, or create Phase 5R-E.",
    ])
    verification_text = "\n".join(verification_lines) + "\n"
    CONTROL_REPORT.write_text(verification_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(verification_text, encoding="utf-8")

    report_lines = [
        "# Phase 5R-D2 Scheduler Report", "", f"Generated: `{generated}`", "",
        "## Decision", "",
        "The active state contains no schedule override. D2 therefore prepared one Thursday 09:05 local launchd calendar event for the active C7 weekly conviction pipeline.",
        "", "## Prepared Artifacts", "",
        "- One launchd plist template.",
        "- Manual install and uninstall scripts.",
        "- Read-only scheduler status script.",
        "- Dedicated stdout, stderr, and setup log paths.",
        "", "## State", "",
        "- Active workflow: `weekly_conviction`.",
        "- Active pipeline: `phase5r_c7`.",
        "- D1 remains parked and uninstalled.",
        "- C2 and C3 remain deprecated.",
        "- D2 scheduler installed: `no`.",
        "- D2 scheduler loaded: `no`.",
        "- Email sent during D2: `no`.",
        "", "## Safety", "",
        "The template has no daily, intraday, interval, broker, order, archived-input, or immediate-run capability.",
    ]
    RESEARCH_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    write_run_log(state, "complete" if passed else "failed")
    if not passed:
        raise RuntimeError("Phase 5R-D2 weekly scheduler verification failed")
    print("Phase 5R-D2 verification passed; scheduler_installed=no; scheduler_loaded=no; email_sent=no")


if __name__ == "__main__":
    main()

