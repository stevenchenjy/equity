"""Bounded, source-validated candidate last sales for zero-capital swing research.

Only explicit collection uses the public Nasdaq client. Reads are offline and
rederive every admitted mark from original HTTP bytes, current prior-close
history and actual clocks. This namespace does not alter account/EOD facts,
capital publication, delivery meaning, or execution authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from contextlib import contextmanager, nullcontext
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import os
import tempfile
import time
from urllib.parse import quote

from daily_common import atomic_write_json, now_et
from investment_plans import regular_close
import intraday_prices as feed

REL = "03_source_data/equity_research/swing_candidate_quotes.local"
CURRENT = REL + "/current.json"
SCHEMA = "equity_swing_candidate_quotes_v1"
MAX_TARGETS = 3
COLLECTION_BUDGET_SECONDS = 35
AUTHORITY = {"capital_authority": False, "actionable_quantity": 0,
             "execution_quote": False, "email_authorized": False}


def record_failure(root: Path, *, current=None, claim_id: str, reason: str) -> dict:
    """Fence previous marks before a bounded attempt, including interruptions."""
    current = feed._now(current)
    if not isinstance(reason, str) or not reason or len(reason) > 300:
        raise ValueError("swing_quote_failure_reason_invalid")
    value = {"schema_version": SCHEMA, "generated_at": current.isoformat(),
             "claim_id": claim_id, "session_date": current.date().isoformat(),
             "scope": {}, "rows": {}, "attempts": [],
             "failures": {"__attempt__": reason}, "status": "unavailable",
             "expires_at": None, **AUTHORITY}
    binding = _retain(Path(root), value)
    return _projection(Path(root), value, binding, current, require_latest=True)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _retain(root: Path, value: dict) -> dict:
    raw = _bytes(value)
    digest = _sha(raw)
    relative = f"{REL}/snapshots/{digest}.json"
    path = feed._safe_target(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("swing_quote_immutable_conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    binding = {"path": relative, "sha256": digest}
    atomic_write_json(feed._safe_target(root, CURRENT), {
        "schema_version": SCHEMA, "source": binding,
        "generated_at": value["generated_at"], "status": value["status"]})
    return binding


def _source(root: Path, binding: dict) -> dict:
    try:
        digest = binding["sha256"]
        if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or binding["path"] != f"{REL}/snapshots/{digest}.json"):
            raise ValueError()
        raw = feed._safe_target(root, binding["path"]).read_bytes()
        if _sha(raw) != digest:
            raise ValueError()
        value = json.loads(raw)
        if value["schema_version"] != SCHEMA:
            raise ValueError()
        return value
    except (KeyError, TypeError, OSError, ValueError) as exc:
        raise ValueError("swing_quote_source_unverified") from exc


def _scope(symbols) -> dict:
    if isinstance(symbols, (list, tuple, set)):
        symbols = {ticker: "stocks" for ticker in symbols}
    if (not isinstance(symbols, dict) or len(symbols) > MAX_TARGETS
            or any(not isinstance(k, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", k)
                   or v != "stocks" for k, v in symbols.items())):
        raise ValueError("swing_quote_scope_invalid")
    return dict(sorted(symbols.items()))


def quote_targets(root: Path, current: datetime) -> list[str]:
    from swing_research_v2 import quote_targets as selected_targets
    return list(_scope(selected_targets(root, current, limit=MAX_TARGETS)))


def _held_rows(root: Path, current: datetime) -> tuple[dict, dict | None]:
    """Reuse the complete currently admitted held batch without another request."""
    try:
        from account_access import capture_version
        snap = feed.load_current(root, current=current, account_version=capture_version(root))
        return snap["rows"], {"path": snap["snapshot_path"], "sha256": snap["snapshot_sha256"]}
    except (OSError, KeyError, ValueError, TypeError):
        return {}, None


def _baselines(root: Path, scope: dict, current: datetime) -> tuple[dict, dict]:
    """Keep canonical full coverage, with separately admitted outside research.

    A private candidate history cannot replace a canonical close or enlarge its
    universe. Its own strict reader must rederive the retained unadjusted source
    lineage and latest required prior close before a quote can use that baseline.
    """
    with feed._safe_target(root, feed.BASELINE).open() as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("swing_quote_canonical_baseline_empty")
    canonical = {row["ticker"] for row in rows}
    selected = {t: kind for t, kind in scope.items() if t in canonical}
    # Even an outside-only observation retains the study's independent current
    # canonical admission, without pretending the outside ticker is in its CSV.
    checked_scope = selected or {rows[0]["ticker"]: "stocks"}
    closes, baseline = feed.canonical_closes(root, checked_scope, current)
    for source in baseline["source_bindings"]:
        if "/history/" in source["path"]:
            history = json.loads(feed._safe_target(root, source["path"]).read_bytes())
            if feed._stamp(history["generated_at"]) > current:
                raise ValueError("swing_quote_baseline_not_available_at_observation")
    closes = {t: p for t, p in closes.items() if t in selected}
    outside = set(scope) - canonical
    if outside:
        try:
            from swing_candidate_history import admitted
            histories = admitted(root, current=current, limit=6)
        except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
            histories = {"histories": {}, "ticker_blockers": {t: str(exc) for t in outside}}
        baseline["research_candidates"] = {}
        baseline["candidate_dependencies"] = {}
        for ticker in sorted(outside):
            try:
                value = histories["histories"][ticker]
                bar = value["bars"][-1]
                if (value.get("price_basis") != "unadjusted"
                        or value.get("common_stock_verified") is not True
                        or bar["session_date"] != baseline["market_session"]
                        or feed._stamp(value["source_available_at"]) > current):
                    raise ValueError("swing_quote_candidate_history_not_current_unadjusted")
                sources = value["source_bindings"]
                if not isinstance(sources, dict) or not sources:
                    raise ValueError("swing_quote_candidate_source_bindings_missing")
                for relative, digest in sources.items():
                    if _sha(feed._safe_target(root, relative).read_bytes()) != digest:
                        raise ValueError("swing_quote_candidate_source_hash_changed")
                    binding = {"path": relative, "sha256": digest}
                    if binding not in baseline["source_bindings"]:
                        baseline["source_bindings"].append(binding)
                close = float(bar["close"])
                if close <= 0 or not math.isfinite(close):
                    raise ValueError("swing_quote_candidate_previous_close_invalid")
                closes[ticker] = close
                baseline["research_candidates"][ticker] = {
                    "previous_close": close, "market_session": bar["session_date"],
                    "price_basis": "unadjusted", "source_bindings": sources}
            except (OSError, KeyError, ValueError, TypeError, IndexError) as exc:
                baseline["candidate_dependencies"][ticker] = histories.get("ticker_blockers", {}).get(ticker) or str(exc)
    return closes, baseline


def _archive_inputs(root: Path, value: dict) -> None:
    """Freeze a replayable admission root before mutable EOD/account pointers move.

    Current consumers still require current pointers. Only explicit historical
    verification reconstructs these exact first-observation bytes in a temporary
    root, so a later close/account update cannot rewrite a forward cohort.
    """
    baseline = value["baseline"]
    required = {item["path"]: item["sha256"] for item in baseline["source_bindings"]}
    required[baseline["path"]] = baseline["sha256"]
    held = False
    for row in value["rows"].values():
        source = row["source"]
        required[source["path"]] = source["sha256"]
        required[source["response"]["path"]] = source["response"]["sha256"]
        if row.get("origin") == "held_scope_reuse":
            held = True
            binding = row["held_snapshot"]
            required[binding["path"]] = binding["sha256"]
            snap = json.loads(feed._source_bytes(root, binding, "snapshots"))
            for original in snap["rows"].values():
                source = original["source"]
                required[source["path"]] = source["sha256"]
                required[source["response"]["path"]] = source["response"]["sha256"]
    account_raws = {}
    if held:
        from account_access import ACCOUNT_INPUTS, account_lock, input_version
        with account_lock(root, shared=True):
            version = input_version(root)
            for row in value["rows"].values():
                if row.get("origin") == "held_scope_reuse":
                    snap = json.loads(feed._source_bytes(root, row["held_snapshot"], "snapshots"))
                    if snap["account_version"] != version:
                        raise ValueError("swing_quote_account_changed_before_archive")
            for relative in ACCOUNT_INPUTS:
                path = feed._safe_target(root, relative)
                if path.exists():
                    account_raws[relative] = path.read_bytes()
                    required[relative] = _sha(account_raws[relative])
    archives = []
    for relative, digest in sorted(required.items()):
        raw = account_raws.get(relative)
        if raw is None:
            raw = feed._safe_target(root, relative).read_bytes()
        if _sha(raw) != digest:
            raise ValueError("swing_quote_input_changed_before_archive")
        archive_relative = f"{REL}/input_history/{digest}.bin"
        target = feed._safe_target(root, archive_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError("swing_quote_input_archive_conflict")
        else:
            with target.open("xb") as stream:
                stream.write(raw)
        archives.append({"original_path": relative, "sha256": digest, "archive_path": archive_relative})
    baseline["input_archives"] = archives


@contextmanager
def _historical_root(root: Path, value: dict):
    archives = value.get("baseline", {}).get("input_archives")
    if not isinstance(archives, list) or not archives:
        raise ValueError("swing_quote_historical_admission_archive_missing")
    required = {item["path"]: item["sha256"] for item in value["baseline"]["source_bindings"]}
    required[value["baseline"]["path"]] = value["baseline"]["sha256"]
    seen = {}
    with tempfile.TemporaryDirectory(prefix="equity-swing-quote-history-") as directory:
        frozen = Path(directory)
        for item in archives:
            digest, relative = item["sha256"], item["original_path"]
            if (not re.fullmatch(r"[0-9a-f]{64}", str(digest))
                    or item["archive_path"] != f"{REL}/input_history/{digest}.bin"
                    or relative in seen):
                raise ValueError("swing_quote_historical_archive_binding_invalid")
            source = feed._safe_target(root, item["archive_path"])
            if _sha(source.read_bytes()) != digest:
                raise ValueError("swing_quote_historical_archive_hash_changed")
            destination = feed._safe_target(frozen, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Read-only immutable archives can be linked into the ephemeral
            # verifier; no original pointer/account path is reopened or written.
            os.link(source, destination)
            seen[relative] = digest
        if any(seen.get(relative) != digest for relative, digest in required.items()):
            raise ValueError("swing_quote_historical_archive_scope_incomplete")
        yield frozen


def collect(root: Path, *, current=None, claim_id: str, client=None, symbols=None) -> dict:
    """Collect at most three selected stocks; never refetch a fresh held mark.

    The production entry derives symbols from validated study definitions. The
    explicit symbols/client arguments support isolated deterministic fixtures.
    No candidate, closed session or absent admitted baseline makes zero calls.
    """
    root = Path(root)
    current = feed._now(current)
    supplied_client = client is not None
    scope = _scope(quote_targets(root, current) if symbols is None else symbols)
    if not isinstance(claim_id, str) or not claim_id or len(claim_id) > 160:
        raise ValueError("swing_quote_claim_identity_required")
    value = {"schema_version": SCHEMA, "generated_at": current.isoformat(),
             "claim_id": claim_id, "session_date": current.date().isoformat(),
             "scope": scope, "rows": {}, "attempts": [], "failures": {},
             "status": "unavailable", "expires_at": None, **AUTHORITY}
    if not scope:
        value.update(status="no_candidates")
    elif not feed.market_open(current):
        value.update(status="market_closed", failures={t: "intraday_market_closed" for t in scope})
    else:
        try:
            closes, value["baseline"] = _baselines(root, scope, current)
        except (OSError, KeyError, ValueError, TypeError, IndexError) as exc:
            value["failures"] = {ticker: str(exc) for ticker in scope}
        else:
            held, held_binding = _held_rows(root, current)
            client = client or feed.NasdaqIntradayClient(root)
            started = time.monotonic()
            for ticker in scope:
                try:
                    if ticker not in closes:
                        raise ValueError("swing_quote_candidate_prior_close_unavailable")
                    if ticker in held:
                        row = dict(held[ticker], origin="held_scope_reuse", held_snapshot=held_binding)
                    else:
                        if time.monotonic() - started > COLLECTION_BUDGET_SECONDS:
                            raise ValueError("swing_quote_collection_budget_exhausted")
                        payload, receipt = client.fetch(ticker, "stocks")
                        value["attempts"].append({"ticker": ticker, **receipt})
                        if receipt.get("error"):
                            raise ValueError(receipt["error"])
                        observed = feed._stamp(receipt["observed_at"])
                        effective = current if supplied_client else feed._now()
                        row = feed.normalize(payload, ticker, "stocks", closes[ticker], observed, effective)
                        row.update(source=receipt, source_url=receipt["source_url"],
                                   previous_close_session=value["baseline"]["market_session"],
                                   origin="candidate_request")
                    value["rows"][ticker] = row
                except (OSError, KeyError, ValueError, TypeError) as exc:
                    value["failures"][ticker] = str(exc)
            final = current if supplied_client else feed._now()
            for ticker, row in list(value["rows"].items()):
                if (not feed.market_open(final)
                        or (final - feed._stamp(row["trade_at"])).total_seconds() > feed.MAX_AGE_SECONDS):
                    del value["rows"][ticker]
                    value["failures"][ticker] = "intraday_price_stale_or_market_closed"
            value["generated_at"] = final.isoformat()
            if feed._trade_span(value["rows"]) > feed.MAX_BATCH_TRADE_SPAN_SECONDS:
                value["failures"]["__scope__"] = "intraday_batch_timestamp_skew"
                value["rows"] = {}
            if value["rows"]:
                value["status"] = "current" if len(value["rows"]) == len(scope) and not value["failures"] else "partial"
                value["expires_at"] = min([feed._stamp(r["trade_at"]) + timedelta(seconds=feed.MAX_AGE_SECONDS)
                    for r in value["rows"].values()] + [regular_close(value["session_date"])]).isoformat()
                try:
                    _archive_inputs(root, value)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    value.update(status="unavailable", rows={}, expires_at=None)
                    value["failures"]["__archive__"] = str(exc)
    binding = _retain(root, value)
    return _projection(root, value, binding, feed._now(value["generated_at"]), require_latest=True)


def _projection(root: Path, value: dict, binding: dict, current: datetime, *,
                require_latest: bool) -> dict:
    if any(value.get(key) != expected for key, expected in AUTHORITY.items()):
        raise ValueError("swing_quote_authority_invalid")
    if require_latest:
        pointer = json.loads(feed._safe_target(root, CURRENT).read_bytes())
        if (pointer.get("schema_version") != SCHEMA or pointer.get("source") != binding
                or pointer.get("generated_at") != value.get("generated_at")
                or pointer.get("status") != value.get("status")):
            raise ValueError("swing_quote_latest_attempt_changed")
    generated = feed._stamp(value["generated_at"])
    if generated > current:
        raise ValueError("swing_quote_future_observation")
    scope = _scope(value["scope"])
    result = {"schema_version": SCHEMA, "generated_at": value["generated_at"],
              "expires_at": None, "status": value["status"], "source": binding,
              "tickers": {}, "failures": dict(value["failures"]),
              "request_count": len(value["attempts"]),
              "held_marks_reused": sum(r.get("origin") == "held_scope_reuse" for r in value["rows"].values()),
              **AUTHORITY}
    if not value["rows"]:
        return result
    if (not feed.market_open(current) or value["session_date"] != current.date().isoformat()
            or generated.date() != current.date()):
        result.update(status="market_closed" if not feed.market_open(current) else "unavailable")
        result["failures"]["__clock__"] = "swing_quote_outside_observed_session"
        return result
    admission = nullcontext(root) if require_latest else _historical_root(root, value)
    with admission as source_root:
        return _admitted_rows(source_root, value, binding, current, scope, result,
                              require_latest=require_latest)


def _admitted_rows(root, value, binding, current, scope, result, *, require_latest):
    generated = feed._stamp(value["generated_at"])
    closes, baseline = _baselines(root, scope, current)
    if ({k: v for k, v in value["baseline"].items() if k not in {"observed_at", "input_archives"}}
            != {k: v for k, v in baseline.items() if k != "observed_at"}):
        raise ValueError("swing_quote_baseline_changed")
    if feed._trade_span(value["rows"]) > feed.MAX_BATCH_TRADE_SPAN_SECONDS:
        raise ValueError("swing_quote_batch_skew")
    for ticker, row in value["rows"].items():
        if ticker not in scope:
            raise ValueError("swing_quote_scope_changed")
        try:
            source = row["source"]
            http = json.loads(feed._source_bytes(root, source, "http_receipts"))
            raw = feed._source_bytes(root, http["response"], "responses")
            expected_url = f"https://api.nasdaq.com/api/quote/{quote(ticker, safe='.-')}/info?assetclass=stocks"
            if (http.get("schema_version") != "equity_intraday_http_receipt_v1"
                    or http.get("ticker") != ticker or http.get("asset_class") != "stocks"
                    or http.get("http_status") != 200 or http.get("error")
                    or http.get("source_url") != expected_url or source.get("source_url") != expected_url
                    or row.get("source_url") != expected_url
                    or http.get("response") != source.get("response")
                    or http.get("response_truncated") is not False
                    or http.get("response_bytes_read") != len(raw)
                    or http.get("observed_at") != source.get("observed_at")):
                raise ValueError("swing_quote_HTTP_binding_invalid")
            requested, observed = feed._stamp(http["requested_at"]), feed._stamp(http["observed_at"])
            if requested > observed or observed > generated:
                raise ValueError("swing_quote_HTTP_clock_invalid")
            normalized = feed.normalize(json.loads(raw), ticker, "stocks", closes[ticker], observed, current)
            expected = {**normalized, "source": source, "source_url": expected_url,
                        "previous_close_session": baseline["market_session"], "origin": row.get("origin")}
            if row.get("origin") == "held_scope_reuse":
                from account_access import capture_version
                held_binding = row["held_snapshot"]
                held = json.loads(feed._source_bytes(root, held_binding, "snapshots"))
                held = feed.validate_snapshot(root, held, current=current,
                    account_version=capture_version(root), require_latest=require_latest)
                expected["held_snapshot"] = held_binding
                if held["rows"].get(ticker) != {k: v for k, v in row.items() if k not in {"origin", "held_snapshot"}}:
                    raise ValueError("swing_quote_held_reuse_mismatch")
            elif row.get("origin") != "candidate_request" or requested < feed._stamp(value["baseline"]["observed_at"]):
                raise ValueError("swing_quote_request_origin_invalid")
            if row != expected:
                raise ValueError("swing_quote_raw_normalization_mismatch")
            expiry = min(feed._stamp(row["trade_at"]) + timedelta(seconds=feed.MAX_AGE_SECONDS),
                         regular_close(value["session_date"]))
            if current >= expiry:
                raise ValueError("intraday_price_stale")
            result["tickers"][ticker] = {"ticker": ticker, "price": row["price"],
                "trade_at": row["trade_at"], "observed_at": row["observed_at"],
                "expires_at": expiry.isoformat(), "baseline_session": baseline["market_session"],
                "baseline_close": closes[ticker], "source": source, "snapshot": binding,
                "source_label": feed.SOURCE_LABEL, "execution_quote": False}
        except (OSError, KeyError, ValueError, TypeError) as exc:
            result["failures"][ticker] = str(exc)
    if result["tickers"]:
        result["status"] = "current" if set(result["tickers"]) == set(scope) and not result["failures"] else "partial"
        result["expires_at"] = min(r["expires_at"] for r in result["tickers"].values())
    else:
        result["status"] = "unavailable"
    return result


def revalidate_quote_context(root: Path, context: dict, current: datetime,
                             scope=None, baseline_bindings=None, *, require_latest=True) -> dict:
    """Require exact immutable proof; historical mode cannot establish a live mark."""
    root, current = Path(root), feed._now(current)
    value = _source(root, context["source"])
    expected = _projection(root, value, context["source"], current, require_latest=require_latest)
    compared = expected
    if scope is not None and set(context.get("tickers", {})) != set(expected["tickers"]):
        compared = dict(expected, tickers={t: r for t, r in expected["tickers"].items() if t in set(scope)})
    if compared != context:
        raise ValueError("swing_quote_projection_changed_or_expired")
    if baseline_bindings and value.get("baseline"):
        b = value["baseline"]
        hashes = {entry["sha256"] for entry in b["source_bindings"]}
        if (baseline_bindings.get("snapshot_sha256", b["sha256"]) != b["sha256"]
                or baseline_bindings.get("market_session", b["market_session"]) != b["market_session"]
                or (baseline_bindings.get("history_sha256") and baseline_bindings["history_sha256"] not in hashes)):
            raise ValueError("swing_quote_study_baseline_changed")
    if scope is not None:
        wanted = set(scope)
        expected = dict(expected, tickers={t: r for t, r in expected["tickers"].items() if t in wanted})
    return expected


def read_quote_context(root: Path, current: datetime, scope=None) -> dict:
    """Offline read; failed latest attempts never fall back to earlier prices."""
    root, current = Path(root), feed._now(current)
    try:
        pointer = json.loads(feed._safe_target(root, CURRENT).read_bytes())
        value = _source(root, pointer["source"])
        result = _projection(root, value, pointer["source"], current, require_latest=True)
        if scope is not None:
            result["tickers"] = {t: r for t, r in result["tickers"].items() if t in set(scope)}
        return result
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"schema_version": SCHEMA, "generated_at": None, "expires_at": None,
                "status": "unavailable", "tickers": {}, "failures": {"__context__": str(exc)}, **AUTHORITY}
