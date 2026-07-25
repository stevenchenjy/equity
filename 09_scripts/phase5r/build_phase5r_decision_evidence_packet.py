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
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from phase5r_daily_common import (
    ACCOUNT_STATE_PATH,
    DAILY_DECISION_JSON_PATH,
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
    / "phase5r_c5_company_research_packets.csv"
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
    maximum_chunks: int = 4,
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
    selected = sorted(verified, key=lambda row: (-row[0], row[1]))[:maximum_chunks]
    return [(chunk, excerpt) for _, _, chunk, excerpt in sorted(selected, key=lambda row: row[1])]


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
                "holding_horizon": position.get("horizon_class", ""),
                "thesis": position.get("thesis", ""),
                "invalidation_rule": position.get("invalidation_rule", ""),
                "deterministic_recommendation": recommendation.get(
                    "recommended_action", "hold"
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
    tickers: set[str], as_of_et: str
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
        complete_close = bool(
            as_of
            and as_of.strftime("%H:%M") >= "16:15"
            and row.get("market_session_date") == as_of.date().isoformat()
            and as_of.weekday() < 5
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
                            accepted_at=row.get("detected_at", ""),
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
            if chunk_ids:
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
                    "accession_number": accession,
                    "items": row.get("items", ""),
                    "materiality": row.get("materiality", ""),
                    "material_event": row.get("material_event", ""),
                    "metadata_source_id": metadata_source_id,
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
            "theme": c5_row.get("theme", ""),
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
            "recommendation_label": recommendation.get(
                "recommendation_label", recommendation.get("eligibility_label", "")
            ),
            "recommended_action": recommendation.get("recommended_action", ""),
            "reason": recommendation.get("reason", ""),
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


def build_packet(as_of_et: str | None = None) -> dict[str, Any]:
    decision = read_json(DAILY_DECISION_JSON_PATH)
    account = read_json(ACCOUNT_STATE_PATH)
    evidence_status = read_json(EVIDENCE_STATUS_PATH, {})
    positions = read_csv(POSITIONS_PATH)
    position_recommendations = read_csv(POSITION_RECOMMENDATION_PATH)
    candidates = read_csv(NEW_CANDIDATE_PATH)
    fundamentals = read_csv(FUNDAMENTALS_PATH)
    as_of = as_of_et or str(decision.get("generated_at") or iso_now())

    entities = _entities(
        positions, candidates, position_recommendations, fundamentals
    )
    tickers = {row["ticker"] for row in entities}
    held_tickers = {row["ticker"] for row in entities if row["role"] == "held"}

    market, market_sources, point_in_time_safe = _market_observations(tickers, as_of)
    fundamental, fundamental_sources, fundamental_calculations = (
        _fundamental_observations(tickers)
    )
    filings, filing_sources, artifact_covered = _filing_evidence(tickers)
    research, research_sources, research_calculations = _research_context(tickers)
    source_catalog = market_sources + fundamental_sources + filing_sources + research_sources
    prompt_injection_text_detected = any(
        pattern in str(source.get("excerpt_text", "")).lower()
        for source in source_catalog
        for pattern in _UNTRUSTED_INSTRUCTION_PATTERNS
    )

    market_gate = decision.get("market_gate", {})
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
            "manual_execution_only": True,
        },
        "gates": {
            "market_data_current": market_gate.get("passed") is True,
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
            "account_state_consistent": not decision.get("account_conflicts", []),
            "point_in_time_safe": point_in_time_safe,
            "prompt_injection_text_detected": prompt_injection_text_detected,
        },
        "market_observations": market,
        "fundamental_observations": fundamental,
        "filing_evidence": filings,
        "research_context": research,
        "calculations": fundamental_calculations + research_calculations,
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

    packet = build_packet(args.as_of)
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
