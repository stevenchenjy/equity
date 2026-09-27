#!/usr/bin/env python3
"""Rebuild private cash/work explanation from a saved canonical decision; offline/no-send."""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path
from daily_common import ROOT, now_et
from capital_work_queue import refresh_capital_work_queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--as-of", help="Aware time for a reproducible rehearsal")
    args = parser.parse_args()
    try:
        decision = json.loads((args.input_root / "04_research/company_research/daily_decision.json").read_text())
        current = datetime.fromisoformat(args.as_of) if args.as_of else now_et()
        result = refresh_capital_work_queue(decision, root=args.output_root, current=current, input_root=args.input_root)
    except (OSError, ValueError):
        result = {"status":"unverified", "failure_code":"canonical_decision_unavailable"}
    print(json.dumps({"status":result["status"], "failure_code":result.get("failure_code"),
        "automatic_action_allowed":False, "email_attempted":False}, sort_keys=True))
    return 0 if result["status"] == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
