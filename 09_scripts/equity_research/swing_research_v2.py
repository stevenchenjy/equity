"""Owner-window swing research. Zero capital; no network, sender or broker path.

V1 code, policy and observations remain untouched. V2 keeps dated daily reference
conditions through the next session's owner windows. Timestamped last sales are
observations, never NBBO or fills. Delayed paths cannot borrow the elapsed open.
"""
from __future__ import annotations

import copy
import csv
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path
import re

import swing_research as old

VERSION = "daily-swing-review-windows-v2-20261028"
SCHEMA = "equity_swing_research_v2"
POLICY = Path("01_policies/swing_research_v2.json")
OUTPUT = Path("08_reviews/swing_research_v2.local")
AUTHORITY = old.AUTHORITY
STRATEGIES = old.STRATEGIES


def _policy(root):
    raw = old._file(root, POLICY)
    value = json.loads(raw)
    if (value.get("schema_version") != "equity_swing_research_policy_v2" or value.get("version") != VERSION
            or any(value.get(k) != v for k, v in AUTHORITY.items())
            or value.get("holding_sessions") != [5, 10, 14] or value.get("one_way_cost_bps") != [10, 25, 50]
            or value.get("delayed_observation_minutes") != [3,5,10] or value.get("commission_per_share_usd") != 0
            or value.get("maximum_gap_r") != .25 or value.get("hypothetical_profit_reference_r") != 2
            or value.get("review_windows") != [{"id": "morning", "start": "09:45", "end": "10:45"},
                                                {"id": "afternoon", "start": "14:45", "end": "15:20"}]
            or value.get("adoption", {}).get("automatic_promotion") is not False):
        raise old.SwingResearchError("swing_v2_policy_unverified")
    return value, raw


def _windows(session, policy, first_seen=None):
    close, result = old.regular_close(session), []
    for row in policy["review_windows"]:
        start = datetime.combine(date.fromisoformat(session), datetime.strptime(row["start"], "%H:%M").time(), tzinfo=old.ET)
        end = datetime.combine(date.fromisoformat(session), datetime.strptime(row["end"], "%H:%M").time(), tzinfo=old.ET)
        start, end = max(start, first_seen) if first_seen else start, min(end, close)
        if start < end:
            result.append({"id": row["id"], "starts_at": start.isoformat(), "ends_at": end.isoformat()})
    return result


def _implementation():
    _, files = old._implementation()
    directory = Path(__file__).resolve().parent
    for name in ("swing_research_v2.py", "swing_outcome_review.py", "swing_candidate_quotes.py", "swing_coverage.py", "swing_candidate_history.py", "intraday_prices.py", "swing_observer.py"):
        if (directory / name).is_file():
            files[name] = (directory / name).read_bytes()
    return old._hash({name: old._digest(raw) for name, raw in sorted(files.items())}), files


def _outside(root, current):
    try:
        from swing_coverage import admitted_histories
        return admitted_histories(root, current, limit=6)
    except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError):
        return {"status": "waiting_on_data", "histories": {}, "blockers": ["outside_current_source_bound_history_required"]}


def _inputs(root, current, outside_context=None):
    policy, policy_raw = _policy(root)
    expected = old.latest_published_market_session(current).isoformat()
    day, required_dates = date.fromisoformat(expected), []
    while len(required_dates) < 51:
        if old.is_us_market_session_date(day): required_dates.append(day.isoformat())
        day -= timedelta(days=1)
    required_dates.reverse()
    raws, series, canonical, blockers, bindings = {str(POLICY): policy_raw}, {}, set(), [], {}
    try:
        _, bundle, canonical_bindings, canonical_raws, _ = old._inputs(root, current)
        raws.update(canonical_raws)
        metadata = {row["ticker"]: row for row in csv.DictReader(io.StringIO(raws[str(old.UNIVERSE)].decode()))}
        for ticker, item in bundle["tickers"].items():
            series[ticker] = {"bars": item["bars"], "price_basis": "unadjusted", "data_source": bundle["data_source"],
                              "canonical": True, "common_stock": ticker in metadata and metadata.get(ticker, {}).get("sector") != "ETF"
                              and metadata.get(ticker, {}).get("is_benchmark") != "yes"}
        canonical = set(series)
        bindings.update(canonical_bindings)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        blockers.append(str(exc) if isinstance(exc, old.SwingResearchError) else "canonical_current_history_unavailable")
    outside = _outside(root, current)
    if outside_context is not None and outside_context != outside:
        raise old.SwingResearchError("swing_outside_context_requires_current_readmission")
    for ticker, item in outside.get("histories", {}).items():
        if ticker in series:
            continue
        try:
            source_bindings = item.get("source_bindings", {})
            if (re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}",ticker) is None or not source_bindings
                    or item.get("price_basis") not in {"unadjusted", "split_adjusted"}
                    or item.get("price_basis") == "split_adjusted" and item.get("basis_consistency_verified") is not True
                    or [bar["session_date"] for bar in item.get("bars", [])[-51:]] != required_dates):
                raise old.SwingResearchError("outside_current_coherent_price_basis_required")
            item_raws={}
            for path, digest in source_bindings.items():
                relative = Path(path)
                if relative.is_absolute() or ".." in relative.parts:
                    raise old.SwingResearchError("swing_outside_source_locator_unverified")
                raw = old._file(root, relative)
                if old._digest(raw) != digest:
                    raise old.SwingResearchError("swing_outside_source_changed")
                item_raws[path] = raw
            for bar in item["bars"]:
                values=[old._number(bar[k]) for k in ("open","high","low","close","volume")]
                if min(values[:4])<=0 or values[4]<0 or not values[2]<=min(values[0],values[3])<=max(values[0],values[3])<=values[1]:
                    raise old.SwingResearchError("outside_ohlcv_invalid")
            series[ticker] = {"bars": item["bars"], "price_basis": item["price_basis"],
                              "data_source": item["data_source"], "canonical": False,
                              "common_stock": item.get("common_stock_verified") is True or item.get("common_stock") is True}
            raws.update(item_raws)
        except (OSError,ValueError,TypeError,KeyError,RuntimeError):
            blockers.append("outside_ticker_history_unverified:"+str(ticker))
    for item in series.values():
        bars = item["bars"]
        if bars[-1]["session_date"] != expected or len({bar["session_date"] for bar in bars}) != len(bars) or [b["session_date"] for b in bars[-51:]] != required_dates:
            raise old.SwingResearchError("swing_v2_current_history_incomplete")
        for bar in bars:
            values = [old._number(bar[k]) for k in ("open", "high", "low", "close", "volume")]
            if min(values[:4]) <= 0 or values[4] < 0 or not values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1]:
                raise old.SwingResearchError("swing_v2_history_ohlcv_invalid")
    if not series:
        raise old.SwingResearchError(blockers[0] if blockers else "swing_v2_current_history_unavailable")
    dataset = {"market_session": expected, "series": series, "canonical_scope": sorted(canonical)}
    dataset_raw = old._json_bytes(dataset)
    implementation, files = _implementation()
    bindings.update(policy_sha256=old._digest(policy_raw), implementation_sha256=implementation,
                    dataset_sha256=old._digest(dataset_raw), market_session=expected, canonical_scope=sorted(canonical),
                    scope=sorted(series), source_hashes={path: old._digest(raw) for path, raw in sorted(raws.items())})
    return policy, dataset, bindings, raws, files, blockers


