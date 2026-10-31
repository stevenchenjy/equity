"""Interactive intake must not wait for the research dashboard projection."""
import fcntl
import hashlib
import http.client
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import test_feedback as fixtures
from account_access import account_lock
from feedback import ACCOUNT, PENDING, version
from server import DECISION, Handler, feedback_snapshot


class FeedbackSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FeedbackTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.fixture.put(DECISION, {'plan_continuity': {'plans': [dict(
            ticker='ABC', plan_id='ABC-original', version=7, record_hash='a' * 64,
            order_draft={'side': 'buy', 'quantity': 100}, instruction='Do not copy this advice.')]}})
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.runtime_root = self.root
        self.http.store = self.fixture.store
        self.lock = self.root / 'runtime.lock'
        self.lock.touch()
        patched = patch('server.RUNTIME_LOCK', self.lock)
        patched.start()
        self.addCleanup(patched.stop)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.origin = 'http://127.0.0.1:' + str(self.http.server_port)

    def request(self, method, path, payload=None, headers=None):
        con = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        headers = headers if headers is not None else {'Origin': self.origin, 'Content-Type': 'application/json'} if payload is not None else {}
        con.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=headers)
        response = con.getresponse()
        status, data = response.status, json.loads(response.read())
        con.close()
        return status, data

    def test_feedback_context_preserves_exact_reference_without_research_or_prices(self):
        with patch('server.current_snapshot', side_effect=AssertionError('expensive research path called')):
            with self.lock.open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                code, context = self.request('GET', '/api/feedback/snapshot')
        self.assertEqual(code, 200)
        self.assertEqual(context['account_version'], version(self.root))
        self.assertEqual(context['snapshot_id'], hashlib.sha256((self.root / DECISION).read_bytes()).hexdigest())
        self.assertEqual(context['account']['cash_available'], 1000)
        self.assertIsNone(context['account']['account_total_value'])
        self.assertFalse(context['research_ready'])
        self.assertIsNone(context['positions'][0]['price'])
        self.assertEqual(context['plans'][0]['version'], 7)
        self.assertIsNone(context['plans'][0]['draft'])
        self.assertEqual(context['plans'][0]['eligible_quantity'], 0)
        payload = self.fixture.payload()
        payload.update(account_version=context['account_version'], snapshot_id=context['snapshot_id'],
            plan={key: context['plans'][0][key] for key in ('plan_id', 'version', 'record_hash')})
        self.assertEqual(self.request('POST', '/api/feedback/preview', payload)[0], 200)
        self.fixture.put(DECISION, {'plan_continuity': {'plans': []}})
        code, error = self.request('POST', '/api/feedback/preview', payload)
        self.assertEqual((code, error['error']), (409, 'plan_reference_changed'))
        self.assertEqual(self.fixture.store.history(), [])

    def test_slow_research_reader_does_not_block_preview_account_lock(self):
        entered, release = threading.Event(), threading.Event()
        result = []

        def slow_read(*_args, **_kwargs):
            entered.set()
            release.wait(4)
            return {'schema_version': 'slow-research-fixture'}

        with patch('server.current_snapshot', side_effect=slow_read):
            reader = threading.Thread(target=lambda: result.append(self.request('GET', '/api/snapshot')), daemon=True)
            reader.start()
            try:
                self.assertTrue(entered.wait(1))
                before = time.monotonic()
                self.assertEqual(self.request('POST', '/api/feedback/preview', self.fixture.payload())[0], 200)
                self.assertLess(time.monotonic() - before, 1)
                self.assertFalse(release.is_set())
                self.assertEqual(self.fixture.store.history(), [])
            finally:
                release.set()
                reader.join(5)
        self.assertEqual(result[0][0], 200)

    def test_slow_earnings_read_does_not_gate_decision_account_or_intake(self):
        entered, release = threading.Event(), threading.Event()
        result = []
        view = {'schema_version':'equity_dashboard_snapshot_v1','account_version':'exact-account',
                'snapshot_id':'exact-publication','capital_decision_status':'recompose_required'}

        def slow_details(*_args, **kwargs):
            if kwargs['include_research_details']:
                entered.set()
                release.wait(4)
                return {**view,'earnings_events':{'schema_version':'equity_earnings_event_view_v1','status':'unverified','events':[]}}
            return view

        with patch('server.current_snapshot', side_effect=slow_details) as snapshot:
            reader=threading.Thread(target=lambda:result.append(self.request('GET','/api/research-details')),daemon=True)
            reader.start()
            try:
                self.assertTrue(entered.wait(1))
                before=time.monotonic()
                code,core=self.request('GET','/api/snapshot')
                self.assertEqual(code,200)
                self.assertNotIn('earnings_events',core)
                self.assertEqual(self.request('GET','/api/feedback/snapshot')[0],200)
                self.assertEqual(self.request('POST','/api/feedback/preview',self.fixture.payload())[0],200)
                self.assertLess(time.monotonic()-before,1)
                self.assertFalse(release.is_set())
                self.assertEqual([call.kwargs['include_research_details'] for call in snapshot.call_args_list],[True,False])
            finally:
                release.set();reader.join(5)
        self.assertEqual(result[0][0],200)
        self.assertEqual((result[0][1]['account_version'],result[0][1]['snapshot_id']),('exact-account','exact-publication'))

    def test_account_change_during_deferred_earnings_rejects_entire_result(self):
        def changed_details(*_args, **_kwargs):
            with account_lock(self.root):
                account=json.loads((self.root/ACCOUNT).read_text());account['cash_available']=999
                self.fixture.put(ACCOUNT,account)
            return {**view,'earnings_events':{'status':'ready','events':[{'status':'eligible_conditional_plan'}]}}
        view={'account_version':'before','snapshot_id':'old-publication','capital_decision_status':'current'}
        with patch('server.current_snapshot',side_effect=changed_details):
            code,result=self.request('GET','/api/research-details')
        self.assertEqual((code,result['error']),(503,'snapshot_changed_during_read'))
        self.assertNotIn('earnings_events',result)

    def test_deferred_earnings_retains_origin_and_publication_checks(self):
        self.assertEqual(self.request('GET','/api/research-details',headers={'Host':'untrusted.example'})[0],403)
        from server import SnapshotError
        with patch('server.current_snapshot',side_effect=SnapshotError('publication_fingerprints_missing')),patch('server.earnings_event_view') as events:
            code,result=self.request('GET','/api/research-details')
        self.assertEqual((code,result['error']),(503,'publication_fingerprints_missing'))
        events.assert_not_called()

    def test_account_change_during_slow_research_is_rejected(self):
        entered, release = threading.Event(), threading.Event()
        result = []

        def slow_read(*_args, **_kwargs):
            entered.set()
            release.wait(4)
            return {'account': {'cash_available': 1000}}

        with patch('server.current_snapshot', side_effect=slow_read):
            reader = threading.Thread(target=lambda: result.append(self.request('GET', '/api/snapshot')), daemon=True)
            reader.start()
            try:
                self.assertTrue(entered.wait(1))
                with account_lock(self.root):
                    account = json.loads((self.root / ACCOUNT).read_text())
                    account['cash_available'] = 999
                    self.fixture.put(ACCOUNT, account)
            finally:
                release.set()
                reader.join(5)
        self.assertEqual(result[0], (503, {'error': 'snapshot_changed_during_read', 'production_effect': False}))

    def test_account_change_after_context_still_fails_preview_version_check(self):
        code, context = self.request('GET', '/api/feedback/snapshot')
        self.assertEqual(code, 200)
        payload = self.fixture.payload()
        payload['account_version'] = context['account_version']
        account = json.loads((self.root / ACCOUNT).read_text())
        account['cash_available'] = 999
        self.fixture.put(ACCOUNT, account)
        code, error = self.request('POST', '/api/feedback/preview', payload)
        self.assertEqual((code, error['error']), (409, 'account_version_changed'))

    def test_incomplete_account_transition_is_not_exposed_as_committed(self):
        self.fixture.put(PENDING, {'records': [{'stage': 'recovery_conflict'}]})
        code, error = self.request('GET', '/api/feedback/snapshot')
        self.assertEqual((code, error['error']), (503, 'requested_data_unavailable'))

    def test_missing_or_malformed_research_keeps_account_intake_available(self):
        for content in ('not-json', '[]'):
            self.fixture.put(DECISION, content)
            code, context = self.request('GET', '/api/feedback/snapshot')
            self.assertEqual(code, 200)
            self.assertEqual(context['plans'], [])
            self.assertEqual(context['account']['cash_available'], 1000)


if __name__ == '__main__':
    unittest.main()
