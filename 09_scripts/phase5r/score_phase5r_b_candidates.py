from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_b_run_log.csv"

CANDIDATES_PATH = DATA_DIR / "phase5r_b_candidates_with_market_data.csv"
SCORES_PATH = DATA_DIR / "phase5r_b_signal_scores.csv"
WATCHLIST_PATH = REVIEWS_DIR / "latest_phase5r_b_watchlist.md"
AUDIT_TRAIL = DATA_DIR / "phase5r_b_audit_trail.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}
FORMULA_VERSION = "phase5r_b_read_only_market_data_v1"

SCORE_FIELDS = [
    "rank",
    "ticker",
    "company_name",
    "theme",
    "last_price",
    "intraday_change_pct",
    "relative_volume",
    "dollar_volume",
    "trend_score",
    "volume_score",
    "catalyst_score",
    "quality_score",
    "risk_penalty",
    "total_score",
    "action_label",
    "data_source",
    "data_quality_label",
    "formula_version",
    "score_explanation",
]

AUDIT_FIELDS = [
    "timestamp",
    "script_name",
    "action",
    "input_path",
    "output_path",
    "status",
    "safety_notes",
]

VOLATILITY_PENALTY = {
    "low": 1.0,
    "medium": 2.5,
    "high": 5.5,
    "very_high": 7.5,
}

