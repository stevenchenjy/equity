from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from phase5r_sec_acceptance import build_acceptance_index, make_acceptance_record, write_acceptance_index
from phase5r_sec_acceptance_extensions import (
    ExtensionValidationError,
    extension_acceptance_records,
    load_extension_artifacts,
    load_extension_audit,
    plan_unindexed_current_records,
    raw_file_sha256,
    write_extension_admission_audit,
    write_extension_artifact,
)


def acceptance_record(
    *,
    accession: str,
    ticker: str = "TST",
    cik: str = "1",
    filing_date: str = "2026-07-24",
    accepted_at: str = "2026-07-24T20:30:45.000Z",
) -> dict[str, str]:
    return make_acceptance_record(
        accession_number=accession,
        ticker=ticker,
        cik=cik,
        filing_date=filing_date,
        accepted_at=accepted_at,
        source_url=f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
    )


class SecAcceptanceExtensionTests(unittest.TestCase):
    def _plan(
        self,
        *,
        historical_records: list[dict[str, str]],
        extensions: list[dict[str, object]],
        current_records: list[dict[str, str]],
        historical_index_sha256: str,
    ) -> tuple[list[dict[str, object]], int]:
        return plan_unindexed_current_records(
            historical_records=historical_records,
            extension_artifacts=extensions,
            current_records=current_records,
            forms_by_accession={
                record["accession_number"]: "10-Q" for record in current_records
            },
            expected_cik_by_ticker={"TST": "1"},
            expected_entity_by_ticker={"TST": "Test Issuer, Inc."},
            permitted_forms={"10-Q"},
            historical_index_sha256=historical_index_sha256,
            admitted_at="2026-07-25T12:00:00+00:00",
        )

    def test_valid_extension_preserves_historical_bytes_and_is_audit_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sec-extension-") as directory:
            root = Path(directory)
            historical_path = root / "immutable-index.json"
            extension_dir = root / "extensions"
            audit_path = root / "admission-audit.csv"
            historical = build_acceptance_index(
                new_records=[acceptance_record(accession="0000000001-26-000001")],
                generated_at="2026-07-25T12:00:00+00:00",
            )
            write_acceptance_index(historical, historical_path)
            before_historical = historical_path.read_bytes()
            historical_sha = raw_file_sha256(historical_path)
            current = acceptance_record(
                accession="0000000001-26-000002",
                accepted_at="2026-07-25T10:30:45.000Z",
                filing_date="2026-07-25",
            )

            planned, count = self._plan(
                historical_records=historical["records"],
                extensions=[],
                current_records=[current],
                historical_index_sha256=historical_sha,
            )
            self.assertEqual(count, 1)
            artifact_path = write_extension_artifact(planned[-1], directory=extension_dir)
            write_extension_admission_audit(
                planned,
                path=audit_path,
                directory=extension_dir,
            )
            before_second_audit_write = audit_path.read_bytes()
            write_extension_admission_audit(
                planned,
                path=audit_path,
                directory=extension_dir,
            )

            self.assertEqual(historical_path.read_bytes(), before_historical)
            self.assertEqual(audit_path.read_bytes(), before_second_audit_write)
            loaded = load_extension_artifacts(
                historical_index_sha256=historical_sha,
                directory=extension_dir,
            )
            self.assertEqual(extension_acceptance_records(loaded), [current])
            audit = load_extension_audit(audit_path)
            self.assertEqual(len(audit), 1)
            row = next(iter(audit.values()))
            self.assertEqual(row["extension_version"], "v1")
            self.assertEqual(row["entity_name"], "Test Issuer, Inc.")
            self.assertEqual(row["extension_artifact_sha256"], raw_file_sha256(artifact_path))
            self.assertEqual(
                row["prior_immutable_index_sha256"],
                historical_sha,
            )

    def test_duplicate_or_identity_conflict_is_rejected_without_extension_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sec-extension-") as directory:
            root = Path(directory)
            historical_path = root / "immutable-index.json"
            extension_dir = root / "extensions"
            historical = build_acceptance_index(
                generated_at="2026-07-25T12:00:00+00:00",
            )
            write_acceptance_index(historical, historical_path)
            current = acceptance_record(
                accession="0000000001-26-000002",
                accepted_at="2026-07-25T10:30:45.000Z",
                filing_date="2026-07-25",
            )
            with self.assertRaisesRegex(ExtensionValidationError, "duplicate"):
                self._plan(
                    historical_records=historical["records"],
                    extensions=[],
                    current_records=[current, copy.deepcopy(current)],
                    historical_index_sha256=raw_file_sha256(historical_path),
                )
            self.assertFalse(extension_dir.exists())

            with self.assertRaisesRegex(ExtensionValidationError, "identity"):
                plan_unindexed_current_records(
                    historical_records=historical["records"],
                    extension_artifacts=[],
                    current_records=[current],
                    forms_by_accession={current["accession_number"]: "10-Q"},
                    expected_cik_by_ticker={"TST": "2"},
                    expected_entity_by_ticker={"TST": "Test Issuer, Inc."},
                    permitted_forms={"10-Q"},
                    historical_index_sha256=raw_file_sha256(historical_path),
                    admitted_at="2026-07-25T12:00:00+00:00",
                )
            self.assertFalse(extension_dir.exists())

    def test_audit_raw_byte_binding_detects_artifact_rewrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sec-extension-") as directory:
            root = Path(directory)
            historical_path = root / "immutable-index.json"
            extension_dir = root / "extensions"
            audit_path = root / "admission-audit.csv"
            historical = build_acceptance_index(
                generated_at="2026-07-25T12:00:00+00:00",
            )
            write_acceptance_index(historical, historical_path)
            current = acceptance_record(
                accession="0000000001-26-000002",
                accepted_at="2026-07-25T10:30:45.000Z",
                filing_date="2026-07-25",
            )
            planned, count = self._plan(
                historical_records=historical["records"],
                extensions=[],
                current_records=[current],
                historical_index_sha256=raw_file_sha256(historical_path),
            )
            self.assertEqual(count, 1)
            artifact_path = write_extension_artifact(planned[-1], directory=extension_dir)
            write_extension_admission_audit(
                planned,
                path=audit_path,
                directory=extension_dir,
            )
            artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ExtensionValidationError, "audit"):
                write_extension_admission_audit(
                    planned,
                    path=audit_path,
                    directory=extension_dir,
                )


if __name__ == "__main__":
    unittest.main()
