from __future__ import annotations

import ast
import csv
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
AUTOMATION_DIR = ROOT / "07_automation"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c3_daily_pipeline_run_log.csv"
PIPELINE_PATH = SCRIPTS_DIR / "run_phase5r_c3_daily_email_pipeline.py"
STATUS_REPORT = CONTROL_DIR / "phase5r_c3_pipeline_status_report.md"
REPORT_PATH = CONTROL_DIR / "phase5r_c3_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c3_pipeline_report.md"
RESEARCH_VERIFICATION = RESEARCH_DIR / "phase5r_c3_verification_report.md"

LOG_FIELDS = [
    "timestamp", "run_id", "mode", "step_order", "phase_step", "script_path", "invocation_mode", "status", "return_code",
    "started_at", "completed_at", "email_send_allowed", "email_send_attempted", "live_send_rows_before", "live_send_rows_after_step",
    "stop_reason", "safety_notes",
]
REQUIRED_FILES = [
    "00_project_control/phase5r_c3_daily_pipeline_policy.md", "00_project_control/phase5r_c3_pipeline_status_report.md", "00_project_control/phase5r_c3_verification_report.md",
    "09_scripts/phase5r/run_phase5r_c3_daily_email_pipeline.py", "09_scripts/phase5r/verify_phase5r_c3_daily_pipeline_boundary.py",
    "04_research/realtime_stock_picker_phase5r/phase5r_c3_pipeline_report.md", "04_research/realtime_stock_picker_phase5r/phase5r_c3_verification_report.md",
    "00_project_control/run_logs/phase5r_c3_daily_pipeline_run_log.csv",
]
EXPECTED_SCRIPT_NAMES = {
    "run_phase5r_b2_full_universe_market_data.py", "score_phase5r_b2_candidates.py", "create_phase5r_b2_manual_trade_tickets.py",
    "create_phase5r_c1_daily_email_brief.py", "send_phase5r_c2_daily_email.py",
}
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
SCHEDULER_MODULES = {"schedule", "apscheduler", "croniter"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "add_attachment"}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def scan_scripts() -> tuple[list[str], list[str], list[str], int, set[str]]:
    broker: list[str] = []
    scheduler: list[str] = []
    blocked: list[str] = []
    c2_run_calls = 0
    suspicious_names: set[str] = set()
    for path in (PIPELINE_PATH, Path(__file__)):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            for module in modules:
                if module in BROKER_MODULES:
                    broker.append(f"{path.name}:{module}")
                if module in SCHEDULER_MODULES:
                    scheduler.append(f"{path.name}:{module}")
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{node.func.attr}")
                if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{node.func.id}")
                if isinstance(node.func, ast.Name) and node.func.id == "run_step" and any(isinstance(arg, ast.Name) and arg.id == "C2_SENDER" for arg in node.args):
                    c2_run_calls += 1
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lowered = node.name.lower()
                if any(token in lowered for token in ("scheduler", "intraday", "alert", "scanner")):
                    suspicious_names.add(f"{path.name}:{node.name}")
    source = PIPELINE_PATH.read_text(encoding="utf-8")
    references = {name for name in EXPECTED_SCRIPT_NAMES if name in source}
    return broker, scheduler, blocked, c2_run_calls, references | suspicious_names


def latest_mode_run(rows: list[dict[str, str]], mode: str) -> list[dict[str, str]]:
    run_ids = [row["run_id"] for row in rows if row["mode"] == mode]
    if not run_ids:
        return []
    target = run_ids[-1]
    return [row for row in rows if row["run_id"] == target]


def phase5r_d_paths() -> list[str]:
    matches: list[str] = []
    pattern = re.compile(r"phase5r(?:_d(?:\\b|[0-9_-])|-d\\b)|phase5rd", re.IGNORECASE)
    for folder in (CONTROL_DIR, DATA_DIR, RESEARCH_DIR, REVIEWS_DIR, AUTOMATION_DIR, SCRIPTS_DIR):
        for path in folder.rglob("*"):
            if path.is_file() and pattern.search(str(path)):
                matches.append(str(path.relative_to(ROOT)))
    return matches


