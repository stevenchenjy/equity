from __future__ import annotations

import ast
import csv
import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
AUTOMATION_DIR = ROOT / "07_automation"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c7_weekly_pipeline_run_log.csv"
PIPELINE = SCRIPTS_DIR / "run_phase5r_c7_weekly_conviction_pipeline.py"
SENDER = SCRIPTS_DIR / "send_phase5r_c6_weekly_email.py"
STATUS_REPORT = CONTROL_DIR / "phase5r_c7_pipeline_status_report.md"
CONTROL_REPORT = CONTROL_DIR / "phase5r_c7_verification_report.md"
PIPELINE_REPORT = RESEARCH_DIR / "phase5r_c7_pipeline_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c7_verification_report.md"
LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
C5_QUEUE = RESEARCH_DIR / "phase5r_c5_research_queue.csv"
C5T_SCENARIOS = POSITION_DIR / "phase5r_c5t_trim_scenario_table.csv"
C6_STATUS = AUTOMATION_DIR / "email_delivery" / "phase5r_c6_delivery_status.csv"
SMTP_CONFIG = AUTOMATION_DIR / "email_delivery" / "phase5r_email_config.local.json"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.steven.phase5r.dailybrief.plist"

LOCAL_HASH_BASELINE = "d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c"
SMTP_SIZE_BASELINE = 241
SMTP_MTIME_BASELINE = 1783625651

EXPECTED_SCRIPTS = {
    "validate_phase5r_c4_position_state.py", "refresh_phase5r_c4r_current_position_intake.py",
    "run_phase5r_b2_full_universe_market_data.py", "score_phase5r_b2_candidates.py",
    "create_phase5r_b2_manual_trade_tickets.py", "create_phase5r_c5_research_queue.py",
    "create_phase5r_c5_company_research_packets.py", "score_phase5r_c5_weekly_conviction.py",
    "create_phase5r_c5_weekly_conviction_memo.py", "create_phase5r_c5t_trim_scenarios.py",
    "create_phase5r_c5t_manual_action_plan.py", "create_phase5r_c6_weekly_email_brief.py",
    "send_phase5r_c6_weekly_email.py",
}
REQUIRED_FILES = [
    CONTROL_DIR / "phase5r_c7_weekly_pipeline_policy.md", STATUS_REPORT, PIPELINE,
    Path(__file__), PIPELINE_REPORT, RUN_LOG,
]
LOG_FIELDS = [
    "timestamp", "run_id", "mode", "step_order", "pipeline_phase", "phase_step",
    "script_path", "invocation_mode", "status", "return_code", "started_at", "completed_at",
    "duration_seconds", "email_send_allowed", "email_send_attempted", "live_send_rows_before",
    "live_send_rows_after_step", "stop_reason", "safety_notes",
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
SCHEDULER_MODULES = {"schedule", "apscheduler", "croniter"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "add_attachment"}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def latest_mode_run(rows: list[dict[str, str]], mode: str) -> list[dict[str, str]]:
    run_ids = [row["run_id"] for row in rows if row["mode"] == mode]
    if not run_ids:
        return []
    target = run_ids[-1]
    return [row for row in rows if row["run_id"] == target]


def source_scan() -> tuple[list[str], list[str], list[str], set[str], int, int, list[str]]:
    broker: list[str] = []
    scheduler: list[str] = []
    blocked: list[str] = []
    suspicious_names: list[str] = []
    for path in (PIPELINE, Path(__file__)):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
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
                if name in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{name}")
            if path == PIPELINE and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lowered = node.name.lower()
                if any(token in lowered for token in ("scheduler", "intraday", "scanner", "repeated_alert")):
                    suspicious_names.append(f"{path.name}:{node.name}")
    pipeline_source = PIPELINE.read_text(encoding="utf-8")
    referenced = {name for name in EXPECTED_SCRIPTS if name in pipeline_source}
    tree = ast.parse(pipeline_source)
    sender_run_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_step":
            if any(isinstance(arg, ast.Name) and arg.id == "C6_SENDER" for arg in node.args):
                sender_run_calls += 1
    sender_tree = ast.parse(SENDER.read_text(encoding="utf-8"))
    send_message_calls = sum(
        1 for node in ast.walk(sender_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "send_message"
    )
    return broker, scheduler, blocked, referenced, sender_run_calls, send_message_calls, suspicious_names


def scheduler_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/com.steven.phase5r.dailybrief"],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def d2_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_d2_|-d2\b)|phase5rd2\b", re.IGNORECASE)
    roots = [CONTROL_DIR, POSITION_DIR, DATA_DIR, RESEARCH_DIR, AUTOMATION_DIR, ROOT / "08_reviews", SCRIPTS_DIR]
    return sorted(str(path.relative_to(ROOT)) for folder in roots for path in folder.rglob("*") if path.is_file() and pattern.search(path.name))


def append_verification_log(status: str, live_count: int) -> None:
    now = timestamp()
    row = {
        "timestamp": now, "run_id": f"phase5r_c7_verification_{now}", "mode": "verify",
        "step_order": "0", "pipeline_phase": "C7", "phase_step": "boundary_verification",
        "script_path": str(Path(__file__).relative_to(ROOT)), "invocation_mode": "verify",
        "status": status, "return_code": "0" if status == "complete" else "1",
        "started_at": now, "completed_at": now, "duration_seconds": "0.000",
        "email_send_allowed": "no", "email_send_attempted": "no",
        "live_send_rows_before": str(live_count), "live_send_rows_after_step": str(live_count),
        "stop_reason": "", "safety_notes": "verification_only=yes; credentials_read=no; child_scripts_not_executed=yes",
    }
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=LOG_FIELDS).writerow(row)


