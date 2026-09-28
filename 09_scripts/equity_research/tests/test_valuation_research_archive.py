from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from valuation_research_inputs import archive_bytes


class ValuationResearchArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.json'
        self.content = b'{"retained": "exact original"}\n'
        self.source.write_bytes(self.content)
        self.history = self.root / 'history'
        self.digest = hashlib.sha256(self.content).hexdigest()

    def test_fsync_failure_cannot_publish_an_incomplete_immutable_target(self):
        with patch('os.fsync', side_effect=OSError('simulated interrupted durable write')):
            with self.assertRaises(OSError):
                archive_bytes(self.source, self.history)
        self.assertFalse((self.history / (self.digest + '.json')).exists())
        self.assertEqual(list(self.history.iterdir()), [])
        self.assertEqual(archive_bytes(self.source, self.history), self.digest)

    def test_private_exact_bytes_and_existing_archive_are_retained(self):
        self.assertEqual(archive_bytes(self.source, self.history), self.digest)
        target = self.history / (self.digest + '.json')
        self.assertEqual(target.read_bytes(), self.content)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.history.stat().st_mode), 0o700)
        inode = target.stat().st_ino
        self.assertEqual(archive_bytes(self.source, self.history), self.digest)
        self.assertEqual(target.stat().st_ino, inode)
        target.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            archive_bytes(self.source, self.history)
        self.assertEqual(target.read_bytes(), b'corrupt')

    def test_source_symlink_is_rejected(self):
        link = self.root / 'source-link.json'
        link.symlink_to(self.source)
        with self.assertRaises((ValueError, OSError)):
            archive_bytes(link, self.history)

    def test_history_symlink_is_rejected(self):
        destination = self.root / 'elsewhere'
        destination.mkdir()
        self.history.symlink_to(destination, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            archive_bytes(self.source, self.history)
        self.assertEqual(list(destination.iterdir()), [])

    def test_existing_target_symlink_is_rejected(self):
        self.history.mkdir()
        target = self.history / (self.digest + '.json')
        target.symlink_to(self.source)
        with self.assertRaises((ValueError, OSError)):
            archive_bytes(self.source, self.history)
        self.assertTrue(target.is_symlink())
        self.assertEqual(self.source.read_bytes(), self.content)


if __name__ == '__main__':
    unittest.main()
