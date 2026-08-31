from __future__ import annotations

import csv
import importlib
import importlib.util
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PHASE5R_DATA_DIR = ROOT / "03_source_data" / "phase5r"
UNIVERSE_PATH = PHASE5R_DATA_DIR / "phase5r_universe_seed.csv"
MANUAL_FALLBACK_PATH = PHASE5R_DATA_DIR / "phase5r_b_manual_market_data_fallback.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}

MARKET_DATA_FIELDS = [
    "ticker",
    "last_price",
    "previous_close",
    "intraday_change_pct",
    "volume",
    "average_volume",
    "relative_volume",
    "dollar_volume",
    "day_high",
    "day_low",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "data_timestamp",
    "data_source",
    "data_quality_label",
]

REQUIRED_NUMERIC_FIELDS = [
    "last_price",
    "previous_close",
    "intraday_change_pct",
    "volume",
    "average_volume",
    "relative_volume",
    "dollar_volume",
]


@dataclass(frozen=True)
class AdapterDecision:
    selected_source: str
    yfinance_available: bool
    manual_fallback_available: bool
    fail_safe_reason: str


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_universe(path: Path = UNIVERSE_PATH) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Canonical Phase 5R universe seed is missing: {path}")
    if "11_archive" in path.parts:
        raise RuntimeError("Archived legacy folders cannot be used as Phase 5R-B inputs")
    rows = read_csv(path)
    legacy = sorted({row.get("ticker", "").upper() for row in rows} & LEGACY_TICKERS)
    if legacy:
        raise RuntimeError(f"Legacy tickers are not allowed in Phase 5R-B universe: {legacy}")
    return rows


def yfinance_available() -> bool:
    return importlib.util.find_spec("yfinance") is not None


def blank_market_row(ticker: str, source: str, quality: str, now: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "last_price": "",
        "previous_close": "",
        "intraday_change_pct": "",
        "volume": "",
        "average_volume": "",
        "relative_volume": "",
        "dollar_volume": "",
        "day_high": "",
        "day_low": "",
        "fifty_two_week_high": "",
        "fifty_two_week_low": "",
        "data_timestamp": now,
        "data_source": source,
        "data_quality_label": quality,
    }


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, "item"):
            value = value.item()
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result


