from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_c5_run_log.csv"

QUEUE = RESEARCH_DIR / "phase5r_c5_research_queue.csv"
SNAPSHOT = DATA_DIR / "phase5r_b2_market_data_snapshot.csv"
LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
OUTPUT = RESEARCH_DIR / "phase5r_c5_company_research_packets.csv"

DEEP_FIELDS = [
    "ticker", "research_role", "current_position_status", "market_score",
    "portfolio_concentration_status", "theme", "holding_horizon_candidate", "valuation_check",
    "filing_check", "earnings_check", "news_check", "technical_check", "risk_check",
    "entry_discipline", "exit_or_trim_conditions", "recommendation_label",
    "recommendation_confidence", "human_action_required", "notes",
]
PACKET_FIELDS = DEEP_FIELDS + [
    "business_quality_score", "earnings_revenue_trend_score", "valuation_reasonableness_score",
    "catalyst_news_quality_score", "technical_entry_discipline_score", "portfolio_fit_score",
    "primary_source_url", "filing_source_url", "market_data_source", "evidence_checked_at",
]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "research_rows", "current_position_rows", "new_candidate_rows", "eligible_buy_review_count",
    "email_sent", "scheduler_used", "broker_used", "smtp_config_modified",
    "archived_legacy_used", "safety_notes",
]

