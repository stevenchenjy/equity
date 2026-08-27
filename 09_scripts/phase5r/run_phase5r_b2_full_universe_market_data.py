from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import sys
from typing import Any

from phase5r_daily_common import (
    atomic_write_csv,
    is_us_market_session_date,
    last_completed_market_session,
    now_et,
)
from phase5r_massive_b2_adapter import (
    AUTH_MISSING_CODE,
    HISTORICAL_SESSION_SEQUENCE_CODE,
    MASSIVE_DATA_SOURCE,
    MASSIVE_MIN_REQUEST_INTERVAL_SECONDS,
    MassiveB2Error,
    MassiveBasicEODClient,
    REQUEST_FAILED_CODE,
)


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
EXPECTED_PRODUCTION_B2_TICKER_COUNT = 29
REQUIRED_PRODUCTION_TICKERS = frozenset({"IOT", "RBRK", *SMOKE_TICKERS})
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

LEGACY_YFINANCE_DATA_SOURCE = "yfinance_public_market_data"
COHERENT_DATA_SOURCES = {MASSIVE_DATA_SOURCE, LEGACY_YFINANCE_DATA_SOURCE}
SMOKE_PRECHECK_ABORTED_CODE = "massive_smoke_preflight_aborted"
SMOKE_VALIDATION_FAILED_CODE = "massive_smoke_validation_failed"
SMOKE_CURRENT_SESSION_NOT_PUBLISHED_CODE = "massive_current_session_not_published"
SMOKE_HISTORICAL_SESSION_SEQUENCE_CODE = HISTORICAL_SESSION_SEQUENCE_CODE
SMOKE_MARKET_ROW_VALIDATION_CODE = "massive_market_row_validation_failed"
FULL_UNIVERSE_INCOMPLETE_CODE = "massive_incomplete_full_universe_response"
FULL_UNIVERSE_STALE_CODE = "massive_stale_full_universe_response"
REUSE_VALIDATED_SNAPSHOT_CODE = "validated_local_snapshot_reused"
REUSE_INVALID_SNAPSHOT_CODE = "local_snapshot_reuse_invalid"
REUSE_STALE_SNAPSHOT_CODE = "local_snapshot_reuse_not_current"


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle), [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    atomic_write_csv(path, fields, rows)


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

    if isinstance(exc, MassiveB2Error):
        return exc.code
    return REQUEST_FAILED_CODE


def smoke_failure_code(rows: list[dict[str, str]]) -> str:
    codes = [row.get("error_code", "") for row in rows]
    return next((code for code in codes if code), SMOKE_VALIDATION_FAILED_CODE)


def history_window(current: datetime) -> tuple[date, date]:
    expected_session = last_completed_market_session(current)
    return expected_session - timedelta(weeks=52), expected_session


def previous_market_session(value: date) -> date:
    candidate = value - timedelta(days=1)
    while not is_us_market_session_date(candidate):
        candidate -= timedelta(days=1)
    return candidate


def expected_history_sessions(current: datetime) -> list[date]:
    start_date, end_date = history_window(current)
    sessions: list[date] = []
    candidate = start_date
    while candidate <= end_date:
        if is_us_market_session_date(candidate):
            sessions.append(candidate)
        candidate += timedelta(days=1)
    return sessions


SMOKE_DIAGNOSTIC_FIELDS = (
    "validation_code",
    "expected_session_count",
    "observed_session_count",
    "expected_latest_session",
    "observed_latest_session",
    "missing_session_count",
    "missing_session_dates",
    "unexpected_session_count",
    "unexpected_session_dates",
    "duplicate_session_count",
    "duplicate_session_dates",
    "session_order_mismatch",
)


def _session_date_list(values: list[date]) -> str:
    """Serialize only normalized calendar dates for bounded local diagnostics."""

    return ",".join(value.isoformat() for value in values)


def session_coverage_diagnostic(
    bars: Any, current: datetime
) -> dict[str, str]:
    """Classify exact session coverage without retaining provider payloads.

    The returned values contain only finite codes, counts, booleans, and ISO
    market-session dates derived from the already-normalized in-memory bars.
    Prices, volumes, provider metadata, response text, URLs, and credentials
    never enter this diagnostic.
    """

    expected = expected_history_sessions(current)
    expected_latest = expected[-1] if expected else None
    observed: list[date] = []
    invalid_session_value = not isinstance(bars, list)
    normalized_bars = bars if isinstance(bars, list) else []
    for bar in normalized_bars:
        value = bar.get("session_date") if isinstance(bar, dict) else None
        if type(value) is not date:
            invalid_session_value = True
            continue
        observed.append(value)

    counts = Counter(observed)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    observed_set = set(observed)
    expected_set = set(expected)
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)
    observed_latest = max(observed) if observed else None
    order_mismatch = observed != expected

    if invalid_session_value:
        code = SMOKE_MARKET_ROW_VALIDATION_CODE
    elif observed == expected:
        code = "none"
    elif observed == expected[:-1] and expected_latest is not None:
        # Category A is deliberately exact: every earlier expected session is
        # present once and only the newest completed session is unavailable.
        code = SMOKE_CURRENT_SESSION_NOT_PUBLISHED_CODE
    else:
        # Category B covers any historical gap, duplicate, unexpected session,
        # or ordering mismatch. Exact affected dates remain available below.
        code = SMOKE_HISTORICAL_SESSION_SEQUENCE_CODE

    return {
        "validation_code": code,
        "expected_session_count": str(len(expected)),
        "observed_session_count": str(len(observed)),
        "expected_latest_session": (
            expected_latest.isoformat() if expected_latest else ""
        ),
        "observed_latest_session": (
            observed_latest.isoformat() if observed_latest else ""
        ),
        "missing_session_count": str(len(missing)),
        "missing_session_dates": _session_date_list(missing),
        "unexpected_session_count": str(len(unexpected)),
        "unexpected_session_dates": _session_date_list(unexpected),
        "duplicate_session_count": str(len(duplicates)),
        "duplicate_session_dates": _session_date_list(duplicates),
        "session_order_mismatch": "yes" if order_mismatch else "no",
    }


