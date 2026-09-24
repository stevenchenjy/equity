#!/usr/bin/env python3
"""Generate one concise current Phase 5R production status artifact."""

from __future__ import annotations

from equity_naming import report_heading

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from active_config import ACTIVE_CONFIG_PATH, load_active_config
from daily_common import (
    ACCOUNT_STATE_PATH,
    AUTOMATION_ALERT_PATH,
    DAILY_DECISION_JSON_PATH,
    DAILY_REFRESH_STATE_PATH,
    EVIDENCE_STATUS_PATH,
    MARKET_SNAPSHOT_PATH,
    ROOT,
    atomic_write_json,
    atomic_write_text,
    iso_now,
    latest_published_market_session,
    now_et,
    read_csv,
    read_json,
)


STATUS_JSON_PATH = ROOT / "00_project_control" / "current_production_status.local.json"
STATUS_MD_PATH = ROOT / "00_project_control" / "current_production_status.local.md"
VALUATION_PATH = ROOT / "04_data" / "equity_research" / "valuation_scenarios.local.json"
SNAPSHOT_PATH = (
    ROOT / "04_research" / "company_research"
    / "recommendation_snapshots.local.jsonl"
)
OUTCOME_PATH = (
    ROOT / "04_research" / "company_research"
    / "recommendation_outcomes.local.csv"
)
WORKFLOW_EVALUATION_PATH = ROOT / "08_reviews/current/workflow_evaluation.local.json"
DEPLOYMENT_RECEIPT_PATH = ROOT / "00_project_control/run_logs/verified_deployment.local.json"
RUNTIME_EXECUTION_PATH = ROOT / "00_project_control/run_logs/runtime_execution_log.csv"


def workflow_health(decision: dict, long_report: dict, incorporation: dict, evaluation: dict,
                    refresh: dict, held_tickers: set[str], held_companies: set[str],
                    *, current: datetime) -> dict[str, Any]:
    """Keep operational completion, maintained views, and price readiness separate."""
    plan = decision.get("plan_continuity", {})
    plan_rows = [row for row in plan.get("plans", []) if isinstance(row, dict)]
    missing_plans = sorted(held_tickers - {row.get("ticker") for row in plan_rows})
    plan_gaps = []
    if not plan:
        plan_gaps.append("plan_continuity_missing")
    if missing_plans:
        plan_gaps.append("held_plan_coverage_incomplete")
    if plan.get("conflicts"):
        plan_gaps.append("active_plan_conflicts")
    if plan.get("unresolved_tickers"):
        plan_gaps.append("maintained_plans_require_review")
    if plan:
        try:
            stamp = datetime.fromisoformat(str(plan.get("as_of", "")).replace("Z", "+00:00"))
            if stamp.tzinfo is None or not 0 <= (current - stamp).total_seconds() <= 30 * 3600:
                plan_gaps.append("plan_continuity_stale_or_future")
        except (ValueError, TypeError):
            plan_gaps.append("plan_continuity_timestamp_missing")
    companies = []
    for ticker in sorted(held_companies):
        row = long_report.get("companies", {}).get(ticker, {})
        view = row.get("maintained_view", {})
        earnings = incorporation.get("companies", {}).get(ticker, {})
        companies.append({"ticker": ticker, "thesis_id": view.get("thesis_id", ""),
            "thesis_version": view.get("thesis_version", view.get("version")),
            "reported_thesis_state": view.get("status", "unresolved"),
            "thesis_state": "reassess" if view.get("status") in {"reviewed", "monitor"} and not earnings.get("positive_decision_eligible") else view.get("status", "unresolved"),
            "business_case_status": view.get("business_case_status", "unresolved"),
            "valuation_readiness": view.get("valuation_readiness", "unresolved"),
            "news_review_status": view.get("news_review", {}).get("status", "unknown"),
            "pending_news_event_count": len(view.get("news_review", {}).get("pending_events", [])),
            "news_review_scope": view.get("news_review", {}).get("review_scope", ""),
            "conclusion": view.get("conclusion", ""), "next_review_at": view.get("next_review_at", ""),
            "review_reasons": view.get("reopen_reasons", []) + (["latest_earnings_pending_incorporation"] if view.get("status") in {"reviewed", "monitor"} and not earnings.get("positive_decision_eligible") else []),
            "earnings_status": earnings.get("status", "unknown"),
            "selected_financial_period": earnings.get("selected_period_end", ""),
            "latest_report_period": earnings.get("latest_report_period_end", ""),
            "earnings_reasons": earnings.get("blocking_reasons", []),
            "positive_decision_eligible": earnings.get("positive_decision_eligible", False)})
    evaluation_fresh = False
    evaluation_reason = "workflow_evaluation_missing"
    if evaluation:
        try:
            generated = datetime.fromisoformat(str(evaluation["generated_at"]).replace("Z", "+00:00"))
            completed = datetime.fromisoformat(str(refresh.get("research_completed_at") or refresh.get("completed_at", "")).replace("Z", "+00:00"))
            evaluation_fresh = (generated.tzinfo is not None and completed.tzinfo is not None
                and completed <= generated <= current and (current - generated).total_seconds() <= 30 * 3600)
            evaluation_reason = "current_refresh_included" if evaluation_fresh else "workflow_evaluation_precedes_refresh_or_is_stale"
        except (KeyError, ValueError, TypeError):
            evaluation_reason = "workflow_evaluation_timestamp_invalid"
    final_evaluation = refresh.get("workflow_evaluation_update", {})
    if final_evaluation and final_evaluation.get("exit_code") != 0:
        evaluation_fresh, evaluation_reason = False, "workflow_evaluation_final_update_failed"
    pending = sorted(row["ticker"] for row in companies if not row["positive_decision_eligible"])
    return {
        "plan_continuity": {"status": plan.get("status", "missing"), "as_of": plan.get("as_of", ""),
            "semantic_fingerprint": plan.get("semantic_fingerprint", ""),
            "block_new_capital": bool(plan.get("block_new_capital", True) or plan_gaps),
            "conflicts": plan.get("conflicts", []), "unresolved_tickers": plan.get("unresolved_tickers", []),
            "missing_held_tickers": missing_plans, "gaps": plan_gaps, "plans": plan_rows},
        "earnings_incorporation": {"generated_at": incorporation.get("generated_at", ""),
            "held_incorporated_count": len(companies) - len(pending), "held_pending_tickers": pending,
            "scope": incorporation.get("scope", "financial_selection_not_analyst_thesis_completion")},
        "maintained_research": {"companies": companies,
            "reviewed_business_views": sum(r["thesis_state"] in {"reviewed", "monitor"} and r["business_case_status"] != "unresolved" for r in companies),
            "reviewed_company_valuations": sum(r["thesis_state"] in {"reviewed", "monitor"} and r["valuation_readiness"] == "reviewed_scenarios" for r in companies)},
        "workflow_evaluation": {"status": "current" if evaluation_fresh else "unresolved", "reason": evaluation_reason,
            "generated_at": evaluation.get("generated_at", ""), "current_refresh_included": evaluation_fresh,
            "operations": evaluation.get("operations", {}), "recommendation_outcomes": evaluation.get("recommendation_outcomes", {}),
            "portfolio_performance": evaluation.get("portfolio_performance", {"status": "not_ready", "blockers": ["evaluation_missing"]})},
    }


