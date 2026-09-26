from __future__ import annotations
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa
import send_daily_email as sender
from delivery_continuity import delivery_meaning_key, covered_by_last_delivery
from email_brief import render_email
from test_email_brief import decision_fixture
from test_owner_review_delivery import delivery_fixture, save_decision

NOW = datetime(2026,9,2,14,tzinfo=ZoneInfo('America/New_York'))


def fixture():
    d=decision_fixture()
    d['workflow_integrity']={'schema_version':'equity_workflow_integrity_v1','blockers':[]}
    d['plan_continuity']={'status':'needs_reconciliation','conflicts':[], 'plans':[
        {'ticker':'RBRK','plan_id':'p','version':1,'record_hash':'a'*64,'action':'protect_review',
         'status':'maintained','current_shares':2,'review_at':'2026-09-02T09:35:00-04:00',
         'instruction':'Retain the recorded plan; verify before acting.',
         'blockers':['fresh_quote_and_available_shares_required'], 'proposed_change_shares':2,
         'historical_order_draft':{'side':'sell','type':'STOP','stop_price':80}}]}
    d['watch_candidates']=[{'ticker':'AAA','label':'watchlist','suggested_whole_shares':'0'}]
    d['long_horizon_research']={'views':{'RBRK':{'status':'monitor','review_id':'r','version':1,
        'valuation_readiness':'incomplete','news_review':{'pending_events':[]}}}}
    return d


