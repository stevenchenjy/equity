from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import refresh_phase5r_sec_filing_artifacts as artifacts


LEDGER_FIELDS = [
    "detected_at",
    "cycle_date",
    "ticker",
    "cik",
    "form",
    "filing_date",
    "accession_number",
    "items",
    "primary_document",
    "source_url",
    "metadata_sha256",
    "is_new",
    "baseline_record",
    "materiality",
    "material_event",
    "review_required",
]


def ledger_row(
    *,
    ticker: str = "TEST",
    cik: str = "1234567",
    form: str = "10-Q",
    filing_date: str = "2026-07-01",
    accession: str = "0001234567-26-000001",
    document: str = "test-20260701.htm",
    detected_at: str = "2026-07-02T12:00:00+00:00",
    is_new: str = "no",
    material_event: str = "no",
) -> dict[str, str]:
    compact = accession.replace("-", "")
    return {
        "detected_at": detected_at,
        "cycle_date": "2026-07-02",
        "ticker": ticker,
        "cik": cik,
        "form": form,
        "filing_date": filing_date,
        "accession_number": accession,
        "items": "",
        "primary_document": document,
        "source_url": (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{compact}/{document}"
        ),
        "metadata_sha256": "0" * 64,
        "is_new": is_new,
        "baseline_record": "no",
        "materiality": "high" if material_event == "yes" else "medium",
        "material_event": material_event,
        "review_required": material_event,
    }


def write_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class NormalizationTests(unittest.TestCase):
    def test_html_normalization_is_deterministic_and_visible_only(self) -> None:
        raw = b"""
        <html><head>
          <style>.hidden { display:none }</style>
          <script>secret_script()</script>
        </head><body>
          <h1>A&nbsp;B</h1>
          <p>Alpha    beta</p>
          <div>Gamma<br/>Delta</div>
          <ix:hidden>hidden inline xbrl</ix:hidden>
        </body></html>
        """
        first = artifacts.normalize_document(raw, "text/html", "utf-8")
        second = artifacts.normalize_document(raw, "text/html", "utf-8")
        self.assertEqual(first, "A B\nAlpha beta\nGamma\nDelta")
        self.assertEqual(first, second)
        self.assertEqual(
            artifacts.sha256_text(first),
            artifacts.sha256_text(second),
        )

    def test_chunk_offsets_and_hashes_are_repeatable(self) -> None:
        text = "abcdefghijklmnopqrstuvwxyz"
        expected_ranges = [(0, 10), (8, 18), (16, 26)]
        first = artifacts.build_chunks(text, max_chars=10, overlap=2)
        second = artifacts.build_chunks(text, max_chars=10, overlap=2)
        self.assertEqual(first, second)
        self.assertEqual(
            [(row["char_start"], row["char_end"]) for row in first],
            expected_ranges,
        )
        for row in first:
            content = text[row["char_start"] : row["char_end"]]
            self.assertEqual(row["sha256"], artifacts.sha256_text(content))


class SelectionAndValidationTests(unittest.TestCase):
    def test_latest_date_ties_and_all_new_material_are_selected(self) -> None:
        rows = [
            ledger_row(
                ticker="AAA",
                filing_date="2026-06-01",
                accession="0001234567-26-000001",
                document="aaa-old.htm",
            ),
            ledger_row(
                ticker="AAA",
                filing_date="2026-07-01",
                accession="0001234567-26-000002",
                document="aaa-latest-q.htm",
            ),
            ledger_row(
                ticker="AAA",
                form="8-K",
                filing_date="2026-07-01",
                accession="0001234567-26-000003",
                document="aaa-latest-k.htm",
            ),
            ledger_row(
                ticker="AAA",
                filing_date="2026-05-01",
                accession="0001234567-26-000004",
                document="aaa-material.htm",
                is_new="yes",
                material_event="yes",
            ),
            ledger_row(
                ticker="BBB",
                cik="2345678",
                filing_date="2026-06-15",
                accession="0002345678-26-000001",
                document="bbb.htm",
            ),
        ]
        selected = artifacts.select_filing_rows(rows)
        identities = {
            (row["ticker"], row["accession"]) for row in selected
        }
        self.assertEqual(
            identities,
            {
                ("AAA", "0001234567-26-000002"),
                ("AAA", "0001234567-26-000003"),
                ("AAA", "0001234567-26-000004"),
                ("BBB", "0002345678-26-000001"),
            },
        )

    def test_sec_host_and_path_are_fail_closed(self) -> None:
        valid = ledger_row()
        artifacts.normalize_ledger_row(valid)

        evil_host = dict(valid)
        evil_host["source_url"] = evil_host["source_url"].replace(
            "www.sec.gov", "www.sec.gov.example.com"
        )
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.normalize_ledger_row(evil_host)

        traversal = dict(valid)
        traversal["source_url"] = traversal["source_url"].replace(
            "test-20260701.htm", "%2e%2e%2fsecret.htm"
        )
        traversal["primary_document"] = "secret.htm"
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.normalize_ledger_row(traversal)

        unsafe_ticker = dict(valid)
        unsafe_ticker["ticker"] = "../TEST"
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.normalize_ledger_row(unsafe_ticker)


