"""Explain existing capital decisions and route unfinished research, without admission.

This projection is read-only. It does not screen securities, change a canonical
action, renew a plan, size a trade or turn an experimental setup into capital.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from daily_common import canonical_sha256, latest_published_market_session, read_json, sha256_file

SCHEMA = "equity_strategy_framework_v1"
ACTIONABLE = {"ACTIONABLE_BUY", "ACTIONABLE_ADD", "REDUCE_REVIEW", "EXIT_REVIEW"}
CLASSES = {"valid_action", "justified_no_action", "research_incomplete", "plan_expired",
           "data_unavailable", "strategy_not_adopted"}
MAX_HANDOFF = 10
POLICY_PATHS = ("00_project_control/active_production_config.json", "01_policies/tactical_trade_policy.json")
IMPLEMENTATION_REL = "09_scripts/equity_research/decision_readiness.py"


def _stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _rows(value: Any) -> list[dict]:
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def _codes(row: dict) -> list[str]:
    raw = row.get("blockers", [])
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _strategies() -> list[dict]:
    return [
        dict(strategy_id="broad_core", label="Index core", horizon="Maintained index allocation",
             status="owner_approved", capital_authority=True,
             description="SPY and QQQM combined core; separate allocation and entry rules, no company valuation gate."),
        dict(strategy_id="long_term_growth", label="Company growth", horizon="Authored company-model horizon",
             status="owner_approved", capital_authority=True,
             description="Current company thesis, bear/base/bull valuation, reviewed allocation and dated plan; numerical gates remain unchanged."),
        dict(strategy_id="tactical_5_session", label="Existing tactical", horizon="At most five trading sessions",
             status="owner_approved", capital_authority=True,
             description="Existing canonical eligibility first, then daily-bar entry, observed invalidation/target and existing tactical risk limits."),
        dict(strategy_id="swing_5_14_research", label="Swing research", horizon="Five to fourteen trading sessions (research only)",
             status="experimental_not_adopted", capital_authority=False,
             description="Separate setup evaluation and forward measurement; no cleared shares, trade instruction or production strategy adoption."),
    ]


def _strategy(plan: dict, row: dict, *, core_tickers: set[str]) -> tuple[str, str]:
    horizon = plan.get("strategy_horizon")
    role = plan.get("role")
    adapter = (row.get("strategy_source") or {}).get("adapter", "")
    if role == "broad_core" or horizon == "broad_core" or adapter == "core_tranche" or row.get("ticker") in core_tickers:
        return "broad_core", "Maintained index allocation"
    if role == "tactical" or horizon in {"multi_day_trend", "intraday_momentum"} or adapter == "reviewed_tactical":
        return "tactical_5_session", str(horizon or "At most five trading sessions")
    case = row.get("research_case") or {}
    return "long_term_growth", str(case.get("horizon") or (plan.get("purpose") or {}).get("holding_period_justification")
                                    or "Company-model horizon not yet verified")


def _accepted(plan: dict, view: dict, case: dict) -> list[dict]:
    records = []
    if plan.get("plan_id") and plan.get("record_hash"):
        records.append(dict(kind="plan", record_id=plan["plan_id"], version=plan.get("version"),
                            record_sha256=plan["record_hash"], status=plan.get("status", "unverified")))
    original = view.get("review_record") or {}
    if original.get("review_id") and original.get("record_sha256"):
        records.append(dict(kind="thesis", record_id=original["review_id"], version=original.get("version"),
                            record_sha256=original["record_sha256"], status=view.get("status", "unverified")))
    if case.get("model_sha256"):
        records.append(dict(kind="valuation_source", record_id=case.get("model_relative_path", ""),
                            version=None, record_sha256=case["model_sha256"],
                            status=case.get("model_admission_status", "unverified")))
    return records


def _expired(plan: dict, current: datetime) -> bool:
    status = str(plan.get("status", ""))
    if any(word in status for word in ("expired", "time_exit_due", "missed")) or plan.get("setup_status") in {"expired", "missed"}:
        return True
    return any((clock := _stamp(plan.get(key))) is not None and current >= clock
               for key in ("valid_until", "time_exit_at"))


def _classify(row: dict, plan: dict, *, current: datetime, capital_valid: bool,
              market_current: bool) -> tuple[str, str]:
    if not capital_valid:
        return "data_unavailable", "publication_recomposition"
    # Existing validated reductions/exits may be independent of new-capital
    # evidence failures. Never hide that contract behind a growth-data failure.
    if row.get("decision") in ACTIONABLE and row.get("order_draft"):
        return "valid_action", "owner_manual_review"
    if _expired(plan, current):
        return "plan_expired", "recurring_analyst"
    deps = _rows(row.get("dependencies"))
    codes = _codes(row)
    if any(any(token in code for token in ("strategy_not_adopted", "strategy_not_production_adopted", "adoption_required",
                                           "experiment_not_adopted", "strategy_definition",
                                           "production_strategy_adapter_not_uniquely_admitted", "strategy_mature_evidence_review_missing")) for code in codes):
        return "strategy_not_adopted", "strategy_review_then_owner_adoption"
    if not market_current or any(d.get("category") in {"A", "B", "C"} for d in deps):
        manual = any(d.get("category") == "C" for d in deps)
        resolver = "approved_manual_account_record" if manual else "approved_public_refresh"
        if market_current and not manual:
            resolver = str(next((d.get("resolver") for d in deps if d.get("category") in {"A", "B"} and d.get("resolver")), resolver))
        return "data_unavailable", resolver
    if row.get("decision") == "BLOCKED" or codes:
        return "research_incomplete", str(next((d.get("resolver") for d in deps if d.get("resolver")), "recurring_analyst"))
    return "justified_no_action", "monitor_changed_evidence"


def _handoff(rows: list[dict], decision: dict, *, report: dict | None) -> list[dict]:
    """Bound work, not final coverage; collector observations never become analysis."""
    tasks: list[dict] = []
    by_ticker = {r["ticker"]: r for r in rows}
    held = {str(r.get("ticker")) for r in _rows(decision.get("held_positions"))}
    queue = decision.get("capital_work_queue") or {}
    for task in _rows(queue.get("plan_reassessment_queue")) + _rows(queue.get("top_opportunities")):
        row = by_ticker.get(str(task.get("ticker")), {})
        if task.get("state") in {"monitoring", "assessed_waiting_reassessment", "resolved", "closed"}:
            continue
        if not task.get("next_step"):
            continue
        tasks.append(dict(ticker=str(task.get("ticker", "")), classification=row.get("classification", "research_incomplete"),
                          reason=task.get("condition") or task.get("source_status", ""), next_step=task["next_step"],
                          resolver=task.get("review_owner") or row.get("resolver", "recurring_analyst"),
                          review_at=task.get("next_review_at"), accepted_records=deepcopy(row.get("accepted_records", [])),
                          source_ids=[task["item_id"]] if task.get("item_id") else [],
                          priority=min(task.get("priority", 4), 1) if task.get("ticker") in held else task.get("priority", 4)))
    for row in rows:
        if row["classification"] not in {"valid_action", "justified_no_action"}:
            tasks.append(dict(ticker=row["ticker"], classification=row["classification"], reason=row["reason"],
                              next_step=row["next_step"], resolver=row["resolver"], review_at=row["review_at"],
                              accepted_records=deepcopy(row["accepted_records"]), source_ids=list(row["blockers"]),
                              priority=1 if row["classification"] == "plan_expired" or row["ticker"] in held else 4))
    if report:
        # Full validated view includes authored next steps and source identities;
        # the short summary is deliberately insufficient to invent those fields.
        for item in _rows(report.get("reassessment_queue")) + _rows(report.get("priority_queue")):
            assessment = item.get("assessment") or {}
            state = str(item.get("state", ""))
            if state not in {"evidence_attached", "research_supported", "eligibility_review", "insufficient_evidence", "rejected", "economics_failed", "expired"}:
                continue
            step = assessment.get("next_step")
            if not step:
                step = ("Assess the retained source-bound evidence and countercase; complete the company-appropriate valuation and record a sourced conclusion through the existing writers."
                        if state == "evidence_attached" else
                        "Inspect the genuinely changed retained evidence and the prior conclusion; record an explicit sourced reassessment before reopening or changing the case.")
            event = item.get("upcoming_earnings") or {}
            tasks.append(dict(ticker=item.get("ticker", ""), classification="research_incomplete",
                              reason=item.get("reason_code", state), next_step=step, resolver="recurring_analyst",
                              review_at=event.get("research_deadline_at") or assessment.get("next_review_at"),
                              accepted_records=deepcopy(by_ticker.get(item.get("ticker"), {}).get("accepted_records", [])),
                              source_ids=[v for v in (item.get("opportunity_id"), assessment.get("assessment_sha256")) if v],
                              priority=1 if item.get("ticker") in held else 2 if event else 3))
    seen, result = set(), []
    for task in sorted(tasks, key=lambda t: (t.get("priority", 4), str(t.get("review_at") or "9999"), str(t.get("ticker")))):
        identity = task["ticker"]
        if not task["ticker"] or identity in seen:
            continue
        seen.add(identity)
        result.append({k: v for k, v in task.items() if k != "priority"})
        if len(result) == MAX_HANDOFF:
            break
    return result


def build(root: Path, decision: dict, current: datetime) -> dict:
    """Return a source-bound explanation of the existing final capital contract."""
    if current.tzinfo is None:
        raise ValueError("strategy_framework_aware_clock_required")
    from capital_decision import validate
    raw_capital = decision.get("capital_decision")
    capital = raw_capital if isinstance(raw_capital, dict) else {}
    error = ""
    try:
        validate(capital, root=root, current=current)
        generated = _stamp(capital.get("generated_at"))
        if generated is None or generated > current:
            raise ValueError("capital_decision_clock_unverified")
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        error = str(exc) or "capital_decision_unverified"
    capital_valid = not error
    expected = latest_published_market_session(current).isoformat()
    market_current = bool(decision.get("market_gate", {}).get("passed") is True
                          and decision.get("market_gate", {}).get("expected_market_session") == expected)
    plans = {r.get("ticker"): r for r in _rows(decision.get("plan_continuity", {}).get("plans"))}
    research = decision.get("long_horizon_research") or {}
    views = {**research.get("views", {}), **research.get("candidate_views", {})}
    core_tickers = set(decision.get("allocation_policy", {}).get("core_tickers", []))
    rows = []
    for original in _rows(capital.get("decisions")):
        ticker = str(original.get("ticker", ""))
        if not ticker:
            continue
        plan = plans.get(ticker, {})
        case = original.get("research_case") or {}
        category, resolver = _classify(original, plan, current=current, capital_valid=capital_valid,
                                       market_current=market_current)
        strategy, horizon = _strategy(plan, original, core_tickers=core_tickers)
        dependencies = _rows(original.get("dependencies"))
        authored = next((d.get("evidence_required") for d in dependencies if d.get("evidence_required")), None)
        reason = " ".join(str(r) for r in original.get("reasons", []) if r)
        if error:
            reason = "Current capital publication is unverified: " + error
        elif not market_current and category == "data_unavailable":
            reason = f"Required completed close {expected} is not admitted. Retained conclusion: " + reason
        if category == "valid_action":
            step = "Review the exact current conditional draft and verify quote, funds, shares and pending orders before any manual submission."
        elif category == "plan_expired":
            step = "Reassess the recorded purpose and named failure conditions using current evidence; append a justified plan version or retain expiry. Do not renew the old instruction from the clock."
        elif category == "justified_no_action":
            step = "Wait for the recorded price/evidence/review condition; an unchanged source does not require a new conclusion."
        else:
            step = authored or ("Obtain the required validated completed close and recompose publication." if not market_current else
                                "Complete the exact missing source-bound research or strategy review; no positive conclusion is inferred.")
        draft = deepcopy(original.get("order_draft")) if category == "valid_action" else None
        rows.append(dict(ticker=ticker, strategy_id=strategy, horizon=horizon, classification=category,
                         canonical_decision=original.get("decision"), eligible_quantity=original.get("shares", 0) if draft else 0,
                         reason=reason, next_step=step, resolver=resolver,
                         review_at=original.get("review_at") or plan.get("review_at") or case.get("next_review_at"),
                         blockers=_codes(original), accepted_records=_accepted(plan, views.get(ticker, {}), case) if capital_valid else [],
                         market_data_timestamp=original.get("market_data_timestamp"),
                         retained_company_conclusion=case.get("conclusion"), order_draft=draft,
                         automatic_action_allowed=False))
    report, report_status = None, "absent"
    if capital_valid and (root / "04_research/company_research/opportunities.local/report.json").is_file():
        try:
            from research_opportunities import read_report
            base = root / "04_research/company_research/opportunities.local"
            for stage in ("intake", "objective"):
                marker = read_json(base / ("last_" + stage + "_run.json"), {})
                if marker and marker.get("exit_code") != 0:
                    raise ValueError("latest_opportunity_stage_failed")
            report = read_report(root, current=current)
            report_status = "validated"
        except (OSError, ValueError, KeyError, TypeError):
            report_status = "unverified"
    policies = {}
    for rel in POLICY_PATHS:
        if (root / rel).is_file():
            policies[rel] = sha256_file(root / rel)
    result = dict(schema_version=SCHEMA, generated_at=current.isoformat(), status="ready" if capital_valid else "unverified",
                  strategies=_strategies(), decisions=rows, analyst_handoff=_handoff(rows, decision, report=report) if capital_valid else [],
                  expected_market_session=expected, market_current=market_current, validation_error=error or None,
                  opportunity_handoff_status=report_status, capital_content_sha256=capital.get("content_sha256"),
                  capital_source_bindings_sha256=canonical_sha256(capital.get("source_bindings", {})), policy_bindings=policies,
                  implementation_sha256=sha256_file(Path(__file__)),
                  opportunity_report_sha256=report.get("report_hash") if report else None,
                  automatic_action_allowed=False, changes_canonical_decisions=False, profitability_established=False)
    result["content_sha256"] = canonical_sha256(result)
    return result


def validate_projection(root: Path, view: dict, capital: dict, current: datetime) -> None:
    """Validate the stored observation's integrity, not current action admission.

    Swing research is a separately bound optional object attached by the caller;
    its integrity and expiry are owned by its own read-time validator.
    The caller must overlay its independently revalidated current capital view
    and suppress expired/stale actions. A later required close does not erase
    the original, explicitly dated research explanation.
    """
    from capital_decision import validate
    if not isinstance(view, dict) or view.get("schema_version") != SCHEMA:
        raise ValueError("strategy_framework_schema_invalid")
    payload = {k: v for k, v in view.items() if k not in {"content_sha256", "swing_research"}}
    if view.get("content_sha256") != canonical_sha256(payload):
        raise ValueError("strategy_framework_content_invalid")
    if view.get("automatic_action_allowed") is not False or view.get("changes_canonical_decisions") is not False:
        raise ValueError("strategy_framework_authority_invalid")
    if view.get("status") != "ready":
        raise ValueError("strategy_framework_publication_unverified")
    generated = _stamp(view.get("generated_at"))
    if current.tzinfo is None or generated is None or generated > current:
        raise ValueError("strategy_framework_clock_stale_or_invalid")
    if view.get("expected_market_session") != latest_published_market_session(generated).isoformat():
        raise ValueError("strategy_framework_original_required_close_invalid")
    validate(capital, root=root, current=generated)
    if (view.get("capital_content_sha256") != capital.get("content_sha256")
            or view.get("capital_source_bindings_sha256") != canonical_sha256(capital.get("source_bindings", {}))):
        raise ValueError("strategy_framework_capital_changed")
    policies = {rel: sha256_file(root / rel) for rel in POLICY_PATHS if (root / rel).is_file()}
    if view.get("policy_bindings") != policies:
        raise ValueError("strategy_framework_policy_changed")
    if view.get("implementation_sha256") != sha256_file(root / IMPLEMENTATION_REL):
        raise ValueError("strategy_framework_implementation_changed")
