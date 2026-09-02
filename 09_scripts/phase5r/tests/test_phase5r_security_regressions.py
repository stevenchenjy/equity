from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

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

    def test_explicit_correction_requires_changed_content_and_deduplicates_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-correction-") as directory:
            root = Path(directory)
            decision = root / "decision.json"
            text = root / "brief.txt"
            html = root / "brief.html"
            decision.write_text('{"version": 2}\n', encoding="utf-8")
            text.write_text("corrected brief\n", encoding="utf-8")
            html.write_text("<p>corrected brief</p>\n", encoding="utf-8")
            current_hashes = (
                common.sha256_file(decision),
                common.sha256_file(text),
                common.sha256_file(html),
            )
            rows = [{
                "cycle_date": "2026-09-01",
                "status": "sent",
                "decision_sha256": "old",
                "brief_text_sha256": "old",
                "brief_html_sha256": "old",
            }]
            with (
                patch.object(sender, "DAILY_DECISION_JSON_PATH", decision),
                patch.object(sender, "DAILY_BRIEF_TEXT_PATH", text),
                patch.object(sender, "DAILY_BRIEF_HTML_PATH", html),
            ):
                self.assertEqual(
                    sender.correction_eligibility(rows, "2026-09-01"),
                    (True, "explicit_changed_content_correction"),
                )
                self.assertEqual(
                    sender.correction_eligibility(
                        rows + [{
                            "cycle_date": "2026-09-01",
                            "status": "correction_send_claimed",
                            "decision_sha256": current_hashes[0],
                            "brief_text_sha256": current_hashes[1],
                            "brief_html_sha256": current_hashes[2],
                        }],
                        "2026-09-01",
                    ),
                    (False, "existing_identical_correction_delivery"),
                )
                self.assertEqual(
                    sender.correction_eligibility(
                        rows + [{
                            "cycle_date": "2026-09-01",
                            "status": "correction_sent",
                            "decision_sha256": "older-correction",
                            "brief_text_sha256": "older-correction",
                            "brief_html_sha256": "older-correction",
                        }],
                        "2026-09-01",
                    ),
                    (True, "explicit_changed_content_correction"),
                )

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


class NotificationPolicySecurityTests(unittest.TestCase):
    def test_pre_send_decision_remains_valid_at_scheduler_send_time(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-notification-") as directory:
            root = Path(directory)
            decision_path = root / "decision.json"
            text_path = root / "brief.txt"
            html_path = root / "brief.html"
            text_path.write_text("Research brief\n", encoding="utf-8")
            html_path.write_text("<p>Research brief</p>\n", encoding="utf-8")
            decision = {
                "cycle_date": "2026-09-01",
                "automatic_action_allowed": False,
                "decision_changed": False,
                "material_events": [{"accession_number": "test"}],
                "account_conflicts": [],
                "eligible_action_review_candidates": [],
                "eligible_new_position_review_candidates": [],
                "market_gate": {"expected_market_session": "2026-08-31"},
                "fundamental_gate": {"weakening_tickers": []},
                "notification_policy": {
                    "event_driven": True,
                    "weekly_summary_weekday": "friday",
                    "unchanged_daily_email": False,
                },
                "notification_policy_evaluation": {
                    "is_weekend": False,
                    "weekly_summary_due": False,
                    "prior_decision_present": True,
                    "first_material_baseline": False,
                    "long_term_fundamental_weakening": False,
                    "scheduler_time_gate_applied": False,
                },
                "send_recommended": True,
                "send_reason": "material_decision_change",
                "boundaries": {
                    "broker_connected": False,
                    "broker_account_read": False,
                    "order_code_created": False,
                    "trade_placed": False,
                },
            }
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            config = {
                "notifications": {
                    "event_driven": True,
                    "weekly_summary_weekday": "friday",
                    "unchanged_daily_email": False,
                }
            }
            with (
                patch.object(sender, "DAILY_DECISION_JSON_PATH", decision_path),
                patch.object(sender, "DAILY_BRIEF_TEXT_PATH", text_path),
                patch.object(sender, "DAILY_BRIEF_HTML_PATH", html_path),
                patch.object(sender, "cycle_date", return_value="2026-09-01"),
                patch.object(
                    sender,
                    "now_et",
                    return_value=datetime(
                        2026,
                        9,
                        1,
                        13,
                        30,
                        tzinfo=ZoneInfo("America/New_York"),
                    ),
                ),
                patch.object(sender, "load_active_config", return_value=config),
            ):
                validated = sender.validate_decision()
                self.assertTrue(validated["send_recommended"])
                decision["generated_at"] = "2026-09-01T13:20:00-04:00"
                decision_path.write_text(json.dumps(decision), encoding="utf-8")
                with patch.object(
                    sender,
                    "now_et",
                    return_value=datetime(
                        2026,
                        9,
                        2,
                        7,
                        30,
                        tzinfo=ZoneInfo("America/New_York"),
                    ),
                ):
                    historical = sender.validate_decision(correction=True)
                self.assertEqual(historical["cycle_date"], "2026-09-01")
                decision["send_recommended"] = False
                decision["send_reason"] = "before_daily_decision_time"
                decision_path.write_text(json.dumps(decision), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "delivery_policy"):
                    sender.validate_decision()


if __name__ == "__main__":
    unittest.main()
