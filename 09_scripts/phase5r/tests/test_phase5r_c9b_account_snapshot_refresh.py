from __future__ import annotations

import unittest

from _support import SCRIPT_DIR  # noqa: F401
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


if __name__ == "__main__":
    unittest.main()
