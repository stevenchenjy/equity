#!/usr/bin/env python3
"""Complete bounded cached official research data; preserve analyst gates."""
import argparse
from pathlib import Path
from daily_common import ROOT, now_et, atomic_write_json
from active_config import load_active_config
from research_backlog import REPORT_REL, run, recompose_final_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--max-tickers", type=int,
        help="Override the configured objective work budget (1-10 issuers); never changes eligibility.")
    parser.add_argument("--apply-objective-updates", action="store_true",
        help="Explicitly publish verified additive numeric improvements and matching SEC receipts; same root only.")
    parser.add_argument("--recompose-only", action="store_true",
        help="Refresh gaps and priority from final admitted inputs; no objective work or canonical writes.")
    args = parser.parse_args()
    if args.recompose_only and (args.apply_objective_updates or args.max_tickers is not None or args.input_root.resolve() != args.output_root.resolve()):
        parser.error("--recompose-only requires one root and no objective work flags")
    max_tickers = args.max_tickers
    if max_tickers is None:
        config = load_active_config(args.input_root / "00_project_control/active_production_config.json")
        max_tickers = config["workflow"].get("objective_research_max_tickers", 3)
    started = now_et()
    marker_path = args.output_root / ("08_reviews/research_backlog.local/last_view_run.json" if args.recompose_only else "08_reviews/research_backlog.local/last_run.json")
    marker = {"schema_version": "equity_research_backlog_run_v1", "started_at": started.isoformat(),
        "automatic_action_allowed": False}
    try:
        report = (recompose_final_view(args.output_root, started) if args.recompose_only else
            run(input_root=args.input_root, output_root=args.output_root, current=started,
                max_tickers=max_tickers, apply_objective_updates=args.apply_objective_updates))
    except (ValueError, KeyError, TypeError, OSError):
        atomic_write_json(marker_path, {**marker, "completed_at": now_et().isoformat(), "exit_code": 1,
            "status": "failed", "reason_code": "research_backlog_failed"})
        print("research_backlog_failed=true prior_history_preserved=true automatic_action_allowed=false")
        return 1
    atomic_write_json(marker_path, {**marker, "completed_at": now_et().isoformat(), "exit_code": 0,
        "status": "success", "reason_code": "final_view_recomposed_without_objective_work" if args.recompose_only else "bounded_official_cache_research_completed", "report_hash": report["report_hash"]})
    if args.recompose_only:
        print("research_backlog_recomposed=true additional_objective_attempts=0 canonical_writes=0 automatic_action_allowed=false")
        return 0
    print(f"research_backlog_created=true objective_dossiers_completed={report['objective_dossiers_completed']} "
        f"financial_fields_completed={report['financial_fields_completed']} canonical_numeric_updates={report['canonical_numeric_updates']} "
        "network_requests=0 automatic_action_allowed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
