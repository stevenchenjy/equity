#!/usr/bin/env python3
"""Run every test in the focused active Phase 5R suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
TEST_DIR = SCRIPT_DIR / "tests"
def main() -> int:
    sys.path[:0] = [str(SCRIPT_DIR), str(TEST_DIR)]
    suite = unittest.defaultTestLoader.discover(str(TEST_DIR), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(
        f"active_tests_run={result.testsRun} "
        f"failures={len(result.failures)} errors={len(result.errors)}"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
