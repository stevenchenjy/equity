from __future__ import annotations

import copy
from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ET, atomic_write_json, canonical_sha256, sha256_file
import opportunity_contract as contract
from opportunity_triggers import packet


class OpportunityValidationCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'retained-source.bin'
        self.source.write_bytes(b'original retained bytes')
        self.current = datetime(2026, 11, 4, 12, tzinfo=ET)
        self.receipt = {'path': self.source.name, 'sha256': sha256_file(self.source),
                        'available_at': self.current.isoformat()}
        self.store = contract.empty_store()
        for revision in range(3):
            moment = self.current + timedelta(seconds=revision)
            observation = packet(ticker='SYN', family='business', trigger='synthetic',
                evidence={'revision': revision}, sources=[copy.deepcopy(self.receipt)],
                current=moment, produced_by={'implementation_sha256': 'a'*64,
                                            'policy_sha256': 'b'*64})
            if revision == 0:
                identity = canonical_sha256({'first_observation_id': observation['observation_id'],
                                             'ticker': observation['ticker']})
                event = {'kind': 'detected', 'to_state': 'queued',
                         'owner': 'research_orchestration', 'reason_code': 'test', 'blockers': []}
            else:
                event = {'kind': 'observed'}
            contract.append_event(self.store, {**event, 'opportunity_id': identity,
                'observation': observation, 'recorded_at': moment.isoformat()})
        self.current += timedelta(seconds=3)

    def test_repeated_source_is_read_once_per_replay_without_changing_result(self):
        original_read = Path.read_bytes
        reads = []
        def read(path):
            if path == self.source:
                reads.append(path)
            return original_read(path)
        with patch.object(Path, 'read_bytes', read):
            result = contract.replay(self.store, root=self.root, current=self.current)
            self.assertEqual(len(reads), 1)
            self.assertEqual(result, contract.replay(self.store))
            self.assertEqual(result, contract.replay(self.store, root=self.root, current=self.current))
            self.assertEqual(len(reads), 2)

    def test_same_size_rewrite_between_replays_is_not_cached(self):
        contract.replay(self.store, root=self.root, current=self.current)
        before = self.source.stat()
        self.source.write_bytes(b'replaced retained bytes')
        os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.source.stat().st_size, before.st_size)
        with self.assertRaisesRegex(ValueError, 'research_source_changed'):
            contract.replay(self.store, root=self.root, current=self.current)

    def test_change_after_last_receipt_is_rejected_by_final_fence(self):
        validate = contract.validate_observation
        def change_after_validation(observation, **kwargs):
            result = validate(observation, **kwargs)
            if observation['evidence']['revision'] == 2:
                self.source.write_bytes(b'changed after last validation')
            return result
        with patch.object(contract, 'validate_observation', change_after_validation):
            with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
                contract.replay(self.store, root=self.root, current=self.current)

    def test_every_receipt_clock_and_expected_hash_still_validate(self):
        store = copy.deepcopy(self.store)
        event = store['events'][-1]
        event['observation']['sources'][0]['available_at'] = (self.current + timedelta(hours=1)).isoformat()
        event['record_hash'] = canonical_sha256({k: v for k, v in event.items() if k != 'record_hash'})
        with self.assertRaisesRegex(ValueError, 'research_source_from_future'):
            contract.replay(store, root=self.root, current=self.current)
        event['observation']['sources'][0]['available_at'] = self.receipt['available_at']
        event['observation']['sources'][0]['sha256'] = 'f'*64
        event['record_hash'] = canonical_sha256({k: v for k, v in event.items() if k != 'record_hash'})
        with self.assertRaisesRegex(ValueError, 'research_source_changed'):
            contract.replay(store, root=self.root, current=self.current)

    def test_journal_hash_is_never_replaced_by_source_cache(self):
        contract.replay(self.store, root=self.root, current=self.current)
        self.store['events'][-1]['recorded_at'] = self.current.isoformat()
        with self.assertRaisesRegex(ValueError, 'research_journal_hash_invalid'):
            contract.replay(self.store, root=self.root, current=self.current)

    def test_validation_only_does_not_copy_output_but_rejects_invalid_transitions(self):
        identity = self.store['events'][0]['opportunity_id']
        contract.append_event(self.store, {'kind': 'transition', 'opportunity_id': identity,
            'from_state': 'queued', 'to_state': 'researching', 'owner': 'objective_research',
            'reason_code': 'test', 'blockers': [], 'sources': [self.receipt],
            'recorded_at': self.current.isoformat()})
        with patch.object(contract.copy, 'deepcopy', side_effect=AssertionError('output copied')):
            self.assertIsNone(contract.validate_journal(self.store, root=self.root, current=self.current))
        # Mutating a normal replay result remains isolated from the journal.
        result = contract.replay(self.store, root=self.root, current=self.current)
        result[identity]['observations'][0]['evidence']['revision'] = 'changed'
        self.assertEqual(self.store['events'][0]['observation']['evidence']['revision'], 0)
        self.store['events'][-1]['owner'] = 'analyst_assessment'
        event = self.store['events'][-1]
        event['record_hash'] = canonical_sha256({k: v for k, v in event.items() if k != 'record_hash'})
        for validate in (contract.replay, contract.validate_journal):
            with self.assertRaisesRegex(ValueError, 'research_transition_owner_or_state_invalid'):
                validate(self.store, root=self.root, current=self.current)

    def test_validation_only_preserves_source_clock_hash_and_final_mutation_checks(self):
        self.source.write_bytes(b'wrong retained bytes')
        with self.assertRaisesRegex(ValueError, 'research_source_changed'):
            contract.validate_journal(self.store, root=self.root, current=self.current)
        self.source.write_bytes(b'original retained bytes')
        event = self.store['events'][-1]
        event['observation']['sources'][0]['available_at'] = (self.current + timedelta(hours=1)).isoformat()
        event['record_hash'] = canonical_sha256({k: v for k, v in event.items() if k != 'record_hash'})
        with self.assertRaisesRegex(ValueError, 'research_source_from_future'):
            contract.validate_journal(self.store, root=self.root, current=self.current)
        event['observation']['sources'][0]['available_at'] = self.receipt['available_at']
        event['record_hash'] = canonical_sha256({k: v for k, v in event.items() if k != 'record_hash'})
        validate = contract.validate_observation
        def change_after_validation(observation, **kwargs):
            result = validate(observation, **kwargs)
            if observation['evidence']['revision'] == 2:
                self.source.write_bytes(b'changed after last validation')
            return result
        with patch.object(contract, 'validate_observation', change_after_validation):
            with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
                contract.validate_journal(self.store, root=self.root, current=self.current)

    def test_validation_only_preserves_required_detection_fields(self):
        # Rechain after omission so the structural contract, not an unrelated
        # record-digest failure, exercises both paths.
        del self.store['events'][0]['reason_code']
        previous = ''
        for event in self.store['events']:
            event['previous_hash'] = previous
            event['record_hash'] = canonical_sha256({k: v for k, v in event.items() if k != 'record_hash'})
            previous = event['record_hash']
        for validate in (contract.replay, contract.validate_journal):
            with self.assertRaisesRegex(KeyError, 'reason_code'):
                validate(self.store, root=self.root, current=self.current)

    def test_validation_only_requires_actual_source_root_and_aware_clock(self):
        with self.assertRaisesRegex(ValueError, 'research_validation_source_root_missing'):
            contract.validate_journal(self.store, root=None, current=self.current)
        with self.assertRaisesRegex(ValueError, 'research_validation_clock_missing'):
            contract.validate_journal(self.store, root=self.root, current=None)
        with self.assertRaisesRegex(ValueError, 'research_validation_clock_missing'):
            contract.validate_journal(self.store, root=self.root, current=self.current.replace(tzinfo=None))

    def test_real_report_reader_validates_without_materializing_discarded_replay(self):
        from research_opportunities import read_report
        atomic_write_json(self.root / contract.STORE_REL, self.store)
        authority = {'mode': 'verified_snapshot', 'local_planning_enabled': False}
        report = {'schema_version': 'equity_research_opportunity_report_v1',
            'store_sha256': sha256_file(self.root / contract.STORE_REL),
            'generated_at': self.current.isoformat(), 'account_authority': authority,
            'opportunities': [], **contract.AUTHORITY}
        report['report_hash'] = canonical_sha256(report)
        atomic_write_json(self.root / contract.REPORT_REL, report)
        before = canonical_sha256(self.store)
        with patch('research_opportunities.load_authority', return_value=authority):
            with patch.object(contract.copy, 'deepcopy', side_effect=AssertionError('discarded view copied')):
                self.assertEqual(read_report(self.root, current=self.current), report)
        self.assertEqual(canonical_sha256(self.store), before)
        self.source.write_bytes(b'changed bytes')
        with patch('research_opportunities.load_authority', return_value=authority):
            with self.assertRaisesRegex(ValueError, 'research_source_changed'):
                read_report(self.root, current=self.current)


if __name__ == '__main__':
    unittest.main()
