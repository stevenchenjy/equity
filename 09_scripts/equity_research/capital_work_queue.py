"""Durable research work for idle capital and dated plans; never allocation authority.

Cash has two disjoint accounting buckets. Reasons work remains unfinished are
explicitly overlapping explanations, not dollar allocations. This module only
consumes canonical decisions and optional research-backlog evidence.
"""
from __future__ import annotations

import copy
import json
import hashlib
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from daily_common import (ET, ExclusiveFileLock, atomic_write_json, atomic_write_text,
                          canonical_sha256, is_us_market_session_date)

SCHEMA = "equity_capital_work_queue_v1"
STORE_REL = Path("08_reviews/capital_work_queue.local/state.json")
REPORT_REL = Path("08_reviews/capital_work_queue.local/report.md")
LOCK_REL = Path("08_reviews/capital_work_queue.local/queue.lock")
BACKLOG_REL = Path("04_research/company_research/research_backlog.local.json")
ACTIVE_STATES = {"open", "blocked", "research_ready", "unverified"}
COMPLETED_PLAN_STATES = {"completed_observed", "completed", "cancelled", "superseded", "closed"}


def _aware(value: Any) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if stamp.tzinfo is None:
        raise ValueError("aware_time_required")
    return stamp.astimezone(ET)


def _money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _usd(value: Decimal | None) -> float | None:
    return float(value.quantize(Decimal("0.01"))) if value is not None else None


def _next_check(current: datetime, *, plan: bool = False, scheduler_state: dict | None = None) -> str:
    # Owner times are suggested appointments, never order expiry. Automatic
    # boundaries come from the installed scheduler implementation, not email time.
    from run_daily_refresh_scheduler import WEEKDAY_SLOTS, WEEKEND_SLOTS
    day = current.date()
    while True:
        if plan:
            slots = ["09:35"] if is_us_market_session_date(day) else []
        else:
            slots = WEEKEND_SLOTS if day.weekday() >= 5 else WEEKDAY_SLOTS
        completed = set(((scheduler_state or {}).get("dates", {}).get(day.isoformat(), {})).get("refresh_slots_completed", []))
        for slot in slots:
            stamp = datetime.combine(day, time.fromisoformat(slot), ET)
            if stamp > current and (plan or slot not in completed):
                return stamp.isoformat()
        day += timedelta(days=1)


def _blockers(row: dict) -> list[str]:
    value = row.get("gate_blockers", row.get("blockers", []))
    return sorted(set(str(x).strip() for x in (value.split(",") if isinstance(value, str) else value or []) if str(x).strip()))


def _item_semantic(item: dict) -> dict:
    return {k: item.get(k) for k in ("item_id", "kind", "ticker", "state", "priority", "condition",
        "next_step", "source_status", "blockers", "plan_id", "plan_version", "plan_record_hash",
        "preserved_purpose", "original_review_at", "original_time_exit_at", "gap_ids", "closure_reason",
        "canonical_classification", "maximum_review_price", "setup_outcome", "work_priority_rank", "review_owner", "evidence_status")}


def validate_state(state: dict) -> None:
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA:
        raise ValueError("queue_schema_invalid")
    if state.get("integrity_sha256") != canonical_sha256({k:v for k,v in state.items() if k != "integrity_sha256"}):
        raise ValueError("queue_integrity_invalid")
    if not isinstance(state.get("items"), list) or not isinstance(state.get("events"), list):
        raise ValueError("queue_shape_invalid")
    ids = [r.get("item_id") for r in state["items"] if isinstance(r, dict)]
    if len(ids) != len(state["items"]) or len(set(ids)) != len(ids) or not all(ids):
        raise ValueError("queue_item_identity_invalid")
    previous = ""
    for event in state["events"]:
        if event.get("previous_event_sha256") != previous or event.get("event_sha256") != canonical_sha256({k:v for k,v in event.items() if k != "event_sha256"}):
            raise ValueError("queue_event_chain_invalid")
        previous = event["event_sha256"]
    _aware(state["generated_at"])


