from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import prepare_phase5r_llm_replay_corpus as prepare
import verify_phase5r_llm_replay_corpus as verify


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
EASTERN = ZoneInfo("America/New_York")


def ledger_row(index: int, *, ticker: str = "TST") -> dict[str, str]:
    filing_day = date(2026, 7, 1) + timedelta(days=index)
    ticker_offsets = {"TST": 0, "AAA": 1, "BBB": 2, "CCC": 3}
    cik = str(1234567 + ticker_offsets.get(ticker, 9))
    accession = f"{int(cik):010d}-26-{index + 1:06d}"
    compact = accession.replace("-", "")
    document = f"tst-{filing_day.strftime('%Y%m%d')}-{index}.htm"
    return {
        "detected_at": f"{filing_day.isoformat()}T18:00:00-04:00",
        "cycle_date": filing_day.isoformat(),
        "ticker": ticker,
        "cik": cik,
        "form": "8-K" if index % 2 else "10-Q",
        "filing_date": filing_day.isoformat(),
        "accession_number": accession,
        "items": "",
        "primary_document": document,
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{compact}/{document}"
        ),
        "metadata_sha256": f"{index:064x}",
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


def market_payload(ticker: str) -> bytes:
    days = [date(2026, 7, day) for day in range(2, 12)]
    timestamps = [
        int(datetime.combine(day, time(9, 30), tzinfo=EASTERN).timestamp())
        for day in days
    ]
    closes = [100.0 + index for index in range(len(days))]
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": ticker,
                        "currency": "USD",
                        "exchangeName": "NMS",
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ],
        }
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeSources:
    def __init__(self) -> None:
        self.sec_calls: list[tuple[str, str, int]] = []
        self.market_calls: list[tuple[str, str, int]] = []

    def sec(
        self, url: str, user_agent: str, max_bytes: int
    ) -> prepare.HttpResult:
        self.sec_calls.append((url, user_agent, max_bytes))
        filename = urlsplit(url).path.rsplit("/", 1)[-1]
        if filename.endswith("-index.html"):
            accession = filename.removesuffix("-index.html")
            sequence = int(accession.rsplit("-", 1)[-1])
            day = sequence
            raw = (
                "<html><body><div class='infoHead'>Accepted</div>"
                f"<div class='info'>2026-07-{day:02d} 17:45:30</div>"
                "</body></html>"
            ).encode("utf-8")
        else:
            raw = (
                "<html><body><h1>Official filing</h1>"
                f"<p>Revenue evidence for {filename}.</p></body></html>"
            ).encode("utf-8")
        return prepare.HttpResult(raw, "text/html", url)

    def market(
        self, url: str, user_agent: str, max_bytes: int
    ) -> prepare.HttpResult:
        self.market_calls.append((url, user_agent, max_bytes))
        ticker = urlsplit(url).path.rsplit("/", 1)[-1]
        return prepare.HttpResult(market_payload(ticker), "application/json", url)


def build_small_corpus(
    directory: Path,
    *,
    packet_count: int = 4,
    case_count: int = 4,
) -> tuple[Path, Path, dict[str, object], FakeSources]:
    ledger = directory / "ledger.csv"
    corpus = directory / "corpus"
    write_ledger(ledger, [ledger_row(index) for index in range(packet_count)])
    sources = FakeSources()
    clock = FakeClock()
    manifest = prepare.refresh_corpus(
        ledger_path=ledger,
        corpus_root=corpus,
        target_packet_count=packet_count,
        target_transition_case_count=case_count,
        target_adversarial_case_count=case_count,
        candidate_padding=0,
        user_agent="Phase5RUnitTest/1.0 unit@example.com",
        sec_requests_per_second=2.0,
        sec_fetcher=sources.sec,
        market_fetcher=sources.market,
        clock=clock.now,
        sleeper=clock.sleep,
    )
    return ledger, corpus, manifest, sources


