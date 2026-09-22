#!/usr/bin/env python3
"""Shared safety and persistence helpers for the Phase 5R daily workflow."""

from __future__ import annotations

from equity_naming import desktop_alert_script

import csv
import calendar
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import time as time_module
from contextlib import AbstractContextManager
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
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
PORTFOLIO_SUMMARY_PATH = (
    ROOT / "05_risk_and_positions" / "phase5r_c9_current_portfolio_summary.csv"
)
POST_ACTION_PORTFOLIO_PATH = (
    ROOT / "05_risk_and_positions" / "phase5r_c9_post_action_portfolio.csv"
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
AUTOMATION_ALERT_PATH = (
    ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_automation_alert.local.json"
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


BASIC_EOD_PUBLICATION_TIME = time(11, 15)
BASIC_EOD_PUBLICATION_TIME_ET = BASIC_EOD_PUBLICATION_TIME.strftime("%H:%M")


def latest_published_market_session(
    current: datetime,
    *,
    publication_time: time = BASIC_EOD_PUBLICATION_TIME,
) -> date:
    """Return the newest close available under the Basic EOD publication SLA.

    Massive Basic is an end-of-day product whose finalized daily dataset is
    published on the following calendar day.  Market close and provider
    publication are therefore separate boundaries: after 16:15 ET the same
    day's close is complete, but it is not yet a valid Basic snapshot.

    Before the publication boundary, step back two calendar days; at or after
    it, step back one.  Normalizing through ``expected_market_session`` keeps
    weekends and regular U.S. market holidays fail-closed and deterministic.
    """

    current_et = current.astimezone(ET) if current.tzinfo is not None else current
    current_clock = current_et.timetz().replace(tzinfo=None)
    calendar_lag_days = 1 if current_clock >= publication_time else 2
    return expected_market_session(
        current_et - timedelta(days=calendar_lag_days)
    )


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
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                extrasaction="ignore",
                lineterminator="\n",
            )
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
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
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
    # Keep the sender's final clock gate aligned with the single active
    # production configuration without creating a module-level import cycle.
    from phase5r_active_config import load_active_config

    send_after = str(load_active_config()["notifications"]["send_after_et"])
    if now_et().strftime("%H:%M") < send_after:
        return False, "before_daily_decision_time", active_state, inhibit
    return True, "delivery_enabled", active_state, inhibit


LEGACY_NOTIFICATION_MODE = "legacy_material_or_weekly"
WATCH_ACTION_NOTIFICATION_MODE = "watch_or_action_change"


def recommendation_notification_fingerprint(decision: dict[str, Any]) -> str:
    """Hash recommendation meaning, excluding quotes, dates and raw filings."""
    def numeric(value: Any) -> str | None:
        try:
            parsed = Decimal(str(value))
            return format(parsed.normalize(), "f") if parsed.is_finite() else None
        except (InvalidOperation, ValueError, TypeError):
            return None

    def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda row: (str(row.get("ticker", "")), canonical_sha256(row)))

    gates = {key: decision.get(key, {}).get("passed") is True
             for key in ("market_gate", "evidence_gate", "fundamental_gate")}
    conflicts = sorted(set(str(item) for item in decision.get("account_conflicts", [])))
    code = str(decision.get("decision_code", ""))
    cash_estimated = decision.get("account", {}).get("cash_basis") == "ledger_estimate"
    can_propose = (code == "action_review_candidate" and all(gates.values())
                   and not conflicts and not cash_estimated)
    held_eligible = set(decision.get("eligible_action_review_candidates", [])) if can_propose else set()
    new_eligible = set(decision.get("eligible_new_position_review_candidates", [])) if can_propose else set()
    pending = set(decision.get("pending_stability_candidates", []))
    held_rows = decision.get("held_positions", [])
    held_tickers = {str(row.get("ticker", "")) for row in held_rows}
    actions = []
    for row in held_rows:
        ticker = str(row.get("ticker", ""))
        eligible = ticker in held_eligible and ticker not in pending
        actions.append({"ticker": ticker, "action": row.get("action", ""), "eligible": eligible,
                        "whole_shares_to_change": numeric(row.get("whole_shares_to_change")) if eligible else None,
                        "target_shares": numeric(row.get("target_shares")) if eligible else None})
    candidates = []
    for row in decision.get("watch_candidates", []):
        ticker = str(row.get("ticker", ""))
        if ticker in held_tickers:
            continue
        eligible = (ticker in new_eligible and ticker not in pending
                    and int(row.get("stability_distinct_closes", decision.get("new_candidate_stability_distinct_closes", 0)) or 0)
                    >= int(row.get("required_distinct_closes", 2) or 2))
        candidates.append({
            "ticker": ticker, "label": row.get("label", ""), "action": row.get("action", ""),
            "eligible": eligible, "pending": ticker in pending,
            "blockers": sorted(set(item.strip() for item in str(row.get("gate_blockers", "")).split(",") if item.strip())),
            "invalidation": " ".join(str(row.get("invalidation", "")).split()),
            "suggested_whole_shares": numeric(row.get("suggested_whole_shares")) if eligible else None,
            "maximum_review_price": numeric(row.get("maximum_review_price")) if eligible else None,
        })
    research_warnings = []
    for row in decision.get("held_research_warnings", []):
        signals = [{key: item.get(key) for key in ("code", "observations", "evidence_date")}
                   for item in row.get("review_signals", []) if isinstance(item, dict)]
        research_warnings.append({"ticker": row.get("ticker"), "signals": sorted(signals, key=lambda item: str(item.get("code")))})
    tactical = decision.get("tactical_review", {})
    tactical_meaning = None
    if isinstance(tactical, dict) and tactical.get("schema_version") == "phase5r_tactical_review_v1":
        drafts = []
        for row in tactical.get("drafts", []):
            if not isinstance(row, dict):
                continue
            quantity = numeric(row.get("quantity"))
            hypothetical = numeric(row.get("hypothetical_quantity"))
            # Rejected price observations move every day; they are not a new
            # actionable plan. A complete conditional plan's prices are meaning.
            proposed = ((row.get("eligible") is True and quantity is not None and Decimal(quantity) > 0)
                        or (hypothetical is not None and Decimal(hypothetical) > 0))
            levels = [numeric(row.get(key)) for key in ("entry_price", "stop_price", "target_price")]
            geometry = (all(value is not None for value in levels)
                        and Decimal(levels[2]) > Decimal(levels[0]) > Decimal(levels[1]) > 0
                        and (Decimal(levels[2]) - Decimal(levels[0])) >= 2 * (Decimal(levels[0]) - Decimal(levels[1])))
            priced = proposed and geometry and row.get("price_evidence", {}).get("validated") is True
            drafts.append({"ticker": row.get("ticker", ""), "side": row.get("side", ""),
                           "eligible": row.get("eligible") is True,
                           "quantity": quantity, "hypothetical_quantity": hypothetical,
                           "blockers": sorted(set(row.get("blockers", []))),
                           "event_risk": row.get("event_risk") is True,
                           "entry_stop_target": levels if priced else None,
                           "order_type": row.get("order_type", "") if priced else None,
                           "time_in_force": row.get("time_in_force", "") if priced else None,
                           "holding_sessions_max": row.get("holding_sessions_max") if priced else None})
        orders = []
        order_review = tactical.get("open_orders", {})
        for row in order_review.get("orders", []):
            if not isinstance(row, dict):
                continue
            orders.append({key: numeric(row.get(key)) if key in {"quantity", "remaining_quantity", "limit_price"}
                           else row.get(key, "") for key in ("order_id", "ticker", "side", "quantity",
                           "remaining_quantity", "limit_price", "time_in_force", "expiration_date", "status", "review_status")})
        tactical_meaning = {"schema_version": tactical["schema_version"],
                            "blockers": sorted(set(tactical.get("blockers", []))),
                            "cash_basis": tactical.get("cash_basis"),
                            "risk_policy": tactical.get("risk_policy", {}),
                            "drafts": ordered(drafts), "orders": ordered(orders),
                            "orders_complete": order_review.get("complete") is True}
    return canonical_sha256({
        "version": "phase5r_recommendation_notification_v1", "decision_code": code,
        "gates": gates, "account_conflicts": conflicts, "cash_estimated": cash_estimated,
        "weakening_tickers": sorted(set(decision.get("fundamental_gate", {}).get("weakening_tickers", []))),
        "actions": ordered(actions), "watch_candidates": ordered(candidates),
        "held_research_warnings": ordered(research_warnings),
        "tactical_review": tactical_meaning,
    })