def _plan_needed(plan: dict) -> bool:
    status = str(plan.get("status", ""))
    return status not in COMPLETED_PLAN_STATES and (
        any(token in status for token in ("expired", "review_due", "time_exit", "pending_verification", "conflict", "invalid", "failed", "missed"))
        or plan.get("setup_status") in {"failed", "expired", "missed"})


def build_capital_work_queue(decision: dict, previous: dict | None = None, *, current: datetime,
                             config: dict | None = None, research_backlog: dict | None = None,
                             source_receipts: list[dict] | None = None, scheduler_state: dict | None = None) -> dict:
    """Pure deterministic builder. Previous histories are preserved, not reconstructed."""
    current = _aware(current)
    now = current.isoformat()
    if previous is not None:
        validate_state(previous)
        if _aware(previous["generated_at"]) > current:
            raise ValueError("queue_clock_regression")
    if not isinstance(decision, dict) or not all(isinstance(decision.get(k), dict) for k in ("account", "capital_allocation", "plan_continuity")):
        raise ValueError("canonical_context_missing")
    decision_time = _aware(decision.get("generated_at"))
    if decision_time > current:
        raise ValueError("decision_from_future")
    if decision_time.date() != current.date():
        raise ValueError("canonical_decision_stale")
    account, plans = decision["account"], decision["plan_continuity"]
    if not isinstance(plans.get("plans"), list):
        raise ValueError("plan_context_invalid")
    plan_context_verified = plans.get("status") in {"current", "needs_reconciliation"}
    plan_rows = plans["plans"] if plan_context_verified else []
    cash, reserve, capital = (_money(account.get(k)) for k in ("cash_available", "cash_reserved", "account_total_value"))
    valid_cash = all(v is not None for v in (cash, reserve, capital)) and reserve <= cash and capital > 0
    remainder = cash - reserve if valid_cash else None
    source_decision = {k:v for k,v in decision.items() if k != "capital_work_queue"}
    decision_sha = canonical_sha256(source_decision)
    source = {"decision_generated_at": decision.get("generated_at"), "decision_sha256": decision_sha,
              "plan_ledger_head": plans.get("ledger_head"), "receipts": copy.deepcopy(source_receipts or [])}
    research_check = _next_check(current, scheduler_state=scheduler_state)
    desired: dict[str, dict] = {}
    terminal_plans = {str(p.get("plan_id")): p for p in plan_rows if p.get("status") in COMPLETED_PLAN_STATES}
    latest_plans = {str(p.get("plan_id")): p for p in plan_rows}
    for plan in plan_rows:
        if not _plan_needed(plan):
            continue
        plan_id, version, record_hash = plan.get("plan_id"), plan.get("version"), plan.get("record_hash")
        if not plan_id or not isinstance(version, int) or not isinstance(record_hash, str) or len(record_hash) != 64:
            raise ValueError("reassessment_source_binding_missing")
        ticker, status = str(plan.get("ticker", "")), str(plan.get("status", ""))
        identity = f"plan:{plan_id}:v{version}"
        tactical = plan.get("role") == "tactical" or "time_exit" in status
        desired[identity] = {"item_id": identity, "kind": "plan_reassessment", "ticker": ticker,
            "state": "blocked", "evidence_status": "current", "priority": 1 if tactical else 2, "source_status": status,
            "setup_outcome": plan.get("setup_status"), "blockers": _blockers(plan),
            "plan_id": plan_id, "plan_version": version, "plan_record_hash": record_hash,
            "preserved_purpose": plan.get("purpose") or plan.get("role"),
            "original_review_at": plan.get("review_at"), "original_time_exit_at": plan.get("time_exit_at"),
            "condition": "Record a sourced reassessment of the existing mandate; an elapsed date does not renew the plan.",
            "next_step": (f"Verify {ticker} fills, cancellations and available shares in one brief account check; then reassess the original "
                          f"{plan.get('role') or 'recorded'} purpose against current evidence and record maintain/reduce/close or an explicitly justified new mandate. No replacement order before reconciliation."),
            "next_review_at": _next_check(current, plan=True), "review_owner": "owner_account_check_then_research",
            "automatic_action_allowed": False, "eligible_quantity": 0,
            "source_refs": copy.deepcopy(plan.get("sources", [])), "evidence": source}
    # Canonical candidates only. Research backlog prioritizes work, never admits an order.
    candidates: dict[str, dict] = {}
    for name in ("watch_candidates", "pending_stability_candidates", "eligible_new_position_review_candidates"):
        for row in decision.get(name, []) or []:
            if isinstance(row, dict) and row.get("ticker"):
                candidates[str(row["ticker"])] = row
    eligible_tickers = {str(r.get("ticker")) if isinstance(r, dict) else str(r) for r in (decision.get("eligible_new_position_review_candidates") or [])}
    backlog_by = {str(row.get("ticker")): row for row in (research_backlog or {}).get("priority_queue", []) if isinstance(row, dict)}
    gap_by = {str(r.get("gap_id")): r for r in (research_backlog or {}).get("items", []) if isinstance(r, dict)}
    for ticker, row in candidates.items():
        blockers = _blockers(row)
        core = row.get("valuation_applicability") == "not_applicable_broad_market_etf" or "core" in str(row.get("action", ""))
        backlog = backlog_by.get(ticker, {})
        eligible = ticker in eligible_tickers
        identity = f"opportunity:{ticker}"
        if core:
            step = f"Recheck {ticker}'s existing core entry and whole-share rules after the next published close; review only within the unchanged core target and reserve."
        elif any("valuation" in b for b in blockers) or not row.get("valuation_base_price"):
            step = f"Complete {ticker}'s sourced debt/cash/dilution and company-specific valuation cases, then compare price, reward/risk and portfolio overlap."
        else:
            step = f"Recheck {ticker}'s observed entry, evidence validity and unchanged sizing gates after the next published close. Skip it if conditions fail."
        gap_steps = [str(gap_by[g]["next_step"]) for g in backlog.get("gap_ids", []) if g in gap_by and gap_by[g].get("next_step")]
        if gap_steps:
            step = f"{ticker}: " + " ".join(dict.fromkeys(gap_steps[:2])) + " Re-evaluate existing price and risk gates after the evidence changes."
        if eligible:
            step += " Canonical research eligibility still requires fresh execution checks and owner approval."
        desired[identity] = {"item_id": identity, "kind": "opportunity_research", "ticker": ticker,
            "state": "research_ready" if eligible else "blocked", "priority": 3 if core else 4,
            "source_status": str(row.get("action", "watch_only")), "blockers": blockers,
            "condition": "Evidence and price must satisfy the existing strategy before capital can be proposed; cash does not create a deadline to invest.",
            "next_step": step, "next_review_at": research_check, "review_owner": "scheduled_research_then_owner_if_eligible",
            "canonical_classification": row.get("label", "watchlist"),
            "maximum_review_price": row.get("maximum_review_price") or None,
            "work_priority_rank": backlog.get("priority_rank") if isinstance(backlog.get("priority_rank"), int) else 999,
            "gap_ids": list(backlog.get("gap_ids", [])), "priority_reasons": list(backlog.get("priority_reasons", [])),
            "automatic_action_allowed": False, "eligible_quantity": 0, "evidence": source}
    # A persistent recurring task keeps the system working even when no candidate qualifies.
    if remainder is not None and remainder > 0:
        desired["capital:recurring_review"] = {"item_id": "capital:recurring_review", "kind": "recurring_capital_review",
            "ticker": None, "state": "open", "priority": 5, "source_status": "unallocated_research_cash",
            "blockers": [], "condition": "Retain reserve and compare updated core, growth and cash alternatives at each completed research cycle.",
            "next_step": "Refresh existing public evidence, carry unfinished valuation work forward, and review changed entry conditions. Keep cash when no alternative passes; do not retune limits after a short streak.",
            "next_review_at": research_check, "review_owner": "scheduled_research",
            "automatic_action_allowed": False, "eligible_quantity": 0, "evidence": source}
    old = {r["item_id"]: copy.deepcopy(r) for r in (previous or {}).get("items", [])}
    events = copy.deepcopy((previous or {}).get("events", []))
    items: list[dict] = []
    for identity in sorted(set(old) | set(desired)):
        before, row = old.get(identity), copy.deepcopy(desired.get(identity))
        if row is None:
            row = copy.deepcopy(before)
            if row["state"] in ACTIVE_STATES and row["kind"] == "plan_reassessment" and not plan_context_verified:
                # A failed ledger read cannot close an outstanding failed/expired
                # task or make its old source binding look newly verified.
                row.update(state="unverified", evidence_status="unverified")
                row["blockers"] = sorted(set(row.get("blockers", []) + ["plan_context_unverified"]))
            elif row["state"] in ACTIVE_STATES:
                plan = terminal_plans.get(str(row.get("plan_id")))
                newer = latest_plans.get(str(row.get("plan_id")))
                row.update(state="resolved" if plan else "superseded" if newer and newer.get("version") != row.get("plan_version") else "not_observed",
                    closure_reason="canonical_plan_terminal" if plan else "new_recorded_plan_version" if newer and newer.get("version") != row.get("plan_version") else "absent_from_current_decision_not_proof_of_success",
                    closed_at=now)
        else:
            row.update(first_seen_at=before.get("first_seen_at", now) if before else now,
                       last_seen_at=now, occurrence=(before.get("occurrence", 1) + (before["state"] not in ACTIVE_STATES)) if before else 1)
            # An overdue unresolved task stays overdue. A routine refresh cannot defer it.
            if before and before["state"] in ACTIVE_STATES:
                row["next_review_at"] = before["next_review_at"]
        if before is None or _item_semantic(row) != _item_semantic(before):
            event = {"item_id": identity, "recorded_at": now, "event": "created" if before is None else "changed",
                     "previous_event_sha256": events[-1]["event_sha256"] if events else "",
                     "before": _item_semantic(before) if before else None, "after": _item_semantic(row),
                     "decision_sha256": decision_sha}
            event["event_sha256"] = canonical_sha256(event)
            events.append(event)
        items.append(row)
    active = sorted((r for r in items if r["state"] in ACTIVE_STATES), key=lambda r:(r["priority"], r.get("work_priority_rank", 999), r.get("ticker") or "", r["item_id"]))
    reason_codes = sorted({b for r in active for b in r.get("blockers", [])})
    if any(r["kind"] == "plan_reassessment" for r in active): reason_codes.append("dated_plan_reassessment_pending")
    if any(r["kind"] == "opportunity_research" and r["state"] == "blocked" for r in active): reason_codes.append("candidate_evidence_or_entry_unresolved")
    for name, code in (("market_gate", "market_evidence_unverified"), ("fundamental_gate", "fundamental_evidence_unverified"), ("evidence_gate", "official_evidence_unverified")):
        gate = decision.get(name)
        if isinstance(gate, dict) and gate.get("passed") is not True:
            reason_codes.append(code)
    if not valid_cash: reason_codes.append("planning_cash_inputs_invalid")
    if not plan_context_verified: reason_codes.append("plan_context_unverified")
    if decision.get("account_conflicts"): reason_codes.append("account_reconciliation_required")
    for key in ("global_blockers", "allocation_blockers", "global_reasons"):
        values = decision.get("workflow_integrity", {}).get(key, [])
        if isinstance(values, list): reason_codes.extend(str(v) for v in values if isinstance(v, str))
    reason_codes.append("execution_buying_power_not_verified_by_research_queue")
    integrity = decision.get("workflow_integrity", {})
    reason_details = [{"code": code, "scope": "global", "tickers": []} for code in integrity.get("global_blockers", [])]
    for ticker, codes in integrity.get("ticker_blockers", {}).items():
        reason_details.extend({"code": code, "scope": "ticker", "tickers": [ticker]} for code in codes)
    for strategy, codes in integrity.get("strategy_blockers", {}).items():
        reason_details.extend({"code": code, "scope": "strategy", "strategy": strategy, "tickers": []} for code in codes)
    for item in active:
        reason_details.extend({"code": code, "scope": "research_item", "tickers": [item["ticker"]] if item.get("ticker") else [], "item_id": item["item_id"]} for code in item.get("blockers", []))
    policy = (config or {}).get("account", {})
    cash_explanation = {"status": "planning_only" if valid_cash else "unverified", "planning_capital_usd": _usd(capital),
        "planning_cash_usd": _usd(cash), "strategic_reserve_usd": _usd(reserve),
        "unallocated_research_cash_usd": _usd(remainder), "cash_basis": account.get("cash_basis", "unverified"),
        "buckets_are_disjoint": True, "reason_amounts_are_additive": False,
        "execution_buying_power_usd": None, "execution_buying_power_verified": False,
        "overlapping_reasons": sorted(set(reason_codes)), "reason_details": reason_details,
        "reasons_are_blockers_for_all_candidates": False,
        "scope_note": "Ticker and plan research reasons apply to their named items; only canonical global blockers apply to every candidate.",
        "approved_targets_pct": {k:policy.get(k) for k in ("core_target_pct", "active_target_pct", "cash_target_pct")},
        "approved_risk_limits": copy.deepcopy(policy.get("research_risk_limits", {})),
        "explanation": "Only reserve plus unallocated research cash sum to planning cash. Evidence, price, pending-plan and execution checks overlap; they are not separate dollar buckets. Planning capital is not current broker buying power; no cash is assigned automatically."}
    state = {"schema_version": SCHEMA, "status": "current", "generated_at": now, "source": source,
        "automatic_action_allowed": False, "classification": "watchlist", "cash_explanation": cash_explanation,
        "items": items, "events": events, "runs": copy.deepcopy((previous or {}).get("runs", [])), "active_item_count": len(active),
        "top_opportunities": [copy.deepcopy(r) for r in active if r["kind"] == "opportunity_research"][:3],
        "plan_reassessment_status": "current" if plan_context_verified else "unverified",
        "plan_reassessment_queue": [copy.deepcopy(r) for r in active if r["kind"] == "plan_reassessment"],
        "next_automatic_review_at": research_check, "schedule_basis": "Existing full-refresh scheduler boundary; actual start depends on 900-second launchd polling and host availability.", "attention_policy": "Routine research refreshes automatically; combine outstanding account checks into a brief market-session review. No continuous intraday monitoring is assumed."}
    run = {"run_id": canonical_sha256(source), "observed_at": now, "source": source, "active_item_count": len(active)}
    if not any(r["run_id"] == run["run_id"] for r in state["runs"]):
        state["runs"].append(run)
    state["integrity_sha256"] = canonical_sha256(state)
    return state


