from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import run_phase5r_b2_full_universe_market_data as b2


ET = ZoneInfo("America/New_York")
PRE_CLOSE = datetime(2026, 8, 5, 9, 0, tzinfo=ET)
POST_CLOSE = datetime(2026, 8, 5, 17, 45, tzinfo=ET)


def _seed(ticker: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Holdings",
        "sector": "Technology",
        "industry": "Software",
        "theme": "research",
        "liquidity_tier": "high",
        "volatility_tier": "medium",
        "is_benchmark": "yes",
        "max_position_pct": "0.10",
    }


class B2RateLimitResilienceTests(unittest.TestCase):
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
            "rate_limit_state": root / "00_project_control" / "run_logs" / "phase5r_b2_rate_limit_state.local.json",
        }

    def _write_inputs(self, paths: dict[str, Path]) -> None:
        seeds = [_seed(ticker) for ticker in b2.SMOKE_TICKERS]
        b2.write_csv(
            paths["data"] / "phase5r_universe_seed.csv", seeds, list(seeds[0])
        )
        b2.write_csv(paths["positions"], [{"ticker": "IOT"}], ["ticker"])

    def _patch_paths(self, stack: ExitStack, paths: dict[str, Path]) -> None:
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
            ("B2_RATE_LIMIT_STATE_PATH", paths["rate_limit_state"]),
        ):
            stack.enter_context(patch.object(b2, name, path))

    def test_rate_limit_stops_remaining_benchmark_probes(self) -> None:
        rate_limit = type("YFRateLimitError", (Exception,), {})
        ticker = Mock()
        ticker.history.side_effect = rate_limit("upstream text must not persist")
        with patch.object(b2.yf, "Ticker", return_value=ticker) as factory:
            rows, passed = b2.smoke_test()

        self.assertFalse(passed)
        factory.assert_called_once_with("QQQ")
        ticker.history.assert_called_once()
        self.assertEqual(rows[0]["error_code"], b2.RATE_LIMIT_CODE)
        self.assertEqual([row["status"] for row in rows], ["failed", "not_attempted", "not_attempted"])
        self.assertTrue(
            all("upstream text must not persist" not in str(row) for row in rows)
        )

    def test_same_day_circuit_allows_only_one_post_close_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "phase5r_b2_rate_limit_state.local.json"
            with patch.object(b2, "B2_RATE_LIMIT_STATE_PATH", state_path):
                b2.record_rate_limit(PRE_CLOSE)
                self.assertEqual(
                    b2.rate_limit_attempt_allowed(
                        datetime(2026, 8, 5, 12, 30, tzinfo=ET)
                    ),
                    (False, b2.RATE_LIMIT_COOLDOWN_CODE),
                )
                self.assertEqual(
                    b2.rate_limit_attempt_allowed(POST_CLOSE),
                    (True, "rate_limit_post_close_retry_available"),
                )
                b2.reserve_post_close_retry(POST_CLOSE)
                self.assertEqual(
                    b2.rate_limit_attempt_allowed(
                        datetime(2026, 8, 5, 18, 0, tzinfo=ET)
                    ),
                    (False, b2.RATE_LIMIT_COOLDOWN_CODE),
                )
                self.assertEqual(
                    b2.rate_limit_attempt_allowed(
                        datetime(2026, 8, 6, 8, 15, tzinfo=ET)
                    ),
                    (True, "rate_limit_state_expired"),
                )

    def test_main_persists_only_finite_rate_limit_audit_data(self) -> None:
        rate_limit = type("YFRateLimitError", (Exception,), {})
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_inputs(paths)
            ticker = Mock()
            ticker.history.side_effect = rate_limit("upstream text must not persist")
            full_retrieval = Mock(
                side_effect=AssertionError("full-universe retrieval must not run")
            )
            with ExitStack() as stack:
                self._patch_paths(stack, paths)
                stack.enter_context(patch.object(b2, "timestamp", return_value="2026-08-05T09:00:00-04:00"))
                stack.enter_context(patch.object(b2, "now_et", return_value=PRE_CLOSE))
                stack.enter_context(patch.object(b2.yf, "Ticker", return_value=ticker))
                stack.enter_context(
                    patch.object(b2, "retrieve_full_universe", full_retrieval)
                )
                result = b2.main()
                state = b2.load_rate_limit_state(PRE_CLOSE)[0]

            self.assertEqual(result, 1)
            full_retrieval.assert_not_called()
            ticker.history.assert_called_once()
            audit = b2.read_csv(paths["audit"])
            self.assertEqual(audit[0]["status"], "failed")
            self.assertIn("source_failure_code=yfinance_rate_limited", audit[0]["safety_notes"])
            self.assertNotIn("upstream text must not persist", "\n".join(row["safety_notes"] for row in audit))
            self.assertIsNotNone(state)
            self.assertEqual(state["source_failure_code"], b2.RATE_LIMIT_CODE)
            decision = paths["decision"].read_text(encoding="utf-8")
            self.assertIn("Source-failure classification: `yfinance_rate_limited`", decision)

    def test_active_circuit_does_not_touch_yfinance_before_post_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_inputs(paths)
            with ExitStack() as stack:
                self._patch_paths(stack, paths)
                stack.enter_context(patch.object(b2, "timestamp", return_value="2026-08-05T12:30:00-04:00"))
                stack.enter_context(patch.object(b2, "now_et", return_value=PRE_CLOSE))
                b2.record_rate_limit(PRE_CLOSE)
                factory = stack.enter_context(patch.object(b2.yf, "Ticker"))
                full_retrieval = stack.enter_context(
                    patch.object(b2, "retrieve_full_universe")
                )
                result = b2.main()

            self.assertEqual(result, 1)
            factory.assert_not_called()
            full_retrieval.assert_not_called()
            audit = b2.read_csv(paths["audit"])
            self.assertEqual(audit[0]["status"], "not_attempted")
            self.assertIn(
                "source_failure_code=yfinance_rate_limited_cooldown",
                audit[0]["safety_notes"],
            )


if __name__ == "__main__":
    unittest.main()
