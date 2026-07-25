from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
RUN_LOG_DIR = CONTROL_DIR / "run_logs"
ACTIVE_STATE = CONTROL_DIR / "active_decision_state.yaml"
C6_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv"
C7_PIPELINE = ROOT / "09_scripts" / "phase5r" / "run_phase5r_c7_weekly_conviction_pipeline.py"
C9_MAINTENANCE_INHIBIT = (
    ROOT / "07_automation" / "scheduler" / "phase5r_c9_maintenance_inhibit.local.json"
)
CHECK_LOG = RUN_LOG_DIR / "phase5r_d3_catchup_check_log.csv"
LOCK_PATH = RUN_LOG_DIR / "phase5r_d3_catchup.lock"
LOCAL_STATE = RUN_LOG_DIR / "phase5r_d3_catchup_state.local.json"
INSTALL_INHIBIT = RUN_LOG_DIR / "phase5r_d3_install_inhibit"
D3F_VERIFICATION_INHIBIT = RUN_LOG_DIR / "phase5r_d3f_verification_inhibit"

REQUIRED_ACTIVE_STATE = {
    "current_workflow": "weekly_conviction",
    "active_pipeline": "phase5r_c7",
    "email_delivery_allowed_from": "phase5r_c7_only",
    "archived_folders_allowed_as_input": "no",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
}
LOG_FIELDS = [
    "timestamp",
    "cycle_id",
    "local_now",
    "scheduled_due_time",
    "decision",
    "reason",
    "c7_invoked",
    "c7_return_code",
    "sent_rows_before",
    "sent_rows_after",
    "send_delta",
    "lock_acquired",
    "active_workflow",
    "active_pipeline",
    "safety_notes",
]
DECISIONS = {
    "not_due_yet",
    "already_sent",
    "catchup_sent",
    "catchup_failed",
    "blocked_by_lock",
    "inactive_workflow",
    "missing_inputs",
    "verification_only",
    "maintenance_inhibit",
}


def local_zone() -> tzinfo:
    requested = os.environ.get("TZ", "").strip()
    if requested:
        try:
            return ZoneInfo(requested)
        except ZoneInfoNotFoundError:
            pass
    try:
        resolved = str(Path("/etc/localtime").resolve())
        marker = "zoneinfo/"
        if marker in resolved:
            return ZoneInfo(resolved.split(marker, 1)[1])
    except (OSError, ZoneInfoNotFoundError):
        pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(local_zone())
    return value.isoformat(timespec="seconds")


def cycle_context(now: datetime) -> tuple[str, datetime]:
    iso_year, iso_week, _ = now.date().isocalendar()
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    due_date = monday + timedelta(days=3)
    due = datetime.combine(due_date, time(hour=9, minute=5), tzinfo=now.tzinfo)
    return f"{iso_year}-W{iso_week:02d}", due


def parse_delivery_timestamp(raw: str, zone: tzinfo) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def read_successful_sends(zone: tzinfo) -> list[tuple[dict[str, str], datetime]]:
    if not C6_STATUS.exists():
        raise RuntimeError("c6_delivery_status_missing")
    try:
        with C6_STATUS.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"timestamp", "sent"}.issubset(reader.fieldnames):
                raise RuntimeError("c6_delivery_status_invalid_columns")
            successful: list[tuple[dict[str, str], datetime]] = []
            for row in reader:
                if row.get("sent", "").strip().lower() != "yes":
                    continue
                try:
                    row_time = parse_delivery_timestamp(row.get("timestamp", ""), zone)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("c6_success_timestamp_invalid") from exc
                successful.append((row, row_time))
            return successful
    except OSError as exc:
        raise RuntimeError("c6_delivery_status_unreadable") from exc


def sent_in_cycle(
    successful: list[tuple[dict[str, str], datetime]],
    cycle_id: str,
    due: datetime,
) -> bool:
    for _, row_time in successful:
        row_cycle, _ = cycle_context(row_time)
        if row_cycle == cycle_id and row_time >= due:
            return True
    return False