def _identity(ticker, session):
    return old._hash({"version": VERSION, "ticker": ticker, "session": session})


def _load(root, current):
    path, rows, previous, seen, observations, last = root / OUTPUT / "ledger.jsonl", [], "", set(), {}, None
    if not path.exists():
        return rows
    for raw in old._file(root, OUTPUT / "ledger.jsonl").splitlines():
        row = json.loads(raw)
        key = ((row.get("kind"),row.get("observation_id"),row.get("window_id"),row.get("sequence")) if row.get("kind")=="window_evaluation" else
               (row.get("kind"), row.get("observation_id"), row.get("window_id"), row.get("horizon_sessions"), row.get("entry_method"),row.get("delay_minutes")))
        clock = old._aware(row["recorded_at"])
        if (row.get("record_hash") != old._hash({k: v for k, v in row.items() if k != "record_hash"})
                or row.get("previous_hash") != previous or key in seen or clock > current or last and clock < last
                or row.get("version") != VERSION or any(row.get(k) != v for k, v in AUTHORITY.items())):
            raise old.SwingResearchError("swing_v2_ledger_integrity_failure")
        if row["kind"] == "observation":
            if row["observation_id"] != _identity(row["ticker"], row["source_session"]) or old.regular_close(row["source_session"]) > clock:
                raise old.SwingResearchError("swing_v2_first_capture_unverified")
            observations[row["observation_id"]] = row
        elif row["kind"] not in {"window_evaluation", "delay_evaluation", "outcome"} or row["observation_id"] not in observations:
            raise old.SwingResearchError("swing_v2_record_unbound")
        rows.append(row); seen.add(key); previous, last = row["record_hash"], clock
    return rows


