"""Retired observations must retain forward evidence without universe drift."""
import copy
from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from _support import SCRIPT_DIR
from test_momentum_experiment import fixture, write_fixture, ET
from tactical_review import _last_sessions
import momentum_experiment as experiment
import momentum_price_coverage as coverage


class OutcomeCoverageTests(unittest.TestCase):
    def matured_fixture(self, root):
        values = fixture(); write_fixture(root, values)
        first = experiment.run(root, values['current'])
        observation = first['current_observations'][0]
        original = (root / experiment.OUTPUT / 'ledger.jsonl').read_bytes()
        current = datetime(2026, 10, 1, 13, 30, tzinfo=ET)
        forward = [observation['earliest_modeled_entry_session'],
                   *experiment.sessions_after(date(2026, 9, 24), 4)]
        existing = {b['session_date']: b for b in observation['bars_at_observation']}
        bars = [existing.get(day, {'session_date': day, 'open': 99, 'high': 101,
                   'low': 98, 'close': 100, 'volume': 100}) for day in _last_sessions(date(2026, 9, 30), 20)]
        for bar in bars:
            if bar['session_date'] in forward:
                bar.update(open=104, high=106, low=102, close=105, volume=100)
        market = dict(values['market'][0], last_price=105, market_session_date='2026-09-30',
                      data_timestamp=current.isoformat())
        values['current'] = current
        values['market'] = [dict(market, ticker='NEXT')]
        values['history'].update(market_session='2026-09-30', generated_at=current.isoformat(),
                                 tickers={'NEXT': {'bars': copy.deepcopy(bars), 'source_url': 'https://example.test/NEXT'}})
        values['decision'].update(generated_at=current.isoformat(), market_gate={'expected_market_session': '2026-09-30'})
        write_fixture(root, values)
        return current, market, {'bars': bars, 'source_url': 'https://example.test/TEST'}, original, observation

    def test_retired_sample_can_complete_with_no_new_retired_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, market, bars, before, observation = self.matured_fixture(root)
            fetch = Mock(return_value=(market, bars, 'none'))
            receipt = coverage.collect_outcome_prices(root, ['NEXT'], current, fetch)
            fetch.assert_called_once_with('TEST')
            self.assertEqual(receipt['requested_tickers'], ['TEST'])
            canonical_before = (root / experiment.SNAPSHOT).read_bytes()
            report = experiment.run(root, current)
            self.assertEqual((root / experiment.SNAPSHOT).read_bytes(), canonical_before)
            records = [json.loads(line) for line in (root / experiment.OUTPUT / 'ledger.jsonl').read_bytes().splitlines()]
            self.assertTrue((root / experiment.OUTPUT / 'ledger.jsonl').read_bytes().startswith(before))
            self.assertEqual(len([r for r in records if r['kind'] == 'observation' and r['ticker'] == 'TEST']), 1)
            outcome = next(r for r in records if r['kind'] == 'outcome')
            expected = experiment.evaluate(observation, {'TEST': bars['bars']}, current)
            self.assertEqual(outcome['models'], expected['models'])
            self.assertEqual(outcome['forward_bars'], expected['forward_bars'])
            self.assertEqual(outcome['evaluation_inputs']['scope'], receipt['scope'])
            self.assertEqual(report['outcome_price_coverage']['new_outcomes'], 1)
            self.assertEqual(report['summary']['outcomes'], 1)
            self.assertEqual({r['ticker'] for r in report['current_observations']}, {'NEXT'})
            ledger = (root / experiment.OUTPUT / 'ledger.jsonl').read_bytes()
            experiment.run(root, current.replace(hour=14))
            self.assertEqual((root / experiment.OUTPUT / 'ledger.jsonl').read_bytes(), ledger)

    def test_unavailable_retired_series_remains_missing_and_preserves_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, _, _, before, _ = self.matured_fixture(root)
            receipt = coverage.collect_outcome_prices(root, ['NEXT'], current,
                Mock(return_value=(None, None, 'massive_request_failed')))
            report = experiment.run(root, current)
            self.assertEqual(receipt['missing'], {'TEST': 'massive_request_failed'})
            self.assertEqual(report['outcome_price_coverage']['missing'], receipt['missing'])
            self.assertEqual(report['summary']['outcomes'], 0)
            self.assertTrue((root / experiment.OUTPUT / 'ledger.jsonl').read_bytes().startswith(before))

    def test_current_coherent_supplement_is_reused_without_a_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, market, bars, _, _ = self.matured_fixture(root)
            coverage.collect_outcome_prices(root, ['NEXT'], current, Mock(return_value=(market, bars, 'none')))
            fetch = Mock(side_effect=AssertionError('unchanged close refetched'))
            coverage.collect_outcome_prices(root, ['NEXT'], current.replace(hour=14), fetch)
            fetch.assert_not_called()

    def test_tampered_supplement_cannot_append_even_a_new_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, market, bars, before, _ = self.matured_fixture(root)
            receipt = coverage.collect_outcome_prices(root, ['NEXT'], current, Mock(return_value=(market, bars, 'none')))
            receipt['market'][0]['last_price'] = 1000
            (root / coverage.PATH).write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'experiment_outcome_coverage_invalid'):
                experiment.run(root, current)
            self.assertEqual((root / experiment.OUTPUT / 'ledger.jsonl').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
