from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
import send_daily_email as sender
from delivery_archive import archive_validated_delivery
from test_owner_review_delivery import delivery_fixture, owner_review_fixture, save_decision


class DeliveryArchiveTests(unittest.TestCase):
    def test_snapshot_hash_mismatch_rejected_before_any_archive_write(self):
        contents = {'decision_sha256': b'{}', 'brief_text_sha256': b'text', 'brief_html_sha256': b'<p>text</p>'}
        hashes = {key: hashlib.sha256(value).hexdigest() for key, value in contents.items()}
        hashes['brief_text_sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'archive'
            with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
                archive_validated_delivery(archive, contents=contents, hashes=hashes)
            self.assertFalse(archive.exists())

    def test_identical_snapshot_is_idempotent_but_symlink_is_rejected(self):
        contents = {'decision_sha256': b'{}', 'brief_text_sha256': b'text', 'brief_html_sha256': b'<p>text</p>'}
        hashes = {key: hashlib.sha256(value).hexdigest() for key, value in contents.items()}
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'archive'
            archive_validated_delivery(archive, contents=contents, hashes=hashes)
            before = {p.name: (p.stat().st_ino, p.read_bytes()) for p in archive.iterdir()}
            archive_validated_delivery(archive, contents=contents, hashes=hashes)
            self.assertEqual(before, {p.name: (p.stat().st_ino, p.read_bytes()) for p in archive.iterdir()})
            target = archive / (hashes['decision_sha256'] + '.json')
            target.unlink()
            external = Path(directory) / 'external'
            external.write_bytes(b'{}')
            target.symlink_to(external)
            with self.assertRaises(OSError):
                archive_validated_delivery(archive, contents=contents, hashes=hashes)
            self.assertEqual(external.read_bytes(), b'{}')

    def test_validated_bytes_survive_replacement_and_precede_claim_without_secrets(self):
        decision = owner_review_fixture()
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            expected = {suffix: path.read_bytes() for suffix, path in (
                ('.json', sender.DAILY_DECISION_JSON_PATH),
                ('.txt', sender.DAILY_BRIEF_TEXT_PATH), ('.html', sender.DAILY_BRIEF_HTML_PATH))}
            archive = sender.DAILY_DELIVERY_LEDGER_PATH.parent / 'sent_decisions.local'
            def replace_after_validation():
                for suffix, content in expected.items():
                    saved = archive / (hashlib.sha256(content).hexdigest() + suffix)
                    self.assertEqual(saved.read_bytes(), content)
                    self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
                self.assertFalse(sender.DAILY_DELIVERY_LEDGER_PATH.exists())
                sender.DAILY_DECISION_JSON_PATH.write_text('{"replacement": true}')
                sender.DAILY_BRIEF_TEXT_PATH.write_text('replacement')
                sender.DAILY_BRIEF_HTML_PATH.write_text('<p>replacement</p>')
                return config.return_value
            config.side_effect = replace_after_validation
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=
                decision['owner_requested_research']['request_id']), 0)
            self.assertEqual(len(list(archive.iterdir())), 3)
            for path in archive.iterdir():
                self.assertNotIn(b'offline-test-password', path.read_bytes())
                self.assertNotIn(b'recipient@example.com', path.read_bytes())
                self.assertNotIn(b'sender@example.com', path.read_bytes())
            self.assertEqual(archive.stat().st_mode & 0o777, 0o700)

    def test_conflicting_archive_is_not_overwritten_and_blocks_before_credentials(self):
        decision = owner_review_fixture()
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            archive = sender.DAILY_DELIVERY_LEDGER_PATH.parent / 'sent_decisions.local'
            archive.mkdir()
            path = archive / (sender.sha256_file(sender.DAILY_DECISION_JSON_PATH) + '.json')
            path.write_bytes(b'conflicting immutable evidence')
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=
                decision['owner_requested_research']['request_id']), 2)
            self.assertEqual(path.read_bytes(), b'conflicting immutable evidence')
            config.assert_not_called()
            smtp.assert_not_called()
            self.assertFalse(sender.DAILY_DELIVERY_LEDGER_PATH.exists())

    def test_archive_failure_blocks_without_claim_or_smtp(self):
        decision = owner_review_fixture()
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            archive = sender.DAILY_DELIVERY_LEDGER_PATH.parent / 'sent_decisions.local'
            archive.write_bytes(b'not a directory')
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=
                decision['owner_requested_research']['request_id']), 2)
            config.assert_not_called()
            smtp.assert_not_called()
            self.assertFalse(sender.DAILY_DELIVERY_LEDGER_PATH.exists())


if __name__ == '__main__':
    unittest.main()