def _verify(root, rows):
    output, datasets, checked, observations, prefix = root / OUTPUT, {}, set(), {}, []
    for row in rows:
        if row["kind"]=="delay_evaluation":
            observation=observations[row["observation_id"]]
            first=next((r for r in prefix if r.get("record_hash")==row.get("first_entry_observation_record_hash") and r.get("first_qualifying_entry") is True),None)
            if first is None or row.get("delay_minutes") not in [3,5,10]:
                raise old.SwingResearchError("swing_v2_delay_observation_unbound")
            policy=json.loads(old._file(output,Path("input_history")/observation["inputs"]["policy_sha256"]))
            context=_quote_context(root,row.get("quote_context"),old._aware(row["recorded_at"]),[row["ticker"]],observation["inputs"],historical=True) if row.get("quote_context") else {"tickers":{}}
            expected=_delay_check(observation,first,row["delay_minutes"],policy,old._aware(row["recorded_at"]),context,prefix)
            if expected is None or expected!={k:v for k,v in row.items() if k not in {"record_hash","previous_hash"}}:
                raise old.SwingResearchError("swing_v2_delay_observation_unverified")
            prefix.append(row);continue
        if row["kind"] == "window_evaluation":
            observation = observations[row["observation_id"]]
            prior_window=[r for r in prefix if r["kind"]=="window_evaluation" and r["observation_id"]==row["observation_id"] and r["window_id"]==row["window_id"]]
            if row.get("sequence")!=len(prior_window)+1 or row.get("first_qualifying_entry") != (row["state"]=="condition_observed" and not any(r.get("first_qualifying_entry") for r in prior_window)):
                raise old.SwingResearchError("swing_v2_window_entry_sequence_unverified")
            if row["state"] == "missed_no_verified_window_observation":
                window = next((w for w in observation["review_windows"] if w["id"] == row["window_id"]), None)
                if window is None or old._aware(window["ends_at"]) > old._aware(row["recorded_at"]) or row.get("quote_observation") is not None:
                    raise old.SwingResearchError("swing_v2_missing_window_chronology_unverified")
                prefix.append(row)
                continue
            context = _quote_context(root, row["quote_context"], old._aware(row["recorded_at"]), [row["ticker"]], observation["inputs"], historical=True)
            policy = json.loads(old._file(output, Path("input_history") / observation["inputs"]["policy_sha256"]))
            expected = _timing(_decorate(observation,prefix,old._aware(row["recorded_at"])), policy, old._aware(row["recorded_at"]), context)
            if (expected["current_quote_status"] != "current" or expected["state"] != row["state"]
                    or expected["quote_observation"] != row["quote_observation"]
                    or expected["current_window"]["id"] != row["window_id"]):
                raise old.SwingResearchError("swing_v2_retained_quote_observation_unverified")
            prefix.append(row)
            continue
        binding = row["inputs"]
        for digest in [binding["policy_sha256"], binding["dataset_sha256"], *binding["source_hashes"].values()]:
            if not isinstance(digest,str) or re.fullmatch(r"[a-f0-9]{64}",digest) is None:
                raise old.SwingResearchError("swing_v2_retained_locator_unverified")
            if digest not in checked:
                if old._digest(old._file(output, Path("input_history") / digest)) != digest:
                    raise old.SwingResearchError("swing_v2_retained_input_changed")
                checked.add(digest)
        implementation = binding["implementation_sha256"]
        if not isinstance(implementation,str) or re.fullmatch(r"[a-f0-9]{64}",implementation) is None:
            raise old.SwingResearchError("swing_v2_retained_locator_unverified")
        if implementation not in checked:
            directory = output / "implementations" / implementation
            files = {path.name: old._digest(old._file(directory,path.name)) for path in directory.glob("*.py")}
            if old._hash(files) != implementation:
                raise old.SwingResearchError("swing_v2_retained_implementation_changed")
            checked.add(implementation)
        if binding["dataset_sha256"] not in datasets:
            datasets[binding["dataset_sha256"]] = json.loads(old._file(output, Path("input_history") / binding["dataset_sha256"]))
        item = datasets[binding["dataset_sha256"]]["series"][row["ticker"]]
        if row["kind"] == "observation":
            if row["bars_at_observation"] != item["bars"][-51:] or row["features"] != old._features(item["bars"]):
                raise old.SwingResearchError("swing_v2_retained_observation_unbound")
            observations[row["observation_id"]] = row
        else:
            policy = json.loads(old._file(output, Path("input_history") / binding["policy_sha256"]))
            if row["entry_method"]=="benchmark_future_open":check=None
            elif row["entry_method"]=="observed_owner_window_mark_not_fill":
                check=next((candidate for candidate in prefix if candidate["kind"]=="window_evaluation" and candidate["observation_id"]==row["observation_id"]
                            and candidate.get("window_id")==row.get("window_id") and candidate.get("first_qualifying_entry") is True),None)
            else:
                check=next((candidate for candidate in prefix if candidate["kind"]=="delay_evaluation" and candidate["observation_id"]==row["observation_id"]
                            and candidate.get("window_id")==row.get("window_id") and candidate.get("delay_minutes")==row.get("delay_minutes") and candidate["state"]=="condition_observed"),None)
            expected = _derive_outcome(observations[row["observation_id"]], check, row["entry_method"], row["horizon_sessions"],
                                       datasets[binding["dataset_sha256"]], binding, policy, old._aware(row["recorded_at"]))
            if expected is None or {k:v for k,v in expected.items() if k not in {"record_hash","previous_hash"}} != {k:v for k,v in row.items() if k not in {"record_hash","previous_hash"}}:
                raise old.SwingResearchError("swing_v2_retained_outcome_calculation_unverified")
        prefix.append(row)


def _quote_context(root, context, current, scope, bindings, *, historical=False):
    try:
        from swing_candidate_quotes import read_quote_context, revalidate_quote_context
        value = context if context is not None else read_quote_context(root, current, scope=scope)
        kwargs = {"scope": scope, "baseline_bindings": bindings}
        if historical:
            kwargs["require_latest"] = False
        return revalidate_quote_context(root, value, current, **kwargs)
    except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError):
        return {"status": "unavailable", "tickers": {}, "failures": {"context": "current_source_bound_candidate_quote_required"}}


