#!/usr/bin/env python3
"""Fifteen-minute launchd wrapper for scheduled public-data refresh slots."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime

from phase5r_active_config import load_active_config
from phase5r_daily_common import (
    BASIC_EOD_PUBLICATION_TIME_ET,
    DAILY_REFRESH_STATE_PATH,
    DAILY_SCHEDULER_STATE_PATH,
    ROOT,
    RUNTIME_EXPECTED_CYCLE_DATE_ENV,
    atomic_write_json,
    cycle_date,
    iso_now,
    latest_published_market_session,
    load_active_state,
    load_inhibit,
    now_et,
    publish_automation_alert,
    read_json,
)


REFRESH_PIPELINE = ROOT / "09_scripts" / "phase5r" / "run_phase5r_daily_refresh.py"
SEC_EVIDENCE_REFRESH = ROOT / "09_scripts" / "phase5r" / "refresh_phase5r_daily_evidence.py"
MASSIVE_B2_RUNNER = (
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_b2_full_universe_market_data.py"
)
EOD_PUBLICATION_RETRY_SLOTS = ("11:15", "11:45", "12:15", "12:45")
WEEKDAY_SLOTS = ("08:15", *EOD_PUBLICATION_RETRY_SLOTS)
WEEKEND_SLOTS = EOD_PUBLICATION_RETRY_SLOTS
FIRST_EOD_PUBLICATION_RETRY_SLOT = EOD_PUBLICATION_RETRY_SLOTS[0]
LAST_EOD_PUBLICATION_RETRY_SLOT = EOD_PUBLICATION_RETRY_SLOTS[-1]
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
# One-shot latest-published-close import for repair/validation through the
# approved Keychain-backed launcher. It runs only B2 and cannot invoke a
# model, sender, broker, portfolio action, or order surface.
MARKET_REFRESH_ONLY_ENV = "PHASE5R_MARKET_REFRESH_ONLY_20260831_9A27"
MARKET_REFRESH_TIMEOUT_SECONDS = 480
# One-shot complete deterministic refresh using the already validated local
# close. This repair/verification entrypoint runs through the credentialed
# dailyrefresh launcher but cannot invoke a model, sender, broker, or order.
FULL_REFRESH_REUSE_ONLY_ENV = (
    "PHASE5R_FULL_REFRESH_REUSE_ONLY_20260901_7C31"
)
# The publication-window refresh can contain the bounded, paced 29-request
# market import. Its parent timeout exceeds that child budget and leaves a
# finite allowance for the existing local refresh steps. Retry slots are
# separate launchd cycles and stop as soon as a full current refresh passes.
DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS = 900


def due_slots(current: datetime) -> list[str]:
    slots = WEEKEND_SLOTS if current.weekday() >= 5 else WEEKDAY_SLOTS
    current_clock = current.strftime("%H:%M")
    return [slot for slot in slots if slot <= current_clock]


def market_snapshot_mode(
    current: datetime,
    due: list[str],
    *,
    market_ready: bool = False,
) -> str:
    """Fetch at bounded publication slots until the latest EOD close is ready."""

    if (
        not market_ready
        and any(slot in due for slot in EOD_PUBLICATION_RETRY_SLOTS)
    ):
        return MARKET_SNAPSHOT_FETCH
    return MARKET_SNAPSHOT_REUSE


def _refresh_state_matches_attempt(
    refresh_state: object,
    *,
    expected_cycle_date: str,
    expected_market_session: str,
    not_before: str,
) -> bool:
    if not isinstance(refresh_state, dict):
        return False
    if (
        refresh_state.get("cycle_date") != expected_cycle_date
        or refresh_state.get("expected_market_session")
        != expected_market_session
    ):
        return False
    try:
        state_started = datetime.fromisoformat(
            str(refresh_state.get("started_at", "")).replace("Z", "+00:00")
        )
        attempt_started = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
    except ValueError:
        return False
    if (
        state_started.tzinfo is None
        or attempt_started.tzinfo is None
        or state_started < attempt_started
    ):
        return False
    return True


def _market_step_passed(
    refresh_state: object,
    *,
    expected_cycle_date: str,
    expected_market_session: str,
    not_before: str,
) -> bool:
    if not _refresh_state_matches_attempt(
        refresh_state,
        expected_cycle_date=expected_cycle_date,
        expected_market_session=expected_market_session,
        not_before=not_before,
    ):
        return False
    assert isinstance(refresh_state, dict)
    steps = refresh_state.get("steps")
    if not isinstance(steps, list):
        return False
    return any(
        isinstance(row, dict)
        and row.get("name") == "market_refresh"
        and row.get("exit_code") == 0
        for row in steps
    )


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


def _run_full_refresh_reuse_only() -> int:
    """Run one full no-send refresh against the validated local close."""

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(REFRESH_PIPELINE),
                "--run",
                "--market-snapshot-mode",
                MARKET_SNAPSHOT_REUSE,
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS,
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
    if os.environ.get(FULL_REFRESH_REUSE_ONLY_ENV) == "1":
        return _run_full_refresh_reuse_only()
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
        configured_slots = tuple(
            notifications["eod_publication_retry_slots_et"]
        )
        if (
            configured_slots != EOD_PUBLICATION_RETRY_SLOTS
            or notifications["market_data_publication_after_et"]
            != BASIC_EOD_PUBLICATION_TIME_ET
        ):
            raise RuntimeError("EOD publication refresh cadence configuration drift")
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
    required_market_session = latest_published_market_session(current).isoformat()
    market_ready = bool(
        date_state.get("eod_publication_market_ready")
        and date_state.get("eod_publication_market_session")
        == required_market_session
    )
    snapshot_mode = market_snapshot_mode(
        current,
        pending,
        market_ready=market_ready,
    )
    refresh_started_at = iso_now()
    # Reserve every currently due slot before the child. A failed child waits
    # for the next configured slot instead of running every 15 minutes, while
    # the later publication slots provide bounded recovery opportunities.
    completed.update(pending)
    date_state["refresh_slots_completed"] = sorted(completed)
    market_attempt: dict[str, object] | None = None
    if snapshot_mode == MARKET_SNAPSHOT_FETCH:
        attempt_slots = [
            slot for slot in pending if slot in EOD_PUBLICATION_RETRY_SLOTS
        ]
        if not attempt_slots:
            raise RuntimeError("EOD market fetch has no publication retry slot")
        market_attempt = {
            "slot": max(attempt_slots),
            "reserved_at": refresh_started_at,
            "status": "reserved_before_child",
        }
        attempts = date_state.setdefault("eod_publication_market_attempts", [])
        if not isinstance(attempts, list):
            raise RuntimeError("EOD publication market attempt state is invalid")
        attempts.append(market_attempt)
        date_state["eod_publication_market_attempt_reserved_at"] = refresh_started_at
        date_state["eod_publication_market_attempt_status"] = "reserved_before_child"
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
    refresh_state = read_json(DAILY_REFRESH_STATE_PATH, {})
    market_passed = _market_step_passed(
        refresh_state,
        expected_cycle_date=cycle_date(),
        expected_market_session=required_market_session,
        not_before=refresh_started_at,
    )
    if market_passed:
        date_state["eod_publication_market_ready"] = True
        date_state["eod_publication_market_session"] = refresh_state.get(
            "expected_market_session", ""
        )
    if snapshot_mode == MARKET_SNAPSHOT_FETCH:
        date_state["eod_publication_market_attempt_status"] = "child_returned"
        date_state["eod_publication_market_attempt_exit_code"] = (
            completed_process.returncode
        )
        if market_attempt is not None:
            market_attempt.update(
                {
                    "completed_at": iso_now(),
                    "status": "market_ready" if market_passed else "market_not_ready",
                    "pipeline_exit_code": completed_process.returncode,
                }
            )
    refresh_fully_passed = bool(
        completed_process.returncode == 0
        and _refresh_state_matches_attempt(
            refresh_state,
            expected_cycle_date=cycle_date(),
            expected_market_session=required_market_session,
            not_before=refresh_started_at,
        )
        and isinstance(refresh_state, dict)
        and refresh_state.get("outcome") == "passed"
    )
    date_state["refresh_fully_passed"] = refresh_fully_passed
    if refresh_fully_passed:
        date_state["refresh_last_passed_at"] = iso_now()
        if any(slot in due for slot in EOD_PUBLICATION_RETRY_SLOTS):
            # No later retry is useful once the latest published close and all
            # deterministic evidence gates have passed.
            completed.update(EOD_PUBLICATION_RETRY_SLOTS)
    date_state["refresh_slots_completed"] = sorted(completed)
    if (
        not refresh_fully_passed
        and LAST_EOD_PUBLICATION_RETRY_SLOT in pending
    ):
        publish_automation_alert(
            component="daily_refresh",
            reason="daily_refresh_publication_window_exhausted",
        )
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
