from __future__ import annotations

import ast
import csv
import os
import plistlib
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
SCHEDULER_DIR = ROOT / "07_automation" / "scheduler"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_d1_scheduler_setup_log.csv"

LABEL = "com.steven.phase5r.dailybrief"
PLIST_PATH = SCHEDULER_DIR / f"{LABEL}.plist.template"
INSTALL_PATH = SCHEDULER_DIR / "install_phase5r_d1_scheduler.sh"
UNINSTALL_PATH = SCHEDULER_DIR / "uninstall_phase5r_d1_scheduler.sh"
STATUS_PATH = SCHEDULER_DIR / "check_phase5r_d1_scheduler_status.sh"
PIPELINE_PATH = SCRIPTS_DIR / "run_phase5r_c3_daily_email_pipeline.py"
REPORT_PATH = CONTROL_DIR / "phase5r_d1_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_d1_scheduler_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_d1_verification_report.md"
INSTALLED_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

EXPECTED_PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
EXPECTED_PIPELINE = "/Users/messssi/Desktop/equity/09_scripts/phase5r/run_phase5r_c3_daily_email_pipeline.py"
EXPECTED_STDOUT = "/Users/messssi/Desktop/equity/00_project_control/run_logs/phase5r_d1_launchd_stdout.log"
EXPECTED_STDERR = "/Users/messssi/Desktop/equity/00_project_control/run_logs/phase5r_d1_launchd_stderr.log"
LOG_FIELDS = ["timestamp", "phase", "action", "status", "plist_template_path", "launchagent_target_path", "scheduler_installed", "pipeline_invoked", "email_sent", "details", "safety_notes"]
REQUIRED_FILES = [
    "00_project_control/phase5r_d1_mac_scheduler_policy.md", "00_project_control/phase5r_d1_install_instructions.md", "00_project_control/phase5r_d1_verification_report.md",
    "07_automation/scheduler/com.steven.phase5r.dailybrief.plist.template", "07_automation/scheduler/install_phase5r_d1_scheduler.sh",
    "07_automation/scheduler/uninstall_phase5r_d1_scheduler.sh", "07_automation/scheduler/check_phase5r_d1_scheduler_status.sh",
    "09_scripts/phase5r/verify_phase5r_d1_scheduler_boundary.py", "04_research/realtime_stock_picker_phase5r/phase5r_d1_scheduler_report.md",
    "04_research/realtime_stock_picker_phase5r/phase5r_d1_verification_report.md", "00_project_control/run_logs/phase5r_d1_scheduler_setup_log.csv",
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "add_attachment"}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def phase5r_e_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_e(?:\\b|[0-9_-])|-e\\b)|phase5re", re.IGNORECASE)
    matches: list[str] = []
    for folder in (CONTROL_DIR, ROOT / "03_source_data", RESEARCH_DIR, ROOT / "08_reviews", ROOT / "07_automation", SCRIPTS_DIR):
        for path in folder.rglob("*"):
            if path.is_file() and pattern.search(str(path)):
                matches.append(str(path.relative_to(ROOT)))
    return matches


def ast_boundary_scan() -> tuple[list[str], list[str]]:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    broker: list[str] = []
    blocked: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [(node.module or "").split(".")[0]]
        broker.extend(module for module in modules if module in BROKER_MODULES)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                blocked.append(node.func.id)
            if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALLS:
                blocked.append(node.func.attr)
    return broker, blocked


