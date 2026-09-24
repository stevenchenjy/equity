"""Shared research publication contract: plans, incorporated facts and history."""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from daily_common import canonical_sha256, sha256_file, ExclusiveFileLock, atomic_write_json, atomic_write_text, read_json, read_csv
from investment_plans import load_plan_context, apply_plan_context, semantic_state, render_plan_lines
from earnings_incorporation import read_earnings_incorporation_status
from thesis_evidence import STORE_REL, evaluate_thesis, evidence_context, stable_news_event, substantive_news, apply_issuer_news_review
from official_news import read_official_news_status
from issuer_news_queue import QUEUE_REL, merge_news_context, record_review_states

WORKFLOW_INPUTS = {
    "05_risk_and_positions/investment_plans.local.json", "05_risk_and_positions/current_positions.local.csv",
    "05_risk_and_positions/current_open_orders.local.json", "05_risk_and_positions/current_account_state.local.json",
    str(STORE_REL), str(QUEUE_REL),
}
CRITICAL_CODES = {"account_conflict_hold", "data_gate_hold", "fundamental_weakening_review"}


def incorporation_meaning(report: dict[str, Any]) -> dict[str, Any]:
    return {ticker: {key: row.get(key) for key in ("status", "positive_decision_eligible", "latest_report_period_end",
               "latest_material_accession", "selected_period_end", "blocking_reasons", "financial_economic_sha256")}
            for ticker, row in sorted(report.get("companies", {}).items())}


def thesis_meaning(context: dict[str, Any]) -> dict[str, Any]:
    def summarize(views):
        result = {ticker: {key: row.get(key) for key in ("status", "review_id", "version", "review_record_sha256",
                "business_case_status", "valuation_readiness", "reopen_reasons", "validation_errors", "news_review")}
            for ticker, row in sorted(views.items())}
        for row in result.values():
            if row["status"] in {"reviewed", "monitor"}:
                row["status"] = "maintained_active"
        return result
    return {"held_views": summarize(context.get("views", {})), "candidate_views": summarize(context.get("candidate_views", {}))}


def workflow_meaning(decision: dict[str, Any]) -> dict[str, Any]:
    return {"plans": semantic_state(decision.get("plan_continuity", {})),
            "incorporation": incorporation_meaning(decision.get("earnings_incorporation", {})),
            "theses": thesis_meaning(decision.get("long_horizon_research", {})),
            "news": news_meaning(decision.get("evidence_coverage", {}).get("official_news", {})),
            "blockers": decision.get("workflow_integrity", {}).get("blockers", [])}


def current_thesis_views(decision: dict[str, Any], *, root: Path, current: datetime,
                         incorporation: dict[str, Any], news: dict[str, Any] | None = None,
                         candidate_tickers: set[str] | None = None) -> dict[str, Any]:
    """Re-read retained evidence and age each review at the decision clock."""
    tickers = set(decision.get("long_horizon_research", {}).get("views", {}))
    tickers.update(row["ticker"] for row in decision.get("held_positions", [])
                   if row.get("asset_role") != "core_allocation")
    if candidate_tickers is not None:
        tickers = set(candidate_tickers)
    try:
        store = read_json(root / STORE_REL, None)
    except (OSError, ValueError):
        store = {"schema_version": "invalid", "records": []}
    context = None
    if store is not None:
        try:
            context = evidence_context(root)
        except (OSError, ValueError, KeyError, TypeError):
            context = {"acceptance": {}, "artifacts": {}}
    events = read_csv(root / "03_source_data/equity_research/daily_evidence_ledger.csv")
    views = {ticker: evaluate_thesis(store, ticker, current.isoformat(), root, context=context,
        material_events=events, incorporation=incorporation.get("companies", {}).get(ticker))
        for ticker in sorted(tickers)}
    news = news if news is not None else current_news_context(decision, root=root, current=current)
    for ticker, view in views.items():
        apply_issuer_news_review(view, ticker=ticker, news=news, current=current)
    return views


