from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from test_thesis_evidence import fixture, material_fixture, AS_OF, SCHEMA, ACCESSION, PERIOD
from thesis_evidence import STORE_REL, stable_news_event, seal_review
from daily_common import canonical_sha256
from workflow_integrity import apply_workflow_integrity, validate_published_workflow, incorporation_meaning, workflow_meaning, reviewed_candidate_ready


class WorkflowPublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        record, context = fixture(self.root)
        self.context = context
        store_path = self.root / STORE_REL
        store_path.parent.mkdir(parents=True)
        store_path.write_text(json.dumps({"schema_version": SCHEMA, "records": [record]}))
        self.record = record
        self.incorporation = {"companies": {"ABC": {"status": "incorporated", "positive_decision_eligible": True,
            "latest_report_period_end": PERIOD, "latest_material_accession": ACCESSION,
            "selected_period_end": PERIOD, "blocking_reasons": [], "financial_economic_sha256": "economic"}}}
        self.news = {"status": "ok", "required_coverage_complete": True, "unconfigured_held_tickers": [],
                     "sources": [{"source_id": "abc", "ticker": "ABC", "freshness": "fresh"}], "recent_events": []}
        context_plan = {"status": "current", "block_new_capital": False, "conflicts": [], "plans": [
            {"ticker": "ABC", "plan_id": "abc-plan", "version": 1, "status": "maintained", "action": "hold",
             "instruction": "Keep current plan; no new quantity.", "role": "long_term_growth", "blockers": []}]}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("workflow_integrity.evidence_context", return_value=context))
        stack.enter_context(patch("workflow_integrity.read_earnings_incorporation_status", side_effect=lambda **_: deepcopy(self.incorporation)))
        stack.enter_context(patch("workflow_integrity.current_news_context", side_effect=lambda *a, **k: deepcopy(self.news)))
        stack.enter_context(patch("workflow_integrity.load_plan_context", side_effect=lambda *a, **k: deepcopy(context_plan)))
        self.current = datetime.fromisoformat(AS_OF)

    def decision(self, code="hold_no_new_position"):
        return {"decision_code": code, "headline": "Original headline", "decisive_advice": "Original advice",
            "decision_fingerprint": "original", "account_conflicts": [], "generated_at": AS_OF,
            "market_gate": {"passed": True}, "evidence_gate": {"passed": True}, "fundamental_gate": {"passed": True},
            "held_positions": [{"ticker": "ABC", "asset_role": "active_stock", "current_shares": "1", "action": "hold", "reason": "baseline"}],
            "long_horizon_research": {"views": {}, "warnings": []}, "watch_candidates": [],
            "eligible_action_review_candidates": [], "eligible_new_position_review_candidates": [],
            "capital_allocation": {"proposed_deployment_value": 100}}

    def publish(self, decision=None):
        decision = decision or self.decision()
        apply_workflow_integrity(decision, root=self.root, current=self.current)
        return decision

    def test_publication_revalidates_source_bytes_not_only_ledger_hash(self):
        decision = self.publish()
        validate_published_workflow(decision, root=self.root, current=self.current)
        source = self.root / self.record["sources"][0]["normalized_path"]
        source.write_text(source.read_text()+" changed")
        with self.assertRaisesRegex(ValueError, "thesis_changed"):
            validate_published_workflow(decision, root=self.root, current=self.current)

    def test_publication_reopens_elapsed_company_review_without_input_mutation(self):
        decision = self.publish()
        with self.assertRaisesRegex(ValueError, "thesis_changed"):
            validate_published_workflow(decision, root=self.root, current=datetime.fromisoformat("2026-10-02T21:00:00+00:00"))

    def test_publication_rehashes_nonperiodic_material_review(self):
        receipt = material_fixture(self.root, self.context)
        record = deepcopy(self.record)
        record["reviewed_material_filings"] = [receipt]
        record["reviewed_material_accessions"].append(receipt["accession"])
        (self.root / STORE_REL).write_text(json.dumps({"schema_version": SCHEMA, "records": [seal_review(record)]}))
        decision = self.publish()
        validate_published_workflow(decision, root=self.root, current=self.current)
        path = self.root / receipt["raw_path"]
        path.write_text(path.read_text()+" changed after report composition")
        with self.assertRaisesRegex(ValueError, "thesis_changed"):
            validate_published_workflow(decision, root=self.root, current=self.current)

    def test_news_expiry_requires_recomposition(self):
        decision = self.publish()
        self.news.update(status="degraded", required_coverage_complete=False)
        with self.assertRaisesRegex(ValueError, "news_changed"):
            validate_published_workflow(decision, root=self.root, current=self.current)

    def test_critical_gate_and_zero_quantity_survive_plan_overlay(self):
        for code in ("data_gate_hold", "account_conflict_hold", "fundamental_weakening_review"):
            with self.subTest(code=code):
                decision = self.decision(code)
                decision["watch_candidates"] = [{"ticker": "ABC", "suggested_whole_shares": "1", "action": "eligible_buy_review"}]
                decision["eligible_new_position_review_candidates"] = ["ABC"]
                self.publish(decision)
                self.assertEqual(decision["decision_code"], code)
                self.assertEqual(decision["headline"], "Original headline")
                self.assertEqual(decision["watch_candidates"][0]["suggested_whole_shares"], "0")
                self.assertFalse(decision["eligible_new_position_review_candidates"])
                self.assertEqual(decision["capital_allocation"]["proposed_deployment_value"], 0)

    def test_missing_data_gate_blocks_inconsistent_positive_baseline(self):
        decision = self.decision("action_review_candidate")
        decision["market_gate"] = {"passed": False}
        decision["watch_candidates"] = [{"ticker": "ABC", "suggested_whole_shares": "1", "action": "eligible_buy_review"}]
        decision["eligible_new_position_review_candidates"] = ["ABC"]
        self.publish(decision)
        self.assertFalse(decision["workflow_integrity"]["new_capital_allowed"])
        self.assertFalse(decision["eligible_new_position_review_candidates"])

    def test_missing_input_binding_rejected(self):
        decision = self.publish()
        decision["workflow_integrity"]["input_hashes"].pop(str(STORE_REL))
        with self.assertRaisesRegex(ValueError, "bindings_incomplete"):
            validate_published_workflow(decision, root=self.root, current=self.current)

    def test_economic_correction_is_meaningful_but_fetch_clock_is_not(self):
        changed = deepcopy(self.incorporation)
        changed["companies"]["ABC"]["retrieved_at"] = "next fetch"
        self.assertEqual(incorporation_meaning(changed), incorporation_meaning(self.incorporation))
        changed["companies"]["ABC"]["financial_economic_sha256"] = "corrected"
        self.assertNotEqual(incorporation_meaning(changed), incorporation_meaning(self.incorporation))

    def test_reviewed_to_monitor_clock_transition_is_not_a_new_instruction(self):
        before = self.publish()
        self.current = datetime.fromisoformat("2026-09-25T21:00:00+00:00")
        after = self.publish()
        self.assertEqual(before["long_horizon_research"]["views"]["ABC"]["status"], "reviewed")
        self.assertEqual(after["long_horizon_research"]["views"]["ABC"]["status"], "monitor")
        self.assertEqual(workflow_meaning(before), workflow_meaning(after))

    def event(self, published="2026-09-24T21:01:00+00:00", title="ABC launches a new product"):
        return {"event_id": "news-abc", "source_id": "abc", "ticker": "ABC", "title": title,
            "url": "https://investors.example.com/abc", "published_at": published,
            "source_type": "official_issuer_announcement", "source_fresh": True,
            "first_seen_at": "2026-09-24T21:01:00+00:00", "last_seen_at": "2026-09-24T21:01:00+00:00"}

    def test_new_issuer_news_reopens_view_preserving_filing_conclusion(self):
        self.current = datetime.fromisoformat("2026-09-24T21:02:00+00:00")
        self.news["recent_events"] = [self.event()]
        decision = self.publish()
        view = decision["long_horizon_research"]["views"]["ABC"]
        self.assertEqual(view["status"], "reassess")
        self.assertEqual(view["conclusion"], self.record["conclusion"])
        self.assertEqual(view["business_case_status"], "provisionally_supported")
        self.assertIn("new_official_issuer_news_unreviewed:news-abc", view["reopen_reasons"])
        self.assertFalse(view["automatic_action_allowed"])

    def test_preexisting_news_remains_explicit_without_overwriting_business_view(self):
        self.news["recent_events"] = [self.event(published="2026-09-24T20:00:00+00:00")]
        view = self.publish()["long_horizon_research"]["views"]["ABC"]
        self.assertEqual(view["status"], "reviewed")
        self.assertEqual(view["news_review"]["status"], "pending_prior_news")
        self.assertEqual(len(view["news_review"]["pending_events"]), 1)

    def test_calendar_only_notice_does_not_reopen_business_case(self):
        self.current = datetime.fromisoformat("2026-09-24T21:02:00+00:00")
        self.news["recent_events"] = [self.event(title="ABC to Participate in Investor Conference")]
        view = self.publish()["long_horizon_research"]["views"]["ABC"]
        self.assertEqual(view["status"], "reviewed")
        self.assertFalse(view["news_review"]["pending_events"])

    def test_news_collection_timestamps_do_not_change_workflow_meaning(self):
        self.news["recent_events"] = [self.event(published="2026-09-24T20:00:00+00:00")]
        before = self.publish()
        self.news["recent_events"][0]["last_seen_at"] = "2026-09-24T21:05:00+00:00"
        self.news["last_attempt_at"] = "2026-09-24T21:05:00+00:00"
        after = self.publish()
        self.assertEqual(workflow_meaning(before), workflow_meaning(after))
        self.news["recent_events"][0]["title"] = "ABC launches a revised product"
        self.assertNotEqual(workflow_meaning(after), workflow_meaning(self.publish()))

    def test_acknowledged_news_clears_pending_but_correction_reopens(self):
        event = self.event(published="2026-09-24T20:00:00+00:00")
        self.news["recent_events"] = [event]
        record = deepcopy(self.record)
        stable = stable_news_event(event)
        record["reviewed_news_events"] = [{"event": stable, "event_sha256": canonical_sha256(stable),
            "assessment": "Headline triaged; further adoption evidence remains a named open question.", "review_scope": "issuer_headline_triage"}]
        path = self.root / STORE_REL
        path.write_text(json.dumps({"schema_version": SCHEMA, "records": [seal_review(record)]}))
        view = self.publish()["long_horizon_research"]["views"]["ABC"]
        self.assertEqual(view["status"], "reviewed")
        self.assertEqual(view["news_review"]["status"], "current")
        self.news["recent_events"][0]["title"] = "ABC withdraws previously announced product"
        view = self.publish()["long_horizon_research"]["views"]["ABC"]
        self.assertEqual(view["status"], "reassess")
        self.assertEqual(view["conclusion"], self.record["conclusion"])

    def test_new_stock_needs_maintained_valuation_and_news_review(self):
        decision = self.decision("action_review_candidate")
        decision["watch_candidates"] = [{"ticker": "NEW", "suggested_whole_shares": "1", "action": "eligible_buy_review"}]
        decision["eligible_new_position_review_candidates"] = ["NEW"]
        self.incorporation["companies"]["NEW"] = {"status": "incorporated", "positive_decision_eligible": True}
        self.publish(decision)
        self.assertEqual(set(decision["long_horizon_research"]["views"]), {"ABC"})
        self.assertEqual(set(decision["long_horizon_research"]["candidate_views"]), {"NEW"})
        self.assertFalse(decision["eligible_new_position_review_candidates"])
        self.assertEqual(decision["watch_candidates"][0]["suggested_whole_shares"], "0")
        self.assertIn("maintained_company_research_incomplete", decision["watch_candidates"][0]["gate_blockers"])
        ready = {"status": "monitor", "business_case_status": "provisionally_supported", "valuation_readiness": "reviewed_scenarios",
            "news_review": {"status": "current", "coverage_complete": True}}
        self.assertTrue(reviewed_candidate_ready(ready))
        for field, value in (("status", "reassess"), ("valuation_readiness", "unresolved"), ("business_case_status", "mixed"),
                             ("news_review", {"status": "pending_prior_news", "coverage_complete": True}),
                             ("news_review", {"status": "current", "coverage_complete": False})):
            self.assertFalse(reviewed_candidate_ready(ready | {field: value}))


if __name__ == "__main__":
    unittest.main()
