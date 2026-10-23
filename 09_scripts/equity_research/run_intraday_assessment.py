#!/usr/bin/env python3
"""Collect an explicit intraday overlay, or recompose it offline; never send."""
import argparse
import json
from pathlib import Path
from daily_common import ROOT
from intraday_assessment import recompose


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--claim-id", default="offline-publication")
    args = parser.parse_args()
    result = recompose(args.root, collect=args.collect, claim_id=args.claim_id)
    print(json.dumps({"status": result["status"], "source": result.get("source"),
        "failure": result.get("failure"), "email_sent": False, "trade_placed": False}))
    # An offline status projection succeeds when it truthfully records absent
    # data. Explicit collection advertises failure unless prices are current.
    return 0 if not args.collect or result["status"] == "current" else 2


if __name__ == "__main__":
    raise SystemExit(main())
