"""Source/time/cost-matched research benchmarks, independent of frozen V2.

No collector, capital, execution or delivery path exists here. A comparison is
a normalized fixed-horizon price-path difference, never a trade or proven edge.
Original V2 records, failed windows and unselected observations remain intact.
"""
from __future__ import annotations
import copy
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from statistics import mean

import swing_research as common

POLICY=Path("01_policies/swing_benchmarks.json")
OUTPUT=Path("08_reviews/swing_benchmarks.local")
VERSION="spy-qqqm-matched-paths-v1-20261028"
SCHEMA="equity_swing_benchmarks_v1"
AUTHORITY={**common.AUTHORITY,"execution_quote":False}


def _policy(root,current):
    raw=common._file(root,POLICY);value=json.loads(raw)
    if (value.get("schema_version")!="equity_swing_benchmark_policy_v1" or value.get("version")!=VERSION
            or value.get("benchmarks")!=["SPY","QQQM"] or value.get("horizons_sessions")!=[5,10,14]
            or value.get("one_way_cost_bps")!=[10,25,50] or value.get("commission_per_share_usd")!=0
            or value.get("paired_mark_max_span_seconds")!=120 or common._aware(value["registered_at"])>current
            or any(value.get(k)!=v for k,v in AUTHORITY.items())):
        raise common.SwingResearchError("benchmark_protocol_unverified")
    return value,raw


def _implementation():
    directory=Path(__file__).resolve().parent
    names=["swing_benchmarks.py","swing_benchmark_quotes.py","swing_benchmark_review.py"]
    return common._hash({name:common._digest((directory/name).read_bytes()) for name in names if (directory/name).exists()})


def _safe(root,relative):
    path=Path(relative)
    if path.is_absolute() or ".." in path.parts:raise common.SwingResearchError("benchmark_source_locator_unverified")
    return common._file(root,path)


def _stock_state(root,current):
    import swing_research_v2 as study
    path=study.OUTPUT/"ledger.jsonl"
    raw=_safe(root,path) if (root/path).exists() else b""
    rows=study._load(root,current);study._verify(root,rows)
    if raw!=(_safe(root,path) if (root/path).exists() else b""):
        raise common.SwingResearchError("benchmark_stock_ledger_changed_during_read")
    return rows,{"path":str(path),"sha256":common._digest(raw),"records":len(rows)},raw


def _pairs(root,current,provided=None):
    try:
        from swing_benchmark_quotes import admitted_pairs,read_poll
        value=admitted_pairs(root,current)
    except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError):
        value={"pairs":[],"dependencies":[{"reason":"source_bound_paired_benchmark_marks_required"}]}
    if provided is not None and provided!=value:raise common.SwingResearchError("benchmark_pair_context_requires_readmission")
    try:value={**value,"poll":read_poll(root,current)}
    except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError):
        value={**value,"poll":{"status":"not_yet_verified","failure":"supplemental_benchmark_poll_receipt_unverified",**AUTHORITY}}
    return value


def _dataset(root,binding,cache):
    import swing_research_v2 as study
    digest=binding["dataset_sha256"]
    if not isinstance(digest,str) or not re.fullmatch(r"[a-f0-9]{64}",digest):
        raise common.SwingResearchError("benchmark_dataset_locator_unverified")
    path=study.OUTPUT/"input_history"/digest
    if digest not in cache:
        raw=_safe(root,path)
        if common._digest(raw)!=digest:raise common.SwingResearchError("benchmark_stock_dataset_changed")
        cache[digest]=(json.loads(raw),{"path":str(path),"sha256":digest})
    return cache[digest]


