"""Escalate verified idle capital; existing admission owners retain all authority.

The private ledger counts completed market observations, never pipeline cycles.
Ranking requests research and reuses admitted drafts; it cannot create a size,
weaken a gate, infer a fill, or connect to an account.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

from daily_common import (ET, ExclusiveFileLock, atomic_write_json, atomic_write_text,
                          canonical_sha256, is_us_market_session_date,
                          last_completed_market_session, latest_published_market_session, sha256_file)
from decision_dependencies import classify
from workflow_integrity import reviewed_candidate_ready

SCHEMA = "equity_capital_deployment_escalation_v1"
STATE_SCHEMA = "equity_capital_escalation_state_v1"
STORE_REL = Path("08_reviews/capital_escalation.local/state.json")
REPORT_REL = Path("08_reviews/capital_escalation.local/report.json")
TEXT_REL = Path("08_reviews/capital_escalation.local/report.md")
LOCK_REL = Path("08_reviews/capital_escalation.local/escalation.lock")
HISTORY_REL = Path("00_project_control/run_logs/decision_history.local.jsonl")
DAILY_REL = Path("04_research/company_research/daily_decision.json")
PROTECTED_INPUTS = (
    "00_project_control/active_production_config.json",
    "05_risk_and_positions/current_account_state.local.json",
    "05_risk_and_positions/current_positions.local.csv",
    "05_risk_and_positions/current_open_orders.local.json",
    "05_risk_and_positions/manual_account_snapshot.local.json",
    "07_automation/email_delivery/daily_delivery_ledger.csv",
    "06_execution_records/manual_executions.local.csv",
    "06_execution_records/pending_execution_report.csv",
    "06_execution_records/reconciliation_report.csv",
)
BUY = {"ACTIONABLE_BUY", "ACTIONABLE_ADD"}
ROUTES = {
    "existing_quality_holding": "Add to an existing high-quality company holding",
    "researched_growth_candidate": "Open the strongest researched growth candidate",
    "diversified_core_growth": "Add a diversified core/growth allocation",
}


def _aware(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("escalation_aware_time_required")
    return result.astimezone(ET)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def _codes(value: Any) -> list[str]:
    values = value.split(",") if isinstance(value, str) else value or []
    return sorted({str(v).strip() for v in values if str(v).strip()})


def _seal(value: dict, field: str) -> dict:
    value[field] = canonical_sha256({k: v for k, v in value.items() if k != field})
    return value


def _previous_session(session: str) -> str:
    prior = date.fromisoformat(session) - timedelta(days=1)
    while not is_us_market_session_date(prior):
        prior -= timedelta(days=1)
    return prior.isoformat()


def _session(decision: dict, contract: dict, current: datetime, *, bound_history: bool = False) -> tuple[str | None, str | None]:
    gate = decision.get("market_gate", {})
    session = gate.get("expected_market_session")
    try:
        day = date.fromisoformat(session)
        stamp = _aware(decision.get("generated_at", current))
        if not bound_history and (contract.get("schema_version") != "equity_capital_decision_v1"
                                  or contract.get("content_sha256") != canonical_sha256({k: v for k, v in contract.items() if k != "content_sha256"})
                                  or any(contract.get(k) is not False for k in ("automatic_action_allowed", "broker_connected", "order_placed"))):
            raise ValueError("unverified_capital_contract")
        if not bound_history and (not isinstance(contract.get("decisions"), list)
                                  or any(not isinstance(row, dict) or row.get("decision") not in BUY | {"HOLD", "NO_ACTION", "BLOCKED", "REDUCE_REVIEW", "EXIT_REVIEW"}
                                         or row.get("decision") in BUY and (type(row.get("shares")) is not int or row["shares"] <= 0 or not row.get("order_draft"))
                                         for row in contract["decisions"])):
            raise ValueError("invalid_capital_outcome")
        if stamp > current or not is_us_market_session_date(day):
            raise ValueError("invalid_session")
        if (gate.get("passed") is not True
                or not (gate.get("complete_close_verified") is True or gate.get("bar_state") == "complete_close")
                or contract.get("market_data_timestamp") != session
                or day > last_completed_market_session(current)
                or session not in {latest_published_market_session(current).isoformat(),
                                   last_completed_market_session(current).isoformat()}):
            raise ValueError("unverified_session")
        return session, None
    except (ValueError, TypeError):
        return None, "validated_completed_market_session_unavailable"


def validate_state(value: dict) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA:
        raise ValueError("escalation_state_schema_invalid")
    if value.get("integrity_sha256") != canonical_sha256({k: v for k, v in value.items() if k != "integrity_sha256"}):
        raise ValueError("escalation_state_integrity_invalid")
    generated = _aware(value["generated_at"])
    observations = value.get("session_observations")
    events = value.get("events")
    if not isinstance(observations, list) or not isinstance(events, list):
        raise ValueError("escalation_state_shape_invalid")
    previous = ""
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("escalation_session_observation_invalid")
        session = row.get("session")
        if (not is_us_market_session_date(date.fromisoformat(session))
                or session <= previous or type(row.get("actionable_seen")) is not bool
                or row.get("observation_sha256") != canonical_sha256({k: v for k, v in row.items() if k != "observation_sha256"})):
            raise ValueError("escalation_session_observation_invalid")
        first, last = _aware(row["first_observed_at"]), _aware(row["last_observed_at"])
        if first > last or last > generated or date.fromisoformat(session) > last_completed_market_session(first):
            raise ValueError("escalation_observation_clock_invalid")
        previous = session
    previous = ""
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("escalation_event_chain_invalid")
        if (event.get("previous_event_sha256") != previous
                or event.get("event_sha256") != canonical_sha256({k: v for k, v in event.items() if k != "event_sha256"})):
            raise ValueError("escalation_event_chain_invalid")
        previous = event["event_sha256"]


def _empty(current: datetime, *, origin: str = "new_verified_observation_ledger") -> dict:
    return _seal(dict(schema_version=STATE_SCHEMA, generated_at=current.isoformat(),
                      origin=origin, session_observations=[], events=[], automatic_action_allowed=False), "integrity_sha256")


def _observe(state: dict, session: str, contract: dict, current: datetime, *, source: str = "current_capital_contract") -> None:
    observations = state["session_observations"]
    actionable = any(row.get("decision") in BUY for row in contract.get("decisions", []))
    from capital_decision import meaning
    digest = canonical_sha256(meaning(contract))
    if observations and session == observations[-1]["session"]:
        row = observations[-1]
        if digest == row.get("capital_meaning_sha256") and (row["actionable_seen"] or not actionable):
            return
        row.update(actionable_seen=row["actionable_seen"] or actionable, last_observed_at=current.isoformat(),
                   capital_meaning_sha256=digest, source_sha256=contract.get("content_sha256", digest))
        kind = "same_session_outcome_changed"
    else:
        row = dict(session=session, first_observed_at=current.isoformat(), last_observed_at=current.isoformat(),
                   actionable_seen=actionable, capital_meaning_sha256=digest,
                   source_sha256=contract.get("content_sha256", digest), source=source)
        observations.append(row)
        kind = "completed_session_observed"
    _seal(row, "observation_sha256")
    event = dict(kind=kind, recorded_at=current.isoformat(), session=session,
                 observation_sha256=row["observation_sha256"],
                 previous_event_sha256=state["events"][-1]["event_sha256"] if state["events"] else "")
    state["events"].append(_seal(event, "event_sha256"))


def _streak(observations: list[dict]) -> tuple[int | None, str, str]:
    if not observations:
        return None, "unverified", "prior_completed_session_observation_missing"
    count = 0
    later = None
    for row in reversed(observations):
        if later and row["session"] != _previous_session(later):
            return (count, "verified", "verified_observed_run_after_history_gap") if count >= 2 else (None, "unverified", "completed_session_history_gap")
        if row["actionable_seen"]:
            return count, "verified", "actionable_session_reset"
        count += 1
        later = row["session"]
    return (count, "verified", "verified_observed_run") if count >= 2 else (None, "unverified", "prior_completed_session_observation_missing")


def _gate(code: str, *, ticker: str | None = None, scope: str = "ticker") -> dict:
    dependency = classify(code, ticker=ticker, scope=scope)
    if dependency["category"] == "C":
        category = "account"
    elif any(w in code for w in ("risk", "budget", "concentration", "portfolio_fit", "allocation_cap")):
        category = "risk"
    elif any(w in code for w in ("valuation", "upside", "reward_to_risk", "target_has_no_upside")):
        category = "valuation"
    elif code == "entry" or code.startswith("entry_above_") or any(w in code for w in ("price", "quote", "spread", "liquidity", "halt", "market", "complete_close", "distinct_close")):
        category = "price"
    elif code in {"score", "whole_share_target_gap", "not_in_canonical_eligible_set", "canonical_buy_not_eligible"} or any(w in code for w in ("strategy", "policy", "purpose_change", "adoption", "core_minimum", "source_bound_allocation")):
        category = "policy"
    else:
        category = "evidence"
    result = dict(code=code, category=category, scope=scope, ticker=ticker,
                  resolver=dependency["resolver"], evidence_required=dependency["evidence_required"])
    if code == "whole_share_target_gap":
        result["evidence_required"] = "Current core holdings already cover the reviewed minimum, so the minimum-core adapter has no additional whole-share authority."
    if code == "core_minimum_satisfied_no_additional_tranche_authority":
        result["evidence_required"] = "A separately reviewed and adopted above-minimum diversified-growth allocation policy is required; the core floor alone cannot authorize another tranche."
    return result


def _research_gate(code: str) -> bool:
    if code in {"score", "upside", "reward_to_risk", "entry", "portfolio_fit", "whole_share_target_gap", "not_in_canonical_eligible_set", "canonical_buy_not_eligible", "confidence"}:
        return False
    return (any(w in code for w in ("thesis", "counterevidence", "maintained_company", "company_specific_valuation", "valuation_unverified", "valuation_missing", "financial", "fundamentals", "incorporation", "objective", "debt_latest", "cash_latest", "ttm_", "dilution", "business_case", "issuer_prospectus", "structure_review"))
            or classify(code)["category"] in {"A", "B"} and not any(w in code for w in ("market", "price_history", "calendar", "complete_close", "latest_completed")))


def _observed_gate(gate: dict, watch: dict, config: dict, *, core_value: Decimal | None, total: Decimal | None, floor: Decimal | None) -> dict:
    """Describe the owner's observed numbers; no score or threshold is changed."""
    code = gate["code"]
    tiers = config.get("account", {}).get("candidate_sizing_tiers", [])
    def minimum(key: str) -> Decimal | None:
        values = [_number(t.get(key)) for t in tiers]
        return min(v for v in values if v is not None) if any(v is not None for v in values) else None
    score, minimum_score = _number(watch.get("score")), minimum("minimum_score")
    price, cap = _number(watch.get("current_price")), _number(watch.get("maximum_review_price"))
    if code == "score" and score is not None and minimum_score is not None:
        gate["evidence_required"] = f"Canonical reviewed score {score:.2f}; the lowest approved sizing tier requires {minimum_score:.2f}. A supported assessment must satisfy an existing tier; escalation does not raise the score."
    elif code in {"entry", "entry_above_canonical_maximum"} and price is not None and cap is not None:
        gate["evidence_required"] = f"Canonical completed price ${price:.2f}; maximum reviewed entry ${cap:.2f}. Entry must satisfy the existing dated price and validity rules."
    elif code in {"upside", "observed_target_has_no_upside"}:
        value, low = _number(watch.get("expected_upside_pct")), minimum("minimum_expected_upside_pct")
        if low is not None:
            observed = f"Canonical expected upside {value:.2f}%; " if value is not None else "Canonical upside gate failed; "
            gate["evidence_required"] = observed + f"the lowest approved sizing tier requires {low:.2f}%. A new sourced valuation or changed observed price must satisfy an existing tier."
    elif code in {"reward_to_risk", "reward_to_risk_below_minimum"}:
        value = _number(watch.get("reward_to_risk_estimate", watch.get("reward_to_risk")))
        low = minimum("minimum_reward_to_risk")
        if low is not None:
            observed = f"Canonical reward-to-risk {value:.2f}; " if value is not None else "Canonical reward-to-risk gate failed; "
            gate["evidence_required"] = observed + f"the lowest approved sizing tier requires {low:.2f}. Keep the reviewed entry, invalidation and reassessment criteria."
    elif code in {"whole_share_target_gap", "core_minimum_satisfied_no_additional_tranche_authority"} and core_value is not None and total is not None and total > 0 and floor is not None:
        gate["evidence_required"] = f"Current held core weight {core_value / total * 100:.2f}% already covers the approved {floor:.2f}% minimum. The core-floor adapter has no additional whole-share authority; an above-floor diversified-growth allocation requires a separately reviewed adopted policy."
    return gate