def _timing(observation, policy, current, context):
    windows = observation["review_windows"]
    applicable = next((row for row in windows if old._aware(row["starts_at"]) <= current < old._aware(row["ends_at"])), None)
    future = next((row for row in windows if current < old._aware(row["starts_at"])), None)
    state = "within_review_window" if applicable else "before_review_window" if future and current < old._aware(windows[0]["starts_at"]) else "between_review_windows" if future else "expired"
    result = {"state": state, "review_windows": windows, "current_window": applicable,
              "next_window": future, "current_quote_status": "unverified", "quote_observation": None,
              "last_evaluated_at": current.isoformat(), "required_conditions": [
                  "Fresh independently source-validated regular-session last sale inside the named owner window.",
                  "Observed price at or above the frozen trigger and no higher than its maximum; invalidate below the observed low.",
                  "A single last sale does not prove rebound sequencing, an executable bid/offer, a fill or capital eligibility."]}
    if observation.get("_day_invalidation"):
        result.update(state="invalidation_observed",current_quote_status="not_used_after_day_invalidation",
                      permanent_for_signal_day=True,historical_invalidation=observation["_day_invalidation"])
        return result
    quote = context.get("tickers", {}).get(observation["ticker"])
    if not applicable or not quote:
        if applicable:
            result["state"] = "awaiting_fresh_quote"
        return result
    trade, observed = old._aware(quote["trade_at"]), old._aware(quote["observed_at"])
    earliest = max(old._aware(observation["first_observed_at"]), old._aware(applicable["starts_at"]))
    if trade < earliest or observed < trade or observed > current or (current - trade).total_seconds() > 300:
        result["state"] = "awaiting_fresh_quote"
        result["current_quote_status"] = "clock_or_window_unverified"
        return result
    price, feature = old._number(quote["price"]), observation["features"]
    maximum = feature["close"] + .25 * (feature["close"] - feature["observed_five_session_low"])
    state = "invalidation_observed" if price <= feature["observed_five_session_low"] else "condition_observed" if feature["close"] <= price <= maximum else "outside_entry_band"
    expiry = min(trade + timedelta(seconds=300), old._aware(applicable["ends_at"]))
    result.update(state=state, current_quote_status="current", quote_observation={"price": price,
                  "trade_at": quote["trade_at"], "observed_at": quote["observed_at"], "expires_at": expiry.isoformat(),
                  "execution_quote": False, "source_label": quote.get("source_label", "Nasdaq Last Sale")})
    result["price_condition"] = "at_or_below_invalidation" if state=="invalidation_observed" else "above_maximum" if price>maximum else "below_trigger" if price<feature["close"] else "within_band"
    return result


def _decorate(observation,rows,current):
    result=copy.deepcopy(observation)
    invalidation=next((row for row in rows if row["kind"]=="window_evaluation" and row["observation_id"]==observation["observation_id"]
                       and row["state"]=="invalidation_observed" and old._aware(row["recorded_at"])<=current),None)
    if invalidation:
        result["_day_invalidation"]={"recorded_at":invalidation["recorded_at"],"record_hash":invalidation["record_hash"],
                                     "observed_at":invalidation["quote_observation"]["observed_at"],"price":invalidation["quote_observation"]["price"]}
    return result


def _delay_check(observation,first,delay,policy,current,context,rows):
    target=old._aware(first["quote_observation"]["observed_at"])+timedelta(minutes=delay)
    window=next(w for w in observation["review_windows"] if w["id"]==first["window_id"])
    if current<target:return None
    result={"kind":"delay_evaluation","version":VERSION,"observation_id":observation["observation_id"],"ticker":observation["ticker"],
            "recorded_at":current.isoformat(),"window_id":first["window_id"],"delay_minutes":delay,
            "first_entry_observation_record_hash":first["record_hash"],"minimum_observation_at":target.isoformat(),
            "entry_method":f"observed_owner_window_delay_{delay}_minutes_mark_not_fill",
            "quote_context":None,"quote_observation":None,"actual_delay_seconds":None,
            "actual_fill":False,"practical_owner_response_verified":False,**AUTHORITY}
    decorated=_decorate(observation,rows,current)
    if decorated.get("_day_invalidation"):
        result.update(state="invalidated_before_delay_observation",invalidation_record_hash=decorated["_day_invalidation"]["record_hash"])
        return result
    if current>=old._aware(window["ends_at"]):
        result["state"]="missed_no_verified_delayed_observation";return result
    timing=_timing(observation,policy,current,context)
    quote=timing.get("quote_observation")
    if timing.get("current_quote_status")!="current" or quote is None or old._aware(quote["observed_at"])<target or old._aware(quote["trade_at"])<target:
        return None
    result.update(state=timing["state"],quote_context=context,quote_observation=quote,
                  actual_delay_seconds=(old._aware(quote["observed_at"])-old._aware(first["quote_observation"]["observed_at"])).total_seconds())
    return result


def _card(observation, strategy, policy, current, context):
    feature = observation["features"]; reference, stop = feature["close"], feature["observed_five_session_low"]
    timing = _timing(observation, policy, current, context)
    return {"ticker": observation["ticker"], "setup": strategy, "state": "research_setup",
            "horizon_sessions": [5, 10, 14], "source_session": observation["source_session"],
            "source_price_basis": observation["price_basis"], "observation_id": observation["observation_id"],
            "first_observed_at": observation["first_observed_at"], "entry_session": observation["valid_session"],
            "benchmark_entry_session": observation["benchmark_entry_session"],
            "time_exits": [{"holding_sessions": horizon,
                            "session": [observation["valid_session"], *old._sessions_after(date.fromisoformat(observation["valid_session"]), horizon-1)][-1],
                            "basis": "conditional_owner_window_entry_session_not_assumed_fill"} for horizon in [5,10,14]],
            "entry_trigger": round(reference, 4), "max_entry": round(reference + .25 * (reference - stop), 4),
            "invalidation": round(stop, 4), "profit_reference": round(reference + 2 * (reference - stop), 4),
            "profit_reference_kind": "hypothetical_2R_not_observed_resistance",
            "review_deadline": observation["valid_until"], "expires_at": observation["valid_until"],
            "validity": {"session": observation["valid_session"], "starts_at": observation["valid_from"], "ends_at": observation["valid_until"]},
            "timing": timing, "thesis": policy["strategies"][strategy], "entry_rule": policy["entry_rule"],
            "exit_rule": policy["exit_rule"], "catalyst_status": "requires_source_bound_analyst_review",
            "growth_quality_status": "technical_setup_not_verified_growth_conviction", "rank_status": "unassessed",
            "practical_entry_status": "unverified_owner_response_delay_and_executable_quote",
            "canonical_scope": observation["canonical"], "evidence_quality": "validated_completed_daily_OHLCV_reference_conditions",
            "skip_reasons": ["Experimental method has no capital authority.", "Growth thesis, catalyst, corporate actions, practical execution and risk-managed entry-day path require separate review."],
            "uncertainty": ["Dated daily levels remain conditional after the open; they are not current execution prices.",
                            "A last-sale mark is not NBBO, touch/recovery sequencing or a fill.",
                            "Daily-volume ratios can mix provider definitions and are not live time-of-day RVOL."], **AUTHORITY}


