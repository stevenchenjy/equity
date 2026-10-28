from datetime import datetime
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from _support import SCRIPT_DIR
import swing_research as common
import swing_outcome_review as reviews


def fixture(root):
    clock = datetime(2026, 10, 5, 14, tzinfo=common.ET)
    observation = {"kind": "observation", "observation_id": "o", "ticker": "TEST", "price_basis": "unadjusted",
                   "bars_at_observation": [{"session_date": "2026-07-15"}]}
    outcome = {"kind": "outcome", "record_hash": "a"*64, "observation_id": "o", "ticker": "TEST",
               "recorded_at": "2026-10-02T17:00:00-04:00", "horizon_sessions": 5,
               "entry_method": "observed_owner_window_mark_not_fill", "window_id": "morning",
               "forward_bars": [{"session_date": "2026-10-02", "close": 99}], "status": "unreviewed_delayed_quote_to_close_price_path",
               "raw_common_price_cost_sensitivity_pct_by_one_way_bps": {"10": -2., "25": -2.3, "50": -2.8}}
    manifest = root/'01_policies/official_news_sources.json';manifest.parent.mkdir(parents=True);manifest.write_text('{"sources":[]}')
    sources=[]
    for i,(host,role) in enumerate([('www.sec.gov','issuer_or_sec_corporate_action_review'),('www.nasdaq.com','independent_exchange_corporate_action_review')]):
        path=Path('03_source_data/equity_research')/f'review-source-{i}.html'
        excerpt=f'Official retained corporate-action evidence body number{i}; this exact excerpt is retained for review.'
        raw=(excerpt+' More issuer/exchange context and dated source coverage for the named review window.'*3).encode()
        (root/path).parent.mkdir(parents=True,exist_ok=True);(root/path).write_bytes(raw)
        sources.append({'path':str(path),'sha256':common._digest(raw),'url':'https://'+host+'/TEST/evidence',
                        'available_at':'2026-10-05T13:00:00-04:00','coverage_from':'2026-07-15','coverage_through':'2026-10-02',
                        'ticker':'TEST','supporting_excerpt':excerpt,'role':role,
                        'coverage_explanation':'The analyst reviewed the complete named signal and forward period against this retained primary body and cross-checked the independent evidence family.'})
    proposal={'schema_version':reviews.SCHEMA,'reviewer':'Research analyst','reviewed_at':clock.isoformat(),
              'ticker':'TEST','observation_id':'o','outcome_record_hash':'a'*64,'horizon_sessions':5,
              'entry_method':outcome['entry_method'],'window_id':'morning','coverage_from':'2026-07-15','coverage_through':'2026-10-02',
              'corporate_action_conclusion':'no_actions_identified_after_source_bound_review','corporate_actions':[],
              'qualifying_method':'source_bound_analyst_review_of_fixed_horizon_price_path_only','sources':sources,
              'reasoning':'The exact issuer and independent exchange evidence were reviewed over the complete signal-history and forward-observation window. No action was identified by that review. This qualifies the negative modeled fixed-horizon price path without changing its original entry, cost assumptions or loss.',
              'limitations':'This is an authored source-bound review, not a mechanical proof of absence. It neither verifies executable fills nor resolves entry-day stop/target ordering.'}
    return clock,[observation,outcome],proposal


class OutcomeReviewTests(unittest.TestCase):
    def test_reviewed_negative_path_preserved_without_strategy_or_capital_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);clock,rows,p=fixture(root)
            with patch('swing_research_v2._load',return_value=rows),patch('swing_research_v2._verify'):
                value=reviews.review(root,p,clock,apply=True)
                self.assertEqual(len(reviews.read_reviews(root,clock)),1)
            self.assertEqual(value['reviewed_price_cost_sensitivity_pct_by_one_way_bps']['25'],-2.3)
            self.assertFalse(value['mechanical_proof_of_no_corporate_actions'])
            self.assertFalse(value['risk_managed_strategy_performance_qualified'])
            self.assertEqual(value['actionable_quantity'],0)

    def test_boolean_only_claim_and_missing_independent_role_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);clock,rows,p=fixture(root)
            with patch('swing_research_v2._load',return_value=rows),patch('swing_research_v2._verify'):
                p['sources'][1]['role']=p['sources'][0]['role']
                with self.assertRaisesRegex(common.SwingResearchError,'independent_(evidence_roles|source_family)'):
                    reviews.review(root,p,clock,apply=True)
            self.assertEqual(len(list((root/reviews.OUTPUT/'failed_reviews').glob('*.json'))),1)
            self.assertFalse((root/reviews.STORE).exists())

    def test_split_and_dividend_adjustments_remain_explicit_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);clock,rows,p=fixture(root)
            with patch('swing_research_v2._load',return_value=rows),patch('swing_research_v2._verify'):
                for event in ({'type':'split','ratio':2},{'type':'cash_dividend','amount':1}):
                    changed=copy.deepcopy(p);changed['corporate_actions']=[event]
                    with self.assertRaisesRegex(common.SwingResearchError,'adjustment_requires_supported_method'):
                        reviews.review(root,changed,clock,apply=True)
            self.assertEqual(len(list((root/reviews.OUTPUT/'failed_reviews').glob('*.json'))),2)

    def test_hash_url_ticker_window_and_future_source_are_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);clock,rows,p=fixture(root)
            changes=[('sha256','0'*64),('url','https://untrusted.example/TEST'),('ticker','OTHER'),
                     ('coverage_from','2026-10-01'),('available_at','2026-10-06T13:00:00-04:00')]
            with patch('swing_research_v2._load',return_value=rows),patch('swing_research_v2._verify'):
                for field,value in changes:
                    changed=copy.deepcopy(p);changed['sources'][0][field]=value
                    with self.subTest(field=field),self.assertRaises(common.SwingResearchError):reviews.validate(root,changed,clock)

    def test_wrong_outcome_or_correction_does_not_qualify(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);clock,rows,p=fixture(root)
            with patch('swing_research_v2._load',return_value=rows),patch('swing_research_v2._verify'):
                changed=copy.deepcopy(p);changed['outcome_record_hash']='b'*64
                with self.assertRaisesRegex(common.SwingResearchError,'immutable_outcome_required'):reviews.validate(root,changed,clock)
                rows[1]['status']='correction_review_required'
                with self.assertRaisesRegex(common.SwingResearchError,'correction_unresolved'):reviews.validate(root,p,clock)

    def test_reapply_deduplicates_and_corrupt_store_is_never_restarted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);clock,rows,p=fixture(root)
            with patch('swing_research_v2._load',return_value=rows),patch('swing_research_v2._verify'):
                reviews.review(root,p,clock,apply=True);before=(root/reviews.STORE).read_bytes()
                reviews.review(root,p,clock,apply=True);self.assertEqual(before,(root/reviews.STORE).read_bytes())
                (root/reviews.STORE).write_bytes(b'corrupt original')
                with self.assertRaises(ValueError):reviews.review(root,p,clock,apply=True)
            self.assertEqual((root/reviews.STORE).read_bytes(),b'corrupt original')


if __name__=='__main__':unittest.main()
