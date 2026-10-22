"""A finite sender process allowance never extends its delivery authority."""
import io
import subprocess
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import run_daily_decision_pipeline as pipeline
from test_delivery_windows import CONFIG

ET = ZoneInfo("America/New_York")


class SenderProcessBudgetTests(unittest.TestCase):
    def execute(self, clock, *, summary="email_sent=true", returncode=0):
        with ExitStack() as stack:
            for name, value in [("load_active_state", {}), ("load_inhibit", {"active": False}),
                    ("now_et", clock), ("load_active_config", CONFIG),
                    ("refresh_readiness", (True, "daily_refresh_ready"))]:
                stack.enter_context(patch.object(pipeline, name, return_value=value))
            stack.enter_context(patch.object(pipeline, "ExclusiveFileLock"))
            stack.enter_context(patch.object(pipeline, "log_daily_run"))
            clear = stack.enter_context(patch.object(pipeline, "clear_automation_alert"))
            run = stack.enter_context(patch.object(pipeline, "run_command", return_value=
                subprocess.CompletedProcess([], returncode, stdout=summary)))
            with redirect_stdout(io.StringIO()):
                result = pipeline.execute(send=True, scheduled_slot="morning")
            return result, run, clear

    def test_sender_gets_finite_validation_and_smtp_allowance(self):
        result, run, _ = self.execute(datetime(2026, 9, 1, 9, 42, tzinfo=ET))
        self.assertEqual(result, 0)
        self.assertEqual(pipeline.SENDER_PROCESS_TIMEOUT_SECONDS, 180)
        self.assertEqual(run.call_args.kwargs["timeout"], 180)
        self.assertEqual(run.call_args.args[0][-2:], ["--delivery-window", "morning"])

    def test_late_pipeline_start_still_never_invokes_sender(self):
        result, run, _ = self.execute(datetime(2026, 9, 1, 10, 31, tzinfo=ET))
        self.assertEqual(result, 2)
        run.assert_not_called()

    def test_uncertain_send_still_fences_and_does_not_clear_alert(self):
        result, _, clear = self.execute(datetime(2026, 9, 1, 9, 42, tzinfo=ET),
            summary="email_sent=unknown reason=smtp_exception_after_claim", returncode=1)
        self.assertEqual(result, pipeline.DELIVERY_STATUS_UNKNOWN_EXIT)
        clear.assert_not_called()

    def test_child_timeout_remains_bounded_and_retains_unknown_marker(self):
        with patch.object(pipeline.subprocess, "run", side_effect=subprocess.TimeoutExpired(
                ["mock-sender"], 180, output=b"email_sent=unknown")) as run:
            result = pipeline.run_command(["mock-sender"], timeout=180)
        self.assertEqual(result.returncode, 124)
        self.assertIn("command_timeout_seconds=180", result.stdout)
        self.assertTrue(pipeline.delivery_status_is_unknown(result.stdout))
        self.assertEqual(run.call_args.kwargs["timeout"], 180)


if __name__ == "__main__":
    unittest.main()
