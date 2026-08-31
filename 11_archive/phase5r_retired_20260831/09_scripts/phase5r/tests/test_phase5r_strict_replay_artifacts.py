from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import phase5r_strict_replay_artifacts as strict_artifacts
import prepare_phase5r_llm_replay_corpus as prepare


def replay_row(
    *,
    ticker: str = "AAA",
    cik: str = "1234567",
    accession: str = "0001234567-26-000001",
    form: str = "8-K",
) -> dict[str, str]:
    document = "aaa-20260701.htm"
    compact = accession.replace("-", "")
    return {
        "ticker": ticker,
        "cik": cik,
        "accession": accession,
        "form": form,
        "filing_date": "2026-07-01",
        "primary_document": document,
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{compact}/{document}"
        ),
        "index_url": (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{compact}/{accession}-index.html"
        ),
    }


def filing_index(
    row: dict[str, str], *, include_exhibit: bool = True
) -> bytes:
    compact = row["accession"].replace("-", "")
    exhibit = ""
    if include_exhibit:
        exhibit = (
            "<tr><td>2</td><td>Press release</td>"
            f'<td><a href="/Archives/edgar/data/{int(row["cik"])}/'
            f'{compact}/aaa-ex99-1.htm">aaa-ex99-1.htm</a></td>'
            "<td>EX-99.1</td><td>16</td></tr>"
        )
    return (
        '<table class="tableFile" summary="Document Format Files">'
        "<tr><th>Seq</th><th>Description</th><th>Document</th>"
        "<th>Type</th><th>Size</th></tr>"
        "<tr><td>1</td><td>Primary</td>"
        f'<td><a href="/Archives/edgar/data/{int(row["cik"])}/'
        f'{compact}/{row["primary_document"]}">'
        f'{row["primary_document"]}</a></td><td>{row["form"]}</td>'
        "<td>100</td></tr>"
        f"{exhibit}</table>"
    ).encode()


def context_for(
    fetcher: prepare.Fetcher,
) -> strict_artifacts.AcquisitionContext:
    return strict_artifacts.AcquisitionContext(
        user_agent="strict-artifact-test test@example.com",
        limiter=prepare.RequestLimiter(
            2.0,
            clock=lambda: 1.0,
            sleeper=lambda _: None,
        ),
        fetcher=fetcher,
    )


