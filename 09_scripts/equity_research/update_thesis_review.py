#!/usr/bin/env python3
"""Validate or append one maintained company review; offline and research-only.

The caller supplies a sealed version with the preceding version's exact hash.
Default mode validates without changing the ledger. --apply appends it under an exclusive
lock. It never updates a position, plan, confidence tier, email or order.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, iso_now, read_json
from thesis_evidence import SCHEMA, STORE_REL, append_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Sealed company review JSON")
    parser.add_argument("--root", type=Path, default=ROOT, help="Evidence and private ledger root")
    parser.add_argument("--apply", action="store_true", help="Append validated version to private ledger")
    args = parser.parse_args()
    root = args.root.resolve()
    record = read_json(args.input)
    lock = root / "00_project_control/run_logs/thesis_dossiers.lock"
    # Uses the same review lock for check/apply so a check never races an append.
    with ExclusiveFileLock(lock):
        store = read_json(root / STORE_REL, {"schema_version": SCHEMA, "records": []})
        updated = append_review(store, record, root, iso_now())
        if args.apply:
            atomic_write_json(root / STORE_REL, updated)
    print(f"thesis={record['ticker']} version={record['version']} validated=true applied={str(args.apply).lower()} automatic_action_allowed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
