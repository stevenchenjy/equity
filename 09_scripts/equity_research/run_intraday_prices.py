#!/usr/bin/env python3
"""Explicit public collection or offline validation; no broker or email path."""
import argparse
import json
from pathlib import Path

from intraday_prices import collect, load_current, load_latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--symbols-json", help='Exact required symbol/asset map, e.g. {"SPY":"etf"}')
    parser.add_argument("--account-version")
    parser.add_argument("--claim-id")
    args = parser.parse_args()
    if args.collect == args.check:
        parser.error("select exactly one of --collect or --check")
    try:
        if args.collect:
            if not all((args.symbols_json, args.account_version, args.claim_id)):
                parser.error("collection requires --symbols-json, --account-version and --claim-id")
            result = collect(args.root, json.loads(args.symbols_json),
                             account_version=args.account_version, claim_id=args.claim_id)
        else:
            result = load_current(args.root, account_version=args.account_version, claim_id=args.claim_id)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result.get("status") == "current" else 2
    except (ValueError, OSError, TypeError) as exc:
        try:
            latest = load_latest(args.root)
        except ValueError:
            latest = None
        print(json.dumps({"status": "unavailable", "reason": str(exc), "latest_attempt": latest}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