def _new_observation(ticker, item, dataset, bindings, policy, current, baseline):
    session = old._sessions_after(date.fromisoformat(dataset["market_session"]), 1)[0]
    windows = _windows(session, policy, current)
    original_windows = _windows(session, policy)
    valid_until = original_windows[-1]["ends_at"] if original_windows else old.regular_close(session).isoformat()
    return {"kind": "observation", "version": VERSION, "observation_id": _identity(ticker, dataset["market_session"]),
            "ticker": ticker, "source_session": dataset["market_session"], "recorded_at": current.isoformat(),
            "first_observed_at": current.isoformat(), "valid_session": session,
            "valid_from": max(old._open(session), current).isoformat(), "valid_until": valid_until,
            "review_windows": windows, "benchmark_entry_session": old._next_open(current),
            "inputs": bindings, "bars_at_observation": item["bars"][-51:], "features": old._features(item["bars"]),
            "price_basis": item["price_basis"], "data_source": item["data_source"],
            "canonical": item["canonical"], "common_stock": item["common_stock"],
            "baseline": {"status": baseline["status"], "reason": baseline["reason"], "comparability": baseline["comparability"],
                         "capture_clock": baseline["capture_clock"], "proof": baseline["proof"],
                         "canonical_actionable_at_capture": baseline["observed_canonical"].get(ticker),
                         "existing_tactical_actionable_at_capture": baseline["observed_tactical"].get(ticker)}, **AUTHORITY}


def _summary(rows, root=None, current=None):
    observations = [row for row in rows if row["kind"] == "observation"]
    outcomes = [row for row in rows if row["kind"] == "outcome"]
    checks = [row for row in rows if row["kind"] == "window_evaluation"]
    delays=[row for row in rows if row["kind"]=="delay_evaluation"]
    qualified, qualification_status = [], "source_bound_review_required"
    if root is not None:
        try:
            from swing_outcome_review import read_reviews
            qualified = read_reviews(root, current)
            qualification_status = "reviewed_fixed_horizon_paths_available" if qualified else "source_bound_review_required"
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            qualification_status = "outcome_review_store_unverified"
    latest = {row["outcome_record_hash"]: row for row in qualified}
    groups = []
    for method in ("benchmark_future_open", "observed_owner_window_mark_not_fill"):
        for horizon in [5,10,14]:
            for basis in sorted({row.get("price_basis") for row in qualified if row.get("price_basis")}):
                group = [row for row in latest.values() if row["entry_method"] == method and row["horizon_sessions"] == horizon and row["price_basis"] == basis]
                if group:
                    groups.append({"entry_method":method,"horizon_sessions":horizon,"price_basis":basis,"reviewed_paths":len(group),
                                   "mean_reviewed_fixed_horizon_price_cost_sensitivity_pct": {str(bps):sum(row["reviewed_price_cost_sensitivity_pct_by_one_way_bps"][str(bps)] for row in group)/len(group) for bps in [10,25,50]},
                                   "interpretation":"Source-bound reviewed modeled fixed-horizon price paths; overlapping samples, not independent trades or risk-managed strategy returns."})
    return {"status": "prospective_research_only", "observations": len(observations), "outcomes": len(outcomes),
            "distinct_signal_sessions": len({row["source_session"] for row in observations}),
            "window_observations": len({(row["observation_id"],row["window_id"]) for row in checks}),
            "verified_state_transitions":len([row for row in checks if row.get("quote_observation")]),
            "condition_observed_windows": sum(row.get("first_qualifying_entry") is True for row in checks),
            "skipped_window_observations": sum(row["state"] != "condition_observed" for row in checks),
            "missed_evidence_windows": sum(row["state"] == "missed_no_verified_window_observation" for row in checks),
            "performance_eligible_paths": 0, "profitability_established": False, "reliable_win_rate": None,
            "reviewed_fixed_horizon_paths": len(latest), "qualification_status": qualification_status, "reviewed_fixed_horizon_groups":groups,
            "reviewed_unique_setup_windows":len({(row["observation_id"],row.get("window_id")) for row in latest.values()}),
            "delayed_observation_cohorts":[{"delay_minutes":delay,"observations":sum(row["delay_minutes"]==delay for row in delays),
                                          "condition_observed":sum(row["delay_minutes"]==delay and row["state"]=="condition_observed" for row in delays),
                                          "missed_or_skipped":sum(row["delay_minutes"]==delay and row["state"]!="condition_observed" for row in delays)} for delay in [3,5,10]],
            "risk_managed_strategy_qualified_paths": 0,
            "portfolio_return": None, "interpretation": "Observed-window last sales and future-open comparisons are distinct. No elapsed open is a delayed entry. Unreviewed corporate actions and entry-day exit ordering remain explicit; modeled observations are not trades."}


