from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import send_daily_email as sender
from email_brief import render_email
from test_email_brief import decision_fixture
from test_owner_review_delivery import delivery_fixture, save_decision


def actionable_fixture():
    decision = decision_fixture()
    decision.update(decision_changed=True, send_recommended=True, send_reason="material_decision_change")
    return decision


@contextmanager
def publication_fixture(*, correction=False):
    config = deepcopy(sender.load_active_config())
    config["notifications"].pop("regular_delivery_mode", None)
    with delivery_fixture() as fixture, patch.object(sender, "load_active_config", return_value=config):
        if correction:
            sender.append_csv_durable(sender.DAILY_DELIVERY_LEDGER_PATH, sender.LEDGER_FIELDS, {
                "cycle_date": "2026-09-01", "status": "sent", "decision_sha256": "prior",
                "brief_text_sha256": "prior", "brief_html_sha256": "prior"})
        yield fixture


class SenderPublicationTests(unittest.TestCase):
    def test_correction_uses_actual_clock_for_workflow_expiry(self):
        decision = actionable_fixture()
        decision["workflow_integrity"] = {"schema_version": "equity_workflow_integrity_v1"}
        with publication_fixture(correction=True) as (config, smtp):
            save_decision(decision)
            def check(_decision, *, root, current):
                self.assertEqual(current.hour, 20)
                self.assertNotEqual(current.isoformat(), decision["generated_at"])
                raise ValueError("workflow_plan_state_changed_recompose_required")
            with patch("workflow_integrity.validate_published_workflow", side_effect=check):
                self.assertEqual(sender.send_once(smtp, correction=True), 2)
            config.assert_not_called()
            smtp.assert_not_called()

    def test_all_delivery_modes_bind_captured_message_and_claim_hashes(self):
        for correction in (False, True):
            for fail_smtp in (False, True):
                with self.subTest(correction=correction, fail_smtp=fail_smtp), publication_fixture(correction=correction) as (config, smtp):
                    decision = actionable_fixture()
                    save_decision(decision)
                    _, expected_text, expected_html = render_email(decision)
                    expected_hashes = {key: sender.sha256_file(path) for key, path in (
                        ("decision_sha256", sender.DAILY_DECISION_JSON_PATH),
                        ("brief_text_sha256", sender.DAILY_BRIEF_TEXT_PATH),
                        ("brief_html_sha256", sender.DAILY_BRIEF_HTML_PATH))}
                    def replace_after_validation():
                        sender.DAILY_DECISION_JSON_PATH.write_text('{"replacement":true}')
                        sender.DAILY_BRIEF_TEXT_PATH.write_text("replacement body")
                        sender.DAILY_BRIEF_HTML_PATH.write_text("<p>replacement</p>")
                        return config.return_value
                    config.side_effect = replace_after_validation
                    if fail_smtp:
                        smtp.return_value.__enter__.return_value.send_message.side_effect = OSError("offline uncertain send")
                    self.assertEqual(sender.send_once(smtp, correction=correction), int(fail_smtp))
                    message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
                    self.assertEqual(message.get_body(preferencelist=("plain",)).get_content(), expected_text)
                    self.assertEqual(message.get_body(preferencelist=("html",)).get_content(), expected_html)
                    rows = sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)[-2:]
                    for row in rows:
                        self.assertEqual({key: row[key] for key in expected_hashes}, expected_hashes)
                    self.assertTrue(rows[-1]["status"].endswith("delivery_unknown" if fail_smtp else "sent"))

    def test_changed_artifacts_while_waiting_for_lock_block_before_credentials(self):
        for correction in (False, True):
            with self.subTest(correction=correction), publication_fixture(correction=correction) as (config, smtp):
                decision = actionable_fixture()
                save_decision(decision)
                @contextmanager
                def change_while_waiting(_path):
                    sender.DAILY_BRIEF_TEXT_PATH.write_text("old instruction replaced during lock wait")
                    yield
                with patch.object(sender, "ExclusiveFileLock", side_effect=change_while_waiting):
                    self.assertEqual(sender.send_once(smtp, correction=correction), 2)
                config.assert_not_called()
                smtp.assert_not_called()
                self.assertFalse(any(row["status"].endswith("send_claimed") for row in sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)))

    def test_workflow_change_after_message_build_blocks_before_durable_claim(self):
        decision = actionable_fixture()
        decision["workflow_integrity"] = {"schema_version": "equity_workflow_integrity_v1"}
        with publication_fixture() as (_, smtp):
            save_decision(decision)
            with patch("workflow_integrity.validate_published_workflow",
                       side_effect=[None, None, ValueError("workflow_inputs_changed_recompose_required")]) as check:
                self.assertEqual(sender.send_once(smtp), 2)
                self.assertEqual(check.call_count, 3)
            smtp.assert_not_called()
            self.assertFalse(sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH))


if __name__ == "__main__":
    unittest.main()