def _history(root,outcome,benchmark,cache):
    """Independently check canonical full-history lineage and exact ETF bars."""
    import market_backup
    import swing_research_v2 as study
    binding=outcome["inputs"];dataset,dataset_source=_dataset(root,binding,cache)
    if benchmark not in dataset.get("canonical_scope",[]):
        raise common.SwingResearchError("benchmark_not_in_original_admitted_canonical_scope")
    history_sha=binding.get("history_sha256")
    if not history_sha:raise common.SwingResearchError("benchmark_original_canonical_history_required")
    key="history:"+history_sha
    if key not in cache:
        raw=_safe(root,study.OUTPUT/"input_history"/history_sha)
        if common._digest(raw)!=history_sha:raise common.SwingResearchError("benchmark_history_bytes_changed")
        history=json.loads(raw)
        market_backup.checked_bundle(history,list(history["tickers"]))
        market_backup.verify_history_sources(root,history)
        if common._aware(history["generated_at"])>common._aware(outcome["recorded_at"]):
            raise common.SwingResearchError("benchmark_source_available_after_outcome")
        cache[key]=history
    history=cache[key];item=dataset["series"].get(benchmark,{})
    if (history.get("snapshot_sha256")!=binding.get("snapshot_sha256")
            or history.get("market_session")!=binding.get("market_session")
            or item.get("price_basis")!="unadjusted" or item.get("common_stock") is not False
            or item.get("bars")!=history["tickers"].get(benchmark,{}).get("bars")):
        raise common.SwingResearchError("benchmark_history_projection_unbound")
    return item["bars"],dataset_source,{"path":str(study.OUTPUT/"input_history"/history_sha),"sha256":history_sha}


def _regime(root,observation,cache):
    dataset,source=_dataset(root,observation["inputs"],cache)
    bars=dataset.get("series",{}).get("SPY",{}).get("bars",[])
    if len(bars)<50 or bars[-1].get("session_date")!=observation["source_session"]:
        return {"classification":"unknown","basis":"original_SPY_history_unavailable"}
    close=common._number(bars[-1]["close"]);ma20=mean(common._number(b["close"]) for b in bars[-20:]);ma50=mean(common._number(b["close"]) for b in bars[-50:])
    classification="adverse_price_trend" if close<ma20<ma50 else "positive_price_trend" if close>ma20>ma50 else "mixed_price_trend"
    return {"classification":classification,"basis":"supplemental_predeclared_SPY_price_descriptor_not_original_authored_regime",
            "source_session":observation["source_session"],"source":source,"original_authored_regime":"unrecorded",
            "close":close,"sma20":ma20,"sma50":ma50}