def _unavailable(current, reason):
    return {"schema_version": SCHEMA, "version": VERSION, "generated_at": current.isoformat(), "status": "waiting_on_data",
            "candidates": [], "review_windows": [], "blockers": [reason], "rank_status": "unassessed",
            "coverage": {"current": False, "screened": 0}, **AUTHORITY}


def build(root, current, *, capture=False, baseline=None, candidate_quote_context=None, outside_coverage_context=None, _with_quotes=True):
    root, current = Path(root), old._aware(current); result = None
    try:
        policy, dataset, bindings, raws, implementations, dependencies = _inputs(root, current, outside_coverage_context)
        baseline_context = old._baseline(root, baseline, bindings, current)
        output = root / OUTPUT
        lock = old.ExclusiveFileLock(output / "study.lock") if capture else None
        if lock: lock.__enter__()
        try:
            ledger = output / "ledger.jsonl"; before = ledger.read_bytes() if ledger.exists() else b""
            rows = _load(root, current); _verify(root, rows); count = len(rows)
            if any(row["kind"] == "observation" and
                   (row["inputs"]["policy_sha256"] != bindings["policy_sha256"]
                    or row["inputs"]["implementation_sha256"] != bindings["implementation_sha256"]) for row in rows):
                raise old.SwingResearchError("swing_v2_frozen_version_identity_changed")
            existing = {row["observation_id"]: row for row in rows if row["kind"] == "observation"}
            actual = []
            for ticker, item in sorted(dataset["series"].items()):
                identity = _identity(ticker, dataset["market_session"])
                observation = existing.get(identity)
                if observation is None:
                    observation = _new_observation(ticker, item, dataset, bindings, policy, current, baseline_context)
                    if capture:
                        old._chain(rows, observation); observation = rows[-1]
                elif (observation["inputs"]["policy_sha256"] != bindings["policy_sha256"]
                      or observation["inputs"]["implementation_sha256"] != bindings["implementation_sha256"]):
                    raise old.SwingResearchError("swing_v2_frozen_version_identity_changed")
                elif observation["bars_at_observation"] != item["bars"][-51:]:
                    raise old.SwingResearchError("swing_v2_same_session_correction_requires_review")
                actual.append(observation)
            selected = [row for row in actual if row["common_stock"] and any(row["features"]["selected"].values())
                        and current < old._aware(row["valid_until"])]
            scope = sorted({row["ticker"] for row in selected})
            context = _quote_context(root, candidate_quote_context, current, scope, bindings) if _with_quotes and scope else {"status": "unavailable", "tickers": {}}
            if capture:
                for observation in selected:
                    timing = _timing(_decorate(observation,rows,current), policy, current, context)
                    window = timing["current_window"]
                    prior_window = [row for row in rows if row["kind"]=="window_evaluation" and row["observation_id"]==observation["observation_id"] and window and row["window_id"]==window["id"]]
                    transition_changed=not prior_window or (prior_window[-1]["state"],prior_window[-1].get("price_condition"))!=(timing["state"],timing.get("price_condition"))
                    if timing["current_quote_status"] == "current" and window and transition_changed:
                        old._chain(rows, {"kind": "window_evaluation", "version": VERSION, "observation_id": observation["observation_id"],
                                         "ticker": observation["ticker"], "recorded_at": current.isoformat(), "window_id": window["id"],
                                         "sequence":len(prior_window)+1,"state": timing["state"],"price_condition":timing.get("price_condition"),"quote_context": context,
                                         "first_qualifying_entry":timing["state"]=="condition_observed" and not any(row.get("first_qualifying_entry") is True for row in prior_window),
                                         "quote_observation": timing["quote_observation"], "entry_method": "observed_owner_window_mark_not_fill", **AUTHORITY})
                all_observations = [row for row in rows if row["kind"] == "observation" and row["common_stock"] and any(row["features"]["selected"].values())]
                seen_windows = {(row["observation_id"],row.get("window_id")) for row in rows if row["kind"] == "window_evaluation"}
                for observation in all_observations:
                    for window in observation["review_windows"]:
                        if current >= old._aware(window["ends_at"]) and (observation["observation_id"],window["id"]) not in seen_windows:
                            old._chain(rows,{"kind":"window_evaluation","version":VERSION,"observation_id":observation["observation_id"],
                                             "ticker":observation["ticker"],"recorded_at":current.isoformat(),"window_id":window["id"],
                                             "sequence":1,"first_qualifying_entry":False,
                                             "state":"missed_no_verified_window_observation","quote_context":None,"quote_observation":None,
                                             "entry_method":"owner_window_missing_evidence","reason":"No admitted timestamped observation was retained in this original window; no fill or missed profit is inferred.",**AUTHORITY})
                recorded_delays={(row["observation_id"],row["window_id"],row["delay_minutes"]) for row in rows if row["kind"]=="delay_evaluation"}
                first_entries=[row for row in rows if row["kind"]=="window_evaluation" and row.get("first_qualifying_entry") is True]
                observation_map={row["observation_id"]:row for row in rows if row["kind"]=="observation"}
                for first in first_entries:
                    for delay in [3,5,10]:
                        if (first["observation_id"],first["window_id"],delay) not in recorded_delays:
                            delayed=_delay_check(observation_map[first["observation_id"]],first,delay,policy,current,context,rows)
                            if delayed is not None:old._chain(rows,delayed)
                _append_outcomes(rows, dataset, bindings, policy, current)
                raws_to_retain = [*raws.values(), old._json_bytes(dataset)]
                for raw in raws_to_retain: old._retain(output / "input_history" / old._digest(raw), raw)
                for name, raw in implementations.items(): old._retain(output / "implementations" / bindings["implementation_sha256"] / name, raw)
                if any(old._file(root, path) != raw for path,raw in raws.items()):
                    raise old.SwingResearchError("swing_v2_inputs_changed_during_read")
                old._append(ledger, before, rows[count:])
            cards = [_card(_decorate(row,rows,current), strategy, policy, current, context) for row in selected for strategy in STRATEGIES if row["features"]["selected"][strategy]]
            valid_session = old._sessions_after(date.fromisoformat(dataset["market_session"]), 1)[0]
            result = {"schema_version": SCHEMA, "version": VERSION, "generated_at": current.isoformat(), "status": "experimental_current",
                      "source_session": dataset["market_session"], "source_bindings": bindings, "blockers": dependencies,
                      "candidates": cards[:12], "additional_setup_count": max(0, len(cards)-12),
                      "review_windows": _windows(valid_session, policy), "rank_status": "unassessed",
                      "selection_basis": "Fixed daily technical definitions; stable ticker order is not a high-potential investment ranking.",
                      "coverage": {"current": True, "screened": len(actual), "setups": len(cards), "scope": sorted(dataset["series"]),
                                   "benchmark_only": sum(not row["common_stock"] for row in actual),
                                   "unselected": sum(not any(row["features"]["selected"].values()) for row in actual)},
                      "performance": _summary(rows, root, current), "adoption": policy["adoption"], "promotion_review": {**policy["promotion_review"], "currently_qualified": False},
                      "baseline_comparability": baseline_context["comparability"], **AUTHORITY}
            result["projection_recorded"] = bool(capture)
            result["projection_sha256"] = old._hash(result)
            if capture:
                _attempt(root, {"status": "passed", "bindings": bindings}, current)
                old._retain(root / OUTPUT / "projections" / (result["projection_sha256"]+".json"),old._json_bytes(result))
            return result
        finally:
            if lock: lock.__exit__(None, None, None)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, old.SwingResearchError) else "swing_v2_source_or_study_unverified"
        result = _unavailable(current, reason)
        if capture:
            try: _attempt(root, {"status": "failed", "reason": reason}, current)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError): result["blockers"].append("swing_v2_attempt_history_unavailable")
        return result