def read_active_state() -> dict[str, object]:
    if not ACTIVE_STATE.exists():
        raise RuntimeError("active_decision_state_missing")
    try:
        state = json.loads(ACTIVE_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("active_decision_state_invalid") from exc
    if not isinstance(state, dict):
        raise RuntimeError("active_decision_state_not_object")
    return state


def read_c9_maintenance_inhibit() -> tuple[bool, str]:
    if not C9_MAINTENANCE_INHIBIT.exists():
        return False, "c9_maintenance_inhibit_absent"
    try:
        state = json.loads(C9_MAINTENANCE_INHIBIT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, "c9_maintenance_inhibit_invalid_fail_closed"
    if not isinstance(state, dict) or not isinstance(state.get("active"), bool):
        return True, "c9_maintenance_inhibit_invalid_fail_closed"
    if state["active"] is False:
        return False, "c9_maintenance_inhibit_inactive"
    reason = state.get("reason")
    allowed_pipeline = state.get("allowed_pipeline")
    if not isinstance(reason, str) or not reason.strip() or allowed_pipeline != "none":
        return True, "c9_maintenance_inhibit_invalid_fail_closed"
    return True, reason.strip()


def default_local_state() -> dict[str, object]:
    return {
        "schema_version": "phase5r_d3_catchup_state_v1",
        "schedule": {
            "weekday": "Thursday",
            "hour": 9,
            "minute": 5,
            "timezone": "system_local",
            "check_interval_seconds": 900,
        },
        "cycle_attempts": {},
        "cycle_recovery_history": [],
        "last_check": None,
        "last_cycle_id": None,
        "last_decision": None,
        "last_reason": None,
        "last_successful_cycle_id": None,
        "last_sent_rows_observed": 0,
    }


def read_local_state() -> dict[str, object]:
    if not LOCAL_STATE.exists():
        return default_local_state()
    try:
        state = json.loads(LOCAL_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("catchup_state_invalid") from exc
    if not isinstance(state, dict) or state.get("schema_version") != "phase5r_d3_catchup_state_v1":
        raise RuntimeError("catchup_state_schema_invalid")
    if not isinstance(state.get("cycle_attempts"), dict):
        raise RuntimeError("catchup_state_attempts_invalid")
    if not isinstance(state.get("cycle_recovery_history", []), list):
        raise RuntimeError("catchup_state_recovery_history_invalid")
    state.setdefault("cycle_recovery_history", [])
    return state


def active_state_protections(state: dict[str, object]) -> list[str]:
    return [
        key
        for key in ("verification_flag_active", "install_inhibit", "protected_verification")
        if state.get(key) is True
    ]


def write_local_state(state: dict[str, object]) -> None:
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = LOCAL_STATE.with_name(f"{LOCAL_STATE.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, LOCAL_STATE)


def append_check_log(row: dict[str, str]) -> None:
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    with CHECK_LOG.open("a+", newline="", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0, os.SEEK_END)
        needs_header = handle.tell() == 0
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_observation_state(row: dict[str, str]) -> None:
    try:
        state = read_local_state()
        state["last_check"] = row["timestamp"]
        state["last_cycle_id"] = row["cycle_id"]
        state["last_decision"] = row["decision"]
        state["last_reason"] = row["reason"]
        state["last_sent_rows_observed"] = int(row["sent_rows_after"] or 0)
        if row["decision"] in {"already_sent", "catchup_sent"}:
            state["last_successful_cycle_id"] = row["cycle_id"]
        write_local_state(state)
    except (OSError, RuntimeError, ValueError):
        return


def record(
    *,
    now: datetime,
    cycle_id: str,
    due: datetime,
    decision: str,
    reason: str,
    state: dict[str, object] | None,
    c7_invoked: bool = False,
    c7_return_code: int | None = None,
    sent_before: int = 0,
    sent_after: int = 0,
    lock_acquired: bool = False,
    update_state: bool = True,
) -> int:
    if decision not in DECISIONS:
        raise ValueError(f"unsupported decision: {decision}")
    row = {
        "timestamp": timestamp(),
        "cycle_id": cycle_id,
        "local_now": timestamp(now),
        "scheduled_due_time": timestamp(due),
        "decision": decision,
        "reason": reason,
        "c7_invoked": "yes" if c7_invoked else "no",
        "c7_return_code": "" if c7_return_code is None else str(c7_return_code),
        "sent_rows_before": str(sent_before),
        "sent_rows_after": str(sent_after),
        "send_delta": str(sent_after - sent_before),
        "lock_acquired": "yes" if lock_acquired else "no",
        "active_workflow": str((state or {}).get("current_workflow", "")),
        "active_pipeline": str((state or {}).get("active_pipeline", "")),
        "safety_notes": (
            "manual_execution_only=yes; broker_connection=no; order_code=no; "
            "archived_inputs=no; child_output_logged=no; smtp_config_read_by_d3=no"
        ),
    }
    append_check_log(row)
    if update_state:
        update_observation_state(row)
    print(f"Phase 5R-D3 decision={decision}; cycle={cycle_id}; reason={reason}")
    return 1 if decision in {"catchup_failed", "inactive_workflow", "missing_inputs"} else 0


def acquire_cycle_lock() -> object | None:
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} acquired_at={timestamp()}\n")
    handle.flush()
    return handle


def release_cycle_lock(handle: object) -> None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
    handle.close()  # type: ignore[attr-defined]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check and catch up the Phase 5R weekly C7 delivery.")
    check_mode = parser.add_mutually_exclusive_group()
    check_mode.add_argument(
        "--verification-only",
        action="store_true",
        help="Validate inputs and log a check without acquiring the cycle lock or invoking C7.",
    )
    check_mode.add_argument(
        "--safe-check",
        action="store_true",
        help="Run the same non-sending validation path with an explicit operational-safe label.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    zone = local_zone()
    now = datetime.now(zone)
    cycle_id, due = cycle_context(now)

    try:
        active_state = read_active_state()
    except RuntimeError as exc:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="missing_inputs",
            reason=str(exc),
            state=None,
        )

    conflicts = [
        key
        for key, expected in REQUIRED_ACTIVE_STATE.items()
        if active_state.get(key) != expected
    ]
    if conflicts:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="inactive_workflow",
            reason="active_state_conflict:" + ",".join(conflicts),
            state=active_state,
        )

    maintenance_active, maintenance_reason = read_c9_maintenance_inhibit()

    if not C7_PIPELINE.exists():
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="missing_inputs",
            reason="c7_pipeline_missing",
            state=active_state,
        )

    try:
        successful = read_successful_sends(zone)
    except RuntimeError as exc:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="missing_inputs",
            reason=str(exc),
            state=active_state,
        )
    sent_before = len(successful)

    if maintenance_active:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="maintenance_inhibit",
            reason=maintenance_reason,
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
            update_state=False,
        )

    try:
        local_state = read_local_state()
    except RuntimeError as exc:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="missing_inputs",
            reason=str(exc),
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
        )

    if args.verification_only or args.safe_check:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="verification_only",
            reason="safe_check_requested" if args.safe_check else "verification_check_requested",
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
            update_state=False,
        )

    if D3F_VERIFICATION_INHIBIT.exists():
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="verification_only",
            reason="protected_verification_active",
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
            update_state=False,
        )

    if INSTALL_INHIBIT.exists():
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="verification_only",
            reason="install_inhibit_active",
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
            update_state=False,
        )

    state_protections = active_state_protections(local_state)
    if state_protections:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="verification_only",
            reason="local_state_protection_active:" + ",".join(state_protections),
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
            update_state=False,
        )

    if sent_in_cycle(successful, cycle_id, due):
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="already_sent",
            reason="successful_c6_send_exists_for_cycle",
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
        )

    if now < due:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="not_due_yet",
            reason="weekly_due_time_has_not_passed",
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
        )

    lock_handle = acquire_cycle_lock()
    if lock_handle is None:
        return record(
            now=now,
            cycle_id=cycle_id,
            due=due,
            decision="blocked_by_lock",
            reason="another_catchup_check_holds_cycle_lock",
            state=active_state,
            sent_before=sent_before,
            sent_after=sent_before,
        )

    c7_return_code: int | None = None
    c7_invoked = False
    decision = "catchup_failed"
    reason = "unexpected_catchup_failure"
    sent_after = sent_before
    try:
        try:
            successful_after_lock = read_successful_sends(zone)
        except RuntimeError as exc:
            reason = str(exc)
        else:
            sent_before = len(successful_after_lock)
            sent_after = sent_before
            if sent_in_cycle(successful_after_lock, cycle_id, due):
                decision = "already_sent"
                reason = "successful_c6_send_found_after_lock"
            else:
                try:
                    local_state = read_local_state()
                except RuntimeError as exc:
                    reason = str(exc)
                else:
                    attempts = local_state["cycle_attempts"]
                    if cycle_id in attempts:
                        reason = "prior_c7_attempt_without_success_requires_manual_review"
                    else:
                        attempts[cycle_id] = {
                            "started_at": timestamp(),
                            "completed_at": None,
                            "outcome": "in_progress",
                            "c7_return_code": None,
                            "send_delta": None,
                        }
                        try:
                            write_local_state(local_state)
                        except OSError:
                            reason = "unable_to_persist_once_per_cycle_attempt_guard"
                        else:
                            c7_invoked = True
                            try:
                                result = subprocess.run(
                                    [sys.executable, str(C7_PIPELINE)],
                                    cwd=ROOT,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    check=False,
                                )
                                c7_return_code = result.returncode
                            except OSError:
                                c7_return_code = -1
                            try:
                                successful_after_run = read_successful_sends(zone)
                                sent_after = len(successful_after_run)
                                cycle_sent = sent_in_cycle(successful_after_run, cycle_id, due)
                            except RuntimeError:
                                sent_after = sent_before
                                cycle_sent = False
                            send_delta = sent_after - sent_before
                            if c7_return_code == 0 and send_delta == 1 and cycle_sent:
                                decision = "catchup_sent"
                                reason = "c7_completed_with_exactly_one_new_c6_send"
                            else:
                                decision = "catchup_failed"
                                reason = "c7_result_or_c6_send_delta_failed_validation"
                            attempts[cycle_id] = {
                                "started_at": attempts[cycle_id]["started_at"],
                                "completed_at": timestamp(),
                                "outcome": decision,
                                "c7_return_code": c7_return_code,
                                "send_delta": send_delta,
                            }
                            try:
                                write_local_state(local_state)
                            except OSError:
                                decision = "catchup_failed"
                                reason = "catchup_completed_but_attempt_state_update_failed"
    finally:
        release_cycle_lock(lock_handle)

    return record(
        now=now,
        cycle_id=cycle_id,
        due=due,
        decision=decision,
        reason=reason,
        state=active_state,
        c7_invoked=c7_invoked,
        c7_return_code=c7_return_code,
        sent_before=sent_before,
        sent_after=sent_after,
        lock_acquired=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
