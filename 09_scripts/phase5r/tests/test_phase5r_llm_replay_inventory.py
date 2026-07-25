from __future__ import annotations

import csv
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import inventory_phase5r_llm_replay_corpus as inventory
import prepare_phase5r_llm_replay_corpus as prepare
from phase5r_sec_acceptance import (
    build_acceptance_index,
    make_acceptance_record,
)


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
    index: int,
    *,
    ticker: str,
    cik: str,
    form: str,
    items: str,
    year: int,
) -> dict[str, str]:
    filing_day = date(year, 7, 1) + timedelta(days=index)
    accession = f"{int(cik):010d}-26-{index + 1:06d}"
    compact = accession.replace("-", "")
    document = f"{ticker.lower()}-{filing_day:%Y%m%d}-{index}.htm"
    return {
        "detected_at": f"{filing_day.isoformat()}T18:00:00-04:00",
        "cycle_date": filing_day.isoformat(),
        "ticker": ticker,
        "cik": cik,
        "form": form,
        "filing_date": filing_day.isoformat(),
        "accession_number": accession,
        "items": items,
        "primary_document": document,
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{compact}/{document}"
        ),
        "metadata_sha256": f"{index + 1:064x}",
        "is_new": "no",
        "baseline_record": "yes",
        "materiality": "high",
        "material_event": "no",
        "review_required": "no",
    }


def write_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_acceptance_index(
    path: Path, rows: list[dict[str, str]]
) -> None:
    records = [
        make_acceptance_record(
            accession_number=row["accession_number"],
            ticker=row["ticker"],
            cik=row["cik"],
            filing_date=row["filing_date"],
            accepted_at=f"{row['filing_date']}T21:00:00+00:00",
            source_url=(
                "https://data.sec.gov/submissions/"
                f"CIK{int(row['cik']):010d}.json"
            ),
        )
        for row in rows
    ]
    payload = build_acceptance_index(
        new_records=records,
        generated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def normalized_row(raw: dict[str, str]) -> dict[str, str]:
    return prepare.normalize_ledger_row(raw)


def write_corpus_sec_sources(
    corpus_root: Path,
    project_root: Path,
    raw_row: dict[str, str],
    *,
    include_primary: bool,
) -> None:
    row = normalized_row(raw_row)
    paths = prepare.filing_paths(corpus_root, row)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    primary = f"primary:{row['accession']}".encode()
    filing_index = f"index:{row['accession']}".encode()
    if include_primary:
        paths["primary"].write_bytes(primary)
    paths["index"].write_bytes(filing_index)
    metadata = {
        "ticker": row["ticker"],
        "cik": row["cik"],
        "accession": row["accession"],
        "primary_url": row["source_url"],
        "index_url": row["index_url"],
        "primary_raw_sha256": prepare.sha256_bytes(primary),
        "index_raw_sha256": prepare.sha256_bytes(filing_index),
    }
    paths["metadata"].write_text(
        json.dumps(metadata, sort_keys=True), encoding="utf-8"
    )


def write_daily_primary(
    project_root: Path,
    index_path: Path,
    raw_row: dict[str, str],
    ledger_sha256: str,
) -> None:
    raw_path = (
        project_root
        / "02_filings"
        / "phase5r_daily"
        / raw_row["ticker"]
        / raw_row["accession_number"]
        / "primary_document.raw"
    )
    normalized_path = raw_path.with_name("normalized_text.txt")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw = f"daily:{raw_row['accession_number']}".encode()
    raw_path.write_bytes(raw)
    normalized_path.write_text("normalized", encoding="utf-8")
    payload = {
        "schema_version": "phase5r_sec_filing_artifact_index_v1",
        "ledger_sha256": ledger_sha256,
        "artifacts": [
            {
                "accession": raw_row["accession_number"],
                "ticker": raw_row["ticker"],
                "cik": raw_row["cik"],
                "primary_document": raw_row["primary_document"],
                "url": raw_row["source_url"],
                "raw_path": raw_path.relative_to(project_root).as_posix(),
                "raw_sha256": prepare.sha256_bytes(raw),
                "normalized_path": normalized_path.relative_to(
                    project_root
                ).as_posix(),
            }
        ],
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload), encoding="utf-8")