def order_options(decision: dict, contract: dict, config: dict | None = None) -> list[dict]:
    """Rank every final outcome, including HOLD add gates, without sizing it."""
    config = config or {}
    held = {row["ticker"]: row for row in decision.get("held_positions", []) if row.get("ticker")}
    watch = {row["ticker"]: row for row in decision.get("watch_candidates", []) if row.get("ticker")}
    plans = {row["ticker"]: row for row in decision.get("plan_continuity", {}).get("plans", []) if row.get("ticker")}
    context = decision.get("research_opportunities", {})
    opportunities = {row["ticker"]: row for row in context.get("decision_candidates", context.get("priority_queue", [])) if row.get("ticker")}
    views = decision.get("long_horizon_research", {})
    eligible_set = set(decision.get("eligible_new_position_review_candidates", [])) | set(decision.get("eligible_action_review_candidates", []))
    total = _number(decision.get("account", {}).get("account_total_value"))
    floor = _number(config.get("account", {}).get("core_minimum_pct", config.get("account", {}).get("core_target_pct")))
    core_value = Decimal(0)
    core_known = True
    for row in held.values():
        if row.get("asset_role") == "core_allocation":
            qty, price = _number(row.get("current_shares")), _number(row.get("current_price"))
            if qty is None or price is None or min(qty, price) < 0:
                core_known = False
            else:
                core_value += qty * price
    ranked = []
    global_codes = sorted(set(_codes(contract.get("global_blockers"))) | set(_codes(decision.get("workflow_integrity", {}).get("global_blockers"))))
    if decision.get("account_conflicts"):
        global_codes = sorted(set(global_codes + ["account_or_execution_conflict"]))
    for row in contract.get("decisions", []):
        ticker = row.get("ticker")
        if not ticker:
            continue
        h, w, p = held.get(ticker, {}), watch.get(ticker, {}), plans.get(ticker, {})
        opportunity = opportunities.get(ticker, {})
        security_kind = str(w.get("security_type", w.get("asset_type", opportunity.get("instrument_kind", opportunity.get("security_type", opportunity.get("asset_type", "")))))).lower()
        issuer = str(opportunity.get("issuer_name", opportunity.get("company_name", opportunity.get("name", "")))).lower()
        fund_prospect = security_kind in {"etf", "fund", "exchange_traded_fund"} or any(word in issuer.split() for word in ("etf", "fund"))
        core = (h.get("asset_role") == "core_allocation" or w.get("asset_role") in {"core_allocation", "core_allocation_candidate"}
                or w.get("valuation_applicability") == "not_applicable_broad_market_etf"
                or p.get("role") == "broad_core")
        route = "diversified_core_growth" if core or fund_prospect else "existing_quality_holding" if h else "researched_growth_candidate"
        view = views.get("candidate_views", {}).get(ticker, views.get("views", {}).get(ticker, {}))
        ready = core or reviewed_candidate_ready(view)
        admitted = row.get("decision") in BUY and not row.get("blockers") and not global_codes
        draft = row.get("order_draft") if admitted else None
        qty = _number(row.get("shares"))
        admitted = bool(admitted and draft and draft.get("side") == "buy" and draft.get("automatic_action_allowed") is False
                        and qty is not None and qty > 0 and qty == qty.to_integral_value()
                        and (_number(row.get("estimated_notional")) or Decimal(0)) > 0)
        codes = set(_codes(row.get("blockers")) + global_codes)
        if not admitted:
            codes.update(_codes(w.get("gate_blockers")))
            codes.update(_codes(opportunity.get("blockers")))
            codes.update(_codes(p.get("blockers")))
            for gate in ("workflow_integrity", "evidence_gate", "fundamental_gate"):
                codes.update(_codes(decision.get(gate, {}).get("ticker_blockers", {}).get(ticker)))
            codes.update(d["code"] for d in row.get("dependencies", []) if d.get("code"))
            if ticker not in eligible_set:
                codes.add("not_in_canonical_eligible_set")
            if core and core_known and total is not None and total > 0 and floor is not None and core_value >= total * floor / 100:
                codes.update({"whole_share_target_gap", "core_minimum_satisfied_no_additional_tranche_authority"})
            if h and not core and p.get("role") not in {"tactical", "long_term_growth"}:
                codes.add("position_purpose_change_requires_recorded_reassessment")
            if not codes:
                codes.add("strategy_entry_and_risk_contract_unavailable")
        score = _number(w.get("score", h.get("score")))
        ranked.append(dict(ticker=ticker, route=route, decision=row.get("decision"), eligible=admitted,
                           blockers=sorted(codes), gates=[_observed_gate(_gate(c, ticker=ticker, scope="global" if c in global_codes else "ticker"), w, config,
                                                                       core_value=core_value if core_known else None, total=total, floor=floor) for c in sorted(codes)],
                           research_ready=ready, canonical_score=float(score) if score is not None else None,
                           shares=row.get("shares", 0) if admitted else 0,
                           estimated_notional=row.get("estimated_notional", 0) if admitted else 0,
                           order_draft=deepcopy(draft) if admitted else None,
                           current_price=w.get("current_price", h.get("current_price")),
                           maximum_review_price=w.get("maximum_review_price"),
                           valuation_base_price=w.get("valuation_base_price"),
                           valuation_bull_price=w.get("valuation_bull_price"),
                           canonical_confidence=w.get("confidence"),
                           canonical_evidence_status="known" if score is not None else "unverified",
                           route_available="core_minimum_satisfied_no_additional_tranche_authority" not in codes,
                           reasons=deepcopy(row.get("reasons", []))))
    ranked.sort(key=lambda r: (not r["eligible"], not r["route_available"], not r["research_ready"],
                               r["canonical_score"] is None, len(r["blockers"]),
                               -(r["canonical_score"] if r["canonical_score"] is not None else -1), r["ticker"]))
    for index, row in enumerate(ranked, 1):
        row["rank"] = index
    return ranked


