from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from phase5r_active_config import load_active_config
from phase5r_c9_common import (
    ACCOUNT_STATE,
    CASH_DEPLOYMENT_PLAN,
    C5_PACKETS,
    C9_ALLOCATION_REPORT,
    C9_MEMO,
    C9_NEW_RECOMMENDATIONS,
    C9_POSITION_RECOMMENDATIONS,
    C9_SCORES,
    CURRENT_POSITIONS,
    DYNAMIC_WEIGHTS,
    EXACT_ACTION_PLAN,
    MARKET_SNAPSHOT,
    PORTFOLIO_SUMMARY,
    POST_ACTION_PORTFOLIO,
    REVIEW_QUEUE,
    ROOT,
    TARGET_ALLOCATION_REPORT,
    WEEKLY_DECISION_SUMMARY,
    append_run_log,
    as_float,
    dynamic_candidate_fit,
    load_account_state,
    load_active_inhibit,
    load_packets,
    read_csv,
    score_from_packet,
    timestamp,
    write_csv,
    write_text,
)
from phase5r_portfolio_construction import individual_sizing_decision


SCRIPTS_DIR = Path(__file__).resolve().parent
CHILD_SCRIPTS = [
    SCRIPTS_DIR / "create_phase5r_c9_account_state.py",
    SCRIPTS_DIR / "calculate_phase5r_c9_dynamic_weights.py",
    SCRIPTS_DIR / "create_phase5r_c9_exact_action_plan.py",
    SCRIPTS_DIR / "create_phase5r_c9_cash_deployment_plan.py",
]
SCORE_FIELDS = [
    "weekly_rank",
    "ticker",
    "asset_role",
    "current_weight_pct",
    "business_quality_score",
    "earnings_revenue_trend_score",
    "valuation_reasonableness_score",
    "catalyst_news_quality_score",
    "technical_entry_discipline_score",
    "portfolio_fit_score",
    "account_aware_conviction_score",
    "holding_horizon_candidate",
    "recommendation_label",
    "recommendation_confidence",
    "concentration_status",
    "portfolio_rule_applied",
    "human_action_required",
    "automatic_action_allowed",
    "score_formula",
]
POSITION_FIELDS = [
    "priority",
    "ticker",
    "current_value",
    "current_price",
    "current_weight_pct",
    "concentration_status",
    "account_aware_conviction_score",
    "recommendation_label",
    "recommended_action",
    "target_weight_pct",
    "target_value",
    "whole_shares_to_change",
    "target_shares",
    "resulting_weight_pct",
    "holding_horizon",
    "trim_price_or_condition",
    "invalidation_price_or_condition",
    "recommendation_confidence",
    "reason",
    "human_confirmation_required",
    "automatic_action_allowed",
    "valuation_bear_price",
    "valuation_base_price",
    "valuation_bull_price",
    "expected_upside_pct",
    "reward_to_risk_estimate",
    "strongest_positive_evidence",
    "strongest_negative_evidence",
    "valuation_source",
]
NEW_FIELDS = [
    "weekly_rank",
    "ticker",
    "asset_role",
    "theme",
    "account_aware_conviction_score",
    "portfolio_fit_score",
    "recommendation_confidence",
    "controlled_research_packet_exists",
    "valuation_applicability",
    "expected_upside_pct",
    "reward_to_risk_estimate",
    "weekly_score_pass",
    "confidence_pass",
    "expected_upside_pass",
    "reward_to_risk_pass",
    "entry_discipline_pass",
    "portfolio_fit_pass",
    "resulting_caps_pass",
    "eligibility_label",
    "recommended_action",
    "reason",
    "human_confirmation_required",
    "automatic_action_allowed",
    "current_price",
    "valuation_bear_price",
    "valuation_base_price",
    "valuation_bull_price",
    "maximum_review_price",
    "suggested_whole_shares",
    "suggested_position_pct",
    "sizing_tier",
    "small_account_exception_used",
    "gate_blockers",
    "holding_horizon",
    "invalidation_condition",
    "strongest_positive_evidence",
    "strongest_negative_evidence",
    "valuation_source",
]

