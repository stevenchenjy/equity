import hashlib
import json
import tempfile
import unittest
import fcntl
import http.client
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

from server import ACCOUNT, CORE_INPUTS, DECISION, MARKET, ORDERS, PLANS, POSITIONS, Handler, SnapshotError, read_snapshot, safe_read


class SnapshotTests(unittest.TestCase):
    def test_presentation_summary_matches_source_without_changing_research_facts(self):
        from plan_summary import SCHEMA, SUMMARY_PATH, source_hash
        p=self.decision['plan_continuity']['plans'][0]
        p.update(reason='Reviewed prior close.',counterargument='No current quote.',purpose={'exit_rule':'No automatic sell.'},record_hash='a'*64)
        self.publish()
        sections={k:[{'label':'要点','text':'仅供复审。'}] for k in ('reason','counterargument','conditions')}
        entry={**{k:p[k] for k in ('ticker','plan_id','version','record_hash')},'source_sha256':source_hash(p),'sections':sections}
        self.put(SUMMARY_PATH,{'schema_version':SCHEMA,'entries':[entry]})
        raw=(self.root/DECISION).read_bytes()
        result=read_snapshot(self.root,self.now)
        self.assertEqual(result['plans'][0]['display_summary'],sections)
        self.assertEqual((self.root/DECISION).read_bytes(),raw)
        p['reason']='New evidence.';self.publish()
        result=read_snapshot(self.root,self.now)
        self.assertIsNone(result['plans'][0]['display_summary'])
        self.assertEqual(result['plans'][0]['reason'],'New evidence.')
        self.assertEqual(result['plans'][0]['eligible_quantity'],2)

    def test_broken_or_symlinked_presentation_notes_do_not_break_snapshot(self):
        from plan_summary import SUMMARY_PATH
        self.put(SUMMARY_PATH,'{broken')
        self.assertIsNone(read_snapshot(self.root,self.now)['plans'][0]['display_summary'])
        path=self.root/SUMMARY_PATH;path.unlink();path.symlink_to(self.root/DECISION)
        self.assertIsNone(read_snapshot(self.root,self.now)['plans'][0]['display_summary'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.fromisoformat('2026-09-30T14:00:00-04:00')
        self.put(ACCOUNT, {'cash_available': 1000, 'last_updated': '2026-09-30T13:00:00-04:00'})
        self.put(ORDERS, {'as_of': '2026-09-30T13:00:00-04:00', 'complete': True, 'orders': [], 'cash_confirmed': True})
        self.put(PLANS, {'records': []})
        self.put(POSITIONS, 'ticker,shares_optional\nABC,2\n')
        self.put(MARKET, 'ticker,last_price,market_session_date,data_quality_label\nABC,100,2026-09-29,ok\n')
        self.decision = {
            'generated_at': '2026-09-30T13:30:00-04:00', 'cycle_date': '2026-09-30',
            'account': {'cash_available': '1000', 'invested_capital': '200', 'account_total_value': '1200'},
            'market_gate': {'expected_market_session': '2026-09-29'},
            'workflow_integrity': {'input_hashes': {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in CORE_INPUTS}},
            'held_positions': [{'ticker': 'ABC', 'current_shares': '2', 'current_price': '100', 'current_weight_pct': '16.6667'}],
            'plan_continuity': {'plans': [{
                'ticker': 'ABC', 'plan_id': 'ABC-1', 'version': 1, 'action': 'protect_review',
                'review_at': '2026-09-30T15:30:00-04:00', 'eligible_quantity': 2,
                'order_draft': {'quantity': 2, 'stop_price': 90}, 'blockers': [],
            }]},
            'eligible_new_position_review_candidates': ['ABC'],
            'watch_candidates': [{'ticker': 'ABC', 'suggested_whole_shares': '1', 'maximum_review_price': '100'}],
        }
        self.publish()

    def put(self, path, data):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))

    def publish(self):
        self.put(DECISION, self.decision)

    def test_current_snapshot_preserves_quantity_and_does_not_change_inputs(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = read_snapshot(self.root, self.now)
        self.assertEqual(result['plans'][0]['eligible_quantity'], 2)
        self.assertEqual(result['candidates'][0]['quantity'], 1)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_review_deadline_suppresses_both_held_and_new_quantities(self):
        result = read_snapshot(self.root, datetime.fromisoformat('2026-09-30T15:30:00-04:00'))
        self.assertEqual(result['plans'][0]['status'], 'expired')
        self.assertEqual(result['plans'][0]['eligible_quantity'], 0)
        self.assertIsNone(result['plans'][0]['draft'])
        self.assertEqual(result['candidates'][0]['quantity'], 0)
        self.assertIsNone(result['candidates'][0]['maximum_review_price'])

    def test_different_day_is_stale_without_renewing_plan(self):
        result = read_snapshot(self.root, datetime.fromisoformat('2026-10-01T08:00:00-04:00'))
        self.assertTrue(result['stale'])
        self.assertEqual(result['plans'][0]['status'], 'expired')

    def test_changed_account_cannot_mix_with_old_decision(self):
        self.put(ACCOUNT, {'cash_available': 900})
        with self.assertRaisesRegex(SnapshotError, 'research_inputs_changed'):
            read_snapshot(self.root, self.now)

    def test_new_market_snapshot_cannot_relabel_old_prices(self):
        self.put(MARKET, 'ticker,last_price,market_session_date,data_quality_label\nABC,110,2026-09-30,ok\n')
        with self.assertRaisesRegex(SnapshotError, 'decision_price_snapshot_mismatch'):
            read_snapshot(self.root, self.now)

    def test_mismatched_dynamic_total_fails_closed(self):
        self.decision['account']['account_total_value'] = '1250'
        self.publish()
        with self.assertRaisesRegex(SnapshotError, 'decision_account_total_does_not_reconcile'):
            read_snapshot(self.root, self.now)

    def test_cash_confirmation_does_not_prove_settlement(self):
        self.assertFalse(read_snapshot(self.root, self.now)['account']['settled_cash_verified'])

    def test_missing_publication_fingerprint_is_rejected(self):
        del self.decision['workflow_integrity']['input_hashes'][PLANS]
        self.publish()
        with self.assertRaisesRegex(SnapshotError, 'publication_fingerprints_missing'):
            read_snapshot(self.root, self.now)

    def test_unknown_input_and_symlink_are_rejected(self):
        self.decision['workflow_integrity']['input_hashes']['../../outside'] = 'a' * 64
        self.publish()
        with self.assertRaisesRegex(SnapshotError, 'unregistered_publication_input'):
            read_snapshot(self.root, self.now)
        linked = self.root / 'linked'
        linked.symlink_to(self.root / ACCOUNT)
        with self.assertRaisesRegex(SnapshotError, 'symlink_input_rejected'):
            safe_read(self.root, 'linked')

    def test_http_routes_reject_mutation_cross_origin_and_busy_runtime(self):
        lock_path = self.root / 'runtime.lock'
        lock_path.touch()
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        http.runtime_root = self.root
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        # Name the listener differently from the standard-library client module.
        import http.client as client_module
        def request(method, path, headers=None):
            client = client_module.HTTPConnection('127.0.0.1', http.server_port)
            client.request(method, path, headers=headers or {})
            response = client.getresponse()
            result = (response.status, response.read())
            client.close()
            return result
        with patch('server.RUNTIME_LOCK', lock_path):
            self.assertEqual(request('GET', '/api/snapshot')[0], 200)
            for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                self.assertEqual(request(method, '/api/snapshot')[0], 405)
            self.assertEqual(request('GET', '/api/snapshot', {'Host': 'untrusted.example'})[0], 403)
            self.assertEqual(request('GET', '/api/snapshot', {'Origin': 'https://untrusted.example'})[0], 403)
            self.assertEqual(request('GET', '/api/snapshot', {'Sec-Fetch-Site': 'cross-site'})[0], 403)
            self.assertEqual(request('GET', '/../../05_risk_and_positions/current_positions.local.csv')[0], 404)
            with lock_path.open('rb') as held:
                fcntl.flock(held.fileno(), fcntl.LOCK_EX)
                code, raw = request('GET', '/api/snapshot')
                self.assertEqual(code, 503)
                self.assertIn(b'runtime_refresh_in_progress', raw)


if __name__ == '__main__':
    unittest.main()
