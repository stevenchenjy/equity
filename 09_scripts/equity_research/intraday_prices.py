"""Source-bound regular-session last-sale observations, isolated from EOD inputs.

This credential-free Nasdaq public quote is an alternative last sale, not a
consolidated NBBO, executable quote, spread, or promise of real-time coverage.
Only an explicitly real-time, timestamped regular-session observation is usable.
A failed latest attempt fences a previous successful snapshot. Nothing here
updates an order, canonical close, company valuation, or email eligibility.
"""
from __future__ import annotations

import csv
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time as clock_time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from daily_common import atomic_write_json, last_completed_market_session, now_et
from investment_plans import regular_close
import market_backup
from market_data_adapter import _NoRedirectHandler

ET = ZoneInfo("America/New_York")
SCHEMA = "equity_intraday_prices_v1"
REL = "03_source_data/equity_research/intraday_prices.local"
CURRENT = REL + "/current.json"
BASELINE = "03_source_data/equity_research/market_data_snapshot.csv"
MAX_AGE_SECONDS = 300
MAX_BATCH_TRADE_SPAN_SECONDS = 120
MAX_SCOPE = 64
COLLECTION_BUDGET_SECONDS = 90
SOURCE_LABEL = "Nasdaq public last sale (alternative market data; not consolidated NBBO)"
SOURCE_DOCS = ["https://www.nasdaq.com/products/data/equities/nasdaq-last-sale",
               "https://www.nasdaq.com/market-activity/stocks/msft"]


class IntradayPriceError(ValueError):
    pass


def _stamp(value) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(ET)
    except (TypeError, ValueError):
        raise IntradayPriceError("intraday_timestamp_invalid") from None


def _now(value=None) -> datetime:
    return _stamp(value or now_et())


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _safe_target(root: Path, relative: str | Path) -> Path:
    """Reject symlinks inside the authority root, including parent directories."""
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise IntradayPriceError("intraday_unsafe_source_path")
    target = Path(root)
    for part in relative.parts:
        target /= part
        if target.is_symlink():
            raise IntradayPriceError("intraday_unsafe_source_path")
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise IntradayPriceError("intraday_unsafe_source_path")
    return target


def _retain(root: Path, directory: str, raw: bytes, suffix="json") -> dict:
    digest = _sha(raw)
    path = Path(REL) / directory / (digest + "." + suffix)
    target = _safe_target(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and target.read_bytes() != raw):
        raise IntradayPriceError("intraday_retained_bytes_conflict")
    if not target.exists():
        target.write_bytes(raw)
    return {"path": str(path), "sha256": digest}


def _source_bytes(root: Path, source: dict, directory: str) -> bytes:
    try:
        path = Path(source["path"])
        if (path.is_absolute() or ".." in path.parts or path.parent != Path(REL) / directory
                or re.fullmatch(r"[a-f0-9]{64}", source["sha256"]) is None
                or path.stem != source["sha256"] or (root / path).is_symlink()):
            raise ValueError()
        raw = _safe_target(root, path).read_bytes()
        if _sha(raw) != source["sha256"]:
            raise ValueError()
        return raw
    except (KeyError, TypeError, ValueError, OSError):
        raise IntradayPriceError("intraday_retained_source_invalid") from None


def _scope(symbols: dict) -> dict:
    if (not isinstance(symbols, dict) or not symbols or len(symbols) > MAX_SCOPE
            or any(not isinstance(k, str) or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", k) is None
                   or v not in {"stocks", "etf"} for k, v in symbols.items())):
        raise IntradayPriceError("intraday_scope_invalid")
    return dict(sorted(symbols.items()))


def _session(current: datetime) -> tuple[datetime, datetime]:
    close = regular_close(str(current.date()))
    return datetime.combine(current.date(), time(9, 30), ET), close


def market_open(current=None) -> bool:
    current = _now(current)
    try:
        start, end = _session(current)
        return start <= current < end
    except ValueError:
        return False


