from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v5 as v5
from run_phase5r_model_pilot_v5 import check_v5_readiness, execute_model_pilot_v5


class ReplacementPilotV5Tests(unittest.TestCase):
    def test_readiness_is_local_and_preserves_one_call_cap(self) -> None:
        report = check_v5_readiness()
        self.assertTrue(report["passed"])
        self.assertFalse(report["provider_constructed"])
        self.assertFalse(report["network_used"])
        self.assertFalse(report["files_written"])
        self.assertEqual(report["new_model_calls"], 1)
        self.assertEqual(report["new_reserved_usd"], "0.05808")

    def test_executor_refuses_before_constructing_a_provider(self) -> None:
        constructed = False

        def factory() -> object:
            nonlocal constructed
            constructed = True
            raise AssertionError("provider must not be constructed")

        with self.assertRaisesRegex(v1.PilotStop, "explicit interactive"):
            execute_model_pilot_v5(
                provider_factory=factory,  # type: ignore[arg-type]
                explicit_user_authorization=False,
            )
        self.assertFalse(constructed)

    def test_check_entrypoint_is_provider_free(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(Path(v5.__file__).resolve()), "--check"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )
        report = json.loads(completed.stdout)
        self.assertTrue(report["passed"])
        self.assertFalse(report["provider_constructed"])
        self.assertFalse(report["network_used"])
        self.assertFalse(report["files_written"])


if __name__ == "__main__":
    unittest.main()
