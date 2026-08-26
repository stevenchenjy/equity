from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_massive_b2_adapter as massive
import run_phase5r_b2_full_universe_market_data as b2


_FIXED_NOW = "2026-08-05T17:45:00-04:00"
POST_CLOSE = datetime(2026, 8, 5, 17, 45, tzinfo=ZoneInfo("America/New_York"))
UNIVERSE_TICKERS = [
    *b2.SMOKE_TICKERS,
    *[f"T{index:02d}" for index in range(1, 25)],
]
HELD_TICKERS = ["IOT", "RBRK"]
B2_TICKERS = [*UNIVERSE_TICKERS, *HELD_TICKERS]
assert len(UNIVERSE_TICKERS) == 27
assert len(B2_TICKERS) == 29
_CANARY = "massive-provider-detail-must-not-persist-7e4a"


def _seed(ticker: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Holdings",
        "sector": "Technology",
        "industry": "Software",
        "theme": "research",
        "liquidity_tier": "high",
        "volatility_tier": "medium",
        "is_benchmark": "yes" if ticker in b2.SMOKE_TICKERS else "no",
        "max_position_pct": "0.10",
    }


def _market_row(ticker: str, price: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "last_price": price,
        "previous_close": "99.0000",
        "intraday_change_pct": "1.0101",
        "volume": "100000",
        "average_volume": "90000",
        "relative_volume": "1.1111",
        "dollar_volume": "10000000",
        "day_high": "101.0000",
        "day_low": "98.0000",
        "fifty_two_week_high": "120.0000",
        "fifty_two_week_low": "75.0000",
        "market_session_date": "2026-08-05",
        "market_age_calendar_days": "0",
        "data_timestamp": _FIXED_NOW,
        "data_source": massive.MASSIVE_DATA_SOURCE,
        "data_quality_label": "ok",
    }


def _quality_row(market: dict[str, str]) -> dict[str, str]:
    return {
        "ticker": market["ticker"],
        "data_source": market["data_source"],
        "data_quality_label": market["data_quality_label"],
        "missing_fields": "",
        "usable_for_scoring": "yes",
        "notes": "read-only public row ready for scoring",
    }


