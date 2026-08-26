#!/usr/bin/env python3
"""Shared safety and persistence helpers for the Phase 5R daily workflow."""

from __future__ import annotations

import csv
import calendar
import fcntl
import hashlib
import json
import os
import stat
import tempfile
import time as time_module
from contextlib import AbstractContextManager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
ET = ZoneInfo("America/New_York")
RUNTIME_EXPECTED_CYCLE_DATE_ENV = "PHASE5R_RUNTIME_EXPECTED_CYCLE_DATE"

ACTIVE_STATE_PATH = ROOT / "00_project_control" / "active_decision_state.yaml"
INHIBIT_PATH = (
    ROOT / "07_automation" / "scheduler" / "phase5r_c9_maintenance_inhibit.local.json"
)
ACCOUNT_STATE_PATH = ROOT / "05_risk_and_positions" / "current_account_state.local.json"
POSITIONS_PATH = ROOT / "05_risk_and_positions" / "current_positions.local.csv"
EXECUTION_LEDGER_PATH = ROOT / "06_execution_records" / "manual_executions.local.csv"
PENDING_EXECUTION_PATH = (
    ROOT / "06_execution_records" / "phase5r_c9b_pending_execution_report.csv"
)
RECONCILIATION_PATH = (
    ROOT / "06_execution_records" / "phase5r_c9b_reconciliation_report.csv"
)

MARKET_SNAPSHOT_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_b2_market_data_snapshot.csv"
)
MARKET_QUALITY_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_b2_market_data_quality_report.csv"
)
EXACT_ACTION_PATH = (
    ROOT / "05_risk_and_positions" / "phase5r_c9_exact_action_plan.csv"
)
POSITION_RECOMMENDATION_PATH = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_position_recommendations.csv"
)
NEW_CANDIDATE_PATH = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_new_candidate_recommendations.csv"
)

EVIDENCE_LEDGER_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_daily_evidence_ledger.csv"
)
EVIDENCE_STATE_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_daily_evidence_state.local.json"
)
EVIDENCE_STATUS_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_daily_evidence_status.json"
)
FUNDAMENTALS_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_daily_fundamentals.csv"
)
SEC_TICKER_MAP_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_sec_ticker_map.local.json"
)

DAILY_DECISION_JSON_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r" / "phase5r_daily_decision.json"
)
DAILY_DECISION_REPORT_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r" / "phase5r_daily_decision.md"
)
DAILY_BRIEF_TEXT_PATH = (
    ROOT / "07_automation" / "email_briefs" / "phase5r_daily_email_brief.txt"
)
DAILY_BRIEF_HTML_PATH = (
    ROOT / "07_automation" / "email_briefs" / "phase5r_daily_email_brief.html"
)
DAILY_DECISION_STATE_PATH = (
    ROOT / "00_project_control" / "run_logs" / "phase5r_daily_decision_state.local.json"
)
DAILY_DELIVERY_LEDGER_PATH = (
    ROOT / "07_automation" / "email_delivery" / "phase5r_daily_delivery_ledger.csv"
)
DAILY_DELIVERY_LOCK_PATH = (
    ROOT / "00_project_control" / "run_logs" / "phase5r_daily_delivery.lock"
)
DAILY_PIPELINE_LOCK_PATH = (
    ROOT / "00_project_control" / "run_logs" / "phase5r_daily_pipeline.lock"
)
DAILY_REFRESH_STATE_PATH = (
    ROOT / "00_project_control" / "run_logs" / "phase5r_daily_refresh_state.local.json"
)
DAILY_SCHEDULER_STATE_PATH = (
    ROOT / "00_project_control" / "run_logs" / "phase5r_daily_scheduler_state.local.json"
)
DAILY_RUN_LOG_PATH = (
    ROOT / "00_project_control" / "run_logs" / "phase5r_daily_run_log.csv"
)

EMAIL_CONFIG_PATH = (
    ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"
)

ACTION_TRANSITIONS = {"add", "trim", "exit", "reduce", "sell", "buy"}
NO_ACTION_LABELS = {
    "hold",
    "watch_only",
    "wait",
    "no_new_position",
    "core_allocation_tranche_review",
}


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat(timespec="seconds")


