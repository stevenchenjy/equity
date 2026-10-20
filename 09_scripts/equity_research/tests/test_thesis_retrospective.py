from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from investment_reasoning import research_method_template
from thesis_evidence import SCHEMA as STORE_SCHEMA, seal_review, validate_store
from thesis_retrospective import (price_observations, reasoning_fingerprint,
                                 retrospective_template, validate_retrospective)
from workflow_evaluation import thesis_review_summary
from create_workflow_evaluation import render_thesis_review
import create_workflow_evaluation as evaluation_cli
from test_thesis_evidence import fixture


class ThesisRetrospectiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.original, self.context = fixture(self.root)
        self.original["research_method"] = research_method_template()
        self.original = seal_review(self.original)
        self.later = copy.deepcopy(self.original)
        self.later.update(version=2, review_id="abc-review-2", reviewed_at="2026-09-28T21:00:00+00:00",
                          supersedes_sha256=self.original["record_sha256"])
        self.later["retrospective"] = retrospective_template(self.original)
        self.later = seal_review(self.later)
        self.now = datetime.fromisoformat("2026-09-29T21:00:00+00:00")

    def snapshot(self, identifier="original", version=1, created="2026-09-24T21:01:00+00:00"):
        return dict(snapshot_id=identifier, ticker="ABC", thesis_id="company_thesis:ABC",
                    thesis_version=version, created_at=created)

    def outcome(self, identifier="original", version=1, day="2026-09-28", change=10):
        return dict(snapshot_id=identifier, ticker="ABC", thesis_id="company_thesis:ABC", thesis_version=str(version),
                    horizon_sessions="1", forecast_origin_session="2026-09-25", evaluation_session=day,
                    entry_close="100", evaluation_close=str(100 + change),
                    absolute_return_pct=str(change), evaluation_basis="forward_next_session_close_v2; not_execution_or_total_return")

    def test_exact_original_anchor_and_immutable_ledger(self):
        original_bytes = copy.deepcopy(self.original)
        store = {"schema_version": STORE_SCHEMA, "records": [self.original, self.later]}
        self.assertEqual(validate_store(store)["ABC"]["version"], 2)
        self.assertEqual(self.original, original_bytes)
        for field, value in (("original_review_id", "missing"), ("original_record_sha256", "0" * 64)):
            bad = copy.deepcopy(self.later)
            bad["retrospective"][field] = value
            with self.assertRaises(ValueError):
                validate_retrospective(bad, [self.original])
        with self.assertRaises(ValueError):
            validate_retrospective(self.later, [dict(self.original, ticker="XYZ")])

    def test_legacy_process_cannot_be_reconstructed_from_later_price(self):
        original = copy.deepcopy(self.original)
        original.pop("research_method")
        original = seal_review(original)
        later = copy.deepcopy(self.later)
        later["retrospective"] = retrospective_template(original)
        validate_retrospective(later, [original])
        later["retrospective"]["decision_process"]["assessment"] = "process_supported"
        with self.assertRaisesRegex(ValueError, "legacy_process"):
            validate_retrospective(later, [original])

    def test_unknown_template_cannot_support_process_quality(self):
        later = copy.deepcopy(self.later)
        later["retrospective"]["decision_process"]["assessment"] = "process_supported"
        with self.assertRaisesRegex(ValueError, "substantive_original_method"):
            validate_retrospective(later, [self.original])
        later["retrospective"]["decision_process"].update(assessment="process_gap", rationale="The original loss paths remained unknown.")
        validate_retrospective(later, [self.original])

    def test_business_realization_requires_later_reported_facts(self):
        later = copy.deepcopy(self.later)
        later["retrospective"]["business_outcome"].update(status="supported", claim_ids=["growth"])
        with self.assertRaisesRegex(ValueError, "evidence_published_after"):
            validate_retrospective(later, [self.original])
        later["sources"][0]["published_at"] = "2026-09-28T20:00:00+00:00"
        validate_retrospective(later, [self.original])
        later["claims"][0]["kind"] = "analyst_inference"
        with self.assertRaisesRegex(ValueError, "inference_only"):
            validate_retrospective(later, [self.original])

    def test_price_uses_first_exact_version_snapshot_and_review_cutoff(self):
        snapshots = [self.snapshot(), self.snapshot("duplicate", created="2026-09-25T21:00:00+00:00"), self.snapshot("new", 2)]
        outcomes = [self.outcome(), self.outcome("duplicate", change=40), self.outcome("new", 2, change=70)]
        result = price_observations(self.original, snapshots, outcomes, self.now)
        self.assertEqual(result["snapshot_id"], "original")
        self.assertEqual(result["horizons"][0]["absolute_return_pct"], "10")
        before_close = datetime.fromisoformat("2026-09-28T15:59:00-04:00")
        self.assertFalse(price_observations(self.original, snapshots, outcomes, before_close)["horizons"])
        self.assertEqual(price_observations(self.original, [snapshots[-1]], outcomes, self.now)["status"], "no_original_version_snapshot")

    def test_later_method_annotation_is_not_backdated(self):
        original = copy.deepcopy(self.original)
        original["research_method"]["authored_at"] = "2026-09-28T21:00:00+00:00"
        self.assertEqual(price_observations(original, [self.snapshot()], [self.outcome()], self.now)["status"], "no_original_version_snapshot")
        later = copy.deepcopy(self.later)
        original = seal_review(original)
        later["retrospective"] = retrospective_template(original)
        with self.assertRaisesRegex(ValueError, "original_must_be_earlier"):
            validate_retrospective(later, [original])

    def test_backfilled_snapshot_cannot_use_an_entry_close_before_authorship(self):
        original = copy.deepcopy(self.original)
        original["research_method"]["authored_at"] = "2026-09-25T21:00:00+00:00"
        snapshot = self.snapshot(created="2026-09-25T21:01:00+00:00")
        result = price_observations(original, [snapshot], [self.outcome()], self.now)
        self.assertEqual(result["status"], "pending_forward_price_path")

    def test_unchanged_restamps_group_without_changing_exact_review_anchor(self):
        self.assertEqual(reasoning_fingerprint(self.original), reasoning_fingerprint(self.later))
        store = {"schema_version": STORE_SCHEMA, "records": [self.original, self.later]}
        with patch("thesis_evidence.evidence_context", return_value=self.context):
            result = thesis_review_summary(store, [self.snapshot()], [self.outcome()], now=self.now,
                                          evidence_root=self.root, held_tickers={"ABC", "ETF"})
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["recorded_versions"], 2)
        self.assertEqual(result["distinct_reasoning_cases"], 1)
        self.assertEqual(result["recorded_method_cases"], 1)
        self.assertEqual(result["prospective_method_cases"], 0)
        self.assertEqual(result["retrospective_cases"], 1)
        self.assertEqual(result["business_evidence_cases"], 0)
        self.assertEqual(result["cases"][0]["original_review_id"], self.original["review_id"])
        self.assertEqual(result["adoption_queue"][0]["priority"], "held")
        self.assertEqual(result["shared_exposure_coverage"], "unknown")
        rendered = "\n".join(render_thesis_review(result))
        self.assertIn("Thesis-based learning", rendered)
        self.assertIn("not_yet_observable", rendered)
        self.assertIn("no causal alpha", rendered)
        result["cases"][0].update(prospective_method_recorded=True, scheduled_review_due=True)
        due_render = "\n".join(render_thesis_review(result))
        self.assertIn("1 substantive original theses are due", due_render)
        self.assertIn("ABC v1 (held)", due_render)

    def test_missing_method_is_actionable_and_unchanged_store_stays_unchanged(self):
        original = copy.deepcopy(self.original)
        original.pop("research_method")
        original = seal_review(original)
        store = {"schema_version": STORE_SCHEMA, "records": [original]}
        before = copy.deepcopy(store)
        with patch("thesis_evidence.evidence_context", return_value=self.context):
            result = thesis_review_summary(store, [self.snapshot()], [self.outcome()], now=self.now,
                                          evidence_root=self.root, held_tickers={"ABC"})
        self.assertEqual(store, before)
        self.assertEqual(result["prospective_method_cases"], 0)
        self.assertEqual(result["retrospective_cases"], 0)
        self.assertEqual(result["adoption_queue"][0]["ticker"], "ABC")
        self.assertTrue(result["adoption_queue"][0]["next_evidence"])
        self.assertIn("No source-bound thesis retrospective", "\n".join(render_thesis_review(result)))

    def test_unknown_consensus_does_not_create_mandatory_adoption_work(self):
        from test_investment_reasoning import method_fixture
        original = method_fixture(self.root, self.original)
        with patch("thesis_evidence.evidence_context", return_value=self.context):
            result = thesis_review_summary({"schema_version": STORE_SCHEMA, "records": [original]},
                [], [], now=self.now, evidence_root=self.root, held_tickers={"ABC"})
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(original["research_method"]["market_consensus"]["status"], "unknown")
        self.assertEqual(result["adoption_queue"], [])
        self.assertEqual(result["prospective_method_cases"], 1)
        self.assertEqual(result["shared_exposures"], [])
        self.assertEqual(result["shared_exposure_coverage"], "partial")
        self.assertIn("Unpaired or missing tags leave diversification unassessed", "\n".join(render_thesis_review(result)))
        original["research_method"]["loss_analysis"] = research_method_template()["loss_analysis"]
        original = seal_review(original)
        with patch("thesis_evidence.evidence_context", return_value=self.context):
            pending = thesis_review_summary({"schema_version": STORE_SCHEMA, "records": [original]},
                [], [], now=self.now, evidence_root=self.root, held_tickers={"ABC"})
        self.assertEqual(pending["adoption_queue"][0]["reason"], "loss_analysis_unknown")

    def test_shared_exposures_use_latest_valid_method_and_remain_qualitative(self):
        original = copy.deepcopy(self.original)
        loss = original["research_method"]["loss_analysis"]
        loss.update(status="assessed", unknowns=[],
            paths=[dict(path_id="conversion", steps=["Demand falls", "Cash conversion weakens"],
                impairment="Per-share cash capacity permanently declines", early_warning="New filing cash conversion declines",
                claim_ids=["growth", "dilution"], unknowns=[])],
            fragile_assumptions=[dict(assumption="Growth persists", adverse_change="Demand slows", consequence="Cash falls",
                claim_ids=["growth"], unknowns=[])],
            shared_exposures=[dict(risk_tag="technology_demand", mechanism="Revenue depends on sustained customer investment",
                claim_ids=["growth"], unknowns=[])])
        original = seal_review(original)
        second = copy.deepcopy(original)
        second.update(ticker="XYZ", review_id="xyz-review-1")
        second = seal_review(second)
        store = {"schema_version": STORE_SCHEMA, "records": [original, second]}
        # Source-byte validity is separately covered; isolate grouping mechanics.
        with patch("thesis_evidence.evidence_context", return_value=self.context), patch("thesis_evidence.validate_review"):
            result = thesis_review_summary(store, [], [], now=self.now, evidence_root=self.root)
        self.assertEqual(result["shared_exposures"][0]["tickers"], ["ABC", "XYZ"])
        self.assertEqual(result["shared_exposure_coverage"], "partial")
        self.assertNotIn("weight", str(result["shared_exposures"]))
        self.assertNotIn("correlation", str(result["shared_exposures"]))

    def test_unverifiable_original_does_not_become_verified_business_outcome(self):
        later = copy.deepcopy(self.later)
        later["retrospective"]["business_outcome"].update(status="supported", claim_ids=["growth"])
        later["sources"][0]["published_at"] = "2026-09-28T20:00:00+00:00"
        later = seal_review(later)
        store = {"schema_version": STORE_SCHEMA, "records": [self.original, later]}
        def validate(record, *args):
            if record["review_id"] == self.original["review_id"]:
                raise ValueError("original retained source unavailable")
        with patch("thesis_evidence.evidence_context", return_value=self.context), patch("thesis_evidence.validate_review", side_effect=validate):
            result = thesis_review_summary(store, [], [], now=self.now, evidence_root=self.root)
        self.assertEqual(result["status"], "partial_evidence")
        self.assertEqual(result["business_evidence_cases"], 0)
        self.assertIn("original_source_evidence_unverified", result["cases"][0]["pending_reasons"])

    def test_malformed_and_future_method_stay_visible_gaps_without_future_content(self):
        for method in ("invalid object", dict(research_method_template(), authored_at="2026-10-02T00:00:00+00:00")):
            if isinstance(method, dict):
                method["waiting_for"]["next_evidence"] = "FUTURE_ONLY_CONTENT"
            original = seal_review(dict(self.original, research_method=method))
            store = {"schema_version": STORE_SCHEMA, "records": [original]}
            with patch("thesis_evidence.evidence_context", return_value=self.context):
                result = thesis_review_summary(store, [self.snapshot()], [self.outcome()], now=self.now, evidence_root=self.root)
            self.assertEqual(result["status"], "partial_evidence")
            self.assertTrue(result["validation_errors"])
            self.assertEqual(result["prospective_method_cases"], 0)
            self.assertEqual(result["cases"], [])
            self.assertNotIn("FUTURE_ONLY_CONTENT", str(result))

    def test_malformed_optional_dossier_json_does_not_stop_evaluation(self):
        def read(path, *args):
            if path == evaluation_cli.ROOT / evaluation_cli.STORE_REL:
                raise ValueError("malformed thesis JSON")
            return {}
        with patch.object(evaluation_cli, "read_json", side_effect=read), patch.object(evaluation_cli, "read_jsonl", return_value=[]), \
             patch.object(evaluation_cli, "read_csv", return_value=[]), patch.object(evaluation_cli, "load_performance_records", return_value=[]):
            report = evaluation_cli.build_report()
        self.assertEqual(report["thesis_review"]["status"], "invalid_evidence")
        self.assertIn("malformed thesis JSON", evaluation_cli.render(report))


if __name__ == "__main__":
    unittest.main()
