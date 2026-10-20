from copy import deepcopy
import unittest

from company_research_presentation import reasoning_view, case_lines
from investment_reasoning import research_method_template


class ResearchReasoningPresentationTests(unittest.TestCase):
    def record(self):
        method = research_method_template()
        method['authored_at'] = '2026-10-19T20:00:00-04:00'
        return {'reviewed_at': '2026-10-19T08:00:00-04:00', 'research_method': method}

    def test_legacy_record_does_not_fabricate_analysis(self):
        self.assertIsNone(reasoning_view({'reviewed_at': '2026-10-19T08:00:00-04:00'}))

    def test_unknown_consensus_and_analysis_remain_unknown(self):
        record = self.record()
        before = deepcopy(record)
        view = reasoning_view(record)
        self.assertEqual(record, before)
        self.assertFalse(view['automatic_action_allowed'])
        self.assertEqual(view['authored_at'], record['research_method']['authored_at'])
        self.assertTrue(any(line.startswith('市场共识未知：') for line in view['lines']))
        self.assertTrue(any(line.startswith('差异化判断待完成：') for line in view['lines']))
        self.assertFalse(any('$' in line for line in view['lines']))

    def test_dated_conditions_remain_dated_in_reopened_case_without_new_order(self):
        record = self.record()
        price = record['research_method']['price_implied_conditions']
        price.update(status='assessed', reference_price={'value': '100.0', 'date': '2026-10-16'},
                     summary='Conditional earnings, not a consensus observation.')
        reasoning = reasoning_view(record)
        case = {'conclusion': 'Original thesis preserved', 'review_status': 'reassessment_required',
                'reference_price': None, 'scenario_prices': None, 'method': 'Existing model',
                'horizon': 'One fiscal year', 'countercase': 'Cash conversion may weaken',
                'next_review_at': '2026-10-20T10:30:00-04:00', 'review_conditions': [],
                'model_admission_status': 'research_model_unverified', 'pending_requirements': [],
                'research_reasoning': reasoning}
        before = deepcopy(case)
        lines = case_lines(case, shares=0)
        self.assertEqual(case, before)
        self.assertIn('历史判断', lines[0])
        self.assertTrue(any('0 股' in line for line in lines))
        self.assertEqual(sum('2026-10-16 · $100.00' in line for line in lines), 1)
        self.assertEqual(sum(line == reasoning['lines'][0] for line in lines), 1)
        self.assertFalse(any('当前价格 $100' in line for line in lines))


if __name__ == '__main__':
    unittest.main()
