from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_b2_run_log.csv"

UNIVERSE_PATH = DATA_DIR / "phase5r_universe_seed.csv"
LOCAL_POSITIONS_PATH = ROOT / "05_risk_and_positions" / "current_positions.local.csv"
SNAPSHOT_PATH = DATA_DIR / "phase5r_b2_market_data_snapshot.csv"
QUALITY_PATH = DATA_DIR / "phase5r_b2_market_data_quality_report.csv"
CANDIDATES_PATH = DATA_DIR / "phase5r_b2_candidates_with_market_data.csv"
AUDIT_PATH = DATA_DIR / "phase5r_b2_audit_trail.csv"
DECISION_PATH = CONTROL_DIR / "phase5r_b2_data_source_decision.md"
REPORT_PATH = RESEARCH_DIR / "phase5r_b2_data_report.md"

SMOKE_TICKERS = ["QQQ", "XLK", "SPY"]
MARKET_FIELDS = [
    "ticker", "last_price", "previous_close", "intraday_change_pct", "volume",
    "average_volume", "relative_volume", "dollar_volume", "day_high", "day_low",
    "fifty_two_week_high", "fifty_two_week_low", "market_session_date",
    "market_age_calendar_days", "data_timestamp", "data_source",
    "data_quality_label",
]
CORE_FIELDS = [
    "last_price", "previous_close", "intraday_change_pct", "volume", "average_volume",
    "relative_volume", "dollar_volume",
]
QUALITY_FIELDS = ["ticker", "data_source", "data_quality_label", "missing_fields", "usable_for_scoring", "notes"]
CANDIDATE_FIELDS = [
    "ticker", "company_name", "sector", "industry", "theme", "liquidity_tier",
    "volatility_tier", "is_benchmark", "max_position_pct", *MARKET_FIELDS[1:],
    "market_data_usable", "candidate_note",
]
AUDIT_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "safety_notes"]


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


def append_csv(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def fmt_float(value: Any) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if value != value else f"{value:.4f}"


def fmt_int(value: Any) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if value != value else str(int(round(value)))


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def empty_market_row(ticker: str, source: str, now: str) -> dict[str, str]:
    return {
        "ticker": ticker, "last_price": "", "previous_close": "", "intraday_change_pct": "",
        "volume": "", "average_volume": "", "relative_volume": "", "dollar_volume": "",
        "day_high": "", "day_low": "", "fifty_two_week_high": "", "fifty_two_week_low": "",
        "market_session_date": "", "market_age_calendar_days": "",
        "data_timestamp": now, "data_source": source, "data_quality_label": "insufficient_data",
    }


def quality_label(row: dict[str, str]) -> str:
    core_missing = [field for field in CORE_FIELDS if not row[field]]
    if core_missing:
        return "insufficient_data"
    optional_missing = [field for field in ("day_high", "day_low", "fifty_two_week_high", "fifty_two_week_low") if not row[field]]
    return "partial" if optional_missing else "ok"


def smoke_test() -> tuple[list[dict[str, str]], bool]:
    results: list[dict[str, str]] = []
    for ticker in SMOKE_TICKERS:
        row = {"ticker": ticker, "last_price": "", "previous_close": "", "volume": "", "status": "failed"}
        try:
            history = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False, raise_errors=False)
            if len(history.index) >= 2:
                row.update({
                    "last_price": fmt_float(history["Close"].iloc[-1]),
                    "previous_close": fmt_float(history["Close"].iloc[-2]),
                    "volume": fmt_int(history["Volume"].iloc[-1]),
                })
                row["status"] = "passed" if row["last_price"] and row["previous_close"] else "failed"
        except Exception as exc:
            row["error_type"] = exc.__class__.__name__
        results.append(row)
    return results, all(row["status"] == "passed" for row in results)


def history_for_ticker(dataset: Any, ticker: str) -> Any | None:
    columns = getattr(dataset, "columns", None)
    if columns is None or len(columns) == 0:
        return None
    try:
        if getattr(columns, "nlevels", 1) > 1:
            if ticker in columns.get_level_values(0):
                return dataset[ticker]
            if ticker in columns.get_level_values(1):
                return dataset.xs(ticker, axis=1, level=1)
        return dataset
    except (KeyError, ValueError):
        return None


