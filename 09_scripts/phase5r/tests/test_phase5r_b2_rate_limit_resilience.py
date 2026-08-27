from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_massive_b2_adapter as massive


START = date(2026, 8, 3)
END = date(2026, 8, 5)
_CANARY_KEY = "massive-test-key-presence-only-7e4a"


def _timestamp(day: int) -> int:
    # Massive daily stock bars are aligned to the start of the ET aggregate
    # window; in August that midnight boundary is 04:00 UTC.
    return int(datetime(2026, 8, day, 4, tzinfo=timezone.utc).timestamp() * 1000)


def _payload(
    ticker: str = "IOT",
    *,
    status: object = "OK",
    adjusted: object = False,
    next_url: object = None,
) -> dict[str, object]:
    results = [
        {"t": _timestamp(3), "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.5, "v": 1000},
        {"t": _timestamp(4), "o": 11.0, "h": 12.0, "l": 10.0, "c": 11.5, "v": 1200},
    ]
    return {
        "status": status,
        "ticker": ticker,
        "adjusted": adjusted,
        "next_url": next_url,
        "resultsCount": len(results),
        "results": results,
    }


def _real_shaped_payload(ticker: str = "IOT") -> dict[str, object]:
    """Sanitized current Custom Bars shape, including optional metadata."""

    payload = _payload(ticker, status="DELAYED")
    payload["queryCount"] = 2
    payload["request_id"] = "opaque-provider-request-id"
    for index, row in enumerate(payload["results"]):
        row.update(
            {
                "vw": 10.75 + index,
                "n": 123 + index,
                "otc": False,
            }
        )
    return payload


class MassiveB2AdapterResilienceTests(unittest.TestCase):
    def _client(self, http_get, *, monotonic=None, sleep=None):
        kwargs = {"http_get": http_get}
        if monotonic is not None:
            kwargs["monotonic"] = monotonic
        if sleep is not None:
            kwargs["sleep"] = sleep
        return massive.MassiveBasicEODClient.from_environment(
            {massive.MASSIVE_API_KEY_ENV: _CANARY_KEY}, **kwargs
        )

    def test_environment_key_is_header_only_with_no_output_or_query_exposure(self) -> None:
        """The external-runtime key authorizes one request but never enters its URL/output."""

        calls: list[tuple[str, dict[str, str], float]] = []

        def http_get(path: str, headers: dict[str, str], timeout: float):
            calls.append((path, dict(headers), timeout))
            return _payload()

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            bars = self._client(http_get).fetch_daily_bars(
                "IOT", start_date=START, end_date=END
            )

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["session_date"], START)
        self.assertEqual(bars[-1]["session_date"], date(2026, 8, 4))
        self.assertEqual(len(calls), 1)
        path, headers, timeout = calls[0]
        parsed = urlsplit(path)
        self.assertEqual(
            parsed.path,
            "/v2/aggs/ticker/IOT/range/1/day/2026-08-03/2026-08-05",
        )
        self.assertEqual(
            parse_qs(parsed.query),
            {"adjusted": ["false"], "sort": ["asc"], "limit": ["50000"]},
        )
        self.assertNotIn(_CANARY_KEY, path)
        self.assertNotIn(_CANARY_KEY, parsed.query)
        self.assertEqual(headers["Authorization"], f"Bearer {_CANARY_KEY}")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(timeout, massive.MASSIVE_HTTP_TIMEOUT_SECONDS)
        self.assertNotIn(_CANARY_KEY, repr(bars))
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_real_stocks_basic_delayed_shape_normalizes_exactly(self) -> None:
        """The Basic delayed shape normalizes without leaking provider metadata."""

        bars = self._client(
            lambda path, headers, timeout: _real_shaped_payload()
        ).fetch_daily_bars("IOT", start_date=START, end_date=END)

        self.assertEqual(len(bars), 2)
        self.assertEqual(
            set(bars[0]),
            {
                "session_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "timestamp_ms",
            },
        )
        self.assertEqual(bars[0]["session_date"], START)
        self.assertEqual(bars[-1]["session_date"], date(2026, 8, 4))
        self.assertEqual(bars[0]["open"], 10.0)
        self.assertEqual(bars[0]["high"], 11.0)
        self.assertEqual(bars[0]["low"], 9.0)
        self.assertEqual(bars[0]["close"], 10.5)
        self.assertEqual(bars[0]["volume"], 1000.0)
        self.assertEqual(bars[0]["timestamp_ms"], _timestamp(3))
        self.assertNotIn("queryCount", bars[0])
        self.assertNotIn("request_id", bars[0])
        self.assertNotIn("vw", bars[0])
        self.assertNotIn("n", bars[0])
        self.assertNotIn("otc", bars[0])

    def test_response_status_success_allowlist_is_exact(self) -> None:
        for status in ("OK", "DELAYED"):
            with self.subTest(status=status):
                bars = self._client(
                    lambda path, headers, timeout, status=status: _payload(
                        status=status
                    )
                ).fetch_daily_bars("IOT", start_date=START, end_date=END)
                self.assertEqual(len(bars), 2)

    def test_smoke_ticker_cache_keeps_the_full_batch_to_twenty_nine_requests(self) -> None:
        calls: list[str] = []

        def http_get(path: str, headers: dict[str, str], timeout: float):
            calls.append(path)
            return _payload()

        client = self._client(http_get)
        first = client.fetch_daily_bars("IOT", start_date=START, end_date=END)
        second = client.fetch_daily_bars("IOT", start_date=START, end_date=END)

        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(len(calls), 1)

    def test_exact_response_validation_failures_are_finite_and_nonreflective(self) -> None:
        """Ticker, adjustment, pagination, and malformed data each stop once."""

        provider_canary = "provider-detail-must-not-be-reflected"
        count_mismatch = _payload()
        count_mismatch["resultsCount"] = 3
        cases = (
            (
                "unsupported_status",
                _payload(status="ERROR"),
                massive.MALFORMED_RESPONSE_CODE,
            ),
            (
                "invalid_status_type",
                _payload(status=True),
                massive.MALFORMED_RESPONSE_CODE,
            ),
            ("ticker", _payload("WRONG"), massive.TICKER_MISMATCH_CODE),
            ("adjustment", _payload(adjusted=True), massive.ADJUSTMENT_MISMATCH_CODE),
            (
                "pagination",
                _payload(
                    next_url=(
                        "https://api.massive.com/v2/next?cursor=opaque&apiKey="
                        + provider_canary
                    )
                ),
                massive.PAGINATION_CODE,
            ),
            (
                "provider_error_envelope",
                {"status": "ERROR", "error": provider_canary},
                massive.MALFORMED_RESPONSE_CODE,
            ),
            (
                "results_count_mismatch",
                count_mismatch,
                massive.MALFORMED_RESPONSE_CODE,
            ),
            (
                "malformed",
                {
                    "status": "OK",
                    "ticker": "IOT",
                    "adjusted": False,
                    "next_url": None,
                    "resultsCount": 1,
                    "results": [{"t": "not-an-integer"}],
                },
                massive.MALFORMED_RESPONSE_CODE,
            ),
        )
        for label, payload, expected_code in cases:
            with self.subTest(case=label):
                calls = 0

                def http_get(path: str, headers: dict[str, str], timeout: float):
                    nonlocal calls
                    calls += 1
                    return payload

                with self.assertRaises(massive.MassiveB2Error) as raised:
                    self._client(http_get).fetch_daily_bars(
                        "IOT", start_date=START, end_date=END
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(str(raised.exception), expected_code)
                self.assertNotIn(provider_canary, str(raised.exception))
                self.assertNotIn(_CANARY_KEY, str(raised.exception))
                self.assertEqual(calls, 1)

    def test_duplicate_provider_session_has_finite_b_code_and_safe_date(self) -> None:
        provider_canary = "duplicate-provider-detail-must-not-be-reflected"
        payload = _payload()
        payload["request_id"] = provider_canary
        payload["results"][1]["t"] = payload["results"][0]["t"]
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(massive.MassiveB2Error) as raised:
                self._client(
                    lambda path, headers, timeout: payload
                ).fetch_daily_bars("IOT", start_date=START, end_date=END)

        self.assertEqual(
            raised.exception.code,
            massive.HISTORICAL_SESSION_SEQUENCE_CODE,
        )
        self.assertEqual(
            raised.exception.diagnostic,
            {"duplicate_session_dates": "2026-08-03"},
        )
        self.assertEqual(str(raised.exception), massive.HISTORICAL_SESSION_SEQUENCE_CODE)
        self.assertNotIn(provider_canary, str(raised.exception))
        self.assertNotIn(_CANARY_KEY, str(raised.exception))
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_invalid_json_body_is_rejected_without_reflection(self) -> None:
        provider_canary = "invalid-json-provider-detail-must-not-be-reflected"

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, maximum_bytes: int) -> bytes:
                self.maximum_bytes = maximum_bytes
                return ('{"status":"OK","detail":"' + provider_canary).encode()

        response = Response()
        opener = Mock()
        opener.open.return_value = response
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(massive, "build_opener", return_value=opener):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaises(massive.MassiveB2Error) as raised:
                    massive.MassiveBasicEODClient(_CANARY_KEY).fetch_daily_bars(
                        "IOT", start_date=START, end_date=END
                    )

        self.assertEqual(raised.exception.code, massive.MALFORMED_RESPONSE_CODE)
        self.assertEqual(str(raised.exception), massive.MALFORMED_RESPONSE_CODE)
        self.assertNotIn(provider_canary, str(raised.exception))
        self.assertNotIn(provider_canary, stdout.getvalue())
        self.assertNotIn(provider_canary, stderr.getvalue())
        opener.open.assert_called_once()
        self.assertEqual(
            response.maximum_bytes,
            massive.MASSIVE_MAX_RESPONSE_BYTES + 1,
        )

    def test_http_429_maps_to_exact_finite_code_without_retry_or_error_reflection(self) -> None:
        """A provider 429 is one request and exposes neither URL detail nor key."""

        provider_detail = f"https://provider.invalid/?apiKey={_CANARY_KEY}"
        error = HTTPError(provider_detail, 429, "rate limited", None, None)
        client = massive.MassiveBasicEODClient(_CANARY_KEY)
        opener = Mock()
        opener.open.side_effect = error
        with patch.object(massive, "build_opener", return_value=opener) as build_opener:
            with self.assertRaises(massive.MassiveB2Error) as raised:
                client.fetch_daily_bars("IOT", start_date=START, end_date=END)

        self.assertEqual(raised.exception.code, massive.RATE_LIMIT_CODE)
        self.assertEqual(str(raised.exception), massive.RATE_LIMIT_CODE)
        self.assertNotIn(_CANARY_KEY, str(raised.exception))
        build_opener.assert_called_once()
        opener.open.assert_called_once()

    def test_pacing_is_strictly_below_five_requests_per_minute_and_failures_retry_zero_times(self) -> None:
        """Every new ticker is locally paced, while a failed request is never retried."""

        clock = [0.0]
        sleeps: list[float] = []
        successful_calls: list[str] = []

        def monotonic() -> float:
            return clock[0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        def success(path: str, headers: dict[str, str], timeout: float):
            successful_calls.append(path)
            ticker = path.split("/ticker/", 1)[1].split("/", 1)[0]
            return _payload(ticker)

        client = self._client(success, monotonic=monotonic, sleep=sleep)
        client.fetch_daily_bars("IOT", start_date=START, end_date=END)
        client.fetch_daily_bars("RBRK", start_date=START, end_date=END)

        self.assertEqual(len(successful_calls), 2)
        self.assertEqual(sleeps, [massive.MASSIVE_MIN_REQUEST_INTERVAL_SECONDS])
        self.assertGreater(massive.MASSIVE_MIN_REQUEST_INTERVAL_SECONDS, 12.0)
        self.assertLess(60.0 / massive.MASSIVE_MIN_REQUEST_INTERVAL_SECONDS, 5.0)

        failed_calls = 0

        def rate_limited(path: str, headers: dict[str, str], timeout: float):
            nonlocal failed_calls
            failed_calls += 1
            raise massive.MassiveB2Error(massive.RATE_LIMIT_CODE)

        with self.assertRaises(massive.MassiveB2Error) as raised:
            self._client(rate_limited).fetch_daily_bars(
                "IOT", start_date=START, end_date=END
            )
        self.assertEqual(raised.exception.code, massive.RATE_LIMIT_CODE)
        self.assertEqual(failed_calls, 1)


if __name__ == "__main__":
    unittest.main()
