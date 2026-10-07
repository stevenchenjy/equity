from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_csv, atomic_write_json, canonical_sha256, read_csv, read_json, sha256_file
from earnings_incorporation import CACHE_REL, assess_company, retain_sec_response, write_selection_receipt
from refresh_daily_evidence import FUNDAMENTAL_FIELDS, fundamental_row
from research_backlog import (ARTIFACT_INDEX_REL, DOSSIER_REL, FUNDAMENTALS_REL, HISTORY_REL,
    LONG_HORIZON_REL, POSITIONS_REL, REPORT_REL, build_backlog, complete_objective_data, run, validate_report)
from test_financial_period_integrity import fixture

NOW = datetime(2026, 9, 27, 17, tzinfo=timezone.utc)
ACC = "0000000001-26-000001"
ACCEPTED = "2026-08-01T20:00:00+00:00"


def inline(*facts, dimension=False, unit="USD"):
    body = "".join(f'<ix:nonFraction name="us-gaap:{tag}" contextRef="instant" unitRef="usd">{value}</ix:nonFraction>'
        for tag, value in facts)
    return f'''<html xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
<xbrli:context id="report"><xbrli:entity><xbrli:identifier>0000000001</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="instant"><xbrli:entity><xbrli:identifier>0000000001</xbrli:identifier>{'<xbrli:segment/>' if dimension else ''}</xbrli:entity>
<xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="usd"><xbrli:measure>iso4217:{unit}</xbrli:measure></xbrli:unit>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="report">2026-06-30</ix:nonNumeric>{body}</html>'''.encode()


