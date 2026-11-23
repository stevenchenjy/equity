"""Objective-only borrowed history keeps validation and callback ownership."""
from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import weakref

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_json, canonical_sha256, read_json
import opportunity_contract as contract
import research_opportunities as opportunities
import test_objective_transition_batch as objective_fixtures

NOW = objective_fixtures.NOW
CURRENT = objective_fixtures.CURRENT
BACKLOG = Path("04_research/company_research/research_backlog.local.json")


class ObjectiveHistoryLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = objective_fixtures.ObjectiveTransitionBatchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def assert_artifacts_equal(self, left, right):
        for relative in (contract.STORE_REL, contract.REPORT_REL, contract.MARKDOWN_REL):
            self.assertEqual((left / relative).read_bytes(), (right / relative).read_bytes())
        for relative in (contract.BASE_REL / "history", contract.BASE_REL / "run_history"):
            snapshots = []
            for root in (left, right):
                directory = root / relative
                snapshots.append({str(path.relative_to(directory)): path.read_bytes()
                                  for path in directory.rglob("*") if path.is_file()})
            self.assertEqual(*snapshots)

    def native_objective(self, root, *, legacy=False):
        values = iter(NOW + timedelta(seconds=n) for n in range(11, 80))
        provider = opportunities.objective_research
        with patch.object(opportunities, "objective_research", wraps=provider) as calls, \
                patch("research_backlog.refresh_attention_view"), \
                patch.object(opportunities.time, "monotonic", return_value=100):
            if legacy:
                namespace = dict(vars(opportunities))
                exec(objective_fixtures.LEGACY_OBJECTIVE, namespace)
                function = namespace["objective"]
            else:
                function = opportunities.objective
            result = function(root, current=CURRENT, allow_network=False, clock=lambda: next(values))
        return result, [call.args[1]["ticker"] for call in calls.call_args_list]

    def test_borrowed_objective_matches_exact_legacy_journal_report_text_and_histories(self):
        specs = [("AQUE", "queued", "success", 0),
                 ("BBLOCK", "data_blocked", "blocked", 1),
                 ("CSUPPORT", "research_supported", "changed", 0),
                 ("DCACHE", "evidence_attached", "cached", 0),
                 ("ERESEARCH", "researching", "blocked", 0),
                 ("FUNCHANGE", "data_blocked", "blocked", 0)]
        dossiers = self.fixture.setup_store(specs)
        with tempfile.TemporaryDirectory() as directory:
            legacy_root = Path(directory) / "legacy"
            shutil.copytree(self.root, legacy_root)
            expected, old_order = self.fixture.run_objective(legacy_root, specs, dossiers, legacy=True)
            actual, new_order = self.fixture.run_objective(self.root, specs, dossiers)
            self.assertEqual((actual, new_order), (expected, old_order))
            self.assert_artifacts_equal(self.root, legacy_root)

    def test_native_offline_provider_order_clocks_and_shared_budget_match_legacy(self):
        specs = [("ACACHE", "evidence_attached", "cached", 0),
                 ("BBLOCK", "data_blocked", "blocked", 0),
                 ("CQUE", "queued", "blocked", 0)]
        self.fixture.setup_store(specs)
        atomic_write_json(self.root / "00_project_control/active_production_config.json",
                          {"workflow": {"objective_research_max_tickers": 4}})
        atomic_write_json(self.root / BACKLOG, {"generated_at": CURRENT.isoformat(),
            "selected_tickers": ["PRIOR1", "PRIOR2"], "reserved_external_event_tickers": ["CQUE"]})
        with tempfile.TemporaryDirectory() as directory:
            legacy_root = Path(directory) / "legacy"
            shutil.copytree(self.root, legacy_root)
            expected, old_order = self.native_objective(legacy_root, legacy=True)
            actual, new_order = self.native_objective(self.root)
            self.assertEqual((actual, new_order), (expected, old_order))
            self.assertEqual(new_order, ["CQUE", "ACACHE", "BBLOCK"])
            self.assertEqual(actual["metrics"]["objective_items_processed"], 2)
            self.assertEqual(actual["metrics"]["canonical_issuers_attempted_before_intake"], 2)
            self.assertEqual(actual["metrics"]["shared_objective_work_budget"], 4)
            self.assertEqual(actual["metrics"]["network_requests"], 0)
            self.assert_artifacts_equal(self.root, legacy_root)

    def test_only_eligible_records_are_prioritized_but_inactive_history_still_validates(self):
        specs = [("ACTIVE", "queued", "blocked", 0),
                 ("CLOSED", "queued", "blocked", 0),
                 ("DEFER", "queued", "blocked", 0)]
        dossiers = self.fixture.setup_store(specs)
        store = read_json(self.root / contract.STORE_REL)
        items = {row["ticker"]: row for row in contract.replay(store).values()}
        for ticker, target in (("CLOSED", "expired"), ("DEFER", "deferred_capacity")):
            item = items[ticker]
            contract.transition(store, item["opportunity_id"], target, owner="research_orchestration",
                reason="fixture inactive work", sources=item["first_observation"]["sources"],
                blockers=[], current=NOW)
        atomic_write_json(self.root / contract.STORE_REL, store)
        priority = opportunities.work_priority
        with patch.object(opportunities, "work_priority", wraps=priority) as rank:
            report, calls = self.fixture.run_objective(self.root, specs, dossiers)
        self.assertEqual(calls, ["ACTIVE"])
        self.assertEqual([call.args[0]["ticker"] for call in rank.call_args_list], ["ACTIVE"])
        self.assertEqual(report["metrics"]["states"]["expired"], 1)
        self.assertEqual(report["metrics"]["states"]["deferred_capacity"], 1)
        # Rechain an invalid *inactive* detection so validation cannot merely
        # fail on an unrelated digest before exercising the required field.
        invalid = copy.deepcopy(store)
        event = next(event for event in invalid["events"]
                     if event["kind"] == "detected" and event["observation"]["ticker"] == "CLOSED")
        del event["reason_code"]
        self.rechain(invalid)
        atomic_write_json(self.root / contract.STORE_REL, invalid)
        with patch.object(opportunities, "work_priority", side_effect=AssertionError("priority ran before validation")), \
                patch.object(opportunities, "objective_research", side_effect=AssertionError("provider ran before validation")):
            with self.assertRaisesRegex(KeyError, "reason_code"):
                opportunities.objective(self.root, current=CURRENT)

    def test_borrowed_read_has_detached_wrappers_while_public_replay_stays_deeply_isolated(self):
        self.fixture.setup_store([("TASK", "data_blocked", "blocked", 0)])
        previous, borrowed, proof = contract.read_validated_store(self.root, current=CURRENT, borrow_history=True)
        self.assertIsNotNone(proof)
        identity = previous["events"][0]["opportunity_id"]
        packet = previous["events"][0]["observation"]
        self.assertIs(borrowed[identity]["first_observation"], packet)
        self.assertIs(borrowed[identity]["observations"][0], packet)
        self.assertIs(borrowed[identity]["transitions"][0], previous["events"][-1])
        before = copy.deepcopy(previous)
        borrowed[identity]["state"] = "wrapper-only"
        borrowed[identity]["observations"].append({"wrapper": "only"})
        borrowed[identity]["transitions"].clear()
        self.assertEqual(previous, before)
        for projected in (contract.replay(previous, root=self.root, current=CURRENT),
                          contract.read_validated_store(self.root, current=CURRENT)[1]):
            projected[identity]["first_observation"]["evidence"]["metrics"]["rank"] = 999
            projected[identity]["observations"][0]["sources"][0]["sha256"] = "f" * 64
            projected[identity]["transitions"][0]["reason_code"] = "caller mutation"
        self.assertEqual(previous, before)
        self.assertEqual(read_json(self.root / contract.STORE_REL), before)

    def test_provider_mutation_cannot_reach_borrowed_history_or_unchanged_journal(self):
        self.fixture.setup_store([("TASK", "data_blocked", "blocked", 0)])
        before = (self.root / contract.STORE_REL).read_bytes()
        seen = []

        def adversarial_provider(root, item, **kwargs):
            seen.append(item["ticker"])
            item["ticker"] = "MUTATED"
            item["state"] = "queued"
            item["blockers"].append("caller-only blocker")
            item["first_observation"]["evidence"]["metrics"]["rank"] = -999
            item["observations"][0]["sources"][0]["sha256"] = "f" * 64
            item["transitions"][0]["reason_code"] = "caller-only transition"
            return None, "same-block"

        with patch.object(opportunities, "objective_research", side_effect=adversarial_provider), \
                patch("research_backlog.refresh_attention_view"):
            report = opportunities.objective(self.root, current=CURRENT)
        self.assertEqual(seen, ["TASK"])
        self.assertEqual((self.root / contract.STORE_REL).read_bytes(), before)
        item = report["opportunities"][0]
        self.assertEqual((item["ticker"], item["state"]), ("TASK", "data_blocked"))
        self.assertNotIn("caller-only blocker", item["blockers"])
        self.assertEqual(item["first_observation"]["evidence"]["metrics"]["rank"], 1)
        self.assertEqual(report["metrics"]["unchanged_items_skipped"], 1)

    @staticmethod
    def rechain(store):
        previous = ""
        for event in store["events"]:
            event["previous_hash"] = previous
            event["record_hash"] = canonical_sha256({key: value for key, value in event.items()
                                                     if key != "record_hash"})
            previous = event["record_hash"]

    def test_borrowed_read_keeps_source_future_clock_and_required_field_validation(self):
        self.fixture.setup_store([("TASK", "queued", "blocked", 0)])
        original = read_json(self.root / contract.STORE_REL)
        source = self.root / original["events"][0]["observation"]["sources"][0]["path"]
        raw_source = source.read_bytes()
        for fault in ("source", "future_event", "future_receipt", "required_field"):
            for borrow in (False, True):
                with self.subTest(fault=fault, borrow=borrow):
                    value = copy.deepcopy(original)
                    expected = ValueError
                    if fault == "source":
                        source.write_bytes(b"changed retained fixture")
                    elif fault == "future_event":
                        value["events"][-1]["recorded_at"] = (CURRENT + timedelta(seconds=1)).isoformat()
                    elif fault == "future_receipt":
                        value["events"][0]["observation"]["sources"][0]["available_at"] = (CURRENT + timedelta(hours=1)).isoformat()
                    else:
                        del value["events"][0]["reason_code"]
                        expected = KeyError
                    self.rechain(value)
                    atomic_write_json(self.root / contract.STORE_REL, value)
                    try:
                        with self.assertRaises(expected):
                            contract.read_validated_store(self.root, current=CURRENT, borrow_history=borrow)
                    finally:
                        source.write_bytes(raw_source)

    def test_backlog_is_released_before_prior_report_load_with_zero_or_nonzero_work_budget(self):
        class Backlog(dict):
            pass

        for remaining in (0, 1):
            with self.subTest(remaining=remaining):
                self.fixture.setup_store([("TASK", "queued", "blocked", 0)])
                atomic_write_json(self.root / BACKLOG, {"generated_at": CURRENT.isoformat(),
                    "selected_tickers": ["PRIOR" + str(index) for index in range(10 - remaining)],
                    "reserved_external_event_tickers": ["TASK"]})
                reader = opportunities.read_json
                references = []

                def track_backlog(path, *args, **kwargs):
                    if path == self.root / BACKLOG:
                        value = Backlog(reader(path, *args, **kwargs),
                                        unused_history=[{"fixture": "unused backlog projection"}])
                        references.append(weakref.ref(value))
                        return value
                    if path == self.root / contract.REPORT_REL:
                        self.assertTrue(references)
                        self.assertIsNone(references[-1](), "backlog still live during prior report allocation")
                    return reader(path, *args, **kwargs)

                with patch.object(opportunities, "read_json", side_effect=track_backlog), \
                        patch.object(opportunities, "objective_research", return_value=(None, "fixture_missing")) as provider, \
                        patch("research_backlog.refresh_attention_view"):
                    report = opportunities.objective(self.root, current=CURRENT)
                self.assertEqual(provider.call_count, remaining)
                self.assertEqual(report["metrics"]["objective_items_processed"], remaining)
                self.assertTrue(references)
                self.assertIsNone(references[-1]())


if __name__ == "__main__":
    unittest.main()
