from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from phase5r_sec_acceptance import (
    AcceptanceIndexError,
    acceptance_map,
    build_acceptance_index,
    make_acceptance_record,
    normalize_acceptance_timestamp,
    validate_acceptance_index,
    write_acceptance_index,
)
from refresh_phase5r_daily_evidence import recent_filings


def record(
    *,
    accession: str = "0000000001-26-000001",
    accepted_at: str = "2026-07-24T20:30:45.000Z",
) -> dict[str, str]:
    return make_acceptance_record(
        accession_number=accession,
        ticker="TST",
        cik="1",
        filing_date="2026-07-24",
        accepted_at=accepted_at,
        source_url="https://data.sec.gov/submissions/CIK0000000001.json",
    )


class SecAcceptanceTests(unittest.TestCase):
    def test_sec_timestamp_is_timezone_aware_and_normalized(self) -> None:
        self.assertEqual(
            normalize_acceptance_timestamp("2026-07-24T20:30:45.000Z"),
            "2026-07-24T20:30:45.000+00:00",
        )
        with self.assertRaisesRegex(AcceptanceIndexError, "timezone"):
            normalize_acceptance_timestamp("2026-07-24T20:30:45")

    def test_index_round_trip_is_hash_validated(self) -> None:
        payload = build_acceptance_index(
            new_records=[record()],
            generated_at="2026-07-24T21:00:00+00:00",
        )
        self.assertEqual(validate_acceptance_index(payload), payload)
        with tempfile.TemporaryDirectory(prefix="phase5r-sec-acceptance-") as directory:
            path = Path(directory) / "index.json"
            write_acceptance_index(payload, path)
            self.assertEqual(
                acceptance_map(path)["0000000001-26-000001"]["accepted_at"],
                "2026-07-24T20:30:45.000+00:00",
            )

    def test_tampered_record_hash_is_rejected(self) -> None:
        payload = build_acceptance_index(
            new_records=[record()],
            generated_at="2026-07-24T21:00:00+00:00",
        )
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["accepted_at"] = "2026-07-24T20:31:45.000+00:00"
        with self.assertRaisesRegex(AcceptanceIndexError, "hash|normalization"):
            validate_acceptance_index(tampered)

    def test_conflicting_duplicate_accession_is_rejected(self) -> None:
        first = record()
        second = make_acceptance_record(
            accession_number=first["accession_number"],
            ticker="ALT",
            cik="1",
            filing_date="2026-07-24",
            accepted_at="2026-07-24T20:30:45.000Z",
            source_url="https://data.sec.gov/submissions/CIK0000000001.json",
        )
        with self.assertRaisesRegex(AcceptanceIndexError, "conflicting"):
            build_acceptance_index(
                new_records=[first, second],
                generated_at="2026-07-24T21:00:00+00:00",
            )

    def test_future_record_is_rejected(self) -> None:
        with self.assertRaisesRegex(AcceptanceIndexError, "later"):
            build_acceptance_index(
                new_records=[record()],
                generated_at="2026-07-24T20:00:00+00:00",
            )

    def test_official_acceptance_can_precede_filing_date_over_weekend(self) -> None:
        weekend_record = make_acceptance_record(
            accession_number="0000000001-26-000002",
            ticker="TST",
            cik="1",
            filing_date="2026-07-27",
            accepted_at="2026-07-24T23:30:00.000Z",
            source_url="https://data.sec.gov/submissions/CIK0000000001.json",
        )
        self.assertEqual(weekend_record["filing_date"], "2026-07-27")

    def test_implausible_acceptance_filing_gap_is_rejected(self) -> None:
        with self.assertRaisesRegex(AcceptanceIndexError, "implausibly"):
            make_acceptance_record(
                accession_number="0000000001-26-000003",
                ticker="TST",
                cik="1",
                filing_date="2026-07-24",
                accepted_at="2026-07-01T20:30:45.000Z",
                source_url="https://data.sec.gov/submissions/CIK0000000001.json",
            )

    def test_submissions_parser_captures_exact_acceptance_time(self) -> None:
        payload = {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000000001-26-000001"],
                    "form": ["10-Q"],
                    "filingDate": ["2026-07-24"],
                    "acceptanceDateTime": ["2026-07-24T20:30:45.000Z"],
                    "items": [""],
                    "primaryDocument": ["test.htm"],
                }
            }
        }
        rows = recent_filings(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["accepted_at"], "2026-07-24T20:30:45.000+00:00"
        )


if __name__ == "__main__":
    unittest.main()
