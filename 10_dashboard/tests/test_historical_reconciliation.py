"""Explicit historical facts settle once without inventing a broker snapshot."""
import copy
import io
import json
import sys
import unittest
import uuid
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch

import feedback
import record_feedback
import test_feedback as fixtures
from daily_common import canonical_sha256
from feedback import (ACCOUNT, CONFIRMED, HISTORICAL_INPUTS, HISTORICAL_SCHEMA,
    JOURNAL, LEDGER, MANUAL, MARKET, ORDERS, PENDING, POSITIONS, RECONCILED,
    FeedbackError, Store, encoded, read, rows, sha, version)


class HistoricalReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FeedbackTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.store = self.fixture.root, self.fixture.store
        account = json.loads(read(self.root, ACCOUNT))
        account['cash_available'] = 970
        self.fixture.put(ACCOUNT, account)
        self.fixture.put(POSITIONS,
            'ticker,entry_date,entry_price,position_pct,shares_optional,thesis,horizon_class,planned_review_date,invalidation_rule\n'
            'CORE,2026-09-01,100,20,2,Core,long_horizon,2026-10-01,Test\n'
            'OTHR,2026-09-01,50,20,1,Growth,long_horizon,2026-10-01,Test\n')
        self.fixture.put(MARKET,
            'ticker,last_price,data_quality_label,market_session_date\n'
            'CORE,100,ok,2026-09-29\nOTHR,50,ok,2026-09-29\nTST,20,ok,2026-09-29\n')
        authority = dict(schema_version='equity_account_record_authority_v1',
            mode='owner_local_ledger', approved_at='2026-09-01T12:00:00-04:00',
            owner_instruction='Use approved local account records for conditional planning.',
            automatic_execution=False, broker_observation_claimed=False)
        authority['content_sha256'] = canonical_sha256(authority)
        self.fixture.put('05_risk_and_positions/account_record_policy.local.json', authority)
        self.original = self.fixture.submit(self.fixture.total_payload(
            ticker='TST', amount='20', date='2026-09-10'))
        self.fixture.submit(self.fixture.total_payload(
            ticker='OTHR', side='sell', amount='50', date='2026-09-20'))
        self.pending_payload = self.fixture.total_payload(
            ticker='TST', amount='31', date='2026-09-10')
        self.pending = self.fixture.submit(self.pending_payload)
        # Exercise a genuine pending revision, preserving both original requests.
        self.pending_payload = {k:v for k,v in self.pending_payload.items() if k != 'preview_hash'}
        self.pending_payload.update(request_id=str(uuid.uuid4()), record_id=self.pending['id'],
            revision=self.pending['revision'])
        self.pending = self.fixture.submit(self.pending_payload)
        self.assertEqual((self.pending['stage'], self.pending['revision']), ('pending', 2))
        self.assertEqual(json.loads(read(self.root, ACCOUNT))['cash_available'], 1000)
        self.source = '08_reviews/owner_requested.local/test/owner-facts.json'
        self.facts = dict(recorded_at=datetime.now(feedback.ET).isoformat(),
            confirmed_facts={
                'additional_purchase': dict(ticker='TST', side='buy', shares=1,
                    total_amount_usd='30', date='2026-09-10'),
                'existing_purchase_correction': dict(record_id=self.original['id'], ticker='TST',
                    shares=1, total_amount_usd='20', corrected_date='2026-09-15')},
            existing_pending_record_id=self.pending['id'], broker_observation_claimed=False,
            trade_placed=False, email_sent=False)
        self.fixture.put(self.source, self.facts)
        self.payload = self.request()

    def raw_record(self, rid):
        with self.store.db() as con:
            return con.execute('SELECT body FROM records WHERE id=?', (rid,)).fetchone()[0].encode()

    def request(self):
        p = {k:copy.deepcopy(v) for k,v in self.pending_payload.items() if k != 'preview_hash'}
        p.update(request_id=str(uuid.uuid4()), record_id=self.pending['id'], revision=2,
            account_version=version(self.root), snapshot_id=None, plan=None)
        p['feedback']['amount'] = '30'
        p['historical_reconciliation'] = dict(schema_version=HISTORICAL_SCHEMA,
            owner_instruction=dict(path=self.source, sha256=sha(read(self.root, self.source))),
            pending_record_sha256=sha(self.raw_record(self.pending['id'])),
            original_record_sha256=sha(self.raw_record(self.original['id'])),
            input_hashes={rel:sha(read(self.root, rel)) if (self.root / rel).exists() else None
                for rel in HISTORICAL_INPUTS},
            date_correction=dict(record_id=self.original['id'], execution_id=self.original['execution_id'],
                expected_date='2026-09-10', corrected_date='2026-09-15',
                reason='The owner corrected the original purchase date.'))
        return p

    def preview(self, p=None):
        p = p or self.payload
        result = self.store.historical_preview(p)
        p['preview_hash'] = result['preview_hash']
        return result

    def table_bytes(self, table):
        with self.store.db() as con:
            return [tuple(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]

    def assert_applied_once(self):
        account = json.loads(read(self.root, ACCOUNT))
        holdings = {r['ticker']:r for r in rows(read(self.root, POSITIONS))}
        self.assertEqual(account['cash_available'], 970)
        self.assertEqual({k:r['shares_optional'] for k,r in holdings.items()}, {'CORE':'2', 'TST':'2'})
        self.assertEqual(holdings['TST']['entry_price'], '25.000000')
        executions = rows(read(self.root, LEDGER))
        self.assertEqual(len(executions), 3)
        additional = [r for r in executions if r['execution_id'] == 'dashboard-' + self.pending['id']]
        self.assertEqual(len(additional), 1)
        self.assertEqual((additional[0]['fill_date'], additional[0]['fill_price']), ('2026-09-10', '30'))
        for rel in (LEDGER, CONFIRMED):
            original = next(r for r in rows(read(self.root, rel))
                if r['execution_id'] == self.original['execution_id'])
            self.assertEqual((original['fill_date'], original['fill_price']), ('2026-09-15', '20'))

    def test_explicit_reconciliation_preserves_original_history_and_current_ledger_basis(self):
        original = self.raw_record(self.original['id'])
        events, requests = self.table_bytes('events'), self.table_bytes('requests')
        orders, manual = read(self.root, ORDERS), read(self.root, MANUAL, optional=True)
        before = {rel:read(self.root, rel, optional=True) for rel in HISTORICAL_INPUTS}
        preview = self.preview()
        self.assertEqual(preview['missing'], [])
        self.assertEqual((preview['changes']['cash_before'], preview['changes']['cash_after']), (1000, 970))
        record = self.store.historical_submit(self.payload)
        self.assertEqual((record['id'], record['revision'], record['stage']), (self.pending['id'], 3, 'applied'))
        self.assertEqual(record['feedback']['amount'], '30')
        self.assertEqual(record['changes']['balance_basis'], 'current_local_ledger_reconciliation_not_historical_balance')
        self.assertFalse(record['historical_reconciliation']['broker_observation_claimed'])
        self.assertFalse(record['historical_reconciliation']['reconstructed_historical_cash_claimed'])
        self.assert_applied_once()
        self.assertEqual(self.raw_record(self.original['id']), original)
        self.assertEqual(self.table_bytes('events')[:len(events)], events)
        self.assertEqual(self.table_bytes('requests')[:len(requests)], requests)
        self.assertEqual(read(self.root, ORDERS), orders)
        self.assertEqual(read(self.root, MANUAL, optional=True), manual)
        with self.store.db() as con:
            retained = {r['path']:r['before'] for r in con.execute('SELECT path,before FROM writes WHERE request_id=?',
                (self.payload['request_id'],))}
        for rel in (ACCOUNT, POSITIONS, LEDGER, CONFIRMED, RECONCILED):
            self.assertEqual(retained[rel], before[rel])
        for rel in (LEDGER, CONFIRMED):
            previous_rows = rows(before[rel])
            current_rows = rows(read(self.root, rel))
            self.assertEqual(len(current_rows), len(previous_rows) + 1)
            for previous, current in zip(previous_rows, current_rows):
                if previous['execution_id'] == self.original['execution_id']:
                    self.assertEqual({k for k in previous if previous[k] != current[k]}, {'fill_date', 'notes'})
                    self.assertTrue(current['notes'].startswith(previous['notes']))
                else:
                    self.assertEqual(current, previous)
        history = {r['id']:r for r in self.store.history()}
        old = history[self.original['id']]
        self.assertEqual(old['feedback']['date'], '2026-09-10')
        self.assertEqual(old['effective_date'], '2026-09-15')
        self.assertEqual(old['execution_date_correction']['record_id'], self.pending['id'])
        self.assertEqual(old['execution_date_correction']['revision'], 3)
        proof = record['historical_reconciliation']['owner_instruction']
        self.assertEqual(sha(read(self.root, proof['path'])), proof['sha256'])

    def test_ordinary_posts_still_cannot_apply_historical_fills(self):
        with self.assertRaisesRegex(FeedbackError, 'historical_reconciliation_cli_required'):
            self.store.preview(self.payload)
        with self.assertRaisesRegex(FeedbackError, 'historical_reconciliation_cli_required'):
            self.store.submit(self.payload)
        ordinary = {k:copy.deepcopy(v) for k,v in self.payload.items() if k != 'historical_reconciliation'}
        result = self.store.preview(ordinary)
        self.assertTrue(any('较晚成交' in reason for reason in result['missing']))
        self.assertEqual(json.loads(read(self.root, ACCOUNT))['cash_available'], 1000)

    def test_request_retry_is_idempotent_and_another_request_cannot_reapply(self):
        self.preview()
        record = self.store.historical_submit(self.payload)
        tables = {t:self.table_bytes(t) for t in ('records', 'requests', 'events', 'writes')}
        self.assertEqual(self.store.historical_submit(self.payload), record)
        for table, contents in tables.items():
            self.assertEqual(self.table_bytes(table), contents)
        second = copy.deepcopy(self.payload)
        second['request_id'] = str(uuid.uuid4())
        with self.assertRaises(FeedbackError):
            self.store.historical_submit(second)
        changed = copy.deepcopy(self.payload)
        changed['feedback']['amount'] = '1'
        with self.assertRaisesRegex(FeedbackError, 'request_id_reused'):
            self.store.historical_submit(changed)
        self.assert_applied_once()

    def test_stale_source_pending_record_and_financial_fingerprints_fail_closed(self):
        cases = [
            lambda p:p.update(account_version='0' * 64),
            lambda p:p.update(revision=1),
            lambda p:p['historical_reconciliation'].update(original_record_sha256='0' * 64),
            lambda p:p['historical_reconciliation'].update(pending_record_sha256='0' * 64),
            lambda p:p['historical_reconciliation']['input_hashes'].update({LEDGER:'0' * 64}),
            lambda p:p['historical_reconciliation']['owner_instruction'].update(sha256='0' * 64),
            lambda p:p['historical_reconciliation']['date_correction'].update(corrected_date='2026-09-14'),
            lambda p:p['feedback'].update(amount='31'),
            lambda p:p['feedback'].update(shares='2'),
        ]
        before = {rel:read(self.root, rel, optional=True) for rel in HISTORICAL_INPUTS}
        for mutate in cases:
            p = copy.deepcopy(self.payload)
            mutate(p)
            with self.subTest(payload=p), self.assertRaises(FeedbackError):
                self.store.historical_preview(p)
        for rel, raw in before.items():
            self.assertEqual(read(self.root, rel, optional=True), raw)

    def test_owner_local_ledger_authority_is_required(self):
        (self.root / '05_risk_and_positions/account_record_policy.local.json').unlink()
        with self.assertRaisesRegex(FeedbackError, 'historical_reconciliation_invalid'):
            self.store.historical_preview(self.payload)

    def test_malformed_owner_facts_fail_with_a_typed_error_without_writing(self):
        for block, value in (('additional_purchase', []), ('existing_purchase_correction', None)):
            changed = copy.deepcopy(self.facts)
            changed['confirmed_facts'][block] = value
            self.fixture.put(self.source, changed)
            p = self.request()
            with self.subTest(block=block), self.assertRaises(FeedbackError):
                self.store.historical_preview(p)
        self.assertEqual(json.loads(read(self.root, ACCOUNT))['cash_available'], 1000)

    def test_known_ticker_order_cannot_be_silently_consumed_or_marked_complete(self):
        orders = json.loads(read(self.root, ORDERS))
        orders['orders'] = [dict(order_id='retained-order', ticker='TST', side='buy', status='open')]
        self.fixture.put(ORDERS, orders)
        p = self.request()
        with self.assertRaisesRegex(FeedbackError, 'historical_reconciliation_invalid'):
            self.store.historical_preview(p)
        self.assertEqual(json.loads(read(self.root, ORDERS)), orders)

    def test_inputs_are_rechecked_immediately_before_preparing_writes(self):
        self.preview()
        before_account = read(self.root, ACCOUNT)
        real = self.store.pending_brief
        def intervening(writes, now):
            draft = real(writes, now)
            (self.root / LEDGER).write_bytes(read(self.root, LEDGER) + b'\n')
            return draft
        with patch.object(self.store, 'pending_brief', side_effect=intervening), \
             self.assertRaisesRegex(FeedbackError, 'historical_reconciliation_invalid'):
            self.store.historical_submit(self.payload)
        self.assertEqual(read(self.root, ACCOUNT), before_account)
        with self.store.db() as con:
            self.assertIsNone(con.execute('SELECT id FROM requests WHERE id=?',
                (self.payload['request_id'],)).fetchone())

    def test_changed_original_economics_cannot_be_hidden_by_fresh_csv_hashes(self):
        for rel in (LEDGER, CONFIRMED):
            original = read(self.root, rel)
            data = rows(original)
            target = next(r for r in data if r['execution_id'] == self.original['execution_id'])
            target['cash_before'] = '9999'
            (self.root / rel).write_bytes(feedback.csv_bytes(data, list(data[0])))
            p = self.request()
            with self.subTest(path=rel), self.assertRaises(FeedbackError):
                self.store.historical_preview(p)
            self.fixture.put(rel, original.decode())

    def test_crash_after_account_write_recovers_date_and_fill_exactly_once(self):
        self.preview()
        real = feedback.atomic
        def interrupted(root, rel, content):
            if rel == LEDGER:
                raise OSError('simulated interruption after account changes')
            return real(root, rel, content)
        with patch('feedback.atomic', side_effect=interrupted), self.assertRaises(OSError):
            self.store.historical_submit(self.payload)
        with self.store.db() as con:
            self.assertEqual(con.execute('SELECT state FROM requests WHERE id=?',
                (self.payload['request_id'],)).fetchone()[0], 'prepared')
        resumed = Store(self.root, self.root / 'runtime.lock', refresh=False)
        record = resumed.historical_submit(self.payload)
        self.assertEqual(record['stage'], 'applied')
        self.assert_applied_once()
        self.assertEqual(self.raw_record(self.original['id']), encoded(self.original))

    def test_intervening_external_change_during_crash_recovery_is_not_overwritten(self):
        self.preview()
        real = feedback.atomic
        def interrupted(root, rel, content):
            if rel == LEDGER:
                raise OSError('simulated interruption')
            return real(root, rel, content)
        with patch('feedback.atomic', side_effect=interrupted), self.assertRaises(OSError):
            self.store.historical_submit(self.payload)
        account = json.loads(read(self.root, ACCOUNT))
        account['cash_available'] = 1234.56
        self.fixture.put(ACCOUNT, account)
        changed = read(self.root, ACCOUNT)
        with self.assertRaisesRegex(FeedbackError, 'recovery_conflict'):
            self.store.historical_submit(self.payload)
        self.assertEqual(read(self.root, ACCOUNT), changed)
        self.assertEqual(len(rows(read(self.root, LEDGER))), 2)

    def test_cli_requires_dedicated_preview_then_same_request_apply(self):
        proposal = self.root / 'operator-proposal.json'
        proposal.write_bytes(encoded(self.payload))
        def cli(flag):
            output = io.StringIO()
            with patch.object(record_feedback, 'DEFAULT_ROOT', self.root), \
                 patch.object(record_feedback, 'RUNTIME_LOCK', self.root / 'runtime.lock'), \
                 patch.object(sys, 'argv', ['record_feedback.py', flag, str(proposal)]), redirect_stdout(output):
                result = record_feedback.main()
            self.assertEqual(result, 0)
            return json.loads(output.getvalue())
        result = cli('--preview-historical-reconciliation')
        self.payload['preview_hash'] = result['preview_hash']
        proposal.write_bytes(encoded(self.payload))
        result = cli('--apply-historical-reconciliation')
        self.assertEqual(result['stage'], 'applied')
        self.assert_applied_once()


if __name__ == '__main__':
    unittest.main()
