"""Versioned research plans and their current effective state.

Records are immutable, source-bound analyst decisions. Re-evaluation changes
their effective status, never their original content or a brokerage order.
Neither a daily HOLD nor an expired ticket silently changes a retained plan.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from daily_common import canonical_sha256, is_us_market_session_date

SCHEMA = "equity_investment_plans_v1"
RELATIVE_PATH = Path("05_risk_and_positions/investment_plans.local.json")
ROLES = {"broad_core", "long_term_growth", "tactical", "unclassified"}
HORIZON_ROLES = {"intraday_momentum": "tactical", "multi_day_trend": "tactical",
                 "long_term_growth": "long_term_growth", "broad_core": "broad_core"}
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


def _required_text(value: Any, fields: tuple[str, ...], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(label + "_required")
    for field in fields:
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(label + "_required_field:" + field)


def _bound_sources(value: dict[str, Any], row: dict[str, Any], label: str) -> None:
    """A narrative must cite receipts already verified by validate_record."""
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError(label + "_sources_required")
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("path"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", "")))
                or not any(source["path"] == item["path"] and source["sha256"] == item["sha256"]
                           for item in row["sources"])):
            raise ValueError(label + "_source_not_bound_to_record")


def _validate_purpose(row: dict[str, Any]) -> None:
    horizon = row.get("strategy_horizon")
    if horizon is None:
        if row.get("purpose") is not None:
            raise ValueError("plan_purpose_requires_strategy_horizon")
        return  # Legacy records are not retroactively reclassified.
    if not isinstance(horizon, str) or HORIZON_ROLES.get(horizon) != row["role"]:
        raise ValueError("plan_strategy_horizon_role_incompatible")
    purpose = row.get("purpose")
    _required_text(purpose, ("strategy", "holding_period_justification", "entry_validity",
                            "failure_condition", "exit_rule"), "plan_purpose")
    _bound_sources(purpose, row, "plan_purpose")
    if horizon == "intraday_momentum":
        effective = stamp(row["effective_at"])
        deadline = stamp(row["time_exit_at"])
        if (deadline.date() != effective.date()
                or deadline > regular_close(effective.date().isoformat())
                or stamp(row["review_at"]) > deadline
                or (row.get("valid_until") and stamp(row["valid_until"]) > deadline)
                or (row.get("order_draft") and row["order_draft"]["session_date"] != effective.date().isoformat())):
            raise ValueError("plan_intraday_same_session_exit_and_review_required")


def _validate_reassessment(row: dict[str, Any]) -> None:
    if "reassessment" not in row:
        return
    review = row["reassessment"]
    _required_text(review, ("previous_plan_id", "previous_record_hash", "reviewed_at", "reviewer",
                           "reason", "evidence_summary", "strategy_justification",
                           "holding_period_justification"), "plan_reassessment")
    if not re.fullmatch(r"[0-9a-f]{64}", review["previous_record_hash"]):
        raise ValueError("plan_reassessment_prior_hash_invalid")
    outcome = review.get("prior_outcome")
    _required_text(outcome, ("status", "detail"), "plan_reassessment_prior_outcome")
    if outcome["status"] not in {"active", "failed", "expired", "expired_and_failed",
                                  "completed", "cancelled", "superseded", "unverified"}:
        raise ValueError("plan_reassessment_prior_outcome_invalid")
    if stamp(review["reviewed_at"]) > stamp(row["recorded_at"]):
        raise ValueError("plan_reassessment_after_recording")
    _bound_sources(review, row, "plan_reassessment")


def _expired_at(row: dict[str, Any], current: datetime) -> bool:
    return (any(row.get(field) and current >= stamp(row[field])
                for field in ("time_exit_at", "valid_until"))
            or bool(row.get("order_draft") and current >= regular_close(row["order_draft"]["session_date"])))


def _validate_append_transition(payload: dict[str, Any], latest: dict[str, dict[str, Any]],
                                proposal: dict[str, Any]) -> None:
    """Prospective authoring rules; old, hash-valid histories remain readable."""
    prior = latest.get(proposal["plan_id"])
    other_active = [row for row in latest.values() if row["ticker"] == proposal["ticker"]
                    and row["plan_id"] != proposal["plan_id"] and row["state"] not in TERMINAL]
    if other_active and (prior is None or proposal["state"] not in TERMINAL):
        raise ValueError("plan_other_active_same_ticker_requires_reconciliation")
    ticker_prior = next((row for row in reversed(payload["records"])
                         if row["ticker"] == proposal["ticker"]), None)
    if prior is not None and ticker_prior is not None and prior["plan_id"] != ticker_prior["plan_id"]:
        if proposal["state"] not in TERMINAL:
            raise ValueError("plan_older_lineage_cannot_be_reopened")
    previous = prior or ticker_prior
    if previous is None:
        if proposal["role"] == "tactical" and proposal.get("strategy_horizon") is None:
            raise ValueError("plan_new_tactical_requires_strategy_horizon")
        if "reassessment" in proposal:
            raise ValueError("plan_reassessment_has_no_prior")
        return
    changed_purpose = (proposal["role"] != previous["role"]
                       or proposal.get("strategy_horizon") != previous.get("strategy_horizon")
                       or proposal.get("purpose") != previous.get("purpose"))
    extended = any(previous.get(field) and (not proposal.get(field)
                   or stamp(proposal[field]) > stamp(previous[field]))
                   for field in ("time_exit_at", "valid_until"))
    # Terminal records keep the outcome known at their own recording time.
    # An already-completed plan is not later relabeled expired by the clock.
    expired = _expired_at(previous, stamp(previous["recorded_at"])
                          if previous["state"] in TERMINAL else stamp(proposal["recorded_at"]))
    expired = expired or previous.get("setup_status") == "expired"
    failed = previous.get("setup_status") == "failed"
    overdue_review_renewed = (stamp(proposal["recorded_at"]) >= stamp(previous["review_at"])
                             and stamp(proposal["review_at"]) > stamp(previous["review_at"]))
    required = (changed_purpose or extended or expired or failed or overdue_review_renewed or prior is None
                or previous["state"] in TERMINAL)
    review = proposal.get("reassessment")
    if not review:
        if required:
            raise ValueError("plan_reassessment_required_for_purpose_or_validity_change")
        return
    if (review["previous_plan_id"] != previous["plan_id"]
            or review["previous_record_hash"] != previous["record_hash"]):
        raise ValueError("plan_reassessment_prior_identity_mismatch")
    if stamp(review["reviewed_at"]) < stamp(previous["recorded_at"]):
        raise ValueError("plan_reassessment_predates_prior")
    if expired and review["prior_outcome"]["status"] not in {"expired", "expired_and_failed"}:
        raise ValueError("plan_reassessment_must_preserve_expired_outcome")
    if failed and review["prior_outcome"]["status"] not in {"failed", "expired_and_failed"}:
        raise ValueError("plan_reassessment_must_preserve_failed_outcome")
    if changed_purpose or extended:
        # A legacy tactical plan must acquire an explicit supported horizon
        # before authoring a new purpose or lengthening its life.
        if proposal.get("strategy_horizon") is None:
            raise ValueError("plan_changed_purpose_or_extension_requires_strategy_horizon")


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
    if "setup_status" in row:
        if not isinstance(row["setup_status"], str) or row["setup_status"] not in {"active", "failed", "expired", "unverified"}:
            raise ValueError("plan_setup_status_invalid")
        _required_text(row, ("setup_status_reason",), "plan_setup_status")
    _validate_purpose(row)
    _validate_reassessment(row)


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
    _validate_append_transition(payload, latest, proposal)
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
    return [row for row in open_orders.get("orders", []) if isinstance(row, dict) and row.get("ticker") == ticker
            and isinstance(row.get("status"), str) and isinstance(row.get("side", ""), str)]


def _order_scopes(open_orders: Any, held: dict[str, int], current: datetime) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    """Bound shared cash/holdings separately from a named plan's execution work."""
    global_blockers: list[str] = []
    ticker_blockers: dict[str, list[str]] = {}
    strategy_blockers: dict[str, list[str]] = {}
    if not isinstance(open_orders, dict) or not isinstance(open_orders.get("orders"), list):
        return ["order_inventory_missing_or_invalid"], {}, {}
    try:
        observed = stamp(open_orders.get("as_of"))
        fresh = open_orders.get("complete") is True and timedelta(0) <= current-observed <= timedelta(hours=24)
        if is_us_market_session_date(current.date()) and current >= regular_close(current.date().isoformat()):
            fresh = fresh and observed >= regular_close(current.date().isoformat())
    except (ValueError, TypeError):
        fresh = False
    if not fresh:
        # A stale/incomplete whole inventory cannot exclude new BUY commitments.
        global_blockers.append("order_inventory_unverified_cannot_bound_buy_commitments")
    if open_orders.get("schema_version", "phase5r_open_orders_v1") != "phase5r_open_orders_v1":
        global_blockers.append("order_inventory_schema_invalid")
    seen: set[str] = set()
    reserved: dict[str, int] = {}
    sides: dict[str, set[str]] = {}
    for order in open_orders["orders"]:
        if not isinstance(order, dict):
            global_blockers.append("order_record_invalid")
            continue
        identity = order.get("order_id", order.get("id"))
        if identity is not None:
            identity = str(identity)
            if identity in seen:
                global_blockers.append("duplicate_or_contradictory_order_identity")
            seen.add(identity)
        ticker, status = order.get("ticker"), order.get("status")
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker):
            global_blockers.append("order_ticker_invalid")
            continue
        if not isinstance(status, str):
            global_blockers.append("order_status_or_side_unknown")
            continue
        if "side" in order and str(order["side"]).lower() not in {"buy", "sell"}:
            global_blockers.append("order_status_or_side_unknown")
            continue
        if status in {"cancelled", "canceled", "filled", "rejected", "expired"}:
            if "remaining_quantity" in order:
                try:
                    if _whole(order["remaining_quantity"]) != 0:
                        raise ValueError("terminal_order_has_remaining_quantity")
                except ValueError:
                    global_blockers.append("terminal_order_quantity_contradiction")
            continue
        side = str(order.get("side", "")).lower()
        if status not in {"open", "pending", "partial_fill", "partially_filled"} or side not in {"buy", "sell"}:
            global_blockers.append("order_status_or_side_unknown")
            continue
        try:
            remaining = _whole(order.get("remaining_quantity"))
            quantity = _whole(order.get("quantity"))
            if not identity or remaining <= 0 or remaining > quantity:
                raise ValueError("invalid_open_quantity")
        except ValueError:
            global_blockers.append("order_quantity_or_identity_unverified")
            continue
        sides.setdefault(ticker, set()).add(side)
        if side == "buy":
            # The canonical allocation does not net order reservations. Preserve
            # that shared-cash barrier instead of implicitly spending it twice.
            global_blockers.append("pending_buy_commitments_require_cash_reconciliation")
        else:
            reserved[ticker] = reserved.get(ticker, 0) + remaining
            ticker_blockers.setdefault(ticker, []).append("outstanding_sell_reserves_current_shares")
            # A fresh complete inventory can identify a still-unresolved old
            # sell without releasing any holdings or assuming sale proceeds.
            tif = order.get("time_in_force")
            try:
                expired = (current >= regular_close(order["session_date"]) if tif == "DAY"
                           else current.date() > date.fromisoformat(order["expiration_date"]) if tif == "GTD" else True)
                if expired:
                    ticker_blockers[ticker].append("sell_order_terminal_status_unverified")
            except (ValueError, TypeError, KeyError):
                ticker_blockers[ticker].append("sell_order_validity_unverified")
    if any(quantity > held.get(ticker, 0) for ticker, quantity in reserved.items()):
        global_blockers.append("sell_reservations_exceed_observed_holdings")
    if any(len(value) > 1 for value in sides.values()):
        global_blockers.append("contradictory_buy_sell_orders_require_reconciliation")
    try:
        risk = float(open_orders.get("existing_tactical_risk_usd"))
        risk_verified = (open_orders.get("existing_tactical_risk_confirmed") is True
                         and not isinstance(open_orders.get("existing_tactical_risk_usd"), bool)
                         and math.isfinite(risk) and risk >= 0)
    except (TypeError, ValueError):
        risk_verified = False
    if not risk_verified:
        strategy_blockers.setdefault("tactical", []).append("existing_tactical_risk_unconfirmed")
    if open_orders.get("cash_confirmed") is not True:
        strategy_blockers.setdefault("tactical", []).append("cash_not_confirmed_for_tactical_execution")
    return sorted(set(global_blockers)), ticker_blockers, strategy_blockers