def canonical_closes(root: Path, symbols: dict, current=None) -> tuple[dict, dict]:
    """Require the admitted full-universe EOD history, not a CSV quality label."""
    current = _now(current)
    scope = _scope(symbols)
    try:
        target = _safe_target(root, BASELINE)
        raw = target.read_bytes()
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        expected = str(last_completed_market_session(current))
        full_tickers = [row["ticker"] for row in rows]
        pointer_path = _safe_target(root, market_backup.CURRENT)
        pointer_raw = pointer_path.read_bytes()
        pointer = json.loads(pointer_raw)
        source_bindings = [{"path": market_backup.CURRENT, "sha256": _sha(pointer_raw)}]
        digest = pointer["history_sha256"]
        seen = set()
        while True:
            if (not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                    or digest in seen or len(seen) >= 512):
                raise ValueError()
            seen.add(digest)
            history_relative = f"{market_backup.REL}/history/{digest}.json"
            history_raw = _safe_target(root, history_relative).read_bytes()
            if _sha(history_raw) != digest:
                raise ValueError()
            current_history = json.loads(history_raw)
            source_bindings.append({"path": history_relative, "sha256": digest})
            for source in current_history.get("observations", []):
                retained_raw = _safe_target(root, source["path"]).read_bytes()
                if _sha(retained_raw) != source["sha256"]:
                    raise ValueError()
                source_bindings.append({"path": source["path"], "sha256": source["sha256"]})
            parent = current_history.get("parent_history_sha256")
            if not parent:
                break
            digest = parent
        # Run the existing admission only after preflighting every source path.
        # It revalidates complete one-year session coverage, numeric/OHLCV sanity
        # and source lineage for either admitted EOD feed.
        history = market_backup.load_baseline(root, full_tickers)
        if history.get("snapshot_sha256") != _sha(raw) or history.get("market_session") != expected:
            raise ValueError()
        for row in rows:
            if (row["market_session_date"] != expected or row.get("data_quality_label") != "ok"
                    or abs(Decimal(row["last_price"]) - Decimal(str(history["tickers"][row["ticker"]]["bars"][-1]["close"])))
                    > Decimal("0.000051")):
                raise ValueError()
        selected = {}
        for ticker in scope:
            matching = [row for row in rows if row.get("ticker") == ticker]
            if len(matching) != 1:
                raise ValueError()
            row = matching[0]
            price = float(row["last_price"])
            if (not math.isfinite(price) or price <= 0 or row["market_session_date"] != expected
                    or row.get("data_quality_label") != "ok"):
                raise ValueError()
            selected[ticker] = price
        if target.read_bytes() != raw or pointer_path.read_bytes() != pointer_raw:
            raise ValueError()
        return selected, {"path": BASELINE, "sha256": _sha(raw), "market_session": expected,
            "observed_at": current.isoformat(), "data_source": history["data_source"],
            "full_scope": full_tickers, "source_bindings": source_bindings}
    except (KeyError, ValueError, OSError, UnicodeError, InvalidOperation, TypeError, OverflowError):
        raise IntradayPriceError("intraday_canonical_previous_close_unavailable") from None


def _number(value, *, signed=False, percent=False) -> Decimal:
    pattern = r"[+-]?" if signed else r"\$?"
    pattern += r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    if percent:
        pattern += "%"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise IntradayPriceError("intraday_numeric_invalid")
    try:
        result = Decimal(value.replace("$", "").replace(",", "").replace("%", ""))
        if not result.is_finite() or (not signed and result <= 0):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError):
        raise IntradayPriceError("intraday_numeric_invalid") from None


def _trade_stamp(value) -> datetime:
    # Date-only values are EOD observations, even if the response was just fetched.
    if not isinstance(value, str) or not value.endswith(" ET"):
        raise IntradayPriceError("intraday_trade_time_missing")
    for fmt in ("%b %d, %Y %I:%M:%S %p ET", "%b %d, %Y %I:%M %p ET"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=ET)
        except ValueError:
            pass
    raise IntradayPriceError("intraday_trade_time_missing")