class StrictReplayArtifactTests(unittest.TestCase):
    def test_exhibit_manifest_is_exact_and_idempotent(self) -> None:
        row = replay_row()
        index_raw = filing_index(row)

        def fetcher(
            url: str, user_agent: str, maximum_bytes: int
        ) -> prepare.HttpResult:
            del user_agent, maximum_bytes
            return prepare.HttpResult(
                raw_bytes=b"official exhibit",
                content_type="text/html",
                final_url=url,
            )

        with tempfile.TemporaryDirectory() as directory_name:
            corpus = Path(directory_name) / "corpus"
            context = context_for(fetcher)
            with prepare.storage_budget_scope(corpus, 1_000_000):
                first = strict_artifacts.materialize_exhibit_manifest(
                    context=context,
                    corpus_root=corpus,
                    row=row,
                    index_raw=index_raw,
                    index_sha256=prepare.sha256_bytes(index_raw),
                )
                request_count = context.request_count
                second = strict_artifacts.materialize_exhibit_manifest(
                    context=context,
                    corpus_root=corpus,
                    row=row,
                    index_raw=index_raw,
                    index_sha256=prepare.sha256_bytes(index_raw),
                )
            self.assertTrue(first["verified"])
            self.assertTrue(second["verified"])
            self.assertEqual(request_count, 1)
            self.assertEqual(context.request_count, request_count)

    def test_rejects_hash_valid_empty_manifest_when_index_has_exhibit(
        self,
    ) -> None:
        row = replay_row()
        index_raw = filing_index(row)
        with tempfile.TemporaryDirectory() as directory_name:
            corpus = Path(directory_name) / "corpus"
            directory = (
                prepare.filing_paths(corpus, row)["directory"] / "exhibits"
            )
            directory.mkdir(parents=True)
            document_rows = strict_artifacts.parse_filing_index_documents(
                index_raw, cik=row["cik"], accession=row["accession"]
            )
            payload = {
                "schema_version": (
                    strict_artifacts.EXHIBIT_MANIFEST_SCHEMA_VERSION
                ),
                "parser_version": strict_artifacts.INDEX_PARSER_VERSION,
                "ticker": row["ticker"],
                "cik": row["cik"],
                "accession": row["accession"],
                "source_filing_index_sha256": prepare.sha256_bytes(index_raw),
                "source_document_table_sha256": prepare.canonical_sha256(
                    document_rows
                ),
                "source_document_count": len(document_rows),
                "discovered_exhibit_count": 0,
                "discovery_complete": True,
                "documents": [],
            }
            payload["manifest_sha256"] = prepare.canonical_sha256(payload)
            manifest = directory / "exhibit_manifest.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            result = strict_artifacts.validate_exhibit_manifest(
                manifest_path=manifest,
                exhibit_directory=directory,
                corpus_root=corpus,
                row=row,
                index_raw=index_raw,
                index_sha256=prepare.sha256_bytes(index_raw),
            )
            self.assertFalse(result["verified"])
            self.assertGreater(
                result["invalid_or_missing_file_count"], 0
            )

    def test_xbrl_reconciliation_filters_future_and_other_accessions(
        self,
    ) -> None:
        row = replay_row(form="10-Q")
        primary = (
            b'<ix:nonFraction name="us-gaap:Revenue">1</ix:nonFraction>'
        )
        records = [
            {
                "start": "2026-01-01",
                "end": "2026-06-30",
                "val": 10,
                "accn": row["accession"],
                "filed": "2026-07-01",
                "form": "10-Q",
                "fy": 2026,
                "fp": "Q2",
            },
            {
                "start": "2026-01-01",
                "end": "2026-06-30",
                "val": 11,
                "accn": "0001234567-26-000002",
                "filed": "2026-07-02",
                "form": "10-Q",
                "fy": 2026,
                "fp": "Q2",
            },
            {
                "start": "2025-01-01",
                "end": "2025-06-30",
                "val": 8,
                "accn": "0001234567-25-000001",
                "filed": "2025-07-01",
                "form": "10-Q",
                "fy": 2025,
                "fp": "Q2",
            },
        ]
        raw = json.dumps(
            {
                "cik": int(row["cik"]),
                "facts": {
                    "us-gaap": {
                        "Revenue": {
                            "label": "Revenue",
                            "units": {"USD": records},
                        }
                    }
                },
            },
            sort_keys=True,
        ).encode()
        payload = strict_artifacts.build_xbrl_reconciliation(
            row=row,
            accepted_at_et="2026-07-01T17:00:00-04:00",
            primary_raw=primary,
            companyfacts_raw=raw,
        )
        self.assertEqual(payload["matching_fact_count"], 1)
        self.assertEqual(payload["excluded_future_record_count"], 1)
        self.assertEqual(payload["excluded_other_accession_record_count"], 1)
        with tempfile.TemporaryDirectory() as directory_name:
            path = Path(directory_name) / "reconciliation.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            valid = strict_artifacts.validate_xbrl_reconciliation(
                path=path,
                row=row,
                accepted_at_et="2026-07-01T17:00:00-04:00",
                primary_raw=primary,
                companyfacts_raw=raw,
            )
            self.assertTrue(valid["verified"])
            payload["facts"][0]["val"] = 999
            path.write_text(json.dumps(payload), encoding="utf-8")
            invalid = strict_artifacts.validate_xbrl_reconciliation(
                path=path,
                row=row,
                accepted_at_et="2026-07-01T17:00:00-04:00",
                primary_raw=primary,
                companyfacts_raw=raw,
            )
            self.assertFalse(invalid["verified"])

    def test_submission_snapshot_identity_and_storage_cap(self) -> None:
        row = replay_row()
        raw = json.dumps(
            {
                "cik": row["cik"],
                "filings": {"recent": {"accessionNumber": []}},
            }
        ).encode()

        def fetcher(
            url: str, user_agent: str, maximum_bytes: int
        ) -> prepare.HttpResult:
            del user_agent, maximum_bytes
            return prepare.HttpResult(
                raw_bytes=raw,
                content_type="application/json",
                final_url=url,
            )

        with tempfile.TemporaryDirectory() as directory_name:
            corpus = Path(directory_name) / "corpus"
            context = context_for(fetcher)
            with prepare.storage_budget_scope(corpus, 1_000_000):
                result = strict_artifacts.materialize_submission_snapshot(
                    context=context,
                    corpus_root=corpus,
                    ticker=row["ticker"],
                    cik=row["cik"],
                )
            self.assertTrue(result["verified"])
            paths = strict_artifacts.submission_paths(
                corpus, row["cik"]
            )
            metadata = json.loads(paths["metadata"].read_text())
            metadata["ticker"] = "WRONG"
            paths["metadata"].write_text(json.dumps(metadata))
            invalid = strict_artifacts.validate_submission_snapshot(
                raw_path=paths["raw"],
                metadata_path=paths["metadata"],
                ticker=row["ticker"],
                cik=row["cik"],
            )
            self.assertFalse(invalid["verified"])

        with tempfile.TemporaryDirectory() as directory_name:
            corpus = Path(directory_name) / "corpus"
            context = context_for(fetcher)
            with self.assertRaises(prepare.CorpusError):
                with prepare.storage_budget_scope(corpus, 8):
                    strict_artifacts.materialize_submission_snapshot(
                        context=context,
                        corpus_root=corpus,
                        ticker=row["ticker"],
                        cik=row["cik"],
                    )
            self.assertFalse(
                strict_artifacts.submission_paths(
                    corpus, row["cik"]
                )["raw"].exists()
            )


if __name__ == "__main__":
    unittest.main()
