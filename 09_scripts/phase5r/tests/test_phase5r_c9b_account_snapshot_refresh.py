from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import reconcile_phase5r_c9b_account_state as reconciliation_runner
from create_phase5r_daily_decision_and_brief import latest_applied_execution
from phase5r_c9b_common import (
    applied_reconciliation_current_state_status,
    applied_reconciliation_matches_current_state,
)


def _reconciliation() -> dict[str, str]:
    return {
        "positions_sha256_after": "a" * 64,
        "account_sha256_after": "b" * 64,
        "reference_price_timestamp": "2026-07-23T23:19:45-04:00",
    }


class C9BAccountSnapshotRefreshTests(unittest.TestCase):
    def test_later_valid_owner_snapshot_is_compatible_without_rewriting_history(self) -> None:
        status = applied_reconciliation_current_state_status(
            _reconciliation(),
            current_positions_sha256="a" * 64,
            current_account_sha256="c" * 64,
            current_account_last_updated="2026-08-04T14:05:00-04:00",
        )
        self.assertEqual(status, "owner_account_snapshot_after_reconciliation")
        self.assertTrue(
            applied_reconciliation_matches_current_state(
                _reconciliation(),
                current_positions_sha256="a" * 64,
                current_account_sha256="c" * 64,
                current_account_last_updated="2026-08-04T14:05:00-04:00",
            )
        )

    def test_original_historical_account_hash_remains_accepted(self) -> None:
        self.assertEqual(
            applied_reconciliation_current_state_status(
                _reconciliation(),
                current_positions_sha256="a" * 64,
                current_account_sha256="b" * 64,
                current_account_last_updated="2026-07-23T23:20:05-04:00",
            ),
            "historical_account_hash_match",
        )

    def test_stale_or_malformed_snapshot_is_rejected(self) -> None:
        for updated_at in ("2026-07-23T23:19:45-04:00", "not-a-timestamp"):
            with self.subTest(updated_at=updated_at):
                self.assertFalse(
                    applied_reconciliation_matches_current_state(
                        _reconciliation(),
                        current_positions_sha256="a" * 64,
                        current_account_sha256="c" * 64,
                        current_account_last_updated=updated_at,
                    )
                )

    def test_position_mutation_remains_a_hard_mismatch(self) -> None:
        self.assertEqual(
            applied_reconciliation_current_state_status(
                _reconciliation(),
                current_positions_sha256="d" * 64,
                current_account_sha256="c" * 64,
                current_account_last_updated="2026-08-04T14:05:00-04:00",
            ),
            "positions_hash_mismatch",
        )

    def test_reconciliation_upsert_preserves_other_execution_history(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "reconciliation.csv"
            first = {
                field: "" for field in reconciliation_runner.RECONCILIATION_FIELDS
            }
            first.update({"execution_id": "first", "reconciliation_status": "applied"})
            replacement = dict(first)
            replacement.update(
                {
                    "execution_id": "second",
                    "reconciliation_status": "pending_no_mutation",
                }
            )
            with patch.object(reconciliation_runner, "RECONCILIATION_REPORT", report):
                reconciliation_runner.upsert_reconciliation_row(first)
                reconciliation_runner.upsert_reconciliation_row(replacement)
                replacement["reconciliation_status"] = "applied"
                reconciliation_runner.upsert_reconciliation_row(replacement)
                rows = reconciliation_runner.read_csv(report)
        self.assertEqual([row["execution_id"] for row in rows], ["first", "second"])
        self.assertEqual(rows[1]["reconciliation_status"], "applied")

    def test_only_latest_applied_fill_is_current_state_anchor(self) -> None:
        rows = [
            {
                "execution_id": "older",
                "order_status": "filled",
                "canonical_state_applied": "yes",
                "fill_date": "2026-07-20",
            },
            {
                "execution_id": "cancelled",
                "order_status": "cancelled",
                "canonical_state_applied": "no",
                "fill_date": "",
            },
            {
                "execution_id": "latest",
                "order_status": "filled",
                "canonical_state_applied": "yes",
                "fill_date": "2026-09-03",
            },
        ]
        self.assertEqual(latest_applied_execution(rows)["execution_id"], "latest")


if __name__ == "__main__":
    unittest.main()
