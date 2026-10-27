"""Interrupted downstream work must not refetch admitted market evidence."""
import copy
import io
import hashlib
import json
import subprocess
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import market_admission as admission
import market_backup
import run_daily_refresh as refresh
import run_daily_refresh_scheduler as scheduler
import run_full_universe_market_data as market
import bounded_refresh_process as processes
import test_refresh_cadence as fixtures

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 26, 9, 10, tzinfo=ET)
STAGE = {"name": "market_refresh", "started_at": "2026-10-26T08:01:00-04:00",
         "completed_at": "2026-10-26T08:07:00-04:00", "exit_code": 0}


class MarketRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixture = fixtures.B2RefreshCadenceTests()
        paths = fixture._paths(self.root)
        fixture._write_coherent_snapshot(paths, "2026-10-23")
        self.paths = paths
        tickers = [*sorted(market.APPROVED_CANDIDATE_TICKERS), "IOT"]
        end = date(2026, 10, 23)
        bars = [{"session_date": str(day), "open": 100., "high": 101., "low": 98., "close": 100., "volume": 100000.}
                for day in market_backup.sessions(end-timedelta(weeks=52), end)]
        bundle = {"schema_version": market_backup.SCHEMA, "price_basis": "unadjusted",
                  "data_source": market_backup.PRIMARY, "market_session": str(end),
                  "generated_at": "2026-10-26T08:06:00-04:00",
                  "tickers": {ticker: {"source_url": "https://api.massive.com/v2/aggs/"+ticker, "bars": bars} for ticker in tickers}}
        self.raw = self.root / market_backup.REL / "responses/original.json"
        self.raw.parent.mkdir(parents=True, exist_ok=True)
        self.raw.write_bytes(b'{"retained_original_observation": true}')
        bundle["observations"] = [{"path": str(self.raw.relative_to(self.root)),
                                   "sha256": hashlib.sha256(self.raw.read_bytes()).hexdigest()}]
        market_backup.publish(self.root, {paths["snapshot"]: paths["snapshot"].read_bytes()}, bundle, paths["snapshot"])

    def capture(self):
        return admission.capture(self.root, current=datetime.fromisoformat(STAGE["completed_at"]), stage=STAGE)

    def test_passed_market_retained_independently_of_incomplete_research(self):
        proof = self.capture()
        state = self.root / "00_project_control/run_logs/daily_refresh_state.local.json"
        state.write_text(json.dumps({"outcome": "in_progress", "running_stage": "research_opportunity_objective"}))
        self.assertEqual(admission.current_admission(self.root, current=NOW), proof)
        archive = json.loads((self.root / proof["receipt_path"]).read_text())
        self.assertFalse(archive["research_passed"])
        self.assertFalse(archive["publication_authorized"])

    def test_missing_corrupt_conflicting_or_mutated_bound_data_is_rejected(self):
        self.capture()
        for path in (self.paths["snapshot"], self.paths["quality"], self.paths["candidates"],
                     self.root / market_backup.CURRENT):
            raw = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(raw+b"\n")
                self.assertIsNone(admission.current_admission(self.root, current=NOW))
                path.write_bytes(raw)
                path.unlink()
                self.assertIsNone(admission.current_admission(self.root, current=NOW))
                path.write_bytes(raw)
        self.assertIsNotNone(admission.current_admission(self.root, current=NOW))

    def test_new_required_session_and_changed_held_scope_need_new_admission(self):
        self.capture()
        self.assertIsNone(admission.current_admission(self.root, current=NOW.replace(hour=16, minute=16)))
        self.paths["positions"].write_text("ticker\nJPM\n")
        self.assertIsNone(admission.current_admission(self.root, current=NOW))

    def test_retained_raw_source_or_history_corruption_fails(self):
        proof = self.capture()
        receipt = json.loads((self.root / proof["receipt_path"]).read_text())
        history = next(self.root / path for path in receipt["source_hashes"] if "/history/" in path)
        raw = self.raw.read_bytes()
        self.raw.write_bytes(raw+b" ")
        self.assertIsNone(admission.current_admission(self.root, current=NOW))
        self.raw.write_bytes(raw)
        self.assertIsNotNone(admission.current_admission(self.root, current=NOW))
        history.write_bytes(history.read_bytes()+b"\n")
        self.assertIsNone(admission.current_admission(self.root, current=NOW))

    def test_pre_attempt_or_future_receipts_cannot_prove_current_attempt(self):
        self.capture()
        self.assertIsNone(admission.current_admission(self.root, current=NOW, not_before="2026-10-26T08:02:00-04:00"))
        self.assertIsNone(admission.current_admission(self.root, current=NOW.replace(hour=7)))

    def test_market_proof_persisted_before_next_stage_can_die(self):
        progress = {"steps": []}
        result = {**STAGE, "allowed_to_fail": False}
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh, "run_step", return_value=result):
            refresh._progress_step(progress, ("market_refresh", "market.py", False), refresh.MARKET_SNAPSHOT_FETCH)
        self.assertIsNotNone(admission.current_admission(self.root, current=NOW))
        saved = json.loads((self.root / refresh.PROGRESS_REL).read_text())
        self.assertEqual(saved["steps"][0]["exit_code"], 0)
        self.assertEqual(saved["outcome"], "in_progress")

    def test_actual_scheduler_reuses_after_downstream_timeout_and_rejects_stale_ready_flag(self):
        self.capture()
        scheduler_state_path = self.root / "scheduler.json"
        full_state_path = self.root / "full-refresh.json"
        initial = {"schema_version": "phase5r_daily_scheduler_state_v1", "dates": {
            "2026-10-26": {"refresh_slots_completed": ["08:00"], "eod_publication_market_ready": True,
                           "eod_publication_market_session": "2026-10-23"}}}
        scheduler_state_path.write_text(json.dumps(initial))
        # The latest final state predates the failed attempt; a valid market
        # receipt remains separate from this incomplete research/publication.
        full_state_path.write_text(json.dumps({"cycle_date": "2026-10-26", "expected_market_session": "2026-10-23",
            "started_at": "2026-10-26T08:00:00-04:00", "outcome": "failed"}))
        progress_path = self.root / refresh.PROGRESS_REL
        progress_path.write_text(json.dumps({"cycle_date": "2026-10-26", "expected_market_session": "2026-10-23",
            "started_at": "2026-10-26T08:30:03-04:00", "outcome": "in_progress",
            "running_stage": "research_opportunity_objective", "steps": [{"name": "market_refresh", "exit_code": 0}]}))
        with ExitStack() as stack:
            stack.enter_context(patch.object(scheduler, "ROOT", self.root))
            stack.enter_context(patch.object(scheduler, "DAILY_SCHEDULER_STATE_PATH", scheduler_state_path))
            stack.enter_context(patch.object(scheduler, "DAILY_REFRESH_STATE_PATH", full_state_path))
            stack.enter_context(patch.object(scheduler, "load_active_state", return_value={"operational_from": "2026-10-01"}))
            stack.enter_context(patch.object(scheduler, "load_inhibit", return_value={"active": False}))
            stack.enter_context(patch.object(scheduler, "load_active_config", return_value={"notifications": {}}))
            stack.enter_context(patch.object(scheduler, "publish_automation_alert"))
            clock = stack.enter_context(patch.object(scheduler, "now_et", return_value=NOW.replace(hour=8, minute=30)))
            stack.enter_context(patch.object(scheduler, "cycle_date", return_value="2026-10-26"))
            stack.enter_context(patch.object(scheduler, "iso_now", side_effect=lambda: clock.return_value.isoformat()))
            stack.enter_context(patch("news_schedule.run_due_news_checks", return_value={"outcome": "not_due"}))
            stack.enter_context(patch.object(scheduler.sys, "argv", ["scheduler"]))
            def timeout(mode, **kwargs):
                clock.return_value = clock.return_value + timedelta(minutes=1)
                return subprocess.CompletedProcess([], 124)
            child = stack.enter_context(patch.object(scheduler, "_run_refresh_pipeline", side_effect=timeout))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(scheduler.main(), 124)
            child.assert_called_once_with(scheduler.MARKET_SNAPSHOT_REUSE, refresh_public=True)
            observed = json.loads(scheduler_state_path.read_text())["dates"]["2026-10-26"]
            self.assertFalse(observed["refresh_fully_passed"])
            interrupted = json.loads(progress_path.read_text())
            self.assertEqual(interrupted["outcome"], "parent_timed_out")
            self.assertEqual(interrupted["running_stage"], "research_opportunity_objective")
            self.assertTrue(interrupted["owned_process_group_terminated"])
            clock.return_value = NOW.replace(hour=9, minute=0)
            child.reset_mock()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(scheduler.main(), 124)
            child.assert_called_once_with(scheduler.MARKET_SNAPSHOT_REUSE, refresh_public=True)
            # A stale true flag is never permission to reuse corrupt bytes.
            self.paths["snapshot"].write_bytes(self.paths["snapshot"].read_bytes()+b"\n")
            clock.return_value = NOW.replace(hour=9, minute=45)
            child.reset_mock()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(scheduler.main(), 124)
            child.assert_called_once_with(scheduler.MARKET_SNAPSHOT_FETCH, refresh_public=True)


