#!/usr/bin/env python3
"""Check, claim or complete one bounded intraday analyst handoff; never send."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from daily_common import ET, ROOT
from short_assessment import check, claim, complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="read-only actual-session due-state check")
    mode.add_argument("--claim", action="store_true", help="reserve a due 90-minute slot; locks never wait")
    mode.add_argument("--complete", action="store_true", help="validate a claim-bound analytical receipt")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--refresh-public", action="store_true", help="with --claim, bounded explicit official-news/calendar reads only")
    parser.add_argument("--input", type=Path, help="completed private result proposal")
    args = parser.parse_args()
    if args.refresh_public and not args.claim:
        parser.error("--refresh-public requires --claim")
    if args.complete != bool(args.input):
        parser.error("--input is required only with --complete")
    current = datetime.now(ET)
    try:
        if args.check:
            result = check(args.root, current)
        elif args.claim:
            result = claim(args.root, current, refresh_public=args.refresh_public, clock=lambda: datetime.now(ET))
        else:
            result = complete(args.root, json.loads(args.input.read_text(encoding="utf-8")), current)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(json.dumps({"outcome": "not_completed", "reason": str(error), "email_sent": False, "trade_placed": False}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