def _build(decision: dict, contract: dict, previous: dict | None, config: dict | None, current: datetime) -> tuple[dict, dict | None]:
    current = _aware(current)
    config = config or {}
    policy = config.get("workflow", {}).get("capital_deployment_escalation", {})
    required = policy.get("required_sessions", 2)
    threshold = _number(policy.get("material_excess_cash_pct", 5))
    policy_valid = type(required) is int and required >= 2 and threshold is not None and 0 <= threshold <= 100
    if not policy_valid:
        required, threshold = 2, Decimal(5)
    ledger_error = None
    try:
        if previous is not None:
            validate_state(previous)
            if _aware(previous["generated_at"]) > current:
                raise ValueError("escalation_state_clock_regression")
        state = deepcopy(previous) if previous is not None else _empty(current)
    except (ValueError, TypeError, KeyError):
        state, ledger_error = None, "prior_session_state_corrupt_or_from_future"
    session, session_error = _session(decision, contract, current)
    if state is not None and session and state["session_observations"] and session < state["session_observations"][-1]["session"]:
        ledger_error = "completed_session_regression"
    if state is not None and session and not ledger_error:
        _observe(state, session, contract, current)
        state["generated_at"] = current.isoformat()
        _seal(state, "integrity_sha256")
    count, history_status, history_reason = _streak(state["session_observations"] if state else [])
    if ledger_error or session_error:
        count, history_status, history_reason = None, "unverified", ledger_error or session_error
    global_codes = set(_codes(contract.get("global_blockers")))
    global_codes.update(_codes(decision.get("workflow_integrity", {}).get("global_blockers")))
    if decision.get("account_conflicts"):
        global_codes.add("account_or_execution_conflict")
    account_codes = sorted(c for c in global_codes if classify(c, scope="global")["category"] == "C")
    account = decision.get("account", {})
    total, available, reserve = (_number(account.get(k)) for k in ("account_total_value", "cash_available", "cash_reserved"))
    target = _number(config.get("account", {}).get("cash_target_pct"))
    valid_cash = all(v is not None for v in (total, available, reserve, target)) and total > 0 and 0 <= reserve <= available <= total and 0 <= target <= 100
    # The capital owner deducts admitted buy drafts from its shared budget and
    # never adds conditional exit proceeds. Reverse only those buy deductions:
    # drafted buys remain cash until observed execution. Known pending-order
    # reservations and the mandatory reserve remain deducted.
    remainder = _number(contract.get("estimated_uncommitted_cash_after"))
    if remainder is not None:
        for row in contract.get("decisions", []):
            amount = _number(row.get("estimated_notional", 0))
            if amount is None or amount < 0:
                remainder = None
                break
            if row.get("order_draft", {}) and row["order_draft"].get("side") == "buy":
                remainder += amount
    if not valid_cash or remainder is None or not 0 <= remainder <= available - reserve:
        valid_cash = False
        account_codes = sorted(set(account_codes + ["shared_account_values_unverified"]))
    cash_target = total * target / 100 if valid_cash else None
    excess = max(Decimal(0), remainder - cash_target) if valid_cash else None
    excess_pct = excess / total * 100 if valid_cash else None
    material = bool(excess_pct is not None and excess_pct > threshold)
    cash = dict(uncommitted_cash_usd=float(remainder) if valid_cash else None,
                account_value_usd=float(total) if valid_cash else None,
                cash_target_pct=float(target) if target is not None else None,
                cash_target_usd=float(cash_target) if cash_target is not None else None,
                excess_cash_usd=float(excess) if excess is not None else None,
                excess_cash_pct=float(excess_pct) if excess_pct is not None else None,
                material_excess_cash_pct=float(threshold), materially_above_target=material,
                material_threshold_is_operational_trigger_not_risk_limit=True)
    ranked = order_options(decision, contract, config)
    admitted = [{k: deepcopy(r[k]) for k in ("ticker", "decision", "shares", "estimated_notional", "order_draft")} for r in ranked if r["eligible"]]
    triggered = bool(policy_valid and material and not account_codes and not session_error and not ledger_error and count is not None and count >= required)
    if account_codes:
        status = "account_integrity_blocked"
    elif session_error:
        status = "session_unverified"
    elif not policy_valid or ledger_error or history_status != "verified":
        status = "history_unverified"
    elif admitted:
        status = "actionable_available"
    elif triggered:
        status = "active"
    elif not material:
        status = "cash_target_met"
    else:
        status = "monitoring"
    routes = []
    for route, label in ROUTES.items():
        choices = [r for r in ranked if r["route"] == route]
        route_status = ("unavailable" if not any(r["route_available"] for r in choices)
                        else "available" if any(r["research_ready"] or r["eligible"] for r in choices) else "research_incomplete")
        routes.append(dict(route=route, label=label, status=route_status,
                           closest_candidate=deepcopy(choices[0]) if choices else None,
                           blockers=(["core_minimum_satisfied_no_additional_tranche_authority"] if choices and not any(r["route_available"] for r in choices) else []) if choices else ["no_existing_company_holding" if route == "existing_quality_holding" else "no_final_capital_candidate_in_route"]))
    requests = []
    for row in ranked:
        research = [g for g in row["gates"] if _research_gate(g["code"])]
        if research and row["ticker"] not in {r["ticker"] for r in requests}:
            requests.append(dict(ticker=row["ticker"], priority=len(requests) + 1,
                                 urgency="immediate" if triggered else "normal", blockers=[g["code"] for g in research],
                                 required_work=deepcopy(research), completed=False))
        if len(requests) >= 3:
            break
    unique_gates = {(g["scope"], g["ticker"], g["code"]): g for row in ranked for g in row["gates"]}
    for code in sorted(global_codes | set(account_codes)):
        unique_gates[("global", None, code)] = _gate(code, scope="global")
    if not policy_valid:
        unique_gates[("global", None, "capital_escalation_trigger_policy_invalid")] = _gate("capital_escalation_trigger_policy_invalid", scope="global")
    closest = next((r for r in ranked if not r["eligible"]), None) if not admitted else ranked[0]
    if admitted:
        explanation = "Existing approved criteria produced a positive conditional manual order draft; retain its exact quantity, validity and gates."
    elif material:
        explanation = "Excess cash remains undeployed because the exact evidence, valuation, price, risk, policy or account gates below prevent an admitted positive draft."
    else:
        explanation = "Verified uncommitted cash is within the approved target plus the configured materiality trigger, or cash cannot yet be verified."
    summary = dict(schema_version=SCHEMA, generated_at=current.isoformat(), status=status, triggered=triggered,
                   required_sessions=required, consecutive_no_action_sessions=count,
                   session_history_status=history_status, session_history_reason=history_reason,
                   observation_session=session, session_ledger_sha256=state.get("integrity_sha256") if state else None,
                   cash=cash, account_integrity_blockers=account_codes, gates=list(unique_gates.values()),
                   ranked_capital_uses=ranked, routes=routes, closest_candidate=deepcopy(closest),
                   admitted_order_drafts=admitted, research_priority_tickers=[r["ticker"] for r in requests],
                   research_requests=requests, explanation=explanation, automatic_action_allowed=False,
                   research_completion_claimed=False, broker_connected=False,
                   source_capital_sha256=contract.get("content_sha256"))
    return _seal(summary, "content_sha256"), state if not ledger_error and not session_error else None


