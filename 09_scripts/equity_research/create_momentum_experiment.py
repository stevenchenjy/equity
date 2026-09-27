#!/usr/bin/env python3
"""Append private momentum observations and forward evaluations; never send or trade."""
import argparse
from pathlib import Path
from daily_common import ROOT, atomic_write_json, now_et
from momentum_experiment import OUTPUT, failure_reason, run, run_attempt_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="Private rehearsal directory; inputs are read from --root")
    args = parser.parse_args()
    output = args.output or args.root / OUTPUT
    try:
        report = run(args.root, now_et(), args.output)
    except Exception as exc:
        try:
            counts = run_attempt_summary(output)
        except Exception:
            counts = {"status": "unverified", "reason_code": "run_history_unavailable"}
        atomic_write_json(output / "status.json", {"status": "failed", "generated_at": now_et().isoformat(),
            "reason": failure_reason(exc), "run_attempt_history": counts,
            "prior_report_is_historical": True, "automatic_action_allowed": False})
        print("momentum_experiment_failed=true prior_records_preserved=true email_sent=false")
        return 1
    atomic_write_json(output / "status.json", {
        "status": "experimental", "generated_at": report["generated_at"], "market_session": report["market_session"],
        "observations": report["summary"]["observations"], "outcomes": report["summary"]["outcomes"],
        "run_attempt_id": report["run_attempt_id"], "run_attempt_history": report["run_attempt_history"],
        "incremental_value_established": False, "automatic_action_allowed": False})
    print(f"momentum_experiment_created=true observations={report['summary']['observations']} outcomes={report['summary']['outcomes']} email_sent=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
