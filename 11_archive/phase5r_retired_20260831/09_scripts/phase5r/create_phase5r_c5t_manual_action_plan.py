from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
CONTROL_DIR = ROOT / "00_project_control"

LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
SCENARIOS = POSITION_DIR / "phase5r_c5t_trim_scenario_table.csv"
C5_SCORES = RESEARCH_DIR / "phase5r_c5_weekly_conviction_scores.csv"
C5_RECOMMENDATIONS = RESEARCH_DIR / "phase5r_c5_position_review_recommendations.csv"
CHECKLIST = POSITION_DIR / "phase5r_c5t_hold_vs_trim_checklist.csv"
TRIGGERS = POSITION_DIR / "phase5r_c5t_next_review_triggers.csv"
PLAN = POSITION_DIR / "phase5r_c5t_manual_action_plan.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c5t_manual_action_report.md"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c5t_run_log.csv"

CHECKLIST_FIELDS = [
    "ticker", "current_position_pct", "weekly_conviction_score", "recommendation_label",
    "hold_case", "trim_case", "wait_case", "evidence_needed_before_action", "next_review_date",
    "thesis_checks", "concentration_checks", "earnings_news_checks", "human_decision_needed",
    "automatic_action_allowed",
]
TRIGGER_FIELDS = [
    "trigger_id", "ticker_or_portfolio", "trigger_category", "condition_to_review", "current_baseline",
    "review_response", "urgency", "next_review_date", "human_decision_needed", "automatic_action_allowed",
]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "account_value_usd", "position_rows", "scenario_count", "scenario_rows", "email_sent",
    "scheduler_used", "broker_used", "smtp_config_modified", "archived_legacy_used", "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_log(account: str, positions: int, scenarios: int, scenario_rows: int) -> None:
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5t", "script_name": Path(__file__).name,
            "action": "create_hold_trim_wait_action_plan",
            "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [LOCAL_POSITIONS, SCENARIOS, C5_SCORES, C5_RECOMMENDATIONS]),
            "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [CHECKLIST, TRIGGERS, PLAN, RESEARCH_REPORT]),
            "status": "complete", "account_value_usd": account, "position_rows": str(positions),
            "scenario_count": str(scenarios), "scenario_rows": str(scenario_rows),
            "email_sent": "no", "scheduler_used": "no", "broker_used": "no",
            "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "planning_only=yes; no_delivery=yes; no_automation=yes; human_decision_required=yes",
        })