EVIDENCE = {
    "IOT": {
        "horizon": "medium_conviction", "business": 8.0, "earnings": 8.5, "valuation": 4.5, "catalyst": 7.5, "fit": 0.5,
        "valuation_check": "Strong growth merits continued study, but valuation is not independently cheap and the current weight dominates portfolio fit.",
        "filing_check": "Q1 FY2027 Form 10-Q filed 2026-06-09; review risk factors and stock-based compensation at each weekly thesis check.",
        "earnings_check": "Q1 FY2027 revenue was $478.8M, up 31% year over year; ending ARR was $1.991B, up 30%; GAAP EPS was positive for a third consecutive quarter.",
        "news_check": "June investor materials emphasize Operational AI and physical-economy workflow expansion; treat company outlook as forward-looking evidence.",
        "risk_check": "29.59% position exceeds the 8% hard cap; growth-stock valuation, competition, and execution remain material risks.",
        "label": "trim_review", "confidence": "high",
        "primary": "https://www.sec.gov/Archives/edgar/data/1642896/000162828026040788/samsaraepr-q12027.htm",
        "filing": "https://www.sec.gov/Archives/edgar/data/1642896/000162828026041893/iot-20260502.htm",
    },
    "RBRK": {
        "horizon": "medium_conviction", "business": 8.0, "earnings": 8.5, "valuation": 4.5, "catalyst": 8.0, "fit": 1.0,
        "valuation_check": "Rapid subscription growth and improving cash generation support quality, but a still-developing earnings profile and current concentration require a valuation discount.",
        "filing_check": "Q1 FY2027 Form 10-Q for the quarter ended 2026-04-30 reviewed; monitor GAAP loss, stock compensation, and platform execution.",
        "earnings_check": "Q1 FY2027 subscription ARR grew 32% to $1.57B, revenue grew 39% to $387.1M, and free-cash-flow margin was 19%.",
        "news_check": "Official results highlighted cyber resilience, identity, and AI operations expansion; adoption evidence is positive but forward execution remains important.",
        "risk_check": "17.75% position exceeds the 8% hard cap; emerging-company volatility, GAAP losses, competition, and platform execution require review.",
        "label": "trim_review", "confidence": "high",
        "primary": "https://ir.rubrik.com/financials/quarterly-results/default.aspx",
        "filing": "https://www.sec.gov/Archives/edgar/data/1943896/000194389626000047/rbrk-20260430.htm",
    },
    "META": {
        "horizon": "core_compounder", "business": 9.0, "earnings": 9.0, "valuation": 5.5, "catalyst": 8.0, "fit": 2.0,
        "valuation_check": "Scale and cash generation are strong, but large AI capital spending and the concentrated technology sleeve require patient entry discipline.",
        "filing_check": "Q1 2026 results reference the 2026 10-K and forthcoming 10-Q; legal, regulatory, privacy, and infrastructure-spending risks remain material.",
        "earnings_check": "Q1 2026 revenue was $56.31B, up 33%; operating income rose 30%; free cash flow was $12.39B.",
        "news_check": "Official results cite strong app momentum and initial Meta Superintelligence Labs model progress, alongside higher planned infrastructure spending.",
        "risk_check": "Active sleeve is already 47.34%; regulatory exposure, advertising dependence, and AI capital intensity reduce portfolio fit.",
        "label": "wait_for_pullback", "confidence": "medium_high",
        "primary": "https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx",
        "filing": "https://investor.atmeta.com/financials/sec-filings/default.aspx",
    },
    "AVGO": {
        "horizon": "core_compounder", "business": 9.0, "earnings": 9.0, "valuation": 5.0, "catalyst": 9.0, "fit": 1.5,
        "valuation_check": "Exceptional AI semiconductor growth and free cash flow are offset by elevated expectations and a crowded AI-infrastructure sleeve.",
        "filing_check": "Q2 FY2026 10-Q filed 2026-06-09; integration, customer concentration, debt, and semiconductor-cycle risks require review.",
        "earnings_check": "Q2 FY2026 revenue was $22.19B, up 48%; AI semiconductor revenue grew 143%; free cash flow was $10.26B.",
        "news_check": "Management expects continued custom accelerator and AI-networking momentum; forward guidance raises both opportunity and expectation risk.",
        "risk_check": "AI-infrastructure overlap and the above-target active sleeve materially penalize portfolio fit.",
        "label": "watch_only", "confidence": "medium_high",
        "primary": "https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-second-quarter-fiscal-year-2026-financial",
        "filing": "https://investors.broadcom.com/financial-information/financial-reports",
    },
    "PANW": {
        "horizon": "core_compounder", "business": 8.5, "earnings": 8.0, "valuation": 5.5, "catalyst": 8.0, "fit": 4.0,
        "valuation_check": "Platform growth and cash flow are attractive, but acquisition effects and premium cybersecurity expectations require a disciplined review level.",
        "filing_check": "FY2026 Q3 official results and quarterly materials reviewed; separate organic performance from acquired revenue and monitor GAAP profitability.",
        "earnings_check": "FY2026 Q3 revenue grew 31% to $3.0B; NGS ARR grew 60% to $8.1B; trailing adjusted free-cash-flow margin was 38.5%.",
        "news_check": "AI-security demand and platform expansion are constructive; integration complexity is the central current execution check.",
        "risk_check": "Cybersecurity diversifies the AI hardware cluster, but the active stock sleeve remains above target.",
        "label": "watch_only", "confidence": "medium_high",
        "primary": "https://investors.paloaltonetworks.com/news-releases/news-release-details/palo-alto-networks-reports-fiscal-third-quarter-2026-financial",
        "filing": "https://investors.paloaltonetworks.com/financial-information/quarterly-results",
    },
    "MU": {
        "horizon": "short_swing", "business": 7.5, "earnings": 9.0, "valuation": 4.0, "catalyst": 9.0, "fit": 1.0,
        "valuation_check": "Record results are compelling, but the memory cycle, extreme recent price range, and unusually strong expectations make valuation normalization difficult.",
        "filing_check": "Fiscal Q3 2026 10-Q filed 2026-06-25; inspect cycle sensitivity, customer agreements, supply investment, and margin durability.",
        "earnings_check": "Fiscal Q3 revenue was $41.46B versus $9.30B a year earlier; operating cash flow was $25.39B; management reported record results.",
        "news_check": "HBM and strategic customer agreements are major catalysts, while capacity investment and cyclicality remain central checks.",
        "risk_check": "High volatility, memory cyclicality, and AI-infrastructure overlap sharply reduce portfolio fit.",
        "label": "watch_only", "confidence": "medium",
        "primary": "https://investors.micron.com/node/50671",
        "filing": "https://investors.micron.com/static-files/23023765-dfef-4e7e-845b-cd744fc20d93",
    },
    "AMD": {
        "horizon": "medium_conviction", "business": 8.5, "earnings": 8.5, "valuation": 4.5, "catalyst": 8.5, "fit": 1.0,
        "valuation_check": "Accelerating data-center demand supports quality, but high volatility and substantial AI expectations require a wider margin of safety.",
        "filing_check": "Q1 2026 10-Q filed 2026-05-06; review export restrictions, competition, supply, and execution across accelerators and CPUs.",
        "earnings_check": "Q1 2026 revenue was $10.25B, up 38%; data-center revenue grew 57%; GAAP operating income rose 83%.",
        "news_check": "MI450, Helios, and server demand are constructive catalysts, with next earnings scheduled for early August 2026.",
        "risk_check": "High volatility, product-cycle competition, and existing AI-theme concentration require a wait stance.",
        "label": "watch_only", "confidence": "medium",
        "primary": "https://ir.amd.com/news-events/press-releases/detail/1284/amd-reports-first-quarter-2026-financial-results",
        "filing": "https://ir.amd.com/financial-information/sec-filings/content/0000002488-26-000076/amd-20260328.htm",
    },
    "ARM": {
        "horizon": "medium_conviction", "business": 8.0, "earnings": 7.5, "valuation": 3.5, "catalyst": 8.0, "fit": 1.0,
        "valuation_check": "Royalty economics and AI compute exposure are attractive, but very high volatility and premium expectations leave little room for execution misses.",
        "filing_check": "FY2026 Q4 shareholder materials and Form 6-K reviewed; monitor customer concentration, China exposure, and licensing-cycle variability.",
        "earnings_check": "FY2026 Q4 revenue was reported at a record $1.49B, up 20%, with a record fiscal year.",
        "news_check": "AI compute adoption is a durable catalyst; the next quarterly release is scheduled for late July 2026.",
        "risk_check": "Very high volatility and direct AI-infrastructure overlap create weak portfolio fit at the current sleeve level.",
        "label": "watch_only", "confidence": "medium",
        "primary": "https://investors.arm.com/news-releases/news-release-details/arm-holdings-plc-reports-results-fourth-quarter-financial-year-0",
        "filing": "https://investors.arm.com/static-files/adf3bac7-1e91-442e-92e0-5f2d8f1b6a14",
    },
    "SPY": {
        "horizon": "core_compounder", "business": 9.0, "earnings": 7.0, "valuation": 5.5, "catalyst": 5.0, "fit": 8.0,
        "valuation_check": "Broad exposure improves diversification, but current index valuation and a 37% technology weight argue for measured entry review.",
        "filing_check": "Official fund page, prospectus, and March 2026 factsheet reviewed; the fund tracks the S&P 500 before expenses.",
        "earnings_check": "ETF-level earnings are diversified across the S&P 500; no single-company earnings thesis applies.",
        "news_check": "Use as a diversification reference rather than a short-term catalyst idea.",
        "risk_check": "Broad-market risk remains, and the fund still carries meaningful technology exposure; active sleeve is above target.",
        "label": "wait_for_pullback", "confidence": "medium_high",
        "primary": "https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy",
        "filing": "https://www.ssga.com/library-content/products/factsheets/etfs/us/factsheet-us-en-spy.pdf",
    },
}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def public_market_context(ticker: str, snapshots: dict[str, dict[str, str]]) -> tuple[str, float, str]:
    row = snapshots.get(ticker)
    if row:
        low = float(row["fifty_two_week_low"])
        high = float(row["fifty_two_week_high"])
        price = float(row["last_price"])
        location = 50.0 if high <= low else 100.0 * (price - low) / (high - low)
        score = max(1.0, min(9.0, 7.0 - abs(location - 55.0) / 18.0))
        return (
            f"B2 public snapshot: ${price:.2f}, {float(row['intraday_change_pct']):+.2f}% daily, "
            f"{location:.0f}% through the 52-week range; weekly entry review should not chase daily strength.",
            round(score, 1), row["data_source"],
        )
    try:
        import yfinance as yf

        history = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=False, timeout=15)
        if history.empty:
            raise RuntimeError("empty public history")
        closes = history["Close"].dropna()
        price = float(closes.iloc[-1])
        low = float(history["Low"].min())
        high = float(history["High"].max())
        location = 50.0 if high <= low else 100.0 * (price - low) / (high - low)
        score = max(1.0, min(9.0, 7.0 - abs(location - 55.0) / 18.0))
        return (
            f"Read-only yfinance context: ${price:.2f}, {location:.0f}% through the trailing one-year range; "
            "use only for weekly entry context.", round(score, 1), "yfinance_public_market_data",
        )
    except Exception:
        return "Public technical context unavailable; no price or signal was invented.", 4.0, "public_market_data_unavailable"


