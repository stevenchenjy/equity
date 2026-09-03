#!/usr/bin/env python3
"""Refresh official SEC filing evidence for held and researched tickers.

This module is read-only with respect to public sources. It never reads email
configuration, connects to a broker, or creates orders.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
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
    ExclusiveFileLock,
)
from phase5r_sec_acceptance import (
    AcceptanceIndexError,
    AcceptanceReconciliationError,
    SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH,
    SEC_ACCEPTANCE_INDEX_PATH,
    load_immutable_acceptance_index,
    make_acceptance_record,
    normalize_acceptance_timestamp,
    reconcile_current_acceptance_records,
    write_acceptance_reconciliation_log,
)
from phase5r_sec_acceptance_extensions import (
    SEC_ACCEPTANCE_EXTENSION_AUDIT_PATH,
    SEC_ACCEPTANCE_EXTENSION_DIR,
    SEC_ACCEPTANCE_EXTENSION_LOCK_PATH,
    ExtensionValidationError,
    extension_acceptance_records,
    load_extension_artifacts,
    plan_unindexed_current_records,
    raw_file_sha256,
    write_extension_admission_audit,
    write_extension_artifact,
)


SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_USER_AGENT_ENV = "PHASE5R_SEC_USER_AGENT"
_SEC_USER_AGENT_MAX_CHARS = 512
# The SEC submissions `recent` arrays can contain issuer-specific legacy rows
# dating back decades. Daily evidence needs a bounded current window; ancient
# malformed legacy metadata must not block current held-company coverage.
SEC_DAILY_SUBMISSION_LOOKBACK_DAYS = 730
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
    "ttm_revenue",
    "ttm_revenue_prior_year",
    "ttm_revenue_yoy_pct",
    "ttm_operating_cash_flow",
    "ttm_capex",
    "ttm_free_cash_flow",
    "ttm_free_cash_flow_margin_pct",
    "diluted_shares_latest",
    "diluted_shares_prior_year",
    "share_dilution_pct",
    "debt_latest",
    "trend_label",
    "data_quality",
    "source_url",
]
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
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
OPERATING_CASH_FLOW_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForProceedsFromOtherPropertyPlantAndEquipment",
)
DILUTED_SHARES_TAGS = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
)
SHARES_OUTSTANDING_TAGS = (
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
)
DEBT_CURRENT_TAGS = (
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtCurrent",
)
DEBT_NONCURRENT_TAGS = (
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "LongTermDebtNoncurrent",
)


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
    score_path = ROOT / "03_source_data" / "phase5r" / "phase5r_b2_signal_scores.csv"
    current_scores = [
        row for row in read_csv(score_path)
        if row.get("ticker", "").strip()
        and row.get("data_quality_label") in {"ok", "partial"}
        and row.get("total_score", "").strip()
    ]
    current_scores.sort(key=lambda row: (-float(row["total_score"]), row["ticker"]))
    watched.add("SPY")
    watched.update(
        row["ticker"].strip().upper()
        for row in current_scores[:8]
        if row["ticker"].strip().upper() != "SPY"
    )
    return sorted(held), sorted(watched | held)


def company_fundamentals_required(ticker: str) -> bool:
    """SPY is the canonical ETF core; company XBRL is not applicable to it."""

    return ticker.strip().upper() != "SPY"


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


def recent_filings(
    payload: dict[str, Any],
    *,
    as_of: date | None = None,
) -> list[dict[str, str]]:
    recent = payload.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    rows: list[dict[str, str]] = []
    oldest_in_scope = (
        as_of - timedelta(days=SEC_DAILY_SUBMISSION_LOOKBACK_DAYS)
        if as_of is not None
        else None
    )
    for index, accession in enumerate(accessions):
        def value(field: str) -> str:
            values = recent.get(field, [])
            return str(values[index]).strip() if index < len(values) else ""

        form = value("form")
        if form not in RELEVANT_FORMS:
            continue
        filing_date = value("filingDate")
        if oldest_in_scope is not None:
            try:
                filing_day = date.fromisoformat(filing_date)
            except ValueError:
                # Keep malformed in-scope-looking metadata so the acceptance
                # validator fails closed instead of silently discarding it.
                filing_day = None
            if filing_day is not None and filing_day < oldest_in_scope:
                continue
        rows.append(
            {
                "accession_number": str(accession).strip(),
                "form": form,
                "filing_date": filing_date,
                "accepted_at": normalize_acceptance_timestamp(
                    value("acceptanceDateTime")
                ),
                "items": value("items"),
                "primary_document": value("primaryDocument"),
            }
        )
    return rows


def current_submission_entity_name(
    payload: dict[str, Any],
    *,
    ticker: str,
    cik: int,
) -> str:
    """Prove that the current SEC submission endpoint identifies this issuer.

    The extension policy relies only on the approved SEC submissions endpoint.
    Its top-level CIK and ticker list must independently agree with the ticker
    map used to construct that endpoint; the bounded official issuer name is
    then retained in a separate extension artifact for auditability.
    """

    if not isinstance(payload, dict):
        raise ExtensionValidationError("SEC acceptance extension submission payload is invalid")
    response_cik = str(payload.get("cik", "")).strip()
    if not response_cik.isdigit() or int(response_cik) != cik:
        raise ExtensionValidationError("SEC acceptance extension CIK identity conflict")
    tickers = payload.get("tickers")
    if not isinstance(tickers, list) or ticker not in {
        str(value).strip().upper() for value in tickers
    }:
        raise ExtensionValidationError("SEC acceptance extension ticker identity conflict")
    entity_name = str(payload.get("name", "")).strip()
    if (
        not entity_name
        or len(entity_name) > 256
        or any(ord(character) < 32 for character in entity_name)
    ):
        raise ExtensionValidationError("SEC acceptance extension entity identity conflict")
    return entity_name


def fact_units(
    payload: dict[str, Any], tags: tuple[str, ...], unit: str = "USD"
) -> list[dict[str, Any]]:
    facts = payload.get("facts", {})
    for taxonomy in ("us-gaap", "ifrs-full"):
        taxonomy_facts = facts.get(taxonomy, {})
        for tag in tags:
            record = taxonomy_facts.get(tag, {})
            units = record.get("units", {})
            values = units.get(unit, [])
            if values:
                return [item for item in values if isinstance(item.get("val"), (int, float))]
    return []


def quarterly_values(
    payload: dict[str, Any], tags: tuple[str, ...], unit: str = "USD"
) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for item in fact_units(payload, tags, unit):
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


def duration_values(
    payload: dict[str, Any], tags: tuple[str, ...], unit: str = "USD"
) -> list[dict[str, Any]]:
    """Return one latest-filed consolidated fact for each duration period."""

    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for item in fact_units(payload, tags, unit):
        if item.get("form") not in {"10-Q", "10-K", "20-F", "40-F"}:
            continue
        try:
            start = datetime.fromisoformat(str(item.get("start", ""))).date()
            end = datetime.fromisoformat(str(item.get("end", ""))).date()
        except ValueError:
            continue
        if start >= end:
            continue
        key = (start.isoformat(), end.isoformat())
        current = selected.get(key)
        if current is None or str(item.get("filed", "")) > str(current.get("filed", "")):
            selected[key] = item
    return sorted(
        selected.values(),
        key=lambda item: (
            str(item.get("end", "")),
            str(item.get("start", "")),
            str(item.get("filed", "")),
        ),
    )


def latest_instant(
    payload: dict[str, Any], tags: tuple[str, ...], unit: str = "USD"
) -> float | None:
    values = [
        item
        for item in fact_units(payload, tags, unit)
        if item.get("form") in {"10-Q", "10-K", "20-F", "40-F"}
        and item.get("end")
    ]
    if not values:
        return None
    latest = max(values, key=lambda item: (str(item.get("end", "")), str(item.get("filed", ""))))
    return float(latest["val"])


def _duration_days(item: dict[str, Any]) -> int:
    start = date.fromisoformat(str(item["start"]))
    end = date.fromisoformat(str(item["end"]))
    return (end - start).days


def _ttm_at(
    values: list[dict[str, Any]], target_end: date
) -> float | None:
    """Derive TTM from an annual fact or annual + YTD - prior YTD."""

    annual = [
        item for item in values
        if date.fromisoformat(str(item["end"])) == target_end
        and item.get("form") in {"10-K", "20-F", "40-F"}
        and 300 <= _duration_days(item) <= 400
    ]
    if annual:
        return float(max(annual, key=lambda item: str(item.get("filed", "")))["val"])

    current_ytd = [
        item for item in values
        if date.fromisoformat(str(item["end"])) == target_end
        and item.get("form") == "10-Q"
        and 60 <= _duration_days(item) <= 300
    ]
    if not current_ytd:
        return None
    current = max(current_ytd, key=_duration_days)
    current_start = date.fromisoformat(str(current["start"]))
    prior_annual = [
        item for item in values
        if item.get("form") in {"10-K", "20-F", "40-F"}
        and 300 <= _duration_days(item) <= 400
        and 0 <= (current_start - date.fromisoformat(str(item["end"]))).days <= 14
    ]
    if not prior_annual:
        return None
    annual_item = max(
        prior_annual,
        key=lambda item: (
            str(item.get("end", "")),
            str(item.get("filed", "")),
        ),
    )
    comparable = [
        item for item in values
        if item.get("form") == "10-Q"
        and 350 <= (
            target_end - date.fromisoformat(str(item["end"]))
        ).days <= 380
        and abs(_duration_days(item) - _duration_days(current)) <= 14
    ]
    if not comparable:
        return None
    prior_ytd = min(
        comparable,
        key=lambda item: (
            abs((target_end - date.fromisoformat(str(item["end"]))).days - 365),
            abs(_duration_days(item) - _duration_days(current)),
            -int(str(item.get("filed", "0000-00-00")).replace("-", "") or 0),
        ),
    )
    return float(annual_item["val"]) + float(current["val"]) - float(prior_ytd["val"])


def trailing_twelve_values(
    payload: dict[str, Any], tags: tuple[str, ...], unit: str = "USD"
) -> tuple[float | None, float | None]:
    """Return current and prior TTM values without summing gapped quarters."""

    values = duration_values(payload, tags, unit)
    if not values:
        return None, None
    target_end = max(date.fromisoformat(str(item["end"])) for item in values)
    prior_ends = sorted(
        {
            date.fromisoformat(str(item["end"]))
            for item in values
            if 350 <= (
                target_end - date.fromisoformat(str(item["end"]))
            ).days <= 380
        },
        key=lambda candidate: abs((target_end - candidate).days - 365),
    )
    prior_end = prior_ends[0] if prior_ends else None
    return (
        _ttm_at(values, target_end),
        _ttm_at(values, prior_end) if prior_end is not None else None,
    )


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
    ttm_revenue, ttm_revenue_prior = trailing_twelve_values(
        payload, REVENUE_TAGS
    )
    ttm_revenue_yoy = (
        (ttm_revenue / ttm_revenue_prior - 1.0) * 100.0
        if ttm_revenue is not None and ttm_revenue_prior not in {None, 0.0}
        else None
    )
    operating_cash_flow, _ = trailing_twelve_values(
        payload, OPERATING_CASH_FLOW_TAGS
    )
    capex, _ = trailing_twelve_values(payload, CAPEX_TAGS)
    free_cash_flow = (
        operating_cash_flow - capex
        if operating_cash_flow is not None and capex is not None
        else None
    )
    free_cash_flow_margin = (
        free_cash_flow / ttm_revenue * 100.0
        if free_cash_flow is not None and ttm_revenue not in {None, 0.0}
        else None
    )
    share_values = quarterly_values(payload, DILUTED_SHARES_TAGS, "shares")
    diluted_shares = (
        float(share_values[-1]["val"])
        if share_values
        else latest_instant(payload, SHARES_OUTSTANDING_TAGS, "shares")
    )
    diluted_prior_frame = ""
    if share_values:
        match = re.fullmatch(
            r"CY(\d{4})Q([1-4])", str(share_values[-1].get("frame", ""))
        )
        if match:
            diluted_prior_frame = (
                f"CY{int(match.group(1)) - 1}Q{match.group(2)}"
            )
    diluted_prior_match = next(
        (
            item for item in share_values
            if str(item.get("frame", "")) == diluted_prior_frame
        ),
        None,
    )
    diluted_prior = (
        float(diluted_prior_match["val"])
        if diluted_prior_match is not None
        else None
    )
    share_dilution = (
        (diluted_shares / diluted_prior - 1.0) * 100.0
        if diluted_shares is not None and diluted_prior not in {None, 0.0}
        else None
    )
    debt_parts = [
        latest_instant(payload, DEBT_CURRENT_TAGS),
        latest_instant(payload, DEBT_NONCURRENT_TAGS),
    ]
    debt = sum(value for value in debt_parts if value is not None)
    if all(value is None for value in debt_parts):
        debt = None
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
        "ttm_revenue": money(ttm_revenue),
        "ttm_revenue_prior_year": money(ttm_revenue_prior),
        "ttm_revenue_yoy_pct": "" if ttm_revenue_yoy is None else f"{ttm_revenue_yoy:.2f}",
        "ttm_operating_cash_flow": money(operating_cash_flow),
        "ttm_capex": money(capex),
        "ttm_free_cash_flow": money(free_cash_flow),
        "ttm_free_cash_flow_margin_pct": "" if free_cash_flow_margin is None else f"{free_cash_flow_margin:.2f}",
        "diluted_shares_latest": money(diluted_shares),
        "diluted_shares_prior_year": money(diluted_prior),
        "share_dilution_pct": "" if share_dilution is None else f"{share_dilution:.2f}",
        "debt_latest": money(debt),
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


def merge_seen_accessions(
    state_seen: dict[str, Any],
    ledger_rows: list[dict[str, str]],
) -> dict[str, set[str]]:
    """Reconcile the mutable state cache with the durable evidence ledger.

    The ledger is the authoritative once-per-accession guard. This prevents a
    missing, stale, or concurrently replaced local state file from appending
    the same SEC filing again on a later scan.
    """

    merged = {
        str(ticker).strip().upper(): {
            str(accession).strip()
            for accession in values
            if str(accession).strip()
        }
        for ticker, values in state_seen.items()
        if isinstance(values, (list, tuple, set))
        and str(ticker).strip()
    }
    for row in ledger_rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        accession = str(row.get("accession_number", "")).strip()
        if ticker and accession:
            merged.setdefault(ticker, set()).add(accession)
    return merged


def sec_user_agent_failure_reason(value: Any) -> str | None:
    """Return a finite configuration result without retaining the value."""

    if not isinstance(value, str) or not value.strip():
        return "sec_user_agent_missing"
    normalized = value.strip()
    if (
        len(normalized) > _SEC_USER_AGENT_MAX_CHARS
        or "\r" in normalized
        or "\n" in normalized
        or "@localhost" in normalized.lower()
        or "@" not in normalized
    ):
        return "sec_user_agent_invalid"
    return None


def write_early_evidence_failure_status(
    *,
    attempt_at: str,
    state: dict[str, Any],
    held_tickers: list[str],
    reason: str,
    network_used: bool,
) -> None:
    """Close the SEC gate before any current evidence artifact can advance."""

    status = {
        "schema_version": "phase5r_daily_evidence_status_v1",
        "last_attempt_at": attempt_at,
        "last_success_at": state.get("last_success_at", ""),
        "scan_status": "failed",
        "reason": reason,
        "held_tickers": held_tickers,
        "held_coverage_complete": False,
        "new_material_event_count": 0,
        "network_used": network_used,
    }
    atomic_write_json(EVIDENCE_STATUS_PATH, status)
    log_daily_run(
        component="evidence_refresh",
        run_mode="live_public_read",
        outcome="failed",
        reason=reason,
    )


def acceptance_index_failure_reason(exc: AcceptanceIndexError) -> str:
    """Map acceptance validation failures to closed, non-sensitive status codes."""

    if isinstance(exc, ExtensionValidationError):
        message = str(exc)
        if "duplicate accession" in message:
            return "sec_acceptance_extension_duplicate_accession"
        if "identity" in message or "ticker" in message or "CIK" in message:
            return "sec_acceptance_extension_identity_conflict"
        if "source" in message or "provenance" in message:
            return "sec_acceptance_extension_provenance_invalid"
        if "future" in message:
            return "sec_acceptance_extension_future_timestamp"
        return "sec_acceptance_extension_validation_failed"
    if isinstance(exc, AcceptanceReconciliationError):
        message = str(exc)
        if "accession is absent from immutable index" in message:
            return "sec_acceptance_unindexed_accession"
        if "identity fields differ" in message:
            return "sec_acceptance_identity_mismatch"
        if "timestamp is not a permitted representation difference" in message:
            return "sec_acceptance_timestamp_unreconciled"
        if "timestamp is later than reconciliation time" in message:
            return "sec_acceptance_current_future_timestamp"
        if "current SEC response contains a duplicate accession" in message:
            return "sec_acceptance_current_duplicate_accession"
        if "immutable SEC index contains a duplicate accession" in message:
            return "sec_acceptance_historical_duplicate_accession"
        return "sec_acceptance_reconciliation_rejected"
    message = str(exc)
    if "conflicting SEC acceptance records" in message:
        return "sec_acceptance_conflict"
    if "later than index generation time" in message:
        return "sec_acceptance_future_timestamp"
    return "sec_acceptance_index_invalid"


def count_unindexed_acceptance_accessions(
    *,
    historical_records: list[dict[str, str]],
    current_records: list[dict[str, str]],
) -> int:
    """Return a safe aggregate only; never retain or emit accession values."""

    historical_accessions = {
        str(row.get("accession_number", "")).strip()
        for row in historical_records
    }
    current_accessions = {
        str(row.get("accession_number", "")).strip()
        for row in current_records
    }
    current_accessions.discard("")
    return len(current_accessions - historical_accessions)


def write_acceptance_index_failure_status(
    *,
    attempt_at: str,
    state: dict[str, Any],
    held_tickers: list[str],
    reason: str,
    unindexed_accession_count: int = 0,
) -> None:
    """Durably close the evidence gate without persisting uncommitted SEC data."""

    status = {
        "schema_version": "phase5r_daily_evidence_status_v1",
        "last_attempt_at": attempt_at,
        "last_success_at": state.get("last_success_at", ""),
        "scan_status": "failed",
        "reason": reason,
        "held_tickers": held_tickers,
        "scanned_tickers": [],
        "held_coverage_complete": False,
        "held_failures": held_tickers,
        "held_fundamental_coverage_complete": False,
        "held_fundamental_failures": held_tickers,
        "optional_missing_tickers": [],
        "request_errors": [reason],
        "fundamental_request_errors": [],
        "fundamental_rows": 0,
        "filings_recorded": 0,
        "baseline_mode": not bool(state.get("initialized")),
        "new_material_event_count": 0,
        "new_material_accessions": [],
        "unindexed_accession_count": unindexed_accession_count,
        "network_used": True,
    }
    atomic_write_json(EVIDENCE_STATUS_PATH, status)
    log_daily_run(
        component="evidence_refresh",
        run_mode="live_public_read",
        outcome="failed",
        reason=reason,
    )


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
    state = read_json(
        EVIDENCE_STATE_PATH,
        {
            "schema_version": "phase5r_daily_evidence_v1",
            "initialized": False,
            "seen_accessions": {},
        },
    )
    user_agent = os.environ.get(SEC_USER_AGENT_ENV, "")
    user_agent_reason = sec_user_agent_failure_reason(user_agent)
    if user_agent_reason is not None:
        write_early_evidence_failure_status(
            attempt_at=attempt_at,
            state=state,
            held_tickers=held_tickers,
            reason=user_agent_reason,
            network_used=False,
        )
        print(f"scan_status=failed reason={user_agent_reason}")
        return 1
    initialized = bool(state.get("initialized"))
    seen_by_ticker = merge_seen_accessions(
        state.get("seen_accessions", {}),
        read_csv(EVIDENCE_LEDGER_PATH),
    )
    errors: list[str] = []
    fundamental_errors: list[str] = []
    fundamental_rows: list[dict[str, str]] = []
    missing_tickers: list[str] = []
    new_material_events: list[dict[str, str]] = []
    # Bind the separate extension layer to the exact historical index bytes.
    # The historical index itself remains read-only throughout this refresh.
    try:
        prior_immutable_index_sha256 = raw_file_sha256(SEC_ACCEPTANCE_INDEX_PATH)
        prior_acceptance_index = load_immutable_acceptance_index(
            SEC_ACCEPTANCE_INDEX_PATH
        )
    except AcceptanceIndexError as exc:
        reason = acceptance_index_failure_reason(exc)
        write_acceptance_index_failure_status(
            attempt_at=attempt_at,
            state=state,
            held_tickers=held_tickers,
            reason=reason,
        )
        print(f"scan_status=failed reason={reason}")
        return 1
    except OSError:
        reason = "sec_acceptance_index_unavailable"
        write_acceptance_index_failure_status(
            attempt_at=attempt_at,
            state=state,
            held_tickers=held_tickers,
            reason=reason,
        )
        print(f"scan_status=failed reason={reason}")
        return 1
    new_acceptance_records: list[dict[str, str]] = []
    forms_by_accession: dict[str, str] = {}
    entity_by_ticker: dict[str, str] = {}
    pending_ledger_rows: list[dict[str, str]] = []
    filings_recorded = 0

    try:
        ticker_map = load_ticker_map(user_agent, args.force_ticker_map)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        write_early_evidence_failure_status(
            attempt_at=attempt_at,
            state=state,
            held_tickers=held_tickers,
            reason="sec_ticker_map_unavailable",
            network_used=True,
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
            filings = recent_filings(
                payload,
                as_of=date.fromisoformat(cycle_date()),
            )
            submission_url = SEC_SUBMISSIONS_URL.format(cik=cik)
            entity_by_ticker[ticker] = current_submission_entity_name(
                payload,
                ticker=ticker,
                cik=cik,
            )
            for filing in filings:
                acceptance_record = make_acceptance_record(
                    accession_number=filing["accession_number"],
                    ticker=ticker,
                    cik=cik,
                    filing_date=filing["filing_date"],
                    accepted_at=filing["accepted_at"],
                    source_url=submission_url,
                )
                new_acceptance_records.append(acceptance_record)
                accession = acceptance_record["accession_number"]
                prior_form = forms_by_accession.get(accession)
                if prior_form is not None and prior_form != filing["form"]:
                    raise ExtensionValidationError(
                        "SEC acceptance extension filing form identity conflict"
                    )
                forms_by_accession[accession] = filing["form"]
        except AcceptanceIndexError as exc:
            reason = acceptance_index_failure_reason(exc)
            write_acceptance_index_failure_status(
                attempt_at=attempt_at,
                state=state,
                held_tickers=held_tickers,
                reason=reason,
            )
            print(f"scan_status=failed reason={reason}")
            return 1

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
            # Do not append an uncommitted filing row.  The acceptance index
            # is validated as one merged snapshot below before any current
            # evidence artifact is allowed to advance.
            pending_ledger_rows.append(row)
            filings_recorded += 1
            existing.add(accession)
            if is_new and row["material_event"] == "yes":
                new_material_events.append(row)

        if company_fundamentals_required(ticker):
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
        if company_fundamentals_required(ticker)
        and fundamental_by_ticker.get(ticker, {}).get("data_quality") != "ok"
    )
    # Validate current official records against the effective acceptance set
    # before mutating current fundamentals or the filing ledger. The effective
    # set is the immutable historical index plus fully validated, separately
    # versioned extensions. The historical index is never overwritten.
    historical_unindexed_accession_count = count_unindexed_acceptance_accessions(
        historical_records=prior_acceptance_index["records"],
        current_records=new_acceptance_records,
    )
    extension_artifacts: list[dict[str, Any]] = []
    extension_admission_count = 0
    unindexed_accession_count = historical_unindexed_accession_count
    try:
        with ExclusiveFileLock(SEC_ACCEPTANCE_EXTENSION_LOCK_PATH):
            if raw_file_sha256(SEC_ACCEPTANCE_INDEX_PATH) != prior_immutable_index_sha256:
                raise ExtensionValidationError(
                    "immutable SEC acceptance index changed during refresh"
                )
            locked_acceptance_index = load_immutable_acceptance_index(
                SEC_ACCEPTANCE_INDEX_PATH
            )
            if locked_acceptance_index != prior_acceptance_index:
                raise ExtensionValidationError(
                    "immutable SEC acceptance index content changed during refresh"
                )
            retained_extensions = load_extension_artifacts(
                historical_index_sha256=prior_immutable_index_sha256,
                directory=SEC_ACCEPTANCE_EXTENSION_DIR,
            )
            planned_extensions, extension_admission_count = plan_unindexed_current_records(
                historical_records=prior_acceptance_index["records"],
                extension_artifacts=retained_extensions,
                current_records=new_acceptance_records,
                forms_by_accession=forms_by_accession,
                expected_cik_by_ticker={
                    ticker: str(cik) for ticker, cik in ticker_map.items()
                },
                expected_entity_by_ticker=entity_by_ticker,
                permitted_forms=RELEVANT_FORMS,
                historical_index_sha256=prior_immutable_index_sha256,
                admitted_at=iso_now(),
            )
            effective_acceptance_records = [
                *prior_acceptance_index["records"],
                *extension_acceptance_records(planned_extensions),
            ]
            unindexed_accession_count = count_unindexed_acceptance_accessions(
                historical_records=effective_acceptance_records,
                current_records=new_acceptance_records,
            )
            if unindexed_accession_count:
                raise ExtensionValidationError(
                    "SEC acceptance extension left an unindexed accession"
                )
            reconciliations = reconcile_current_acceptance_records(
                historical_records=effective_acceptance_records,
                current_records=new_acceptance_records,
                reconciled_at=iso_now(),
            )
            # All validation precedes persistence. The timestamp audit is
            # append-only; the extension and its raw-byte-bound admission
            # audit are written only after the whole source batch reconciles.
            write_acceptance_reconciliation_log(
                reconciliations,
                path=SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH,
            )
            if extension_admission_count:
                write_extension_artifact(
                    planned_extensions[-1],
                    directory=SEC_ACCEPTANCE_EXTENSION_DIR,
                )
            write_extension_admission_audit(
                planned_extensions,
                path=SEC_ACCEPTANCE_EXTENSION_AUDIT_PATH,
                directory=SEC_ACCEPTANCE_EXTENSION_DIR,
            )
            extension_artifacts = planned_extensions
    except AcceptanceIndexError as exc:
        reason = acceptance_index_failure_reason(exc)
        write_acceptance_index_failure_status(
            attempt_at=attempt_at,
            state=state,
            held_tickers=held_tickers,
            reason=reason,
            unindexed_accession_count=historical_unindexed_accession_count,
        )
        print(f"scan_status=failed reason={reason}")
        return 1
    except RuntimeError:
        reason = "sec_acceptance_extension_lock_unavailable"
        write_acceptance_index_failure_status(
            attempt_at=attempt_at,
            state=state,
            held_tickers=held_tickers,
            reason=reason,
            unindexed_accession_count=historical_unindexed_accession_count,
        )
        print(f"scan_status=failed reason={reason}")
        return 1
    except (OSError, UnicodeError, csv.Error):
        reason = "sec_acceptance_extension_persistence_unavailable"
        write_acceptance_index_failure_status(
            attempt_at=attempt_at,
            state=state,
            held_tickers=held_tickers,
            reason=reason,
            unindexed_accession_count=historical_unindexed_accession_count,
        )
        print(f"scan_status=failed reason={reason}")
        return 1

    # Reconciliation-log persistence occurs before any current ledger or
    # fundamentals write so a log failure cannot advance either artifact.
    for row in pending_ledger_rows:
        append_csv_durable(EVIDENCE_LEDGER_PATH, LEDGER_FIELDS, row)
    atomic_write_csv(FUNDAMENTALS_PATH, FUNDAMENTAL_FIELDS, fundamental_rows)
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
        "sec_acceptance_historical_record_count": prior_acceptance_index["record_count"],
        "sec_acceptance_record_count": (
            prior_acceptance_index["record_count"]
            + len(extension_acceptance_records(extension_artifacts))
        ),
        "sec_acceptance_source": prior_acceptance_index["source_authority"],
        "sec_acceptance_reconciliation_count": len(reconciliations),
        "sec_acceptance_extension_version_count": len(extension_artifacts),
        "sec_acceptance_extension_admission_count": extension_admission_count,
        "unindexed_accession_count": unindexed_accession_count,
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
