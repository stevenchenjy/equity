from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, nullcontext, redirect_stderr, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_massive_b2_adapter as massive
import run_phase5r_b2_full_universe_market_data as b2
import run_phase5r_daily_decision_pipeline as final_pipeline
import run_phase5r_daily_refresh as daily_refresh
import run_phase5r_daily_refresh_scheduler as refresh_scheduler
import run_phase5r_daily_scheduler as decision_scheduler
import score_phase5r_b2_candidates as scoring


ET = ZoneInfo("America/New_York")
PRE_CLOSE = datetime(2026, 8, 5, 12, 30, tzinfo=ET)
CLOSE_BOUNDARY = datetime(2026, 8, 5, 16, 15, tzinfo=ET)
POST_CLOSE = datetime(2026, 8, 5, 17, 45, tzinfo=ET)
POST_CLOSE_RETRY = datetime(2026, 8, 5, 18, 15, tzinfo=ET)


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
        "data_source": b2.MASSIVE_DATA_SOURCE,
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
            }[name]
            stack.enter_context(patch.object(b2, name, value))

    def test_preclose_reuse_keeps_current_local_snapshot_and_skips_massive_client(self) -> None:
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
                factory = stack.enter_context(
                    patch.object(b2.MassiveBasicEODClient, "from_environment")
                )
                result = b2.main(["--reuse-validated-snapshot"])

            self.assertEqual(result, 0)
            factory.assert_not_called()
            for name, original in prior.items():
                self.assertEqual(paths[name].read_bytes(), original)
            audit = b2.read_csv(paths["audit"])
            self.assertEqual(audit[-1]["action"], "reuse_validated_market_snapshot")
            self.assertEqual(audit[-1]["status"], "complete")
            self.assertIn("public_source_called=no", audit[-1]["safety_notes"])

    def test_post_close_market_child_timeout_covers_bounded_import_budget(self) -> None:
        completed = daily_refresh.subprocess.CompletedProcess(["child"], 0)
        with patch.object(
            daily_refresh.subprocess, "run", return_value=completed
        ) as run:
            result = daily_refresh.run_step(
                "market_refresh",
                "run_phase5r_b2_full_universe_market_data.py",
                False,
                market_snapshot_mode=daily_refresh.MARKET_SNAPSHOT_FETCH,
            )

        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(daily_refresh.POST_CLOSE_MARKET_REFRESH_TIMEOUT_SECONDS, 480)
        self.assertEqual(refresh_scheduler.DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS, 900)
        self.assertGreaterEqual(
            daily_refresh.POST_CLOSE_MARKET_REFRESH_TIMEOUT_SECONDS,
            29 * massive.MASSIVE_MIN_REQUEST_INTERVAL_SECONDS,
        )
        self.assertEqual(
            run.call_args.kwargs["timeout"],
            daily_refresh.POST_CLOSE_MARKET_REFRESH_TIMEOUT_SECONDS,
        )

    def test_refresh_scheduler_rejects_stale_child_state(self) -> None:
        stale_state = {
            "cycle_date": "2026-08-05",
            "expected_market_session": "2026-08-05",
            "started_at": "2026-08-05T17:44:59-04:00",
            "steps": [{"name": "market_refresh", "exit_code": 0}],
        }
        self.assertFalse(
            refresh_scheduler._market_step_passed(
                stale_state,
                expected_cycle_date="2026-08-05",
                expected_market_session="2026-08-05",
                not_before="2026-08-05T17:45:00-04:00",
            )
        )

    def test_ambiguous_delivery_states_are_terminal(self) -> None:
        for summary in (
            "email_sent=unknown reason=smtp_exception_after_claim",
            "email_sent=false reason=existing_delivery_unknown",
            "email_sent=false reason=existing_send_claimed",
        ):
            with self.subTest(summary=summary):
                self.assertTrue(final_pipeline.delivery_status_is_unknown(summary))
        self.assertFalse(
            final_pipeline.delivery_status_is_unknown(
                "email_sent=false reason=existing_sent"
            )
        )

    def test_reuse_rejects_previous_close_at_current_close_boundary_without_massive_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            self._write_coherent_snapshot(paths, "2026-08-04")
            prior = paths["snapshot"].read_bytes()
            with ExitStack() as stack:
                self._patch_b2_paths(stack, paths)
                stack.enter_context(
                    patch.object(b2, "now_et", return_value=CLOSE_BOUNDARY)
                )
                factory = stack.enter_context(
                    patch.object(b2.MassiveBasicEODClient, "from_environment")
                )
                result = b2.main(["--reuse-validated-snapshot"])

            self.assertEqual(result, 1)
            factory.assert_not_called()
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
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(
                POST_CLOSE_RETRY,
                ["18:15"],
                market_ready=False,
            ),
            refresh_scheduler.MARKET_SNAPSHOT_FETCH,
        )
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(
                POST_CLOSE_RETRY,
                ["18:15"],
                market_ready=True,
            ),
            refresh_scheduler.MARKET_SNAPSHOT_REUSE,
        )
        labor_day = datetime(2026, 9, 7, 17, 45, tzinfo=ET)
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(labor_day, ["17:45"]),
            refresh_scheduler.MARKET_SNAPSHOT_REUSE,
        )

    def test_scheduler_reuse_starts_only_one_deterministic_child(self) -> None:
        scheduler_state: dict[str, object] = {
            "schema_version": "phase5r_daily_scheduler_state_v1",
            "dates": {},
        }

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
            stack.enter_context(patch.object(refresh_scheduler, "read_json", return_value=scheduler_state))
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
        self.assertEqual(
            run.call_args.kwargs["timeout"],
            refresh_scheduler.DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS,
        )

    def test_failed_post_close_refresh_never_starts_a_second_child(self) -> None:
        """A failed child reserves its slot and waits for the next retry slot."""

        scheduler_state: dict[str, object] = {
            "schema_version": "phase5r_daily_scheduler_state_v1",
            "dates": {},
        }
        refresh = refresh_scheduler.subprocess.CompletedProcess(["refresh"], 0)
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
            stack.enter_context(patch.object(refresh_scheduler, "now_et", return_value=POST_CLOSE))
            stack.enter_context(
                patch.object(refresh_scheduler, "iso_now", return_value="2026-08-05T17:45:00-04:00")
            )
            stack.enter_context(patch.object(refresh_scheduler, "read_json", return_value=scheduler_state))
            stack.enter_context(patch.object(refresh_scheduler, "atomic_write_json"))
            run = stack.enter_context(
                patch.object(refresh_scheduler.subprocess, "run", return_value=refresh)
            )
            stack.enter_context(
                patch.object(refresh_scheduler.sys, "argv", ["daily_refresh_scheduler.py"])
            )
            with redirect_stdout(io.StringIO()):
                result = refresh_scheduler.main()

        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn(str(refresh_scheduler.REFRESH_PIPELINE), command)
        date_state = scheduler_state["dates"]["2026-08-05"]
        self.assertIn(
            refresh_scheduler.POST_CLOSE_MARKET_SLOT,
            date_state["refresh_slots_completed"],
        )
        self.assertEqual(
            date_state["post_close_market_attempt_status"], "child_returned"
        )
        remaining = [
            slot
            for slot in refresh_scheduler.due_slots(POST_CLOSE)
            if slot not in set(date_state["refresh_slots_completed"])
        ]
        self.assertEqual(
            refresh_scheduler.market_snapshot_mode(POST_CLOSE, remaining),
            refresh_scheduler.MARKET_SNAPSHOT_REUSE,
        )

    def test_later_post_close_slot_retries_market_after_not_published(self) -> None:
        scheduler_state: dict[str, object] = {
            "schema_version": "phase5r_daily_scheduler_state_v1",
            "dates": {
                "2026-08-05": {
                    "refresh_slots_completed": [
                        "08:15",
                        "12:30",
                        "16:15",
                        "17:45",
                    ],
                    "post_close_market_ready": False,
                }
            },
        }
        refresh_state = {
            "outcome": "degraded_decision_created",
            "steps": [
                {"name": "market_refresh", "exit_code": 1},
            ],
        }
        completed = refresh_scheduler.subprocess.CompletedProcess(["refresh"], 1)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    refresh_scheduler,
                    "load_active_state",
                    return_value={"operational_from": "2026-08-01"},
                )
            )
            stack.enter_context(
                patch.object(
                    refresh_scheduler,
                    "load_inhibit",
                    return_value={"active": False},
                )
            )
            stack.enter_context(
                patch.object(
                    refresh_scheduler,
                    "cycle_date",
                    return_value="2026-08-05",
                )
            )
            stack.enter_context(
                patch.object(
                    refresh_scheduler,
                    "now_et",
                    return_value=POST_CLOSE_RETRY,
                )
            )
            stack.enter_context(
                patch.object(
                    refresh_scheduler,
                    "iso_now",
                    return_value="2026-08-05T18:15:00-04:00",
                )
            )
            stack.enter_context(
                patch.object(
                    refresh_scheduler,
                    "read_json",
                    side_effect=[scheduler_state, refresh_state],
                )
            )
            stack.enter_context(patch.object(refresh_scheduler, "atomic_write_json"))
            run = stack.enter_context(
                patch.object(
                    refresh_scheduler.subprocess,
                    "run",
                    return_value=completed,
                )
            )
            stack.enter_context(
                patch.object(
                    refresh_scheduler.sys,
                    "argv",
                    ["daily_refresh_scheduler.py"],
                )
            )
            with redirect_stdout(io.StringIO()):
                result = refresh_scheduler.main()

        self.assertEqual(result, 1)
        self.assertIn(
            refresh_scheduler.MARKET_SNAPSHOT_FETCH,
            run.call_args.args[0],
        )
        date_state = scheduler_state["dates"]["2026-08-05"]
        self.assertIn("18:15", date_state["refresh_slots_completed"])
        self.assertEqual(
            date_state["post_close_market_attempts"][-1]["status"],
            "market_not_ready",
        )

    def test_stale_preserved_candidate_is_never_scored_as_actionable(self) -> None:
        row = _seed("NVDA") | {
            key: value
            for key, value in _market_row("NVDA", "2026-08-04").items()
            if key != "ticker"
        }
        row.update(
            {"market_data_usable": "yes", "candidate_note": "daily public data attached"}
        )

        result = scoring.score_row(
            row, expected_market_session="2026-08-05"
        )

        self.assertEqual(result["action_label"], "insufficient_data")
        self.assertEqual(result["total_score"], "0.00")

    def test_sec_only_runtime_marker_invokes_no_daily_or_model_path(self) -> None:
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

    def test_full_reuse_runtime_marker_invokes_one_no_send_refresh(self) -> None:
        """The repair marker reuses local market data and cannot send email."""

        completed = refresh_scheduler.subprocess.CompletedProcess(["refresh"], 0)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {refresh_scheduler.FULL_REFRESH_REUSE_ONLY_ENV: "1"},
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
            [
                refresh_scheduler.sys.executable,
                str(refresh_scheduler.REFRESH_PIPELINE),
                "--run",
                "--market-snapshot-mode",
                refresh_scheduler.MARKET_SNAPSHOT_REUSE,
            ],
            cwd=refresh_scheduler.ROOT,
            stdout=refresh_scheduler.subprocess.DEVNULL,
            stderr=refresh_scheduler.subprocess.DEVNULL,
            timeout=refresh_scheduler.DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS,
            check=False,
        )
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_b2_auth_probe_constructs_client_without_network_and_is_mute(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {massive.MASSIVE_API_KEY_ENV: "offline-presence-canary"},
                clear=True,
            ),
            patch.object(
                b2.MassiveBasicEODClient,
                "fetch_daily_bars",
                side_effect=AssertionError("network path must not run"),
            ) as fetch,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = b2.main(["--massive-auth-presence-probe"])

        self.assertEqual(result, b2.MASSIVE_AUTH_PROBE_PRESENT_EXIT)
        fetch.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_b2_auth_probe_fails_closed_when_auth_is_absent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = b2.main(["--massive-auth-presence-probe"])
        self.assertEqual(result, b2.MASSIVE_AUTH_PROBE_ABSENT_EXIT)

    def test_massive_runtime_auth_presence_probe_reaches_b2_child_and_is_mute(self) -> None:
        """The launchd probe maps only fixed status from the no-network B2 child."""

        stdout = io.StringIO()
        stderr = io.StringIO()
        completed = [
            refresh_scheduler.subprocess.CompletedProcess(["b2-probe"], 0),
            refresh_scheduler.subprocess.CompletedProcess(["b2-probe"], 2),
        ]
        with (
            patch.dict(
                os.environ,
                {refresh_scheduler.MASSIVE_AUTH_PRESENCE_PROBE_ENV: "1"},
                clear=True,
            ),
            patch.object(
                refresh_scheduler.subprocess,
                "run",
                side_effect=completed,
            ) as run,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            present = refresh_scheduler.main()
            absent = refresh_scheduler.main()

        self.assertEqual(present, refresh_scheduler.MASSIVE_AUTH_PRESENCE_PRESENT_EXIT)
        self.assertEqual(absent, refresh_scheduler.MASSIVE_AUTH_PRESENCE_ABSENT_EXIT)
        self.assertEqual(run.call_count, 2)
        run.assert_called_with(
            [
                refresh_scheduler.sys.executable,
                str(refresh_scheduler.MASSIVE_B2_RUNNER),
                "--massive-auth-presence-probe",
            ],
            cwd=refresh_scheduler.ROOT,
            stdout=refresh_scheduler.subprocess.DEVNULL,
            stderr=refresh_scheduler.subprocess.DEVNULL,
            timeout=refresh_scheduler.MASSIVE_B2_PROBE_TIMEOUT_SECONDS,
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
                        "cycle_date": "2026-08-05",
                        "expected_market_session": "2026-08-05",
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
                stack.enter_context(
                    patch.object(
                        final_pipeline,
                        "cycle_date",
                        return_value="2026-08-05",
                    )
                )
                stack.enter_context(
                    patch.object(
                        final_pipeline,
                        "last_completed_market_session",
                        return_value=date(2026, 8, 5),
                    )
                )
                stack.enter_context(patch.object(final_pipeline, "load_active_state"))
                stack.enter_context(
                    patch.object(final_pipeline, "load_inhibit", return_value={"active": False})
                )
                run = stack.enter_context(
                    patch.object(final_pipeline, "run_command", return_value=completed)
                )
                log = stack.enter_context(patch.object(final_pipeline, "log_daily_run"))
                result = final_pipeline.execute(send=True)

        self.assertEqual(result, final_pipeline.REFRESH_NOT_READY_EXIT)
        run.assert_not_called()
        self.assertEqual(log.call_args.kwargs["reason"], "daily_refresh_not_fully_passed")

    def test_final_pipeline_sends_only_after_current_passed_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            refresh_state = Path(directory) / "refresh_state.json"
            refresh_state.write_text(
                json.dumps(
                    {
                        "schema_version": "phase5r_daily_refresh_state_v1",
                        "cycle_date": "2026-08-05",
                        "expected_market_session": "2026-08-05",
                        "started_at": "2026-08-05T18:20:00-04:00",
                        "completed_at": "2026-08-05T18:25:00-04:00",
                        "outcome": "passed",
                        "decision_created": True,
                        "hard_failures": [],
                        "soft_failures": [],
                    }
                ),
                encoding="utf-8",
            )
            sender = final_pipeline.subprocess.CompletedProcess(
                ["sender"],
                0,
                "email_sent=false reason=unchanged_daily_email_suppressed",
            )
            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(final_pipeline, "DAILY_REFRESH_STATE_PATH", refresh_state)
                )
                stack.enter_context(
                    patch.object(final_pipeline, "ExclusiveFileLock", return_value=nullcontext())
                )
                stack.enter_context(
                    patch.object(final_pipeline, "cycle_date", return_value="2026-08-05")
                )
                stack.enter_context(
                    patch.object(
                        final_pipeline,
                        "last_completed_market_session",
                        return_value=date(2026, 8, 5),
                    )
                )
                stack.enter_context(patch.object(final_pipeline, "load_active_state"))
                stack.enter_context(
                    patch.object(final_pipeline, "load_inhibit", return_value={"active": False})
                )
                run = stack.enter_context(
                    patch.object(final_pipeline, "run_command", return_value=sender)
                )
                clear = stack.enter_context(
                    patch.object(final_pipeline, "clear_automation_alert")
                )
                stack.enter_context(patch.object(final_pipeline, "log_daily_run"))
                with redirect_stdout(io.StringIO()):
                    result = final_pipeline.execute(send=True)

        self.assertEqual(result, 0)
        run.assert_called_once_with(
            [final_pipeline.sys.executable, str(final_pipeline.SENDER_SCRIPT), "--send"],
            timeout=90,
        )
        clear.assert_called_once_with(component="daily_decision")

    def test_decision_scheduler_wait_does_not_consume_send_attempt(self) -> None:
        scheduler_state: dict[str, object] = {
            "schema_version": "phase5r_daily_scheduler_state_v1",
            "dates": {},
        }
        waiting = decision_scheduler.subprocess.CompletedProcess(
            ["decision"],
            final_pipeline.REFRESH_NOT_READY_EXIT,
            stdout="daily_pipeline_outcome=waiting reason=daily_refresh_market_session_not_current",
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    decision_scheduler,
                    "load_active_state",
                    return_value={"operational_from": "2026-08-01"},
                )
            )
            stack.enter_context(
                patch.object(decision_scheduler, "load_inhibit", return_value={"active": False})
            )
            stack.enter_context(
                patch.object(decision_scheduler, "cycle_date", return_value="2026-08-05")
            )
            stack.enter_context(
                patch.object(
                    decision_scheduler,
                    "now_et",
                    return_value=datetime(2026, 8, 5, 18, 45, tzinfo=ET),
                )
            )
            stack.enter_context(
                patch.object(
                    decision_scheduler,
                    "iso_now",
                    return_value="2026-08-05T18:45:00-04:00",
                )
            )
            stack.enter_context(
                patch.object(decision_scheduler, "read_json", return_value=scheduler_state)
            )
            stack.enter_context(patch.object(decision_scheduler, "atomic_write_json"))
            stack.enter_context(
                patch.object(decision_scheduler.subprocess, "run", return_value=waiting)
            )
            alert = stack.enter_context(
                patch.object(decision_scheduler, "publish_automation_alert")
            )
            stack.enter_context(
                patch.object(decision_scheduler.sys, "argv", ["daily_scheduler.py"])
            )
            with redirect_stdout(io.StringIO()):
                result = decision_scheduler.main()

        self.assertEqual(result, 0)
        date_state = scheduler_state["dates"]["2026-08-05"]
        self.assertNotIn("decision_attempts", date_state)
        self.assertEqual(date_state["decision_refresh_waits"], 1)
        alert.assert_not_called()

    def test_decision_scheduler_publishes_terminal_alert_after_deadline(self) -> None:
        scheduler_state: dict[str, object] = {
            "schema_version": "phase5r_daily_scheduler_state_v1",
            "dates": {},
        }
        waiting = decision_scheduler.subprocess.CompletedProcess(
            ["decision"],
            final_pipeline.REFRESH_NOT_READY_EXIT,
            stdout="daily_pipeline_outcome=waiting reason=daily_refresh_not_fully_passed",
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    decision_scheduler,
                    "load_active_state",
                    return_value={"operational_from": "2026-08-01"},
                )
            )
            stack.enter_context(
                patch.object(decision_scheduler, "load_inhibit", return_value={"active": False})
            )
            stack.enter_context(
                patch.object(decision_scheduler, "cycle_date", return_value="2026-08-05")
            )
            stack.enter_context(
                patch.object(
                    decision_scheduler,
                    "now_et",
                    return_value=datetime(2026, 8, 5, 20, 0, tzinfo=ET),
                )
            )
            stack.enter_context(
                patch.object(
                    decision_scheduler,
                    "iso_now",
                    return_value="2026-08-05T20:00:00-04:00",
                )
            )
            stack.enter_context(
                patch.object(decision_scheduler, "read_json", return_value=scheduler_state)
            )
            stack.enter_context(patch.object(decision_scheduler, "atomic_write_json"))
            stack.enter_context(
                patch.object(decision_scheduler.subprocess, "run", return_value=waiting)
            )
            alert = stack.enter_context(
                patch.object(decision_scheduler, "publish_automation_alert")
            )
            stack.enter_context(
                patch.object(decision_scheduler.sys, "argv", ["daily_scheduler.py"])
            )
            with redirect_stdout(io.StringIO()):
                result = decision_scheduler.main()

        self.assertEqual(result, 0)
        date_state = scheduler_state["dates"]["2026-08-05"]
        self.assertTrue(date_state["decision_terminal_failure"])
        self.assertNotIn("decision_attempts", date_state)
        alert.assert_called_once_with(
            component="daily_decision",
            reason="daily_decision_refresh_deadline_exhausted",
        )


if __name__ == "__main__":
    unittest.main()
