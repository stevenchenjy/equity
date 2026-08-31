from __future__ import annotations

import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
BRIEF_DIR = ROOT / "07_automation" / "email_briefs"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
SCHEDULER_DIR = ROOT / "07_automation" / "scheduler"

ACTIVE_STATE = CONTROL_DIR / "active_decision_state.yaml"
ACCOUNT_STATE = POSITION_DIR / "current_account_state.local.json"
SUMMARY = POSITION_DIR / "phase5r_c9_current_portfolio_summary.csv"
WEIGHTS = POSITION_DIR / "phase5r_c9_dynamic_position_weights.csv"
ACTIONS = POSITION_DIR / "phase5r_c9_exact_action_plan.csv"
CASH_PLANS = POSITION_DIR / "phase5r_c9_cash_deployment_plan.csv"
NEW_RECOMMENDATIONS = RESEARCH_DIR / "phase5r_c9_new_candidate_recommendations.csv"
C9_MEMO = RESEARCH_DIR / "phase5r_c9_account_aware_memo.md"
WEEKLY_SUMMARY = POSITION_DIR / "phase5r_c9_weekly_decision_summary.md"
C9B_EXECUTIONS = ROOT / "06_execution_records" / "manual_executions.local.csv"
C9B_PRICE_ACTIONS = POSITION_DIR / "phase5r_c9b_price_aware_action_plan.csv"
C9_INHIBIT = SCHEDULER_DIR / "phase5r_c9_maintenance_inhibit.local.json"

SUBJECT_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_subject.txt"
TEXT_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_body.txt"
HTML_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_body.html"
METADATA_PATH = BRIEF_DIR / "phase5r_c6_email_metadata.csv"
PREVIEW_PATH = REVIEWS_DIR / "latest_phase5r_c6_weekly_email_preview.md"
REPORT_PATH = RESEARCH_DIR / "phase5r_c6_weekly_email_report.md"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c6_run_log.csv"

METADATA_FIELDS = [
    "generated_at",
    "brief_date",
    "primary_scenario",
    "current_position_count",
    "position_review_count",
    "trim_review_count",
    "position_labels",
    "new_eligible_count",
    "eligible_tickers",
    "wait_for_pullback_tickers",
    "watch_only_tickers",
    "reject_count",
    "other_candidate_labels",
    "backup_scenarios",
    "next_review_date",
    "email_subject",
    "send_allowed",
    "delivery_phase",
    "source_paths",
]
LOG_FIELDS = [
    "timestamp",
    "phase",
    "script_name",
    "action",
    "mode",
    "status",
    "subject",
    "smtp_username",
    "recipient_email",
    "sent",
    "message_count",
    "input_paths",
    "output_paths",
    "error_type",
    "error_message_redacted",
    "broker_used",
    "scheduler_used",
    "archived_legacy_used",
    "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid C6 JSON input: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"C6 JSON input must be an object: {path.name}")
    return value


def append_log(inputs: list[Path], outputs: list[Path], subject: str, scenario: str) -> None:
    exists = RUN_LOG.exists() and RUN_LOG.stat().st_size > 0
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp(),
                "phase": "phase5r_c6",
                "script_name": Path(__file__).name,
                "action": "compose_c9b_execution_aware_weekly_email",
                "mode": "compose",
                "status": "complete",
                "subject": subject,
                "smtp_username": "",
                "recipient_email": "",
                "sent": "no",
                "message_count": "0",
                "input_paths": ";".join(str(path.relative_to(ROOT)) for path in inputs),
                "output_paths": ";".join(str(path.relative_to(ROOT)) for path in outputs),
                "error_type": "",
                "error_message_redacted": "",
                "broker_used": "no",
                "scheduler_used": "no",
                "archived_legacy_used": "no",
                "safety_notes": (
                    f"c9_account_aware=yes; c9b_execution_aware=yes; primary_scenario={scenario}; credentials_read=no; "
                    "stored_position_pct_current_truth=no; maintenance_inhibit_required=yes; fill_price_invented=no"
                ),
            }
        )


