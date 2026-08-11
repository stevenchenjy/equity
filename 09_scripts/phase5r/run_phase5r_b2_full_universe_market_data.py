from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, time, timezone
import math
from pathlib import Path
import sys
from typing import Any

import yfinance as yf

from phase5r_daily_common import (
    atomic_write_json,
    last_completed_market_session,
    now_et,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_b2_run_log.csv"
B2_RATE_LIMIT_STATE_PATH = (
    CONTROL_DIR / "run_logs" / "phase5r_b2_rate_limit_state.local.json"
)

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

RATE_LIMIT_STATE_SCHEMA = "phase5r_b2_rate_limit_state_v1"
RATE_LIMIT_CODE = "yfinance_rate_limited"
RATE_LIMIT_COOLDOWN_CODE = "yfinance_rate_limited_cooldown"
RATE_LIMIT_STATE_INVALID_CODE = "rate_limit_state_invalid"
SMOKE_PRECHECK_ABORTED_CODE = "yfinance_smoke_preflight_aborted"
FULL_UNIVERSE_INCOMPLETE_CODE = "yfinance_incomplete_full_universe_response"
FULL_UNIVERSE_STALE_CODE = "yfinance_stale_full_universe_response"
REUSE_VALIDATED_SNAPSHOT_CODE = "validated_local_snapshot_reused"
REUSE_INVALID_SNAPSHOT_CODE = "local_snapshot_reuse_invalid"
REUSE_STALE_SNAPSHOT_CODE = "local_snapshot_reuse_not_current"
POST_CLOSE_RETRY_TIME_ET = time(17, 45)


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle), [])


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


def source_failure_code(exc: Exception) -> str:
    """Map source exceptions to finite, non-sensitive audit codes."""

    if (
        exc.__class__.__name__ == "YFRateLimitError"
        or getattr(exc, "status_code", None) == 429
    ):
        return RATE_LIMIT_CODE
    if isinstance(exc, TimeoutError):
        return "yfinance_timeout"
    return "yfinance_request_failed"


