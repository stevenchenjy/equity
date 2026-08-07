from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR  # noqa: F401
import run_phase5r_b2_full_universe_market_data as b2


_FIXED_NOW = "2026-08-05T16:30:00-04:00"


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
        "market_session_date": "2026-08-04",
        "market_age_calendar_days": "1",
        "data_timestamp": "2026-08-04T20:15:00-04:00",
        "data_source": "yfinance_public_market_data",
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


def _candidate_row(
    seed: dict[str, str], market: dict[str, str]
) -> dict[str, str]:
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


class B2MarketRefreshFailureCommitTests(unittest.TestCase):
    def _paths(self, root: Path) -> dict[str, Path]:
        return {
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

    def _write_coherent_prior_outputs(self, paths: dict[str, Path]) -> None:
        seeds = [_seed(ticker) for ticker in b2.SMOKE_TICKERS]
        market_rows = [
            _market_row("QQQ", "100.0000"),
            _market_row("XLK", "101.0000"),
            _market_row("SPY", "102.0000"),
            _market_row("IOT", "103.0000"),
        ]
        market_by_ticker = {row["ticker"]: row for row in market_rows}
        b2.write_csv(paths["data"] / "phase5r_universe_seed.csv", seeds, list(seeds[0]))
        b2.write_csv(paths["positions"], [{"ticker": "IOT"}], ["ticker"])
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

    def _run_failed_smoke(
        self, paths: dict[str, Path]
    ) -> tuple[object, Mock]:
        smoke_rows = [
            {
                "ticker": ticker,
                "last_price": "",
                "previous_close": "",
                "volume": "",
                "status": "failed",
            }
            for ticker in b2.SMOKE_TICKERS
        ]
        full_retrieval = Mock(
            side_effect=AssertionError("full-universe retrieval must not run")
        )
        with ExitStack() as stack:
            for name, path in (
                ("ROOT", paths["data"].parents[1]),
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
            stack.enter_context(patch.object(b2, "timestamp", return_value=_FIXED_NOW))
            stack.enter_context(
                patch.object(b2, "smoke_test", return_value=(smoke_rows, False))
            )
            stack.enter_context(
                patch.object(b2, "retrieve_full_universe", full_retrieval)
            )
            return b2.main(), full_retrieval

    def test_failed_smoke_preserves_coherent_prior_trio_and_returns_nonzero(self) -> None:
        """A failed current source probe must not replace a usable prior baseline."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._paths(root)
            self._write_coherent_prior_outputs(paths)
            prior_bytes = {
                name: paths[name].read_bytes()
                for name in ("snapshot", "quality", "candidates")
            }
            result, full_retrieval = self._run_failed_smoke(paths)

            with self.subTest(contract="failed current source is nonzero"):
                self.assertEqual(result, 1)
            with self.subTest(contract="full-universe retrieval is skipped"):
                full_retrieval.assert_not_called()
            for name, expected in prior_bytes.items():
                with self.subTest(artifact=name):
                    self.assertEqual(paths[name].read_bytes(), expected)

            audit = b2.read_csv(paths["audit"])
            self.assertGreaterEqual(len(audit), 2)
            self.assertEqual(
                (audit[0]["action"], audit[0]["status"]),
                ("benchmark_smoke_test", "failed"),
            )
            self.assertEqual(
                (audit[1]["action"], audit[1]["status"]),
                ("full_universe_market_data_refresh", "not_attempted"),
            )
            self.assertIn("smoke_test_passed=no", audit[1]["safety_notes"])
            self.assertIn("fail_safe_stop=yes", audit[1]["safety_notes"])
            decision = paths["decision"].read_text(encoding="utf-8")
            self.assertIn("- Benchmark preflight: `failed`.", decision)
            self.assertIn(
                "- Full-universe action: `not attempted because benchmark preflight failed`.",
                decision,
            )

    def test_full_retrieval_exception_after_passed_smoke_preserves_prior_trio(self) -> None:
        """The post-preflight source failure has the same fail-closed commit rule."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._paths(root)
            self._write_coherent_prior_outputs(paths)
            prior_bytes = {
                name: paths[name].read_bytes()
                for name in ("snapshot", "quality", "candidates")
            }
            smoke_rows = [
                {
                    "ticker": ticker,
                    "last_price": "100.0000",
                    "previous_close": "99.0000",
                    "volume": "100000",
                    "status": "passed",
                }
                for ticker in b2.SMOKE_TICKERS
            ]
            with ExitStack() as stack:
                for name, path in (
                    ("ROOT", root),
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
                stack.enter_context(patch.object(b2, "timestamp", return_value=_FIXED_NOW))
                stack.enter_context(
                    patch.object(b2, "smoke_test", return_value=(smoke_rows, True))
                )
                download = stack.enter_context(
                    patch.object(
                        b2.yf,
                        "download",
                        side_effect=OSError("offline test source failure"),
                    )
                )
                result = b2.main()

            self.assertEqual(result, 1)
            download.assert_called_once()
            for name, expected in prior_bytes.items():
                with self.subTest(artifact=name):
                    self.assertEqual(paths[name].read_bytes(), expected)
            audit = b2.read_csv(paths["audit"])
            self.assertGreaterEqual(len(audit), 3)
            self.assertEqual(
                (audit[0]["action"], audit[0]["status"]),
                ("benchmark_smoke_test", "passed"),
            )
            self.assertEqual(
                (audit[1]["action"], audit[1]["status"]),
                ("full_universe_market_data_refresh", "failed"),
            )
            self.assertIn("smoke_test_passed=yes", audit[1]["safety_notes"])
            self.assertIn("full_retrieval_succeeded=no", audit[1]["safety_notes"])
            self.assertIn("fail_safe_stop=yes", audit[1]["safety_notes"])
            self.assertEqual(
                audit[-1]["status"], "source_failure_prior_outputs_preserved"
            )
            self.assertIn(
                "- Full-universe action: `full-universe retrieval failed safely: OSError`.",
                paths["decision"].read_text(encoding="utf-8"),
            )

    def test_failed_smoke_replaces_an_incoherent_prior_trio_with_one_fallback(self) -> None:
        """A partial or contradictory baseline may never be selectively reused."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._paths(root)
            self._write_coherent_prior_outputs(paths)
            candidates = b2.read_csv(paths["candidates"])
            candidates[0]["last_price"] = "999.0000"
            b2.write_csv(paths["candidates"], candidates, b2.CANDIDATE_FIELDS)

            result, full_retrieval = self._run_failed_smoke(paths)

            self.assertEqual(result, 1)
            full_retrieval.assert_not_called()
            snapshot = b2.read_csv(paths["snapshot"])
            quality = b2.read_csv(paths["quality"])
            candidates = b2.read_csv(paths["candidates"])
            self.assertEqual(
                {row["ticker"] for row in snapshot}, {"QQQ", "XLK", "SPY", "IOT"}
            )
            self.assertEqual(
                {row["ticker"] for row in quality}, {"QQQ", "XLK", "SPY", "IOT"}
            )
            self.assertEqual(
                {row["ticker"] for row in candidates}, set(b2.SMOKE_TICKERS)
            )
            self.assertTrue(
                all(
                    row["data_source"] == "yfinance_smoke_test_failed"
                    and row["data_quality_label"] == "insufficient_data"
                    and all(not row[field] for field in b2.CORE_FIELDS)
                    for row in snapshot
                )
            )
            self.assertTrue(
                all(
                    row["data_source"] == "yfinance_smoke_test_failed"
                    and row["data_quality_label"] == "insufficient_data"
                    and row["usable_for_scoring"] == "no"
                    for row in quality
                )
            )
            self.assertTrue(
                all(
                    row["data_source"] == "yfinance_smoke_test_failed"
                    and row["data_quality_label"] == "insufficient_data"
                    and row["market_data_usable"] == "no"
                    and all(not row[field] for field in b2.CORE_FIELDS)
                    for row in candidates
                )
            )


if __name__ == "__main__":
    unittest.main()