def _derive(root,observation,outcome,benchmark,policy,implementation,pairs,cache):
    if outcome.get("status")=="correction_review_required":raise common.SwingResearchError("stock_history_correction_review_required")
    if outcome.get("price_basis",observation["price_basis"])!="unadjusted":raise common.SwingResearchError("stock_benchmark_price_basis_mismatch")
    days=[bar["session_date"] for bar in outcome["forward_bars"]]
    bars,dataset_source,history_source=_history(root,outcome,benchmark,cache)
    lookup={bar["session_date"]:bar for bar in bars}
    if any(day not in lookup for day in days):raise common.SwingResearchError("benchmark_exact_forward_sessions_missing")
    forward=[lookup[day] for day in days]
    original_dataset,_=_dataset(root,observation["inputs"],cache)
    original={bar["session_date"]:bar for bar in original_dataset.get("series",{}).get(benchmark,{}).get("bars",[])}
    if any(day in lookup and lookup[day]!=bar for day,bar in original.items()):
        raise common.SwingResearchError("benchmark_original_history_correction_review_required")
    pair=None
    if outcome["entry_method"]=="benchmark_future_open":
        if days[0]!=observation["benchmark_entry_session"]:raise common.SwingResearchError("benchmark_entry_session_mismatch")
        entry_clock=common._open(days[0]);stock_entry=common._number(outcome["forward_bars"][0]["open"]);benchmark_entry=common._number(forward[0]["open"])
        entry_kind="same_future_regular_open_not_fill"
    else:
        matching=[pair for pair in pairs.get("pairs",[]) if pair.get("entry_observation_record_hash")==outcome.get("entry_observation_record_hash")]
        if len(matching)!=1:raise common.SwingResearchError("genuine_paired_owner_window_benchmark_marks_required")
        pair=matching[0]
        if (pair.get("observation_id")!=observation["observation_id"] or pair.get("ticker")!=outcome["ticker"]
                or pair.get("entry_method")!=outcome["entry_method"] or pair.get("window_id")!=outcome.get("window_id")
                or pair.get("delay_minutes")!=outcome.get("delay_minutes") or pair.get("pair_max_span_seconds",121)>120
                or pair.get("execution_quote") is not False or pair.get("capital_authority") is not False):
            raise common.SwingResearchError("benchmark_pair_stock_entry_identity_mismatch")
        mark=pair["benchmarks"][benchmark];stock_mark=pair["stock_quote"]
        if stock_mark["price"]!=outcome["entry_price"] or stock_mark["observed_at"]!=outcome["entry_observed_at"]:
            raise common.SwingResearchError("benchmark_pair_does_not_match_actual_stock_mark")
        entry_clock=common._aware(stock_mark["observed_at"]);stock_entry=common._number(stock_mark["price"]);benchmark_entry=common._number(mark["price"])
        if entry_clock.date().isoformat()!=days[0] or common._aware(mark["observed_at"]).date()!=entry_clock.date():
            raise common.SwingResearchError("benchmark_pair_entry_session_mismatch")
        entry_kind="paired_bounded_asynchronous_last_sales_not_fills"
    stock_exit=common._number(outcome["forward_bars"][-1]["close"]);benchmark_exit=common._number(forward[-1]["close"])
    stock_values=common._net(stock_entry,stock_exit,policy);benchmark_values=common._net(benchmark_entry,benchmark_exit,policy)
    if stock_values!=outcome.get("raw_common_price_cost_sensitivity_pct_by_one_way_bps"):
        raise common.SwingResearchError("benchmark_stock_path_arithmetic_mismatch")
    record={"schema_version":"equity_swing_benchmark_comparison_v1","protocol_sha256":common._digest(common._file(root,POLICY)),
            "implementation_sha256":implementation,"observation_id":observation["observation_id"],"stock_observation_record_hash":observation["record_hash"],
            "stock_outcome_record_hash":outcome["record_hash"],"ticker":outcome["ticker"],"benchmark":benchmark,
            "entry_method":outcome["entry_method"],"window_id":outcome.get("window_id"),"delay_minutes":outcome.get("delay_minutes"),
            "horizon_sessions":outcome["horizon_sessions"],"entry_session":days[0],"exit_session":days[-1],"entry_clock":entry_clock.isoformat(),
            "entry_kind":entry_kind,"price_basis":"unadjusted","stock_entry":stock_entry,"stock_exit":stock_exit,
            "benchmark_entry":benchmark_entry,"benchmark_exit":benchmark_exit,"benchmark_forward_bars":forward,
            "stock_raw_price_cost_sensitivity_pct":stock_values,"benchmark_raw_price_cost_sensitivity_pct":benchmark_values,
            "raw_excess_price_path_pct_points_by_cost_bps":{key:round(stock_values[key]-benchmark_values[key],6) for key in stock_values},
            "dataset_source":dataset_source,"benchmark_history_source":history_source,"pair_source":pair.get("source") if pair else None,
            "pair_entry_observation_record_hash":outcome.get("entry_observation_record_hash"),
            "design_timing":"prospective_protocol_before_entry" if common._aware(policy["registered_at"])<entry_clock else "retrospective_protocol_registered_after_entry",
            "cohort":"technical_selected" if any(observation["features"]["selected"].values()) else "technical_unselected",
            "regime":_regime(root,observation,cache),"corporate_action_review_required":True,"qualification_at_capture":"raw_unreviewed",
            "profitability_established":False,**AUTHORITY}
    record["comparison_id"]=common._hash({"protocol":record["protocol_sha256"],"stock_outcome":outcome["record_hash"],"benchmark":benchmark})
    return record


