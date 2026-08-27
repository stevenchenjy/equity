#!/usr/bin/env python3
"""Bounded Massive Stocks Basic EOD adapter for the active Phase 5R B2 path.

The adapter performs one Custom Bars request per ticker, authenticates only by
an externally supplied Authorization header, never retries, and returns only a
small normalized in-memory bar series.  It does not persist raw provider data,
credentials, request identifiers, response text, broker data, orders, or email.
"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo


MASSIVE_API_KEY_ENV = "MASSIVE_API_KEY"
MASSIVE_BASE_URL = "https://api.massive.com"
MASSIVE_DATA_SOURCE = "massive_stocks_basic_eod"
MASSIVE_MIN_REQUEST_INTERVAL_SECONDS = 13.0
MASSIVE_HTTP_TIMEOUT_SECONDS = 10.0
MASSIVE_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MASSIVE_HISTORY_LIMIT = 50000

AUTH_MISSING_CODE = "massive_authentication_missing"
AUTH_FAILED_CODE = "massive_authentication_failed"
RATE_LIMIT_CODE = "massive_rate_limited"
TIMEOUT_CODE = "massive_timeout"
SERVICE_UNAVAILABLE_CODE = "massive_service_unavailable"
REQUEST_REJECTED_CODE = "massive_request_rejected"
REQUEST_FAILED_CODE = "massive_request_failed"
RESPONSE_OVERSIZE_CODE = "massive_response_oversize"
MALFORMED_RESPONSE_CODE = "massive_malformed_response"
PAGINATION_CODE = "massive_unexpected_pagination"
TICKER_MISMATCH_CODE = "massive_ticker_mismatch"
ADJUSTMENT_MISMATCH_CODE = "massive_adjustment_mismatch"
STALE_RESPONSE_CODE = "massive_stale_response"
HISTORICAL_SESSION_SEQUENCE_CODE = "massive_historical_session_sequence_invalid"

FINITE_FAILURE_CODES = frozenset(
    {
        AUTH_MISSING_CODE,
        AUTH_FAILED_CODE,
        RATE_LIMIT_CODE,
        TIMEOUT_CODE,
        SERVICE_UNAVAILABLE_CODE,
        REQUEST_REJECTED_CODE,
        REQUEST_FAILED_CODE,
        RESPONSE_OVERSIZE_CODE,
        MALFORMED_RESPONSE_CODE,
        PAGINATION_CODE,
        TICKER_MISMATCH_CODE,
        ADJUSTMENT_MISMATCH_CODE,
        STALE_RESPONSE_CODE,
        HISTORICAL_SESSION_SEQUENCE_CODE,
    }
)

ET = ZoneInfo("America/New_York")
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")

HttpGet = Callable[[str, Mapping[str, str], float], Any]


class MassiveB2Error(RuntimeError):
    """Finite, non-sensitive provider failure safe for local audit fields."""

    def __init__(
        self,
        code: str,
        *,
        diagnostic: Mapping[str, str] | None = None,
    ) -> None:
        if code not in FINITE_FAILURE_CODES:
            raise ValueError("unsupported Massive B2 failure code")
        safe_diagnostic: dict[str, str] = {}
        for key, value in dict(diagnostic or {}).items():
            if key == "duplicate_session_dates":
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}(,\d{4}-\d{2}-\d{2})*", value) is None:
                    raise ValueError("unsafe Massive B2 diagnostic")
            elif key == "session_order_mismatch":
                if value not in {"yes", "no"}:
                    raise ValueError("unsafe Massive B2 diagnostic")
            else:
                raise ValueError("unsupported Massive B2 diagnostic field")
            safe_diagnostic[key] = value
        self.code = code
        self.diagnostic = safe_diagnostic
        super().__init__(code)


class _NoRedirectHandler(HTTPRedirectHandler):
    """Keep the authorization header bound to the configured API origin."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def api_key_from_environment(
    environment: Mapping[str, str] | None = None,
) -> str:
    """Return the external runtime key without printing or persisting it."""

    source = os.environ if environment is None else environment
    value = source.get(MASSIVE_API_KEY_ENV)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() or ord(character) < 33 for character in value)
    ):
        raise MassiveB2Error(AUTH_MISSING_CODE)
    return value


