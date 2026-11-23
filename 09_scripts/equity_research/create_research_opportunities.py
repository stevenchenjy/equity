#!/usr/bin/env python3
"""Run research-only intake or bounded objective work; never send or trade."""
import argparse
from pathlib import Path
from daily_common import ROOT, now_et, atomic_write_json, ExclusiveFileLock
from opportunity_contract import BASE_REL
from research_opportunities import intake, objective


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--stage", choices=("intake", "objective"), default="intake")
    parser.add_argument("--refresh", action="store_true", help="Explicit bounded public SEC requests for noncanonical issuer research only")
    parser.add_argument("--defer-attention-view", action="store_true",
        help="Coordinated full pipeline only: retain backlog preflight and require its later final view")
    args = parser.parse_args()
    if args.defer_attention_view and args.stage != "objective":
        parser.error("--defer-attention-view requires --stage objective")
    # Serialize both markers and journal work. A second manual/scheduled
    # invocation must not overwrite the first invocation's completion marker.
    try:
        with ExclusiveFileLock(args.root / BASE_REL / "stage.lock"):
            return run_stage(args.root, args.stage, allow_network=args.refresh,
                             defer_attention_view=args.defer_attention_view)
    except RuntimeError:
        print("research_opportunities=busy prior_run_marker_preserved=true capital_authority=false email_sent=false")
        return 3


def run_stage(root: Path, stage: str, *, allow_network: bool = False,
              defer_attention_view: bool = False) -> int:
    if defer_attention_view and stage != "objective":
        raise ValueError("attention_view_deferral_requires_objective_stage")
    marker = root / BASE_REL / ("last_"+stage+"_run.json")
    started = now_et()
    atomic_write_json(marker, {"started_at": started.isoformat(), "exit_code": None, "stage": stage})
    try:
        report = (intake(root, current=now_et()) if stage == "intake"
            else objective(root, current=now_et(), allow_network=allow_network, clock=now_et,
                           defer_attention_view=defer_attention_view))
    except Exception:
        atomic_write_json(marker, {"started_at": started.isoformat(), "completed_at": now_et().isoformat(),
            "exit_code": 1, "stage": stage, "reason_code": "research_stage_failed_prior_journal_preserved"})
        print("research_opportunities=failed prior_journal_preserved=true capital_authority=false email_sent=false")
        return 1
    atomic_write_json(marker, {"started_at": started.isoformat(), "completed_at": now_et().isoformat(),
        "exit_code": 0, "stage": stage, "report_hash": report["report_hash"],
        **({"attention_view_deferred": True, "attention_report_hash": report["report_hash"]}
           if defer_attention_view else {})})
    print(f"research_opportunities=ready stage={stage} queue={report['metrics']['research_queue_size']} "
        f"network_requests={report['metrics']['network_requests']} capital_authority=false email_sent=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
