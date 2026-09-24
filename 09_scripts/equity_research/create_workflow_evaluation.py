#!/usr/bin/env python3
"""Create a private operational/outcome/performance report, or preview confirmed records."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from daily_common import (DAILY_RUN_LOG_PATH, DAILY_SCHEDULER_STATE_PATH, ROOT,
                          atomic_write_json, atomic_write_text, iso_now, now_et, read_csv, read_json)
from track_recommendation_outcomes import SNAPSHOT_PATH, OUTCOME_PATH, HISTORY_PATH
from workflow_evaluation import (EVALUATION_JSON_PATH, EVALUATION_MD_PATH, PERFORMANCE_PATH, REFRESH_HISTORY_PATH,
    load_performance_records, operational_summary, outcome_coverage, performance_summary,
    read_jsonl, record_performance)


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
    lines.extend(["", *ideas["limitations"], "", "## Actual portfolio performance", "",
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
    return {"schema_version": "workflow_evaluation_v1", "generated_at": iso_now(),
            "operations": operational_summary(read_json(DAILY_SCHEDULER_STATE_PATH), read_csv(DAILY_RUN_LOG_PATH),
                 read_csv(ROOT / "00_project_control/run_logs/runtime_execution_log.csv"), read_jsonl(REFRESH_HISTORY_PATH), now=now_et()),
            "recommendation_outcomes": outcome_coverage(read_jsonl(SNAPSHOT_PATH), read_csv(OUTCOME_PATH), read_csv(HISTORY_PATH)),
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