def main() -> None:
    positions = read_csv(LOCAL_POSITIONS)
    scenarios = read_csv(SCENARIOS)
    scores = {row["ticker"]: row for row in read_csv(C5_SCORES)}
    recommendations = {row["ticker"]: row for row in read_csv(C5_RECOMMENDATIONS)}
    next_review_dates = {row["planned_review_date"] for row in positions}
    if len(next_review_dates) != 1:
        raise RuntimeError("Current positions must share one next review date for C5T")
    next_review = next_review_dates.pop()

    checklist_rows: list[dict[str, str]] = []
    for position in positions:
        ticker = position["ticker"].upper()
        pct = float(position["position_pct"])
        score = scores[ticker]
        checklist_rows.append({
            "ticker": ticker, "current_position_pct": f"{pct:.2f}",
            "weekly_conviction_score": score["weekly_conviction_score"],
            "recommendation_label": recommendations[ticker]["recommendation_label"],
            "hold_case": "Consider holding through the next review only if the thesis remains intact and the concentration exception is consciously accepted.",
            "trim_case": "Consider a trim review because the current weight is above 8%; compare light, 30% sleeve, 8% cap, 6% cap, and whole-share scenarios.",
            "wait_case": "Wait until the scheduled review if no material thesis, earnings, news, or concentration decision has changed.",
            "evidence_needed_before_action": "Fresh public price, current thesis check, material filing or company-news review, tax and lot implications, and fractional-share availability.",
            "next_review_date": next_review,
            "thesis_checks": position["invalidation_rule"],
            "concentration_checks": f"Current {pct:.2f}% versus 6% default, 8% hard cap, and 30% total active-sleeve target.",
            "earnings_news_checks": "Review the latest official filing, earnings release, guidance change, governance issue, and material company announcement.",
            "human_decision_needed": "yes", "automatic_action_allowed": "no",
        })
    write_csv(CHECKLIST, checklist_rows, CHECKLIST_FIELDS)

    trigger_rows: list[dict[str, str]] = []
    trigger_id = 1
    for position in positions:
        ticker = position["ticker"].upper()
        baseline = scores[ticker]["weekly_conviction_score"]
        entries = [
            ("thesis_deterioration", "A material customer, product, competitive, governance, or business-quality change weakens the documented thesis.", "Reassess hold versus trim review; use exit review only if the thesis is materially impaired.", "event_review"),
            ("earnings_risk", "Official earnings, guidance, filing, or material news changes the expected earnings path.", "Refresh the evidence packet and reconsider the weekly label.", "event_review"),
            ("score_drop", "Weekly conviction score falls by at least 1.0 point or below 5.5.", "Review which score component changed before considering a different label.", "next_weekly_review"),
            ("concentration_still_above_cap", "Position remains above 8% at the next review.", "Compare the scenario table again and document the manual decision.", "next_weekly_review"),
            ("public_market_data_missing", "Reference price or public market data is unavailable or stale.", "Pause scenario use until current public data is independently confirmed.", "before_any_decision"),
            ("price_gap_up_down", "Public price gaps at least 8% from the prior close or weekly reference.", "Review the cause and updated concentration; do not react to price movement alone.", "event_review"),
        ]
        for category, condition, response, urgency in entries:
            trigger_rows.append({
                "trigger_id": str(trigger_id), "ticker_or_portfolio": ticker, "trigger_category": category,
                "condition_to_review": condition, "current_baseline": f"score={baseline}; position_pct={position['position_pct']}",
                "review_response": response, "urgency": urgency, "next_review_date": next_review,
                "human_decision_needed": "yes", "automatic_action_allowed": "no",
            })
            trigger_id += 1
    portfolio_entries = [
        ("active_sleeve_still_above_target", "Combined active sleeve remains above 30%.", "Keep new sizing reviews constrained and revisit concentration scenarios.", "active_sleeve=47.34%; target=30.00%"),
        ("new_eligible_candidates_appear", "One or two eligible candidates appear in next week's research.", "Review funding source and portfolio fit before considering any new allocation.", "current_eligible_candidates=0"),
    ]
    for category, condition, response, baseline in portfolio_entries:
        trigger_rows.append({
            "trigger_id": str(trigger_id), "ticker_or_portfolio": "PORTFOLIO", "trigger_category": category,
            "condition_to_review": condition, "current_baseline": baseline, "review_response": response,
            "urgency": "next_weekly_review", "next_review_date": next_review,
            "human_decision_needed": "yes", "automatic_action_allowed": "no",
        })
        trigger_id += 1
    write_csv(TRIGGERS, trigger_rows, TRIGGER_FIELDS)

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in scenarios:
        grouped.setdefault(row["scenario_id"], []).append(row)
    scenario_summary = []
    for scenario_id, group in sorted(grouped.items(), key=lambda item: int(item[1][0]["scenario_order"])):
        scenario_summary.append({
            "scenario_id": scenario_id,
            "sleeve": group[0]["scenario_total_sleeve_pct"],
            "cash": group[0]["scenario_total_cash_released"],
            "iot": next(row for row in group if row["ticker"] == "IOT"),
            "rbrk": next(row for row in group if row["ticker"] == "RBRK"),
        })

    lines = [
        "# Phase 5R-C5T Manual Action Plan", "", f"Generated: `{timestamp()}`", "",
        "## Decision Frame", "",
        "This planner compares hold, wait, and trim-review scenarios for independent human review. It does not change positions. Current company evidence remains constructive, while concentration remains the controlling portfolio risk.", "",
        "- Account-value assumption: `1000.00 USD` from current local position notes.",
        "- Current sleeve: `47.34%`.", "- Current positions: `IOT 29.59%`, `RBRK 17.75%`.",
        f"- Next scheduled review: `{next_review}`.", "",
        "## Scenario Comparison", "",
        "| Scenario | IOT Hold / Trim Shares | RBRK Hold / Trim Shares | Resulting Sleeve | Estimated Cash Released |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in scenario_summary:
        lines.append(
            f"| {item['scenario_id']} | {item['iot']['approximate_shares_to_hold']} / {item['iot']['approximate_shares_to_trim']} | "
            f"{item['rbrk']['approximate_shares_to_hold']} / {item['rbrk']['approximate_shares_to_trim']} | "
            f"{item['sleeve']}% | ${item['cash']} |"
        )
    lines.extend(["", "## Whole-Share Constraint", "",
                  "At the current reference prices, two whole IOT shares are about 7.40% of the assumed account. One whole RBRK share is about 8.88%, so retaining one RBRK share cannot satisfy the 8% cap without fractional shares or a higher account value.", "",
                  "## Hold, Trim Review, Or Wait", ""])
    for row in checklist_rows:
        lines.extend([f"### {row['ticker']}", "", f"- Hold case: {row['hold_case']}", f"- Trim case: {row['trim_case']}", f"- Wait case: {row['wait_case']}", f"- Evidence needed: {row['evidence_needed_before_action']}", ""])
    lines.extend(["## Next-Review Checklist", "",
                  "- Reconfirm both theses from current official evidence.",
                  "- Refresh public reference prices and recalculate actual weights.",
                  "- Confirm whether fractional shares are available.",
                  "- Review tax, lot, and account-specific implications independently.",
                  "- Recheck the 8% single-stock cap and 30% active-sleeve target.",
                  "- Check whether any new eligible candidate changes the funding and diversification discussion.",
                  "- Record the manual decision: hold, light trim review, policy-target trim review, or wait.", "",
                  "## Boundary", "",
                  "Every scenario requires a manual decision. The files provide estimates for research planning only and cannot alter a brokerage account."])
    PLAN.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report_lines = [
        "# Phase 5R-C5T Manual Action Report", "", f"Generated: `{timestamp()}`", "",
        "## Output Summary", "", f"- Current positions reviewed: `{len(positions)}`.",
        f"- Scenarios compared: `{len(grouped)}`.", f"- Scenario rows: `{len(scenarios)}`.",
        f"- Next-review triggers: `{len(trigger_rows)}`.", "- Every scenario and trigger requires a human decision.", "",
        "## Practical Finding", "", "The whole-share scenario can place IOT below the 8% hard cap while retaining two shares. Retaining one whole RBRK share remains above the cap under the 1000 USD assumption.", "",
        "## Boundary", "", "C5T generated local planning artifacts only. It did not access a broker, change positions, send email, activate a scheduler, read archived holdings, or modify SMTP configuration.",
    ]
    RESEARCH_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    append_log(scenarios[0]["account_value_usd"], len(positions), len(grouped), len(scenarios))
    print(f"Created C5T manual action plan: scenarios={len(grouped)} triggers={len(trigger_rows)}")


if __name__ == "__main__":
    main()
