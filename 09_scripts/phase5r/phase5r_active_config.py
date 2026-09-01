#!/usr/bin/env python3
"""Load the single active Phase 5R production configuration."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from phase5r_daily_common import ROOT, read_json


ACTIVE_CONFIG_PATH = ROOT / "00_project_control" / "phase5r_active_production_config.json"
_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "effective_from",
    "review_by",
    "authority",
    "workflow",
    "account",
    "notifications",
    "model_policy",
    "outcome_tracking",
    "boundaries",
}


class ActiveConfigError(ValueError):
    """Raised when the active configuration is unsafe or incomplete."""


def load_active_config(path: Path = ACTIVE_CONFIG_PATH) -> dict[str, Any]:
    config = read_json(path)
    if not isinstance(config, dict) or set(config) != _REQUIRED_TOP_LEVEL:
        raise ActiveConfigError("active production configuration fields do not match contract")
    if config.get("schema_version") != "phase5r_active_production_config_v1":
        raise ActiveConfigError("unsupported active production configuration")
    try:
        effective = date.fromisoformat(str(config["effective_from"]))
        review_by = date.fromisoformat(str(config["review_by"]))
    except ValueError as exc:
        raise ActiveConfigError("configuration dates must be ISO dates") from exc
    if review_by < effective:
        raise ActiveConfigError("review_by cannot precede effective_from")
    boundaries = config.get("boundaries", {})
    if boundaries.get("research_only") is not True:
        raise ActiveConfigError("research_only must remain true")
    for field in (
        "broker_connected",
        "broker_account_read",
        "automatic_action_allowed",
        "order_code_created",
        "trade_placed",
    ):
        if boundaries.get(field) is not False:
            raise ActiveConfigError(f"{field} must remain false")
    policy = config.get("model_policy", {})
    if (
        policy.get("status") != "removed_from_active_production"
        or policy.get("active") is not False
        or policy.get("calls_allowed") is not False
        or policy.get("default_action") != "no_call"
        or float(policy.get("monthly_hard_cap_usd", -1)) != 0.0
        or int(policy.get("actual_calls", -1)) != 0
        or float(policy.get("metered_cost_usd", -1)) != 0.0
    ):
        raise ActiveConfigError("model path must remain removed with zero calls and cost")
    notifications = config.get("notifications", {})
    filing_lookback = notifications.get("new_filing_lookback_calendar_days")
    retry_slots = notifications.get("post_close_refresh_retry_slots_et")
    time_pattern = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
    if (
        notifications.get("event_driven") is not True
        or type(filing_lookback) is not int
        or filing_lookback not in range(1, 31)
        or not isinstance(retry_slots, list)
        or len(retry_slots) != 4
        or retry_slots != sorted(set(retry_slots))
        or any(
            not isinstance(value, str) or time_pattern.fullmatch(value) is None
            for value in retry_slots
        )
        or time_pattern.fullmatch(str(notifications.get("send_after_et", "")))
        is None
        or time_pattern.fullmatch(
            str(notifications.get("terminal_alert_after_et", ""))
        )
        is None
    ):
        raise ActiveConfigError(
            "event-driven notification cadence is invalid"
        )
    return config


def main() -> int:
    config = load_active_config()
    print(
        "active_config_valid=true "
        f"schema={config['schema_version']} "
        f"monthly_model_cap_usd={config['model_policy']['monthly_hard_cap_usd']} "
        "broker_connected=false automatic_action_allowed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