def fmt_float(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def fmt_int(value: float | None) -> str:
    return "" if value is None else str(int(round(value)))


def quality_label(row: dict[str, str]) -> str:
    missing = [field for field in REQUIRED_NUMERIC_FIELDS if row.get(field, "") == ""]
    if not missing:
        return "ok"
    if row.get("last_price") and row.get("previous_close"):
        return "partial"
    return "insufficient_data"


def read_manual_fallback(tickers: list[str], now: str) -> tuple[list[dict[str, str]], str]:
    if not MANUAL_FALLBACK_PATH.exists():
        rows = [blank_market_row(ticker, "manual_csv_fallback_missing", "insufficient_data", now) for ticker in tickers]
        return rows, "manual fallback file not present; no market values invented"
    if "11_archive" in MANUAL_FALLBACK_PATH.parts:
        raise RuntimeError("Manual fallback cannot be loaded from archived legacy folders")

    manual_rows = {row.get("ticker", "").upper(): row for row in read_csv(MANUAL_FALLBACK_PATH)}
    rows: list[dict[str, str]] = []
    for ticker in tickers:
        if ticker in LEGACY_TICKERS:
            raise RuntimeError(f"Legacy ticker cannot enter Phase 5R-B fallback: {ticker}")
        source = manual_rows.get(ticker)
        if not source:
            rows.append(blank_market_row(ticker, "manual_csv_fallback", "insufficient_data", now))
            continue
        row = {field: source.get(field, "") for field in MARKET_DATA_FIELDS}
        row["ticker"] = ticker
        row["data_timestamp"] = row.get("data_timestamp") or now
        row["data_source"] = "manual_csv_fallback"
        row["data_quality_label"] = quality_label(row)
        rows.append(row)
    return rows, f"manual fallback file used: {MANUAL_FALLBACK_PATH.relative_to(ROOT)}"


def fetch_with_yfinance(tickers: list[str], now: str) -> tuple[list[dict[str, str]], str]:
    yf = importlib.import_module("yfinance")
    rows: list[dict[str, str]] = []
    for ticker in tickers:
        if ticker in LEGACY_TICKERS:
            raise RuntimeError(f"Legacy ticker cannot enter Phase 5R-B yfinance adapter: {ticker}")
        row = blank_market_row(ticker, "yfinance_public_market_data", "insufficient_data", now)
        try:
            ticker_obj = yf.Ticker(ticker)
            fast_info = getattr(ticker_obj, "fast_info", {}) or {}
            history = ticker_obj.history(period="5d", interval="1d", auto_adjust=False)
            last_price = as_float(fast_info.get("last_price") or fast_info.get("lastPrice"))
            previous_close = as_float(fast_info.get("previous_close") or fast_info.get("previousClose"))
            volume = as_float(fast_info.get("last_volume") or fast_info.get("lastVolume"))
            average_volume = as_float(fast_info.get("three_month_average_volume") or fast_info.get("threeMonthAverageVolume"))
            day_high = as_float(fast_info.get("day_high") or fast_info.get("dayHigh"))
            day_low = as_float(fast_info.get("day_low") or fast_info.get("dayLow"))
            year_high = as_float(fast_info.get("year_high") or fast_info.get("yearHigh"))
            year_low = as_float(fast_info.get("year_low") or fast_info.get("yearLow"))

            if last_price is None and not history.empty:
                last_price = as_float(history["Close"].iloc[-1])
            if previous_close is None and len(history.index) >= 2:
                previous_close = as_float(history["Close"].iloc[-2])
            if volume is None and not history.empty:
                volume = as_float(history["Volume"].iloc[-1])
            if average_volume is None and not history.empty:
                average_volume = as_float(history["Volume"].tail(min(5, len(history.index))).mean())
            if day_high is None and not history.empty:
                day_high = as_float(history["High"].iloc[-1])
            if day_low is None and not history.empty:
                day_low = as_float(history["Low"].iloc[-1])

            intraday_change_pct = None
            if last_price is not None and previous_close not in {None, 0.0}:
                intraday_change_pct = ((last_price - previous_close) / previous_close) * 100.0
            relative_volume = None
            if volume is not None and average_volume not in {None, 0.0}:
                relative_volume = volume / average_volume
            dollar_volume = None
            if last_price is not None and volume is not None:
                dollar_volume = last_price * volume

            row.update(
                {
                    "last_price": fmt_float(last_price),
                    "previous_close": fmt_float(previous_close),
                    "intraday_change_pct": fmt_float(intraday_change_pct),
                    "volume": fmt_int(volume),
                    "average_volume": fmt_int(average_volume),
                    "relative_volume": fmt_float(relative_volume),
                    "dollar_volume": fmt_int(dollar_volume),
                    "day_high": fmt_float(day_high),
                    "day_low": fmt_float(day_low),
                    "fifty_two_week_high": fmt_float(year_high),
                    "fifty_two_week_low": fmt_float(year_low),
                }
            )
            row["data_quality_label"] = quality_label(row)
        except Exception:
            row = blank_market_row(ticker, "yfinance_public_market_data_error", "insufficient_data", now)
        rows.append(row)
    return rows, "yfinance public market data adapter used"


def load_market_data(universe_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], AdapterDecision]:
    tickers = [row["ticker"].upper() for row in universe_rows]
    now = timestamp()
    has_yfinance = yfinance_available()
    has_manual = MANUAL_FALLBACK_PATH.exists()

    if has_yfinance:
        try:
            rows, note = fetch_with_yfinance(tickers, now)
            return rows, AdapterDecision("yfinance_public_market_data", True, has_manual, note)
        except Exception as exc:
            rows, note = read_manual_fallback(tickers, now)
            return rows, AdapterDecision("manual_csv_fallback", True, has_manual, f"yfinance failed safely: {exc}; {note}")

    rows, note = read_manual_fallback(tickers, now)
    selected = "manual_csv_fallback" if has_manual else "manual_csv_fallback_missing"
    return rows, AdapterDecision(selected, False, has_manual, f"yfinance unavailable; {note}")