def normalize(payload, ticker: str, asset_class: str, previous_close: float,
              observed_at: datetime, current=None) -> dict:
    current = _now(current or observed_at)
    observed_at = _now(observed_at)
    if not market_open(current) or not market_open(observed_at):
        raise IntradayPriceError("intraday_market_closed")
    if (not isinstance(payload, dict) or not isinstance(payload.get("status"), dict)
            or payload["status"].get("rCode") != 200
            or payload["status"].get("bCodeMessage") not in (None, [])
            or not isinstance(payload.get("data"), dict)):
        raise IntradayPriceError("intraday_provider_response_invalid")
    data = payload["data"]
    primary = data.get("primaryData")
    if (data.get("symbol") != ticker or data.get("assetClass") != asset_class.upper()
            or data.get("marketStatus") != "Open" or not isinstance(primary, dict)):
        raise IntradayPriceError("intraday_symbol_asset_or_session_conflict")
    if primary.get("isRealTime") is not True:
        raise IntradayPriceError("intraday_delay_unverified")
    if primary.get("currency") not in (None, "USD"):
        raise IntradayPriceError("intraday_currency_invalid")
    trade = _trade_stamp(primary.get("lastTradeTimestamp"))
    start, end = _session(current)
    if trade.date() != current.date() or not start <= trade < end:
        raise IntradayPriceError("intraday_trade_session_invalid")
    if observed_at > current or trade > observed_at or trade > current:
        raise IntradayPriceError("intraday_future_timestamp")
    if (current - trade).total_seconds() > MAX_AGE_SECONDS:
        raise IntradayPriceError("intraday_price_stale")
    price = _number(primary.get("lastSalePrice"))
    change = _number(primary.get("netChange"), signed=True)
    pct = _number(primary.get("percentageChange"), signed=True, percent=True)
    base = Decimal(str(previous_close))
    if not base.is_finite() or base <= 0 or abs(price - change - base) > Decimal("0.005"):
        raise IntradayPriceError("intraday_previous_close_conflict")
    # Provider percentages are displayed to hundredths; this is display precision,
    # not a portfolio loss or entry threshold.
    if abs(pct - (price / base - 1) * 100) > Decimal("0.011"):
        raise IntradayPriceError("intraday_percentage_conflict")
    return {"ticker": ticker, "asset_class": asset_class, "price": float(price),
            "trade_at": trade.isoformat(), "observed_at": observed_at.isoformat(),
            "previous_close": float(base), "net_change": float(change),
            "change_pct": float(pct), "delay_status": "provider_realtime",
            "source_label": SOURCE_LABEL, "timestamp_precision":
                "second" if re.search(r"\d{1,2}:\d{2}:\d{2}", primary["lastTradeTimestamp"]) else "minute"}


class NasdaqIntradayClient:
    """One bounded unauthenticated request per symbol; no redirects or retry."""
    def __init__(self, root: Path, *, get=None, sleep=clock_time.sleep,
                 monotonic=clock_time.monotonic, now=now_et):
        self.root, self.get, self.sleep, self.clock, self.now = root, get, sleep, monotonic, now
        self.last = None

    def fetch(self, ticker: str, asset_class: str) -> tuple[object, dict]:
        _scope({ticker: asset_class})
        url = f"https://api.nasdaq.com/api/quote/{quote(ticker, safe='.-')}/info?assetclass={asset_class}"
        if self.last is not None:
            self.sleep(max(0, 1.0 - (self.clock() - self.last)))
        self.last = self.clock()
        started = _now(self.now()).isoformat()
        raw, status, headers, error = b"", None, {}, None
        try:
            if self.get:
                raw = self.get(url)
                status = 200
            else:
                req = Request(url, headers={"Accept": "application/json", "User-Agent":
                    "Mozilla/5.0 (compatible; personal equity research)"})
                with build_opener(_NoRedirectHandler()).open(req, timeout=8) as response:
                    status, headers = response.status, dict(response.headers)
                    raw = response.read(2_000_001)
            if not isinstance(raw, bytes) or len(raw) > 2_000_000:
                raise IntradayPriceError("intraday_response_size_invalid")
            if status != 200:
                raise IntradayPriceError("intraday_http_failed")
        except HTTPError as exc:
            status, headers = exc.code, dict(exc.headers)
            raw = exc.read(2_000_001)
            error = "intraday_http_failed"
        except Exception as exc:
            error = str(exc) if isinstance(exc, IntradayPriceError) else "intraday_request_failed"
        observed = _now(self.now()).isoformat()
        source = _retain(self.root, "responses", raw if isinstance(raw, bytes) else b"", "bin")
        receipt = {"schema_version": "equity_intraday_http_receipt_v1", "ticker": ticker,
            "asset_class": asset_class, "source_url": url, "requested_at": started,
            "observed_at": observed, "http_status": status, "response_headers": headers,
            "response": source, "response_bytes_read": len(raw) if isinstance(raw, bytes) else 0,
            "response_truncated": isinstance(raw, bytes) and len(raw) > 2_000_000, "error": error}
        binding = _retain(self.root, "http_receipts", _bytes(receipt))
        binding.update(source_url=url, observed_at=observed, response=source)
        if error:
            return None, {**binding, "error": error}
        try:
            return json.loads(raw), binding
        except (ValueError, UnicodeError):
            return None, {**binding, "error": "intraday_json_invalid"}


