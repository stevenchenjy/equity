"""Synthetic benchmark comparisons through genuine retained market/V2 admission.

Invented temp-store prices and source bodies below are fixtures, not investment
evidence. No network, SMTP, broker or production collector is used.
"""
import copy
import csv
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from _support import SCRIPT_DIR
from test_swing_quote_replay_integration import SwingQuoteReplayIntegrationTests, stamp
import intraday_prices as feed
import market_backup
import swing_benchmarks as bench
import swing_research as common
import swing_research_v2 as study
import swing_outcome_review as review


class MatchedBenchmarkTests(SwingQuoteReplayIntegrationTests):
    # Do not rerun the imported integration suite as inherited test methods.
    test_original_http_window_cohort_survives_new_close_account_and_matures=None
    test_changed_archived_original_is_rejected_without_rewriting_cohort=None

    def setUp(self):
        super().setUp()
        self.capture_clock=stamp("2026-09-22T17:00:00-04:00")
        self.future=stamp("2026-09-29T17:00:00-04:00")
        policy=json.loads((SCRIPT_DIR.parents[1]/bench.POLICY).read_bytes())
        policy["registered_at"]="2026-09-22T16:45:00-04:00"
        (self.root/bench.POLICY).write_text(json.dumps(policy))

    def _write_market(self,msft):
        """Three original unadjusted provider histories; real lineage admission."""
        session=msft[-1]["session_date"];cutoff=date.fromisoformat(session)-timedelta(weeks=52)
        msft=[row for row in msft if date.fromisoformat(row["session_date"])>=cutoff]
        universe=self.root/common.UNIVERSE
        benchmarks=getattr(self,"test_benchmarks",(("SPY",770.),("QQQM",300.)))
        universe.write_text("ticker,company_name,sector,is_benchmark\nMSFT,Synthetic Microsoft,Technology,no\n"+"".join(f"{ticker},Synthetic {ticker},ETF,yes\n" for ticker,_ in benchmarks))
        clock=stamp(session+"T16:30:00-04:00")
        histories={"MSFT":msft}
        for ticker,base in benchmarks:
            histories[ticker]=[{"session_date":row["session_date"],"open":base,"high":base+1,"low":base-1,"close":base,"volume":1000.} for row in msft]
        rows=[{"ticker":ticker,"last_price":bars[-1]["close"],"market_session_date":session,"data_quality_label":"ok","data_timestamp":clock.isoformat()} for ticker,bars in histories.items()]
        with (self.root/feed.BASELINE).open("w") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        observations=[];items={}
        for ticker,bars in histories.items():
            raw=json.dumps({"kind":"synthetic_unadjusted_provider_fixture","ticker":ticker,"bars":bars},sort_keys=True).encode()
            digest=hashlib.sha256(raw).hexdigest();relative=f"{market_backup.REL}/responses/{digest}.json"
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            observations.append({"path":relative,"sha256":digest});items[ticker]={"source_url":f"https://api.massive.com/synthetic-fixture/{ticker}","bars":bars}
        bundle={"schema_version":market_backup.SCHEMA,"market_session":session,"generated_at":clock.isoformat(),"data_source":market_backup.PRIMARY,"price_basis":"unadjusted","tickers":items,"observations":observations}
        pointer=market_backup.pointer_for(self.root,bundle,hashlib.sha256((self.root/feed.BASELINE).read_bytes()).hexdigest())
        feed.atomic_write_json(self.root/market_backup.CURRENT,pointer)
        self.assertEqual(market_backup.load_baseline(self.root,list(histories))["market_session"],session)

    def _capture(self,windows=False):
        value=study.build(self.root,self.capture_clock,capture=True)
        self.assertEqual(value["status"],"experimental_current",value)
        if windows:
            for clock,price in ((self.first+timedelta(seconds=10),514.),(self.first+timedelta(minutes=3,seconds=10),511.),(self.first+timedelta(minutes=6,seconds=20),512.)):
                context=self._held_and_candidate_quote(clock,price)
                value=study.build(self.root,clock+timedelta(seconds=10),capture=True,candidate_quote_context=context)
                self.assertEqual(value["status"],"experimental_current",value)
        return study._load(self.root,self.first+timedelta(minutes=7))

    def _mature(self):
        days=common._sessions_after(date(2026,9,22),5)
        bars=[{"session_date":day,"open":512.+i,"high":515.+i,"low":508.+i,"close":513.+i,"volume":1100.} for i,day in enumerate(days)]
        self._write_market(self.msft+bars)
        value=study.build(self.root,self.future,capture=True)
        self.assertEqual(value["status"],"experimental_current",value)
        rows=study._load(self.root,self.future);study._verify(self.root,rows)
        return rows

    def _review(self,outcome,clock):
        rows=study._load(self.root,clock)
        observation=next(row for row in rows if row["kind"]=="observation" and row["observation_id"]==outcome["observation_id"])
        start=observation["bars_at_observation"][0]["session_date"];end=outcome["forward_bars"][-1]["session_date"]
        manifest=self.root/"01_policies/official_news_sources.json";manifest.write_text('{"sources":[]}')
        sources=[]
        for index,(host,role) in enumerate((("www.sec.gov","issuer_or_sec_corporate_action_review"),("www.nasdaq.com","independent_exchange_corporate_action_review"))):
            path=Path("03_source_data/equity_research")/f"synthetic-review-{outcome['record_hash']}-{index}.html"
            excerpt=f"Synthetic retained evidence for {outcome['ticker']} corporate-action coverage; no real financial claim."
            raw=(excerpt+" Explicitly synthetic independent primary body for complete window tests."*4).encode()
            (self.root/path).parent.mkdir(parents=True,exist_ok=True);(self.root/path).write_bytes(raw)
            sources.append({"path":str(path),"sha256":common._digest(raw),"url":f"https://{host}/{outcome['ticker']}/fixture","available_at":clock.isoformat(),"coverage_from":start,"coverage_through":end,"ticker":outcome["ticker"],"supporting_excerpt":excerpt,"role":role,"coverage_explanation":"Synthetic analyst reviewed the named complete original signal and forward period using retained original issuer and independent exchange bodies. This is a test fixture."})
        proposal={"schema_version":review.SCHEMA,"reviewer":"Synthetic test reviewer","reviewed_at":clock.isoformat(),"ticker":outcome["ticker"],"observation_id":outcome["observation_id"],"outcome_record_hash":outcome["record_hash"],"horizon_sessions":outcome["horizon_sessions"],"entry_method":outcome["entry_method"],"window_id":outcome.get("window_id"),"coverage_from":start,"coverage_through":end,"corporate_action_conclusion":"no_actions_identified_after_source_bound_review","corporate_actions":[],"qualifying_method":"source_bound_analyst_review_of_fixed_horizon_price_path_only","sources":sources,"reasoning":"These synthetic primary source bytes cover the complete named original signal and forward window. The explicit no-action judgment qualifies only the unchanged nominal fixed-horizon price path. It supplies no trading or actual performance evidence and preserves every original modeled entry, cost and failure.","limitations":"Synthetic test only; not mechanical proof of absence, execution, bid/ask, fills, total return or managed strategy performance. Capital authority stays false."}
        return review.review(self.root,proposal,clock,apply=True)

    def test_future_open_both_benchmarks_same_dates_costs_and_unique_denominators(self):
        self._capture();rows=self._mature()
        before=(self.root/study.OUTPUT/"ledger.jsonl").read_bytes()
        value=bench.build(self.root,self.future,capture=True)
        self.assertEqual(value["status"],"raw_comparisons_available",value)
        self.assertEqual(value["summary"]["unique_stock_outcomes"],1)
        self.assertEqual(value["summary"]["comparison_pairs"],2)
        self.assertEqual(value["summary"]["qualified_strategy_paths"],0)
        stored,_=bench._comparison_ledger(self.root,self.future)
        for row in stored:
            self.assertEqual(row["entry_session"],"2026-09-23")
            self.assertEqual(row["exit_session"],"2026-09-29")
            self.assertEqual(row["stock_entry"],512.)
            self.assertEqual(row["benchmark_entry"],770. if row["benchmark"]=="SPY" else 300.)
            for cost in (10,25,50):
                expected=common._net(512.,517.,{"commission_per_share_usd":0,"one_way_cost_bps":[cost]})[str(cost)]-common._net(row["benchmark_entry"],row["benchmark_exit"],{"commission_per_share_usd":0,"one_way_cost_bps":[cost]})[str(cost)]
                self.assertAlmostEqual(row["raw_excess_price_path_pct_points_by_cost_bps"][str(cost)],expected,6)
            self.assertFalse(row["capital_authority"])
            self.assertEqual(row["regime"]["original_authored_regime"],"unrecorded")
        self.assertEqual(before,(self.root/study.OUTPUT/"ledger.jsonl").read_bytes())
        ledger=(self.root/bench.OUTPUT/"comparisons.jsonl").read_bytes()
        bench.build(self.root,self.future+timedelta(minutes=1),capture=True)
        self.assertEqual(ledger,(self.root/bench.OUTPUT/"comparisons.jsonl").read_bytes())

    def test_window_missing_pair_is_visible_now_never_substitutes_open(self):
        self._capture(windows=True)
        value=bench.build(self.root,self.first+timedelta(minutes=7))
        self.assertEqual(value["summary"]["genuine_entry_count"],2)
        self.assertEqual(value["summary"]["unpaired_entry_count"],2)
        self.assertEqual(value["summary"]["nonqualifying_window_transitions"],1)
        self.assertEqual(value["summary"]["missed_or_skipped_windows"],0)
        self.assertIn("paired_benchmark_observation_not_recorded",{row["code"] for row in value["dependencies"]})
        self._mature();value=bench.build(self.root,self.future,capture=True)
        self.assertEqual(value["summary"]["comparison_pairs"],2)
        self.assertEqual(value["summary"]["unmatched_pairs"],4)
        self.assertTrue(all(row["entry_method"]=="benchmark_future_open" for row in value["comparisons"]))

    def test_joint_source_bound_reviews_qualify_only_exact_paths(self):
        self._capture();rows=self._mature();clock=self.future+timedelta(minutes=5)
        outcomes=[row for row in rows if row["kind"]=="outcome"]
        stock=next(row for row in outcomes if row["ticker"]=="MSFT")
        self._review(stock,clock)
        partial=bench.build(self.root,clock)
        self.assertEqual(partial["summary"]["reviewed_pairs"],0)
        for row in outcomes:
            if row["ticker"] in {"SPY","QQQM"}:self._review(row,clock)
        value=bench.build(self.root,clock,capture=True)
        self.assertEqual(value["summary"]["reviewed_pairs"],2)
        self.assertEqual(value["summary"]["unique_reviewed_stock_outcomes"],1)
        self.assertEqual(value["summary"]["qualified_strategy_paths"],0)
        self.assertFalse(value["profitability_established"])

    def test_pair_entry_reuses_only_exact_reviewed_ETF_action_coverage(self):
        self._capture(windows=True);rows=self._mature();clock=self.future+timedelta(minutes=5)
        outcomes=[row for row in rows if row["kind"]=="outcome"]
        for row in outcomes:self._review(row,clock)
        observations={row["observation_id"]:row for row in rows if row["kind"]=="observation"}
        window=next(row for row in outcomes if row["ticker"]=="MSFT" and row["entry_method"]=="observed_owner_window_mark_not_fill")
        entry=next(row for row in rows if row["record_hash"]==window["entry_observation_record_hash"])
        pair={"entry_observation_record_hash":entry["record_hash"],"observation_id":entry["observation_id"],"ticker":"MSFT","entry_method":window["entry_method"],"window_id":window["window_id"],"delay_minutes":None,"pair_max_span_seconds":60,"execution_quote":False,"capital_authority":False,"stock_quote":entry["quote_observation"],"benchmarks":{ticker:{"price":price,"observed_at":entry["quote_observation"]["observed_at"]} for ticker,price in (("SPY",760.),("QQQM",295.))},"source":{"path":"synthetic-pair.json","sha256":"a"*64}}
        policy,_=bench._policy(self.root,clock)
        # Pair reader validation is tested end to end in the separate original-HTTP
        # suite; this narrowly exercises the comparison's exact coverage matcher.
        record=bench._derive(self.root,observations[window["observation_id"]],window,"SPY",policy,bench._implementation(),{"pairs":[pair]}, {})
        annotated,_=bench._annotate(self.root,[record],rows,clock)
        self.assertTrue(annotated[0]["reviewed_fixed_path_comparison"])
        self.assertEqual(record["benchmark_entry"],760.)
        self.assertNotEqual(record["benchmark_entry"],record["benchmark_forward_bars"][0]["open"])
        changed=copy.deepcopy(record);changed["benchmark_forward_bars"][0]["close"]+=1
        mismatch,_=bench._annotate(self.root,[changed],rows,clock)
        self.assertFalse(mismatch[0]["reviewed_fixed_path_comparison"])
        bad=copy.deepcopy(pair);bad["stock_quote"]["price"]+=1
        with self.assertRaisesRegex(ValueError,"does_not_match_actual_stock_mark"):
            bench._derive(self.root,observations[window["observation_id"]],window,"SPY",policy,bench._implementation(),{"pairs":[bad]}, {})

    def test_policy_registered_after_entry_is_retrospective(self):
        self._capture();self._mature()
        path=self.root/bench.POLICY;policy=json.loads(path.read_bytes());policy["registered_at"]="2026-09-24T17:00:00-04:00";path.write_text(json.dumps(policy))
        value=bench.build(self.root,self.future,capture=True)
        self.assertEqual(value["summary"]["prospective_matched_pairs"],0)
        self.assertTrue(all(row["design_timing"]=="retrospective_protocol_registered_after_entry" for row in value["comparisons"]))

    def test_missing_original_benchmark_stays_a_scoped_dependency(self):
        self.test_benchmarks=(("SPY",770.),)
        self._write_market(self.msft)
        self._capture();self._mature()
        value=bench.build(self.root,self.future,capture=True)
        self.assertEqual(value["summary"]["comparison_pairs"],1)
        self.assertEqual(value["summary"]["unmatched_pairs"],1)
        self.assertEqual(value["comparisons"][0]["benchmark"],"SPY")
        self.assertIn("benchmark_not_in_original_admitted_canonical_scope",{row["code"] for row in value["dependencies"]})

    def test_projection_forgery_omission_and_ledger_corruption_fail_closed(self):
        self._capture();self._mature();value=bench.build(self.root,self.future,capture=True)
        read=bench.revalidate_projection(self.root,value,self.future+timedelta(minutes=1))
        self.assertEqual(read["read_time_summary"]["comparison_pairs"],2)
        for change in ("count","omission"):
            tampered=copy.deepcopy(value)
            if change=="count":tampered["summary"]["reviewed_pairs"]=999
            else:tampered["comparisons"]=[]
            tampered["projection_sha256"]=common._hash({key:val for key,val in tampered.items() if key!="projection_sha256"})
            self.assertEqual(bench.revalidate_projection(self.root,tampered,self.future)["status"],"unavailable")
        ledger=self.root/bench.OUTPUT/"comparisons.jsonl";original=ledger.read_bytes()
        ledger.write_bytes(original.splitlines(keepends=True)[0])
        omitted=bench.build(self.root,self.future)
        self.assertEqual(omitted["status"],"unavailable")
        self.assertIn("benchmark_original_comparison_prefix_changed",{row["code"] for row in omitted["dependencies"]})
        ledger.write_bytes(original)
        ledger=self.root/bench.OUTPUT/"comparisons.jsonl";ledger.write_bytes(b"corrupt retained original benchmark attempts")
        self.assertEqual(bench.build(self.root,self.future,capture=True)["status"],"unavailable")
        self.assertEqual(ledger.read_bytes(),b"corrupt retained original benchmark attempts")

    def test_mixed_review_status_means_use_the_exact_displayed_denominators(self):
        rows=[]
        for reviewed,value in ((True,10.),(False,-10.)):
            rows.append({"benchmark":"SPY","entry_method":"benchmark_future_open","horizon_sessions":5,"cohort":"technical_selected","regime":{"classification":"mixed_price_trend"},"reviewed_fixed_path_comparison":reviewed,"raw_excess_price_path_pct_points_by_cost_bps":{str(cost):value for cost in (10,25,50)}})
        group=bench._group(rows)[0]
        self.assertEqual(group["raw_pairs"],1);self.assertEqual(group["reviewed_pairs"],1)
        self.assertEqual(group["raw_mean_excess_price_path_pct_by_cost_bps"]["25"],-10.)
        self.assertEqual(group["reviewed_mean_excess_price_path_pct_by_cost_bps"]["25"],10.)
        self.assertIsNone(bench._group(rows[:1])[0]["raw_mean_excess_price_path_pct_by_cost_bps"]["25"])


if __name__=="__main__":unittest.main()