def notification_change_comparison(
    decision: dict[str, Any], prior_state: dict[str, Any], prior_decision: dict[str, Any]
) -> dict[str, Any]:
    current = recommendation_notification_fingerprint(decision)
    prior = prior_state.get("notification_change_fingerprint", "")
    source = "prior_state"
    anchor = prior_state.get("notification_change_anchor", "")
    if (prior_state.get("cycle_date") == decision.get("cycle_date")
            and isinstance(anchor, str) and len(anchor) == 64
            and all(char in "0123456789abcdef" for char in anchor)):
        prior = anchor
        source = "same_cycle_anchor"
    if not isinstance(prior, str) or len(prior) != 64 or any(char not in "0123456789abcdef" for char in prior):
        prior = ""
        source = "initial_baseline"
        if (isinstance(prior_decision, dict) and prior_decision.get("decision_code")
                and isinstance(prior_decision.get("held_positions"), list)
                and isinstance(prior_decision.get("watch_candidates"), list)
                and all(isinstance(prior_decision.get(key), dict)
                        for key in ("market_gate", "evidence_gate", "fundamental_gate", "account"))):
            prior = recommendation_notification_fingerprint(prior_decision)
            source = "prior_decision_migration"
    return {"fingerprint": current, "prior_fingerprint": prior,
            "changed": bool(prior) and current != prior, "comparison_source": source}