class DeliveryContinuityTests(unittest.TestCase):
    def test_next_day_and_weekend_rank_churn_do_not_repeat_retained_plan(self):
        a=fixture();b=copy.deepcopy(a)
        b.update(cycle_date='2026-09-05',generated_at='2026-09-05T13:00:00-04:00')
        b['watch_candidates']=[{'ticker':'BBB','label':'watchlist','suggested_whole_shares':'0'}]
        b['independent_market_discovery']={'schema_version':'phase5r_market_discovery_v1','complete':True,
            'status':'complete','top_stocks':[{'ticker':'NEW'}]}
        b['held_positions'][0]['current_price']='99.00'
        b['account']['account_total_value']='2500'
        p=b['plan_continuity']['plans'][0]
        p.update(status='expired_pending_verification',action='reconcile_plan',
            blockers=['fresh_quote_and_available_shares_required','order_snapshot_requires_recheck'])
        self.assertEqual(delivery_meaning_key(a),delivery_meaning_key(b))
        row={'status':'owner_review_sent','timestamp':'2026-09-01T21:00:00-04:00','reason':delivery_meaning_key(a)}
        self.assertTrue(covered_by_last_delivery([row],b,current=NOW,archive_dir=Path('/nonexistent')))

    def test_meaningful_risk_plan_evidence_and_account_changes_still_notify(self):
        a=fixture()
        for mutate in [
            lambda d:d['plan_continuity']['plans'][0].update(version=2,record_hash='b'*64),
            lambda d:d['plan_continuity']['plans'][0].update(status='position_changed_pending_verification'),
            lambda d:d['held_positions'][0].update(current_shares='1'),
            lambda d:d['account'].update(cash_available='1500'),
            lambda d:d['market_gate'].update(passed=False),
            lambda d:d.update(account_conflicts=['unreconciled_fill']),
            lambda d:d['long_horizon_research']['views']['RBRK'].update(version=2),
            lambda d:d['long_horizon_research']['views']['RBRK']['news_review'].update(pending_events=[{'event_id':'new'}]),
            lambda d:d['fundamental_gate'].update(weakening_tickers=['RBRK']),
        ]:
            b=copy.deepcopy(a);mutate(b)
            self.assertNotEqual(delivery_meaning_key(a),delivery_meaning_key(b))

    def test_changed_and_removed_eligible_order_proposals_notify(self):
        a=fixture();a.update(decision_code='action_review_candidate',eligible_new_position_review_candidates=['AAA'],new_candidate_stability_distinct_closes=2)
        a['watch_candidates'][0].update(action='eligible_buy_review',suggested_whole_shares='1',maximum_review_price='100')
        b=copy.deepcopy(a);b['watch_candidates'][0]['maximum_review_price']='99'
        self.assertNotEqual(delivery_meaning_key(a),delivery_meaning_key(b))
        b=copy.deepcopy(a);b['eligible_new_position_review_candidates']=[]
        self.assertNotEqual(delivery_meaning_key(a),delivery_meaning_key(b))
        a['tactical_review']={'schema_version':'phase5r_tactical_review_v1','open_orders':{'complete':True,'orders':[{'ticker':'AAA','status':'open','quantity':1,'remaining_quantity':1}]}}
        b=copy.deepcopy(a);b['tactical_review']['open_orders']['orders'][0].update(status='filled',remaining_quantity=0)
        self.assertNotEqual(delivery_meaning_key(a),delivery_meaning_key(b))

    def test_stale_order_snapshot_and_rejected_entry_diagnostics_do_not_repeat_mail(self):
        a=fixture()
        a['tactical_review']={'schema_version':'phase5r_tactical_review_v1',
            'blockers':['latest_completed_session_missing'], 'open_orders':{'complete':True,'orders':[
                {'ticker':'RBRK','status':'pending','quantity':2,'remaining_quantity':2,'limit_price':100,'review_status':'pending'}]},
            'drafts':[{'ticker':'AAA','eligible':False,'quantity':0,'blockers':['valuation']} ]}
        b=copy.deepcopy(a)
        b['tactical_review']['blockers']=['open_orders_unconfirmed']
        b['tactical_review']['open_orders']['complete']=False
        b['tactical_review']['open_orders']['orders'][0]['review_status']='expired_pending_verification'
        b['tactical_review']['drafts']=[{'ticker':'BBB','eligible':False,'quantity':0}]
        self.assertEqual(delivery_meaning_key(a),delivery_meaning_key(b))

    def test_latest_receipt_wins_and_claim_unknown_prevent_retries(self):
        a=fixture();b=copy.deepcopy(a);b['account']['cash_available']='1500'
        for status in ['send_claimed','sent','delivery_unknown','owner_review_sent','correction_sent']:
            rows=[{'timestamp':'2026-09-01T10:00:00-04:00','status':'sent','reason':delivery_meaning_key(a)},
                  {'timestamp':'2026-09-02T10:00:00-04:00','status':status,'reason':delivery_meaning_key(b)}]
            self.assertFalse(covered_by_last_delivery(rows,a,current=NOW,archive_dir=Path('/none')))
            self.assertTrue(covered_by_last_delivery(rows,b,current=NOW,archive_dir=Path('/none')))

    def test_legacy_archive_requires_exact_receipt_hash(self):
        d=fixture();raw=json.dumps(d).encode();digest=hashlib.sha256(raw).hexdigest()
        rows=[{'timestamp':'2026-09-01T21:00:00-04:00','status':'sent','decision_sha256':digest}]
        with tempfile.TemporaryDirectory() as temp:
            archive=Path(temp)
            self.assertFalse(covered_by_last_delivery(rows,d,current=NOW,archive_dir=archive))
            (archive/(digest+'.json')).write_bytes(raw)
            self.assertTrue(covered_by_last_delivery(rows,d,current=NOW,archive_dir=archive))
            (archive/(digest+'.json')).write_bytes(raw+b' ')
            self.assertFalse(covered_by_last_delivery(rows,d,current=NOW,archive_dir=archive))

    def test_suppression_occurs_before_credentials_or_smtp(self):
        d=fixture()
        d['send_recommended']=True
        with delivery_fixture() as (config,smtp):
            save_decision(d)
            row={'timestamp':'2026-08-31T21:00:00-04:00','status':'owner_review_sent','reason':delivery_meaning_key(d)}
            with patch.object(sender,'validate_decision',return_value=d), patch.object(sender,'read_csv',return_value=[row]):
                self.assertEqual(sender.send_once(smtp),0)
            config.assert_not_called();smtp.assert_not_called()

    def test_new_renderer_is_compact_english_and_retains_expiry_without_renewal(self):
        d=fixture();p=d['plan_continuity']['plans'][0]
        p.update(status='expired_pending_verification',action='reconcile_plan')
        subject,text,html=render_email(d)
        self.assertIn('Portfolio update',subject)
        self.assertEqual(html.count('<h2'),6)
        self.assertLess(len(text.split()),650)
        for body in [text,html]:
            self.assertIn('dated plan expired; outcome unconfirmed',body)
            self.assertIn('previous protection review',body)
            self.assertIn('zero newly eligible',body)
            self.assertNotIn('$80.00',body)
            self.assertNotRegex(body,r'[\u4e00-\u9fff]')
        d['account_conflicts']=['new conflict'];d['eligible_new_position_review_candidates']=['AAA']
        d['watch_candidates'][0].update(suggested_whole_shares='99',maximum_review_price='123.45')
        for body in render_email(d)[1:]:
            self.assertNotIn('123.45',body)
            self.assertIn('New trade drafts are withheld',body)


if __name__=='__main__':unittest.main()
