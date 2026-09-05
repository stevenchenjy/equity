#!/usr/bin/env python3
"""Explicit public-SEC diagnostic with immutable raw response caching.

Never writes canonical fundamentals or decisions. --fetch permits public
companyfacts/submissions requests only; otherwise re-evaluates cached bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from phase5r_daily_common import ROOT, atomic_write_json, atomic_write_text, iso_now, read_json
from refresh_phase5r_daily_evidence import fundamental_row, fact_units, SEC_USER_AGENT_ENV, sec_user_agent_failure_reason


def fetch(url: str, user_agent: str, root: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError("SEC response exceeds diagnostic bound")
    json.loads(raw)
    path = root / (hashlib.sha256(raw).hexdigest() + ".json")
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("immutable SEC cache mismatch")
    else:
        atomic_write_text(path, raw.decode("utf-8"))
    return path


def acceptance_map(submissions: dict) -> dict[str, str]:
    recent = submissions.get("filings", {}).get("recent", {})
    return dict(zip(recent.get("accessionNumber", []), recent.get("acceptanceDateTime", [])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--ticker-map", type=Path, default=ROOT / "03_source_data/phase5r/phase5r_sec_ticker_map.local.json")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    tickers = sorted(set(args.tickers.upper().split(",")))
    if len(tickers) > 12 or any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", ticker) for ticker in tickers):
        raise ValueError("bounded valid ticker list required")
    mapping = read_json(args.ticker_map)
    user_agent = os.environ.get(SEC_USER_AGENT_ENV, "")
    if args.fetch and sec_user_agent_failure_reason(user_agent):
        raise ValueError("valid public SEC user agent required")
    results = []
    for ticker in tickers:
        cik = int(mapping[ticker])
        root = args.cache_root / ticker
        receipt_path = root / "latest_receipt.json"
        if args.fetch:
            acquired = iso_now()
            facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
            submissions_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
            facts_path = fetch(facts_url, user_agent, root)
            time.sleep(0.2)
            submissions_path = fetch(submissions_url, user_agent, root)
            receipt = {"ticker": ticker, "cik": cik, "fetched_at": acquired, "companyfacts_url": facts_url,
                       "companyfacts_sha256": facts_path.stem, "submissions_url": submissions_url,
                       "submissions_sha256": submissions_path.stem, "canonical_effect": False}
            atomic_write_json(receipt_path, receipt)
        else:
            receipt = read_json(receipt_path)
        payloads = []
        for key in ("companyfacts_sha256", "submissions_sha256"):
            digest = receipt[key]
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid cache identity")
            raw = (root / f"{digest}.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("cached SEC response hash mismatch")
            payloads.append(json.loads(raw))
        facts, submissions = payloads
        accepted = acceptance_map(submissions)
        row = fundamental_row(ticker, cik, facts, receipt["fetched_at"], acceptance_by_accession=accepted)
        end = row["latest_period_end"]
        relevant = {}
        for tag in facts.get("facts", {}).get("us-gaap", {}):
            if re.search(r"Debt|Borrow|NotesPayable|CreditFacility.*Outstanding|DilutedShares|SharesOutstanding|PaymentsToAcquireProperty|PaymentsForProceedsFromOtherProperty", tag):
                values = fact_units(facts, (tag,), "shares" if "Shares" in tag else "USD", as_of=datetime.fromisoformat(receipt["fetched_at"]), acceptance_by_accession=accepted)
                current = [item for item in values if item["end"] == end]
                if current:
                    relevant[tag] = [{key: item.get(key) for key in ("start", "end", "val", "filed", "accn")} for item in sorted(current, key=lambda item: item["filed"])[-3:]]
        result = {"ticker": ticker, "receipt": receipt, "fundamental_row": row, "reported_relevant_tags": relevant}
        atomic_write_json(root / "audit.json", result)
        results.append({"ticker": ticker, "period": end, "quality": row["data_quality"], "valuation_quality": row["valuation_input_quality"], "limitations": row["valuation_input_limitations"], "reported_tags": relevant})
        time.sleep(0.2)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
