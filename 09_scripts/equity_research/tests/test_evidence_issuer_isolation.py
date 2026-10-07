"""Offline publication regressions for scoped SEC issuer admission."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from _support import SCRIPT_DIR  # noqa: F401
import earnings_incorporation as incorporation
import refresh_daily_evidence as evidence
from sec_acceptance import build_acceptance_index, load_acceptance_index, make_acceptance_record, write_acceptance_index


NOW = "2026-07-27T12:00:00+00:00"
OLD = "2026-07-23T12:00:00+00:00"


class IssuerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.paths = {name: self.root / value for name, value in {
            "EVIDENCE_STATE_PATH": "state.json", "EVIDENCE_STATUS_PATH": "status.json",
            "EVIDENCE_LEDGER_PATH": "ledger.csv", "FUNDAMENTALS_PATH": "fundamentals.csv",
            "SEC_ACCEPTANCE_INDEX_PATH": "acceptance.json",
            "SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH": "reconciliation.csv",
            "SEC_ACCEPTANCE_EXTENSION_DIR": "extensions",
            "SEC_ACCEPTANCE_EXTENSION_AUDIT_PATH": "extension-audit.csv",
            "SEC_ACCEPTANCE_EXTENSION_LOCK_PATH": "extension.lock",
        }.items()}
        self.tickers = {"ALFA": 1, "BETA": 2, "SPY": 3}
        self.held = ["SPY"]
        self.bad = {"BETA"}
        self.incomplete = set()
        self.request_failures = set()
        self.supplement_failures = set()
        self.payloads = {}
        prior = build_acceptance_index(new_records=[self.record(t) for t in ("ALFA", "BETA")], generated_at=OLD.replace("23", "24"))
        write_acceptance_index(prior, self.paths["SEC_ACCEPTANCE_INDEX_PATH"])
        evidence.atomic_write_json(self.paths["EVIDENCE_STATE_PATH"], {
            "initialized": True, "last_success_at": OLD,
            "seen_accessions": {"BETA": ["0000000002-26-000009"]},
        })
        evidence.atomic_write_csv(self.paths["FUNDAMENTALS_PATH"], evidence.FUNDAMENTAL_FIELDS,
                                  [self.financial(t, OLD) for t in ("ALFA", "BETA")])
        evidence.atomic_write_csv(self.paths["EVIDENCE_LEDGER_PATH"], evidence.LEDGER_FIELDS, [])
        for ticker in ("ALFA", "BETA"):
            p = self.root / incorporation.CACHE_REL / f"{ticker}.selection.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"ticker": ticker, "selected_at": OLD}) + "\n")
        self.before = {name: p.read_bytes() for name, p in self.paths.items() if p.is_file()}
        self.old_selections = {t: self.selection(t).read_bytes() for t in ("ALFA", "BETA")}
        for name, value in {**self.paths, "ROOT": self.root}.items():
            self.stack.enter_context(mock.patch.object(evidence, name, value))
        self.stack.enter_context(mock.patch.object(evidence, "researched_tickers", side_effect=lambda: (self.held, sorted(self.tickers))))
        self.stack.enter_context(mock.patch.object(evidence, "load_ticker_map", side_effect=lambda *_: self.tickers))
        self.stack.enter_context(mock.patch.object(evidence, "load_immutable_acceptance_index", side_effect=lambda p: load_acceptance_index(p)))
        self.stack.enter_context(mock.patch.object(evidence, "request_json", side_effect=self.request))
        self.stack.enter_context(mock.patch.object(evidence, "fundamental_row", side_effect=lambda t, _c, _facts, at, **_: self.financial(t, at)))
        self.stack.enter_context(mock.patch.object(evidence, "supplement_cached_latest_report", side_effect=lambda facts, **_: (facts, {})))
        self.stack.enter_context(mock.patch.object(evidence, "supplement_companyfacts", side_effect=self.supplement))
        self.stack.enter_context(mock.patch.object(evidence.time, "sleep"))
        self.stack.enter_context(mock.patch.object(evidence, "iso_now", return_value=NOW))
        self.stack.enter_context(mock.patch.object(incorporation, "iso_now", return_value=NOW))
        self.stack.enter_context(mock.patch.object(evidence, "cycle_date", return_value="2026-07-27"))
        self.stack.enter_context(mock.patch.object(evidence, "log_daily_run"))
        self.stack.enter_context(mock.patch.dict(os.environ, {evidence.SEC_USER_AGENT_ENV: "IsolationTests tests@example.com"}))
        self.stack.enter_context(mock.patch.object(sys, "argv", ["refresh_daily_evidence.py"]))

    def selection(self, ticker):
        return self.root / incorporation.CACHE_REL / f"{ticker}.selection.json"

    def record(self, ticker):
        cik = self.tickers[ticker]
        return make_acceptance_record(accession_number=f"{cik:010d}-26-000001", ticker=ticker,
            cik=str(cik), filing_date="2026-07-24", accepted_at="2026-07-24T08:00:00Z",
            source_url=evidence.SEC_SUBMISSIONS_URL.format(cik=cik))

    def financial(self, ticker, at):
        row = {k: "" for k in evidence.FUNDAMENTAL_FIELDS}
        row.update(ticker=ticker, cik=str(self.tickers[ticker]), fetched_at=at,
                   latest_period_end="2026-06-30", data_quality="insufficient" if ticker in self.incomplete else "ok")
        return row

    def supplement(self, ticker, _cik, facts, *_args, **_kwargs):
        if ticker in self.supplement_failures:
            raise OSError("synthetic optional supplemental endpoint failure")
        return facts

    def request(self, url, _agent):
        cik = int(url.split("CIK")[1].split(".")[0])
        ticker = next(t for t, c in self.tickers.items() if c == cik)
        if ticker in self.request_failures:
            raise OSError("synthetic issuer endpoint outage")
        if "/submissions/" in url:
            accessions = [] if ticker == "SPY" else [f"{cik:010d}-26-000001", f"{cik:010d}-26-000002"]
            accepted = "2026-07-24T16:00:00Z" if ticker in self.bad else "2026-07-24T12:00:00Z"
            value = {"cik": str(cik), "tickers": [ticker], "name": f"{ticker} Synthetic Issuer",
                     "filings": {"recent": {"accessionNumber": accessions, "form": ["10-Q"] * len(accessions),
                         "filingDate": ["2026-07-24"] * len(accessions), "reportDate": ["2026-06-30"] * len(accessions),
                         "acceptanceDateTime": [accepted, "2026-07-24T13:00:00Z"][:len(accessions)],
                         "items": [""] * len(accessions), "primaryDocument": ["test.htm"] * len(accessions)}}}
        else:
            value = {"cik": str(cik), "facts": {}}
        raw = (json.dumps(value) + "\n").encode()
        result = incorporation.SecPayload(value)
        result.receipt = incorporation.retain_sec_response(raw, url=url, retrieved_at=NOW, root=self.root)
        self.payloads[url] = (raw, result.receipt)
        return result

    def run_refresh(self, code=0):
        self.assertEqual(evidence.main(), code)
        return json.loads(self.paths["EVIDENCE_STATUS_PATH"].read_text())

    def assert_no_admission(self):
        for name in ("EVIDENCE_STATE_PATH", "EVIDENCE_LEDGER_PATH", "FUNDAMENTALS_PATH", "SEC_ACCEPTANCE_INDEX_PATH"):
            self.assertEqual(self.paths[name].read_bytes(), self.before[name], name)
        for ticker in ("ALFA", "BETA"):
            self.assertEqual(self.selection(ticker).read_bytes(), self.old_selections[ticker])
        self.assertFalse(self.paths["SEC_ACCEPTANCE_EXTENSION_DIR"].exists())

    def test_mixed_batch_admits_healthy_issuer_and_retains_rejected_history(self):
        status = self.run_refresh()
        self.assertEqual(status["scan_status"], "partial")
        self.assertTrue(status["global_integrity_passed"])
        self.assertEqual(status["failure_scope"], "ticker")
        self.assertEqual(status["admitted_tickers"], ["ALFA"])
        self.assertEqual(status["not_applicable_tickers"], ["SPY"])
        self.assertEqual(status["last_completed_at"], NOW)
        self.assertEqual(status["submission_failed_tickers"], ["BETA"])
        self.assertIn("sec_acceptance_timestamp_unreconciled", status["ticker_blockers"]["BETA"])
        self.assertIn("0000000002-26-000001", status["ticker_failure_diagnostics"]["BETA"][0])
        self.assertTrue(status["held_coverage_complete"])
        self.assertTrue(status["held_fundamental_coverage_complete"])
        self.assertEqual(status["held_fundamental_failures"], [])
        self.assertEqual(status["sec_acceptance_extension_admission_count"], 1)
        self.assertEqual(self.paths["SEC_ACCEPTANCE_INDEX_PATH"].read_bytes(), self.before["SEC_ACCEPTANCE_INDEX_PATH"])
        self.assertEqual(self.selection("BETA").read_bytes(), self.old_selections["BETA"])
        healthy = json.loads(self.selection("ALFA").read_text())
        self.assertEqual(healthy["selected_at"], NOW)
        self.assertEqual(healthy["financial_selection"]["fetched_at"], NOW)
        rows = {r["ticker"]: r for r in evidence.read_csv(self.paths["FUNDAMENTALS_PATH"])}
        self.assertEqual(rows["ALFA"]["fetched_at"], NOW)
        self.assertEqual(rows["BETA"]["fetched_at"], OLD)
        self.assertEqual({r["ticker"] for r in evidence.read_csv(self.paths["EVIDENCE_LEDGER_PATH"])}, {"ALFA"})
        state = json.loads(self.paths["EVIDENCE_STATE_PATH"].read_text())
        self.assertEqual(state["seen_accessions"]["BETA"], ["0000000002-26-000009"])
        self.assertEqual(state["last_success_at"], OLD)
        for raw, receipt in self.payloads.values():
            self.assertEqual((self.root / receipt["raw_path"]).read_bytes(), raw)

    def test_failed_held_company_does_not_mark_etf_fundamentals_failed(self):
        self.held = ["BETA", "SPY"]
        status = self.run_refresh()
        self.assertEqual(status["held_failures"], ["BETA"])
        self.assertEqual(status["held_fundamental_failures"], ["BETA"])
        self.assertTrue(status["global_integrity_passed"])

    def test_all_issuers_rejected_preserve_canonical_inputs(self):
        del self.tickers["SPY"]
        self.held = ["BETA"]
        self.bad = {"ALFA", "BETA"}
        status = self.run_refresh()
        self.assertEqual(status["scan_status"], "partial")
        self.assertEqual(status["admitted_tickers"], [])
        self.assertEqual(status["failed_tickers"], ["ALFA", "BETA"])
        self.assertTrue(status["global_integrity_passed"])
        self.assertEqual(status["filings_recorded"], 0)
        self.assertEqual(status["fundamental_rows"], 0)
        self.assert_no_admission()

    def test_shared_immutable_corruption_remains_global(self):
        self.paths["SEC_ACCEPTANCE_INDEX_PATH"].write_text('{"invalid":true}')
        self.before["SEC_ACCEPTANCE_INDEX_PATH"] = self.paths["SEC_ACCEPTANCE_INDEX_PATH"].read_bytes()
        status = self.run_refresh(1)
        self.assertEqual(status["failure_scope"], "global")
        self.assertFalse(status["global_integrity_passed"])
        self.assertTrue(status["global_blockers"])
        self.assert_no_admission()
        self.assertEqual(self.payloads, {})

    def test_shared_audit_corruption_stops_before_new_extension_write(self):
        for name in ("SEC_ACCEPTANCE_EXTENSION_AUDIT_PATH", "SEC_ACCEPTANCE_RECONCILIATION_LOG_PATH"):
            with self.subTest(journal=name):
                self.paths[name].write_text("invalid,audit,header\n")
                status = self.run_refresh(1)
                self.assertFalse(status["global_integrity_passed"])
                self.assertEqual(status["failure_scope"], "global")
                self.assert_no_admission()
                self.paths[name].unlink()

    def test_company_gap_remains_local_and_can_receive_partial_financial_receipt(self):
        self.bad = set()
        self.incomplete = {"BETA"}
        status = self.run_refresh()
        self.assertEqual(status["failed_tickers"], ["BETA"])
        self.assertEqual(status["ticker_blockers"]["BETA"], ["company_fundamentals_incomplete"])
        self.assertEqual(status["submission_failed_tickers"], [])
        self.assertIn("BETA", status["admitted_tickers"])
        self.assertEqual(json.loads(self.selection("BETA").read_text())["financial_selection"]["data_quality"], "insufficient")

    def test_optional_supplement_failure_does_not_block_complete_standard_facts(self):
        self.bad = set()
        self.supplement_failures = {"ALFA"}
        status = self.run_refresh()
        self.assertEqual(status["scan_status"], "ok")
        self.assertEqual(status["ticker_blockers"], {})
        self.assertIn("ALFA:supplemental_cash_flow_unavailable", status["fundamental_request_errors"])

    def test_issuer_request_failure_is_local_and_retains_stale_receipt(self):
        self.bad = set()
        self.request_failures = {"BETA"}
        status = self.run_refresh()
        self.assertEqual(status["submission_failed_tickers"], ["BETA"])
        self.assertEqual(self.selection("BETA").read_bytes(), self.old_selections["BETA"])
        self.assertIn("sec_submissions_request_failed", status["ticker_blockers"]["BETA"])

    def test_missing_etf_mapping_is_not_a_company_sec_blocker(self):
        self.bad = set()
        with mock.patch.object(evidence, "load_ticker_map", return_value={"ALFA": 1, "BETA": 2}):
            status = self.run_refresh()
        self.assertEqual(status["scan_status"], "ok")
        self.assertEqual(status["not_applicable_tickers"], ["SPY"])
        self.assertEqual(status["submission_failed_tickers"], [])
        self.assertNotIn("SPY", status["ticker_blockers"])
        self.assertTrue(status["held_coverage_complete"])
        self.assertTrue(status["held_fundamental_coverage_complete"])

    def test_selection_publication_failure_replaces_previous_passing_envelope(self):
        evidence.atomic_write_json(self.paths["EVIDENCE_STATUS_PATH"], {
            "scan_status": "ok", "global_integrity_passed": True, "last_attempt_at": NOW,
        })
        with mock.patch.object(evidence, "write_selection_receipt", side_effect=OSError("synthetic full disk")):
            status = self.run_refresh(1)
        self.assertEqual(status["scan_status"], "failed")
        self.assertFalse(status["global_integrity_passed"])
        self.assertEqual(status["global_blockers"], ["sec_evidence_publication_failed"])
        self.assertEqual(status["last_success_at"], OLD)
        self.assertEqual(self.selection("BETA").read_bytes(), self.old_selections["BETA"])
        # The valid accepted prefix is retained; recovery must reconcile it,
        # never erase new admitted rows or pretend this batch completed.
        self.assertEqual({r["ticker"] for r in evidence.read_csv(self.paths["EVIDENCE_LEDGER_PATH"])}, {"ALFA"})


if __name__ == "__main__":
    unittest.main()