def market_row_from_history(ticker: str, history: Any | None, now: str) -> dict[str, str]:
    row = empty_market_row(ticker, "yfinance_public_market_data", now)
    if history is None:
        return row
    try:
        history = history.dropna(how="all")
        if len(history.index) < 2:
            return row
        last = number(history["Close"].iloc[-1])
        previous = number(history["Close"].iloc[-2])
        volume = number(history["Volume"].iloc[-1])
        average_volume = number(history["Volume"].tail(min(20, len(history.index))).mean())
        day_high = number(history["High"].iloc[-1])
        day_low = number(history["Low"].iloc[-1])
        year_high = number(history["High"].max())
        year_low = number(history["Low"].min())
        session_date = history.index[-1].date()
        change = ((last - previous) / previous) * 100 if last is not None and previous not in {None, 0.0} else None
        relative_volume = volume / average_volume if volume is not None and average_volume not in {None, 0.0} else None
        dollar_volume = last * volume if last is not None and volume is not None else None
        row.update({
            "last_price": fmt_float(last), "previous_close": fmt_float(previous),
            "intraday_change_pct": fmt_float(change), "volume": fmt_int(volume),
            "average_volume": fmt_int(average_volume), "relative_volume": fmt_float(relative_volume),
            "dollar_volume": fmt_int(dollar_volume), "day_high": fmt_float(day_high),
            "day_low": fmt_float(day_low), "fifty_two_week_high": fmt_float(year_high),
            "fifty_two_week_low": fmt_float(year_low),
            "market_session_date": session_date.isoformat(),
            "market_age_calendar_days": str((date.today() - session_date).days),
        })
        row["data_quality_label"] = quality_label(row)
    except (KeyError, TypeError, ValueError):
        pass
    return row


def retrieve_full_universe(tickers: list[str], now: str) -> tuple[list[dict[str, str]], str]:
    try:
        dataset = yf.download(
            tickers=tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=False,
            progress=False, threads=False,
        )
        return [market_row_from_history(ticker, history_for_ticker(dataset, ticker), now) for ticker in tickers], "full-universe public daily history retrieved"
    except Exception as exc:
        return [empty_market_row(ticker, "yfinance_public_market_data_error", now) for ticker in tickers], f"full-universe retrieval failed safely: {exc.__class__.__name__}"


