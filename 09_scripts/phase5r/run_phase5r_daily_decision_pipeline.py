#!/usr/bin/env python3
"""Consume one fully passed daily refresh and optionally send its decision."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta

from phase5r_daily_common import (
    DAILY_PIPELINE_LOCK_PATH,
    DAILY_REFRESH_STATE_PATH,
    ET,
    ROOT,
    ExclusiveFileLock,
    clear_automation_alert,
    cycle_date,
    latest_published_market_session,
    load_active_state,
    load_inhibit,
    log_daily_run,
    now_et,
    read_json,
)
SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"
SENDER_SCRIPT = SCRIPT_DIR / "send_phase5r_daily_email.py"
REFRESH_NOT_READY_EXIT = 75
DELIVERY_STATUS_UNKNOWN_EXIT = 76


def delivery_status_is_unknown(summary: str) -> bool:
    return any(
        marker in summary
        for marker in (
            "email_sent=unknown",
            "existing_delivery_unknown",
            "existing_send_claimed",
        )
    )


def _parse_aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def refresh_readiness() -> tuple[bool, str]:
    """Require today's complete, latest-published-session handoff before delivery."""

    try:
        state = read_json(DAILY_REFRESH_STATE_PATH, {})
    except (OSError, TypeError, ValueError):
        return False, "refresh_state_unavailable"
    if not isinstance(state, dict):
        return False, "refresh_state_invalid"
    if (
        state.get("schema_version") != "phase5r_daily_refresh_state_v1"
        or state.get("outcome") != "passed"
        or state.get("decision_created") is not True
        or state.get("hard_failures")
        or state.get("soft_failures")
    ):
        return False, "daily_refresh_not_fully_passed"
    required_cycle = cycle_date()
    if state.get("cycle_date") != required_cycle:
        return False, "daily_refresh_cycle_not_current"
    current = now_et()
    required_market_session = latest_published_market_session(current).isoformat()
    if state.get("expected_market_session") != required_market_session:
        return False, "daily_refresh_market_session_not_current"
    state_started = _parse_aware_timestamp(state.get("started_at"))
    state_completed = _parse_aware_timestamp(state.get("completed_at"))
    if not state_started or not state_completed or state_completed < state_started:
        return False, "daily_refresh_timestamp_invalid"
    if state_completed > current + timedelta(minutes=5):
        return False, "daily_refresh_timestamp_invalid"
    if state_completed.astimezone(ET).date().isoformat() != required_cycle:
        return False, "daily_refresh_completion_not_current"
    return True, "daily_refresh_ready"


def run_command(arguments: list[str], timeout: int = 360) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            arguments,
            124,
            stdout=f"{partial}\ncommand_timeout_seconds={timeout}",
        )


def safe_check() -> int:
    load_active_state()
    load_inhibit()
    for target in (SENDER_SCRIPT,):
        if not target.exists():
            raise RuntimeError(f"required daily script missing: {target.name}")
    sender = run_command([sys.executable, str(SENDER_SCRIPT), "--check"])
    if sender.returncode != 0:
        raise RuntimeError("daily pipeline protected checks failed")
    print(
        "safe_check_passed=true email_attempted=false email_sent=false "
        "smtp_config_read=false broker_connected=false order_code_created=false"
    )
    return 0


def execute(send: bool) -> int:
    load_active_state()
    inhibit = load_inhibit()
    if send and bool(inhibit.get("active")):
        print(
            "daily_pipeline_blocked=true reason=maintenance_inhibit_active "
            "email_attempted=false"
        )
        return 2
    with ExclusiveFileLock(DAILY_PIPELINE_LOCK_PATH):
        ready, readiness_reason = refresh_readiness()
        if not ready:
            log_daily_run(
                component="daily_pipeline",
                run_mode="scheduled_send" if send else "protected_no_send",
                outcome="waiting",
                reason=readiness_reason,
            )
            print(
                f"daily_pipeline_outcome=waiting reason={readiness_reason} "
                "email_attempted=false"
            )
            return REFRESH_NOT_READY_EXIT
        if not send:
            log_daily_run(
                component="daily_pipeline",
                run_mode="protected_no_send",
                outcome="passed",
                reason="daily_refresh_and_decision_complete",
            )
            print(
                "daily_pipeline_outcome=passed mode=no_send "
                "email_attempted=false email_sent=false"
            )
            return 0
        sender = run_command([sys.executable, str(SENDER_SCRIPT), "--send"], timeout=90)
        sender_summary = " ".join(sender.stdout.strip().split())[-500:]
        delivery_status_unknown = delivery_status_is_unknown(sender_summary)
        pipeline_outcome = (
            "delivery_unknown"
            if delivery_status_unknown
            else "passed"
            if sender.returncode == 0
            else "sender_nonzero"
        )
        log_daily_run(
            component="daily_pipeline",
            run_mode="scheduled_send",
            outcome=pipeline_outcome,
            reason=sender_summary or f"sender_exit_{sender.returncode}",
            email_attempted=(
                "yes"
                if "email_sent=true" in sender_summary
                or "email_sent=unknown" in sender_summary
                else "no"
            ),
            email_sent=(
                "yes"
                if "email_sent=true" in sender_summary
                else "unknown"
                if "email_sent=unknown" in sender_summary
                else "no"
            ),
        )
        print(
            f"daily_pipeline_outcome={pipeline_outcome} "
            f"sender_exit={sender.returncode} {sender_summary}"
        )
        if sender.returncode == 0 and not delivery_status_unknown:
            clear_automation_alert(component="daily_decision")
        return (
            DELIVERY_STATUS_UNKNOWN_EXIT
            if delivery_status_unknown
            else sender.returncode
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scheduled", action="store_true")
    mode.add_argument("--no-send", action="store_true")
    mode.add_argument("--safe-check", action="store_true")
    args = parser.parse_args()
    if args.safe_check:
        return safe_check()
    return execute(send=args.scheduled)


if __name__ == "__main__":
    raise SystemExit(main())