def semantic_state(state: dict) -> dict:
    """Stable recommendation context; rendering clocks never request a new email."""
    return {"status":state.get("status"), "failure_code":state.get("failure_code"),
        "cash_explanation":state.get("cash_explanation"), "plan_reassessment_status":state.get("plan_reassessment_status"),
        "top_opportunities":[_item_semantic(r) for r in state.get("top_opportunities", [])],
        "plan_reassessment_queue":[_item_semantic(r) for r in state.get("plan_reassessment_queue", [])]}


def compact_summary(state: dict) -> dict:
    out = {k:copy.deepcopy(state[k]) for k in ("schema_version", "status", "generated_at", "cash_explanation", "top_opportunities",
        "plan_reassessment_queue", "plan_reassessment_status", "next_automatic_review_at", "attention_policy", "active_item_count", "automatic_action_allowed", "source", "schedule_basis")}
    for field in ("top_opportunities", "plan_reassessment_queue"):
        for row in out[field]:
            row.pop("evidence", None)
            row.pop("source_refs", None)
    out["semantic_sha256"] = canonical_sha256(semantic_state(out))
    return out


def render_report(state: dict) -> str:
    cash = state["cash_explanation"]
    lines = ["# Cash and ongoing research work", "", f"As of {state['generated_at']}. Research only; no automatic allocation.", "",
        f"Planning cash: {cash['planning_cash_usd']}; retained reserve: {cash['strategic_reserve_usd']}; unallocated research cash: {cash['unallocated_research_cash_usd']}.",
        cash["explanation"], "", "## Dated plan reassessments", ""]
    if state.get("plan_reassessment_status") != "current":
        lines.append("Current plan reassessment coverage is unverified; restore the source-bound plan context. Any retained tasks below remain unresolved historical work, not freshly verified instructions.")
    for row in state["plan_reassessment_queue"]:
        lines.append(f"- {row['ticker']} ({row['source_status']}; {row['plan_id']} v{row['plan_version']}): {row['next_step']} Review appointment: {row['next_review_at']}. Original deadline remains {row.get('original_time_exit_at') or row.get('original_review_at')}.")
    if not state["plan_reassessment_queue"] and state.get("plan_reassessment_status") == "current":
        lines.append("No current source-bound reassessment item.")
    lines += ["", "## Opportunity research", ""]
    for row in state["top_opportunities"]:
        lines.append(f"- {row['ticker']}: {row['next_step']} Next review: {row['next_review_at']}; unresolved: {', '.join(row['blockers']) or 'fresh execution checks and owner approval'}.")
    lines += ["", state["attention_policy"], f"Next automatic research review: {state['next_automatic_review_at']}.",
              f"History retained: {len(state['items'])} stable items and {len(state['events'])} changes; repeated refreshes do not duplicate tickets.", ""]
    return "\n".join(lines)


