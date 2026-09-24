#!/usr/bin/env python3
"""Preview or apply a manual cash/share update in one command."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from daily_common import (
    ACCOUNT_STATE_PATH,
    MARKET_SNAPSHOT_PATH,
    POSITIONS_PATH,
    atomic_write_csv,
    atomic_write_json,
    atomic_write_text,
    iso_now,
    read_csv,
    read_json,
    ROOT,
    sha256_file,
    now_et,
)

MANUAL_SNAPSHOT_PATH = ROOT / "05_risk_and_positions" / "manual_account_snapshot.local.json"
CONFIRMED_PATH = ROOT / "06_execution_records" / "confirmed_execution_report.csv"
UI_VALUATION_FIELDS = {"ticker", "last_price", "valuation_basis", "data_source", "data_timestamp"}


def read_ui_valuation(path: Path, required_tickers: set[str]) -> tuple[dict[str, dict[str, str]], str, str]:
    """Read an auditable manual valuation reference, never a B2 market row."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("valuation snapshot must be a regular local CSV of at most 1 MB")
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if (reader.fieldnames is None or len(reader.fieldnames) != len(UI_VALUATION_FIELDS)
            or set(reader.fieldnames) != UI_VALUATION_FIELDS):
        raise ValueError("valuation snapshot requires exactly ticker, last_price, valuation_basis, data_source, data_timestamp")
    market: dict[str, dict[str, str]] = {}
    current = now_et()
    for row in reader:
        if set(row) != UI_VALUATION_FIELDS or any(value is None for value in row.values()):
            raise ValueError("valuation snapshot contains a malformed row")
        ticker = row["ticker"].strip().upper()
        if not ticker or ticker in market:
            raise ValueError("valuation snapshot tickers must be nonempty and unique")
        price = float(row["last_price"])
        if not math.isfinite(price) or price <= 0:
            raise ValueError("valuation snapshot prices must be finite and positive")
        if row["valuation_basis"] != "manual_ui_observation" or not row["data_source"].strip():
            raise ValueError("valuation snapshot needs manual_ui_observation and explicit source provenance")
        observed = datetime.fromisoformat(row["data_timestamp"])
        if (observed.tzinfo is None or observed.utcoffset() is None
                or observed.astimezone(current.tzinfo).date() != current.date()
                or observed > current + timedelta(minutes=5)):
            raise ValueError("valuation snapshot timestamps must be timezone-aware observations from today, not future quotes")
        market[ticker] = dict(row, ticker=ticker)
    if set(market) != required_tickers:
        raise ValueError("valuation snapshot must cover exactly every positive-share position")
    return market, raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def current_manual_snapshot_matches(positions_hash: str, account_hash: str) -> bool:
    """A later owner snapshot may supersede history, but cannot waive new fills."""
    if MANUAL_SNAPSHOT_PATH.is_symlink():
        return False
    try:
        receipt = read_json(MANUAL_SNAPSHOT_PATH, {})
        return (receipt.get("schema_version") == "phase5r_owner_snapshot_v1"
                and len(positions_hash) == 64 and len(account_hash) == 64
                and receipt.get("positions_sha256_after") == positions_hash
                and receipt.get("account_sha256_after") == account_hash
                and receipt.get("confirmed_execution_sha256") == sha256_file(CONFIRMED_PATH)
                and receipt.get("owner_snapshot") is True
                and bool(receipt.get("source_note")))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def parse_position(value: str) -> tuple[str, float, float | None]:
    try:
        ticker, remainder = value.upper().split("=", 1)
        if "@" in remainder:
            shares_text, entry_text = remainder.split("@", 1)
            entry = float(entry_text)
        else:
            shares_text = remainder
            entry = None
        shares = float(shares_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("position must be TICKER=SHARES or TICKER=SHARES@ENTRY_PRICE") from exc
    if (not ticker or not math.isfinite(shares) or shares < 0
            or (entry is not None and (not math.isfinite(entry) or entry <= 0))):
        raise argparse.ArgumentTypeError("ticker, non-negative shares, and positive entry price are required")
    return ticker, shares, entry


def main() -> int:
    parser = argparse.ArgumentParser(
        epilog=(
            "Example: update_manual_account.py --cash 1900 "
            "--position IOT=4@36.44 --position RBRK=2@84.40 --apply"
        )
    )
    parser.add_argument("--cash", type=float, required=True)
    parser.add_argument("--cash-basis", choices=["owner_recorded", "ledger_estimate"], default="owner_recorded")
    parser.add_argument("--planning-capital-min", type=float)
    parser.add_argument("--planning-capital-max", type=float)
    parser.add_argument("--new-position-date", type=date.fromisoformat)
    parser.add_argument("--source-note", default="Explicit owner-provided manual account snapshot")
    parser.add_argument("--cash-reserved", type=float)
    parser.add_argument("--valuation-snapshot", type=Path,
                        help="Local manually observed UI marks for the account-total reference only; never replaces canonical B2 prices")
    parser.add_argument("--position", action="append", type=parse_position, default=[])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.cash) or args.cash < 0:
        raise ValueError("cash cannot be negative")
    if not args.position:
        raise ValueError("at least one --position is required; include every current position")
    if len({item[0] for item in args.position}) != len(args.position):
        raise ValueError("position tickers must be unique")

    account = read_json(ACCOUNT_STATE_PATH)
    for value in (args.planning_capital_min, args.planning_capital_max):
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("planning capital must be finite and positive")
    if (args.planning_capital_min is None) != (args.planning_capital_max is None):
        raise ValueError("both planning capital endpoints are required")
    if args.planning_capital_min is not None and args.planning_capital_min > args.planning_capital_max:
        raise ValueError("planning capital range is reversed")
    if not args.source_note.strip():
        raise ValueError("source note is required")
    before_positions = read_csv(POSITIONS_PATH)
    existing = {row["ticker"].upper(): row for row in read_csv(POSITIONS_PATH)}
    fields = list(read_csv(POSITIONS_PATH)[0].keys())
    valuation_text = ""
    valuation_hash = ""
    if args.valuation_snapshot:
        market, valuation_text, valuation_hash = read_ui_valuation(
            args.valuation_snapshot, {ticker for ticker, shares, _ in args.position if shares > 0})
    else:
        market = {row["ticker"].upper(): row for row in read_csv(MARKET_SNAPSHOT_PATH)}
    new_rows: list[dict[str, str]] = []
    holdings_value = 0.0
    for ticker, shares, entry in args.position:
        if shares == 0:
            continue
        prior = existing.get(ticker)
        if prior is None and entry is None:
            raise ValueError(f"new ticker {ticker} requires @ENTRY_PRICE")
        quote = market.get(ticker, {})
        if not args.valuation_snapshot and quote.get("data_quality_label") not in {"ok", "partial"}:
            raise ValueError(f"current market close is unavailable for {ticker}")
        close = float(quote["last_price"])
        if not math.isfinite(close) or close <= 0:
            raise ValueError(f"valuation price must be finite and positive for {ticker}")
        holdings_value += shares * close
        if prior is None:
            prior = {
                "ticker": ticker,
                "entry_date": (args.new_position_date or now_et().date()).isoformat(),
                "entry_price": f"{entry:.8f}",
                "position_pct": "0",
                "shares_optional": f"{shares:g}",
                "thesis": "Manual position recorded; full research thesis review required.",
                "horizon_class": "long_term_research",
                "planned_review_date": now_et().date().isoformat(),
                "max_loss_pct_of_account": "0.50",
                "invalidation_rule": "Review immediately because a complete thesis and invalidation rule are pending.",
                "current_action": "review_required",
                "notes": "Created by the explicit manual account updater; no broker was read.",
            }
        row = dict(prior)
        row["shares_optional"] = f"{shares:g}"
        if entry is not None:
            row["entry_price"] = f"{entry:.8f}"
        if entry is not None or prior is None or row["shares_optional"] != prior.get("shares_optional"):
            row["notes"] = args.source_note
        new_rows.append(row)

    effective_total = args.cash + holdings_value
    if not math.isfinite(effective_total) or effective_total <= 0:
        raise ValueError("effective account total must be finite and positive")
    for row in new_rows:
        ticker = row["ticker"].upper()
        shares = float(row["shares_optional"])
        close = float(market[ticker]["last_price"])
        row["position_pct"] = f"{shares * close / effective_total * 100.0:.4f}"
    reserved = account["cash_reserved"] if args.cash_reserved is None else args.cash_reserved
    if not math.isfinite(float(reserved)) or float(reserved) < 0 or float(reserved) > args.cash:
        raise ValueError("cash reserved must be between zero and available cash")
    updated_account = dict(account)
    updated_account.update({
        "account_total_value": round(effective_total, 2),
        "cash_available": round(args.cash, 2),
        "cash_reserved": round(float(reserved), 2),
        "last_updated": iso_now(),
        "cash_basis": args.cash_basis,
    })
    if args.planning_capital_min is not None:
        updated_account.update(planning_capital_min=args.planning_capital_min,
                               planning_capital_max=args.planning_capital_max)
    if args.preview:
        print(
            f"preview=true positions={len(new_rows)} cash={args.cash:.2f} "
            f"holdings_at_reference_prices={holdings_value:.2f} effective_total={effective_total:.2f} "
            f"valuation_basis={'manual_ui_observation' if args.valuation_snapshot else 'canonical_market_snapshot'} "
            "files_changed=false broker_read=false"
        )
        return 0
    receipt = {
        "schema_version": "phase5r_owner_snapshot_v1", "owner_snapshot": True,
        "recorded_at": iso_now(), "source_note": args.source_note,
        "positions_sha256_before": sha256_file(POSITIONS_PATH),
        "account_sha256_before": sha256_file(ACCOUNT_STATE_PATH),
        "confirmed_execution_sha256": sha256_file(CONFIRMED_PATH),
        "positions_before": before_positions, "account_before": account,
    }
    if args.valuation_snapshot:
        valuation_archive = MANUAL_SNAPSHOT_PATH.parent / "manual_snapshots.local" / (valuation_hash + ".valuation.csv")
        atomic_write_text(valuation_archive, valuation_text)
        receipt.update(
            valuation_basis="manual_ui_observation",
            valuation_snapshot_sha256=valuation_hash,
            valuation_snapshot_archive=str(valuation_archive),
            valuation_marks=list(market.values()),
            canonical_market_snapshot_modified=False,
        )
    atomic_write_csv(POSITIONS_PATH, fields, new_rows)
    atomic_write_json(ACCOUNT_STATE_PATH, updated_account)
    receipt.update(positions_sha256_after=sha256_file(POSITIONS_PATH),
                   account_sha256_after=sha256_file(ACCOUNT_STATE_PATH),
                   positions_after=new_rows, account_after=updated_account)
    archive = MANUAL_SNAPSHOT_PATH.parent / "manual_snapshots.local" / (receipt["account_sha256_after"] + ".json")
    atomic_write_json(archive, receipt)
    atomic_write_json(MANUAL_SNAPSHOT_PATH, receipt)
    print(
        f"applied=true positions={len(new_rows)} effective_total={effective_total:.2f} "
        "manual_truth_updated=true broker_read=false automatic_order=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