def deployment_health(receipt: dict, execution_rows: list[dict], *, current: datetime) -> dict:
    latest = next((row for row in reversed(execution_rows)
                   if row.get("event") in {"preflight", "scheduler_exec_authorized", "sync_only"}), {})
    fallback = latest.get("sync_action") == "verified_deployment_network_fallback"
    jobs = {}
    for row in reversed(execution_rows):
        if row.get("job") in {"dailyrefresh", "dailydecision"} and row.get("job") not in jobs and row.get("event") in {"preflight", "scheduler_exec_authorized"}:
            jobs[row["job"]] = {key: row.get(key, "") for key in ("timestamp", "event", "outcome", "sync_action")}
    age = None
    try:
        verified = datetime.fromisoformat(str(receipt.get("verified_at", "")).replace("Z", "+00:00"))
        if verified.tzinfo is not None:
            age = (current - verified).total_seconds()
    except (TypeError, ValueError):
        pass
    return {"status": "collection_on_verified_deployment_network_fallback" if fallback else
            "latest_preflight_blocked" if latest.get("outcome") == "blocked" else "online_sync_observed" if latest else "unknown",
            "latest_event_at": latest.get("timestamp", ""), "latest_job": latest.get("job", ""),
            "latest_sync_action": latest.get("sync_action", ""), "verified_at": receipt.get("verified_at", ""),
            "verified_commit": receipt.get("commit", ""), "receipt_age_seconds": age,
            "receipt_within_fallback_window": age is not None and 0 <= age <= 86400,
            "jobs": jobs,
            "public_collection_fallback_observed": jobs.get("dailyrefresh", {}).get("sync_action") == "verified_deployment_network_fallback",
            "interpretation": "Collection fallback is limited to public refresh; it is not a successful fetch or sender authorization."}
def jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    config = load_active_config()
    refresh = read_json(DAILY_REFRESH_STATE_PATH, {})
    evidence = read_json(EVIDENCE_STATUS_PATH, {})
    decision = read_json(DAILY_DECISION_JSON_PATH, {})
    account = read_json(ACCOUNT_STATE_PATH, {})
    try:
        automation_alert = read_json(AUTOMATION_ALERT_PATH, {})
    except (OSError, TypeError, ValueError):
        automation_alert = {
            "active": True,
            "component": "status_generator",
            "reason": "automation_alert_state_invalid",
        }
    valuation = read_json(VALUATION_PATH, {"records": []})
    market_rows = read_csv(MARKET_SNAPSHOT_PATH)
    valid_market = [row for row in market_rows if row.get("data_quality_label") in {"ok", "partial"}]
    sessions = sorted({row.get("market_session_date", "") for row in valid_market if row.get("market_session_date")})
    blockers: list[str] = []
    if refresh.get("outcome") != "passed":
        blockers.append("deterministic_refresh_not_fully_passed")
    if not valid_market:
        blockers.append("current_market_snapshot_invalid")
    if evidence.get("scan_status") != "ok":
        blockers.append(str(evidence.get("reason") or "official_evidence_refresh_not_ok"))
    if automation_alert.get("active") is True:
        blockers.append(
            str(automation_alert.get("reason") or "scheduled_automation_blocked")
        )
    completed_valuations = sum(
        row.get("status") == "complete" for row in valuation.get("records", [])
        if isinstance(row, dict)
    )
    current = now_et()
    expected_session = latest_published_market_session(current).isoformat()
    if any(row.get("market_session_date") != expected_session for row in market_rows) or not market_rows:
        blockers.append("market_snapshot_not_expected_published_session")
    try:
        completed = datetime.fromisoformat(refresh.get("completed_at", ""))
        if completed.tzinfo is None or not 0 <= (current - completed).total_seconds() <= 30 * 3600:
            blockers.append("refresh_completion_stale_or_future")
    except (TypeError, ValueError):
        blockers.append("refresh_completion_missing")
    from official_news import read_official_news_status
    from market_regime import load_regime_controls
    try:
        news = read_official_news_status(now=current)
    except (OSError, ValueError, TypeError, KeyError):
        news = {"status": "degraded", "required_coverage_complete": False,
                "reason": "official_news_receipt_invalid"}
    regime = load_regime_controls(expected_session)
    long_report = read_json(ROOT / "04_research/company_research/long_horizon_research.local.json", {})
    positions = read_csv(ROOT / "05_risk_and_positions/current_positions.local.csv")
    universe = read_csv(ROOT / "03_source_data/equity_research/universe_seed.csv")
    benchmarks = {row.get("ticker") for row in universe if row.get("is_benchmark") == "yes"}
    held_companies = {row.get("ticker") for row in positions if row.get("ticker") not in benchmarks}
    news_covered = {row.get("ticker") for row in news.get("sources", []) if isinstance(row, dict)}
    news["unconfigured_held_tickers"] = sorted(held_companies - news_covered)
    if news["unconfigured_held_tickers"]:
        news.update(status="degraded", required_coverage_complete=False)
    valued = {row.get("ticker") for row in valuation.get("records", []) if row.get("status") == "complete"}
    research_gaps = [f"{ticker}:valuation_incomplete" for ticker in sorted(held_companies - valued)]
    if not long_report:
        research_gaps.append("long_horizon_research_missing")
    elif long_report.get("market_session_date") != expected_session:
        research_gaps.append("long_horizon_research_market_session_stale")
    from earnings_incorporation import read_earnings_incorporation_status
    try:
        incorporation = read_earnings_incorporation_status(root=ROOT, now=current)
    except (OSError, ValueError, TypeError, KeyError):
        incorporation = {"companies": {}, "status": "invalid_evidence"}
    try:
        evaluation = read_json(WORKFLOW_EVALUATION_PATH, {})
    except (OSError, ValueError, TypeError):
        evaluation = {}
    health = workflow_health(decision, long_report, incorporation, evaluation, refresh,
        {row.get("ticker") for row in positions if row.get("ticker")}, held_companies, current=current)
    for company in health["maintained_research"]["companies"]:
        if company["thesis_state"] not in {"reviewed", "monitor"}:
            research_gaps.append(f"{company['ticker']}:thesis_{company['thesis_state']}")
        if company["valuation_readiness"] != "reviewed_scenarios":
            research_gaps.append(f"{company['ticker']}:company_specific_valuation_pending")
    blockers.extend(health["plan_continuity"]["gaps"])
    if health["earnings_incorporation"]["held_pending_tickers"]:
        blockers.append("held_earnings_pending_incorporation")
    if not health["workflow_evaluation"]["current_refresh_included"]:
        blockers.append(health["workflow_evaluation"]["reason"])
    try:
        deployment = deployment_health(read_json(DEPLOYMENT_RECEIPT_PATH, {}), read_csv(RUNTIME_EXECUTION_PATH), current=current)
    except (OSError, ValueError, TypeError):
        deployment = {"status": "deployment_evidence_invalid", "latest_sync_action": "", "verified_at": ""}
    scheduler = read_json(ROOT / "00_project_control/run_logs/daily_scheduler_state.local.json", {}).get("dates", {})
    retained = sorted(scheduler)[-60:]
    reliability = {
        "retained_calendar_days": len(retained),
        "fully_refreshed_days": sum(scheduler[day].get("refresh_fully_passed") is True for day in retained),
        "delivery_unknown_days": [day for day in retained if scheduler[day].get("decision_terminal_reason") == "delivery_status_unknown"],
        "interpretation": "daily final states, not per-request uptime; retention does not establish long-term SLA",
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unavailable"
    status: dict[str, Any] = {
        "schema_version": "phase5r_current_production_status_v1",
        "generated_at": iso_now(),
        "active_config": str(ACTIVE_CONFIG_PATH.relative_to(ROOT)),
        "git_commit": commit,
        "deterministic_refresh": {
            "outcome": refresh.get("outcome", "missing"),
            "completed_at": refresh.get("completed_at", ""),
            "hard_failures": refresh.get("hard_failures", []),
            "soft_failures": refresh.get("soft_failures", []),
        },
        "market": {
            "latest_completed_session": sessions[-1] if sessions else "",
            "session_scope": "latest_validated_published_close_not_exchange_calendar",
            "valid_rows": len(valid_market),
            "total_rows": len(market_rows),
        },
        "official_evidence": {
            "status": evidence.get("scan_status", "missing"),
            "reason": evidence.get("reason", ""),
            "held_coverage_complete": evidence.get("held_coverage_complete", False),
            "last_success_at": evidence.get("last_success_at", ""),
        },
        "decision": {
            "code": decision.get("decision_code", "missing"),
            "headline": decision.get("headline", ""),
            "send_recommended": decision.get("send_recommended", False),
            "send_reason": decision.get("send_reason", ""),
            "next_review": decision.get("next_scheduled_review", ""),
        },
        "account": {
            "cash_available": account.get("cash_available"),
            "cash_reserved": account.get("cash_reserved"),
            "position_truth": "manual local cash and whole shares",
            "last_manual_update": account.get("last_updated", ""),
            "cash_basis": account.get("cash_basis", "unavailable"),
        },
        "valuation": {
            "complete_records": completed_valuations,
            "total_records": len(valuation.get("records", [])),
            "policy": valuation.get("policy", ""),
        },
        "outcomes": {
            "recommendation_snapshots": jsonl_count(SNAPSHOT_PATH),
            "evaluated_horizon_rows": len(read_csv(OUTCOME_PATH)),
        },
        "research_readiness": {
            "held_company_count": len(held_companies),
            "held_complete_valuations": len(held_companies & valued),
            "reviewed_business_views": health["maintained_research"]["reviewed_business_views"],
            "reviewed_company_valuations": health["maintained_research"]["reviewed_company_valuations"],
            "gaps": research_gaps,
            "interpretation": "Operational success is separate from an evidenced long-term investment thesis",
        },
        "official_news": news,
        "market_regime": regime,
        "reliability": reliability,
        **health,
        "deployment": deployment,
        "automation_alert": {
            "active": automation_alert.get("active", False),
            "component": automation_alert.get("component", ""),
            "reason": automation_alert.get("reason", ""),
            "updated_at": automation_alert.get("updated_at", ""),
        },
        "model": {
            "scope": "retired_production_pilot_only_not_current_shadow_evaluation",
            "status": config["model_policy"]["status"],
            "active": False,
            "calls_allowed": False,
            "metered_cost_usd": "0.000000",
            "monthly_hard_cap_usd": config["model_policy"]["monthly_hard_cap_usd"],
            "historical_archive": config["model_policy"]["historical_archive"],
        },
        "blockers": sorted(set(blockers)),
        "boundaries": config["boundaries"],
    }
    atomic_write_json(STATUS_JSON_PATH, status)
    lines = [
        report_heading("production_status"),
        "",
        f"Generated: `{status['generated_at']}`",
        "",
        f"- Deterministic refresh: `{status['deterministic_refresh']['outcome']}`.",
        f"- Market: `{status['market']['valid_rows']}/{status['market']['total_rows']}` valid rows; latest validated published close `{status['market']['latest_completed_session'] or 'none'}` (provider publication can lag the exchange calendar).",
        f"- SEC evidence: `{status['official_evidence']['status']}`; held coverage `{status['official_evidence']['held_coverage_complete']}`.",
        f"- Decision: `{status['decision']['code']}`; email `{status['decision']['send_reason'] or 'not generated'}`.",
        f"- Valuation: `{status['valuation']['complete_records']}/{status['valuation']['total_records']}` complete records.",
        f"- Outcome evidence: `{status['outcomes']['recommendation_snapshots']}` snapshots, `{status['outcomes']['evaluated_horizon_rows']}` evaluated horizon rows.",
        f"- Production model: retired; calls allowed `{status['model']['calls_allowed']}`; retired-pilot metered cost `${status['model']['metered_cost_usd']}`. These are not current SHADOW usage or costs; see `08_reviews/shadow_llm/reviews.local/evaluation.md`.",
        f"- Current blockers: `{', '.join(status['blockers']) or 'none'}`.",
        f"- Research coverage: `{len(held_companies & valued)}/{len(held_companies)}` held-company valuations complete; gaps `{', '.join(research_gaps) or 'see company thesis review status'}`.",
        f"- Maintained business views: `{health['maintained_research']['reviewed_business_views']}/{len(held_companies)}` reviewed/monitor; reviewed company-specific valuations: `{health['maintained_research']['reviewed_company_valuations']}/{len(held_companies)}`. A business conclusion does not establish an attractive entry price.",
        f"- Latest earnings incorporated: `{health['earnings_incorporation']['held_incorporated_count']}/{len(held_companies)}`; pending `{', '.join(health['earnings_incorporation']['held_pending_tickers']) or 'none'}`.",
        f"- Maintained plans: `{health['plan_continuity']['status']}`; new capital blocked `{health['plan_continuity']['block_new_capital']}`; unresolved `{', '.join(health['plan_continuity']['unresolved_tickers']) or 'none'}`; missing held plans `{', '.join(health['plan_continuity']['missing_held_tickers']) or 'none'}`; conflicts `{len(health['plan_continuity']['conflicts'])}`.",
        f"- Official news: `{news.get('status', 'missing')}`; this is independent of the SEC filing check.",
        f"- Market context: `{regime['regime']}`; new-capital confirmation `{regime['required_distinct_closes']}` distinct closes.",
        f"- Retained daily refresh completions: `{reliability['fully_refreshed_days']}/{len(retained)}` calendar days; delivery-unknown dates `{', '.join(reliability['delivery_unknown_days']) or 'none'}`.",
        f"- Workflow evaluation: `{health['workflow_evaluation']['status']}`; `{health['workflow_evaluation']['reason']}`; on-time `{evaluation.get('operations', {}).get('on_time_cycles', 'unknown')}/{evaluation.get('operations', {}).get('due_calendar_cycles', 'unknown')}` due calendar cycles; late `{evaluation.get('operations', {}).get('late_cycles', 'unknown')}`. A stale report is historical only.",
        f"- Actual portfolio performance readiness: `{health['workflow_evaluation']['portfolio_performance'].get('status', 'unknown')}`; planning cash is excluded.",
        f"- Deployment: `{deployment['status']}`; latest sync action `{deployment.get('latest_sync_action', '')}`; public collection fallback observed `{deployment.get('public_collection_fallback_observed', False)}`; last verified online `{deployment.get('verified_at', '')}`.",
        "- Boundaries: research only; no broker read, automatic order, or trade placement.",
        "",
        "This generated file and `active_production_config.json` are the current authority. Older pilot registries and dated reports are historical evidence only.",
    ]
    lines.extend(["", "| Held company | Maintained view | Business evidence | Company valuation | News assessment | Selected / latest financial period |", "|---|---|---|---|---|---|"])
    for company in health["maintained_research"]["companies"]:
        lines.append(f"| {company['ticker']} | {company['thesis_state']} | {company['business_case_status']} | {company['valuation_readiness']} | {company['news_review_status']}; {company['pending_news_event_count']} pending | {company['selected_financial_period'] or 'unknown'} / {company['latest_report_period'] or 'unknown'} |")
    atomic_write_text(STATUS_MD_PATH, "\n".join(lines) + "\n")
    print(
        f"current_status_written=true refresh={refresh.get('outcome', 'missing')} "
        f"blockers={len(status['blockers'])} broker_connected=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
