#!/usr/bin/env python3
"""Fifteen-minute launchd wrapper for one ET daily decision attempt."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from phase5r_active_config import load_active_config
from phase5r_daily_common import (
    DAILY_SCHEDULER_STATE_PATH,
    ROOT,
    RUNTIME_EXPECTED_CYCLE_DATE_ENV,
    atomic_write_json,
    clear_automation_alert,
    cycle_date,
    iso_now,
    load_active_state,
    load_inhibit,
    now_et,
    publish_automation_alert,
    read_json,
)
from run_phase5r_daily_decision_pipeline import (
    REFRESH_NOT_READY_EXIT,
    delivery_status_is_unknown,
)


DECISION_PIPELINE = (
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_daily_decision_pipeline.py"
)
DECISION_TIME = "18:30"
DECISION_TERMINAL_TIME = "20:00"
MAX_AUTOMATIC_ATTEMPTS = 2


def main() -> int:
    expected_cycle_date = os.environ.get(RUNTIME_EXPECTED_CYCLE_DATE_ENV)
    if expected_cycle_date and cycle_date() != expected_cycle_date:
        print(
            "scheduler_action=none reason=runtime_invocation_cycle_date_changed "
            "pipeline_invoked=false"
        )
        return 70
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-check", action="store_true")
    args = parser.parse_args()
    active = load_active_state()
    inhibit = load_inhibit()
    if args.safe_check:
        notifications = load_active_config()["notifications"]
        if (
            notifications["send_after_et"] != DECISION_TIME
            or notifications["terminal_alert_after_et"]
            != DECISION_TERMINAL_TIME
        ):
            raise RuntimeError("daily decision cadence configuration drift")
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
    if date_state.get("decision_terminal_failure") is True:
        print("scheduler_action=none reason=daily_decision_terminal_failure")
        return 0
    attempts = int(date_state.get("decision_attempts", 0) or 0)
    if attempts >= MAX_AUTOMATIC_ATTEMPTS:
        date_state["decision_terminal_failure"] = True
        date_state["decision_terminal_reason"] = (
            "scheduled_email_attempts_exhausted"
        )
        state["updated_at"] = iso_now()
        atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
        publish_automation_alert(
            component="daily_decision",
            reason="scheduled_email_attempts_exhausted",
        )
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
    summary = " ".join(completed_process.stdout.strip().split())[-500:]
    if completed_process.returncode == REFRESH_NOT_READY_EXIT:
        waits = int(date_state.get("decision_refresh_waits", 0) or 0) + 1
        date_state["decision_refresh_waits"] = waits
        date_state["decision_last_wait_at"] = iso_now()
        date_state["decision_last_wait_reason"] = summary
        if now_et().strftime("%H:%M") >= DECISION_TERMINAL_TIME:
            date_state["decision_terminal_failure"] = True
            date_state["decision_terminal_reason"] = (
                "daily_decision_refresh_deadline_exhausted"
            )
            publish_automation_alert(
                component="daily_decision",
                reason="daily_decision_refresh_deadline_exhausted",
            )
        state["updated_at"] = iso_now()
        for old_date in sorted(state["dates"])[:-14]:
            del state["dates"][old_date]
        atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
        print(
            "scheduler_action=waiting_for_refresh "
            f"wait={waits} terminal={str(date_state.get('decision_terminal_failure') is True).lower()} "
            f"{summary}"
        )
        return 0

    attempts += 1
    date_state["decision_attempts"] = attempts
    date_state["decision_last_attempt_at"] = iso_now()
    date_state["decision_last_exit_code"] = completed_process.returncode
    delivery_status_unknown = delivery_status_is_unknown(summary)
    if delivery_status_unknown:
        date_state["decision_terminal_failure"] = True
        date_state["decision_terminal_reason"] = "delivery_status_unknown"
        publish_automation_alert(
            component="daily_decision",
            reason="delivery_status_unknown",
        )
    elif completed_process.returncode == 0:
        date_state["decision_completed"] = True
        date_state["decision_completed_at"] = iso_now()
        clear_automation_alert(component="daily_decision")
    elif attempts >= MAX_AUTOMATIC_ATTEMPTS:
        date_state["decision_terminal_failure"] = True
        date_state["decision_terminal_reason"] = (
            "scheduled_email_attempts_exhausted"
        )
        publish_automation_alert(
            component="daily_decision",
            reason="scheduled_email_attempts_exhausted",
        )
    state["updated_at"] = iso_now()
    for old_date in sorted(state["dates"])[:-14]:
        del state["dates"][old_date]
    atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
    print(
        f"scheduler_action=daily_decision exit_code={completed_process.returncode} "
        f"attempt={attempts} {summary}"
    )
    return completed_process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
