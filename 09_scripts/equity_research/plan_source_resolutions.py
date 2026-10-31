"""Explicit recovery of exact historical plan sources, never current inputs.

The append-only receipt names a plan record, its original logical source and
one retained file with identical bytes. No search, price substitution, record
rewrite or new plan authority is involved.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from daily_common import canonical_sha256, now_et

SCHEMA = "equity_plan_source_resolutions_v1"
RELATIVE_PATH = "05_risk_and_positions/plan_source_resolutions.local.json"
PLAN_PATH = "05_risk_and_positions/investment_plans.local.json"
PROPOSAL_FIELDS = {"plan_id", "plan_version", "plan_record_hash", "logical_path",
                   "expected_sha256", "retained_path", "reason", "reviewer"}
RECEIPT_FIELDS = PROPOSAL_FIELDS | {"registered_at", "previous_hash", "resolution_hash"}
MAX_SOURCE_BYTES = 32_000_000


def safe_path(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or Path(relative).is_absolute() or ".." in Path(relative).parts
            or Path(relative).as_posix() != relative or relative == "."):
        raise ValueError("plan_source_resolution_path_invalid")
    root = root.resolve()
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise ValueError("plan_source_resolution_path_outside_root")
    part = root
    for name in Path(relative).parts:
        part = part / name
        if part.is_symlink():
            raise ValueError("plan_source_resolution_symlink_rejected")
    return target


def read_regular(root: Path, relative: str, *, maximum: int = MAX_SOURCE_BYTES) -> bytes:
    target = safe_path(root, relative)
    before = target.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
        raise ValueError("plan_source_resolution_file_invalid")
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    try:
        if identity(os.fstat(descriptor)) != identity(before):
            raise ValueError("plan_source_resolution_file_changed")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(maximum + 1)
        if (len(raw) > maximum or identity(os.fstat(descriptor)) != identity(before)
                or identity(target.stat(follow_symlinks=False)) != identity(before)):
            raise ValueError("plan_source_resolution_file_changed")
        return raw
    finally:
        os.close(descriptor)


def _stamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed
    except (ValueError, TypeError) as exc:
        raise ValueError("plan_source_resolution_timestamp_invalid") from exc


def _key(row: dict) -> tuple:
    return (row["plan_id"], row["plan_version"], row["plan_record_hash"], row["logical_path"], row["expected_sha256"])


def _validate_proposal(row: dict, ledger: dict, *, root: Path) -> None:
    if not isinstance(row, dict) or set(row) != PROPOSAL_FIELDS:
        raise ValueError("plan_source_resolution_fields_invalid")
    if (not isinstance(row["plan_id"], str) or not row["plan_id"]
            or type(row["plan_version"]) is not int or row["plan_version"] < 1
            or any(not isinstance(row[k], str) or not row[k].strip() for k in ("reason", "reviewer", "logical_path", "retained_path"))
            or any(re.fullmatch(r"[0-9a-f]{64}", str(row[k])) is None for k in ("plan_record_hash", "expected_sha256"))):
        raise ValueError("plan_source_resolution_identity_invalid")
    matches = [r for r in ledger.get("records", []) if r.get("plan_id") == row["plan_id"]
               and type(r.get("version")) is int and r.get("version") == row["plan_version"]
               and r.get("record_hash") == row["plan_record_hash"]]
    if len(matches) != 1:
        raise ValueError("plan_source_resolution_record_not_found")
    plan = matches[0]
    if canonical_sha256({k: v for k, v in plan.items() if k != "record_hash"}) != row["plan_record_hash"]:
        raise ValueError("plan_source_resolution_record_hash_invalid")
    sources = [s for s in plan.get("sources", []) if s.get("path") == row["logical_path"]]
    if len(sources) != 1 or sources[0].get("sha256") != row["expected_sha256"]:
        raise ValueError("plan_source_resolution_source_not_bound")
    logical = safe_path(root, row["logical_path"])
    if logical.exists():
        info = logical.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("plan_source_resolution_logical_file_invalid")
    if row["retained_path"] in {row["logical_path"], RELATIVE_PATH, PLAN_PATH}:
        raise ValueError("plan_source_resolution_retained_path_invalid")
    if hashlib.sha256(read_regular(root, row["retained_path"])).hexdigest() != row["expected_sha256"]:
        raise ValueError("plan_source_resolution_retained_hash_mismatch")


def validate_registry(payload: dict, ledger: dict, *, root: Path, current: datetime | None = None) -> dict:
    if not isinstance(ledger, dict) or not isinstance(ledger.get("records"), list) or any(not isinstance(r, dict) for r in ledger["records"]):
        raise ValueError("plan_source_resolution_ledger_invalid")
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "records"} or payload.get("schema_version") != SCHEMA or not isinstance(payload.get("records"), list):
        raise ValueError("plan_source_resolution_registry_invalid")
    current = current or now_et()
    result, chain, previous_time = {}, "", None
    for receipt in payload["records"]:
        if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
            raise ValueError("plan_source_resolution_receipt_invalid")
        proposal = {k: receipt[k] for k in PROPOSAL_FIELDS}
        _validate_proposal(proposal, ledger, root=root)
        registered = _stamp(receipt["registered_at"])
        plan = next(r for r in ledger["records"] if r["record_hash"] == receipt["plan_record_hash"])
        if registered > current or registered < _stamp(plan["recorded_at"]) or (previous_time and registered < previous_time):
            raise ValueError("plan_source_resolution_time_order_invalid")
        if receipt["previous_hash"] != chain or receipt["resolution_hash"] != canonical_sha256({k: v for k, v in receipt.items() if k != "resolution_hash"}):
            raise ValueError("plan_source_resolution_chain_invalid")
        key = _key(receipt)
        if key in result:
            raise ValueError("plan_source_resolution_duplicate")
        result[key], chain, previous_time = receipt, receipt["resolution_hash"], registered
    return result


def load(root: Path, ledger: dict) -> dict:
    path = safe_path(root, RELATIVE_PATH)
    if not path.exists():
        return {}
    payload = json.loads(read_regular(root, RELATIVE_PATH, maximum=2_000_000))
    return validate_registry(payload, ledger, root=root)


def validate_source(root: Path, row: dict, source: dict, resolutions: dict | None = None) -> None:
    """Only an exact, registered historical record may use retained bytes."""
    target = safe_path(root, source["path"])
    missing = not target.exists()
    if not missing and hashlib.sha256(read_regular(root, source["path"])).hexdigest() == source["sha256"]:
        return
    key = (row.get("plan_id"), row.get("version"), row.get("record_hash"), source["path"], source["sha256"])
    if resolutions and key in resolutions:
        # Registry validation already checked this exact source and file hash.
        receipt = resolutions[key]
        if hashlib.sha256(read_regular(root, receipt["retained_path"])).hexdigest() == source["sha256"]:
            return
        raise ValueError("plan_source_resolution_retained_hash_mismatch")
    raise ValueError("plan_source_missing" if missing else "plan_source_hash_mismatch")


def proof_hashes(root: Path, ledger: dict | None = None) -> dict[str, str]:
    path = safe_path(root, RELATIVE_PATH)
    if not path.exists():
        return {}
    ledger = ledger if ledger is not None else json.loads(read_regular(root, PLAN_PATH))
    raw = read_regular(root, RELATIVE_PATH, maximum=2_000_000)
    receipts = validate_registry(json.loads(raw), ledger, root=root)
    return {RELATIVE_PATH: hashlib.sha256(raw).hexdigest(),
            **{row["retained_path"]: row["expected_sha256"] for row in receipts.values()}}


def append_resolutions(payload: dict, proposals: list[dict], ledger: dict, *, root: Path,
                       current: datetime | None = None) -> tuple[dict, int]:
    from investment_plans import validate_ledger
    # Validate the original immutable chain without requiring mutable source
    # paths to still hold their historical contents. Receipts cannot repair it.
    validate_ledger(ledger)
    current = current or now_et()
    existing = validate_registry(payload, ledger, root=root, current=current)
    if not isinstance(proposals, list) or not proposals:
        raise ValueError("plan_source_resolution_proposals_required")
    result, count = deepcopy(payload), 0
    for proposal in proposals:
        _validate_proposal(proposal, ledger, root=root)
        key = _key(proposal)
        if key in existing:
            if any(existing[key][k] != proposal[k] for k in PROPOSAL_FIELDS):
                raise ValueError("plan_source_resolution_already_registered")
            continue
        row = {**proposal, "registered_at": current.isoformat(),
               "previous_hash": result["records"][-1]["resolution_hash"] if result["records"] else ""}
        row["resolution_hash"] = canonical_sha256(row)
        result["records"].append(row)
        existing[key], count = row, count + 1
    validate_registry(result, ledger, root=root, current=current)
    return result, count
