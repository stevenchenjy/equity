from __future__ import annotations
import copy
import json
import unittest
import tempfile
from datetime import datetime, date
from pathlib import Path
from _support import SCRIPT_DIR
from test_momentum_experiment import fixture, ET
import momentum_experiment as m
from tactical_review import _last_sessions
from archived_momentum import evaluate_archived


class ArchivedMomentumTests(unittest.TestCase):
    def inputs(self, archive_index=-1):
        root = SCRIPT_DIR.parents[1]
        config = json.loads((root / '01_policies/momentum_implementation_archives.json').read_text())
        archive = config['archives'][archive_index]
        values = fixture()
        values['policy']['version'] = archive['experiment_version']
        values['inputs'].update(implementation_files=archive['implementation_files'],
            implementation_sha256=m.canonical_sha256(archive['implementation_files']))
        row = m.observe(**values)[0][0]
        row['previous_hash'] = ''
        row['record_hash'] = m.canonical_sha256(row)
        forward = m.sessions_after(date(2026, 9, 23), 5)
        existing = {b['session_date']: b for b in row['bars_at_observation']}
        bars = [existing.get(day, {'session_date': day, 'open': 104, 'high': 106,
            'low': 102, 'close': 105, 'volume': 100}) for day in _last_sessions(date(2026, 9, 30), 20)]
        current = datetime(2026, 10, 1, 13, 30, tzinfo=ET)
        history = copy.deepcopy(values['history'])
        history.update(market_session='2026-09-30', generated_at=current.isoformat())
        history['tickers']['TEST']['bars'] = bars
        market = [{**values['market'][0], 'last_price': 105, 'market_session_date': '2026-09-30',
                   'data_timestamp': current.isoformat()}]
        return dict(root=root, records=[row], history=history, market=market, current=current,
                    inputs={'market_sha256': 'a' * 64, 'implementation_sha256': 'b' * 64})

    def test_old_observation_matures_using_its_verified_frozen_code(self):
        args = self.inputs()
        before = copy.deepcopy(args['records'])
        outcomes = evaluate_archived(**args)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]['status'], 'matured_price_path_study')
        self.assertEqual(outcomes[0]['evaluation_inputs']['implementation_sha256'],
                         args['records'][0]['inputs']['implementation_sha256'])
        self.assertEqual(args['records'], before)
        self.assertFalse(outcomes[0]['models']['breakout_only']['actual_fill'])

    def test_missing_forward_data_stays_pending(self):
        args = self.inputs()
        args['market'][0]['data_quality_label'] = 'missing'
        self.assertEqual(evaluate_archived(**args), [])

    def test_mismatched_frozen_source_binding_fails_closed(self):
        args = self.inputs()
        args['records'][0]['inputs']['implementation_files']['tactical_review.py'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'archive_implementation_mismatch'):
            evaluate_archived(**args)

    def test_duplicate_archive_registration_fails_before_evaluation(self):
        args = self.inputs()
        config = json.loads((args['root'] / '01_policies/momentum_implementation_archives.json').read_text())
        config['archives'].append(copy.deepcopy(config['archives'][0]))
        with tempfile.TemporaryDirectory() as directory:
            args['root'] = Path(directory)
            target = args['root'] / '01_policies/momentum_implementation_archives.json'
            target.parent.mkdir()
            target.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'archive_config_duplicate'):
                evaluate_archived(**args)

    def test_legacy_four_file_and_current_five_file_archives_both_mature(self):
        for index in (0, 1, 2):
            with self.subTest(archive_index=index):
                args = self.inputs(index)
                self.assertEqual(len(evaluate_archived(**args)), 1)

    def test_new_rest_session_waits_for_frozen_publication_rule(self):
        args = self.inputs()
        args['current'] = datetime(2026, 10, 1, 9, 0, tzinfo=ET)
        args['history']['generated_at'] = args['current'].isoformat()
        args['market'][0]['data_timestamp'] = args['current'].isoformat()
        before = copy.deepcopy(args)
        waiting = []
        self.assertEqual(evaluate_archived(**args, deferred=waiting), [])
        self.assertEqual(args, before)
        self.assertEqual(waiting, [{
            'experiment_version': 'eod-breakout-v3-20260928',
            'observation_count': 1,
            'reason': 'historical_publication_rule_not_yet_satisfied',
            'required_market_session': '2026-09-29',
            'observed_market_session': '2026-09-30',
        }])
        # Actual later time satisfies the old clock; no history rewrite needed.
        args['current'] = datetime(2026, 10, 1, 11, 15, tzinfo=ET)
        self.assertEqual(len(evaluate_archived(**args)), 1)

    def test_older_stale_market_session_is_not_silently_deferred(self):
        args = self.inputs()
        args['current'] = datetime(2026, 10, 2, 13, 30, tzinfo=ET)
        with self.assertRaisesRegex(ValueError, 'archive_evaluation_failed'):
            evaluate_archived(**args, deferred=[])

    def test_future_observation_receipt_is_not_silently_deferred(self):
        args = self.inputs()
        args['current'] = datetime(2026, 10, 1, 9, 0, tzinfo=ET)
        with self.assertRaisesRegex(ValueError, 'archive_evaluation_failed'):
            evaluate_archived(**args, deferred=[])

    def test_five_file_archive_rejects_changed_archive_runner_binding(self):
        args = self.inputs()
        args['records'][0]['inputs']['implementation_files']['archived_momentum.py'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'archive_implementation_mismatch'):
            evaluate_archived(**args)

    def test_active_version_migration_keeps_every_strategy_parameter(self):
        import subprocess
        root = SCRIPT_DIR.parents[1]
        old = json.loads(subprocess.check_output(['git', 'show',
            'e199070b5dff899bc829402059417a96491d19cd:01_policies/momentum_experiment.json'], cwd=root))
        active = json.loads((root / '01_policies/momentum_experiment.json').read_text())
        self.assertEqual(old.pop('version'), 'eod-breakout-v3-20260928')
        self.assertEqual(active.pop('version'), 'eod-breakout-v4-20260928')
        self.assertEqual(active, old)
