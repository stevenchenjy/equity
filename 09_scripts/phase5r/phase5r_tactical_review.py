"""Offline, fail-closed short-horizon research layered below canonical eligibility.

No new signal can grant canonical eligibility. The sidecar is populated only by
the existing public EOD collector and is bound to the exact snapshot bytes.
Neither this module nor its output connects to a broker or submits an order.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from phase5r_daily_common import (
    ROOT, MARKET_SNAPSHOT_PATH, read_json, sha256_file,
    is_us_market_session_date, last_completed_market_session,
)

POLICY_PATH = ROOT / "01_policies/tactical_trade_policy.json"
HISTORY_PATH = ROOT / "03_source_data/phase5r/phase5r_tactical_price_history.local.json"
ORDERS_PATH = ROOT / "05_risk_and_positions/current_open_orders.local.json"
SCHEMA_VERSION = "phase5r_tactical_review_v1"
HISTORY_SCHEMA = "phase5r_tactical_price_history_v1"
CASH_CONFIRMED_BASES = {"confirmed", "broker_confirmed", "owner_confirmed", "confirmed_available_cash"}
HYPOTHETICAL_BLOCKERS = {"cash_not_confirmed", "existing_tactical_risk_unconfirmed",
                         "open_orders_unconfirmed", "event_calendar_unconfirmed",
                         "existing_order_requires_reconciliation"}
FOUR_RULES = [
    "Each ordinary trade risks at most 0.5% of account value; event exposure at most 0.25%; combined tactical planned risk at most 2% and each name at most 5% of capital.",
    "Before entry, record a dated entry, observed invalidation, observed target, at least 2R, whole-share quantity and confirmed funds; a watch level is not an order.",
    "Exit/review no later than the fifth regular session, sooner on invalidation; never relabel a failed trade as a one-year core holding. Stops may slip or fail to fill.",
    "Recheck events, quotes and pending orders before submission; a DAY draft expires with its named session. Re-entry requires a fresh canonical review and newly valid setup, never automatic averaging down.",
]


def _number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _positive(value: Any) -> Decimal | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _integer(value: Any) -> int:
    result = _number(value)
    return int(result) if result is not None and result >= 0 and result == result.to_integral_value() else 0


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def _sessions_after(day: date, count: int = 1) -> date:
    for _ in range(count):
        day += timedelta(days=1)
        while not is_us_market_session_date(day):
            day += timedelta(days=1)
    return day


def _last_sessions(end: date, count: int) -> list[str]:
    result: list[str] = []
    while len(result) < count:
        if is_us_market_session_date(end):
            result.append(end.isoformat())
        end -= timedelta(days=1)
    return list(reversed(result))


def _money(value: Decimal | None) -> float | None:
    return float(value.quantize(Decimal("0.01"))) if value is not None else None


def review_open_orders(payload: dict[str, Any], current: datetime, session: date) -> dict[str, Any]:
    stamp = _stamp(payload.get("as_of"))
    completed_close = datetime.combine(last_completed_market_session(current), time(16),
                                       tzinfo=ZoneInfo("America/New_York"))
    fresh = bool(stamp and timedelta(0) <= current - stamp <= timedelta(hours=24)
                 and stamp >= completed_close)
    complete = (payload.get("schema_version") == "phase5r_open_orders_v1"
                and isinstance(payload.get("orders"), list)
                and payload.get("complete") is True and fresh)
    rows = []
    reserve = Decimal(0)
    active_tickers: set[str] = set()
    for raw in payload.get("orders", []) if isinstance(payload.get("orders"), list) else []:
        if not isinstance(raw, dict):
            complete = False
            continue
        row = dict(raw)
        ticker = str(row.get("ticker", "")).upper()
        status = str(row.get("status", "unknown")).lower()
        tif = str(row.get("time_in_force", "")).upper()
        row["review_status"] = status
        row["review_reason"] = "Historical status as reported; never proof of a fill."
        remaining = _number(row.get("remaining_quantity"))
        price = _positive(row.get("limit_price"))
        if status in {"open", "partial_fill", "partially_filled", "pending"}:
            active_tickers.add(ticker)
            expired = ((tif == "DAY" and (_day(row.get("session_date")) or date.min) < session)
                       or (tif == "GTD" and (_day(row.get("expiration_date")) or date.min) < session))
            if expired:
                row["review_status"] = "expired_pending_verification"
                row["review_reason"] = "Named session/date has passed; verify terminal status and any fills before replacement."
                complete = False
            elif (tif not in {"DAY", "GTD"} or remaining is None or remaining <= 0
                  or remaining != remaining.to_integral_value() or not ticker
                  or str(row.get("side", "")).lower() not in {"buy", "sell"}):
                row["review_status"] = "unknown_pending_verification"
                complete = False
            if str(row.get("side", "")).lower() == "buy":
                if price is None or remaining is None or remaining <= 0:
                    complete = False
                else:
                    reservation = price * remaining
                    reserve += reservation
                    row["cash_reservation_usd"] = _money(reservation)
        elif status not in {"cancelled", "canceled", "filled", "rejected", "expired"}:
            complete = False
            active_tickers.add(ticker)
        rows.append(row)
    return {"as_of": payload.get("as_of", ""), "source": payload.get("source", ""),
            "complete": complete, "status": "verified_snapshot" if complete else "unconfirmed_snapshot",
            "orders": rows, "cash_reservation_usd": _money(reserve), "active_tickers": sorted(active_tickers)}


def _validated_bars(history: dict[str, Any], ticker: str, session: date,
                    snapshot_hash: str, close: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if (history.get("schema_version") != HISTORY_SCHEMA or history.get("validated") is not True
            or len(snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in snapshot_hash)
            or history.get("snapshot_sha256") != snapshot_hash
            or history.get("market_session") != session.isoformat()):
        return [], ["price_history_missing_or_unbound"]
    tickers = history.get("tickers", {})
    if not isinstance(tickers, dict):
        return [], ["price_history_malformed"]
    series = tickers.get(ticker, {})
    bars = series.get("bars", []) if isinstance(series, dict) else []
    if not isinstance(bars, list) or len(bars) < 20:
        return [], ["price_history_incomplete"]
    bars = bars[-20:]
    if any(not isinstance(bar, dict) for bar in bars):
        return [], ["price_history_malformed"]
    if [bar.get("session_date") for bar in bars] != _last_sessions(session, 20):
        return [], ["price_history_session_mismatch"]
    for bar in bars:
        values = {key: _positive(bar.get(key)) for key in ("open", "high", "low", "close")}
        volume = _number(bar.get("volume"))
        if (any(value is None for value in values.values()) or volume is None or volume < 0
                or not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]):
            return [], ["price_history_invalid_ohlc"]
    actual_close = _positive(close)
    if actual_close is None or abs(_number(bars[-1]["close"]) - actual_close) > Decimal("0.02"):
        return [], ["price_history_close_mismatch"]
    if not history.get("data_source") or not series.get("source_url"):
        return [], ["price_history_source_missing"]
    return bars, []


def build_tactical_review(decision: dict[str, Any], *, current: datetime,
                          policy: dict[str, Any], history: dict[str, Any],
                          open_orders: dict[str, Any], snapshot_hash: str,
                          market_rows: list[dict[str, Any]],
                          exact_actions: list[dict[str, Any]],
                          all_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build dated human-review records; canonical account/actions are never changed."""
    account = decision.get("account", {})
    market_gate = decision.get("market_gate", {})
    observed_session = _day(market_gate.get("expected_market_session"))
    session = observed_session or last_completed_market_session(current)
    current = current.astimezone(ZoneInfo("America/New_York"))
    # A research draft generated before the close applies to the remaining
    # current session; a DAY draft generated after the close is for the next.
    next_session = current.date() if is_us_market_session_date(current.date()) and current.strftime("%H:%M") < "16:00" else _sessions_after(current.date())
    blockers: list[str] = []
    required_policy = {"ordinary_risk_pct": Decimal("0.5"), "event_risk_pct": Decimal("0.25"),
                       "combined_risk_pct": Decimal("2"), "max_position_pct": Decimal("5"),
                       "min_reward_to_risk": Decimal("2"), "max_holding_sessions": Decimal("5")}
    if (policy.get("schema_version") != "phase5r_tactical_policy_v1"
            or any(_number(policy.get(key)) != value for key, value in required_policy.items())):
        blockers.append("tactical_policy_invalid")
    for gate in ("market_gate", "evidence_gate", "fundamental_gate"):
        if decision.get(gate, {}).get("passed") is not True:
            blockers.append(gate + "_failed")
    if market_gate.get("complete_close_verified") is not True:
        blockers.append("complete_close_unverified")
    if observed_session != last_completed_market_session(current):
        blockers.append("latest_completed_session_missing")
    if decision.get("account_conflicts") or decision.get("pending_execution_summaries"):
        blockers.append("account_or_execution_conflict")
    value = _positive(account.get("account_total_value"))
    cash = _number(account.get("cash_available"))
    reserve = _number(account.get("cash_reserved"))
    if value is None or cash is None or cash < 0 or reserve is None or reserve < 0:
        blockers.append("account_values_invalid")
    cash_basis = str(account.get("cash_basis", "")).lower()
    cash_confirmed = (cash_basis in CASH_CONFIRMED_BASES or
                      (cash_basis == "owner_recorded" and open_orders.get("cash_confirmed") is True))
    if not cash_confirmed:
        blockers.append("cash_not_confirmed")
    order_review = review_open_orders(open_orders, current, next_session)
    if not order_review["complete"]:
        blockers.append("open_orders_unconfirmed")
    existing_risk = _number(open_orders.get("existing_tactical_risk_usd"))
    if (open_orders.get("existing_tactical_risk_confirmed") is not True
            or existing_risk is None or existing_risk < 0):
        blockers.append("existing_tactical_risk_unconfirmed")
        existing_risk = None
    by_market = {str(row.get("ticker", "")).upper(): row for row in market_rows}
    by_action = {str(row.get("ticker", "")).upper(): row for row in exact_actions}
    candidates = {str(row.get("ticker", "")).upper(): row for row in (all_candidates or decision.get("watch_candidates", []))}
    held = {str(row.get("ticker", "")).upper(): row for row in decision.get("held_positions", [])}
    coverage = sorted(set(policy.get("coverage_tickers", [])) | set(held) | set(candidates))
    eligible_held = set(decision.get("eligible_action_review_candidates", []))
    eligible_new = set(decision.get("eligible_new_position_review_candidates", []))
    event_tickers = {str(row.get("ticker", "")).upper() for row in decision.get("material_events", [])}
    ordinary = value * Decimal("0.005") if value else None
    event_budget = value * Decimal("0.0025") if value else None
    combined = value * Decimal("0.02") if value else None
    remaining_cash = max(Decimal(0), (cash or Decimal(0)) - (reserve or Decimal(0)) - Decimal(str(order_review["cash_reservation_usd"])))
    remaining_risk = max(Decimal(0), (combined or Decimal(0)) - (existing_risk or Decimal(0)))
    drafts = []
    holdings = []
    for ticker in coverage:
        row = by_market.get(ticker, {})
        issues = list(blockers)
        action = by_action.get(ticker, {})
        candidate = candidates.get(ticker, {})
        canonical_qty = 0
        max_price = None
        if ticker in eligible_held and str(action.get("recommended_action", "")).lower().startswith(("add", "buy")):
            canonical_qty = _integer(action.get("whole_shares_to_change"))
            max_price = _positive(action.get("maximum_buy_price"))
        elif ticker in eligible_new and candidate.get("eligibility_label", candidate.get("label")) in {"eligible_buy_review", "eligible_core_starter_review"}:
            canonical_qty = _integer(candidate.get("suggested_whole_shares"))
            max_price = _positive(candidate.get("maximum_review_price"))
        if canonical_qty <= 0:
            issues.append("canonical_buy_not_eligible")
        if max_price is None:
            issues.append("canonical_maximum_price_missing")
        if row.get("market_session_date") != session.isoformat() or row.get("data_quality_label") != "ok":
            issues.append("ticker_market_data_unverified")
        if ticker in order_review["active_tickers"]:
            issues.append("existing_order_requires_reconciliation")
        bars, history_issues = _validated_bars(history, ticker, session, snapshot_hash, row.get("last_price"))
        issues.extend(history_issues)
        entry = stop = target = rr = None
        if bars:
            entry = _number(bars[-1]["high"])
            stop = min(_number(bar["low"]) for bar in bars[-5:])
            # Never manufacture a 2R target: use a price actually reached earlier.
            target = max(_number(bar["high"]) for bar in bars[:-1])
            if entry <= stop or target <= entry:
                issues.append("observed_target_has_no_upside")
            else:
                rr = (target - entry) / (entry - stop)
                if rr < Decimal(2):
                    issues.append("reward_to_risk_below_2")
            if max_price is not None and entry > max_price:
                issues.append("entry_above_canonical_maximum")
        # Event window must be independently recorded; absence is not no-event.
        calendar = open_orders.get("event_calendar", {})
        calendar = calendar if isinstance(calendar, dict) else {}
        calendar_date = _day(calendar.get("as_of_session"))
        events = calendar.get("events", [])
        events = events if isinstance(events, list) else []
        calendar_confirmed = calendar_date == session and calendar.get("complete") is True
        if not calendar_confirmed:
            issues.append("event_calendar_unconfirmed")
        last_exit = _sessions_after(next_session, 4)
        scheduled = [event for event in events if isinstance(event, dict)
                     and str(event.get("ticker", "")).upper() in {ticker, "ALL", "MARKET"}
                     and next_session <= (_day(event.get("session_date")) or date.min) <= last_exit]
        event_risk = not calendar_confirmed or ticker in event_tickers or bool(scheduled)
        risk_limit = event_budget if event_risk else ordinary
        qty = scenario_qty = 0
        assumptions = []
        only_assumptions = set(issues).issubset(HYPOTHETICAL_BLOCKERS)
        if only_assumptions and entry and stop and rr is not None and rr >= 2 and value and risk_limit:
            per_share = entry - stop
            held_value = (_positive(held.get(ticker, {}).get("current_shares")) or Decimal(0)) * (_positive(row.get("last_price")) or Decimal(0))
            capacity = max(Decimal(0), value * Decimal("0.05") - held_value)
            quantity_limit = min(Decimal(canonical_qty), remaining_cash / entry, capacity / entry,
                                 risk_limit / per_share, remaining_risk / per_share)
            sized_qty = max(0, int(quantity_limit.to_integral_value(rounding=ROUND_FLOOR)))
            if not sized_qty:
                issues.append("whole_share_cash_cap_or_risk_limit")
            elif issues:
                scenario_qty = sized_qty
                if "cash_not_confirmed" in issues:
                    assumptions.append("Assumes recorded cash is confirmed available after reserves and pending orders; actual eligible quantity is zero.")
                if "existing_tactical_risk_unconfirmed" in issues:
                    assumptions.append("Assumes zero existing tactical planned risk, which is NOT confirmed; actual eligible quantity is zero.")
                if "open_orders_unconfirmed" in issues or "existing_order_requires_reconciliation" in issues:
                    assumptions.append("Requires a fresh complete pending-order check and confirmation of every cancellation/fill before replacement; shown reservations are only known orders, not proof of available cash.")
                if "event_calendar_unconfirmed" in issues:
                    assumptions.append("Requires a fresh official earnings/catalyst and macro calendar check before entry; coverage is unconfirmed, so the smaller 0.25% event-risk budget is used.")
            else:
                qty = sized_qty
            if sized_qty:
                # All displayed proposals share one cash/risk budget, including scenarios.
                remaining_cash -= entry * sized_qty
                remaining_risk -= per_share * sized_qty
        reasons = sorted(set(issues))
        price_basis = (f"{history.get('data_source')}; completed daily OHLC through {session}; "
                       f"{history.get('tickers', {}).get(ticker, {}).get('source_url', '')}" if bars else "")
        drafts.append({"ticker": ticker, "side": "buy", "classification": "real-trade candidate" if qty else "watchlist",
                       "eligible": qty > 0, "quantity": qty, "canonical_quantity_ceiling": canonical_qty,
                       "hypothetical_quantity": scenario_qty, "hypothetical_assumptions": assumptions,
                       "entry_price": _money(entry), "stop_price": _money(stop), "target_price": _money(target),
                       "reward_to_risk": round(float(rr), 4) if rr is not None else None,
                       "planned_risk_usd": _money((entry - stop) * qty) if entry and stop else 0,
                       "event_risk": event_risk, "risk_limit_usd": _money(risk_limit),
                       "session_date": next_session.isoformat(), "time_in_force": "DAY", "order_type": "conditional limit draft",
                       "time_exit_session": last_exit.isoformat(), "holding_sessions_max": 5,
                       "entry_rule": "Human review only after price reclaims the observed entry; do not chase above the limit or canonical maximum; refresh quote, calendar and orders first.",
                       "invalidation_rule": "A break of the observed five-session low invalidates this trade; review exit promptly. The level is not guaranteed execution.",
                       "reentry_rule": "After exit, require a new complete-close canonical review, new observed setup and at least 2R; no automatic averaging down or conversion to core.",
                       "blockers": reasons, "price_basis": price_basis,
                       "price_evidence": {"validated": bool(bars), "history_session": session.isoformat() if bars else "",
                                          "snapshot_sha256": snapshot_hash if bars else ""}})
        if ticker in held:
            holding = held[ticker]
            holdings.append({"ticker": ticker, "held_shares": holding.get("current_shares", ""),
                             "preference": holding.get("action", "hold_pending_research"), "classification": "watchlist",
                             "proposed_share_change": 0,
                             "reason": "Existing canonical holding thesis is unchanged by this tactical overlay; no recorded trade is silently reclassified as core. " + str(holding.get("reason", ""))})
    return {"schema_version": SCHEMA_VERSION, "as_of": current.isoformat(), "market_session": session.isoformat(),
            "next_session": next_session.isoformat(), "classification": "real-trade candidate" if any(row["eligible"] for row in drafts) else "watchlist",
            "global_gates_passed": not blockers, "blockers": sorted(set(blockers)), "cash_basis": account.get("cash_basis", "unknown"),
            "risk_policy": {key: float(value) for key, value in required_policy.items()},
            "risk_budget": {"account_value": _money(value), "ordinary_usd": _money(ordinary), "event_usd": _money(event_budget),
                            "combined_usd": _money(combined), "open_risk_usd": _money(existing_risk)},
            "open_orders": order_review, "holdings": holdings, "drafts": drafts, "four_rules": FOUR_RULES,
            "performance_claim": "Risk discipline only; no tested profitability or guaranteed loss limit.",
            "research_only": True, "automatic_action_allowed": False}


def load_tactical_review(decision: dict[str, Any], *, current: datetime,
                         market_rows: list[dict[str, Any]], exact_actions: list[dict[str, Any]],
                         all_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    def safe_json(path: Path) -> dict[str, Any]:
        try:
            value = read_json(path, {})
            return value if isinstance(value, dict) else {}
        except (ValueError, OSError):
            return {}
    return build_tactical_review(decision, current=current, policy=safe_json(POLICY_PATH),
                                 history=safe_json(HISTORY_PATH), open_orders=safe_json(ORDERS_PATH),
                                 snapshot_hash=sha256_file(MARKET_SNAPSHOT_PATH), market_rows=market_rows,
                                 exact_actions=exact_actions, all_candidates=all_candidates)