def _parse_aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def load_rate_limit_state(
    current: datetime | None = None,
) -> tuple[dict[str, object] | None, str]:
    """Read only the bounded local circuit state; malformed state fails closed."""

    if not B2_RATE_LIMIT_STATE_PATH.exists():
        return None, "clear"
    try:
        payload = json.loads(B2_RATE_LIMIT_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "invalid"
    if not isinstance(payload, dict) or payload.get("schema_version") != RATE_LIMIT_STATE_SCHEMA:
        return None, "invalid"
    status = payload.get("status")
    if status == "cleared":
        return None, "clear"
    if status != "active":
        return None, "invalid"
    detected_at = _parse_aware_datetime(payload.get("detected_at"))
    rate_limit_date = payload.get("rate_limit_et_date")
    post_close_retry_consumed = payload.get("post_close_retry_consumed")
    if (
        detected_at is None
        or not isinstance(rate_limit_date, str)
        or not isinstance(post_close_retry_consumed, bool)
        or payload.get("source_failure_code") != RATE_LIMIT_CODE
    ):
        return None, "invalid"
    try:
        parsed_date = date.fromisoformat(rate_limit_date)
    except ValueError:
        return None, "invalid"
    current = current or now_et()
    if detected_at.astimezone(current.tzinfo).date() != parsed_date:
        return None, "invalid"
    return payload, "active"


def rate_limit_attempt_allowed(
    current: datetime | None = None,
) -> tuple[bool, str]:
    """Allow at most one post-close recovery attempt after a same-day 429."""

    current = current or now_et()
    state, state_status = load_rate_limit_state(current)
    if state_status == "invalid":
        return False, RATE_LIMIT_STATE_INVALID_CODE
    if state is None:
        return True, "rate_limit_state_clear"
    rate_limit_date = date.fromisoformat(str(state["rate_limit_et_date"]))
    current_date = current.date()
    if rate_limit_date < current_date:
        return True, "rate_limit_state_expired"
    if rate_limit_date > current_date:
        return False, RATE_LIMIT_STATE_INVALID_CODE
    if current.timetz().replace(tzinfo=None) < POST_CLOSE_RETRY_TIME_ET:
        return False, RATE_LIMIT_COOLDOWN_CODE
    if bool(state["post_close_retry_consumed"]):
        return False, RATE_LIMIT_COOLDOWN_CODE
    return True, "rate_limit_post_close_retry_available"


def record_rate_limit(current: datetime | None = None) -> None:
    """Persist a finite 429 state without response text, URLs, or credentials."""

    current = current or now_et()
    atomic_write_json(
        B2_RATE_LIMIT_STATE_PATH,
        {
            "schema_version": RATE_LIMIT_STATE_SCHEMA,
            "status": "active",
            "detected_at": current.isoformat(timespec="seconds"),
            "rate_limit_et_date": current.date().isoformat(),
            "post_close_retry_consumed": (
                current.timetz().replace(tzinfo=None) >= POST_CLOSE_RETRY_TIME_ET
            ),
            "source_failure_code": RATE_LIMIT_CODE,
        },
    )


def reserve_post_close_retry(current: datetime | None = None) -> None:
    """Consume the single recovery allowance before making a network request."""

    current = current or now_et()
    state, state_status = load_rate_limit_state(current)
    if state_status != "active" or state is None:
        raise RuntimeError("post-close retry requires active rate-limit state")
    updated = dict(state)
    updated["post_close_retry_consumed"] = True
    updated["post_close_retry_reserved_at"] = current.isoformat(timespec="seconds")
    atomic_write_json(B2_RATE_LIMIT_STATE_PATH, updated)


def clear_rate_limit_state(current: datetime | None = None) -> None:
    """Retain a non-sensitive recovery marker after a successful full refresh."""

    current = current or now_et()
    atomic_write_json(
        B2_RATE_LIMIT_STATE_PATH,
        {
            "schema_version": RATE_LIMIT_STATE_SCHEMA,
            "status": "cleared",
            "cleared_at": current.isoformat(timespec="seconds"),
            "source_failure_code": "none",
        },
    )


def rate_limit_cooldown_rows(
    error_code: str = RATE_LIMIT_COOLDOWN_CODE,
) -> list[dict[str, str]]:
    return [
        {
            "ticker": ticker,
            "last_price": "",
            "previous_close": "",
            "volume": "",
            "status": "not_attempted",
            "error_code": error_code,
        }
        for ticker in SMOKE_TICKERS
    ]


def smoke_failure_code(rows: list[dict[str, str]]) -> str:
    codes = [row.get("error_code", "") for row in rows]
    if RATE_LIMIT_CODE in codes:
        return RATE_LIMIT_CODE
    if RATE_LIMIT_COOLDOWN_CODE in codes:
        return RATE_LIMIT_COOLDOWN_CODE
    return next((code for code in codes if code), "yfinance_smoke_validation_failed")


def smoke_test() -> tuple[list[dict[str, str]], bool]:
    results: list[dict[str, str]] = []
    for index, ticker in enumerate(SMOKE_TICKERS):
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
            row["error_code"] = source_failure_code(exc)
        if row["status"] != "passed" and "error_code" not in row:
            row["error_code"] = "yfinance_smoke_validation_failed"
        results.append(row)
        if row["status"] != "passed":
            # A failed required benchmark already makes the preflight fail.
            # Do not turn that result into extra source pressure by probing
            # the remaining benchmarks.  A recognized 429 gets its distinct
            # circuit code; other failures remain finite and non-sensitive.
            remaining_code = (
                RATE_LIMIT_COOLDOWN_CODE
                if row.get("error_code") == RATE_LIMIT_CODE
                else SMOKE_PRECHECK_ABORTED_CODE
            )
            results.extend(
                {
                    "ticker": remaining,
                    "last_price": "",
                    "previous_close": "",
                    "volume": "",
                    "status": "not_attempted",
                    "error_code": remaining_code,
                }
                for remaining in SMOKE_TICKERS[index + 1 :]
            )
            break
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


def retrieve_full_universe(
    tickers: list[str], now: str
) -> tuple[list[dict[str, str]], str, bool, str]:
    try:
        dataset = yf.download(
            tickers=tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=False,
            progress=False, threads=False,
        )
        return (
            [
                market_row_from_history(
                    ticker, history_for_ticker(dataset, ticker), now
                )
                for ticker in tickers
            ],
            "full-universe public daily history retrieved",
            True,
            "none",
        )
    except Exception as exc:
        failure_code = source_failure_code(exc)
        return (
            [
                empty_market_row(
                    ticker, "yfinance_public_market_data_error", now
                )
                for ticker in tickers
            ],
            f"full-universe retrieval failed safely: {failure_code}",
            False,
            failure_code,
        )


def write_decision(
    smoke_rows: list[dict[str, str]],
    smoke_passed: bool,
    full_note: str,
    held_tickers: list[str],
    *,
    prior_outputs_preserved: bool = False,
    source_failure_code: str = "none",
) -> None:
    lines = [
        "# Phase 5R-B2 Data Source Decision", "", f"Generated: `{timestamp()}`", "",
        "## Decision", "", "- Selected source: `yfinance_public_market_data`.",
        "- Source use: `public read-only market data`.",
        f"- Benchmark preflight: `{'passed' if smoke_passed else 'failed'}`.",
        f"- Source-failure classification: `{source_failure_code}`.",
        f"- Full-universe action: `{full_note}`.", "",
        "## Benchmark Preflight", "", "| Ticker | Last Price | Previous Close | Volume | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in smoke_rows:
        lines.append(f"| {row['ticker']} | {row['last_price'] or 'n/a'} | {row['previous_close'] or 'n/a'} | {row['volume'] or 'n/a'} | {row['status']} |")
    if prior_outputs_preserved:
        lines.extend(
            [
                "",
                "## Failure Commit Boundary",
                "",
                "- The current source failure is blocking and this refresh exits nonzero.",
                "- The prior coherent canonical output trio was preserved byte-for-byte; it was not re-dated or treated as a successful current refresh.",
            ]
        )
    lines.extend([
        "", "## Boundary", "", "- Candidate rows come only from the canonical Phase 5R universe.",
        f"- Current-position price-monitoring rows: `{','.join(held_tickers) if held_tickers else 'none'}`; only current local ticker symbols were added to the public snapshot.",
        "- No stored position percentage, position note, archived holding file, broker, credential, API key, order, or email workflow was used.",
        "- This is one daily research refresh; it has no scheduler or intraday alert mechanism.",
    ])
    DECISION_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_data_report(
    rows: list[dict[str, str]],
    candidate_count: int,
    held_count: int,
    smoke_passed: bool,
    full_note: str,
    *,
    prior_outputs_preserved: bool = False,
    source_failure_code: str = "none",
) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["data_quality_label"]] = counts.get(row["data_quality_label"], 0) + 1
    lines = [
        "# Phase 5R-B2 Data Report", "", f"Generated: `{timestamp()}`", "",
        "## Summary", "", f"- Public snapshot rows: `{len(rows)}`.",
        f"- Canonical candidate rows: `{candidate_count}`.",
        f"- Current-position price-monitoring rows: `{held_count}`.",
        f"- Benchmark preflight: `{'passed' if smoke_passed else 'failed'}`.",
        f"- Source-failure classification: `{source_failure_code}`.",
        f"- Full-universe retrieval: `{full_note}`.", f"- Data quality counts: `{counts}`.", "",
        "## Interpretation Boundary", "", "This is a read-only daily research snapshot. Public prices may be delayed and signals require independent, human review. It is not a broker-connected system and cannot execute a trade.",
    ]
    if prior_outputs_preserved:
        lines.extend(
            [
                "",
                "## Failure Commit Boundary",
                "",
                "The current source failure remains blocking. The displayed rows are an unchanged prior coherent baseline, not a new market-data observation.",
            ]
        )
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


def finite_number(value: str) -> float | None:
    parsed = number(value)
    return parsed if parsed is not None and math.isfinite(parsed) else None


def unique_rows_by_ticker(
    rows: list[dict[str, str]], expected_tickers: set[str]
) -> dict[str, dict[str, str]] | None:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        ticker = row.get("ticker", "").strip().upper()
        if not ticker or ticker not in expected_tickers or ticker in indexed:
            return None
        indexed[ticker] = row
    return indexed if set(indexed) == expected_tickers else None


def parse_iso_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def prior_outputs_are_coherent(
    *,
    universe: list[dict[str, str]],
    tickers: list[str],
    held_tickers: list[str],
) -> tuple[bool, list[dict[str, str]], str]:
    """Validate a prior B2 trio before leaving it untouched after source failure.

    This intentionally does not judge freshness: preserved files retain their
    original timestamps, and downstream market-session gates remain responsible
    for rejecting an old observation.  It only prevents a failed current fetch
    from replacing a structurally coherent prior baseline with empty rows.
    """

    required_paths = (SNAPSHOT_PATH, QUALITY_PATH, CANDIDATES_PATH)
    if not all(path.exists() for path in required_paths):
        return False, [], "prior_output_missing"
    try:
        if (
            csv_header(SNAPSHOT_PATH) != MARKET_FIELDS
            or csv_header(QUALITY_PATH) != QUALITY_FIELDS
            or csv_header(CANDIDATES_PATH) != CANDIDATE_FIELDS
        ):
            return False, [], "prior_output_schema_mismatch"
        market_rows = read_csv(SNAPSHOT_PATH)
        quality_rows = read_csv(QUALITY_PATH)
        candidate_rows = read_csv(CANDIDATES_PATH)
    except (OSError, StopIteration, UnicodeError, csv.Error):
        return False, [], "prior_output_unreadable"
    if any(
        None in row for rows in (market_rows, quality_rows, candidate_rows) for row in rows
    ):
        return False, [], "prior_output_extra_cells"

    expected_market_tickers = {ticker.strip().upper() for ticker in tickers}
    expected_candidate_tickers = {
        row.get("ticker", "").strip().upper() for row in universe
    }
    if (
        not expected_market_tickers
        or not expected_candidate_tickers
        or len(expected_market_tickers) != len(tickers)
        or len(expected_candidate_tickers) != len(universe)
    ):
        return False, [], "current_input_ticker_coverage_invalid"
    market_by_ticker = unique_rows_by_ticker(market_rows, expected_market_tickers)
    quality_by_ticker = unique_rows_by_ticker(
        quality_rows, expected_market_tickers
    )
    candidates_by_ticker = unique_rows_by_ticker(
        candidate_rows, expected_candidate_tickers
    )
    if not market_by_ticker or not quality_by_ticker or not candidates_by_ticker:
        return False, [], "prior_output_ticker_coverage_invalid"

    required_positive_fields = {
        "last_price",
        "previous_close",
    }
    required_nonnegative_fields = {
        "volume",
        "average_volume",
        "relative_volume",
        "dollar_volume",
    }
    optional_positive_fields = {
        "day_high",
        "day_low",
        "fifty_two_week_high",
        "fifty_two_week_low",
    }
    held_set = {ticker.strip().upper() for ticker in held_tickers}
    for ticker, market in market_by_ticker.items():
        if (
            market.get("data_source") != "yfinance_public_market_data"
            or market.get("data_quality_label") != quality_label(market)
            or market.get("data_quality_label") == "insufficient_data"
            or not parse_iso_datetime(market.get("data_timestamp", ""))
        ):
            return False, [], f"prior_market_row_invalid:{ticker}"
        if ticker in held_set and market.get("data_quality_label") != "ok":
            return False, [], f"prior_held_market_quality_invalid:{ticker}"
        try:
            date.fromisoformat(market.get("market_session_date", ""))
            age = int(market.get("market_age_calendar_days", ""))
        except ValueError:
            return False, [], f"prior_market_provenance_invalid:{ticker}"
        if age < 0:
            return False, [], f"prior_market_age_invalid:{ticker}"
        if any(
            finite_number(market.get(field, "")) is None
            or finite_number(market.get(field, "")) <= 0
            for field in required_positive_fields
        ):
            return False, [], f"prior_market_positive_value_invalid:{ticker}"
        if any(
            finite_number(market.get(field, "")) is None
            or finite_number(market.get(field, "")) < 0
            for field in required_nonnegative_fields
        ) or finite_number(market.get("intraday_change_pct", "")) is None:
            return False, [], f"prior_market_numeric_value_invalid:{ticker}"
        if any(
            market.get(field, "")
            and (
                finite_number(market[field]) is None
                or finite_number(market[field]) <= 0
            )
            for field in optional_positive_fields
        ):
            return False, [], f"prior_market_optional_value_invalid:{ticker}"
        quality = quality_by_ticker[ticker]
        missing = [field for field in CORE_FIELDS if not market[field]]
        usable = "yes" if not missing else "no"
        expected_notes = (
            "read-only public row ready for scoring"
            if usable == "yes"
            else "data unavailable; preserved as insufficient_data without invented values"
        )
        if (
            quality.get("data_source") != market["data_source"]
            or quality.get("data_quality_label") != market["data_quality_label"]
            or quality.get("missing_fields") != ";".join(missing)
            or quality.get("usable_for_scoring", "").lower() != usable
            or quality.get("notes") != expected_notes
        ):
            return False, [], f"prior_quality_row_invalid:{ticker}"

    universe_by_ticker = {
        row["ticker"].strip().upper(): row for row in universe
    }
    seed_fields = (
        "ticker",
        "company_name",
        "sector",
        "industry",
        "theme",
        "liquidity_tier",
        "volatility_tier",
        "is_benchmark",
        "max_position_pct",
    )
    for ticker, candidate in candidates_by_ticker.items():
        market = market_by_ticker[ticker]
        seed = universe_by_ticker[ticker]
        missing = [field for field in CORE_FIELDS if not market[field]]
        usable = "yes" if not missing else "no"
        expected_candidate_note = (
            "daily public data attached"
            if usable == "yes"
            else "insufficient public data; do not score"
        )
        if (
            any(candidate.get(field) != seed.get(field) for field in seed_fields)
            or any(
                candidate.get(field) != market.get(field)
                for field in MARKET_FIELDS[1:]
            )
            or candidate.get("market_data_usable", "").lower() != usable
            or candidate.get("candidate_note") != expected_candidate_note
        ):
            return False, [], f"prior_candidate_row_invalid:{ticker}"
    return True, market_rows, "prior_output_trio_coherent"


def full_universe_rows_are_committable(
    *,
    market_rows: list[dict[str, str]],
    tickers: list[str],
    held_tickers: list[str],
    current: datetime,
) -> tuple[bool, str]:
    """Accept a live B2 response only when every covered row is usable.

    A successful ``yf.download`` call can still yield an empty or incomplete
    frame for one ticker.  That is an upstream data failure, not a successful
    refresh: rejecting the whole response before any output write keeps the
    snapshot, quality report, and candidate attachment atomic as a trio.
    """

    expected_tickers = {ticker.strip().upper() for ticker in tickers}
    if not expected_tickers or len(expected_tickers) != len(tickers):
        return False, FULL_UNIVERSE_INCOMPLETE_CODE
    market_by_ticker = unique_rows_by_ticker(market_rows, expected_tickers)
    if market_by_ticker is None:
        return False, FULL_UNIVERSE_INCOMPLETE_CODE

    expected_session = last_completed_market_session(current).isoformat()
    held_set = {ticker.strip().upper() for ticker in held_tickers}
    required_positive_fields = {"last_price", "previous_close"}
    required_nonnegative_fields = {
        "volume",
        "average_volume",
        "relative_volume",
        "dollar_volume",
    }
    optional_positive_fields = {
        "day_high",
        "day_low",
        "fifty_two_week_high",
        "fifty_two_week_low",
    }
    for ticker in tickers:
        row = market_by_ticker[ticker]
        if set(row) != set(MARKET_FIELDS):
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
        if (
            row.get("data_source") != "yfinance_public_market_data"
            or row.get("data_quality_label") != quality_label(row)
            or row.get("data_quality_label") == "insufficient_data"
            or not parse_iso_datetime(row.get("data_timestamp", ""))
        ):
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
        if row.get("market_session_date") != expected_session:
            return False, FULL_UNIVERSE_STALE_CODE
        if ticker in held_set and row.get("data_quality_label") != "ok":
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
        try:
            session_date = date.fromisoformat(row["market_session_date"])
            age = int(row["market_age_calendar_days"])
        except (TypeError, ValueError):
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
        if session_date.isoformat() != expected_session or age < 0:
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
        if any(
            finite_number(row[field]) is None or finite_number(row[field]) <= 0
            for field in required_positive_fields
        ):
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
        if (
            any(
                finite_number(row[field]) is None or finite_number(row[field]) < 0
                for field in required_nonnegative_fields
            )
            or finite_number(row["intraday_change_pct"]) is None
        ):
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
        if any(
            row[field]
            and (
                finite_number(row[field]) is None
                or finite_number(row[field]) <= 0
            )
            for field in optional_positive_fields
        ):
            return False, FULL_UNIVERSE_INCOMPLETE_CODE
    return True, "full_universe_response_committable"


def validated_snapshot_reuse(
    *,
    universe: list[dict[str, str]],
    tickers: list[str],
    held_tickers: list[str],
    current: datetime | None = None,
) -> tuple[bool, str, str]:
    """Accept only an exact, coherent local close for no-network reuse.

    This is deliberately stricter than failure preservation: a coherent prior
    trio can be retained after an upstream failure, but it cannot be presented
    as a current reusable close unless every covered ticker has the most recent
    completed U.S. market-session date.
    """

    current = current or now_et()
    coherent, rows, _ = prior_outputs_are_coherent(
        universe=universe,
        tickers=tickers,
        held_tickers=held_tickers,
    )
    if not coherent:
        return False, REUSE_INVALID_SNAPSHOT_CODE, ""
    expected_session = last_completed_market_session(current).isoformat()
    observed_sessions = {row.get("market_session_date", "") for row in rows}
    if observed_sessions != {expected_session}:
        return False, REUSE_STALE_SNAPSHOT_CODE, expected_session
    return True, REUSE_VALIDATED_SNAPSHOT_CODE, expected_session


def reuse_validated_snapshot(
    *,
    universe: list[dict[str, str]],
    tickers: list[str],
    held_tickers: list[str],
) -> int:
    """Reuse a verified local B2 trio without touching the public provider."""

    valid, reuse_code, expected_session = validated_snapshot_reuse(
        universe=universe,
        tickers=tickers,
        held_tickers=held_tickers,
    )
    append_audit(
        "reuse_validated_market_snapshot",
        ";".join(
            str(path.relative_to(ROOT))
            for path in (
                UNIVERSE_PATH,
                LOCAL_POSITIONS_PATH,
                SNAPSHOT_PATH,
                QUALITY_PATH,
                CANDIDATES_PATH,
            )
        ),
        ";".join(
            str(path.relative_to(ROOT))
            for path in (SNAPSHOT_PATH, QUALITY_PATH, CANDIDATES_PATH)
        ),
        "complete" if valid else "failed",
        "network_attempted=no; public_source_called=no; "
        "snapshot_bytes_unchanged=yes; "
        f"reuse_validation_code={reuse_code}; "
        f"expected_completed_session={expected_session or 'unavailable'}",
    )
    print(
        "Phase 5R-B2 "
        f"snapshot_reuse_validated={str(valid).lower()}; "
        "public_source_called=false; "
        f"reuse_validation_code={reuse_code}"
    )
    return 0 if valid else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reuse-validated-snapshot",
        action="store_true",
        help="validate and reuse only the current coherent local B2 trio",
    )
    args = parser.parse_args([] if argv is None else argv)
    universe = read_csv(UNIVERSE_PATH)
    candidate_tickers = [row["ticker"].upper() for row in universe]
    if not universe:
        raise RuntimeError("Canonical Phase 5R universe is empty")
    if set(SMOKE_TICKERS) - set(candidate_tickers):
        raise RuntimeError(
            "Canonical universe must include QQQ, XLK, and SPY for the preflight"
        )
    if not LOCAL_POSITIONS_PATH.exists():
        raise RuntimeError("Current local positions are required for C9 price monitoring")
    current_positions = read_csv(LOCAL_POSITIONS_PATH)
    held_tickers = sorted(
        {
            row.get("ticker", "").strip().upper()
            for row in current_positions
            if row.get("ticker", "").strip()
        }
    )
    if not held_tickers:
        raise RuntimeError("Current local positions contain no ticker symbols")
    tickers = list(candidate_tickers)
    tickers.extend(
        ticker for ticker in held_tickers if ticker not in set(candidate_tickers)
    )

    if args.reuse_validated_snapshot:
        return reuse_validated_snapshot(
            universe=universe,
            tickers=tickers,
            held_tickers=held_tickers,
        )

    rate_limit_check_time = now_et()
    network_attempt_allowed, rate_limit_state_reason = rate_limit_attempt_allowed(
        rate_limit_check_time
    )
    if network_attempt_allowed:
        if rate_limit_state_reason == "rate_limit_post_close_retry_available":
            # Persist consumption before the request, so an interrupted process
            # cannot issue a duplicate post-close recovery call.
            reserve_post_close_retry(rate_limit_check_time)
        smoke_rows, smoke_passed = smoke_test()
        current_source_failure_code = (
            "none" if smoke_passed else smoke_failure_code(smoke_rows)
        )
        if current_source_failure_code == RATE_LIMIT_CODE:
            record_rate_limit(rate_limit_check_time)
    else:
        smoke_rows = rate_limit_cooldown_rows(rate_limit_state_reason)
        smoke_passed = False
        current_source_failure_code = rate_limit_state_reason
    smoke_audit_status = (
        "passed"
        if smoke_passed
        else "not_attempted"
        if not network_attempt_allowed
        else "failed"
    )
    append_audit(
        "benchmark_smoke_test",
        "QQQ;XLK;SPY",
        "in_memory_preflight_only",
        smoke_audit_status,
        "sequence=1; full_universe_fetch_not_started_before_this_check; "
        f"network_attempted={'yes' if network_attempt_allowed else 'no'}; "
        f"source_failure_code={current_source_failure_code}; "
        f"rate_limit_circuit={rate_limit_state_reason}",
    )
    now = timestamp()
    source_failure = False
    full_retrieval_succeeded = False
    prior_outputs_preserved = False
    prior_validation_reason = "not_checked"
    if smoke_passed:
        (
            market_rows,
            full_note,
            full_retrieval_succeeded,
            full_failure_code,
        ) = retrieve_full_universe(tickers, now)
        if full_retrieval_succeeded:
            committable, commit_code = full_universe_rows_are_committable(
                market_rows=market_rows,
                tickers=tickers,
                held_tickers=held_tickers,
                current=rate_limit_check_time,
            )
            if not committable:
                market_rows = [
                    empty_market_row(
                        ticker,
                        "yfinance_public_market_data_error",
                        now,
                    )
                    for ticker in tickers
                ]
                full_note = (
                    "full-universe response rejected before commit: "
                    f"{commit_code}"
                )
                full_retrieval_succeeded = False
                full_failure_code = commit_code
        source_failure = not full_retrieval_succeeded
        current_source_failure_code = full_failure_code
        if current_source_failure_code == RATE_LIMIT_CODE:
            record_rate_limit(rate_limit_check_time)
        append_audit(
            "full_universe_market_data_refresh",
            ";".join(
                str(path.relative_to(ROOT))
                for path in [UNIVERSE_PATH, LOCAL_POSITIONS_PATH]
            ),
            str(SNAPSHOT_PATH.relative_to(ROOT)),
            "complete" if full_retrieval_succeeded else "failed",
            "sequence=2; smoke_test_passed=yes; "
            f"full_retrieval_succeeded={'yes' if full_retrieval_succeeded else 'no'}; "
            "held_tickers_price_only=yes; "
            f"source_failure_code={current_source_failure_code}; "
            f"fail_safe_stop={'no' if full_retrieval_succeeded else 'yes'}",
        )
    else:
        source_name = (
            "yfinance_rate_limit_circuit_open"
            if current_source_failure_code
            in {RATE_LIMIT_CODE, RATE_LIMIT_COOLDOWN_CODE, RATE_LIMIT_STATE_INVALID_CODE}
            else "yfinance_smoke_test_failed"
        )
        market_rows = [
            empty_market_row(ticker, source_name, now)
            for ticker in tickers
        ]
        full_note = (
            "not attempted because benchmark preflight was rate limited"
            if current_source_failure_code == RATE_LIMIT_CODE
            else "not attempted because rate-limit circuit is active"
            if current_source_failure_code
            in {RATE_LIMIT_COOLDOWN_CODE, RATE_LIMIT_STATE_INVALID_CODE}
            else "not attempted because benchmark preflight failed"
        )
        source_failure = True
        append_audit(
            "full_universe_market_data_refresh",
            ";".join(
                str(path.relative_to(ROOT))
                for path in [UNIVERSE_PATH, LOCAL_POSITIONS_PATH]
            ),
            str(SNAPSHOT_PATH.relative_to(ROOT)),
            "not_attempted",
            "sequence=2; smoke_test_passed=no; fail_safe_stop=yes; "
            "held_tickers_price_only=yes; "
            f"source_failure_code={current_source_failure_code}; "
            f"network_attempted={'yes' if network_attempt_allowed else 'no'}",
        )

    if source_failure:
        (
            prior_outputs_preserved,
            prior_market_rows,
            prior_validation_reason,
        ) = prior_outputs_are_coherent(
            universe=universe,
            tickers=tickers,
            held_tickers=held_tickers,
        )
        if prior_outputs_preserved:
            market_rows = prior_market_rows

    if not prior_outputs_preserved:
        market_by_ticker = {row["ticker"]: row for row in market_rows}
        quality_rows: list[dict[str, str]] = []
        candidates: list[dict[str, str]] = []
        for ticker in tickers:
            market = market_by_ticker[ticker]
            missing = [field for field in CORE_FIELDS if not market[field]]
            usable = "yes" if not missing else "no"
            quality_rows.append(
                {
                    "ticker": ticker,
                    "data_source": market["data_source"],
                    "data_quality_label": market["data_quality_label"],
                    "missing_fields": ";".join(missing),
                    "usable_for_scoring": usable,
                    "notes": (
                        "read-only public row ready for scoring"
                        if usable == "yes"
                        else "data unavailable; preserved as insufficient_data without invented values"
                    ),
                }
            )
        for seed in universe:
            ticker = seed["ticker"].upper()
            market = market_by_ticker[ticker]
            missing = [field for field in CORE_FIELDS if not market[field]]
            usable = "yes" if not missing else "no"
            candidate = {
                key: seed[key]
                for key in (
                    "ticker",
                    "company_name",
                    "sector",
                    "industry",
                    "theme",
                    "liquidity_tier",
                    "volatility_tier",
                    "is_benchmark",
                    "max_position_pct",
                )
            }
            candidate.update({field: market[field] for field in MARKET_FIELDS[1:]})
            candidate.update(
                {
                    "market_data_usable": usable,
                    "candidate_note": (
                        "daily public data attached"
                        if usable == "yes"
                        else "insufficient public data; do not score"
                    ),
                }
            )
            candidates.append(candidate)

        write_csv(SNAPSHOT_PATH, market_rows, MARKET_FIELDS)
        write_csv(QUALITY_PATH, quality_rows, QUALITY_FIELDS)
        write_csv(CANDIDATES_PATH, candidates, CANDIDATE_FIELDS)

    write_decision(
        smoke_rows,
        smoke_passed,
        full_note,
        held_tickers,
        prior_outputs_preserved=prior_outputs_preserved,
        source_failure_code=current_source_failure_code,
    )
    write_data_report(
        market_rows,
        len(universe),
        len(
            [
                ticker
                for ticker in held_tickers
                if ticker not in set(candidate_tickers)
            ]
        ),
        smoke_passed,
        full_note,
        prior_outputs_preserved=prior_outputs_preserved,
        source_failure_code=current_source_failure_code,
    )
    # A successful provider response is not a completed recovery until all
    # current B2 artifacts have been written.  Leaving an active 429 circuit
    # intact on a local write failure is conservative and prevents a duplicate
    # same-day public-source attempt after an interrupted commit.
    if full_retrieval_succeeded:
        clear_rate_limit_state(rate_limit_check_time)
    written_paths = [DECISION_PATH, REPORT_PATH]
    if not prior_outputs_preserved:
        written_paths = [
            SNAPSHOT_PATH,
            QUALITY_PATH,
            CANDIDATES_PATH,
            *written_paths,
        ]
    append_audit(
        "write_b2_market_data_outputs",
        ";".join(
            str(path.relative_to(ROOT))
            for path in [UNIVERSE_PATH, LOCAL_POSITIONS_PATH]
        ),
        ";".join(str(path.relative_to(ROOT)) for path in written_paths),
        (
            "source_failure_prior_outputs_preserved"
            if source_failure and prior_outputs_preserved
            else "source_failure_insufficient_outputs_written"
            if source_failure
            else "complete"
        ),
        f"snapshot_rows={len(market_rows)}; candidate_rows={len(universe)}; "
        f"held_price_rows={len([ticker for ticker in held_tickers if ticker not in set(candidate_tickers)])}; "
        f"smoke_test_passed={'yes' if smoke_passed else 'no'}; "
        f"source_failure={'yes' if source_failure else 'no'}; "
        f"source_failure_code={current_source_failure_code}; "
        f"prior_outputs_preserved={'yes' if prior_outputs_preserved else 'no'}; "
        f"prior_validation={prior_validation_reason}",
    )
    print(
        f"Phase 5R-B2 smoke_test_passed={smoke_passed}; "
        f"market_rows={len(market_rows)}; "
        f"source_failure_blocking={str(source_failure).lower()}; "
        f"prior_outputs_preserved={str(prior_outputs_preserved).lower()}"
    )
    return 1 if source_failure else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
