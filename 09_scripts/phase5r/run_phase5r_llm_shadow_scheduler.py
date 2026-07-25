#!/usr/bin/env python3
"""Independent 15-minute wrapper for one post-close model shadow attempt."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from phase5r_daily_common import (
    ROOT,
    atomic_write_json,
    cycle_date,
    iso_now,
    load_active_state,
    load_inhibit,
    now_et,
    read_json,
)
from phase5r_llm_provider import CodexCliProvider
from run_phase5r_llm_shadow import load_registry


SHADOW_RUNNER = ROOT / "09_scripts" / "phase5r" / "run_phase5r_llm_shadow.py"
STATE_PATH = (
    ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_llm_shadow_scheduler_state.local.json"
)
SHADOW_TIME = "18:00"
MAX_AUTOMATIC_ATTEMPTS = 2
TIMEOUT_SECONDS = 1100


def validate_runtime_boundary(
    active: dict[str, object],
    inhibit: dict[str, object],
    registry: dict[str, object],
) -> None:
    required_active = {
        "current_workflow": "daily_decision",
        "active_pipeline": "phase5r_daily",
        "email_delivery_allowed_from": "phase5r_daily_only",
        "broker_connection_allowed": "no",
        "order_code_allowed": "no",
        "manual_execution_only": "yes",
    }
    for key, expected in required_active.items():
        if active.get(key) != expected:
            raise RuntimeError(f"shadow runtime boundary failed: active.{key}")
    if (
        inhibit.get("active") is not False
        or inhibit.get("allowed_pipeline") != "phase5r_daily"
    ):
        raise RuntimeError("shadow runtime boundary failed: maintenance inhibit")
    if (
        registry.get("canonical_influence_enabled") is not False
        or registry.get("automatic_action_allowed") is not False
        or registry.get("email_eligible") is not False
        or registry.get("broker_connection_allowed") is not False
        or registry.get("order_code_allowed") is not False
        or registry.get("tools_enabled") is not False
        or registry.get("provider_credentials_read_by_repository") is not False
    ):
        raise RuntimeError("shadow runtime boundary failed: model registry")
    if not SHADOW_RUNNER.is_file():
        raise RuntimeError("shadow runtime boundary failed: runner missing")
    CodexCliProvider(
        Path(str(registry["provider_executable"])),
        expected_sha256=str(registry["provider_executable_sha256"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-check", action="store_true")
    args = parser.parse_args()
    active = load_active_state()
    inhibit = load_inhibit()
    registry = load_registry()
    validate_runtime_boundary(active, inhibit, registry)
    if args.safe_check:
        print(
            "safe_check_passed=true component=llm_shadow_scheduler "
            f"live_shadow_enabled={str(registry['live_shadow_enabled']).lower()} "
            "provider_invoked=false credential_read=false email_attempted=false"
        )
        return 0
    if registry["mode"] != "shadow" or registry["live_shadow_enabled"] is not True:
        print(
            "scheduler_action=none reason=live_shadow_not_enabled "
            "provider_invoked=false email_attempted=false"
        )
        return 0
    if cycle_date() < str(active.get("operational_from", "")):
        print("scheduler_action=none reason=before_operational_from")
        return 0
    if now_et().strftime("%H:%M") < SHADOW_TIME:
        print("scheduler_action=none reason=before_shadow_time")
        return 0

    state = read_json(
        STATE_PATH,
        {"schema_version": "phase5r_llm_shadow_scheduler_state_v1", "dates": {}},
    )
    date_state = state.setdefault("dates", {}).setdefault(cycle_date(), {})
    if date_state.get("completed") is True:
        print("scheduler_action=none reason=shadow_already_completed")
        return 0
    attempts = int(date_state.get("attempts", 0) or 0)
    if attempts >= MAX_AUTOMATIC_ATTEMPTS:
        print("scheduler_action=none reason=automatic_attempt_limit_reached")
        return 0

    command = [sys.executable, str(SHADOW_RUNNER), "--live-shadow"]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        completed = subprocess.CompletedProcess(
            command,
            124,
            stdout=f"{partial}\nshadow_timeout_seconds={TIMEOUT_SECONDS}",
        )
    attempts += 1
    date_state["attempts"] = attempts
    date_state["last_attempt_at"] = iso_now()
    date_state["last_exit_code"] = completed.returncode
    if completed.returncode == 0:
        date_state["completed"] = True
        date_state["completed_at"] = iso_now()
    state["updated_at"] = iso_now()
    for old_date in sorted(state["dates"])[:-60]:
        del state["dates"][old_date]
    atomic_write_json(STATE_PATH, state)
    summary = " ".join(completed.stdout.strip().split())[-500:]
    print(
        f"scheduler_action=llm_shadow exit_code={completed.returncode} "
        f"attempt={attempts} {summary}"
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
