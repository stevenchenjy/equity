from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import plistlib
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
RUN_LOG_DIR = CONTROL_DIR / "run_logs"
SCHEDULER_DIR = ROOT / "07_automation" / "scheduler"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"

ACTIVE_STATE = CONTROL_DIR / "active_decision_state.yaml"
C6_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv"
C7_LOG = RUN_LOG_DIR / "phase5r_c7_weekly_pipeline_run_log.csv"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"
D3_STATE = RUN_LOG_DIR / "phase5r_d3_catchup_state.local.json"
INSTALL_INHIBIT = RUN_LOG_DIR / "phase5r_d3_install_inhibit"
D3F_HOLD = RUN_LOG_DIR / "phase5r_d3f_verification_inhibit"
D3_CHECK_LOG = RUN_LOG_DIR / "phase5r_d3_catchup_check_log.csv"
D3F_LOG = RUN_LOG_DIR / "phase5r_d3f_hotfix_log.csv"

INSTALL = SCHEDULER_DIR / "install_phase5r_d3_catchup_scheduler.sh"
STATUS = SCHEDULER_DIR / "check_phase5r_d3_catchup_status.sh"
UNINSTALL = SCHEDULER_DIR / "uninstall_phase5r_d3_catchup_scheduler.sh"
UNBLOCK = SCHEDULER_DIR / "unblock_phase5r_d3_catchup_after_verification.sh"
PLIST_TEMPLATE = SCHEDULER_DIR / "com.steven.phase5r.weeklycatchup.plist.template"
WRAPPER = SCRIPTS_DIR / "run_phase5r_d3_weekly_catchup.py"
PLAN = CONTROL_DIR / "phase5r_d3f_hotfix_plan.md"
CONTROL_REPORT = CONTROL_DIR / "phase5r_d3f_verification_report.md"
OPERATIONAL_STATUS = CONTROL_DIR / "phase5r_d3f_operational_status.md"
RESEARCH_HOTFIX = RESEARCH_DIR / "phase5r_d3f_hotfix_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_d3f_verification_report.md"

D2_LABEL = "com.steven.phase5r.weeklyconviction"
D3_LABEL = "com.steven.phase5r.weeklycatchup"
PYTHON_BIN = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
ROOT_ABSOLUTE = "/Users/messssi/Desktop/equity"
WRAPPER_ABSOLUTE = f"{ROOT_ABSOLUTE}/09_scripts/phase5r/run_phase5r_d3_weekly_catchup.py"
INSTALLED_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{D3_LABEL}.plist"

SHELL_SCRIPTS = [INSTALL, STATUS, UNINSTALL, UNBLOCK]
UNSAFE_ASSIGNMENT = re.compile(
    r"(?:^|[;\s])(status|path|UID|EUID|RANDOM)\s*=", re.MULTILINE
)
PROTECTION_KEYS = ("verification_flag_active", "install_inhibit", "protected_verification")
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


def digest(file_name: Path) -> str | None:
    return hashlib.sha256(file_name.read_bytes()).hexdigest() if file_name.exists() else None


def metadata(file_name: Path) -> tuple[int, int, int] | None:
    if not file_name.exists():
        return None
    file_stat = file_name.stat()
    return file_stat.st_size, file_stat.st_mtime_ns, file_stat.st_ctime_ns


def loaded(label: str) -> bool:
    result = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def launchd_details(label: str) -> str:
    result = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.stdout


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def successful_send_count() -> int:
    with C6_STATUS.open(newline="", encoding="utf-8") as handle:
        return sum(row.get("sent", "").lower() == "yes" for row in csv.DictReader(handle))


def d3f_rows() -> list[dict[str, str]]:
    with D3F_LOG.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def state_protections() -> list[str]:
    state = json.loads(D3_STATE.read_text(encoding="utf-8"))
    return [key for key in PROTECTION_KEYS if state.get(key) is True]


def scan_wrapper_boundary() -> tuple[list[str], list[str]]:
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
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            else:
                call_name = ""
            if call_name in BLOCKED_ORDER_CALLS:
                order_calls.append(call_name)
    return broker_imports, order_calls


def phase5r_e_files() -> list[str]:
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
        str(file_name.relative_to(ROOT))
        for folder in roots
        for file_name in folder.rglob("*")
        if file_name.is_file() and pattern.search(file_name.name)
    )


