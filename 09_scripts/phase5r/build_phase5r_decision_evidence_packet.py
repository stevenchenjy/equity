#!/usr/bin/env python3
"""Build one immutable, sanitized Phase 5R model-evidence packet.

The packet contains public research and coarse portfolio constraints.  It never
contains SMTP configuration, credentials, identity fields, exact account
dollars, order details, or a capability to send/execute anything.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from phase5r_daily_common import (
    ACCOUNT_STATE_PATH,
    DAILY_DECISION_JSON_PATH,
    ET,
    EVIDENCE_LEDGER_PATH,
    EVIDENCE_STATUS_PATH,
    FUNDAMENTALS_PATH,
    MARKET_QUALITY_PATH,
    MARKET_SNAPSHOT_PATH,
    NEW_CANDIDATE_PATH,
    POSITION_RECOMMENDATION_PATH,
    POSITIONS_PATH,
    ROOT,
    atomic_write_json,
    canonical_sha256,
    cycle_date,
    iso_now,
    read_csv,
    read_json,
    sha256_file,
)
from phase5r_llm_contract import PACKET_SCHEMA_VERSION, validate_packet
from phase5r_evidence_freshness import build_evidence_freshness_receipt
from phase5r_return_objective import return_objective_payload
from phase5r_sec_acceptance import acceptance_map
from phase5r_valuation_evidence_v1 import valuation_packet_calculations
from phase5r_valuation_input_bundle import (
    DEFAULT_BUNDLE_PATH as DEFAULT_VALUATION_BUNDLE_PATH,
    load_valuation_input_bundle,
)


PACKET_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_llm_evidence_packet.json"
)
ARTIFACT_INDEX_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_filing_artifact_index.json"
)
C5_PACKET_PATH = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_current_research_baseline.csv"
)
C9_SCORE_PATH = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_account_aware_conviction_scores.csv"
)

_C9_WEIGHTS = (
    ("business_quality_score", Decimal("0.25")),
    ("earnings_revenue_trend_score", Decimal("0.20")),
    ("valuation_reasonableness_score", Decimal("0.15")),
    ("catalyst_news_quality_score", Decimal("0.15")),
    ("technical_entry_discipline_score", Decimal("0.15")),
    ("portfolio_fit_score", Decimal("0.10")),
)
_PUBLIC_FORMS = {"10-K", "10-Q", "8-K", "20-F", "6-K", "40-F", "S-1", "S-1/A"}
_UNTRUSTED_INSTRUCTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all instructions",
    "system prompt",
    "assistant:",
    "execute this command",
    "reveal the password",
    "buy now",
    "sell now",
)
_LOCAL_EMAIL_PATTERN = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
_LOCAL_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"password|secret|credential|smtp[_ -]?password|broker[_ -]?token)"
    r"[A-Z0-9_-]*\s*[:=]\s*[^\s,;]+"
)
_LOCAL_PATH_PATTERN = re.compile(
    r"(?i)(?:file://|/Users/[^/\s]+/|[A-Z]:\\Users\\[^\\\s]+\\)"
)
_LOCAL_CURRENCY_PATTERN = re.compile(
    r"(?i)(?:[$€£]\s*\d[\d,]*(?:\.\d+)?|"
    r"\b\d[\d,]*(?:\.\d+)?\s*(?:USD|dollars?)\b)"
)


def _sanitize_local_text(value: Any, *, maximum_length: int = 4000) -> str:
    text = str(value or "")
    text = _LOCAL_EMAIL_PATTERN.sub("[email_redacted]", text)
    text = _LOCAL_SECRET_PATTERN.sub("[secret_redacted]", text)
    text = _LOCAL_PATH_PATTERN.sub("[local_path_redacted]", text)
    text = _LOCAL_CURRENCY_PATTERN.sub("[local_currency_redacted]", text)
    return text[:maximum_length]


def _decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _round(value: Decimal, places: str = "0.01") -> str:
    return format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def _safe_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _utc_text(value: Any) -> str:
    parsed = _safe_time(str(value or ""))
    if parsed is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _date_from_period(value: Any) -> str:
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", str(value or ""))
    return match.group(0) if match else ""


def _evidence_freshness_receipts(
    *,
    tickers: set[str],
    as_of: str,
    verified_close_session: str,
    evidence_status: dict[str, Any],
    market_observations: list[dict[str, Any]],
    valuation_evidence: list[dict[str, Any]],
    source_catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build ticker-local receipts without fetching or inferring evidence."""

    as_of_utc = _utc_text(as_of)
    market_by_ticker = {
        str(row.get("ticker", "")).upper(): row
        for row in market_observations
        if row.get("ticker")
    }
    valuation_by_ticker = {
        str(row.get("ticker", "")).upper(): row
        for row in valuation_evidence
        if row.get("ticker")
    }
    scanned_tickers = {
        str(value).upper()
        for value in evidence_status.get("scanned_tickers", [])
        if isinstance(value, str) and value
    }
    status_digest = (
        sha256_file(EVIDENCE_STATUS_PATH)
        if EVIDENCE_STATUS_PATH.exists()
        else ""
    )
    receipts: list[dict[str, Any]] = []
    for ticker in sorted(tickers):
        market_row = market_by_ticker.get(ticker, {})
        valuation_row = valuation_by_ticker.get(ticker, {})
        valuation_inputs = {
            str(row.get("input_id", "")): row
            for row in valuation_row.get("input_receipts", [])
            if isinstance(row, dict)
        }
        share_price = valuation_inputs.get("share_price", {})
        scenario_times = sorted(
            {
                _utc_text(
                    valuation_inputs.get(input_id, {}).get(
                        "available_at_utc",
                        "",
                    )
                )
                for input_id in (
                    "target_price_assumption",
                    "downside_price_assumption",
                )
                if _utc_text(
                    valuation_inputs.get(input_id, {}).get(
                        "available_at_utc",
                        "",
                    )
                )
            }
        )
        durable_sec_source_ids = sorted(
            str(source["source_id"])
            for source in source_catalog
            if str(source.get("ticker", "")).upper() == ticker
            and str(source.get("source_type", "")).startswith("sec_")
            and source.get("authority") == "primary_official"
        )
        receipts.append(
            build_evidence_freshness_receipt(
                ticker=ticker,
                as_of_utc=as_of_utc,
                sec_scan={
                    "status_artifact_sha256": status_digest,
                    "completed_through_utc": _utc_text(
                        evidence_status.get("last_success_at", "")
                    ),
                    "ticker_scanned": ticker in scanned_tickers,
                    "complete": (
                        evidence_status.get("scan_status") == "ok"
                        and ticker in scanned_tickers
                    ),
                },
                market={
                    "observed_at_utc": _utc_text(
                        market_row.get("data_timestamp", "")
                    ),
                    "market_session_date": str(
                        market_row.get("market_session_date", "")
                    ),
                    "expected_market_session_date": verified_close_session,
                    "complete_close": (
                        market_row.get("bar_state") == "complete_close"
                    ),
                },
                valuation={
                    "valuation_receipt_sha256": str(
                        valuation_row.get("receipt_sha256", "")
                    ),
                    "receipt_as_of_utc": str(
                        valuation_row.get("as_of_utc", "")
                    ),
                    "market_input_at_utc": _utc_text(
                        share_price.get("available_at_utc", "")
                    ),
                    "market_session_date": _date_from_period(
                        share_price.get("period", "")
                    ),
                    "expected_market_session_date": verified_close_session,
                    "scenario_refreshed_at_utc": (
                        scenario_times[-1] if scenario_times else ""
                    ),
                    "complete": (
                        valuation_row.get("sufficiency", {}).get(
                            "decision_sufficient"
                        )
                        is True
                        and valuation_row.get("guardrails", {}).get(
                            "action_grade_valuation_permitted"
                        )
                        is True
                    ),
                },
                durable_sec_source_ids=durable_sec_source_ids,
            )
        )
    return receipts


