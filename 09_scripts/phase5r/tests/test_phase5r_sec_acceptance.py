from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phase5r_sec_acceptance import (
    AcceptanceIndexError,
    acceptance_map,
    build_acceptance_index,
    load_acceptance_index,
    load_acceptance_reconciliation_log,
    make_acceptance_record,
    normalize_acceptance_timestamp,
    validate_acceptance_index,
    write_acceptance_index,
)
from refresh_phase5r_daily_evidence import (
    merge_seen_accessions,
    recent_filings,
)
import refresh_phase5r_daily_evidence as daily_evidence


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
    def test_durable_ledger_repairs_stale_seen_accession_cache(self) -> None:
        merged = merge_seen_accessions(
            {"arm": ["0001973239-26-000113"]},
            [
                {
                    "ticker": "ARM",
                    "accession_number": "0001973239-26-000114",
                }
            ],
        )
        self.assertEqual(
            merged["ARM"],
            {
                "0001973239-26-000113",
                "0001973239-26-000114",
            },
        )

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


class SecAcceptanceRefreshFailureTests(unittest.TestCase):
    """Regression coverage for the SEC acceptance precommit boundary."""

    _VALID_TEST_USER_AGENT = "Phase5R-Test/1.0 test@example.com"

    @staticmethod
    def _submissions_payload(*, accepted_at: str) -> dict[str, object]:
        return {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000000001-26-000001"],
                    "form": ["10-Q"],
                    "filingDate": ["2026-07-24"],
                    "acceptanceDateTime": [accepted_at],
                    "items": [""],
                    "primaryDocument": ["test.htm"],
                }
            }
        }

    def _run_acceptance_failure(
        self,
        *,
        prior_index: dict[str, object],
        accepted_at: str,
        generated_at: str,
        expected_reason: str,
    ) -> None:
        """Run an offline refresh that must fail before any evidence commit."""

        with tempfile.TemporaryDirectory(prefix="phase5r-sec-precommit-") as directory:
            root = Path(directory)
            fundamentals_path = root / "fundamentals.csv"
            acceptance_path = root / "acceptance.json"
            reconciliation_path = root / "reconciliation.csv"
            state_path = root / "state.json"
            status_path = root / "status.json"
            ledger_path = root / "ledger.csv"
            fundamentals_path.write_bytes(b"old-fundamentals\n")
            write_acceptance_index(prior_index, acceptance_path)
            state_path.write_text(
                '{"initialized": true, "last_success_at": "2026-07-23T20:00:00+00:00", '
                '"seen_accessions": {}}\n',
                encoding="utf-8",
            )
            status_path.write_text('{"previous": "status"}\n', encoding="utf-8")
            daily_evidence.append_csv_durable(
                ledger_path,
                daily_evidence.LEDGER_FIELDS,
                {
                    "ticker": "OLD",
                    "accession_number": "0000000001-26-000000",
                },
            )
            before_fundamentals = fundamentals_path.read_bytes()
            before_acceptance = acceptance_path.read_bytes()
            before_state = state_path.read_bytes()
            before_ledger = ledger_path.read_bytes()

            def fake_request_json(url: str, _user_agent: str) -> dict[str, object]:
                if "/submissions/" in url:
                    return self._submissions_payload(accepted_at=accepted_at)
                if "/companyfacts/" in url:
                    return {"facts": {}}
                raise AssertionError(f"unexpected public-source URL: {url}")

            with (
                mock.patch.object(daily_evidence, "EVIDENCE_STATE_PATH", state_path),
                mock.patch.object(daily_evidence, "EVIDENCE_STATUS_PATH", status_path),
                mock.patch.object(daily_evidence, "EVIDENCE_LEDGER_PATH", ledger_path),
                mock.patch.object(daily_evidence, "FUNDAMENTALS_PATH", fundamentals_path),
                mock.patch.object(
                    daily_evidence,
                    "researched_tickers",
                    return_value=(["TST"], ["TST"]),
                ),
                mock.patch.object(
                    daily_evidence,
                    "load_ticker_map",
                    return_value={"TST": 1},
                ),
                mock.patch.object(
                    daily_evidence,
                    "load_immutable_acceptance_index",
                    side_effect=lambda: load_acceptance_index(acceptance_path),
                ),
                mock.patch.object(
                    daily_evidence,
                    "SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH",
                    reconciliation_path,
                ),
                mock.patch.object(
                    daily_evidence,
                    "request_json",
                    side_effect=fake_request_json,
                ),
                mock.patch.object(daily_evidence.time, "sleep"),
                mock.patch.object(daily_evidence, "iso_now", return_value=generated_at),
                mock.patch.object(daily_evidence, "log_daily_run") as log_daily_run,
                mock.patch.dict(
                    os.environ,
                    {
                        daily_evidence.SEC_USER_AGENT_ENV: self._VALID_TEST_USER_AGENT,
                    },
                ),
                mock.patch.object(sys, "argv", ["refresh_phase5r_daily_evidence.py"]),
            ):
                self.assertEqual(daily_evidence.main(), 1)

            self.assertEqual(fundamentals_path.read_bytes(), before_fundamentals)
            self.assertEqual(acceptance_path.read_bytes(), before_acceptance)
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual(ledger_path.read_bytes(), before_ledger)
            self.assertFalse(reconciliation_path.exists())
            log_daily_run.assert_called_once_with(
                component="evidence_refresh",
                run_mode="live_public_read",
                outcome="failed",
                reason=expected_reason,
            )
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["scan_status"], "failed")
            self.assertEqual(status["reason"], expected_reason)
            self.assertFalse(status["held_coverage_complete"])
            self.assertFalse(status["held_fundamental_coverage_complete"])
            self.assertEqual(status["request_errors"], [expected_reason])

    def test_identity_conflict_fails_closed_without_mutation(self) -> None:
        prior = build_acceptance_index(
            new_records=[
                make_acceptance_record(
                    accession_number="0000000001-26-000001",
                    ticker="ALT",
                    cik="1",
                    filing_date="2026-07-24",
                    accepted_at="2026-07-24T19:30:45.000Z",
                    source_url="https://data.sec.gov/submissions/CIK0000000001.json",
                )
            ],
            generated_at="2026-07-24T21:00:00+00:00",
        )
        self._run_acceptance_failure(
            prior_index=prior,
            accepted_at="2026-07-24T20:30:45.000Z",
            generated_at="2026-07-24T21:00:00+00:00",
            expected_reason="sec_acceptance_reconciliation_rejected",
        )

    def test_unindexed_current_accession_fails_closed_without_mutation(self) -> None:
        prior = build_acceptance_index(
            generated_at="2026-07-24T21:00:00+00:00",
        )
        self._run_acceptance_failure(
            prior_index=prior,
            accepted_at="2026-07-24T20:30:45.000Z",
            generated_at="2026-07-24T20:00:00+00:00",
            expected_reason="sec_acceptance_reconciliation_rejected",
        )

    def test_valid_reconciliation_releases_staged_ledger_without_index_mutation(self) -> None:
        """An accepted time representation change logs without rewriting the index."""

        with tempfile.TemporaryDirectory(prefix="phase5r-sec-precommit-success-") as directory:
            root = Path(directory)
            fundamentals_path = root / "fundamentals.csv"
            acceptance_path = root / "acceptance.json"
            reconciliation_path = root / "reconciliation.csv"
            state_path = root / "state.json"
            status_path = root / "status.json"
            ledger_path = root / "ledger.csv"
            prior = build_acceptance_index(
                new_records=[
                    make_acceptance_record(
                        accession_number="0000000001-26-000001",
                        ticker="TST",
                        cik="1",
                        filing_date="2026-07-24",
                        accepted_at="2026-07-24T20:30:45.000Z",
                        source_url="https://data.sec.gov/submissions/CIK0000000001.json",
                    )
                ],
                generated_at="2026-07-24T21:00:00+00:00",
            )
            write_acceptance_index(prior, acceptance_path)
            before_acceptance = acceptance_path.read_bytes()
            fundamentals_path.write_bytes(b"old-fundamentals\n")
            state_path.write_text(
                '{"initialized": true, "last_success_at": "2026-07-23T20:00:00+00:00", '
                '"seen_accessions": {}}\n',
                encoding="utf-8",
            )
            daily_evidence.append_csv_durable(
                ledger_path,
                daily_evidence.LEDGER_FIELDS,
                {
                    "ticker": "OLD",
                    "accession_number": "0000000001-26-000000",
                },
            )

            def fake_request_json(url: str, _user_agent: str) -> dict[str, object]:
                if "/submissions/" in url:
                    return self._submissions_payload(
                        accepted_at="2026-07-24T16:30:45.000Z"
                    )
                if "/companyfacts/" in url:
                    return {"facts": {}}
                raise AssertionError(f"unexpected public-source URL: {url}")

            with (
                mock.patch.object(daily_evidence, "EVIDENCE_STATE_PATH", state_path),
                mock.patch.object(daily_evidence, "EVIDENCE_STATUS_PATH", status_path),
                mock.patch.object(daily_evidence, "EVIDENCE_LEDGER_PATH", ledger_path),
                mock.patch.object(daily_evidence, "FUNDAMENTALS_PATH", fundamentals_path),
                mock.patch.object(
                    daily_evidence,
                    "researched_tickers",
                    return_value=(["TST"], ["TST"]),
                ),
                mock.patch.object(
                    daily_evidence,
                    "load_ticker_map",
                    return_value={"TST": 1},
                ),
                mock.patch.object(
                    daily_evidence,
                    "load_immutable_acceptance_index",
                    side_effect=lambda: load_acceptance_index(acceptance_path),
                ),
                mock.patch.object(
                    daily_evidence,
                    "SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH",
                    reconciliation_path,
                ),
                mock.patch.object(
                    daily_evidence,
                    "request_json",
                    side_effect=fake_request_json,
                ),
                mock.patch.object(daily_evidence.time, "sleep"),
                mock.patch.object(
                    daily_evidence,
                    "iso_now",
                    return_value="2026-07-24T21:00:00+00:00",
                ),
                mock.patch.object(daily_evidence, "log_daily_run") as log_daily_run,
                mock.patch.dict(
                    os.environ,
                    {
                        daily_evidence.SEC_USER_AGENT_ENV: self._VALID_TEST_USER_AGENT,
                    },
                ),
                mock.patch.object(sys, "argv", ["refresh_phase5r_daily_evidence.py"]),
            ):
                self.assertEqual(daily_evidence.main(), 0)

            self.assertEqual(acceptance_path.read_bytes(), before_acceptance)
            log_daily_run.assert_called_once_with(
                component="evidence_refresh",
                run_mode="live_public_read",
                outcome="passed",
                reason="complete",
            )
            ledger_rows = daily_evidence.read_csv(ledger_path)
            self.assertEqual(len(ledger_rows), 2)
            self.assertEqual(ledger_rows[-1]["ticker"], "TST")
            self.assertEqual(
                ledger_rows[-1]["accession_number"], "0000000001-26-000001"
            )
            self.assertEqual(
                load_acceptance_index(acceptance_path)["record_count"], 1
            )
            reconciliation_rows = load_acceptance_reconciliation_log(reconciliation_path)
            self.assertEqual(len(reconciliation_rows), 1)
            self.assertEqual(
                next(iter(reconciliation_rows.values()))["reconciliation_decision"],
                "eastern_wall_clock_representation_equivalent",
            )

    def _run_user_agent_preflight_failure(
        self,
        *,
        environment: dict[str, str],
        expected_reason: str,
    ) -> None:
        """A rejected User-Agent must close before any SEC or evidence mutation."""

        with tempfile.TemporaryDirectory(prefix="phase5r-sec-user-agent-") as directory:
            root = Path(directory)
            fundamentals_path = root / "fundamentals.csv"
            acceptance_path = root / "acceptance.json"
            state_path = root / "state.json"
            status_path = root / "status.json"
            ledger_path = root / "ledger.csv"
            prior_index = build_acceptance_index(
                generated_at="2026-07-24T21:00:00+00:00",
            )
            fundamentals_path.write_bytes(b"old-fundamentals\n")
            write_acceptance_index(prior_index, acceptance_path)
            state_path.write_bytes(
                b'{"initialized": true, "last_success_at": '
                b'"2026-07-23T20:00:00+00:00", "seen_accessions": {}}\n'
            )
            status_path.write_bytes(b'{"previous": "status"}\n')
            daily_evidence.append_csv_durable(
                ledger_path,
                daily_evidence.LEDGER_FIELDS,
                {
                    "ticker": "OLD",
                    "accession_number": "0000000001-26-000000",
                },
            )
            before_fundamentals = fundamentals_path.read_bytes()
            before_acceptance = acceptance_path.read_bytes()
            before_state = state_path.read_bytes()
            before_ledger = ledger_path.read_bytes()

            with (
                mock.patch.object(daily_evidence, "EVIDENCE_STATE_PATH", state_path),
                mock.patch.object(daily_evidence, "EVIDENCE_STATUS_PATH", status_path),
                mock.patch.object(daily_evidence, "EVIDENCE_LEDGER_PATH", ledger_path),
                mock.patch.object(daily_evidence, "FUNDAMENTALS_PATH", fundamentals_path),
                mock.patch.object(
                    daily_evidence,
                    "researched_tickers",
                    return_value=(["TST"], ["TST"]),
                ),
                mock.patch.object(
                    daily_evidence,
                    "load_ticker_map",
                    side_effect=AssertionError("User-Agent preflight must precede ticker-map access"),
                ) as load_ticker_map,
                mock.patch.object(
                    daily_evidence,
                    "request_json",
                    side_effect=AssertionError("User-Agent preflight must make no network request"),
                ) as request_json,
                mock.patch.object(
                    daily_evidence,
                    "load_immutable_acceptance_index",
                    side_effect=AssertionError("User-Agent preflight must precede acceptance loading"),
                ) as load_immutable_acceptance_index_mock,
                mock.patch.object(
                    daily_evidence,
                    "iso_now",
                    return_value="2026-07-24T21:00:00+00:00",
                ),
                mock.patch.object(daily_evidence, "log_daily_run") as log_daily_run,
                mock.patch.dict(os.environ, environment, clear=True),
                mock.patch.object(sys, "argv", ["refresh_phase5r_daily_evidence.py"]),
            ):
                self.assertEqual(daily_evidence.main(), 1)

            self.assertEqual(fundamentals_path.read_bytes(), before_fundamentals)
            self.assertEqual(acceptance_path.read_bytes(), before_acceptance)
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual(ledger_path.read_bytes(), before_ledger)
            load_ticker_map.assert_not_called()
            request_json.assert_not_called()
            load_immutable_acceptance_index_mock.assert_not_called()
            log_daily_run.assert_called_once_with(
                component="evidence_refresh",
                run_mode="live_public_read",
                outcome="failed",
                reason=expected_reason,
            )
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["scan_status"], "failed")
            self.assertEqual(status["reason"], expected_reason)
            self.assertEqual(status["last_attempt_at"], "2026-07-24T21:00:00+00:00")
            self.assertEqual(status["last_success_at"], "2026-07-23T20:00:00+00:00")
            self.assertEqual(status["held_tickers"], ["TST"])
            self.assertFalse(status["held_coverage_complete"])
            self.assertEqual(status["new_material_event_count"], 0)
            self.assertFalse(status["network_used"])

    def test_missing_user_agent_preflight_fails_closed_without_network_or_mutation(self) -> None:
        self._run_user_agent_preflight_failure(
            environment={},
            expected_reason="sec_user_agent_missing",
        )

    def test_invalid_user_agent_preflight_fails_closed_without_network_or_mutation(self) -> None:
        self._run_user_agent_preflight_failure(
            environment={daily_evidence.SEC_USER_AGENT_ENV: "not-a-contact"},
            expected_reason="sec_user_agent_invalid",
        )


if __name__ == "__main__":
    unittest.main()
