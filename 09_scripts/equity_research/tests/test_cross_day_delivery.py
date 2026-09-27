from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import daily_common as common
import send_daily_email as sender
from delivery_continuity import delivery_meaning_key, delivery_notification_comparison
from test_delivery_continuity import fixture
from test_email_brief import decision_fixture
from test_owner_review_delivery import delivery_fixture, save_decision

ET = ZoneInfo("America/New_York")
MONDAY = datetime(2026, 9, 28, 11, 20, tzinfo=ET)


def receipt(decision, timestamp="2026-09-27T13:30:17-04:00", status="sent"):
    return {"timestamp": timestamp, "status": status, "reason": delivery_meaning_key(decision)}


def compare(decision, fallback, rows, current=MONDAY, archive_dir=Path("/nonexistent")):
    return delivery_notification_comparison(decision, fallback, rows=rows,
                                            current=current, archive_dir=archive_dir)


class CrossDayDeliveryTests(unittest.TestCase):
    def test_undelivered_post_send_change_survives_monday_and_repeated_research(self):
        delivered = fixture()
        changed = copy.deepcopy(delivered)
        changed["account"]["cash_reserved"] = "0"
        changed.update(cycle_date="2026-09-27", generated_at="2026-09-27T15:04:34-04:00")
        state = {"cycle_date": changed["cycle_date"],
                 "notification_change_fingerprint": common.recommendation_notification_fingerprint(changed)}
        monday = copy.deepcopy(changed)
        monday.update(cycle_date="2026-09-28", generated_at="2026-09-28T08:20:00-04:00")
        fallback = common.notification_change_comparison(monday, state, changed)
        self.assertFalse(fallback["changed"])
        rows = [receipt(delivered)]
        first = compare(monday, fallback, rows)
        self.assertTrue(first["changed"])
        self.assertEqual(first["comparison_source"], "last_delivery")
        state.update(cycle_date=monday["cycle_date"], notification_change_fingerprint=fallback["fingerprint"])
        repeated = compare(monday, common.notification_change_comparison(monday, state, monday), rows)
        self.assertTrue(repeated["changed"])
        self.assertEqual(common.notification_delivery_policy(
            is_weekend=False, weekly_summary_due=False, material_event=False, decision_changed=False,
            account_conflict=False, fundamental_weakening=False, first_material_baseline=False,
            regular_delivery_mode=common.WATCH_ACTION_NOTIFICATION_MODE, notification_changed=first["changed"]),
            (True, "watch_or_action_changed"))

    def test_latest_delivery_suppresses_covered_state_and_screening_churn(self):
        delivered = fixture()
        changed = copy.deepcopy(delivered)
        changed["account"]["cash_reserved"] = "0"
        changed["watch_candidates"] = [{"ticker": "OTHER", "label": "watchlist", "suggested_whole_shares": "0"}]
        for status in ("sent", "send_claimed", "delivery_unknown", "owner_review_sent", "correction_sent"):
            rows = [receipt(delivered), receipt(changed, "2026-09-27T17:00:00-04:00", status)]
            with self.subTest(status=status):
                self.assertFalse(compare(changed, {"changed": True}, rows)["changed"])
        churn = copy.deepcopy(delivered)
        churn["watch_candidates"] = changed["watch_candidates"]
        churn["held_positions"][0]["current_price"] = "200"
        churn["plan_continuity"]["plans"][0].update(status="expired_pending_verification", action="reconcile_plan")
        self.assertFalse(compare(churn, {"changed": True}, [receipt(delivered)])["changed"])

    def test_missing_or_invalid_latest_receipt_keeps_fallback_without_searching_older(self):
        decision = fixture()
        fallback = common.notification_change_comparison(decision, {}, {})
        self.assertFalse(fallback["changed"])
        for rows in ([], [receipt(decision), {"timestamp": "2026-09-27T17:00:00-04:00", "status": "sent"}],
                     [receipt(decision, "2026-09-29T10:00:00-04:00")]):
            self.assertEqual(compare(decision, fallback, rows), fallback)

    def test_legacy_receipt_uses_only_exact_archived_bytes(self):
        prior = fixture()
        raw = json.dumps(prior).encode()
        digest = hashlib.sha256(raw).hexdigest()
        rows = [{"timestamp": "2026-09-27T13:30:00-04:00", "status": "sent", "decision_sha256": digest}]
        changed = copy.deepcopy(prior)
        changed["account"]["cash_reserved"] = "0"
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            path = archive / (digest + ".json")
            path.write_bytes(raw)
            self.assertTrue(compare(changed, {"changed": False}, rows, archive_dir=archive)["changed"])
            path.write_bytes(raw + b" ")
            self.assertEqual(compare(changed, {"changed": False}, rows, archive_dir=archive), {"changed": False})

    def test_sender_recomputes_receipt_bound_change_without_credentials_or_smtp(self):
        prior = decision_fixture()
        decision = copy.deepcopy(prior)
        decision["account"]["cash_reserved"] = "0"
        decision["notification_policy"]["regular_delivery_mode"] = common.WATCH_ACTION_NOTIFICATION_MODE
        rows = [receipt(prior, "2026-08-31T14:00:00-04:00")]
        decision["notification_change"] = compare(decision, {}, rows, datetime(2026, 9, 1, 13, tzinfo=ET))
        decision.update(send_recommended=True, send_reason="watch_or_action_changed")
        with delivery_fixture() as (config, smtp), patch.object(sender, "read_csv", return_value=rows):
            save_decision(decision)
            self.assertEqual(sender.validate_decision(), decision)
            for field, value in (("receipt_sha256", "0" * 64), ("changed", False),
                                 ("compared_at", "2026-09-02T13:00:00-04:00")):
                tampered = copy.deepcopy(decision)
                tampered["notification_change"][field] = value
                save_decision(tampered)
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "notification_change"):
                    sender.validate_decision()
            config.assert_not_called()
            smtp.assert_not_called()

    def test_sender_preserves_composition_anchor_then_latest_delivery_suppression(self):
        prior = decision_fixture()
        decision = copy.deepcopy(prior)
        decision["account"]["cash_reserved"] = "0"
        decision["notification_policy"]["regular_delivery_mode"] = common.WATCH_ACTION_NOTIFICATION_MODE
        rows = [receipt(prior, "2026-08-31T14:00:00-04:00")]
        decision["notification_change"] = compare(decision, {}, rows, datetime(2026, 9, 1, 13, tzinfo=ET))
        decision.update(send_recommended=True, send_reason="watch_or_action_changed")
        # A later receipt must not falsify the stored comparison. The existing
        # send-time duplicate guard still independently suppresses covered work.
        rows.append(receipt(decision, "2026-09-01T18:00:00-04:00", "owner_review_sent"))
        with delivery_fixture() as (config, smtp), patch.object(sender, "read_csv", return_value=rows):
            save_decision(decision)
            self.assertEqual(sender.validate_decision(), decision)
            self.assertEqual(sender.send_once(smtp), 0)
            config.assert_not_called()
            smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
