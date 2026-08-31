from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
CONTROL_DIR = ROOT / "00_project_control"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c3_daily_pipeline_run_log.csv"
STATUS_REPORT = CONTROL_DIR / "phase5r_c3_pipeline_status_report.md"
C2_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c2_delivery_status.csv"

B2_MARKET_REFRESH = SCRIPTS_DIR / "run_phase5r_b2_full_universe_market_data.py"
B2_SCORING = SCRIPTS_DIR / "score_phase5r_b2_candidates.py"
B2_TICKETS = SCRIPTS_DIR / "create_phase5r_b2_manual_trade_tickets.py"
C1_COMPOSER = SCRIPTS_DIR / "create_phase5r_c1_daily_email_brief.py"
C2_SENDER = SCRIPTS_DIR / "send_phase5r_c2_daily_email.py"
LEGACY_PIPELINE_RETIRED = True

LOG_FIELDS = [
    "timestamp",
    "run_id",
    "mode",
    "step_order",
    "phase_step",
    "script_path",
    "invocation_mode",
    "status",
    "return_code",
    "started_at",
    "completed_at",
    "email_send_allowed",
    "email_send_attempted",
    "live_send_rows_before",
    "live_send_rows_after_step",
    "stop_reason",
    "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def make_run_id(mode: str) -> str:
    compact = datetime.now(timezone.utc).astimezone().strftime("%Y%m%dT%H%M%S%z")
    return f"phase5r_c3_{compact}_{mode}"


def live_send_row_count() -> int:
    if not C2_STATUS.exists():
        return 0
    with C2_STATUS.open(newline="", encoding="utf-8") as handle:
        return sum(1 for row in csv.DictReader(handle) if row.get("mode") == "send")


def append_log(row: dict[str, str]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def log_result(
    run_id: str,
    mode: str,
    step_order: int,
    phase_step: str,
    script: Path,
    invocation_mode: str,
    status: str,
    return_code: str,
    started_at: str,
    completed_at: str,
    email_send_allowed: str,
    email_send_attempted: str,
    live_before: int,
    live_after: int,
    stop_reason: str = "",
) -> dict[str, str]:
    row = {
        "timestamp": completed_at,
        "run_id": run_id,
        "mode": mode,
        "step_order": str(step_order),
        "phase_step": phase_step,
        "script_path": str(script.relative_to(ROOT)),
        "invocation_mode": invocation_mode,
        "status": status,
        "return_code": return_code,
        "started_at": started_at,
        "completed_at": completed_at,
        "email_send_allowed": email_send_allowed,
        "email_send_attempted": email_send_attempted,
        "live_send_rows_before": str(live_before),
        "live_send_rows_after_step": str(live_after),
        "stop_reason": stop_reason,
        "safety_notes": "manual_pipeline_only=yes; child_output_logged=no; credentials_read_by_c3=no; no_scheduler=yes; no_intraday_alerts=yes; no_broker=yes; no_orders=yes; archived_legacy_used=no",
    }
    append_log(row)
    return row


def run_step(
    run_id: str,
    mode: str,
    step_order: int,
    phase_step: str,
    script: Path,
    invocation_mode: str,
    args: list[str],
    live_before: int,
    email_send_allowed: str = "no",
    email_send_attempted: str = "no",
) -> dict[str, str]:
    started_at = timestamp()
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
    return log_result(
        run_id,
        mode,
        step_order,
        phase_step,
        script,
        invocation_mode,
        status,
        str(return_code),
        started_at,
        completed_at,
        email_send_allowed,
        email_send_attempted,
        live_before,
        live_send_row_count(),
        "" if status == "complete" else f"{phase_step} returned nonzero status",
    )


def skipped_step(
    run_id: str,
    mode: str,
    step_order: int,
    phase_step: str,
    script: Path,
    invocation_mode: str,
    live_before: int,
    reason: str,
) -> dict[str, str]:
    now = timestamp()
    return log_result(
        run_id,
        mode,
        step_order,
        phase_step,
        script,
        invocation_mode,
        "skipped",
        "",
        now,
        now,
        "no",
        "no",
        live_before,
        live_send_row_count(),
        reason,
    )


def write_status_report(
    run_id: str,
    mode: str,
    results: list[dict[str, str]],
    pipeline_status: str,
    live_before: int,
    live_after: int,
) -> None:
    lines = [
        "# Phase 5R-C3 Pipeline Status Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Run Summary",
        "",
        f"- Run ID: `{run_id}`.",
        f"- Mode: `{mode}`.",
        f"- Pipeline status: `{pipeline_status}`.",
        f"- Live-send rows before: `{live_before}`.",
        f"- Live-send rows after: `{live_after}`.",
        f"- Live-send row delta: `{live_after - live_before}`.",
        "",
        "## Step Status",
        "",
        "| Step | Phase | Invocation | Status | Return Code | Email Attempted | Stop Reason |",
        "| ---: | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in results:
        lines.append(
            f"| {row['step_order']} | {row['phase_step']} | {row['invocation_mode']} | {row['status']} | {row['return_code'] or 'n/a'} | {row['email_send_attempted']} | {row['stop_reason'] or 'none'} |"
        )
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- Manual invocation only; no scheduler or repeated notification mechanism.",
            "- C3 does not read SMTP credentials. The existing C2 sender owns that boundary.",
            "- No broker connection, order placement, archived legacy input, or legacy holding data.",
        ]
    )
    STATUS_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 5R daily research and email pipeline once.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Refresh and compose, then run C2 without sending.")
    mode.add_argument("--no-send", action="store_true", help="Refresh and compose without invoking C2.")
    return parser.parse_args()


def main() -> int:
    if LEGACY_PIPELINE_RETIRED:
        print(
            "legacy_pipeline_retired=true component=phase5r_c3 "
            "children_invoked=false email_attempted=false"
        )
        return 3
    args = parse_args()
    mode = "dry_run" if args.dry_run else "no_send" if args.no_send else "send"
    run_id = make_run_id(mode)
    live_before = live_send_row_count()
    results: list[dict[str, str]] = []
    required_steps = [
        (1, "B2 market refresh", B2_MARKET_REFRESH, "standard"),
        (2, "B2 scoring", B2_SCORING, "standard"),
        (3, "B2 manual tickets", B2_TICKETS, "standard"),
        (4, "C1 brief composition", C1_COMPOSER, "standard"),
    ]

    failure_reason = ""
    failed_index = 0
    for index, phase_step, script, invocation_mode in required_steps:
        row = run_step(run_id, mode, index, phase_step, script, invocation_mode, [], live_before)
        results.append(row)
        if row["status"] != "complete":
            failure_reason = f"stopped after {phase_step} failure"
            failed_index = index
            break

    if failure_reason:
        for index, phase_step, script, invocation_mode in required_steps:
            if index > failed_index:
                results.append(skipped_step(run_id, mode, index, phase_step, script, invocation_mode, live_before, failure_reason))
        results.append(skipped_step(run_id, mode, 5, "C2 delivery", C2_SENDER, "not_started", live_before, failure_reason))
        live_after = live_send_row_count()
        write_status_report(run_id, mode, results, "failed", live_before, live_after)
        print(f"Phase 5R-C3 pipeline failed; report={STATUS_REPORT.relative_to(ROOT)}")
        return 1

    if mode == "no_send":
        results.append(skipped_step(run_id, mode, 5, "C2 delivery", C2_SENDER, "no_send", live_before, "delivery disabled by --no-send"))
    else:
        c2_args = ["--dry-run"] if mode == "dry_run" else []
        results.append(
            run_step(
                run_id,
                mode,
                5,
                "C2 delivery",
                C2_SENDER,
                "dry_run" if mode == "dry_run" else "send",
                c2_args,
                live_before,
                "yes" if mode == "send" else "no",
                "yes" if mode == "send" else "no",
            )
        )

    live_after = live_send_row_count()
    c2_ok = results[-1]["status"] in {"complete", "skipped"}
    send_delta_ok = (mode == "send" and live_after - live_before == 1) or (mode != "send" and live_after == live_before)
    pipeline_status = "complete" if c2_ok and send_delta_ok else "failed"
    if not send_delta_ok:
        results[-1]["status"] = "failed"
        results[-1]["stop_reason"] = "live-send row delta violated selected mode boundary"
    write_status_report(run_id, mode, results, pipeline_status, live_before, live_after)
    print(f"Phase 5R-C3 mode={mode}; status={pipeline_status}; report={STATUS_REPORT.relative_to(ROOT)}")
    return 0 if pipeline_status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
