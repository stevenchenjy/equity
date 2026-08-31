#!/usr/bin/env python3
"""Fifteen-minute launchd wrapper for scheduled public-data refresh slots."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime

from phase5r_daily_common import (
    DAILY_SCHEDULER_STATE_PATH,
    ROOT,
    RUNTIME_EXPECTED_CYCLE_DATE_ENV,
    atomic_write_json,
    cycle_date,
    iso_now,
    is_us_market_session_date,
    load_active_state,
    load_inhibit,
    now_et,
    read_json,
)


REFRESH_PIPELINE = ROOT / "09_scripts" / "phase5r" / "run_phase5r_daily_refresh.py"
SEC_EVIDENCE_REFRESH = ROOT / "09_scripts" / "phase5r" / "refresh_phase5r_daily_evidence.py"
MASSIVE_B2_RUNNER = (
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_b2_full_universe_market_data.py"
)
WEEKDAY_SLOTS = ("08:15", "12:30", "16:15", "17:45")
WEEKEND_SLOTS = ("12:00",)
POST_CLOSE_MARKET_SLOT = "17:45"
MARKET_SNAPSHOT_FETCH = "fetch"
MARKET_SNAPSHOT_REUSE = "reuse_validated_snapshot"
# Equivalent no-output presence probe for the externally configured Massive
# credential used by the B2 child. It returns only a fixed exit status and
# never prints, hashes, persists, or sends the credential.
MASSIVE_AUTH_PRESENCE_PROBE_ENV = (
    "PHASE5R_MASSIVE_AUTH_PRESENCE_PROBE_20260820_B2E0"
)
MASSIVE_AUTH_PRESENCE_PRESENT_EXIT = 74
MASSIVE_AUTH_PRESENCE_ABSENT_EXIT = 75
MASSIVE_AUTH_PRESENCE_INTERNAL_ERROR_EXIT = 76
MASSIVE_B2_PROBE_PRESENT_EXIT = 0
MASSIVE_B2_PROBE_ABSENT_EXIT = 2
MASSIVE_B2_PROBE_INTERNAL_ERROR_EXIT = 3
MASSIVE_B2_PROBE_TIMEOUT_SECONDS = 15
# A one-shot, externally initiated SEC-only path.  It uses this already
# approved launchd runtime so the configured User-Agent remains external to
# the repository.  It deliberately does not run B2, the deterministic refresh,
# a model, or email.  The caller must remove this temporary marker after
# observing the child result; no credential value is read or emitted here.
SEC_REFRESH_ONLY_ENV = "PHASE5R_SEC_REFRESH_ONLY_20260811_41C2"
SEC_REFRESH_TIMEOUT_SECONDS = 240
# One-shot completed-close import for repair/validation through the approved
# Keychain-backed launcher. It runs only B2 and cannot invoke a model,
# sender, broker, portfolio action, or order surface.
MARKET_REFRESH_ONLY_ENV = "PHASE5R_MARKET_REFRESH_ONLY_20260831_9A27"
MARKET_REFRESH_TIMEOUT_SECONDS = 480
# The post-close daily refresh can contain the bounded, paced 29-request market
# import. Its parent timeout exceeds that child budget and leaves a finite
# allowance for the existing local refresh steps; cadence remains 17:45 ET.
DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS = 900


def due_slots(current: datetime) -> list[str]:
    slots = WEEKEND_SLOTS if current.weekday() >= 5 else WEEKDAY_SLOTS
    current_clock = current.strftime("%H:%M")
    return [slot for slot in slots if slot <= current_clock]


def market_snapshot_mode(current: datetime, due: list[str]) -> str:
    """Fetch only once after a regular-session close; otherwise reuse locally."""

    if (
        POST_CLOSE_MARKET_SLOT in due
        and is_us_market_session_date(current.date())
    ):
        return MARKET_SNAPSHOT_FETCH
    return MARKET_SNAPSHOT_REUSE


def _massive_auth_presence_probe_exit_code() -> int:
    """Prove the B2 child can construct its client, without provider I/O."""

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(MASSIVE_B2_RUNNER),
                "--massive-auth-presence-probe",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=MASSIVE_B2_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        return MASSIVE_AUTH_PRESENCE_INTERNAL_ERROR_EXIT
    return {
        MASSIVE_B2_PROBE_PRESENT_EXIT: MASSIVE_AUTH_PRESENCE_PRESENT_EXIT,
        MASSIVE_B2_PROBE_ABSENT_EXIT: MASSIVE_AUTH_PRESENCE_ABSENT_EXIT,
        MASSIVE_B2_PROBE_INTERNAL_ERROR_EXIT: MASSIVE_AUTH_PRESENCE_INTERNAL_ERROR_EXIT,
    }.get(completed.returncode, MASSIVE_AUTH_PRESENCE_INTERNAL_ERROR_EXIT)


def _run_sec_refresh_only() -> int:
    """Run the approved official-evidence refresh without other daily steps."""

    try:
        completed = subprocess.run(
            [sys.executable, str(SEC_EVIDENCE_REFRESH)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=SEC_REFRESH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124
    return completed.returncode


def _run_market_refresh_only() -> int:
    """Run one bounded Massive completed-close import and nothing else."""

    try:
        completed = subprocess.run(
            [sys.executable, str(MASSIVE_B2_RUNNER)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=MARKET_REFRESH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124
    return completed.returncode


def _safe_refresh_child_status(returncode: int) -> str:
    if returncode == 0:
        return "completed"
    if returncode == 124:
        return "timed_out"
    return "failed"


def main() -> int:
    # This must run before argument parsing, state reads, locks, writes, or
    # scheduler execution.  It is used only for the externally initiated,
    # no-output launchd authentication-presence check.
    if os.environ.get(MASSIVE_AUTH_PRESENCE_PROBE_ENV) == "1":
        return _massive_auth_presence_probe_exit_code()
    if os.environ.get(SEC_REFRESH_ONLY_ENV) == "1":
        return _run_sec_refresh_only()
    if os.environ.get(MARKET_REFRESH_ONLY_ENV) == "1":
        return _run_market_refresh_only()
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
        required = (REFRESH_PIPELINE, SEC_EVIDENCE_REFRESH, MASSIVE_B2_RUNNER)
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(
                f"required daily refresh component missing: {','.join(missing)}"
            )
        print(
            "safe_check_passed=true component=daily_refresh_scheduler "
            "pipeline_invoked=false model_invoked=false email_attempted=false"
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
    snapshot_mode = market_snapshot_mode(current, pending)
    refresh_started_at = iso_now()
    if snapshot_mode == MARKET_SNAPSHOT_FETCH:
        # Reserve the one post-close source attempt before starting the child.
        # If this process or a later deterministic step fails, a future 15-minute
        # tick may still run local reuse work but cannot repeat the Massive call.
        date_state["post_close_market_attempt_reserved_at"] = refresh_started_at
        date_state["post_close_market_attempt_status"] = "reserved_before_child"
        completed.add(POST_CLOSE_MARKET_SLOT)
        date_state["refresh_slots_completed"] = sorted(completed)
        state["updated_at"] = refresh_started_at
        atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
    try:
        completed_process = subprocess.run(
            [
                sys.executable,
                str(REFRESH_PIPELINE),
                "--run",
                "--market-snapshot-mode",
                snapshot_mode,
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        completed_process = subprocess.CompletedProcess(
            [
                sys.executable,
                str(REFRESH_PIPELINE),
                "--run",
                "--market-snapshot-mode",
                snapshot_mode,
            ],
            124,
        )
    date_state["refresh_last_attempt_at"] = iso_now()
    date_state["refresh_last_exit_code"] = completed_process.returncode
    date_state["market_snapshot_mode"] = snapshot_mode
    if snapshot_mode == MARKET_SNAPSHOT_FETCH:
        date_state["post_close_market_attempt_status"] = "child_returned"
        date_state["post_close_market_attempt_exit_code"] = (
            completed_process.returncode
        )
    if completed_process.returncode == 0:
        date_state["refresh_slots_completed"] = sorted(completed | set(due))
    state["updated_at"] = iso_now()
    for old_date in sorted(state["dates"])[:-14]:
        del state["dates"][old_date]
    atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
    print(
        f"scheduler_action=refresh exit_code={completed_process.returncode} "
        f"refresh_status={_safe_refresh_child_status(completed_process.returncode)} "
        f"market_snapshot_mode={snapshot_mode} "
        f"covered_slots={','.join(due)} model_path=removed "
        "email_attempted=false"
    )
    return completed_process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
