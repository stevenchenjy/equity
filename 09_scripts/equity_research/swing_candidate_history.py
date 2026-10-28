"""Bounded outside-universe unadjusted histories for research only.

Reuse the approved Massive Custom Bars normalizer and Nasdaq new-session
two-close overlap. No canonical universe, market pointer, account or order is
written. A dated discovery lead is not represented as current broad coverage.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import argparse
import json
import os
import fcntl
import re
import sys

from daily_common import (ET, ExclusiveFileLock, atomic_write_json, canonical_sha256,
                          latest_published_market_session, now_et, sha256_file)
import market_backup as backup
import market_data_adapter as primary
import market_discovery as discovery

BASE = Path("03_source_data/equity_research/swing_candidate_history.local")
SCHEMA = "equity_swing_candidate_history_v1"
AUTHORITY = {"research_only": True, "capital_authority": False, "canonical_admission": False,
             "actionable_quantity": 0, "automatic_action_allowed": False}
MAX_TARGETS = 2


def _inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    if (path.is_absolute() or ".." in path.parts or (root/path).is_symlink()
            or not (root/path).resolve().is_relative_to(root.resolve())
            or any((root/Path(*path.parts[:n])).is_symlink() for n in range(1,len(path.parts)))):
        raise ValueError("outside_history_source_path_invalid")
    return root/path


def _stamp(value) -> datetime:
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if value.tzinfo is None:
        raise ValueError("outside_history_aware_clock_required")
    return value.astimezone(ET)


def _seal(record: dict) -> dict:
    result = dict(record)
    result["content_sha256"] = canonical_sha256({k:v for k,v in result.items() if k != "content_sha256"})
    return result


def _retain_json(path: Path, value: dict) -> dict:
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    discovery._retain_original(path, raw)
    return {"path": str(path), "sha256": sha256_file(path)}


def _primary_bars(payload: dict, ticker: str, start: date, end: date) -> list[dict]:
    return [{"session_date":str(bar["session_date"]), **{key:bar[key] for key in backup.FIELDS}}
            for bar in primary._normalized_bars(payload,ticker=ticker,start_date=start,end_date=end)]


def _checked_primary(payload: dict, ticker: str, start: date, end: date) -> list[dict]:
    bars = _primary_bars(payload,ticker,start,end)
    last = date.fromisoformat(bars[-1]["session_date"])
    if last > end or len(backup.sessions(last, end)) > 6:
        raise ValueError("outside_history_primary_baseline_stale")
    return backup.checked_bars([b for b in bars if date.fromisoformat(b["session_date"]) >= last-timedelta(weeks=52)], last)


def _merge(bars: list[dict], payload: dict | None, ticker: str, end: date) -> list[dict]:
    last = date.fromisoformat(bars[-1]["session_date"])
    if last == end:
        return backup.checked_bars(bars, end)
    if payload is None:
        raise ValueError("outside_history_current_extension_missing")
    start = date.fromisoformat(bars[-2]["session_date"])
    extension = backup.normalize(payload, ticker, start, end)
    prior = {b["session_date"]: b for b in bars}
    overlap = [b for b in extension if b["session_date"] <= str(last)]
    if len(overlap) != 2 or any(b["session_date"] not in prior or abs(
            Decimal(str(b["close"]))-Decimal(str(prior[b["session_date"]]["close"]))) > Decimal("0.005") for b in overlap):
        raise ValueError("outside_history_overlap_price_basis_conflict")
    merged = [*bars, *[b for b in extension if b["session_date"] > str(last)]]
    return backup.checked_bars([b for b in merged if date.fromisoformat(b["session_date"]) >= end-timedelta(weeks=52)], end)


def validate_record(root: Path, record: dict, current: datetime, *, cache: dict | None = None) -> dict:
    current = _stamp(current)
    if (record.get("schema_version") != SCHEMA or _seal(record) != record
            or any(record.get(k) != v for k,v in AUTHORITY.items())
            or record.get("price_basis") != "unadjusted"
            or record.get("source_session") != latest_published_market_session(current).isoformat()
            or _stamp(record["observed_at"]) > current
            or record.get("source_session") != latest_published_market_session(_stamp(record["observed_at"])).isoformat()):
        raise ValueError("outside_history_record_or_clock_unverified")
    cache = {} if cache is None else cache
    def raw(relative):
        path = _inside(root, relative)
        if relative not in cache: cache[relative] = path.read_bytes()
        value = cache[relative]
        import hashlib
        if hashlib.sha256(value).hexdigest() != record["source_bindings"].get(relative):
            raise ValueError("outside_history_original_source_changed")
        return value
    ticker = record["ticker"]
    http = json.loads(raw(record["primary_http_receipt_path"]))
    expected_endpoint = (discovery.BASE+f"/v2/aggs/ticker/{ticker}/range/1/day/"
                         f"{record['primary_request_start']}/{record['source_session']}")
    if (http.get("endpoint_family") != "custom_bars" or http.get("endpoint") != expected_endpoint
            or http.get("http_status") != 200 or http.get("response_retention") != "original_bytes"
            or http.get("response_truncated") is not False
            or http.get("credential_headers_retained") is not False
            or _stamp(http["requested_at"]) > _stamp(record["observed_at"])
            or latest_published_market_session(_stamp(http["requested_at"])).isoformat() != record["source_session"]
            or str(BASE/http.get("response_path", "")) != record["primary_response_path"]
            or http.get("response_sha256") != record["source_bindings"].get(record["primary_response_path"])):
        raise ValueError("outside_history_original_http_receipt_unverified")
    original_primary = raw(record["primary_response_path"])
    if len(original_primary) > primary.MASSIVE_MAX_RESPONSE_BYTES or http.get("response_bytes") != len(original_primary):
        raise ValueError("outside_history_primary_response_size_unverified")
    metadata = json.loads(raw(record["metadata_path"]))
    if metadata.get("sha256") != discovery._digest(metadata.get("payload")):
        raise ValueError("outside_history_metadata_checksum_unverified")
    metadata = metadata["payload"]
    discovery.validate_metadata(metadata, date.fromisoformat(record["source_session"]))
    identity = metadata["rows"].get(ticker, {})
    if (identity.get("ticker") != ticker or identity.get("type") != "CS" or identity.get("primary_exchange") not in discovery.EXCHANGES
            or str(identity.get("currency_name", "")).lower() != "usd"):
        raise ValueError("outside_history_common_stock_identity_unverified")
    end, start = date.fromisoformat(record["source_session"]), date.fromisoformat(record["primary_request_start"])
    bars = _checked_primary(json.loads(raw(record["primary_response_path"])), ticker, start, end)
    nasdaq = json.loads(raw(record["nasdaq_response_path"])) if record.get("nasdaq_response_path") else None
    if nasdaq is not None:
        receipt = record.get("nasdaq_http_receipt") or {}
        last = date.fromisoformat(bars[-2]["session_date"])
        expected = (f"https://api.nasdaq.com/api/quote/{ticker}/historical?assetclass=stocks&fromdate={last}&todate={end}&limit=5000")
        if (receipt.get("ticker") != ticker or receipt.get("path") != record["nasdaq_response_path"]
                or receipt.get("sha256") != record["source_bindings"].get(record["nasdaq_response_path"])
                or receipt.get("source_url") != expected or receipt.get("price_field") != "Close/Last"
                or _stamp(receipt["observed_at"]) > _stamp(record["observed_at"])):
            raise ValueError("outside_history_nasdaq_receipt_unverified")
    merged = _merge(bars, nasdaq, ticker, end)
    if merged != record.get("bars"):
        raise ValueError("outside_history_calculation_unverified")
    for relative in record["source_bindings"]: raw(relative)
    return record


def admitted(root: Path, current: datetime, limit: int = 6) -> dict:
    """Current focused coverage, even when whole-market grouped data failed."""
    root, current = Path(root), _stamp(current)
    histories, blocked, cache = {}, {}, {}
    pointers = []
    for path in (root/BASE/"current").glob("*.json"):
        try:
            value = json.loads(path.read_text())
            rank = value.get("dated_screen_rank")
            pointers.append((rank if type(rank) is int else 999999, path, value))
        except (OSError, ValueError): blocked[path.stem] = "outside_history_pointer_unverified"
    for _, path, pointer in sorted(pointers, key=lambda value: (value[0], value[1].name)):
        ticker = path.stem
        try:
            if pointer.get("status") != "current" or pointer.get("source_session") != latest_published_market_session(current).isoformat():
                raise ValueError(pointer.get("failure_code") or "outside_history_current_source_missing")
            relative = pointer["history_path"]
            if not re.fullmatch(re.escape(str(BASE))+r"/history/[a-f0-9]{64}\.json", relative):
                raise ValueError("outside_history_locator_invalid")
            file = _inside(root, relative)
            if sha256_file(file) != pointer["history_sha256"]:
                raise ValueError("outside_history_archive_hash_invalid")
            record = validate_record(root, json.loads(file.read_text()), current, cache=cache)
            if record["ticker"] != ticker:
                raise ValueError("outside_history_pointer_identity_mismatch")
            proof = {**record["source_bindings"], relative:pointer["history_sha256"],
                     str(path.relative_to(root)):sha256_file(path)}
            histories[ticker] = dict(ticker=ticker, name=record["name"], bars=record["bars"],
                source_session=record["source_session"], discovery_session=record["discovery_session"],
                first_seen_at=record.get("first_seen_at"), dated_screen_rank=record["dated_screen_rank"],
                price_basis="unadjusted", data_source=record["data_source"], instrument_kind="stock", security_type="CS",
                common_stock_verified=True, source_available_at=record["observed_at"],
                source_bindings=proof,
                sources=[{"path":rel,"sha256":digest} for rel,digest in proof.items()],
                corporate_action_review_required=True, basis_consistency="retained_unadjusted_baseline_with_two_close_extension", **AUTHORITY)
            if len(histories) == limit: break
        except (OSError, ValueError, KeyError, TypeError, primary.MassiveB2Error) as exc:
            blocked[ticker] = str(exc) if isinstance(exc, (ValueError, primary.MassiveB2Error)) else "outside_history_source_unverified"
    return dict(status="ready" if histories else "waiting_on_data", histories=histories, ticker_blockers=blocked,
                scope="Focused retained outside-universe leads only; not current whole-market coverage.", **AUTHORITY)


def research_targets(root: Path, current: datetime, limit: int = 6) -> list[dict]:
    from swing_coverage import _scope, _continuity, _historical_leads
    canonical, _ = _scope(root)
    items, _, state = _continuity(root, current)
    if state != "validated": return []
    session = latest_published_market_session(current)
    rel = discovery.CACHE_RELATIVE/f"metadata-{session}.local.json"
    metadata = discovery._cache_read(root/rel)
    discovery.validate_metadata(metadata, session)
    targets = []
    for lead in _historical_leads(items, canonical):
        row = metadata["rows"].get(lead["ticker"], {})
        if (re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", lead["ticker"]) and row.get("type") == "CS"
                and row.get("primary_exchange") in discovery.EXCHANGES and str(row.get("currency_name", "")).lower() == "usd"):
            item=items[lead["ticker"]]
            observation=next((o for o in item.get("observations",[]) if o.get("observation_id")==lead["observation_id"]),{})
            targets.append({**lead, "metadata_path": str(rel), "metadata_sha256": sha256_file(root/rel),
                            "target_sources":[{"path":s["path"],"sha256":s["sha256"]} for s in observation.get("sources",[])]})
            if len(targets) == limit: break
    return targets


def collect(root: Path, current: datetime, max_candidates: int = MAX_TARGETS, *, massive=None, nasdaq=None, targets=None, clock=now_et) -> dict:
    """Coordinator holds runtime/pipeline locks. No retry or canonical mutation."""
    root, current = Path(root), _stamp(current)
    if type(max_candidates) is not int or not 1 <= max_candidates <= MAX_TARGETS:
        raise ValueError("outside_history_target_budget_invalid")
    for folder in (BASE, *(BASE/name for name in ("requests","completions","current","history","http_receipts","http_originals"))):
        _inside(root,str(folder))
    result = dict(schema_version=SCHEMA,generated_at=current.isoformat(),source_session=latest_published_market_session(current).isoformat(),
                  status="completed", attempted=0, reused=0, attempts=[], **AUTHORITY)
    available = admitted(root, current)["histories"]
    try: targets = research_targets(root, current) if targets is None else targets
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**result, "status":"waiting_on_data", "dependency":str(exc)}
    receipts = []
    with ExclusiveFileLock(root/BASE/"collector.lock"):
        for target in targets:
            ticker = target["ticker"]
            if not isinstance(ticker,str) or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}",ticker) is None:
                result["attempts"].append({"status":"invalid_target_identity"});continue
            if ticker in available:
                result["reused"] += 1
                continue
            if result["attempted"] == max_candidates: break
            reserved_today = []
            for prior in (root/BASE/"requests").glob("*.json"):
                try:
                    value = json.loads(prior.read_text())
                    if (value.get("source_session") == latest_published_market_session(current).isoformat()
                            and _stamp(value["requested_at"]).date() == current.date()): reserved_today.append(value)
                except (OSError,ValueError,KeyError,TypeError):
                    raise ValueError("outside_history_request_budget_evidence_unverified") from None
            if len(reserved_today) >= MAX_TARGETS:
                result["attempts"].append({"ticker":ticker,"status":"daily_focused_collection_budget_exhausted"})
                break
            identity = canonical_sha256({"ticker":ticker,"source_session":latest_published_market_session(current).isoformat(),
                                         "attempt_date":current.date().isoformat()})
            reservation = root/BASE/"requests"/(identity+".json")
            if reservation.exists():
                result["attempts"].append({"ticker":ticker,"status":"already_attempted_same_source_and_date"})
                continue
            discovery._retain_original(reservation, (json.dumps({"ticker":ticker,"requested_at":current.isoformat(),
                "source_session":latest_published_market_session(current).isoformat(), **AUTHORITY},sort_keys=True)+"\n").encode())
            result["attempted"] += 1
            attempt = dict(ticker=ticker, request_id=identity, requested_at=current.isoformat(), **AUTHORITY)
            try:
                if massive is None:
                    archiver = discovery.DiscoveryClient.from_environment(state_path=root/BASE/"request-pacing.local.json")
                    def get(path, headers, timeout):
                        try: payload = archiver.request(path)
                        except discovery.DiscoveryError as exc:
                            raise primary.MassiveB2Error(primary.AUTH_FAILED_CODE if exc.code == "authentication_failed" else primary.REQUEST_FAILED_CODE) from None
                        receipts.append(archiver.http_receipts[-1])
                        return payload
                    massive = primary.MassiveBasicEODClient.from_environment(http_get=get)
                end = latest_published_market_session(current)
                start = end-timedelta(weeks=53)
                bars = massive.fetch_daily_bars(ticker, start_date=start, end_date=end)
                source = receipts[-1] if receipts else massive.receipts[-1]
                if source.get("response_retention") != "original_bytes" or not source.get("response_path"):
                    raise ValueError("outside_history_original_primary_response_unavailable")
                primary_rel = str(BASE/source["response_path"])
                primary_raw = json.loads(_inside(root, primary_rel).read_text())
                baseline = _checked_primary(primary_raw, ticker, start, end)
                normalized = [{"session_date":str(b["session_date"]), **{key:b[key] for key in backup.FIELDS}} for b in bars]
                if baseline != [b for b in normalized if date.fromisoformat(b["session_date"]) >= date.fromisoformat(normalized[-1]["session_date"])-timedelta(weeks=52)]:
                    raise ValueError("outside_history_primary_normalization_mismatch")
                nasdaq_rel, nasdaq_payload = None, None
                http_rel = str(BASE/source["receipt_path"])
                bindings = {primary_rel:sha256_file(root/primary_rel),http_rel:sha256_file(root/http_rel),
                            target["metadata_path"]:target["metadata_sha256"]}
                bindings.update({s["path"]:s["sha256"] for s in target.get("target_sources",[])})
                if baseline[-1]["session_date"] != str(end):
                    if nasdaq is None: nasdaq = backup.NasdaqHistoricalClient(root)
                    client = nasdaq
                    client.fetch(ticker,"stocks",date.fromisoformat(baseline[-2]["session_date"]),end)
                    observation = client.receipts[-1]
                    nasdaq_rel = observation["path"]
                    bindings[nasdaq_rel] = observation["sha256"]
                    nasdaq_receipt = dict(observation)
                    nasdaq_payload = json.loads(_inside(root,nasdaq_rel).read_text())
                else:
                    nasdaq_receipt = None
                merged = _merge(baseline,nasdaq_payload,ticker,end)
                record = _seal(dict(schema_version=SCHEMA,ticker=ticker,name=target.get("name",ticker),
                    source_session=str(end),observed_at=_stamp(clock()).isoformat(),primary_request_start=str(start),
                    primary_response_path=primary_rel,nasdaq_response_path=nasdaq_rel,metadata_path=target["metadata_path"],
                    primary_http_receipt_path=http_rel,nasdaq_http_receipt=nasdaq_receipt,
                    source_bindings=bindings,bars=merged,price_basis="unadjusted",
                    discovery_session=target["discovery_session"],first_seen_at=target.get("first_seen_at"),
                    dated_screen_rank=target.get("dated_screen_rank",999999),target_observation_id=target.get("observation_id"),
                    data_source="massive_unadjusted_history_nasdaq_eod_extension_research" if nasdaq_rel else "massive_unadjusted_research",**AUTHORITY))
                validate_record(root,record,_stamp(clock()))
                raw = (json.dumps(record,sort_keys=True,indent=2)+"\n").encode()
                import hashlib
                digest = hashlib.sha256(raw).hexdigest(); relative = BASE/"history"/(digest+".json")
                discovery._retain_original(root/relative,raw)
                pointer = dict(status="current",ticker=ticker,source_session=str(end),history_path=str(relative),
                    history_sha256=digest,dated_screen_rank=target.get("dated_screen_rank",999999),**AUTHORITY)
                atomic_write_json(root/BASE/"current"/(ticker+".json"),pointer)
                attempt.update(status="admitted_current_research_history",history_sha256=digest)
            except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
                code = str(exc) if (isinstance(exc,(ValueError,primary.MassiveB2Error))
                                     and re.fullmatch(r"[a-z][a-z0-9_]{0,119}",str(exc))) else "outside_history_source_attempt_failed"
                attempt.update(status="failed",failure_code=code)
                if "archiver" in locals() and archiver.http_receipts:
                    last_http = archiver.http_receipts[-1]
                    attempt["original_http_evidence"] = {k:last_http.get(k) for k in (
                        "http_status","endpoint_family","receipt_path","receipt_sha256","response_path","response_sha256","provider_message")}

                atomic_write_json(root/BASE/"current"/(ticker+".json"),dict(status="failed",ticker=ticker,
                    source_session=latest_published_market_session(current).isoformat(),failure_code=code,**AUTHORITY))
            _retain_json(root/BASE/"completions"/(identity+".json"),attempt)
            result["attempts"].append(attempt)
    if any(row.get("status") == "failed" for row in result["attempts"]):
        result["status"] = "completed_with_dependencies"
    elif not result["attempted"] and not result["reused"]:
        result["status"] = "no_new_collection"
    return result


def _active_claim(root: Path, current: datetime) -> bool:
    path=root/"00_project_control/run_logs/short_assessment.local.json"
    if not path.exists():return False
    state=json.loads(path.read_text())
    return any(r.get("status") in {"claimed","active","running"}
               and (not (r.get("expires_at") or r.get("deadline_at")) or
                    _stamp(r.get("expires_at") or r.get("deadline_at"))>current)
               for r in state.get("slots",{}).values())


def _verify_coordinator(root: Path) -> None:
    for path in (root.parent/".locks/equity-research-runtime.lock",root/"00_project_control/run_logs/daily_pipeline.lock"):
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                owner=os.read(descriptor,512).decode()
                if path.name=="daily_pipeline.lock" and not owner.startswith(f"pid={os.getppid()} "):
                    raise ValueError("outside_history_coordinator_parent_unverified")
            else:
                fcntl.flock(descriptor,fcntl.LOCK_UN)
                raise ValueError("outside_history_coordinator_lock_not_held")
        finally:os.close(descriptor)


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,required=True);parser.add_argument("--collect",action="store_true")
    parser.add_argument("--pipeline-coordinated",action="store_true")
    args=parser.parse_args();root=args.root.resolve();current=now_et()
    if not args.collect:
        value=admitted(root,current);print(json.dumps({k:v for k,v in value.items() if k!="histories"},sort_keys=True));return 0
    try:
        if _active_claim(root,current): print('status=pending_active_short_claim');return 0
        if args.pipeline_coordinated:
            _verify_coordinator(root)
            current=now_et()
            if _active_claim(root,current): print('status=pending_active_short_claim');return 0
            value=collect(root,current)
        else:
            with ExitStack() as stack:
                stack.enter_context(ExclusiveFileLock(root.parent/".locks/equity-research-runtime.lock"))
                stack.enter_context(ExclusiveFileLock(root/"00_project_control/run_logs/daily_pipeline.lock"))
                current=now_et()
                if _active_claim(root,current): print('status=pending_active_short_claim');return 0
                value=collect(root,current)
        print(json.dumps(value,sort_keys=True))
        return 2 if value["status"] in {"completed_with_dependencies","waiting_on_data"} else 0
    except RuntimeError:
        print('status=pending_mutation_lock');return 0
    except (OSError,ValueError,KeyError,TypeError):
        print('status=unverified_collection_admission');return 2


if __name__=="__main__":sys.exit(main())