def _publish(root: Path, snapshot: dict) -> dict:
    binding = _retain(root, "snapshots", _bytes(snapshot))
    pointer = {"schema_version": "equity_intraday_prices_pointer_v1", "snapshot": binding,
               "status": snapshot["status"], "generated_at": snapshot["generated_at"]}
    atomic_write_json(_safe_target(root, CURRENT), pointer)
    return {**snapshot, "snapshot_path": binding["path"], "snapshot_sha256": binding["sha256"]}


def _trade_span(rows: dict) -> float:
    stamps = [_stamp(row["trade_at"]) for row in rows.values()]
    return (max(stamps) - min(stamps)).total_seconds() if stamps else 0


def _empty_snapshot(symbols: dict, account_version: str, claim_id: str, current: datetime) -> dict:
    scope = _scope(symbols)
    if not isinstance(account_version, str) or not account_version or not isinstance(claim_id, str) or not claim_id:
        raise IntradayPriceError("intraday_account_or_claim_binding_required")
    return {"schema_version": SCHEMA, "generated_at": current.isoformat(),
        "session_date": str(current.date()), "claim_id": claim_id, "account_version": account_version,
        "symbols": list(scope), "asset_classes": scope, "rows": {}, "failures": {}, "attempts": [],
        "status": "unavailable", "complete": False, "expires_at": None,
        "source_label": SOURCE_LABEL, "source_documentation": SOURCE_DOCS,
        "execution_quote": False, "canonical_eod_modified": False}


def record_unavailable(root: Path, symbols: dict, *, account_version: str, claim_id: str,
                       reason: str, current=None) -> dict:
    """Retain a truthful unavailable observation without a public network call.

    Offline recomposition uses this when no intraday attempt has been admitted.
    It cannot create marks or claim that a source was queried successfully.
    """
    if (not isinstance(reason, str) or not reason.strip() or len(reason) > 300
            or any(ord(char) < 32 for char in reason)):
        raise IntradayPriceError("intraday_unavailable_reason_invalid")
    snapshot = _empty_snapshot(symbols, account_version, claim_id, _now(current))
    snapshot["failures"] = {ticker: reason for ticker in snapshot["symbols"]}
    return _publish(Path(root), snapshot)


