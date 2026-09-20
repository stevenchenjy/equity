from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import verify_phase5r_c8_active_state_guard as guard


def registry_row(path: str, freshness: str, *, kind: str = "exact") -> dict[str, str]:
    return {"registry_id": "TEST", "path_spec": path, "path_kind": kind,
            "allowed_as_active_input": "yes", "decision_freshness": freshness}


class OptionalActiveInputTests(unittest.TestCase):
    def test_first_run_missing_exact_optional_receipts_and_review_are_allowed(self) -> None:
        rows = [registry_row(path, freshness) for path, freshness in guard.OPTIONAL_ACTIVE_INPUTS.items()]
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            self.assertEqual(guard._registry_paths(rows), ([], []))

    def test_optional_marker_cannot_waive_existing_required_account_or_policies(self) -> None:
        paths = [
            "05_risk_and_positions/current_account_state.local.json",
            "05_risk_and_positions/current_positions.local.csv",
            "01_policies/phase5r_market_regime_policy.json",
            "01_policies/phase5r_long_horizon_research_policy.json",
            "01_policies/phase5r_official_news_sources.json",
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            for path in paths:
                with self.subTest(path=path):
                    missing, forbidden = guard._registry_paths([registry_row(path, "optional_generated_research")])
                    self.assertEqual(missing, [path])
                    self.assertIn("TEST:unsupported_optional_input", forbidden)

    def test_wrong_category_unknown_path_or_glob_cannot_claim_optional(self) -> None:
        thesis = "05_risk_and_positions/phase5r_thesis_reviews.local.json"
        rows = [registry_row(thesis, "optional_generated_research"),
                registry_row("03_source_data/phase5r/unregistered.local.json", "optional_generated_evidence"),
                registry_row("03_source_data/phase5r/*.json", "optional_generated_evidence", kind="pattern")]
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            missing, forbidden = guard._registry_paths(rows)
        self.assertEqual(len(missing), 3)
        self.assertEqual(forbidden.count("TEST:unsupported_optional_input"), 3)

    def test_present_policy_is_still_rejected_if_relabeled_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            policy = Path(directory) / "policy.json"
            policy.write_text("{}")
            missing, forbidden = guard._registry_paths([registry_row("policy.json", "optional_generated_research")])
        self.assertEqual(missing, [])
        self.assertIn("TEST:unsupported_optional_input", forbidden)

    def test_optional_nonfile_or_broken_symlink_is_not_treated_as_absent(self) -> None:
        thesis = "05_risk_and_positions/phase5r_thesis_reviews.local.json"
        row = registry_row(thesis, "optional_current_review")
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            target = Path(directory) / thesis
            target.mkdir(parents=True)
            self.assertEqual(guard._registry_paths([row])[0], [thesis])
            target.rmdir()
            target.symlink_to(Path(directory) / "nonexistent")
            self.assertEqual(guard._registry_paths([row])[0], [thesis])

    def test_optional_missing_never_overrides_forbidden_or_unallowed_input(self) -> None:
        path, freshness = next(iter(guard.OPTIONAL_ACTIVE_INPUTS.items()))
        row = registry_row(path, freshness) | {"allowed_as_active_input": "no"}
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            self.assertIn("TEST:not_explicitly_allowed", guard._registry_paths([row])[1])


if __name__ == "__main__":
    unittest.main()
