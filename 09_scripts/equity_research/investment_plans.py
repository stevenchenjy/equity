"""Versioned research plans and their current effective state.

Records are immutable, source-bound analyst decisions. Re-evaluation changes
their effective status, never their original content or a brokerage order.
Neither a daily HOLD nor an expired ticket silently changes a retained plan.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from daily_common import canonical_sha256, is_us_market_session_date

SCHEMA = "equity_investment_plans_v1"
RELATIVE_PATH = Path("05_risk_and_positions/investment_plans.local.json")
ROLES = {"broad_core", "long_term_growth", "tactical", "unclassified"}
ACTIONS = {"hold", "protect_review", "exit_review", "trim_review", "watch"}
TERMINAL = {"completed", "cancelled", "superseded"}
ET = ZoneInfo("America/New_York")
# NYSE published calendar, verified 2026-09-24. Exceptional closures require
# a source update. Unsupported years cannot validate a DAY draft.
CALENDAR_SOURCE = "https://www.nyse.com/markets/hours-calendars"
EARLY_CLOSES = {"2025-07-03", "2025-11-28", "2025-12-24", "2026-11-27",
                "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}


def stamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("plan_timestamp_invalid") from exc
    if result.tzinfo is None:
        raise ValueError("plan_timestamp_timezone_required")
    return result.astimezone(ET)


def regular_close(session: str) -> datetime:
    day = date.fromisoformat(session)
    if day.year not in {2025, 2026, 2027, 2028} or not is_us_market_session_date(day):
        raise ValueError("plan_session_calendar_unverified")
    return datetime.combine(day, time(13 if session in EARLY_CLOSES else 16), ET)


def _whole(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("plan_quantity_invalid")
    try:
        number = float(value)
        if number < 0 or not number.is_integer():
            raise ValueError
        return int(number)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("plan_quantity_invalid") from exc


def validate_record(row: dict[str, Any], *, root: Path | None = None) -> None:
    if not isinstance(row, dict):
        raise ValueError("plan_record_invalid")
    for key in ("plan_id", "ticker", "role", "action", "recorded_at", "effective_at",
                "review_at", "reason", "counterargument", "reviewer", "change_reason",
                "account_observed_at", "instruction", "state"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError("plan_required_field:" + key)
    if (not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", row["ticker"])
            or not re.fullmatch(r"[A-Za-z0-9_.\-]{1,100}", row["plan_id"])
            or row["role"] not in ROLES or row["action"] not in ACTIONS
            or row["state"] not in {"proposed", "maintained", *TERMINAL}
            or row.get("automatic_action_allowed") is not False):
        raise ValueError("plan_identity_or_authority_invalid")
    recorded = stamp(row["recorded_at"])
    if stamp(row["effective_at"]) > recorded or stamp(row["account_observed_at"]) > recorded:
        raise ValueError("plan_observation_after_recording")
    if stamp(row["review_at"]) < stamp(row["effective_at"]):
        raise ValueError("plan_review_before_effective")
    expected = _whole(row.get("expected_shares"))
    quantity = _whole(row.get("proposed_change_shares"))
    if quantity > expected or (row["action"] in {"hold", "watch"} and quantity):
        raise ValueError("plan_change_exceeds_position")
    if row["role"] == "tactical" and not row.get("time_exit_at"):
        raise ValueError("tactical_time_exit_required")
    if row.get("time_exit_at"):
        deadline = stamp(row["time_exit_at"])
        if deadline > regular_close(deadline.date().isoformat()):
            raise ValueError("plan_deadline_after_regular_close")
        if deadline < datetime.combine(deadline.date(), time(9, 30), ET) or deadline < stamp(row["effective_at"]):
            raise ValueError("plan_deadline_before_session_or_effective_time")
    if row.get("valid_until"):
        stamp(row["valid_until"])
    draft = row.get("order_draft")
    if draft:
        if (not isinstance(draft, dict) or draft.get("side") != "sell"
                or draft.get("type") not in {"LIMIT", "STOP", "MARKETABLE_LIMIT"}
                or draft.get("time_in_force") != "DAY"
                or _whole(draft.get("quantity")) != quantity or quantity == 0):
            raise ValueError("plan_draft_invalid")
        regular_close(draft.get("session_date", ""))
        for field in ("limit_price", "stop_price"):
            if draft.get(field) is not None:
                from math import isfinite
                price = float(draft[field])
                if not isfinite(price) or price <= 0:
                    raise ValueError("plan_price_invalid")
        if draft["type"] == "STOP" and draft.get("stop_price") is None:
            raise ValueError("plan_stop_missing")
        if draft["type"] == "LIMIT" and draft.get("limit_price") is None:
            raise ValueError("plan_limit_missing")
    evidence = row.get("sources")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("plan_sources_required")
    for source in evidence:
        if (not isinstance(source, dict) or not isinstance(source.get("path"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", "")))):
            raise ValueError("plan_source_invalid")
        path = Path(source["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("plan_source_path_invalid")
        if root is not None:
            target = (root / path).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                raise ValueError("plan_source_missing")
            if hashlib.sha256(target.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("plan_source_hash_mismatch")


def validate_ledger(payload: dict[str, Any], *, root: Path | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA or not isinstance(payload.get("records"), list):
        raise ValueError("plan_ledger_schema_invalid")
    latest: dict[str, dict[str, Any]] = {}
    chain = ""
    for row in payload["records"]:
        validate_record(row, root=root)
        prior = latest.get(row["plan_id"])
        if (row.get("version") != (prior["version"] + 1 if prior else 1)
                or row.get("supersedes") != (prior["record_hash"] if prior else None)
                or row.get("previous_hash") != chain):
            raise ValueError("plan_version_chain_invalid")
        expected = canonical_sha256({key: value for key, value in row.items() if key != "record_hash"})
        if row.get("record_hash") != expected:
            raise ValueError("plan_record_hash_invalid")
        if prior and (row["ticker"] != prior["ticker"] or stamp(row["recorded_at"]) < stamp(prior["recorded_at"])):
            raise ValueError("plan_identity_or_time_changed")
        latest[row["plan_id"]] = row
        chain = expected
    return latest


def append_plan(payload: dict[str, Any], proposal: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    latest = validate_ledger(payload, root=root)
    if any(key in proposal for key in ("version", "record_hash", "previous_hash", "supersedes")):
        raise ValueError("plan_writer_owns_version_fields")
    validate_record(proposal, root=root)
    prior = latest.get(proposal["plan_id"])
    row = copy.deepcopy(proposal)
    row["expected_shares"] = _whole(row["expected_shares"])
    row["proposed_change_shares"] = _whole(row["proposed_change_shares"])
    row.update(version=prior["version"] + 1 if prior else 1,
               supersedes=prior["record_hash"] if prior else None,
               previous_hash=payload["records"][-1]["record_hash"] if payload["records"] else "")
    row["record_hash"] = canonical_sha256(row)
    result = {"schema_version": SCHEMA, "records": [*payload["records"], row]}
    validate_ledger(result, root=root)
    return result


def _observed_orders(open_orders: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    return [row for row in open_orders.get("orders", []) if isinstance(row, dict) and row.get("ticker") == ticker]


def evaluate_plans(payload: dict[str, Any], positions: list[dict[str, Any]], *,
                   current: datetime, open_orders: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    current = stamp(current.isoformat())
    base = {"schema_version": "equity_plan_continuity_v1", "as_of": current.isoformat(),
            "automatic_action_allowed": False, "orders_verified_at": open_orders.get("as_of", ""),
            "plans": [], "conflicts": [], "unresolved_tickers": [], "block_new_capital": False}
    try:
        latest = validate_ledger(payload, root=root)
    except (ValueError, TypeError, OSError) as exc:
        base.update(status="invalid", conflicts=[str(exc)], block_new_capital=True)
        return base
    held = {row["ticker"]: _whole(row.get("current_shares", row.get("shares_optional", 0))) for row in positions}
    active: dict[str, list[dict[str, Any]]] = {}
    for row in latest.values():
        if stamp(row["recorded_at"]) > current or stamp(row["effective_at"]) > current:
            base["conflicts"].append(row["ticker"] + ":future_plan_record")
            continue
        if row["state"] not in TERMINAL:
            active.setdefault(row["ticker"], []).append(row)
    for ticker, rows in sorted(active.items()):
        if len(rows) > 1:
            base["conflicts"].append(ticker + ":multiple_active_plans")
    for ticker in sorted(set(held) | set(active)):
        rows = active.get(ticker, [])
        if len(rows) != 1:
            base["unresolved_tickers"].append(ticker)
            base["plans"].append({"ticker": ticker, "status": "conflict" if rows else "unrecorded",
                "role": "unclassified", "action": "reconcile_plan", "instruction": "研究计划缺失或冲突；先核对，不生成新增股数。",
                "eligible_quantity": 0, "current_shares": held.get(ticker, 0), "historical_instruction": ""})
            continue
        row = rows[0]
        quantity = held.get(ticker, 0)
        draft = row.get("order_draft") or {}
        observations = _observed_orders(open_orders, ticker)
        linked = next((x for x in observations if str(x.get("order_id", x.get("id", ""))) == str(row.get("broker_order_id", "__none__"))), None)
        status = "maintained"
        reasons: list[str] = []
        if not quantity:
            # Absence of a holding alone never proves an execution.
            try:
                observed_at = stamp(open_orders.get("as_of"))
                confirmed_close = (open_orders.get("complete") is True and linked is not None
                    and linked.get("status") == "filled" and linked.get("side", "").lower() == "sell"
                    and _whole(linked.get("quantity")) == row["expected_shares"]
                    and _whole(linked.get("remaining_quantity")) == 0
                    and stamp(row["account_observed_at"]) <= observed_at <= current)
            except (ValueError, TypeError):
                confirmed_close = False
            status = "completed_observed" if confirmed_close else "position_absent_pending_verification"
        elif quantity != row["expected_shares"]:
            status = "position_changed_pending_verification"
            reasons.append("remaining_quantity_changed")
        elif row.get("time_exit_at") and current >= stamp(row["time_exit_at"]):
            status = "time_exit_due_pending_verification"
        elif row.get("valid_until") and current >= stamp(row["valid_until"]):
            status = "expired_pending_verification"
        elif draft and current >= regular_close(draft["session_date"]):
            status = "expired_pending_verification"
        elif current >= stamp(row["review_at"]):
            status = "review_due"
        if linked and linked.get("status") in {"cancelled", "canceled", "rejected", "expired"} and quantity:
            reasons.append("linked_order_terminal_plan_needs_review")
            if status == "maintained":
                status = "order_changed_pending_review"
        outstanding = [x for x in observations if x.get("status") in {"open", "pending", "partial_fill", "partially_filled"} and x.get("side", "").lower() == "sell"]
        other_orders = [x for x in outstanding if x is not linked]
        if other_orders and (row["action"] != "hold" or not quantity):
            reasons.append("other_sell_order_reserves_shares")
            if status in {"maintained", "completed_observed"}:
                status = "order_conflict_pending_review"
        try:
            order_stamp = stamp(open_orders.get("as_of"))
            orders_fresh = open_orders.get("complete") is True and timedelta(0) <= current - order_stamp <= timedelta(hours=24)
            if is_us_market_session_date(current.date()) and current >= regular_close(current.date().isoformat()):
                orders_fresh = orders_fresh and order_stamp >= regular_close(current.date().isoformat())
        except (ValueError, TypeError):
            orders_fresh = False
        if not orders_fresh:
            reasons.append("order_snapshot_requires_recheck")
        if row["action"] != "hold":
            reasons.append("fresh_quote_and_available_shares_required")
        labels = {
            "maintained": "保留研究计划",
            "expired_pending_verification": "旧方案已到期；成交/撤单及剩余持仓待核对，不续用旧报价",
            "time_exit_due_pending_verification": "原定时间退出期限已到；先核对实际成交及剩余持仓，不顺延期限",
            "position_changed_pending_verification": "持仓数量变化；核对成交并修订计划后再形成数量方案",
            "position_absent_pending_verification": "记录中已无持仓；核对成交来源，停止显示旧卖出方案",
            "completed_observed": "关联卖出已记录成交，且当前已无持仓；旧方案结束",
            "review_due": "计划复核到期；保留原依据，等待当前证据复核",
            "order_changed_pending_review": "关联订单状态改变；先核对并更新计划",
            "order_conflict_pending_review": "已有其他卖单占用持仓；不得叠加独立卖出方案",
        }
        instruction = row["instruction"] if status == "maintained" else labels[status]
        if status == "maintained" and row["action"] != "hold":
            instruction += "；仅为未提交的研究计划，先核验报价、订单和剩余股数。"
        if row.get("time_exit_at") and quantity:
            instruction += " 原定时间退出/复核：" + row["time_exit_at"] + "。"
        effective = {key: row.get(key) for key in ("plan_id", "version", "record_hash", "ticker", "role", "reason", "counterargument", "change_reason", "review_at", "time_exit_at", "thesis_id", "account_observed_at", "sources")}
        effective.update(status=status, action=row["action"] if status == "maintained" else "reconcile_plan",
                         instruction=instruction, historical_instruction=row["instruction"],
                         current_shares=quantity, eligible_quantity=0, proposed_change_shares=row["proposed_change_shares"],
                         historical_order_draft=draft, observed_orders=observations, blockers=sorted(set(reasons)),
                         validity="research_only_requires_current_verification", automatic_action_allowed=False)
        base["plans"].append(effective)
        if status != "completed_observed" and (status != "maintained" or reasons):
            base["unresolved_tickers"].append(ticker)
    base["unresolved_tickers"] = sorted(set(base["unresolved_tickers"]))
    base["block_new_capital"] = bool(base["conflicts"] or base["unresolved_tickers"])
    base["status"] = "needs_reconciliation" if base["block_new_capital"] else "current"
    base["ledger_head"] = payload["records"][-1]["record_hash"] if payload["records"] else ""
    base["semantic_fingerprint"] = canonical_sha256(semantic_state(base))
    return base


def semantic_state(context: dict[str, Any]) -> dict[str, Any]:
    return {"status": context.get("status"), "conflicts": context.get("conflicts", []),
            "plans": [{key: row.get(key) for key in ("ticker", "plan_id", "version", "record_hash", "role", "status", "action", "current_shares", "review_at", "time_exit_at", "blockers")}
                      for row in context.get("plans", [])]}


def load_plan_context(root: Path, positions: list[dict[str, Any]], current: datetime) -> dict[str, Any]:
    try:
        payload = json.loads((root / RELATIVE_PATH).read_text())
        orders = json.loads((root / "05_risk_and_positions/current_open_orders.local.json").read_text())
    except (OSError, ValueError) as exc:
        return {"schema_version": "equity_plan_continuity_v1", "status": "missing_or_invalid",
                "as_of": current.isoformat(), "plans": [], "conflicts": [type(exc).__name__ + ":plan_inputs_unavailable"],
                "unresolved_tickers": [row["ticker"] for row in positions], "block_new_capital": True,
                "automatic_action_allowed": False}
    return evaluate_plans(payload, positions, current=current, open_orders=orders, root=root)


def apply_plan_context(held_rows: list[dict[str, Any]], context: dict[str, Any]) -> None:
    """Project one current instruction; retain prior arithmetic as diagnostics."""
    plans = {row["ticker"]: row for row in context.get("plans", [])}
    for row in held_rows:
        prior = {key: row.get(key) for key in ("action", "reason", "whole_shares_to_change", "target_shares", "invalidation")}
        plan = plans.get(row["ticker"])
        row["baseline_research"] = prior
        row["action"] = "maintained_plan_review"
        row["whole_shares_to_change"] = "0"
        row["target_shares"] = row.get("current_shares", "0")
        row["human_confirmation_required"] = "no"
        row["reason"] = plan["instruction"] if plan else "计划资料缺失或冲突；先核对，不生成新数量方案。"
        row["current_instruction"] = row["reason"]
        row["plan_status"] = plan.get("status", "missing") if plan else "missing"
        row["plan_id"] = plan.get("plan_id") if plan else None
        row["plan_version"] = plan.get("version") if plan else None
        row["invalidation"] = row["reason"]
        if any(word in str(prior.get("action", "")) for word in ("trim", "exit", "reduce", "sell")):
            if not plan or plan.get("action") not in {"exit_review", "trim_review"}:
                row["reason"] += " 原有集中度或投资逻辑风险规则也提出复核；需合并核验，不能被计划中的持有结论覆盖。"
                row["current_instruction"] = row["reason"]
                row["invalidation"] = row["reason"]
                context["conflicts"].append(row["ticker"] + ":baseline_risk_review_requires_merge")
                context["block_new_capital"] = True
                context["status"] = "needs_reconciliation"
    context["semantic_fingerprint"] = canonical_sha256(semantic_state(context))


def render_plan_lines(context: dict[str, Any]) -> list[str]:
    lines = ["当前计划状态：" + context.get("status", "missing") + "；历史价格/草案不自动续期。"]
    for row in context.get("plans", []):
        lines.append(f"{row['ticker']} · {row.get('role', 'unclassified')} · {row.get('plan_id') or '未建档'} v{row.get('version') or '?'}：{row['instruction']}")
    if context.get("conflicts"):
        lines.append("计划校验冲突：" + "; ".join(context["conflicts"]))
    return lines
