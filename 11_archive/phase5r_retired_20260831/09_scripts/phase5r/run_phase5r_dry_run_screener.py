from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "04_data" / "phase5r_universe_seed.csv"
CANDIDATES_PATH = ROOT / "04_data" / "phase5r_dry_run_candidates.csv"
AUDIT_TRAIL = ROOT / "04_data" / "phase5r_audit_trail.csv"
RUN_LOG = ROOT / "06_logs" / "phase5r_a_run_log.csv"

CANDIDATE_FIELDS = [
    "ticker",
    "company_name",
    "theme",
    "price_placeholder",
    "intraday_change_pct_placeholder",
    "relative_volume_placeholder",
    "dollar_volume_placeholder",
    "trend_score",
    "volume_score",
    "catalyst_score",
    "quality_score",
    "risk_penalty",
    "total_score",
    "action_label",
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

# Static dry-run placeholder data. These values are not live market data.
PLACEHOLDER_MARKET_DATA = {
    "NVDA": (128.40, 2.6, 1.8, 31500000000),
    "AMD": (164.25, 1.8, 1.5, 11800000000),
    "AVGO": (1725.50, 1.1, 1.3, 8900000000),
    "TSM": (184.10, 0.8, 1.2, 4300000000),
    "ASML": (1012.20, 0.4, 1.0, 1900000000),
    "ARM": (141.30, 3.4, 1.7, 5100000000),
    "MU": (134.60, 2.0, 1.6, 6200000000),
    "SMCI": (864.00, 4.2, 2.2, 7800000000),
    "VRT": (95.80, 2.8, 1.9, 2600000000),
    "EQIX": (770.50, 0.3, 0.8, 650000000),
    "DLR": (151.40, -0.2, 0.7, 540000000),
    "MSFT": (445.20, 0.9, 1.1, 9200000000),
    "GOOGL": (176.40, 0.6, 1.0, 6100000000),
    "AMZN": (191.10, 1.2, 1.2, 7600000000),
    "META": (512.80, 1.5, 1.3, 8100000000),
    "ORCL": (138.70, 0.5, 1.1, 2100000000),
    "NOW": (755.90, 0.7, 0.9, 950000000),
    "CRM": (254.20, -0.4, 0.9, 1600000000),
    "SNOW": (133.50, 2.4, 1.4, 1300000000),
    "DDOG": (127.30, 1.9, 1.5, 1150000000),
    "NET": (92.60, 2.7, 1.6, 980000000),
    "CRWD": (372.10, 2.1, 1.4, 2200000000),
    "PANW": (336.00, 0.8, 1.0, 1850000000),
    "ZS": (196.40, 1.6, 1.3, 720000000),
    "QQQ": (482.60, 0.7, 1.0, 18400000000),
    "XLK": (226.80, 0.6, 0.9, 3100000000),
    "SPY": (548.20, 0.4, 1.0, 38600000000),
}

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


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


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


def action_label(score: float, row: dict[str, str]) -> str:
    if row["price_placeholder"] == "" or row["relative_volume_placeholder"] == "":
        return "insufficient_data"
    if score >= 7.00:
        return "possible_buy_manual_review"
    if score >= 5.25:
        return "watch"
    return "avoid"


def main() -> None:
    with UNIVERSE_PATH.open(newline="", encoding="utf-8") as handle:
        universe = list(csv.DictReader(handle))

    rows: list[dict[str, str]] = []
    for seed in universe:
        ticker = seed["ticker"]
        if ticker in {"IOT", "RBRK"}:
            raise RuntimeError("Legacy IOT/RBRK ticker cannot enter Phase 5R dry-run candidates")
        placeholder = PLACEHOLDER_MARKET_DATA.get(ticker)
        if placeholder is None:
            candidate = {
                "ticker": ticker,
                "company_name": seed["company_name"],
                "theme": seed["theme"],
                "price_placeholder": "",
                "intraday_change_pct_placeholder": "",
                "relative_volume_placeholder": "",
                "dollar_volume_placeholder": "",
                "trend_score": "",
                "volume_score": "",
                "catalyst_score": "",
                "quality_score": "",
                "risk_penalty": "",
                "total_score": "",
                "action_label": "insufficient_data",
            }
            rows.append(candidate)
            continue

        price, change_pct, relative_volume, dollar_volume = placeholder
        candidate = {
            "ticker": ticker,
            "company_name": seed["company_name"],
            "theme": seed["theme"],
            "price_placeholder": f"{price:.2f}",
            "intraday_change_pct_placeholder": f"{change_pct:.2f}",
            "relative_volume_placeholder": f"{relative_volume:.2f}",
            "dollar_volume_placeholder": f"{int(dollar_volume)}",
            "trend_score": f"{trend_score(change_pct):.2f}",
            "volume_score": f"{volume_score(relative_volume, dollar_volume):.2f}",
            "catalyst_score": f"{THEME_CATALYST.get(seed['theme'], 5.0):.2f}",
            "quality_score": f"{quality_score(seed):.2f}",
            "risk_penalty": f"{risk_penalty(seed, change_pct):.2f}",
            "total_score": "",
            "action_label": "",
        }
        score = total_score(candidate)
        candidate["total_score"] = f"{score:.2f}"
        candidate["action_label"] = action_label(score, candidate)
        rows.append(candidate)

    rows.sort(key=lambda item: (item["action_label"] != "possible_buy_manual_review", -float(item["total_score"] or 0), item["ticker"]))

    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CANDIDATES_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    now = timestamp()
    safety = "static_placeholder_data_only=yes; network_calls=no; no_env_read=yes; no_broker=yes; old_iot_rbrk_data_used=no"
    for log_path in (AUDIT_TRAIL, RUN_LOG):
        append_csv(
            log_path,
            {
                "timestamp": now,
                "script_name": Path(__file__).name,
                "action": "run_phase5r_dry_run_screener",
                "input_path": str(UNIVERSE_PATH.relative_to(ROOT)),
                "output_path": str(CANDIDATES_PATH.relative_to(ROOT)),
                "status": "complete",
                "safety_notes": safety,
            },
            AUDIT_FIELDS,
        )
    print(f"Wrote {len(rows)} dry-run candidates to {CANDIDATES_PATH}")


if __name__ == "__main__":
    main()
