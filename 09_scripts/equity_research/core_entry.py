"""Existing dated broad-core entry admission; shared by decision and legacy output."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

def eligible_core_tranche(decision: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    """A same-session, exact core review that can be displayed and continued.

    This is a conditional human draft, never execution authority.  An ordinary
    optimistic screen row cannot acquire an order side through presentation.
    """
    from investment_plans import regular_close

    ticker = row.get("ticker")
    if (decision.get("decision_code") != "action_review_candidate"
            or ticker not in decision.get("eligible_new_position_review_candidates", [])
            or row.get("action") != "core_allocation_tranche_review"
            or row.get("human_confirmation_required") != "yes"
            or row.get("valuation_applicability") != "not_applicable_broad_market_etf"
            or row.get("gate_blockers") or row.get("workflow_global_blockers")
            or row.get("workflow_ticker_blockers")
            or decision.get("account_conflicts")
            or decision.get("account", {}).get("cash_basis") != "owner_recorded"
            or decision.get("plan_continuity", {}).get("block_new_capital") is True
            or decision.get("plan_continuity", {}).get("global_blockers")
            or decision.get("workflow_integrity", {}).get("global_blockers")
            or ticker in decision.get("workflow_integrity", {}).get("blocked_tickers", [])
            or ticker in decision.get("workflow_integrity", {}).get("ticker_blockers", {})
            or not all(decision.get(k, {}).get("passed") is True for k in
                       ("market_gate", "evidence_gate", "fundamental_gate"))
            or decision.get("market_gate", {}).get("bar_state") != "complete_close"):
        return None
    try:
        generated = datetime.fromisoformat(decision["generated_at"])
        session = decision["cycle_date"]
        qty = Decimal(str(row["suggested_whole_shares"]))
        cap = Decimal(str(row["maximum_review_price"]))
        planning_cash = Decimal(str(decision["account"]["cash_available"]))
        held = next((p for p in decision["held_positions"] if p["ticker"] == ticker), {})
        held_before = Decimal(str(held.get("current_shares", 0)))
        maintained = next(p for p in decision["plan_continuity"]["plans"] if p["ticker"] == ticker)
        review = datetime.fromisoformat(maintained["review_at"])
        if (generated.tzinfo is None or generated.date().isoformat() != session
                or generated >= regular_close(session) or review.tzinfo is None
                or review <= generated or maintained.get("status") != "maintained"
                or maintained.get("role") != "broad_core"
                or Decimal(str(maintained.get("current_shares", held_before))) != held_before
                or qty <= 0 or qty != qty.to_integral_value() or cap <= 0
                or not cap.is_finite() or not qty.is_finite()
                or not planning_cash.is_finite() or planning_cash < qty * cap
                or held_before < 0 or held_before != held_before.to_integral_value()
                or int(row.get("stability_distinct_closes", 0)) < int(row.get("required_distinct_closes", 2))):
            return None
    except (KeyError, StopIteration, TypeError, ValueError, InvalidOperation):
        return None
    return {"ticker": ticker, "quantity": int(qty), "max_price": str(cap),
            "session_date": session, "review_at": maintained["review_at"],
            "held_before": int(held_before)}
