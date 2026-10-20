"""Owner-requested optional pairs stay visible, dated and distinct from orders."""
import copy
import unittest
from datetime import datetime

from _support import SCRIPT_DIR  # noqa: F401
from capital_presentation import optional_rotation_cards
from delivery_followthrough import _displayed_actions
from delivery_continuity import delivery_meaning_key
from email_brief import render_email
from investment_plans import validate_record, append_plan, evaluate_plans
from test_investment_plans import record, ledger, SCHEMA
import test_capital_decision as capital_fixtures


def rotation_plan():
    row = record('SPY', 'broad_core')
    row.update(action='hold', state='maintained', expected_shares=2,
        proposed_change_shares=0, order_draft={}, strategy_horizon='broad_core',
        recorded_at='2026-10-19T21:00:00-04:00', effective_at='2026-10-19T21:00:00-04:00',
        account_observed_at='2026-10-19T20:00:00-04:00',
        review_at='2026-10-20T10:30:00-04:00', valid_until='2026-10-20T10:30:00-04:00',
        instruction='持有记录中的 SPY；配对换仓只按独立的有效行动卡自主决定。')
    row['purpose'] = {key: 'Retain the same approved index-core purpose.' for key in
        ('strategy','holding_period_justification','entry_validity','failure_condition','exit_rule')}
    row['purpose']['sources'] = copy.deepcopy(row['sources'])
    row['conditional_rotation_review'] = dict(optional=True, human_execution_only=True,
        sequence='buy_fully_then_sell', session_date='2026-10-20',
        starts_at='2026-10-20T09:45:00-04:00', ends_at='2026-10-20T10:30:00-04:00',
        buy=dict(ticker='QQQM', quantity=2, maximum_price=292.26),
        sell=dict(ticker='SPY', quantity=1, minimum_price=763.25),
        expected_holdings={'SPY':2,'QQQM':0}, minimum_combined_core_pct=30,
        reference_close='2026-10-16',
        skip_conditions=['价格不好或风险过于激进，就跳过；保留当前持仓。'],
        incomplete_pair_rule='保留真实的中间持仓并复核，不追价，不推定 SPY 已卖出。',
        rationale='这只是可选的指数结构调整，不要求买入 QQQM。', sources=copy.deepcopy(row['sources']))
    return row


def context(row=None, when='2026-10-20T09:35:00-04:00', positions=None, orders=None):
    return evaluate_plans(ledger(row or rotation_plan()), positions or [{'ticker':'SPY','current_shares':2}],
        current=datetime.fromisoformat(when), open_orders=orders or
        {'as_of':'2026-10-20T09:30:00-04:00','complete':True,'orders':[]})


def decision():
    fixture=capital_fixtures.CapitalDecisionTests(); fixture.setUp()
    fixture.v['current']=datetime.fromisoformat('2026-10-20T09:35:00-04:00')
    d=fixture.d
    d.update(generated_at=fixture.v['current'].isoformat(), cycle_date='2026-10-20',
        held_positions=[dict(ticker='SPY',current_shares=2,current_price=763.25,asset_role='core_allocation')],
        eligible_new_position_review_candidates=[],eligible_action_review_candidates=[],watch_candidates=[],
        plan_continuity=context(), allocation_policy=dict(core_tickers=['SPY','QQQM'],core_minimum_pct=30,
        core_weight_pct=38.17,stock_maximum_pct=70))
    d['account'].update(account_total_value=3999.29,cash_available=1553.64,cash_reserved=0,
        last_updated='2026-10-19T20:00:00-04:00')
    d['market_gate']['expected_market_session']='2026-10-19'
    d['capital_decision']=fixture.build()
    return d


