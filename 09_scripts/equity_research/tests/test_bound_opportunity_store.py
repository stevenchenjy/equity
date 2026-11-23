"""Bound initial reads keep every journal/source/publication fence intact."""
from __future__ import annotations

import copy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_json, canonical_sha256, read_json
import opportunity_contract as contract
import test_research_opportunities as fixtures

NOW = fixtures.NOW


class BoundOpportunityStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OpportunityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.path = self.root / contract.STORE_REL
        self.store = self.fixture.queue_store([("AONE", "queued", 1, False), ("BTWO", "queued", 2, False)])
        atomic_write_json(self.path, self.store)

    def load(self, root=None, current=NOW):
        return contract.read_validated_store(root or self.root, current=current)

    def history_bytes(self, root):
        folder = root / contract.BASE_REL / "history"
        return {str(path.relative_to(folder)): path.read_bytes() for path in folder.rglob("*") if path.is_file()}

    def test_bound_publication_matches_legacy_current_history_and_no_change_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_root = Path(directory) / "legacy"
            shutil.copytree(self.root, legacy_root)
            previous, items, proof = self.load()
            legacy_previous = read_json(legacy_root / contract.STORE_REL)
            self.assertEqual(items, contract.replay(legacy_previous, root=legacy_root, current=NOW))
            before = self.path.read_bytes()
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous, current=NOW,
                                   previous_proof=proof)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(self.history_bytes(self.root), {})
            candidate, legacy = copy.deepcopy(previous), copy.deepcopy(legacy_previous)
            identity = next(iter(items))
            for store in (candidate, legacy):
                contract.transition(store, identity, "researching", owner="objective_research",
                    reason="bound_read_fixture", sources=items[identity]["first_observation"]["sources"],
                    blockers=[], current=NOW + timedelta(seconds=1))
            contract.publish_store(legacy_root, legacy, previous=legacy_previous, current=NOW + timedelta(seconds=1))
            contract.publish_store(self.root, candidate, previous=previous, current=NOW + timedelta(seconds=1),
                                   previous_proof=proof)
            self.assertEqual(self.path.read_bytes(), (legacy_root / contract.STORE_REL).read_bytes())
            self.assertEqual(self.history_bytes(self.root), self.history_bytes(legacy_root))

    def test_bound_publication_never_decodes_or_reads_whole_current_store_again(self):
        previous, _, proof = self.load()
        original_read = Path.read_bytes
        original_json = contract.read_json
        def guarded_bytes(path):
            self.assertNotEqual(path, self.path, "second whole-store allocation")
            return original_read(path)
        def guarded_json(path, *args, **kwargs):
            self.assertNotEqual(path, self.path, "second whole-store JSON decode")
            return original_json(path, *args, **kwargs)
        with patch.object(Path, "read_bytes", new=guarded_bytes), \
                patch.object(contract, "read_json", side_effect=guarded_json):
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                   current=NOW, previous_proof=proof)

    def test_bound_initial_decode_keeps_legacy_utf8_acceptance_and_rejections(self):
        payload = copy.deepcopy(self.store)
        payload["unicode_metadata"] = 'café 日本語 😀 combining e\u0301 quote" LF\n'
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.path.write_bytes(text.encode("utf-8"))
        legacy = read_json(self.path)
        previous, items, proof = self.load()
        self.assertEqual(previous, legacy)
        self.assertEqual(previous["unicode_metadata"], payload["unicode_metadata"])
        self.assertEqual(items, contract.replay(legacy, root=self.root, current=NOW))
        contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                               current=NOW, previous_proof=proof)
        self.assertEqual(self.path.read_bytes(), text.encode("utf-8"))
        for name, raw in (("utf8_bom", text.encode("utf-8-sig")),
                          ("utf16", text.encode("utf-16")),
                          ("utf32", text.encode("utf-32")),
                          ("invalid_utf8", b"\xff" + text.encode("utf-8"))):
            with self.subTest(encoding=name):
                self.path.write_bytes(raw)
                with self.assertRaises((UnicodeDecodeError, json.JSONDecodeError)):
                    read_json(self.path)
                with self.assertRaises((UnicodeDecodeError, json.JSONDecodeError)):
                    self.load()
                self.assertEqual(self.path.read_bytes(), raw)

    def test_fake_copied_or_wrong_root_proofs_cannot_admit_publication(self):
        previous, _, proof = self.load()
        before = self.path.read_bytes()
        for fake in (object(), copy.copy(proof), "a" * 64):
            with self.subTest(fake=type(fake).__name__):
                with self.assertRaises(ValueError):
                    contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                           current=NOW, previous_proof=fake)
                self.assertEqual(self.path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "other"
            shutil.copytree(self.root, other)
            with self.assertRaises(ValueError):
                contract.publish_store(other, copy.deepcopy(previous), previous=previous,
                                       current=NOW, previous_proof=proof)
            self.assertEqual((other / contract.STORE_REL).read_bytes(), before)

    def test_mutated_previous_header_count_or_rehashed_prefix_fails_closed(self):
        baseline = self.path.read_bytes()
        for mutation in ("header", "count", "rehashed_prefix", "truncated_final"):
            with self.subTest(mutation=mutation):
                previous, _, proof = self.load()
                candidate = copy.deepcopy(previous)
                if mutation == "header":
                    previous["extra_metadata"] = "changed after read"
                    candidate["extra_metadata"] = "changed after read"
                elif mutation == "count":
                    previous["events"].pop()
                elif mutation == "rehashed_prefix":
                    previous["events"][0]["reason_code"] = "changed history"
                    prior = ""
                    for event in previous["events"]:
                        event["previous_hash"] = prior
                        event["record_hash"] = canonical_sha256({k: v for k, v in event.items() if k != "record_hash"})
                        prior = event["record_hash"]
                    candidate = copy.deepcopy(previous)
                    contract.validate_journal(candidate, root=self.root, current=NOW)
                else:
                    candidate["events"].pop()
                with self.assertRaises(ValueError):
                    contract.publish_store(self.root, candidate, previous=previous, current=NOW,
                                           previous_proof=proof)
                self.assertEqual(self.path.read_bytes(), baseline)
                self.assertEqual(self.history_bytes(self.root), {})

    def test_raw_replacement_and_source_or_clock_changes_preserve_current_and_history(self):
        baseline = self.path.read_bytes()
        previous, items, proof = self.load()
        # Formatting alone is a real concurrent byte replacement, even though
        # legacy semantic comparison would accept it. Bound reads fail closed.
        self.path.write_bytes(baseline + b"\n")
        with self.assertRaises(ValueError):
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                   current=NOW, previous_proof=proof)
        self.assertEqual(self.path.read_bytes(), baseline + b"\n")
        self.path.write_bytes(baseline)
        previous, items, proof = self.load()
        source = self.root / next(iter(items.values()))["first_observation"]["sources"][0]["path"]
        source.write_bytes(b"changed retained source")
        with self.assertRaisesRegex(ValueError, "source_changed"):
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                   current=NOW, previous_proof=proof)
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(self.path.read_bytes(), baseline)
        self.assertEqual(self.history_bytes(self.root), {})

    def test_initial_and_final_clock_checks_are_not_inherited_from_a_read_proof(self):
        with self.assertRaisesRegex(ValueError, "clock_regression"):
            self.load(current=NOW - timedelta(microseconds=1))
        previous, _, proof = self.load()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "clock_regression"):
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                current=NOW - timedelta(microseconds=1), previous_proof=proof)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_store_proof_cannot_accept_a_file_that_appeared_after_read(self):
        self.path.unlink()
        previous, items, proof = self.load()
        self.assertEqual(previous, contract.empty_store())
        self.assertEqual(items, {})
        atomic_write_json(self.path, contract.empty_store())
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                   current=NOW, previous_proof=proof)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.history_bytes(self.root), {})

    def test_empty_initial_publication_matches_legacy_and_still_binds_header(self):
        self.path.unlink()
        with tempfile.TemporaryDirectory() as directory:
            legacy_root = Path(directory) / "legacy"
            shutil.copytree(self.root, legacy_root)
            previous, items, proof = self.load()
            self.assertEqual(items, {})
            contract.publish_store(legacy_root, contract.empty_store(), previous=contract.empty_store(), current=NOW)
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                   current=NOW, previous_proof=proof)
            self.assertEqual(self.path.read_bytes(), (legacy_root / contract.STORE_REL).read_bytes())
            self.assertEqual(self.history_bytes(self.root), self.history_bytes(legacy_root))
        previous, _, proof = self.load()
        before = self.path.read_bytes()
        previous["new_metadata"] = "empty history is not an unbound header"
        with self.assertRaises(ValueError):
            contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                   current=NOW, previous_proof=proof)
        self.assertEqual(self.path.read_bytes(), before)

    def test_file_changed_during_fresh_stream_hash_never_publishes(self):
        previous, _, proof = self.load()
        original = self.path.read_bytes()
        real_open = Path.open
        changed = []
        target = self.path
        class ChangingReader:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): self.stream.__enter__(); return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def __getattr__(self, name): return getattr(self.stream, name)
            def read(self, *args):
                data = self.stream.read(*args)
                if data and not changed:
                    changed.append(True)
                    target.write_bytes(original + b"\n")
                return data
            def readinto(self, buffer):
                count = self.stream.readinto(buffer)
                if count and not changed:
                    changed.append(True)
                    target.write_bytes(original + b"\n")
                return count
        def opened(path, mode="r", *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            return ChangingReader(stream) if path == target and mode == "rb" else stream
        with patch.object(Path, "open", new=opened):
            with self.assertRaises(ValueError):
                contract.publish_store(self.root, copy.deepcopy(previous), previous=previous,
                                       current=NOW, previous_proof=proof)
        self.assertTrue(changed, "fixture must exercise the fresh streamed current-file hash")
        self.assertEqual(self.path.read_bytes(), original + b"\n")
        self.assertEqual(self.history_bytes(self.root), {})


if __name__ == "__main__":
    unittest.main()