def reviewed_candidate_ready(view: dict[str, Any]) -> bool:
    """Legacy financial completeness alone cannot clear a new company idea."""
    news = view.get("news_review", {})
    return (view.get("status") in {"reviewed", "monitor"}
        and view.get("business_case_status") == "provisionally_supported"
        and view.get("valuation_readiness") == "reviewed_scenarios"
        and not view.get("validation_errors") and not view.get("reopen_reasons")
        and news.get("status") == "current" and news.get("coverage_complete") is True)


def current_news_context(decision: dict[str, Any], *, root: Path, current: datetime,
                         persist_queue: bool = False) -> dict[str, Any]:
    try:
        result = read_official_news_status(now=current,
            manifest_path=root / "01_policies/official_news_sources.json",
            status_path=root / "03_source_data/equity_research/official_news_status.local.json",
            events_path=root / "03_source_data/equity_research/official_news_events.local.json")
    except (OSError, ValueError, TypeError, KeyError):
        result = {"status": "missing", "required_coverage_complete": False, "sources": [], "recent_events": []}
    held = {row["ticker"] for row in decision.get("held_positions", []) if row.get("asset_role") != "core_allocation"}
    covered = {str(row.get("ticker", "")).upper() for row in result.get("sources", [])}
    result["unconfigured_held_tickers"] = sorted(held-covered)
    if held-covered:
        result["required_coverage_complete"] = False
        if result.get("status") == "ok":
            result["status"] = "degraded"
    # Queue corruption is deliberately not swallowed as a missing feed: doing
    # so would silently erase unresolved research and permit false clearance.
    return merge_news_context(result, root=root, current=current, persist=persist_queue)


def news_meaning(context: dict[str, Any]) -> dict[str, Any]:
    # Fetch clocks and the rolling feed window are not research conclusions.
    # Retained event identity and maintained pending states drive continuity.
    return {"status": context.get("status"), "required_coverage_complete": context.get("required_coverage_complete"),
        "unconfigured_held_tickers": context.get("unconfigured_held_tickers", []),
        "sources": sorted((row.get("source_id", ""), row.get("freshness", "")) for row in context.get("sources", [])),
        "events": sorted((row.get("event_id", ""), canonical_sha256(stable_news_event(row)))
                         for row in context.get("review_events", context.get("recent_events", []))
                         if substantive_news(row) and row.get("source_type") == "official_issuer_announcement")}


