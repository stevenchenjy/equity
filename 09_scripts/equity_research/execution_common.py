from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from account_common import (
    ACCOUNT_STATE,
    C9_INHIBIT,
    CURRENT_POSITIONS,
    MARKET_SNAPSHOT,
    ROOT,
    as_float,
    csv_fields,
    load_account_state,
    load_active_inhibit,
    load_market_rows,
    read_csv,
    timestamp,
    write_csv,
    write_text,
)


CONTROL_DIR = ROOT / "00_project_control"
EXECUTION_DIR = ROOT / "06_execution_records"
POSITION_DIR = ROOT / "05_risk_and_positions"
GENERATED_POSITION_DIR = POSITION_DIR / "generated" / "current"
RESEARCH_DIR = ROOT / "04_research" / "company_research"

EXECUTION_FILE = EXECUTION_DIR / "manual_executions.local.csv"
PENDING_REPORT = EXECUTION_DIR / "pending_execution_report.csv"
CONFIRMED_REPORT = EXECUTION_DIR / "confirmed_execution_report.csv"
RECONCILIATION_REPORT = EXECUTION_DIR / "reconciliation_report.csv"
POST_EXECUTION_WEIGHTS = GENERATED_POSITION_DIR / "post_execution_weights.csv"
POST_EXECUTION_SUMMARY = GENERATED_POSITION_DIR / "post_execution_account_summary.md"
PRICE_AWARE_ACTION_PLAN = GENERATED_POSITION_DIR / "price_aware_action_plan.csv"
EXECUTION_RESEARCH_REPORT = RESEARCH_DIR / "execution_report.md"
C9B_RUN_LOG = CONTROL_DIR / "run_logs" / "execution_run_log.csv"

