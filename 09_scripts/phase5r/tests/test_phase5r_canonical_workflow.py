from __future__ import annotations

import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
import verify_phase5r_c8_active_state_guard as workflow_guard


class CanonicalWorkflowTests(unittest.TestCase):
    def test_repository_static_workflow_is_daily_only(self) -> None:
        checks = workflow_guard.collect_checks(include_runtime=False)
        failures = [
            f"{check.check_id}:{check.detail}"
            for check in checks
            if not check.passed
        ]
        self.assertEqual(failures, [])

    def test_weekly_path_cannot_enter_active_registry(self) -> None:
        rows = workflow_guard._read_csv(workflow_guard.ALLOWED_PATH)
        mutated = copy.deepcopy(rows)
        mutated[0]["path_spec"] = (
            "09_scripts/phase5r/"
            "run_phase5r_c7_weekly_conviction_pipeline.py"
        )
        _, forbidden = workflow_guard._registry_paths(mutated)
        self.assertTrue(forbidden)

    def test_retired_sender_cannot_regain_send_authority(self) -> None:
        rows = workflow_guard._read_csv(
            workflow_guard.DEPRECATED_PATH
        )
        mutated = copy.deepcopy(rows)
        mutated[0]["email_send_allowed"] = "yes"
        issues = workflow_guard._deprecated_registry_issues(mutated)
        self.assertIn("DW-001", issues)

    def test_canonical_runtime_has_no_weekly_dependency(self) -> None:
        self.assertEqual(workflow_guard._canonical_source_issues(), [])


if __name__ == "__main__":
    unittest.main()
