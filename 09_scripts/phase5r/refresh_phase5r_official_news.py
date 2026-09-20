#!/usr/bin/env python3
"""Explicit public-network refresh or offline status check for official news."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from phase5r_daily_common import ExclusiveFileLock
from phase5r_official_news import EVENTS_PATH, LOCK_PATH, STATUS_PATH, read_official_news_status, refresh_news


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--refresh", action="store_true", help="bounded public HTTPS reads and local news receipts")
    mode.add_argument("--check", action="store_true", help="offline, read-only receipt and freshness check")
    parser.add_argument("--output-dir", type=Path, help="isolated local receipt directory for validation")
    args = parser.parse_args()
    paths = {"events_path": EVENTS_PATH, "status_path": STATUS_PATH}
    lock_path = LOCK_PATH
    if args.output_dir:
        paths = {"events_path": args.output_dir / EVENTS_PATH.name, "status_path": args.output_dir / STATUS_PATH.name}
        lock_path = args.output_dir / "phase5r_official_news.lock"
    if args.refresh:
        with ExclusiveFileLock(lock_path):
            status = refresh_news(**paths)
    else:
        status = read_official_news_status(**paths)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if status["required_coverage_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
