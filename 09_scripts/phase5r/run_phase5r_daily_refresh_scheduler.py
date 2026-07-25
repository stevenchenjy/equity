#!/usr/bin/env python3
"""Fifteen-minute launchd wrapper for scheduled public-data refresh slots."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime

from phase5r_daily_common import (
    DAILY_REFRESH_STATE_PATH,
    DAILY_SCHEDULER_STATE_PATH,
    ROOT,
    atomic_write_json,
    cycle_date,
    iso_now,
    load_active_state,
    load_inhibit,
    now_et,
    read_json,
)


REFRESH_PIPELINE = ROOT / "09_scripts" / "phase5r" / "run_phase5r_daily_refresh.py"
WEEKDAY_SLOTS = ("08:15", "12:30", "16:15", "17:45")
WEEKEND_SLOTS = ("12:00",)


def due_slots(current: datetime) -> list[str]:
    slots = WEEKEND_SLOTS if current.weekday() >= 5 else WEEKDAY_SLOTS
    current_clock = current.strftime("%H:%M")
    return [slot for slot in slots if slot <= current_clock]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-check", action="store_true")
    args = parser.parse_args()
    active = load_active_state()
    inhibit = load_inhibit()
    if args.safe_check:
        print(
            "safe_check_passed=true component=daily_refresh_scheduler "
            "pipeline_invoked=false email_attempted=false"
        )
        return 0
    if bool(inhibit.get("active")):
        print(
            "scheduler_action=none reason=maintenance_inhibit_active "
            "pipeline_invoked=false"
        )
        return 0
    if cycle_date() < str(active.get("operational_from", "")):
        print(
            "scheduler_action=none reason=before_operational_from "
            "pipeline_invoked=false"
        )
        return 0
    current = now_et()
    due = due_slots(current)
    if not due:
        print("scheduler_action=none reason=no_refresh_slot_due")
        return 0
    state = read_json(
        DAILY_SCHEDULER_STATE_PATH,
        {"schema_version": "phase5r_daily_scheduler_state_v1", "dates": {}},
    )
    date_state = state.setdefault("dates", {}).setdefault(cycle_date(), {})
    completed = set(date_state.get("refresh_slots_completed", []))
    pending = [slot for slot in due if slot not in completed]
    if not pending:
        print("scheduler_action=none reason=refresh_slots_already_completed")
        return 0
    try:
        completed_process = subprocess.run(
            [sys.executable, str(REFRESH_PIPELINE), "--run"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=420,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        completed_process = subprocess.CompletedProcess(
            [sys.executable, str(REFRESH_PIPELINE), "--run"],
            124,
            stdout=f"{partial}\nrefresh_pipeline_timeout_seconds=420",
        )
    date_state["refresh_last_attempt_at"] = iso_now()
    date_state["refresh_last_exit_code"] = completed_process.returncode
    if completed_process.returncode == 0:
        date_state["refresh_slots_completed"] = sorted(completed | set(due))
    state["updated_at"] = iso_now()
    for old_date in sorted(state["dates"])[:-14]:
        del state["dates"][old_date]
    atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
    summary = " ".join(completed_process.stdout.strip().split())[-400:]
    print(
        f"scheduler_action=refresh exit_code={completed_process.returncode} "
        f"covered_slots={','.join(due)} {summary}"
    )
    return completed_process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
