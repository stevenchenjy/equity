import copy
import unittest
from _support import SCRIPT_DIR
from phase5r_email_brief import render_email
from test_phase5r_owner_review_delivery import owner_review_fixture

class CompactReviewTests(unittest.TestCase):
    def test_compact_keeps_conditions_dates_and_escapes_without_second_report(self):
        d=owner_review_fixture()
        d['owner_requested_research'].update(presentation='compact',formatting_only=True)
        d['owner_requested_research']['sections']=[{'title':'NVDA <review>','body':'Status: Conditional, not cleared.\nEntry: 1 share only after a verified trigger.\nStop: $90; gaps can exceed planned loss.\nExit: Friday or invalidation.','sources':['https://www.chase.com/personal/investments/faqs/self-directed-investing']}]
        original=copy.deepcopy(d)
        subject,plain,html=render_email(d)
        self.assertIn('[Equity] Your trading plan',subject)
        for body in (plain,html):
            self.assertIn('Conditional, not cleared.',body)
            self.assertIn('1 share only after a verified trigger.',body)
            self.assertIn('2026-09-01',body)
            self.assertIn('Formatting update only.',body)
            self.assertNotIn('原定时报告背景',body)
        self.assertIn('NVDA &lt;review&gt;',html)
        self.assertNotIn('NVDA <review>',html)
        self.assertIn('<strong>Stop:</strong>',html)
        self.assertIn('lang="en"',html)
        self.assertEqual(d,original)

    def test_new_research_does_not_claim_formatting_only(self):
        d=owner_review_fixture();d['owner_requested_research']['presentation']='compact'
        for body in render_email(d)[1:]:
            self.assertNotIn('Formatting update only.',body)

    def test_compact_retains_source_validation(self):
        d=owner_review_fixture();d['owner_requested_research']['presentation']='compact'
        d['owner_requested_research']['sections'][0]['sources']=['https://invalid.example/source']
        with self.assertRaisesRegex(ValueError,'source_not_allowed'):
            render_email(d)
