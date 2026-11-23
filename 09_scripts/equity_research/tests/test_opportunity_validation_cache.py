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

    def test_transition_batch_retains_no_old_observation_copies_and_matches_serial_events(self):
        identity = self.store['events'][0]['opportunity_id']
        changes = [{'identity': identity, 'target': target, 'owner': 'objective_research',
                    'reason': 'fixture_' + target, 'sources': [self.receipt], 'blockers': []}
                   for target in ('researching', 'data_blocked', 'researching')]
        expected = copy.deepcopy(self.store)
        for change in changes:
            contract.transition(expected, change['identity'], change['target'],
                owner=change['owner'], reason=change['reason'], sources=change['sources'],
                blockers=change['blockers'], current=self.current)
        before = copy.deepcopy(self.store)
        observations = {id(event['observation']) for event in self.store['events']}
        deepcopy = copy.deepcopy
        copied = []

        def copy_only_new_event(value, *args, **kwargs):
            # Retained packet copies dominate peak projection memory. The new
            # transition event is deliberately still copied for caller isolation.
            self.assertNotIn(id(value), observations, 'unused history materialized')
            copied.append(value)
            return deepcopy(value, *args, **kwargs)

        replay = contract._replay
        with patch.object(contract.copy, 'deepcopy', side_effect=copy_only_new_event), \
                patch.object(contract, '_replay', wraps=replay) as boundaries:
            contract.transition_batch(self.store, changes, root=self.root, current=self.current)
        self.assertEqual([call.kwargs.get('materialize', True) for call in boundaries.call_args_list],
                         [False, False])
        self.assertEqual(self.store, expected)
        self.assertEqual(canonical_sha256(self.store), canonical_sha256(expected))
        self.assertEqual(self.store['events'][:len(before['events'])], before['events'])
        self.assertTrue(copied)
        changes[0]['sources'][0]['sha256'] = 'f' * 64
        self.assertEqual(self.store['events'][-3]['sources'][0]['sha256'],
                         before['events'][0]['observation']['sources'][0]['sha256'])

    def test_transition_batch_preserves_each_original_task_clock_and_default_timestamp(self):
        identity = self.store['events'][0]['opportunity_id']
        changes = [{'identity': identity, 'target': target, 'owner': 'objective_research',
                    'reason': 'fixture_' + target, 'sources': [self.receipt], 'blockers': [],
                    'recorded_at': (self.current + timedelta(seconds=index)).isoformat()}
                   for index, target in enumerate(('researching', 'data_blocked', 'researching'))]
        final = self.current + timedelta(seconds=2)
        del changes[-1]['recorded_at']  # Legacy callers still use the batch clock.
        expected = copy.deepcopy(self.store)
        for change in changes:
            contract.transition(expected, change['identity'], change['target'],
                owner=change['owner'], reason=change['reason'], sources=change['sources'],
                blockers=change['blockers'],
                current=datetime.fromisoformat(change.get('recorded_at', final.isoformat())))
        actual = copy.deepcopy(self.store)
        contract.transition_batch(actual, changes, root=self.root, current=final)
        self.assertEqual(actual, expected)
        self.assertEqual(canonical_sha256(actual), canonical_sha256(expected))
        self.assertEqual([event['recorded_at'] for event in actual['events'][-3:]],
                         [(self.current + timedelta(seconds=index)).isoformat() for index in range(3)])

    def test_transition_batch_rejects_per_event_clock_and_receipt_faults_atomically(self):
        identity = self.store['events'][0]['opportunity_id']
        final = self.current + timedelta(seconds=2)
        for fault in ('regression', 'future', 'naive', 'future_source', 'unknown_key'):
            with self.subTest(fault=fault):
                changes = [{'identity': identity, 'target': target, 'owner': 'objective_research',
                            'reason': 'fixture_' + target, 'sources': [copy.deepcopy(self.receipt)],
                            'blockers': [], 'recorded_at': (self.current + timedelta(seconds=index)).isoformat()}
                           for index, target in enumerate(('researching', 'data_blocked', 'researching'))]
                if fault == 'regression':
                    changes[-1]['recorded_at'] = self.current.isoformat()
                elif fault == 'future':
                    changes[-1]['recorded_at'] = (final + timedelta(seconds=1)).isoformat()
                elif fault == 'naive':
                    changes[-1]['recorded_at'] = final.replace(tzinfo=None).isoformat()
                elif fault == 'future_source':
                    changes[0]['sources'][0]['available_at'] = final.isoformat()
                else:
                    changes[-1]['unchecked'] = True
                original = copy.deepcopy(self.store)
                with self.assertRaises(ValueError):
                    contract.transition_batch(self.store, changes, root=self.root, current=final)
                self.assertEqual(self.store, original)

    def test_transition_batch_validation_only_boundary_keeps_final_source_and_required_field_checks(self):
        identity = self.store['events'][0]['opportunity_id']
        change = {'identity': identity, 'target': 'researching', 'owner': 'objective_research',
                  'reason': 'fixture', 'sources': [self.receipt], 'blockers': []}
        before = copy.deepcopy(self.store)
        validate = contract.validate_observation

        def change_after_validation(observation, **kwargs):
            result = validate(observation, **kwargs)
            if observation['evidence']['revision'] == 2:
                self.source.write_bytes(b'changed after boundary validation')
            return result

        with patch.object(contract, 'validate_observation', change_after_validation):
            with self.assertRaisesRegex(ValueError, 'validation_sources_changed_during_transaction'):
                contract.transition_batch(self.store, [change], root=self.root, current=self.current)
        self.assertEqual(self.store, before)
        self.source.write_bytes(b'original retained bytes')
        del self.store['events'][0]['reason_code']
        previous = ''
        for event in self.store['events']:
            event['previous_hash'] = previous
            event['record_hash'] = canonical_sha256({k: v for k, v in event.items() if k != 'record_hash'})
            previous = event['record_hash']
        invalid = copy.deepcopy(self.store)
        with self.assertRaisesRegex(KeyError, 'reason_code'):
            contract.transition_batch(self.store, [change], root=self.root, current=self.current)
        self.assertEqual(self.store, invalid)

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