def _comparison_ledger(root,current):
    path=root/OUTPUT/"comparisons.jsonl";rows=[];previous="";seen=set()
    raw=_safe(root,OUTPUT/"comparisons.jsonl") if path.exists() else b""
    for prefix in sorted((root/OUTPUT/"comparison_prefixes").glob("*")):
        retained=common._file(prefix.parent,prefix.name)
        if common._digest(retained)!=prefix.name or not raw.startswith(retained):
            raise common.SwingResearchError("benchmark_original_comparison_prefix_changed")
    for line in raw.splitlines():
        row=json.loads(line)
        if (row.get("record_hash")!=common._hash({k:v for k,v in row.items() if k!="record_hash"}) or row.get("previous_hash")!=previous
                or row.get("comparison_id") in seen or common._aware(row["recorded_at"])>current
                or any(row.get(k)!=v for k,v in AUTHORITY.items())):
            raise common.SwingResearchError("benchmark_comparison_ledger_integrity_failure")
        rows.append(row);previous=row["record_hash"];seen.add(row["comparison_id"])
    return rows,raw


def _stock_reviews(root,current):
    try:
        from swing_outcome_review import read_reviews
        return {row["outcome_record_hash"]:row for row in read_reviews(root,current)},None
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError,IndexError):return {},"source_bound_stock_outcome_review_store_unverified"


def _qualified_stock_or_etf(record,stock_rows,reviews):
    stock=reviews.get(record["stock_outcome_record_hash"])
    matches=[row for row in stock_rows if row["kind"]=="outcome" and row["ticker"]==record["benchmark"]
             and row["entry_method"]=="benchmark_future_open"
             and row["horizon_sessions"]==record["horizon_sessions"] and row.get("forward_bars")==record["benchmark_forward_bars"]
             and row.get("status")!="correction_review_required"]
    # The existing writer independently validates issuer/exchange original bytes,
    # explicit no-action judgment, complete signal/forward coverage and clocks.
    # Its corporate-action coverage can cover a later same-day paired entry;
    # the old ETF open-to-close PERFORMANCE is never reused for that arithmetic.
    reviewed=[reviews[row["record_hash"]] for row in matches if row["record_hash"] in reviews
              and reviews[row["record_hash"]]["coverage_from"]<=record["entry_session"]
              and reviews[row["record_hash"]]["coverage_through"]==record["exit_session"]]
    benchmark=reviewed[0] if reviewed else None
    return stock,benchmark


def _annotate(root,records,stock_rows,current):
    reviews,dependency=_stock_reviews(root,current);result=[]
    try:
        from swing_benchmark_review import read_reviews
        forward_reviews={row["comparison_record_hash"]:row for row in read_reviews(root,current)}
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError,IndexError):
        forward_reviews={};dependency="source_bound_benchmark_forward_review_store_unverified"
    for record in records:
        stock,benchmark=_qualified_stock_or_etf(record,stock_rows,reviews)
        forward_review=forward_reviews.get(record.get("record_hash"))
        benchmark=forward_review or benchmark
        row=copy.deepcopy(record)
        row["reviewed_fixed_path_comparison"]=bool(stock and benchmark)
        row["review_status"]="source_bound_reviewed_fixed_path_only" if stock and benchmark else "raw_unreviewed"
        row["qualification_dependencies"]=[name for name,value in (("stock_corporate_action_review_required",stock),("benchmark_distribution_and_corporate_action_review_required",benchmark)) if not value]
        row["stock_review_record_hash"]=stock.get("record_hash") if stock else None
        row["benchmark_review_record_hash"]=benchmark.get("record_hash") if benchmark else None
        row["benchmark_review_use"]=("independent_forward_window_only_action_review_stock_setup_history_not_cleared" if forward_review
                                     else "exact_forward_window_corporate_action_coverage_only_not_original_ETF_return"
                                     if benchmark else None)
        result.append(row)
    return result,dependency