def evaluate(decision: dict, contract: dict, previous: dict | None = None,
             config: dict | None = None, current: datetime | None = None) -> dict:
    """Pure evaluation; previous is the validated private session state."""
    return _build(decision, contract, previous, config, _aware(current or decision.get("generated_at")))[0]


def _bootstrap(root: Path, current: datetime) -> dict | None:
    """Only hash-bound capital outcomes can seed sessions; legacy screens cannot."""
    path = root / HISTORY_REL
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError("linked_decision_history")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    previous_hash = ""
    state = _empty(current, origin="verified_hash_bound_decision_history")
    for row in rows:
        workflow = row.get("workflow", {})
        if (row.get("schema_version") != "equity_decision_history_v1"
                or row.get("previous_hash") != previous_hash
                or row.get("record_hash") != canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
                or row.get("workflow_fingerprint") != canonical_sha256(workflow)):
            raise ValueError("decision_history_hash_chain_invalid")
        previous_hash = row["record_hash"]
        contract = workflow.get("capital_decision")
        if not contract:
            continue
        if "market_gate_failed" in _codes(contract.get("global_blockers")):
            continue
        stamp = _aware(row["recorded_at"])
        if stamp > current:
            raise ValueError("decision_history_from_future")
        session = contract.get("market_data_timestamp")
        if (contract.get("schema_version") != "equity_capital_decision_v1"
                or any(contract.get(k) is not False for k in ("automatic_action_allowed", "broker_connected", "order_placed"))
                or not isinstance(contract.get("decisions"), list)
                or any(r.get("decision") not in BUY | {"HOLD", "REDUCE_REVIEW", "EXIT_REVIEW", "NO_ACTION", "BLOCKED"} for r in contract["decisions"])):
            raise ValueError("decision_history_capital_contract_invalid")
        synthetic = dict(generated_at=stamp.isoformat(), market_gate=dict(passed=True, complete_close_verified=True, expected_market_session=session))
        valid_session, error = _session(synthetic, contract, stamp, bound_history=True)
        if error:
            continue
        if state["session_observations"] and valid_session < state["session_observations"][-1]["session"]:
            raise ValueError("decision_history_session_regression")
        _observe(state, valid_session, contract, stamp, source="hash_bound_decision_history")
    return _seal(state, "integrity_sha256") if state["session_observations"] else None


