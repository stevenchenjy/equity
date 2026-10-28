"""Public history collection cannot leak into offline publication or its budget."""
import subprocess
import unittest
from unittest.mock import patch
from _support import SCRIPT_DIR  # noqa: F401
import run_daily_refresh as refresh


class SwingPipelineBoundaryTests(unittest.TestCase):
    def invoke(self, public, remaining=None):
        with patch("decision_dependencies.observe", return_value=None), \
             patch.object(refresh, "run_stage", return_value=subprocess.CompletedProcess([], 0)) as runner:
            refresh.run_step("swing_candidate_history", "run_swing_candidate_history.py", True,
                             market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE,
                             refresh_public=public, maximum_child_seconds=remaining)
        return runner.call_args

    def test_operator_reuse_is_offline_and_passes_exact_root_to_finite_advisory_stage(self):
        call = self.invoke(False)
        command = call.args[0]
        self.assertIn("--pipeline-coordinated", command)
        self.assertEqual(command[command.index("--root") + 1], str(refresh.ROOT))
        self.assertNotIn("--collect", command)
        self.assertEqual(call.kwargs["timeout"], 210)
        self.assertIn("swing_candidate_history", refresh.ADVISORY_STEPS)

    def test_scheduled_public_reuse_can_collect_without_extending_remaining_refresh_time(self):
        call = self.invoke(True, 30)
        self.assertIn("--collect", call.args[0])
        self.assertEqual(call.kwargs["timeout"], 30)


if __name__ == "__main__":unittest.main()