def main() -> None:
    rows = read_csv(RUN_LOG)
    dry_rows = latest_mode_run(rows, "dry_run")
    no_send_rows = latest_mode_run(rows, "no_send")
    dry_sender = [row for row in dry_rows if row["phase_step"] == "weekly_email_delivery"]
    no_send_sender = [row for row in no_send_rows if row["phase_step"] == "weekly_email_delivery"]
    broker, scheduler, blocked, referenced, sender_run_calls, send_message_calls, suspicious_names = source_scan()
    dry_safe = (
        len(dry_rows) == 13 and len(dry_sender) == 1
        and dry_sender[0]["invocation_mode"] == "dry_run"
        and dry_sender[0]["status"] == "complete"
        and dry_sender[0]["email_send_attempted"] == "no"
        and dry_sender[0]["live_send_rows_before"] == dry_sender[0]["live_send_rows_after_step"]
    )
    no_send_safe = (
        len(no_send_rows) == 13 and len(no_send_sender) == 1
        and no_send_sender[0]["invocation_mode"] == "no_send"
        and no_send_sender[0]["status"] == "skipped"
        and no_send_sender[0]["email_send_attempted"] == "no"
        and no_send_sender[0]["live_send_rows_before"] == no_send_sender[0]["live_send_rows_after_step"]
    )
    required_steps_ok = all(row["status"] == "complete" for row in dry_rows[:12]) and all(row["status"] == "complete" for row in no_send_rows[:12])
    local_tickers = {row["ticker"].upper() for row in read_csv(LOCAL_POSITIONS)}
    queue_current = [row for row in read_csv(C5_QUEUE) if row["research_role"] == "current_position_risk_review"]
    c5t_tickers = {row["ticker"] for row in read_csv(C5T_SCENARIOS)}
    b2_legacy = []
    for path in [DATA_DIR / "phase5r_b2_market_data_snapshot.csv", DATA_DIR / "phase5r_b2_signal_scores.csv", DATA_DIR / "phase5r_b2_manual_trade_tickets.csv"]:
        b2_legacy.extend(row["ticker"] for row in read_csv(path) if row.get("ticker", "").upper() in {"IOT", "RBRK"})
    pipeline_source = PIPELINE.read_text(encoding="utf-8")
    archive_log_refs = [row["script_path"] for row in rows if "11_archive" in row["script_path"]]
    output_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in [RUN_LOG, STATUS_REPORT, PIPELINE_REPORT]
        if path.exists()
    )
    password_markers = re.findall(r"(?i)(?:smtp_app_password|smtp_password|password\s*[:=]\s*[^,;\s]+)", output_text)
    smtp_stat = SMTP_CONFIG.stat()
    smtp_unchanged = smtp_stat.st_size == SMTP_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_MTIME_BASELINE
    live_count = sum(1 for row in read_csv(C6_STATUS) if row.get("mode") == "send" and row.get("sent") == "yes")
    checks = [
        ("C7 pipeline script was created", PIPELINE.exists() and all(path.exists() for path in REQUIRED_FILES), f"missing={[str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]}"),
        ("pipeline references position validation, B2, C5, C5T, C6 composer, and C6 sender", referenced == EXPECTED_SCRIPTS, f"references={len(referenced)}"),
        ("required weekly steps completed in test modes", required_steps_ok, f"dry_rows={len(dry_rows)}; no_send_rows={len(no_send_rows)}"),
        ("default mode sends at most one weekly email", sender_run_calls == 1 and send_message_calls == 1, f"sender_run_calls={sender_run_calls}; send_message_calls={send_message_calls}"),
        ("--dry-run sends no email", dry_safe, f"sender_rows={len(dry_sender)}"),
        ("--no-send sends no email", no_send_safe, f"sender_rows={len(no_send_sender)}"),
        ("no scheduler code created", not scheduler and not suspicious_names, f"scheduler_imports={scheduler}; suspicious={suspicious_names}"),
        ("no daily scheduler created", "launchd" not in pipeline_source.lower() and not scheduler, "no scheduler mechanism referenced"),
        ("no intraday alert logic created", not suspicious_names and "intraday" not in pipeline_source.lower(), f"suspicious={suspicious_names}"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not blocked, f"violations={blocked}"),
        ("no archived legacy data used", "11_archive" not in pipeline_source and not archive_log_refs, f"archive_refs={archive_log_refs}"),
        ("IOT/RBRK use only current local and C5/C5T context", local_tickers == {"IOT", "RBRK"} and {row["ticker"] for row in queue_current} == local_tickers and c5t_tickers == local_tickers and not b2_legacy, f"local={sorted(local_tickers)}; b2_legacy={b2_legacy}"),
        ("no SMTP password printed or logged", "phase5r_email_config.local.json" not in pipeline_source and not password_markers, f"markers={password_markers}"),
        ("SMTP config remained unchanged", smtp_unchanged, "metadata unchanged; C7 did not read config content"),
        ("current local positions remained read-only", digest(LOCAL_POSITIONS) == LOCAL_HASH_BASELINE, "hash unchanged"),
        ("scheduler was not installed or loaded", not D1_INSTALLED.exists() and not scheduler_loaded(), f"installed={D1_INSTALLED.exists()}"),
        ("Phase 5R-D2 was not created", not d2_paths(), f"paths={d2_paths()}"),
    ]
    passed = all(ok for _, ok, _ in checks)
    generated = timestamp()
    lines = ["# Phase 5R-C7 Verification Report", "", f"Generated: `{generated}`", "", "## Required Checks", ""]
    lines.extend(f"- **{'PASS' if ok else 'FAIL'}** - {label}: {detail}." for label, ok, detail in checks)
    lines.extend(["", "## Test Scope", "", "C7 was exercised in `--no-send` and `--dry-run` modes. Default live-delivery mode was inspected but not run during construction.", "", "## Pipeline", "", "- Position validation and C4R refresh precede market research.", "- B2 refresh, scoring, and manual tickets precede C5.", "- C5 research precedes C5T planning.", "- C6 composition precedes the single mode-controlled delivery step.", "", "## Boundary", "", "C7 is a manual weekly runner with strict stop-on-failure behavior. It has no scheduler, repeated notification, broker integration, automatic portfolio action, archived holding dependency, credential logging, or Phase 5R-D2 artifact."])
    report = "\n".join(lines) + "\n"
    CONTROL_REPORT.write_text(report, encoding="utf-8")
    RESEARCH_REPORT.write_text(report, encoding="utf-8")
    append_verification_log("complete" if passed else "failed", live_count)
    if not passed:
        raise RuntimeError("Phase 5R-C7 verification failed")
    print("Phase 5R-C7 verification passed; default_send_not_run=yes")


if __name__ == "__main__":
    main()
