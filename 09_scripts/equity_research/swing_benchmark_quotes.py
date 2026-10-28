"""Supplemental paired SPY/QQQM last sales for genuine V2 entry observations.

This collector never changes the frozen strategy, held quote pointer, account,
research slots or capital. Historical pairs are dated research measurements,
not executable quotes or fills. A missing pair is never replaced by an open.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote

from daily_common import ExclusiveFileLock, atomic_write_json, now_et
import intraday_prices as feed
import swing_candidate_quotes as stocks
import swing_observer as observer
import swing_research_v2 as study

REL = "03_source_data/equity_research/swing_benchmark_quotes.local"
SCHEMA = "equity_swing_benchmark_pairs_v1"
BENCHMARKS = {"SPY": "etf", "QQQM": "etf"}
MIN_REMAINING_SECONDS = 28
MAX_ENTRY_TARGETS = 12
MAX_PAIR_SPAN_SECONDS = 120
AUTHORITY = {"research_only": True, "capital_authority": False,
             "actionable_quantity": 0, "execution_quote": False,
             "fully_passed_research": False, "research_slot_consumed": False,
             "email_sent": False, "trade_placed": False}


def _bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n").encode()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _retain(root, folder, raw, suffix="json"):
    digest = _hash(raw)
    relative = f"{REL}/{folder}/{digest}.{suffix}"
    path = feed._safe_target(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("benchmark_immutable_source_conflict") from None
    else:
        with os.fdopen(descriptor,"wb") as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return {"path": relative, "sha256": digest}


def _read(root, binding, folder):
    digest = binding.get("sha256")
    if (not isinstance(digest,str) or not re.fullmatch(r"[a-f0-9]{64}",digest)
            or binding.get("path") != f"{REL}/{folder}/{digest}.json"):
        raise ValueError("benchmark_source_locator_invalid")
    raw=feed._safe_target(root,binding["path"]).read_bytes()
    if _hash(raw)!=digest:raise ValueError("benchmark_source_hash_changed")
    return json.loads(raw)


def _entries(root,current):
    rows=study._load(root,current)
    study._verify(root,rows)
    observations={row["observation_id"]:row for row in rows if row["kind"]=="observation"}
    entries={row["record_hash"]:row for row in rows if
        (row["kind"]=="window_evaluation" and row.get("first_qualifying_entry") is True and row["state"]=="condition_observed")
        or (row["kind"]=="delay_evaluation" and row["state"]=="condition_observed")}
    return entries,observations


def _window(entry,observation):
    windows=[w for w in observation["review_windows"] if w["id"]==entry["window_id"]]
    if len(windows)!=1:raise ValueError("benchmark_entry_window_unverified")
    return windows[0]


def _eligible(entry,observation,current):
    window=_window(entry,observation)
    begins,ends=feed._stamp(window["starts_at"]),feed._stamp(window["ends_at"])
    recorded=feed._stamp(entry["recorded_at"])
    mark=entry["quote_observation"]
    trade,observed=feed._stamp(mark["trade_at"]),feed._stamp(mark["observed_at"])
    if (not begins<=recorded<=current<ends or not begins<=trade<=observed<=recorded
            or (current-trade).total_seconds()>MAX_PAIR_SPAN_SECONDS):
        raise ValueError("benchmark_entry_clock_not_pairable_without_replay")
    return window


def _archive(root,value):
    baseline=value["baseline"]
    sources={item["path"]:item["sha256"] for item in baseline["source_bindings"]}
    sources[baseline["path"]]=baseline["sha256"]
    archives=[]
    for relative,digest in sorted(sources.items()):
        raw=feed._safe_target(root,relative).read_bytes()
        if _hash(raw)!=digest:raise ValueError("benchmark_baseline_changed_before_archive")
        retained=_retain(root,"input_history",raw,"bin")
        archives.append({"original_path":relative,"sha256":digest,"archive_path":retained["path"]})
    baseline["input_archives"]=archives


@contextmanager
def _historical_root(root,value):
    baseline=value["baseline"]
    required={item["path"]:item["sha256"] for item in baseline["source_bindings"]}
    required[baseline["path"]]=baseline["sha256"]
    seen={}
    with tempfile.TemporaryDirectory(prefix="equity-benchmark-history-") as directory:
        frozen=Path(directory)
        for item in baseline.get("input_archives",[]):
            relative,digest=item["original_path"],item["sha256"]
            if (not re.fullmatch(r"[a-f0-9]{64}",str(digest)) or relative in seen
                    or item["archive_path"]!=f"{REL}/input_history/{digest}.bin"):
                raise ValueError("benchmark_archive_locator_invalid")
            source=feed._safe_target(root,item["archive_path"])
            if _hash(source.read_bytes())!=digest:raise ValueError("benchmark_baseline_archive_changed")
            target=feed._safe_target(frozen,relative);target.parent.mkdir(parents=True,exist_ok=True)
            os.link(source,target);seen[relative]=digest
        if seen!=required:raise ValueError("benchmark_baseline_archive_scope_invalid")
        yield frozen


def _validate_batch(root,value,current):
    if (value.get("schema_version")!=SCHEMA or any(value.get(k)!=v for k,v in AUTHORITY.items())
            or set(value.get("rows",{}))!=set(BENCHMARKS)
            or value.get("status")!="complete_pair" or value.get("failures")
            or [row.get("ticker") for row in value.get("attempts",[])]!=list(BENCHMARKS)):
        raise ValueError("benchmark_complete_pair_required")
    generated=feed._stamp(value["generated_at"])
    if generated>current or not feed.market_open(generated):raise ValueError("benchmark_collection_clock_unverified")
    with _historical_root(root,value) as frozen:
        closes,baseline=stocks._baselines(frozen,BENCHMARKS,feed._stamp(value["baseline"]["observed_at"]))
    if ({k:v for k,v in value["baseline"].items() if k not in {"observed_at","input_archives"}}
            != {k:v for k,v in baseline.items() if k!="observed_at"}):
        raise ValueError("benchmark_baseline_reconstruction_mismatch")
    result={}
    for ticker,row in value["rows"].items():
        source=row["source"]
        http=json.loads(feed._source_bytes(root,source,"http_receipts"))
        raw=feed._source_bytes(root,http["response"],"responses")
        url=f"https://api.nasdaq.com/api/quote/{quote(ticker,safe='.-')}/info?assetclass=etf"
        if (http.get("schema_version")!="equity_intraday_http_receipt_v1" or http.get("ticker")!=ticker
                or http.get("asset_class")!="etf" or http.get("http_status")!=200 or http.get("error")
                or http.get("source_url")!=url or source.get("source_url")!=url or row.get("source_url")!=url
                or http.get("response")!=source.get("response") or http.get("response_truncated") is not False
                or http.get("response_bytes_read")!=len(raw) or len(raw)>2_000_000
                or http.get("observed_at")!=source.get("observed_at")):
            raise ValueError("benchmark_HTTP_source_binding_invalid")
        requested,observed=feed._stamp(http["requested_at"]),feed._stamp(http["observed_at"])
        if not feed._stamp(value["baseline"]["observed_at"])<=requested<=observed<=generated:
            raise ValueError("benchmark_HTTP_clock_unverified")
        normalized=feed.normalize(json.loads(raw),ticker,"etf",closes[ticker],observed,generated)
        expected={**normalized,"source":source,"source_url":url,"previous_close_session":baseline["market_session"]}
        if row!=expected:raise ValueError("benchmark_raw_normalization_mismatch")
        result[ticker]={**row,"requested_at":http["requested_at"]}
    if feed._trade_span(result)>feed.MAX_BATCH_TRADE_SPAN_SECONDS:
        raise ValueError("benchmark_pair_timestamp_skew")
    return result


def _pair(entry,observation,marks,collected,binding):
    window=_eligible(entry,observation,collected)
    start,end=feed._stamp(window["starts_at"]),feed._stamp(window["ends_at"])
    captured=feed._stamp(entry["recorded_at"])
    stock=entry["quote_observation"]
    times=[feed._stamp(stock["trade_at"])]
    for mark in marks.values():
        if (not captured<=feed._stamp(mark["requested_at"])<=feed._stamp(mark["observed_at"])<end
                or not start<=feed._stamp(mark["trade_at"])<end):
            raise ValueError("benchmark_pair_outside_original_capture_window")
        times.append(feed._stamp(mark["trade_at"]))
    span=(max(times)-min(times)).total_seconds()
    if span>MAX_PAIR_SPAN_SECONDS:raise ValueError("stock_benchmark_trade_clocks_not_matched")
    return dict(entry_observation_record_hash=entry["record_hash"],observation_id=entry["observation_id"],
        ticker=entry["ticker"],source_session=observation["source_session"],valid_session=observation["valid_session"],
        entry_method=entry["entry_method"],window_id=entry["window_id"],delay_minutes=entry.get("delay_minutes"),
        stock_quote=stock,benchmarks=marks,collected_at=collected.isoformat(),source=binding,
        pair_max_span_seconds=span,**AUTHORITY)


def collect(root,*,current=None,remaining_seconds=0,client=None,clock=now_et,monotonic=time.monotonic):
    """Supplement a completed observer run under newly acquired NB locks."""
    root=Path(root);current=feed._now(current or clock())
    result=dict(schema_version=SCHEMA,status="no_new_entry_observations",request_count=0,paired_entries=0,**AUTHORITY)
    if remaining_seconds<MIN_REMAINING_SECONDS:
        return dict(result,status="deferred_remaining_worker_budget",remaining_seconds=max(0,remaining_seconds))
    if not observer.due_window(current):return dict(result,status="outside_review_window")
    started=monotonic();deadline=started+remaining_seconds-2
    with ExitStack() as locks:
        try:
            locks.enter_context(ExclusiveFileLock(root.parent/".locks/equity-research-runtime.lock"))
            locks.enter_context(ExclusiveFileLock(root/"00_project_control/run_logs/daily_pipeline.lock"))
        except RuntimeError:return dict(result,status="deferred_mutation_lock")
        actual=feed._now(clock())
        if not observer.due_window(actual) or observer.active_claim(root,actual):
            return dict(result,status="deferred_changed_window_or_active_claim")
        observer._configuration(root)
        entries,observations=_entries(root,actual)
        pending=[]
        for key,entry in entries.items():
            if feed._safe_target(root,f"{REL}/requests/{key}.json").exists():continue
            try:_eligible(entry,observations[entry["observation_id"]],actual)
            except (ValueError,KeyError,TypeError):continue
            pending.append(entry)
        pending.sort(key=lambda row:(row["recorded_at"],row["record_hash"]))
        pending=pending[:MAX_ENTRY_TARGETS]
        if not pending:return result
        if deadline-monotonic()<MIN_REMAINING_SECONDS-3:return dict(result,status="deferred_remaining_worker_budget")
        closes,baseline=stocks._baselines(root,BENCHMARKS,actual)
        value=dict(schema_version=SCHEMA,generated_at=actual.isoformat(),baseline=baseline,rows={},attempts=[],
                   entries=[row["record_hash"] for row in pending],failures={},**AUTHORITY)
        # Reserve before HTTP: interruption is retained and never retried as if
        # it were the original stock observation at a later price.
        for entry in pending:
            path=feed._safe_target(root,f"{REL}/requests/{entry['record_hash']}.json")
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("xb") as stream:stream.write(_bytes({"entry_record_hash":entry["record_hash"],"requested_at":actual.isoformat(),**AUTHORITY}))
        _archive(root,value)
        client=client or feed.NasdaqIntradayClient(root)
        # The last stock request completed before its V2 entry capture. Keep at
        # least the existing one-second public-provider cadence across clients.
        since_stock=(feed._now(clock())-max(feed._stamp(row["recorded_at"]) for row in pending)).total_seconds()
        if since_stock<1:time.sleep(max(0,1-since_stock))
        for ticker in BENCHMARKS:
            if deadline-monotonic()<10:
                value["failures"][ticker]="benchmark_shared_worker_budget_exhausted";break
            result["request_count"]+=1
            try:
                payload,source=client.fetch(ticker,"etf")
                value["attempts"].append({"ticker":ticker,**source})
                if source.get("error"):raise ValueError(source["error"])
                observed=feed._stamp(source["observed_at"]);effective=feed._now(clock())
                mark=feed.normalize(payload,ticker,"etf",closes[ticker],observed,effective)
                value["rows"][ticker]={**mark,"source":source,"source_url":source["source_url"],"previous_close_session":baseline["market_session"]}
            except (OSError,ValueError,KeyError,TypeError) as exc:value["failures"][ticker]=str(exc) if isinstance(exc,ValueError) else "benchmark_provider_attempt_failed"
        value["generated_at"]=feed._now(clock()).isoformat()
        value["status"]="complete_pair" if set(value["rows"])==set(BENCHMARKS) and not value["failures"] else "unavailable_pair"
        binding=_retain(root,"snapshots",_bytes(value))
        try:marks=_validate_batch(root,value,feed._now(clock()))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            marks=None;failure=next(iter(value["failures"].values()),str(exc))
        for entry in pending:
            reason=None
            try:
                if marks is None:raise ValueError(failure)
                _pair(entry,observations[entry["observation_id"]],marks,feed._stamp(value["generated_at"]),binding)
            except (ValueError,KeyError,TypeError) as exc:reason=str(exc)
            result["paired_entries"]+=int(reason is None)
            completion={"entry_record_hash":entry["record_hash"],"source":binding,"status":"paired" if reason is None else "dependency",
                        "reason":reason,"completed_at":value["generated_at"],**AUTHORITY}
            path=feed._safe_target(root,f"{REL}/completions/{entry['record_hash']}.json");path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("xb") as stream:stream.write(_bytes(completion))
        result["status"]="paired" if result["paired_entries"] else "waiting_on_paired_observations"
        return result


def admitted_pairs(root,current):
    """Revalidate dated pair measurements without reviving a current mark."""
    root,current=Path(root),feed._now(current)
    result=dict(schema_version=SCHEMA,status="waiting_on_paired_observations",pairs=[],dependencies=[],source_bindings=[],**AUTHORITY)
    try:entries,observations=_entries(root,current)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError):return dict(result,status="unavailable",failure="source_bound_v2_entry_ledger_unverified")
    batches={}
    for key,entry in entries.items():
        try:
            path=feed._safe_target(root,f"{REL}/completions/{key}.json")
            if not path.exists():
                request=feed._safe_target(root,f"{REL}/requests/{key}.json")
                raise ValueError("benchmark_attempt_interrupted_no_completion" if request.exists() else "paired_benchmark_observation_not_recorded")
            completion=json.loads(path.read_bytes())
            if (completion.get("entry_record_hash")!=key or any(completion.get(k)!=v for k,v in AUTHORITY.items())):
                raise ValueError("benchmark_completion_binding_unverified")
            value=_read(root,completion["source"],"snapshots")
            request_path=feed._safe_target(root,f"{REL}/requests/{key}.json")
            request=json.loads(request_path.read_bytes())
            if (request.get("entry_record_hash")!=key or any(request.get(k)!=v for k,v in AUTHORITY.items())
                    or not feed._stamp(entry["recorded_at"])<=feed._stamp(request["requested_at"])<=feed._stamp(value["generated_at"])
                    or completion.get("completed_at")!=value["generated_at"]):
                raise ValueError("benchmark_request_completion_chronology_unverified")
            if key not in value["entries"]:raise ValueError("benchmark_original_entry_not_bound")
            if completion.get("status")!="paired":
                raise ValueError(completion.get("reason") or "benchmark_completion_unavailable")
            digest=completion["source"]["sha256"]
            if digest not in batches:batches[digest]=_validate_batch(root,value,current)
            marks=batches[digest]
            pair=_pair(entry,observations[entry["observation_id"]],marks,feed._stamp(value["generated_at"]),completion["source"])
            if completion.get("status")!="paired" or completion.get("reason") is not None:
                raise ValueError(completion.get("reason") or "benchmark_completion_unavailable")
            result["pairs"].append(pair)
            for source in (completion["source"],{"path":str(path.relative_to(root)),"sha256":_hash(path.read_bytes())},
                           {"path":str(request_path.relative_to(root)),"sha256":_hash(request_path.read_bytes())}):
                if source not in result["source_bindings"]:result["source_bindings"].append(source)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            result["dependencies"].append({"entry_observation_record_hash":key,"ticker":entry["ticker"],"reason":str(exc)})
    if result["pairs"]:result["status"]="paired"
    return result


def after_observer(root, *, remaining_seconds, observer_result=None, current=None, clock=now_et, collector=None):
    """Persist the separate supplemental outcome, including budget deferrals.

    Collection alone requires the existing runtime/pipeline locks. This isolated
    immutable operational audit can record why those locks could not be taken;
    it never rewrites the original observer receipt or its study observations.
    """
    root=Path(root);started=feed._now(current or clock())
    try:
        value=(collector or collect)(root,current=started,clock=clock,remaining_seconds=remaining_seconds)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        reason=str(exc) if isinstance(exc,(ValueError,RuntimeError)) and re.fullmatch(r"[a-z][a-z0-9_]{0,179}",str(exc)) else "paired_benchmark_source_or_admission_unverified"
        value=dict(status="unavailable",failure=reason,request_count=None,paired_entries=0,**AUTHORITY)
    original_source=None
    try:
        pointer=json.loads(feed._safe_target(root,f"{observer.REL}/current.json").read_bytes())
        binding=pointer["receipt"]
        if binding["path"]!=f"{observer.REL}/receipts/{binding['sha256']}.json":raise ValueError()
        raw=feed._safe_target(root,binding["path"]).read_bytes()
        if _hash(raw)!=binding["sha256"] or json.loads(raw)!=observer_result:raise ValueError()
        original_source=binding
    except (OSError,ValueError,KeyError,TypeError):pass
    receipt={**value,"schema_version":SCHEMA,"started_at":started.isoformat(),"completed_at":feed._now(clock()).isoformat(),
             "remaining_worker_budget_seconds_at_entry":max(0,remaining_seconds),
             "observer_source":original_source,"observer_source_status":"verified" if original_source else "unverified",
             "observer":{key:(observer_result or {}).get(key) for key in ("status","started_at","completed_at","study_version")},**AUTHORITY}
    binding=_retain(root,"polls",_bytes(receipt))
    atomic_write_json(feed._safe_target(root,f"{REL}/current_poll.json"),dict(source=binding,status=receipt["status"],completed_at=receipt["completed_at"]))
    return {**receipt,"source":binding}


def read_poll(root,current):
    try:
        pointer=json.loads(feed._safe_target(root,f"{REL}/current_poll.json").read_bytes())
        value=_read(root,pointer["source"],"polls")
        if (value.get("schema_version")!=SCHEMA or any(value.get(k)!=v for k,v in AUTHORITY.items())
                or value.get("status")!=pointer.get("status") or value.get("completed_at")!=pointer.get("completed_at")
                or not feed._stamp(value["started_at"])<=feed._stamp(value["completed_at"])<=feed._now(current)):
            raise ValueError()
        if value.get("observer_source_status")=="verified":
            source=value["observer_source"]
            if (source["path"]!=f"{observer.REL}/receipts/{source['sha256']}.json"
                    or _hash(feed._safe_target(root,source["path"]).read_bytes())!=source["sha256"]):
                raise ValueError()
        return {**value,"source":pointer["source"]}
    except (OSError,ValueError,KeyError,TypeError):
        return dict(status="not_yet_verified",failure="supplemental_benchmark_poll_receipt_unverified",**AUTHORITY)
