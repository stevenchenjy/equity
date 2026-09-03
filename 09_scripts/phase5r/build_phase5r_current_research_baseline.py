#!/usr/bin/env python3
"""Build current deterministic research packets from market and SEC evidence."""

from __future__ import annotations

from phase5r_daily_common import (
    EVIDENCE_LEDGER_PATH,
    FUNDAMENTALS_PATH,
    MARKET_SNAPSHOT_PATH,
    POSITIONS_PATH,
    ROOT,
    atomic_write_csv,
    cycle_date,
    iso_now,
    latest_published_market_session,
    now_et,
    read_csv,
)


SIGNAL_SCORES_PATH = ROOT / "03_source_data" / "phase5r" / "phase5r_b2_signal_scores.csv"
UNIVERSE_PATH = ROOT / "03_source_data" / "phase5r" / "phase5r_universe_seed.csv"
OUTPUT_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_current_research_baseline.csv"
)
FIELDS = [
    "ticker", "research_role", "current_position_status", "market_score",
    "portfolio_concentration_status", "theme", "holding_horizon_candidate",
    "valuation_check", "filing_check", "earnings_check", "news_check",
    "technical_check", "risk_check", "entry_discipline",
    "exit_or_trim_conditions", "recommendation_label",
    "recommendation_confidence", "human_action_required", "notes",
    "business_quality_score", "earnings_revenue_trend_score",
    "valuation_reasonableness_score", "catalyst_news_quality_score",
    "technical_entry_discipline_score", "portfolio_fit_score",
    "primary_source_url", "filing_source_url", "market_data_source",
    "evidence_checked_at",
]


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def clamp(value: float) -> float:
    return max(0.0, min(10.0, value))


def selected_tickers() -> tuple[list[str], set[str]]:
    held = {
        row.get("ticker", "").strip().upper()
        for row in read_csv(POSITIONS_PATH)
        if row.get("ticker", "").strip()
    }
    ranked = [
        row for row in read_csv(SIGNAL_SCORES_PATH)
        if row.get("ticker", "").strip().upper() not in held
        and number(row.get("total_score")) not in {None, 0.0}
        and row.get("data_quality_label") in {"ok", "partial"}
    ]
    ranked.sort(key=lambda row: (-float(row["total_score"]), row["ticker"]))
    candidates = [
        row["ticker"].strip().upper() for row in ranked
        if row["ticker"].strip().upper() != "SPY"
    ][:3]
    return sorted(held | {"SPY", *candidates}), held