class AcceptanceAndSelectionTests(unittest.TestCase):
    def test_acceptance_parser_preserves_exact_second_and_dst_offset(self) -> None:
        raw = (
            b"<html><body><div>Accepted</div>"
            b"<div>2026-07-02 17:45:30</div></body></html>"
        )
        accepted, header = prepare.parse_sec_acceptance(raw)
        self.assertEqual(header, "2026-07-02 17:45:30")
        self.assertEqual(accepted, "2026-07-02T17:45:30-04:00")

        winter = (
            b"<html><body>ACCEPTANCE-DATETIME: 20260102174530</body></html>"
        )
        accepted, header = prepare.parse_sec_acceptance(winter)
        self.assertEqual(header, "20260102174530")
        self.assertEqual(accepted, "2026-01-02T17:45:30-05:00")

    def test_round_robin_selection_is_distinct_and_balanced(self) -> None:
        rows = [
            prepare.normalize_ledger_row(ledger_row(index, ticker=ticker))
            for ticker in ("AAA", "BBB", "CCC")
            for index in range(4)
        ]
        selected = prepare.select_candidate_rows(
            rows, target_packet_count=6, candidate_padding=0
        )
        self.assertEqual(len(selected), 6)
        self.assertEqual(len({row["accession"] for row in selected}), 6)
        self.assertEqual(
            {ticker: sum(row["ticker"] == ticker for row in selected) for ticker in ("AAA", "BBB", "CCC")},
            {"AAA": 2, "BBB": 2, "CCC": 2},
        )

    def test_unsafe_sec_url_and_rate_above_two_fail_closed(self) -> None:
        raw = ledger_row(0)
        raw["source_url"] = raw["source_url"].replace(
            "www.sec.gov", "www.sec.gov.example.com"
        )
        with self.assertRaises(prepare.CorpusError):
            prepare.normalize_ledger_row(raw)
        with self.assertRaises(prepare.CorpusError):
            prepare.RequestLimiter(2.0001)

    def test_official_acceptance_may_precede_filing_date_over_weekend(self) -> None:
        prepare.validate_acceptance_filing_date(
            "2026-07-17T22:05:00-04:00", "2026-07-20"
        )
        with self.assertRaises(prepare.CorpusError):
            prepare.validate_acceptance_filing_date(
                "2026-06-01T12:00:00-04:00", "2026-07-20"
            )


