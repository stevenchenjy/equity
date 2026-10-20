#!/usr/bin/env python3
"""Validate or append one maintained company review; offline and research-only.

The caller supplies a sealed version with the preceding version's exact hash.
Default mode validates without changing the ledger. --apply appends it under an exclusive
lock. It never updates a position, plan, confidence tier, email or order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, iso_now, read_json
from thesis_evidence import SCHEMA, STORE_REL, append_review
from investment_reasoning import research_method_template
from thesis_retrospective import retrospective_template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path, help="Sealed company review JSON")
    mode.add_argument("--research-method-template", action="store_true",
                      help="Print an unknown research-method block for the next dossier version")
    mode.add_argument("--retrospective-template", type=Path, metavar="ORIGINAL_REVIEW_JSON",
                      help="Print an unresolved retrospective anchored to an existing review")
    parser.add_argument("--root", type=Path, default=ROOT, help="Evidence and private ledger root")
    parser.add_argument("--apply", action="store_true", help="Append validated version to private ledger")
    args = parser.parse_args()
    if args.research_method_template or args.retrospective_template:
        if args.apply:
            parser.error("template mode cannot apply a dossier review")
        block = ({"research_method": research_method_template()} if args.research_method_template
                 else {"retrospective": retrospective_template(read_json(args.retrospective_template))})
        print(json.dumps(block, ensure_ascii=False, indent=2))
        return 0
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
