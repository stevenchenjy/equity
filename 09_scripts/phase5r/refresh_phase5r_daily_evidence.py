#!/usr/bin/env python3
"""Refresh official SEC filing evidence for held and researched tickers.

This module is read-only with respect to public sources. It never reads email
configuration, connects to a broker, or creates orders.
"""

from __future__ import annotations

import argparse
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from phase5r_daily_common import (
    EVIDENCE_LEDGER_PATH,
    EVIDENCE_STATE_PATH,
    EVIDENCE_STATUS_PATH,
    FUNDAMENTALS_PATH,
    NEW_CANDIDATE_PATH,
    POSITION_RECOMMENDATION_PATH,
    POSITIONS_PATH,
    ROOT,
    SEC_TICKER_MAP_PATH,
    atomic_write_json,
    atomic_write_csv,
    canonical_sha256,
    cycle_date,
    iso_now,
    read_csv,
    read_json,
    log_daily_run,
    append_csv_durable,
)
from phase5r_sec_acceptance import (
    AcceptanceIndexError,
    build_acceptance_index,
    load_acceptance_index,
    make_acceptance_record,
    normalize_acceptance_timestamp,
    write_acceptance_index,
)


SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
RELEVANT_FORMS = {
    "10-K",
    "10-Q",
    "20-F",
    "40-F",
    "8-K",
    "6-K",
    "DEF 14A",
    "S-3",
    "S-3ASR",
    "424B2",
    "424B3",
    "424B4",
    "424B5",
}
HIGH_MATERIALITY_FORMS = {
    "10-K",
    "10-Q",
    "20-F",
    "40-F",
    "S-3",
    "S-3ASR",
    "424B2",
    "424B3",
    "424B4",
    "424B5",
}
EIGHT_K_MATERIAL_ITEMS = {
    "1.01",
    "1.02",
    "2.01",
    "2.02",
    "2.05",
    "2.06",
    "3.01",
    "3.02",
    "4.01",
    "4.02",
    "5.01",
    "5.02",
    "7.01",
    "8.01",
}
LEDGER_FIELDS = [
    "detected_at",
    "cycle_date",
    "ticker",
    "cik",
    "form",
    "filing_date",
    "accession_number",
    "items",
    "primary_document",
    "source_url",
    "metadata_sha256",
    "is_new",
    "baseline_record",
    "materiality",
    "material_event",
    "review_required",
]
FUNDAMENTAL_FIELDS = [
    "ticker",
    "cik",
    "fetched_at",
    "latest_period_end",
    "latest_frame",
    "revenue_latest",
    "revenue_prior_year",
    "revenue_yoy_pct",
    "net_income_latest",
    "net_margin_pct",
    "cash_latest",
    "assets_latest",
    "liabilities_latest",
    "trend_label",
    "data_quality",
    "source_url",
]
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
NET_INCOME_TAGS = ("NetIncomeLoss", "ProfitLoss")
CASH_TAGS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
ASSET_TAGS = ("Assets",)
LIABILITY_TAGS = ("Liabilities",)


