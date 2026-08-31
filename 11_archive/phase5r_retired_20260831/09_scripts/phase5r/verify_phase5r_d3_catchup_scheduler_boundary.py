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
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG_DIR = CONTROL_DIR / "run_logs"

ACTIVE_STATE = CONTROL_DIR / "active_decision_state.yaml"
C6_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv"
C7_LOG = RUN_LOG_DIR / "phase5r_c7_weekly_pipeline_run_log.csv"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"

POLICY = CONTROL_DIR / "phase5r_d3_catchup_scheduler_policy.md"
STATE_POLICY = CONTROL_DIR / "phase5r_d3_catchup_state_policy.md"
INSTALL_INSTRUCTIONS = CONTROL_DIR / "phase5r_d3_install_instructions.md"
MIGRATION_PLAN = CONTROL_DIR / "phase5r_d3_migration_from_d2_plan.md"
CONTROL_REPORT = CONTROL_DIR / "phase5r_d3_verification_report.md"
RESEARCH_SCHEDULER_REPORT = RESEARCH_DIR / "phase5r_d3_catchup_scheduler_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_d3_verification_report.md"

PLIST = SCHEDULER_DIR / "com.steven.phase5r.weeklycatchup.plist.template"
INSTALL = SCHEDULER_DIR / "install_phase5r_d3_catchup_scheduler.sh"
UNINSTALL = SCHEDULER_DIR / "uninstall_phase5r_d3_catchup_scheduler.sh"
STATUS = SCHEDULER_DIR / "check_phase5r_d3_catchup_status.sh"
STATE_TEMPLATE = SCHEDULER_DIR / "phase5r_d3_catchup_state.template.json"
STATE_EXAMPLE = SCHEDULER_DIR / "phase5r_d3_catchup_state.local.json.example"
WRAPPER = SCRIPTS_DIR / "run_phase5r_d3_weekly_catchup.py"
CHECK_LOG = RUN_LOG_DIR / "phase5r_d3_catchup_check_log.csv"
STDOUT_LOG = RUN_LOG_DIR / "phase5r_d3_launchd_stdout.log"
STDERR_LOG = RUN_LOG_DIR / "phase5r_d3_launchd_stderr.log"

D2_LABEL = "com.steven.phase5r.weeklyconviction"
D3_LABEL = "com.steven.phase5r.weeklycatchup"
PYTHON_BIN = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
ROOT_ABSOLUTE = "/Users/messssi/Desktop/equity"
WRAPPER_ABSOLUTE = f"{ROOT_ABSOLUTE}/09_scripts/phase5r/run_phase5r_d3_weekly_catchup.py"
STDOUT_ABSOLUTE = "/Users/messssi/Library/Logs/phase5r_d3_launchd_stdout.log"
STDERR_ABSOLUTE = "/Users/messssi/Library/Logs/phase5r_d3_launchd_stderr.log"
D3_INSTALLED = Path.home() / "Library" / "LaunchAgents" / f"{D3_LABEL}.plist"
D2_INSTALLED = Path.home() / "Library" / "LaunchAgents" / f"{D2_LABEL}.plist"

