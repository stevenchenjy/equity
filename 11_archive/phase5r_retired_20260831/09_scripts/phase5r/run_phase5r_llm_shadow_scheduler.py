#!/usr/bin/env python3
"""Independent 15-minute wrapper for one post-close model shadow attempt."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from phase5r_daily_common import (
    ROOT,
    atomic_write_json,
    canonical_sha256,
    iso_now,
    load_active_state,
    load_inhibit,
    now_et,
    read_json,
)
from phase5r_llm_activation_receipt import verify_active_activation_receipt
from phase5r_llm_provider import CodexCliProvider
from run_phase5r_llm_shadow import load_registry


SHADOW_RUNNER = ROOT / "09_scripts" / "phase5r" / "run_phase5r_llm_shadow.py"
DAILY_DECISION_PATH = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_daily_decision.json"
)
STATE_PATH = (
    ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_llm_shadow_scheduler_state.local.json"
)
SHADOW_TIME = "18:00"
MAX_AUTOMATIC_ATTEMPTS = 2
TIMEOUT_SECONDS = 1100
ROUTER_GATE_TIMEOUT_SECONDS = 120
SCHEDULER_STATE_SCHEMA_VERSION = (
    "phase5r_llm_shadow_scheduler_state_v2"
)


def _persist_scheduler_state(state: dict[str, object]) -> None:
    atomic_write_json(STATE_PATH, state)
    state_directory_descriptor = os.open(
        STATE_PATH.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(state_directory_descriptor)
    finally:
        os.close(state_directory_descriptor)


def _finalize_unknown_launch_claims(
    state: dict[str, object],
    date_state: dict[str, object],
) -> bool:
    claims = date_state.get("attempt_claims")
    if claims is None:
        return False
    if not isinstance(claims, list) or any(
        not isinstance(claim, dict) for claim in claims
    ):
        raise RuntimeError("shadow scheduler attempt claims are invalid")
    pending = [
        claim
        for claim in claims
        if claim.get("status") == "launch_claimed"
    ]
    if not pending:
        return False
    recovered_at = iso_now()
    for claim in pending:
        claim["status"] = "outcome_unknown"
        claim["recovered_at"] = recovered_at
    date_state["last_unknown_outcome_at"] = recovered_at
    state["updated_at"] = recovered_at
    _persist_scheduler_state(state)
    return True


def weekend_has_material_change(
    *,
    current_cycle_date: str,
    weekday: int,
    decision: dict[str, object],
) -> bool:
    """Suppress weekend inference unless deterministic state materially changed."""

    if weekday < 5:
        return True
    if decision.get("cycle_date") != current_cycle_date:
        return False
    evidence_gate = decision.get("evidence_gate", {})
    event_count = (
        evidence_gate.get("new_material_event_count", 0)
        if isinstance(evidence_gate, dict)
        else 0
    )
    material_events = decision.get("material_events", [])
    eligible = decision.get("eligible_action_review_candidates", [])
    return bool(
        decision.get("decision_changed") is True
        or decision.get("human_review_required") is True
        or isinstance(event_count, int)
        and not isinstance(event_count, bool)
        and event_count > 0
        or isinstance(material_events, list)
        and bool(material_events)
        or isinstance(eligible, list)
        and bool(eligible)
    )


def validate_runtime_boundary(
    active: dict[str, object],
    inhibit: dict[str, object],
    registry: dict[str, object],
    *,
    verify_activation: bool = True,
) -> str:
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
    mode = registry.get("mode")
    enabled = registry.get("live_shadow_enabled")
    if mode == "shadow" and enabled is True:
        if not verify_activation:
            return "deferred"
        CodexCliProvider(
            Path(str(registry["provider_executable"])),
            expected_sha256=str(registry["provider_executable_sha256"]),
        )
        receipt_result = verify_active_activation_receipt()
        if receipt_result.get("passed") is not True:
            raise RuntimeError(
                "shadow runtime boundary failed: activation receipt"
            )
        return "verified"
    if mode == "offline_fixture" and enabled is False:
        return "not_required"
    raise RuntimeError(
        "shadow runtime boundary failed: registry mode/enabled mismatch"
    )


def _run_explicit_router_gate(
    envelope_path: Path,
    *,
    check_mode: bool,
) -> subprocess.CompletedProcess[str]:
    """Run the local planner before activation or provider construction."""

    command = [
        sys.executable,
        str(SHADOW_RUNNER),
        "--check" if check_mode else "--live-shadow",
        "--router-envelope",
        str(envelope_path),
    ]
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=ROUTER_GATE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=(
                f"{partial}\n"
                "shadow_router_gate_timeout="
                f"{ROUTER_GATE_TIMEOUT_SECONDS}"
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-check", action="store_true")
    parser.add_argument("--router-envelope", type=Path)
    args = parser.parse_args()
    active = load_active_state()
    inhibit = load_inhibit()
    registry = load_registry()
    if args.safe_check:
        if args.router_envelope is not None:
            validate_runtime_boundary(
                active,
                inhibit,
                registry,
                verify_activation=False,
            )
            router_result = _run_explicit_router_gate(
                args.router_envelope,
                check_mode=True,
            )
            summary = " ".join(
                router_result.stdout.strip().split()
            )[-500:]
            print(
                "safe_check_component=llm_shadow_router_gate "
                f"exit_code={router_result.returncode} {summary}"
            )
            return router_result.returncode
        receipt_state = validate_runtime_boundary(
            active,
            inhibit,
            registry,
            verify_activation=True,
        )
        print(
            "safe_check_passed=true component=llm_shadow_scheduler "
            f"live_shadow_enabled={str(registry['live_shadow_enabled']).lower()} "
            f"activation_receipt={receipt_state} "
            "provider_invoked=false credential_read=false email_attempted=false"
        )
        return 0
    validate_runtime_boundary(
        active,
        inhibit,
        registry,
        verify_activation=False,
    )
    if registry["mode"] != "shadow" or registry["live_shadow_enabled"] is not True:
        print(
            "scheduler_action=none reason=live_shadow_not_enabled "
            "provider_invoked=false email_attempted=false"
        )
        return 0
    current = now_et()
    current_cycle = current.date().isoformat()
    if current_cycle < str(active.get("operational_from", "")):
        print("scheduler_action=none reason=before_operational_from")
        return 0
    if current.strftime("%H:%M") < SHADOW_TIME:
        print("scheduler_action=none reason=before_shadow_time")
        return 0
    if args.router_envelope is not None:
        # An explicit router envelope never falls through to the legacy
        # all-role executor. The runner persists a local planning receipt and
        # blocks every unsupported call set without constructing a provider.
        router_result = _run_explicit_router_gate(
            args.router_envelope,
            check_mode=False,
        )
        summary = " ".join(
            router_result.stdout.strip().split()
        )[-500:]
        print(
            "scheduler_action=llm_shadow_router_gate "
            f"exit_code={router_result.returncode} {summary}"
        )
        return router_result.returncode
    daily_decision = read_json(DAILY_DECISION_PATH, {})
    if not weekend_has_material_change(
        current_cycle_date=current_cycle,
        weekday=current.weekday(),
        decision=daily_decision,
    ):
        print(
            "scheduler_action=none reason=weekend_no_material_change "
            "provider_invoked=false email_attempted=false"
        )
        return 0

    state = read_json(
        STATE_PATH,
        {
            "schema_version": SCHEDULER_STATE_SCHEMA_VERSION,
            "dates": {},
        },
    )
    if state.get("schema_version") not in {
        "phase5r_llm_shadow_scheduler_state_v1",
        SCHEDULER_STATE_SCHEMA_VERSION,
    } or not isinstance(state.get("dates"), dict):
        raise RuntimeError("shadow scheduler state contract is invalid")
    state["schema_version"] = SCHEDULER_STATE_SCHEMA_VERSION
    date_state = state.setdefault("dates", {}).setdefault(current_cycle, {})
    if not isinstance(date_state, dict):
        raise RuntimeError("shadow scheduler date state is invalid")
    # Resolve a prior process-launch ambiguity before *any* completed/cap
    # early exit. The claim stays charged to the cap and no provider is
    # relaunched merely to finalize scheduler state.
    _finalize_unknown_launch_claims(state, date_state)
    if date_state.get("completed") is True:
        print("scheduler_action=none reason=shadow_already_completed")
        return 0
    attempts = int(date_state.get("attempts", 0) or 0)
    if attempts >= MAX_AUTOMATIC_ATTEMPTS:
        print("scheduler_action=none reason=automatic_attempt_limit_reached")
        return 0

    # The receipt revalidates the complete corpus/response closure. Keep that
    # expensive read immediately adjacent to the only provider-launch path,
    # after all no-call exits. Reload mutable controls so an early snapshot
    # cannot authorize a later launch.
    active = load_active_state()
    inhibit = load_inhibit()
    registry = load_registry()
    receipt_state = validate_runtime_boundary(
        active,
        inhibit,
        registry,
        verify_activation=True,
    )
    if receipt_state != "verified":
        print(
            "scheduler_action=none reason=live_shadow_not_enabled "
            "provider_invoked=false email_attempted=false"
        )
        return 0

    # Persist the attempt claim before any child process can exist. An
    # unresolved older claim remains charged to the cap; on recovery it is
    # explicitly classified as an unknown launch outcome, never erased.
    claims = date_state.setdefault("attempt_claims", [])
    if not isinstance(claims, list):
        raise RuntimeError("shadow scheduler attempt claims are invalid")
    attempts += 1
    claimed_at = iso_now()
    claim_id = canonical_sha256(
        {
            "schema_version": "phase5r_llm_shadow_launch_claim_v1",
            "cycle_date": current_cycle,
            "attempt_number": attempts,
            "claimed_at": claimed_at,
        }
    )
    claim = {
        "schema_version": "phase5r_llm_shadow_launch_claim_v1",
        "claim_id": claim_id,
        "attempt_number": attempts,
        "claimed_at": claimed_at,
        "status": "launch_claimed",
    }
    claims.append(claim)
    date_state["attempts"] = attempts
    date_state["last_attempt_at"] = claimed_at
    date_state["last_claim_id"] = claim_id
    state["updated_at"] = claimed_at
    for old_date in sorted(state["dates"])[:-60]:
        del state["dates"][old_date]
    _persist_scheduler_state(state)

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
    finished_at = iso_now()
    claim["status"] = "completed"
    claim["finished_at"] = finished_at
    claim["exit_code"] = completed.returncode
    date_state["last_exit_code"] = completed.returncode
    if completed.returncode == 0:
        date_state["completed"] = True
        date_state["completed_at"] = finished_at
    state["updated_at"] = finished_at
    _persist_scheduler_state(state)
    summary = " ".join(completed.stdout.strip().split())[-500:]
    print(
        f"scheduler_action=llm_shadow exit_code={completed.returncode} "
        f"attempt={attempts} {summary}"
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
