from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import daily_common as common
import run_runtime_scheduler as runtime


class RuntimePreflightAlertTests(unittest.TestCase):
    root = Path("/isolated-runtime-test")

    @contextmanager
    def policy(self, clock="15:30", *, inhibited=False, operational_from="2026-09-01"):
        current = datetime.fromisoformat(f"2026-09-24T{clock}:00-04:00")
        with ExitStack() as stack:
            stack.enter_context(patch.object(runtime, "ROOT", self.root))
            stack.enter_context(patch.object(runtime, "PRODUCTION_RUNTIME_ROOT", self.root))
            clock_mock = stack.enter_context(patch.object(runtime, "datetime"))
            clock_mock.now.return_value = current
            stack.enter_context(patch.object(runtime, "load_inhibit", return_value={"active": inhibited}))
            stack.enter_context(patch.object(runtime, "load_active_state", return_value={"operational_from": operational_from}))
            stack.enter_context(patch.object(runtime, "load_active_config", return_value={"notifications": {"terminal_alert_after_et": "15:30"}}))
            yield

    def test_waits_until_existing_terminal_deadline(self):
        for clock, expected in [("08:30", 0), ("15:29", 0), ("15:30", 1), ("20:15", 1)]:
            with self.subTest(clock=clock), self.policy(clock), patch.object(runtime, "publish_automation_alert") as alert:
                runtime._best_effort_preflight_alert(self.root, job="dailyrefresh")
                self.assertEqual(alert.call_count, expected)

    def test_maintenance_and_operational_date_suppress_alert(self):
        for options in [{"inhibited": True}, {"operational_from": "2026-09-25"}]:
            with self.subTest(options=options), self.policy(**options), patch.object(runtime, "publish_automation_alert") as alert:
                runtime._best_effort_preflight_alert(self.root, job="dailydecision")
                alert.assert_not_called()

    def test_other_checkout_and_unknown_job_cannot_publish(self):
        for root, job in [(Path("/authoring-checkout"), "dailyrefresh"), (self.root, "unknown")]:
            with self.subTest(root=root, job=job), self.policy(), patch.object(runtime, "publish_automation_alert") as alert:
                runtime._best_effort_preflight_alert(root, job=job)
                alert.assert_not_called()

    def invoke_failed(self, *, mode=None):
        lock = MagicMock()
        lock.__enter__.return_value.contention_observed = False
        failure = runtime.RuntimeSyncError("git_fetch_failed", "untrusted-provider-output")
        arguments = ["runtime_scheduler.py", "--job", "dailyrefresh"]
        if mode:
            arguments.append(mode)
        with (
            patch.object(runtime.sys, "argv", arguments),
            patch.object(runtime, "ExclusiveFileLock", return_value=lock),
            patch.object(runtime, "assert_non_icloud_runtime_root"),
            patch.object(runtime, "sync_runtime_repository", side_effect=failure),
            patch.object(runtime, "inspect_runtime_repository", side_effect=failure),
            patch.object(runtime, "_best_effort_failure_record") as record,
            patch.object(runtime, "_exec_scheduler") as execute,
            redirect_stderr(io.StringIO()),
        ):
            result = runtime.main()
        self.assertEqual(result, 70)
        record.assert_called_once()
        execute.assert_not_called()

    def test_failed_live_preflight_alerts_without_authorizing_child(self):
        with self.policy(), patch.object(runtime, "publish_automation_alert") as alert:
            self.invoke_failed()
            alert.assert_called_once_with(
                component="runtime_preflight", reason="scheduled_runtime_preflight_blocked"
            )
            self.assertNotIn("untrusted-provider-output", str(alert.call_args))

    def test_safe_check_and_sync_only_never_notify(self):
        for mode in ["--safe-check", "--sync-only"]:
            with self.subTest(mode=mode), self.policy(), patch.object(runtime, "publish_automation_alert") as alert:
                self.invoke_failed(mode=mode)
                alert.assert_not_called()

    def test_alert_write_failure_preserves_original_blocked_exit(self):
        with self.policy(), patch.object(runtime, "publish_automation_alert", side_effect=OSError("read-only")):
            self.invoke_failed()

    def test_bad_notification_config_does_not_break_failure_handling(self):
        with self.policy(), patch.object(runtime, "load_active_config", side_effect=ValueError("bad config")), patch.object(runtime, "publish_automation_alert") as alert:
            self.invoke_failed()
            alert.assert_not_called()

    def test_both_jobs_share_one_fixed_local_notification_per_cycle(self):
        with tempfile.TemporaryDirectory(prefix="equity-runtime-alert-") as directory:
            target = Path(directory) / "alert.json"
            with (
                self.policy(),
                patch.object(common, "AUTOMATION_ALERT_PATH", target),
                patch.object(common, "cycle_date", return_value="2026-09-24"),
                patch.object(common, "iso_now", return_value="2026-09-24T15:30:00-04:00"),
                patch.object(common.subprocess, "run") as notify,
            ):
                for job in ("dailyrefresh", "dailydecision", "dailyrefresh"):
                    runtime._best_effort_preflight_alert(self.root, job=job)
            notify.assert_called_once()
            self.assertEqual(notify.call_args.args[0][0], "/usr/bin/osascript")
            saved = json.loads(target.read_text())
            self.assertTrue(saved["active"])
            self.assertFalse(saved["email_attempted"])
            self.assertFalse(saved["broker_connected"])
            self.assertEqual(saved["reason"], "scheduled_runtime_preflight_blocked")


if __name__ == "__main__":
    unittest.main()
