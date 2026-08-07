#!/usr/bin/env python3
"""Fifteen-minute launchd wrapper for scheduled public-data refresh slots."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
import re

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
PRODUCTION_SHADOW_RUNNER = (
    ROOT / "09_scripts" / "phase5r" / "run_phase5r_production_shadow.py"
)
PRODUCTION_SHADOW_EMAIL_RUNNER = (
    ROOT / "09_scripts" / "phase5r" / "send_phase5r_production_shadow_email.py"
)
WEEKDAY_SLOTS = ("08:15", "12:30", "16:15", "17:45")
WEEKEND_SLOTS = ("12:00",)
_SAFE_SHADOW_OUTCOMES = frozenset(
    {"blocked", "completed", "completed_with_material_citation_issue", "terminal_failure"}
)
_SAFE_EMAIL_OUTCOMES = frozenset(
    {"blocked", "deduplicated", "sent", "delivery_unknown"}
)
_MAX_SHADOW_RESULT_BYTES = 16 * 1024
_RUN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}")
# This process-local sentinel is deliberately not a command-line argument or
# plist setting.  A tightly scoped launchd test can set it in the existing
# user-domain environment, kickstart this exact job, and infer only the fixed
# exit status.  No result is printed, persisted, hashed, or logged.
AUTH_PRESENCE_PROBE_ENV = "PHASE5R_AUTH_PRESENCE_PROBE_20260804_5F17"
# Deliberately distinct from normal scheduler success (0), so the external
# launcher can distinguish an actual probe result from a prior job status.
AUTH_PRESENCE_PRESENT_EXIT = 71
AUTH_PRESENCE_ABSENT_EXIT = 72
AUTH_PRESENCE_INTERNAL_ERROR_EXIT = 73


def due_slots(current: datetime) -> list[str]:
    slots = WEEKEND_SLOTS if current.weekday() >= 5 else WEEKDAY_SLOTS
    current_clock = current.strftime("%H:%M")
    return [slot for slot in slots if slot <= current_clock]


def _safe_json_child_outcome(
    process: subprocess.CompletedProcess[str] | None, *, allowed_outcomes: frozenset[str]
) -> tuple[str, dict[str, object] | None]:
    """Accept only a small, parsed child result and never log raw output."""

    if process is None:
        return "not_started_refresh_nonzero", None
    raw = process.stdout
    if not isinstance(raw, str) or len(raw.encode("utf-8", errors="ignore")) > _MAX_SHADOW_RESULT_BYTES:
        return "unparseable_or_oversize_child_result", None
    try:
        result = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return "unparseable_or_oversize_child_result", None
    outcome = result.get("outcome") if isinstance(result, dict) else None
    if outcome not in allowed_outcomes:
        return "unparseable_or_oversize_child_result", None
    return f"outcome={outcome}", result


def _safe_shadow_child_result(
    process: subprocess.CompletedProcess[str] | None,
) -> tuple[str, str | None]:
    status, result = _safe_json_child_outcome(
        process, allowed_outcomes=_SAFE_SHADOW_OUTCOMES
    )
    if result is None:
        return status, None
    run_id = result.get("run_id")
    if result.get("outcome") == "completed":
        if not isinstance(run_id, str) or _RUN_ID_PATTERN.fullmatch(run_id) is None:
            return "unparseable_or_oversize_child_result", None
        return status, run_id
    return status, None


def _safe_shadow_child_status(process: subprocess.CompletedProcess[str] | None) -> str:
    """Compatibility wrapper used by safety tests and launchd summaries."""

    return _safe_shadow_child_result(process)[0]


def _safe_email_child_status(process: subprocess.CompletedProcess[str] | None) -> str:
    status, _ = _safe_json_child_outcome(
        process, allowed_outcomes=_SAFE_EMAIL_OUTCOMES
    )
    return status


def _auth_presence_probe_exit_code() -> int:
    """Return only a fixed presence result; never materialize the credential."""

    try:
        return (
            AUTH_PRESENCE_PRESENT_EXIT
            if bool(os.environ.get("OPENAI_API_KEY"))
            else AUTH_PRESENCE_ABSENT_EXIT
        )
    except Exception:
        # A probe must remain mute and fail closed even for an unusual runtime
        # environment implementation.
        return AUTH_PRESENCE_INTERNAL_ERROR_EXIT


def _safe_refresh_child_status(returncode: int) -> str:
    if returncode == 0:
        return "completed"
    if returncode == 124:
        return "timed_out"
    return "failed"


def _parse_aware_timestamp(value: object) -> datetime | None:
    """Parse a scheduler-state timestamp without accepting a naive value."""

    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _refresh_state_allows_shadow(
    *, refresh_returncode: int, refresh_started_at: str
) -> str:
    """Require a current, fully passed deterministic refresh before shadow.

    ``run_phase5r_daily_refresh.py`` deliberately returns zero when it created
    a deterministic decision, including a degraded data-gate hold.  That is
    useful to the historical decision workflow, but it is not enough authority
    to start a provider-backed shadow.  Read the just-written bounded refresh
    receipt and allow the companion only after its explicit full-pass outcome.
    """

    if refresh_returncode != 0:
        return "not_started_refresh_nonzero"
    expected_start = _parse_aware_timestamp(refresh_started_at)
    if expected_start is None:
        return "not_started_refresh_state_invalid"
    state = read_json(DAILY_REFRESH_STATE_PATH, {})
    if not isinstance(state, dict):
        return "not_started_refresh_state_invalid"
    if state.get("schema_version") != "phase5r_daily_refresh_state_v1":
        return "not_started_refresh_state_invalid"
    if state.get("outcome") != "passed":
        return "not_started_refresh_state_not_passed"
    if state.get("decision_created") is not True:
        return "not_started_refresh_state_not_passed"
    if state.get("hard_failures") or state.get("soft_failures"):
        return "not_started_refresh_state_not_passed"
    state_started = _parse_aware_timestamp(state.get("started_at"))
    state_completed = _parse_aware_timestamp(state.get("completed_at"))
    if (
        state_started is None
        or state_completed is None
        or state_started < expected_start
        or state_completed < state_started
    ):
        # A zero exit code must never authorize shadow from a stale or malformed
        # receipt left by an earlier refresh invocation.
        return "not_started_refresh_state_stale_or_invalid"
    return "passed"


def main() -> int:
    # This must run before argument parsing, state reads, locks, writes, or
    # scheduler execution.  It is used only for the externally initiated,
    # no-output launchd authentication-presence check.
    if os.environ.get(AUTH_PRESENCE_PROBE_ENV) == "1":
        return _auth_presence_probe_exit_code()
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-check", action="store_true")
    args = parser.parse_args()
    active = load_active_state()
    inhibit = load_inhibit()
    if args.safe_check:
        if not PRODUCTION_SHADOW_RUNNER.is_file():
            raise RuntimeError("production shadow runner is missing")
        if not PRODUCTION_SHADOW_EMAIL_RUNNER.is_file():
            raise RuntimeError("production shadow email runner is missing")
        print(
            "safe_check_passed=true component=daily_refresh_scheduler "
            "pipeline_invoked=false production_shadow_invoked=false email_attempted=false"
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
    refresh_started_at = iso_now()
    try:
        completed_process = subprocess.run(
            [sys.executable, str(REFRESH_PIPELINE), "--run"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=420,
            check=False,
        )
    except subprocess.TimeoutExpired:
        completed_process = subprocess.CompletedProcess(
            [sys.executable, str(REFRESH_PIPELINE), "--run"],
            124,
        )
    shadow_process: subprocess.CompletedProcess[str] | None = None
    email_process: subprocess.CompletedProcess[str] | None = None
    refresh_gate = _refresh_state_allows_shadow(
        refresh_returncode=completed_process.returncode,
        refresh_started_at=refresh_started_at,
    )
    if refresh_gate == "passed":
        # This is a post-refresh, separately bounded companion.  It never
        # changes the deterministic refresh result and owns its own daily lock,
        # freshness gate, no-retry policy, and cost ledger.
        try:
            shadow_process = subprocess.run(
                [sys.executable, str(PRODUCTION_SHADOW_RUNNER), "--run"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=360,
                check=False,
            )
        except subprocess.TimeoutExpired:
            shadow_process = subprocess.CompletedProcess(
                [sys.executable, str(PRODUCTION_SHADOW_RUNNER), "--run"],
                124,
                stdout="",
            )
        shadow_status, completed_run_id = _safe_shadow_child_result(shadow_process)
        # The email companion is deliberately separate from both the normal
        # daily sender and the provider runner.  It is eligible only for a
        # fully accepted shadow result and owns its own durable send receipt.
        if completed_run_id is not None:
            try:
                email_process = subprocess.run(
                    [
                        sys.executable,
                        str(PRODUCTION_SHADOW_EMAIL_RUNNER),
                        "--send-run-id",
                        completed_run_id,
                    ],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=90,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                email_process = subprocess.CompletedProcess(
                    [sys.executable, str(PRODUCTION_SHADOW_EMAIL_RUNNER)],
                    124,
                    stdout="",
                )
    else:
        shadow_status = refresh_gate
    date_state["refresh_last_attempt_at"] = iso_now()
    date_state["refresh_last_exit_code"] = completed_process.returncode
    date_state["refresh_last_shadow_gate"] = refresh_gate
    if shadow_process is not None:
        date_state["production_shadow_last_attempt_at"] = iso_now()
        date_state["production_shadow_last_exit_code"] = shadow_process.returncode
    if completed_process.returncode == 0:
        date_state["refresh_slots_completed"] = sorted(completed | set(due))
    state["updated_at"] = iso_now()
    for old_date in sorted(state["dates"])[:-14]:
        del state["dates"][old_date]
    atomic_write_json(DAILY_SCHEDULER_STATE_PATH, state)
    shadow_summary = shadow_status
    email_summary = _safe_email_child_status(email_process)
    print(
        f"scheduler_action=refresh exit_code={completed_process.returncode} "
        f"refresh_status={_safe_refresh_child_status(completed_process.returncode)} "
        f"refresh_gate={refresh_gate} "
        f"covered_slots={','.join(due)} shadow_exit="
        f"{shadow_process.returncode if shadow_process is not None else 'not_started'} "
        f"email_exit={email_process.returncode if email_process is not None else 'not_started'} "
        f"{shadow_summary} email_{email_summary}"
    )
    return completed_process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
