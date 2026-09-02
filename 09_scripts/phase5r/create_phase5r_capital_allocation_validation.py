#!/usr/bin/env python3
"""Write a point-in-time gate audit and bounded allocation validation report."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from phase5r_daily_common import (
    NEW_CANDIDATE_PATH,
    PORTFOLIO_SUMMARY_PATH,
    ROOT,
    atomic_write_csv,
    atomic_write_text,
    iso_now,
    read_csv,
)


SNAPSHOT_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_snapshots.local.jsonl"
)
OUTCOME_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_outcomes.local.csv"
)
VALUATION_PATH = ROOT / "04_data" / "phase5r" / "phase5r_valuation_scenarios.local.json"
BASELINE_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_current_research_baseline.csv"
)
AUDIT_PATH = ROOT / "05_risk_and_positions" / "phase5r_c9_gate_audit.csv"
REPORT_PATH = (
    ROOT / "08_reviews" / "current"
    / "phase5r_capital_allocation_validation.local.md"
)
AUDIT_FIELDS = [
    "ticker", "asset_role", "current_price", "valuation_applicability",
    "expected_upside_pct", "reward_to_risk", "score", "confidence",
    "sizing_tier", "suggested_whole_shares", "suggested_position_pct",
    "eligibility", "gate_blockers", "legacy_strict_pass",
    "exploratory_relaxed_pass", "automatic_action_allowed",
]


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    candidates = read_csv(NEW_CANDIDATE_PATH)
    summary_rows = read_csv(PORTFOLIO_SUMMARY_PATH)
    if len(summary_rows) != 1:
        raise RuntimeError("portfolio summary must contain one row")
    summary = summary_rows[0]
    account_total = _number(summary.get("account_total_value"))
    deployable_cash = _number(summary.get("deployable_cash"))
    active_headroom = max(
        0.0,
        account_total
        * (
            _number(summary.get("active_stock_hard_cap_pct"))
            - _number(summary.get("current_active_stock_weight_pct"))
        )
        / 100.0,
    )
    baseline = {row["ticker"]: row for row in read_csv(BASELINE_PATH)}
    audit_rows: list[dict[str, str]] = []
    for row in candidates:
        technical = _number(
            baseline.get(row["ticker"], {}).get("technical_entry_discipline_score")
        )
        score = _number(row.get("account_aware_conviction_score"))
        upside = _number(row.get("expected_upside_pct"))
        reward_risk = _number(row.get("reward_to_risk_estimate"))
        fit = _number(row.get("portfolio_fit_score"))
        confidence_ok = row.get("recommendation_confidence") in {"medium_high", "high"}
        valuation_ok = (
            row.get("valuation_applicability") == "applicable_company_ev_to_revenue"
        )
        current_price = _number(row.get("current_price"))
        legacy_whole_share_feasible = current_price > 0 and current_price <= min(
            deployable_cash,
            account_total * 0.06,
            active_headroom,
        ) + 1e-9
        legacy = (
            valuation_ok and score >= 7.5 and confidence_ok and upside >= 15.0
            and reward_risk >= 1.5 and technical >= 6.0 and fit >= 5.0
            and legacy_whole_share_feasible
        )
        exploratory = (
            valuation_ok and score >= 6.5 and confidence_ok and upside >= 5.0
            and reward_risk >= 1.0 and technical >= 5.0 and fit >= 4.0
            and legacy_whole_share_feasible
        )
        audit_rows.append({
            "ticker": row.get("ticker", ""),
            "asset_role": row.get("asset_role", ""),
            "current_price": row.get("current_price", ""),
            "valuation_applicability": row.get("valuation_applicability", ""),
            "expected_upside_pct": row.get("expected_upside_pct", ""),
            "reward_to_risk": row.get("reward_to_risk_estimate", ""),
            "score": row.get("account_aware_conviction_score", ""),
            "confidence": row.get("recommendation_confidence", ""),
            "sizing_tier": row.get("sizing_tier", ""),
            "suggested_whole_shares": row.get("suggested_whole_shares", ""),
            "suggested_position_pct": row.get("suggested_position_pct", ""),
            "eligibility": row.get("eligibility_label", ""),
            "gate_blockers": row.get("gate_blockers", ""),
            "legacy_strict_pass": "yes" if legacy else "no",
            "exploratory_relaxed_pass": "yes" if exploratory else "no",
            "automatic_action_allowed": "no",
        })
    atomic_write_csv(AUDIT_PATH, AUDIT_FIELDS, audit_rows)

    snapshots = _jsonl(SNAPSHOT_PATH)
    outcomes = read_csv(OUTCOME_PATH)
    outcome_sessions = sorted({
        row.get("evaluation_session", "") for row in outcomes
        if row.get("evaluation_session")
    })
    horizons = sorted({
        int(row["horizon_sessions"]) for row in outcomes
        if row.get("horizon_sessions")
    })
    blockers = Counter(
        blocker
        for row in audit_rows
        for blocker in row["gate_blockers"].split(",")
        if blocker
    )
    valuation = json.loads(VALUATION_PATH.read_text(encoding="utf-8"))
    complete = [
        row for row in valuation.get("records", []) if row.get("status") == "complete"
    ]
    below_market = [
        row for row in complete
        if _number(row.get("scenario_prices", {}).get("base"))
        < _number(row.get("current_price"))
    ]
    production_eligible = sum(
        row["eligibility"] in {"eligible_buy_review", "eligible_core_starter_review"}
        for row in audit_rows
    )
    legacy_eligible = sum(row["legacy_strict_pass"] == "yes" for row in audit_rows)
    relaxed_eligible = sum(
        row["exploratory_relaxed_pass"] == "yes" for row in audit_rows
    )
    invested_pct = 100.0 - _number(summary.get("current_cash_pct"))
    lines = [
        "# Phase 5R capital-allocation validation",
        "",
        f"Generated: `{iso_now()}`",
        "",
        "## Current point-in-time result",
        "",
        f"- Dynamic account total: `${_number(summary.get('account_total_value')):.2f}`.",
        f"- Invested capital: `${_number(summary.get('current_holdings_value')):.2f}` (`{invested_pct:.4f}%`).",
        f"- Cash: `${_number(summary.get('cash_available')):.2f}` (`{_number(summary.get('current_cash_pct')):.4f}%`).",
        f"- Production allocation-review candidates: `{production_eligible}`.",
        f"- Most common blockers: `{dict(blockers)}`.",
        "",
        "## Threshold sensitivity (current cross-section only)",
        "",
        f"- Legacy strict binary profile: `{legacy_eligible}` candidates.",
        f"- Production tiered profile: `{production_eligible}` candidates, including the separate core policy.",
        f"- Exploratory relaxed profile: `{relaxed_eligible}` individual candidates.",
        "- The relaxed profile is diagnostic only and cannot create a production recommendation.",
        "",
        "## Valuation audit",
        "",
        f"- Complete company valuations: `{len(complete)}`; base scenario below market: `{len(below_market)}`.",
        "- The company method uses explicit EV/TTM-revenue bands plus balance-sheet, FCF, and dilution adjustments with visible scenarios.",
        "- It does not project future revenue or margin expansion. That is conservative for high-growth companies, but the outcome history is too short to fit a forward-growth model without overfitting.",
        "- The valuation arithmetic therefore remains unchanged; sizing tiers cannot bypass an adverse valuation.",
        "",
        "## Walk-forward evidence",
        "",
        f"- Point-in-time snapshots: `{len(snapshots)}`.",
        f"- Completed outcome rows: `{len(outcomes)}` across `{len(outcome_sessions)}` evaluation session(s); horizons observed: `{horizons}`.",
        "- The ledger does not yet contain enough independent sessions or historical portfolio-cash snapshots to compare cash drag, drawdown, turnover, or opportunity cost robustly.",
        "- No future information or retrospective parameter optimization was used. Continue the configured 1/5/20/60-session tracking before changing valuation bands from performance results.",
        "",
        "All rows are research-only. Broker connectivity and automatic action remain disabled.",
    ]
    atomic_write_text(REPORT_PATH, "\n".join(lines) + "\n")
    print(
        f"capital_validation_complete=true snapshots={len(snapshots)} outcomes={len(outcomes)} "
        f"production_eligible={production_eligible} broker_connected=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
