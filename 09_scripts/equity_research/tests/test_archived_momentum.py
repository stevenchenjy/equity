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
    def inputs(self):
        root = SCRIPT_DIR.parents[1]
        config = json.loads((root / '01_policies/momentum_implementation_archives.json').read_text())
        archive = config['archives'][-1]
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
