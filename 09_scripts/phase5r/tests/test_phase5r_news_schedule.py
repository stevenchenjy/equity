from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_news_schedule as schedule
import run_phase5r_daily_refresh_scheduler as refresh_scheduler


class OfficialNewsScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "news-state.json"
        patcher = patch.object(schedule, "STATE_PATH", self.state_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def moment(self, clock: str, day: str = "2026-09-21") -> datetime:
        return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=ZoneInfo("America/New_York"))

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def news_calls(self, child) -> list:
        return [call for call in child.call_args_list if str(schedule.SCRIPT) in call.args[0]]

    def test_morning_success_does_not_consume_afternoon_or_evening_news(self) -> None:
        with patch.object(schedule.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as child:
            morning = schedule.run_due_news_checks(self.moment("11:30"))
            repeated = schedule.run_due_news_checks(self.moment("12:00"))
            afternoon = schedule.run_due_news_checks(self.moment("16:45"))
            evening = schedule.run_due_news_checks(self.moment("20:15"))
        self.assertEqual(morning["covered_slots"], ["08:15", "11:15"])
        self.assertEqual(repeated["outcome"], "not_due")
        self.assertEqual(afternoon["covered_slots"], ["16:45"])
        self.assertEqual(evening["covered_slots"], ["20:15"])
        self.assertEqual(len(self.news_calls(child)), 3)

    def test_late_wakeup_coalesces_all_missed_slots_into_one_attempt(self) -> None:
        def reserved_before_network(command, **_kwargs):
            if str(schedule.SCRIPT) not in command:
                return SimpleNamespace(returncode=0)
            today = self.state()["dates"]["2026-09-21"]
            self.assertEqual(today["last_outcome"], "attempt_reserved")
            self.assertEqual(today["attempted_slots"], list(schedule.SLOTS))
            return SimpleNamespace(returncode=0)

        with patch.object(schedule.subprocess, "run", side_effect=reserved_before_network) as child:
            result = schedule.run_due_news_checks(self.moment("23:00"))
            duplicate = schedule.run_due_news_checks(self.moment("23:15"))
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(duplicate["outcome"], "not_due")
        self.assertEqual(len(self.news_calls(child)), 1)

    def test_timeout_is_not_success_and_waits_for_next_bounded_slot(self) -> None:
        with patch.object(schedule.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 150)) as child:
            failed = schedule.run_due_news_checks(self.moment("08:15"))
            repeated = schedule.run_due_news_checks(self.moment("08:30"))
        self.assertEqual(failed["outcome"], "degraded")
        self.assertEqual(failed["exit_code"], 124)
        self.assertEqual(repeated["outcome"], "not_due")
        self.assertEqual(len(self.news_calls(child)), 1)
        self.assertNotIn("last_success_at", self.state()["dates"]["2026-09-21"])
        with patch.object(schedule.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            recovered = schedule.run_due_news_checks(self.moment("11:15"))
        self.assertEqual(recovered["covered_slots"], ["11:15"])
        self.assertEqual(recovered["outcome"], "passed")

    def test_process_crash_leaves_reservation_and_cannot_create_retry_storm(self) -> None:
        with patch.object(schedule.subprocess, "run", side_effect=SystemExit("simulated process termination")):
            with self.assertRaises(SystemExit):
                schedule.run_due_news_checks(self.moment("11:15"))
        today = self.state()["dates"]["2026-09-21"]
        self.assertEqual(today["last_outcome"], "attempt_reserved")
        with patch.object(schedule.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as child:
            no_retry = schedule.run_due_news_checks(self.moment("11:30"))
            recovered = schedule.run_due_news_checks(self.moment("16:45"))
        self.assertEqual(no_retry["outcome"], "not_due")
        self.assertEqual(recovered["outcome"], "passed")
        self.assertEqual(len(self.news_calls(child)), 1)

    def test_nonzero_child_does_not_overwrite_last_success_and_next_day_starts_fresh(self) -> None:
        with patch.object(schedule.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            schedule.run_due_news_checks(self.moment("08:15"))
        success_at = self.state()["dates"]["2026-09-21"]["last_success_at"]
        with patch.object(schedule.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            failure = schedule.run_due_news_checks(self.moment("11:15"))
        self.assertEqual(failure["outcome"], "degraded")
        self.assertEqual(self.state()["dates"]["2026-09-21"]["last_success_at"], success_at)
        with patch.object(schedule.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as child:
            tomorrow = schedule.run_due_news_checks(self.moment("08:15", "2026-09-22"))
        self.assertEqual(tomorrow["covered_slots"], ["08:15"])
        self.assertEqual(len(self.news_calls(child)), 1)

    def test_before_activation_and_before_first_slot_have_no_network_or_state_writes(self) -> None:
        with patch.object(schedule.subprocess, "run") as child:
            before = schedule.run_due_news_checks(self.moment("20:30", "2026-09-19"))
            early = schedule.run_due_news_checks(self.moment("08:00"))
        self.assertEqual(before["outcome"], "not_active")
        self.assertEqual(early["outcome"], "not_due")
        child.assert_not_called()
        self.assertFalse(self.state_path.exists())

    def test_later_status_refresh_failure_cannot_erase_successful_news_receipt(self) -> None:
        def result(command, **_kwargs):
            if str(schedule.SCRIPT) in command:
                return SimpleNamespace(returncode=0)
            raise subprocess.TimeoutExpired("status", 20)
        with patch.object(schedule.subprocess, "run", side_effect=result) as child:
            result = schedule.run_due_news_checks(self.moment("16:45"))
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(self.state()["dates"]["2026-09-21"]["last_outcome"], "passed")
        self.assertEqual(len(self.news_calls(child)), 1)

    def test_history_pruning_keeps_sixty_days(self) -> None:
        history = {f"2026-06-{day:02d}": {} for day in range(1, 31)}
        history.update({f"2026-07-{day:02d}": {} for day in range(1, 32)})
        self.state_path.write_text(json.dumps({"schema_version": "phase5r_news_scheduler_v1", "dates": history}))
        with patch.object(schedule.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            schedule.run_due_news_checks(self.moment("08:15"))
        days = self.state()["dates"]
        self.assertEqual(len(days), 60)
        self.assertIn("2026-09-21", days)
        self.assertNotIn("2026-06-01", days)

    def test_malformed_news_state_does_not_stop_eod_refresh(self) -> None:
        self.state_path.write_text("{invalid-json")
        current = self.moment("11:15")
        eod_state = {"schema_version": "phase5r_daily_scheduler_state_v1", "dates": {}}
        output = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(refresh_scheduler.sys, "argv", ["daily_refresh_scheduler.py"]),
            patch.object(refresh_scheduler, "load_active_state", return_value={"operational_from": "2026-08-01"}),
            patch.object(refresh_scheduler, "load_inhibit", return_value={"active": False}),
            patch.object(refresh_scheduler, "cycle_date", return_value="2026-09-21"),
            patch.object(refresh_scheduler, "now_et", return_value=current),
            patch.object(refresh_scheduler, "iso_now", return_value=current.isoformat()),
            patch.object(refresh_scheduler, "read_json", side_effect=lambda path, _default: eod_state if path == refresh_scheduler.DAILY_SCHEDULER_STATE_PATH else {}),
            patch.object(refresh_scheduler, "atomic_write_json"),
            patch.object(refresh_scheduler.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as child,
            redirect_stdout(output),
        ):
            result = refresh_scheduler.main()
        self.assertEqual(result, 0)
        child.assert_called_once()
        self.assertIn(str(refresh_scheduler.REFRESH_PIPELINE), child.call_args.args[0])
        self.assertIn("research_refresh_continues=true", output.getvalue())
        self.assertIn("11:15", eod_state["dates"]["2026-09-21"]["refresh_slots_completed"])


if __name__ == "__main__":
    unittest.main()
