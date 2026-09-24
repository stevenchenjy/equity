from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import PROJECT_ROOT
from long_horizon_research import build_long_horizon_report
from thesis_evidence import (
    RECORD_SCHEMA, SCHEMA, ThesisValidationError, append_review, evaluate_thesis,
    seal_review, source_receipt, validate_review, validate_store, stable_news_event, material_filing_receipt,
)
from daily_common import canonical_sha256

AS_OF = "2026-09-24T21:00:00+00:00"
PERIOD = "2026-06-30"
ACCESSION = "0000000001-26-000001"


def fixture(root):
    folder = root / "02_filings/issuer_filings/ABC" / ACCESSION
    folder.mkdir(parents=True)
    raw = f'<ix:nonNumeric name="dei:DocumentPeriodEndDate">{PERIOD}</ix:nonNumeric>'
    text = "Revenue grew 20 percent. Share compensation remains a material cost."
    (folder / "primary_document.raw").write_text(raw)
    (folder / "normalized_text.txt").write_text(text)
    artifact = {"source_id": "abc-q2", "ticker": "ABC", "accession": ACCESSION,
        "url": "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/abc.htm",
        "normalized_path": str((folder / "normalized_text.txt").relative_to(root)),
        "normalized_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "raw_path": str((folder / "primary_document.raw").relative_to(root)),
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(), "fetched_at": "2026-09-23T20:00:00+00:00",
        "form": "10-Q", "primary_document": "abc.htm"}
    context = {"acceptance": {ACCESSION: {"ticker": "ABC", "cik": "1", "accepted_at": "2026-08-01T20:00:00+00:00"}},
               "artifacts": {"abc-q2": artifact}}
    def claim(identifier, statement, stance, start, end):
        return {"claim_id": identifier, "statement": statement, "kind": "reported_fact", "stance": stance,
                "citations": [{"source_id": "abc-q2", "char_start": start, "char_end": end, "excerpt": text[start:end]}]}
    claims = [claim("growth", "Revenue grew.", "supporting", 0, 23),
              claim("dilution", "Compensation requires per-share review.", "contradictory", 24, len(text))]
    def section(status, summary):
        return {"status": status, "summary": summary, "claim_ids": ["growth", "dilution"], "unresolved": ["Future durability is uncertain."]}
    record = seal_review({"schema_version": RECORD_SCHEMA, "ticker": "ABC", "version": 1, "review_id": "abc-review-1",
        "reviewed_at": AS_OF, "reviewer": "research analyst", "review_state": "reviewed", "financial_period_end": PERIOD,
        "next_review_at": "2026-10-01T21:00:00+00:00", "change_reason": "First researched conclusion.",
        "supersedes_sha256": "", "sources": [source_receipt(artifact, context, PERIOD)], "claims": claims,
        "business_case": section("provisionally_supported", "Growth supports a provisional business thesis."),
        "per_share_economics": section("partial", "Per-share economics need more evidence."),
        "valuation": section("unresolved", "No reviewed company-specific valuation yet."),
        "valuation_model": None,
        "portfolio_role_and_alternatives": section("partial", "Potential growth research, benchmark comparison pending."),
        "conclusion": "Provisional business support; price attractiveness remains unresolved.",
        "unresolved_questions": ["What growth is sustainable?"], "invalidation_conditions": ["Repeated growth deterioration warrants review."],
        "reviewed_material_accessions": [ACCESSION]})
    return record, context


def material_fixture(root, context):
    accession = "0000000001-26-000003"
    folder = root / "02_filings/issuer_filings/ABC" / accession
    folder.mkdir(parents=True)
    text = "Item 5.02: A director joined the Audit Committee. No other items are reported in this document."
    raw = "<html><body>"+text+"</body></html>"
    (folder / "primary_document.raw").write_text(raw)
    (folder / "normalized_text.txt").write_text(text)
    artifact = {"source_id": "abc-amendment", "ticker": "ABC", "accession": accession,
        "url": "https://www.sec.gov/Archives/edgar/data/1/000000000126000003/abc.htm",
        "normalized_path": str((folder / "normalized_text.txt").relative_to(root)),
        "normalized_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "raw_path": str((folder / "primary_document.raw").relative_to(root)),
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(), "fetched_at": "2026-09-24T20:30:00+00:00",
        "form": "8-K/A", "primary_document": "abc.htm"}
    context["acceptance"][accession] = {"ticker": "ABC", "cik": "1", "form": "8-K/A",
        "accepted_at": "2026-09-20T20:00:00+00:00"}
    context["artifacts"][artifact["source_id"]] = artifact
    return material_filing_receipt(artifact, context, assessment="Read the complete primary amendment; it reports a committee appointment and does not revise the financial thesis.",
        disposition="no_change_to_maintained_view", char_start=0, char_end=len(text), excerpt=text)


class MaintainedThesisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record, self.context = fixture(self.root)
        self.store = {"schema_version": SCHEMA, "records": [self.record]}
        self.incorporation = {"status": "incorporated", "latest_report_period_end": PERIOD,
                              "latest_material_accession": ACCESSION}

    def evaluate(self, **kwargs):
        return evaluate_thesis(kwargs.pop("store", self.store), "ABC", kwargs.pop("observed_at", AS_OF), self.root,
            context=self.context, incorporation=kwargs.pop("incorporation", self.incorporation), **kwargs)

    def test_review_persists_then_monitors_without_completing_valuation(self):
        first = self.evaluate()
        next_day = self.evaluate(observed_at="2026-09-25T21:00:00+00:00")
        self.assertEqual(first["status"], "reviewed")
        self.assertEqual(next_day["status"], "monitor")
        self.assertEqual(first["review_record"], next_day["review_record"])
        self.assertEqual(next_day["valuation_readiness"], "unresolved")
        self.assertEqual(next_day["investment_conviction"], "not_assessed")
        self.assertFalse(next_day["recommendation_authority"])

    def test_expiry_preserves_old_conclusion_but_reopens_effective_state(self):
        result = self.evaluate(observed_at="2026-10-01T21:00:00+00:00")
        self.assertEqual(result["status"], "reassess")
        self.assertIn("scheduled_company_review_due", result["reopen_reasons"])
        self.assertEqual(result["conclusion"], self.record["conclusion"])
        self.assertEqual(self.store["records"][0]["review_state"], "reviewed")

    def test_new_period_and_pending_incorporation_reopen(self):
        changed = self.incorporation | {"latest_report_period_end": "2026-09-30"}
        self.assertIn("new_financial_period_not_reviewed", self.evaluate(incorporation=changed)["reopen_reasons"])
        for incorporation in (None, {"status": "pending_incorporation"}, {"status": "unknown"}):
            self.assertEqual(self.evaluate(incorporation=incorporation)["status"], "reassess")

    def test_new_material_filing_and_late_detection_reopen(self):
        accession = "0000000001-26-000002"
        self.context["acceptance"][accession] = {"ticker": "ABC", "accepted_at": "2026-09-25T19:00:00+00:00"}
        event = {"ticker": "ABC", "accession_number": accession, "material_event": "yes"}
        result = self.evaluate(observed_at="2026-09-25T21:00:00+00:00", material_events=[event])
        self.assertIn("new_material_filing_not_reviewed:"+accession, result["reopen_reasons"])
        self.context["acceptance"][accession]["accepted_at"] = "2026-09-20T19:00:00+00:00"
        event["detected_at"] = "2026-09-25T19:00:00+00:00"
        result = self.evaluate(observed_at="2026-09-25T21:00:00+00:00", material_events=[event])
        self.assertIn("late_detected_material_filing_not_reviewed:"+accession, result["reopen_reasons"])

    def test_same_period_amendment_requires_explicit_incorporation(self):
        result = self.evaluate(incorporation=self.incorporation | {"latest_material_accession": "0000000001-26-000002"})
        self.assertIn("latest_earnings_accession_not_reviewed", result["reopen_reasons"])

    def test_material_review_survives_index_rotation_but_rehashes_retained_raw(self):
        receipt = material_fixture(self.root, self.context)
        record = deepcopy(self.record)
        record["reviewed_material_filings"] = [receipt]
        record["reviewed_material_accessions"].append(receipt["accession"])
        record = seal_review(record)
        validate_review(record, self.root, self.context, AS_OF, admission=True)
        store = {"schema_version": SCHEMA, "records": [record]}
        self.context["artifacts"].pop(receipt["source_id"])
        self.assertEqual(self.evaluate(store=store)["status"], "reviewed")
        with self.assertRaisesRegex(ThesisValidationError, "verified artifact index"):
            validate_review(record, self.root, self.context, AS_OF, admission=True)
        source = self.root / receipt["raw_path"]
        source.write_text(source.read_text()+"altered")
        result = self.evaluate(store=store)
        self.assertEqual(result["status"], "unresolved")
        self.assertIn("source content hash differs", result["validation_errors"][0])
        self.assertEqual(result["conclusion"], "")

    def test_bare_material_accession_cannot_claim_completed_review(self):
        receipt = material_fixture(self.root, self.context)
        record = deepcopy(self.record)
        record["reviewed_material_accessions"].append(receipt["accession"])
        record = seal_review(record)
        with self.assertRaisesRegex(ThesisValidationError, "lacks verified receipt"):
            validate_review(record, self.root, self.context, AS_OF, admission=True)
        result = self.evaluate(store={"schema_version": SCHEMA, "records": [record]})
        self.assertEqual(result["status"], "reassess")
        self.assertEqual(result["conclusion"], record["conclusion"])
        self.assertIn("material_filing_acknowledgment_without_verified_receipt:"+receipt["accession"], result["reopen_reasons"])
        record["reviewed_material_filings"] = [receipt | {"disposition": "reassessment_required"}]
        result = self.evaluate(store={"schema_version": SCHEMA, "records": [seal_review(record)]})
        self.assertIn("reviewed_material_filing_requires_reassessment:"+receipt["accession"], result["reopen_reasons"])

    def test_modified_source_and_forged_excerpt_fail_closed(self):
        path = self.root / self.record["sources"][0]["normalized_path"]
        path.write_text(path.read_text()+" changed")
        result = self.evaluate()
        self.assertEqual(result["status"], "unresolved")
        self.assertIn("hash differs", result["validation_errors"][0])
        self.assertEqual(result["conclusion"], "")
        path.write_text(path.read_text().removesuffix(" changed"))
        record = deepcopy(self.record)
        record["claims"][0]["citations"][0]["excerpt"] = "fabricated text"
        result = self.evaluate(store={"schema_version": SCHEMA, "records": [seal_review(record)]})
        self.assertEqual(result["status"], "unresolved")

    def test_mismatched_period_future_date_and_path_escape_rejected(self):
        for field, value in (("financial_period_end", "2026-03-31"), ("fetched_at", "2026-10-01T21:00:00+00:00"),
                             ("published_at", "2026-08-02T20:00:00+00:00"), ("normalized_path", "../../outside.txt")):
            with self.subTest(field=field):
                record = deepcopy(self.record)
                record["sources"][0][field] = value
                with self.assertRaises((ThesisValidationError, OSError)):
                    validate_review(seal_review(record), self.root, self.context, AS_OF)

    def test_unsupported_source_cannot_promote_review(self):
        record = deepcopy(self.record)
        record["sources"][0]["url"] = "https://example.com/research"
        with self.assertRaises(ThesisValidationError):
            validate_review(seal_review(record), self.root, self.context, AS_OF)

    def test_review_requires_counterevidence_and_named_unknowns(self):
        record = deepcopy(self.record)
        record["claims"][1]["stance"] = "supporting"
        with self.assertRaises(ThesisValidationError):
            validate_review(seal_review(record), self.root, self.context, AS_OF)

    def test_company_specific_valuation_can_progress_but_generic_grid_cannot(self):
        from test_valuation_input_bundle import _bundle
        from valuation_input_bundle import seal_bundle
        bundle = _bundle(self.root, ticker="ABC")
        bundle["records"][0]["inputs"]["share_price"]["period"] = "2026-09-23 close"
        bundle = seal_bundle(bundle)
        path = self.root / "04_data/equity_research/valuation_source_review.local.json"
        path.write_text(json.dumps(bundle))
        record = deepcopy(self.record)
        record["valuation"]["status"] = "reviewed_scenarios"
        record["valuation_model"] = {"relative_path": str(path.relative_to(self.root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "assumptions_reason": "Company-specific growth assumptions were independently assessed.",
            "countercase_reason": "Lower customer growth and increased dilution reduce value.", "claim_ids": ["growth", "dilution"]}
        validate_review(seal_review(record), self.root, self.context, AS_OF)
        source = bundle["records"][0]["sources"][-1]
        source["source_type"] = "deterministic_valuation_policy"
        # Invalid source type/path/authority must fail, and must never promote
        # the original generic policy grid into a reviewed company valuation.
        path.write_text(json.dumps(seal_bundle(bundle)))
        record["valuation_model"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            validate_review(seal_review(record), self.root, self.context, AS_OF)
        record = deepcopy(self.record)
        record["valuation"]["status"] = "reviewed_scenarios"
        with self.assertRaises(ThesisValidationError):
            validate_review(seal_review(record), self.root, self.context, AS_OF)

    def test_version_append_and_stale_writer_rejection(self):
        second = deepcopy(self.record)
        second.update(version=2, review_id="abc-review-2", supersedes_sha256=self.record["record_sha256"],
                      change_reason="Reviewed new counterevidence.")
        second["business_case"]["status"] = "mixed"
        second = seal_review(second)
        with patch("thesis_evidence.evidence_context", return_value=self.context):
            updated = append_review(self.store, second, self.root, AS_OF)
            with self.assertRaises(ThesisValidationError):
                append_review(updated, second, self.root, AS_OF)
        self.assertEqual(len(updated["records"]), 2)
        self.assertEqual(updated["records"][0], self.record)
        self.assertEqual(validate_store(updated)["ABC"]["version"], 2)

    def test_tampered_history_never_silently_reverts_to_old_review(self):
        store = deepcopy(self.store)
        store["records"][0]["conclusion"] = "Unrecorded edit"
        self.assertEqual(self.evaluate(store=store)["status"], "unresolved")

    def test_daily_report_uses_maintained_conclusion_without_action_authority(self):
        policy = json.loads((PROJECT_ROOT / "01_policies/long_horizon_research_policy.json").read_text())
        with patch("long_horizon_research.evidence_context", return_value=self.context):
            report = build_long_horizon_report([], [{"ticker": "ABC"}], [], policy, AS_OF,
                thesis_store=self.store, evidence_root=self.root,
                incorporation_report={"companies": {"ABC": self.incorporation}})
        row = report["companies"]["ABC"]
        self.assertEqual(row["readiness"], "reviewed_thesis_valuation_pending")
        self.assertEqual(row["maintained_view"]["conclusion"], self.record["conclusion"])
        self.assertIn("unresolved_business_evidence:What growth is sustainable?", row["missing_evidence"])
        self.assertFalse(report["canonical_influence_allowed"])

    def test_news_acknowledgment_requires_matching_fresh_source_at_admission(self):
        event = {"event_id": "event-abc", "source_id": "abc-ir", "ticker": "ABC",
            "source_type": "official_issuer_announcement", "title": "ABC launches product",
            "url": "https://example.com/abc", "published_at": "2026-09-24T20:30:00+00:00", "source_fresh": True}
        record = deepcopy(self.record)
        stable = stable_news_event(event)
        record["reviewed_news_events"] = [{"event": stable, "event_sha256": canonical_sha256(stable),
            "assessment": "Issuer headline triaged; commercial outcome remains unverified.", "review_scope": "issuer_headline_triage"}]
        with patch("official_news.read_official_news_status", return_value={"recent_events": [event]}):
            validate_review(seal_review(record), self.root, self.context, AS_OF, admission=True)
            event["source_fresh"] = False
            with self.assertRaisesRegex(ThesisValidationError, "fresh issuer"):
                validate_review(seal_review(record), self.root, self.context, AS_OF, admission=True)
        record["reviewed_news_events"][0]["event_sha256"] = "wrong"
        with self.assertRaisesRegex(ThesisValidationError, "hash differs"):
            validate_review(seal_review(record), self.root, self.context, AS_OF)

    def test_long_report_and_decision_overlay_share_news_reassessment(self):
        from create_long_horizon_research import render_report
        policy = json.loads((PROJECT_ROOT / "01_policies/long_horizon_research_policy.json").read_text())
        event = {"event_id": "event-abc", "source_id": "abc-ir", "ticker": "ABC",
            "source_type": "official_issuer_announcement", "title": "ABC launches product",
            "url": "https://example.com/abc", "published_at": "2026-09-24T21:01:00+00:00", "source_fresh": True}
        news = {"sources": [{"ticker": "ABC", "freshness": "fresh"}], "recent_events": [event], "required_coverage_complete": True}
        with patch("long_horizon_research.evidence_context", return_value=self.context):
            report = build_long_horizon_report([], [{"ticker": "ABC"}], [], policy, "2026-09-24T21:02:00+00:00",
                thesis_store=self.store, evidence_root=self.root, official_news_report=news,
                incorporation_report={"companies": {"ABC": self.incorporation}})
        view = report["companies"]["ABC"]["maintained_view"]
        self.assertEqual(view["status"], "reassess")
        self.assertEqual(report["companies"]["ABC"]["readiness"], "research_reassessment_required")
        self.assertIn("ABC launches product", render_report(report))
        self.assertEqual(view["conclusion"], self.record["conclusion"])


if __name__ == "__main__":
    unittest.main()
