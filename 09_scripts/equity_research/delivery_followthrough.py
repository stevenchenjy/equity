"""Presentation-only continuation of an exactly archived prior delivered plan.

An owner planning assumption is never a fill, an account update or eligibility.
Rendering consumes this bound context, never a mutable receipt file.
"""
from __future__ import annotations

import hashlib
import html as html_module
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from daily_common import canonical_sha256, read_csv, sha256_file, last_completed_market_session

ET = ZoneInfo("America/New_York")
LEDGER_REL = Path("07_automation/email_delivery/daily_delivery_ledger.csv")
RECORD_PATHS = (
    "05_risk_and_positions/current_positions.local.csv",
    "05_risk_and_positions/current_account_state.local.json",
    "05_risk_and_positions/current_open_orders.local.json",
)
STATUSES = {prefix + status for prefix in ("", "owner_review_", "correction_")
            for status in ("send_claimed", "sent", "delivery_unknown")}


def _stamp(value: Any) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp_unaware")
    return result


def _positive(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("draft_number_invalid")
    return result


def _same_day_receipts(root: Path, current: datetime) -> list[dict[str, str]]:
    selected = []
    for index, row in enumerate(read_csv(root / LEDGER_REL)):
        if row.get("status") not in STATUSES:
            continue
        try:
            stamp = _stamp(row.get("timestamp"))
        except ValueError:
            continue
        if stamp <= current and stamp.astimezone(ET).date() == current.astimezone(ET).date():
            selected.append((stamp, index, row))
    return [row for _, _, row in sorted(selected, key=lambda value: value[:2])]


def _identity(row: dict[str, str]) -> tuple | None:
    hashes = tuple(row.get(key, "") for key in ("decision_sha256", "brief_text_sha256", "brief_html_sha256"))
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes):
        return None
    scope = tuple(part for part in row.get("reason", "").split(";")
                  if part.startswith(("scheduled_slot=", "owner_request_sha256=")))
    return (row.get("status", "").removesuffix("send_claimed").removesuffix("sent"), *hashes, *scope)


def _uncertain(rows: list[dict[str, str]]) -> bool:
    if any(row["status"].endswith("delivery_unknown") for row in rows):
        return True
    for index, row in enumerate(rows):
        if row["status"].endswith("send_claimed"):
            key = _identity(row)
            if key is None or not any(later["status"].endswith("sent") and _identity(later) == key
                                      for later in rows[index + 1:]):
                return True
    return False


def _archive(root: Path, row: dict[str, str]) -> tuple[dict, str, str]:
    values = []
    for field, suffix in (("decision_sha256", ".json"), ("brief_text_sha256", ".txt"), ("brief_html_sha256", ".html")):
        digest = row.get(field, "")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("archive_digest_missing")
        path = root / LEDGER_REL.parent / "sent_decisions.local" / (digest + suffix)
        if path.is_symlink():
            raise ValueError("archive_symlink")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("archive_digest_mismatch")
        values.append(content.decode("utf-8"))
    prior = json.loads(values[0])
    if not isinstance(prior, dict):
        raise ValueError("archive_decision_invalid")
    return prior, values[1], values[2]