EXECUTION_FIELDS = [
    "execution_id",
    "ticker",
    "side",
    "shares",
    "order_type",
    "order_submitted_at",
    "order_status",
    "limit_price_optional",
    "fill_date",
    "fill_price",
    "fees",
    "shares_before",
    "shares_after",
    "cash_before",
    "cash_after",
    "account_total_after",
    "source",
    "notes",
]
ALLOWED_STATUSES = {"pending_fill", "filled", "cancelled", "partial_fill"}
ALLOWED_SIDES = {"buy", "sell"}
RUN_LOG_FIELDS = [
    "timestamp",
    "phase",
    "script_name",
    "action",
    "status",
    "execution_id",
    "execution_status",
    "input_paths",
    "output_paths",
    "positions_modified",
    "account_state_modified",
    "email_sent",
    "d3_inhibit_active",
    "broker_used",
    "order_code_created",
    "smtp_config_modified",
    "archived_legacy_used",
    "notes",
]

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_APPLIED_RECONCILIATION_ACCEPTED_STATES = frozenset(
    {
        "historical_account_hash_match",
        "owner_account_snapshot_after_reconciliation",
        "verified_allocation_policy_only_migration",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def allocation_policy_proof_hashes(root: Path) -> dict[str, str | None]:
    """Bind private policy proofs for publication, never substitute old facts."""
    from migrate_allocation_policy import ACCOUNT, CONFIG, POSITIONS, MANUAL, CONFIRMED, ORDERS
    root = root.resolve()
    directory = root / "05_risk_and_positions/allocation_policy_migrations.local"
    if not directory.exists() and not directory.is_symlink():
        return {}
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("allocation_policy_proof_directory_invalid")
    receipts = sorted(directory.glob("*.json"))
    if not receipts:
        return {}
    paths = {root / rel for rel in (ACCOUNT, CONFIG, POSITIONS, MANUAL, CONFIRMED, ORDERS)} | set(receipts)
    for receipt in receipts:
        if receipt.is_symlink() or not receipt.is_file():
            raise ValueError("allocation_policy_proof_file_invalid")
        try:
            bindings = json.loads(receipt.read_bytes()).get("source_bindings", {})
            for rel in (ACCOUNT, MANUAL):
                digest = bindings.get(rel)
                if isinstance(digest, str) and _SHA256_PATTERN.fullmatch(digest):
                    paths.add(root / "11_archive/portfolio_versions.local" / Path(rel).name / digest)
        except (ValueError, TypeError, AttributeError):
            pass  # Malformed bytes remain bound and cannot grant equivalence.
    result = {}
    for path in sorted(paths):
        if path.is_symlink() or path.resolve() != path or (path.exists() and not path.is_file()):
            raise ValueError("allocation_policy_proof_file_invalid")
        result[str(path.relative_to(root))] = sha256(path) if path.exists() else None
    return result


def allocation_policy_migration_equivalence(
    root: Path, *, expected_account_sha256: str, current_account_sha256: str,
    current_positions_sha256: str, current_account_last_updated: object,
) -> bool | None:
    """Prove one applied metadata-only transition; None means no such claim.

    Historical bytes are used only to prove financial identity to a reconciled
    account. They cannot supply current holdings, orders, cash or freshness.
    """
    from active_config import load_active_config, validate_allocation_targets, validate_research_risk_limits
    from account_common import validate_account_state
    from migrate_allocation_policy import ACCOUNT, CONFIG, POSITIONS, MANUAL, CONFIRMED, ORDERS, POLICY_FIELDS, _bytes, _sha
    root = root.resolve()
    directory = root / "05_risk_and_positions/allocation_policy_migrations.local"
    expected_archive = root / "11_archive/portfolio_versions.local" / Path(ACCOUNT).name / expected_account_sha256
    def later_owner_observation() -> bool:
        from update_manual_account import current_manual_snapshot_matches
        try:
            snapshot = json.loads((root / MANUAL).read_bytes())
            if "allocation_policy_rebind" in snapshot:
                return False
            if not current_manual_snapshot_matches(current_positions_sha256, current_account_sha256, root=root):
                return False
            if sha256(root / ACCOUNT) != current_account_sha256 or sha256(expected_archive) != expected_account_sha256:
                return False
            old = validate_account_state(json.loads(expected_archive.read_bytes()))
            current = validate_account_state(json.loads((root / ACCOUNT).read_bytes()))
            old_time = datetime.fromisoformat(old["last_updated"])
            new_time = datetime.fromisoformat(current["last_updated"])
            observed_time = datetime.fromisoformat(snapshot["recorded_at"])
            return (current["last_updated"] == current_account_last_updated
                    and all(value.tzinfo is not None for value in (old_time, new_time, observed_time))
                    and old_time < new_time <= observed_time)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False
    if later_owner_observation():
        # A separate, newly bound owner observation has its own authority.
        # Its ordinary timestamp checks still run in the calling classifier.
        return None
    def missing_proof() -> bool | None:
        # A removed journal must not turn a metadata-only edit into a later
        # owner observation through the legacy timestamp compatibility path.
        try:
            if expected_archive.is_file() and sha256(expected_archive) == expected_account_sha256:
                old = json.loads(expected_archive.read_bytes())
                current = json.loads((root / ACCOUNT).read_bytes())
                if ({k: v for k, v in old.items() if k not in POLICY_FIELDS}
                        == {k: v for k, v in current.items() if k not in POLICY_FIELDS}):
                    return False
        except (OSError, ValueError, TypeError, AttributeError):
            return False
        return None
    if not directory.exists() and not directory.is_symlink():
        return missing_proof()
    try:
        proof_hashes = allocation_policy_proof_hashes(root)
        candidates = []
        for path in sorted(directory.glob("*.json")):
            receipt = json.loads(path.read_bytes())
            bindings = receipt.get("source_bindings", {})
            if bindings.get(ACCOUNT) == expected_account_sha256 or receipt.get("account_sha256_after") == current_account_sha256:
                candidates.append((path, receipt))
        if not candidates:
            return missing_proof()
        if len(candidates) != 1:
            return False
        path, receipt = candidates[0]
        bindings = receipt["source_bindings"]
        if (receipt.get("schema_version") != "equity_allocation_policy_migration_v1"
                or receipt.get("status") != "applied" or receipt.get("applied") is not True
                or any(receipt.get(key) is not False for key in
                       ("broker_evidence_updated", "financial_facts_changed", "owner_snapshot_created",
                        "broker_read", "email_sent", "trade_placed"))
                or not str(receipt.get("request_reference", "")).strip()
                or set(bindings) != {ACCOUNT, CONFIG, POSITIONS, MANUAL, CONFIRMED, ORDERS}
                or bindings[ACCOUNT] != expected_account_sha256
                or receipt.get("account_sha256_after") != current_account_sha256
                or bindings[POSITIONS] != current_positions_sha256):
            return False
        receipt_id = _sha(_bytes({"bindings": bindings, "after": current_account_sha256,
                                  "request_reference": receipt["request_reference"]}))
        if path.name != f"{receipt_id}.json":
            return False
        # The historical config digest stays in the immutable receipt ID.
        # Live configuration may change unrelated notification/data settings;
        # current approved policy fields are compared explicitly below, and
        # publication separately binds the current config bytes.
        for rel in (POSITIONS, CONFIRMED, ORDERS):
            if proof_hashes.get(rel) != bindings[rel]:
                return False
        archive = root / "11_archive/portfolio_versions.local" / Path(ACCOUNT).name / expected_account_sha256
        if (Path(receipt["predecessor_archives"][ACCOUNT]).resolve() != archive
                or proof_hashes.get(str(archive.relative_to(root))) != expected_account_sha256
                or proof_hashes.get(ACCOUNT) != current_account_sha256):
            return False
        before = validate_account_state(json.loads(archive.read_bytes()))
        after = validate_account_state(json.loads((root / ACCOUNT).read_bytes()))
        if (before != receipt["account_before"] or after != receipt["account_after"]
                or _sha(_bytes(after)) != current_account_sha256
                or {k: v for k, v in before.items() if k not in POLICY_FIELDS}
                   != {k: v for k, v in after.items() if k not in POLICY_FIELDS}
                or after["last_updated"] != current_account_last_updated
                or receipt.get("observation_time_preserved") != before["last_updated"]):
            return False
        policy = load_active_config(root / CONFIG)["account"]
        targets = validate_allocation_targets(policy)
        approved = {**validate_research_risk_limits(policy.get("research_risk_limits")),
                    "core_allocation_target_pct": targets["core_target_pct"],
                    "core_minimum_pct": targets["core_minimum_pct"],
                    "active_stock_target_pct": targets["active_target_pct"],
                    "cash_target_pct": targets["cash_target_pct"]}
        if {k: after[k] for k in POLICY_FIELDS} != approved:
            return False
        changes = {key: {"before": before.get(key), "after": after.get(key)} for key in sorted(POLICY_FIELDS)
                   if key not in before or before.get(key) != after.get(key)}
        if not changes or receipt.get("changes") != changes:
            return False
        manual_hash = bindings[MANUAL]
        if manual_hash is None:
            if proof_hashes.get(MANUAL) is not None or receipt.get("manual_snapshot_rebound") is not False:
                return False
        else:
            manual_archive = root / "11_archive/portfolio_versions.local" / Path(MANUAL).name / manual_hash
            if (Path(receipt["predecessor_archives"][MANUAL]).resolve() != manual_archive
                    or proof_hashes.get(str(manual_archive.relative_to(root))) != manual_hash):
                return False
            if receipt.get("manual_snapshot_rebound") is True:
                manual_before = json.loads(manual_archive.read_bytes())
                manual_after = {**manual_before, "account_sha256_after": current_account_sha256,
                    "allocation_policy_rebind": {"policy_only": True, "receipt_path": str(path.relative_to(root)),
                        "prior_account_sha256": expected_account_sha256, "new_account_sha256": current_account_sha256,
                        "broker_evidence_updated": False}}
                if json.loads((root / MANUAL).read_bytes()) != manual_after:
                    return False
            elif receipt.get("manual_snapshot_rebound") is not False or proof_hashes.get(MANUAL) != manual_hash:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def applied_reconciliation_current_state_status(
    reconciliation: Mapping[str, object],
    *,
    current_positions_sha256: str,
    current_account_sha256: str,
    current_account_last_updated: object,
    root: Path | None = None,
) -> str:
    """Classify whether a current C9 state remains consistent with one fill.

    C9B reconciliation hashes are historical raw-byte evidence and must never
    be rewritten merely because the Project Owner later confirms a current
    account snapshot.  A later snapshot is compatible only when the reconciled
    position bytes remain exact, the current account state has already passed
    the C9 schema validator, and its timestamp is strictly after the
    reconciliation's public-price reference.  This is not a fill replay or a
    waiver of C9 arithmetic checks.
    """

    expected_positions = str(reconciliation.get("positions_sha256_after", "")).strip()
    expected_account = str(reconciliation.get("account_sha256_after", "")).strip()
    if (
        _SHA256_PATTERN.fullmatch(expected_positions) is None
        or _SHA256_PATTERN.fullmatch(expected_account) is None
        or _SHA256_PATTERN.fullmatch(current_positions_sha256) is None
        or _SHA256_PATTERN.fullmatch(current_account_sha256) is None
    ):
        return "reconciliation_hash_invalid"
    if current_positions_sha256 != expected_positions:
        return "positions_hash_mismatch"
    if current_account_sha256 == expected_account:
        return "historical_account_hash_match"

    if root is not None:
        equivalent = allocation_policy_migration_equivalence(root,
            expected_account_sha256=expected_account, current_account_sha256=current_account_sha256,
            current_positions_sha256=current_positions_sha256,
            current_account_last_updated=current_account_last_updated)
        if equivalent is not None:
            return "verified_allocation_policy_only_migration" if equivalent else "allocation_policy_migration_proof_invalid"

    reference_timestamp = str(
        reconciliation.get("reference_price_timestamp", "")
    ).strip()
    if not isinstance(current_account_last_updated, str):
        return "account_refresh_timestamp_invalid"
    try:
        reference_at = datetime.fromisoformat(reference_timestamp)
        updated_at = datetime.fromisoformat(current_account_last_updated)
    except ValueError:
        return "account_refresh_timestamp_invalid"
    if reference_at.tzinfo is None or updated_at.tzinfo is None:
        return "account_refresh_timestamp_invalid"
    if updated_at <= reference_at:
        return "account_refresh_timestamp_not_newer"
    return "owner_account_snapshot_after_reconciliation"


def applied_reconciliation_matches_current_state(
    reconciliation: Mapping[str, object],
    *,
    current_positions_sha256: str,
    current_account_sha256: str,
    current_account_last_updated: object,
    root: Path | None = None,
) -> bool:
    """Return the closed accepted subset of reconciliation-state statuses."""

    return (
        applied_reconciliation_current_state_status(
            reconciliation,
            current_positions_sha256=current_positions_sha256,
            current_account_sha256=current_account_sha256,
            current_account_last_updated=current_account_last_updated,
            root=root,
        )
        in _APPLIED_RECONCILIATION_ACCEPTED_STATES
    )


def optional_float(value: object, field: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return as_float(value, field)


def parse_iso(value: str, field: str, *, date_only: bool = False) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")
    try:
        if date_only:
            datetime.strptime(value, "%Y-%m-%d")
        else:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError
    except ValueError as exc:
        kind = "YYYY-MM-DD" if date_only else "timezone-aware ISO timestamp"
        raise ValueError(f"{field} must be a {kind}") from exc


def write_private_execution_rows(rows: list[dict[str, str]]) -> None:
    write_csv(EXECUTION_FILE, rows, EXECUTION_FIELDS)
    os.chmod(EXECUTION_FILE, 0o600)


def load_execution_rows() -> list[dict[str, str]]:
    if not EXECUTION_FILE.exists():
        raise FileNotFoundError("manual_executions.local.csv is required")
    if csv_fields(EXECUTION_FILE) != EXECUTION_FIELDS:
        raise ValueError("manual execution columns do not match the C9B contract")
    rows = read_csv(EXECUTION_FILE)
    if not rows:
        raise ValueError("manual execution file must contain at least one record")
    seen: set[str] = set()
    for row in rows:
        execution_id = row["execution_id"].strip()
        if not execution_id or execution_id in seen:
            raise ValueError("execution_id values must be non-empty and unique")
        seen.add(execution_id)
        validate_execution_row(row)
    return rows


def validate_execution_row(row: dict[str, str]) -> None:
    execution_id = row["execution_id"].strip()
    ticker = row["ticker"].strip().upper()
    side = row["side"].strip()
    status = row["order_status"].strip()
    if not execution_id or not ticker:
        raise ValueError("execution_id and ticker are required")
    if side not in ALLOWED_SIDES:
        raise ValueError(f"{execution_id}.side must be buy or sell")
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"{execution_id}.order_status is unsupported")
    if not row["order_type"].strip() or not row["source"].strip():
        raise ValueError(f"{execution_id}.order_type and source are required")
    shares = as_float(row["shares"], f"{execution_id}.shares")
    before = as_float(row["shares_before"], f"{execution_id}.shares_before")
    after = as_float(row["shares_after"], f"{execution_id}.shares_after")
    if shares <= 0 or before < 0 or after < 0:
        raise ValueError(f"{execution_id} share values are invalid")
    if not all(math.isclose(value, round(value), abs_tol=1e-9) for value in (shares, before, after)):
        raise ValueError(f"{execution_id} uses whole shares only")
    expected_after = before - shares if side == "sell" else before + shares
    if not math.isclose(after, expected_after, abs_tol=1e-9):
        raise ValueError(f"{execution_id}.shares_after does not reconcile with side and shares")
    if row["order_submitted_at"].strip():
        parse_iso(row["order_submitted_at"], f"{execution_id}.order_submitted_at")
    limit_price = optional_float(row["limit_price_optional"], f"{execution_id}.limit_price_optional")
    if limit_price is not None and limit_price <= 0:
        raise ValueError(f"{execution_id}.limit_price_optional must be positive")

    fill_price = optional_float(row["fill_price"], f"{execution_id}.fill_price")
    fees = optional_float(row["fees"], f"{execution_id}.fees")
    cash_before = optional_float(row["cash_before"], f"{execution_id}.cash_before")
    cash_after = optional_float(row["cash_after"], f"{execution_id}.cash_after")
    account_total_after = optional_float(row["account_total_after"], f"{execution_id}.account_total_after")
    if any(value is not None and value < 0 for value in (fees, cash_before, cash_after, account_total_after)):
        raise ValueError(f"{execution_id} financial values cannot be negative")

    if status == "pending_fill":
        unknowns = {
            "fill_date": row["fill_date"].strip(),
            "fill_price": row["fill_price"].strip(),
            "fees": row["fees"].strip(),
            "cash_before": row["cash_before"].strip(),
            "cash_after": row["cash_after"].strip(),
            "account_total_after": row["account_total_after"].strip(),
        }
        present = [field for field, value in unknowns.items() if value]
        if present:
            raise ValueError(f"{execution_id} pending_fill must leave unknown fields blank: {','.join(present)}")
    elif status in {"filled", "partial_fill"}:
        parse_iso(row["fill_date"], f"{execution_id}.fill_date", date_only=True)
        if fill_price is None or fill_price <= 0:
            raise ValueError(f"{execution_id}.fill_price must be a confirmed positive number")
        if fees is None:
            raise ValueError(f"{execution_id}.fees must be entered explicitly, including 0 when confirmed")
        if status == "partial_fill" and "actual filled shares" not in row["notes"].lower():
            raise ValueError(f"{execution_id} partial_fill notes must identify shares as actual filled shares")
    elif status == "cancelled":
        if any((row["fill_date"].strip(), row["fill_price"].strip(), row["cash_after"].strip(), row["account_total_after"].strip())):
            raise ValueError(f"{execution_id} cancelled record cannot contain fill or reconciled account values")


def select_execution(rows: list[dict[str, str]], execution_id: str) -> dict[str, str]:
    matches = [row for row in rows if row["execution_id"] == execution_id]
    if len(matches) != 1:
        raise ValueError(f"execution_id not found uniquely: {execution_id}")
    return matches[0]


def execution_cash(row: dict[str, str], account: dict[str, object]) -> tuple[float, float, float, str]:
    execution_id = row["execution_id"]
    shares = as_float(row["shares"], f"{execution_id}.shares")
    fill_price = as_float(row["fill_price"], f"{execution_id}.fill_price")
    fees = as_float(row["fees"], f"{execution_id}.fees")
    supplied_before = optional_float(row["cash_before"], f"{execution_id}.cash_before")
    cash_before = supplied_before if supplied_before is not None else as_float(account["cash_available"], "cash_available")
    expected = cash_before + shares * fill_price - fees if row["side"] == "sell" else cash_before - shares * fill_price - fees
    supplied_after = optional_float(row["cash_after"], f"{execution_id}.cash_after")
    if supplied_after is None:
        return cash_before, expected, 0.0, "calculated_from_validated_fill"
    difference = supplied_after - expected
    if abs(difference) > 0.01:
        raise ValueError(f"{execution_id}.cash_after differs from fill arithmetic by {difference:.2f}")
    return cash_before, supplied_after, difference, "user_confirmed_cash_after"


def intraday_range_pct(market_row: dict[str, str]) -> float:
    price = as_float(market_row["last_price"], "last_price")
    high = as_float(market_row["day_high"], "day_high")
    low = as_float(market_row["day_low"], "day_low")
    return max(0.0, (high - low) / price * 100.0)


def slippage_review_pct(market_row: dict[str, str]) -> float:
    range_pct = intraday_range_pct(market_row)
    dollar_volume = as_float(market_row["dollar_volume"], "dollar_volume")
    if dollar_volume >= 5_000_000_000 and range_pct <= 2.0:
        return 0.15
    if dollar_volume >= 1_000_000_000:
        return 0.25
    if range_pct >= 5.0:
        return round(min(1.0, max(0.50, range_pct * 0.10)), 2)
    if range_pct >= 3.0:
        return round(min(0.75, max(0.40, range_pct * 0.10)), 2)
    return 0.30


def append_c9b_log(
    script_name: str,
    action: str,
    status: str,
    inputs: Iterable[Path],
    outputs: Iterable[Path],
    *,
    execution_id: str = "",
    execution_status: str = "",
    positions_modified: str = "no",
    account_state_modified: str = "no",
    notes: str = "",
) -> None:
    inhibit_state = "invalid"
    try:
        inhibit_state = "yes" if load_active_inhibit().get("active") is True else "no"
    except ValueError:
        pass
    C9B_RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = C9B_RUN_LOG.exists() and C9B_RUN_LOG.stat().st_size > 0
    with C9B_RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp(),
                "phase": "phase5r_c9b",
                "script_name": script_name,
                "action": action,
                "status": status,
                "execution_id": execution_id,
                "execution_status": execution_status,
                "input_paths": ";".join(str(path.relative_to(ROOT)) for path in inputs),
                "output_paths": ";".join(str(path.relative_to(ROOT)) for path in outputs),
                "positions_modified": positions_modified,
                "account_state_modified": account_state_modified,
                "email_sent": "no",
                "d3_inhibit_active": inhibit_state,
                "broker_used": "no",
                "order_code_created": "no",
                "smtp_config_modified": "no",
                "archived_legacy_used": "no",
                "notes": notes,
            }
        )


__all__ = [
    "ACCOUNT_STATE",
    "applied_reconciliation_current_state_status",
    "applied_reconciliation_matches_current_state",
    "C9B_RUN_LOG",
    "C9_INHIBIT",
    "CONFIRMED_REPORT",
    "CURRENT_POSITIONS",
    "EXECUTION_FIELDS",
    "EXECUTION_FILE",
    "EXECUTION_RESEARCH_REPORT",
    "MARKET_SNAPSHOT",
    "PENDING_REPORT",
    "POST_EXECUTION_SUMMARY",
    "POST_EXECUTION_WEIGHTS",
    "PRICE_AWARE_ACTION_PLAN",
    "RECONCILIATION_REPORT",
    "ROOT",
    "append_c9b_log",
    "as_float",
    "execution_cash",
    "intraday_range_pct",
    "load_account_state",
    "load_active_inhibit",
    "load_execution_rows",
    "load_market_rows",
    "optional_float",
    "read_csv",
    "select_execution",
    "sha256",
    "slippage_review_pct",
    "timestamp",
    "validate_execution_row",
    "write_csv",
    "write_private_execution_rows",
    "write_text",
]
