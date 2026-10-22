"""Power availability never confers research or delivery authority."""
import io
import subprocess
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import session_awake as worker

ET = ZoneInfo("America/New_York")


class SessionAwakeTests(unittest.TestCase):
    def test_operating_day_bounds_are_eastern_and_holidays_stay_off(self):
        self.assertEqual(worker.assertion_seconds(datetime(2026, 10, 22, 7, 59, tzinfo=ET)), 0)
        self.assertEqual(worker.assertion_seconds(datetime(2026, 10, 22, 8, tzinfo=ET)), 29700)
        self.assertEqual(worker.assertion_seconds(datetime(2026, 10, 22, 16, 15, tzinfo=ET)), 0)
        self.assertEqual(worker.assertion_seconds(datetime(2026, 10, 24, 10, tzinfo=ET)), 0)
        self.assertEqual(worker.assertion_seconds(datetime(2026, 11, 26, 10, tzinfo=ET)), 0)
        self.assertEqual(worker.assertion_seconds(datetime(2026, 11, 2, 13, tzinfo=ZoneInfo("UTC"))), 29700)
        with self.assertRaisesRegex(ValueError, "aware_clock"):
            worker.assertion_seconds(datetime(2026, 10, 22, 8))

    def test_readonly_check_never_starts_a_process(self):
        with patch.object(worker.subprocess, "run") as process, redirect_stdout(io.StringIO()):
            self.assertEqual(worker.run_assertion(datetime(2026, 10, 22, 9, 30, tzinfo=ET), check=True), 0)
        process.assert_not_called()

    def test_assertion_has_bounded_power_only_arguments(self):
        with patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as process, redirect_stdout(io.StringIO()):
            self.assertEqual(worker.run_assertion(datetime(2026, 10, 22, 15, 30, tzinfo=ET)), 0)
        process.assert_called_once_with(["/usr/bin/caffeinate", "-si", "-t", "2700"], check=False)

    def test_early_close_does_not_cancel_existing_full_review_availability(self):
        # The regular exchange closes at 13:00; the unchanged 13:45 full review
        # and its normal brief window still need host availability.
        self.assertEqual(worker.assertion_seconds(datetime(2026, 11, 27, 13, 45, tzinfo=ET)), 9000)


if __name__ == "__main__":
    unittest.main()
