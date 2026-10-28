from __future__ import annotations
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from _support import SCRIPT_DIR
from test_swing_research import fixture, current, policy as v1policy, breakout_bars, bars
import swing_research as old
import swing_research_v2 as swing


def v2policy():
    return json.loads((SCRIPT_DIR.parents[1] / swing.POLICY).read_text())


def setup(root, *, clock=None, series=None, etf=False):
    clock = clock or current()
    bundle = fixture(root, series, observed=clock)
    (root / swing.POLICY).write_text(json.dumps(v2policy()))
    (root / old.UNIVERSE).write_text("ticker,sector,is_benchmark\nTEST," + ("ETF,yes" if etf else "Technology,no") + "\n")
    return bundle


def quote(clock, price=103.0):
    return {"status": "current", "tickers": {"TEST": {"price": price, "trade_at": clock.isoformat(),
            "observed_at": clock.isoformat(), "execution_quote": False, "source_label": "Nasdaq Last Sale"}}}


class SwingV2Tests(unittest.TestCase):
    def test_v1_policy_remains_unchanged_and_v2_has_separate_namespace(self):
        self.assertEqual(v1policy()["version"], "daily-swing-forward-v1-20261027")
        self.assertNotEqual(swing.OUTPUT, old.OUTPUT)
        self.assertNotEqual(swing.POLICY, old.POLICY)

    def test_window_clock_uses_exchange_dst_and_early_close(self):
        windows = swing._windows("2026-12-23", v2policy())
        self.assertEqual(windows[0]["starts_at"], "2026-12-23T09:45:00-05:00")
        windows = swing._windows("2026-11-27", v2policy())
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["ends_at"], "2026-11-27T10:45:00-05:00")

    def test_postopen_levels_survive_only_as_dated_conditional_research(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                view = swing.build(root, current())
            self.assertEqual(view["status"], "experimental_current")
            card = view["candidates"][0]
            self.assertEqual(card["timing"]["state"], "awaiting_fresh_quote")
            self.assertEqual(card["entry_trigger"], 103)
            self.assertEqual(card["review_deadline"], "2026-09-23T15:20:00-04:00")
            self.assertEqual(card["first_observed_at"], current().isoformat())
            self.assertFalse(card["capital_authority"])
            self.assertEqual(card["actionable_quantity"], 0)
            self.assertFalse((root / swing.OUTPUT).exists())

    def test_premarket_and_between_windows_never_show_current_entry_mark(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); clock = current().replace(hour=8); bundle = setup(root, clock=clock)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                view = swing.build(root, clock, capture=True)
                self.assertEqual(view["candidates"][0]["timing"]["state"], "before_review_window")
                later = swing.revalidate_projection(root, view, current().replace(hour=12))
            self.assertEqual(later["candidates"][0]["timing"]["state"], "between_review_windows")
            self.assertIsNone(later["candidates"][0]["timing"]["quote_observation"])

    def test_expired_signal_is_not_rolled_to_another_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                view = swing.build(root, current(), capture=True)
                expired = swing.revalidate_projection(root, view, current().replace(hour=15, minute=21))
            self.assertEqual(expired["candidates"], [])
            self.assertEqual(expired["expired_candidates_suppressed"], len(view["candidates"]))

    def test_same_source_clocks_preserve_original_first_capture(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                first = swing.build(root, current(), capture=True)
                before = (root / swing.OUTPUT / "ledger.jsonl").read_bytes()
                later = swing.build(root, current() + timedelta(minutes=15), capture=True)
            self.assertEqual(later["candidates"][0]["first_observed_at"], first["candidates"][0]["first_observed_at"])
            self.assertEqual((root / swing.OUTPUT / "ledger.jsonl").read_bytes(), before)

    def test_no_opportunity_still_has_applicable_owner_windows(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root, series=bars())
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                view = swing.build(root, current())
            self.assertEqual(view["candidates"], [])
            self.assertEqual(len(view["review_windows"]), 2)

    def test_etf_setup_is_benchmark_observation_not_growth_stock_card(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root, etf=True)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                view = swing.build(root, current(), capture=True)
                targets = swing.quote_targets(root, current())
            self.assertEqual(view["candidates"], [])
            self.assertEqual(view["coverage"]["benchmark_only"], 1)
            self.assertEqual(targets, [])

    def test_afteropen_quote_does_not_precede_actual_first_capture(self):
        p = v2policy(); clock = current()
        ob = {"ticker": "TEST", "first_observed_at": clock.isoformat(), "features": old._features(breakout_bars()),
              "review_windows": swing._windows("2026-09-23", p, clock)}
        result = swing._timing(ob, p, clock + timedelta(seconds=30), quote(clock - timedelta(seconds=1)))
        self.assertEqual(result["state"], "awaiting_fresh_quote")
        result = swing._timing(ob, p, clock + timedelta(seconds=30), quote(clock + timedelta(seconds=10)))
        self.assertEqual(result["state"], "condition_observed")
        self.assertFalse(result["quote_observation"]["execution_quote"])

    def test_quote_expiry_keeps_blueprint_but_suppresses_current_condition(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                view = swing.build(root, current(), capture=True)
                with patch.object(swing, "_quote_context", return_value=quote(current() + timedelta(seconds=10))):
                    observed = swing.revalidate_projection(root, view, current() + timedelta(seconds=30))
                    expired = swing.revalidate_projection(root, view, current() + timedelta(minutes=6))
            self.assertEqual(observed["candidates"][0]["timing"]["state"], "condition_observed")
            self.assertEqual(expired["candidates"][0]["timing"]["state"], "awaiting_fresh_quote")
            self.assertEqual(expired["candidates"][0]["entry_trigger"], 103)

    def test_out_of_band_and_invalidation_are_observations_not_fills(self):
        clock = current(); p = v2policy()
        ob = {"ticker": "TEST", "first_observed_at": clock.isoformat(), "features": old._features(breakout_bars()),
              "review_windows": swing._windows("2026-09-23", p, clock)}
        for price, state in ((107, "outside_entry_band"), (97, "invalidation_observed")):
            self.assertEqual(swing._timing(ob, p, clock + timedelta(seconds=30), quote(clock + timedelta(seconds=10), price))["state"], state)

    def test_first_window_observation_is_immutable_and_not_an_elapsed_open(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                swing.build(root, current(), capture=True)
                with patch.object(swing, "_quote_context", return_value=quote(current() + timedelta(seconds=10))):
                    view = swing.build(root, current() + timedelta(seconds=30), capture=True)
                def admission(_root, context, clock, scope, bindings, **kwargs):
                    return context if kwargs.get("historical") else quote(current() + timedelta(minutes=1),104)
                with patch.object(swing, "_quote_context", side_effect=admission):
                    later = swing.build(root, current() + timedelta(minutes=2), capture=True)
                    self.assertEqual(later["status"],"experimental_current")
            rows = swing._load(root, current() + timedelta(minutes=3))
            checks = [row for row in rows if row["kind"] == "window_evaluation"]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["quote_observation"]["price"], 103)
            self.assertEqual(view["performance"]["outcomes"], 0)
            self.assertEqual(view["performance"]["performance_eligible_paths"], 0)

    def test_delayed_window_path_uses_observed_mark_not_elapsed_open(self):
        original=breakout_bars();clock=current();p=v2policy()
        ob={"observation_id":"o","ticker":"TEST","source_session":"2026-09-22","price_basis":"unadjusted",
            "bars_at_observation":original[-51:],"features":old._features(original),"benchmark_entry_session":"2026-09-24"}
        check={"state":"condition_observed","window_id":"morning","record_hash":"a"*64,
               "quote_observation":{"price":103.,"observed_at":clock.isoformat()}}
        days=["2026-09-23",*old._sessions_after(clock.date(),4)]
        forward=[{"session_date":day,"open":80. if index==0 else 106.,"high":120.,"low":75.,"close":105.,"volume":100.}
                 for index,day in enumerate(days)]
        dataset={"series":{"TEST":{"bars":original+forward,"price_basis":"unadjusted"}}}
        matured=old.regular_close(days[-1])+timedelta(minutes=20)
        result=swing._derive_outcome(ob,check,"observed_owner_window_mark_not_fill",5,dataset,{},p,matured)
        self.assertEqual(result["entry_price"],103.)
        self.assertEqual(result["entry_day_exit_ordering_status"],"unverified_daily_bar_includes_pre_entry_prices")
        self.assertFalse(result["actual_fill"])
        self.assertAlmostEqual(result["raw_common_price_cost_sensitivity_pct_by_one_way_bps"]["25"],old._net(103.,105.,p)["25"])
        self.assertIsNone(swing._derive_outcome(ob,check,"observed_owner_window_mark_not_fill",14,dataset,{},p,matured))

    def test_full_future_source_and_immutable_window_replay_are_bound(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);original=breakout_bars();bundle=setup(root,series=original)
            context=quote(current()+timedelta(seconds=10))
            def admitted(_root,value,clock,scope,bindings,**kwargs): return value if kwargs.get("historical") else context
            with patch.object(old.market_backup,"load_baseline",return_value=bundle),patch.object(swing,"_outside",return_value={"histories":{}}),patch.object(swing,"_quote_context",side_effect=admitted):
                swing.build(root,current(),capture=True)
                swing.build(root,current()+timedelta(seconds=30),capture=True)
            dates=["2026-09-23",*old._sessions_after(current().date(),5)]
            future=[{"session_date":day,"open":103.,"high":104.,"low":100.,"close":103.,"volume":100.} for day in dates]
            clock=old.regular_close(dates[-1])+timedelta(minutes=30)
            later=setup(root,clock=clock,series=original+future)
            with patch.object(old.market_backup,"load_baseline",return_value=later),patch.object(swing,"_outside",return_value={"histories":{}}),patch.object(swing,"_quote_context",side_effect=admitted):
                view=swing.build(root,clock,capture=True)
                self.assertEqual(view["status"],"experimental_current")
                rows=swing._load(root,clock);swing._verify(root,rows)
                outcomes=[row for row in rows if row["kind"]=="outcome"]
                self.assertEqual(len(outcomes),2)
                delayed=next(row for row in outcomes if row["entry_method"]=="observed_owner_window_mark_not_fill")
                delayed["entry_price"]+=1
                with self.assertRaisesRegex(old.SwingResearchError,"retained_outcome_calculation_unverified"):swing._verify(root,rows)

    def test_frozen_identity_and_missing_forward_bars_stay_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle=setup(root)
            with patch.object(old.market_backup,"load_baseline",return_value=bundle),patch.object(swing,"_outside",return_value={"histories":{}}):
                swing.build(root,current(),capture=True)
                with patch.object(swing,"_implementation",return_value=("a"*64,{})):
                    result=swing.build(root,current()+timedelta(minutes=5),capture=True)
            self.assertEqual(result["candidates"],[])
            self.assertIn("swing_v2_frozen_version_identity_changed",result["blockers"])

    def test_out_of_band_recovery_can_record_first_actual_qualifying_mark(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle=setup(root);now=current()
            fresh=quote(now+timedelta(seconds=10),107.)
            def admitted(_root,context,clock,scope,bindings,**kwargs): return context if kwargs.get("historical") else fresh
            with patch.object(old.market_backup,"load_baseline",return_value=bundle),patch.object(swing,"_outside",return_value={"histories":{}}),patch.object(swing,"_quote_context",side_effect=admitted):
                original=swing.build(root,now,capture=True)
                swing.build(root,now+timedelta(seconds=30),capture=True)
                fresh=quote(now+timedelta(minutes=3),103.)
                recovered=swing.build(root,now+timedelta(minutes=3,seconds=10),capture=True)
                rows=swing._load(root,now+timedelta(minutes=4));swing._verify(root,rows)
                read=swing.revalidate_projection(root,original,now+timedelta(minutes=4))
            checks=[row for row in rows if row["kind"]=="window_evaluation"]
            self.assertEqual([row["state"] for row in checks],["outside_entry_band","condition_observed"])
            self.assertEqual([row["first_qualifying_entry"] for row in checks],[False,True])
            self.assertEqual(recovered["candidates"][0]["timing"]["state"],"condition_observed")
            self.assertEqual(read["read_time_performance"]["window_observations"],1)
            self.assertEqual(read["read_time_performance"]["verified_state_transitions"],2)
            self.assertEqual(read["performance"]["window_observations"],0)

    def test_verified_day_invalidation_does_not_revive_after_price_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle=setup(root);now=current();fresh=quote(now+timedelta(seconds=10),97.)
            def admitted(_root,context,clock,scope,bindings,**kwargs):return context if kwargs.get("historical") else fresh
            with patch.object(old.market_backup,"load_baseline",return_value=bundle),patch.object(swing,"_outside",return_value={"histories":{}}),patch.object(swing,"_quote_context",side_effect=admitted):
                view=swing.build(root,now,capture=True)
                invalid=swing.build(root,now+timedelta(seconds=30),capture=True)
                fresh=quote(now+timedelta(minutes=3),103.)
                recovered=swing.build(root,now+timedelta(minutes=3,seconds=10),capture=True)
                read=swing.revalidate_projection(root,view,now+timedelta(minutes=4))
            self.assertEqual(invalid["candidates"][0]["timing"]["state"],"invalidation_observed")
            self.assertEqual(recovered["candidates"][0]["timing"]["state"],"invalidation_observed")
            self.assertTrue(read["candidates"][0]["timing"]["permanent_for_signal_day"])
            self.assertEqual(recovered["performance"]["condition_observed_windows"],0)

    def test_original_projection_receipt_rejects_forged_metadata_even_with_new_self_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle=setup(root)
            with patch.object(old.market_backup,"load_baseline",return_value=bundle),patch.object(swing,"_outside",return_value={"histories":{}}):
                view=swing.build(root,current(),capture=True)
                for key in ("profitability","promotion","omitted","omitted_unsealed"):
                    forged=copy.deepcopy(view)
                    if key=="profitability":forged["performance"]["profitability_established"]=True
                    elif key=="promotion":forged["promotion_review"]["currently_qualified"]=True
                    else:
                        forged["candidates"]=[]
                        if key=="omitted_unsealed":forged["projection_recorded"]=False
                    forged["projection_sha256"]=old._hash({k:v for k,v in forged.items() if k!="projection_sha256"})
                    result=swing.revalidate_projection(root,forged,current())
                    self.assertEqual(result["candidates"],[])
                    self.assertNotEqual(result["status"],"experimental_current")

    def test_bad_outside_history_does_not_discard_valid_canonical_scope(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle=setup(root)
            outside={"histories":{"BAD":{"bars":breakout_bars(),"price_basis":"unadjusted","source_bindings":{"missing.json":"a"*64},"data_source":"test","common_stock_verified":True}}}
            with patch.object(old.market_backup,"load_baseline",return_value=bundle),patch.object(swing,"_outside",return_value=outside):
                view=swing.build(root,current())
            self.assertEqual(view["status"],"experimental_current")
            self.assertEqual(view["coverage"]["scope"],["TEST"])
            self.assertIn("outside_ticker_history_unverified:BAD",view["blockers"])

    def test_actual_delayed_quotes_are_after_target_not_reused_original_mark(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle=setup(root);now=current();fresh=quote(now+timedelta(seconds=10),103.)
            def admitted(_root,context,clock,scope,bindings,**kwargs):return context if kwargs.get("historical") else fresh
            with patch.object(old.market_backup,"load_baseline",return_value=bundle),patch.object(swing,"_outside",return_value={"histories":{}}),patch.object(swing,"_quote_context",side_effect=admitted):
                swing.build(root,now,capture=True);swing.build(root,now+timedelta(seconds=30),capture=True)
                # Clock passage with the old mark cannot fabricate a3-minute observation.
                swing.build(root,now+timedelta(minutes=3,seconds=30),capture=True)
                self.assertFalse(any(r["kind"]=="delay_evaluation" for r in swing._load(root,now+timedelta(minutes=4))))
                fresh=quote(now+timedelta(minutes=4),103.5)
                view=swing.build(root,now+timedelta(minutes=4,seconds=10),capture=True)
                rows=swing._load(root,now+timedelta(minutes=5));swing._verify(root,rows)
            delayed=[r for r in rows if r["kind"]=="delay_evaluation"]
            self.assertEqual(len(delayed),1)
            self.assertEqual(delayed[0]["delay_minutes"],3)
            self.assertEqual(delayed[0]["actual_delay_seconds"],230)
            self.assertEqual(delayed[0]["quote_observation"]["price"],103.5)
            self.assertFalse(delayed[0]["actual_fill"])

    def test_delayed_outside_or_missing_observation_is_not_filled(self):
        p=v2policy();now=current()
        ob={"observation_id":"o","ticker":"TEST","first_observed_at":now.isoformat(),"features":old._features(breakout_bars()),
            "review_windows":swing._windows("2026-09-23",p,now)}
        first={"record_hash":"a"*64,"window_id":"morning","quote_observation":{"observed_at":now.isoformat()}}
        later=now+timedelta(minutes=6)
        check=swing._delay_check(ob,first,5,p,later,quote(later,107.),[])
        self.assertEqual(check["state"],"outside_entry_band")
        self.assertEqual(check["actual_delay_seconds"],360)
        missed=swing._delay_check(ob,first,10,p,now.replace(hour=11),{"tickers":{}},[])
        self.assertEqual(missed["state"],"missed_no_verified_delayed_observation")
        self.assertIsNone(missed["quote_observation"])

    def test_delay_variants_use_distinct_actual_prices_but_not_independent_setup_count(self):
        original=breakout_bars();now=current();p=v2policy()
        ob={"observation_id":"o","ticker":"TEST","source_session":"2026-09-22","price_basis":"unadjusted",
            "bars_at_observation":original[-51:],"features":old._features(original),"benchmark_entry_session":"2026-09-24"}
        dates=["2026-09-23",*old._sessions_after(now.date(),4)]
        future=[{"session_date":day,"open":80.,"high":120.,"low":75.,"close":110.,"volume":100.} for day in dates]
        dataset={"series":{"TEST":{"bars":original+future,"price_basis":"unadjusted"}}};end=old.regular_close(dates[-1])+timedelta(minutes=30)
        for delay,price in ((3,103.),(5,104.),(10,104.1)):
            check={"state":"condition_observed","window_id":"morning","record_hash":"a"*64,"delay_minutes":delay,"actual_delay_seconds":delay*60,
                   "quote_observation":{"observed_at":(now+timedelta(minutes=delay)).isoformat(),"price":price}}
            result=swing._derive_outcome(ob,check,f"observed_owner_window_delay_{delay}_minutes_mark_not_fill",5,dataset,{},p,end)
            self.assertEqual(result["entry_price"],price)
            self.assertEqual(result["delay_minutes"],delay)
            self.assertFalse(result["actual_fill"])

    def test_stale_sources_and_tampered_reference_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle = setup(root)
            with patch.object(old.market_backup, "load_baseline", return_value=bundle), patch.object(swing, "_outside", return_value={"histories": {}}):
                view = swing.build(root, current())
                bad = copy.deepcopy(view); bad["candidates"][0]["entry_trigger"] += 1
                self.assertEqual(swing.revalidate_projection(root, bad, current())["candidates"], [])
                self.assertEqual(swing.revalidate_projection(root, view, current() + timedelta(days=1))["candidates"], [])


if __name__ == "__main__": unittest.main()