def _group(records):
    groups=[]
    keys=sorted({(row["benchmark"],row["entry_method"],row["horizon_sessions"],row["cohort"],row["regime"]["classification"]) for row in records})
    for benchmark,method,horizon,cohort,regime in keys:
        rows=[row for row in records if (row["benchmark"],row["entry_method"],row["horizon_sessions"],row["cohort"],row["regime"]["classification"])==(benchmark,method,horizon,cohort,regime)]
        reviewed=[row for row in rows if row["reviewed_fixed_path_comparison"]]
        raw=[row for row in rows if not row["reviewed_fixed_path_comparison"]]
        groups.append({"benchmark":benchmark,"entry_method":method,"horizon_sessions":horizon,"cohort":cohort,"regime":regime,
                       "raw_pairs":len(rows)-len(reviewed),"reviewed_pairs":len(reviewed),"matched_pairs":len(rows),
                       "raw_mean_excess_price_path_pct_by_cost_bps":{str(cost):round(mean(row["raw_excess_price_path_pct_points_by_cost_bps"][str(cost)] for row in raw),6) if raw else None for cost in [10,25,50]},
                       "reviewed_mean_excess_price_path_pct_by_cost_bps":{str(cost):round(mean(row["raw_excess_price_path_pct_points_by_cost_bps"][str(cost)] for row in reviewed),6) if reviewed else None for cost in [10,25,50]}})
    return groups


def _attempt(root,meaning,current):
    identity=common._hash(meaning);path=root/OUTPUT/"attempts"/(identity+".json")
    if path.exists():
        if json.loads(path.read_bytes())["meaning"]!=meaning:raise common.SwingResearchError("benchmark_attempt_history_unverified")
        return
    common._retain(path,common._json_bytes({"recorded_at":current.isoformat(),"meaning":meaning,**AUTHORITY}))