def _finish_scopes(context: dict[str, Any]) -> None:
    context["global_blockers"] = sorted(set(context.get("global_blockers", [])))
    context["ticker_blockers"] = {ticker: sorted(set(codes)) for ticker, codes in sorted(context.get("ticker_blockers", {}).items()) if codes}
    context["strategy_blockers"] = {name: sorted(set(codes)) for name, codes in sorted(context.get("strategy_blockers", {}).items()) if codes}
    context["blocked_tickers"] = sorted(context["ticker_blockers"])
    context["unresolved_tickers"] = sorted(set(context.get("unresolved_tickers", [])) | set(context["blocked_tickers"]))
    context["block_new_capital"] = bool(context["global_blockers"])
    if context.get("status") not in {"invalid", "missing_or_invalid"}:
        context["status"] = "needs_reconciliation" if context["global_blockers"] or context["unresolved_tickers"] else "current"


def evaluate_plans(payload: dict[str, Any], positions: list[dict[str, Any]], *,
                   current: datetime, open_orders: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    current = stamp(current.isoformat())
    base = {"schema_version": "equity_plan_continuity_v1", "as_of": current.isoformat(),
            "automatic_action_allowed": False, "orders_verified_at": open_orders.get("as_of", "") if isinstance(open_orders, dict) else "",
            "plans": [], "conflicts": [], "unresolved_tickers": [], "block_new_capital": False,
            "global_blockers": [], "ticker_blockers": {}, "strategy_blockers": {}, "blocked_tickers": []}
    try:
        latest = validate_ledger(payload, root=root)
    except (ValueError, TypeError, OSError) as exc:
        base.update(status="invalid", conflicts=[str(exc)], block_new_capital=True, global_blockers=["plan_ledger_integrity_invalid"])
        return base
    try:
        held = {row["ticker"]: _whole(row.get("current_shares", row.get("shares_optional", 0))) for row in positions}
        if len(held) != len(positions) or any(not isinstance(ticker, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker) for ticker in held):
            raise ValueError("duplicate_or_invalid_position")
    except (ValueError, KeyError, TypeError):
        base.update(status="invalid", conflicts=["positions_invalid"], block_new_capital=True, global_blockers=["position_inventory_integrity_invalid"])
        return base
    base["global_blockers"], base["ticker_blockers"], base["strategy_blockers"] = _order_scopes(open_orders, held, current)
    if not isinstance(open_orders, dict) or not isinstance(open_orders.get("orders"), list):
        open_orders = {"orders": [], "complete": False}
    active: dict[str, list[dict[str, Any]]] = {}
    for row in latest.values():
        if stamp(row["recorded_at"]) > current or stamp(row["effective_at"]) > current:
            base["conflicts"].append(row["ticker"] + ":future_plan_record")
            base["ticker_blockers"].setdefault(row["ticker"], []).append("future_plan_record")
            continue
        if row["state"] not in TERMINAL:
            active.setdefault(row["ticker"], []).append(row)
    for ticker, rows in sorted(active.items()):
        if len(rows) > 1:
            base["conflicts"].append(ticker + ":multiple_active_plans")
            base["ticker_blockers"].setdefault(ticker, []).append("multiple_active_plans")
    for ticker in sorted(set(held) | set(active)):
        rows = active.get(ticker, [])
        if len(rows) != 1:
            base["ticker_blockers"].setdefault(ticker, []).append("plan_conflict" if rows else "plan_unrecorded")
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
        elif row.get("setup_status") == "failed":
            status = "failed_setup_pending_review"
        elif row.get("setup_status") == "expired":
            status = "expired_pending_verification"
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
        if row["role"] == "tactical":
            reasons.extend(base["strategy_blockers"].get("tactical", []))
        labels = {
            "maintained": "保留研究计划",
            "failed_setup_pending_review": "研究记录已确认原方案失效；保留失败记录，重新评估后才能更改持仓目的或续期",
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
        effective = {key: row.get(key) for key in ("plan_id", "version", "record_hash", "ticker", "role", "reason", "counterargument", "change_reason", "review_at", "time_exit_at", "thesis_id", "account_observed_at", "sources", "strategy_horizon", "purpose", "setup_status", "setup_status_reason", "reassessment")}
        effective.update(status=status, action=row["action"] if status == "maintained" else "reconcile_plan",
                         instruction=instruction, historical_instruction=row["instruction"],
                         current_shares=quantity, eligible_quantity=0, proposed_change_shares=row["proposed_change_shares"],
                         historical_order_draft=draft, observed_orders=observations, blockers=sorted(set(reasons)),
                         validity="research_only_requires_current_verification", automatic_action_allowed=False)
        base["plans"].append(effective)
        if status != "completed_observed" and (status != "maintained" or reasons):
            base["unresolved_tickers"].append(ticker)
            base["ticker_blockers"].setdefault(ticker, []).extend(reasons)
            if status != "maintained":
                base["ticker_blockers"][ticker].append(status)
    _finish_scopes(base)
    base["ledger_head"] = payload["records"][-1]["record_hash"] if payload["records"] else ""
    base["semantic_fingerprint"] = canonical_sha256(semantic_state(base))
    return base


def semantic_state(context: dict[str, Any]) -> dict[str, Any]:
    return {"status": context.get("status"), "conflicts": context.get("conflicts", []),
            "global_blockers": context.get("global_blockers", []), "ticker_blockers": context.get("ticker_blockers", {}),
            "strategy_blockers": context.get("strategy_blockers", {}),
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
                "global_blockers": ["plan_or_order_inputs_unavailable"], "ticker_blockers": {}, "strategy_blockers": {}, "blocked_tickers": [],
                "automatic_action_allowed": False}
    context = evaluate_plans(payload, positions, current=current, open_orders=orders, root=root)
    from account_feedback_gate import feedback_blocker
    blocker=feedback_blocker(root)
    if blocker:
        context['global_blockers']=sorted(set(context.get('global_blockers',[])+[blocker]))
        context['conflicts'].append(blocker)
        for plan in context.get('plans',[]):
            if plan.get('status')=='completed_observed': continue
            plan.update(status='account_feedback_pending_verification',action='reconcile_plan',eligible_quantity=0,order_draft=None,
                instruction='用户报告的账户事实尚待补全或恢复；先核对实际现金、股数和挂单，历史委托条件暂停。',
                blockers=sorted(set(plan.get('blockers',[])+[blocker])))
        _finish_scopes(context)
    return context


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
                context.setdefault("ticker_blockers", {}).setdefault(row["ticker"], []).append("baseline_risk_review_requires_merge")
    # Legacy callers with an explicitly global block retain that conservative
    # interpretation until a scoped context has been recomputed.
    if "global_blockers" not in context and context.get("block_new_capital"):
        context["global_blockers"] = ["legacy_plan_scope_unverified"]
    _finish_scopes(context)
    context["semantic_fingerprint"] = canonical_sha256(semantic_state(context))


def render_plan_lines(context: dict[str, Any]) -> list[str]:
    lines = ["当前计划状态：" + context.get("status", "missing") + "；历史价格/草案不自动续期。"]
    for row in context.get("plans", []):
        purpose = row.get("role", "unclassified")
        if row.get("strategy_horizon"):
            purpose += " / " + row["strategy_horizon"]
        lines.append(f"{row['ticker']} · {purpose} · {row.get('plan_id') or '未建档'} v{row.get('version') or '?'}：{row['instruction']}")
    if context.get("conflicts"):
        lines.append("计划校验冲突：" + "; ".join(context["conflicts"]))
    return lines
