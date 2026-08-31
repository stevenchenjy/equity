#!/usr/bin/env python3
"""Run the active Phase 5R suite while retaining retired-pilot tests in history."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
TEST_DIR = SCRIPT_DIR / "tests"
RETIRED_TEST_MODULE_PREFIXES = (
    "test_phase5r_model_pilot",
    "test_phase5r_safe_shadow_readiness",
)


def flattened(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flattened(item)
        else:
            yield item


def main() -> int:
    sys.path[:0] = [str(SCRIPT_DIR), str(TEST_DIR)]
    discovered = unittest.defaultTestLoader.discover(str(TEST_DIR), pattern="test_*.py")
    active = unittest.TestSuite()
    excluded = 0
    for test in flattened(discovered):
        module = test.__class__.__module__.split(".")[-1]
        if module.startswith(RETIRED_TEST_MODULE_PREFIXES):
            excluded += 1
        else:
            active.addTest(test)
    result = unittest.TextTestRunner(verbosity=1).run(active)
    print(
        f"active_tests_run={result.testsRun} retired_tests_excluded={excluded} "
        f"failures={len(result.failures)} errors={len(result.errors)}"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
