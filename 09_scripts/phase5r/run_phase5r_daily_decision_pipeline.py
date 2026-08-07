#!/usr/bin/env python3
"""Run the final daily refresh and optionally perform one guarded send."""

from __future__ import annotations

import argparse
import subprocess
import sys

from phase5r_daily_common import (
    DAILY_PIPELINE_LOCK_PATH,
    ROOT,
    ExclusiveFileLock,
    load_active_state,
    load_inhibit,
    log_daily_run,
)
from phase5r_production_shadow_email_gate import observation_email_suppressed


SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"
REFRESH_SCRIPT = SCRIPT_DIR / "run_phase5r_daily_refresh.py"
SENDER_SCRIPT = SCRIPT_DIR / "send_phase5r_daily_email.py"


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
    for target in (REFRESH_SCRIPT, SENDER_SCRIPT):
        if not target.exists():
            raise RuntimeError(f"required daily script missing: {target.name}")
    refresh = run_command([sys.executable, str(REFRESH_SCRIPT), "--safe-check"])
    sender = run_command([sys.executable, str(SENDER_SCRIPT), "--check"])
    if refresh.returncode != 0 or sender.returncode != 0:
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
        refresh = run_command(
            [sys.executable, str(REFRESH_SCRIPT), "--run", "--no-lock"]
        )
        if refresh.returncode != 0:
            log_daily_run(
                component="daily_pipeline",
                run_mode="scheduled_send" if send else "protected_no_send",
                outcome="failed",
                reason="daily_decision_not_created",
            )
            print(
                "daily_pipeline_outcome=failed reason=daily_decision_not_created "
                "email_attempted=false"
            )
            return 1
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
        if observation_email_suppressed():
            log_daily_run(
                component="daily_pipeline",
                run_mode="scheduled_send_suppressed_observation",
                outcome="passed",
                reason="production_shadow_observation_email_suppressed",
                email_attempted="no",
                email_sent="no",
            )
            print(
                "daily_pipeline_outcome=passed mode=observation_email_suppressed "
                "email_attempted=false email_sent=false"
            )
            return 0
        sender = run_command([sys.executable, str(SENDER_SCRIPT), "--send"], timeout=90)
        sender_summary = " ".join(sender.stdout.strip().split())[-500:]
        log_daily_run(
            component="daily_pipeline",
            run_mode="scheduled_send",
            outcome="passed" if sender.returncode == 0 else "sender_nonzero",
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
            f"daily_pipeline_outcome={'passed' if sender.returncode == 0 else 'sender_nonzero'} "
            f"sender_exit={sender.returncode} {sender_summary}"
        )
        return sender.returncode


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