def _attempt(root, meaning, current):
    meaning = {**meaning, "required_session": old.latest_published_market_session(current).isoformat(), "version": VERSION}
    path = root / OUTPUT / "attempts" / (old._hash(meaning) + ".json")
    if path.exists():
        if json.loads(old._file(path.parent, path.name))["meaning"] != meaning:
            raise old.SwingResearchError("swing_v2_attempt_history_unverified")
        return
    old._retain(path, old._json_bytes({"meaning": meaning, "recorded_at": current.isoformat(), **AUTHORITY}))


def _append_outcomes(rows, dataset, bindings, policy, current):
    observations = {row["observation_id"]: row for row in rows if row["kind"] == "observation"}
    existing = {(row["observation_id"], row.get("entry_method"), row.get("window_id"), row.get("horizon_sessions")) for row in rows if row["kind"] == "outcome"}
    checks = [row for row in rows if row["kind"] == "window_evaluation" and row.get("first_qualifying_entry") is True
              or row["kind"]=="delay_evaluation" and row["state"]=="condition_observed"]
    for observation in observations.values():
        item = dataset["series"].get(observation["ticker"])
        if not item or item["price_basis"] != observation["price_basis"]: continue
        for horizon in [5, 10, 14]:
            key = (observation["observation_id"], "benchmark_future_open", None, horizon)
            if key not in existing:
                outcome = _derive_outcome(observation, None, "benchmark_future_open", horizon, dataset, bindings, policy, current)
                if outcome:
                    old._chain(rows, outcome)
            for check in [row for row in checks if row["observation_id"] == observation["observation_id"]]:
                method=check["entry_method"]
                key = (observation["observation_id"], method, check["window_id"], horizon)
                if key in existing: continue
                outcome = _derive_outcome(observation, check, method, horizon, dataset, bindings, policy, current)
                if outcome: old._chain(rows, outcome)