class ResearchBacklogTests(unittest.TestCase):
    def test_negative_analyst_assessment_defers_canonical_priority_without_completing_gaps(self):
        from test_capital_work_queue import negative_opportunity, WHEN
        opportunity = negative_opportunity("ABC")
        research = {"market_session_date": "2026-09-25", "companies": {"ABC": {
            "readiness": "reviewed_thesis_valuation_pending", "missing_evidence": ["valuation_assumptions"]}}}
        def build(positions=None, report=None, item=None, current=WHEN):
            return build_backlog(fundamentals=[{"ticker": "ABC"}], positions=positions or [],
                research=report or research, dossiers={}, current=current, opportunities=[item or opportunity])
        result = build()
        self.assertEqual(result["priority_queue"], [])
        self.assertTrue(result["issuer_queue"][0]["assessment_waiting_for_change"])
        self.assertTrue(result["issuer_queue"][0]["gap_ids"])
        self.assertTrue(any(r["status"] == "pending_objective" for r in result["items"]))
        self.assertTrue(build(positions=[{"ticker": "ABC", "current_shares": "1"}])["priority_queue"])
        newer = copy.deepcopy(opportunity); newer["last_evidence_at"] = "2026-09-27T13:40:00-04:00"
        self.assertTrue(build(item=newer)["priority_queue"])
        self.assertTrue(build(report={**research, "market_session_date": "2026-09-28"})["priority_queue"])
        self.assertTrue(build(current=datetime.fromisoformat("2026-09-28T13:45:00-04:00"))["priority_queue"])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payload = fixture()
        del self.payload["facts"]["us-gaap"]["DebtAndCapitalLeaseObligations"]
        self.sub = {"cik": 1, "filings": {"recent": {"accessionNumber": [ACC], "form": ["10-Q"],
            "reportDate": ["2026-06-30"], "filingDate": ["2026-08-01"],
            "acceptanceDateTime": [ACCEPTED], "primaryDocument": ["report.htm"], "items": [""]}}}
        self.row = fundamental_row("ABC", 1, self.payload, NOW.isoformat(), acceptance_by_accession={ACC: ACCEPTED})
        self.save_sources()
        self.set_report(inline(("DebtAndCapitalLeaseObligations", 50)))
        atomic_write_csv(self.root / POSITIONS_REL, ["ticker", "current_shares"], [{"ticker": "ABC", "current_shares": "1"}])
        atomic_write_json(self.root / LONG_HORIZON_REL, {"generated_at": NOW.isoformat(), "companies": {
            "ABC": {"held": True, "readiness": "reviewed_thesis_valuation_pending", "missing_evidence": ["durability", "valuation_assumptions"]}}})

    def save_sources(self, retrieved=NOW):
        sr = retain_sec_response(json.dumps(self.sub).encode(), url="https://data.sec.gov/submissions/CIK0000000001.json",
            retrieved_at=retrieved.isoformat(), root=self.root)
        fr = retain_sec_response(json.dumps(self.payload).encode(), url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            retrieved_at=retrieved.isoformat(), root=self.root)
        atomic_write_csv(self.root / FUNDAMENTALS_REL, FUNDAMENTAL_FIELDS, [self.row])
        self.row = read_csv(self.root / FUNDAMENTALS_REL)[0]
        with patch("earnings_incorporation.iso_now", return_value=retrieved.isoformat()):
            write_selection_receipt(ticker="ABC", cik=1, fundamental=self.row, filings=[], submissions_receipt=sr,
                companyfacts_receipt=fr, diagnostic={}, root=self.root)

    def set_report(self, raw):
        artifact = {"ticker": "ABC", "cik": "1", "accession": ACC, "form": "10-Q",
            "url": "https://www.sec.gov/Archives/edgar/data/1/"+ACC.replace("-", "")+"/report.htm",
            "raw_path": "02_filings/report.raw", "raw_sha256": hashlib.sha256(raw).hexdigest(), "fetched_at": NOW.isoformat()}
        (self.root / artifact["raw_path"]).write_bytes(raw)
        atomic_write_json(self.root / ARTIFACT_INDEX_REL, {"artifacts": [artifact]})

    def complete(self, current=NOW):
        return complete_objective_data(root=self.root, ticker="ABC", row=self.row, current=current)

    def execute(self, **kwargs):
        with patch("earnings_incorporation.iso_now", return_value=kwargs.get("current", NOW).isoformat()):
            return run(input_root=self.root, output_root=kwargs.pop("output_root", self.root), current=kwargs.pop("current", NOW), **kwargs)

    def test_safe_same_period_debt_patch_and_receipt_then_idempotent_rerun(self):
        before = copy.deepcopy(self.row)
        result = self.execute(apply_objective_updates=True)
        self.assertEqual(result["selected_tickers"], ["ABC"])
        self.assertEqual(result["canonical_numeric_updates"], 1)
        row = read_csv(self.root / FUNDAMENTALS_REL)[0]
        self.assertEqual(row["debt_latest"], "50.00")
        self.assertEqual(row["latest_period_end"], before["latest_period_end"])
        self.assertEqual(row["revenue_latest"], before["revenue_latest"])
        receipt = read_json(self.root / CACHE_REL / "ABC.selection.json")
        self.assertEqual(receipt["financial_selection_sha256"], canonical_sha256(row))
        self.assertEqual(receipt["companyfacts"]["retrieved_at"], NOW.isoformat())
        assessment = assess_company("ABC", row, receipt, root=self.root, now=NOW, ledger=[], news={})
        self.assertEqual(assessment["blocking_reasons"], [])
        self.assertTrue(assessment["thesis_review_separate"])
        self.assertGreaterEqual(result["counts"]["pending_research"], 2)
        first_history = (self.root / HISTORY_REL).read_bytes()
        repeated = self.execute(apply_objective_updates=True)
        self.assertEqual(repeated["selected_tickers"], [])
        self.assertEqual(repeated["canonical_numeric_updates"], 0)
        self.assertTrue((self.root / HISTORY_REL).read_bytes().startswith(first_history))
        validate_report(repeated, root=self.root, current=NOW)

    def test_current_issuer_rejection_cannot_reuse_prior_fresh_selection(self):
        self.execute()
        status = self.root / "03_source_data/equity_research/daily_evidence_status.json"
        atomic_write_json(status, {"submission_failed_tickers": ["ABC"],
            "ticker_blockers": {"ABC": ["sec_acceptance_reconciliation_failed"]}})
        result = self.complete()
        self.assertEqual(result["reason_code"], "issuer_evidence_quarantined")
        self.assertEqual(result["fields_completed"], [])
        refreshed = self.execute()
        self.assertIn("ABC", refreshed["selected_tickers"])
        self.assertEqual(read_json(self.root / DOSSIER_REL / "ABC.json")["reason_code"], "issuer_evidence_quarantined")
        atomic_write_json(status, {"submission_failed_tickers": ["OTHER"],
            "ticker_blockers": {"ABC": ["company_fundamentals_incomplete"], "OTHER": ["conflict"]}})
        result = self.complete()
        self.assertNotEqual(result["reason_code"], "issuer_evidence_quarantined")
        self.assertIn("debt_latest", result["fields_completed"])

    def test_read_only_dossier_completes_values_without_mutating_input_and_apply_later(self):
        before = sha256_file(self.root / FUNDAMENTALS_REL)
        result = self.execute()
        self.assertEqual(result["objective_dossiers_completed"], 1)
        self.assertEqual(result["financial_fields_completed"], 1)
        self.assertEqual(result["canonical_numeric_updates"], 0)
        self.assertEqual(before, sha256_file(self.root / FUNDAMENTALS_REL))
        dossier = read_json(self.root / DOSSIER_REL / "ABC.json")
        self.assertEqual(dossier["objective_facts"]["debt_latest"]["value"], 50)
        self.assertEqual(dossier["canonical_update"], "verified_patch_available_explicit_apply_flag_required")
        self.assertTrue(any(r["reason_code"] == "debt_latest" and r["status"] == "pending_objective" for r in result["items"]))
        self.assertEqual(self.execute(apply_objective_updates=True)["canonical_numeric_updates"], 1)

    def test_explicit_zero_is_admitted_absence_and_ambiguous_debt_never_become_zero(self):
        self.set_report(inline(("DebtAndCapitalLeaseObligations", 0)))
        self.assertEqual(self.complete()["proposed_fundamental"]["debt_latest"], "0.00")
        for raw in (inline(), inline(("DebtAndCapitalLeaseObligations", 50), ("DebtAndCapitalLeaseObligations", 60)),
                inline(("DebtAndCapitalLeaseObligations", 50), dimension=True),
                inline(("DebtAndCapitalLeaseObligations", 50), unit="EUR"),
                inline(("LongTermDebtCurrent", 10), ("LongTermDebtNoncurrent", 40))):
            with self.subTest(raw=raw):
                self.set_report(raw)
                result = self.complete()
                self.assertNotIn("proposed_fundamental", result)
                self.assertIn("debt_latest", result["remaining_financial_gaps"])

    def test_total_debt_and_components_are_mutually_exclusive(self):
        self.set_report(inline(("DebtAndCapitalLeaseObligations", 50), ("DebtCurrent", 10), ("LongTermDebtNoncurrent", 40)))
        self.assertEqual(self.complete()["proposed_fundamental"]["debt_latest"], "50.00")
        self.set_report(inline(("DebtCurrent", 10), ("LongTermDebtNoncurrent", 40)))
        self.assertEqual(self.complete()["proposed_fundamental"]["debt_latest"], "50.00")

    def test_conflicts_or_changed_bytes_prevent_patch_but_retains_known_data(self):
        self.set_report(inline(("DebtAndCapitalLeaseObligations", 50), ("CashAndCashEquivalentsAtCarryingValue", 999)))
        result = self.complete()
        self.assertEqual(result["reason_code"], "companyfacts_report_value_conflict")
        self.assertEqual(result["objective_facts"]["cash_latest"]["value"], 200)
        self.assertNotIn("proposed_fundamental", result)
        (self.root / "02_filings/report.raw").write_bytes(b"tampered")
        result = self.complete()
        self.assertEqual(result["reason_code"], "objective_source_validation_failed")
        self.assertNotIn("proposed_fundamental", result)

    def test_stale_receipts_reopen_and_fresh_same_bytes_can_retry(self):
        result = self.execute(current=NOW + timedelta(hours=37))
        self.assertEqual(result["attempts_latest_run"][0]["status"], "unverified")
        old_hash = read_json(self.root / CACHE_REL / "ABC.selection.json")["companyfacts"]["raw_sha256"]
        self.save_sources(retrieved=NOW + timedelta(hours=37))
        self.assertEqual(old_hash, read_json(self.root / CACHE_REL / "ABC.selection.json")["companyfacts"]["raw_sha256"])
        result = self.execute(current=NOW + timedelta(hours=37))
        self.assertEqual(result["selected_tickers"], ["ABC"])
        self.assertEqual(result["objective_dossiers_completed"], 1)

    def test_news_repoll_without_changed_evidence_does_not_repeat_objective_work(self):
        self.set_report(inline())  # No admissible numeric patch to retry.
        path = self.root / "03_source_data/equity_research/official_news_events.local.json"
        event = {"ticker": "ABC", "event_id": "story-1", "title": "Customer announcement",
            "url": "https://example.test/announcement", "published_at": ACCEPTED,
            "first_seen_at": NOW.isoformat(), "last_seen_at": NOW.isoformat()}
        atomic_write_json(path, {"events": [event]})
        first = self.execute()
        self.assertEqual(first["selected_tickers"], ["ABC"])
        dossier_before = (self.root / DOSSIER_REL / "ABC.json").read_bytes()
        history_before = (self.root / HISTORY_REL).read_bytes()
        event["last_seen_at"] = (NOW + timedelta(hours=1)).isoformat()
        atomic_write_json(path, {"events": [event]})
        repeated = self.execute(current=NOW + timedelta(hours=1))
        self.assertEqual(repeated["selected_tickers"], [])
        self.assertEqual(repeated["objective_dossiers_completed"], 0)
        self.assertEqual((self.root / DOSSIER_REL / "ABC.json").read_bytes(), dossier_before)
        self.assertTrue((self.root / HISTORY_REL).read_bytes().startswith(history_before))

    def test_changed_news_content_and_new_events_reopen_objective_work(self):
        self.set_report(inline())
        path = self.root / "03_source_data/equity_research/official_news_events.local.json"
        event = {"ticker": "ABC", "event_id": "story-1", "title": "Customer announcement",
            "url": "https://example.test/announcement", "published_at": ACCEPTED,
            "first_seen_at": NOW.isoformat(), "last_seen_at": NOW.isoformat()}
        atomic_write_json(path, {"events": [event]})
        self.execute()
        event["title"] = "Corrected customer announcement"
        atomic_write_json(path, {"events": [event]})
        self.assertEqual(self.execute()["selected_tickers"], ["ABC"])
        event["published_at"] = (NOW - timedelta(hours=1)).isoformat()
        atomic_write_json(path, {"events": [event]})
        self.assertEqual(self.execute()["selected_tickers"], ["ABC"])
        atomic_write_json(path, {"events": [event, {**event, "event_id": "story-2"}]})
        self.assertEqual(self.execute()["selected_tickers"], ["ABC"])

    def test_new_material_evidence_cannot_be_hidden_by_current_same_period(self):
        atomic_write_csv(self.root / "03_source_data/equity_research/daily_evidence_ledger.csv",
            ["ticker", "form", "items", "filing_date", "accession_number"],
            [{"ticker": "ABC", "form": "8-K", "items": "2.02", "filing_date": "2026-09-27", "accession_number": "new"}])
        result = self.complete()
        self.assertEqual(result["status"], "unverified")
        self.assertIn("material_ledger_ahead_of_verified_submission", result["blocking_reasons"])

    def test_canonical_position_shares_override_stale_research_held_flag(self):
        result = build_backlog(fundamentals=[self.row], positions=[{"ticker": "ZZZ", "shares_optional": "1"}],
            research={"companies": {"ABC": {"held": True}}}, dossiers={}, current=NOW)
        self.assertEqual(result["priority_queue"][0]["ticker"], "ZZZ")
        self.assertTrue(result["priority_queue"][0]["held"])
        self.assertFalse(next(r for r in result["issuer_queue"] if r["ticker"] == "ABC")["held"])

    def test_changed_unselected_dossier_reopens_and_unknown_holding_stays_visible(self):
        self.execute(max_tickers=1)
        (self.root / "02_filings/report.raw").write_bytes(b"tampered")
        atomic_write_csv(self.root / POSITIONS_REL, ["ticker", "current_shares"],
            [{"ticker": "AAA", "current_shares": "1"}, {"ticker": "ABC", "current_shares": "1"}])
        result = self.execute(max_tickers=1)
        self.assertEqual(result["selected_tickers"], ["AAA"])
        objective = next(r for r in result["items"] if r["ticker"] == "ABC" and r["kind"] == "objective_attachment")
        self.assertEqual(objective["status"], "unverified")
        self.assertTrue(any(r["ticker"] == "AAA" for r in result["priority_queue"]))

    def test_cross_root_never_changes_inputs_even_with_explicit_apply_flag(self):
        with tempfile.TemporaryDirectory() as out:
            before = {p.relative_to(self.root).as_posix(): sha256_file(p) for p in self.root.rglob("*") if p.is_file()}
            result = self.execute(output_root=Path(out))
            self.assertTrue(result["input_root_read_only"])
            self.assertEqual(before, {p.relative_to(self.root).as_posix(): sha256_file(p) for p in self.root.rglob("*") if p.is_file()})
            with self.assertRaisesRegex(ValueError, "cross_root_objective_updates_forbidden"):
                self.execute(output_root=Path(out), apply_objective_updates=True)

    def test_ten_issuer_budget_is_valid_and_out_of_bounds_is_rejected(self):
        result = self.execute(max_tickers=10)
        self.assertEqual(result["work_budget_tickers"], 10)
        validate_report(result, root=self.root, current=NOW)
        for budget in (0, 11, -1, True, 1.5):
            with self.subTest(budget=budget), self.assertRaisesRegex(ValueError, "research_work_budget_out_of_bounds"):
                self.execute(max_tickers=budget)

    def test_report_and_history_tampering_fail_closed_and_preserve_records(self):
        result = self.execute()
        altered = copy.deepcopy(result); altered["status"] = "pass"
        with self.assertRaisesRegex(ValueError, "report_unverified"):
            validate_report(altered)
        with self.assertRaisesRegex(ValueError, "report_unverified"):
            validate_report(result, current=NOW - timedelta(seconds=1))
        history_path = self.root / HISTORY_REL
        history_path.write_text(history_path.read_text().replace('"objective_attempt"', '"forged_attempt"', 1))
        before = history_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "history_invalid"):
            self.execute()
        self.assertEqual(before, history_path.read_bytes())

    def test_interrupted_publication_never_claims_applied_or_analyst_completed(self):
        with patch("research_backlog.write_selection_receipt", side_effect=OSError("secret excluded")):
            with self.assertRaises(OSError):
                self.execute(apply_objective_updates=True)
        self.assertFalse((self.root / REPORT_REL).exists())
        historical = [read_json(p) for p in (self.root / DOSSIER_REL / "history").glob("*.json")]
        self.assertTrue(historical)
        self.assertTrue(all(r["canonical_update"] != "verified_numeric_patch_applied" for r in historical))
        self.assertNotIn("secret", (self.root / HISTORY_REL).read_text())
        self.assertIn("objective_publication_failed", (self.root / HISTORY_REL).read_text())
        receipt = read_json(self.root / CACHE_REL / "ABC.selection.json")
        self.assertNotEqual(receipt["financial_selection_sha256"], canonical_sha256(read_csv(self.root / FUNDAMENTALS_REL)[0]))


if __name__ == "__main__":
    unittest.main()
