#!/usr/bin/env python3
"""Bounded public-only swing observation, separate from research and delivery."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from daily_common import ROOT, now_et
from swing_observer import MAX_WORKER_SECONDS, due_window, run, _receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="read-only actual-window check; no collection")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check:
        print(json.dumps({"window": due_window(now_et()), "network_attempted": False,
                          "email_sent": False, "trade_placed": False}))
        return 0
    if args.worker:
        try:
            value = run(args.root)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            value = {"status": "unavailable", "failure": str(exc), "email_sent": False, "trade_placed": False}
        print(json.dumps(value))
        return 2 if value["status"] in {"failed", "unavailable", "waiting_on_data", "unavailable_quotes"} else 0
    # A hung provider/filesystem cannot create an indefinitely active poll.
    # A worker that reached collection already fenced its prior quote pointer.
    try:
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                    "--root", str(args.root), "--worker"],
                                   timeout=MAX_WORKER_SECONDS, check=False)
        return completed.returncode
    except subprocess.TimeoutExpired:
        value = {"schema_version": "equity_swing_observer_receipt_v1", "status": "timed_out",
                 "completed_at": now_et().isoformat(), "worker_timeout_seconds": MAX_WORKER_SECONDS,
                 "failure": "bounded_worker_stopped_after_timeout", "capital_authority": False,
                 "research_slot_consumed": False, "fully_passed_research": False,
                 "email_sent": False, "trade_placed": False}
        # Only the isolated observer audit is written here. The stopped worker
        # already fenced quote reuse; do not contend with a new analyst owner.
        _receipt(args.root, value)
        print(json.dumps(value))
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