def _displayed_actions(prior: dict, text: str, html: str, sent_at: datetime) -> tuple[list[dict], bool]:
    """Only full maintained drafts have exact structured instructions today.

    Owner free prose and the canonical 'up to' proposals do not encode a
    specific completed quantity. Never parse them into purported trades.
    """
    from email_brief import money, shares
    from investment_plans import regular_close
    if prior.get("owner_requested_research"):
        return [], True
    actions = []
    incomplete = False
    proposal_tickers = set(prior.get("eligible_action_review_candidates", [])) | set(prior.get("eligible_new_position_review_candidates", []))
    html_text = html_module.unescape(re.sub(r"<[^>]+>", "", html))
    def displayed(exact: str) -> bool:
        return exact in text and " ".join(exact.split()) in " ".join(html_text.split())
    if prior.get("capital_decision") is not None:
        # New publications have one authoritative draft. Never fall back to a
        # legacy ceiling when the archived capital contract is invalid/omitted.
        from capital_decision import validate
        from capital_presentation import action_lines
        try:
            contract = prior["capital_decision"]
            validate(contract, current=sent_at)
            for row in contract["decisions"]:
                draft = row.get("order_draft")
                if not draft:
                    continue
                ticker, qty = row["ticker"], _positive(row["shares"])
                side = draft["side"]
                label = {"ACTIONABLE_BUY": "BUY", "ACTIONABLE_ADD": "ADD",
                         "REDUCE_REVIEW": "REDUCE REVIEW", "EXIT_REVIEW": "EXIT REVIEW"}[row["decision"]]
                if (not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker)
                        or side not in {"buy", "sell"} or qty != qty.to_integral_value()
                        or not displayed(f"{label} — {ticker}")
                        or not all(displayed(line) for line in action_lines(row))):
                    incomplete = True
                    continue
                holding = next((h for h in prior.get("held_positions", []) if h.get("ticker") == ticker), {})
                held = Decimal(str(holding.get("current_shares", 0)))
                if not held.is_finite() or held < 0 or held != held.to_integral_value() or (side == "sell" and qty > held):
                    incomplete = True
                    continue
                actions.append({"ticker": ticker, "side": side, "quantity": int(qty),
                    "order_type": draft["entry_order_type"], "session_date": draft["entry_window"]["session"],
                    "review_at": draft["entry_window"]["ends_at"],
                    "time_exit_at": (regular_close(row["position_purpose"]["time_exit_session"]).isoformat()
                                     if row.get("position_purpose", {}).get("time_exit_session") else None),
                    "draft_sha256": canonical_sha256(draft), "held_before": int(held),
                    "assumed_fill_price": str(_positive(draft["exit_price"] if side == "sell" else draft["entry_limit"])),
                    "source": "exact_displayed_capital_draft"})
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return [], True
        return actions, incomplete or len({a["ticker"] for a in actions}) != len(actions)
    for plan in prior.get("plan_continuity", {}).get("plans", []):
        draft = plan.get("historical_order_draft")
        if plan.get("status") != "maintained" or not draft:
            continue
        try:
            ticker = plan["ticker"]
            if (not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker)
                    or plan.get("action") not in {"protect_review", "exit_review", "trim_review"}
                    or plan.get("automatic_action_allowed") is not False
                    or plan.get("validity") != "research_only_requires_current_verification"
                    or not re.fullmatch(r"[0-9a-f]{64}", str(plan.get("record_hash", "")))
                    or draft.get("side") != "sell" or draft.get("type") not in {"STOP", "LIMIT", "MARKETABLE_LIMIT"}
                    or draft.get("time_in_force") != "DAY"):
                continue
            quantity = _positive(draft["quantity"])
            held_quantity = _positive(plan["current_shares"])
            if (quantity != quantity.to_integral_value() or held_quantity != held_quantity.to_integral_value()
                    or quantity != _positive(plan["proposed_change_shares"]) or quantity > held_quantity):
                continue
            if sent_at >= _stamp(plan["review_at"]) or sent_at >= regular_close(draft["session_date"]):
                continue
            if plan.get("time_exit_at") and sent_at >= _stamp(plan["time_exit_at"]):
                continue
            _positive(draft["stop_price"] if draft["type"] == "STOP" else draft["limit_price"])
            levels = "; ".join(f"{label} {money(draft[field])}" for field, label in
                (("limit_price", "limit"), ("stop_price", "stop")) if draft.get(field) is not None)
            exact = (f"Maintained conditional plan — {ticker}: sell {shares(quantity)} shares; "
                     f"{draft['type']}; {levels}; DAY; session {draft['session_date']}; review {plan['review_at']}")
            # Text is the authoritative literal instruction; the complete HTML
            # must also be present and hash-bound by _archive, not reconstructed.
            if not displayed(exact):
                incomplete = True
                continue
            actions.append({"ticker": ticker, "side": "sell", "quantity": int(quantity),
                "order_type": draft["type"], "session_date": draft["session_date"],
                "plan_id": plan.get("plan_id"), "plan_record_hash": plan["record_hash"],
                "review_at": plan["review_at"], "time_exit_at": plan.get("time_exit_at"),
                "draft_sha256": canonical_sha256(draft), "held_before": int(held_quantity),
                "assumed_fill_price": str(_positive(draft["stop_price"] if draft["type"] == "STOP" else draft["limit_price"])),
                "source": "exact_displayed_maintained_conditional_draft"})
        except (KeyError, TypeError, ValueError, InvalidOperation):
            incomplete = True
    for draft in prior.get("tactical_review", {}).get("drafts", []):
        if draft.get("eligible") is not True:
            continue
        try:
            ticker = draft["ticker"]
            qty, entry, stop, target = (_positive(draft[field]) for field in ("quantity", "entry_price", "stop_price", "target_price"))
            risk = _positive(draft["planned_risk_usd"])
            if (not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker) or ticker not in proposal_tickers
                    or draft.get("side") != "buy" or qty != qty.to_integral_value()
                    or draft.get("time_in_force") != "DAY" or draft.get("order_type") != "conditional limit draft"
                    or not stop < entry < target or sent_at >= regular_close(draft["session_date"])
                    or not draft.get("entry_rule") or not draft.get("invalidation_rule")
                    or draft.get("blockers") or prior.get("account_conflicts")
                    or prior.get("tactical_review", {}).get("global_gates_passed") is not True):
                incomplete = True
                continue
            exact = (f"{ticker} tactical draft: buy {shares(qty)} shares; entry/max {money(entry)}, "
                     f"stop {money(stop)}, target {money(target)}, planned risk {money(risk)}; "
                     f"{draft['order_type']}, DAY, session {draft['session_date']}; exit/review {draft['time_exit_session']}.")
            if not displayed(exact):
                incomplete = True
                continue
            holding = next((row for row in prior.get("held_positions", []) if row.get("ticker") == ticker), {})
            held_before = Decimal(str(holding.get("current_shares", 0)))
            if not held_before.is_finite() or held_before < 0 or held_before != held_before.to_integral_value():
                incomplete = True
                continue
            actions.append({"ticker": ticker, "side": "buy", "quantity": int(qty),
                "order_type": draft["order_type"], "session_date": draft["session_date"],
                "review_at": regular_close(draft["session_date"]).isoformat(),
                "time_exit_at": regular_close(draft["time_exit_session"]).isoformat(),
                "draft_sha256": canonical_sha256(draft), "held_before": int(held_before),
                "assumed_fill_price": str(entry), "source": "exact_displayed_eligible_tactical_draft"})
        except (KeyError, TypeError, ValueError, InvalidOperation):
            incomplete = True
    from scheduled_email import eligible_core_tranche, core_tranche_line
    for row in prior.get("watch_candidates", []):
        if row.get("ticker") not in proposal_tickers or row.get("action") != "core_allocation_tranche_review":
            continue
        draft = eligible_core_tranche(prior, row)
        if not draft:
            incomplete = True
            continue
        try:
            if sent_at >= regular_close(draft["session_date"]) or not displayed(core_tranche_line(draft)):
                incomplete = True
                continue
            actions.append({"ticker": draft["ticker"], "side": "buy", "quantity": draft["quantity"],
                "order_type": "LIMIT", "session_date": draft["session_date"],
                "review_at": draft["review_at"], "time_exit_at": None,
                "draft_sha256": canonical_sha256(draft), "held_before": draft["held_before"],
                "assumed_fill_price": draft["max_price"],
                "source": "exact_displayed_eligible_core_tranche"})
        except (KeyError, TypeError, ValueError, InvalidOperation):
            incomplete = True
    if proposal_tickers - {action["ticker"] for action in actions}:
        incomplete = True
    if len({action["ticker"] for action in actions}) != len(actions):
        incomplete = True  # Multiple/opposite same-ticker drafts need explicit reconciliation.
    return actions, incomplete


