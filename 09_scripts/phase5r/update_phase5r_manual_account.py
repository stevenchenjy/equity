#!/usr/bin/env python3
"""Preview or apply a manual cash/share update in one command."""

from __future__ import annotations

import argparse
from datetime import datetime

from phase5r_daily_common import (
    ACCOUNT_STATE_PATH,
    MARKET_SNAPSHOT_PATH,
    POSITIONS_PATH,
    atomic_write_csv,
    atomic_write_json,
    iso_now,
    read_csv,
    read_json,
)


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
    if not ticker or shares < 0 or (entry is not None and entry <= 0):
        raise argparse.ArgumentTypeError("ticker, non-negative shares, and positive entry price are required")
    return ticker, shares, entry


def main() -> int:
    parser = argparse.ArgumentParser(
        epilog=(
            "Example: update_phase5r_manual_account.py --cash 1900 "
            "--position IOT=4@36.44 --position RBRK=2@84.40 --apply"
        )
    )
    parser.add_argument("--cash", type=float, required=True)
    parser.add_argument("--cash-reserved", type=float)
    parser.add_argument("--position", action="append", type=parse_position, default=[])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.cash < 0:
        raise ValueError("cash cannot be negative")
    if not args.position:
        raise ValueError("at least one --position is required; include every current position")
    if len({item[0] for item in args.position}) != len(args.position):
        raise ValueError("position tickers must be unique")

    account = read_json(ACCOUNT_STATE_PATH)
    existing = {row["ticker"].upper(): row for row in read_csv(POSITIONS_PATH)}
    fields = list(read_csv(POSITIONS_PATH)[0].keys())
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
        if quote.get("data_quality_label") not in {"ok", "partial"}:
            raise ValueError(f"current market close is unavailable for {ticker}")
        close = float(quote["last_price"])
        holdings_value += shares * close
        if prior is None:
            prior = {
                "ticker": ticker,
                "entry_date": datetime.now().date().isoformat(),
                "entry_price": f"{entry:.2f}",
                "position_pct": "0",
                "shares_optional": f"{shares:g}",
                "thesis": "Manual position recorded; full research thesis review required.",
                "horizon_class": "long_term_research",
                "planned_review_date": datetime.now().date().isoformat(),
                "max_loss_pct_of_account": "0.50",
                "invalidation_rule": "Review immediately because a complete thesis and invalidation rule are pending.",
                "current_action": "review_required",
                "notes": "Created by the explicit manual account updater; no broker was read.",
            }
        row = dict(prior)
        row["shares_optional"] = f"{shares:g}"
        if entry is not None:
            row["entry_price"] = f"{entry:.2f}"
        new_rows.append(row)

    effective_total = args.cash + holdings_value
    for row in new_rows:
        ticker = row["ticker"].upper()
        shares = float(row["shares_optional"])
        close = float(market[ticker]["last_price"])
        row["position_pct"] = f"{shares * close / effective_total * 100.0:.4f}"
    reserved = account["cash_reserved"] if args.cash_reserved is None else args.cash_reserved
    if float(reserved) < 0 or float(reserved) > args.cash:
        raise ValueError("cash reserved must be between zero and available cash")
    updated_account = dict(account)
    updated_account.update({
        "account_total_value": round(effective_total, 2),
        "cash_available": round(args.cash, 2),
        "cash_reserved": round(float(reserved), 2),
        "last_updated": iso_now(),
    })
    if args.preview:
        print(
            f"preview=true positions={len(new_rows)} cash={args.cash:.2f} "
            f"holdings_at_current_close={holdings_value:.2f} effective_total={effective_total:.2f} "
            "files_changed=false broker_read=false"
        )
        return 0
    atomic_write_csv(POSITIONS_PATH, fields, new_rows)
    atomic_write_json(ACCOUNT_STATE_PATH, updated_account)
    print(
        f"applied=true positions={len(new_rows)} effective_total={effective_total:.2f} "
        "manual_truth_updated=true broker_read=false automatic_order=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
