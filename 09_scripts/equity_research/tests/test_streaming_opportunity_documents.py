"""Byte and failure invariants for the scratch opportunity JSON prototype."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import opportunity_contract as document


def canonical_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def pretty_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")


class StreamingOpportunityDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="opportunity-document-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def store(self, values):
        value = document.empty_store()
        value["events"] = values
        return value

    def specimens(self):
        shared = {"nested": [{"empty": []}, {}, [1, {"leaf": True}]],
                  "text": 'quote" slash\\ LF\n tab\t nul\0 日本語 😀 e\u0301 \u2028 \u2029',
                  "numbers": [0, -0.0, 0.0, 1.2e-7, 1e20, 1e-300,
                              1.7976931348623157e308, 10**80,
                              float("inf"), float("-inf"), float("nan")],
                  "null": None, "boolean": False}
        # Repeated references are legal JSON input. They must not be mistaken
        # for cycles when a top-level array is encoded one item at a time.
        yield self.store([shared, "a\nb", None, True, [], {}, shared])
        yield self.store([])
        yield {"schema_version": "equity_research_opportunity_report_v1",
               "opportunities": [shared, {"after": [[], {}]}],
               "priority_queue": [shared], "reassessment_queue": [],
               "diagnostics": {"z": None, "a": {"b": [1, 2]}},
               "generated_at": "2026-11-23T01:00:00-05:00"}
        # Fallback inputs retain the old C encoder's full behavior.
        yield {"schema_version": "other_schema", "events": [shared], "a": []}
        yield [shared, [], {}]
        yield {"schema_version": "other_schema", "nonstring": {1: "one", 2: "two"}}

    def test_exact_pretty_bytes_and_canonical_hash_for_native_and_fallback_values(self):
        for index, payload in enumerate(self.specimens()):
            with self.subTest(specimen=index):
                expected_canonical = canonical_bytes(payload)
                expected_pretty = pretty_bytes(payload)
                self.assertEqual("".join(document._document_chunks(payload)).encode("utf-8"),
                                 expected_canonical)
                self.assertEqual("".join(document._document_chunks(payload, pretty=True)).encode("utf-8")
                                 + b"\n", expected_pretty)
                self.assertEqual(document.document_sha256(payload),
                                 hashlib.sha256(expected_canonical).hexdigest())
                target = self.root / str(index) / "current.json"
                document.atomic_write_document(target, payload)
                self.assertEqual(target.read_bytes(), expected_pretty)
                self.assertTrue(target.read_bytes().endswith(b"\n"))

    def test_shuffled_envelope_keys_and_empty_containers_keep_exact_indentation(self):
        payload = {"z": [], "schema_version": "equity_research_opportunity_store_v1",
                   "events": [[], {}, [{"x": [[], {}]}], "tail"], "a": {}}
        reordered = dict(reversed(list(payload.items())))
        for value in (payload, reordered):
            self.assertEqual("".join(document._document_chunks(value, pretty=True)),
                             json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            self.assertEqual(document.document_sha256(value),
                             hashlib.sha256(canonical_bytes(payload)).hexdigest())

    def test_known_envelope_never_sends_whole_document_or_events_array_to_dumps(self):
        events = [{"sequence": i, "payload": "nested " + "x" * 80} for i in range(17)]
        payload = self.store(events)
        expected_hash = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        expected_pretty = pretty_bytes(payload)
        original = json.dumps
        encoded_inputs = []

        def bounded_encode(value, *args, **kwargs):
            self.assertIsNot(value, payload, "whole known document encoded at once")
            self.assertIsNot(value, events, "whole known event array encoded at once")
            encoded_inputs.append(value)
            return original(value, *args, **kwargs)

        target = self.root / "report.json"
        with patch.object(document.json, "dumps", side_effect=bounded_encode):
            self.assertEqual(document.document_sha256(payload), expected_hash)
            document.atomic_write_document(target, payload)
        self.assertEqual(target.read_bytes(), expected_pretty)
        self.assertTrue(any(value is events[0] for value in encoded_inputs),
                        "test must observe the C-backed subtree encoder")

    def test_mid_encode_fsync_and_replace_failures_keep_old_current_and_remove_temporary(self):
        payload = self.store([{"revision": 2}])
        for fault in ("encode", "fsync", "replace"):
            with self.subTest(fault=fault):
                target = self.root / fault / "current.json"
                target.parent.mkdir()
                old = b'{"original":"retained"}\n'
                target.write_bytes(old)

                def failed_chunks(*args, **kwargs):
                    yield '{"partial":'
                    raise ValueError("synthetic mid-encode failure")

                if fault == "encode":
                    context = patch.object(document, "_document_chunks", side_effect=failed_chunks)
                    expected = ValueError
                elif fault == "fsync":
                    context = patch.object(document.os, "fsync", side_effect=OSError("synthetic fsync failure"))
                    expected = OSError
                else:
                    context = patch.object(document.os, "replace", side_effect=OSError("synthetic replace failure"))
                    expected = OSError
                with context:
                    with self.assertRaises(expected):
                        document.atomic_write_document(target, payload)
                self.assertEqual(target.read_bytes(), old)
                self.assertEqual(set(target.parent.iterdir()), {target})

    def test_json_and_unicode_failures_never_publish_partial_current(self):
        cyclic = self.store([])
        cyclic["events"].append(cyclic)
        cases = [("cycle", cyclic, ValueError),
                 ("unsupported", self.store([{1, 2}]), TypeError),
                 ("surrogate", self.store(["\ud800"]), UnicodeEncodeError),
                 ("mixed_keys", {"schema_version": "other_schema", 1: "mixed"}, TypeError)]
        for name, payload, expected in cases:
            with self.subTest(fault=name):
                target = self.root / name / "current.json"
                target.parent.mkdir()
                old = b"unchanged predecessor\n"
                target.write_bytes(old)
                with self.assertRaises(expected):
                    document.document_sha256(payload)
                with self.assertRaises(expected):
                    document.atomic_write_document(target, payload)
                self.assertEqual(target.read_bytes(), old)
                self.assertEqual(set(target.parent.iterdir()), {target})

    def test_document_encoding_does_not_mutate_legal_shared_input(self):
        shared = {"nested": {"items": [1, "value"]}}
        payload = self.store([shared, shared])
        before = copy.deepcopy(payload)
        before_bytes = pretty_bytes(payload)
        document.document_sha256(payload)
        document.atomic_write_document(self.root / "current.json", payload)
        self.assertEqual(payload, before)
        self.assertIs(payload["events"][0], payload["events"][1])
        self.assertEqual(pretty_bytes(payload), before_bytes)

    def test_atomic_document_keeps_destination_safety_checks_outside_portfolio_scope(self):
        source = self.root / "source.json"
        source.write_bytes(b"untouched source\n")
        linked = self.root / "linked.json"
        linked.symlink_to(source)
        directory = self.root / "directory.json"
        directory.mkdir()
        for target in (linked, directory):
            with self.subTest(target=target.name):
                before = set(self.root.iterdir())
                with self.assertRaisesRegex(ValueError, "non-regular"):
                    document.atomic_write_document(target, self.store([]))
                self.assertEqual(set(self.root.iterdir()), before)
        self.assertTrue(linked.is_symlink())
        self.assertTrue(directory.is_dir())
        self.assertEqual(source.read_bytes(), b"untouched source\n")


if __name__ == "__main__":
    unittest.main()