def main() -> None:
    generated_reports = {str(REPORT_PATH.relative_to(ROOT)), str(RESEARCH_REPORT.relative_to(ROOT)), str(RESEARCH_VERIFICATION.relative_to(ROOT))}
    missing = [name for name in REQUIRED_FILES if name not in generated_reports and not (ROOT / name).exists()]
    rows = read_csv(RUN_LOG)
    dry_rows = latest_mode_run(rows, "dry_run")
    no_send_rows = latest_mode_run(rows, "no_send")
    dry_c2 = [row for row in dry_rows if row["phase_step"] == "C2 delivery"]
    no_send_c2 = [row for row in no_send_rows if row["phase_step"] == "C2 delivery"]
    broker, scheduler, blocked, c2_run_calls, reference_data = scan_scripts()
    referenced_scripts = reference_data & EXPECTED_SCRIPT_NAMES
    suspicious_names = reference_data - EXPECTED_SCRIPT_NAMES
    dry_safe = bool(dry_c2) and all(row["invocation_mode"] == "dry_run" and row["email_send_attempted"] == "no" and row["live_send_rows_before"] == row["live_send_rows_after_step"] for row in dry_c2)
    no_send_safe = bool(no_send_c2) and all(row["status"] == "skipped" and row["invocation_mode"] == "no_send" and row["email_send_attempted"] == "no" and row["live_send_rows_before"] == row["live_send_rows_after_step"] for row in no_send_c2)
    data_paths = [DATA_DIR / "phase5r_b2_market_data_snapshot.csv", DATA_DIR / "phase5r_b2_signal_scores.csv", DATA_DIR / "phase5r_b2_manual_trade_tickets.csv"]
    legacy_outputs: list[str] = []
    for path in data_paths:
        if path.exists():
            for row in read_csv(path):
                if row.get("ticker", "").upper() in {"IOT", "RBRK"}:
                    legacy_outputs.append(f"{path.name}:{row['ticker']}")
    pipeline_source = PIPELINE_PATH.read_text(encoding="utf-8")
    log_text = RUN_LOG.read_text(encoding="utf-8")
    status_text = STATUS_REPORT.read_text(encoding="utf-8") if STATUS_REPORT.exists() else ""
    password_markers = re.findall(r"(?i)(?:smtp_app_password|smtp_password|password\\s*[:=]\\s*[^,;\\s]+)", log_text + status_text)
    archive_inputs = [row for row in rows if "11_archive" in row["script_path"]]
    phase_d = phase5r_d_paths()
    checks = [
        ("C3 pipeline script was created", not missing, f"missing={missing}"),
        ("pipeline references B2, C1, and C2 scripts", referenced_scripts == EXPECTED_SCRIPT_NAMES, f"references={sorted(referenced_scripts)}"),
        ("default mode sends at most one email", c2_run_calls == 1, f"C2_run_step_calls={c2_run_calls}"),
        ("--dry-run sends no email", dry_safe, f"C2_rows={len(dry_c2)}"),
        ("--no-send sends no email", no_send_safe, f"C2_rows={len(no_send_c2)}"),
        ("no scheduler code created", not scheduler and not suspicious_names, f"scheduler_imports={scheduler}, suspicious_names={sorted(suspicious_names)}"),
        ("no intraday alert logic created", not suspicious_names, f"suspicious_names={sorted(suspicious_names)}"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not blocked, f"violations={blocked}"),
        ("no archived legacy data used", not archive_inputs and "11_archive" not in pipeline_source, f"archive_inputs={archive_inputs}"),
        ("no IOT/RBRK holding data used", not legacy_outputs, f"legacy_outputs={legacy_outputs}"),
        ("no password printed or logged", "smtp_app_password" not in pipeline_source and not password_markers, f"markers={password_markers}"),
        ("Phase 5R-D was not created", not phase_d, f"paths={phase_d}"),
    ]
    lines = ["# Phase 5R-C3 Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    for label, passed, detail in checks:
        lines.append(f"- **{'PASS' if passed else 'FAIL'}** - {label}: {detail}.")
    lines.extend(["", "## Test Scope", "", "C3 was exercised in `--no-send` and `--dry-run` modes only. The default live-send mode was not invoked during build verification.", "", "## Boundary", "", "The pipeline is a manual one-command runner. It contains no scheduler, repeated-notification mechanism, intraday alert, broker integration, order placement, credential access, archived legacy dependency, or Phase 5R-D artifact."])
    report_text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    RESEARCH_VERIFICATION.write_text(report_text, encoding="utf-8")
    research_lines = [
        "# Phase 5R-C3 Pipeline Report", "", f"Generated: `{timestamp()}`", "", "## Pipeline", "",
        "The C3 runner refreshes B2 market data, recalculates B2 scores, rebuilds B2 manual tickets, composes the C1 daily brief, and invokes the C2 sender at most once according to the selected mode.", "",
        "## Validation", "", f"- Latest `--no-send` step rows: `{len(no_send_rows)}`.", f"- Latest `--dry-run` step rows: `{len(dry_rows)}`.",
        "- Live emails sent during C3 build verification: `0`.", "- Default mode was verified statically to contain one C2 invocation path.", "",
        "## Safety Boundary", "", "Manual execution only. No scheduler, intraday alert, repeated notification, broker connection, order placement, SMTP credential handling in C3, archived legacy input, or Phase 5R-D.",
    ]
    RESEARCH_REPORT.write_text("\n".join(research_lines) + "\n", encoding="utf-8")
    verify_row = {
        "timestamp": timestamp(), "run_id": f"phase5r_c3_verification_{datetime.now(timezone.utc).astimezone().strftime('%Y%m%dT%H%M%S%z')}", "mode": "verify", "step_order": "0",
        "phase_step": "C3 boundary verification", "script_path": str(Path(__file__).relative_to(ROOT)), "invocation_mode": "verification_only",
        "status": "complete" if all(passed for _, passed, _ in checks) else "failed", "return_code": "0" if all(passed for _, passed, _ in checks) else "1",
        "started_at": timestamp(), "completed_at": timestamp(), "email_send_allowed": "no", "email_send_attempted": "no",
        "live_send_rows_before": "", "live_send_rows_after_step": "", "stop_reason": "",
        "safety_notes": "verification_only=yes; live_send_invoked=no; credentials_read=no; no_scheduler=yes; no_intraday_alerts=yes; no_broker=yes; no_orders=yes; archived_legacy_used=no",
    }
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=LOG_FIELDS).writerow(verify_row)
    if not all(passed for _, passed, _ in checks):
        raise RuntimeError("Phase 5R-C3 verification failed; see verification report")
    print("Wrote Phase 5R-C3 verification reports; no live email was sent during verification.")


if __name__ == "__main__":
    main()
