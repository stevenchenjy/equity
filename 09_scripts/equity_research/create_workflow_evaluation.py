#!/usr/bin/env python3
"""Create a private operational/outcome/performance report, or preview confirmed records."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from daily_common import (DAILY_DECISION_JSON_PATH, DAILY_RUN_LOG_PATH, DAILY_SCHEDULER_STATE_PATH, ROOT,
                          atomic_write_json, atomic_write_text, iso_now, now_et, read_csv, read_json)
from track_recommendation_outcomes import SNAPSHOT_PATH, OUTCOME_PATH, HISTORY_PATH
from workflow_evaluation import (EVALUATION_JSON_PATH, EVALUATION_MD_PATH, PERFORMANCE_PATH, REFRESH_HISTORY_PATH,
    load_performance_records, operational_summary, outcome_coverage, performance_summary,
    read_jsonl, record_performance, thesis_review_summary, empty_thesis_review)
from thesis_evidence import STORE_REL


def render_thesis_review(review: dict) -> list[str]:
    """One learning section in the existing evaluation, with no parallel report."""
    def cell(value: object) -> str:
        return " ".join(str(value).split()).replace("|", "\\|")

    lines = ["", "## Thesis-based learning", "",
        f"Status: **{review['status']}**. {review['recorded_versions']} recorded versions; {review['distinct_reasoning_cases']} distinct reasoning cases after unchanged restamps are grouped.",
        f"Cases with a recorded method: {review['recorded_method_cases']}; with substantive prospective reasoning: {review['prospective_method_cases']}. Assessed price conditions: {review['price_conditions_assessed_cases']}; assessed loss paths: {review['loss_paths_assessed_cases']}; falsifiable differences: {review['falsifiable_difference_cases']}.",
        f"Cases with a recorded retrospective: {review['retrospective_cases']}; with later business facts assessed: {review['business_evidence_cases']}; with an original-version price path: {review['price_observed_cases']}.",
        "Unknown templates do not count as substantive reasoning or supported decision process; coverage does not establish investment skill."]
    if review["validation_errors"]:
        lines.extend(["", "Validation gaps: " + "; ".join(cell(value) for value in review["validation_errors"])])
    if review["adoption_queue"]:
        lines.extend(["", "Use the next existing company review to close these gaps; held companies come first.", "",
            "| Company | Priority | Pending method | Next evidence |", "|---|---|---|---|"])
        focused = [row for row in review["adoption_queue"] if row["priority"] == "held"] or review["adoption_queue"][:5]
        for row in focused:
            lines.append("| " + " | ".join(cell(row[key]) for key in ("ticker", "priority", "reason", "next_evidence")) + " |")
        remaining = [row["ticker"] for row in review["adoption_queue"] if row not in focused]
        if remaining:
            lines.extend(["", "Other existing company reviews with method gaps: " + ", ".join(remaining)
                + ". Their full pending reasons remain in this evaluation's JSON; reuse their existing review queues."])
    reviewed = [row for row in review["cases"] if row["retrospective_review_id"]]
    due = sorted((row for row in review["cases"] if row["prospective_method_recorded"] and row["scheduled_review_due"]),
        key=lambda row: (row["position_scope"] != "held", row["ticker"], row["original_version"]))
    if due:
        lines.extend(["", f"{len(due)} substantive original theses are due for a retrospective; assess the next evidence even when the outcome remains unobservable."])
        for row in due[:5]:
            lines.append(f"- {row['ticker']} v{row['original_version']} ({row['position_scope']}): {cell(row['next_evidence'])}")
        if len(due) > 5:
            lines.append(f"- {len(due) - 5} additional pending cases remain in this evaluation's JSON.")
    if reviewed:
        lines.extend(["", "| Original thesis | Process judgment | Business outcome | Original-version price observation | Next evidence / lesson |",
            "|---|---|---|---|---|"])
        for row in reviewed:
            prices = row["price_observations"]
            observed = prices["horizons"][-1] if prices["horizons"] else None
            price_text = (f"{observed['horizon_sessions']} sessions: {observed['absolute_return_pct']}% to {observed['evaluation_session']}"
                if observed else prices["status"])
            lines.append("| " + " | ".join(cell(value) for value in (f"{row['ticker']} v{row['original_version']}",
                row["decision_process"]["assessment"] + ": " + row["decision_process"]["rationale"],
                row["business_outcome"]["status"] + ": " + row["business_outcome"]["assessment"], price_text,
                row["next_evidence"] + " / " + row["lesson"])) + " |")
    else:
        lines.extend(["", "No source-bound thesis retrospective has been recorded. Existing price paths alone do not establish business realization or decision quality."])
    lines.extend(["", f"Shared exposure coverage: **{review['shared_exposure_coverage']}**. Groups describe the latest researched companies; held membership is shown separately. Groups require the same assessed tag on at least two companies. Unpaired or missing tags leave diversification unassessed."])
    for row in review["shared_exposures"]:
        mechanisms = "; ".join(f"{member['ticker']} ({member['position_scope']}): {member['mechanism']}" for member in row["mechanisms"])
        lines.append(f"- {cell(row['driver'])}: {cell(', '.join(row['tickers']))}. {cell(mechanisms)}")
    lines.extend(["", *review["limitations"]])
    return lines


def render(report: dict) -> str:
    ops, ideas, performance = report["operations"], report["recommendation_outcomes"], report["portfolio_performance"]
    lines = ["# Workflow reliability and results", "", f"Generated: {report['generated_at']}", "",
             "## Availability", "",
             f"Engineering readiness target: {ops['ready_deadline_et']} ET after the provider publication retry window.",
             f"Retained window: {ops['calendar_cycles_observed_or_missing']} calendar cycles, including {ops['exchange_sessions_in_window']} exchange sessions.",
             f"Due cycles: {ops['due_calendar_cycles']}; on time: {ops['on_time_cycles']}; late: {ops['late_cycles']}; eventually ready: {ops['eventually_ready_cycles']}; unknown/missing: {ops['unknown_or_missing_cycles']}.",
             "The denominator is calendar research cycles, including weekends; it is not a count of market sessions. Missing days remain visible.",
             f"Timed refreshes: {ops['timed_runs']}; median seconds: {ops['median_refresh_seconds'] if ops['median_refresh_seconds'] is not None else 'unavailable'}.",
             ops["historical_timing_limit"], "", "| Step | Timed observations | Median seconds | Maximum seconds |", "|---|---:|---:|---:|"]
    for name, row in ops["step_timing"].items():
        lines.append(f"| {name} | {row['observations']} | {row['median_seconds']:.2f} | {row['maximum_seconds']:.2f} |")
    lines.extend(["", "Observed runtime failure reasons: " + (json.dumps(ops["failure_reason_counts"], sort_keys=True) if ops["failure_reason_counts"] else "none in available records"), "",
                  "Unresolved delivery terminals: " + (", ".join(f"{r['cycle_date']}: {r['delivery_terminal_reason']}" for r in ops["cycles"] if r["delivery_terminal_reason"]) or "none recorded"),
                  "", "## Recommendation follow-through", "",
                  f"{ideas['snapshot_rows']} immutable snapshots; {ideas['unique_origin_observations']} unique ticker/origin observations; {ideas['unique_matured_observations']} with at least one matured horizon.",
                  f"Plan-linked snapshots: {ideas['plan_linked_snapshots']}; thesis-linked: {ideas['thesis_linked_snapshots']}. Old unlinked snapshots remain unchanged.",
                  f"Distinct material instruction versions: {ideas['unique_material_instruction_versions']}. Completed review meetings are unmeasured, not inferred from groups of ten.",
                  f"Snapshots without an available forward origin: {ideas['snapshots_without_available_forward_origin']}.", "",
                  "| Horizon sessions | Matured observations | Pending/missing |", "|---:|---:|---:|"])
    for row in ideas["horizons"]:
        lines.append(f"| {row['horizon_sessions']} | {row['matured']} | {row['pending_or_missing']} |")
    lines.extend(["", *ideas["limitations"]])
    if "thesis_review" in report:
        lines.extend(render_thesis_review(report["thesis_review"]))
    lines.extend(["", "## Actual portfolio performance", "",
                  f"Status: **{performance['status']}**. Confirmed actual NAV observations: {performance.get('actual_nav_observations', 0)}; usable reviewed intervals: {performance.get('ready_intervals', 0)}.",
                  "Blockers: " + (", ".join(performance.get("blockers", [])) or "none for the individually listed intervals"), ""])
    for row in performance.get("intervals", []):
        lines.append(f"- {row['review_id']}: {row['status']}; return {row['return_pct'] if row['return_pct'] is not None else 'unavailable'}%; blockers {', '.join(row['blockers']) or 'none'}.")
    lines.extend(["", *performance.get("limitations", []), "", "No recommendation, email, account balance, or broker order was changed by this report."])
    return "\n".join(lines) + "\n"


def build_report() -> dict:
    try:
        portfolio = performance_summary(load_performance_records())
    except (ValueError, KeyError, TypeError, OSError):
        portfolio = {"status": "invalid_evidence", "blockers": ["private_performance_ledger_invalid; preserve records and review"],
                     "portfolio_lifetime_return_pct": None}
    snapshots, outcomes = read_jsonl(SNAPSHOT_PATH), read_csv(OUTCOME_PATH)
    try:
        decision = read_json(DAILY_DECISION_JSON_PATH, {})
        thesis = thesis_review_summary(read_json(ROOT / STORE_REL, None), snapshots, outcomes,
            now=now_et(), evidence_root=ROOT,
            held_tickers={row["ticker"] for row in decision.get("held_positions", [])
                if isinstance(row, dict) and row.get("ticker") and row.get("asset_role") != "core_allocation"})
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        thesis = empty_thesis_review()
        thesis.update(status="invalid_evidence", validation_errors=[str(exc)])
    return {"schema_version": "workflow_evaluation_v1", "generated_at": iso_now(),
            "operations": operational_summary(read_json(DAILY_SCHEDULER_STATE_PATH), read_csv(DAILY_RUN_LOG_PATH),
                 read_csv(ROOT / "00_project_control/run_logs/runtime_execution_log.csv"), read_jsonl(REFRESH_HISTORY_PATH), now=now_et()),
            "recommendation_outcomes": outcome_coverage(snapshots, outcomes, read_csv(HISTORY_PATH)),
            "thesis_review": thesis,
            "portfolio_performance": portfolio, "automatic_action_allowed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, help="JSON confirmed observation/flow/interval record; preview unless --apply")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ledger", type=Path, default=PERFORMANCE_PATH)
    args = parser.parse_args()
    if args.apply and not args.record:
        parser.error("--apply requires --record")
    if args.record:
        record = json.loads(args.record.read_text())
        source = Path(record["source_reference"]).expanduser()
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != record.get("source_sha256"):
            raise ValueError("source_reference must be a local evidence file matching its recorded SHA-256")
        print(json.dumps(record_performance(record, path=args.ledger, apply=args.apply), sort_keys=True))
        return 0
    report = build_report()
    atomic_write_json(EVALUATION_JSON_PATH, report)
    atomic_write_text(EVALUATION_MD_PATH, render(report))
    print(f"workflow_evaluation_created=true performance_status={report['portfolio_performance']['status']} broker_connected=false email_sent=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
