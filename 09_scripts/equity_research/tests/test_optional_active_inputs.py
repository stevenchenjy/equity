from __future__ import annotations

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import verify_active_state_guard as guard


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
            "01_policies/market_regime_policy.json",
            "01_policies/long_horizon_research_policy.json",
            "01_policies/official_news_sources.json",
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            for path in paths:
                with self.subTest(path=path):
                    missing, forbidden = guard._registry_paths([registry_row(path, "optional_generated_research")])
                    self.assertEqual(missing, [path])
                    self.assertIn("TEST:unsupported_optional_input", forbidden)

    def test_wrong_category_unknown_path_or_glob_cannot_claim_optional(self) -> None:
        thesis = "05_risk_and_positions/thesis_reviews.local.json"
        rows = [registry_row(thesis, "optional_generated_research"),
                registry_row("03_source_data/equity_research/unregistered.local.json", "optional_generated_evidence"),
                registry_row("03_source_data/equity_research/*.json", "optional_generated_evidence", kind="pattern")]
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
        thesis = "05_risk_and_positions/thesis_reviews.local.json"
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

    def test_registered_recursive_optional_patterns_allow_directory_containers(self) -> None:
        for pattern, freshness in guard.OPTIONAL_ACTIVE_PATTERNS.items():
            if not pattern.endswith("/**/*"):
                continue
            with self.subTest(pattern=pattern), tempfile.TemporaryDirectory() as directory, \
                    patch.object(guard, "ROOT", Path(directory)):
                nested = Path(directory) / pattern.removesuffix("/**/*") / "history" / "session"
                nested.mkdir(parents=True)
                row = registry_row(pattern, freshness, kind="pattern")
                self.assertEqual(guard._registry_paths([row]), ([], []))
                (nested / "receipt.json").write_text("{}")
                self.assertEqual(guard._registry_paths([row]), ([], []))

    def test_registered_optional_patterns_reject_unsafe_entries_and_container_links(self) -> None:
        pattern = "08_reviews/swing_benchmarks.local/**/*"
        row = registry_row(pattern, guard.OPTIONAL_ACTIVE_PATTERNS[pattern], kind="pattern")
        for kind in ("file_link", "directory_link", "broken_link", "fifo", "container_link", "broken_container_link"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory, \
                    patch.object(guard, "ROOT", Path(directory)):
                root = Path(directory)
                base = root / pattern.removesuffix("/**/*")
                base.parent.mkdir(parents=True)
                safe = root / "safe"
                safe.mkdir()
                (safe / "receipt.json").write_text("{}")
                if kind in {"container_link", "broken_container_link"}:
                    base.symlink_to(safe if kind == "container_link" else root / "missing")
                else:
                    base.mkdir()
                    entry = base / "entry"
                    if kind == "fifo": os.mkfifo(entry)
                    else: entry.symlink_to(safe / "receipt.json" if kind == "file_link" else
                                          safe if kind == "directory_link" else root / "missing")
                self.assertEqual(guard._registry_paths([row])[0], [pattern])

    def test_optional_exact_file_symlink_remains_unsafe(self) -> None:
        path, freshness = next(iter(guard.OPTIONAL_ACTIVE_INPUTS.items()))
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, "ROOT", Path(directory)):
            target = Path(directory) / path
            target.parent.mkdir(parents=True)
            original = Path(directory) / "source.json"
            original.write_text("{}")
            target.symlink_to(original)
            self.assertEqual(guard._registry_paths([registry_row(path, freshness)])[0], [path])


if __name__ == "__main__":
    unittest.main()