def _decision_tickers(values: Any) -> set[str]:
    """Accept current string rows and the legacy ``{"ticker": ...}`` shape."""

    if not isinstance(values, list):
        return set()
    tickers: set[str] = set()
    for value in values:
        raw = value.get("ticker", "") if isinstance(value, dict) else value
        ticker = str(raw or "").strip().upper()
        if ticker:
            tickers.add(ticker)
    return tickers


def _allowed_classifications_by_ticker(
    decision: dict[str, Any],
    entities: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Translate the deterministic C9 decision into a per-ticker policy cap.

    The map is consumed only by the deterministic adjudicator and is removed
    from every semantic model view.  A model may therefore form an independent
    opinion, but it cannot promote a classification that C9 has not opened.
    """

    held_rows = {
        str(row.get("ticker", "")).strip().upper(): row
        for row in decision.get("held_positions", [])
        if isinstance(row, dict) and str(row.get("ticker", "")).strip()
    }
    candidate_rows = {
        str(row.get("ticker", "")).strip().upper(): row
        for row in decision.get("watch_candidates", [])
        if isinstance(row, dict) and str(row.get("ticker", "")).strip()
    }
    eligible_tickers = _decision_tickers(
        decision.get("eligible_action_review_candidates", [])
    )
    allowed: dict[str, list[str]] = {}
    for entity in entities:
        ticker = str(entity["ticker"]).upper()
        role = str(entity["role"])
        if role == "held":
            action = str(held_rows.get(ticker, {}).get("action", "hold")).lower()
            if "exit" in action or "sell" in action:
                classifications = [
                    "hold_existing",
                    "trim_review",
                    "exit_review",
                    "abstain",
                ]
            elif "trim" in action or "reduce" in action:
                classifications = [
                    "hold_existing",
                    "trim_review",
                    "abstain",
                ]
            elif "add" in action or "buy" in action:
                classifications = [
                    "hold_existing",
                    "paper_trade_candidate",
                    "real_trade_candidate",
                    "abstain",
                ]
            else:
                classifications = ["hold_existing", "abstain"]
        else:
            candidate = candidate_rows.get(ticker, {})
            action = str(candidate.get("action", "")).lower()
            label = str(candidate.get("label", "")).lower()
            c9_buy_review = (
                ticker in eligible_tickers
                and (
                    "buy" in action
                    or "add" in action
                    or "entry" in action
                    or label == "eligible_buy_review"
                )
            )
            if c9_buy_review:
                classifications = [
                    "reject",
                    "watchlist",
                    "paper_trade_candidate",
                    "real_trade_candidate",
                    "abstain",
                ]
            else:
                classifications = ["reject", "watchlist", "abstain"]
        allowed[ticker] = classifications
    return allowed


def _source(
    *,
    source_id: str,
    source_type: str,
    ticker: str,
    accepted_at: str,
    source_url: str,
    content_sha256: str,
    locator: dict[str, Any],
    authority: str,
    excerpt_text: str = "",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "ticker": ticker,
        "accepted_at": accepted_at,
        "source_url": source_url,
        "content_sha256": content_sha256,
        "locator": locator,
        "authority": authority,
        "excerpt_text": excerpt_text,
    }


def _source_file_manifest(paths: Iterable[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        rows.append(
            {
                "relative_path": str(path.relative_to(ROOT)),
                "sha256": sha256_file(path) if path.exists() else "absent",
            }
        )
    return rows


def _position_band(weight: Decimal | None) -> str:
    if weight is None:
        return "unknown"
    if weight < Decimal("2"):
        return "under_2_pct"
    if weight < Decimal("5"):
        return "2_to_5_pct"
    if weight < Decimal("8"):
        return "5_to_8_pct"
    return "over_8_pct"


def _artifact_map() -> dict[str, list[dict[str, Any]]]:
    payload = read_json(
        ARTIFACT_INDEX_PATH,
        {"schema_version": "phase5r_sec_filing_artifact_index_v1", "artifacts": []},
    )
    by_accession: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in payload.get("artifacts", []):
        accession = str(
            artifact.get("accession_number") or artifact.get("accession") or ""
        )
        if accession:
            by_accession[accession].append(artifact)
    return by_accession


def _verified_artifact_chunks(
    artifact: dict[str, Any],
    *,
    maximum_chunks: int = 8,
) -> list[tuple[dict[str, Any], str]]:
    relative_path = str(artifact.get("normalized_path", ""))
    if not relative_path:
        return []
    candidate = (ROOT / relative_path).resolve()
    allowed_root = (ROOT / "02_filings" / "phase5r_daily").resolve()
    if allowed_root != candidate and allowed_root not in candidate.parents:
        return []
    try:
        normalized_text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    normalized_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    if normalized_hash != artifact.get("normalized_sha256"):
        return []
    terms = {
        "risk": 5,
        "revenue": 4,
        "liquidity": 4,
        "cash flow": 4,
        "management discussion": 4,
        "outlook": 4,
        "guidance": 4,
        "competition": 3,
        "stock-based compensation": 3,
        "going concern": 6,
        "material weakness": 6,
        "cybersecurity": 3,
        "artificial intelligence": 2,
    }
    verified: list[tuple[int, int, dict[str, Any], str]] = []
    for chunk in artifact.get("chunks", []):
        start = chunk.get("char_start")
        end = chunk.get("char_end")
        index = int(chunk.get("chunk_index", chunk.get("index", 0)) or 0)
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(normalized_text)
        ):
            continue
        excerpt = normalized_text[start:end]
        digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        if digest != chunk.get("sha256"):
            continue
        lowered = excerpt.lower()
        score = sum(lowered.count(term) * weight for term, weight in terms.items())
        if index == 0:
            score += 1
        verified.append((score, index, chunk, excerpt))
    if not verified or maximum_chunks <= 0:
        return []
    by_index = sorted(verified, key=lambda row: row[1])
    semantic_slots = min(len(by_index), max(1, maximum_chunks // 2))
    selected_by_index = {
        row[1]: row
        for row in sorted(verified, key=lambda row: (-row[0], row[1]))[
            :semantic_slots
        ]
    }
    coverage_slots = maximum_chunks - len(selected_by_index)
    if coverage_slots > 0:
        if coverage_slots == 1:
            coverage_positions = [0]
        else:
            coverage_positions = [
                round(position * (len(by_index) - 1) / (coverage_slots - 1))
                for position in range(coverage_slots)
            ]
        for position in coverage_positions:
            selected_by_index[by_index[position][1]] = by_index[position]
    if len(selected_by_index) < min(maximum_chunks, len(by_index)):
        for row in sorted(verified, key=lambda item: (-item[0], item[1])):
            selected_by_index.setdefault(row[1], row)
            if len(selected_by_index) >= min(maximum_chunks, len(by_index)):
                break
    selected = sorted(selected_by_index.values(), key=lambda row: row[1])[
        :maximum_chunks
    ]
    return [(chunk, excerpt) for _, _, chunk, excerpt in selected]


def _entities(
    positions: list[dict[str, str]],
    candidates: list[dict[str, str]],
    position_recommendations: list[dict[str, str]],
    fundamentals: list[dict[str, str]],
) -> list[dict[str, Any]]:
    recommendations = {
        row.get("ticker", "").upper(): row for row in position_recommendations
    }
    fundamental_map = {row.get("ticker", "").upper(): row for row in fundamentals}
    rows: list[dict[str, Any]] = []
    held: set[str] = set()
    for position in positions:
        ticker = position.get("ticker", "").strip().upper()
        if not ticker:
            continue
        held.add(ticker)
        recommendation = recommendations.get(ticker, {})
        weight = _decimal(recommendation.get("current_weight_pct"))
        rows.append(
            {
                "ticker": ticker,
                "role": "held",
                "cik": fundamental_map.get(ticker, {}).get("cik", ""),
                "position_weight_band": _position_band(weight),
                "position_weight_pct_rounded": (
                    _round(weight, "0.1") if weight is not None else ""
                ),
                "concentration_status": recommendation.get(
                    "concentration_status", "unknown"
                ),
                "holding_horizon": _sanitize_local_text(
                    position.get("horizon_class", "")
                ),
                "thesis": _sanitize_local_text(position.get("thesis", "")),
                "invalidation_rule": _sanitize_local_text(
                    position.get("invalidation_rule", "")
                ),
                "deterministic_recommendation": _sanitize_local_text(
                    recommendation.get("recommended_action", "hold")
                ),
            }
        )
    for candidate in candidates[:5]:
        ticker = candidate.get("ticker", "").strip().upper()
        if not ticker or ticker in held:
            continue
        rows.append(
            {
                "ticker": ticker,
                "role": "candidate",
                "cik": fundamental_map.get(ticker, {}).get("cik", ""),
                "position_weight_band": "not_held",
                "position_weight_pct_rounded": "0.0",
                "concentration_status": "not_held",
                "holding_horizon": "",
                "thesis": "",
                "invalidation_rule": "",
                "deterministic_recommendation": candidate.get(
                    "recommended_action", "watchlist"
                ),
            }
        )
    return rows


def _market_observations(
    tickers: set[str],
    as_of_et: str,
    verified_close_session: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    quality = {row.get("ticker", "").upper(): row for row in read_csv(MARKET_QUALITY_PATH)}
    as_of = _safe_time(as_of_et)
    observations: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    point_in_time_safe = as_of is not None
    for row in read_csv(MARKET_SNAPSHOT_PATH):
        ticker = row.get("ticker", "").upper()
        if ticker not in tickers:
            continue
        timestamp = row.get("data_timestamp", "")
        parsed_timestamp = _safe_time(timestamp)
        if as_of and parsed_timestamp and parsed_timestamp > as_of:
            point_in_time_safe = False
        close_cutoff: datetime | None = None
        try:
            if verified_close_session:
                close_cutoff = datetime.combine(
                    datetime.fromisoformat(verified_close_session).date(),
                    time(16, 15),
                    tzinfo=ET,
                )
        except ValueError:
            close_cutoff = None
        complete_close = bool(
            as_of
            and parsed_timestamp
            and close_cutoff
            and row.get("market_session_date") == verified_close_session
            and close_cutoff
            <= parsed_timestamp.astimezone(ET)
            <= as_of.astimezone(ET)
        )
        source_id = f"market:{ticker}:{row.get('market_session_date', 'unknown')}"
        public_row = {
            "ticker": ticker,
            "last_price": row.get("last_price", ""),
            "previous_close": row.get("previous_close", ""),
            "intraday_change_pct": row.get("intraday_change_pct", ""),
            "relative_volume": row.get("relative_volume", ""),
            "fifty_two_week_high": row.get("fifty_two_week_high", ""),
            "fifty_two_week_low": row.get("fifty_two_week_low", ""),
            "market_session_date": row.get("market_session_date", ""),
            "data_timestamp": timestamp,
            "data_source": row.get("data_source", ""),
            "data_quality_label": row.get("data_quality_label", ""),
            "usable_for_scoring": quality.get(ticker, {}).get(
                "usable_for_scoring", "no"
            ),
            "bar_state": "complete_close" if complete_close else "intraday_or_unverified",
            "source_id": source_id,
        }
        observations.append(public_row)
        sources.append(
            _source(
                source_id=source_id,
                source_type="public_market_observation",
                ticker=ticker,
                accepted_at=timestamp,
                source_url="",
                content_sha256=canonical_sha256(public_row),
                locator={
                    "dataset": "phase5r_b2_market_data_snapshot",
                    "session": row.get("market_session_date", ""),
                },
                authority="secondary_public_market_context",
            )
        )
    return observations, sources, point_in_time_safe


def _fundamental_observations(
    tickers: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    calculations: list[dict[str, Any]] = []
    for row in read_csv(FUNDAMENTALS_PATH):
        ticker = row.get("ticker", "").upper()
        if ticker not in tickers:
            continue
        source_id = f"sec-xbrl:{ticker}:{row.get('latest_frame') or row.get('latest_period_end') or 'unknown'}"
        public_row = {
            "ticker": ticker,
            "cik": row.get("cik", ""),
            "fetched_at": row.get("fetched_at", ""),
            "latest_period_end": row.get("latest_period_end", ""),
            "latest_frame": row.get("latest_frame", ""),
            "revenue_latest": row.get("revenue_latest", ""),
            "revenue_prior_year": row.get("revenue_prior_year", ""),
            "revenue_yoy_pct": row.get("revenue_yoy_pct", ""),
            "net_income_latest": row.get("net_income_latest", ""),
            "net_margin_pct": row.get("net_margin_pct", ""),
            "cash_latest": row.get("cash_latest", ""),
            "assets_latest": row.get("assets_latest", ""),
            "liabilities_latest": row.get("liabilities_latest", ""),
            "trend_label": row.get("trend_label", ""),
            "data_quality": row.get("data_quality", ""),
            "source_id": source_id,
        }
        observations.append(public_row)
        sources.append(
            _source(
                source_id=source_id,
                source_type="sec_companyfacts_xbrl",
                ticker=ticker,
                accepted_at=row.get("fetched_at", ""),
                source_url=row.get("source_url", ""),
                content_sha256=canonical_sha256(public_row),
                locator={
                    "cik": row.get("cik", ""),
                    "period": row.get("latest_period_end", ""),
                    "frame": row.get("latest_frame", ""),
                },
                authority="primary_official",
            )
        )
        revenue = _decimal(row.get("revenue_latest"))
        prior = _decimal(row.get("revenue_prior_year"))
        supplied_yoy = _decimal(row.get("revenue_yoy_pct"))
        if revenue is not None and prior not in {None, Decimal("0")} and supplied_yoy is not None:
            recomputed = (revenue / prior - Decimal("1")) * Decimal("100")
            calculations.append(
                {
                    "calculation_id": f"calc:revenue_yoy:{ticker}:{row.get('latest_frame') or 'period'}",
                    "ticker": ticker,
                    "metric": "revenue_yoy_pct",
                    "value": _round(supplied_yoy),
                    "recomputed_value": _round(recomputed),
                    "unit": "pct",
                    "period": row.get("latest_frame") or row.get("latest_period_end", ""),
                    "formula": "(revenue_latest/revenue_prior_year-1)*100",
                    "source_ids": [source_id],
                    "reconciled": _round(supplied_yoy) == _round(recomputed),
                }
            )
        income = _decimal(row.get("net_income_latest"))
        supplied_margin = _decimal(row.get("net_margin_pct"))
        if revenue not in {None, Decimal("0")} and income is not None and supplied_margin is not None:
            recomputed = income / revenue * Decimal("100")
            calculations.append(
                {
                    "calculation_id": f"calc:net_margin:{ticker}:{row.get('latest_frame') or 'period'}",
                    "ticker": ticker,
                    "metric": "net_margin_pct",
                    "value": _round(supplied_margin),
                    "recomputed_value": _round(recomputed),
                    "unit": "pct",
                    "period": row.get("latest_frame") or row.get("latest_period_end", ""),
                    "formula": "net_income_latest/revenue_latest*100",
                    "source_ids": [source_id],
                    "reconciled": _round(supplied_margin) == _round(recomputed),
                }
            )
    return observations, sources, calculations


def _filing_evidence(
    tickers: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    artifacts = _artifact_map()
    acceptance_records = acceptance_map()
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(EVIDENCE_LEDGER_PATH):
        ticker = row.get("ticker", "").upper()
        if ticker in tickers and row.get("form") in _PUBLIC_FORMS:
            by_ticker[ticker].append(row)
    evidence: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    covered: set[str] = set()
    for ticker, rows in sorted(by_ticker.items()):
        rows.sort(
            key=lambda row: (
                row.get("filing_date", ""),
                row.get("accession_number", ""),
            ),
            reverse=True,
        )
        selected = rows[:2]
        selected_accessions = {row.get("accession_number", "") for row in selected}
        selected.extend(
            row
            for row in rows[2:]
            if row.get("material_event") == "yes"
            and row.get("accession_number", "") not in selected_accessions
        )
        for row in selected:
            accession = row.get("accession_number", "")
            acceptance_record = acceptance_records.get(accession, {})
            accepted_at = str(acceptance_record.get("accepted_at", ""))
            acceptance_source_id = (
                f"sec-acceptance:{accession}" if acceptance_record else ""
            )
            if acceptance_record:
                sources.append(
                    _source(
                        source_id=acceptance_source_id,
                        source_type="sec_submission_acceptance",
                        ticker=ticker,
                        accepted_at=accepted_at,
                        source_url=str(acceptance_record["source_url"]),
                        content_sha256=str(
                            acceptance_record["record_sha256"]
                        ),
                        locator={
                            "cik": acceptance_record["cik"],
                            "accession_number": accession,
                            "filing_date": acceptance_record["filing_date"],
                            "field": "acceptanceDateTime",
                        },
                        authority="primary_official_metadata",
                    )
                )
            artifact_rows = artifacts.get(accession, [])
            chunk_ids: list[str] = []
            for artifact in artifact_rows:
                for chunk, excerpt in _verified_artifact_chunks(artifact):
                    chunk_id = str(
                        chunk.get("source_id")
                        or (
                            f"{artifact.get('source_id', f'sec-filing:{accession}')}"
                            f":chunk:{chunk.get('chunk_index', chunk.get('index', 0))}"
                        )
                    )
                    chunk_ids.append(chunk_id)
                    sources.append(
                        _source(
                            source_id=chunk_id,
                            source_type="sec_filing_text_chunk",
                            ticker=ticker,
                            accepted_at=accepted_at,
                            source_url=row.get("source_url", ""),
                            content_sha256=str(chunk.get("sha256", "")),
                            locator={
                                "cik": row.get("cik", ""),
                                "accession_number": accession,
                                "form": row.get("form", ""),
                                "char_start": chunk.get("char_start"),
                                "char_end": chunk.get("char_end"),
                                "parser": {
                                    "id": artifact.get("parser_id", ""),
                                    "version": artifact.get("parser_version", ""),
                                },
                            },
                            authority="primary_official",
                            excerpt_text=excerpt,
                        )
                    )
            if chunk_ids and acceptance_record:
                covered.add(ticker)
            metadata_source_id = f"sec-filing-metadata:{accession}"
            sources.append(
                _source(
                    source_id=metadata_source_id,
                    source_type="sec_filing_metadata",
                    ticker=ticker,
                    accepted_at=row.get("detected_at", ""),
                    source_url=row.get("source_url", ""),
                    content_sha256=row.get("metadata_sha256", ""),
                    locator={
                        "cik": row.get("cik", ""),
                        "accession_number": accession,
                        "form": row.get("form", ""),
                        "filing_date": row.get("filing_date", ""),
                    },
                    authority="primary_official_metadata",
                )
            )
            evidence.append(
                {
                    "ticker": ticker,
                    "cik": row.get("cik", ""),
                    "form": row.get("form", ""),
                    "filing_date": row.get("filing_date", ""),
                    "accepted_at": accepted_at,
                    "accession_number": accession,
                    "items": row.get("items", ""),
                    "materiality": row.get("materiality", ""),
                    "material_event": row.get("material_event", ""),
                    "metadata_source_id": metadata_source_id,
                    "acceptance_source_id": acceptance_source_id,
                    "text_chunk_source_ids": chunk_ids,
                }
            )
    return evidence, sources, covered


def _research_context(
    tickers: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    c5 = {row.get("ticker", "").upper(): row for row in read_csv(C5_PACKET_PATH)}
    c9 = {row.get("ticker", "").upper(): row for row in read_csv(C9_SCORE_PATH)}
    position = {
        row.get("ticker", "").upper(): row for row in read_csv(POSITION_RECOMMENDATION_PATH)
    }
    candidate = {
        row.get("ticker", "").upper(): row for row in read_csv(NEW_CANDIDATE_PATH)
    }
    context: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    calculations: list[dict[str, Any]] = []
    for ticker in sorted(tickers):
        c5_row = c5.get(ticker, {})
        c9_row = c9.get(ticker, {})
        recommendation = position.get(ticker) or candidate.get(ticker) or {}
        source_id = f"research-context:{ticker}:{c5_row.get('evidence_checked_at') or cycle_date()}"
        public_context = {
            "ticker": ticker,
            "theme": _sanitize_local_text(c5_row.get("theme", "")),
            "business_quality_score": c5_row.get("business_quality_score", ""),
            "earnings_revenue_trend_score": c5_row.get(
                "earnings_revenue_trend_score", ""
            ),
            "valuation_reasonableness_score": c5_row.get(
                "valuation_reasonableness_score", ""
            ),
            "catalyst_news_quality_score": c5_row.get(
                "catalyst_news_quality_score", ""
            ),
            "technical_entry_discipline_score": c5_row.get(
                "technical_entry_discipline_score", ""
            ),
            "portfolio_fit_score": c9_row.get("portfolio_fit_score", ""),
            "deterministic_conviction_score": c9_row.get(
                "account_aware_conviction_score", ""
            ),
            "recommendation_label": _sanitize_local_text(
                recommendation.get(
                    "recommendation_label",
                    recommendation.get("eligibility_label", ""),
                )
            ),
            "recommended_action": _sanitize_local_text(
                recommendation.get("recommended_action", "")
            ),
            "reason": _sanitize_local_text(recommendation.get("reason", "")),
            "primary_source_url": c5_row.get("primary_source_url", ""),
            "filing_source_url": c5_row.get("filing_source_url", ""),
            "evidence_checked_at": c5_row.get("evidence_checked_at", ""),
            "source_id": source_id,
        }
        context.append(public_context)
        sources.append(
            _source(
                source_id=source_id,
                source_type="derived_research_context",
                ticker=ticker,
                accepted_at=c5_row.get("evidence_checked_at", ""),
                source_url=c5_row.get("primary_source_url", ""),
                content_sha256=canonical_sha256(public_context),
                locator={"dataset": "phase5r_c5_c9", "ticker": ticker},
                authority="derived_not_primary",
            )
        )
        components: list[Decimal] = []
        complete = True
        for field, weight in _C9_WEIGHTS:
            value = _decimal(
                c9_row.get(field)
                if field == "portfolio_fit_score"
                else c5_row.get(field)
            )
            if value is None:
                complete = False
                break
            components.append(value * weight)
        supplied = _decimal(c9_row.get("account_aware_conviction_score"))
        if complete and supplied is not None:
            recomputed = sum(components, Decimal("0"))
            calculations.append(
                {
                    "calculation_id": f"calc:c9_score:{ticker}:{cycle_date()}",
                    "ticker": ticker,
                    "metric": "account_aware_conviction_score",
                    "value": _round(supplied),
                    "recomputed_value": _round(recomputed),
                    "unit": "score_0_to_10",
                    "period": cycle_date(),
                    "formula": (
                        "0.25*business+0.20*earnings+0.15*valuation+"
                        "0.15*catalyst+0.15*technical+0.10*portfolio_fit"
                    ),
                    "source_ids": [source_id],
                    "reconciled": _round(supplied) == _round(recomputed),
                }
            )
    return context, sources, calculations


def _resolve_packet_as_of(as_of_et: str | None) -> str:
    return as_of_et or iso_now()


def build_packet(
    as_of_et: str | None = None,
    *,
    valuation_bundle_path: Path = DEFAULT_VALUATION_BUNDLE_PATH,
    valuation_source_root: Path = ROOT,
) -> dict[str, Any]:
    decision = read_json(DAILY_DECISION_JSON_PATH)
    account = read_json(ACCOUNT_STATE_PATH)
    evidence_status = read_json(EVIDENCE_STATUS_PATH, {})
    positions = read_csv(POSITIONS_PATH)
    position_recommendations = read_csv(POSITION_RECOMMENDATION_PATH)
    candidates = read_csv(NEW_CANDIDATE_PATH)
    fundamentals = read_csv(FUNDAMENTALS_PATH)
    # This packet is a fresh point-in-time research snapshot.  The underlying
    # deterministic decision may predate later verified SEC artifacts, so using
    # its generation time here can falsely place already-local evidence in the
    # future.  Historical replay callers always pass an explicit as-of.
    as_of = _resolve_packet_as_of(as_of_et)

    entities = _entities(
        positions, candidates, position_recommendations, fundamentals
    )
    tickers = {row["ticker"] for row in entities}
    held_tickers = {row["ticker"] for row in entities if row["role"] == "held"}

    market_gate = decision.get("market_gate", {})
    verified_close_session = (
        str(market_gate.get("expected_market_session", ""))
        if market_gate.get("complete_close_verified") is True
        else ""
    )
    market, market_sources, point_in_time_safe = _market_observations(
        tickers,
        as_of,
        verified_close_session,
    )
    fundamental, fundamental_sources, fundamental_calculations = (
        _fundamental_observations(tickers)
    )
    filings, filing_sources, artifact_covered = _filing_evidence(tickers)
    research, research_sources, research_calculations = _research_context(tickers)
    valuation_evidence, valuation_sources = load_valuation_input_bundle(
        path=valuation_bundle_path,
        packet_as_of=as_of,
        active_tickers=tickers,
        project_root=valuation_source_root,
    )
    source_catalog = (
        market_sources
        + fundamental_sources
        + filing_sources
        + research_sources
        + valuation_sources
    )
    untrusted_text = json.dumps(
        {
            "entities": entities,
            "research_context": research,
            "source_excerpts": [
                source.get("excerpt_text", "") for source in source_catalog
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).lower()
    prompt_injection_text_detected = any(
        pattern in untrusted_text for pattern in _UNTRUSTED_INSTRUCTION_PATTERNS
    )
    valuation_calculations = [
        calculation
        for receipt in valuation_evidence
        for calculation in valuation_packet_calculations(receipt)
    ]
    valuation_action_grade_tickers = sorted(
        receipt["ticker"]
        for receipt in valuation_evidence
        if receipt["sufficiency"]["decision_sufficient"] is True
        and receipt["guardrails"]["action_grade_valuation_permitted"] is True
    )
    evidence_freshness = _evidence_freshness_receipts(
        tickers=tickers,
        as_of=as_of,
        verified_close_session=verified_close_session,
        evidence_status=evidence_status,
        market_observations=market,
        valuation_evidence=valuation_evidence,
        source_catalog=source_catalog,
    )

    boundaries = {
        "research_only": True,
        "canonical_effect": False,
        "email_eligible": False,
        "automatic_action_allowed": False,
        "broker_connected": False,
        "order_code_available": False,
        "exact_account_dollars_included": False,
    }
    unsigned = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "generated_at": as_of,
        "as_of_et": as_of,
        "cycle_date": str(decision.get("cycle_date") or cycle_date()),
        "decision_fingerprint": str(decision.get("decision_fingerprint", "")),
        "entities": entities,
        "portfolio_constraints": {
            "account_size_band": "under_10k",
            "investment_horizon_years": account.get("investment_horizon_years"),
            "core_allocation_target_pct": account.get("core_allocation_target_pct"),
            "active_stock_target_pct": account.get("active_stock_target_pct"),
            "active_stock_hard_cap_pct": account.get("active_stock_hard_cap_pct"),
            "single_stock_default_cap_pct": account.get(
                "single_stock_default_cap_pct"
            ),
            "single_stock_hard_cap_pct": account.get("single_stock_hard_cap_pct"),
            "cash_target_pct": account.get("cash_target_pct"),
            "return_objective": return_objective_payload(),
            "manual_execution_only": True,
        },
        "gates": {
            "market_data_current": market_gate.get("passed") is True,
            # The active B2 source is public yfinance context.  It is useful for
            # HOLD/WATCH research, but it is not a licensed SIP-grade action
            # source and therefore cannot independently unlock a transition.
            "market_data_action_grade": False,
            "market_data_action_grade_tickers": [],
            # This list is derived only from sealed, locally re-hashed
            # valuation input bundles. Public market data remains non-action
            # grade, so a valuation receipt cannot independently authorize an
            # action transition.
            "valuation_action_grade_tickers": valuation_action_grade_tickers,
            "allowed_classifications_by_ticker": (
                _allowed_classifications_by_ticker(decision, entities)
            ),
            "sec_held_coverage_complete": evidence_status.get(
                "held_coverage_complete"
            )
            is True,
            "fundamental_held_coverage_complete": evidence_status.get(
                "held_fundamental_coverage_complete"
            )
            is True,
            "filing_artifact_provenance_complete": held_tickers.issubset(
                artifact_covered
            ),
            "sec_acceptance_provenance_complete": held_tickers.issubset(
                artifact_covered
            ),
            "account_state_consistent": not decision.get("account_conflicts", []),
            "point_in_time_safe": point_in_time_safe,
            "prompt_injection_text_detected": prompt_injection_text_detected,
            "deterministic_action_stability_distinct_closes": int(
                decision.get("action_stability_distinct_closes", 0) or 0
            ),
            "deterministic_transition_pending_tickers": sorted(
                _decision_tickers(decision.get("pending_stability_candidates", []))
            ),
            "deterministic_transition_eligible_tickers": sorted(
                _decision_tickers(
                    decision.get("eligible_action_review_candidates", [])
                )
            ),
            "verified_close_session": verified_close_session,
        },
        "market_observations": market,
        "fundamental_observations": fundamental,
        "filing_evidence": filings,
        "research_context": research,
        "valuation_evidence": valuation_evidence,
        "evidence_freshness": evidence_freshness,
        "calculations": (
            fundamental_calculations
            + research_calculations
            + valuation_calculations
        ),
        "source_catalog": source_catalog,
        "boundaries": boundaries,
    }
    packet = {"packet_id": canonical_sha256(unsigned), **unsigned}
    validate_packet(packet)
    return packet


def write_packet(packet: dict[str, Any], output_path: Path = PACKET_PATH) -> None:
    validate_packet(packet)
    atomic_write_json(output_path, packet)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--as-of", help="ISO timestamp override for deterministic replay")
    parser.add_argument("--output", type=Path, default=PACKET_PATH)
    args = parser.parse_args()

    verification_as_of = args.as_of or iso_now()
    packet = build_packet(verification_as_of)
    if args.check:
        print(
            f"safe_check_passed=true packet_valid=true packet_id={packet['packet_id']} "
            "network_used=false email_attempted=false exact_account_dollars_included=false"
        )
        return 0
    write_packet(packet, args.output)
    print(
        f"packet_built=true packet_id={packet['packet_id']} "
        f"entities={len(packet['entities'])} sources={len(packet['source_catalog'])} "
        "canonical_effect=false email_eligible=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
