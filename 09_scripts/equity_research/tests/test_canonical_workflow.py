from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import verify_active_state_guard as workflow_guard


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
            "09_scripts/equity_research/"
            "run_c7_weekly_conviction_pipeline.py"
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

    def test_runtime_artifacts_required_only_for_runtime_scope(self) -> None:
        rows = [{"registry_id": "FIXTURE", "path_spec": path, "path_kind": kind,
                 "allowed_as_active_input": "yes", "decision_freshness": "current_run"}
                for kind, path in workflow_guard.RUNTIME_REQUIRED_PATHS]
        with tempfile.TemporaryDirectory() as directory, patch.object(workflow_guard, "ROOT", Path(directory)):
            self.assertEqual(workflow_guard._registry_paths(rows, include_runtime=False), ([], []))
            missing, forbidden = workflow_guard._registry_paths(rows, include_runtime=True)
            self.assertEqual(set(missing), {row["path_spec"] for row in rows})
            self.assertEqual(forbidden, [])
            self.assertEqual(workflow_guard._registry_paths(rows)[0], missing)

    def test_static_scope_never_waives_policy_or_registry_authority(self) -> None:
        rows = [{"registry_id": "POLICY", "path_spec": "00_project_control/active_production_config.json",
                 "path_kind": "exact", "allowed_as_active_input": "yes", "decision_freshness": "current_run"},
                {"registry_id": "PRIVATE", "path_spec": "05_risk_and_positions/current_positions.local.csv",
                 "path_kind": "exact", "allowed_as_active_input": "no", "decision_freshness": "current_run"}]
        with tempfile.TemporaryDirectory() as directory, patch.object(workflow_guard, "ROOT", Path(directory)):
            missing, forbidden = workflow_guard._registry_paths(rows, include_runtime=False)
        self.assertEqual(missing, [rows[0]["path_spec"]])
        self.assertIn("PRIVATE:not_explicitly_allowed", forbidden)


if __name__ == "__main__":
    unittest.main()