def request_json(url: str, user_agent: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return __import__("json").loads(response.read().decode("utf-8"))


def researched_tickers() -> tuple[list[str], list[str]]:
    held = {
        row.get("ticker", "").strip().upper()
        for row in read_csv(POSITIONS_PATH)
        if row.get("ticker", "").strip()
    }
    watched: set[str] = set()
    for source in (POSITION_RECOMMENDATION_PATH, NEW_CANDIDATE_PATH):
        for row in read_csv(source):
            ticker = row.get("ticker", "").strip().upper()
            if ticker:
                watched.add(ticker)
    queue_path = (
        ROOT
        / "04_research"
        / "realtime_stock_picker_phase5r"
        / "phase5r_c5_company_research_packets.csv"
    )
    for row in read_csv(queue_path):
        ticker = row.get("ticker", "").strip().upper()
        if ticker:
            watched.add(ticker)
    return sorted(held), sorted(watched | held)


def load_ticker_map(user_agent: str, force: bool) -> dict[str, int]:
    cache_fresh = (
        SEC_TICKER_MAP_PATH.exists()
        and (time.time() - SEC_TICKER_MAP_PATH.stat().st_mtime) < 24 * 60 * 60
    )
    if cache_fresh and not force:
        cached = read_json(SEC_TICKER_MAP_PATH, {})
        return {str(key).upper(): int(value) for key, value in cached.items()}
    raw = request_json(SEC_TICKER_URL, user_agent)
    ticker_map = {
        str(record["ticker"]).upper(): int(record["cik_str"])
        for record in raw.values()
        if record.get("ticker") and record.get("cik_str")
    }
    atomic_write_json(SEC_TICKER_MAP_PATH, ticker_map)
    return ticker_map


def recent_filings(payload: dict[str, Any]) -> list[dict[str, str]]:
    recent = payload.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    rows: list[dict[str, str]] = []
    for index, accession in enumerate(accessions):
        def value(field: str) -> str:
            values = recent.get(field, [])
            return str(values[index]).strip() if index < len(values) else ""

        form = value("form")
        if form not in RELEVANT_FORMS:
            continue
        rows.append(
            {
                "accession_number": str(accession).strip(),
                "form": form,
                "filing_date": value("filingDate"),
                "accepted_at": normalize_acceptance_timestamp(
                    value("acceptanceDateTime")
                ),
                "items": value("items"),
                "primary_document": value("primaryDocument"),
            }
        )
    return rows


def fact_units(payload: dict[str, Any], tags: tuple[str, ...]) -> list[dict[str, Any]]:
    facts = payload.get("facts", {})
    for taxonomy in ("us-gaap", "ifrs-full"):
        taxonomy_facts = facts.get(taxonomy, {})
        for tag in tags:
            record = taxonomy_facts.get(tag, {})
            units = record.get("units", {})
            values = units.get("USD", [])
            if values:
                return [item for item in values if isinstance(item.get("val"), (int, float))]
    return []


def quarterly_values(payload: dict[str, Any], tags: tuple[str, ...]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for item in fact_units(payload, tags):
        frame = str(item.get("frame", ""))
        if not re.fullmatch(r"CY\d{4}Q[1-4]", frame):
            continue
        if item.get("form") not in {"10-Q", "10-K", "20-F", "40-F"}:
            continue
        try:
            duration_days = (
                datetime.fromisoformat(str(item.get("end", ""))).date()
                - datetime.fromisoformat(str(item.get("start", ""))).date()
            ).days
        except ValueError:
            continue
        if not 60 <= duration_days <= 130:
            continue
        current = selected.get(frame)
        if current is None or str(item.get("filed", "")) > str(current.get("filed", "")):
            selected[frame] = item
    return sorted(selected.values(), key=lambda item: str(item.get("frame", "")))


def latest_instant(payload: dict[str, Any], tags: tuple[str, ...]) -> float | None:
    values = [
        item
        for item in fact_units(payload, tags)
        if item.get("form") in {"10-Q", "10-K", "20-F", "40-F"}
        and item.get("end")
    ]
    if not values:
        return None
    latest = max(values, key=lambda item: (str(item.get("end", "")), str(item.get("filed", ""))))
    return float(latest["val"])


def money(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def fundamental_row(
    ticker: str, cik: int, payload: dict[str, Any], fetched_at: str
) -> dict[str, str]:
    revenue = quarterly_values(payload, REVENUE_TAGS)
    latest = revenue[-1] if revenue else None
    latest_frame = str(latest.get("frame", "")) if latest else ""
    prior_frame = ""
    if latest_frame:
        match = re.fullmatch(r"CY(\d{4})Q([1-4])", latest_frame)
        if match:
            prior_frame = f"CY{int(match.group(1)) - 1}Q{match.group(2)}"
    prior = next(
        (item for item in revenue if str(item.get("frame", "")) == prior_frame),
        None,
    )
    revenue_latest = float(latest["val"]) if latest else None
    revenue_prior = float(prior["val"]) if prior else None
    revenue_yoy = (
        (revenue_latest / revenue_prior - 1.0) * 100.0
        if revenue_latest is not None and revenue_prior not in {None, 0.0}
        else None
    )
    net_income_values = quarterly_values(payload, NET_INCOME_TAGS)
    net_income_match = next(
        (
            item
            for item in reversed(net_income_values)
            if str(item.get("frame", "")) == latest_frame
        ),
        None,
    )
    net_income = float(net_income_match["val"]) if net_income_match else None
    net_margin = (
        net_income / revenue_latest * 100.0
        if net_income is not None and revenue_latest not in {None, 0.0}
        else None
    )
    cash = latest_instant(payload, CASH_TAGS)
    assets = latest_instant(payload, ASSET_TAGS)
    liabilities = latest_instant(payload, LIABILITY_TAGS)
    if revenue_yoy is None:
        trend = "insufficient_trend"
    elif revenue_yoy >= 15.0:
        trend = "strong_growth"
    elif revenue_yoy >= 5.0:
        trend = "growth"
    elif revenue_yoy >= 0.0:
        trend = "stable"
    else:
        trend = "contracting"
    if revenue_latest is not None and revenue_prior is not None and cash is not None:
        quality = "ok"
    elif revenue_latest is not None:
        quality = "partial"
    else:
        quality = "unavailable"
    return {
        "ticker": ticker,
        "cik": str(cik),
        "fetched_at": fetched_at,
        "latest_period_end": str(latest.get("end", "")) if latest else "",
        "latest_frame": latest_frame,
        "revenue_latest": money(revenue_latest),
        "revenue_prior_year": money(revenue_prior),
        "revenue_yoy_pct": "" if revenue_yoy is None else f"{revenue_yoy:.2f}",
        "net_income_latest": money(net_income),
        "net_margin_pct": "" if net_margin is None else f"{net_margin:.2f}",
        "cash_latest": money(cash),
        "assets_latest": money(assets),
        "liabilities_latest": money(liabilities),
        "trend_label": trend,
        "data_quality": quality,
        "source_url": SEC_COMPANYFACTS_URL.format(cik=cik),
    }


def classify_materiality(form: str, items: str) -> tuple[str, str, str]:
    if form in HIGH_MATERIALITY_FORMS:
        return "high", "yes", "yes"
    if form == "8-K":
        item_set = {part.strip() for part in items.split(",") if part.strip()}
        if item_set & EIGHT_K_MATERIAL_ITEMS:
            return "high", "yes", "yes"
        return "medium", "no", "no"
    if form in {"6-K", "DEF 14A"}:
        return "medium", "yes", "yes"
    return "low", "no", "no"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="static no-network check")
    parser.add_argument("--force-ticker-map", action="store_true")
    args = parser.parse_args()

    held_tickers, all_tickers = researched_tickers()
    if not held_tickers:
        raise RuntimeError("no held tickers found")
    if args.check:
        print(
            f"safe_check_passed=true held={','.join(held_tickers)} "
            f"universe_count={len(all_tickers)} network_used=no"
        )
        return 0

    attempt_at = iso_now()
    user_agent = os.environ.get(
        "PHASE5R_SEC_USER_AGENT",
        "Phase5R-LocalResearch/1.0 research-contact@localhost",
    )
    state = read_json(
        EVIDENCE_STATE_PATH,
        {
            "schema_version": "phase5r_daily_evidence_v1",
            "initialized": False,
            "seen_accessions": {},
        },
    )
    initialized = bool(state.get("initialized"))
    seen_by_ticker = {
        str(ticker).upper(): set(values)
        for ticker, values in state.get("seen_accessions", {}).items()
    }
    errors: list[str] = []
    fundamental_errors: list[str] = []
    fundamental_rows: list[dict[str, str]] = []
    missing_tickers: list[str] = []
    new_material_events: list[dict[str, str]] = []
    prior_acceptance_index = load_acceptance_index()
    new_acceptance_records: list[dict[str, str]] = []
    filings_recorded = 0

    try:
        ticker_map = load_ticker_map(user_agent, args.force_ticker_map)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        status = {
            "schema_version": "phase5r_daily_evidence_status_v1",
            "last_attempt_at": attempt_at,
            "last_success_at": state.get("last_success_at", ""),
            "scan_status": "failed",
            "reason": "sec_ticker_map_unavailable",
            "held_tickers": held_tickers,
            "held_coverage_complete": False,
            "new_material_event_count": 0,
            "network_used": True,
        }
        atomic_write_json(EVIDENCE_STATUS_PATH, status)
        log_daily_run(
            component="evidence_refresh",
            run_mode="live_public_read",
            outcome="failed",
            reason="sec_ticker_map_unavailable",
        )
        print(f"scan_status=failed reason=sec_ticker_map_unavailable type={type(exc).__name__}")
        return 1

    for ticker in all_tickers:
        cik = ticker_map.get(ticker)
        if not cik:
            missing_tickers.append(ticker)
            continue
        try:
            payload = request_json(SEC_SUBMISSIONS_URL.format(cik=cik), user_agent)
            time.sleep(0.20)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            errors.append(f"{ticker}:{type(exc).__name__}")
            continue

        try:
            filings = recent_filings(payload)
            submission_url = SEC_SUBMISSIONS_URL.format(cik=cik)
            new_acceptance_records.extend(
                make_acceptance_record(
                    accession_number=filing["accession_number"],
                    ticker=ticker,
                    cik=cik,
                    filing_date=filing["filing_date"],
                    accepted_at=filing["accepted_at"],
                    source_url=submission_url,
                )
                for filing in filings
                if filing["accepted_at"]
            )
        except AcceptanceIndexError as exc:
            errors.append(f"{ticker}:{type(exc).__name__}")
            continue

        existing = seen_by_ticker.setdefault(ticker, set())
        for filing in filings:
            accession = filing["accession_number"]
            if not accession or accession in existing:
                continue
            is_new = initialized
            baseline = not initialized
            materiality, material_event, review_required = classify_materiality(
                filing["form"], filing["items"]
            )
            accession_compact = accession.replace("-", "")
            document = filing["primary_document"]
            source_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession_compact}/{document}"
                if document
                else f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_compact}/"
            )
            metadata = {
                "ticker": ticker,
                "cik": cik,
                **filing,
                "source_url": source_url,
            }
            row = {
                "detected_at": attempt_at,
                "cycle_date": cycle_date(),
                "ticker": ticker,
                "cik": str(cik),
                **filing,
                "source_url": source_url,
                "metadata_sha256": canonical_sha256(metadata),
                "is_new": "yes" if is_new else "no",
                "baseline_record": "yes" if baseline else "no",
                "materiality": materiality,
                "material_event": material_event if is_new else "no",
                "review_required": review_required if is_new else "no",
            }
            append_csv_durable(EVIDENCE_LEDGER_PATH, LEDGER_FIELDS, row)
            filings_recorded += 1
            existing.add(accession)
            if is_new and row["material_event"] == "yes":
                new_material_events.append(row)

        if ticker != "SPY":
            try:
                companyfacts = request_json(
                    SEC_COMPANYFACTS_URL.format(cik=cik), user_agent
                )
                time.sleep(0.20)
                fundamental_rows.append(
                    fundamental_row(ticker, cik, companyfacts, attempt_at)
                )
            except (OSError, ValueError, urllib.error.URLError) as exc:
                fundamental_errors.append(f"{ticker}:{type(exc).__name__}")

    held_failures = sorted(
        ticker
        for ticker in held_tickers
        if ticker in missing_tickers or any(item.startswith(f"{ticker}:") for item in errors)
    )
    fundamental_by_ticker = {row["ticker"]: row for row in fundamental_rows}
    held_fundamental_failures = sorted(
        ticker
        for ticker in held_tickers
        if fundamental_by_ticker.get(ticker, {}).get("data_quality") != "ok"
    )
    atomic_write_csv(FUNDAMENTALS_PATH, FUNDAMENTAL_FIELDS, fundamental_rows)
    acceptance_index = build_acceptance_index(
        prior_records=prior_acceptance_index["records"],
        new_records=new_acceptance_records,
        generated_at=iso_now(),
    )
    write_acceptance_index(acceptance_index)
    success_at = iso_now()
    state.update(
        {
            "schema_version": "phase5r_daily_evidence_v1",
            "initialized": True,
            "last_attempt_at": attempt_at,
            "last_success_at": success_at if not held_failures else state.get("last_success_at", ""),
            "seen_accessions": {
                ticker: sorted(accessions)[-500:]
                for ticker, accessions in sorted(seen_by_ticker.items())
            },
        }
    )
    atomic_write_json(EVIDENCE_STATE_PATH, state)

    scan_status = "ok" if not held_failures else "held_coverage_failed"
    status = {
        "schema_version": "phase5r_daily_evidence_status_v1",
        "last_attempt_at": attempt_at,
        "last_success_at": success_at if scan_status == "ok" else state.get("last_success_at", ""),
        "scan_status": scan_status,
        "reason": "complete" if scan_status == "ok" else "held_ticker_sec_scan_failed",
        "held_tickers": held_tickers,
        "scanned_tickers": sorted(
            set(all_tickers) - set(missing_tickers) - {item.split(":", 1)[0] for item in errors}
        ),
        "held_coverage_complete": not held_failures,
        "held_failures": held_failures,
        "held_fundamental_coverage_complete": not held_fundamental_failures,
        "held_fundamental_failures": held_fundamental_failures,
        "optional_missing_tickers": sorted(set(missing_tickers) - set(held_tickers)),
        "request_errors": errors,
        "fundamental_request_errors": fundamental_errors,
        "fundamental_rows": len(fundamental_rows),
        "filings_recorded": filings_recorded,
        "baseline_mode": not initialized,
        "new_material_event_count": len(new_material_events),
        "new_material_accessions": [
            row["accession_number"] for row in new_material_events
        ],
        "sec_acceptance_record_count": acceptance_index["record_count"],
        "sec_acceptance_source": acceptance_index["source_authority"],
        "network_used": True,
    }
    atomic_write_json(EVIDENCE_STATUS_PATH, status)
    log_daily_run(
        component="evidence_refresh",
        run_mode="live_public_read",
        outcome="passed" if scan_status == "ok" else "failed",
        reason=status["reason"],
    )
    print(
        f"scan_status={scan_status} held_coverage_complete="
        f"{str(not held_failures).lower()} new_material_events={len(new_material_events)} "
        f"baseline_mode={str(not initialized).lower()}"
    )
    return 0 if scan_status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