def _text(summary: dict) -> str:
    cash = summary["cash"]
    lines = ["# Capital deployment escalation", "", "Generated: " + summary["generated_at"], "",
             "Status: " + summary["status"], "Consecutive completed no-action sessions: " + str(summary["consecutive_no_action_sessions"]),
             "History: " + summary["session_history_reason"],
             "Excess cash: " + str(cash["excess_cash_usd"]) + "; target cash: " + str(cash["cash_target_usd"]), "", summary["explanation"], ""]
    for route in summary["routes"]:
        lines.append(route["label"] + ": " + route["status"])
        candidate = route["closest_candidate"]
        if candidate:
            lines.append(candidate["ticker"] + " — " + str(candidate["decision"]) + "; exact gates: " + (", ".join(candidate["blockers"]) or "none"))
        else:
            lines.append("Exact gate: " + ", ".join(route["blockers"]))
        lines.append("")
    lines.extend("- " + (g["ticker"] or "account-wide") + " / " + g["category"] + " / " + g["code"] + ": " + g["evidence_required"] for g in summary["gates"])
    lines.extend(["", "Immediate research requests: " + (", ".join(r["ticker"] for r in summary["research_requests"] if r["urgency"] == "immediate") or "none"),
                  "Research requests are work to complete, not completed research. Existing conditional drafts require human review; no automatic action is authorized.", ""])
    return "\n".join(lines)