def main() -> None:
    generated_reports = {str(REPORT_PATH.relative_to(ROOT)), str(RESEARCH_REPORT.relative_to(ROOT)), str(RESEARCH_VERIFICATION.relative_to(ROOT))}
    missing = [name for name in REQUIRED_FILES if name not in generated_reports and not (ROOT / name).exists()]
    with PLIST_PATH.open("rb") as handle:
        plist = plistlib.load(handle)
    arguments = plist.get("ProgramArguments", [])
    schedule = plist.get("StartCalendarInterval", [])
    expected_schedule = [{"Weekday": weekday, "Hour": 9, "Minute": 5} for weekday in range(1, 6)]
    shell_paths = [INSTALL_PATH, UNINSTALL_PATH, STATUS_PATH]
    shell_text = "\n".join(path.read_text(encoding="utf-8") for path in shell_paths)
    shell_executable = all(path.exists() and os.access(path, os.X_OK) for path in shell_paths)
    broker, blocked = ast_boundary_scan()
    shell_boundary_violations = re.findall(r"(?i)(?:alpaca|ib_insync|robin_stocks|place_order|submit_order|execute_trade|send_order)", shell_text)
    credential_markers = re.findall(r"(?i)(?:smtp_app_password|smtp_password|password\\s*[:=]\\s*[^,;\\s]+)", PLIST_PATH.read_text(encoding="utf-8") + shell_text + RUN_LOG.read_text(encoding="utf-8"))
    phase_e = phase5r_e_paths()
    target_installed = INSTALLED_PATH.exists()
    checks = [
        ("plist template created", PLIST_PATH.exists() and plist.get("Label") == LABEL, f"label={plist.get('Label')}"),
        ("install script created", INSTALL_PATH.exists() and shell_executable, f"exists={INSTALL_PATH.exists()}, all_shell_scripts_executable={shell_executable}"),
        ("uninstall script created", UNINSTALL_PATH.exists() and shell_executable, f"exists={UNINSTALL_PATH.exists()}, all_shell_scripts_executable={shell_executable}"),
        ("status script created", STATUS_PATH.exists() and shell_executable, f"exists={STATUS_PATH.exists()}, all_shell_scripts_executable={shell_executable}"),
        ("scheduler points only to C3 pipeline", arguments == [EXPECTED_PYTHON, EXPECTED_PIPELINE] and Path(arguments[0]).is_absolute() and Path(arguments[1]).is_absolute(), f"ProgramArguments={arguments}"),
        ("scheduler runs once per weekday morning", schedule == expected_schedule and "StartInterval" not in plist and plist.get("KeepAlive") is False, f"schedule={schedule}"),
        ("scheduler uses local time and excludes weekends", {item['Weekday'] for item in schedule} == {1, 2, 3, 4, 5} and all(item['Hour'] == 9 and item['Minute'] == 5 for item in schedule), "Weekday=1..5; no timezone override"),
        ("installation does not trigger an immediate run", plist.get("RunAtLoad") is False and "kickstart" not in shell_text, f"RunAtLoad={plist.get('RunAtLoad')}"),
        ("launchd output paths are canonical", plist.get("StandardOutPath") == EXPECTED_STDOUT and plist.get("StandardErrorPath") == EXPECTED_STDERR, f"stdout={plist.get('StandardOutPath')}, stderr={plist.get('StandardErrorPath')}"),
        ("no intraday alert or repeated schedule logic", schedule == expected_schedule and "StartInterval" not in plist and plist.get("KeepAlive") is False, "five weekly calendar entries only"),
        ("no broker/order code", not broker and not blocked and not shell_boundary_violations, f"broker={broker}, blocked={blocked}, shell={shell_boundary_violations}"),
        ("no password exposure", not credential_markers and "phase5r_email_config.local.json" not in shell_text, f"markers={credential_markers}"),
        ("no archived legacy inputs", "11_archive" not in PLIST_PATH.read_text(encoding="utf-8") and "11_archive" not in shell_text, "archive references absent"),
        ("Phase 5R-E was not created", not phase_e, f"paths={phase_e}"),
    ]
    lines = ["# Phase 5R-D1 Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    for label, passed, detail in checks:
        lines.append(f"- **{'PASS' if passed else 'FAIL'}** - {label}: {detail}.")
    lines.extend(["", "## Installation State", "", f"- User LaunchAgent target exists: `{'yes' if target_installed else 'no'}`.", "- D1 verification did not install, load, or run the scheduler.", "- No pipeline or email was triggered during setup verification.", "", "## Boundary", "", "The D1 artifacts define a local weekday launchd schedule only. They contain no credentials, broker integration, order placement, intraday alerting, repeated interval, cloud deployment, archived legacy dependency, or Phase 5R-E artifact."])
    report_text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(report_text, encoding="utf-8")
    research_lines = [
        "# Phase 5R-D1 Scheduler Report", "", f"Generated: `{timestamp()}`", "", "## Scheduler Design", "",
        "The D1 launchd agent invokes the existing C3 pipeline once at 9:05 AM local time on Monday through Friday. The template uses absolute Python, project, pipeline, stdout, and stderr paths.", "",
        "## Installation State", "", f"- Installed during D1 build: `{'yes' if target_installed else 'no'}`.",
        "- Pipeline invoked during D1 build: `no`.", "- Email sent during D1 build: `no`.", "",
        "## Safety Boundary", "", "No RunAtLoad execution, KeepAlive retry, interval timer, weekend entry, intraday scan, broker connection, order placement, SMTP credential handling, cloud deployment, archived legacy input, or Phase 5R-E.",
    ]
    RESEARCH_REPORT.write_text("\n".join(research_lines) + "\n", encoding="utf-8")
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=LOG_FIELDS).writerow({
            "timestamp": timestamp(), "phase": "phase5r_d1", "action": "verify_scheduler_artifacts",
            "status": "complete" if all(passed for _, passed, _ in checks) else "failed",
            "plist_template_path": str(PLIST_PATH.relative_to(ROOT)), "launchagent_target_path": f"~/Library/LaunchAgents/{LABEL}.plist",
            "scheduler_installed": "yes" if target_installed else "no", "pipeline_invoked": "no", "email_sent": "no",
            "details": "Validated plist schedule, absolute paths, management scripts, and safety boundary without loading launchd",
            "safety_notes": "config_read=no; credentials_modified=no; no_broker=yes; no_orders=yes; archived_legacy_used=no; phase5r_e_created=no",
        })
    if not all(passed for _, passed, _ in checks):
        raise RuntimeError("Phase 5R-D1 verification failed; see verification report")
    print("Wrote Phase 5R-D1 verification reports; scheduler was not installed or run.")


if __name__ == "__main__":
    main()
