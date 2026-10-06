#!/usr/bin/env python3
"""Load the single active Phase 5R production configuration."""

from __future__ import annotations

import re
import math
from datetime import date
from pathlib import Path
from typing import Any

from daily_common import ROOT, read_json, LEGACY_NOTIFICATION_MODE, WATCH_ACTION_NOTIFICATION_MODE


ACTIVE_CONFIG_PATH = ROOT / "00_project_control" / "active_production_config.json"
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


RESEARCH_RISK_LIMIT_KEYS = {
    "active_stock_hard_cap_pct", "single_stock_default_cap_pct", "single_stock_hard_cap_pct",
}


def validate_research_risk_limits(value: Any) -> dict[str, float | None]:
    """Validate an optional research overlay without accepting financial data."""
    if not isinstance(value, dict) or set(value) != RESEARCH_RISK_LIMIT_KEYS:
        raise ActiveConfigError("research risk limits must contain exactly the three allowed cap fields")
    active = value["active_stock_hard_cap_pct"]
    if type(active) not in {int, float} or not math.isfinite(active) or not 0 < active <= 100:
        raise ActiveConfigError("active-stock hard cap must be a finite percentage in (0, 100]")
    name_caps = (value["single_stock_default_cap_pct"], value["single_stock_hard_cap_pct"])
    # JSON null explicitly removes the independent name limit. It is not a
    # disguised 70/100% cap; the aggregate sleeve and available funds still bind.
    if name_caps != (None, None):
        if any(type(item) not in {int, float} or not math.isfinite(item) for item in name_caps):
            raise ActiveConfigError("single-stock caps must both be null or finite numbers")
        if not 0 < name_caps[0] <= name_caps[1] <= active:
            raise ActiveConfigError("numeric caps require 0 < default <= single hard <= active hard <= 100")
    limits = {key: None if item is None else float(item) for key, item in value.items()}
    return limits


def validate_allocation_targets(account: dict[str, Any]) -> dict[str, float]:
    """Validate an explicitly configured target set and its broad-core floor.

    Empty legacy account sections have no overlay. A partial set is invalid,
    because combining new targets with stale account percentages is ambiguous.
    """
    if not isinstance(account, dict):
        raise ActiveConfigError("account configuration must be an object")
    names = ("core_target_pct", "active_target_pct", "cash_target_pct")
    if account.get("sizing_method") == "source_bound_company_allocation" and not all(
            name in account for name in (*names, "core_minimum_pct")):
        raise ActiveConfigError("source-bound sizing requires all three allocation targets and the core minimum")
    if not any(name in account for name in (*names, "core_minimum_pct")):
        return {}
    if not all(name in account for name in names):
        raise ActiveConfigError("all three allocation targets must be configured together")
    raw = {name: account[name] for name in names}
    if any(type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 100 for value in raw.values()):
        raise ActiveConfigError("allocation targets must be finite percentages")
    if not math.isclose(sum(raw.values()), 100, abs_tol=0.01):
        raise ActiveConfigError("allocation targets must sum to 100")
    result = {key: float(value) for key, value in raw.items()}
    if "core_minimum_pct" in account:
        minimum = account["core_minimum_pct"]
        if type(minimum) not in {int, float} or not math.isfinite(minimum) or not 0 <= minimum <= result["core_target_pct"]:
            raise ActiveConfigError("core minimum must be finite and no greater than the planning core target")
        result["core_minimum_pct"] = float(minimum)
    return result


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
    account = config.get("account", {})
    targets = validate_allocation_targets(account)
    research_budget = config.get("workflow", {}).get("objective_research_max_tickers", 3)
    if type(research_budget) is not int or not 1 <= research_budget <= 10:
        raise ActiveConfigError("objective research budget must be an integer from 1 to 10")
    if "research_risk_limits" in account:
        limits = validate_research_risk_limits(account["research_risk_limits"])
        if targets and targets["active_target_pct"] > limits["active_stock_hard_cap_pct"]:
            raise ActiveConfigError("active target cannot exceed the aggregate stock cap")
        if targets.get("core_minimum_pct", 0) + limits["active_stock_hard_cap_pct"] > 100:
            raise ActiveConfigError("core minimum plus aggregate stock cap cannot exceed 100")
        for name in ("single_stock_default_cap_pct", "single_stock_hard_cap_pct"):
            if name in account and account[name] != limits[name]:
                raise ActiveConfigError("top-level name caps must agree with the research policy")
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
    retry_slots = notifications.get("eod_publication_retry_slots_et")
    publication_after = str(
        notifications.get("market_data_publication_after_et", "")
    )
    send_after = str(notifications.get("send_after_et", ""))
    terminal_after = str(notifications.get("terminal_alert_after_et", ""))
    windows = notifications.get("delivery_windows_et")
    afternoon_slots = notifications.get("afternoon_refresh_slots_et")
    time_pattern = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
    if (
        notifications.get("event_driven") is not True
        or notifications.get("regular_delivery_mode", LEGACY_NOTIFICATION_MODE)
        not in {LEGACY_NOTIFICATION_MODE, WATCH_ACTION_NOTIFICATION_MODE}
        or notifications.get("weekly_summary_weekday") != "friday"
        or notifications.get("unchanged_daily_email") is not False
        or type(filing_lookback) is not int
        or filing_lookback not in range(1, 31)
        or not isinstance(retry_slots, list)
        or len(retry_slots) != 4
        or retry_slots != sorted(set(retry_slots))
        or any(
            not isinstance(value, str) or time_pattern.fullmatch(value) is None
            for value in retry_slots
        )
        or time_pattern.fullmatch(publication_after) is None
        or time_pattern.fullmatch(send_after) is None
        or time_pattern.fullmatch(terminal_after) is None
        or retry_slots[0] < publication_after
        or retry_slots[0] >= send_after
        or send_after >= terminal_after
    ):
        raise ActiveConfigError(
            "event-driven notification cadence is invalid"
        )
    if (
        windows != [
            {"id": "morning", "start": "09:30", "end": "10:30", "refresh_not_before": "08:00"},
            {"id": "afternoon", "start": "14:30", "end": "15:05", "refresh_not_before": "13:30"},
        ]
        or afternoon_slots != ["13:30", "14:00"]
        or send_after != windows[0]["start"]
        or terminal_after != windows[-1]["end"]
    ):
        raise ActiveConfigError("owner delivery windows do not match approved schedule")
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