def build(root,current,*,capture=False,paired_context=None):
    root,current=Path(root),common._aware(current)
    try:
        policy,policy_raw=_policy(root,current);implementation=_implementation()
        stock_rows,stock_source,stock_raw=_stock_state(root,current)
        pairs=_pairs(root,current,paired_context);cache={};dependencies=Counter()
        for dependency in pairs.get("dependencies",[]):
            dependencies[dependency.get("reason","source_bound_paired_benchmark_marks_required")]+=1
        if pairs.get("failure"):dependencies[pairs["failure"]]+=1
        observations={row["observation_id"]:row for row in stock_rows if row["kind"]=="observation" and row["common_stock"]}
        outcomes=[row for row in stock_rows if row["kind"]=="outcome" and row["observation_id"] in observations]
        expected=[]
        for outcome in outcomes:
            for benchmark in policy["benchmarks"]:
                try:expected.append(_derive(root,observations[outcome["observation_id"]],outcome,benchmark,policy,implementation,pairs,cache))
                except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError,IndexError) as exc:
                    dependencies[str(exc) if isinstance(exc,common.SwingResearchError) else "benchmark_source_or_pair_unverified"]+=1
        lock=common.ExclusiveFileLock(root/OUTPUT/"comparison.lock") if capture else None
        if lock:lock.__enter__()
        try:
            rows,before=_comparison_ledger(root,current);by_id={row["comparison_id"]:row for row in rows};prior=len(rows)
            definitions={row["comparison_id"]:row for row in expected}
            for row in rows:
                canonical=definitions.get(row["comparison_id"])
                if canonical is None or canonical!={k:v for k,v in row.items() if k not in {"recorded_at","record_hash","previous_hash"}}:
                    raise common.SwingResearchError("benchmark_retained_comparison_source_or_protocol_changed")
            for record in expected:
                if record["comparison_id"] not in by_id:
                    value={**record,"recorded_at":current.isoformat()}
                    if capture:common._chain(rows,value);by_id[record["comparison_id"]]=rows[-1]
                    else:by_id[record["comparison_id"]]=value
            annotated,review_dependency=_annotate(root,list(by_id.values()),stock_rows,current)
            if review_dependency:dependencies[review_dependency]+=1
            for record in annotated:
                for reason in record["qualification_dependencies"]:dependencies[reason]+=1
            stock_ids={row["record_hash"] for row in outcomes};matched={row["stock_outcome_record_hash"] for row in annotated}
            reviewed=[row for row in annotated if row["reviewed_fixed_path_comparison"]]
            unique_entries={(row["observation_id"],row.get("window_id")) for row in stock_rows if row["kind"] in {"window_evaluation","delay_evaluation"} and (row.get("first_qualifying_entry") is True or row["kind"]=="delay_evaluation" and row["state"]=="condition_observed")}
            genuine_entries=[row for row in stock_rows if row["kind"]=="window_evaluation" and row.get("first_qualifying_entry") is True or row["kind"]=="delay_evaluation" and row["state"]=="condition_observed"]
            entry_keys=lambda row:(row["observation_id"],row.get("window_id"),row.get("entry_method"),row.get("delay_minutes"))
            entered_keys={entry_keys(row) for row in genuine_entries}
            nonqualifying=[row for row in stock_rows if row["kind"] in {"window_evaluation","delay_evaluation"} and row["state"]!="condition_observed"]
            paired_ids={row["entry_observation_record_hash"] for row in pairs.get("pairs",[])}
            paired_entries=sum(row["record_hash"] in paired_ids for row in genuine_entries)
            pending=max(0,(len(observations)+len(genuine_entries))*3-len(outcomes))
            missed=len({entry_keys(row) for row in nonqualifying}-entered_keys)
            summary={"stock_observations":len(observations),"technical_selected_observations":sum(any(row["features"]["selected"].values()) for row in observations.values()),
                     "unique_stock_outcomes":len(stock_ids),"unique_matched_stock_outcomes":len(matched),"comparison_pairs":len(annotated),
                     "raw_pairs":len(annotated)-len(reviewed),"reviewed_pairs":len(reviewed),"unique_reviewed_stock_outcomes":len({row["stock_outcome_record_hash"] for row in reviewed}),
                     "pending_stock_horizons":pending,"unmatched_pairs":len(outcomes)*2-len(annotated),"missed_or_skipped_windows":missed,
                     "nonqualifying_window_transitions":len(nonqualifying),"genuine_entry_count":len(genuine_entries),
                     "paired_entry_count":paired_entries,"unpaired_entry_count":len(genuine_entries)-paired_entries,
                     "unique_setup_windows":len(unique_entries),"prospective_matched_pairs":sum(row["design_timing"]=="prospective_protocol_before_entry" for row in annotated),
                     "qualified_strategy_paths":0,"distinct_source_sessions":len({row["source_session"] for row in observations.values()})}
            status="reviewed_comparisons_available" if reviewed else "raw_comparisons_available" if annotated else "pending_forward_evidence"
            view={"schema_version":SCHEMA,"generated_at":current.isoformat(),"status":status,
                  "protocol":{"version":VERSION,"sha256":common._digest(policy_raw),"registered_at":policy["registered_at"],"benchmarks":["SPY","QQQM"],"horizons":[5,10,14],"costs_bps":[10,25,50],"implementation_sha256":implementation},
                  "stock_source":{**stock_source,"observations":len(observations),"outcomes":len(outcomes)},"summary":summary,"groups":_group(annotated),
                  "paired_observation_sources":pairs.get("source_bindings",[]),
                  "supplemental_poll":pairs.get("poll"),
                  "dependencies":[{"code":key,"count":value} for key,value in sorted(dependencies.items())],
                  "comparisons":[{key:row.get(key) for key in ("comparison_id","ticker","benchmark","entry_method","horizon_sessions","entry_session","exit_session","review_status","design_timing","regime","raw_excess_price_path_pct_points_by_cost_bps")} for row in annotated[:12]],
                  "comparison_list_truncated":max(0,len(annotated)-12),"profitability_established":False,"reliable_win_rate":None,
                  "interpretation":"Matched normalized fixed-horizon price paths and equal per-side cost sensitivities. Excess is a percentage-point difference, not alpha, total return, portfolio profit or execution. Two benchmarks, overlapping horizons and delays are not independent trades. Reviewed means require joint exact source-bound action reviews; risk-managed strategy qualification remains zero.",**AUTHORITY}
            after=before+b"".join(common._json_bytes(row) for row in rows[prior:]) if capture else before
            view["comparison_source"]={"path":str(OUTPUT/"comparisons.jsonl"),"sha256":common._digest(after),"records":len(rows)}
            view["projection_recorded"]=capture;view["projection_sha256"]=common._hash(view)
            if capture:
                registration={"version":VERSION,"policy_sha256":common._digest(policy_raw),"implementation_sha256":implementation}
                common._retain(root/OUTPUT/"protocols"/VERSION/common._digest(policy_raw),policy_raw)
                common._retain(root/OUTPUT/"registration.json",common._json_bytes(registration))
                common._retain(root/OUTPUT/"stock_prefixes"/stock_source["sha256"],stock_raw)
                for value in cache.values():
                    if isinstance(value,tuple):
                        _,source=value;raw=_safe(root,source["path"]);common._retain(root/OUTPUT/"input_history"/source["sha256"],raw)
                common._append(root/OUTPUT/"comparisons.jsonl",before,rows[prior:])
                common._retain(root/OUTPUT/"comparison_prefixes"/common._digest(after),after)
                _attempt(root,{"stock_source":stock_source,"policy_sha256":common._digest(policy_raw),"comparison_ids":sorted(by_id)},current)
                common._retain(root/OUTPUT/"projections"/(view["projection_sha256"]+".json"),common._json_bytes(view))
            return view
        finally:
            if lock:lock.__exit__(None,None,None)
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError,IndexError) as exc:
        reason=str(exc) if isinstance(exc,common.SwingResearchError) else "benchmark_source_or_private_history_unverified"
        if capture:
            try:_attempt(root,{"status":"failed","reason":reason},current)
            except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError,IndexError):reason+=";benchmark_attempt_history_unavailable"
        return {"schema_version":SCHEMA,"generated_at":current.isoformat(),"status":"unavailable","summary":{},"groups":[],"comparisons":[],"dependencies":[{"code":reason,"count":1}],"profitability_established":False,"reliable_win_rate":None,**AUTHORITY}