def _http_failure_code(status: int) -> str:
    if status in {401, 403}:
        return AUTH_FAILED_CODE
    if status == 429:
        return RATE_LIMIT_CODE
    if 400 <= status < 500:
        return REQUEST_REJECTED_CODE
    if status >= 500:
        return SERVICE_UNAVAILABLE_CODE
    return REQUEST_FAILED_CODE


def _default_http_get(
    path_and_query: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> Any:
    """Fetch and parse one bounded JSON response without reflecting failures."""

    try:
        request = Request(
            f"{MASSIVE_BASE_URL}{path_and_query}",
            headers=dict(headers),
            method="GET",
        )
        with build_opener(_NoRedirectHandler()).open(
            request, timeout=timeout_seconds
        ) as response:
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise MassiveB2Error(_http_failure_code(status))
            raw = response.read(MASSIVE_MAX_RESPONSE_BYTES + 1)
    except MassiveB2Error:
        raise
    except HTTPError as exc:
        raise MassiveB2Error(_http_failure_code(int(exc.code))) from None
    except (TimeoutError, socket.timeout):
        raise MassiveB2Error(TIMEOUT_CODE) from None
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise MassiveB2Error(TIMEOUT_CODE) from None
        raise MassiveB2Error(REQUEST_FAILED_CODE) from None
    except OSError:
        raise MassiveB2Error(REQUEST_FAILED_CODE) from None
    except Exception:
        # Never reflect a provider/library exception because it may contain a
        # request object or headers. The runner persists this finite code only.
        raise MassiveB2Error(REQUEST_FAILED_CODE) from None

    if len(raw) > MASSIVE_MAX_RESPONSE_BYTES:
        raise MassiveB2Error(RESPONSE_OVERSIZE_CODE)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise MassiveB2Error(MALFORMED_RESPONSE_CODE) from None


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
    parsed = float(value)
    if not math.isfinite(parsed):
        raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
    return parsed


def _normalized_bars(
    payload: Any,
    *,
    ticker: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
    # Stocks Basic can label a structurally successful end-of-day response as
    # DELAYED. Accept only the two successful response states; every missing,
    # non-string, or error state still fails closed before bar normalization.
    response_status = payload.get("status")
    if (
        not isinstance(response_status, str)
        or response_status not in {"OK", "DELAYED"}
    ):
        raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
    if payload.get("ticker") != ticker:
        raise MassiveB2Error(TICKER_MISMATCH_CODE)
    # The former B2 source used yfinance(auto_adjust=False).  Explicitly
    # require Massive's unadjusted series so downstream close/range/volume
    # semantics do not silently change during the source replacement.
    if payload.get("adjusted") is not False:
        raise MassiveB2Error(ADJUSTMENT_MISMATCH_CODE)
    if payload.get("next_url") not in {None, ""}:
        raise MassiveB2Error(PAGINATION_CODE)
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
    results_count = payload.get("resultsCount")
    if (
        not isinstance(results_count, int)
        or isinstance(results_count, bool)
        or results_count != len(results)
    ):
        raise MassiveB2Error(MALFORMED_RESPONSE_CODE)

    bars: list[dict[str, Any]] = []
    seen_timestamps: set[int] = set()
    seen_session_dates: set[date] = set()
    prior_timestamp = 0
    for raw in results:
        if not isinstance(raw, dict):
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
        timestamp_ms = raw.get("t")
        if (
            not isinstance(timestamp_ms, int)
            or isinstance(timestamp_ms, bool)
            or timestamp_ms <= 0
        ):
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
        if raw.get("otc") is True:
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
        try:
            session_date = datetime.fromtimestamp(
                timestamp_ms / 1000,
                tz=timezone.utc,
            ).astimezone(ET).date()
        except (OSError, OverflowError, ValueError):
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE) from None
        if session_date < start_date or session_date > end_date:
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
        if timestamp_ms <= prior_timestamp or timestamp_ms in seen_timestamps:
            diagnostic = (
                {"duplicate_session_dates": session_date.isoformat()}
                if timestamp_ms in seen_timestamps
                else {"session_order_mismatch": "yes"}
            )
            raise MassiveB2Error(
                HISTORICAL_SESSION_SEQUENCE_CODE,
                diagnostic=diagnostic,
            )
        if session_date in seen_session_dates:
            raise MassiveB2Error(
                HISTORICAL_SESSION_SEQUENCE_CODE,
                diagnostic={"duplicate_session_dates": session_date.isoformat()},
            )

        open_price = _finite_number(raw.get("o"))
        high = _finite_number(raw.get("h"))
        low = _finite_number(raw.get("l"))
        close = _finite_number(raw.get("c"))
        volume = _finite_number(raw.get("v"))
        if (
            min(open_price, high, low, close) <= 0
            or volume < 0
            or high < low
            or not low <= open_price <= high
            or not low <= close <= high
        ):
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)

        bars.append(
            {
                "session_date": session_date,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "timestamp_ms": timestamp_ms,
            }
        )
        prior_timestamp = timestamp_ms
        seen_timestamps.add(timestamp_ms)
        seen_session_dates.add(session_date)
    return bars


