from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_daily_common import ExclusiveFileLock
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

if __name__ == "__main__":
    unittest.main()