def main() -> None:
    inputs = [
        ACTIVE_STATE,
        ACCOUNT_STATE,
        SUMMARY,
        WEIGHTS,
        ACTIONS,
        CASH_PLANS,
        NEW_RECOMMENDATIONS,
        C9_MEMO,
        WEEKLY_SUMMARY,
        C9B_EXECUTIONS,
        C9B_PRICE_ACTIONS,
        C9_INHIBIT,
    ]
    for path in inputs:
        if not path.exists():
            raise FileNotFoundError(f"required C9 C6 input missing: {path.relative_to(ROOT)}")
    active = load_json(ACTIVE_STATE)
    scenario = str(active.get("primary_decision", ""))
    if (
        active.get("schema_version") != "phase5r_c9_v1"
        or active.get("current_workflow") != "weekly_conviction"
        or active.get("active_pipeline") != "phase5r_c7"
        or scenario != "c9_account_aware_manual_review"
        or active.get("email_delivery_allowed_from") != "phase5r_c7_only"
        or active.get("broker_connection_allowed") != "no"
        or active.get("order_code_allowed") != "no"
        or active.get("manual_execution_only") != "yes"
    ):
        raise ValueError("active decision state does not authorize C9 C6 composition")
    inhibit = load_json(C9_INHIBIT)
    if inhibit.get("active") is not True or inhibit.get("allowed_pipeline") != "none":
        raise ValueError("C9 maintenance inhibit must remain active during C6 composition")
    account = load_json(ACCOUNT_STATE)
    summary_rows = read_csv(SUMMARY)
    if len(summary_rows) != 1:
        raise ValueError("C9 summary must contain one row")
    summary = summary_rows[0]
    account_total = float(account.get("account_total_value", 0))
    if account_total <= 0 or abs(float(summary["account_total_value"]) - account_total) > 0.01:
        raise ValueError("C9 C6 account total must match the canonical account state")
    weights = read_csv(WEIGHTS)
    actions = read_csv(ACTIONS)
    if {row["ticker"] for row in weights} != {row["ticker"] for row in actions}:
        raise ValueError("C9 weights and actions must cover the same current tickers")
    cash_plans = read_csv(CASH_PLANS)
    executions = read_csv(C9B_EXECUTIONS)
    price_actions = read_csv(C9B_PRICE_ACTIONS)
    price_by_ticker = {row["ticker"]: row for row in price_actions}
    if set(price_by_ticker) != {row["ticker"] for row in actions}:
        raise ValueError("C9B price-aware actions must cover every current-position action")
    execution_by_ticker = {row["ticker"]: row for row in executions}
    new_rows = read_csv(NEW_RECOMMENDATIONS)
    eligible = [
        row
        for row in new_rows
        if row["asset_role"] == "individual_stock_candidate" and row["eligibility_label"] == "eligible_buy_review"
    ]
    if eligible:
        raise ValueError("C9 C6 refuses unexpected individual-stock eligibility without a separate verified path")
    planned_review_dates = {row["planned_review_date"] for row in cash_plans}
    if len(planned_review_dates) != 1:
        raise ValueError("C9 cash plans must share one review date")
    next_review = planned_review_dates.pop()

    generated_at = timestamp()
    brief_date = generated_at[:10]
    subject = f"Weekly AI Equity Account Review — {brief_date} — {len(actions)} Position Reviews / 0 New Eligible"
    action_lines = [
        f"- {row['ticker']}: ${float(row['current_value']):.2f}, {float(row['current_weight_pct']):.4f}%; "
        f"label {row['current_label']}; action {row['recommended_action']}; target {float(row['target_weight_pct']):.4f}% / "
        f"${float(row['target_value']):.2f}; whole shares to change {row['whole_shares_to_change']}; resulting weight "
        f"{float(row['resulting_weight_pct']):.4f}%. Reason: {row['reason']}"
        for row in actions
    ]
    price_lines = []
    for row in actions:
        ticker = row["ticker"]
        price_row = price_by_ticker[ticker]
        execution_status = execution_by_ticker.get(ticker, {}).get("order_status", "no_execution_record")
        preferred_condition = (
            price_row["minimum_sell_price_or_condition"]
            if not price_row["minimum_sell_price_or_condition"].startswith("not_applicable")
            else price_row["maximum_buy_price_or_condition"]
        )
        price_lines.append(
            f"- {ticker}: shares under review {price_row['shares_under_review']}; target shares {price_row['target_shares']}; "
            f"reference ${float(price_row['reference_price']):.2f} at {price_row['reference_price_timestamp']}; "
            f"preferred condition {preferred_condition}; maximum slippage {price_row['maximum_slippage_pct']}%; "
            f"order-style review {price_row['suggested_order_style']}; resulting reference weight "
            f"{float(price_row['target_weight_after']):.4f}%; fill confirmation status {execution_status}."
        )
    core_options = []
    for plan_id in ("no_deployment_until_next_review", "three_tranche_core_plan", "partial_core_plus_cash_reserve"):
        rows = [row for row in cash_plans if row["plan_id"] == plan_id]
        amount = sum(float(row["planned_amount"]) for row in rows)
        status = rows[0]["status"]
        core_options.append(f"- {plan_id}: planned total ${amount:.2f}; status {status}. {rows[0]['reason']}")
    watch_only = [row["ticker"] for row in new_rows if row["asset_role"] == "individual_stock_candidate"]
    text_lines = [
        "1. Header",
        f"Weekly AI Equity Account Review - {brief_date}",
        "Low-attention, account-aware research planning for independent human review.",
        "",
        "2. This Week's Main Decision",
        "Use recalculated current weights and the C9B execution-intake state. Do not change canonical shares, cash, or account total while the IOT record is pending; reconcile only after an actual fill is confirmed.",
        f"Primary scenario: {scenario}.",
        f"Next review: {next_review}.",
        "",
        "3. Account State",
        f"- Account total: ${float(summary['account_total_value']):.2f}.",
        f"- Current cash: ${float(summary['cash_available']):.2f} ({float(summary['current_cash_pct']):.4f}%).",
        f"- Current active-stock value: ${float(summary['current_active_stock_value']):.2f} ({float(summary['current_active_stock_weight_pct']):.4f}%).",
        f"- Current core value: ${float(summary['current_core_value']):.2f} ({float(summary['current_core_weight_pct']):.4f}%).",
        f"- Account reconciliation: {summary['reconciliation_status']}; difference ${float(summary['reconciliation_difference']):.2f}.",
        "",
        "4. Exact Current-Position Review",
        *action_lines,
        "- No add is recommended for IOT or RBRK this week.",
        "",
        "5. Execution and Price Framework",
        *price_lines,
        "- Reference prices and review tolerances are not assumed fills. Limit orders may not execute or may fill only partially.",
        "",
        "6. Core and Cash-Deployment Approaches",
        *core_options,
        "- SPY is a separate broad-market core candidate, not an individual momentum-stock candidate.",
        "",
        "7. New Individual-Stock Review",
        "- Eligible individual-stock purchase reviews: 0.",
        f"- Waiting for complete upside and reward-to-risk evidence: {', '.join(watch_only) if watch_only else 'none'}.",
        "",
        "8. Safety Boundary",
        "- Every action requires independent human confirmation.",
        "- Automatic action is prohibited.",
        "- C9 maintenance remains active; no cash tranche is currently actionable.",
        "- This composer did not read SMTP configuration and did not send email.",
        "- No broker or archived holding input is used.",
    ]
    text_body = "\n".join(text_lines) + "\n"
    action_html = "".join(f"<li>{html.escape(line[2:])}</li>" for line in action_lines)
    price_html = "".join(f"<li>{html.escape(line[2:])}</li>" for line in price_lines)
    core_html = "".join(f"<li>{html.escape(line[2:])}</li>" for line in core_options)
    html_body = "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset=\"utf-8\"><title>Weekly AI Equity Account Review</title>",
            "<style>body{font-family:Arial,sans-serif;line-height:1.45;max-width:760px;margin:20px auto;padding:0 16px;color:#202124}h1{font-size:24px}h2{font-size:18px;margin-top:24px}.decision{border-left:4px solid #1a73e8;padding:12px;background:#f7f9fc}</style></head><body>",
            f"<h1>Weekly AI Equity Account Review - {html.escape(brief_date)}</h1>",
            f"<div class=\"decision\"><strong>Primary scenario: {html.escape(scenario)}.</strong><br>Next review: {html.escape(next_review)}.</div>",
            "<h2>Account State</h2>",
            f"<p>Account total ${float(summary['account_total_value']):.2f}; cash ${float(summary['cash_available']):.2f} ({float(summary['current_cash_pct']):.4f}%); active stocks ${float(summary['current_active_stock_value']):.2f} ({float(summary['current_active_stock_weight_pct']):.4f}%).</p>",
            f"<h2>Exact Position Review</h2><ul>{action_html}</ul>",
            f"<h2>Execution and Price Framework</h2><ul>{price_html}</ul><p>Reference prices are not assumed fills. Limit orders may not execute or may fill only partially.</p>",
            f"<h2>Core and Cash Options</h2><ul>{core_html}</ul>",
            "<h2>New Individual Stocks</h2><p>Zero eligible purchase reviews; missing upside and reward-to-risk evidence was not invented.</p>",
            "<h2>Boundary</h2><p>Human confirmation required. Automatic action prohibited. Maintenance remains active. No email was sent by composition.</p>",
            "</body></html>",
        ]
    ) + "\n"

    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    SUBJECT_PATH.write_text(subject + "\n", encoding="utf-8")
    TEXT_PATH.write_text(text_body, encoding="utf-8")
    HTML_PATH.write_text(html_body, encoding="utf-8")
    position_labels = ";".join(f"{row['ticker']}={row['current_label']}" for row in actions)
    metadata = {
        "generated_at": generated_at,
        "brief_date": brief_date,
        "primary_scenario": scenario,
        "current_position_count": str(len(weights)),
        "position_review_count": str(len(actions)),
        "trim_review_count": str(sum(row["recommended_action"] == "trim_specific_shares_review" for row in actions)),
        "position_labels": position_labels,
        "new_eligible_count": "0",
        "eligible_tickers": "",
        "wait_for_pullback_tickers": "",
        "watch_only_tickers": ";".join(watch_only),
        "reject_count": "0",
        "other_candidate_labels": "SPY=core_allocation_candidate",
        "backup_scenarios": "three_tranche_core_plan;partial_core_plus_cash_reserve",
        "next_review_date": next_review,
        "email_subject": subject,
        "send_allowed": "manual_command_only",
        "delivery_phase": "phase5r_c6_weekly_manual_send",
        "source_paths": ";".join(str(path.relative_to(ROOT)) for path in inputs),
    }
    write_csv(METADATA_PATH, [metadata], METADATA_FIELDS)
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.write_text(
        "# Latest Phase 5R-C6 Weekly Email Preview\n\n"
        f"Subject: `{subject}`\n\nLocal preview only. No email was sent.\n\n```text\n{text_body.rstrip()}\n```\n",
        encoding="utf-8",
    )
    execution_states = ";".join(f"{row['ticker']}={row['order_status']}" for row in executions)
    REPORT_PATH.write_text(
        "# Phase 5R-C6 Weekly Email Report\n\n"
        f"Generated: `{generated_at}`\n\n"
        "## C9/C9B Composition\n\n"
        f"- Primary scenario: `{scenario}`.\n"
        f"- Account total: `{float(summary['account_total_value']):.2f}`.\n"
        f"- Current position reviews: `{len(actions)}`.\n"
        "- New eligible individual stocks: `0`.\n"
        f"- Next review date: `{next_review}`.\n"
        f"- Execution states: `{execution_states}`.\n"
        "- Delivery during composition: `none`.\n\n"
        "## Boundary\n\nC6 used C9 account-aware and C9B execution/price-reference outputs. It did not infer a fill, read SMTP configuration, send email, access a broker, or use archived holdings.\n",
        encoding="utf-8",
    )
    outputs = [SUBJECT_PATH, TEXT_PATH, HTML_PATH, METADATA_PATH, PREVIEW_PATH, REPORT_PATH]
    append_log(inputs, outputs, subject, scenario)
    print(f"Created C9-compatible C6 weekly brief; positions={len(actions)}; eligible=0; sent=no")


if __name__ == "__main__":
    main()
