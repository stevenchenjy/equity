from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from phase5r_daily_common import latest_published_market_session, now_et


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_b2_run_log.csv"
CANDIDATES_PATH = DATA_DIR / "phase5r_b2_candidates_with_market_data.csv"
SCORES_PATH = DATA_DIR / "phase5r_b2_signal_scores.csv"
AUDIT_PATH = DATA_DIR / "phase5r_b2_audit_trail.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}
FORMULA_VERSION = "phase5r_b2_daily_read_only_v1"
SCORE_FIELDS = [
    "rank", "ticker", "company_name", "theme", "last_price", "intraday_change_pct", "relative_volume", "dollar_volume",
    "trend_score", "volume_score", "catalyst_score", "quality_score", "risk_penalty", "total_score", "action_label",
    "data_source", "data_quality_label", "formula_version", "score_explanation",
]
AUDIT_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "safety_notes"]
VOLATILITY_PENALTY = {"low": 1.0, "medium": 2.5, "high": 5.5, "very_high": 7.5}
THEME_CATALYST = {"AI infrastructure": 8.5, "Semiconductors": 7.5, "Cybersecurity": 7.0, "Cloud software": 6.5, "Data centers": 7.0, "Benchmark ETF": 5.0}


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


def append_audit(action: str, outputs: str) -> None:
    row = {
        "timestamp": timestamp(), "script_name": Path(__file__).name, "action": action,
        "input_path": str(CANDIDATES_PATH.relative_to(ROOT)), "output_path": outputs, "status": "complete",
        "safety_notes": "read_only_scoring=yes; manual_execution_only=yes; no_broker=yes; no_orders=yes; no_email=yes; no_credentials=yes; archived_legacy_used=no",
    }
    for path in (AUDIT_PATH, RUN_LOG):
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow(row)


def as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float) -> float:
    return max(0.0, min(10.0, value))


def score_row(
    row: dict[str, str], *, expected_market_session: str | None = None
) -> dict[str, str]:
    ticker = row["ticker"].upper()
    if ticker in LEGACY_TICKERS:
        raise RuntimeError("Legacy IOT/RBRK tickers are excluded from Phase 5R-B2")
    change, rel_volume, dollar_volume = (as_float(row[key]) for key in ("intraday_change_pct", "relative_volume", "dollar_volume"))
    base = {
        "rank": "", "ticker": ticker, "company_name": row["company_name"], "theme": row["theme"], "last_price": row["last_price"],
        "intraday_change_pct": row["intraday_change_pct"], "relative_volume": row["relative_volume"], "dollar_volume": row["dollar_volume"],
        "data_source": row["data_source"], "data_quality_label": row["data_quality_label"], "formula_version": FORMULA_VERSION,
    }
    current_session = (
        expected_market_session is None
        or row.get("market_session_date") == expected_market_session
    )
    if (
        not current_session
        or row["market_data_usable"] != "yes"
        or None in {change, rel_volume, dollar_volume}
    ):
        explanation = (
            "Market session is stale; no scoreable signal produced."
            if not current_session
            else "Incomplete public market data; no scoreable signal produced."
        )
        return base | {
            "trend_score": "", "volume_score": "", "catalyst_score": "", "quality_score": "", "risk_penalty": "",
            "total_score": "0.00", "action_label": "insufficient_data", "score_explanation": explanation,
        }
    trend = round(clamp(5.0 + change * 1.2), 2)
    volume = round(clamp(4.0 + rel_volume * 2.0 + (1.0 if dollar_volume >= 1_000_000_000 else 0.0)), 2)
    catalyst = THEME_CATALYST.get(row["theme"], 5.0)
    quality = {"mega": 9.0, "large": 7.5, "mid": 5.5}.get(row["liquidity_tier"], 5.0) + (0.5 if row["is_benchmark"] == "yes" else 0.0)
    penalty = round(clamp(VOLATILITY_PENALTY.get(row["volatility_tier"], 4.0) + max(0.0, change - 3.0) * 0.8), 2)
    total = round(0.30 * trend + 0.25 * volume + 0.20 * catalyst + 0.15 * quality - 0.10 * penalty, 2)
    action = "possible_buy_manual_review" if total >= 7.0 else "watch" if total >= 5.25 else "avoid"
    return base | {
        "trend_score": f"{trend:.2f}", "volume_score": f"{volume:.2f}", "catalyst_score": f"{catalyst:.2f}",
        "quality_score": f"{quality:.2f}", "risk_penalty": f"{penalty:.2f}", "total_score": f"{total:.2f}", "action_label": action,
        "score_explanation": f"Daily read-only score {total:.2f}; trend={trend:.2f}, volume={volume:.2f}, catalyst={catalyst:.2f}, quality={quality:.2f}, risk_penalty={penalty:.2f}.",
    }


def main() -> None:
    expected_session = latest_published_market_session(now_et()).isoformat()
    scores = [
        score_row(row, expected_market_session=expected_session)
        for row in read_csv(CANDIDATES_PATH)
    ]
    scores.sort(key=lambda row: (-float(row["total_score"]), row["ticker"]))
    for index, row in enumerate(scores, start=1):
        row["rank"] = str(index)
    write_csv(SCORES_PATH, scores, SCORE_FIELDS)
    append_audit("score_phase5r_b2_candidates", str(SCORES_PATH.relative_to(ROOT)))
    print(f"Wrote Phase 5R-B2 score rows: {len(scores)}")


if __name__ == "__main__":
    main()
