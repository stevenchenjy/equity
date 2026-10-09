import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from _support import SCRIPT_DIR
from daily_common import ROOT, canonical_sha256
from account_authority import load_authority, POLICY_REL, SCHEMA
import test_capital_decision as capital_tests
from investment_plans import _order_scopes
from workflow_integrity import _account_blockers
from tactical_review import review_open_orders, build_tactical_review
from capital_presentation import cards
import capital_decision
import production_strategies


class LocalAccountAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.base = capital_tests.CapitalDecisionTests('test_eligible_company_exact_order_and_loss')
        self.base.setUp()
        self.v, self.d = self.base.v, self.base.d
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        registry = production_strategies.registry(ROOT)
        paths = {production_strategies.REGISTRY}
        paths.update(p for r in registry['strategies'] for p in r['policy_bindings'])
        for rel in paths:
            dest = self.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dest)
        self.policy = {'schema_version': SCHEMA, 'mode': 'owner_local_ledger',
                       'approved_at': self.v['current'].isoformat(), 'owner_instruction': 'Use local records for conditional manual plans.',
                       'automatic_execution': False, 'broker_observation_claimed': False}
        self.write_policy()
        self.d['account'].update(cash_basis='ledger_estimate', last_updated=(self.v['current']-timedelta(days=7)).isoformat())
        self.v['open_orders'].update(as_of=(self.v['current']-timedelta(days=7)).isoformat(), complete=False, cash_confirmed=False,
                                     existing_tactical_risk_confirmed=False, existing_tactical_risk_usd=None)

    def write_policy(self):
        value = {**self.policy, 'content_sha256': canonical_sha256(self.policy)}
        path = self.root / POLICY_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def build(self):
        self.d['tactical_review'] = build_tactical_review(**self.v, local_authority=load_authority(self.root, self.v['current'])['local_planning_enabled'])
        return capital_decision.build(self.d, root=self.root, current=self.v['current'], config=self.base.config, orders=self.v['open_orders'])

    def test_aged_local_record_supports_exact_draft_without_faking_broker_observation(self):
        before = copy.deepcopy((self.d['account'], self.v['open_orders']))
        c = self.build()
        self.assertEqual(c['global_blockers'], [])
        self.assertEqual(c['decisions'][0]['decision'], 'ACTIONABLE_BUY')
        self.assertEqual(c['decisions'][0]['shares'], 4)
        self.assertEqual(before, (self.d['account'], self.v['open_orders']))
        review = self.d['tactical_review']['open_orders']
        self.assertFalse(review['broker_inventory_verified'])
        self.assertEqual(review['status'], 'owner_local_inventory')
        self.d['capital_decision'] = c
        rendered = cards(self.d)
        self.assertIn('Entry: LIMIT ≤ $102.00', '\n'.join(r['body'] for r in rendered))
        self.assertIn('Account planning basis', [r['title'] for r in rendered])
        self.assertFalse(_account_blockers(self.d, local_authority=True))
        self.assertIn('planning_cash_unverified', _account_blockers(self.d))

    def test_strict_mode_remains_strict_and_approval_cannot_fabricate_verification(self):
        (self.root / POLICY_REL).unlink()
        c = self.build()
        self.assertIn('current_account_snapshot_stale', c['global_blockers'])
        self.assertIn('order_inventory_unverified_cannot_bound_buy_commitments', c['global_blockers'])
        self.assertEqual(c['decisions'][0]['shares'], 0)
        self.policy['broker_observation_claimed'] = True
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'approval_invalid'):
            self.build()

    def test_known_orders_reserve_cash_and_shares_even_when_old(self):
        buy = dict(order_id='known-buy', ticker='OTHER', side='buy', status='pending', quantity=2, remaining_quantity=2,
                   limit_price=100, time_in_force='GTC')
        self.v['open_orders']['orders'] = [buy]
        reviewed = review_open_orders(self.v['open_orders'], self.v['current'], self.v['current'].date(), [], local_authority=True)
        self.assertEqual(reviewed['cash_reservation_usd'], 200)
        self.assertFalse(reviewed['global_blockers'])
        global_codes, _, _ = _order_scopes(self.v['open_orders'], {}, self.v['current'], local_authority=True)
        self.assertFalse(global_codes)
        sell = {**buy, 'order_id':'known-sell', 'side':'sell', 'ticker':'HELD'}
        self.v['open_orders']['orders'] = [sell]
        reviewed = review_open_orders(self.v['open_orders'], self.v['current'], self.v['current'].date(),
                                     [dict(ticker='HELD', current_shares=1)], local_authority=True)
        self.assertIn('sell_reservations_exceed_observed_holdings', reviewed['global_blockers'])
        self.v['open_orders']['orders'] = [buy, buy]
        reviewed = review_open_orders(self.v['open_orders'], self.v['current'], self.v['current'].date(), [], local_authority=True)
        self.assertIn('duplicate_order_identity', reviewed['global_blockers'])
        buy['limit_price'] = None
        self.v['open_orders']['orders'] = [buy]
        reviewed = review_open_orders(self.v['open_orders'], self.v['current'], self.v['current'].date(), [], local_authority=True)
        self.assertIn('buy_commitment_unbounded', reviewed['global_blockers'])

    def test_company_economics_and_real_account_conflicts_still_determine_decision(self):
        self.d['eligible_new_position_review_candidates'] = []
        self.d['watch_candidates'][0]['gate_blockers'] = 'upside,reward_to_risk'
        c = self.build()
        self.assertEqual(c['decisions'][0]['decision'], 'NO_ACTION')
        self.assertEqual(c['decisions'][0]['shares'], 0)
        self.d['account']['cash_available'] = -1
        self.assertIn('shared_account_values_unverified', self.build()['global_blockers'])
        self.d['account_conflicts'] = ['unreconciled owner fill']
        self.assertIn('account_or_execution_conflict', _account_blockers(self.d, local_authority=True))

    def test_risk_zero_is_only_derived_for_local_core_or_empty_inventory(self):
        self.d['held_positions'] = [dict(ticker='SPY', current_shares=2, current_price=500, asset_role='core_allocation')]
        review = build_tactical_review(**self.v, local_authority=True)
        self.assertEqual(review['risk_budget']['open_risk_usd'], 0)
        self.assertEqual(review['risk_budget']['open_risk_basis'], 'derived_local_core_only_inventory')
        self.d['held_positions'][0]['asset_role'] = 'active_stock'
        review = build_tactical_review(**self.v, local_authority=True)
        self.assertIn('existing_tactical_risk_unconfirmed', review['blockers'])
        self.assertIsNone(review['risk_budget']['open_risk_usd'])

    def test_contract_cannot_invent_broker_verification_even_with_recomputed_hash(self):
        c = self.build()
        c['account_authority']['broker_observation_claimed'] = True
        c['content_sha256'] = canonical_sha256({k:v for k,v in c.items() if k != 'content_sha256'})
        with self.assertRaisesRegex(ValueError, 'account_authority_invalid'):
            capital_decision.validate(c, current=self.v['current'], root=self.root)

    def test_private_approval_is_ignored_by_the_actual_repository(self):
        import subprocess
        result = subprocess.run(['git', 'check-ignore', '-q', POLICY_REL], cwd=ROOT)
        self.assertEqual(result.returncode, 0)

    def test_policy_change_invalidates_published_capital_contract(self):
        c = self.build()
        self.policy['owner_instruction'] += ' changed'
        self.write_policy()
        with self.assertRaisesRegex(ValueError, 'inputs_changed'):
            capital_decision.validate(c, current=self.v['current'], root=self.root)
