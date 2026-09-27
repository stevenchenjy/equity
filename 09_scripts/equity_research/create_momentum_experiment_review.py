#!/usr/bin/env python3
"""Publish a local manual-review packet; never promote, send email or trade."""
import argparse
from pathlib import Path

from daily_common import ROOT, atomic_write_json, now_et
from momentum_experiment_review import OUTPUT, SCHEMA, ReviewError, run
from momentum_experiment import OUTPUT as EXPERIMENT_OUTPUT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output or args.root / OUTPUT
    if output.resolve() == (args.root / EXPERIMENT_OUTPUT).resolve():
        print("momentum_manual_review_failed=true reason=review_output_conflicts_with_frozen_experiment email_sent=false trade_placed=false")
        return 2
    try:
        report = run(args.root, now_et(), args.output)
    except Exception as exc:
        reason = (str(exc) if isinstance(exc, ReviewError)
                  else "review_input_missing" if isinstance(exc, FileNotFoundError)
                  else "review_input_invalid" if isinstance(exc, (ValueError, TypeError, KeyError))
                  else "review_io_error" if isinstance(exc, OSError) else "review_internal_error")
        atomic_write_json(output / "status.json", {"schema_version": SCHEMA, "status": "failed",
            "generated_at": now_et().isoformat(), "reason": reason, "prior_report_is_historical": True,
            "ready_for_owner_review": False, "complete_cohorts": 0, "incremental_value_established": False,
            "automatic_action_allowed": False, "automatic_promotion": False, "changes_canonical_eligibility": False})
        print(f"momentum_manual_review_failed=true reason={reason} email_sent=false trade_placed=false")
        return 1
    print(f"momentum_manual_review_created=true status={report['status']} complete_cohorts={report['complete_cohorts']} email_sent=false trade_placed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