def presentation_lines(summary: dict) -> list[str]:
    """Use the same exact gates in the private report and adjacent renderers."""
    return _text(summary).splitlines()


def refresh(root: Path, decision: dict, contract: dict, *, current: datetime) -> dict:
    """Locked refresh preserves corrupt/history-regressed state and exposes it."""
    root, current = Path(root).resolve(), _aware(current)
    config = json.loads((root / "00_project_control/active_production_config.json").read_text())
    with ExclusiveFileLock(root / LOCK_REL):
        path = root / STORE_REL
        try:
            if path.is_symlink():
                raise ValueError("linked_escalation_state")
            previous = json.loads(path.read_text()) if path.exists() else _bootstrap(root, current)
        except (OSError, ValueError, TypeError, KeyError):
            previous = {"schema_version": "invalid_preserved_state"}
        summary, state = _build(decision, contract, previous, config, current)
        summary["protected_source_bindings"] = {rel: sha256_file(root / rel) if (root / rel).is_file() else None for rel in PROTECTED_INPUTS}
        _seal(summary, "content_sha256")
        if state is not None:
            atomic_write_json(path, state)
        atomic_write_json(root / REPORT_REL, summary)
        atomic_write_text(root / TEXT_REL, _text(summary))
    decision["capital_deployment_escalation"] = summary
    return summary