def refresh_capital_work_queue(decision: dict, *, root: Path, current: datetime, input_root: Path | None = None) -> dict:
    """Persist one private atomic state containing history; fail without erasing it.

    A missing optional backlog is reported as unavailable. Malformed previous
    queue state is never treated as a new empty queue. Fixed error codes keep
    exception details and account contents out of diagnostics.
    """
    root = Path(root).resolve()
    input_root = Path(input_root).resolve() if input_root is not None else root
    path = root / STORE_REL
    phase = "queue_read_failed"
    try:
        with ExclusiveFileLock(root / LOCK_REL):
            if path.is_symlink(): raise ValueError("linked_queue")
            previous = json.loads(path.read_text()) if path.exists() else None
            if previous is not None: validate_state(previous)
            phase = "queue_inputs_invalid"
            config_path = input_root / "00_project_control/active_production_config.json"
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
            backlog, backlog_status = None, "unavailable"
            backlog_path = input_root / BACKLOG_REL
            if backlog_path.exists() or "research_backlog" in decision:
                try:
                    from research_backlog import validate_report
                    # The decision's health verdict includes current refresh failure
                    # evidence. Never replace it with an older same-day success file.
                    if "research_backlog" in decision:
                        health = decision["research_backlog"]
                    else:
                        from work_queue_reporting import read_backlog_summary
                        health = read_backlog_summary(input_root, current=current)
                    if (not isinstance(health, dict) or health.get("status") not in {"ready", "current"}
                            or health.get("freshness") != "current"):
                        raise ValueError("backlog_latest_health_unverified")
                    candidate = json.loads(backlog_path.read_text())
                    validate_report(candidate, root=input_root, current=current)
                    backlog, backlog_status = candidate, "available"
                except (OSError, ValueError, TypeError):
                    backlog_status = "unverified"
            receipts = [{"path":str(config_path.relative_to(input_root)), "sha256":hashlib.sha256(config_path.read_bytes()).hexdigest()}] if config_path.exists() else []
            if backlog is not None:
                receipts.append({"path":str(BACKLOG_REL), "sha256":hashlib.sha256(backlog_path.read_bytes()).hexdigest()})
            scheduler_path = input_root / "00_project_control/run_logs/daily_scheduler_state.local.json"
            scheduler_state = json.loads(scheduler_path.read_text()) if scheduler_path.exists() else {}
            if not isinstance(scheduler_state, dict): raise ValueError("scheduler_state_invalid")
            state = build_capital_work_queue(decision, previous, current=current, config=config,
                research_backlog=backlog, source_receipts=receipts, scheduler_state=scheduler_state)
            phase = "queue_write_failed"
            atomic_write_json(path, state)
            # State is authoritative. A report-write failure must not pretend it vanished.
            try:
                atomic_write_text(root / REPORT_REL, render_report(state))
                report_status = "current"
            except OSError:
                report_status = "write_failed"
            summary = compact_summary(state)
            summary.update(backlog_status=backlog_status, report_status=report_status)
            return summary
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, ArithmeticError):
        return {"schema_version":SCHEMA, "status":"unverified", "failure_code":phase,
            "history_preserved":True, "automatic_action_allowed":False,
            "cash_explanation":{"status":"unverified", "execution_buying_power_verified":False},
            "top_opportunities":[], "plan_reassessment_queue":[], "plan_reassessment_status":"unverified"}
