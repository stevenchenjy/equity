from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_daily_common as common
from phase5r_daily_common import ExclusiveFileLock
import send_phase5r_daily_email as sender


class CanonicalLockRegressionTests(unittest.TestCase):
    def test_exclusive_lock_refuses_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-lock-symlink-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.lock"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            lock_path = root / "pipeline.lock"
            lock_path.symlink_to(canary)
            before = canary.read_bytes()
            with self.assertRaises((OSError, RuntimeError)):
                with ExclusiveFileLock(lock_path):
                    pass
            self.assertEqual(canary.read_bytes(), before)

    def test_exclusive_lock_refuses_hardlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-lock-hardlink-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.lock"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            lock_path = root / "pipeline.lock"
            os.link(canary, lock_path)
            before = canary.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "one link"):
                with ExclusiveFileLock(lock_path):
                    pass
            self.assertEqual(canary.read_bytes(), before)


class SmtpConfigurationSecurityTests(unittest.TestCase):
    @staticmethod
    def _write_config(path: Path, mode: int) -> None:
        path.write_text(
            json.dumps(
                {
                    "smtp_host": "smtp.gmail.com",
                    "smtp_port": 587,
                    "smtp_username": "sender@example.com",
                    "smtp_app_password": "offline-test-password",
                    "recipient_email": "recipient@example.com",
                    "sender_name": "Phase 5R",
                }
            ),
            encoding="utf-8",
        )
        path.chmod(mode)

    def test_owner_private_smtp_configuration_loads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-smtp-config-") as directory:
            path = Path(directory) / "email.json"
            self._write_config(path, 0o600)
            with patch.object(sender, "EMAIL_CONFIG_PATH", path):
                config = sender.load_config()
        self.assertEqual(config["smtp_host"], "smtp.gmail.com")

    def test_group_or_world_readable_smtp_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-smtp-config-") as directory:
            path = Path(directory) / "email.json"
            self._write_config(path, 0o644)
            with (
                patch.object(sender, "EMAIL_CONFIG_PATH", path),
                self.assertRaisesRegex(sender.ConfigError, "permissions"),
            ):
                sender.load_config()


class AutomationAlertTests(unittest.TestCase):
    def test_same_terminal_alert_notifies_only_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-alert-") as directory:
            path = Path(directory) / "alert.json"
            with (
                patch.object(common, "AUTOMATION_ALERT_PATH", path),
                patch.object(common, "cycle_date", return_value="2026-09-01"),
                patch.object(
                    common,
                    "iso_now",
                    return_value="2026-09-01T20:00:00-04:00",
                ),
                patch.object(common.subprocess, "run") as notify,
            ):
                common.publish_automation_alert(
                    component="daily_decision",
                    reason="scheduled_email_attempts_exhausted",
                )
                common.publish_automation_alert(
                    component="daily_decision",
                    reason="scheduled_email_attempts_exhausted",
                )

            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(payload["active"])
        self.assertEqual(payload["reason"], "scheduled_email_attempts_exhausted")
        self.assertEqual(notify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