def market_row_from_massive_bars(
    ticker: str,
    bars: list[dict[str, Any]],
    now: str,
    current: datetime,
    *,
    diagnostic: dict[str, str] | None = None,
) -> dict[str, str]:
    row = empty_market_row(ticker, MASSIVE_DATA_SOURCE, now)
    coverage = session_coverage_diagnostic(bars, current)
    if diagnostic is not None:
        diagnostic.update(coverage)
    if coverage["validation_code"] != "none":
        return row
    try:
        expected_sessions = expected_history_sessions(current)
        observed_sessions = [bar["session_date"] for bar in bars]
        if len(expected_sessions) < 20 or observed_sessions != expected_sessions:
            return row
        expected_session = last_completed_market_session(current)
        expected_previous = previous_market_session(expected_session)
        if (
            bars[-1]["session_date"] != expected_session
            or bars[-2]["session_date"] != expected_previous
            or any(
                not is_us_market_session_date(bar["session_date"])
                for bar in bars
            )
        ):
            return row
        last = number(bars[-1]["close"])
        previous = number(bars[-2]["close"])
        volume = number(bars[-1]["volume"])
        average_volume = number(
            sum(float(bar["volume"]) for bar in bars[-20:]) / 20
        )
        day_high = number(bars[-1]["high"])
        day_low = number(bars[-1]["low"])
        year_high = number(max(float(bar["high"]) for bar in bars))
        year_low = number(min(float(bar["low"]) for bar in bars))
        change = (
            ((last - previous) / previous) * 100
            if last is not None and previous not in {None, 0.0}
            else None
        )
        relative_volume = (
            volume / average_volume
            if volume is not None and average_volume not in {None, 0.0}
            else None
        )
        dollar_volume = (
            last * volume
            if last is not None and volume is not None
            else None
        )
        row.update(
            {
                "last_price": fmt_float(last),
                "previous_close": fmt_float(previous),
                "intraday_change_pct": fmt_float(change),
                "volume": fmt_int(volume),
                "average_volume": fmt_int(average_volume),
                "relative_volume": fmt_float(relative_volume),
                "dollar_volume": fmt_int(dollar_volume),
                "day_high": fmt_float(day_high),
                "day_low": fmt_float(day_low),
                "fifty_two_week_high": fmt_float(year_high),
                "fifty_two_week_low": fmt_float(year_low),
                "market_session_date": expected_session.isoformat(),
                "market_age_calendar_days": str(
                    (current.date() - expected_session).days
                ),
            }
        )
        row["data_quality_label"] = quality_label(row)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        if diagnostic is not None:
            diagnostic["validation_code"] = SMOKE_MARKET_ROW_VALIDATION_CODE
        return empty_market_row(ticker, MASSIVE_DATA_SOURCE, now)
    if row["data_quality_label"] == "insufficient_data" and diagnostic is not None:
        diagnostic["validation_code"] = SMOKE_MARKET_ROW_VALIDATION_CODE
    return row


