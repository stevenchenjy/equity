"""Historical source recovery preserves plan hashes and current source bytes."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR
import capital_decision
from daily_common import atomic_write_json, canonical_sha256
import investment_plans as plans
import plan_source_resolutions as recovery
import register_plan_source_resolution as writer
from test_investment_plans import ledger, record
from workflow_inputs import WORKFLOW_INPUTS


class PlanSourceResolutionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.original = "03_source_data/equity_research/synthetic_current.csv"
        self.retained = "08_reviews/synthetic-review.local/retained.csv"
        self.old = b"ticker,close\nABC,41\n"
        self.new = b"ticker,close\nABC,43\n"
        self.put(self.original, self.old)
        self.put(self.retained, self.old)
        row = record(ticker="ABC", role="long_term_growth")
        row.update(action="hold", proposed_change_shares=0, order_draft=None,
                   sources=[{"path": self.original, "sha256": self.digest(self.old)}])
        self.ledger = ledger(row)
        self.put(recovery.PLAN_PATH, json.dumps(self.ledger).encode())
        self.put(self.original, self.new)
        self.current = datetime.fromisoformat("2026-09-25T12:00:00-04:00")
        self.proposal = dict(plan_id=row["plan_id"], plan_version=1,
            plan_record_hash=self.ledger["records"][0]["record_hash"], logical_path=self.original,
            expected_sha256=self.digest(self.old), retained_path=self.retained,
            reviewer="Synthetic analyst", reason="Exact historical source retained before current input changed.")
        self.empty = {"schema_version": recovery.SCHEMA, "records": []}

    def digest(self, raw):
        return hashlib.sha256(raw).hexdigest()

    def put(self, relative, raw):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def register(self, proposals=None):
        result, count = recovery.append_resolutions(self.empty, proposals or [self.proposal],
            self.ledger, root=self.root, current=self.current)
        atomic_write_json(self.root / recovery.RELATIVE_PATH, result)
        return result, count

    def test_exact_registration_restores_read_and_append_without_changing_history_or_current_data(self):
        with self.assertRaisesRegex(ValueError, "plan_source_hash_mismatch"):
            plans.validate_ledger(self.ledger, root=self.root)
        original_ledger = (self.root / recovery.PLAN_PATH).read_bytes()
        result, count = self.register()
        self.assertEqual(count, 1)
        self.assertEqual(plans.validate_ledger(self.ledger, root=self.root)["ABC-plan"]["record_hash"], self.proposal["plan_record_hash"])
        self.assertEqual((self.root / self.original).read_bytes(), self.new)
        self.assertEqual((self.root / recovery.PLAN_PATH).read_bytes(), original_ledger)
        proposal = deepcopy(self.ledger["records"][0])
        for key in ("version", "record_hash", "previous_hash", "supersedes"):
            proposal.pop(key)
        proposal["sources"] = [{"path": self.retained, "sha256": self.digest(self.old)}]
        appended = plans.append_plan(self.ledger, proposal, root=self.root)
        self.assertEqual(appended["records"][0], self.ledger["records"][0])
        self.assertEqual(appended["records"][-1]["version"], 2)
        again, added = recovery.append_resolutions(result, [self.proposal], self.ledger, root=self.root, current=self.current)
        self.assertEqual(added, 0)
        self.assertEqual(again, result)

    def test_resolution_cannot_authorize_new_proposal_with_same_mutable_source(self):
        self.register()
        proposal = deepcopy(self.ledger["records"][0])
        for key in ("version", "record_hash", "previous_hash", "supersedes"):
            proposal.pop(key)
        with self.assertRaisesRegex(ValueError, "plan_source_hash_mismatch"):
            plans.append_plan(self.ledger, proposal, root=self.root)

    def test_missing_original_is_recoverable_only_by_exact_registration(self):
        (self.root / self.original).unlink()
        with self.assertRaisesRegex(ValueError, "plan_source_missing"):
            plans.validate_ledger(self.ledger, root=self.root)
        self.register()
        plans.validate_ledger(self.ledger, root=self.root)

    def test_exact_identity_source_and_bytes_are_required(self):
        for changes in ({"plan_record_hash": "a" * 64}, {"plan_version": 2},
                        {"plan_id": "other"}, {"logical_path": "different.csv"},
                        {"expected_sha256": "b" * 64}, {"plan_version": True},
                        {"retained_path": self.original}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                recovery.append_resolutions(self.empty, [{**self.proposal, **changes}], self.ledger,
                    root=self.root, current=self.current)
        self.put(self.retained, b"different retained bytes")
        with self.assertRaisesRegex(ValueError, "retained_hash_mismatch"):
            recovery.append_resolutions(self.empty, [self.proposal], self.ledger, root=self.root, current=self.current)

    def test_missing_changed_symlink_and_outside_retained_files_fail_closed(self):
        self.register()
        path = self.root / self.retained
        path.unlink()
        with self.assertRaises(OSError):
            plans.validate_ledger(self.ledger, root=self.root)
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "retained_hash_mismatch"):
            plans.validate_ledger(self.ledger, root=self.root)
        other = self.root / "other.csv"
        other.write_bytes(self.old)
        path.unlink()
        path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink_rejected"):
            plans.validate_ledger(self.ledger, root=self.root)
        for relative in ("../outside.csv", "/tmp/outside.csv", "08_reviews/../other.csv"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                recovery.append_resolutions(self.empty, [{**self.proposal, "retained_path": relative}],
                    self.ledger, root=self.root, current=self.current)

    def test_parent_symlink_registry_symlink_and_nonregular_sources_are_rejected(self):
        alternate = self.root / "alternate"
        alternate.mkdir()
        (alternate / "retained.csv").write_bytes(self.old)
        link = self.root / "linked"
        link.symlink_to(alternate, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink_rejected"):
            recovery.append_resolutions(self.empty, [{**self.proposal, "retained_path": "linked/retained.csv"}],
                self.ledger, root=self.root, current=self.current)
        (self.root / recovery.RELATIVE_PATH).symlink_to(self.root / recovery.PLAN_PATH)
        with self.assertRaisesRegex(ValueError, "symlink_rejected"):
            plans.validate_ledger(self.ledger, root=self.root)
        (self.root / recovery.RELATIVE_PATH).unlink()
        (self.root / self.retained).unlink()
        (self.root / self.retained).mkdir()
        with self.assertRaisesRegex(ValueError, "file_invalid"):
            recovery.append_resolutions(self.empty, [self.proposal], self.ledger, root=self.root, current=self.current)

    def test_receipts_cannot_repair_tampered_plan_or_receipt_chain(self):
        payload, _ = self.register()
        bad = deepcopy(self.ledger)
        bad["records"][0]["instruction"] = "changed history"
        with self.assertRaises(ValueError):
            plans.validate_ledger(bad, root=self.root)
        for field, value in (("reason", "changed receipt"), ("previous_hash", "a" * 64),
                             ("registered_at", (self.current + timedelta(days=500)).isoformat())):
            changed = deepcopy(payload)
            changed["records"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                recovery.validate_registry(changed, self.ledger, root=self.root, current=self.current)

    def test_registry_and_explicit_retained_files_enter_capital_and_workflow_bindings(self):
        self.register()
        self.assertIn(recovery.RELATIVE_PATH, WORKFLOW_INPUTS)
        binding = capital_decision.binding(self.root)
        self.assertEqual(binding[self.retained], self.digest(self.old))
        self.assertEqual(binding[recovery.RELATIVE_PATH], self.digest((self.root / recovery.RELATIVE_PATH).read_bytes()))
        self.put(self.retained, b"changed")
        with self.assertRaisesRegex(ValueError, "retained_hash_mismatch"):
            capital_decision.binding(self.root)

    def test_cli_preview_apply_batch_and_retry_preserve_plan_and_live_sources(self):
        second_source, second_retained = "source2.json", "08_reviews/synthetic-review.local/source2.json"
        self.put(second_source, b"new 2")
        self.put(second_retained, b"old 2")
        self.ledger["records"][0]["sources"].append({"path": second_source, "sha256": self.digest(b"old 2")})
        row = self.ledger["records"][0]
        row["record_hash"] = canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
        self.put(recovery.PLAN_PATH, json.dumps(self.ledger).encode())
        first = {**self.proposal, "plan_record_hash": row["record_hash"]}
        second = {**first, "logical_path": second_source, "retained_path": second_retained,
                  "expected_sha256": self.digest(b"old 2")}
        proposal = self.root / "proposals.json"
        proposal.write_text(json.dumps({"resolutions": [first, second]}))
        args = ["--root", str(self.root), "--input", str(proposal)]
        before = (self.root / recovery.PLAN_PATH).read_bytes()
        self.assertEqual(writer.main(args), 0)
        self.assertFalse((self.root / recovery.RELATIVE_PATH).exists())
        self.assertEqual(writer.main([*args, "--apply"]), 0)
        registered = (self.root / recovery.RELATIVE_PATH).read_bytes()
        self.assertEqual(writer.main([*args, "--apply"]), 0)
        self.assertEqual((self.root / recovery.RELATIVE_PATH).read_bytes(), registered)
        self.assertEqual((self.root / recovery.PLAN_PATH).read_bytes(), before)
        self.assertEqual((self.root / self.original).read_bytes(), self.new)
        self.assertEqual((self.root / second_source).read_bytes(), b"new 2")
        plans.validate_ledger(self.ledger, root=self.root)

    def test_invalid_batch_never_partially_publishes_receipts(self):
        path = self.root / "invalid-batch.json"
        path.write_text(json.dumps({"resolutions": [self.proposal, {**self.proposal, "plan_version": 2}]}))
        before = (self.root / recovery.PLAN_PATH).read_bytes()
        with self.assertRaisesRegex(ValueError, "record_not_found"):
            writer.main(["--root", str(self.root), "--input", str(path), "--apply"])
        self.assertFalse((self.root / recovery.RELATIVE_PATH).exists())
        self.assertEqual((self.root / recovery.PLAN_PATH).read_bytes(), before)
        self.assertEqual((self.root / self.original).read_bytes(), self.new)


if __name__ == "__main__":
    unittest.main()