class RefreshAndVerifierTests(unittest.TestCase):
    def test_refresh_builds_real_unlabeled_packets_and_honest_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            ledger, corpus, manifest, sources = build_small_corpus(
                Path(directory_name)
            )
            self.assertEqual(len(sources.sec_calls), 8)
            self.assertEqual(len(sources.market_calls), 1)
            self.assertEqual(len(manifest["packets"]), 4)
            self.assertEqual(len(manifest["cases"]), 7)
            self.assertEqual(
                manifest["requirements"]["material_transition_probe_count"], 3
            )
            self.assertEqual(
                manifest["requirements"]["adversarial_safety_probe_count"], 4
            )
            transitions = [
                case
                for case in manifest["cases"]
                if case["case_kind"]
                == "material_transition_detection_probe"
            ]
            self.assertEqual(
                len({case["transition_fingerprint"] for case in transitions}),
                len(transitions),
            )
            for case in transitions:
                identity = {
                    "case_kind": case["case_kind"],
                    "ticker": case["ticker"],
                    "prior_packet_id": case["prior_packet_id"],
                    "current_packet_id": case["current_packet_id"],
                }
                self.assertEqual(
                    case["transition_fingerprint"],
                    prepare.canonical_sha256(identity),
                )
            self.assertFalse(manifest["requirements"]["requirements_met"])
            self.assertFalse(
                manifest["quality_separation"]["provider_quality_scored"]
            )
            self.assertFalse(
                manifest["quality_separation"]["live_inference_unlock"]
            )
            binding = manifest["promotion_binding_contract"]
            self.assertTrue(
                binding["evaluation_must_bind_exact_manifest_file_sha256"]
            )
            self.assertTrue(
                binding["evaluation_must_bind_model_registry_file_sha256"]
            )
            self.assertFalse(
                binding["corpus_or_fixture_counts_unlock_live_shadow"]
            )
            for record in manifest["packets"]:
                packet = json.loads(
                    (corpus / record["relative_path"]).read_text(encoding="utf-8")
                )
                self.assertIsNone(
                    packet["historical_outcome"]["decision_label"]
                )
                self.assertFalse(
                    packet["evaluation_status"][
                        "provider_quality_scoring_eligible"
                    ]
                )
                accepted_day = datetime.fromisoformat(
                    packet["acceptance"]["accepted_at_et"]
                ).date()
                bar_day = date.fromisoformat(
                    packet["market_close"]["bar_date"]
                )
                self.assertGreater(bar_day, accepted_day)
                market_source = next(
                    source
                    for source in packet["source_catalog"]
                    if source["source_type"]
                    == "public_historical_daily_market_data"
                )
                observation = json.loads(
                    (corpus / market_source["relative_path"]).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertFalse(observation["future_bars_included"])
                self.assertEqual(
                    set(observation["bar"]),
                    {"bar_index", "timestamp", "bar_date", "close"},
                )
                self.assertNotIn("timestamp", observation)
            report = verify.verify_corpus(
                corpus_root=corpus,
                ledger_path=ledger,
                enforce_minimums=False,
            )
            self.assertTrue(report["passed"], report["issues"])
            self.assertFalse(report["provider_quality_scored"])
            self.assertFalse(report["live_inference_unlock"])

    def test_verified_cache_prevents_repeat_network_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            ledger, corpus, _, sources = build_small_corpus(root)
            second = FakeSources()
            clock = FakeClock()

            def forbidden_sec(
                url: str, user_agent: str, max_bytes: int
            ) -> prepare.HttpResult:
                del url, user_agent, max_bytes
                raise AssertionError("verified SEC cache must be reused")

            def forbidden_market(
                url: str, user_agent: str, max_bytes: int
            ) -> prepare.HttpResult:
                del url, user_agent, max_bytes
                raise AssertionError("verified market cache must be reused")

            manifest = prepare.refresh_corpus(
                ledger_path=ledger,
                corpus_root=corpus,
                target_packet_count=4,
                target_transition_case_count=4,
                target_adversarial_case_count=4,
                candidate_padding=0,
                user_agent="Phase5RUnitTest/1.0 unit@example.com",
                sec_requests_per_second=2.0,
                sec_fetcher=forbidden_sec,
                market_fetcher=forbidden_market,
                clock=clock.now,
                sleeper=clock.sleep,
            )
            self.assertEqual(len(sources.sec_calls), 8)
            self.assertEqual(len(second.sec_calls), 0)
            self.assertEqual(len(manifest["packets"]), 4)

    def test_corrupted_primary_fails_offline_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            ledger, corpus, manifest, _ = build_small_corpus(
                Path(directory_name)
            )
            packet_record = manifest["packets"][0]
            packet = json.loads(
                (corpus / packet_record["relative_path"]).read_text(
                    encoding="utf-8"
                )
            )
            primary = next(
                source
                for source in packet["source_catalog"]
                if source["source_type"] == "sec_primary_document"
            )
            (corpus / primary["relative_path"]).write_bytes(b"tampered")
            report = verify.verify_corpus(
                corpus_root=corpus,
                ledger_path=ledger,
                enforce_minimums=False,
            )
            self.assertFalse(report["passed"])
            self.assertIn("hash mismatch", report["issues"][0])

    def test_one_ticker_cannot_inflate_distinct_issuers_with_multiple_ciks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            ledger = root / "ledger.csv"
            corpus = root / "corpus"
            rows = [ledger_row(0), ledger_row(1)]
            replacement_cik = "7654321"
            replacement_accession = "0007654321-26-000002"
            replacement_document = "tst-20260702-replacement.htm"
            rows[1].update(
                {
                    "cik": replacement_cik,
                    "accession_number": replacement_accession,
                    "primary_document": replacement_document,
                    "source_url": (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{int(replacement_cik)}/"
                        f"{replacement_accession.replace('-', '')}/"
                        f"{replacement_document}"
                    ),
                }
            )
            write_ledger(ledger, rows)
            sources = FakeSources()
            clock = FakeClock()
            prepare.refresh_corpus(
                ledger_path=ledger,
                corpus_root=corpus,
                target_packet_count=2,
                target_transition_case_count=1,
                target_adversarial_case_count=1,
                candidate_padding=0,
                user_agent="Phase5RUnitTest/1.0 unit@example.com",
                sec_requests_per_second=2.0,
                sec_fetcher=sources.sec,
                market_fetcher=sources.market,
                clock=clock.now,
                sleeper=clock.sleep,
            )
            report = verify.verify_corpus(
                corpus_root=corpus,
                ledger_path=ledger,
                enforce_minimums=False,
            )
            self.assertFalse(report["passed"])
            self.assertIn(
                "corpus ticker maps to multiple CIK identities",
                report["issues"][0],
            )

    def test_stale_manifest_hard_minimum_fails_offline_verification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            ledger, corpus, manifest, _ = build_small_corpus(
                Path(directory_name)
            )
            manifest["requirements"][
                "minimum_real_point_in_time_packets"
            ] = 249
            (corpus / prepare.MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report = verify.verify_corpus(
                corpus_root=corpus,
                ledger_path=ledger,
                enforce_minimums=False,
            )
            self.assertFalse(report["passed"])
            self.assertIn(
                "manifest requirement counts are inconsistent",
                report["issues"][0],
            )

    def test_same_day_close_is_never_selected(self) -> None:
        accepted = "2026-07-02T08:00:00-04:00"
        bars = {
            date(2026, 7, 2): {
                "bar_index": 0,
                "timestamp": 1,
                "bar_date": "2026-07-02",
                "close": "100",
            },
            date(2026, 7, 3): {
                "bar_index": 1,
                "timestamp": 2,
                "bar_date": "2026-07-03",
                "close": "101",
            },
        }
        selected, as_of = prepare.select_first_close_after_acceptance(
            accepted, bars
        )
        self.assertEqual(selected["bar_date"], "2026-07-03")
        self.assertEqual(as_of, "2026-07-03T23:59:59-04:00")


class OfflineBoundaryTests(unittest.TestCase):
    def test_valid_check_is_network_free_and_byte_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            ledger, corpus, _, _ = build_small_corpus(Path(directory_name))
            before = {
                path: (
                    prepare.sha256_bytes(path.read_bytes()),
                    path.stat().st_mtime_ns,
                )
                for path in corpus.rglob("*")
                if path.is_file()
            }
            with mock.patch.object(
                prepare.urllib.request,
                "urlopen",
                side_effect=AssertionError("offline verifier attempted network"),
            ):
                report = verify.verify_corpus(
                    corpus_root=corpus,
                    ledger_path=ledger,
                    enforce_minimums=False,
                )
            after = {
                path: (
                    prepare.sha256_bytes(path.read_bytes()),
                    path.stat().st_mtime_ns,
                )
                for path in corpus.rglob("*")
                if path.is_file()
            }
            self.assertTrue(report["passed"], report["issues"])
            self.assertEqual(before, after)
            self.assertFalse(report["network_used"])
            self.assertFalse(report["files_written"])

    def test_check_on_missing_corpus_uses_no_network_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            ledger = root / "ledger.csv"
            corpus = root / "must_not_be_created"
            write_ledger(ledger, [ledger_row(0)])
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "prepare_phase5r_llm_replay_corpus.py"),
                    "--check",
                    "--allow-incomplete",
                    "--ledger",
                    str(ledger),
                    "--corpus-root",
                    str(corpus),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("network_used=false", completed.stdout)
            self.assertIn("files_written=false", completed.stdout)
            self.assertFalse(corpus.exists())

    def test_sec_limiter_spaces_requests_at_half_second(self) -> None:
        clock = FakeClock()
        limiter = prepare.RequestLimiter(
            2.0, clock=clock.now, sleeper=clock.sleep
        )
        limiter.wait()
        limiter.wait()
        limiter.wait()
        self.assertEqual(clock.sleeps, [0.5, 0.5])


if __name__ == "__main__":
    unittest.main()