class CacheTests(unittest.TestCase):
    def test_second_refresh_uses_verified_cache_without_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            project_root = Path(directory_name)
            ledger_path = (
                project_root
                / "03_source_data"
                / "phase5r"
                / "phase5r_daily_evidence_ledger.csv"
            )
            artifact_root = project_root / "02_filings" / "phase5r_daily"
            index_path = (
                project_root
                / "03_source_data"
                / "phase5r"
                / "phase5r_sec_filing_artifact_index.json"
            )
            write_ledger(ledger_path, [ledger_row()])
            calls: list[str] = []

            def fake_fetch(url: str, user_agent: str, max_bytes: int) -> artifacts.FetchResult:
                self.assertIn("sec.gov", url)
                self.assertEqual(user_agent, "UnitTest/1.0 test@example.com")
                self.assertEqual(max_bytes, artifacts.MAX_RAW_BYTES)
                calls.append(url)
                return artifacts.FetchResult(
                    b"<html><body><h1>Quarterly report</h1><p>Revenue grew.</p></body></html>",
                    "text/html",
                    "utf-8",
                )

            first = artifacts.refresh_artifacts(
                ledger_path=ledger_path,
                artifact_root=artifact_root,
                index_path=index_path,
                project_root=project_root,
                fetcher=fake_fetch,
                user_agent="UnitTest/1.0 test@example.com",
            )
            self.assertEqual(first["network_fetch_count"], 1)
            self.assertEqual(first["cache_hit_count"], 0)
            self.assertEqual(len(calls), 1)

            def forbidden_fetch(
                url: str, user_agent: str, max_bytes: int
            ) -> artifacts.FetchResult:
                del url, user_agent, max_bytes
                raise AssertionError("verified cache must prevent network fetch")

            second = artifacts.refresh_artifacts(
                ledger_path=ledger_path,
                artifact_root=artifact_root,
                index_path=index_path,
                project_root=project_root,
                fetcher=forbidden_fetch,
                user_agent="UnitTest/1.0 test@example.com",
            )
            self.assertEqual(second["network_fetch_count"], 0)
            self.assertEqual(second["cache_hit_count"], 1)
            entry = second["artifacts"][0]
            raw_path = project_root / entry["raw_path"]
            normalized_path = project_root / entry["normalized_path"]
            self.assertEqual(
                artifacts.sha256_bytes(raw_path.read_bytes()),
                entry["raw_sha256"],
            )
            normalized_text = normalized_path.read_text(encoding="utf-8")
            self.assertEqual(
                artifacts.sha256_text(normalized_text),
                entry["normalized_sha256"],
            )
            self.assertEqual(
                artifacts.build_chunks(normalized_text),
                entry["chunks"],
            )
            on_disk = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["artifacts"][0]["cache_status"], "hit")
            self.assertFalse(list(index_path.parent.glob(f".{index_path.name}.*")))

            normalized_path.write_text("tampered", encoding="utf-8")
            reparsed = artifacts.refresh_artifacts(
                ledger_path=ledger_path,
                artifact_root=artifact_root,
                index_path=index_path,
                project_root=project_root,
                fetcher=forbidden_fetch,
                user_agent="UnitTest/1.0 test@example.com",
            )
            self.assertEqual(reparsed["network_fetch_count"], 0)
            self.assertEqual(reparsed["cache_hit_count"], 0)
            self.assertEqual(reparsed["reparsed_count"], 1)
            repaired_entry = reparsed["artifacts"][0]
            repaired_text = normalized_path.read_text(encoding="utf-8")
            self.assertNotEqual(repaired_text, "tampered")
            self.assertEqual(
                artifacts.sha256_text(repaired_text),
                repaired_entry["normalized_sha256"],
            )

    def test_check_reports_missing_cache_without_network_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            project_root = Path(directory_name)
            ledger_path = project_root / "ledger.csv"
            artifact_root = project_root / "filings"
            index_path = project_root / "index.json"
            write_ledger(ledger_path, [ledger_row()])
            summary = artifacts.check_artifacts(
                ledger_path=ledger_path,
                artifact_root=artifact_root,
                index_path=index_path,
                project_root=project_root,
            )
            self.assertEqual(
                summary,
                {
                    "selected": 1,
                    "complete_cache": 0,
                    "reparsable_cache": 0,
                    "missing_cache": 1,
                },
            )
            self.assertFalse(index_path.exists())
            self.assertFalse(artifact_root.exists())

    def test_unsupported_content_type_and_size_cap_fail_closed(self) -> None:
        row = artifacts.normalize_ledger_row(ledger_row())
        with tempfile.TemporaryDirectory() as directory_name:
            project_root = Path(directory_name)
            _, raw_path, text_path = artifacts.artifact_paths(
                project_root / "filings", row
            )
            with self.assertRaises(artifacts.ArtifactError):
                artifacts.build_entry(
                    row,
                    artifacts.FetchResult(b"{}", "application/json", "utf-8"),
                    raw_path=raw_path,
                    text_path=text_path,
                    project_root=project_root,
                    fetched_at="2026-07-24T00:00:00+00:00",
                    cache_status="fetched",
                )
            with self.assertRaises(artifacts.ArtifactError):
                artifacts.build_entry(
                    row,
                    artifacts.FetchResult(
                        b"x" * (artifacts.MAX_RAW_BYTES + 1),
                        "text/plain",
                        "utf-8",
                    ),
                    raw_path=raw_path,
                    text_path=text_path,
                    project_root=project_root,
                    fetched_at="2026-07-24T00:00:00+00:00",
                    cache_status="fetched",
                )


if __name__ == "__main__":
    unittest.main()