def collect(root: Path, symbols: dict, *, account_version: str, claim_id: str,
            current=None, client=None) -> dict:
    root = Path(root)
    current = _now(current)
    scope = _scope(symbols)
    snapshot = _empty_snapshot(scope, account_version, claim_id, current)
    if not market_open(current):
        snapshot["status"] = "market_closed"
        snapshot["failures"] = {ticker: "intraday_market_closed" for ticker in scope}
        return _publish(root, snapshot)
    try:
        closes, snapshot["baseline"] = canonical_closes(root, scope, current)
    except IntradayPriceError as exc:
        snapshot["failures"] = {ticker: str(exc) for ticker in scope}
        return _publish(root, snapshot)
    supplied_client = client is not None
    client = client or NasdaqIntradayClient(root)
    started = clock_time.monotonic()
    for ticker, asset_class in scope.items():
        if clock_time.monotonic() - started > COLLECTION_BUDGET_SECONDS:
            snapshot["failures"][ticker] = "intraday_collection_budget_exhausted"
            continue
        try:
            payload, receipt = client.fetch(ticker, asset_class)
            snapshot["attempts"].append({"ticker": ticker, **receipt})
            if receipt.get("error"):
                raise IntradayPriceError(receipt["error"])
            observed = _stamp(receipt["observed_at"])
            effective = current if supplied_client else _now()
            row = normalize(payload, ticker, asset_class, closes[ticker], observed, effective)
            row.update(source=receipt, source_url=receipt["source_url"],
                       previous_close_session=snapshot["baseline"]["market_session"])
            snapshot["rows"][ticker] = row
        except (IntradayPriceError, KeyError, ValueError) as exc:
            snapshot["failures"][ticker] = str(exc)
    # Do not publish a complete mark if a slow batch has made its earliest trade old.
    final = current if supplied_client else _now()
    for ticker, row in list(snapshot["rows"].items()):
        if (final - _stamp(row["trade_at"])).total_seconds() > MAX_AGE_SECONDS or not market_open(final):
            snapshot["failures"][ticker] = "intraday_price_stale" if market_open(final) else "intraday_market_closed"
            del snapshot["rows"][ticker]
    if _trade_span(snapshot["rows"]) > MAX_BATCH_TRADE_SPAN_SECONDS:
        # Keep individual source-bound observations, but do not present their
        # differently timed prices as a coherent complete portfolio mark.
        snapshot["failures"]["__scope__"] = "intraday_batch_timestamp_skew"
    snapshot["generated_at"] = final.isoformat()
    snapshot["complete"] = len(snapshot["rows"]) == len(scope) and not snapshot["failures"]
    snapshot["status"] = "current" if snapshot["complete"] else "partial" if snapshot["rows"] else "unavailable"
    if snapshot["rows"]:
        snapshot["expires_at"] = min([_stamp(row["trade_at"]) + timedelta(seconds=MAX_AGE_SECONDS)
            for row in snapshot["rows"].values()] + [regular_close(snapshot["session_date"])]).isoformat()
    return _publish(root, snapshot)


def load_latest(root: Path) -> dict:
    """Read the exact latest attempt, including explicit unavailable dependencies."""
    try:
        pointer = json.loads(_safe_target(Path(root), CURRENT).read_bytes())
        if pointer.get("schema_version") != "equity_intraday_prices_pointer_v1":
            raise ValueError()
        binding = pointer["snapshot"]
        result = json.loads(_source_bytes(Path(root), binding, "snapshots"))
        if (result.get("schema_version") != SCHEMA or pointer.get("status") != result.get("status")
                or pointer.get("generated_at") != result.get("generated_at")):
            raise ValueError()
        return {**result, "snapshot_path": binding["path"], "snapshot_sha256": binding["sha256"]}
    except (OSError, KeyError, ValueError, TypeError):
        raise IntradayPriceError("intraday_latest_attempt_unavailable") from None


