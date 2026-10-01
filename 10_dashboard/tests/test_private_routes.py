import hashlib
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from datetime import datetime

import test_feedback as fixture_module
from feedback import ACCOUNT, ORDERS, encoded, read, verify_publication
from server import Handler, email_version
from dashboard_publication import bind_dashboard_link, publication_id
from email_brief import render_email
from connect_private import our_route


class PrivateRoutesTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.FeedbackTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http.store=self.fixture.store
        self.http.runtime_root=self.root
        self.http.access={'host':'test.example.ts.net','owner_login':'owner@example.test'}
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.local='http://127.0.0.1:'+str(self.http.server_port)
        self.lock=self.root/'runtime.lock';self.lock.touch()
        self.patch=patch('server.RUNTIME_LOCK',self.lock);self.patch.start();self.addCleanup(self.patch.stop)

    def request(self,method,path,payload=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        body=json.dumps(payload) if payload is not None else None
        conn.request(method,path,body=body,headers=headers or {})
        res=conn.getresponse();code,raw=res.status,res.read();conn.close()
        return code,json.loads(raw)

    def test_form_roundtrip_and_unknown_origin_cannot_mutate(self):
        p=self.fixture.payload()
        good={'Origin':self.local,'Content-Type':'application/json'}
        for headers in [{},{'Content-Type':'application/json'},dict(good,Origin='https://evil.example'),dict(good,**{'Sec-Fetch-Site':'cross-site'})]:
            self.assertEqual(self.request('POST','/api/feedback',p,headers)[0],403)
        self.assertEqual(self.fixture.store.history(),[])
        code,preview=self.request('POST','/api/feedback/preview',p,good)
        self.assertEqual(code,200)
        self.assertEqual(self.fixture.store.history(),[])
        p['preview_hash']=preview['preview_hash']
        code,result=self.request('POST','/api/feedback',p,good)
        self.assertEqual((code,result['stage']),(200,'applied'))
        self.assertEqual(self.request('POST','/api/feedback',p,good),(200,result))
        self.assertEqual(len(self.request('GET','/api/feedback')[1]['records']),1)

    def test_tailscale_owner_host_and_https_origin_required(self):
        private={'Host':'test.example.ts.net','Tailscale-User-Login':'owner@example.test'}
        self.assertEqual(self.request('GET','/api/feedback',headers=private)[0],200)
        for headers in [{'Host':private['Host']},dict(private,**{'Tailscale-User-Login':'other@example.test'}),dict(private,Host='other.example.ts.net')]:
            self.assertEqual(self.request('GET','/api/feedback',headers=headers)[0],403)
        p=self.fixture.payload()
        good=dict(private,Origin='https://test.example.ts.net',**{'Content-Type':'application/json'})
        self.assertEqual(self.request('POST','/api/feedback/preview',p,good)[0],200)
        self.assertEqual(self.request('POST','/api/feedback/preview',p,dict(good,Origin='http://test.example.ts.net'))[0],403)

    def archive(self):
        d={'generated_at':'2026-09-30T14:00:00-04:00','cycle_date':'2026-09-30','decision_fingerprint':'test-v1','headline':'Original email',
           'plan_continuity':{'plans':[]}}
        bind_dashboard_link(d,self.root)
        raw=encoded(d);key=hashlib.sha256(raw).hexdigest()
        self.fixture.put('07_automation/email_delivery/sent_decisions.local/'+key+'.json',raw.decode())
        text=b'Original sent body; historical price and conditions.';text_hash=hashlib.sha256(text).hexdigest()
        self.fixture.put('07_automation/email_delivery/sent_decisions.local/'+text_hash+'.txt',text.decode())
        self.fixture.put('07_automation/email_delivery/daily_delivery_ledger.csv','timestamp,status,decision_sha256,brief_text_sha256\n2026-09-30T14:01:00-04:00,sent,'+key+','+text_hash+'\n')
        return d,key

    def test_mail_link_resolves_exact_sent_archive_and_rejects_tampering(self):
        self.fixture.put('07_automation/dashboard.local/access.json',self.http.access)
        d,key=self.archive()
        code,view=self.request('GET','/api/email-publication?id='+publication_id(d))
        self.assertEqual((code,view['id'],view['headline']),(200,key,'Original email'))
        self.assertTrue(view['body_archive_verified']);self.assertIn('historical price and conditions',view['original_text'])
        p=self.fixture.payload();p['email_version_id']=key
        self.assertEqual(self.fixture.submit(p)['email_version_id'],key)
        self.fixture.put('07_automation/email_delivery/sent_decisions.local/'+key+'.json',{'tampered':True})
        self.assertEqual(self.request('GET','/api/email-publication?id='+publication_id(d))[0],503)
        with self.assertRaisesRegex(ValueError,'archive_hash_mismatch'):email_version(self.root,key)

    def test_email_render_snapshots_host_and_handles_owner_review_identity(self):
        self.fixture.put('07_automation/dashboard.local/access.json',self.http.access)
        d,key=self.archive()
        # Later owner-review metadata changes the publication identity before sending.
        d['owner_requested_research']={'request_id':'review-1'}
        token=publication_id(d)
        with patch('email_brief._render_email_without_dashboard',return_value=('Subject','Body','<body>Body</body>')):
            _,plain,html=render_email(d)
            self.assertIn('https://test.example.ts.net/?publication='+token,plain)
            self.assertIn(token,html)
            self.fixture.put('07_automation/dashboard.local/access.json',{'host':'changed.example.ts.net'})
            self.assertEqual(render_email(d)[1],plain)
            d['dashboard_link']['url']='https://evil.example/?publication='+token
            self.assertEqual(render_email(d),('Subject','Body','<body>Body</body>'))

    def test_sent_body_is_read_from_archive_and_never_rebuilt_with_current_template(self):
        d,key=self.archive()
        text_hash=hashlib.sha256(b'Original sent body; historical price and conditions.').hexdigest()
        path='07_automation/email_delivery/sent_decisions.local/'+text_hash+'.txt'
        with patch('email_brief.render_email',side_effect=AssertionError('must not rerender an old email')):
            self.assertTrue(email_version(self.root,key)['body_archive_verified'])
            self.fixture.put(path,'tampered')
            with self.assertRaisesRegex(ValueError,'body_archive_hash_mismatch'):email_version(self.root,key)
            (self.root/path).unlink()
            self.assertFalse(email_version(self.root,key)['body_archive_verified'])

    def test_owner_inventory_observation_has_real_immutable_hash(self):
        order=self.fixture.submit(self.fixture.payload(status='pending',shares='2',order_price='100'))
        p=self.fixture.payload(status='account',date=datetime.now().astimezone().date().isoformat(),cash='1000',account_observed=True,
             holdings=[{'ticker':'ABC','shares':'2','entry_price':'100'}],inventory_complete=True,
             orders_match=True,observed_order_ids=[order['order_id']])
        self.assertEqual(self.fixture.submit(p)['stage'],'applied')
        observation=json.loads(read(self.root,ORDERS))['current_inventory_observation']['source']
        self.assertEqual(hashlib.sha256(read(self.root,observation['path'])).hexdigest(),observation['sha256'])
        self.assertTrue(observation['path'].endswith('.json'))

    def test_final_publication_cannot_bind_hashes_to_stale_holdings_or_brief(self):
        d={'account':{'cash_available':'1000','invested_capital':'200','account_total_value':'1200'},
           'held_positions':[{'ticker':'ABC','current_shares':'2','current_price':'100'}]}
        self.fixture.put('07_automation/email_briefs/daily_email_brief.txt','fresh plain')
        self.fixture.put('07_automation/email_briefs/daily_email_brief.html','fresh html')
        with patch('email_brief.render_email',return_value=('Subject','fresh plain','fresh html')):
            verify_publication(self.root,d)
            d['held_positions'][0]['current_shares']='1'
            with self.assertRaisesRegex(ValueError,'published_shares_differ'):verify_publication(self.root,d)
            d['held_positions'][0]['current_shares']='2'
            self.fixture.put('07_automation/email_briefs/daily_email_brief.html','old html')
            with self.assertRaisesRegex(ValueError,'published_brief_differs'):verify_publication(self.root,d)

    def test_private_route_retry_cannot_adopt_other_service(self):
        config={'TCP':{'443':{'HTTPS':True}},'Web':{'test.example.ts.net:443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8765'}}}}}
        self.assertTrue(our_route(config,'test.example.ts.net'))
        config['TCP']['80']={'HTTP':True}
        self.assertFalse(our_route(config,'test.example.ts.net'))