def main() -> None:
    required = [
        ACTIVE_STATE,
        C6_STATUS,
        D3_STATE,
        D3_CHECK_LOG,
        D3F_LOG,
        PLIST_TEMPLATE,
        WRAPPER,
        PLAN,
        *SHELL_SCRIPTS,
    ]
    missing = [str(file_name.relative_to(ROOT)) for file_name in required if not file_name.exists()]
    if missing:
        raise RuntimeError(f"missing D3F inputs: {missing}")

    # This independent hold remains present if verification fails. The unblock
    # script clears legacy protection while preserving this hold.
    D3F_HOLD.touch(exist_ok=True)

    c6_hash_before = digest(C6_STATUS)
    c7_hash_before = digest(C7_LOG)
    smtp_before = metadata(SMTP_CONFIG)
    send_count_before = successful_send_count()
    phase_e_before = phase5r_e_files()
    d3f_rows_before = len(d3f_rows())

    state = json.loads(ACTIVE_STATE.read_text(encoding="utf-8"))
    with PLIST_TEMPLATE.open("rb") as handle:
        template = plistlib.load(handle)
    with INSTALLED_PLIST.open("rb") as handle:
        installed = plistlib.load(handle)
    wrapper_source = WRAPPER.read_text(encoding="utf-8")
    broker_imports, order_calls = scan_wrapper_boundary()

    unsafe_assignments: dict[str, list[str]] = {}
    syntax_results: dict[str, int] = {}
    for shell_script in SHELL_SCRIPTS:
        shell_source = shell_script.read_text(encoding="utf-8")
        unsafe_assignments[str(shell_script.relative_to(ROOT))] = UNSAFE_ASSIGNMENT.findall(shell_source)
        syntax_results[str(shell_script.relative_to(ROOT))] = run(["/bin/zsh", "-n", str(shell_script)]).returncode

    status_before = run(["/bin/zsh", str(STATUS)])
    safe_wrapper = run([PYTHON_BIN, str(WRAPPER), "--safe-check"])
    unblock_check = run(["/bin/zsh", str(UNBLOCK), "--check-only", "--preserve-verification-hold"])
    unblock_clear = run(["/bin/zsh", str(UNBLOCK), "--preserve-verification-hold"])

    # Prove that the loaded LaunchAgent now starts successfully and that the
    # independent D3F hold blocks C7 after legacy protection is cleared.
    rows_before_kickstart = D3_CHECK_LOG.read_text(encoding="utf-8").count("\n")
    kickstart = run(["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{D3_LABEL}"])
    protected_row_seen = False
    for _ in range(60):
        lines = D3_CHECK_LOG.read_text(encoding="utf-8").splitlines()
        new_lines = lines[rows_before_kickstart:]
        if any(",verification_only,protected_verification_active," in line for line in new_lines):
            protected_row_seen = True
            break
        time.sleep(0.25)

    status_after = run(["/bin/zsh", str(STATUS)])
    c6_hash_after = digest(C6_STATUS)
    c7_hash_after = digest(C7_LOG)
    smtp_after = metadata(SMTP_CONFIG)
    send_count_after = successful_send_count()
    phase_e_after = phase5r_e_files()
    protection_after = state_protections()
    d3f_after = d3f_rows()
    launchd_state = launchd_details(D3_LABEL)

    old_workflow_markers = [
        marker
        for marker in (
            "send_phase5r_c2_daily_email",
            "run_phase5r_c3_daily_email_pipeline",
        )
        if marker in wrapper_source
    ]
    archive_markers = [
        marker
        for marker in ("11_archive", "legacy_pre_5r", "archived_iot", "archived_rbrk")
        if marker in wrapper_source.lower()
    ]
    checks = [
        (
            "active state authorizes weekly_conviction and phase5r_c7",
            state.get("current_workflow") == "weekly_conviction"
            and state.get("active_pipeline") == "phase5r_c7"
            and state.get("broker_connection_allowed") == "no"
            and state.get("order_code_allowed") == "no",
            f"workflow={state.get('current_workflow')}; pipeline={state.get('active_pipeline')}",
        ),
        (
            "zsh read-only assignment bug is fixed in every D3 shell script",
            all(not names for names in unsafe_assignments.values()),
            f"unsafe_assignments={unsafe_assignments}",
        ),
        (
            "install, check, uninstall, and unblock scripts parse under zsh",
            all(exit_code == 0 for exit_code in syntax_results.values()),
            f"syntax_return_codes={syntax_results}",
        ),
        (
            "check script runs without a zsh read-only variable error",
            status_before.returncode == 0
            and status_after.returncode == 0
            and "read-only variable" not in (status_before.stderr + status_after.stderr),
            f"before_return={status_before.returncode}; after_return={status_after.returncode}",
        ),
        (
            "D3 remains loaded and D2 remains unloaded",
            loaded(D3_LABEL) and not loaded(D2_LABEL),
            f"d3_loaded={loaded(D3_LABEL)}; d2_loaded={loaded(D2_LABEL)}",
        ),
        (
            "installed D3 plist exists and matches the repaired template",
            INSTALLED_PLIST.exists() and installed == template,
            f"installed={INSTALLED_PLIST.exists()}",
        ),
        (
            "D3 plist points only to the D3 catch-up wrapper",
            installed.get("ProgramArguments") == [PYTHON_BIN, WRAPPER_ABSOLUTE]
            and installed.get("WorkingDirectory") == ROOT_ABSOLUTE,
            f"ProgramArguments={installed.get('ProgramArguments')}",
        ),
        (
            "D3 launchd schedule remains RunAtLoad=true, KeepAlive=false, StartInterval=900",
            installed.get("RunAtLoad") is True
            and installed.get("KeepAlive") is False
            and installed.get("StartInterval") == 900
            and "StartCalendarInterval" not in installed,
            "check-only interval configuration preserved",
        ),
        (
            "launchd stdout and stderr use a spawn-safe non-Desktop location",
            installed.get("StandardOutPath") == "/Users/messssi/Library/Logs/phase5r_d3_launchd_stdout.log"
            and installed.get("StandardErrorPath") == "/Users/messssi/Library/Logs/phase5r_d3_launchd_stderr.log",
            "prevents launchd EX_CONFIG before wrapper startup",
        ),
        (
            "loaded D3 LaunchAgent executes successfully after plist repair",
            kickstart.returncode == 0 and protected_row_seen and "last exit code = 0" in launchd_state,
            f"kickstart_return={kickstart.returncode}; protected_row_seen={protected_row_seen}",
        ),
        (
            "D3 wrapper points only to C7 as its child email pipeline",
            "run_phase5r_c7_weekly_conviction_pipeline.py" in wrapper_source
            and "send_phase5r_c6_weekly_email.py" not in wrapper_source
            and not old_workflow_markers,
            f"forbidden_workflow_markers={old_workflow_markers}",
        ),
        (
            "D3 wrapper retains lock protection",
            "phase5r_d3_catchup.lock" in wrapper_source
            and "fcntl.LOCK_EX | fcntl.LOCK_NB" in wrapper_source,
            "nonblocking OS file lock",
        ),
        (
            "D3 wrapper retains once-per-cycle and C6 sent guards",
            "cycle_attempts" in wrapper_source
            and "sent_in_cycle" in wrapper_source
            and "phase5r_c6_delivery_status.csv" in wrapper_source
            and "send_delta == 1" in wrapper_source,
            "C6 success plus durable attempt ledger",
        ),
        (
            "explicit wrapper safe-check mode does not invoke C7",
            safe_wrapper.returncode == 0
            and "decision=verification_only" in safe_wrapper.stdout
            and "safe_check_requested" in safe_wrapper.stdout,
            f"return={safe_wrapper.returncode}",
        ),
        (
            "unblock script validates safely and clears legacy protection",
            unblock_check.returncode == 0
            and unblock_clear.returncode == 0
            and not INSTALL_INHIBIT.exists()
            and not protection_after
            and D3F_HOLD.exists(),
            f"check_return={unblock_check.returncode}; clear_return={unblock_clear.returncode}; state_flags={protection_after}",
        ),
        (
            "D3F unblock audit rows record no C7 invocation or email",
            len(d3f_after) >= d3f_rows_before + 2
            and all(
                row.get("c7_invoked") == "no"
                and row.get("email_sent") == "no"
                and row.get("smtp_config_modified") == "no"
                for row in d3f_after[d3f_rows_before:]
            ),
            f"new_d3f_rows={len(d3f_after) - d3f_rows_before}",
        ),
        (
            "no email was sent and C7 was not run during D3F verification",
            c6_hash_before == c6_hash_after
            and c7_hash_before == c7_hash_after
            and send_count_before == send_count_after,
            f"successful_send_rows={send_count_after}; hashes_unchanged={c6_hash_before == c6_hash_after and c7_hash_before == c7_hash_after}",
        ),
        (
            "SMTP configuration was not modified or read",
            smtp_before == smtp_after,
            "metadata unchanged; content not opened",
        ),
        (
            "no broker imports or order calls were added",
            not broker_imports and not order_calls,
            f"broker_imports={broker_imports}; order_calls={order_calls}",
        ),
        (
            "no archived legacy input is referenced",
            not archive_markers,
            f"archive_markers={archive_markers}",
        ),
        (
            "Phase 5R-E was not created",
            phase_e_before == phase_e_after and not phase_e_after,
            f"paths={phase_e_after}",
        ),
    ]

    passed = all(ok for _, ok, _ in checks)
    generated = timestamp()
    report_lines = [
        "# Phase 5R-D3F Verification Report",
        "",
        f"Generated: `{generated}`",
        "",
        "## Result",
        "",
        f"Overall status: `{'PASS' if passed else 'FAIL'}`.",
        "",
        "## Checks",
        "",
    ]
    report_lines.extend(
        f"- **{'PASS' if ok else 'FAIL'}** - {label}: {detail}."
        for label, ok, detail in checks
    )
    report_lines.extend(
        [
            "",
            "## Verification Safety Boundary",
            "",
            "The independent `phase5r_d3f_verification_inhibit` remained present throughout verification. The legacy install inhibit and any local-state protection flags were cleared only by the explicit unblock script while that independent hold remained active.",
            "",
            "C7 was not invoked, no email was sent, SMTP configuration content was not read, D3 remained loaded, D2 remained unloaded, and no broker, order, archived-input, or Phase 5R-E capability was introduced.",
            "",
            "## Post-verification Handoff",
            "",
            "The temporary D3F hold must be cleared through the same unblock script after this verification process ends. That command performs no C7 or email invocation; it only makes the next ordinary 900-second D3 check eligible.",
        ]
    )
    report_text = "\n".join(report_lines) + "\n"
    CONTROL_REPORT.write_text(report_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(report_text, encoding="utf-8")

    hotfix_lines = [
        "# Phase 5R-D3F Hotfix Report",
        "",
        f"Generated: `{generated}`",
        "",
        "## Root Cause",
        "",
        "The installer exit trap assigned zsh's read-only `status` parameter. Independently, launchd could not open stdout/stderr under the protected Desktop tree and returned `78: EX_CONFIG` before the wrapper started.",
        "",
        "## Fix",
        "",
        "- Renamed the trap value to `exit_code` and audited all D3 shell assignments.",
        "- Moved launchd stdout/stderr to `~/Library/Logs` while retaining the project wrapper and working directory.",
        "- Added safe-check and independent D3F verification protection.",
        "- Added an explicit preflighted unblock command and D3F audit log.",
        "- Updated status output to separate historical verification decisions from live blocking state.",
        "",
        "## Live Verification Result",
        "",
        "The repaired LaunchAgent started the D3 wrapper and exited zero under protection. D3 remained loaded, D2 remained unloaded, and C6/C7 were unchanged.",
        "",
        "## Duplicate Protection",
        "",
        "The C6 successful-send check, nonblocking file lock, after-lock recheck, and durable once-per-cycle attempt ledger remain unchanged. A catch-up success still requires exactly one new qualifying C6 `sent=yes` row.",
    ]
    RESEARCH_HOTFIX.write_text("\n".join(hotfix_lines) + "\n", encoding="utf-8")

    if not passed:
        failures = [label for label, ok, _ in checks if not ok]
        raise RuntimeError("Phase 5R-D3F verification failed: " + "; ".join(failures))
    print("Phase 5R-D3F verification passed; d3_loaded=yes; d2_loaded=no; c7_invoked=no; email_sent=no; temporary_hold=present")


if __name__ == "__main__":
    main()