def revalidate_projection(root,view,current):
    root,current=Path(root),common._aware(current)
    try:
        if (view.get("schema_version")!=SCHEMA or any(view.get(k)!=v for k,v in AUTHORITY.items())
                or view.get("projection_sha256")!=common._hash({k:v for k,v in view.items() if k!="projection_sha256"})
                or common._aware(view["generated_at"])>current):raise common.SwingResearchError("benchmark_projection_unverified")
        if view.get("projection_recorded") is not True or json.loads(_safe(root,OUTPUT/"projections"/(view["projection_sha256"]+".json")))!=view:
            raise common.SwingResearchError("benchmark_projection_receipt_unverified")
        prefix=_safe(root,OUTPUT/"comparison_prefixes"/view["comparison_source"]["sha256"])
        actual=_safe(root,OUTPUT/"comparisons.jsonl") if (root/OUTPUT/"comparisons.jsonl").exists() else b""
        if common._digest(prefix)!=view["comparison_source"]["sha256"] or not actual.startswith(prefix):
            raise common.SwingResearchError("benchmark_projection_comparison_prefix_changed")
        current_view=build(root,current,capture=False)
        if current_view["status"]=="unavailable":return current_view
        if current_view["protocol"]!=view["protocol"]:raise common.SwingResearchError("benchmark_projection_protocol_changed")
        result=copy.deepcopy(view)
        result.update(read_time_summary=current_view["summary"],read_time_groups=current_view["groups"],read_time_dependencies=current_view["dependencies"],
                      read_time_supplemental_poll=current_view.get("supplemental_poll"),
                      read_time_comparison_status="independent_source_rederivation_no_new_capture",
                      read_time_proof={"generated_at":current.isoformat(),"stock_ledger_sha256":current_view["stock_source"]["sha256"],
                                       "comparison_ledger_sha256":common._digest(_safe(root,OUTPUT/"comparisons.jsonl")) if (root/OUTPUT/"comparisons.jsonl").exists() else None,
                                       "protocol_sha256":current_view["protocol"]["sha256"],"original_projection_sha256":view["projection_sha256"]})
        return result
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError,IndexError) as exc:
        return {"schema_version":SCHEMA,"status":"unavailable","summary":{},"groups":[],"dependencies":[{"code":str(exc) if isinstance(exc,common.SwingResearchError) else "benchmark_projection_unverified","count":1}],"profitability_established":False,**AUTHORITY}
