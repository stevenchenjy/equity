"""Stable owner-attention windows; clocks never confer trading eligibility."""
from __future__ import annotations

from datetime import datetime
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
