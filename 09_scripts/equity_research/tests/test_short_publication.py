from __future__ import annotations

import json
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_json, canonical_sha256, sha256_file
import test_short_assessment as fixture_module
import short_assessment as short
import short_publication as publication


class ShortPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ShortAssessmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.runtime_lock = self.fixture.runtime_lock
        self.current = self.fixture.moment("09:31")
        self.claim = self.fixture.claim()
        self.row = self.claim["receipt"]

    def clock(self):
        return self.current

    def runner(self, name, script, allowed_to_fail, **kwargs):
        self.assertFalse(allowed_to_fail)
        self.assertEqual(kwargs["market_snapshot_mode"], "reuse_validated_snapshot")
        self.assertLessEqual(kwargs["maximum_child_seconds"], 75)
        if name == "daily_decision":
            self.fixture.typed_publication("09:32")
        if name == "current_status":
            self.current = self.fixture.moment("09:33")
        return {"name": name, "exit_code": 0, "allowed_to_fail": False}

    def run_publication(self, runner=None):
        return publication.run(self.root, self.row["claim_id"], clock=self.clock,
            runtime_lock=self.runtime_lock, step_runner=runner or self.runner)

    def test_real_typed_receipt_completes_claim_without_claiming_full_research(self):
        receipt = self.run_publication()
        self.assertEqual(receipt["outcome"], "passed")
        self.assertEqual([step["name"] for step in receipt["steps"]], list(publication.STEP_NAMES))
        self.assertFalse(receipt["fully_passed_research"])
        self.assertFalse(receipt["email_attempted"])
        self.assertFalse(receipt["email_sent"])
        self.assertEqual(receipt["artifacts"], short._hashes(self.root, publication.ARTIFACTS))
        immutable = self.root / short.RECEIPTS_REL / self.row["claim_id"] / (
            "publication-" + receipt["receipt_sha256"] + ".json")
        self.assertEqual(json.loads(immutable.read_text()), receipt)
        metadata = publication.validate_receipt(self.root, self.row, self.fixture.moment("09:35"))
        self.assertFalse(metadata["fully_passed_research"])
        # Route through the actual completion API after a bound input changes.
        # The publication's regenerated input hashes remain the authority.
        state = json.loads((self.root / short.STATE_REL).read_text())
        state["slots"][self.row["slot_id"]]["publication_recomposition_required"] = True
        atomic_write_json(self.root / short.STATE_REL, state)
        done = self.fixture.complete(self.fixture.result(self.claim))
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["publication"]["receipt_sha256"], receipt["receipt_sha256"])
        self.assertFalse(done["publication"]["fully_passed_research"])

    def test_exact_artifact_tamper_and_resealed_receipt_cannot_pass(self):
        receipt = self.run_publication()
        html = self.root / publication.ARTIFACTS[2]
        html.write_text(html.read_text() + "corrupt")
        with self.assertRaisesRegex(ValueError, "final_email_recomposition"):
            publication.validate_receipt(self.root, self.row, self.fixture.moment("09:35"))
        self.fixture.typed_publication("09:32")
        receipt["artifacts"][publication.ARTIFACTS[0]] = "0" * 64
        receipt["receipt_sha256"] = canonical_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})
        atomic_write_json(self.root / publication.STATE_REL, receipt)
        with self.assertRaisesRegex(ValueError, "artifact_changed"):
            publication.validate_receipt(self.root, self.row, self.fixture.moment("09:35"))

    def test_actual_account_or_analyst_change_rejects_before_any_steps(self):
        account = self.root / short.ACCOUNT_MARKET[0]
        account.parent.mkdir(parents=True, exist_ok=True)
        account.write_text("ticker,shares\nMETA,1\n")
        with self.assertRaisesRegex(ValueError, "account_or_market_changed"):
            self.run_publication(lambda *args, **kwargs: self.fail("no step may run"))
        account.unlink()
        path = self.root / short.MUTABLE_STORES[0]
        atomic_write_json(path, {"schema_version": "equity_investment_plans_v1", "records": [{"new_plan": True}]})
        with self.assertRaisesRegex(ValueError, "analyst_amendment_requires_full_refresh"):
            self.run_publication(lambda *args, **kwargs: self.fail("no step may run"))

    def test_source_validated_collector_append_is_recorded_separately(self):
        from opportunity_contract import empty_store
        other = fixture_module.ShortAssessmentTests()
        other.setUp()
        self.addCleanup(other.doCleanups)
        self.fixture, self.root, self.runtime_lock = other, other.root, other.runtime_lock
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, empty_store())
        self.fixture.typed_publication("09:20")
        self.claim = self.fixture.claim()
        self.row = self.claim["receipt"]
        def collector(name, script, allowed_to_fail, **kwargs):
            if name == "research_opportunity_intake":
                self.fixture.journal_detection("09:31")
            return self.runner(name, script, allowed_to_fail, **kwargs)
        receipt = self.run_publication(collector)
        self.assertEqual(receipt["outcome"], "passed")
        self.assertNotEqual(receipt["protected_before"]["stores"][short.OPPORTUNITY_JOURNAL],
                            receipt["protected_after"]["stores"][short.OPPORTUNITY_JOURNAL])
        self.assertEqual(receipt["protected_after"]["collector_changes"]["appended_records"], 1)
        metadata = publication.validate_receipt(self.root, self.row, self.fixture.moment("09:35"))
        self.assertFalse(metadata["fully_passed_research"])
        self.fixture.source.write_text("Changed retained original source.")
        with self.assertRaises(ValueError):
            publication.validate_receipt(self.root, self.row, self.fixture.moment("09:35"))

    def test_unchanged_journal_cannot_hide_corrupted_retained_source(self):
        from opportunity_contract import empty_store
        other = fixture_module.ShortAssessmentTests()
        other.setUp()
        self.addCleanup(other.doCleanups)
        self.fixture, self.root, self.runtime_lock = other, other.root, other.runtime_lock
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, empty_store())
        self.fixture.journal_detection("09:20")
        self.fixture.typed_publication("09:20")
        self.claim = self.fixture.claim()
        self.row = self.claim["receipt"]
        receipt = self.run_publication()
        self.assertEqual(receipt["outcome"], "passed")
        self.fixture.source.write_text("Corrupted existing journal source without changing store bytes.")
        with self.assertRaises(ValueError):
            publication.validate_receipt(self.root, self.row, self.fixture.moment("09:35"))

    def test_budget_expiry_and_child_timeout_never_publish_success(self):
        self.current = self.fixture.moment("09:40")
        with self.assertRaisesRegex(ValueError, "outside_claim_budget"):
            self.run_publication()
        self.current = self.fixture.moment("09:31")
        def slow(name, script, allowed_to_fail, **kwargs):
            self.current = self.fixture.moment("09:41")
            return {"name": name, "exit_code": 124}
        receipt = self.run_publication(slow)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertFalse(receipt["fully_passed_research"])
        with self.assertRaisesRegex(ValueError, "valid_no_send_receipt_required"):
            publication.validate_receipt(self.root, self.row, self.fixture.moment("09:41"))

    def test_successful_child_that_exhausts_budget_does_not_start_another_step(self):
        calls = []
        def slow(name, script, allowed_to_fail, **kwargs):
            calls.append(name)
            self.current = self.fixture.moment("09:41")
            return {"name": name, "exit_code": 0}
        receipt = self.run_publication(slow)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual(calls, [publication.STEP_NAMES[0]])
        self.assertIn("outside_claim_budget", receipt["reason"])

    def test_changed_inputs_during_closure_and_receipt_corruption_remain_fenced(self):
        def changed(name, script, allowed_to_fail, **kwargs):
            result = self.runner(name, script, allowed_to_fail, **kwargs)
            if name == "current_status":
                atomic_write_json(self.root / short.MUTABLE_STORES[0], {"records": [{"plan": "changed"}]})
            return result
        receipt = self.run_publication(changed)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertIn("analyst_amendment", receipt["reason"])
        receipt["outcome"] = "passed"
        atomic_write_json(self.root / publication.STATE_REL, receipt)
        with self.assertRaisesRegex(ValueError, "valid_no_send_receipt_required"):
            publication.validate_receipt(self.root, self.row, self.fixture.moment("09:35"))


if __name__ == "__main__":
    unittest.main()