class OptionalRotationEmailTests(unittest.TestCase):
    def test_writer_binds_optional_pair_without_making_an_order(self):
        row=rotation_plan(); first=append_plan({'schema_version':SCHEMA,'records':[]},row)
        self.assertEqual(first['records'][0]['version'],1)
        self.assertEqual(first['records'][0]['order_draft'],{})
        self.assertEqual(first['records'][0]['proposed_change_shares'],0)
        changed=copy.deepcopy(row); changed['conditional_rotation_review']['buy']['maximum_price']=290
        second=append_plan(first,changed)
        self.assertEqual(second['records'][0],first['records'][0])
        self.assertNotEqual(second['records'][1]['record_hash'],first['records'][0]['record_hash'])

    def test_invalid_authority_order_sequence_sources_and_expiry_rejected(self):
        for mutation in ('optional','sequence','deadline','source','price','quantity'):
            with self.subTest(mutation=mutation):
                row=rotation_plan(); r=row['conditional_rotation_review']
                if mutation=='optional':r['optional']=False
                if mutation=='sequence':r['sequence']='sell_first'
                if mutation=='deadline':r['ends_at']='2026-10-20T10:45:00-04:00'
                if mutation=='source':r['sources'][0]['sha256']='0'*64
                if mutation=='price':r['buy']['maximum_price']=0
                if mutation=='quantity':r['buy']['quantity']=1.5
                with self.assertRaises(ValueError):validate_record(row)

    def test_final_plain_and_html_put_buy_sell_before_hold_with_skip_rules(self):
        d=decision(); before=copy.deepcopy(d)
        subject,plain,html=render_email(d)
        for text in (plain,html):
            self.assertLess(text.index('可选换仓 · BUY 买入 2 股 QQQM'),text.index('配对第二步 · SELL 卖出 1 股 SPY'))
            self.assertLess(text.index('配对第二步 · SELL 卖出 1 股 SPY'),text.index('HOLD — SPY'))
            self.assertLess(text.index('跳过条件'),text.index('Supporting information'))
            lead=text.split('HOLD — SPY')[0]
            for term in ('$292.26','$763.25','09:45','10:30','全部实际成交','仅部分成交时不卖 SPY','过于激进','不换仓'):
                self.assertIn(term,lead)
            self.assertIn('OTHER BUY — none',lead)
        self.assertIn('data-action-kind="buy"',html)
        self.assertIn('data-action-kind="sell"',html)
        self.assertEqual(d,before)
        self.assertFalse(any(row['order_draft'] for row in d['capital_decision']['decisions']))

    def test_future_preview_is_allowed_but_exact_deadline_and_next_session_are_not(self):
        d=decision()
        for when in ('2026-10-19T22:00:00-04:00','2026-10-20T09:30:00-04:00','2026-10-20T10:29:59-04:00'):
            d['generated_at']=when;self.assertEqual(len(optional_rotation_cards(d)),3)
        for when in ('2026-10-20T10:30:00-04:00','2026-10-20T14:30:00-04:00','2026-10-21T09:30:00-04:00'):
            d['generated_at']=when;self.assertEqual(optional_rotation_cards(d),[])

    def test_recorded_partial_fill_or_order_prevents_duplicate_pair(self):
        changed=context(positions=[{'ticker':'SPY','current_shares':2},{'ticker':'QQQM','current_shares':1}])
        self.assertNotIn('conditional_rotation_review',next(x for x in changed['plans'] if x['ticker']=='SPY'))
        order=dict(ticker='QQQM',order_id='q',status='open',side='buy',quantity=2,remaining_quantity=2,limit_price=292.26)
        changed=context(orders={'as_of':'2026-10-20T09:30:00-04:00','complete':True,'orders':[order]})
        self.assertNotIn('conditional_rotation_review',changed['plans'][0])

    def test_insufficient_cash_changed_holdings_policy_or_real_conflict_hides_pair(self):
        for mutation in ('cash','holdings','policy','conflict'):
            d=decision()
            if mutation=='cash':d['capital_decision']['planning_cash']=100
            if mutation=='holdings':d['held_positions'][0]['current_shares']=1
            if mutation=='policy':d['allocation_policy']['core_tickers']=['SPY']
            if mutation=='conflict':d['workflow_integrity']['global_blockers']=['shared_account_values_unverified']
            self.assertEqual(optional_rotation_cards(d),[])

    def test_optional_review_is_not_assumed_filled_and_plan_change_is_meaningful(self):
        d=decision(); _,plain,html=render_email(d)
        actions,incomplete=_displayed_actions(d,plain,html,datetime.fromisoformat(d['generated_at']))
        self.assertEqual(actions,[]);self.assertFalse(incomplete)
        old=copy.deepcopy(d);old['plan_continuity']['plans'][0]['version']-=1
        old['plan_continuity']['plans'][0]['record_hash']='0'*64
        self.assertNotEqual(delivery_meaning_key(old),delivery_meaning_key(d))


if __name__=='__main__':unittest.main()