def smoke_test(
    client: MassiveBasicEODClient,
    *,
    current: datetime,
    now: str,
) -> tuple[list[dict[str, str]], bool]:
    start_date, end_date = history_window(current)
    results: list[dict[str, str]] = []
    for index, ticker in enumerate(SMOKE_TICKERS):
        row = {"ticker": ticker, "last_price": "", "previous_close": "", "volume": "", "status": "failed"}
        try:
            bars = client.fetch_daily_bars(
                ticker,
                start_date=start_date,
                end_date=end_date,
            )
            diagnostic: dict[str, str] = {}
            market = market_row_from_massive_bars(
                ticker,
                bars,
                now,
                current,
                diagnostic=diagnostic,
            )
            row.update(
                {
                    field: diagnostic.get(field, "")
                    for field in SMOKE_DIAGNOSTIC_FIELDS
                }
            )
            if market["data_quality_label"] != "insufficient_data":
                row.update({
                    "last_price": market["last_price"],
                    "previous_close": market["previous_close"],
                    "volume": market["volume"],
                })
                row["status"] = "passed" if row["last_price"] and row["previous_close"] else "failed"
        except Exception as exc:
            row["error_code"] = source_failure_code(exc)
            if (
                isinstance(exc, MassiveB2Error)
                and exc.code == HISTORICAL_SESSION_SEQUENCE_CODE
            ):
                row["validation_code"] = exc.code
                for field in (
                    "duplicate_session_dates",
                    "session_order_mismatch",
                ):
                    if field in exc.diagnostic:
                        row[field] = exc.diagnostic[field]
                if row.get("duplicate_session_dates"):
                    row["duplicate_session_count"] = str(
                        len(row["duplicate_session_dates"].split(","))
                    )
        if row["status"] != "passed" and "error_code" not in row:
            row["error_code"] = (
                row.get("validation_code") or SMOKE_VALIDATION_FAILED_CODE
            )
        results.append(row)
        if row["status"] != "passed":
            results.extend(
                {
                    "ticker": remaining,
                    "last_price": "",
                    "previous_close": "",
                    "volume": "",
                    "status": "not_attempted",
                    "error_code": SMOKE_PRECHECK_ABORTED_CODE,
                }
                for remaining in SMOKE_TICKERS[index + 1 :]
            )
            break
    return results, all(row["status"] == "passed" for row in results)


def validation_diagnostic_notes(
    row: dict[str, str] | None, *, prefix: str
) -> str:
    """Return bounded date/count metadata for one validation result."""

    if row is None:
        return f"{prefix}_diagnostic=not_available"
    if row.get("validation_code") == "none":
        return f"{prefix}_diagnostic=passed"
    fields = ["ticker", *SMOKE_DIAGNOSTIC_FIELDS]
    return "; ".join(
        f"{prefix}_diagnostic_{field}={row.get(field, '') or 'none'}"
        for field in fields
    )


def smoke_diagnostic_notes(rows: list[dict[str, str]]) -> str:
    """Return finite audit notes for the first locally diagnosed smoke row."""

    diagnosed = next(
        (
            candidate
            for candidate in rows
            if candidate.get("validation_code")
            and candidate.get("validation_code") != "none"
        ),
        None,
    )
    observed = next(
        (candidate for candidate in rows if candidate.get("validation_code")),
        None,
    )
    return validation_diagnostic_notes(
        diagnosed or observed,
        prefix="session",
    )