THEME_CATALYST = {
    "AI infrastructure": 8.5,
    "Semiconductors": 7.5,
    "Cybersecurity": 7.0,
    "Cloud software": 6.5,
    "Data centers": 7.0,
    "Benchmark ETF": 5.0,
}


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def as_float(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def trend_score(change_pct: float) -> float:
    return round(clamp(5.0 + change_pct * 1.2), 2)


def volume_score(relative_volume: float, dollar_volume: float) -> float:
    dollar_component = 1.0 if dollar_volume >= 1_000_000_000 else 0.0
    return round(clamp(4.0 + relative_volume * 2.0 + dollar_component), 2)


def quality_score(row: dict[str, str]) -> float:
    liquidity = {"mega": 9.0, "large": 7.5, "mid": 5.5}.get(row["liquidity_tier"], 5.0)
    benchmark_bonus = 0.5 if row["is_benchmark"] == "yes" else 0.0
    return round(clamp(liquidity + benchmark_bonus), 2)


def risk_penalty(row: dict[str, str], change_pct: float) -> float:
    base = VOLATILITY_PENALTY.get(row["volatility_tier"], 4.0)
    chase_penalty = max(0.0, change_pct - 3.0) * 0.8
    return round(clamp(base + chase_penalty), 2)


def total_score(row: dict[str, str]) -> float:
    return round(
        0.30 * float(row["trend_score"])
        + 0.25 * float(row["volume_score"])
        + 0.20 * float(row["catalyst_score"])
        + 0.15 * float(row["quality_score"])
        - 0.10 * float(row["risk_penalty"]),
        2,
    )


def action_label(score: float, data_quality: str) -> str:
    if data_quality == "insufficient_data":
        return "insufficient_data"
    if score >= 7.00:
        return "possible_buy_manual_review"
    if score >= 5.25:
        return "watch"
    return "avoid"


def score_candidate(row: dict[str, str]) -> dict[str, str]:
    ticker = row["ticker"].upper()
    if ticker in LEGACY_TICKERS:
        raise RuntimeError("Legacy IOT/RBRK ticker cannot enter Phase 5R-B scores")

    change_pct = as_float(row["intraday_change_pct"])
    rel_volume = as_float(row["relative_volume"])
    dollar_volume = as_float(row["dollar_volume"])
    if row["market_data_usable"] != "yes" or change_pct is None or rel_volume is None or dollar_volume is None:
        return {
            "rank": "",
            "ticker": ticker,
            "company_name": row["company_name"],
            "theme": row["theme"],
            "last_price": row["last_price"],
            "intraday_change_pct": row["intraday_change_pct"],
            "relative_volume": row["relative_volume"],
            "dollar_volume": row["dollar_volume"],
            "trend_score": "",
            "volume_score": "",
            "catalyst_score": "",
            "quality_score": "",
            "risk_penalty": "",
            "total_score": "0.00",
            "action_label": "insufficient_data",
            "data_source": row["data_source"],
            "data_quality_label": row["data_quality_label"],
            "formula_version": FORMULA_VERSION,
            "score_explanation": "Insufficient read-only market data; no scoreable signal produced.",
        }

    scored = {
        "rank": "",
        "ticker": ticker,
        "company_name": row["company_name"],
        "theme": row["theme"],
        "last_price": row["last_price"],
        "intraday_change_pct": row["intraday_change_pct"],
        "relative_volume": row["relative_volume"],
        "dollar_volume": row["dollar_volume"],
        "trend_score": f"{trend_score(change_pct):.2f}",
        "volume_score": f"{volume_score(rel_volume, dollar_volume):.2f}",
        "catalyst_score": f"{THEME_CATALYST.get(row['theme'], 5.0):.2f}",
        "quality_score": f"{quality_score(row):.2f}",
        "risk_penalty": f"{risk_penalty(row, change_pct):.2f}",
        "total_score": "",
        "action_label": "",
        "data_source": row["data_source"],
        "data_quality_label": row["data_quality_label"],
        "formula_version": FORMULA_VERSION,
        "score_explanation": "",
    }
    score = total_score(scored)
    scored["total_score"] = f"{score:.2f}"
    scored["action_label"] = action_label(score, row["data_quality_label"])
    scored["score_explanation"] = (
        f"Read-only market score {score:.2f}; trend={scored['trend_score']}, "
        f"volume={scored['volume_score']}, catalyst={scored['catalyst_score']}, "
        f"quality={scored['quality_score']}, risk_penalty={scored['risk_penalty']}."
    )
    return scored


def write_watchlist(rows: list[dict[str, str]]) -> None:
    lines = [
        "# Latest Phase 5R-B Watchlist",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "This watchlist uses the Phase 5R-B read-only market data adapter. It is not an order recommendation and cannot execute trades.",
        "",
        "| Rank | Ticker | Company | Theme | Price | Score | Action | Data Quality |",
        "| ---: | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        if row["action_label"] in {"possible_buy_manual_review", "watch", "insufficient_data"}:
            lines.append(
                f"| {row['rank']} | {row['ticker']} | {row['company_name']} | {row['theme']} | {row['last_price'] or 'n/a'} | {row['total_score']} | {row['action_label']} | {row['data_quality_label']} |"
            )
    lines.extend(
        [
            "",
            "Manual execution boundary: no broker connection, no order placement, no email automation, no archived IOT/RBRK legacy data.",
        ]
    )
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    candidates = read_csv(CANDIDATES_PATH)
    score_rows = [score_candidate(row) for row in candidates]
    score_rows.sort(key=lambda item: (-float(item["total_score"]), item["ticker"]))
    for index, row in enumerate(score_rows, start=1):
        row["rank"] = str(index)

    write_csv(SCORES_PATH, score_rows, SCORE_FIELDS)
    write_watchlist(score_rows)

    now = timestamp()
    safety = "read_only_scoring=yes; manual_execution_only=yes; credentialless=yes; no_broker=yes; no_orders=yes; no_email=yes; archived_legacy_used=no"
    append_csv(
        AUDIT_TRAIL,
        {
            "timestamp": now,
            "script_name": Path(__file__).name,
            "action": "score_phase5r_b_candidates",
            "input_path": str(CANDIDATES_PATH.relative_to(ROOT)),
            "output_path": f"{SCORES_PATH.relative_to(ROOT)};{WATCHLIST_PATH.relative_to(ROOT)}",
            "status": "complete",
            "safety_notes": safety,
        },
        AUDIT_FIELDS,
    )
    append_csv(
        RUN_LOG,
        {
            "timestamp": now,
            "script_name": Path(__file__).name,
            "action": "score_phase5r_b_candidates",
            "input_path": str(CANDIDATES_PATH.relative_to(ROOT)),
            "output_path": f"{SCORES_PATH.relative_to(ROOT)};{WATCHLIST_PATH.relative_to(ROOT)}",
            "status": "complete",
            "safety_notes": safety,
        },
        AUDIT_FIELDS,
    )
    print(f"Wrote Phase 5R-B signal score rows: {len(score_rows)}")


if __name__ == "__main__":
    main()