class MassiveBasicEODClient:
    """One-process, no-retry client paced safely below five calls per minute."""

    __slots__ = (
        "_api_key",
        "_http_get",
        "_monotonic",
        "_sleep",
        "_last_request_started",
        "_cache",
    )

    def __init__(
        self,
        api_key: str,
        *,
        http_get: HttpGet = _default_http_get,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(api_key, str) or not api_key:
            raise MassiveB2Error(AUTH_MISSING_CODE)
        self._api_key = api_key
        self._http_get = http_get
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_started: float | None = None
        self._cache: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> "MassiveBasicEODClient":
        return cls(api_key_from_environment(environment), **kwargs)

    def _pace(self) -> None:
        current = self._monotonic()
        if self._last_request_started is not None:
            remaining = (
                MASSIVE_MIN_REQUEST_INTERVAL_SECONDS
                - (current - self._last_request_started)
            )
            if remaining > 0:
                self._sleep(remaining)
                current = self._monotonic()
        self._last_request_started = current

    def fetch_daily_bars(
        self,
        ticker: str,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        if not isinstance(ticker, str) or _TICKER.fullmatch(ticker) is None:
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
        if start_date >= end_date:
            raise MassiveB2Error(MALFORMED_RESPONSE_CODE)
        cache_key = (ticker, start_date.isoformat(), end_date.isoformat())
        if cache_key in self._cache:
            return [dict(bar) for bar in self._cache[cache_key]]

        query = urlencode(
            {
                "adjusted": "false",
                "sort": "asc",
                "limit": str(MASSIVE_HISTORY_LIMIT),
            }
        )
        path = (
            f"/v2/aggs/ticker/{quote(ticker, safe='.-')}/range/1/day/"
            f"{start_date.isoformat()}/{end_date.isoformat()}?{query}"
        )
        self._pace()
        payload = self._http_get(
            path,
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": "Phase5R-Massive-B2/1.0",
            },
            MASSIVE_HTTP_TIMEOUT_SECONDS,
        )
        bars = _normalized_bars(
            payload,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
        )
        self._cache[cache_key] = [dict(bar) for bar in bars]
        return [dict(bar) for bar in bars]


__all__ = [
    "ADJUSTMENT_MISMATCH_CODE",
    "AUTH_FAILED_CODE",
    "AUTH_MISSING_CODE",
    "FINITE_FAILURE_CODES",
    "HISTORICAL_SESSION_SEQUENCE_CODE",
    "MALFORMED_RESPONSE_CODE",
    "MASSIVE_API_KEY_ENV",
    "MASSIVE_DATA_SOURCE",
    "MASSIVE_HTTP_TIMEOUT_SECONDS",
    "MASSIVE_MIN_REQUEST_INTERVAL_SECONDS",
    "MassiveB2Error",
    "MassiveBasicEODClient",
    "PAGINATION_CODE",
    "RATE_LIMIT_CODE",
    "REQUEST_FAILED_CODE",
    "STALE_RESPONSE_CODE",
    "api_key_from_environment",
]
