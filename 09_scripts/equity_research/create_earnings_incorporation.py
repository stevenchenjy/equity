#!/usr/bin/env python3
"""Publish an offline source-bound latest-earnings reconciliation."""
import argparse
from pathlib import Path
from daily_common import ROOT, atomic_write_json
from earnings_incorporation import STATUS_REL, build_earnings_incorporation, reconcile_cached_financial_selections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true', help='Read-only reconciliation; do not publish.')
    args = parser.parse_args()
    incorporated = [] if args.check else reconcile_cached_financial_selections(root=args.root)
    result = build_earnings_incorporation(root=args.root)
    if not args.check:
        atomic_write_json(args.root / STATUS_REL, result)
    print('earnings_incorporation companies='+str(len(result['companies']))+' held_pending='+','.join(result['held_pending_tickers'])+' advanced='+','.join(incorporated))
    # Pending company research is an explicit decision gate, not an outage.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
