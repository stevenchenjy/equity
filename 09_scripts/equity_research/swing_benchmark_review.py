"""Source-bound forward-window-only SPY/QQQM action review.

Use --root ROOT --input PROPOSAL to validate, then --apply under documented
runtime/pipeline locks. This writer never reviews the stock signal history,
executes an order, adjusts distributions, or qualifies a managed strategy.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path

import swing_research as common
import swing_benchmarks as benchmark
from swing_outcome_review import _sources

SCHEMA="equity_swing_benchmark_review_v1"
OUTPUT=benchmark.OUTPUT
STORE=OUTPUT/"forward_reviews.jsonl"
AUTHORITY=benchmark.AUTHORITY


def validate(root,proposal,current,*,history_current=None):
    """Validate an exact immutable comparison and two independent official bodies.

    Required proposal: schema_version, comparison_id, comparison_record_hash,
    benchmark, protocol_sha256, benchmark_forward_bars_sha256, pair_source,
    reviewer, reviewed_at, coverage_from/through, sources (existing primary
    evidence schema), reasoning, limitations, corporate_actions=[], conclusion
    and qualifying_method. The original stock leg needs its separate review.
    """
    root,current=Path(root),common._aware(current)
    history_clock=common._aware(history_current) if history_current else current
    if (not isinstance(proposal,dict) or proposal.get("schema_version")!=SCHEMA
            or not isinstance(proposal.get("reviewer"),str) or len(proposal["reviewer"].strip())<3
            or common._aware(proposal["reviewed_at"])>current
            or not isinstance(proposal.get("reasoning"),str) or len(proposal["reasoning"].strip())<160
            or not isinstance(proposal.get("limitations"),str) or len(proposal["limitations"].strip())<80):
        raise common.SwingResearchError("benchmark_review_authored_reasoning_and_clock_required")
    reviewed_at=common._aware(proposal["reviewed_at"])
    records,_=benchmark._comparison_ledger(root,history_clock)
    matches=[row for row in records if row["comparison_id"]==proposal.get("comparison_id")
             and row["record_hash"]==proposal.get("comparison_record_hash")]
    if len(matches)!=1:raise common.SwingResearchError("benchmark_review_exact_immutable_comparison_required")
    record=matches[0]
    if reviewed_at<common._aware(record["recorded_at"]):
        raise common.SwingResearchError("benchmark_review_cannot_predate_comparison")
    policy,raw=benchmark._policy(root,current)
    implementation=benchmark._implementation()
    stock_rows,_,_=benchmark._stock_state(root,history_clock)
    observation=next((row for row in stock_rows if row["record_hash"]==record["stock_observation_record_hash"]),None)
    outcome=next((row for row in stock_rows if row["record_hash"]==record["stock_outcome_record_hash"]),None)
    if observation is None or outcome is None:raise common.SwingResearchError("benchmark_review_stock_source_required")
    expected=benchmark._derive(root,observation,outcome,record["benchmark"],policy,implementation,
                               benchmark._pairs(root,history_clock),{})
    if expected!={key:value for key,value in record.items() if key not in {"recorded_at","record_hash","previous_hash"}}:
        raise common.SwingResearchError("benchmark_review_original_comparison_source_changed")
    bars_hash=common._hash(record["benchmark_forward_bars"])
    if (proposal.get("benchmark")!=record["benchmark"] or record["benchmark"] not in {"SPY","QQQM"}
            or proposal.get("protocol_sha256")!=record["protocol_sha256"]
            or common._digest(raw)!=record["protocol_sha256"] or record["implementation_sha256"]!=implementation
            or proposal.get("benchmark_forward_bars_sha256")!=bars_hash
            or proposal.get("pair_source")!=record["pair_source"]):
        raise common.SwingResearchError("benchmark_review_exact_protocol_path_pair_binding_required")
    start,end=record["entry_session"],common.regular_close(record["exit_session"])
    if (reviewed_at<end or proposal.get("coverage_from")!=start
            or proposal.get("coverage_through")!=record["exit_session"]):
        raise common.SwingResearchError("benchmark_review_complete_forward_window_required")
    if (proposal.get("corporate_action_conclusion")!="no_actions_identified_after_source_bound_forward_review"
            or proposal.get("corporate_actions")!=[]):
        raise common.SwingResearchError("benchmark_review_forward_split_distribution_adjustment_requires_supported_method")
    if proposal.get("qualifying_method")!="source_bound_analyst_review_of_benchmark_forward_price_path_only":
        raise common.SwingResearchError("benchmark_review_qualification_scope_invalid")
    # Reuse the established independent issuer/SEC + exchange evidence gate.
    # The explicit ticker here is the ETF, never the original stock symbol.
    evidence={**proposal,"ticker":record["benchmark"]}
    raws=_sources(root,evidence,reviewed_at,start,end)
    result={"schema_version":SCHEMA,"recorded_at":current.isoformat(),"reviewed_at":proposal["reviewed_at"],
            "reviewer":proposal["reviewer"],"comparison_id":record["comparison_id"],"comparison_record_hash":record["record_hash"],
            "benchmark":record["benchmark"],"protocol_sha256":record["protocol_sha256"],"implementation_sha256":implementation,
            "stock_outcome_record_hash":record["stock_outcome_record_hash"],"benchmark_forward_bars_sha256":bars_hash,
            "pair_source":record["pair_source"],"entry_method":record["entry_method"],"entry_session":start,"exit_session":record["exit_session"],
            "coverage_from":start,"coverage_through":record["exit_session"],"qualification_scope":"source_bound_reviewed_benchmark_forward_price_path_only",
            "source_bound_analyst_judgment":True,"mechanical_proof_of_no_corporate_actions":False,
            "original_stock_setup_history_cleared":False,"stock_leg_review_still_required":True,
            "risk_managed_strategy_performance_qualified":False,"actual_fill_or_account_return":False,
            "sources":proposal["sources"],"reasoning":proposal["reasoning"],"limitations":proposal["limitations"],
            "proposal_sha256":common._hash(proposal),"profitability_established":False,**AUTHORITY}
    return result,raws


def read_reviews(root,current):
    root,current=Path(root),common._aware(current)
    if not (root/STORE).exists():return []
    rows=[];previous="";seen=set()
    for line in benchmark._safe(root,STORE).splitlines():
        row=json.loads(line)
        if (row.get("record_hash")!=common._hash({key:value for key,value in row.items() if key!="record_hash"})
                or row.get("previous_hash")!=previous or row.get("proposal_sha256") in seen
                or common._aware(row["recorded_at"])>current or any(row.get(key)!=value for key,value in AUTHORITY.items())):
            raise common.SwingResearchError("benchmark_forward_review_history_integrity_failure")
        raw=benchmark._safe(root,OUTPUT/"forward_review_inputs"/row["proposal_sha256"])
        proposal=json.loads(raw)
        if common._hash(proposal)!=row["proposal_sha256"]:raise common.SwingResearchError("benchmark_forward_review_proposal_changed")
        expected,_=validate(root,proposal,common._aware(row["recorded_at"]),history_current=current)
        if expected!={key:value for key,value in row.items() if key not in {"record_hash","previous_hash"}}:
            raise common.SwingResearchError("benchmark_forward_review_projection_changed")
        rows.append(row);previous=row["record_hash"];seen.add(row["proposal_sha256"])
    return rows


def review(root,proposal,current,*,apply=False):
    root,current=Path(root),common._aware(current)
    raw=common._json_bytes(proposal);identity=common._hash(proposal)
    try:
        value,sources=validate(root,proposal,current)
        if not apply:return value
        with common.ExclusiveFileLock(root/OUTPUT/"forward_reviews.lock"):
            rows=read_reviews(root,current)
            old=next((row for row in rows if row["proposal_sha256"]==identity),None)
            if old:return old
            for digest,body in sources.items():common._retain(root/OUTPUT/"forward_review_sources"/digest,body)
            common._retain(root/OUTPUT/"forward_review_inputs"/identity,raw)
            before=benchmark._safe(root,STORE) if (root/STORE).exists() else b""
            common._chain(rows,value);common._append(root/STORE,before,[rows[-1]])
            return rows[-1]
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,AttributeError,IndexError) as exc:
        if apply:
            failure={"proposal_sha256":identity,"reason":str(exc) if isinstance(exc,common.SwingResearchError) else "benchmark_forward_review_unverified",**AUTHORITY}
            common._retain(root/OUTPUT/"failed_forward_review_inputs"/identity,raw)
            path=root/OUTPUT/"failed_forward_reviews"/(common._hash(failure)+".json")
            if not path.exists():common._retain(path,common._json_bytes({**failure,"recorded_at":current.isoformat()}))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True);parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--apply",action="store_true");args=parser.parse_args()
    value=review(args.root,json.loads(args.input.read_text()),datetime.now(common.ET),apply=args.apply)
    print(json.dumps(value,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
