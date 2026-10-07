from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import unittest
from _support import SCRIPT_DIR
from evidence_scope import shared_integrity_passed, current_shared_integrity_passed, ticker_scan_complete, required_issuer_blockers
from create_daily_decision_and_brief import candidate_stability
from decision_dependencies import classify
from build_decision_evidence_packet import _selected_filing_rows


def partial():
    return dict(scan_status="partial", global_integrity_passed=True, global_blockers=[],
                failure_scope="ticker", failed_tickers=["BAD"], submission_failed_tickers=["BAD"],
                ticker_blockers={"BAD": ["sec_acceptance_reconciliation_failed"]},
                admitted_tickers=["GOOD"], scanned_tickers=["GOOD"], held_coverage_complete=False,
                last_completed_at="2026-10-07T13:32:00-04:00",
                last_attempt_at="2026-10-07T13:30:00-04:00")


class EvidenceScopeTests(unittest.TestCase):
    def test_missing_current_issuer_is_not_admitted_by_absence_of_errors(self):
        codes = required_issuer_blockers(partial(), {"GOOD", "MISSING"})
        self.assertNotIn("GOOD", codes)
        self.assertIn("current_issuer_scan_missing", codes["MISSING"])
        self.assertIn("sec_acceptance_reconciliation_failed", codes["BAD"])
    def test_known_funds_do_not_require_company_admission_but_arbitrary_skip_does(self):
        status = partial()
        status["not_applicable_tickers"] = ["QQQM", "XLI", "UNVERIFIED"]
        codes = required_issuer_blockers(status, {"SPY", "QQQM", "XLI", "UNVERIFIED"})
        self.assertFalse({"SPY", "QQQM", "XLI"} & codes.keys())
        self.assertIn("current_issuer_scan_missing", codes["UNVERIFIED"])

    def test_packet_keeps_periodic_source_after_multiple_newer_events(self):
        rows = [dict(form=f, filing_date=d, accession_number=str(i), material_event="no")
                for i, (f, d) in enumerate([("10-K", "2026-02-01"), ("10-Q", "2026-05-01"),
                    ("10-Q", "2026-08-26"), ("8-K", "2026-09-03"), ("8-K", "2026-09-10")])]
        self.assertEqual({r["accession_number"] for r in _selected_filing_rows(rows, set())}, {"0", "2", "3", "4"})
    def test_scoped_dependencies_route_to_factual_workers(self):
        self.assertEqual(classify("company_fundamentals_incomplete", ticker="ABC")["category"], "A")
        self.assertEqual(classify("sec_submissions_request_failed", ticker="ABC")["category"], "B")
        self.assertEqual(classify("sec_acceptance_timestamp_unreconciled", ticker="ABC")["category"], "B")
    def test_one_rejected_issuer_does_not_block_healthy_scan_or_stability(self):
        status = partial()
        self.assertTrue(current_shared_integrity_passed(status, datetime.fromisoformat("2026-10-07T14:00:00-04:00")))
        self.assertTrue(ticker_scan_complete(status, "GOOD"))
        self.assertFalse(ticker_scan_complete(status, "BAD"))
        rows = [{"ticker": t} for t in ("GOOD", "BAD")]
        first = candidate_stability({}, rows, "2026-10-05", valid_close=True)
        second = candidate_stability({"new_candidate_stability": first}, rows, "2026-10-06",
                                     valid_close=True, invalid_tickers={"BAD"})
        self.assertEqual(second["proposals"]["GOOD"]["distinct_closes"], 2)
        self.assertEqual(second["proposals"]["BAD"]["distinct_closes"], 0)

    def test_partial_needs_complete_explicit_contract_and_current_time(self):
        for key, value in [("global_integrity_passed", False), ("global_blockers", ["bad_index"]),
                           ("failure_scope", "global"), ("ticker_blockers", {}),
                           ("admitted_tickers", ["BAD"]), ("scan_status", "failed")]:
            status = partial(); status[key] = value
            with self.subTest(key=key): self.assertFalse(shared_integrity_passed(status))
        status = partial(); del status["global_integrity_passed"]
        self.assertFalse(shared_integrity_passed(status))
        for at in ("2026-10-07T13:00:00-04:00", "2026-10-08T14:00:00-04:00"):
            self.assertFalse(current_shared_integrity_passed(partial(), datetime.fromisoformat(at)))

    def test_admitted_issuer_with_numeric_gap_is_local_and_not_complete(self):
        status = partial(); status.update(admitted_tickers=["GOOD", "BAD"], submission_failed_tickers=[])
        status["ticker_blockers"] = {"BAD": ["company_fundamentals_unverified"]}
        self.assertTrue(shared_integrity_passed(status))
        self.assertFalse(ticker_scan_complete(status, "BAD"))

    def test_legacy_failed_receipt_is_not_rescued_and_global_failure_breaks_all_runs(self):
        self.assertFalse(shared_integrity_passed(dict(scan_status="failed", held_coverage_complete=True)))
        self.assertTrue(shared_integrity_passed(dict(scan_status="ok", held_coverage_complete=True)))
        self.assertFalse(shared_integrity_passed(dict(scan_status="ok", held_coverage_complete=False)))
        state = candidate_stability({}, [{"ticker": "GOOD"}], "2026-10-06", valid_close=False)
        self.assertEqual(state["proposals"]["GOOD"]["distinct_closes"], 0)


if __name__ == "__main__": unittest.main()