def _verified_current_snapshot(decision: dict, *, root: Path, after: datetime, current: datetime) -> dict | None:
    """Existing complete owner snapshot authority can replace a hypothesis.

    Neither changed bytes nor equal quantities prove any particular fill.
    Require a newly recorded complete account snapshot bound to current files,
    plus a later complete, sourced order observation; canonical gates still run.
    """
    from update_manual_account import current_manual_snapshot_matches
    from tactical_review import review_open_orders
    try:
        bindings = decision.get("workflow_integrity", {}).get("input_hashes", {})
        if any(bindings.get(path) != sha256_file(root / path) for path in RECORD_PATHS):
            return None
        snapshot_path = root / "05_risk_and_positions/manual_account_snapshot.local.json"
        snapshot = json.loads(snapshot_path.read_bytes())
        if (not after < _stamp(snapshot["recorded_at"]) <= current
                or not current_manual_snapshot_matches(bindings[RECORD_PATHS[0]], bindings[RECORD_PATHS[1]], root=root)):
            return None
        account = json.loads((root / RECORD_PATHS[1]).read_bytes())
        if account.get("cash_basis") != "owner_recorded":
            return None
        orders = json.loads((root / RECORD_PATHS[2]).read_bytes())
        observation = orders["current_inventory_observation"]
        if not after < _stamp(orders["as_of"]) <= current or observation.get("complete") is not True:
            return None
        source = observation["source"]
        source_path = Path(source["path"])
        if source_path.is_absolute() or ".." in source_path.parts or (root / source_path).is_symlink():
            return None
        if source.get("sha256") != sha256_file(root / source_path):
            return None
        reviewed = review_open_orders(orders, current, last_completed_market_session(current), decision.get("held_positions", []))
        if reviewed.get("complete") is not True:
            return None
        return {"snapshot_recorded_at": snapshot["recorded_at"], "snapshot_sha256": sha256_file(snapshot_path),
                "confirmed_execution_sha256": snapshot["confirmed_execution_sha256"],
                "order_observed_at": orders["as_of"], "order_source_sha256": source["sha256"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def build_followthrough(decision: dict[str, Any], *, root: Path, current: datetime) -> dict[str, Any]:
    context: dict[str, Any] = {"schema_version": "equity_delivery_followthrough_v1", "as_of": current.isoformat(),
        "basis": "owner_assumed_execution_scenario_only", "canonical_state_changed": False,
        "creates_trade_eligibility": False, "status": "no_prior_same_day_delivery", "actions": []}
    rows = _same_day_receipts(root, current)
    if not rows:
        return context
    context["receipt_state_sha256"] = canonical_sha256(rows)
    if _uncertain(rows):
        context["status"] = "prior_delivery_uncertain"
        return context
    row = next((row for row in reversed(rows) if row["status"].endswith("sent")), None)
    if row is None:
        return context
    context.update(prior_sent_at=row["timestamp"], prior_receipt_sha256=canonical_sha256(row),
        prior_decision_sha256=row.get("decision_sha256"), prior_text_sha256=row.get("brief_text_sha256"),
        prior_html_sha256=row.get("brief_html_sha256"))
    actual_snapshot = _verified_current_snapshot(decision, root=root, after=_stamp(row["timestamp"]), current=current)
    if actual_snapshot is not None:
        context.update(status="verified_current_snapshot_supersedes", actual_snapshot=actual_snapshot)
        return context
    try:
        prior, text, html = _archive(root, row)
        actions, incomplete = _displayed_actions(prior, text, html, _stamp(row["timestamp"]))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        context["status"] = "prior_exact_content_unavailable"
        return context
    # A later status email or one-ticker correction cannot silently erase an
    # earlier instruction. Only identical fully structured action sets are
    # unambiguous repetitions; otherwise retain a reconciliation dependency.
    sent_rows = [candidate for candidate in rows if candidate["status"].endswith("sent")]
    for older in sent_rows[:-1]:
        try:
            old_decision, old_text, old_html = _archive(root, older)
            old_actions, old_incomplete = _displayed_actions(old_decision, old_text, old_html, _stamp(older["timestamp"]))
        except (OSError, UnicodeError, ValueError, TypeError, KeyError):
            old_actions, old_incomplete = [], True
        if old_incomplete or (old_actions and old_actions != actions):
            context["status"] = "multiple_deliveries_require_reconciliation"
            return context
    if incomplete:
        context["status"] = "prior_action_not_structured"
        context["unstructured_candidate_tickers"] = sorted(
            set(prior.get("eligible_action_review_candidates", []))
            | set(prior.get("eligible_new_position_review_candidates", [])))
        return context
    if not actions:
        context["status"] = "prior_no_specific_order"
        return context
    old_bindings = prior.get("workflow_integrity", {}).get("input_hashes", {})
    new_bindings = decision.get("workflow_integrity", {}).get("input_hashes", {})
    context["record_bindings"] = {key: new_bindings.get(key) for key in RECORD_PATHS}
    if any(not re.fullmatch(r"[0-9a-f]{64}", str(old_bindings.get(key, "")))
           or not re.fullmatch(r"[0-9a-f]{64}", str(new_bindings.get(key, ""))) for key in RECORD_PATHS):
        context["status"] = "account_record_bindings_unavailable"
        return context
    if any(old_bindings[key] != new_bindings[key] for key in RECORD_PATHS):
        context["status"] = "records_updated_since_delivery"
        return context
    current_plans = {plan.get("ticker"): plan for plan in decision.get("plan_continuity", {}).get("plans", [])}
    for action in actions:
        plan = current_plans.get(action["ticker"], {})
        awaiting_actual_execution = False
        if action["source"] == "exact_displayed_capital_draft":
            current_row = next((row for row in decision.get("capital_decision", {}).get("decisions", [])
                                if row.get("ticker") == action["ticker"]), {})
            current_draft = current_row.get("order_draft")
            same = current_draft is not None and canonical_sha256(current_draft) == action["draft_sha256"]
            awaiting_actual_execution = current_draft is None
        elif action["source"] == "exact_displayed_eligible_tactical_draft":
            current_draft = next((draft for draft in decision.get("tactical_review", {}).get("drafts", [])
                                  if draft.get("ticker") == action["ticker"]), {})
            same = canonical_sha256(current_draft) == action["draft_sha256"]
        elif action["source"] == "exact_displayed_eligible_core_tranche":
            from scheduled_email import eligible_core_tranche
            current_row = next((row for row in decision.get("watch_candidates", [])
                                if row.get("ticker") == action["ticker"]), {})
            current_draft = eligible_core_tranche(decision, current_row)
            same = current_draft is not None and canonical_sha256(current_draft) == action["draft_sha256"]
        else:
            same = plan.get("record_hash") == action["plan_record_hash"]
        expired = current >= _stamp(action["review_at"])
        if action.get("time_exit_at"):
            expired = expired or current >= _stamp(action["time_exit_at"])
        from investment_plans import regular_close
        expired = expired or current >= regular_close(action["session_date"])
        action["continuation"] = ("expired_reconcile" if expired else "same_plan_do_not_repeat" if same else
                                  "execution_reconciliation_required" if awaiting_actual_execution else "changed_plan_reconcile")
        action["assumed_remaining_shares"] = action["held_before"] + action["quantity"] * (1 if action["side"] == "buy" else -1)
    cash_after = None
    try:
        cash_before = Decimal(str(prior.get("account", {}).get("cash_available")))
        if cash_before.is_finite() and cash_before >= 0:
            cash_after = str(cash_before + sum(Decimal(action["assumed_fill_price"]) * action["quantity"]
                * (1 if action["side"] == "sell" else -1) for action in actions))
    except (ValueError, TypeError, InvalidOperation):
        pass
    context.update(status="conditional_execution_followthrough", actions=actions,
        assumed_cash_after_at_stated_levels_before_fees=cash_after,
        scenario_price_basis="original displayed order levels only; actual fills, gaps, fees and settlement are unverified")
    return context


def validate_followthrough(decision: dict[str, Any], *, root: Path, current: datetime) -> None:
    context = decision.get("delivery_followthrough")
    if decision.get("owner_requested_research"):
        return  # Explicit owner review renders its own appendix, not this context.
    if context is None:
        return  # Exact dated legacy artifacts retain their original rendering.
    try:
        as_of = _stamp(context["as_of"])
        if as_of > current or as_of.astimezone(ET).date() != current.astimezone(ET).date():
            raise ValueError("followthrough_clock_invalid")
        expected = build_followthrough(decision, root=root, current=as_of)
        if context != expected:
            raise ValueError("followthrough_binding_changed")
        latest = build_followthrough(decision, root=root, current=current)
        latest["as_of"] = context["as_of"]
        if latest != context:
            raise ValueError("followthrough_recompose_required")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ValueError("delivery_followthrough_recompose_required") from exc


def continuation_requires_reconciliation(context: dict[str, Any]) -> bool:
    return context.get("status") in {"conditional_execution_followthrough", "prior_delivery_uncertain",
        "prior_exact_content_unavailable", "prior_action_not_structured", "account_record_bindings_unavailable",
        "records_updated_since_delivery", "multiple_deliveries_require_reconciliation"}


def continuation_lines(context: dict[str, Any]) -> list[str]:
    status = context.get("status")
    if status == "no_prior_same_day_delivery" or not status:
        return []
    time = context.get("prior_sent_at", "unconfirmed time")
    lead = f"Earlier email: {time}. "
    if status == "conditional_execution_followthrough":
        lines = [lead + "For follow-up planning only, use your assumption that the earlier instructions were completed as specified. "
                 "This owner assumption is not a verified order or fill and does not change recorded holdings, cash or blockers. "
                 "No additional portfolio-changing draft is supplied from unreconciled cash or shares; earlier protection remains subject to verification, not cancellation."]
        for action in context.get("actions", []):
            ticker = action["ticker"]
            lines.append(f"{ticker}: if the earlier {action['quantity']}-share {action['side']} fully filled during its original validity, "
                f"the assumed remaining holding is {action['assumed_remaining_shares']} shares. Do not repeat that {'sale' if action['side'] == 'sell' else 'purchase'}. "
                "Placing a stop or limit does not establish a fill; if pending, partial, unsubmitted or unknown, reconcile actual remaining shares and orders first.")
            if action["continuation"] == "execution_reconciliation_required":
                lines.append(f"{ticker}: confirm current holdings, remaining orders and execution funds before any additional draft; the earlier level is retained only for this labelled scenario.")
            elif action["continuation"] != "same_plan_do_not_repeat":
                lines.append(f"{ticker}: the earlier draft has expired or the maintained plan changed. Reconcile before considering a replacement or opposite action; no renewed price, deadline or additional quantity is supplied here.")
        if context.get("assumed_cash_after_at_stated_levels_before_fees") is not None:
            from email_brief import money
            lines.append("Illustrative cash after all listed assumed fills: "
                + money(context["assumed_cash_after_at_stated_levels_before_fees"])
                + " at the original stated levels, before unverified fees, slippage/gaps and settlement. This is a hypothetical calculation, not available buying power or authority for another order.")
        else:
            lines.append("Post-execution cash is not calculated: the exact price/cash basis is incomplete.")
        return lines
    messages = {
        "prior_delivery_uncertain": "Delivery status is uncertain; no execution assumption can be established. Check the earlier message and actual order/fill state before a continuation.",
        "prior_exact_content_unavailable": "Exact archived instructions are unavailable; no execution scenario has been reconstructed from the current report.",
        "prior_action_not_structured": "The previous review contained an up-to quantity or narrative, not a precise completed-order draft. No fill is assumed. Check actual holdings, fills and outstanding orders before another buy or sell.",
        "prior_no_specific_order": "The previous report contained no specific valid order draft; watch/hold/no-action does not create an assumed trade.",
        "account_record_bindings_unavailable": "The prior plan cannot be bound to the same account records; no post-execution quantities are assumed.",
        "records_updated_since_delivery": "Account, holdings or order records changed after that report. Current recorded evidence takes precedence over any assumed execution; this change alone does not prove the earlier order filled or reconcile every earlier instruction. Additional quantities remain withheld pending that reconciliation.",
        "verified_current_snapshot_supersedes": "A later complete owner-recorded account snapshot and sourced current order inventory now supply the actual-state basis. That verified snapshot supersedes the planning assumption; the earlier assumed trade is not applied again. Any new proposal still follows the unchanged canonical evidence and risk checks.",
        "multiple_deliveries_require_reconciliation": "Multiple earlier messages contain different or unstructured instructions. A later status update does not establish that earlier actions were completed or superseded. Reconcile those instructions before an additional portfolio-changing draft; no combined fills or quantities are invented.",
    }
    names = context.get("unstructured_candidate_tickers", []) if status == "prior_action_not_structured" else []
    if names:
        return [lead + "Earlier candidate(s): " + ", ".join(names) + ". "
                + messages[status]]
    return [lead + messages.get(status, "Continuation requires reconciliation.")]
