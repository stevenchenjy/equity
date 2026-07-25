#!/usr/bin/env python3
"""Fifteen-minute launchd wrapper for one ET daily decision attempt."""

from __future__ import annotations

import argparse
import subprocess
import sys

from phase5r_daily_common import (
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


DECISION_PIPELINE = (
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_daily_decision_pipeline.py"
)
DECISION_TIME = "18:30"
MAX_AUTOMATIC_ATTEMPTS = 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-check", action="store_true")
    args = parser.parse_args()
    active = load_active_state()
    inhibit = load_inhibit()
    if args.safe_check:
        print(
            "safe_check_passed=true component=daily_decision_scheduler "
            "pipeline_invoked=false sender_invoked=false"
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
    if now_et().strftime("%H:%M") < DECISION_TIME:
        print("scheduler_action=none reason=before_daily_decision_time")
        return 0

    state = read_json(
        DAILY_SCHEDULER_STATE_PATH,
        {"schema_version": "phase5r_daily_scheduler_state_v1", "dates": {}},
    )
    date_state = state.setdefault("dates", {}).setdefault(cycle_date(), {})
    if date_state.get("decision_completed") is True:
        print("scheduler_action=none reason=daily_decision_already_completed")
        return 0
    attempts = int(date_state.get("decision_attempts", 0) or 0)
    if attempts >= MAX_AUTOMATIC_ATTEMPTS:
        print("scheduler_action=none reason=automatic_attempt_limit_reached")
        return 0

    try:
        completed_process = subprocess.run(
            [sys.executable, str(DECISION_PIPELINE), "--scheduled"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=520,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        completed_process = subprocess.CompletedProcess(
            [sys.executable, str(DECISION_PIPELINE), "--scheduled"],
            124,
            stdout=f"{partial}\ndecision_pipeline_timeout_seconds=520",
        )
    attempts += 1
    date_state["decision_attempts"] = attempts
    date_state["decision_last_attempt_at"] = iso_now()
    date_state["decision_last_exit_code"] = completed_process.returncode
    if completed_process.returncode == 0:
        date_state["decision_completed"] = True
        date_state["decision_completed_at"] = iso_now()
    state["updated_at"] = iso_now()
    for old_date in sorted(state["dates"])[:-14]:
        del state["dates"][old_date]
    atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
    summary = " ".join(completed_process.stdout.strip().split())[-500:]
    print(
        f"scheduler_action=daily_decision exit_code={completed_process.returncode} "
        f"attempt={attempts} {summary}"
    )
    return completed_process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