def apply_workflow_integrity(decision: dict[str, Any], *, root: Path, current: datetime) -> None:
    held = decision.get("held_positions", [])
    plans = load_plan_context(root, held, current)
    apply_plan_context(held, plans)
    try:
        incorporation = read_earnings_incorporation_status(root=root, now=current)
    except (OSError, ValueError, TypeError, KeyError):
        incorporation = {"schema_version": "earnings_incorporation_v1", "companies": {},
                         "held_pending_tickers": [row["ticker"] for row in held if row.get("asset_role") != "core_allocation"],
                         "status": "invalid"}
    blockers = []
    baseline_code = decision.get("decision_code")
    if baseline_code in CRITICAL_CODES:
        blockers.append("baseline_risk_gate:"+baseline_code)
    if any(decision.get(gate, {}).get("passed") is not True for gate in ("market_gate", "evidence_gate", "fundamental_gate")):
        blockers.append("baseline_data_prerequisites_unresolved")
    if plans.get("block_new_capital"):
        blockers.append("maintained_plans_require_reconciliation")
    companies = incorporation.get("companies", {})
    held_pending = [row["ticker"] for row in held if row.get("asset_role") != "core_allocation"
                    and companies.get(row["ticker"], {}).get("positive_decision_eligible") is not True]
    if held_pending:
        blockers.append("held_latest_earnings_pending:" + ",".join(sorted(held_pending)))
    news = current_news_context(decision, root=root, current=current, persist_queue=True)
    decision.setdefault("evidence_coverage", {})["official_news"] = news
    if news.get("required_coverage_complete") is not True:
        blockers.append("held_news_coverage_incomplete")
    views = current_thesis_views(decision, root=root, current=current, incorporation=incorporation, news=news)
    decision.setdefault("long_horizon_research", {})["views"] = views
    eligible = set(decision.get("eligible_new_position_review_candidates", []))
    candidate_tickers = {row["ticker"] for row in decision.get("watch_candidates", []) if row.get("ticker") in eligible
        and row.get("valuation_applicability") != "not_applicable_broad_market_etf"
        and row.get("asset_role") not in {"core_allocation", "core_allocation_candidate"}}
    candidate_views = current_thesis_views(decision, root=root, current=current, incorporation=incorporation,
        news=news, candidate_tickers=candidate_tickers) if candidate_tickers else {}
    decision["long_horizon_research"]["candidate_views"] = candidate_views
    record_review_states(views | candidate_views, root=root, current=current)
    for warning in decision["long_horizon_research"].get("warnings", []):
        warning["maintained_view"] = views.get(warning.get("ticker"), {})
    reassess = [ticker for ticker, view in views.items() if view.get("status") in {"reassess", "invalidated"} or view.get("validation_errors")]
    if reassess:
        blockers.append("company_reviews_require_reassessment:"+",".join(sorted(reassess)))
    # A durable plan is a research instruction, not permission to recreate its
    # former quantity. Preserve the original deterministic proposal separately.
    decision["baseline_decision"] = {key: decision.get(key) for key in ("headline", "decisive_advice", "decision_code", "eligible_action_review_candidates", "eligible_new_position_review_candidates")}
    decision["eligible_action_review_candidates"] = []
    retained_new = []
    for row in decision.get("watch_candidates", []):
        ticker = row.get("ticker", "")
        core = row.get("valuation_applicability") == "not_applicable_broad_market_etf" or row.get("asset_role") in {"core_allocation", "core_allocation_candidate"}
        missing = not core and companies.get(ticker, {}).get("positive_decision_eligible") is not True
        review_missing = ticker in candidate_tickers and not reviewed_candidate_ready(candidate_views.get(ticker, {}))
        if blockers or missing or review_missing:
            row["baseline_research_proposal"] = {key: row.get(key) for key in ("label", "action", "suggested_whole_shares", "maximum_review_price")}
            row["suggested_whole_shares"] = "0"
            row["action"] = "research_prerequisites_unresolved"
            row["label"] = "watchlist"
            row["gate_blockers"] = ",".join(filter(None, [str(row.get("gate_blockers", "")), *blockers,
                                                    "latest_earnings_pending_incorporation" if missing else "",
                                                    "maintained_company_research_incomplete" if review_missing else ""]))
        elif ticker in decision.get("eligible_new_position_review_candidates", []):
            retained_new.append(ticker)
    decision["eligible_new_position_review_candidates"] = retained_new
    decision["plan_continuity"] = plans
    decision["earnings_incorporation"] = incorporation
    decision["workflow_integrity"] = {"schema_version": "equity_workflow_integrity_v1", "blockers": blockers,
        "new_capital_allowed": not blockers, "current_instruction_authority": "versioned_plans_reconciled_with_observed_facts",
        "input_hashes": {path: sha256_file(root / path) if (root / path).exists() else None for path in sorted(WORKFLOW_INPUTS)},
        "historical_baseline_is_current_instruction": False, "automatic_action_allowed": False}
    if not retained_new and not decision.get("account_conflicts") and baseline_code not in CRITICAL_CODES:
        decision["decision_code"] = "maintained_plan_review"
        decision["headline"] = "按维护中的计划复核｜过期方案与待补证据已分开标示"
        decision["decisive_advice"] = "以当前计划状态为准；旧报价和旧 DAY 委托不自动续期。待核对事项未解决前不新增仓位。" if blockers else "按已记录计划观察；本次未形成新增仓位方案。"
    if blockers or not retained_new:
        decision["capital_allocation"]["proposed_deployment_value"] = 0
    decision["human_review_reasons"] = sorted(set(decision.get("human_review_reasons", []) + (["maintained_plan_reconciliation"] if blockers else [])))
    decision["human_review_required"] = bool(decision["human_review_reasons"])
    decision["decision_fingerprint"] = canonical_sha256({"baseline": decision["decision_fingerprint"], "workflow": workflow_meaning(decision)})
    atomic_write_json(root / "08_reviews/current/maintained_plans.local.json", plans)
    atomic_write_text(root / "08_reviews/current/maintained_plans.local.md", "# Current maintained research plans\n\n" +
        "Generated: " + current.isoformat() + "\n\n" + "\n\n".join(render_plan_lines(plans)) +
        "\n\nOriginal proposals are preserved in the private versioned ledger; no brokerage order is changed.\n")


