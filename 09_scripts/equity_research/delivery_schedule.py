"""Stable owner-attention windows; clocks never confer trading eligibility."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def configured_delivery_windows(notifications: dict[str, Any]) -> list[dict[str, str]]:
    """Return explicit windows, retaining one-window legacy configuration reads."""
    rows = notifications.get("delivery_windows_et")
    if rows is None:
        return [{"id": "legacy_daily", "start": notifications["send_after_et"],
                 "end": notifications["terminal_alert_after_et"], "refresh_not_before": "00:00"}]
    return [dict(row) for row in rows]


def active_delivery_window(notifications: dict[str, Any], current: datetime) -> dict[str, str] | None:
    local = current.astimezone(ET)
    if local.weekday() >= 5:
        return None
    clock = local.strftime("%H:%M")
    return next((row for row in configured_delivery_windows(notifications)
                 if row["start"] <= clock <= row["end"]), None)


def delivery_window_by_id(notifications: dict[str, Any], slot: str) -> dict[str, str] | None:
    return next((row for row in configured_delivery_windows(notifications) if row["id"] == slot), None)


def assessment_delivery_enabled(notifications: dict[str, Any], current: datetime, *, alerts: bool = False) -> bool:
    """The dated contract is opt-in; its activation never causes a catch-up send."""
    key = "intraday_alerts_enabled" if alerts else "mandatory_daily_briefs"
    if notifications.get(key) is not True or current.tzinfo is None:
        return False
    try:
        effective = date.fromisoformat(str(notifications.get("delivery_assessment_effective_from", "")))
    except ValueError:
        return False
    return current.astimezone(ET).date() >= effective


def intraday_alert_window_open(current: datetime) -> bool:
    """Use the actual regular session, including holidays and early closes."""
    from daily_common import is_us_market_session_date
    from investment_plans import regular_close
    if current.tzinfo is None:
        return False
    local = current.astimezone(ET)
    return (is_us_market_session_date(local.date())
            and datetime.combine(local.date(), time(9, 30), ET) <= local < regular_close(local.date().isoformat()))