def validate_snapshot(root: Path, snapshot: dict, *, current=None, account_version=None,
                      symbols=None, claim_id=None, require_latest=True) -> dict:
    """Revalidate retained source bytes and admission at the supplied time.

    ``require_latest=False`` is reserved for verifying an immutable historical
    publication at its original timestamp. It cannot establish a current mark;
    current consumers and ``load_current`` always require the latest attempt.
    """
    current = _now(current)
    root = Path(root)
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != SCHEMA
            or snapshot.get("status") != "current" or snapshot.get("complete") is not True):
        raise IntradayPriceError("intraday_complete_current_scope_required")
    core = {key: value for key, value in snapshot.items() if key not in {"snapshot_path", "snapshot_sha256"}}
    digest = _sha(_bytes(core))
    binding = {"path": f"{REL}/snapshots/{digest}.json", "sha256": digest}
    if ((snapshot.get("snapshot_path", binding["path"]) != binding["path"])
            or snapshot.get("snapshot_sha256", digest) != digest):
        raise IntradayPriceError("intraday_snapshot_content_binding_invalid")
    if json.loads(_source_bytes(root, binding, "snapshots")) != core:
        raise IntradayPriceError("intraday_snapshot_content_binding_invalid")
    if require_latest and digest != load_latest(root).get("snapshot_sha256"):
        raise IntradayPriceError("intraday_latest_attempt_changed")
    scope = _scope(snapshot.get("asset_classes"))
    if (snapshot.get("symbols") != list(scope) or set(snapshot.get("rows", {})) != set(scope)
            or snapshot.get("failures") or snapshot.get("execution_quote") is not False
            or snapshot.get("canonical_eod_modified") is not False
            or snapshot.get("source_label") != SOURCE_LABEL):
        raise IntradayPriceError("intraday_snapshot_scope_invalid")
    if _trade_span(snapshot["rows"]) > MAX_BATCH_TRADE_SPAN_SECONDS:
        raise IntradayPriceError("intraday_batch_timestamp_skew")
    requested = set(symbols) if symbols is not None else set(scope)
    if (requested != set(scope) or (isinstance(symbols, dict) and _scope(symbols) != scope)
            or (account_version is not None and snapshot.get("account_version") != account_version)
            or (claim_id is not None and snapshot.get("claim_id") != claim_id)):
        raise IntradayPriceError("intraday_snapshot_binding_changed")
    if not market_open(current):
        raise IntradayPriceError("intraday_market_closed")
    generated = _stamp(snapshot.get("generated_at"))
    if generated > current or generated.date() != current.date() or snapshot.get("session_date") != str(current.date()):
        raise IntradayPriceError("intraday_snapshot_clock_invalid")
    if _stamp(snapshot.get("expires_at")) < current:
        raise IntradayPriceError("intraday_price_stale")
    closes, baseline = canonical_closes(root, scope, current)
    supplied_baseline = snapshot.get("baseline", {})
    if ({key: value for key, value in supplied_baseline.items() if key != "observed_at"}
            != {key: value for key, value in baseline.items() if key != "observed_at"}):
        raise IntradayPriceError("intraday_previous_close_binding_changed")
    observed_times = []
    baseline_observed = _stamp(supplied_baseline.get("observed_at"))
    if baseline_observed > generated or baseline_observed.date() != current.date():
        raise IntradayPriceError("intraday_previous_close_clock_invalid")
    for ticker, row in snapshot["rows"].items():
        source = row.get("source", {})
        receipt = json.loads(_source_bytes(root, source, "http_receipts"))
        raw = _source_bytes(root, receipt.get("response", {}), "responses")
        expected_url = f"https://api.nasdaq.com/api/quote/{quote(ticker, safe='.-')}/info?assetclass={scope[ticker]}"
        if (receipt.get("schema_version") != "equity_intraday_http_receipt_v1"
                or receipt.get("ticker") != ticker or receipt.get("asset_class") != scope[ticker]
                or receipt.get("source_url") != expected_url or source.get("source_url") != expected_url
                or row.get("source_url") != expected_url or receipt.get("http_status") != 200
                or receipt.get("error") or receipt.get("response") != source.get("response")
                or receipt.get("response_truncated") is not False
                or receipt.get("response_bytes_read") != len(raw) or len(raw) > 2_000_000
                or receipt.get("observed_at") != source.get("observed_at")):
            raise IntradayPriceError("intraday_http_binding_invalid")
        observed = _stamp(receipt["observed_at"])
        requested_at = _stamp(receipt.get("requested_at"))
        if requested_at < baseline_observed or requested_at > observed or observed > generated:
            raise IntradayPriceError("intraday_http_clock_invalid")
        normalized = normalize(json.loads(raw), ticker, scope[ticker], closes[ticker], observed, current)
        expected_row = {**normalized, "source": source, "source_url": expected_url,
                        "previous_close_session": baseline["market_session"]}
        if row != expected_row:
            raise IntradayPriceError("intraday_normalized_source_mismatch")
        observed_times.append(_stamp(row["trade_at"]) + timedelta(seconds=MAX_AGE_SECONDS))
    expected_expiry = min(observed_times + [regular_close(snapshot["session_date"])])
    if _stamp(snapshot["expires_at"]) != expected_expiry:
        raise IntradayPriceError("intraday_expiry_invalid")
    return snapshot


def load_current(root: Path, **kwargs) -> dict:
    kwargs["require_latest"] = True
    return validate_snapshot(Path(root), load_latest(Path(root)), **kwargs)