def _candidate_row(seed: dict[str, str], market: dict[str, str]) -> dict[str, str]:
    row = {
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
    row.update({field: market[field] for field in b2.MARKET_FIELDS[1:]})
    row.update(
        {
            "market_data_usable": "yes",
            "candidate_note": "daily public data attached",
        }
    )
    return row


def _valid_bars(current: datetime) -> list[dict[str, object]]:
    return [
        {
            "session_date": session,
            "open": 90.0 + index,
            "high": 92.0 + index,
            "low": 89.0 + index,
            "close": 91.0 + index,
            "volume": 100000.0 + index,
        }
        for index, session in enumerate(b2.expected_history_sessions(current))
    ]


class _PartialTwentyNineTickerClient:
    def __init__(self, current: datetime, missing_ticker: str) -> None:
        self.current = current
        self.missing_ticker = missing_ticker
        self.calls: list[str] = []

    def fetch_daily_bars(
        self, ticker: str, *, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        self.calls.append(ticker)
        if ticker == self.missing_ticker:
            return []
        return _valid_bars(self.current)


class _FailingFullFetchClient:
    def __init__(self, current: datetime) -> None:
        self.current = current
        self.calls: list[str] = []

    def fetch_daily_bars(
        self, ticker: str, *, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        self.calls.append(ticker)
        if len(self.calls) <= len(b2.SMOKE_TICKERS):
            return _valid_bars(self.current)
        raise OSError(_CANARY)


class _CompleteCachedClient:
    def __init__(self, current: datetime) -> None:
        self.current = current
        self.calls: list[str] = []
        self.cache: dict[str, list[dict[str, object]]] = {}

    def fetch_daily_bars(
        self, ticker: str, *, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        if ticker not in self.cache:
            self.calls.append(ticker)
            self.cache[ticker] = _valid_bars(self.current)
        return [dict(bar) for bar in self.cache[ticker]]


class B2MarketRefreshFailureCommitTests(unittest.TestCase):
    def _paths(self, root: Path) -> dict[str, Path]:
        return {
            "root": root,
            "data": root / "03_source_data" / "phase5r",
            "positions": root / "05_risk_and_positions" / "current_positions.local.csv",
            "snapshot": root / "03_source_data" / "phase5r" / "phase5r_b2_market_data_snapshot.csv",
            "quality": root / "03_source_data" / "phase5r" / "phase5r_b2_market_data_quality_report.csv",
            "candidates": root / "03_source_data" / "phase5r" / "phase5r_b2_candidates_with_market_data.csv",
            "audit": root / "03_source_data" / "phase5r" / "phase5r_b2_audit_trail.csv",
            "decision": root / "00_project_control" / "phase5r_b2_data_source_decision.md",
            "report": root / "04_research" / "realtime_stock_picker_phase5r" / "phase5r_b2_data_report.md",
            "run_log": root / "00_project_control" / "run_logs" / "phase5r_b2_run_log.csv",
        }

    def _patch_paths(self, stack: ExitStack, paths: dict[str, Path]) -> None:
        for name, path in (
            ("ROOT", paths["root"]),
            ("DATA_DIR", paths["data"]),
            ("UNIVERSE_PATH", paths["data"] / "phase5r_universe_seed.csv"),
            ("LOCAL_POSITIONS_PATH", paths["positions"]),
            ("SNAPSHOT_PATH", paths["snapshot"]),
            ("QUALITY_PATH", paths["quality"]),
            ("CANDIDATES_PATH", paths["candidates"]),
            ("AUDIT_PATH", paths["audit"]),
            ("DECISION_PATH", paths["decision"]),
            ("REPORT_PATH", paths["report"]),
            ("RUN_LOG", paths["run_log"]),
        ):
            stack.enter_context(patch.object(b2, name, path))

    def _write_prior_outputs(self, paths: dict[str, Path]) -> None:
        seeds = [_seed(ticker) for ticker in UNIVERSE_TICKERS]
        market_rows = [
            _market_row(ticker, f"{100 + index:.4f}")
            for index, ticker in enumerate(B2_TICKERS)
        ]
        market_by_ticker = {row["ticker"]: row for row in market_rows}
        b2.write_csv(paths["data"] / "phase5r_universe_seed.csv", seeds, list(seeds[0]))
        b2.write_csv(
            paths["positions"],
            [{"ticker": ticker} for ticker in HELD_TICKERS],
            ["ticker"],
        )
        b2.write_csv(paths["snapshot"], market_rows, b2.MARKET_FIELDS)
        b2.write_csv(
            paths["quality"],
            [_quality_row(row) for row in market_rows],
            b2.QUALITY_FIELDS,
        )
        b2.write_csv(
            paths["candidates"],
            [_candidate_row(seed, market_by_ticker[seed["ticker"]]) for seed in seeds],
            b2.CANDIDATE_FIELDS,
        )

    @staticmethod
    def _trio_bytes(paths: dict[str, Path]) -> dict[str, bytes]:
        return {
            name: paths[name].read_bytes()
            for name in ("snapshot", "quality", "candidates")
        }

    def _run_with_client(
        self, paths: dict[str, Path], client: object
    ) -> int:
        with ExitStack() as stack:
            self._patch_paths(stack, paths)
            stack.enter_context(patch.object(b2, "timestamp", return_value=_FIXED_NOW))
            stack.enter_context(patch.object(b2, "now_et", return_value=POST_CLOSE))
            stack.enter_context(
                patch.object(
                    b2.MassiveBasicEODClient,
                    "from_environment",
                    return_value=client,
                )
            )
            return b2.main()

    def test_full_massive_provider_failure_preserves_coherent_prior_trio_and_logs_only_code(self) -> None:
        """A post-preflight provider failure cannot overwrite the last complete batch."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_prior_outputs(paths)
            prior = self._trio_bytes(paths)
            client = _FailingFullFetchClient(POST_CLOSE)
            result = self._run_with_client(paths, client)

            self.assertEqual(result, 1)
            self.assertEqual(client.calls, [*b2.SMOKE_TICKERS, b2.SMOKE_TICKERS[0]])
            for name, expected in prior.items():
                self.assertEqual(paths[name].read_bytes(), expected, name)
            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (paths["audit"], paths["decision"], paths["report"], paths["run_log"])
            )
            self.assertIn(
                f"source_failure_code={massive.REQUEST_FAILED_CODE}", persisted
            )
            self.assertNotIn(_CANARY, persisted)

    def test_complete_valid_batch_commits_all_twenty_nine_rows_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_prior_outputs(paths)
            prior = self._trio_bytes(paths)
            client = _CompleteCachedClient(POST_CLOSE)

            result = self._run_with_client(paths, client)

            self.assertEqual(result, 0)
            self.assertEqual(len(client.calls), 29)
            self.assertEqual(set(client.calls), set(B2_TICKERS))
            self.assertTrue(any(paths[name].read_bytes() != prior[name] for name in prior))
            snapshot = b2.read_csv(paths["snapshot"])
            quality = b2.read_csv(paths["quality"])
            candidates = b2.read_csv(paths["candidates"])
            self.assertEqual(len(snapshot), 29)
            self.assertEqual(len(quality), 29)
            self.assertEqual(len(candidates), 27)
            self.assertEqual({row["ticker"] for row in snapshot}, set(B2_TICKERS))
            self.assertEqual(
                {row["data_source"] for row in snapshot},
                {massive.MASSIVE_DATA_SOURCE},
            )
            self.assertEqual(
                {row["market_session_date"] for row in snapshot},
                {"2026-08-05"},
            )

    def test_thirtieth_ticker_is_rejected_before_client_construction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_prior_outputs(paths)
            extra_seed = _seed("EXTRA")
            seeds = [_seed(ticker) for ticker in UNIVERSE_TICKERS] + [extra_seed]
            b2.write_csv(
                paths["data"] / "phase5r_universe_seed.csv",
                seeds,
                list(seeds[0]),
            )
            with ExitStack() as stack:
                self._patch_paths(stack, paths)
                stack.enter_context(patch.object(b2, "now_et", return_value=POST_CLOSE))
                factory = stack.enter_context(
                    patch.object(b2.MassiveBasicEODClient, "from_environment")
                )
                with self.assertRaisesRegex(RuntimeError, "exact approved 29"):
                    b2.main()

            factory.assert_not_called()

    def test_partial_twenty_nine_ticker_fetch_cannot_commit_any_part_of_prior_trio(self) -> None:
        """A single unusable ticker makes the complete 29-ticker batch noncommittable."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_prior_outputs(paths)
            prior = self._trio_bytes(paths)
            client = _PartialTwentyNineTickerClient(POST_CLOSE, B2_TICKERS[-1])
            result = self._run_with_client(paths, client)

            self.assertEqual(result, 1)
            self.assertEqual(client.calls[:3], b2.SMOKE_TICKERS)
            self.assertEqual(client.calls[3:], B2_TICKERS)
            self.assertEqual(len(client.calls[3:]), 29)
            for name, expected in prior.items():
                self.assertEqual(paths[name].read_bytes(), expected, name)
            audit = b2.read_csv(paths["audit"])
            self.assertIn(
                f"source_failure_code={b2.FULL_UNIVERSE_INCOMPLETE_CODE}",
                audit[1]["safety_notes"],
            )

    def test_failed_source_leaves_even_an_invalid_prior_trio_byte_for_byte_unchanged(self) -> None:
        """Failure is not authority to replace a malformed baseline with fallback rows."""

        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_prior_outputs(paths)
            malformed_candidates = paths["candidates"].read_bytes() + b"truncated,prior,row\n"
            paths["candidates"].write_bytes(malformed_candidates)
            prior = self._trio_bytes(paths)
            smoke_rows = [
                {
                    "ticker": ticker,
                    "last_price": "",
                    "previous_close": "",
                    "volume": "",
                    "status": "failed",
                    "error_code": massive.MALFORMED_RESPONSE_CODE,
                }
                for ticker in b2.SMOKE_TICKERS
            ]
            full_retrieval = Mock(
                side_effect=AssertionError("failed smoke must prevent full fetch")
            )
            with ExitStack() as stack:
                self._patch_paths(stack, paths)
                stack.enter_context(patch.object(b2, "timestamp", return_value=_FIXED_NOW))
                stack.enter_context(patch.object(b2, "now_et", return_value=POST_CLOSE))
                stack.enter_context(
                    patch.object(b2.MassiveBasicEODClient, "from_environment", return_value=object())
                )
                stack.enter_context(
                    patch.object(b2, "smoke_test", return_value=(smoke_rows, False))
                )
                stack.enter_context(
                    patch.object(b2, "retrieve_full_universe", full_retrieval)
                )
                result = b2.main()

            self.assertEqual(result, 1)
            full_retrieval.assert_not_called()
            for name, expected in prior.items():
                self.assertEqual(paths[name].read_bytes(), expected, name)

    def test_full_response_requires_the_latest_completed_session(self) -> None:
        """A complete-looking delayed Massive response remains noncommittable."""

        rows = [
            _market_row(ticker, str(100 + index))
            for index, ticker in enumerate(B2_TICKERS)
        ]
        rows[0]["market_session_date"] = "2026-08-04"
        rows[0]["market_age_calendar_days"] = "1"

        committable, code = b2.full_universe_rows_are_committable(
            market_rows=rows,
            tickers=B2_TICKERS,
            held_tickers=HELD_TICKERS,
            current=POST_CLOSE,
        )

        self.assertFalse(committable)
        self.assertEqual(code, b2.FULL_UNIVERSE_STALE_CODE)

    def test_massive_bars_preserve_all_existing_b2_calculations(self) -> None:
        bars = [
            {
                "session_date": session,
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 100.0,
                "volume": 1000.0,
            }
            for session in b2.expected_history_sessions(POST_CLOSE)
        ]
        bars[-2]["close"] = 99.0
        bars[-1].update(
            {"high": 111.0, "low": 98.0, "close": 110.0, "volume": 2000.0}
        )

        row = b2.market_row_from_massive_bars(
            "IOT", bars, _FIXED_NOW, POST_CLOSE
        )

        self.assertEqual(row["last_price"], "110.0000")
        self.assertEqual(row["previous_close"], "99.0000")
        self.assertEqual(row["intraday_change_pct"], "11.1111")
        self.assertEqual(row["volume"], "2000")
        self.assertEqual(row["average_volume"], "1050")
        self.assertEqual(row["relative_volume"], "1.9048")
        self.assertEqual(row["dollar_volume"], "220000")
        self.assertEqual(row["day_high"], "111.0000")
        self.assertEqual(row["day_low"], "98.0000")
        self.assertEqual(row["fifty_two_week_high"], "111.0000")
        self.assertEqual(row["fifty_two_week_low"], "95.0000")
        self.assertEqual(row["market_session_date"], "2026-08-05")
        self.assertEqual(row["data_source"], massive.MASSIVE_DATA_SOURCE)
        self.assertEqual(row["data_quality_label"], "ok")

        del bars[len(bars) // 2]
        incomplete = b2.market_row_from_massive_bars(
            "IOT", bars, _FIXED_NOW, POST_CLOSE
        )
        self.assertEqual(incomplete["data_quality_label"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
