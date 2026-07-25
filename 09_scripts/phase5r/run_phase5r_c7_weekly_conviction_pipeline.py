from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c7_weekly_pipeline_run_log.csv"
STATUS_REPORT = CONTROL_DIR / "phase5r_c7_pipeline_status_report.md"
PIPELINE_REPORT = RESEARCH_DIR / "phase5r_c7_pipeline_report.md"
C6_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv"
ACTIVE_STATE = CONTROL_DIR / "active_decision_state.yaml"
C9_MAINTENANCE_INHIBIT = ROOT / "07_automation" / "scheduler" / "phase5r_c9_maintenance_inhibit.local.json"

REQUIRED_ACTIVE_STATE = {
    "schema_version": "phase5r_c9_v1",
    "current_workflow": "weekly_conviction",
    "active_pipeline": "phase5r_c7",
    "primary_decision": "c9_account_aware_manual_review",
    "daily_pipeline_status": "parked",
    "d1_scheduler_status": "parked_uninstalled",
    "email_delivery_allowed_from": "phase5r_c7_only",
    "current_positions_source": "05_risk_and_positions/current_positions.local.csv",
    "archived_folders_allowed_as_input": "no",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
    "active_research_phase": "phase5r_c9",
    "active_action_planner": "phase5r_c9",
    "active_state_guard": "phase5r_c9",
}

B2_MARKET_REFRESH = SCRIPTS_DIR / "run_phase5r_b2_full_universe_market_data.py"
B2_SCORING = SCRIPTS_DIR / "score_phase5r_b2_candidates.py"
C9_ACCOUNT_STATE = SCRIPTS_DIR / "create_phase5r_c9_account_state.py"
C9_REGENERATION = SCRIPTS_DIR / "regenerate_phase5r_c9_portfolio_outputs.py"
C9_VERIFICATION = SCRIPTS_DIR / "verify_phase5r_c9_account_boundary.py"
C9B_EXECUTION_VALIDATION = SCRIPTS_DIR / "validate_phase5r_c9b_execution_fill.py"
C9B_RECONCILIATION_PREVIEW = SCRIPTS_DIR / "reconcile_phase5r_c9b_account_state.py"
C9B_PRICE_PLAN = SCRIPTS_DIR / "create_phase5r_c9b_price_aware_action_plan.py"
C9B_VERIFICATION = SCRIPTS_DIR / "verify_phase5r_c9b_boundary.py"
C6_COMPOSER = SCRIPTS_DIR / "create_phase5r_c6_weekly_email_brief.py"
C6_SENDER = SCRIPTS_DIR / "send_phase5r_c6_weekly_email.py"

STEP_REGISTRY = [
    (1, "B2", "public_market_data_refresh", B2_MARKET_REFRESH),
    (2, "B2", "candidate_scoring", B2_SCORING),
    (3, "C9", "account_state", C9_ACCOUNT_STATE),
    (4, "C9", "account_aware_regeneration", C9_REGENERATION),
    (5, "C9", "account_boundary_verification", C9_VERIFICATION),
    (6, "C9B", "execution_intake_validation", C9B_EXECUTION_VALIDATION),
    (7, "C9B", "account_reconciliation_preview", C9B_RECONCILIATION_PREVIEW),
    (8, "C9B", "price_aware_action_plan", C9B_PRICE_PLAN),
    (9, "C6", "weekly_email_composition", C6_COMPOSER),
    (10, "C9B", "execution_boundary_verification", C9B_VERIFICATION),
]