def write_decision(smoke_rows: list[dict[str, str]], smoke_passed: bool, full_note: str, held_tickers: list[str]) -> None:
    lines = [
        "# Phase 5R-B2 Data Source Decision", "", f"Generated: `{timestamp()}`", "",
        "## Decision", "", "- Selected source: `yfinance_public_market_data`.",
        "- Source use: `public read-only market data`.",
        f"- Benchmark preflight: `{'passed' if smoke_passed else 'failed'}`.",
        f"- Full-universe action: `{full_note}`.", "",
        "## Benchmark Preflight", "", "| Ticker | Last Price | Previous Close | Volume | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in smoke_rows:
        lines.append(f"| {row['ticker']} | {row['last_price'] or 'n/a'} | {row['previous_close'] or 'n/a'} | {row['volume'] or 'n/a'} | {row['status']} |")
    lines.extend([
        "", "## Boundary", "", "- Candidate rows come only from the canonical Phase 5R universe.",
        f"- Current-position price-monitoring rows: `{','.join(held_tickers) if held_tickers else 'none'}`; only current local ticker symbols were added to the public snapshot.",
        "- No stored position percentage, position note, archived holding file, broker, credential, API key, order, or email workflow was used.",
        "- This is one daily research refresh; it has no scheduler or intraday alert mechanism.",
    ])
    DECISION_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_data_report(rows: list[dict[str, str]], candidate_count: int, held_count: int, smoke_passed: bool, full_note: str) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["data_quality_label"]] = counts.get(row["data_quality_label"], 0) + 1
    lines = [
        "# Phase 5R-B2 Data Report", "", f"Generated: `{timestamp()}`", "",
        "## Summary", "", f"- Public snapshot rows: `{len(rows)}`.",
        f"- Canonical candidate rows: `{candidate_count}`.",
        f"- Current-position price-monitoring rows: `{held_count}`.",
        f"- Benchmark preflight: `{'passed' if smoke_passed else 'failed'}`.",
        f"- Full-universe retrieval: `{full_note}`.", f"- Data quality counts: `{counts}`.", "",
        "## Interpretation Boundary", "", "This is a read-only daily research snapshot. Public prices may be delayed and signals require independent, human review. It is not a broker-connected system and cannot execute a trade.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_audit(action: str, inputs: str, outputs: str, status: str, notes: str) -> None:
    row = {
        "timestamp": timestamp(), "script_name": Path(__file__).name, "action": action,
        "input_path": inputs, "output_path": outputs, "status": status,
        "safety_notes": f"read_only_public_market_data=yes; canonical_candidate_universe=yes; current_position_price_monitoring=yes; no_broker=yes; no_orders=yes; no_email=yes; no_credentials=yes; archived_legacy_used=no; {notes}",
    }
    append_csv(AUDIT_PATH, row)
    append_csv(RUN_LOG, row)


def main() -> None:
    universe = read_csv(UNIVERSE_PATH)
    candidate_tickers = [row["ticker"].upper() for row in universe]
    if not universe:
        raise RuntimeError("Canonical Phase 5R universe is empty")
    if set(SMOKE_TICKERS) - set(candidate_tickers):
        raise RuntimeError("Canonical universe must include QQQ, XLK, and SPY for the preflight")
    if not LOCAL_POSITIONS_PATH.exists():
        raise RuntimeError("Current local positions are required for C9 price monitoring")
    current_positions = read_csv(LOCAL_POSITIONS_PATH)
    held_tickers = sorted({row.get("ticker", "").strip().upper() for row in current_positions if row.get("ticker", "").strip()})
    if not held_tickers:
        raise RuntimeError("Current local positions contain no ticker symbols")
    tickers = list(candidate_tickers)
    tickers.extend(ticker for ticker in held_tickers if ticker not in set(candidate_tickers))

    smoke_rows, smoke_passed = smoke_test()
    append_audit("benchmark_smoke_test", "QQQ;XLK;SPY", "in_memory_preflight_only", "passed" if smoke_passed else "failed", "sequence=1; full_universe_fetch_not_started_before_this_check")
    now = timestamp()
    if smoke_passed:
        market_rows, full_note = retrieve_full_universe(tickers, now)
        append_audit("full_universe_market_data_refresh", ";".join(str(path.relative_to(ROOT)) for path in [UNIVERSE_PATH, LOCAL_POSITIONS_PATH]), str(SNAPSHOT_PATH.relative_to(ROOT)), "complete", "sequence=2; smoke_test_passed=yes; held_tickers_price_only=yes")
    else:
        market_rows = [empty_market_row(ticker, "yfinance_smoke_test_failed", now) for ticker in tickers]
        full_note = "not attempted because benchmark preflight failed"
        append_audit("full_universe_market_data_refresh", ";".join(str(path.relative_to(ROOT)) for path in [UNIVERSE_PATH, LOCAL_POSITIONS_PATH]), str(SNAPSHOT_PATH.relative_to(ROOT)), "not_attempted", "sequence=2; smoke_test_passed=no; fail_safe_stop=yes; held_tickers_price_only=yes")

    market_by_ticker = {row["ticker"]: row for row in market_rows}
    quality_rows: list[dict[str, str]] = []
    candidates: list[dict[str, str]] = []
    for ticker in tickers:
        market = market_by_ticker[ticker]
        missing = [field for field in CORE_FIELDS if not market[field]]
        usable = "yes" if not missing else "no"
        quality_rows.append({
            "ticker": ticker, "data_source": market["data_source"], "data_quality_label": market["data_quality_label"],
            "missing_fields": ";".join(missing), "usable_for_scoring": usable,
            "notes": "read-only public row ready for scoring" if usable == "yes" else "data unavailable; preserved as insufficient_data without invented values",
        })
    for seed in universe:
        ticker = seed["ticker"].upper()
        market = market_by_ticker[ticker]
        missing = [field for field in CORE_FIELDS if not market[field]]
        usable = "yes" if not missing else "no"
        candidate = {key: seed[key] for key in ("ticker", "company_name", "sector", "industry", "theme", "liquidity_tier", "volatility_tier", "is_benchmark", "max_position_pct")}
        candidate.update({field: market[field] for field in MARKET_FIELDS[1:]})
        candidate.update({"market_data_usable": usable, "candidate_note": "daily public data attached" if usable == "yes" else "insufficient public data; do not score"})
        candidates.append(candidate)

    write_csv(SNAPSHOT_PATH, market_rows, MARKET_FIELDS)
    write_csv(QUALITY_PATH, quality_rows, QUALITY_FIELDS)
    write_csv(CANDIDATES_PATH, candidates, CANDIDATE_FIELDS)
    write_decision(smoke_rows, smoke_passed, full_note, held_tickers)
    write_data_report(market_rows, len(universe), len([ticker for ticker in held_tickers if ticker not in set(candidate_tickers)]), smoke_passed, full_note)
    append_audit("write_b2_market_data_outputs", ";".join(str(path.relative_to(ROOT)) for path in [UNIVERSE_PATH, LOCAL_POSITIONS_PATH]), ";".join(str(path.relative_to(ROOT)) for path in [SNAPSHOT_PATH, QUALITY_PATH, CANDIDATES_PATH, DECISION_PATH, REPORT_PATH]), "complete", f"snapshot_rows={len(market_rows)}; candidate_rows={len(universe)}; held_price_rows={len([ticker for ticker in held_tickers if ticker not in set(candidate_tickers)])}; smoke_test_passed={'yes' if smoke_passed else 'no'}")
    print(f"Phase 5R-B2 smoke_test_passed={smoke_passed}; market_rows={len(market_rows)}")


if __name__ == "__main__":
    main()
