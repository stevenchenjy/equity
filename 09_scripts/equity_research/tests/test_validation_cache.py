from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import sha256_file
from opportunity_contract import inside, validate_receipts
from validation_cache import file_hash_validation, content_proof_scope, resolved_sha256


class ValidationCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'source.json'
        self.path.write_bytes(b'original')

    def test_unchanged_source_reused_only_within_transaction(self):
        original = Path.read_bytes
        reads = []
        def read(path):
            reads.append(path)
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            with file_hash_validation():
                expected = sha256_file(self.path)
                for _ in range(3):
                    self.assertEqual(sha256_file(self.path), expected)
                with file_hash_validation():
                    self.assertEqual(sha256_file(self.path), expected)
            self.assertEqual(len(reads), 1)
            with file_hash_validation():
                self.assertEqual(sha256_file(self.path), expected)
            self.assertEqual(len(reads), 2)
            sha256_file(self.path); sha256_file(self.path)
            self.assertEqual(len(reads), 4)

    def test_resolved_source_locator_is_proved_once_and_rechecked_at_exit(self):
        def resolve(root, locator):
            return (root / locator).resolve()

        resolver = Mock(side_effect=resolve)
        with file_hash_validation():
            expected = resolved_sha256(self.path.parent, self.path.name, resolver)
            for _ in range(4):
                self.assertEqual(resolved_sha256(self.path.parent, self.path.name, resolver), expected)
            self.assertEqual(resolver.call_count, 1)
        self.assertEqual(resolver.call_count, 2)

    def test_resolved_source_locator_retarget_and_atomic_replacement_fail_final_fence(self):
        def resolve(root, locator):
            return (root / locator).resolve()

        alias = self.path.with_name('alias.json')
        other = self.path.with_name('other.json')
        other.write_bytes(b'original')
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
            with file_hash_validation():
                resolved_sha256(alias.parent, alias.name, resolve)
                alias.unlink()
                alias.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
            with file_hash_validation():
                resolved_sha256(self.path.parent, self.path.name, resolve)
                os.replace(other, self.path)

    def test_research_source_cannot_retarget_outside_its_root(self):
        with tempfile.TemporaryDirectory() as outside_folder:
            outside = Path(outside_folder) / self.path.name
            outside.write_bytes(self.path.read_bytes())
            alias = self.path.with_name('alias.json')
            alias.symlink_to(self.path)
            with self.assertRaisesRegex(ValueError, 'research_path_escape'):
                with file_hash_validation():
                    resolved_sha256(alias.parent, alias.name, inside)
                    alias.unlink()
                    alias.symlink_to(outside)

    def test_resolved_source_content_change_fails_final_fence(self):
        with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
            with file_hash_validation():
                prior = resolved_sha256(self.path.parent, self.path.name, inside)
                self.path.write_bytes(b'changed contents after initial proof')
                self.assertEqual(resolved_sha256(self.path.parent, self.path.name, inside), prior)

    def test_research_receipt_clocks_and_expected_digests_are_checked_individually(self):
        current = datetime(2026, 11, 18, 13, tzinfo=timezone.utc)
        receipt = {'path': self.path.name, 'sha256': sha256_file(self.path),
                   'available_at': current.isoformat()}
        with file_hash_validation():
            validate_receipts([receipt], root=self.path.parent, current=current)
            with self.assertRaisesRegex(ValueError, 'research_source_from_future'):
                validate_receipts([receipt], root=self.path.parent, current=current - timedelta(seconds=1))
            with self.assertRaisesRegex(ValueError, 'research_source_changed'):
                validate_receipts([{**receipt, 'sha256': '0' * 64}], root=self.path.parent, current=current)

    def test_same_size_rewrite_with_preserved_mtime_invalidates(self):
        original = self.path.stat()
        with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
            with file_hash_validation():
                before = sha256_file(self.path)
                self.path.write_bytes(b'replaced')
                os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns))
                self.assertEqual(self.path.stat().st_size, original.st_size)
                self.assertEqual(self.path.stat().st_mtime_ns, original.st_mtime_ns)
                self.assertNotEqual(sha256_file(self.path), before)
                self.assertEqual(sha256_file(self.path), hashlib.sha256(b'replaced').hexdigest())

    def test_reproving_identical_bytes_enrolls_in_independent_final_fence(self):
        with content_proof_scope():
            prior = sha256_file(self.path)
            with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
                with file_hash_validation():
                    with patch.object(Path, 'read_bytes', side_effect=AssertionError('duplicate read')):
                        self.assertEqual(sha256_file(self.path), prior)
                    self.path.write_bytes(b'changed')
            with file_hash_validation():
                self.assertNotEqual(sha256_file(self.path), prior)

    def test_replaced_locator_with_original_size_and_mtime_always_rehashes(self):
        original = self.path.stat()
        with content_proof_scope():
            prior = sha256_file(self.path)
            replacement = self.path.with_suffix('.new')
            replacement.write_bytes(b'replaced')
            os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
            os.replace(replacement, self.path)
            new = sha256_file(self.path)
        self.assertNotEqual(new, prior)
        self.assertEqual(new, hashlib.sha256(b'replaced').hexdigest())

    def test_atomic_replacement_invalidates_even_with_same_bytes_and_mtime(self):
        original = self.path.stat()
        with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
            with file_hash_validation():
                sha256_file(self.path)
                replacement = self.path.with_suffix('.new')
                replacement.write_bytes(b'original')
                os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
                os.replace(replacement, self.path)
                self.assertEqual(sha256_file(self.path), hashlib.sha256(b'original').hexdigest())

    def test_final_fence_catches_change_after_last_lookup_and_context_is_reset(self):
        with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
            with file_hash_validation():
                sha256_file(self.path)
                self.path.write_bytes(b'changed without another lookup')
        with file_hash_validation():
            self.assertEqual(sha256_file(self.path), hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_failure_does_not_leave_cache_in_later_validation(self):
        with self.assertRaisesRegex(RuntimeError, 'expected failure'):
            with file_hash_validation():
                sha256_file(self.path)
                raise RuntimeError('expected failure')
        self.path.write_bytes(b'changed')
        with file_hash_validation():
            self.assertEqual(sha256_file(self.path), hashlib.sha256(b'changed').hexdigest())


if __name__ == '__main__':
    unittest.main()
