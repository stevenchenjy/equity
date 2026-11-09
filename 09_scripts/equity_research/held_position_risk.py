"""Independent dated risk visibility for every recorded holding.

This projection never sizes orders, renews plans, invents loss thresholds or
authorizes notifications. Each quote is checked independently; missing portfolio
coverage cannot erase another holding's observation. Recorded average basis is
not an acquisition fill, and basis return is not portfolio drawdown.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from daily_common import (ET, ExclusiveFileLock, atomic_write_json, canonical_sha256,
                          is_us_market_session_date, latest_published_market_session,
                          sha256_file)
from investment_plans import load_plan_context, stamp

SCHEMA = "equity_held_position_risk_v1"
POSITIONS = "05_risk_and_positions/current_positions.local.csv"
MARKET = "03_source_data/equity_research/market_data_snapshot.csv"
QUALITY = "03_source_data/equity_research/market_data_quality_report.csv"
ORDERS = "05_risk_and_positions/current_open_orders.local.json"
INPUTS = (POSITIONS, MARKET, QUALITY, ORDERS,
          "05_risk_and_positions/current_account_state.local.json",
          "05_risk_and_positions/account_record_policy.local.json",
          "05_risk_and_positions/investment_plans.local.json",
          "05_risk_and_positions/plan_source_resolutions.local.json")
OUTPUT = "04_research/company_research/held_position_risk.local.json"
HISTORY = "05_risk_and_positions/generated/held_risk_observations.local"
ALERTS = {"RISK_ALERT", "PLAN_EXPIRED", "REVIEW_REQUIRED", "UNVERIFIED", "REDUCE_REVIEW", "EXIT_REVIEW"}


def number(value):
    try:
        value = Decimal(str(value))
        return value if value.is_finite() and value > 0 else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def _csv(root, relative):
    try:
        with (root / relative).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        return []


def _inventory(root):
    try:
        with (root / POSITIONS).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, strict=True)
            if not {"ticker", "shares_optional", "entry_price"} <= set(reader.fieldnames or []):
                return [], False
            rows = list(reader)
            return rows, all(None not in row and None not in row.values() for row in rows)
    except (OSError, UnicodeError, csv.Error):
        return [], False


def _zero_quantity(row):
    try:
        value = Decimal(str(row.get("shares_optional")))
        return value.is_finite() and value == 0
    except (ValueError, TypeError, InvalidOperation):
        return False


def _json(root, relative):
    try:
        value = json.loads((root / relative).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _bindings(root):
    return {path: sha256_file(root / path) if (root / path).is_file() else None for path in INPUTS}


def _review_deadline(current):
    """Existing morning/afternoon review windows; never extend an order."""
    day = current.date()
    for _ in range(12):
        if is_us_market_session_date(day):
            for hour, minute in ((10, 30), (15, 5)):
                due = datetime.combine(day, datetime.min.time(), tzinfo=ET).replace(hour=hour, minute=minute)
                if due > current:
                    return due.isoformat()
        day += timedelta(days=1)
    raise ValueError("held_risk_review_calendar_unavailable")


def material_intraday_conditions(decision):
    report = decision.get("intraday_portfolio_risk", {})
    if report.get("status") != "current":
        return []
    result = []
    for key in ("plan_conditions", "reassessment_triggers"):
        for item in report.get(key, []):
            if (isinstance(item, dict) and item.get("status") in
                    {"triggered", "breached", "requires_reassessment", "price_condition_met_reassessment_required"}
                    and item.get("kind") != "reviewed_allocation_maximum_entry_price"
                    and item not in result):
                result.append(item)
    return result


def _quote(root, ticker, quotes, quality, current, expected, market_gate, inventory_tickers=()):
    matches = [row for row in quotes if str(row.get("ticker") or "").upper() == ticker]
    checks = [row for row in quality if str(row.get("ticker") or "").upper() == ticker]
    # Portfolio-wide provenance failures are different from a missing other
    # ticker. Never turn an invalid backup lineage into an admitted observation.
    failures = market_gate.get("failures", [])
    known_tickers = {str(row.get("ticker") or "").upper() for row in quotes + quality} | set(inventory_tickers)
    if any(str(code).split(":", 1)[0] not in known_tickers for code in failures):
        return None
    if any(str(code).startswith(ticker + ":") for code in failures):
        return None
    if len(matches) != 1 or len(checks) != 1:
        return None
    row = matches[0]
    try:
        price = number(row.get("last_price"))
        observed = stamp(row.get("data_timestamp"))
        if (price is None or row.get("market_session_date") != expected
                or row.get("data_quality_label") != "ok"
                or checks[0].get("usable_for_scoring") != "yes"
                or not row.get("data_source") or observed > current):
            return None
    except (ValueError, TypeError):
        return None
    return {"price": float(price), "session": expected, "collected_at": row["data_timestamp"],
            "source": row["data_source"], "basis": "canonical completed close; not live"}


def build(decision, *, root: Path, current: datetime) -> dict:
    current = current.astimezone(ET)
    bindings = _bindings(root)
    inventory, inventory_available = _inventory(root)
    inventory = [row for row in inventory if not _zero_quantity(row)]
    quotes, quality = _csv(root, MARKET), _csv(root, QUALITY)
    orders = _json(root, ORDERS)
    expected = latest_published_market_session(current).isoformat()
    # Read raw inventory even when portfolio recomposition or company research
    # failed. An invalid row stays visible with an unavailable recommendation.
    held = [{"ticker": str(r.get("ticker") or "").upper(), "current_shares": r.get("shares_optional")}
            for r in inventory]
    try:
        context = load_plan_context(root, held, current)
    except (ValueError, TypeError, KeyError, OSError):
        context = {"status": "invalid", "global_blockers": ["plan_context_unavailable"], "plans": []}
    plans = {p["ticker"]: p for p in context.get("plans", [])}
    capital = {p["ticker"]: p for p in decision.get("capital_decision", {}).get("decisions", [])}
    global_issues = list(context.get("global_blockers", []))
    global_issues += [code for code in decision.get("workflow_integrity", {}).get("global_blockers", [])
                      if any(word in code for word in ("account", "inventory", "execution", "cash"))]
    next_review = _review_deadline(current)
    rows = []
    for item in inventory:
        ticker = str(item.get("ticker") or "").upper()
        qty, basis = number(item.get("shares_optional")), number(item.get("entry_price"))
        p, c = plans.get(ticker, {}), capital.get(ticker, {})
        issues = list(dict.fromkeys(global_issues + context.get("ticker_blockers", {}).get(ticker, [])))
        valid_inventory = (qty is not None and qty == qty.to_integral_value()
                           and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker)
                           and sum(str(r.get("ticker") or "").upper() == ticker for r in inventory) == 1)
        if not valid_inventory:
            issues.append("recorded_quantity_or_identity_unverified")
        mark = _quote(root, ticker, quotes, quality, current, expected, decision.get("market_gate", {}),
                      [row["ticker"] for row in held])
        if mark is None:
            issues.append("current_ticker_close_unavailable")
        plan_state = p.get("status", "unrecorded")
        if plan_state != "maintained":
            issues.append("held_plan_" + plan_state)
        observed = Decimal(str(mark["price"])) if mark else None
        conditions = []
        allocation = p.get("reviewed_allocation") or {}
        draft = p.get("historical_order_draft") or {}
        refs = [("company_invalidation", allocation.get("invalidation_price"), "at_or_below"),
                ("company_reassessment", allocation.get("reassessment_price"), "at_or_above")]
        if draft.get("side") == "sell" and draft.get("type") == "STOP":
            refs.append(("recorded_stop_reference", draft.get("stop_price"), "at_or_below"))
        for kind, raw, direction in refs:
            threshold = number(raw)
            if threshold is None:
                continue
            crossed = (None if observed is None else observed <= threshold if direction == "at_or_below" else observed >= threshold)
            # Only the latest evaluated plan for this inventory is inspected.
            # Never resurrect a closed position's historical stop lineage.
            expired = plan_state in {"expired_pending_verification", "time_exit_due_pending_verification"}
            revalidation = plan_state != "maintained"
            conditions.append({"kind": kind, "reference": float(threshold), "direction": direction,
                "crossed_at_observation": crossed, "reference_expired": expired,
                "reference_requires_revalidation": revalidation,
                "plan_id": p.get("plan_id"), "plan_version": p.get("version"),
                "meaning": ("Expired plan reference only; no renewed order and no assertion it was crossed while valid."
                            if expired else "Prior plan reference requires revalidation; no current order or fill inferred."
                            if revalidation else "Existing plan condition requires review when crossed; no fill inferred.")})
        intraday = [x for x in material_intraday_conditions(decision) if x.get("ticker") == ticker]
        crossed = any(x["crossed_at_observation"] is True for x in conditions) or bool(intraday)
        account_problem = not valid_inventory or bool(global_issues) or plan_state in {
            "position_changed_pending_verification", "order_conflict_pending_review", "conflict"}
        if account_problem or mark is None:
            state = "UNVERIFIED"
        elif crossed:
            state = "RISK_ALERT"
        elif plan_state in {"expired_pending_verification", "time_exit_due_pending_verification"}:
            state = "PLAN_EXPIRED"
        elif c.get("decision") in {"REDUCE_REVIEW", "EXIT_REVIEW"}:
            state = c["decision"]
        elif plan_state != "maintained" or c.get("decision") != "HOLD" or c.get("blockers") or p.get("blockers"):
            state = "REVIEW_REQUIRED"
        else:
            state = "REVIEWED_HOLD"
        pending = [x for x in orders.get("orders", []) if isinstance(x, dict) and x.get("ticker") == ticker
                   and x.get("status") in {"open", "pending", "partial_fill", "partially_filled"}]
        if pending:
            issues.append("known_order_remaining_quantity_requires_reconciliation_before_replacement")
            if state == "REVIEWED_HOLD":
                state = "REVIEW_REQUIRED"
        changes = c.get("blockers", [])
        next_step = ("Recurring analyst: review the existing purpose, current adverse evidence and permitted reduce/exit response; "
                     "record a source-bound plan or exact unresolved dependency by the next review window.")
        if account_problem or pending or "earlier_instruction_execution_unreconciled" in changes:
            next_step += " Owner/account record: provide actual remaining shares and each earlier order's filled, cancelled or remaining quantity; never duplicate a reserved sale."
        if mark is None:
            next_step += " Public-data worker: restore this ticker's dated canonical close; retain other independently verified observations."
        if state == "REVIEWED_HOLD":
            next_step = "Recurring analyst: reassess by the recorded plan deadline, sooner if the stated invalidation or material evidence changes."
        rows.append({"ticker": ticker, "recorded_shares": float(qty) if qty else None,
            "strategy": p.get("role", item.get("horizon_class", "unclassified")),
            "state": state, "plan_state": plan_state, "plan_review_at": p.get("review_at"),
            "plan_id": p.get("plan_id"), "plan_version": p.get("version"), "plan_record_hash": p.get("record_hash"),
            "quote": mark, "recorded_average_basis": float(basis) if basis else None,
            "basis_label": "Recorded average basis; may include wash-sale adjustments; not an acquisition fill.",
            "basis_price_change_pct": round(float((observed / basis - 1) * 100), 4) if observed and basis else None,
            "unrealized_change_usd": round(float((observed - basis) * qty), 2) if observed and basis and valid_inventory else None,
            "conditions": conditions, "intraday_conditions": intraday, "dependencies": sorted(set(issues)),
            "capital_blockers": c.get("blockers", []),
            "capital_outcome": c.get("decision", "unavailable"),
            "action_draft_available": bool(c.get("order_draft")),
            "order_observed_at": orders.get("as_of"), "known_pending_orders": pending,
            "broker_protection": "Current broker protection unverified; a research draft is not a resting order.",
            "rationale": p.get("reason", "No current source-bound rationale available."),
            "invalidation": (p.get("purpose") or {}).get("failure_condition", "No current structured invalidation verified."),
            "next_step": next_step,
            "review_due_by": p.get("review_at") if state == "REVIEWED_HOLD" else next_review,
            "review_deadline_is_service_expectation": True})
    if bindings != _bindings(root):
        raise ValueError("held_risk_inputs_changed_during_assessment")
    report = {"schema_version": SCHEMA, "generated_at": current.isoformat(), "source_bindings": bindings,
        "expected_market_session": expected, "holdings": rows,
        "coverage": "complete" if inventory and all(row["quote"] for row in rows) else "partial_or_unavailable",
        "inventory_available": inventory_available,
        "attention_tickers": [row["ticker"] for row in rows if row["state"] in ALERTS],
        "limitations": ["Basis-relative observations exclude cash flows, realized trades, dividends and costs; they are not portfolio performance or peak drawdown.",
                        "No generic percentage-loss threshold is approved here. Tactical budgets apply only to their approved strategy.",
                        "Review deadlines are service expectations, not evidence a review or execution occurred."],
        "automatic_action_allowed": False, "trading_eligibility_granted": False, "email_authorized": False}
    report["content_sha256"] = canonical_sha256(report)
    return report


def validate_publication(decision, *, root: Path, current: datetime):
    report = decision.get("held_position_risk")
    if report is None:
        return  # Preserve the renderer/validation of immutable legacy emails.
    generated = stamp(report.get("generated_at"))
    if generated > current or report != build(decision, root=root, current=generated):
        raise ValueError("held_risk_publication_changed_recompose_required")


def publish(root: Path, report: dict):
    """Small immutable observations, with no new row for an unchanged result."""
    meaning = {k: v for k, v in report.items() if k not in {"generated_at", "content_sha256"}}
    digest = canonical_sha256(meaning)
    path = root / HISTORY / (digest + ".json")
    with ExclusiveFileLock(root / HISTORY / "writer.lock"):
        if path.exists():
            retained = json.loads(path.read_text())
            if {k: v for k, v in retained.items() if k not in {"generated_at", "content_sha256"}} != meaning:
                raise ValueError("held_risk_history_conflict")
        else:
            atomic_write_json(path, report)
        atomic_write_json(root / OUTPUT, report)


def cards(decision):
    report = decision.get("held_position_risk")
    if not isinstance(report, dict):
        return []
    lines = ["Dated risk observations; conditional order drafts are shown separately."]
    shared_next_steps = []
    if not report.get("inventory_available"):
        lines.append("UNVERIFIED — the current position inventory is unavailable; no holding recommendation can be made.")
    for row in report.get("holdings", []):
        mark, change = row["quote"], row["basis_price_change_pct"]
        label = row["state"].replace("_", " ")
        lines.append(f"{row['ticker']} — {label}: {row['recorded_shares']:g} recorded shares." if row["recorded_shares"] is not None else f"{row['ticker']} — UNVERIFIED: recorded quantity unavailable.")
        if mark:
            text = f"Close ${mark['price']:.2f} on {mark['session']}; not live."
            if change is not None:
                text += f" {change:+.2f}% vs recorded average basis ${row['recorded_average_basis']:.2f}."
            lines.append(text)
        else:
            lines.append("Current ticker price unavailable; no current return is inferred.")
        lines.append(f"Plan: {row['plan_state'].replace('_', ' ')}; recorded review {row['plan_review_at'] or 'unavailable'}.")
        for condition in row["conditions"]:
            if condition["crossed_at_observation"]:
                lines.append(f"Observed crossing: {condition['kind'].replace('_', ' ')} ${condition['reference']:.2f}. {condition['meaning']}")
        for condition in row.get("intraday_conditions", []):
            lines.append("Dated intraday risk observation: " + str(condition.get("condition") or condition.get("message"))
                         + " See the separately bound intraday observation clock and expiry; no fill inferred.")
        if row["state"] == "REVIEWED_HOLD":
            lines.append("Rationale: " + row["rationale"])
            lines.append("Review/invalidation: " + row["invalidation"])
        next_step = row["next_step"] + " Due: " + str(row["review_due_by"]) + "."
        if next_step not in shared_next_steps:
            shared_next_steps.append(next_step)
        if row["dependencies"]:
            lines.append("Unresolved: " + "; ".join(code.replace("_", " ") for code in row["dependencies"]) + ".")
        extra = [code for code in row.get("capital_blockers", []) if code not in row["dependencies"]]
        if extra:
            lines.append("Decision work: " + "; ".join(code.replace("_", " ") for code in extra) + ".")
    lines.extend(shared_next_steps)
    lines.append("Recorded basis may include wash-sale adjustments. These changes are not total portfolio drawdown. Current broker protection is unverified.")
    return [{"title": "Positions requiring attention" if report.get("attention_tickers") else
                     "UNVERIFIED holdings" if not report.get("inventory_available") else
                     "Reviewed holdings" if report.get("holdings") else "No holdings recorded",
             "body": "\n".join(lines), "group": "action", "kind": "inactive", "sources": []}]
