#!/usr/bin/env python3
"""Admit an explicitly owner-authorized experiment trigger for research only."""
import argparse
from pathlib import Path
from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, now_et, read_json
from opportunity_contract import BASE_REL, POLICY_REL, inside, require
from opportunity_triggers import validate_approval


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    proposal = read_json(args.input)
    with ExclusiveFileLock(args.root / BASE_REL / "store.lock"):
        validate_approval(proposal, root=args.root, current=now_et())
        path = inside(args.root, read_json(args.root / POLICY_REL)["approval_store"])
        store = read_json(path, {"schema_version": "equity_experiment_research_approvals_v1", "approvals": []})
        for existing in store["approvals"]:
            validate_approval(existing, root=args.root, current=now_et())
        matches = [r for r in store["approvals"] if r["approval_id"] == proposal["approval_id"]]
        if args.apply and not matches:
            require(not any(r["experiment_version"] == proposal["experiment_version"] and r["policy_sha256"] == proposal["policy_sha256"] for r in store["approvals"]), "experiment_research_approval_conflict_requires_new_review")
            atomic_write_json(args.root / BASE_REL / "approval_history" / (proposal["approval_id"]+".json"), proposal)
            store["approvals"].append(proposal)
            atomic_write_json(path, store)
    print("experiment_research_approval="+("recorded" if args.apply else "validated")+" capital_authority=false automatic_promotion=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