VALUATION_SCENARIO_PATH = (
    ROOT / "04_data" / "phase5r" / "phase5r_valuation_scenarios.local.json"
)


def run_children() -> None:
    for script in CHILD_SCRIPTS:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=script.parents[2],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"C9 child stage failed safely: {script.name}")


def main() -> None:
    inhibit = load_active_inhibit()
    maintenance_active = inhibit.get("active") is True
    run_children()
    account = load_account_state()
    construction_policy = load_active_config()["account"]
    valuation_payload = json.loads(VALUATION_SCENARIO_PATH.read_text(encoding="utf-8"))
    valuation_by_ticker = {
        row["ticker"]: row for row in valuation_payload.get("records", [])
        if isinstance(row, dict) and row.get("ticker")
    }
    packets = load_packets()
    weights = {row["ticker"]: row for row in read_csv(DYNAMIC_WEIGHTS)}
    actions = {row["ticker"]: row for row in read_csv(EXACT_ACTION_PLAN)}
    summary_rows = read_csv(PORTFOLIO_SUMMARY)
    if len(summary_rows) != 1:
        raise ValueError("C9 portfolio summary must contain one row")
    summary = summary_rows[0]
    market_by_ticker = {
        row["ticker"].strip().upper(): row
        for row in read_csv(MARKET_SNAPSHOT)
        if row.get("ticker", "").strip()
    }
    cash_plans = read_csv(CASH_DEPLOYMENT_PLAN)
    core_plan = next(
        (
            row for row in cash_plans
            if row.get("plan_id") == "core_starter_whole_share_review"
        ),
        {},
    )
    active_weight = as_float(summary["current_active_stock_weight_pct"], "current_active_stock_weight_pct")

    scored: list[dict[str, str]] = []
    for ticker, packet in packets.items():
        if ticker in weights:
            weight_row = weights[ticker]
            role = "current_position"
            weight = weight_row["current_weight_pct"]
            fit = as_float(weight_row["portfolio_fit_score"], f"{ticker}.portfolio_fit_score")
            score = as_float(weight_row["current_research_score"], f"{ticker}.current_research_score")
            label = weight_row["current_recommendation_label"]
            concentration = weight_row["concentration_status"]
            rule = (
                "core_allocation_policy"
                if weight_row.get("asset_role") == "core_allocation"
                else "dynamic_single_stock_weight_and_current_research"
            )
        elif ticker == "SPY":
            role = "core_allocation_candidate"
            weight = "0.0000"
            fit = 9.0
            score = score_from_packet(packet, fit)
            label = "core_allocation_candidate"
            concentration = "separate_core_sleeve"
            rule = "separate_core_allocation_policy"
        else:
            role = "individual_stock_candidate"
            weight = "0.0000"
            fit = dynamic_candidate_fit(packet["theme"], active_weight, account)
            score = score_from_packet(packet, fit)
            label = "wait_for_more_evidence"
            concentration = "not_held"
            rule = "eligibility_evidence_incomplete"
        scored.append(
            {
                "weekly_rank": "",
                "ticker": ticker,
                "asset_role": role,
                "current_weight_pct": weight,
                "business_quality_score": packet["business_quality_score"],
                "earnings_revenue_trend_score": packet["earnings_revenue_trend_score"],
                "valuation_reasonableness_score": packet["valuation_reasonableness_score"],
                "catalyst_news_quality_score": packet["catalyst_news_quality_score"],
                "technical_entry_discipline_score": packet["technical_entry_discipline_score"],
                "portfolio_fit_score": f"{fit:.1f}",
                "account_aware_conviction_score": f"{score:.2f}",
                "holding_horizon_candidate": packet["holding_horizon_candidate"],
                "recommendation_label": label,
                "recommendation_confidence": packet["recommendation_confidence"],
                "concentration_status": concentration,
                "portfolio_rule_applied": rule,
                "human_action_required": (
                    "yes" if label in {"exit_review", "trim_review", "add_review"} else "no"
                ),
                "automatic_action_allowed": "no",
                "score_formula": "0.25*business+0.20*earnings+0.15*valuation+0.15*catalyst+0.15*technical+0.10*dynamic_portfolio_fit",
            }
        )
    role_order = {"current_position": 0, "core_allocation_candidate": 1, "individual_stock_candidate": 2}
    scored.sort(key=lambda row: (role_order[row["asset_role"]], -float(row["account_aware_conviction_score"]), row["ticker"]))
    for rank, row in enumerate(scored, start=1):
        row["weekly_rank"] = str(rank)
    write_csv(C9_SCORES, scored, SCORE_FIELDS)

    score_by_ticker = {row["ticker"]: row for row in scored}
    position_rows: list[dict[str, str]] = []
    for priority, action in enumerate(
        sorted(actions.values(), key=lambda row: (row["recommended_action"] != "trim_specific_shares_review", -float(row["current_weight_pct"]))),
        start=1,
    ):
        ticker = action["ticker"]
        score = score_by_ticker[ticker]
        valuation = valuation_by_ticker.get(ticker, {})
        prices = valuation.get("scenario_prices", {})
        position_rows.append(
            {
                "priority": str(priority),
                "ticker": ticker,
                "current_value": action["current_value"],
                "current_price": action["current_price"],
                "current_weight_pct": action["current_weight_pct"],
                "concentration_status": weights[ticker]["concentration_status"],
                "account_aware_conviction_score": score["account_aware_conviction_score"],
                "recommendation_label": score["recommendation_label"],
                "recommended_action": action["recommended_action"],
                "target_weight_pct": action["target_weight_pct"],
                "target_value": action["target_value"],
                "whole_shares_to_change": action["whole_shares_to_change"],
                "target_shares": action["target_shares"],
                "resulting_weight_pct": action["resulting_weight_pct"],
                "holding_horizon": action["holding_horizon"],
                "trim_price_or_condition": action["trim_price_or_condition"],
                "invalidation_price_or_condition": action["invalidation_price_or_condition"],
                "recommendation_confidence": action["recommendation_confidence"],
                "reason": action["reason"],
                "human_confirmation_required": action["human_confirmation_required"],
                "automatic_action_allowed": "no",
                "valuation_bear_price": str(prices.get("bear", "")),
                "valuation_base_price": str(prices.get("base", "")),
                "valuation_bull_price": str(prices.get("bull", "")),
                "expected_upside_pct": str(valuation.get("expected_upside_pct", "")),
                "reward_to_risk_estimate": str(valuation.get("reward_to_risk", "")),
                "strongest_positive_evidence": valuation.get("strongest_positive_evidence", ""),
                "strongest_negative_evidence": valuation.get("strongest_negative_evidence", ""),
                "valuation_source": valuation.get("fundamental_source_url", ""),
            }
        )
    write_csv(C9_POSITION_RECOMMENDATIONS, position_rows, POSITION_FIELDS)

    new_rows: list[dict[str, str]] = []
    individual_eligible_used = False
    deployable_cash = as_float(summary["deployable_cash"], "deployable_cash")
    account_total = as_float(summary["account_total_value"], "account_total_value")
    default_cap_pct = as_float(account["single_stock_default_cap_pct"], "single_stock_default_cap_pct")
    active_hard_pct = as_float(account["active_stock_hard_cap_pct"], "active_stock_hard_cap_pct")
    for score in scored:
        ticker = score["ticker"]
        is_core = ticker == "SPY"
        if score["asset_role"] == "current_position" and not is_core:
            continue
        packet = packets[ticker]
        valuation = valuation_by_ticker.get(ticker, {})
        prices = valuation.get("scenario_prices", {}) if valuation.get("status") == "complete" else {}
        market_row = market_by_ticker.get(ticker, {})
        current_price = as_float(
            str(valuation.get("current_price") or market_row.get("last_price") or 0),
            f"{ticker}.current_price",
        )
        expected_upside = as_float(str(valuation.get("expected_upside_pct", 0) or 0), f"{ticker}.expected_upside_pct")
        reward_to_risk = as_float(str(valuation.get("reward_to_risk", 0) or 0), f"{ticker}.reward_to_risk")
        base_price = as_float(str(prices.get("base", 0) or 0), f"{ticker}.base_price")
        entry_score = as_float(packet["technical_entry_discipline_score"], f"{ticker}.technical")
        sizing = individual_sizing_decision(
            policy=construction_policy,
            valuation_complete=valuation.get("status") == "complete",
            score=float(score["account_aware_conviction_score"]),
            confidence=score["recommendation_confidence"],
            expected_upside_pct=expected_upside,
            reward_to_risk=reward_to_risk,
            entry_score=entry_score,
            portfolio_fit_score=float(score["portfolio_fit_score"]),
            current_price=current_price,
            account_total=account_total,
            deployable_cash=deployable_cash,
            active_weight_pct=active_weight,
            active_hard_cap_pct=active_hard_pct,
            single_stock_default_cap_pct=default_cap_pct,
        )
        gate_results = sizing["gate_results"]
        weekly_pass = bool(gate_results["score"])
        confidence_pass = bool(gate_results["confidence"])
        entry_pass = bool(gate_results["entry"])
        fit_pass = bool(gate_results["portfolio_fit"])
        expected_upside_pass = bool(gate_results["upside"])
        reward_to_risk_pass = bool(gate_results["reward_to_risk"])
        suggested_whole_shares = int(sizing["suggested_whole_shares"])
        suggested_position_pct = float(sizing["suggested_position_pct"])
        caps_pass = suggested_whole_shares >= 1
        sizing_tier = str(sizing["sizing_tier"])
        maximum_review_price = (
            base_price
            / (1.0 + float(construction_policy["candidate_sizing_tiers"][-1]["minimum_expected_upside_pct"]) / 100.0)
            if base_price > 0
            else 0.0
        )
        if is_core:
            core_status = core_plan.get("status", "not_selected")
            suggested_whole_shares = int(core_plan.get("planned_shares", "0") or 0)
            suggested_position_pct = as_float(
                core_plan.get("core_weight_after", "0") or "0",
                "SPY.core_weight_after",
            )
            sizing_tier = core_plan.get("sizing_tier", "no_allocation")
            maximum_review_price = current_price
            eligibility_label = (
                "eligible_core_starter_review"
                if core_status == "selected_review"
                else "core_review_blocked_maintenance"
                if core_status == "blocked_maintenance"
                else "wait_for_core_entry"
            )
            action = (
                "core_allocation_tranche_review"
                if core_status in {"selected_review", "blocked_maintenance"}
                else "watch_only"
            )
            reason = (
                "Broad-market ETF valuation is not an individual-company EV/revenue exercise. "
                f"The separate core policy produced status={core_status}, {suggested_whole_shares} whole share(s), "
                f"and a resulting core weight of {suggested_position_pct:.4f}%. "
                + core_plan.get("reason", "")
            )
            resulting_caps_pass = "yes" if suggested_whole_shares >= 1 else "no"
            gate_blockers = ",".join(
                part.strip()
                for part in core_plan.get("reason", "").partition("Failed gates:")[2].rstrip(".").split(",")
                if part.strip() and part.strip() != "none"
            )
            valuation_applicability = "not_applicable_broad_market_etf"
        elif suggested_whole_shares >= 1 and not individual_eligible_used:
            individual_eligible_used = True
            eligibility_label = "eligible_buy_review"
            action = "eligible_buy_review"
            reason = (
                f"The {sizing_tier} gates pass: expected upside {expected_upside:.2f}%, "
                f"reward/risk {reward_to_risk:.2f}, and a {suggested_whole_shares}-share scenario is "
                f"{suggested_position_pct:.4f}% of the account. Independent human review is required."
            )
            resulting_caps_pass = "yes"
            gate_blockers = ""
            valuation_applicability = "applicable_company_ev_to_revenue"
        else:
            eligibility_label = "wait_for_more_evidence"
            action = "watch_only"
            failed = list(sizing["failed_gates"])
            if suggested_whole_shares >= 1 and individual_eligible_used:
                failed.append("one_candidate_attention_limit")
            reason = "Deterministic purchase-review gates not all satisfied: " + ",".join(failed or ["valuation_incomplete"])
            resulting_caps_pass = "yes" if caps_pass else "no"
            gate_blockers = ",".join(failed)
            valuation_applicability = "applicable_company_ev_to_revenue"
        new_rows.append(
            {
                "weekly_rank": score["weekly_rank"],
                "ticker": ticker,
                "asset_role": "core_allocation_candidate" if is_core else score["asset_role"],
                "theme": packet["theme"],
                "account_aware_conviction_score": score["account_aware_conviction_score"],
                "portfolio_fit_score": score["portfolio_fit_score"],
                "recommendation_confidence": score["recommendation_confidence"],
                "controlled_research_packet_exists": "yes",
                "valuation_applicability": valuation_applicability,
                "expected_upside_pct": f"{expected_upside:.2f}" if valuation.get("status") == "complete" else "",
                "reward_to_risk_estimate": f"{reward_to_risk:.2f}" if valuation.get("status") == "complete" else "",
                "weekly_score_pass": "yes" if weekly_pass else "no",
                "confidence_pass": "yes" if confidence_pass else "no",
                "expected_upside_pass": "yes" if expected_upside_pass else "no",
                "reward_to_risk_pass": "yes" if reward_to_risk_pass else "no",
                "entry_discipline_pass": "yes" if entry_pass else "no",
                "portfolio_fit_pass": "yes" if fit_pass else "no",
                "resulting_caps_pass": resulting_caps_pass,
                "eligibility_label": eligibility_label,
                "recommended_action": action,
                "reason": reason,
                "human_confirmation_required": (
                    "yes"
                    if eligibility_label in {"eligible_buy_review", "eligible_core_starter_review"}
                    else "no"
                ),
                "automatic_action_allowed": "no",
                "current_price": f"{current_price:.2f}" if current_price > 0 else "",
                "valuation_bear_price": str(prices.get("bear", "")),
                "valuation_base_price": str(prices.get("base", "")),
                "valuation_bull_price": str(prices.get("bull", "")),
                "maximum_review_price": f"{maximum_review_price:.2f}" if maximum_review_price > 0 else "",
                "suggested_whole_shares": str(suggested_whole_shares) if suggested_whole_shares else "0",
                "suggested_position_pct": f"{suggested_position_pct:.4f}",
                "sizing_tier": sizing_tier,
                "small_account_exception_used": (
                    "yes" if sizing.get("small_account_exception_used") else "no"
                ),
                "gate_blockers": gate_blockers,
                "holding_horizon": packet["holding_horizon_candidate"],
                "invalidation_condition": packet["exit_or_trim_conditions"],
                "strongest_positive_evidence": valuation.get("strongest_positive_evidence", ""),
                "strongest_negative_evidence": valuation.get("strongest_negative_evidence", ""),
                "valuation_source": valuation.get("fundamental_source_url", ""),
            }
        )
    write_csv(C9_NEW_RECOMMENDATIONS, new_rows, NEW_FIELDS)

    eligible_individual = [
        row
        for row in new_rows
        if row["asset_role"] == "individual_stock_candidate" and row["eligibility_label"] == "eligible_buy_review"
    ]
    review_date = cash_plans[0]["planned_review_date"]
    core_recommendation = next(
        row for row in new_rows if row["asset_role"] == "core_allocation_candidate"
    )
    post_action_rows = read_csv(POST_ACTION_PORTFOLIO)
    selected_post_action = next(
        row for row in post_action_rows
        if row["scenario"] == "after_position_and_core_reviews"
    )
    invested_pct = 100.0 - as_float(summary["current_cash_pct"], "current_cash_pct")
    underdeployment_threshold = as_float(
        construction_policy["underdeployment_review_invested_pct_below"],
        "underdeployment_review_invested_pct_below",
    )
    action_lines = [
        f"- {row['ticker']}: ${float(row['current_value']):.2f}, {float(row['current_weight_pct']):.4f}%, "
        f"{row['recommended_action']}; target {float(row['target_weight_pct']):.4f}% / ${float(row['target_value']):.2f}; "
        f"whole shares to change {row['whole_shares_to_change']}."
        for row in position_rows
    ]
    memo_lines = [
        "# Phase 5R-C9 Account-Aware Memo",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Account State",
        "",
        f"- Account total: `${float(summary['account_total_value']):.2f}`.",
        f"- Reported cash: `${float(summary['cash_available']):.2f}` (`{float(summary['current_cash_pct']):.4f}%`).",
        f"- Active-stock sleeve: `${float(summary['current_active_stock_value']):.2f}` (`{active_weight:.4f}%`), status `{summary['active_stock_status']}`.",
        f"- Core sleeve currently recorded: `${float(summary['current_core_value']):.2f}`.",
        f"- Invested capital: `${float(summary['current_holdings_value']):.2f}` (`{invested_pct:.4f}%`); underdeployment review threshold `{underdeployment_threshold:.2f}%`.",
        f"- Cash/holding reconciliation difference: `${float(summary['reconciliation_difference']):.2f}` (`{summary['reconciliation_status']}`).",
        "",
        "## Current Position Actions",
        "",
        *action_lines,
        "",
        "Every held position was recalculated independently. A trim/exit scenario now flows into a complete post-action cash and allocation review.",
        "",
        "## Core and Cash",
        "",
        (
            f"Current core conclusion: `{core_recommendation['eligibility_label']}`; "
            f"whole-share example `{core_recommendation['suggested_whole_shares']}` SPY at the "
            f"quality-ok close `${core_recommendation['current_price']}` (about "
            f"`{core_recommendation['suggested_position_pct']}%`). Individual-company EV/revenue "
            "valuation is explicitly not applicable to this broad-market ETF; the separate core policy "
            "uses allocation gap, market quality, entry discipline, range position, reserve, and whole-share feasibility."
        ),
        f"Cash rationale: {core_plan.get('cash_rationale', '')}",
        "",
        "## New Individual Stocks",
        "",
        f"Eligible individual-stock purchase reviews: `{len(eligible_individual)}`. At most one candidate is surfaced per refresh; every scenario remains research-only and requires independent human confirmation.",
        "Uncertainty now maps to starter, normal, or high-conviction sizing. Negative/incomplete valuation, inadequate reward/risk, or infeasible whole-share concentration still produces zero allocation.",
        "",
        "## Portfolio After All Current Reviews",
        "",
        f"- Hypothetical active stocks: `${float(selected_post_action['resulting_active_value']):.2f}` (`{float(selected_post_action['active_weight_pct']):.4f}%`).",
        f"- Hypothetical core: `${float(selected_post_action['resulting_core_value']):.2f}` (`{float(selected_post_action['core_weight_pct']):.4f}%`).",
        f"- Hypothetical retained cash: `${float(selected_post_action['resulting_cash']):.2f}` (`{float(selected_post_action['cash_weight_pct']):.4f}%`).",
        f"- Why cash remains: {selected_post_action['retained_cash_reason']}",
        "",
        "## Next Review",
        "",
        f"Next planned daily review: `{review_date}`.",
        "",
        "HOLD and WATCH require no routine human confirmation. Any portfolio-action transition remains a research plan requiring independent human review. Automatic action is prohibited.",
    ]
    write_text(C9_MEMO, "\n".join(memo_lines) + "\n")

    allocation_rows = read_csv(TARGET_ALLOCATION_REPORT)
    allocation_lines = [
        "# Phase 5R-C9 Allocation Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "| Role | Current Value | Current Weight | Target Weight | Target Value | Status |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in allocation_rows:
        allocation_lines.append(
            f"| {row['asset_role']} | ${float(row['current_value']):.2f} | {float(row['current_weight_pct']):.4f}% | "
            f"{float(row['target_weight_pct']):.2f}% | ${float(row['target_value']):.2f} | {row['policy_status']} |"
        )
    allocation_lines.extend(
        [
            "",
            (
                "The 60% core target is a planning target, not a forced deployment rule. "
                f"Current whole-share core status is `{core_plan.get('status', 'not_selected')}`; "
                "the reserve, freshness, entry, and human-confirmation gates remain binding."
            ),
        ]
    )
    write_text(C9_ALLOCATION_REPORT, "\n".join(allocation_lines) + "\n")

    weekly_lines = [
        "# Phase 5R-C9 Supporting Decision Summary (Daily Refresh)",
        "",
        f"Generated: `{timestamp()}`",
        "",
        f"- Primary scenario: `c9_account_aware_manual_review`.",
        f"- Account total: `${float(summary['account_total_value']):.2f}`.",
        f"- Current cash: `${float(summary['cash_available']):.2f}` (`{float(summary['current_cash_pct']):.4f}%`).",
        f"- Current active-stock sleeve: `${float(summary['current_active_stock_value']):.2f}` (`{active_weight:.4f}%`).",
        f"- Capital-deployment decision: `{core_recommendation['eligibility_label']}`; proposed whole shares `{core_recommendation['suggested_whole_shares']}`.",
        f"- Post-review retained cash: `${float(selected_post_action['resulting_cash']):.2f}` (`{float(selected_post_action['cash_weight_pct']):.4f}%`).",
        f"- New eligible individual-stock count: `{len(eligible_individual)}`.",
        f"- Next review date: `{review_date}`.",
        "",
        "## Exact Current-Position Review",
        "",
        *action_lines,
        "",
        (
            "No transaction is automatic. "
            + (
                "Maintenance inhibit remains active. "
                if maintenance_active
                else "The active workflow is eligible only through the separate daily sender. "
            )
            + "This C9 refresh sent no email."
        ),
    ]
    write_text(WEEKLY_DECISION_SUMMARY, "\n".join(weekly_lines) + "\n")

    outputs = [
        C9_SCORES,
        C9_POSITION_RECOMMENDATIONS,
        C9_NEW_RECOMMENDATIONS,
        C9_MEMO,
        C9_ALLOCATION_REPORT,
        WEEKLY_DECISION_SUMMARY,
    ]
    append_run_log(
        Path(__file__).name,
        "regenerate_account_aware_portfolio_outputs",
        "complete",
        [ACCOUNT_STATE, CURRENT_POSITIONS, MARKET_SNAPSHOT, C5_PACKETS, DYNAMIC_WEIGHTS, EXACT_ACTION_PLAN],
        outputs,
        position_count=len(position_rows),
        notes=(
            f"eligible_individual_count={len(eligible_individual)}; core_separate=yes; "
            "stored_position_pct_current_truth=no; no_email=yes"
        ),
    )
    print(
        "Phase 5R-C9 portfolio regeneration complete; "
        f"positions={len(position_rows)}; individual_eligible={len(eligible_individual)}"
    )


if __name__ == "__main__":
    main()
