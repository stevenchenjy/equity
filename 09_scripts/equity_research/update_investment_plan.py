#!/usr/bin/env python3
"""Validate/append a private research-plan version; never interact with a broker."""
import argparse
import json
from pathlib import Path
from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, now_et
from investment_plans import SCHEMA, RELATIVE_PATH, append_plan, stamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    proposal = json.loads(args.input.read_text())
    if stamp(proposal["recorded_at"]) > now_et():
        raise ValueError("future_plan_record")
    target = args.root / RELATIVE_PATH
    with ExclusiveFileLock(target.with_suffix(".lock")):
        prior = json.loads(target.read_text()) if target.exists() else {"schema_version": SCHEMA, "records": []}
        result = append_plan(prior, proposal, root=args.root)
        record = result["records"][-1]
        if args.apply:
            atomic_write_json(target, result)
        print(json.dumps({"applied": args.apply, "plan_id": record["plan_id"], "version": record["version"],
                          "record_hash": record["record_hash"], "automatic_action_allowed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
