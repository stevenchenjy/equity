"""Lossless history retention, not source-data pruning."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from opportunity_contract import retain_history_json


class OpportunityHistoryRetentionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.payload = {"events": [{"evidence": "original source \u03b1"}] * 2000}
        self.raw = (json.dumps(self.payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()

    def tearDown(self):
        self.directory.cleanup()

    def test_new_archive_recovers_exact_bytes_and_is_idempotent(self):
        path = self.root / "original.json"
        archive = retain_history_json(path, self.payload)
        self.assertEqual(archive.suffixes, [".json", ".gz"])
        self.assertEqual(gzip.decompress(archive.read_bytes()), self.raw)
        self.assertLess(archive.stat().st_size, len(self.raw) / 10)
        original = archive.read_bytes()
        self.assertEqual(retain_history_json(path, self.payload), archive)
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse(path.exists())

    def test_existing_plain_history_is_preserved_without_duplicate(self):
        path = self.root / "old.json"
        path.write_bytes(self.raw)
        self.assertEqual(retain_history_json(path, self.payload), path)
        self.assertEqual(path.read_bytes(), self.raw)
        self.assertFalse(path.with_suffix(".json.gz").exists())

    def test_plain_and_compressed_conflicts_do_not_overwrite_evidence(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                path = self.root / (str(compressed) + ".json")
                existing = retain_history_json(path, self.payload) if compressed else path
                if not compressed:
                    existing.write_bytes(self.raw)
                original = existing.read_bytes()
                with self.assertRaisesRegex(ValueError, "archive_conflict"):
                    retain_history_json(path, {"events": ["different"]})
                self.assertEqual(existing.read_bytes(), original)

    def test_corrupt_archive_fails_closed(self):
        path = self.root / "corrupt.json"
        archive = path.with_suffix(".json.gz")
        archive.write_bytes(b"not gzip")
        with self.assertRaisesRegex(ValueError, "archive_corrupt"):
            retain_history_json(path, self.payload)
        self.assertEqual(archive.read_bytes(), b"not gzip")


if __name__ == "__main__":
    unittest.main()
