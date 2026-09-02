#!/usr/bin/env python3
"""Refresh market, official evidence, account-aware research, and daily brief.

This pipeline never imports or invokes an email sender.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from phase5r_daily_common import (
    DAILY_PIPELINE_LOCK_PATH,
    DAILY_REFRESH_STATE_PATH,
    ROOT,
    ExclusiveFileLock,
    atomic_write_json,
    cycle_date,
    iso_now,
    latest_published_market_session,
    load_active_state,
    load_inhibit,
    log_daily_run,
    now_et,
)


SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"
MARKET_SNAPSHOT_FETCH = "fetch"
MARKET_SNAPSHOT_REUSE = "reuse_validated_snapshot"
MARKET_SNAPSHOT_MODES = (MARKET_SNAPSHOT_FETCH, MARKET_SNAPSHOT_REUSE)
# The isolated EOD-publication market importer has a bounded 29-request plan paced
# at least 13 seconds between request starts. Keep a fixed allowance for HTTP
# time, process startup, local validation, and commit; all other children
# retain the historical short timeout.
DEFAULT_CHILD_TIMEOUT_SECONDS = 240
EOD_MARKET_REFRESH_TIMEOUT_SECONDS = 480
STEP_SPECS = [
    ("market_refresh", "run_phase5r_b2_full_universe_market_data.py", False),
    ("market_scoring", "score_phase5r_b2_candidates.py", False),
    ("official_evidence", "refresh_phase5r_daily_evidence.py", True),
    (
        "sec_filing_artifacts",
        "refresh_phase5r_sec_filing_artifacts.py",
        True,
    ),
    (
        "current_research_baseline",
        "build_phase5r_current_research_baseline.py",
        False,
    ),
    (
        "valuation_scenarios",
        "refresh_phase5r_valuation_scenarios.py",
        False,
    ),
    # portfolio_outputs owns the account/weight/action/cash child sequence.
    # Running those children here as well duplicated C9 work and widened the
    # refresh race window without changing the result.
    ("portfolio_outputs", "regenerate_phase5r_c9_portfolio_outputs.py", False),
    ("price_aware_review", "create_phase5r_c9b_price_aware_action_plan.py", True),
    (
        "daily_decision",
        "create_phase5r_daily_decision_and_brief.py",
        False,
    ),
    (
        "outcome_tracking",
        "track_phase5r_recommendation_outcomes.py",
        False,
    ),
    (
        "capital_allocation_validation",
        "create_phase5r_capital_allocation_validation.py",
        False,
    ),
    # Persist the sanitized deterministic packet as an auditable research
    # artifact. No model or external inference path consumes it in production.
    ("evidence_packet", "build_phase5r_decision_evidence_packet.py", False),
]
CURRENT_STATUS_SPEC = (
    "current_status",
    "generate_phase5r_current_status.py",
    True,
)


def run_step(
    name: str,
    script_name: str,
    allowed_to_fail: bool,
    *,
    market_snapshot_mode: str = MARKET_SNAPSHOT_FETCH,
) -> dict[str, Any]:
    timeout_seconds = (
        EOD_MARKET_REFRESH_TIMEOUT_SECONDS
        if name == "market_refresh"
        and market_snapshot_mode == MARKET_SNAPSHOT_FETCH
        else DEFAULT_CHILD_TIMEOUT_SECONDS
    )
    extra_arguments = (
        ["--reuse-validated-snapshot"]
        if name == "market_refresh" and market_snapshot_mode == MARKET_SNAPSHOT_REUSE
        else
        ["--refresh"]
        if name == "sec_filing_artifacts"
        else ["--build"]
        if name == "evidence_packet"
        else []
    )
    try:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / script_name), *extra_arguments],
            cwd=ROOT,
            # Child diagnostics can contain third-party response fragments.
            # The durable refresh state records only finite status fields, so
            # do not capture or reflect stdout/stderr into a state file or a
            # launchd log.
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "script": script_name,
            "exit_code": 124,
            "allowed_to_fail": allowed_to_fail,
            "outcome": "timed_out",
            "result_code": f"child_timeout_{timeout_seconds}_seconds",
        }
    return {
        "name": name,
        "script": script_name,
        "exit_code": completed.returncode,
        "allowed_to_fail": allowed_to_fail,
        "outcome": "passed" if completed.returncode == 0 else "failed",
        "result_code": (
            "child_completed" if completed.returncode == 0 else "child_nonzero_exit"
        ),
    }


def safe_check() -> int:
    load_active_state()
    load_inhibit()
    missing = [
        script_name
        for _, script_name, _ in [*STEP_SPECS, CURRENT_STATUS_SPEC]
        if not (SCRIPT_DIR / script_name).exists()
    ]
    if missing:
        raise RuntimeError(f"missing daily refresh scripts: {','.join(missing)}")
    print(
        "safe_check_passed=true sender_reference=false smtp_config_read=false "
        "broker_connected=false order_code_created=false"
    )
    return 0


def run_refresh(no_lock: bool, market_snapshot_mode: str = MARKET_SNAPSHOT_FETCH) -> int:
    load_active_state()
    load_inhibit()
    if market_snapshot_mode not in MARKET_SNAPSHOT_MODES:
        raise ValueError("invalid market snapshot mode")
    lock_context = nullcontext() if no_lock else ExclusiveFileLock(DAILY_PIPELINE_LOCK_PATH)
    started_at = iso_now()
    refresh_cycle_date = cycle_date()
    expected_market_session = latest_published_market_session(now_et()).isoformat()
    with lock_context:
        steps = [
            run_step(*spec, market_snapshot_mode=market_snapshot_mode)
            for spec in STEP_SPECS
        ]
    hard_failures = [
        row["name"]
        for row in steps
        if row["exit_code"] != 0 and not row["allowed_to_fail"]
    ]
    soft_failures = [
        row["name"]
        for row in steps
        if row["exit_code"] != 0 and row["allowed_to_fail"]
    ]
    decision_completed = any(
        row["name"] == "daily_decision" and row["exit_code"] == 0 for row in steps
    )
    if decision_completed and not hard_failures and not soft_failures:
        outcome = "passed"
    elif decision_completed:
        outcome = "degraded_decision_created"
    else:
        outcome = "failed"
    state = {
        "schema_version": "phase5r_daily_refresh_state_v1",
        "cycle_date": refresh_cycle_date,
        "expected_market_session": expected_market_session,
        "started_at": started_at,
        "completed_at": iso_now(),
        "outcome": outcome,
        "hard_failures": hard_failures,
        "soft_failures": soft_failures,
        "decision_created": decision_completed,
        "market_snapshot_mode": market_snapshot_mode,
        "steps": steps,
        "email_attempted": False,
        "email_sent": False,
        "broker_connected": False,
        "broker_account_read": False,
        "order_code_created": False,
    }
    atomic_write_json(DAILY_REFRESH_STATE_PATH, state)
    # The status report must observe this run's final outcome rather than the
    # prior run.  Treat reporting as non-canonical: a rendering failure is
    # recorded but cannot turn an otherwise valid deterministic decision into
    # a failed research cycle.
    status_step = run_step(
        *CURRENT_STATUS_SPEC,
        market_snapshot_mode=market_snapshot_mode,
    )
    state["current_status_update"] = status_step
    state["completed_at"] = iso_now()
    atomic_write_json(DAILY_REFRESH_STATE_PATH, state)
    log_daily_run(
        component="daily_refresh",
        run_mode="public_research_no_send",
        outcome=outcome,
        reason=(
            "complete"
            if outcome == "passed"
            else ",".join(hard_failures + soft_failures) or "decision_not_created"
        ),
    )
    print(
        f"daily_refresh_outcome={outcome} decision_created="
        f"{str(decision_completed).lower()} email_attempted=false "
        f"hard_failures={','.join(hard_failures) or 'none'} "
        f"soft_failures={','.join(soft_failures) or 'none'}"
    )
    # A degraded decision remains a useful fail-closed research artifact, but
    # it is not scheduler success and can never authorize email. Returning
    # nonzero lets bounded later slots recover transient provider failures.
    return 0 if outcome == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--safe-check", action="store_true")
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="internal: caller already owns the daily pipeline lock",
    )
    parser.add_argument(
        "--market-snapshot-mode",
        choices=MARKET_SNAPSHOT_MODES,
        default=MARKET_SNAPSHOT_FETCH,
        help="internal: either fetch public data or reuse an exact validated local close",
    )
    args = parser.parse_args()
    if args.safe_check:
        if args.no_lock:
            raise ValueError("--no-lock is valid only with --run")
        return safe_check()
    return run_refresh(args.no_lock, args.market_snapshot_mode)


if __name__ == "__main__":
    raise SystemExit(main())
