"""Chart markers follow audited effective dates without rewriting saved facts."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class ChartExecutionCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        market = self.root / server.MARKET
        market.parent.mkdir(parents=True)
        market.write_text('ticker,last_price,data_quality_label,market_session_date\nABC,100,ok,2026-10-28\n')
        history = market.parent / 'tactical_price_history.local.json'
        history.write_text(json.dumps({'data_source': 'synthetic_test_only',
            'tickers': {'ABC': {'source_url': 'https://example.invalid/ABC'}}}))
        self.bars = patch.object(server, '_validated_bars', return_value=([], []))
        self.bars.start()
        self.addCleanup(self.bars.stop)

    def record(self, identifier, date, price):
        return {'id': identifier, 'stage': 'applied', 'feedback': {
            'ticker': 'ABC', 'status': 'filled', 'side': 'buy', 'shares': '1',
            'date': date, 'time': ''}, 'changes': {'fill_price': price}}

    def test_corrected_marker_uses_effective_date_and_retains_original_audit(self):
        original = self.record('synthetic-original', '2026-10-02', 20)
        correction = {'original_date': '2026-10-02', 'corrected_date': '2026-10-20',
            'record_id': 'synthetic-reconciliation', 'revision': 3,
            'recorded_at': '2026-10-29T10:00:00-04:00', 'reason': 'Synthetic date correction',
            'owner_source': {'path': 'synthetic-owner-facts.json', 'sha256': 'a' * 64}}
        original.update(effective_date='2026-10-20', execution_date_correction=correction)
        additional = self.record('synthetic-additional', '2026-10-02', 30)
        fills = {row['id']: row for row in server.chart(self.root, 'ABC', [original, additional])['fills']}
        self.assertEqual(fills['synthetic-original']['date'], '2026-10-20')
        self.assertEqual(fills['synthetic-original']['original_date'], '2026-10-02')
        self.assertEqual(fills['synthetic-original']['execution_date_correction'], correction)
        self.assertEqual(fills['synthetic-additional']['date'], '2026-10-02')
        self.assertEqual(original['feedback']['date'], '2026-10-02')

    def test_uncorrected_marker_keeps_its_original_date_and_economics(self):
        record = self.record('synthetic-uncorrected', '2026-10-09', 15)
        fill = server.chart(self.root, 'ABC', [record])['fills'][0]
        self.assertEqual((fill['date'], fill['price'], fill['shares']), ('2026-10-09', 15, '1'))


if __name__ == '__main__':
    unittest.main()