LOG_FIELDS = [
    "timestamp", "run_id", "mode", "step_order", "pipeline_phase", "phase_step",
    "script_path", "invocation_mode", "status", "return_code", "started_at", "completed_at",
    "duration_seconds", "email_send_allowed", "email_send_attempted", "live_send_rows_before",
    "live_send_rows_after_step", "stop_reason", "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def make_run_id(mode: str) -> str:
    compact = datetime.now(timezone.utc).astimezone().strftime("%Y%m%dT%H%M%S%z")
    return f"phase5r_c7_{compact}_{mode}"


def live_send_row_count() -> int:
    if not C6_STATUS.exists():
        return 0
    with C6_STATUS.open(newline="", encoding="utf-8") as handle:
        return sum(1 for row in csv.DictReader(handle) if row.get("mode") == "send" and row.get("sent") == "yes")


def validate_active_state() -> None:
    if not ACTIVE_STATE.exists():
        raise RuntimeError("active decision state is missing")
    try:
        with ACTIVE_STATE.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("active decision state is invalid") from exc
    if not isinstance(state, dict):
        raise RuntimeError("active decision state must be an object")
    conflicts = {
        key: state.get(key)
        for key, expected in REQUIRED_ACTIVE_STATE.items()
        if state.get(key) != expected
    }
    if conflicts:
        raise RuntimeError("active decision state conflicts with the C7 weekly boundary")


def validate_c9_maintenance_mode(mode: str) -> None:
    try:
        state = json.loads(C9_MAINTENANCE_INHIBIT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("C9 maintenance state is missing or invalid") from exc
    if not isinstance(state, dict) or not isinstance(state.get("active"), bool):
        raise RuntimeError("C9 maintenance state is invalid")
    if state["active"] is True:
        if state.get("allowed_pipeline") != "none" or mode != "no_send":
            raise RuntimeError("C9 maintenance permits only explicit C7 --no-send verification")
    elif state.get("allowed_pipeline") != "phase5r_c7":
        raise RuntimeError("cleared C9 maintenance state does not authorize C7")


def append_log(row: dict[str, str]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def build_log_row(
    run_id: str,
    mode: str,
    step_order: int,
    pipeline_phase: str,
    phase_step: str,
    script: Path,
    invocation_mode: str,
    status: str,
    return_code: str,
    started_at: str,
    completed_at: str,
    duration_seconds: float,
    live_before: int,
    email_send_allowed: str = "no",
    email_send_attempted: str = "no",
    stop_reason: str = "",
) -> dict[str, str]:
    return {
        "timestamp": completed_at, "run_id": run_id, "mode": mode,
        "step_order": str(step_order), "pipeline_phase": pipeline_phase, "phase_step": phase_step,
        "script_path": str(script.relative_to(ROOT)), "invocation_mode": invocation_mode,
        "status": status, "return_code": return_code, "started_at": started_at,
        "completed_at": completed_at, "duration_seconds": f"{duration_seconds:.3f}",
        "email_send_allowed": email_send_allowed, "email_send_attempted": email_send_attempted,
        "live_send_rows_before": str(live_before),
        "live_send_rows_after_step": str(live_send_row_count()), "stop_reason": stop_reason,
        "safety_notes": "manual_weekly_pipeline=yes; child_output_logged=no; credentials_read_by_c7=no; no_scheduler=yes; no_repeated_alerts=yes; no_broker=yes; archived_legacy_used=no",
    }


def run_step(
    run_id: str,
    mode: str,
    step_order: int,
    pipeline_phase: str,
    phase_step: str,
    script: Path,
    invocation_mode: str,
    args: list[str],
    live_before: int,
    email_send_allowed: str = "no",
    email_send_attempted: str = "no",
) -> dict[str, str]:
    started_at = timestamp()
    started_monotonic = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return_code = result.returncode
    except OSError:
        return_code = -1
    completed_at = timestamp()
    status = "complete" if return_code == 0 else "failed"
    row = build_log_row(
        run_id, mode, step_order, pipeline_phase, phase_step, script, invocation_mode,
        status, str(return_code), started_at, completed_at, time.monotonic() - started_monotonic,
        live_before, email_send_allowed, email_send_attempted,
        "" if status == "complete" else f"{phase_step} returned nonzero status",
    )
    append_log(row)
    return row


def skipped_step(
    run_id: str,
    mode: str,
    step_order: int,
    pipeline_phase: str,
    phase_step: str,
    script: Path,
    invocation_mode: str,
    live_before: int,
    reason: str,
) -> dict[str, str]:
    now = timestamp()
    row = build_log_row(
        run_id, mode, step_order, pipeline_phase, phase_step, script, invocation_mode,
        "skipped", "", now, now, 0.0, live_before, "no", "no", reason,
    )
    append_log(row)
    return row


def write_reports(
    run_id: str,
    mode: str,
    results: list[dict[str, str]],
    pipeline_status: str,
    live_before: int,
    live_after: int,
) -> None:
    generated = timestamp()
    lines = [
        "# Phase 5R-C7 Pipeline Status Report", "", f"Generated: `{generated}`", "",
        "## Run Summary", "", f"- Run ID: `{run_id}`.", f"- Mode: `{mode}`.",
        f"- Pipeline status: `{pipeline_status}`.", f"- Live-send rows before: `{live_before}`.",
        f"- Live-send rows after: `{live_after}`.", f"- Live-send row delta: `{live_after - live_before}`.", "",
        "## Step Status", "",
        "| Step | Phase | Action | Invocation | Status | Return | Duration | Email Attempted | Stop Reason |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in results:
        lines.append(
            f"| {row['step_order']} | {row['pipeline_phase']} | {row['phase_step']} | "
            f"{row['invocation_mode']} | {row['status']} | {row['return_code'] or 'n/a'} | "
            f"{row['duration_seconds']}s | {row['email_send_attempted']} | {row['stop_reason'] or 'none'} |"
        )
    lines.extend([
        "", "## Safety Boundary", "",
        "- Manual weekly invocation only; no scheduler or repeated notification mechanism.",
        "- While C9 maintenance is active, C7 permits only explicit --no-send verification.",
        "- C7 does not read SMTP configuration. The existing C6 sender owns that boundary.",
        "- Child output is not copied into C7 logs, preventing credential-bearing exception text from propagating.",
        "- No broker connection, automatic portfolio change, attachment, or archived holding input.",
    ])
    status_text = "\n".join(lines) + "\n"
    STATUS_REPORT.write_text(status_text, encoding="utf-8")

    complete_count = sum(row["status"] == "complete" for row in results)
    skipped_count = sum(row["status"] == "skipped" for row in results)
    failed_count = sum(row["status"] == "failed" for row in results)
    research_lines = [
        "# Phase 5R-C7 Pipeline Report", "", f"Generated: `{generated}`", "",
        "## Latest Run", "", f"- Run ID: `{run_id}`.", f"- Mode: `{mode}`.",
        f"- Status: `{pipeline_status}`.", f"- Completed steps: `{complete_count}`.",
        f"- Skipped steps: `{skipped_count}`.", f"- Failed steps: `{failed_count}`.",
        f"- Live-send delta: `{live_after - live_before}`.", "",
        "## Workflow", "",
        "The runner refreshes public B2 data, validates the C9 account state, regenerates account-aware weights/actions/allocation/research, verifies C9, validates and previews C9B execution reconciliation without applying state, refreshes price guidance, composes C6, verifies the C9B boundary, and delegates delivery only when the selected mode and maintenance state allow it.", "",
        "## Boundary", "",
        "C7 is a manual orchestration layer. It does not read credentials, connect to brokers, alter positions, install scheduling, read archived holdings, or create Phase 5R-D2.",
    ]
    PIPELINE_REPORT.write_text("\n".join(research_lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 5R weekly conviction pipeline once.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Run all steps and invoke C6 delivery in dry-run mode.")
    mode.add_argument("--no-send", action="store_true", help="Run through C6 composition and skip delivery.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = "dry_run" if args.dry_run else "no_send" if args.no_send else "send"
    try:
        validate_active_state()
        validate_c9_maintenance_mode(mode)
    except RuntimeError:
        print("Phase 5R-C7 blocked by active-state or C9-maintenance guard.")
        return 1
    run_id = make_run_id(mode)
    live_before = live_send_row_count()
    results: list[dict[str, str]] = []
    failed_at: int | None = None
    failure_reason = ""

    for step_order, pipeline_phase, phase_step, script in STEP_REGISTRY:
        row = run_step(
            run_id, mode, step_order, pipeline_phase, phase_step, script,
            "standard", [], live_before,
        )
        results.append(row)
        if row["status"] != "complete":
            failed_at = step_order
            failure_reason = f"stopped after {phase_step} failure"
            break

    if failed_at is not None:
        for step_order, pipeline_phase, phase_step, script in STEP_REGISTRY:
            if step_order > failed_at:
                results.append(skipped_step(
                    run_id, mode, step_order, pipeline_phase, phase_step, script,
                    "not_started", live_before, failure_reason,
                ))
        results.append(skipped_step(
            run_id, mode, len(STEP_REGISTRY) + 1, "C6", "weekly_email_delivery", C6_SENDER,
            "not_started", live_before, failure_reason,
        ))
        live_after = live_send_row_count()
        write_reports(run_id, mode, results, "failed", live_before, live_after)
        print(f"Phase 5R-C7 mode={mode}; status=failed; failed_step={failed_at}")
        return 1

    if mode == "no_send":
        sender_row = skipped_step(
            run_id, mode, len(STEP_REGISTRY) + 1, "C6", "weekly_email_delivery", C6_SENDER,
            "no_send", live_before, "delivery disabled by --no-send",
        )
    else:
        sender_args = ["--dry-run"] if mode == "dry_run" else []
        sender_row = run_step(
            run_id, mode, len(STEP_REGISTRY) + 1, "C6", "weekly_email_delivery", C6_SENDER,
            "dry_run" if mode == "dry_run" else "send", sender_args, live_before,
            "yes" if mode == "send" else "no", "yes" if mode == "send" else "no",
        )
    results.append(sender_row)

    live_after = live_send_row_count()
    sender_ok = sender_row["status"] in {"complete", "skipped"}
    send_delta_ok = (
        (mode == "send" and live_after - live_before == 1)
        or (mode in {"dry_run", "no_send"} and live_after == live_before)
    )
    pipeline_status = "complete" if sender_ok and send_delta_ok else "failed"
    if not send_delta_ok:
        sender_row["status"] = "failed"
        sender_row["stop_reason"] = "live-send row delta violated selected mode"
    write_reports(run_id, mode, results, pipeline_status, live_before, live_after)
    print(f"Phase 5R-C7 mode={mode}; status={pipeline_status}; live_send_delta={live_after - live_before}")
    return 0 if pipeline_status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