def main() -> int:
    expected_session = latest_published_market_session(now_et()).isoformat()
    tickers, held = selected_tickers()
    market = {row.get("ticker", "").strip().upper(): row for row in read_csv(MARKET_SNAPSHOT_PATH)}
    scores = {row.get("ticker", "").strip().upper(): row for row in read_csv(SIGNAL_SCORES_PATH)}
    fundamentals = {row.get("ticker", "").strip().upper(): row for row in read_csv(FUNDAMENTALS_PATH)}
    universe = {row.get("ticker", "").strip().upper(): row for row in read_csv(UNIVERSE_PATH)}
    position_rows = {row.get("ticker", "").strip().upper(): row for row in read_csv(POSITIONS_PATH)}
    material_today = {
        row.get("ticker", "").strip().upper()
        for row in read_csv(EVIDENCE_LEDGER_PATH)
        if row.get("cycle_date") == cycle_date()
        and row.get("material_event") == "yes"
        and row.get("is_new") == "yes"
    }
    rows: list[dict[str, str]] = []
    for ticker in tickers:
        market_row = market.get(ticker, {})
        if (
            market_row.get("market_session_date") != expected_session
            or market_row.get("data_quality_label") not in {"ok", "partial"}
            or number(market_row.get("last_price")) is None
        ):
            raise ValueError(f"current research baseline lacks a valid completed close for {ticker}")
        score_row = scores.get(ticker, {})
        fundamental = fundamentals.get(ticker, {})
        is_benchmark = (
            universe.get(ticker, {}).get("is_benchmark", "").strip().lower()
            == "yes"
        )
        if (
            ticker in held
            and not is_benchmark
            and fundamental.get("data_quality") not in {"ok", "partial"}
        ):
            raise ValueError(f"current research baseline lacks SEC fundamentals for held ticker {ticker}")
        yoy = number(fundamental.get("revenue_yoy_pct"))
        margin = number(fundamental.get("net_margin_pct"))
        market_score = number(score_row.get("total_score"))
        if ticker in held and market_score is None:
            market_score = clamp(5.0 + (number(market_row.get("intraday_change_pct")) or 0.0) * 0.5)
        if market_score is None:
            market_score = 5.0
        earnings_score = (
            8.5 if yoy is not None and yoy >= 25
            else 7.5 if yoy is not None and yoy >= 15
            else 6.0 if yoy is not None and yoy >= 5
            else 5.0 if yoy is not None and yoy >= 0
            else 3.5 if yoy is not None else 4.0
        )
        business_score = clamp(
            6.0 + (1.0 if margin is not None and margin >= 0 else 0.0)
            + (0.5 if yoy is not None and yoy >= 15 else 0.0)
        )
        catalyst_score = 8.0 if ticker in material_today else 5.0
        theme = universe.get(ticker, {}).get("theme", "Current holding") or "Current holding"
        position = position_rows.get(ticker, {})
        role = (
            "current_position" if ticker in held else
            "core_allocation_candidate" if ticker == "SPY" else
            "individual_stock_candidate"
        )
        recommendation = (
            "hold_existing" if ticker in held else
            "core_allocation_candidate" if ticker == "SPY" else
            "watch_for_valuation"
        )
        primary_url = fundamental.get("source_url", "")
        rows.append({
            "ticker": ticker,
            "research_role": role,
            "current_position_status": position.get("current_action", "not_held"),
            "market_score": f"{market_score:.2f}",
            "portfolio_concentration_status": "calculated_downstream_from_current_shares_and_close",
            "theme": theme,
            "holding_horizon_candidate": position.get("horizon_class", "long_term_research"),
            "valuation_check": "deterministic_source_bound_valuation_follows_this_step",
            "filing_check": f"SEC companyfacts refreshed {fundamental.get('fetched_at', 'not_applicable_to_etf')}",
            "earnings_check": f"revenue_yoy_pct={fundamental.get('revenue_yoy_pct') or 'unavailable'}; net_margin_pct={fundamental.get('net_margin_pct') or 'unavailable'}",
            "news_check": "new_material_official_filing" if ticker in material_today else "no_new_material_official_filing_detected",
            "technical_check": f"completed_session={expected_session}; deterministic_market_score={market_score:.2f}",
            "risk_check": "position sizing and caps calculated from current whole shares downstream",
            "entry_discipline": "no purchase without valuation, evidence, portfolio-fit, and whole-share cap checks",
            "exit_or_trim_conditions": position.get("invalidation_rule", "reassess on evidence break or valuation/risk conflict"),
            "recommendation_label": recommendation,
            "recommendation_confidence": "medium_high" if fundamental.get("data_quality") == "ok" or is_benchmark else "medium",
            "human_action_required": "no",
            "notes": "Generated from the current completed close, current SEC evidence, and current local position truth; no stale C5 narrative used.",
            "business_quality_score": f"{business_score:.1f}",
            "earnings_revenue_trend_score": f"{earnings_score:.1f}",
            "valuation_reasonableness_score": "4.0",
            "catalyst_news_quality_score": f"{catalyst_score:.1f}",
            "technical_entry_discipline_score": f"{clamp(market_score):.1f}",
            "portfolio_fit_score": "5.0",
            "primary_source_url": primary_url,
            "filing_source_url": primary_url,
            "market_data_source": market_row.get("data_source", ""),
            "evidence_checked_at": iso_now(),
        })
    atomic_write_csv(OUTPUT_PATH, FIELDS, rows)
    print(
        f"current_research_baseline_rows={len(rows)} held={len(held)} "
        f"market_session={expected_session} stale_c5_used=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