def retrieve_full_universe(
    tickers: list[str],
    now: str,
    *,
    client: MassiveBasicEODClient,
    current: datetime,
) -> tuple[
    list[dict[str, str]],
    str,
    bool,
    str,
    dict[str, str] | None,
]:
    start_date, end_date = history_window(current)
    try:
        rows: list[dict[str, str]] = []
        first_diagnostic: dict[str, str] | None = None
        for ticker in tickers:
            diagnostic: dict[str, str] = {}
            row = market_row_from_massive_bars(
                ticker,
                client.fetch_daily_bars(
                    ticker,
                    start_date=start_date,
                    end_date=end_date,
                ),
                now,
                current,
                diagnostic=diagnostic,
            )
            rows.append(row)
            if (
                first_diagnostic is None
                and diagnostic.get("validation_code")
                and diagnostic.get("validation_code") != "none"
            ):
                first_diagnostic = {"ticker": ticker, **diagnostic}
        if first_diagnostic is not None:
            failure_code = first_diagnostic["validation_code"]
            return (
                rows,
                f"full-universe response rejected before commit: {failure_code}",
                False,
                failure_code,
                first_diagnostic,
            )
        return (
            rows,
            "full-universe Massive Stocks Basic EOD history retrieved",
            True,
            "none",
            None,
        )
    except Exception as exc:
        failure_code = source_failure_code(exc)
        failure_diagnostic: dict[str, str] | None = None
        if (
            isinstance(exc, MassiveB2Error)
            and exc.code == HISTORICAL_SESSION_SEQUENCE_CODE
        ):
            failure_diagnostic = {
                "ticker": ticker,
                "validation_code": exc.code,
                **{
                    field: value
                    for field, value in exc.diagnostic.items()
                    if field in SMOKE_DIAGNOSTIC_FIELDS
                },
            }
        return (
            [
                empty_market_row(
                    ticker, f"{MASSIVE_DATA_SOURCE}_error", now
                )
                for ticker in tickers
            ],
            f"full-universe retrieval failed safely: {failure_code}",
            False,
            failure_code,
            failure_diagnostic,
        )


