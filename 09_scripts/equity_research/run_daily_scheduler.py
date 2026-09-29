#!/usr/bin/env python3
"""Fifteen-minute launchd wrapper for bounded owner-attention delivery windows."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from active_config import load_active_config
from delivery_schedule import active_delivery_window, configured_delivery_windows
from daily_common import (
    DAILY_SCHEDULER_STATE_PATH, ROOT, RUNTIME_EXPECTED_CYCLE_DATE_ENV,
    atomic_write_json, clear_automation_alert, cycle_date, iso_now,
    is_us_market_session_date, load_active_state, load_inhibit, now_et,
    publish_automation_alert, read_json,
)
from run_daily_decision_pipeline import (
    REFRESH_NOT_READY_EXIT, delivery_status_is_unknown, refresh_readiness,
)

DECISION_PIPELINE = ROOT / "09_scripts" / "equity_research" / "run_daily_decision_pipeline.py"
DECISION_TIME = "09:30"
DECISION_TERMINAL_TIME = "15:05"
MAX_AUTOMATIC_ATTEMPTS = 2


def _save_state(state: dict) -> None:
    state["updated_at"] = iso_now()
    atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)


def main() -> int:
    expected_cycle_date = os.environ.get(RUNTIME_EXPECTED_CYCLE_DATE_ENV)
    if expected_cycle_date and cycle_date() != expected_cycle_date:
        print("scheduler_action=none reason=runtime_invocation_cycle_date_changed pipeline_invoked=false")
        return 70
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-check", action="store_true")
    args = parser.parse_args()
    active = load_active_state()
    inhibit = load_inhibit()
    notifications = load_active_config()["notifications"]
    windows = configured_delivery_windows(notifications)
    if args.safe_check:
        if (notifications["send_after_et"] != windows[0]["start"]
                or notifications["terminal_alert_after_et"] != windows[-1]["end"]):
            raise RuntimeError("daily decision cadence configuration drift")
        print("safe_check_passed=true component=daily_decision_scheduler pipeline_invoked=false sender_invoked=false")
        return 0
    if bool(inhibit.get("active")):
        print("scheduler_action=none reason=maintenance_inhibit_active pipeline_invoked=false")
        return 0
    if cycle_date() < str(active.get("operational_from", "")):
        print("scheduler_action=none reason=before_operational_from pipeline_invoked=false")
        return 0
    current = now_et()
    if not is_us_market_session_date(current.date()):
        print("scheduler_action=none reason=non_market_session pipeline_invoked=false")
        return 0
    if current.strftime("%H:%M") < windows[0]["start"]:
        print("scheduler_action=none reason=before_daily_decision_time")
        return 0
    state = read_json(DAILY_SCHEDULER_STATE_PATH,
                      {"schema_version": "phase5r_daily_scheduler_state_v1", "dates": {}})
    date_state = state.setdefault("dates", {}).setdefault(cycle_date(), {})
    if date_state.get("decision_completed") is True and "delivery_windows" not in date_state:
        print("scheduler_action=none reason=legacy_daily_decision_already_completed pipeline_invoked=false")
        return 0
    slots = date_state.setdefault("delivery_windows", {})
    # A new purpose/window must never bypass an ambiguous SMTP result. Preserve
    # historical day-wide terminal fields; no private state migration occurs.
    if (date_state.get("decision_terminal_reason") == "delivery_status_unknown"
            or any(row.get("decision_terminal_reason") == "delivery_status_unknown" for row in slots.values())):
        print("scheduler_action=none reason=delivery_status_unknown pipeline_invoked=false")
        return 0
    changed = False
    for candidate in windows:
        if current.strftime("%H:%M") <= candidate["end"]:
            continue
        previous = slots.setdefault(candidate["id"], {})
        if previous.get("decision_completed") or previous.get("decision_terminal_failure"):
            continue
        if previous.get("decision_successful_checks", 0) and previous.get("decision_last_check_exit_code") == 0:
            previous.update(decision_completed=True, decision_completed_at=iso_now(),
                            decision_window_closed_reason="closed_no_material_change")
        else:
            reason = ("daily_decision_refresh_deadline_exhausted" if previous.get("decision_refresh_waits")
                      else "daily_decision_delivery_window_missed")
            previous.update(decision_terminal_failure=True, decision_terminal_reason=reason,
                            decision_window_closed_at=iso_now())
            publish_automation_alert(component="daily_decision", reason=reason + ":" + candidate["id"])
        changed = True
    if changed:
        _save_state(state)
    window = active_delivery_window(notifications, current)
    if window is None:
        print("scheduler_action=none reason=outside_delivery_window pipeline_invoked=false")
        return 0
    slot = window["id"]
    slot_state = slots.setdefault(slot, {})
    if slot_state.get("decision_completed") is True:
        print(f"scheduler_action=none reason=delivery_window_already_completed delivery_window={slot}")
        return 0
    if slot_state.get("decision_terminal_failure") is True:
        print(f"scheduler_action=none reason=delivery_window_terminal_failure delivery_window={slot}")
        return 0
    attempts = int(slot_state.get("decision_attempts", 0) or 0)
    if attempts >= MAX_AUTOMATIC_ATTEMPTS:
        slot_state.update(decision_terminal_failure=True, decision_terminal_reason="scheduled_email_attempts_exhausted")
        _save_state(state)
        publish_automation_alert(component="daily_decision", reason="scheduled_email_attempts_exhausted:" + slot)
        print(f"scheduler_action=none reason=automatic_attempt_limit_reached delivery_window={slot}")
        return 0
    arguments = [sys.executable, str(DECISION_PIPELINE), "--scheduled", "--delivery-window", slot]
    try:
        completed_process = subprocess.run(arguments, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, timeout=520, check=False)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        completed_process = subprocess.CompletedProcess(arguments, 124,
            stdout=f"{partial}\ndecision_pipeline_timeout_seconds=520")
    summary = " ".join(completed_process.stdout.strip().split())[-500:]
    slot_state.update(decision_checks=int(slot_state.get("decision_checks", 0) or 0) + 1,
                      decision_last_check_at=iso_now(), decision_last_check_exit_code=completed_process.returncode,
                      decision_last_check_reason=summary)
    if completed_process.returncode == REFRESH_NOT_READY_EXIT:
        waits = int(slot_state.get("decision_refresh_waits", 0) or 0) + 1
        slot_state.update(decision_refresh_waits=waits, decision_last_wait_at=iso_now(),
                          decision_last_wait_reason=summary)
        _save_state(state)
        print(f"scheduler_action=waiting_for_refresh delivery_window={slot} wait={waits} {summary}")
        return 0
    unknown = delivery_status_is_unknown(summary)
    terminal_receipt = "email_sent=true" in summary or "reason=existing_sent" in summary.split()
    quiet = completed_process.returncode == 0 and "email_sent=false" in summary and not terminal_receipt and not unknown
    if quiet:
        # Research can finish after the first wake. Recheck through this window
        # without charging SMTP attempts or acknowledging unsent new research.
        slot_state["decision_successful_checks"] = int(slot_state.get("decision_successful_checks", 0) or 0) + 1
        _save_state(state)
        clear_automation_alert(component="daily_decision")
        print(f"scheduler_action=quiet_check delivery_window={slot} smtp_attempts={attempts} {summary}")
        return 0
    attempts += 1
    slot_state.update(decision_attempts=attempts, decision_last_attempt_at=iso_now(),
                      decision_last_exit_code=completed_process.returncode)
    if unknown:
        slot_state.update(decision_terminal_failure=True, decision_terminal_reason="delivery_status_unknown")
        publish_automation_alert(component="daily_decision", reason="delivery_status_unknown")
    elif completed_process.returncode == 0 and terminal_receipt:
        slot_state.update(decision_completed=True, decision_completed_at=iso_now())
        clear_automation_alert(component="daily_decision")
    elif attempts >= MAX_AUTOMATIC_ATTEMPTS:
        slot_state.update(decision_terminal_failure=True, decision_terminal_reason="scheduled_email_attempts_exhausted")
        publish_automation_alert(component="daily_decision", reason="scheduled_email_attempts_exhausted:" + slot)
    _save_state(state)
    print(f"scheduler_action=daily_decision delivery_window={slot} exit_code={completed_process.returncode} attempt={attempts} {summary}")
    return completed_process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
