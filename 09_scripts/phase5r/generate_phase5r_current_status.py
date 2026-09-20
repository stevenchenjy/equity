#!/usr/bin/env python3
"""Generate one concise current Phase 5R production status artifact."""

from __future__ import annotations

from equity_naming import report_heading

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from phase5r_active_config import ACTIVE_CONFIG_PATH, load_active_config
from phase5r_daily_common import (
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


STATUS_JSON_PATH = ROOT / "00_project_control" / "phase5r_current_production_status.local.json"
STATUS_MD_PATH = ROOT / "00_project_control" / "phase5r_current_production_status.local.md"
VALUATION_PATH = ROOT / "04_data" / "phase5r" / "phase5r_valuation_scenarios.local.json"
SNAPSHOT_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_snapshots.local.jsonl"
)
OUTCOME_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_outcomes.local.csv"
)
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
    from phase5r_official_news import read_official_news_status
    from phase5r_market_regime import load_regime_controls
    try:
        news = read_official_news_status(now=current)
    except (OSError, ValueError, TypeError, KeyError):
        news = {"status": "degraded", "required_coverage_complete": False,
                "reason": "official_news_receipt_invalid"}
    regime = load_regime_controls(expected_session)
    long_report = read_json(ROOT / "04_research/realtime_stock_picker_phase5r/phase5r_long_horizon_research.local.json", {})
    positions = read_csv(ROOT / "05_risk_and_positions/current_positions.local.csv")
    universe = read_csv(ROOT / "03_source_data/phase5r/phase5r_universe_seed.csv")
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
    for ticker in sorted(held_companies):
        company = long_report.get("companies", {}).get(ticker, {})
        if company.get("readiness") != "research_complete":
            research_gaps.append(f"{ticker}:thesis_research_pending")
    scheduler = read_json(ROOT / "00_project_control/run_logs/phase5r_daily_scheduler_state.local.json", {}).get("dates", {})
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
            "gaps": research_gaps,
            "interpretation": "Operational success is separate from an evidenced long-term investment thesis",
        },
        "official_news": news,
        "market_regime": regime,
        "reliability": reliability,
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
        f"- Production model: retired; calls allowed `{status['model']['calls_allowed']}`; retired-pilot metered cost `${status['model']['metered_cost_usd']}`. These are not current SHADOW usage or costs; see `08_reviews/phase5r_shadow_llm/reviews.local/evaluation.md`.",
        f"- Current blockers: `{', '.join(status['blockers']) or 'none'}`.",
        f"- Research coverage: `{len(held_companies & valued)}/{len(held_companies)}` held-company valuations complete; gaps `{', '.join(research_gaps) or 'see company thesis review status'}`.",
        f"- Official news: `{news.get('status', 'missing')}`; this is independent of the SEC filing check.",
        f"- Market context: `{regime['regime']}`; new-capital confirmation `{regime['required_distinct_closes']}` distinct closes.",
        f"- Retained daily refresh completions: `{reliability['fully_refreshed_days']}/{len(retained)}` calendar days; delivery-unknown dates `{', '.join(reliability['delivery_unknown_days']) or 'none'}`.",
        "- Boundaries: research only; no broker read, automatic order, or trade placement.",
        "",
        "This generated file and `phase5r_active_production_config.json` are the current authority. Older pilot registries and dated reports are historical evidence only.",
    ]
    atomic_write_text(STATUS_MD_PATH, "\n".join(lines) + "\n")
    print(
        f"current_status_written=true refresh={refresh.get('outcome', 'missing')} "
        f"blockers={len(status['blockers'])} broker_connected=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
