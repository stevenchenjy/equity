"""Backlog proof reuse preserves canonical updates and live validation fences."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import weakref

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_json, canonical_sha256, read_json, sha256_file
from earnings_incorporation import CACHE_REL
import opportunity_contract as contract
from opportunity_triggers import packet
import research_backlog as backlog
import research_opportunities as opportunities
import test_research_backlog as backlog_fixtures
import validation_cache

NOW = backlog_fixtures.NOW


class BacklogReportProofScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = backlog_fixtures.ResearchBacklogTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root.resolve()
        destination = self.root / contract.POLICY_REL
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SCRIPT_DIR.parents[1] / contract.POLICY_REL, destination)
        self.publish_attention()

    def publish_attention(self, *, direct_fundamentals=False, changed=False):
        if direct_fundamentals:
            path = self.root / backlog.FUNDAMENTALS_REL
            source = {"path": str(backlog.FUNDAMENTALS_REL), "sha256": sha256_file(path),
                      "available_at": NOW.isoformat()}
        else:
            source = contract.retain_input(self.root, self.root / CACHE_REL / "ABC.selection.json",
                                           available_at=NOW.isoformat())
        observation = packet(ticker="ABC", family="request", trigger="owner_requested_research",
            evidence={"question": "changed source-bound question" if changed else "source-bound question"},
            sources=[source], current=NOW,
            produced_by={"implementation_sha256": "a" * 64, "policy_sha256": "b" * 64})
        if changed:
            store = read_json(self.root / contract.STORE_REL)
            identity = store["events"][0]["opportunity_id"]
            contract.append_event(store, {"kind": "observed", "opportunity_id": identity,
                "observation": observation, "recorded_at": NOW.isoformat()})
        else:
            identity = canonical_sha256({"first_observation_id": observation["observation_id"],
                                         "ticker": observation["ticker"]})
            store = contract.empty_store()
            contract.append_event(store, {"kind": "detected", "opportunity_id": identity,
                "observation": observation, "recorded_at": NOW.isoformat(),
                "owner": "research_orchestration", "to_state": "queued",
                "reason_code": "fixture_research", "blockers": []})
        atomic_write_json(self.root / contract.STORE_REL, store)
        return opportunities.publish_view(self.root, store, current=NOW,
            metrics=opportunities._base_metrics(), diagnostics={})

    def execute(self, root, *, legacy=False):
        context = patch.object(opportunities, "report_proof_scope", return_value=nullcontext()) if legacy else nullcontext()
        with context, patch("earnings_incorporation.iso_now", return_value=NOW.isoformat()):
            return backlog.run(input_root=root, output_root=root, current=NOW,
                               max_tickers=3, apply_objective_updates=True)

    def test_run_matches_unscoped_bytes_and_proves_unchanged_journal_once_after_canonical_update(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_root = Path(directory) / "legacy"
            shutil.copytree(self.root, legacy_root)
            validate = opportunities.validate_journal
            with patch.object(opportunities, "validate_journal", wraps=validate) as old_proof:
                expected = self.execute(legacy_root, legacy=True)
            with patch.object(opportunities, "validate_journal", wraps=validate) as new_proof:
                actual = self.execute(self.root)
            self.assertEqual(old_proof.call_count, 2)
            self.assertEqual(new_proof.call_count, 1)
            self.assertEqual(actual, expected)
            self.assertEqual(actual["canonical_numeric_updates"], 1)
            self.assertIn("attention_state", actual["issuer_queue"][0])
            for relative in (backlog.REPORT_REL, backlog.MARKDOWN_REL, backlog.HISTORY_REL,
                             backlog.FUNDAMENTALS_REL, CACHE_REL / "ABC.selection.json"):
                self.assertEqual((self.root / relative).read_bytes(),
                                 (legacy_root / relative).read_bytes())
            # The current selection changed, while the report's retained
            # historical copy stays valid. Reusing its proof is legitimate.
            report = opportunities.read_report(self.root, current=NOW)
            retained = report["opportunities"][0]["first_observation"]["sources"][0]
            self.assertNotEqual(sha256_file(self.root / CACHE_REL / "ABC.selection.json"), retained["sha256"])
            self.assertEqual(sha256_file(self.root / retained["path"]), retained["sha256"])

    def test_canonical_update_invalidating_direct_receipt_is_not_hidden_by_scope(self):
        self.publish_attention(direct_fundamentals=True)
        with tempfile.TemporaryDirectory() as directory:
            legacy_root = Path(directory) / "legacy"
            shutil.copytree(self.root, legacy_root)
            expected = self.execute(legacy_root, legacy=True)
            actual = self.execute(self.root)
            self.assertEqual(actual, expected)
            self.assertEqual(actual["canonical_numeric_updates"], 1)
            self.assertNotIn("attention_state", actual["issuer_queue"][0])
            self.assertEqual(backlog.attention_rows(self.root, NOW), [])
            with self.assertRaisesRegex(ValueError, "research_source_changed"):
                opportunities.read_report(self.root, current=NOW)
            for relative in (backlog.REPORT_REL, backlog.MARKDOWN_REL, backlog.HISTORY_REL):
                self.assertEqual((self.root / relative).read_bytes(),
                                 (legacy_root / relative).read_bytes())

    def test_initial_attention_and_last_item_are_released_before_final_read_including_empty_input(self):
        class TrackedList(list):
            pass

        class TrackedOpportunity(dict):
            pass

        read_attention = backlog.attention_rows
        for empty in (False, True):
            with self.subTest(empty=empty), tempfile.TemporaryDirectory() as directory:
                actual_root = Path(directory) / "actual"
                legacy_root = Path(directory) / "legacy"
                shutil.copytree(self.root, actual_root)
                if empty:
                    (actual_root / contract.REPORT_REL).unlink()
                shutil.copytree(actual_root, legacy_root)
                expected = self.execute(legacy_root, legacy=True)
                references = {}
                calls = []

                def track_lifetime(root, current):
                    calls.append(root)
                    if len(calls) == 1:
                        rows = read_attention(root, current)
                        self.assertEqual(bool(rows), not empty)
                        tracked = TrackedList(TrackedOpportunity(row) for row in rows)
                        references["list"] = weakref.ref(tracked)
                        references["items"] = tuple(weakref.ref(row) for row in tracked)
                        return tracked
                    # No forced collection: the ordinary source objects have
                    # no cycles. The first list and the loop's last item must
                    # be gone before another full projection is allocated.
                    self.assertIsNone(references["list"]())
                    self.assertTrue(all(reference() is None for reference in references["items"]))
                    return read_attention(root, current)

                with patch.object(backlog, "attention_rows", side_effect=track_lifetime):
                    actual = self.execute(actual_root)
                self.assertEqual(len(calls), 2)
                self.assertEqual(actual, expected)
                for relative in (backlog.REPORT_REL, backlog.MARKDOWN_REL, backlog.HISTORY_REL):
                    self.assertEqual((actual_root / relative).read_bytes(),
                                     (legacy_root / relative).read_bytes())

    def test_replaced_report_and_store_require_a_second_complete_proof(self):
        validate = opportunities.validate_journal
        with opportunities.report_proof_scope(), \
                patch.object(opportunities, "validate_journal", wraps=validate) as proof:
            original = opportunities.read_report(self.root, current=NOW)
            self.publish_attention(changed=True)
            changed = opportunities.read_report(self.root, current=NOW)
            self.assertNotEqual(original["store_sha256"], changed["store_sha256"])
            self.assertEqual(len(changed["opportunities"][0]["observations"]), 2)
            self.assertEqual(proof.call_count, 2)
            self.assertEqual(opportunities.read_report(self.root, current=NOW), changed)
            self.assertEqual(proof.call_count, 2)

    def test_reused_proof_still_checks_current_authority_and_clock(self):
        validate = opportunities.validate_journal
        with opportunities.report_proof_scope(), \
                patch.object(opportunities, "validate_journal", wraps=validate) as proof:
            opportunities.read_report(self.root, current=NOW)
            with patch.object(opportunities, "load_authority", return_value={"mode": "changed_authority"}):
                with self.assertRaisesRegex(ValueError, "account_authority_changed"):
                    opportunities.read_report(self.root, current=NOW)
            with self.assertRaisesRegex(ValueError, "stale_clock"):
                opportunities.read_report(self.root, current=NOW + timedelta(hours=25))
            with self.assertRaisesRegex(ValueError, "stale_clock"):
                opportunities.read_report(self.root, current=NOW - timedelta(seconds=1))
            self.assertEqual(proof.call_count, 1)

    def test_reused_receipt_proof_keeps_ending_source_mutation_fence(self):
        resolve = opportunities.resolved_sha256
        with opportunities.report_proof_scope():
            report = opportunities.read_report(self.root, current=NOW)
            locator = report["opportunities"][0]["first_observation"]["sources"][0]["path"]
            source = self.root / locator
            original = source.read_bytes()

            def mutate_after_verified_digest(root, path, inside):
                result = resolve(root, path, inside)
                if path == locator:
                    source.write_bytes(b"changed after the last reused receipt lookup")
                return result

            try:
                with patch.object(opportunities, "resolved_sha256", side_effect=mutate_after_verified_digest):
                    with self.assertRaisesRegex(ValueError, "validation_sources_changed_during_transaction"):
                        opportunities.read_report(self.root, current=NOW)
            finally:
                source.write_bytes(original)

    def test_nested_and_exception_scopes_restore_context_and_never_share_reader_objects(self):
        prior_reports = opportunities._REPORT_PROOFS.get()
        prior_digests = validation_cache._OPERATION_DIGESTS.get()
        validate = opportunities.validate_journal
        with patch.object(opportunities, "validate_journal", wraps=validate) as proof:
            with self.assertRaisesRegex(RuntimeError, "fixture scope exit"):
                with opportunities.report_proof_scope():
                    first = opportunities.read_report(self.root, current=NOW)
                    expected = copy.deepcopy(first)
                    first["opportunities"].clear()
                    with opportunities.report_proof_scope():
                        self.assertEqual(opportunities.read_report(self.root, current=NOW), expected)
                    self.assertEqual(proof.call_count, 1)
                    raise RuntimeError("fixture scope exit")
            self.assertIs(opportunities._REPORT_PROOFS.get(), prior_reports)
            self.assertIs(validation_cache._OPERATION_DIGESTS.get(), prior_digests)
            with opportunities.report_proof_scope():
                self.assertEqual(opportunities.read_report(self.root, current=NOW), expected)
            self.assertEqual(proof.call_count, 2)


if __name__ == "__main__":
    unittest.main()