def write_xbrl_source(
    corpus_root: Path, raw_row: dict[str, str]
) -> None:
    directory = corpus_root / "xbrl" / raw_row["ticker"]
    directory.mkdir(parents=True, exist_ok=True)
    raw = b'{"facts":{}}'
    (directory / "companyfacts.raw.json").write_bytes(raw)
    (directory / "source_metadata.json").write_text(
        json.dumps(
            {
                "ticker": raw_row["ticker"],
                "cik": raw_row["cik"],
                "raw_sha256": prepare.sha256_bytes(raw),
            }
        ),
        encoding="utf-8",
    )
    row = normalized_row(raw_row)
    primary = f"primary:{row['accession']}".encode()
    reconciliation_path = (
        prepare.filing_paths(corpus_root, row)["directory"]
        / "xbrl_reconciliation.json"
    )
    reconciliation_path.write_text(
        json.dumps(
            {
                "ticker": row["ticker"],
                "cik": row["cik"],
                "accession": row["accession"],
                "source_primary_sha256": prepare.sha256_bytes(primary),
                "future_facts_excluded": True,
            }
        ),
        encoding="utf-8",
    )


def write_exhibit_manifest(
    corpus_root: Path,
    raw_row: dict[str, str],
) -> None:
    row = normalized_row(raw_row)
    directory = prepare.filing_paths(corpus_root, row)["directory"] / "exhibits"
    directory.mkdir(parents=True, exist_ok=True)
    exhibit = directory / "ex99-1.htm"
    raw = b"official exhibit"
    exhibit.write_bytes(raw)
    (directory / "exhibit_manifest.json").write_text(
        json.dumps(
            {
                "accession": row["accession"],
                "discovery_complete": True,
                "source_filing_index_sha256": prepare.sha256_bytes(
                    f"index:{row['accession']}".encode()
                ),
                "documents": [
                    {
                        "relative_path": exhibit.relative_to(
                            corpus_root
                        ).as_posix(),
                        "sha256": prepare.sha256_bytes(raw),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def write_market_manifest(
    corpus_root: Path,
    rows: list[dict[str, str]],
) -> None:
    sources = []
    for ticker in sorted({row["ticker"] for row in rows}):
        ticker_rows = [row for row in rows if row["ticker"] == ticker]
        start = min(date.fromisoformat(row["filing_date"]) for row in ticker_rows)
        end = max(date.fromisoformat(row["filing_date"]) for row in ticker_rows)
        relative = Path("market") / ticker / "history.raw.json"
        raw_path = corpus_root / relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw = f"market:{ticker}".encode()
        raw_path.write_bytes(raw)
        sources.append(
            {
                "ticker": ticker,
                "relative_path": relative.as_posix(),
                "raw_sha256": prepare.sha256_bytes(raw),
                "coverage_start": start.isoformat(),
                "coverage_end_exclusive": (
                    end + timedelta(days=21)
                ).isoformat(),
            }
        )
    (corpus_root / "manifest.json").write_text(
        json.dumps({"market_sources": sources}), encoding="utf-8"
    )


def write_submission_snapshots(
    corpus_root: Path, rows: list[dict[str, str]]
) -> None:
    by_identity = {
        (row["ticker"], row["cik"]): row for row in rows
    }
    for (ticker, cik), _ in by_identity.items():
        directory = (
            corpus_root / "sec_submissions" / f"CIK{int(cik):010d}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        raw = f"submissions:{ticker}:{cik}".encode()
        (directory / "submissions.raw.json").write_bytes(raw)
        (directory / "source_metadata.json").write_text(
            json.dumps(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "url": (
                        "https://data.sec.gov/submissions/"
                        f"CIK{int(cik):010d}.json"
                    ),
                    "raw_sha256": prepare.sha256_bytes(raw),
                }
            ),
            encoding="utf-8",
        )


def tree_fingerprint(root: Path) -> tuple[set[str], dict[str, tuple[str, int]]]:
    directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir()
    }
    files = {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
        if path.is_file()
    }
    return directories, files


class InventoryContentTests(unittest.TestCase):
    @staticmethod
    def _complete_stage_records(
        packet_count: int,
        issuer_count: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "cik": str((index % issuer_count) + 1),
                "locally_complete": True,
                "acceptance": {"present": True},
            }
            for index in range(packet_count)
        ]

    def test_qualification_readiness_enforces_packet_and_issuer_floors(
        self,
    ) -> None:
        cases = (
            (249, 20, False),
            (250, 19, False),
            (250, 20, True),
        )
        for packet_count, issuer_count, expected in cases:
            with self.subTest(
                packet_count=packet_count,
                issuer_count=issuer_count,
            ):
                result = inventory._stage_summary(
                    self._complete_stage_records(
                        packet_count,
                        issuer_count,
                    ),
                    target=packet_count,
                    name="qualification",
                )
                self.assertIs(
                    result["readiness_gate_passed"],
                    expected,
                )

    def test_qualification_issuer_count_excludes_padding(self) -> None:
        records = self._complete_stage_records(250, 19)
        records.append(
            {
                "cik": "20",
                "locally_complete": True,
                "acceptance": {"present": True},
            }
        )
        result = inventory._stage_summary(
            records,
            target=250,
            name="qualification",
        )
        self.assertEqual(result["selected_issuer_count"], 19)
        self.assertFalse(result["readiness_gate_passed"])

    def test_freezes_inputs_and_reports_cohort_distributions(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            ledger = root / "ledger.csv"
            acceptance = root / "acceptance.json"
            daily_index = root / "daily_index.json"
            corpus = root / "corpus"
            rows = [
                ledger_row(
                    0,
                    ticker="AAA",
                    cik="1234567",
                    form="10-Q",
                    items="",
                    year=2025,
                ),
                ledger_row(
                    1,
                    ticker="BBB",
                    cik="1234568",
                    form="8-K",
                    items="2.02,9.01",
                    year=2026,
                ),
            ]
            write_ledger(ledger, rows)
            write_acceptance_index(acceptance, rows)
            write_corpus_sec_sources(
                corpus, root, rows[0], include_primary=True
            )
            write_corpus_sec_sources(
                corpus, root, rows[1], include_primary=False
            )
            write_daily_primary(
                root,
                daily_index,
                rows[1],
                prepare.sha256_bytes(ledger.read_bytes()),
            )
            write_xbrl_source(corpus, rows[0])
            write_exhibit_manifest(corpus, rows[1])
            write_market_manifest(corpus, rows)
            write_submission_snapshots(corpus, rows)

            report = inventory.inventory_replay_readiness(
                ledger_path=ledger,
                acceptance_index_path=acceptance,
                corpus_root=corpus,
                daily_artifact_index_path=daily_index,
                project_root=root,
                target_packet_count=2,
                candidate_padding=0,
                pilot_packet_count=2,
            )
            repeated = inventory.inventory_replay_readiness(
                ledger_path=ledger,
                acceptance_index_path=acceptance,
                corpus_root=corpus,
                daily_artifact_index_path=daily_index,
                project_root=root,
                target_packet_count=2,
                candidate_padding=0,
                pilot_packet_count=2,
            )

            self.assertEqual(report, repeated)
            self.assertEqual(
                report["source_freeze"]["ledger"]["sha256"],
                prepare.sha256_bytes(ledger.read_bytes()),
            )
            self.assertEqual(
                report["source_freeze"]["acceptance_index"]["sha256"],
                prepare.sha256_bytes(acceptance.read_bytes()),
            )
            self.assertTrue(
                report["source_freeze"]["acceptance_index"][
                    "validation_passed"
                ]
            )
            self.assertEqual(
                report["distributions"]["forms"], {"10-Q": 1, "8-K": 1}
            )
            self.assertEqual(
                report["distributions"]["filing_years"],
                {"2025": 1, "2026": 1},
            )
            self.assertEqual(
                report["distributions"]["items"],
                {"(none_reported)": 1, "2.02": 1, "9.01": 1},
            )
            self.assertEqual(len(report["distributions"]["issuers"]), 2)
            self.assertEqual(
                report["artifact_summary"][
                    "locally_complete_accession_count"
                ],
                2,
            )
            self.assertTrue(
                report["stage_readiness"]["pilot"][
                    "offline_artifacts_complete"
                ]
            )
            requests = report["request_estimates"]
            self.assertEqual(
                requests["current_builder_unchanged"]["total_requests"], 1
            )
            self.assertEqual(
                requests["qualification_acquisition_with_verified_reuse"][
                    "total_request_lower"
                ],
                0,
            )
            self.assertEqual(
                requests["qualification_acquisition_with_verified_reuse"][
                    "total_request_upper"
                ],
                0,
            )
            second_record = next(
                row
                for row in report["accessions"]
                if row["ticker"] == "BBB"
            )
            self.assertTrue(
                second_record["artifacts"]["primary"]["available_offline"]
            )
            self.assertTrue(
                second_record["artifacts"]["primary"]["missing_from_corpus"]
            )
            self.assertFalse(
                second_record["artifacts"]["exhibits"]["missing"]
            )

    def test_reports_each_missing_artifact_and_bounded_estimates(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            ledger = root / "ledger.csv"
            acceptance = root / "acceptance.json"
            rows = [
                ledger_row(
                    0,
                    ticker="AAA",
                    cik="1234567",
                    form="10-Q",
                    items="",
                    year=2026,
                ),
                ledger_row(
                    1,
                    ticker="AAA",
                    cik="1234567",
                    form="8-K",
                    items="2.02,9.01",
                    year=2026,
                ),
            ]
            write_ledger(ledger, rows)
            write_acceptance_index(acceptance, rows)
            report = inventory.inventory_replay_readiness(
                ledger_path=ledger,
                acceptance_index_path=acceptance,
                corpus_root=root / "missing_corpus",
                daily_artifact_index_path=root / "missing_daily_index.json",
                project_root=root,
                target_packet_count=2,
                candidate_padding=0,
                pilot_packet_count=1,
            )

            by_form = {row["form"]: row for row in report["accessions"]}
            self.assertEqual(
                set(by_form["10-Q"]["missing_artifacts"]),
                {
                    "primary",
                    "filing_index",
                    "xbrl",
                    "market",
                    "raw_submission_snapshot",
                },
            )
            self.assertEqual(
                set(by_form["8-K"]["missing_artifacts"]),
                {
                    "primary",
                    "filing_index",
                    "exhibits",
                    "market",
                    "raw_submission_snapshot",
                },
            )
            estimate = report["request_estimates"][
                "qualification_acquisition_with_verified_reuse"
            ]
            self.assertEqual(estimate["sec_primary_requests"], 2)
            self.assertEqual(estimate["sec_filing_index_requests"], 2)
            self.assertEqual(estimate["sec_xbrl_issuer_requests"], 1)
            self.assertEqual(estimate["sec_exhibit_request_lower"], 1)
            self.assertEqual(
                estimate["sec_exhibit_request_upper"],
                inventory.MAX_EXHIBITS_PER_ACCESSION_PLANNING,
            )
            storage = report["storage_estimates"]
            self.assertGreater(
                storage["qualification_planning_upper_bytes"],
                storage["current_builder_projected_total_hard_cap_bytes"],
            )
            self.assertTrue(
                storage[
                    "qualification_upper_is_planning_not_protocol_bound"
                ]
            )


class ReadOnlyBoundaryTests(unittest.TestCase):
    def test_function_is_network_free_and_tree_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            ledger = root / "ledger.csv"
            acceptance = root / "acceptance.json"
            rows = [
                ledger_row(
                    0,
                    ticker="AAA",
                    cik="1234567",
                    form="10-Q",
                    items="",
                    year=2026,
                )
            ]
            write_ledger(ledger, rows)
            write_acceptance_index(acceptance, rows)
            corpus = root / "must_not_be_created"
            before = tree_fingerprint(root)
            with (
                mock.patch.object(
                    urllib.request,
                    "urlopen",
                    side_effect=AssertionError("network attempted"),
                ),
                mock.patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network attempted"),
                ),
            ):
                report = inventory.inventory_replay_readiness(
                    ledger_path=ledger,
                    acceptance_index_path=acceptance,
                    corpus_root=corpus,
                    daily_artifact_index_path=root / "missing.json",
                    project_root=root,
                    target_packet_count=1,
                    candidate_padding=0,
                    pilot_packet_count=1,
                )
            after = tree_fingerprint(root)
            self.assertEqual(before, after)
            self.assertFalse(corpus.exists())
            self.assertFalse(report["boundaries"]["network_used"])
            self.assertFalse(report["boundaries"]["files_written"])
            self.assertFalse(
                report["boundaries"]["authentication_requested"]
            )

    def test_cli_prints_json_but_does_not_create_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            ledger = root / "ledger.csv"
            acceptance = root / "acceptance.json"
            rows = [
                ledger_row(
                    0,
                    ticker="AAA",
                    cik="1234567",
                    form="10-Q",
                    items="",
                    year=2026,
                )
            ]
            write_ledger(ledger, rows)
            write_acceptance_index(acceptance, rows)
            corpus = root / "must_not_be_created"
            before = tree_fingerprint(root)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(
                        SCRIPT_DIR
                        / "inventory_phase5r_llm_replay_corpus.py"
                    ),
                    "--ledger",
                    str(ledger),
                    "--acceptance-index",
                    str(acceptance),
                    "--corpus-root",
                    str(corpus),
                    "--daily-artifact-index",
                    str(root / "missing.json"),
                    "--project-root",
                    str(root),
                    "--target-packets",
                    "1",
                    "--candidate-padding",
                    "0",
                    "--pilot-packets",
                    "1",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            after = tree_fingerprint(root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(
                payload["mode"], "strictly_read_only_offline_inventory"
            )
            self.assertEqual(payload["request_estimates"]["inventory_requests"], 0)
            self.assertEqual(before, after)
            self.assertFalse(corpus.exists())


if __name__ == "__main__":
    unittest.main()