def write_decision(
    smoke_rows: list[dict[str, str]],
    smoke_passed: bool,
    full_note: str,
    held_tickers: list[str],
    *,
    prior_outputs_preserved: bool = False,
    source_failure_code: str = "none",
    full_diagnostic: dict[str, str] | None = None,
) -> None:
    lines = [
        "# Phase 5R-B2 Data Source Decision", "", f"Generated: `{timestamp()}`", "",
        "## Decision", "", f"- Selected source: `{MASSIVE_DATA_SOURCE}`.",
        "- Source use: `Massive Stocks Basic end-of-day read-only market data`.",
        "- Price basis: `unadjusted`; this preserves the former B2 `auto_adjust=False` semantics.",
        f"- Benchmark preflight: `{'passed' if smoke_passed else 'failed'}`.",
        f"- Source-failure classification: `{source_failure_code}`.",
        f"- Full-universe action: `{full_note}`.", "",
        "## Benchmark Preflight", "", "| Ticker | Last Price | Previous Close | Volume | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in smoke_rows:
        lines.append(f"| {row['ticker']} | {row['last_price'] or 'n/a'} | {row['previous_close'] or 'n/a'} | {row['volume'] or 'n/a'} | {row['status']} |")
    diagnosed_rows = [
        row
        for row in smoke_rows
        if row.get("validation_code")
        and row.get("validation_code") != "none"
    ]
    if full_diagnostic is not None:
        diagnosed_rows.append(full_diagnostic)
    if diagnosed_rows:
        lines.extend(["", "## Finite Session Diagnostic", ""])
        for row in diagnosed_rows:
            lines.append(
                f"- `{row['ticker']}`: code=`{row['validation_code']}`; "
                f"expected_count=`{row.get('expected_session_count') or 'unknown'}`; "
                f"observed_count=`{row.get('observed_session_count') or 'unknown'}`; "
                f"expected_latest=`{row.get('expected_latest_session') or 'none'}`; "
                f"observed_latest=`{row.get('observed_latest_session') or 'none'}`; "
                f"missing_dates=`{row.get('missing_session_dates') or 'none'}`; "
                f"unexpected_dates=`{row.get('unexpected_session_dates') or 'none'}`; "
                f"duplicate_dates=`{row.get('duplicate_session_dates') or 'none'}`; "
                f"order_mismatch=`{row.get('session_order_mismatch') or 'unknown'}`."
            )
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
        "- Provider authentication was supplied only by the external runtime; no API key value was printed, logged, persisted, hashed, or written to repository configuration.",
        "- No stored position percentage, position note, archived holding file, broker, account, order, or email workflow was used.",
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
        "safety_notes": f"read_only_public_market_data=yes; canonical_candidate_universe=yes; current_position_price_monitoring=yes; no_broker=yes; no_account=yes; no_orders=yes; no_email=yes; external_runtime_auth_only=yes; credential_value_logged=no; credential_value_persisted=no; archived_legacy_used=no; {notes}",
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
            market.get("data_source") not in COHERENT_DATA_SOURCES
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

    A successful provider request can still yield an empty or incomplete
    series for one ticker.  That is an upstream data failure, not a successful
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
            row.get("data_source") != MASSIVE_DATA_SOURCE
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

    if (
        len(tickers) != EXPECTED_PRODUCTION_B2_TICKER_COUNT
        or len(set(tickers)) != EXPECTED_PRODUCTION_B2_TICKER_COUNT
        or not REQUIRED_PRODUCTION_TICKERS.issubset(tickers)
    ):
        raise RuntimeError("production B2 ticker scope must be the exact approved 29")

    refresh_time = now_et()
    now = timestamp()
    client: MassiveBasicEODClient | None = None
    network_attempted = False
    try:
        client = MassiveBasicEODClient.from_environment()
    except Exception as exc:
        current_source_failure_code = source_failure_code(exc)
        smoke_rows = [
            {
                "ticker": ticker,
                "last_price": "",
                "previous_close": "",
                "volume": "",
                "status": "not_attempted",
                "error_code": current_source_failure_code,
            }
            for ticker in SMOKE_TICKERS
        ]
        smoke_passed = False
    else:
        network_attempted = True
        smoke_rows, smoke_passed = smoke_test(
            client,
            current=refresh_time,
            now=now,
        )
        current_source_failure_code = (
            "none" if smoke_passed else smoke_failure_code(smoke_rows)
        )
    smoke_audit_status = (
        "passed"
        if smoke_passed
        else "not_attempted"
        if not network_attempted
        else "failed"
    )
    append_audit(
        "benchmark_smoke_test",
        "QQQ;XLK;SPY",
        "in_memory_preflight_only",
        smoke_audit_status,
        "sequence=1; full_universe_fetch_not_started_before_this_check; "
        f"network_attempted={'yes' if network_attempted else 'no'}; "
        f"source_failure_code={current_source_failure_code}; "
        "provider=massive_stocks_basic_eod; adjusted=false; retries=0; "
        f"min_request_interval_seconds={MASSIVE_MIN_REQUEST_INTERVAL_SECONDS:.1f}; "
        f"{smoke_diagnostic_notes(smoke_rows)}",
    )
    source_failure = False
    full_retrieval_succeeded = False
    full_diagnostic: dict[str, str] | None = None
    prior_outputs_preserved = False
    prior_validation_reason = "not_checked"
    if smoke_passed:
        (
            market_rows,
            full_note,
            full_retrieval_succeeded,
            full_failure_code,
            full_diagnostic,
        ) = retrieve_full_universe(
            tickers,
            now,
            client=client,
            current=refresh_time,
        )
        if full_retrieval_succeeded:
            committable, commit_code = full_universe_rows_are_committable(
                market_rows=market_rows,
                tickers=tickers,
                held_tickers=held_tickers,
                current=refresh_time,
            )
            if not committable:
                market_rows = [
                    empty_market_row(
                        ticker,
                        f"{MASSIVE_DATA_SOURCE}_error",
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
            f"maximum_provider_requests={len(tickers)}; "
            f"source_failure_code={current_source_failure_code}; "
            f"fail_safe_stop={'no' if full_retrieval_succeeded else 'yes'}; "
            f"{validation_diagnostic_notes(full_diagnostic, prefix='full_session')}",
        )
    else:
        source_name = f"{MASSIVE_DATA_SOURCE}_unavailable"
        market_rows = [
            empty_market_row(ticker, source_name, now)
            for ticker in tickers
        ]
        full_note = (
            "not attempted because external Massive authentication is unavailable"
            if current_source_failure_code == AUTH_MISSING_CODE
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
            f"network_attempted={'yes' if network_attempted else 'no'}; "
            "retries=0",
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

    # A provider or validation failure never publishes a replacement B2 trio.
    # This remains true when the existing trio is already invalid: downstream
    # gates keep rejecting those unchanged bytes until a complete Massive
    # batch passes every commit check.
    if not source_failure:
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
        full_diagnostic=full_diagnostic,
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
    written_paths = [DECISION_PATH, REPORT_PATH]
    if not source_failure:
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
            else "source_failure_market_outputs_untouched"
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
