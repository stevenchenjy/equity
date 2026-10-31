"""Attention projection keeps complete orders and removes internal backlog mail."""
from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR, visible_html_text  # noqa: F401
from daily_common import canonical_sha256
from capital_presentation import action_lines
from email_brief import EMAIL_BRIEF_VERSION, render_email
from attention_email import DIRECT_VERSION, cards, direct_action, held_earnings_card
import test_capital_decision as capital_tests
from test_assessment_presentation import envelope
import delivery_followthrough as follow


class AttentionEmailTests(unittest.TestCase):
    def setUp(self):
        # Presentation edits correctly invalidate the source checkout's old
        # strategy bindings. Review exact current bytes only in a temporary
        # registry; never alter production admission to make a fixture pass.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = SCRIPT_DIR.parent.parent
        registry = json.loads((source / '01_policies/production_strategies.json').read_text())
        for strategy in registry['strategies']:
            strategy['policy_bindings']['09_scripts/equity_research/attention_email.py'] = ''
            for relative in strategy['policy_bindings']:
                original = source / relative
                strategy['policy_bindings'][relative] = hashlib.sha256(original.read_bytes()).hexdigest()
                link = self.root / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.exists():
                    link.symlink_to(original)
        registry_path = self.root / '01_policies/production_strategies.json'
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry))
        self.builder = capital_tests.CapitalDecisionTests()
        self.builder.setUp()
        self.decision = self.builder.d
        # These tests retain the historical v4 renderer and archive contract.
        self.decision['email_brief_version'] = 'equity_attention_email_v4'
        self.decision['capital_decision'] = self.build()

    def build(self):
        with patch.object(capital_tests, 'ROOT', self.root):
            return self.builder.build()

    def no_entry(self):
        self.decision['eligible_action_review_candidates'] = []
        self.decision['eligible_new_position_review_candidates'] = []
        self.decision['capital_decision'] = self.build()

    def direct_exit(self):
        self.decision['email_brief_version'] = DIRECT_VERSION
        self.decision['eligible_new_position_review_candidates'] = []
        self.decision['eligible_action_review_candidates'] = []
        self.decision['watch_candidates'] = []
        self.decision['held_positions'] = [dict(ticker='TEST', current_shares=6, current_price=101, asset_role='active_stock')]
        plans = [dict(ticker='TEST', status='maintained', action='trim_review', blockers=['fresh_quote_and_available_shares_required'],
            review_at='2026-09-23T11:15:00-04:00', instruction='Verify a fresh bid at/above103, six recorded shares including pending settlement (P), two sellable shares, no conflicting order and no material issuer news. If the bid is below103, skip; do not lower the limit or chase.',
            reason='Reduce the exposure while retaining participation. ' + 'DETAILED_MODEL_ANALYSIS ' * 60,
            purpose={'failure_condition':'If the issuer announces a customer cancellation, skip and reassess.',
                     'exit_rule':'Cancel any unfilled remainder at11:15EDT; do not carry or automatically reprice.'},
            historical_order_draft={'side':'sell','type':'LIMIT','quantity':2,'limit_price':103,'time_in_force':'DAY',
                                    'session_date':'2026-09-23','starts_at':'2026-09-23T10:05:00-04:00'})]
        for ticker, qty in (('AAA',3),('BBB',7),('CCC',5),('DDD',9)):
            self.decision['held_positions'].append(dict(ticker=ticker,current_shares=qty,current_price=10,asset_role='active_stock'))
            plans.append(dict(ticker=ticker,status='maintained',action='hold',blockers=[],instruction='Keep the recorded shares.',
                              review_at='2026-09-23T15:00:00-04:00'))
        self.decision['plan_continuity'] = {'plans':plans}
        self.decision['delivery_followthrough'] = {'status':'prior_no_specific_order','prior_sent_at':self.decision['generated_at']}
        self.decision['capital_decision'] = self.build()
        return next(row for row in self.decision['capital_decision']['decisions'] if row['ticker']=='TEST')

    def test_v5_first_visible_action_exact_conditions_and_small_email_leave_contract_unchanged(self):
        row = self.direct_exit()
        self.assertIsNotNone(row['order_draft'])
        before = copy.deepcopy(self.decision)
        subject, plain, document = render_email(self.decision)
        visible = visible_html_text(document)
        action = 'SELL 2 TEST — LIMIT ≥ $103.00 · DAY'
        self.assertIn(action, subject)
        self.assertTrue(visible.startswith(action))
        self.assertRegex(document,r'<h1[^>]*>SELL 2 TEST')
        self.assertIn('display:none;max-height:0', document)
        for text in (plain, visible):
            for condition in ('10:05–11:15 EDT','fresh bid at/above 103','pending settlement (P)',
                              'two sellable shares','no conflicting order','no material issuer news',
                              'do not lower the limit or chase','customer cancellation',
                              'Cancel any unfilled remainder at 11:15 EDT','do not carry or automatically reprice',
                              'no downside protection','No fill or spendable proceeds are assumed'):
                self.assertIn(condition,text)
            for omitted in ('DETAILED_MODEL_ANALYSIS','Opportunity shortlist','Candidate outcomes:',
                            'Earlier instructions','Intraday portfolio risk','Supporting information'):
                self.assertNotIn(omitted,text)
            self.assertEqual(text.count('AAA 3 shares'),1)
            self.assertIn('Add 0 / sell 0 for these holdings',text)
        self.assertLess(len(plain.split()),330)
        self.assertEqual(before,self.decision)
        shown,incomplete=follow._displayed_actions(self.decision,plain,document,self.builder.v['current'])
        self.assertFalse(incomplete)
        self.assertEqual([(r['ticker'],r['side'],r['quantity']) for r in shown],[('TEST','sell',2)])
        for bad_plain,bad_html in ((plain.replace('$103.00','$102.00'),document),
                                   (plain,document.replace('customer cancellation','ordinary update'))):
            self.assertEqual(follow._displayed_actions(self.decision,bad_plain,bad_html,self.builder.v['current']),([],True))

    def test_v5_keeps_additional_authored_condition_and_genuine_earlier_order_blocker(self):
        row=self.direct_exit()
        row['order_draft']['cancel_conditions'].append('Skip if a newly announced capital raise changes the case.')
        contract=self.decision['capital_decision']
        contract['content_sha256']=canonical_sha256({k:v for k,v in contract.items() if k!='content_sha256'})
        _,plain,document=render_email(self.decision)
        for body in (plain,visible_html_text(document)):
            self.assertIn('Skip if a newly announced capital raise changes the case.',body)
        self.decision['delivery_followthrough']={'status':'conditional_execution_followthrough','requires_reconciliation':True,'actions':[]}
        _,plain,_=render_email(self.decision)
        self.assertIn('Earlier order — reconcile before replacing',plain)
        self.assertIn('not a verified order or fill',plain)

    def test_v5_receipt_archive_accepts_complete_projection_and_rejects_missing_critical_line(self):
        self.direct_exit()
        import delivery_assessments as assessments
        from daily_common import atomic_write_json
        subject,plain,document=render_email(self.decision)
        archive=self.root/assessments.ARCHIVE_REL;archive.mkdir(parents=True,exist_ok=True)
        raw=json.dumps(self.decision).encode();digest=hashlib.sha256(raw).hexdigest()
        (archive/(digest+'.json')).write_bytes(raw)
        def receipt(text):
            text_digest=hashlib.sha256(text.encode()).hexdigest();html_digest=hashlib.sha256(document.encode()).hexdigest()
            (archive/(text_digest+'.txt')).write_text(text);(archive/(html_digest+'.html')).write_text(document)
            return {'decision_sha256':digest,'brief_text_sha256':text_digest,'brief_html_sha256':html_digest}
        with patch.object(assessments,'advice_projection',return_value={'actions':[{'ticker':'TEST'}],'priority':[]}):
            self.assertEqual(assessments._archived_receipt_baseline(receipt(plain),root=self.root)['status'],'verified')
            self.assertEqual(assessments._archived_receipt_baseline(receipt(plain.replace('customer cancellation','ordinary update')),root=self.root)['status'],'unverified')

    def test_v5_buy_keeps_exact_risk_target_time_exit_and_conditions_without_model_dump(self):
        self.decision['email_brief_version']=DIRECT_VERSION
        row=self.decision['capital_decision']['decisions'][0]
        row['thesis_summary']='MODEL_ESSAY '*200
        contract=self.decision['capital_decision']
        contract['content_sha256']=canonical_sha256({k:v for k,v in contract.items() if k!='content_sha256'})
        subject,plain,document=render_email(self.decision)
        draft=row['order_draft']
        self.assertIn('BUY 4 TEST — LIMIT ≤ $102.00 · DAY',subject)
        self.assertTrue(visible_html_text(document).startswith('BUY 4 TEST'))
        for body in (plain,visible_html_text(document)):
            self.assertIn('invalidate $98.00; planned loss $16.00 (0.16%)',body)
            self.assertIn(f"Target / review: ${draft['initial_reassessment_price']:.2f}",body)
            self.assertIn(draft['trigger_rule'],body)
            self.assertIn(draft['invalidation_rule'],' '.join(body.split()))
            self.assertIn(draft['reassessment_rule'],' '.join(body.split()))
            for value in draft['cancel_conditions']:
                self.assertIn(value,body)
            for omitted in ('MODEL_ESSAY','Capital: approximately','weight 0.00%','Cash: $'):
                self.assertNotIn(omitted,body)
        shown,incomplete=follow._displayed_actions(self.decision,plain,document,self.builder.v['current'])
        self.assertFalse(incomplete);self.assertEqual(shown[0]['quantity'],4)

    def test_v5_stop_and_marketable_limit_headers_keep_trigger_and_cancellation(self):
        for kind in ('STOP','MARKETABLE_LIMIT'):
            self.direct_exit()
            plan=self.decision['plan_continuity']['plans'][0]
            raw=plan['historical_order_draft'];raw['type']=kind
            if kind=='STOP':raw['stop_price']=99;raw.pop('limit_price')
            self.decision['capital_decision']=self.build()
            row=next(r for r in self.decision['capital_decision']['decisions'] if r['ticker']=='TEST')
            self.assertIsNotNone(row['order_draft'])
            title,required=direct_action(self.decision,row)
            self.assertIn('SELL 2 TEST — '+kind,title)
            self.assertIn('≤ $99.00' if kind=='STOP' else '≥ $103.00',title)
            _,plain,document=render_email(self.decision)
            self.assertTrue(visible_html_text(document).startswith(title))
            self.assertIn('stop can gap' if kind=='STOP' else 'sell limit gives no downside protection',plain)
            self.assertIn('customer cancellation',plain)
            self.assertIn('11:15 EDT',plain)
            self.assertFalse(follow._displayed_actions(self.decision,plain,document,self.builder.v['current'])[1])

    def test_v5_owner_review_and_changed_action_alert_share_direct_projection_only_for_shown_actions(self):
        self.direct_exit()
        self.decision['owner_requested_research']={'mode':'explicit_one_off_research',
            'decision_fingerprint':'synthetic-bound-review','presentation':'compact',
            'sections':[{'title':'LONG_OWNER_CASE','body':'OWNER_MODEL_ESSAY '*80,'sources':[]}]}
        self.decision['decision_fingerprint']='synthetic-bound-review'
        subject,plain,document=render_email(self.decision)
        self.assertIn('SELL 2 TEST',subject)
        self.assertTrue(visible_html_text(document).startswith('SELL 2 TEST'))
        self.assertNotIn('OWNER_MODEL_ESSAY',plain)
        self.assertFalse(follow._displayed_actions(self.decision,plain,document,self.builder.v['current'])[1])
        self.decision.pop('owner_requested_research')
        alert=envelope(self.decision,changed=['TEST'],priority=False)
        subject,plain,document=render_email(alert)
        self.assertIn('SELL 2 TEST',subject)
        self.assertTrue(visible_html_text(document).startswith('SELL 2 TEST'))
        self.assertNotIn('Capital: approximately',plain)
        shown,incomplete=follow._displayed_actions(alert,plain,document,self.builder.v['current'])
        self.assertFalse(incomplete);self.assertEqual([r['ticker'] for r in shown],['TEST'])
        self.assertEqual(follow._displayed_actions(alert,plain.replace('customer cancellation','ordinary update'),document,self.builder.v['current']),([],True))
        self.decision['analyst_priority_review']={'status':'current','entries':[{'ticker':ticker,
            'reason':'The issuer reported a new contract.','next_step':'Verify collections before completing the model.'}
            for ticker in ('CASE','OTHER')]}
        priority_only=envelope(self.decision,priority=True)
        _,plain,document=render_email(priority_only)
        self.assertNotIn('SELL 2 TEST',plain)
        self.assertIn('No new or repeated trading instruction',plain)
        for entry in self.decision['analyst_priority_review']['entries']:
            self.assertIn('Research priority — '+entry['ticker'],plain)
            self.assertIn(entry['reason'],plain);self.assertIn(entry['next_step'],plain)
        self.assertEqual(follow._displayed_actions(priority_only,plain,document,self.builder.v['current']),([],False))

    def test_v5_owner_review_validates_current_followthrough_while_legacy_appendix_bypass_stays(self):
        self.direct_exit()
        self.decision['owner_requested_research']={'presentation':'compact'}
        self.decision['delivery_followthrough']={'as_of':self.decision['generated_at'],'status':'prior_no_specific_order'}
        with patch.object(follow,'build_followthrough',return_value={'status':'changed'}) as reader:
            with self.assertRaisesRegex(ValueError,'delivery_followthrough_recompose_required'):
                follow.validate_followthrough(self.decision,root=self.root,current=self.builder.v['current'])
            reader.assert_called_once()
        self.decision['email_brief_version']='equity_attention_email_v4'
        with patch.object(follow,'build_followthrough') as reader:
            follow.validate_followthrough(self.decision,root=self.root,current=self.builder.v['current'])
            reader.assert_not_called()

    def test_v5_paired_rotation_keeps_sequence_and_genuine_risk_while_empty_monitor_is_omitted(self):
        self.no_entry();self.decision['email_brief_version']=DIRECT_VERSION
        rotations=[{'title':'OPTIONAL BUY 3 SYN','body':'Buy all3 first; only then consider selling the pair. Skip a partial fill.',
                    'headline':'LIMIT ≤ $17.00','kind':'buy','group':'action','sources':[]},
                   {'title':'PAIRED SELL 2 OLD','body':'Never sell before the full buy fills. Deadline tomorrow; no extension.',
                    'headline':'LIMIT ≥ $26.00','kind':'sell','group':'action','sources':[]}]
        self.decision['intraday_portfolio_risk']={'schema_version':'intraday_portfolio_risk_v1','status':'unavailable',
            'plan_conditions':[{'ticker':'SYN','status':'triggered','condition':'Current plan support failed; reassess.'}]}
        with patch('attention_email.optional_rotation_cards',return_value=rotations):
            subject,plain,document=render_email(self.decision)
        self.assertIn('OPTIONAL BUY 3 SYN',subject)
        self.assertTrue(visible_html_text(document).startswith('OPTIONAL BUY 3 SYN'))
        self.assertIn(rotations[0]['body'],plain);self.assertIn(rotations[1]['body'],plain)
        self.assertIn('Current plan support failed; reassess.',plain)
        self.assertNotIn('Observation status: unavailable',plain)

    def test_complete_real_engine_buy_draft_survives_both_bodies_and_archive_admission(self):
        row = self.decision['capital_decision']['decisions'][0]
        before = copy.deepcopy(self.decision)
        subject, plain, document = render_email(self.decision)
        visible = html.unescape(re.sub(r'<[^>]+>', '', document))
        self.assertIn('Conditional action', subject)
        for line in action_lines(row):
            self.assertIn(line, plain)
            self.assertIn(' '.join(line.split()), ' '.join(visible.split()))
        shown, incomplete = follow._displayed_actions(self.decision, plain, document, self.builder.v['current'])
        self.assertFalse(incomplete)
        self.assertEqual([(r['ticker'], r['side'], r['quantity']) for r in shown], [('TEST', 'buy', 4)])
        self.assertEqual(self.decision, before)

    def test_large_unfinished_queue_is_counted_not_promoted_or_dumped(self):
        self.decision['long_horizon_research'] = {}
        self.decision['capital_decision'] = self.build()
        contract = self.decision['capital_decision']
        row = contract['decisions'][0]
        self.assertEqual(row['decision'], 'BLOCKED')
        contract['decisions'] += [{**copy.deepcopy(row), 'ticker': 'PENDING' + str(i),
            'reasons': ['UNFINISHED_DOSSIER ' * 200]} for i in range(42)]
        contract['content_sha256'] = canonical_sha256({k:v for k,v in contract.items() if k != 'content_sha256'})
        self.decision['research_opportunities'] = {'raw_queue': ['RAW_QUEUE_ITEM' * 100] * 50}
        subject, plain, document = render_email(self.decision)
        self.assertIn('No new trade', subject)
        self.assertNotIn('Action plan', subject)
        for body in (plain, document):
            self.assertNotIn('UNFINISHED_DOSSIER', body)
            self.assertNotIn('RAW_QUEUE_ITEM', body)
            self.assertNotIn('Candidate decisions — research detail', body)
            self.assertIn('43 need evidence', body)
            self.assertIn('No current source-bound analyst shortlist', body)
        self.assertLess(len(plain), 4000)

    def test_only_current_authored_priority_order_is_listed_and_bounded(self):
        self.no_entry()
        self.decision['analyst_priority_review'] = {'schema_version':'equity_priority_review_context_v1',
            'status':'current', 'reviewed_at':self.decision['generated_at'], 'next_review_at':'2026-09-23T15:00:00-04:00',
            'entries':[{'ticker':ticker, 'reason':'A reviewed operating change changes the downside case.',
                        'next_step':'Verify collected cash and update the current allocation case.',
                        'sources':[{'source_url':'https://www.sec.gov/Archives/edgar/data/1/report.htm'}]}
                       for ticker in ('CASEA','CASEB','CASEC','CASED')]}
        subject, plain, _ = render_email(self.decision)
        self.assertIn('Company attention', subject)
        self.assertLess(plain.index('1. CASEA'), plain.index('2. CASEB'))
        self.assertIn('3. CASEC', plain)
        self.assertNotIn('CASED', plain)
        self.assertIn('Decisive next step:', plain)
        self.assertIn('not a cleared buy', plain)
        self.decision['analyst_priority_review']['status'] = 'inputs_changed'
        subject, plain, _ = render_email(self.decision)
        self.assertIn('No new trade', subject)
        self.assertNotIn('CASEA', plain)

    def test_material_global_failure_remains_prominent_with_no_synthetic_order(self):
        self.decision['workflow_integrity']['global_blockers'] = ['unrecorded_account_change']
        self.decision['capital_decision'] = self.build()
        _, plain, document = render_email(self.decision)
        self.assertIn('Required before any new trade', plain)
        self.assertIn('account', plain.lower())
        self.assertNotIn('Entry: LIMIT', plain)
        self.assertNotIn('BUY — TEST', document)

    def test_adverse_undrafted_exit_cannot_be_hidden_as_routine_hold(self):
        self.no_entry()
        c = self.decision['capital_decision']
        row = c['decisions'][0]
        row.update(decision='EXIT_REVIEW', reasons=['Verified loss of the sole customer requires immediate exit assessment.'])
        c['content_sha256'] = canonical_sha256({k:v for k,v in c.items() if k != 'content_sha256'})
        sections = cards(self.decision)
        exit_card = next(s for s in sections if s['title'] == 'EXIT REVIEW — TEST')
        self.assertEqual(exit_card['group'], 'action')
        self.assertEqual(exit_card['kind'], 'sell')
        _, plain, _ = render_email(self.decision)
        self.assertLess(plain.index('EXIT REVIEW — TEST'), plain.index('Opportunity shortlist'))
        self.assertIn(row['reasons'][0], plain)
        self.assertNotIn('Entry: LIMIT', plain)

    def test_independent_complete_exit_is_not_contradicted_by_source_limitation_banner(self):
        self.decision['eligible_new_position_review_candidates'] = []
        self.decision['watch_candidates'] = []
        self.decision['held_positions'] = [dict(ticker='TEST', current_shares=2, current_price=101, asset_role='active_stock')]
        self.decision['plan_continuity'] = {'plans':[dict(ticker='TEST', status='maintained', action='sell_review',
            blockers=['fresh_quote_and_available_shares_required'], review_at='2026-09-23T15:30:00-04:00',
            instruction='Reassess the complete two-share conditional exit; no order is submitted.',
            reason='Maintained sourced thesis exit', historical_order_draft={'side':'sell','type':'LIMIT',
            'quantity':2,'limit_price':102,'time_in_force':'DAY','session_date':'2026-09-23'})]}
        self.decision['evidence_gate']['passed'] = False
        self.decision['capital_decision'] = self.build()
        row = self.decision['capital_decision']['decisions'][0]
        self.assertEqual(row['decision'], 'EXIT_REVIEW')
        self.assertIsNotNone(row['order_draft'])
        _, plain, document = render_email(self.decision)
        self.assertIn('separately admitted sell/protection draft', plain)
        self.assertNotIn('No new order is approved', plain)
        for line in action_lines(row):
            self.assertIn(line, plain)
        self.assertIn('data-action-kind="sell"', document)

    def test_mixed_buy_and_unchanged_holding_zero_is_scoped_to_existing_holding(self):
        self.decision['held_positions'] = [dict(ticker='SPY', current_shares=2, current_price=100, asset_role='core_allocation')]
        self.decision['plan_continuity'] = {'plans':[dict(ticker='SPY', status='maintained', action='hold',
            instruction='Retain the two recorded index shares', blockers=[],
            review_at='2026-09-23T15:30:00-04:00', valid_until='2026-09-23T16:00:00-04:00')]}
        self.decision['capital_decision'] = self.build()
        self.assertTrue(any(r.get('order_draft') for r in self.decision['capital_decision']['decisions']))
        _, plain, _ = render_email(self.decision)
        self.assertIn('BUY — TEST', plain)
        self.assertIn('For these holdings only: add 0 / sell 0', plain)
        self.assertIn('Separate action cards govern any other ticker', plain)
        self.assertIn('SPY 2 recorded shares', plain)

    def test_skip_only_rotation_is_no_new_trade_not_positive_rotation_subject(self):
        self.no_entry()
        skip = {'title':'Skip the rotation', 'body':'Prices fail the fixed limits.', 'kind':'inactive', 'group':'action', 'sources':[]}
        with patch('attention_email.optional_rotation_cards', return_value=[skip]):
            subject, plain, _ = render_email(self.decision)
        self.assertIn('No new trade', subject)
        self.assertIn('Skip the rotation', plain)
        self.assertNotIn('Read the complete conditional drafts', plain)

    def test_held_completed_negative_is_no_action_not_unfinished_company_research(self):
        self.no_entry()
        self.decision['held_positions'] = [dict(ticker='TEST', current_shares=1, current_price=101, asset_role='active_stock')]
        c = self.decision['capital_decision']
        row = c['decisions'][0]
        row.update(decision='NO_ACTION', reasons=['Completed current company review: the observed price fails the unchanged valuation test.'],
                   research_case={'review_status':'current', 'business_case_status':'mixed', 'valuation_readiness':'reviewed_scenarios'})
        c['content_sha256'] = canonical_sha256({k:v for k,v in c.items() if k != 'content_sha256'})
        _, plain, document = render_email(self.decision)
        visible = html.unescape(re.sub(r'<[^>]+>', '', document))
        for body in (plain, visible):
            self.assertIn('No additional action — TEST', body)
            self.assertIn(row['reasons'][0], body)
            self.assertNotIn('Holding decision incomplete — TEST', body)
            self.assertNotIn('BUY — TEST', body)

    def test_only_three_nearest_current_or_future_held_catalysts_keep_uncertainty_and_deadlines(self):
        self.no_entry()
        self.decision['held_positions'] = [{'ticker':ticker,'current_shares':1} for ticker in ('MSFT','AMZN','NVDA','FOUR','OLD')]
        self.decision['generated_at'] = '2026-10-27T15:50:00-04:00'
        def event(ticker, day, **extra):
            return {'ticker':ticker,'event_date':day,'timing':'pre_event','status':'reviewed_without_entry',
                    'date_confidence':'exchange_calendar_estimate','event_at':None,'session':'after_close',
                    'research_deadline_at':day+'T16:00:00-04:00','blockers':[],
                    'sources':[{'source_url':'https://api.nasdaq.com/api/calendar/earnings?date='+day}], **extra}
        self.decision['earnings_events'] = {'schema_version':'equity_earnings_event_view_v1','status':'ready',
            'events':[event('UNHELD'+str(i),'2026-10-27') for i in range(80)] + [
                event('OLD','2026-10-26'),
                event('MSFT','2026-10-28',status='review_due',blockers=['earnings_event_review_due']),
                event('AMZN','2026-10-29'),
                event('NVDA','2026-10-30',date_confidence='issuer_confirmed',event_at='2026-10-30T17:00:00-04:00'),
                event('FOUR','2026-11-01'),
                event('OLD','2026-10-27',event_at='2026-10-27T09:00:00-04:00'),
            ]}
        before = copy.deepcopy(self.decision)
        card = held_earnings_card(self.decision)
        self.assertEqual(card['group'], 'attention')
        self.assertIn('MSFT: 2026-10-28; exact event time unverified', card['body'])
        self.assertIn('AMZN: 2026-10-29', card['body'])
        self.assertIn('NVDA: 2026-10-30; recorded event time 2026-10-30T17:00:00-04:00', card['body'])
        self.assertIn('date confidence: exchange calendar estimate', card['body'])
        self.assertIn('Research state: review due; recheck due', card['body'])
        self.assertIn('Research deadline: 2026-10-28T16:00:00-04:00', card['body'])
        for absent in ('UNHELD','OLD:','FOUR:'):
            self.assertNotIn(absent, card['body'])
        self.assertEqual(len(card['sources']), 3)
        self.assertLess(len(card['body']), 2000)
        self.assertNotIn('Entry: LIMIT', card['body'])
        self.assertEqual(before, self.decision)

    def test_held_event_warning_keeps_only_safe_retained_links_without_inventing_schedule(self):
        self.decision['held_positions'] = [{'ticker':'MSFT','current_shares':1}]
        self.decision['earnings_events'] = {'schema_version':'equity_earnings_event_view_v1','events':[
            {'ticker':'MSFT','event_date':'2026-09-23','status':'detected','date_confidence':'exchange_calendar_estimate',
             'sources':[{'source_url':'javascript:alert(1)'},{'source_url':'https://user:secret@example.test/private'},
                        {'source_url':'https://www.sec.gov/Archives/report.htm'}]}]}
        card = held_earnings_card(self.decision)
        self.assertIn('exact event time unverified', card['body'])
        self.assertIn('Research deadline: unverified', card['body'])
        self.assertEqual(card['sources'], ['https://www.sec.gov/Archives/report.htm'])

    def test_unknown_held_event_date_remains_an_explicit_timing_dependency(self):
        self.decision['held_positions'] = [{'ticker':'MSFT','current_shares':1}]
        self.decision['earnings_events'] = {'schema_version':'equity_earnings_event_view_v1','events':[
            {'ticker':'MSFT','event_date':None,'status':'schedule_conflict','event_at':None,
             'research_deadline_at':'2026-09-23T16:00:00-04:00'}]}
        card = held_earnings_card(self.decision)
        self.assertIn('Timing dependency: MSFT — event date/time unverified', card['body'])
        self.assertIn('2026-09-23T16:00:00-04:00', card['body'])
        self.assertNotIn('no event', card['body'].lower())

    def test_known_and_unknown_held_events_share_the_three_named_event_budget(self):
        self.decision['held_positions'] = [{'ticker':ticker,'current_shares':1} for ticker in ('ONE','TWO','THREE','UNKONE','UNKTWO','UNKTHREE')]
        known = [{'ticker':ticker,'event_date':'2026-09-23','status':'detected'} for ticker in ('ONE','TWO','THREE')]
        unknown = [{'ticker':ticker,'event_date':None,'status':'schedule_conflict'} for ticker in ('UNKONE','UNKTWO','UNKTHREE')]
        self.decision['earnings_events'] = {'schema_version':'equity_earnings_event_view_v1','events':known+unknown}
        card = held_earnings_card(self.decision)
        for ticker in ('ONE','TWO','THREE'):
            self.assertIn(ticker+': 2026-09-23', card['body'])
        for ticker in ('UNKONE','UNKTWO','UNKTHREE'):
            self.assertNotIn(ticker, card['body'])
        self.assertIn('Additional unresolved held-event timing records: 3', card['body'])

    def test_v4_alert_uses_shared_shell_and_preserves_withdrawal(self):
        alert = envelope(self.decision, removed=['OLD'], priority=False)
        subject, plain, document = render_email(alert)
        self.assertIn('Action update', subject)
        self.assertIn('OLD — previous eligible instruction withdrawn; do not resubmit its earlier quantity.', plain)
        self.assertIn('max-width:600px', document)
        self.assertNotIn('BUY — TEST', plain)

    def test_v4_changed_action_alert_preserves_every_exact_condition_for_followthrough(self):
        alert = envelope(self.decision, changed=['TEST'], priority=False)
        _, plain, document = render_email(alert)
        for line in action_lines(self.decision['capital_decision']['decisions'][0]):
            self.assertIn(line, plain)
        shown, incomplete = follow._displayed_actions(alert, plain, document, self.builder.v['current'])
        self.assertFalse(incomplete)
        self.assertEqual([(r['ticker'], r['side'], r['quantity']) for r in shown], [('TEST', 'buy', 4)])

    def test_v3_alert_keeps_historical_renderer(self):
        self.decision['email_brief_version'] = 'equity_action_email_v3'
        alert = envelope(self.decision, changed=['TEST'], priority=False)
        _, plain, document = render_email(alert)
        self.assertTrue(document.startswith('<html><body>'))
        self.assertNotIn('max-width:600px', document)
        shown, incomplete = follow._displayed_actions(alert, plain, document, self.builder.v['current'])
        self.assertFalse(incomplete)
        self.assertEqual(len(shown), 1)


if __name__ == '__main__':
    unittest.main()
