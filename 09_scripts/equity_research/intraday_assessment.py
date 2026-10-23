"""Retain an optional intraday risk observation without changing capital inputs."""
from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from account_access import account_lock, capture_version, input_version
from daily_common import atomic_write_json, now_et, sha256_file
from investment_plans import stamp
import intraday_prices as prices
import intraday_portfolio_risk as risk

CURRENT = "04_research/company_research/intraday_portfolio_risk.local.json"
HISTORY = "04_research/company_research/intraday_portfolio_risk.local/assessments"
SCHEMA = "equity_intraday_risk_receipt_v1"


def held_symbols(root: Path) -> dict[str, str]:
    """The complete positive local inventory; never a momentum shortlist."""
    with (root / "03_source_data/equity_research/universe_seed.csv").open() as stream:
        metadata = {row["ticker"]: row for row in csv.DictReader(stream)}
    with (root / "05_risk_and_positions/current_positions.local.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    selected = {}
    for row in rows:
        ticker = row["ticker"]
        if ticker in selected or ticker not in metadata:
            raise ValueError("intraday_instrument_metadata_missing_or_duplicate:" + ticker)
        try:
            quantity = Decimal(row["shares_optional"])
        except InvalidOperation:
            raise ValueError("intraday_inventory_invalid:" + ticker) from None
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("intraday_positive_inventory_required:" + ticker)
        selected[ticker] = "etf" if metadata[ticker].get("sector", "").upper() == "ETF" else "stocks"
    if not selected:
        raise ValueError("intraday_equity_inventory_empty")
    return dict(sorted(selected.items()))


def _safe(root: Path, path: Path) -> None:
    if (not path.resolve().is_relative_to(root.resolve())
            or any(parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(root))
            or (path.exists() and not path.is_file())):
        raise ValueError("intraday_risk_receipt_path_unsafe")


def _retain(root: Path, assessment: dict) -> dict:
    raw = (json.dumps(assessment, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = root / HISTORY / (digest + ".json")
    _safe(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("intraday_risk_immutable_receipt_changed")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"path": str(path.relative_to(root)), "sha256": digest}


def recompose(root: Path, *, current: datetime | None = None, collect: bool = False,
              claim_id: str = "offline-publication", client=None) -> dict:
    """Only explicit collect=True may use HTTP; the full-refresh stage is offline."""
    root = root.resolve(); current = current or now_et()
    receipt = {"schema_version": SCHEMA, "generated_at": current.isoformat(),
               "collection_requested": collect, "email_sent": False, "trade_placed": False}
    try:
        with account_lock(root, shared=True):
            version = input_version(root)
            symbols = held_symbols(root)
        if collect:
            snapshot = prices.collect(root, symbols, account_version=version, claim_id=claim_id,
                                      current=current, client=client)
        elif (root / prices.CURRENT).exists():
            snapshot = prices.load_latest(root)
        else:
            snapshot = prices.record_unavailable(root, symbols, account_version=version,
                claim_id=claim_id, reason="intraday_not_collected_in_regular_session", current=current)
        # Real HTTP may consume part of the five-minute age allowance. Never
        # measure post-network risk against the clock from before the requests.
        assessed_at = (current if client is not None or not collect else now_et())
        assessment = risk.assess(root, snapshot, current=assessed_at)
        if capture_version(root) != version:
            raise ValueError("intraday_account_changed_during_collection")
        receipt.update(assessment=assessment, source=_retain(root, assessment),
                       status=assessment["status"], account_input_version=version)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # An optional failed overlay cannot fabricate a mark or disable the
        # separately validated canonical close, account, company or risk gates.
        receipt.update(status="unavailable", failure=str(exc))
    _safe(root, root / CURRENT)
    atomic_write_json(root / CURRENT, receipt)
    return receipt


def publication_context(root: Path, current: datetime) -> dict | None:
    """Verify an immutable as-of observation, separate from live UI projection."""
    path = root / CURRENT
    if not path.exists():
        return None
    error = None
    generated = None
    try:
        _safe(root, path)
        value = json.loads(path.read_bytes())
        generated = value.get("generated_at")
        if value.get("schema_version") != SCHEMA or stamp(value["generated_at"]) > current:
            raise ValueError("intraday_risk_receipt_invalid")
        if "assessment" not in value:
            raise ValueError(value.get("failure", "intraday_risk_assessment_unavailable"))
        source = value["source"]; retained = root / source["path"]
        _safe(root, retained)
        if (Path(source["path"]).parent != Path(HISTORY) or retained.is_symlink()
                or not retained.resolve().is_relative_to(root.resolve())
                or sha256_file(retained) != source["sha256"]
                or json.loads(retained.read_bytes()) != value["assessment"]):
            raise ValueError("intraday_risk_immutable_receipt_invalid")
        return risk.validate_assessment(root, value["assessment"], current=current)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        error = str(exc)
    return {"schema_version": risk.SCHEMA, "status": "unavailable",
            "generated_at": generated, "positions": [],
            "dependencies": [error], "performance_is_actual": False,
            "automatic_action_allowed": False, "email_authorized": False,
            "trading_eligibility_granted": False, "new_order_quantities": 0}


def attention(root: Path, current: datetime) -> dict:
    view = publication_context(root, current)
    if view is None:
        return {"status": "not_collected", "reassessment_triggers": []}
    projected = risk.projection(root, view, current=current)
    try:
        receipt = json.loads((root / CURRENT).read_bytes())
    except (OSError, ValueError, TypeError):
        receipt = {}
    return {**projected, "assessment_source": receipt.get("source"),
            "canonical_eod_prices_unchanged": True}