def notification_delivery_policy(
    *,
    is_weekend: bool,
    weekly_summary_due: bool,
    material_event: bool,
    decision_changed: bool,
    account_conflict: bool,
    fundamental_weakening: bool,
    first_material_baseline: bool,
    regular_delivery_mode: str = LEGACY_NOTIFICATION_MODE,
    notification_changed: bool = False,
) -> tuple[bool, str]:
    """Return event-driven eligibility independently of scheduler time."""

    if regular_delivery_mode == WATCH_ACTION_NOTIFICATION_MODE:
        return (notification_changed,
                "watch_or_action_changed" if notification_changed else "unchanged_watch_and_actions_suppressed")
    if regular_delivery_mode != LEGACY_NOTIFICATION_MODE:
        raise ValueError("notification_mode_invalid")
    if weekly_summary_due:
        return True, "friday_weekly_summary"
    if is_weekend:
        send = bool(material_event or decision_changed or account_conflict)
        return (
            send,
            "weekend_material_change" if send else "weekend_no_material_change",
        )
    send = bool(
        decision_changed
        or material_event
        or account_conflict
        or fundamental_weakening
        or first_material_baseline
    )
    return (
        send,
        "material_decision_change"
        if send
        else "unchanged_daily_email_suppressed",
    )


def weekly_summary_due_for_published_session(
    current: datetime,
    published_session: date,
) -> bool:
    """Schedule the Friday-close summary once, on its Saturday publication day."""

    return bool(
        published_session.weekday() == calendar.FRIDAY
        and current.date() == published_session + timedelta(days=1)
    )


def publish_automation_alert(*, component: str, reason: str) -> None:
    """Persist one terminal blocker and notify the logged-in owner once.

    The Notification Center text is fixed so neither provider output nor a
    secret can cross this boundary. The JSON artifact is the canonical alert;
    a best-effort local notification failure never changes scheduler control
    flow.
    """

    try:
        prior = read_json(AUTOMATION_ALERT_PATH, {})
    except (OSError, TypeError, ValueError):
        prior = {}
    already_notified = bool(
        prior.get("active") is True
        and prior.get("cycle_date") == cycle_date()
    )
    atomic_write_json(
        AUTOMATION_ALERT_PATH,
        {
            "schema_version": "phase5r_automation_alert_v1",
            "active": True,
            "cycle_date": cycle_date(),
            "created_at": prior.get("created_at", iso_now())
            if already_notified
            else iso_now(),
            "updated_at": iso_now(),
            "component": component,
            "reason": reason,
            "email_attempted": False,
            "broker_connected": False,
            "order_code_created": False,
        },
    )
    if already_notified:
        return
    try:
        subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                desktop_alert_script(),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def clear_automation_alert(*, component: str) -> None:
    """Clear any prior terminal alert after a completed daily decision."""

    try:
        prior = read_json(AUTOMATION_ALERT_PATH, {})
    except (OSError, TypeError, ValueError):
        prior = {}
    if prior.get("active") is not True:
        return
    atomic_write_json(
        AUTOMATION_ALERT_PATH,
        {
            **prior,
            "active": False,
            "cleared_at": iso_now(),
            "updated_at": iso_now(),
            "cleared_by": component,
        },
    )


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
