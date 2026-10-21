#!/usr/bin/env python3
"""Retain independent earnings-calendar leads; public network requires --refresh."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from daily_common import ROOT, ExclusiveFileLock, atomic_write_json
from earnings_events import BASE_REL, LOCK_REL, STATUS_REL, refresh_events, summary, utc_now


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='one bounded anonymous public HTTPS GET per requested date; no retry')
    parser.add_argument('--check', action='store_true', help='offline verification (also the default)')
    parser.add_argument('--root', type=Path, default=ROOT, help='workspace root for retained evidence')
    args = parser.parse_args()
    if args.refresh and args.check:
        parser.error('--refresh and --check are mutually exclusive')
    if args.refresh:
        with ExclusiveFileLock(args.root / LOCK_REL):
            marker = {'started_at': utc_now().isoformat(), 'completed_at': None, 'exit_code': None}
            atomic_write_json(args.root / BASE_REL / 'last_run.json', marker)
            try:
                refresh_events(args.root)
            except (OSError, ValueError, KeyError, TypeError):
                marker.update(completed_at=utc_now().isoformat(), exit_code=1)
                atomic_write_json(args.root / BASE_REL / 'last_run.json', marker)
                raise
            marker.update(completed_at=utc_now().isoformat(), exit_code=0)
            atomic_write_json(args.root / BASE_REL / 'last_run.json', marker)
            result = summary(args.root, current=utc_now())
            atomic_write_json(args.root / STATUS_REL, result)
    else:
        result = summary(args.root, current=utc_now())
    print(json.dumps({k: v for k, v in result.items() if k != 'events'}, ensure_ascii=False, sort_keys=True))
    # Partial discovery is not a failed capital/research batch. Consumers expose
    # coverage explicitly; no provider failure suppresses unrelated research.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
