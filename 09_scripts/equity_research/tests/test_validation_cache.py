from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import sha256_file
from validation_cache import file_hash_validation


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
