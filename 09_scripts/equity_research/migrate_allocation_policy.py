#!/usr/bin/env python3
"""Apply approved allocation metadata without recording new broker evidence.

Default/check mode is read-only. Apply serializes runtime, pipeline and this
writer, saves exact predecessors, and preserves account-observation clocks.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from typing import Any

from account_common import validate_account_state
from active_config import load_active_config, validate_allocation_targets, validate_research_risk_limits
from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, atomic_write_text, iso_now, read_json, sha256_file
from portfolio_archive import snapshot_current
from update_manual_account import current_manual_snapshot_matches

CONFIG = "00_project_control/active_production_config.json"
ACCOUNT = "05_risk_and_positions/current_account_state.local.json"
POSITIONS = "05_risk_and_positions/current_positions.local.csv"
MANUAL = "05_risk_and_positions/manual_account_snapshot.local.json"
CONFIRMED = "06_execution_records/confirmed_execution_report.csv"
ORDERS = "05_risk_and_positions/current_open_orders.local.json"
POLICY_FIELDS = {"core_allocation_target_pct", "core_minimum_pct", "active_stock_target_pct",
                 "active_stock_hard_cap_pct", "cash_target_pct", "single_stock_default_cap_pct",
                 "single_stock_hard_cap_pct"}


def _bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def proposal(root: Path) -> dict[str, Any]:
    for rel in (CONFIG, ACCOUNT, POSITIONS, MANUAL, CONFIRMED, ORDERS):
        path = root / rel
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"policy migration refuses non-regular input: {rel}")
    config = load_active_config(root / CONFIG)
    policy = config["account"]
    targets = validate_allocation_targets(policy)
    limits = validate_research_risk_limits(policy.get("research_risk_limits"))
    if set(targets) != {"core_target_pct", "core_minimum_pct", "active_target_pct", "cash_target_pct"}:
        raise ValueError("migration requires complete approved targets including core_minimum_pct")
    original_bytes = (root / ACCOUNT).read_bytes()
    original = validate_account_state(json.loads(original_bytes))
    updated = {**original, **limits,
               "core_allocation_target_pct": targets["core_target_pct"],
               "core_minimum_pct": targets["core_minimum_pct"],
               "active_stock_target_pct": targets["active_target_pct"],
               "cash_target_pct": targets["cash_target_pct"]}
    validate_account_state(updated)
    if {k: v for k, v in updated.items() if k not in POLICY_FIELDS} != {
            k: v for k, v in original.items() if k not in POLICY_FIELDS}:
        raise ValueError("allocation migration attempted to alter financial facts")
    changes = {key: {"before": original.get(key), "after": updated.get(key)}
               for key in sorted(POLICY_FIELDS)
               if key not in original or original.get(key) != updated.get(key)}
    bindings = {rel: sha256_file(root / rel) if (root / rel).exists() else None
                for rel in (CONFIG, ACCOUNT, POSITIONS, MANUAL, CONFIRMED, ORDERS)}
    matching_snapshot = current_manual_snapshot_matches(bindings[POSITIONS], bindings[ACCOUNT], root=root)
    return dict(schema_version="equity_allocation_policy_migration_v1", changes=changes,
                source_bindings=bindings, account_before=original, account_after=updated,
                account_sha256_after=_sha(_bytes(updated)),
                prior_manual_snapshot_matches=matching_snapshot,
                observation_time_preserved=original["last_updated"],
                broker_evidence_updated=False, financial_facts_changed=False,
                broker_read=False, email_sent=False, trade_placed=False)


def migrate(root: Path, *, apply: bool = False, request_reference: str = "") -> dict[str, Any]:
    root = root.resolve()
    if not apply:
        return {**proposal(root), "applied": False}
    if not request_reference.strip():
        raise ValueError("apply requires the explicit owner request reference")
    with ExitStack() as stack:
        for path in (root.parent / ".locks/equity-research-runtime.lock",
                     root / "00_project_control/run_logs/daily_pipeline.lock",
                     root / "05_risk_and_positions/allocation_policy.local.lock"):
            stack.enter_context(ExclusiveFileLock(path, wait_timeout_seconds=5))
        result = proposal(root)
        if not result["changes"]:
            return {**result, "applied": False, "status": "already_current"}
        account_before = (root / ACCOUNT).read_bytes()
        manual_before = (root / MANUAL).read_bytes() if (root / MANUAL).exists() else None
        result.update(request_reference=request_reference.strip(), policy_changed_at=iso_now(),
                      owner_snapshot_created=False, status="prepared", applied=False)
        receipt_id = _sha(_bytes({"bindings": result["source_bindings"], "after": result["account_sha256_after"],
                                 "request_reference": request_reference.strip()}))
        directory = root / "05_risk_and_positions/allocation_policy_migrations.local"
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError("policy migration receipt directory must be a private real directory")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        receipt_path = directory / f"{receipt_id}.json"
        if receipt_path.exists():
            existing = read_json(receipt_path)
            if existing.get("status") == "applied":
                raise ValueError("a prior applied migration exists with nonmatching current policy; inspect history")
        result["predecessor_archives"] = {
            ACCOUNT: str(snapshot_current(root / ACCOUNT)),
            MANUAL: str(snapshot_current(root / MANUAL)) if manual_before is not None else None,
        }
        atomic_write_json(receipt_path, result)
        receipt_path.chmod(0o600)
        # Re-read every bound input after backups and before the first mutation.
        if any((sha256_file(root / rel) if (root / rel).exists() else None) != digest
               for rel, digest in result["source_bindings"].items()):
            raise ValueError("policy migration inputs changed; no active state written")
        wrote_account = wrote_manual = False
        try:
            atomic_write_json(root / ACCOUNT, result["account_after"])
            (root / ACCOUNT).chmod(0o600)
            wrote_account = True
            if sha256_file(root / ACCOUNT) != result["account_sha256_after"]:
                raise ValueError("migrated account readback mismatch")
            if result["prior_manual_snapshot_matches"]:
                rebound = json.loads(manual_before)
                # Preserve recorded_at/observed_at and the original owner facts.
                # The separate metadata explicitly explains the changed hash.
                rebound["account_sha256_after"] = result["account_sha256_after"]
                rebound["allocation_policy_rebind"] = {
                    "policy_only": True, "receipt_path": str(receipt_path.relative_to(root)),
                    "prior_account_sha256": result["source_bindings"][ACCOUNT],
                    "new_account_sha256": result["account_sha256_after"],
                    "broker_evidence_updated": False,
                }
                atomic_write_json(root / MANUAL, rebound)
                (root / MANUAL).chmod(0o600)
                wrote_manual = True
            for rel in (POSITIONS, CONFIRMED, CONFIG, ORDERS):
                if (sha256_file(root / rel) if (root / rel).exists() else None) != result["source_bindings"][rel]:
                    raise ValueError(f"protected migration input changed: {rel}")
            result.update(status="applied", applied=True,
                          manual_snapshot_rebound=wrote_manual,
                          completed_at=iso_now())
            atomic_write_json(receipt_path, result)
        except Exception:
            if wrote_manual:
                atomic_write_text(root / MANUAL, manual_before.decode())
            if wrote_account:
                atomic_write_text(root / ACCOUNT, account_before.decode())
            result.update(status="rolled_back", applied=False, completed_at=iso_now())
            atomic_write_json(receipt_path, result)
            raise
        return {**result, "receipt_path": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--request-reference", default="")
    args = parser.parse_args()
    result = migrate(args.root, apply=args.apply, request_reference=args.request_reference)
    # Do not put account dollars/holdings or original source receipts in stdout.
    print(json.dumps({key: result[key] for key in (
        "applied", "changes", "observation_time_preserved", "broker_evidence_updated",
        "financial_facts_changed", "broker_read", "email_sent", "trade_placed", "receipt_path", "status") if key in result},
        ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