def validate_published_workflow(decision: dict[str, Any], *, root: Path, current: datetime) -> None:
    contract = decision.get("workflow_integrity")
    if contract is None:
        return  # Dated legacy artifacts retain their original validation path.
    if contract.get("schema_version") != "equity_workflow_integrity_v1":
        raise ValueError("workflow_integrity_schema_invalid")
    if set(contract.get("input_hashes", {})) != WORKFLOW_INPUTS:
        raise ValueError("workflow_input_bindings_incomplete")
    for path, digest in contract.get("input_hashes", {}).items():
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("workflow_input_path_invalid")
        actual = sha256_file(root / candidate) if (root / candidate).exists() else None
        if digest != actual:
            raise ValueError("workflow_inputs_changed_recompose_required")
    current_context = load_plan_context(root, decision.get("held_positions", []), current)
    # Reapply the preserved baseline only to detect current conflicts, not to
    # change any persisted decision or economic fact during validation.
    import copy
    rows = copy.deepcopy(decision.get("held_positions", []))
    for row in rows:
        if isinstance(row.get("baseline_research"), dict):
            row.update(row["baseline_research"])
    apply_plan_context(rows, current_context)
    if semantic_state(current_context) != semantic_state(decision.get("plan_continuity", {})):
        raise ValueError("workflow_plan_state_changed_recompose_required")
    current_earnings = read_earnings_incorporation_status(root=root, now=current)
    if incorporation_meaning(current_earnings) != incorporation_meaning(decision.get("earnings_incorporation", {})):
        raise ValueError("workflow_earnings_changed_recompose_required")
    news = current_news_context(decision, root=root, current=current)
    current_views = current_thesis_views(decision, root=root, current=current, incorporation=current_earnings, news=news)
    candidates = set(decision.get("long_horizon_research", {}).get("candidate_views", {}))
    candidate_views = current_thesis_views(decision, root=root, current=current, incorporation=current_earnings,
        news=news, candidate_tickers=candidates) if candidates else {}
    if thesis_meaning({"views": current_views, "candidate_views": candidate_views}) != thesis_meaning(decision.get("long_horizon_research", {})):
        raise ValueError("workflow_thesis_changed_recompose_required")
    if news_meaning(news) != news_meaning(decision.get("evidence_coverage", {}).get("official_news", {})):
        raise ValueError("workflow_news_changed_recompose_required")


def record_decision_history(decision: dict[str, Any], *, root: Path) -> None:
    path = root / "00_project_control/run_logs/decision_history.local.jsonl"
    snapshot = workflow_meaning(decision)
    fingerprint = canonical_sha256(snapshot)
    with ExclusiveFileLock(path.with_suffix(".lock")):
        prior = []
        if path.exists():
            prior = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        previous_hash = ""
        for row in prior:
            if row.get("previous_hash") != previous_hash or row.get("record_hash") != canonical_sha256({key: value for key, value in row.items() if key != "record_hash"}):
                raise ValueError("decision_history_hash_chain_invalid")
            previous_hash = row["record_hash"]
        if prior and prior[-1].get("workflow_fingerprint") == fingerprint:
            return
        old = prior[-1].get("workflow", {}) if prior else {}
        changed = [key for key in snapshot if snapshot[key] != old.get(key)]
        row = {"schema_version": "equity_decision_history_v1", "recorded_at": decision["generated_at"],
               "workflow_fingerprint": fingerprint, "decision_fingerprint": decision["decision_fingerprint"],
               "changed_components": changed, "workflow": snapshot,
               "instructions": [{key: p.get(key) for key in ("ticker", "plan_id", "version", "status", "instruction", "reason", "change_reason")}
                                for p in decision.get("plan_continuity", {}).get("plans", [])],
               "previous_hash": previous_hash, "automatic_action_allowed": False}
        row["record_hash"] = canonical_sha256(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
