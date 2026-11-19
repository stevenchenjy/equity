"""A statement can bind fractional observed holdings without replaying its fills."""
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
from chase_statement import COLUMNS, DISPLAY_DESCRIPTION_LIMIT, SOURCE_DIR, activity_register, snapshot_context


class ChaseStatementTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / SOURCE_DIR).mkdir(parents=True)
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(COLUMNS)
        # Two identical-looking fractional fills are distinct displayed rows.
        for n in (1, 2):
            writer.writerow((n, '2026-09-29', 'Buy', 'XYZ', 'XYZ', '', '', '20', '0.125', '-2.50'))
        writer.writerow((3, '2026-09-28', 'Sell', 'XYZ', 'XYZ', '', '', '19', '-1', '19'))
        self.activity = self.keep(data.getvalue().encode(), '.csv')
        self.chase = {
            'account': 'Chase Self-Directed example', 'currency': 'USD',
            'source': {'positions_and_balances_reported_asof_et': '2026-09-29T20:00:00-04:00',
                       'order_status_reported_asof_et': '2026-09-29T19:57:00-04:00'},
            'order_status': {'working_orders_visible': 0},
            'transactions': {'sha256': self.activity, 'broker_reported_and_captured_row_count': 3,
                             'first_displayed_trade_date_et': '2026-09-28', 'last_displayed_trade_date_et': '2026-09-29',
                             'types': {'Buy': 2, 'Sell': 1}},
            'read_only_reconciliation': {'approved_snapshot': {'sha256': 'a' * 64},
                                         'approved_positions': {'sha256': 'b' * 64},
                                         'approved_observation_at_et': '2026-09-28T21:00:00-04:00'},
            'positions': [{'ticker': 'XYZ', 'quantity_shares': '0.25', 'displayed_unit_price_usd': '22',
                           'market_value_usd': '5.50', 'cost_usd': '5.00'}],
            'balances_usd': {'cash_available_to_trade': '94.50', 'cash_and_sweep_funds': '94.50',
                             'positions_market_value_excluding_cash_and_sweep': '5.50', 'account_value': '100',
                             'cash_available_to_withdraw': '90.00', 'unsettled_trades_proceeds': '4.50'}}
        self.feedback = {'date': '2026-09-29', 'cash': '94.50', 'inventory_complete': True, 'account_observed': True,
                         'no_open_orders': True, 'holdings': [{'ticker': 'XYZ', 'shares': '.25', 'entry_price': '20'}]}

    def keep(self, data, suffix):
        digest = hashlib.sha256(data).hexdigest()
        (self.root / SOURCE_DIR / (digest + suffix)).write_bytes(data)
        return digest

    def run_snapshot(self):
        wrapper = {'schema': 'private_brokerage_observation_v1', 'accounts': {'chase': self.chase}}
        digest = self.keep(json.dumps(wrapper).encode(), '.json')
        now = datetime(2026, 9, 29, 22, tzinfo=ZoneInfo('America/New_York'))
        return snapshot_context(self.root, digest, self.feedback, now, {'last_updated': '2026-09-28T21:00:00-04:00', 'cash_available': '99.50'},
                                [], 'a' * 64, 'b' * 64)

    def test_all_rows_retained_and_only_newer_trade_deltas_bridge_shares(self):
        result = self.run_snapshot()
        self.assertEqual((result['rows'], result['rows_after_starting_ledger_date']), (3, 2))
        self.assertEqual(result['opened_dates'], {'XYZ': '2026-09-29'})
        self.assertEqual(result['account_value'], '100')
        self.assertEqual(result['activity']['sha256'], self.activity)

    def test_partially_overlapping_window_preserves_multiplicity_without_replaying_rows(self):
        first = self.run_snapshot()
        rows = list(csv.DictReader(io.StringIO((self.root / SOURCE_DIR / (self.activity + '.csv')).read_text())))
        later = io.StringIO()
        writer = csv.DictWriter(later, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(dict(rows[0], display_row='1', trade_date_et='2026-09-30'))
        for i, row in enumerate(rows[:2], 2):
            writer.writerow(dict(row, display_row=str(i), settlement_status_displayed='settled'))
        second = {**first, 'activity': {'sha256': self.keep(later.getvalue().encode(), '.csv')}}
        merged = list(csv.DictReader(io.StringIO(activity_register(self.root, [first, second]).decode())))
        self.assertEqual(len(merged), 4)
        repeated = [r for r in merged if r['trade_date_et'] == '2026-09-29']
        self.assertEqual(len({r['activity_id'] for r in repeated}), 2)
        self.assertTrue(all(r['latest_statement_sha256'] == second['activity']['sha256'] for r in repeated))
        self.assertEqual(activity_register(self.root, [first, second]), activity_register(self.root, [first, second, second]))

    def routing_window(self, rows, observed_at):
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(COLUMNS)
        for i, (description, status) in enumerate(rows, 1):
            writer.writerow((i, '2026-09-29', 'Sell', 'XYZ', description, '2026-09-30', status,
                             '19.00', '-1', '18.99'))
        return {'account': 'Chase', 'account_as_of': observed_at,
                'activity': {'sha256': self.keep(data.getvalue().encode(), '.csv')}}

    def clipped_routing_description(self):
        suffix = ' ROME: ROUTE'
        return 'X' * (DISPLAY_DESCRIPTION_LIMIT - len(suffix)) + suffix

    def test_settled_truncated_reference_preserves_id_and_both_source_observations(self):
        original = self.routing_window([('XYZ ROME: ROUTE123 ACTUAL', 'Pending')], '2026-09-29T21:00:00-04:00')
        clipped = self.clipped_routing_description()
        settled = self.routing_window([(clipped, '')], '2026-09-30T21:00:00-04:00')
        end = list(csv.DictReader(io.StringIO(activity_register(self.root, [original, settled]).decode())))
        first = list(csv.DictReader(io.StringIO(activity_register(self.root, [original]).decode())))
        self.assertEqual(len(end), 1)
        self.assertEqual(end[0]['activity_id'], first[0]['activity_id'])
        self.assertEqual(end[0]['first_statement_sha256'], original['activity']['sha256'])
        self.assertEqual(end[0]['latest_statement_sha256'], settled['activity']['sha256'])
        self.assertEqual(end[0]['broker_display_description'], clipped)
        self.assertEqual(activity_register(self.root, [original, settled]),
                         activity_register(self.root, [original, settled, settled]))

    def test_truncated_reference_never_collapses_distinct_same_economic_rows(self):
        full = 'XYZ ROME: ROUTE123 ACTUAL'
        clipped = self.clipped_routing_description()
        first = self.routing_window([(full, 'Pending')], '2026-09-29T21:00:00-04:00')
        both = self.routing_window([(clipped, ''), (full, '')], '2026-09-30T21:00:00-04:00')
        kept = list(csv.DictReader(io.StringIO(activity_register(self.root, [first, both]).decode())))
        self.assertEqual(len(set(row['activity_id'] for row in kept)), 2)

        distinct = self.routing_window([(full, 'Pending'), ('XYZ ROME: ROUTE456 ACTUAL', 'Pending')],
                                       '2026-09-29T21:00:00-04:00')
        ambiguous = self.routing_window([(clipped, '')], '2026-09-30T21:00:00-04:00')
        with self.assertRaisesRegex(ValueError, 'ambiguous truncated Chase transaction reference'):
            activity_register(self.root, [distinct, ambiguous])

    def test_fraction_and_settlement_cannot_be_rounded_or_added_twice(self):
        self.feedback['holdings'][0]['shares'] = '1'
        with self.assertRaisesRegex(ValueError, 'holding quantity differs'):
            self.run_snapshot()
        self.feedback['holdings'][0]['shares'] = '0.25'
        self.feedback['cash'] = '99.00'
        with self.assertRaisesRegex(ValueError, 'cash and securities do not reconcile'):
            self.run_snapshot()

    def test_wrong_baseline_and_tampered_rows_rejected(self):
        self.chase['read_only_reconciliation']['approved_positions']['sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'baseline changed'):
            self.run_snapshot()
        (self.root / SOURCE_DIR / (self.activity + '.csv')).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.run_snapshot()