def _derive_outcome(observation, check, method, horizon, dataset, bindings, policy, current):
    item = dataset["series"].get(observation["ticker"])
    if not item or item["price_basis"] != observation["price_basis"]: return None
    if method == "benchmark_future_open":
        proxy = {**observation, "entry_session": observation["benchmark_entry_session"]}
        result = old._outcome(proxy, item["bars"], horizon, policy, current, inputs=bindings)
        if result: result.update(version=VERSION, entry_method=method, price_basis=item["price_basis"])
        return result
    if (method!="observed_owner_window_mark_not_fill" and not method.startswith("observed_owner_window_delay_")) or check is None or check["state"] != "condition_observed": return None
    entry_day = old._aware(check["quote_observation"]["observed_at"]).date()
    days = [entry_day.isoformat(), *old._sessions_after(entry_day, horizon-1)]
    lookup = {bar["session_date"]: bar for bar in item["bars"]}
    if any(day not in lookup for day in days) or current < old.regular_close(days[-1]): return None
    entry = check["quote_observation"]["price"]
    corrected = any(bar["session_date"] in lookup and bar != lookup[bar["session_date"]] for bar in observation["bars_at_observation"])
    result = {"kind": "outcome", "version": VERSION, "observation_id": observation["observation_id"],
                                 "ticker": observation["ticker"], "recorded_at": current.isoformat(), "horizon_sessions": horizon,
                                 "entry_method":method,"window_id":check["window_id"],"delay_minutes":check.get("delay_minutes"),
                                 "actual_observation_delay_seconds":check.get("actual_delay_seconds"),
                                 "entry_observation_record_hash": check["record_hash"], "entry_observed_at": check["quote_observation"]["observed_at"],
                                 "entry_price": entry, "forward_bars": [lookup[day] for day in days], "inputs": bindings,
                                 "status": "correction_review_required" if corrected else "unreviewed_delayed_quote_to_close_price_path", "price_basis": item["price_basis"],
                                 "entry_day_exit_ordering_status": "unverified_daily_bar_includes_pre_entry_prices",
                                 "corporate_action_review_required": True, "performance_eligible": False,
                                 "actual_fill": False, **AUTHORITY}
    if not corrected: result["raw_common_price_cost_sensitivity_pct_by_one_way_bps"] = old._net(entry, lookup[days[-1]]["close"], policy)
    return result


def quote_targets(root, current, limit=3):
    view = build(root, current, capture=False, candidate_quote_context={}, _with_quotes=False)
    return sorted({row["ticker"] for row in view.get("candidates", [])})[:max(0,min(3,limit))]


def revalidate_projection(root, view, current, candidate_quote_context=None):
    root, current = Path(root), old._aware(current)
    try:
        if view.get("schema_version") != SCHEMA or view.get("version") != VERSION or old._aware(view["generated_at"]) > current or any(view.get(k) != v for k,v in AUTHORITY.items()):
            raise old.SwingResearchError("swing_v2_projection_unverified")
        if view.get("projection_sha256") != old._hash({k:v for k,v in view.items() if k != "projection_sha256"}):
            raise old.SwingResearchError("swing_v2_projection_content_unverified")
        if view.get("projection_recorded") is True:
            digest=view["projection_sha256"]
            if re.fullmatch(r"[a-f0-9]{64}",digest) is None or json.loads(old._file(root,OUTPUT/"projections"/(digest+".json"))) != view:
                raise old.SwingResearchError("swing_v2_projection_receipt_unverified")
        else:
            expected=build(root,old._aware(view["generated_at"]),capture=False,candidate_quote_context={},_with_quotes=False)
            fields={"schema_version","version","status","source_session","source_bindings","blockers","additional_setup_count","review_windows","rank_status","selection_basis","coverage","performance","adoption","promotion_review","baseline_comparability"}
            if any(view.get(k)!=expected.get(k) for k in fields):
                raise old.SwingResearchError("swing_v2_projection_metadata_unverified")
            if {(r.get("observation_id"),r.get("setup")) for r in view.get("candidates",[])}!={(r.get("observation_id"),r.get("setup")) for r in expected.get("candidates",[])}:
                raise old.SwingResearchError("swing_v2_projection_candidate_set_unverified")
        policy, dataset, bindings, _, _, _ = _inputs(root, current)
        if bindings != view.get("source_bindings"):
            raise old.SwingResearchError("swing_v2_projection_sources_changed")
        rows = _load(root, current); _verify(root, rows)
        stored = {row["observation_id"]: row for row in rows if row["kind"] == "observation"}
        scope = sorted({row["ticker"] for row in view.get("candidates", [])})
        context = _quote_context(root, candidate_quote_context, current, scope, bindings) if scope else {"tickers": {}}
        result = copy.deepcopy(view); result["candidates"] = []
        for card in view.get("candidates", []):
            observation = stored.get(card["observation_id"])
            if observation is None:
                baseline = old._baseline(root, None, bindings, old._aware(view["generated_at"]))
                observation = _new_observation(card["ticker"], dataset["series"][card["ticker"]], dataset, bindings,
                                               policy, old._aware(view["generated_at"]), baseline)
            expected = _card(_decorate(observation,rows,current), card["setup"], policy, current, context)
            if (not observation["common_stock"] or not observation["features"]["selected"].get(card["setup"])
                    or {k:v for k,v in card.items() if k != "timing"} != {k:v for k,v in expected.items() if k != "timing"}):
                raise old.SwingResearchError("swing_v2_projection_candidate_unverified")
            if current < old._aware(observation["valid_until"]): result["candidates"].append(expected)
        result["read_time"] = current.isoformat()
        result["expired_candidates_suppressed"] = len(view.get("candidates", []))-len(result["candidates"])
        result["read_time_performance"] = _summary(rows,root,current)
        ledger=root/OUTPUT/"ledger.jsonl"
        result["read_time_study_proof"]={"record_count":len(rows),"ledger_sha256":old._digest(ledger.read_bytes()) if ledger.exists() else None,
                                         "original_projection_generated_at":view["generated_at"],"original_projection_sha256":view["projection_sha256"]}
        return result
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return _unavailable(current, str(exc) if isinstance(exc, old.SwingResearchError) else "swing_v2_projection_unverified")
