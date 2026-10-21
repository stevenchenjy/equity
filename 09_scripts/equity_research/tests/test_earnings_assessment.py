"""Event review must be dated, substantive and bound to the detected source."""
import copy
import json
import shutil
from datetime import timedelta
import unittest

from _support import SCRIPT_DIR
import test_research_opportunities as support
from test_research_opportunities import NOW, REPO
from daily_common import read_json
from earnings_events import refresh_events, summary
from research_opportunities import intake, read_report
from update_research_assessment import apply_assessment


class EarningsAssessmentTests(unittest.TestCase):
    setUp = support.OpportunityTests.setUp
    tearDown = support.OpportunityTests.tearDown
    discovery = support.OpportunityTests.discovery
    evidence = support.OpportunityTests.evidence
    assessment = support.OpportunityTests.assessment

    def proposal(self):
        shutil.copy2(REPO/'01_policies/earnings_event_policy.json', self.root/'01_policies/earnings_event_policy.json')
        def fetch(day, policy):
            rows = [{'symbol':'SYN','name':'Synthetic event company','time':'time-after-hours',
                     'fiscalQuarterEnding':'Sep/2026'}] if day.isoformat() == '2026-10-05' else []
            return json.dumps({'status':{'rCode':200},'data':{'asOf':day.strftime('%a, %b %d, %Y'),'rows':rows}}).encode()
        refresh_events(self.root, fetcher=fetch, clock=lambda: NOW)
        intake(self.root, current=NOW)
        p = self.assessment('unresolved')
        p['next_review_at'] = (NOW+timedelta(days=1)).isoformat()
        event = summary(self.root, current=NOW)['events'][0]
        p['earnings_event_review'] = {'event_id':event['event_id'],
            'expectations_case':'Consensus is not verified; do not infer a beat from momentum.',
            'priced_in_assessment':'No supported expectations gap has been established.',
            'valuation_case':'Current company-specific event valuation is missing.',
            'downside_case':'Earnings gaps can exceed the planned event-loss allowance.',
            'recheck_condition':'No entry pending issuer confirmation and current expectations, valuation and downside evidence.',
            'sources':event['sources']}
        return p

    def test_source_bound_unresolved_event_review_reaches_final_advice_without_entry(self):
        p = self.proposal()
        apply_assessment(self.root, p, current=NOW, apply=True)
        event = summary(self.root, current=NOW)['events'][0]
        self.assertEqual(event['status'], 'reviewed_without_entry')
        self.assertEqual(event['event_review']['valuation_case'], p['earnings_event_review']['valuation_case'])
        self.assertFalse(event['capital_authority'])
        self.assertNotEqual(event['status'], 'eligible_conditional_plan')

    def test_empty_case_or_unbound_event_cannot_claim_a_review(self):
        p = self.proposal()
        for mutate in (lambda v:v['earnings_event_review'].update(valuation_case=''),
                       lambda v:v['earnings_event_review'].update(event_id='a'*64),
                       lambda v:v['earnings_event_review'].update(sources=p['supporting_points'][0]['sources'])):
            bad=copy.deepcopy(p);mutate(bad)
            with self.assertRaises(ValueError): apply_assessment(self.root,bad,current=NOW)

    def test_review_cannot_be_backdated_or_extend_past_event_deadline(self):
        p = self.proposal()
        for values in ({'assessed_at':(NOW-timedelta(minutes=1)).isoformat()},
                       {'next_review_at':(NOW+timedelta(days=5)).isoformat()}):
            bad=copy.deepcopy(p);bad.update(values)
            with self.assertRaises(ValueError):apply_assessment(self.root,bad,current=NOW)

    def test_same_event_assessment_replay_is_idempotent(self):
        p=self.proposal()
        apply_assessment(self.root,p,current=NOW,apply=True)
        old=read_report(self.root,current=NOW)['journal_head']
        self.assertEqual(apply_assessment(self.root,p,current=NOW,apply=True)['status'],'already_recorded')
        self.assertEqual(old,read_report(self.root,current=NOW)['journal_head'])

    def test_new_review_cannot_be_admitted_after_event_using_an_old_assessment_clock(self):
        p=self.proposal()
        with self.assertRaisesRegex(ValueError,'admitted_after_deadline'):
            apply_assessment(self.root,p,current=NOW+timedelta(days=3),apply=True)
