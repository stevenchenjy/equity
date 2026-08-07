from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phase5r_sec_acceptance import (
    AcceptanceReconciliationError,
    build_acceptance_index,
    load_immutable_acceptance_index,
    load_acceptance_reconciliation_log,
    make_acceptance_record,
    reconcile_current_acceptance_records,
    write_acceptance_index,
    write_acceptance_reconciliation_log,
)


def acceptance_record(
    *,
    accession: str = "0000000001-26-000001",
    ticker: str = "TST",
    accepted_at: str = "2026-07-24T20:30:45.000Z",
) -> dict[str, str]:
    return make_acceptance_record(
        accession_number=accession,
        ticker=ticker,
        cik="1",
        filing_date="2026-07-24",
        accepted_at=accepted_at,
        source_url="https://data.sec.gov/submissions/CIK0000000001.json",
    )


class SecAcceptanceReconciliationTests(unittest.TestCase):
    def _reconcile(
        self,
        historical: dict[str, str],
        current: dict[str, str],
    ) -> list[dict[str, str]]:
        return reconcile_current_acceptance_records(
            historical_records=[historical],
            current_records=[current],
            reconciled_at="2026-07-25T12:00:00+00:00",
        )

    def test_eastern_wall_clock_shift_is_audited_and_index_stays_unchanged(self) -> None:
        historical = acceptance_record()
        current = acceptance_record(accepted_at="2026-07-24T16:30:45.000Z")
        rows = self._reconcile(historical, current)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            row["reconciliation_decision"],
            "eastern_wall_clock_representation_equivalent",
        )
        self.assertEqual(row["detected_offset_seconds"], "-14400")
        self.assertEqual(row["original_timestamp"], historical["accepted_at"])
        self.assertEqual(row["normalized_timestamp"], current["accepted_at"])

        with tempfile.TemporaryDirectory(prefix="phase5r-sec-reconcile-") as directory:
            root = Path(directory)
            index_path = root / "immutable-index.json"
            log_path = root / "reconciliation.csv"
            index = build_acceptance_index(
                new_records=[historical],
                generated_at="2026-07-25T12:00:00+00:00",
            )
            write_acceptance_index(index, index_path)
            before_index = index_path.read_bytes()
            write_acceptance_reconciliation_log(rows, log_path)
            before_second_write = log_path.read_bytes()
            write_acceptance_reconciliation_log(rows, log_path)
            self.assertEqual(index_path.read_bytes(), before_index)
            self.assertEqual(log_path.read_bytes(), before_second_write)
            stored = load_acceptance_reconciliation_log(log_path)
            self.assertEqual(len(stored), 1)
            self.assertEqual(
                next(iter(stored.values()))["reconciliation_decision"],
                "eastern_wall_clock_representation_equivalent",
            )

    def test_winter_eastern_wall_clock_shift_requires_standard_offset(self) -> None:
        historical = make_acceptance_record(
            accession_number="0000000001-26-000002",
            ticker="TST",
            cik="1",
            filing_date="2026-01-15",
            accepted_at="2026-01-15T20:30:45.000Z",
            source_url="https://data.sec.gov/submissions/CIK0000000001.json",
        )
        current = make_acceptance_record(
            accession_number="0000000001-26-000002",
            ticker="TST",
            cik="1",
            filing_date="2026-01-15",
            accepted_at="2026-01-15T15:30:45.000Z",
            source_url="https://data.sec.gov/submissions/CIK0000000001.json",
        )
        rows = reconcile_current_acceptance_records(
            historical_records=[historical],
            current_records=[current],
            reconciled_at="2026-01-16T12:00:00+00:00",
        )
        self.assertEqual(rows[0]["detected_offset_seconds"], "-18000")
        self.assertEqual(
            rows[0]["reconciliation_decision"],
            "eastern_wall_clock_representation_equivalent",
        )

    def test_same_utc_instant_with_different_timezone_notation_is_reconciled(self) -> None:
        historical = acceptance_record()
        current = acceptance_record(accepted_at="2026-07-24T16:30:45.000-04:00")
        rows = self._reconcile(historical, current)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detected_offset_seconds"], "0")
        self.assertEqual(
            rows[0]["reconciliation_decision"], "canonical_utc_equivalent"
        )

    def test_unknown_accession_is_never_silently_accepted(self) -> None:
        with self.assertRaisesRegex(AcceptanceReconciliationError, "absent"):
            self._reconcile(
                acceptance_record(),
                acceptance_record(accession="0000000001-26-000002"),
            )

    def test_missing_immutable_index_cannot_be_bootstrapped_by_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sec-reconcile-") as directory:
            missing_path = Path(directory) / "missing-index.json"
            with self.assertRaisesRegex(AcceptanceReconciliationError, "missing"):
                load_immutable_acceptance_index(missing_path)

    def test_identity_mismatch_is_never_reconciled_as_a_time_difference(self) -> None:
        with self.assertRaisesRegex(AcceptanceReconciliationError, "identity"):
            self._reconcile(
                acceptance_record(),
                acceptance_record(ticker="ALT"),
            )

    def test_arbitrary_timestamp_shift_is_rejected(self) -> None:
        with self.assertRaisesRegex(AcceptanceReconciliationError, "permitted"):
            self._reconcile(
                acceptance_record(),
                acceptance_record(accepted_at="2026-07-24T19:30:45.000Z"),
            )

    def test_invalid_batch_never_partially_appends_to_log(self) -> None:
        historical = acceptance_record()
        current = acceptance_record(accepted_at="2026-07-24T16:30:45.000Z")
        valid = self._reconcile(historical, current)[0]
        invalid = dict(valid)
        invalid["reconciliation_decision"] = "not-authorized"
        with tempfile.TemporaryDirectory(prefix="phase5r-sec-reconcile-") as directory:
            path = Path(directory) / "reconciliation.csv"
            with self.assertRaisesRegex(AcceptanceReconciliationError, "decision"):
                write_acceptance_reconciliation_log([valid, invalid], path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