class SchedulingRecoveryTests(unittest.TestCase):
    def test_scheduled_public_work_is_independent_of_eod_reuse_and_operator_offline(self):
        for name, script in (("market_refresh", "market.py"), ("earnings_event_discovery", "calendar.py"),
                             ("research_opportunity_objective", "objective.py"), ("market_discovery", "discovery.py")):
            with self.subTest(stage=name), patch.object(refresh, "run_stage", return_value=subprocess.CompletedProcess([], 0)) as child, \
                 patch("decision_dependencies.observe", return_value=None), patch("decision_dependencies.record_attempt"), \
                 patch.object(refresh, "atomic_write_json"):
                refresh.run_step(name, script, True, market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE, refresh_public=True)
                arguments = child.call_args.args[0]
                if name == "market_refresh":
                    self.assertIn("--reuse-validated-snapshot", arguments)
                    self.assertNotIn("--refresh", arguments)
                else:
                    self.assertIn("--refresh", arguments)
                child.reset_mock()
                refresh.run_step(name, script, True, market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE)
                self.assertNotIn("--refresh", child.call_args.args[0])

    def test_short_window_protection_preserves_grace_budget_and_early_close(self):
        for clock in ("13:43", "14:00", "14:11", "14:24"):
            hour, minute = map(int, clock.split(":"))
            self.assertEqual(scheduler.short_window_conflict(NOW.replace(hour=hour, minute=minute))["slot"], "14:00")
        self.assertIsNone(scheduler.short_window_conflict(NOW.replace(hour=14, minute=25)))
        self.assertIsNone(scheduler.short_window_conflict(NOW.replace(day=25, hour=14)))  # Sunday
        self.assertIsNone(scheduler.short_window_conflict(datetime(2026, 11, 27, 14, tzinfo=ET)))  # 13:00 close
        self.assertIsNone(scheduler.short_window_conflict(datetime(2026, 11, 26, 9, 30, tzinfo=ET)))

    def test_deferred_refresh_does_not_poll_reserve_or_spawn(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.object(scheduler, "ROOT", root))
            stack.enter_context(patch.object(scheduler, "load_active_state", return_value={"operational_from": "2026-10-01"}))
            stack.enter_context(patch.object(scheduler, "load_inhibit", return_value={"active": False}))
            stack.enter_context(patch.object(scheduler, "cycle_date", return_value="2026-10-26"))
            stack.enter_context(patch.object(scheduler, "now_et", return_value=NOW.replace(hour=14, minute=11)))
            stack.enter_context(patch.object(scheduler, "load_active_config", return_value={"notifications": {
                "delivery_assessment_effective_from": "2026-10-22", "short_assessment_slots_et": ["09:30", "11:00", "12:30", "14:00", "15:30"]}}))
            stack.enter_context(patch.object(scheduler.sys, "argv", ["scheduler"]))
            news = stack.enter_context(patch("news_schedule.run_due_news_checks"))
            child = stack.enter_context(patch.object(scheduler, "_run_refresh_pipeline"))
            state = stack.enter_context(patch.object(scheduler, "read_json"))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(scheduler.main(), 0)
            news.assert_not_called()
            child.assert_not_called()
            state.assert_not_called()
            receipt = json.loads((root / "00_project_control/run_logs/daily_refresh_deferral.local.json").read_text())
            self.assertFalse(receipt["refresh_slot_consumed"])

    def test_required_stage_budget_exhaustion_is_explicit_failed_not_skipped_pass(self):
        with patch.object(refresh, "run_step") as child, patch.object(refresh, "time") as clock, \
             patch.object(refresh, "iso_now", return_value=NOW.isoformat()):
            clock.monotonic.return_value = 20
            row = refresh._progress_step(None, ("daily_decision", "decision.py", False),
                                         refresh.MARKET_SNAPSHOT_REUSE, deadline=10)
        child.assert_not_called()
        self.assertEqual(row["exit_code"], 124)
        self.assertEqual(row["outcome"], "not_run_budget_exhausted")
        self.assertFalse(row["allowed_to_fail"])

    def test_news_duration_rechecks_actual_clock_before_reserving_refresh(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.object(scheduler, "ROOT", root))
            stack.enter_context(patch.object(scheduler, "load_active_state", return_value={"operational_from": "2026-10-01"}))
            stack.enter_context(patch.object(scheduler, "load_inhibit", return_value={"active": False}))
            stack.enter_context(patch.object(scheduler, "cycle_date", return_value="2026-10-26"))
            stack.enter_context(patch.object(scheduler, "now_et", side_effect=[NOW.replace(hour=9, minute=9), NOW.replace(hour=9, minute=13)]))
            stack.enter_context(patch.object(scheduler, "load_active_config", return_value={"notifications": {
                "delivery_assessment_effective_from": "2026-10-22", "short_assessment_slots_et": ["09:30", "11:00", "12:30", "14:00", "15:30"]}}))
            stack.enter_context(patch.object(scheduler.sys, "argv", ["scheduler"]))
            news = stack.enter_context(patch("news_schedule.run_due_news_checks", return_value={"outcome": "passed"}))
            child = stack.enter_context(patch.object(scheduler, "_run_refresh_pipeline"))
            state = stack.enter_context(patch.object(scheduler, "read_json"))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(scheduler.main(), 0)
            news.assert_called_once()
            child.assert_not_called()
            state.assert_not_called()

    def test_timeout_terminates_owned_grandchild_as_well_as_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "orphan-mutation"
            launched = root / "launched"
            script = root / "pipeline.py"
            child_code = "import time,pathlib; time.sleep(.7); pathlib.Path("+repr(str(marker))+").write_text('unexpected')"
            # A separate stage process group inside the same pipeline session
            # must also be terminated by the enclosing scheduler deadline.
            script.write_text("import subprocess,sys,time,pathlib\nsubprocess.Popen([sys.executable,'-c',"+repr(child_code)+"],process_group=0)\npathlib.Path("+repr(str(launched))+").write_text('spawned')\ntime.sleep(30)\n")
            independent_marker = root / "independent-job-survived"
            independent = subprocess.Popen([scheduler.sys.executable, "-c",
                "import time,pathlib; time.sleep(.5); pathlib.Path("+repr(str(independent_marker))+").write_text('independent')"],
                start_new_session=True)
            try:
                with patch.object(scheduler, "ROOT", root), patch.object(scheduler, "REFRESH_PIPELINE", script), \
                     patch.object(scheduler, "DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS", .3):
                    completed = scheduler._run_refresh_pipeline(scheduler.MARKET_SNAPSHOT_REUSE)
                self.assertEqual(independent.wait(timeout=3), 0)
            finally:
                if independent.poll() is None:
                    independent.kill()
                    independent.wait()
            self.assertEqual(completed.returncode, 124)
            self.assertTrue(launched.exists())
            time.sleep(.8)
            self.assertFalse(marker.exists())
            self.assertTrue(independent_marker.exists())

    def test_stage_timeout_cannot_leave_a_grandchild_mutating_after_next_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "orphan-mutation"
            launched = root / "launched"
            child_code = "import time,pathlib; time.sleep(.7); pathlib.Path("+repr(str(marker))+").write_text('unexpected')"
            command = [scheduler.sys.executable, "-c", "import subprocess,sys,time,pathlib; subprocess.Popen([sys.executable,'-c',"+repr(child_code)+"]); pathlib.Path("+repr(str(launched))+").write_text('spawned'); time.sleep(30)"]
            with self.assertRaises(subprocess.TimeoutExpired):
                processes.run_stage(command, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=.3)
            self.assertTrue(launched.exists())
            # The full parent may finish normally after a failed advisory
            # stage. Its stage descendants must already be gone at this point.
            time.sleep(.8)
            self.assertFalse(marker.exists())

    def test_pipeline_interrupt_cleans_owned_groups_before_releasing_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "interrupt-orphan"
            script = root / "pipeline.py"
            child_code = "import time,pathlib; time.sleep(.7); pathlib.Path("+repr(str(marker))+").write_text('unexpected')"
            script.write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',"+repr(child_code)+"],process_group=0)\ntime.sleep(30)\n")
            def interrupt(*args):
                time.sleep(.3)
                raise KeyboardInterrupt()
            with patch.object(scheduler, "ROOT", root), patch.object(scheduler, "REFRESH_PIPELINE", script), \
                 patch.object(processes, "wait_unreaped", side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    scheduler._run_refresh_pipeline(scheduler.MARKET_SNAPSHOT_REUSE)
            time.sleep(.8)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
