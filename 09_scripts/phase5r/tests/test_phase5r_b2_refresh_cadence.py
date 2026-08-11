from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import run_phase5r_b2_full_universe_market_data as b2
import run_phase5r_daily_decision_pipeline as final_pipeline
import run_phase5r_daily_refresh as daily_refresh
import run_phase5r_daily_refresh_scheduler as refresh_scheduler


ET = ZoneInfo("America/New_York")
PRE_CLOSE = datetime(2026, 8, 5, 12, 30, tzinfo=ET)
CLOSE_BOUNDARY = datetime(2026, 8, 5, 16, 15, tzinfo=ET)
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


def _market_row(ticker: str, session: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "last_price": "100.0000",
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
        "market_session_date": session,
        "market_age_calendar_days": "1",
        "data_timestamp": f"{session}T20:15:00-04:00",
        "data_source": "yfinance_public_market_data",
        "data_quality_label": "ok",
    }


class B2RefreshCadenceTests(unittest.TestCase):
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
            "rate_limit_state": root / "00_project_control" / "run_logs" / "phase5r_b2_rate_limit_state.local.json",
        }

    def _write_coherent_snapshot(self, paths: dict[str, Path], session: str) -> None:
        seeds = [_seed(ticker) for ticker in b2.SMOKE_TICKERS]
        rows = [_market_row(ticker, session) for ticker in (*b2.SMOKE_TICKERS, "IOT")]
        by_ticker = {row["ticker"]: row for row in rows}
        b2.write_csv(paths["data"] / "phase5r_universe_seed.csv", seeds, list(seeds[0]))
        b2.write_csv(paths["positions"], [{"ticker": "IOT"}], ["ticker"])
        b2.write_csv(paths["snapshot"], rows, b2.MARKET_FIELDS)
        b2.write_csv(
            paths["quality"],
            [
                {
                    "ticker": row["ticker"],
                    "data_source": row["data_source"],
                    "data_quality_label": row["data_quality_label"],
                    "missing_fields": "",
                    "usable_for_scoring": "yes",
                    "notes": "read-only public row ready for scoring",
                }
                for row in rows
            ],
            b2.QUALITY_FIELDS,
        )
        candidates: list[dict[str, str]] = []
        for seed in seeds:
            market = by_ticker[seed["ticker"]]
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
            candidate.update({field: market[field] for field in b2.MARKET_FIELDS[1:]})
            candidate.update(
                {
                    "market_data_usable": "yes",
                    "candidate_note": "daily public data attached",
                }
            )
            candidates.append(candidate)
        b2.write_csv(paths["candidates"], candidates, b2.CANDIDATE_FIELDS)

    def _patch_b2_paths(self, stack: ExitStack, paths: dict[str, Path]) -> None:
        for name in (
            "ROOT",
            "DATA_DIR",
            "UNIVERSE_PATH",
            "LOCAL_POSITIONS_PATH",
            "SNAPSHOT_PATH",
            "QUALITY_PATH",
            "CANDIDATES_PATH",
            "AUDIT_PATH",
            "DECISION_PATH",
            "REPORT_PATH",
            "RUN_LOG",
            "B2_RATE_LIMIT_STATE_PATH",
        ):
            value = {
                "ROOT": paths["root"],
                "DATA_DIR": paths["data"],
                "UNIVERSE_PATH": paths["data"] / "phase5r_universe_seed.csv",
                "LOCAL_POSITIONS_PATH": paths["positions"],
                "SNAPSHOT_PATH": paths["snapshot"],
                "QUALITY_PATH": paths["quality"],
                "CANDIDATES_PATH": paths["candidates"],
                "AUDIT_PATH": paths["audit"],
                "DECISION_PATH": paths["decision"],
                "REPORT_PATH": paths["report"],
                "RUN_LOG": paths["run_log"],
                "B2_RATE_LIMIT_STATE_PATH": paths["rate_limit_state"],
            }[name]
            stack.enter_context(patch.object(b2, name, value))

    def test_preclose_reuse_keeps_current_local_snapshot_and_skips_yfinance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_coherent_snapshot(paths, "2026-08-04")
            prior = {
                name: paths[name].read_bytes()
                for name in ("snapshot", "quality", "candidates")
            }
            with ExitStack() as stack:
                self._patch_b2_paths(stack, paths)
                stack.enter_context(patch.object(b2, "now_et", return_value=PRE_CLOSE))
                ticker = stack.enter_context(patch.object(b2.yf, "Ticker"))
                download = stack.enter_context(patch.object(b2.yf, "download"))
                result = b2.main(["--reuse-validated-snapshot"])

            self.assertEqual(result, 0)
            ticker.assert_not_called()
            download.assert_not_called()
            for name, original in prior.items():
                self.assertEqual(paths[name].read_bytes(), original)
            audit = b2.read_csv(paths["audit"])
            self.assertEqual(audit[-1]["action"], "reuse_validated_market_snapshot")
            self.assertEqual(audit[-1]["status"], "complete")
            self.assertIn("public_source_called=no", audit[-1]["safety_notes"])

    def test_reuse_rejects_previous_close_at_current_close_boundary_without_yfinance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_coherent_snapshot(paths, "2026-08-04")
            prior = paths["snapshot"].read_bytes()
            with ExitStack() as stack:
                self._patch_b2_paths(stack, paths)
                stack.enter_context(
                    patch.object(b2, "now_et", return_value=CLOSE_BOUNDARY)
                )
                ticker = stack.enter_context(patch.object(b2.yf, "Ticker"))
                download = stack.enter_context(patch.object(b2.yf, "download"))
                result = b2.main(["--reuse-validated-snapshot"])

            self.assertEqual(result, 1)
            ticker.assert_not_called()
            download.assert_not_called()
            self.assertEqual(paths["snapshot"].read_bytes(), prior)
            audit = b2.read_csv(paths["audit"])
            self.assertIn(
                f"reuse_validation_code={b2.REUSE_STALE_SNAPSHOT_CODE}",
                audit[-1]["safety_notes"],
            )

    def test_scheduler_fetches_only_post_close_regular_session(self) -> None:
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(PRE_CLOSE, ["08:15", "12:30"]),
            refresh_scheduler.MARKET_SNAPSHOT_REUSE,
        )
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(
                POST_CLOSE, ["08:15", "12:30", "16:15", "17:45"]
            ),
            refresh_scheduler.MARKET_SNAPSHOT_FETCH,
        )
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(POST_CLOSE, ["08:15"]),
            refresh_scheduler.MARKET_SNAPSHOT_REUSE,
        )
        labor_day = datetime(2026, 9, 7, 17, 45, tzinfo=ET)
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(labor_day, ["17:45"]),
            refresh_scheduler.MARKET_SNAPSHOT_REUSE,
        )

    def test_scheduler_reuse_never_starts_shadow_or_a_second_child(self) -> None:
        scheduler_state: dict[str, object] = {
            "schema_version": "phase5r_daily_scheduler_state_v1",
            "dates": {},
        }
        refresh_state = {
            "schema_version": "phase5r_daily_refresh_state_v1",
            "outcome": "passed",
            "decision_created": True,
            "hard_failures": [],
            "soft_failures": [],
            "started_at": "2026-08-05T12:30:00-04:00",
            "completed_at": "2026-08-05T12:30:01-04:00",
        }

        def fake_read_json(path: Path, default: object) -> object:
            if path == refresh_scheduler.DAILY_REFRESH_STATE_PATH:
                return refresh_state
            return scheduler_state

        completed = refresh_scheduler.subprocess.CompletedProcess(["refresh"], 0)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    refresh_scheduler,
                    "load_active_state",
                    return_value={"operational_from": "2026-08-01"},
                )
            )
            stack.enter_context(
                patch.object(refresh_scheduler, "load_inhibit", return_value={"active": False})
            )
            stack.enter_context(patch.object(refresh_scheduler, "cycle_date", return_value="2026-08-05"))
            stack.enter_context(patch.object(refresh_scheduler, "now_et", return_value=PRE_CLOSE))
            stack.enter_context(
                patch.object(refresh_scheduler, "iso_now", return_value="2026-08-05T12:30:00-04:00")
            )
            stack.enter_context(patch.object(refresh_scheduler, "read_json", side_effect=fake_read_json))
            stack.enter_context(patch.object(refresh_scheduler, "atomic_write_json"))
            run = stack.enter_context(
                patch.object(refresh_scheduler.subprocess, "run", return_value=completed)
            )
            stack.enter_context(
                patch.object(refresh_scheduler.sys, "argv", ["daily_refresh_scheduler.py"])
            )
            result = refresh_scheduler.main()

        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 1)
        arguments = run.call_args.args[0]
        self.assertIn("--market-snapshot-mode", arguments)
        self.assertIn(refresh_scheduler.MARKET_SNAPSHOT_REUSE, arguments)

    def test_sec_only_runtime_marker_invokes_no_daily_or_shadow_path(self) -> None:
        """The existing launchd job can refresh SEC evidence without B2 or email."""

        completed = refresh_scheduler.subprocess.CompletedProcess(["sec"], 0)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {refresh_scheduler.SEC_REFRESH_ONLY_ENV: "1"},
                clear=True,
            ),
            patch.object(
                refresh_scheduler.subprocess,
                "run",
                return_value=completed,
            ) as run,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = refresh_scheduler.main()

        self.assertEqual(result, 0)
        run.assert_called_once_with(
            [refresh_scheduler.sys.executable, str(refresh_scheduler.SEC_EVIDENCE_REFRESH)],
            cwd=refresh_scheduler.ROOT,
            stdout=refresh_scheduler.subprocess.DEVNULL,
            stderr=refresh_scheduler.subprocess.DEVNULL,
            timeout=refresh_scheduler.SEC_REFRESH_TIMEOUT_SECONDS,
            check=False,
        )
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_refresh_pipeline_propagates_reuse_mode_only_to_b2(self) -> None:
        completed = daily_refresh.subprocess.CompletedProcess(["child"], 0)
        with patch.object(
            daily_refresh.subprocess, "run", return_value=completed
        ) as run:
            result = daily_refresh.run_step(
                "market_refresh",
                "run_phase5r_b2_full_universe_market_data.py",
                False,
                market_snapshot_mode=daily_refresh.MARKET_SNAPSHOT_REUSE,
            )

        self.assertEqual(result["outcome"], "passed")
        arguments = run.call_args.args[0]
        self.assertIn("--reuse-validated-snapshot", arguments)
        self.assertNotIn("--refresh", arguments)

    def test_final_pipeline_rejects_degraded_reuse_before_sender(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            refresh_state = Path(directory) / "refresh_state.json"
            refresh_state.write_text(
                json.dumps(
                    {
                        "schema_version": "phase5r_daily_refresh_state_v1",
                        "started_at": "2026-08-05T18:30:00-04:00",
                        "completed_at": "2026-08-05T18:30:01-04:00",
                        "outcome": "degraded_decision_created",
                        "decision_created": True,
                        "hard_failures": ["market_refresh"],
                        "soft_failures": [],
                    }
                ),
                encoding="utf-8",
            )
            completed = final_pipeline.subprocess.CompletedProcess(["refresh"], 0, "")
            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(final_pipeline, "DAILY_REFRESH_STATE_PATH", refresh_state)
                )
                stack.enter_context(
                    patch.object(
                        final_pipeline,
                        "ExclusiveFileLock",
                        return_value=nullcontext(),
                    )
                )
                stack.enter_context(patch.object(final_pipeline, "iso_now", return_value="2026-08-05T18:30:00-04:00"))
                stack.enter_context(patch.object(final_pipeline, "load_active_state"))
                stack.enter_context(
                    patch.object(final_pipeline, "load_inhibit", return_value={"active": False})
                )
                run = stack.enter_context(
                    patch.object(final_pipeline, "run_command", return_value=completed)
                )
                log = stack.enter_context(patch.object(final_pipeline, "log_daily_run"))
                result = final_pipeline.execute(send=True)

        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 1)
        self.assertIn("--market-snapshot-mode", run.call_args.args[0])
        self.assertIn("reuse_validated_snapshot", run.call_args.args[0])
        self.assertEqual(log.call_args.kwargs["reason"], "daily_refresh_not_fully_passed")


if __name__ == "__main__":
    unittest.main()
