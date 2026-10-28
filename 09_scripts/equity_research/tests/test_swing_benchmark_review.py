"""Genuine temp-store review admission, with explicitly synthetic evidence."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import unittest

import test_swing_benchmarks as fixtures
import swing_benchmarks as benchmark
import swing_benchmark_review as review
import swing_research as common
import swing_research_v2 as study


class BenchmarkForwardReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.MatchedBenchmarkTests("test_future_open_both_benchmarks_same_dates_costs_and_unique_denominators")
        self.fixture.setUp();self.root=self.fixture.root
        self.fixture._capture();self.rows=self.fixture._mature()
        self.clock=self.fixture.future+timedelta(minutes=5)
        view=benchmark.build(self.root,self.clock,capture=True)
        self.assertEqual(view["status"],"raw_comparisons_available",view)
        comparisons,_=benchmark._comparison_ledger(self.root,self.clock)
        self.record=next(row for row in comparisons if row["benchmark"]=="SPY")
        self.proposal=self._proposal(self.record)

    def tearDown(self):self.fixture.tearDown()

    def _proposal(self,record):
        manifest=self.root/"01_policies/official_news_sources.json";manifest.write_text('{"sources":[]}')
        sources=[]
        for index,(host,role) in enumerate((("www.sec.gov","issuer_or_sec_corporate_action_review"),("www.nasdaq.com","independent_exchange_corporate_action_review"))):
            path=Path("03_source_data/equity_research")/f"synthetic-forward-review-{index}.html"
            excerpt="Synthetic ETF evidence states a distribution before this forward review window and no action identified inside the specified future path."
            body=(excerpt+" Synthetic historical cash distribution effective2026-08-28, outside reviewed2026-09-23 through2026-09-29. Explicit synthetic analyst coverage fixture only."*3).encode()
            (self.root/path).write_bytes(body)
            sources.append({"path":str(path),"sha256":common._digest(body),"url":f"https://{host}/SPY/synthetic-forward-review","available_at":self.clock.isoformat(),"coverage_from":record["entry_session"],"coverage_through":record["exit_session"],"ticker":"SPY","supporting_excerpt":excerpt,"role":role,"coverage_explanation":"This authored synthetic review covers only the complete named future entry-to-exit interval. A prior distribution outside this window is acknowledged and does not assert that the original stock setup history has no actions."})
        return {"schema_version":review.SCHEMA,"comparison_id":record["comparison_id"],"comparison_record_hash":record["record_hash"],"benchmark":"SPY","protocol_sha256":record["protocol_sha256"],"benchmark_forward_bars_sha256":common._hash(record["benchmark_forward_bars"]),"pair_source":record["pair_source"],"reviewer":"Synthetic independent analyst","reviewed_at":self.clock.isoformat(),"coverage_from":record["entry_session"],"coverage_through":record["exit_session"],"sources":sources,"corporate_actions":[],"corporate_action_conclusion":"no_actions_identified_after_source_bound_forward_review","qualifying_method":"source_bound_analyst_review_of_benchmark_forward_price_path_only","reasoning":"The retained synthetic issuer/SEC and exchange evidence were independently reviewed for the exact original forward entry and exit interval. The prior distribution is outside this interval. No forward action was identified by this authored review; original paired prices, costs and all source hashes remain unchanged.","limitations":"Synthetic fixture only. The review does not clear the stock signal history, prove absence mechanically, verify execution, adjust distributions or establish managed strategy profitability."}

    def test_prior_outside_window_distribution_does_not_block_forward_review_or_clear_stock(self):
        ledger=(self.root/study.OUTPUT/"ledger.jsonl").read_bytes()
        value=review.review(self.root,self.proposal,self.clock,apply=True)
        self.assertEqual(value["coverage_from"],"2026-09-23")
        self.assertFalse(value["original_stock_setup_history_cleared"])
        self.assertTrue(value["stock_leg_review_still_required"])
        self.assertFalse(value["capital_authority"])
        view=benchmark.build(self.root,self.clock)
        self.assertEqual(view["summary"]["reviewed_pairs"],0)
        stock=next(row for row in self.rows if row["kind"]=="outcome" and row["ticker"]=="MSFT")
        self.fixture._review(stock,self.clock)
        view=benchmark.build(self.root,self.clock,capture=True)
        self.assertEqual(view["summary"]["reviewed_pairs"],1)
        self.assertEqual(view["summary"]["raw_pairs"],1)
        self.assertEqual(view["summary"]["qualified_strategy_paths"],0)
        self.assertEqual((self.root/study.OUTPUT/"ledger.jsonl").read_bytes(),ledger)
        self.assertEqual(len(review.read_reviews(self.root,self.clock)),1)

    def test_exact_comparison_protocol_path_and_pair_source_required(self):
        changes=(("comparison_id","a"*64),("comparison_record_hash","b"*64),("benchmark","QQQM"),("protocol_sha256","c"*64),("benchmark_forward_bars_sha256","d"*64),("pair_source",{"path":"invented.json","sha256":"e"*64}))
        for key,value in changes:
            changed=copy.deepcopy(self.proposal);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):review.review(self.root,changed,self.clock,apply=True)
        self.assertEqual(len(list((self.root/review.OUTPUT/"failed_forward_reviews").glob("*.json"))),len(changes))
        self.assertFalse((self.root/review.STORE).exists())

    def test_forward_dividend_and_split_remain_dependencies_without_adjustments(self):
        for action in ({"type":"cash_dividend","amount":1.},{"type":"split","ratio":2}):
            changed=copy.deepcopy(self.proposal);changed["corporate_actions"]=[action]
            with self.assertRaisesRegex(ValueError,"forward_split_distribution_adjustment"):
                review.review(self.root,changed,self.clock,apply=True)
        self.assertFalse((self.root/review.STORE).exists())

    def test_source_corruption_role_window_future_clock_fail_and_original_is_preserved(self):
        review.review(self.root,self.proposal,self.clock,apply=True)
        before=(self.root/review.STORE).read_bytes()
        source=self.root/self.proposal["sources"][0]["path"]
        source.write_bytes(b"preserved synthetic corrupted original official source")
        with self.assertRaisesRegex(ValueError,"primary_source_unverified"):
            review.read_reviews(self.root,self.clock+timedelta(minutes=1))
        self.assertEqual((self.root/review.STORE).read_bytes(),before)
        self.assertEqual(source.read_bytes(),b"preserved synthetic corrupted original official source")

    def test_incomplete_window_boolean_claim_and_missing_independence_rejected(self):
        changes=[]
        value=copy.deepcopy(self.proposal);value["coverage_from"]="2026-09-24";changes.append(value)
        value=copy.deepcopy(self.proposal);value["reviewed_at"]=(self.clock+timedelta(minutes=1)).isoformat();changes.append(value)
        value=copy.deepcopy(self.proposal);value["sources"][1]["role"]=value["sources"][0]["role"];changes.append(value)
        value=copy.deepcopy(self.proposal);value["sources"][0]["available_at"]=(self.clock+timedelta(minutes=1)).isoformat();changes.append(value)
        value=copy.deepcopy(self.proposal);value["corporate_action_conclusion"]=True;changes.append(value)
        for value in changes:
            with self.subTest(proposal=value),self.assertRaises(ValueError):review.validate(self.root,value,self.clock)

    def test_deduplicate_and_never_restart_corrupt_review_history(self):
        review.review(self.root,self.proposal,self.clock,apply=True)
        before=(self.root/review.STORE).read_bytes()
        review.review(self.root,self.proposal,self.clock,apply=True)
        self.assertEqual((self.root/review.STORE).read_bytes(),before)
        (self.root/review.STORE).write_bytes(b"preserved failed review history")
        with self.assertRaises(ValueError):review.review(self.root,self.proposal,self.clock,apply=True)
        self.assertEqual((self.root/review.STORE).read_bytes(),b"preserved failed review history")


if __name__=="__main__":unittest.main()
