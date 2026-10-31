#!/usr/bin/env python3
"""Preview/register exact retained bytes for a historical plan source."""
import argparse
import json
from pathlib import Path

from daily_common import ROOT, ExclusiveFileLock, atomic_write_json
from plan_source_resolutions import (SCHEMA, RELATIVE_PATH, PLAN_PATH, append_resolutions,
                                     read_regular, safe_path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help='JSON object with a resolutions array; exact record/source identities and explicit retained paths')
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    proposal = json.loads(args.input.read_text())
    if not isinstance(proposal, dict) or set(proposal) != {"resolutions"}:
        raise ValueError("plan_source_resolution_input_invalid")
    root = args.root.resolve()
    target = safe_path(root, RELATIVE_PATH)
    # Share the maintained-plan writer's lock; this cannot race a plan append.
    plan = safe_path(root, PLAN_PATH)
    with ExclusiveFileLock(plan.with_suffix(".lock")):
        ledger_raw = read_regular(root, PLAN_PATH)
        prior_raw = read_regular(root, RELATIVE_PATH, maximum=2_000_000) if target.exists() else None
        payload = json.loads(prior_raw) if prior_raw is not None else {"schema_version": SCHEMA, "records": []}
        result, added = append_resolutions(payload, proposal["resolutions"], json.loads(ledger_raw), root=root)
        if read_regular(root, PLAN_PATH) != ledger_raw:
            raise ValueError("plan_source_resolution_ledger_changed")
        if (read_regular(root, RELATIVE_PATH, maximum=2_000_000) if target.exists() else None) != prior_raw:
            raise ValueError("plan_source_resolution_registry_changed")
        if args.apply and added:
            atomic_write_json(target, result)
        print(json.dumps({"applied": bool(args.apply and added), "preview": not args.apply,
            "new_receipts": added, "total_receipts": len(result["records"]),
            "ledger_modified": False, "current_sources_modified": False, "automatic_action_allowed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
