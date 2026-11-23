"""Scratch-only history streaming equivalence and publication failures."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import opportunity_contract as contract


class StreamingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.payload = contract.empty_store()
        self.payload['events'] = [{'value': index, 'text': 'alpha α\u2028beta\nline',
                                  'floats': [-0.0, 1e-30, 1e30]} for index in range(300)]
        self.raw = (json.dumps(self.payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()

    def test_exact_bytes_names_deterministic_new_gzip_and_plain_precedence(self):
        expected = hashlib.sha256(json.dumps(self.payload, ensure_ascii=False, sort_keys=True,
                                             separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(contract.document_sha256(self.payload), expected)
        first = contract.retain_history_json(self.root / (expected + '.json'), self.payload)
        second = contract.retain_history_json(self.root / 'other.json', self.payload)
        self.assertEqual(first.name, expected + '.json.gz')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(gzip.decompress(first.read_bytes()), self.raw)
        self.assertEqual(contract.retain_history_json(self.root / (expected + '.json'), self.payload), first)
        plain = self.root / 'plain.json'
        plain.write_bytes(self.raw)
        plain.with_suffix('.json.gz').write_bytes(b'untouched later corrupt candidate')
        self.assertEqual(contract.retain_history_json(plain, self.payload), plain)
        self.assertEqual(plain.with_suffix('.json.gz').read_bytes(), b'untouched later corrupt candidate')

    def test_existing_plain_and_gzip_are_streamed_without_read_bytes(self):
        path = self.root / 'streamed.json'
        compressed = contract.retain_history_json(path, self.payload)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole archive read')):
            self.assertEqual(contract.retain_history_json(path, self.payload), compressed)
        plain = self.root / 'plain.json'
        plain.write_bytes(self.raw)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole plain read')):
            self.assertEqual(contract.retain_history_json(plain, self.payload), plain)

    def test_checksum_truncation_trailing_and_multimember_archives(self):
        original = gzip.compress(self.raw, mtime=0)
        bad_crc = bytearray(original)
        bad_crc[-8] ^= 1
        cases = {'header': b'not gzip', 'truncated': original[:-4],
                 'checksum': bytes(bad_crc), 'trailing': original + b'bad trailing member'}
        for name, raw in cases.items():
            with self.subTest(name=name):
                path = self.root / (name + '.json')
                archive = path.with_suffix('.json.gz')
                archive.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, 'archive_corrupt'):
                    contract.retain_history_json(path, self.payload)
                self.assertEqual(archive.read_bytes(), raw)
        path = self.root / 'members.json'
        split = len(self.raw) // 2
        members = gzip.compress(self.raw[:split], mtime=0) + gzip.compress(self.raw[split:], mtime=0)
        archive = path.with_suffix('.json.gz')
        archive.write_bytes(members)
        self.assertEqual(contract.retain_history_json(path, self.payload), archive)
        self.assertEqual(archive.read_bytes(), members)

    def test_competing_link_winner_is_verified_and_never_replaced(self):
        for same in (True, False):
            with self.subTest(same=same):
                path = self.root / (str(same) + '.json')
                compressed = path.with_suffix('.json.gz')
                winner = gzip.compress(self.raw if same else b'different immutable bytes', mtime=0)
                def compete(source, target):
                    Path(target).write_bytes(winner)
                    raise FileExistsError('fixture winner')
                with patch.object(contract.os, 'link', side_effect=compete):
                    if same:
                        self.assertEqual(contract.retain_history_json(path, self.payload), compressed)
                    else:
                        with self.assertRaisesRegex(ValueError, 'archive_conflict'):
                            contract.retain_history_json(path, self.payload)
                self.assertEqual(compressed.read_bytes(), winner)
                self.assertFalse(list(self.root.glob('.history-*')))

    def test_mid_encoding_sync_and_link_failures_do_not_publish_or_leak(self):
        for fault in ('encode', 'fsync', 'link'):
            with self.subTest(fault=fault):
                path = self.root / (fault + '.json')
                def broken_parts(*args, **kwargs):
                    yield b'{"incomplete":'
                    raise ValueError('fixture encoding failure')
                target = {'encode': '_document_bytes', 'fsync': 'os.fsync', 'link': 'os.link'}[fault]
                replacement = broken_parts if fault == 'encode' else OSError('fixture durability failure')
                with patch('opportunity_contract.' + target, side_effect=replacement):
                    with self.assertRaises((ValueError, OSError)):
                        contract.retain_history_json(path, self.payload)
                self.assertFalse(path.exists())
                self.assertFalse(path.with_suffix('.json.gz').exists())
                self.assertFalse(list(self.root.glob('.history-*')))

    def test_conflicting_existing_history_preserves_original_and_input(self):
        before = copy.deepcopy(self.payload)
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                path = self.root / ('conflict-' + str(compressed) + '.json')
                existing = path.with_suffix('.json.gz') if compressed else path
                raw = gzip.compress(b'different', mtime=0) if compressed else b'different'
                existing.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, 'archive_conflict'):
                    contract.retain_history_json(path, self.payload)
                self.assertEqual(existing.read_bytes(), raw)
        self.assertEqual(self.payload, before)


if __name__ == '__main__':
    unittest.main()