def append_log(row_count: int, current_count: int) -> None:
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5", "script_name": Path(__file__).name,
            "action": "create_controlled_company_research_packets",
            "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [QUEUE, SNAPSHOT, LOCAL_POSITIONS]),
            "output_paths": str(OUTPUT.relative_to(ROOT)), "status": "complete", "research_rows": str(row_count),
            "current_position_rows": str(current_count), "new_candidate_rows": str(row_count - current_count),
            "eligible_buy_review_count": "0", "email_sent": "no", "scheduler_used": "no",
            "broker_used": "no", "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "controlled_primary_sources=yes; public_market_data_read_only=yes; manual_review_only=yes",
        })


def main() -> None:
    queue = read_csv(QUEUE)
    positions = {row["ticker"].upper(): row for row in read_csv(LOCAL_POSITIONS)}
    snapshots = {row["ticker"].upper(): row for row in read_csv(SNAPSHOT)}
    rows: list[dict[str, str]] = []
    checked = timestamp()
    for item in queue:
        ticker = item["ticker"].upper()
        evidence = EVIDENCE.get(ticker)
        if evidence is None:
            raise RuntimeError(f"No controlled source packet for queued ticker {ticker}")
        technical_text, technical_score, market_source = public_market_context(ticker, snapshots)
        current = positions.get(ticker)
        pct = float(item["position_pct"])
        is_current = item["research_role"] == "current_position_risk_review"
        entry = (
            "Do not add while above the 8% hard cap; review thesis and concentration on the weekly cadence."
            if is_current else
            "Wait for a weekly entry review with valuation support, stable public data, and no response to one-day momentum."
        )
        exit_conditions = (
            "Trim review remains warranted while above 8%; escalate to exit review only for a material thesis, filing, governance, or earnings break."
            if is_current else
            "Remove from the active queue if earnings quality, filing risk, catalyst quality, or portfolio fit materially weakens."
        )
        rows.append({
            "ticker": ticker, "research_role": item["research_role"],
            "current_position_status": f"current_local_position_{pct:.2f}_pct" if current else "not_held",
            "market_score": item["market_score"] or "not_in_b2_universe",
            "portfolio_concentration_status": item["portfolio_concentration_status"], "theme": item["theme"],
            "holding_horizon_candidate": evidence["horizon"], "valuation_check": evidence["valuation_check"],
            "filing_check": evidence["filing_check"], "earnings_check": evidence["earnings_check"],
            "news_check": evidence["news_check"], "technical_check": technical_text,
            "risk_check": evidence["risk_check"], "entry_discipline": entry,
            "exit_or_trim_conditions": exit_conditions, "recommendation_label": evidence["label"],
            "recommendation_confidence": evidence["confidence"], "human_action_required": "yes",
            "notes": "Weekly research classification only; evidence may become stale and requires independent review.",
            "business_quality_score": f"{evidence['business']:.1f}",
            "earnings_revenue_trend_score": f"{evidence['earnings']:.1f}",
            "valuation_reasonableness_score": f"{evidence['valuation']:.1f}",
            "catalyst_news_quality_score": f"{evidence['catalyst']:.1f}",
            "technical_entry_discipline_score": f"{technical_score:.1f}",
            "portfolio_fit_score": f"{evidence['fit']:.1f}", "primary_source_url": evidence["primary"],
            "filing_source_url": evidence["filing"], "market_data_source": market_source,
            "evidence_checked_at": checked,
        })
    write_csv(OUTPUT, rows, PACKET_FIELDS)
    append_log(len(rows), sum(row["research_role"] == "current_position_risk_review" for row in rows))
    print(f"Created Phase 5R-C5 company packets: rows={len(rows)}")


if __name__ == "__main__":
    main()