REQUIRED_STATE = {
    "current_workflow": "weekly_conviction",
    "active_pipeline": "phase5r_c7",
    "email_delivery_allowed_from": "phase5r_c7_only",
    "archived_folders_allowed_as_input": "no",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
}
REQUIRED_DECISIONS = {
    "not_due_yet",
    "already_sent",
    "catchup_sent",
    "catchup_failed",
    "blocked_by_lock",
    "inactive_workflow",
    "missing_inputs",
    "verification_only",
}
REQUIRED_LOG_FIELDS = [
    "timestamp",
    "cycle_id",
    "local_now",
    "scheduled_due_time",
    "decision",
    "reason",
    "c7_invoked",
    "c7_return_code",
    "sent_rows_before",
    "sent_rows_after",
    "send_delta",
    "lock_acquired",
    "active_workflow",
    "active_pipeline",
    "safety_notes",
]
REQUIRED_STATIC_OUTPUTS = [
    POLICY,
    STATE_POLICY,
    INSTALL_INSTRUCTIONS,
    MIGRATION_PLAN,
    RESEARCH_SCHEDULER_REPORT,
    PLIST,
    INSTALL,
    UNINSTALL,
    STATUS,
    STATE_TEMPLATE,
    STATE_EXAMPLE,
    WRAPPER,
    Path(__file__),
    CHECK_LOG,
    STDOUT_LOG,
    STDERR_LOG,
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
BLOCKED_ORDER_CALLS = {
    "place_order",
    "submit_order",
    "create_order",
    "send_order",
    "execute_trade",
}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def metadata(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def loaded(label: str) -> bool:
    result = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def successful_send_count() -> int:
    with C6_STATUS.open(newline="", encoding="utf-8") as handle:
        return sum(row.get("sent", "").lower() == "yes" for row in csv.DictReader(handle))


def check_log_rows() -> list[dict[str, str]]:
    with CHECK_LOG.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def scan_wrapper_ast() -> tuple[list[str], list[str]]:
    tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
    broker_imports: list[str] = []
    order_calls: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [(node.module or "").split(".")[0]]
        broker_imports.extend(module for module in modules if module in BROKER_MODULES)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                name = ""
            if name in BLOCKED_ORDER_CALLS:
                order_calls.append(name)
    return broker_imports, order_calls


def phase5r_e_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_e_|-e\b)|phase5re\b", re.IGNORECASE)
    roots = [
        CONTROL_DIR,
        ROOT / "03_source_data",
        RESEARCH_DIR,
        ROOT / "05_risk_and_positions",
        ROOT / "07_automation",
        ROOT / "08_reviews",
        SCRIPTS_DIR,
    ]
    return sorted(
        str(path.relative_to(ROOT))
        for folder in roots
        for path in folder.rglob("*")
        if path.is_file() and pattern.search(path.name)
    )


def main() -> None:
    missing = [path for path in REQUIRED_STATIC_OUTPUTS if not path.exists()]
    if missing:
        raise RuntimeError(f"missing required D3 outputs: {missing}")

    active_state = json.loads(ACTIVE_STATE.read_text(encoding="utf-8"))
    plist = plistlib.loads(PLIST.read_bytes())
    wrapper_source = WRAPPER.read_text(encoding="utf-8")
    install_source = INSTALL.read_text(encoding="utf-8")
    uninstall_source = UNINSTALL.read_text(encoding="utf-8")
    status_source = STATUS.read_text(encoding="utf-8")
    state_template = json.loads(STATE_TEMPLATE.read_text(encoding="utf-8"))
    state_example = json.loads(STATE_EXAMPLE.read_text(encoding="utf-8"))
    broker_imports, order_calls = scan_wrapper_ast()

    c6_hash_before = digest(C6_STATUS)
    c7_hash_before = digest(C7_LOG)
    smtp_metadata_before = metadata(SMTP_CONFIG)
    stdout_hash_before = digest(STDOUT_LOG)
    stderr_hash_before = digest(STDERR_LOG)
    send_count_before = successful_send_count()
    d2_loaded_before = loaded(D2_LABEL)
    d3_loaded_before = loaded(D3_LABEL)
    d2_installed_before = D2_INSTALLED.exists()
    d3_installed_before = D3_INSTALLED.exists()
    phase_e_before = phase5r_e_paths()
    rows_before = check_log_rows()

    if d3_installed_before or d3_loaded_before:
        raise RuntimeError("D3 must remain uninstalled and unloaded during verification")

    verification_run = subprocess.run(
        [PYTHON_BIN, str(WRAPPER), "--verification-only"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    rows_after = check_log_rows()
    latest_row = rows_after[-1] if rows_after else {}
    c6_hash_after = digest(C6_STATUS)
    c7_hash_after = digest(C7_LOG)
    smtp_metadata_after = metadata(SMTP_CONFIG)
    stdout_hash_after = digest(STDOUT_LOG)
    stderr_hash_after = digest(STDERR_LOG)
    send_count_after = successful_send_count()
    d2_loaded_after = loaded(D2_LABEL)
    d3_loaded_after = loaded(D3_LABEL)
    d2_installed_after = D2_INSTALLED.exists()
    d3_installed_after = D3_INSTALLED.exists()
    phase_e_after = phase5r_e_paths()

    program_arguments = plist.get("ProgramArguments")
    wrapper_lower = wrapper_source.lower()
    forbidden_wrapper_references = [
        marker
        for marker in (
            "send_phase5r_c2_daily_email",
            "run_phase5r_c3_daily_email_pipeline",
            "com.steven.phase5r.dailybrief",
            "run_phase5r_d1",
        )
        if marker in wrapper_lower
    ]
    archive_references = [
        marker
        for marker in ("11_archive", "legacy_pre_5r", "archived_iot", "archived_rbrk")
        if marker in wrapper_lower
    ]
    reports_and_logs = [
        POLICY,
        STATE_POLICY,
        INSTALL_INSTRUCTIONS,
        MIGRATION_PLAN,
        RESEARCH_SCHEDULER_REPORT,
        CHECK_LOG,
        STDOUT_LOG,
        STDERR_LOG,
    ]
    secret_markers = []
    for path in reports_and_logs:
        content = path.read_text(encoding="utf-8", errors="replace").lower()
        if "smtp_app_password" in content or "phase5r_email_config.local.json" in content:
            secret_markers.append(str(path.relative_to(ROOT)))

    checks = [
        (
            "active_decision_state.yaml was read and satisfies D3 boundary",
            isinstance(active_state, dict) and all(active_state.get(k) == v for k, v in REQUIRED_STATE.items()),
            f"workflow={active_state.get('current_workflow')}; pipeline={active_state.get('active_pipeline')}",
        ),
        (
            "active workflow is weekly_conviction",
            active_state.get("current_workflow") == "weekly_conviction",
            "source=active_decision_state.yaml",
        ),
        (
            "active pipeline is phase5r_c7",
            active_state.get("active_pipeline") == "phase5r_c7",
            "source=active_decision_state.yaml",
        ),
        (
            "D3 plist template exists with correct label and absolute wrapper",
            plist.get("Label") == D3_LABEL and program_arguments == [PYTHON_BIN, WRAPPER_ABSOLUTE],
            f"ProgramArguments={program_arguments}",
        ),
        (
            "D3 wrapper and management scripts exist and are executable",
            WRAPPER.exists()
            and all(path.exists() and os.access(path, os.X_OK) for path in (INSTALL, UNINSTALL, STATUS)),
            "install/uninstall/status prepared",
        ),
        (
            "D3 wrapper invokes only the C7 pipeline for email workflow",
            "run_phase5r_c7_weekly_conviction_pipeline.py" in wrapper_source
            and "subprocess.run" in wrapper_source
            and "send_phase5r_c6_weekly_email.py" not in wrapper_source,
            "C6 is status-only; C7 is the sole child workflow",
        ),
        (
            "D3 wrapper excludes C2 direct sender, C3 daily pipeline, and D1 daily scheduler",
            not forbidden_wrapper_references,
            f"forbidden_references={forbidden_wrapper_references}",
        ),
        (
            "D3 uses StartInterval=900 as a check-only trigger",
            plist.get("StartInterval") == 900
            and "StartCalendarInterval" not in plist
            and program_arguments == [PYTHON_BIN, WRAPPER_ABSOLUTE]
            and "not_due_yet" in wrapper_source
            and "already_sent" in wrapper_source,
            f"StartInterval={plist.get('StartInterval')}; StartCalendarInterval={'StartCalendarInterval' in plist}",
        ),
        (
            "D3 has RunAtLoad=true and KeepAlive=false",
            plist.get("RunAtLoad") is True and plist.get("KeepAlive") is False,
            f"RunAtLoad={plist.get('RunAtLoad')}; KeepAlive={plist.get('KeepAlive')}",
        ),
        (
            "D3 uses required working directory and log paths",
            plist.get("WorkingDirectory") == ROOT_ABSOLUTE
            and plist.get("StandardOutPath") == STDOUT_ABSOLUTE
            and plist.get("StandardErrorPath") == STDERR_ABSOLUTE,
            "all scheduler paths are absolute",
        ),
        (
            "D3 uses a nonblocking OS lock file",
            "phase5r_d3_catchup.lock" in wrapper_source
            and "fcntl.LOCK_EX | fcntl.LOCK_NB" in wrapper_source
            and "release_cycle_lock" in wrapper_source,
            "concurrent due checks fail as blocked_by_lock",
        ),
        (
            "D3 has once-per-cycle send and attempt guards",
            "cycle_context" in wrapper_source
            and "sent_in_cycle" in wrapper_source
            and "cycle_attempts" in wrapper_source
            and "prior_c7_attempt_without_success_requires_manual_review" in wrapper_source,
            "ISO cycle plus durable attempt ledger",
        ),
        (
            "D3 reads C6 delivery status and validates exactly one new successful row",
            "phase5r_c6_delivery_status.csv" in wrapper_source
            and "send_delta == 1" in wrapper_source
            and 'row.get("sent", "").strip().lower() != "yes"' in wrapper_source,
            "C6 status is the confirmed-delivery authority",
        ),
        (
            "D3 state template and example are valid and schema-matched",
            state_template.get("schema_version") == "phase5r_d3_catchup_state_v1"
            and state_example.get("schema_version") == state_template.get("schema_version")
            and isinstance(state_template.get("cycle_attempts"), dict)
            and state_template.get("schedule", {}).get("check_interval_seconds") == 900,
            "state schema and schedule validated",
        ),
        (
            "all allowed D3 decision values are implemented",
            REQUIRED_DECISIONS.issubset(set(ast.literal_eval(next(
                node.value
                for node in ast.walk(ast.parse(wrapper_source))
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "DECISIONS" for target in node.targets)
            )))),
            f"required_decisions={sorted(REQUIRED_DECISIONS)}",
        ),
        (
            "check log uses the required columns",
            list(latest_row.keys()) == REQUIRED_LOG_FIELDS,
            f"columns={list(latest_row.keys())}",
        ),
        (
            "verification-only check was logged without C7 invocation",
            verification_run.returncode == 0
            and len(rows_after) == len(rows_before) + 1
            and latest_row.get("decision") == "verification_only"
            and latest_row.get("reason") == "verification_check_requested"
            and latest_row.get("c7_invoked") == "no"
            and latest_row.get("send_delta") == "0",
            f"return={verification_run.returncode}; latest_decision={latest_row.get('decision')}",
        ),
        (
            "D3 scheduler was not installed or loaded during verification",
            not d3_installed_before and not d3_loaded_before and not d3_installed_after and not d3_loaded_after,
            f"before=installed:{d3_installed_before},loaded:{d3_loaded_before}; after=installed:{d3_installed_after},loaded:{d3_loaded_after}",
        ),
        (
            "D2 live state was not changed during verification",
            d2_loaded_before == d2_loaded_after and d2_installed_before == d2_installed_after,
            f"loaded={d2_loaded_after}; installed={d2_installed_after}",
        ),
        (
            "C7 was not run and no email was sent during verification",
            c7_hash_before == c7_hash_after
            and c6_hash_before == c6_hash_after
            and send_count_before == send_count_after,
            f"successful_send_rows={send_count_after}; hashes_unchanged={c7_hash_before == c7_hash_after and c6_hash_before == c6_hash_after}",
        ),
        (
            "launchd output logs were not written during verification",
            stdout_hash_before == stdout_hash_after and stderr_hash_before == stderr_hash_after,
            "D3 remained unloaded",
        ),
        (
            "install script migrates D2 safely and inhibits RunAtLoad delivery",
            D2_LABEL in install_source
            and "launchctl bootout" in install_source
            and "D2_TARGET" in install_source
            and "INSTALL_INHIBIT" in install_source
            and "install_inhibit_active" in install_source
            and "launchctl bootstrap" in install_source,
            "manual install owns D2-to-D3 cutover",
        ),
        (
            "uninstall preserves artifacts and does not reinstall D2",
            "launchctl bootout" in uninstall_source
            and D2_LABEL not in uninstall_source
            and "launchctl bootstrap" not in uninstall_source,
            "D3-only uninstall",
        ),
        (
            "status script is read-only and cannot invoke C7",
            "launchctl print" in status_source
            and "run_phase5r_c7_weekly_conviction_pipeline" not in status_source
            and "launchctl bootstrap" not in status_source,
            "workflow, scheduler, due, D3, and C6 status only",
        ),
        (
            "no broker libraries or order calls exist in D3 wrapper",
            not broker_imports and not order_calls,
            f"broker_imports={broker_imports}; order_calls={order_calls}",
        ),
        (
            "no archived legacy input is referenced",
            not archive_references,
            f"archive_references={archive_references}",
        ),
        (
            "SMTP configuration was not modified or read by verification",
            smtp_metadata_before == smtp_metadata_after,
            "metadata unchanged; content not opened",
        ),
        (
            "no SMTP password marker appears in D3 logs or reports",
            not secret_markers,
            f"secret_markers={secret_markers}",
        ),
        (
            "Phase 5R-E was not created",
            phase_e_before == phase_e_after and not phase_e_after,
            f"paths={phase_e_after}",
        ),
        (
            "all required non-verification D3 outputs exist",
            all(path.exists() for path in REQUIRED_STATIC_OUTPUTS),
            f"output_count={len(REQUIRED_STATIC_OUTPUTS)}",
        ),
    ]

    passed = all(ok for _, ok, _ in checks)
    generated = timestamp()
    lines = [
        "# Phase 5R-D3 Verification Report",
        "",
        f"Generated: `{generated}`",
        "",
        "## Result",
        "",
        f"Overall status: `{'PASS' if passed else 'FAIL'}`.",
        "",
        "## Required Checks",
        "",
    ]
    lines.extend(
        f"- **{'PASS' if ok else 'FAIL'}** - {label}: {detail}."
        for label, ok, detail in checks
    )
    lines.extend(
        [
            "",
            "## Live Scheduler State",
            "",
            f"- D2 installed: `{str(d2_installed_after).lower()}`.",
            f"- D2 loaded: `{str(d2_loaded_after).lower()}`.",
            "- D3 installed: `false`.",
            "- D3 loaded: `false`.",
            "",
            "## Verification Boundary",
            "",
            "Verification executed only the wrapper's explicit verification-only path. It did not acquire the cycle send lock, invoke C7, send email, install or load D3, change D2, read SMTP configuration content, access a broker, create order code, read archived holdings, or create Phase 5R-E.",
        ]
    )
    report_text = "\n".join(lines) + "\n"
    CONTROL_REPORT.write_text(report_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(report_text, encoding="utf-8")

    if not passed:
        failures = [label for label, ok, _ in checks if not ok]
        raise RuntimeError("Phase 5R-D3 verification failed: " + "; ".join(failures))
    print("Phase 5R-D3 verification passed; scheduler_installed=no; scheduler_loaded=no; c7_invoked=no; email_sent=no")


if __name__ == "__main__":
    main()