def research_priorities(root: Path, current: datetime) -> list[str]:
    """Read only current, hash-bound immediate requests for bounded workers."""
    try:
        current = _aware(current)
        summary = json.loads((Path(root) / REPORT_REL).read_text())
        state = json.loads((Path(root) / STORE_REL).read_text())
        decision = json.loads((Path(root) / DAILY_REL).read_text())
        validate_state(state)
        stamp = _aware(summary["generated_at"])
        if (summary.get("schema_version") != SCHEMA
                or summary.get("content_sha256") != canonical_sha256({k: v for k, v in summary.items() if k != "content_sha256"})
                or summary.get("session_ledger_sha256") != state["integrity_sha256"]
                or decision.get("capital_deployment_escalation", {}).get("content_sha256") != summary["content_sha256"]
                or decision.get("capital_decision", {}).get("content_sha256") != summary.get("source_capital_sha256")
                or summary.get("protected_source_bindings") != {rel: sha256_file(Path(root) / rel) if (Path(root) / rel).is_file() else None for rel in PROTECTED_INPUTS}
                or not 0 <= (current - stamp).total_seconds() <= 86400
                or summary.get("status") != "active" or summary.get("triggered") is not True
                or summary.get("observation_session") not in {latest_published_market_session(current).isoformat(), last_completed_market_session(current).isoformat()}):
            return []
        return list(dict.fromkeys(r["ticker"] for r in summary.get("research_requests", []) if r.get("urgency") == "immediate"))[:3]
    except (OSError, ValueError, TypeError, KeyError):
        return []