def cycle_date(value: datetime | None = None) -> str:
    return (value or now_et()).date().isoformat()


def nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (ordinal - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    value = date(year, month, last_day)
    return value - timedelta(days=(value.weekday() - weekday) % 7)


def observed(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def us_market_holidays(year: int) -> set[date]:
    """Return the regular U.S. market holidays used by the daily gates."""

    return {
        observed(date(year, 1, 1)),
        nth_weekday(year, 1, calendar.MONDAY, 3),
        nth_weekday(year, 2, calendar.MONDAY, 3),
        easter_sunday(year) - timedelta(days=2),
        last_weekday(year, 5, calendar.MONDAY),
        observed(date(year, 6, 19)),
        observed(date(year, 7, 4)),
        nth_weekday(year, 9, calendar.MONDAY, 1),
        nth_weekday(year, 11, calendar.THURSDAY, 4),
        observed(date(year, 12, 25)),
    }


def is_us_market_session_date(value: date) -> bool:
    holidays = us_market_holidays(value.year) | us_market_holidays(value.year - 1)
    return value.weekday() < 5 and value not in holidays


def expected_market_session(current: datetime) -> date:
    """Return the trading session expected by existing daily decision gates."""

    candidate = current.date()
    while not is_us_market_session_date(candidate):
        candidate -= timedelta(days=1)
    return candidate


def last_completed_market_session(
    current: datetime,
    *,
    close_time: time = time(16, 15),
) -> date:
    """Return the most recent session that can safely be reused as a close.

    This intentionally mirrors the daily close boundary.  A pre-close weekday
    can reuse only the preceding completed session; a holiday or weekend is
    normalized back to the prior regular session.
    """

    candidate = current
    if (
        is_us_market_session_date(current.date())
        and current.timetz().replace(tzinfo=None) < close_time
    ):
        candidate = current - timedelta(days=1)
    return expected_market_session(candidate)


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def atomic_write_csv(
    path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(
            file_descriptor, "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def append_csv_durable(
    path: Path, fieldnames: list[str], row: dict[str, Any]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if not existed:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256_bytes(handle.read())


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0", ""}:
            return False
    raise ValueError(f"not a boolean value: {value!r}")


def load_active_state() -> dict[str, Any]:
    payload = read_json(ACTIVE_STATE_PATH)
    if payload.get("current_workflow") != "daily_decision":
        raise RuntimeError("active workflow is not daily_decision")
    if payload.get("active_pipeline") != "phase5r_daily":
        raise RuntimeError("active pipeline is not phase5r_daily")
    if payload.get("email_delivery_allowed_from") != "phase5r_daily_only":
        raise RuntimeError("email delivery is not restricted to phase5r_daily")
    if payload.get("broker_connection_allowed") != "no":
        raise RuntimeError("broker connection boundary is not closed")
    if payload.get("order_code_allowed") != "no":
        raise RuntimeError("order-code boundary is not closed")
    if payload.get("manual_execution_only") != "yes":
        raise RuntimeError("manual execution boundary is not active")
    return payload


def load_inhibit() -> dict[str, Any]:
    payload = read_json(INHIBIT_PATH)
    active = bool_value(payload.get("active"))
    allowed = payload.get("allowed_pipeline")
    if active and allowed != "none":
        raise RuntimeError("active maintenance inhibit must allow no pipeline")
    if not active and allowed != "phase5r_daily":
        raise RuntimeError("cleared inhibit must allow only phase5r_daily")
    return payload


def delivery_guard() -> tuple[bool, str, dict[str, Any], dict[str, Any]]:
    active_state = load_active_state()
    inhibit = load_inhibit()
    if bool_value(inhibit.get("active")):
        return False, "maintenance_inhibit_active", active_state, inhibit
    operational_from = str(active_state.get("operational_from", "")).strip()
    if not operational_from:
        return False, "operational_from_missing", active_state, inhibit
    if cycle_date() < operational_from:
        return False, "before_operational_from", active_state, inhibit
    if now_et().strftime("%H:%M") < "18:30":
        return False, "before_daily_decision_time", active_state, inhibit
    return True, "delivery_enabled", active_state, inhibit


def unresolved_execution_conflicts() -> list[str]:
    conflicts: list[str] = []
    for row in read_csv(PENDING_EXECUTION_PATH):
        execution_id = row.get("execution_id", "").strip()
        if execution_id:
            conflicts.append(f"pending:{execution_id}")
    for row in read_csv(RECONCILIATION_PATH):
        execution_id = row.get("execution_id", "").strip()
        applied = row.get("canonical_state_applied", "").strip().lower()
        status = row.get("reconciliation_status", "").strip().lower()
        if execution_id and not (applied == "yes" and status == "applied"):
            conflicts.append(f"unreconciled:{execution_id}")
    return sorted(set(conflicts))


class ExclusiveFileLock(AbstractContextManager["ExclusiveFileLock"]):
    """Process lock using flock over a private, non-linked regular file."""

    def __init__(
        self,
        path: Path,
        *,
        wait_timeout_seconds: float = 0.0,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        if wait_timeout_seconds < 0:
            raise ValueError("lock wait timeout cannot be negative")
        if poll_interval_seconds <= 0:
            raise ValueError("lock poll interval must be positive")
        self.path = path
        self.wait_timeout_seconds = wait_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.handle: Any | None = None
        self.contention_observed = False
        self.waited_seconds = 0.0

    def __enter__(self) -> "ExclusiveFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not hasattr(os, "O_NOFOLLOW"):
            raise RuntimeError("O_NOFOLLOW is required for canonical file locks")
        file_descriptor = os.open(
            self.path,
            os.O_RDWR
            | os.O_CREAT
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            os.close(file_descriptor)
            raise RuntimeError(
                f"lock must be a private regular file with one link: {self.path}"
            )
        try:
            self.handle = os.fdopen(
                file_descriptor,
                "r+",
                encoding="utf-8",
            )
        except Exception:
            os.close(file_descriptor)
            raise
        started = time_module.monotonic()
        deadline = started + self.wait_timeout_seconds
        while True:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                self.contention_observed = True
                remaining = deadline - time_module.monotonic()
                if self.wait_timeout_seconds == 0:
                    self.handle.close()
                    self.handle = None
                    raise RuntimeError(f"lock already held: {self.path}") from exc
                if remaining <= 0:
                    self.waited_seconds = time_module.monotonic() - started
                    self.handle.close()
                    self.handle = None
                    raise RuntimeError(
                        f"lock wait timed out: {self.path}"
                    ) from exc
                time_module.sleep(min(self.poll_interval_seconds, remaining))
        self.waited_seconds = time_module.monotonic() - started
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"pid={os.getpid()} acquired_at={iso_now()}\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


def log_daily_run(
    *,
    component: str,
    run_mode: str,
    outcome: str,
    reason: str,
    email_attempted: str = "no",
    email_sent: str = "no",
    c7_invoked: str = "no",
    smtp_config_read: str = "no",
    smtp_config_modified: str = "no",
    broker_account_read: str = "no",
) -> None:
    append_csv_durable(
        DAILY_RUN_LOG_PATH,
        [
            "logged_at",
            "cycle_date",
            "component",
            "run_mode",
            "outcome",
            "reason",
            "email_attempted",
            "email_sent",
            "c7_invoked",
            "smtp_config_read",
            "smtp_config_modified",
            "broker_connected",
            "broker_account_read",
            "order_code_created",
        ],
        {
            "logged_at": iso_now(),
            "cycle_date": cycle_date(),
            "component": component,
            "run_mode": run_mode,
            "outcome": outcome,
            "reason": reason,
            "email_attempted": email_attempted,
            "email_sent": email_sent,
            "c7_invoked": c7_invoked,
            "smtp_config_read": smtp_config_read,
            "smtp_config_modified": smtp_config_modified,
            "broker_connected": "no",
            "broker_account_read": broker_account_read,
            "order_code_created": "no",
        },
    )
