from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    REVIEW_QUEUE,
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
]


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
    packets = load_packets()
    weights = {row["ticker"]: row for row in read_csv(DYNAMIC_WEIGHTS)}
    actions = {row["ticker"]: row for row in read_csv(EXACT_ACTION_PLAN)}
    summary_rows = read_csv(PORTFOLIO_SUMMARY)
    if len(summary_rows) != 1:
        raise ValueError("C9 portfolio summary must contain one row")
    summary = summary_rows[0]
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
            rule = "dynamic_single_stock_weight_and_current_research"
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
        position_rows.append(
            {
                "priority": str(priority),
                "ticker": ticker,
                "current_value": action["current_value"],
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
            }
        )
    write_csv(C9_POSITION_RECOMMENDATIONS, position_rows, POSITION_FIELDS)

    new_rows: list[dict[str, str]] = []
    for score in scored:
        if score["asset_role"] == "current_position":
            continue
        ticker = score["ticker"]
        packet = packets[ticker]
        is_core = score["asset_role"] == "core_allocation_candidate"
        weekly_pass = float(score["account_aware_conviction_score"]) >= 7.5
        confidence_pass = score["recommendation_confidence"] in {"medium_high", "high"}
        entry_pass = as_float(packet["technical_entry_discipline_score"], f"{ticker}.technical") >= 6.0
        fit_pass = float(score["portfolio_fit_score"]) >= 5.0
        if is_core:
            eligibility_label = "separate_core_review"
            action = "core_allocation_tranche_review"
            reason = (
                "Broad-market core candidate is evaluated under the separate core policy; current cash plans are options only "
                + (
                    "and remain blocked by maintenance."
                    if maintenance_active
                    else "and none is selected by the current daily decision."
                )
            )
            resulting_caps_pass = "yes"
        else:
            eligibility_label = "wait_for_more_evidence"
            action = "watch_only"
            reason = (
                "Expected upside and reward-to-risk estimates are unavailable, so individual-stock eligibility is incomplete; "
                "no value was invented and no purchase review is recommended."
            )
            resulting_caps_pass = "no"
        new_rows.append(
            {
                "weekly_rank": score["weekly_rank"],
                "ticker": ticker,
                "asset_role": score["asset_role"],
                "theme": packet["theme"],
                "account_aware_conviction_score": score["account_aware_conviction_score"],
                "portfolio_fit_score": score["portfolio_fit_score"],
                "recommendation_confidence": score["recommendation_confidence"],
                "controlled_research_packet_exists": "yes",
                "expected_upside_pct": "",
                "reward_to_risk_estimate": "",
                "weekly_score_pass": "yes" if weekly_pass else "no",
                "confidence_pass": "yes" if confidence_pass else "no",
                "expected_upside_pass": "no",
                "reward_to_risk_pass": "no",
                "entry_discipline_pass": "yes" if entry_pass else "no",
                "portfolio_fit_pass": "yes" if fit_pass else "no",
                "resulting_caps_pass": resulting_caps_pass,
                "eligibility_label": eligibility_label,
                "recommended_action": action,
                "reason": reason,
                "human_confirmation_required": (
                    "yes" if action in {"eligible_buy_review", "add_specific_dollars_review"} else "no"
                ),
                "automatic_action_allowed": "no",
            }
        )
    write_csv(C9_NEW_RECOMMENDATIONS, new_rows, NEW_FIELDS)

    eligible_individual = [
        row
        for row in new_rows
        if row["asset_role"] == "individual_stock_candidate" and row["eligibility_label"] == "eligible_buy_review"
    ]
    cash_plans = read_csv(CASH_DEPLOYMENT_PLAN)
    review_date = cash_plans[0]["planned_review_date"]
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
        f"- Cash/holding reconciliation difference: `${float(summary['reconciliation_difference']):.2f}` (`{summary['reconciliation_status']}`).",
        "",
        "## Current Position Actions",
        "",
        *action_lines,
        "",
        "IOT and RBRK were recalculated independently. No add is recommended for either current position today.",
        "",
        "## Core and Cash",
        "",
        (
            "SPY is separated from individual-stock momentum research and appears only as a broad-market core candidate. "
            "Three cash-deployment approaches are documented; "
            + (
                "maintenance blocks every purchase tranche."
                if maintenance_active
                else "the current daily decision selects none of them."
            )
            + " The current cash decision is `no_deployment_until_next_review`."
        ),
        "",
        "## New Individual Stocks",
        "",
        f"Eligible individual-stock purchase reviews: `{len(eligible_individual)}`. Expected-upside and reward-to-risk evidence is unavailable, so no individual-stock purchase is recommended.",
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
                "The 60% core target is a policy target, not an instruction to deploy immediately. "
                + (
                    "All core plans remain maintenance-blocked."
                    if maintenance_active
                    else "All core plans remain conditional and unselected by the current daily decision."
                )
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
        f"- Cash-deployment decision: `no_deployment_until_next_review`.",
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
