"""The aggregate backup-host allowance must fit existing absolute windows."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from active_config import load_active_config
from daily_common import ET
from delivery_schedule import active_delivery_window
import run_daily_refresh as refresh
import run_daily_refresh_scheduler as scheduler
import run_runtime_scheduler as runtime
import short_assessment as short


DAY = datetime(2026, 11, 23, tzinfo=ET)


class BackupHostCapacityTests(unittest.TestCase):
    def test_only_aggregate_capacity_expands_and_parent_preserves_reporting_margin(self):
        self.assertEqual(refresh.FULL_REFRESH_MAX_SECONDS, 1260)
        self.assertEqual(scheduler.DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS, 1320)
        self.assertEqual(refresh.FINAL_REPORT_RESERVE_SECONDS, 30)
        self.assertGreater(scheduler.DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS,
                           refresh.FULL_REFRESH_MAX_SECONDS + refresh.FINAL_REPORT_RESERVE_SECONDS)
        self.assertEqual(refresh.DEFAULT_CHILD_TIMEOUT_SECONDS, 240)
        self.assertEqual(refresh.DAILY_DECISION_TIMEOUT_SECONDS, 360)
        self.assertEqual(refresh.EOD_MARKET_REFRESH_TIMEOUT_SECONDS, 600)
        self.assertEqual(refresh.MARKET_DISCOVERY_TIMEOUT_SECONDS, 360)
        self.assertEqual(refresh.SWING_CANDIDATE_HISTORY_TIMEOUT_SECONDS, 210)
        self.assertEqual(refresh.CAPITAL_ESCALATION_TIMEOUT_SECONDS, 900)
        self.assertEqual(scheduler.SCHEDULED_NEWS_ALLOWANCE_SECONDS, 170)
        self.assertEqual(runtime.NORMAL_REFRESH_GIT_PREFLIGHT_SECONDS, 240)
        self.assertEqual(short.MAX_DURATION, timedelta(minutes=10))
        self.assertEqual(short.SLOT_GRACE, timedelta(minutes=15))
        config = load_active_config(SCRIPT_DIR.parents[1] / "00_project_control/active_production_config.json")
        self.assertEqual(config["workflow"]["objective_research_max_tickers"], 10)

    def test_child_limits_and_remaining_deadline_still_bound_real_stage_invocation(self):
        complete = subprocess.CompletedProcess([], 0)
        with patch.object(refresh, "run_stage", return_value=complete) as child, \
                patch("decision_dependencies.observe", return_value=None), \
                patch("decision_dependencies.record_attempt"), patch.object(refresh, "atomic_write_json"):
            for name, script, remaining, expected in (
                    ("research_opportunity_intake", "intake.py", None, 240),
                    ("daily_decision", "composer.py", None, 360),
                    ("daily_decision", "composer.py", 45, 45)):
                with self.subTest(name=name, remaining=remaining):
                    result = refresh.run_step(name, script, True,
                        market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE,
                        maximum_child_seconds=remaining)
                    self.assertEqual(result["exit_code"], 0)
                    self.assertEqual(child.call_args.kwargs["timeout"], expected)

    def test_nominal_nine_and_thirteen_thirty_fit_with_seventy_second_margin(self):
        lookahead = (scheduler.DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS
                     + scheduler.SCHEDULED_NEWS_ALLOWANCE_SECONDS
                     + runtime.NORMAL_REFRESH_GIT_PREFLIGHT_SECONDS)
        self.assertEqual(lookahead, 1730)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for hour, minute, protected_hour, protected_minute in ((9, 0, 9, 30), (13, 30, 14, 0)):
                current = DAY.replace(hour=hour, minute=minute)
                protected = DAY.replace(hour=protected_hour, minute=protected_minute)
                with self.subTest(current=current):
                    self.assertEqual(protected - current - timedelta(seconds=lookahead), timedelta(seconds=70))
                    self.assertFalse(runtime._defer_normal_refresh(root, current=current, phase="before_runtime_lock"))
                    self.assertFalse(runtime._defer_normal_refresh(root, current=current, phase="after_runtime_lock"))
                    self.assertFalse(runtime._defer_normal_refresh(root, current=current, phase="after_git_preflight",
                                                                  include_git_budget=False))
            self.assertFalse((root / runtime.SHORT_DEFERRAL_RELATIVE_PATH).exists())

    def test_actual_late_arrival_defers_without_consuming_refresh_or_running_pipeline(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            state = root / "00_project_control/run_logs/daily_scheduler_state.local.json"
            state.parent.mkdir(parents=True)
            original = b'{"refresh_slots_completed":["08:00"]}\n'
            state.write_bytes(original)
            for hour, minute, slot in ((9, 0, "09:30"), (13, 30, "14:00")):
                nominal = DAY.replace(hour=hour, minute=minute)
                self.assertFalse(runtime._defer_normal_refresh(root, current=nominal + timedelta(seconds=70),
                                                              phase="after_runtime_lock"))
                self.assertTrue(runtime._defer_normal_refresh(root,
                    current=nominal + timedelta(seconds=70, microseconds=1), phase="after_runtime_lock"))
                receipt = json.loads((root / runtime.SHORT_DEFERRAL_RELATIVE_PATH).read_text())
                self.assertEqual(receipt["slot"], slot)
                for field in ("refresh_slot_consumed", "pipeline_invoked", "email_attempted",
                              "runtime_execution_authorized"):
                    self.assertIs(receipt[field], False)
                self.assertEqual(state.read_bytes(), original)

    def test_fourteen_short_keeps_priority_and_early_close_does_not_invent_a_slot(self):
        for clock in ((14, 0), (14, 15), (14, 24)):
            current = DAY.replace(hour=clock[0], minute=clock[1])
            conflict = scheduler.short_window_conflict(current)
            self.assertEqual(conflict["slot"], "14:00")
            self.assertEqual(datetime.fromisoformat(conflict["protected_until"]), DAY.replace(hour=14, minute=25))
        self.assertIsNone(scheduler.short_window_conflict(DAY.replace(hour=14, minute=25)))
        self.assertIsNone(scheduler.short_window_conflict(DAY.replace(day=27, hour=14)))
        self.assertIsNone(scheduler.short_window_conflict(DAY.replace(day=26, hour=9, minute=30)))

    def test_long_compute_does_not_extend_existing_absolute_delivery_windows(self):
        notifications = load_active_config(SCRIPT_DIR.parents[1] / "00_project_control/active_production_config.json")["notifications"]
        self.assertEqual(notifications["delivery_windows_et"], [
            {"id": "morning", "start": "09:30", "end": "10:30", "refresh_not_before": "08:00"},
            {"id": "afternoon", "start": "14:30", "end": "15:05", "refresh_not_before": "13:30"}])
        self.assertEqual(active_delivery_window(notifications, DAY.replace(hour=15, minute=5))["id"], "afternoon")
        for current in (DAY.replace(hour=10, minute=31), DAY.replace(hour=15, minute=6),
                        DAY.replace(hour=20)):
            self.assertIsNone(active_delivery_window(notifications, current))


if __name__ == "__main__":
    unittest.main()
