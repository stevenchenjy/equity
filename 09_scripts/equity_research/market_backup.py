"""Validated unadjusted-history continuity with a bounded public Nasdaq extension.

Nasdaq's historical adjustment semantics are not assumed equivalent to Massive.
Old validated unadjusted bars are retained; only new session bars are admitted,
after exact session coverage and two overlapping closes agree to displayed
half-cent precision. Every failed/partial batch preserves the canonical files.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener

from daily_common import atomic_write_json, atomic_write_text, is_us_market_session_date, now_et, sha256_file
from market_data_adapter import MassiveB2Error, _NoRedirectHandler

SOURCE = "massive_unadjusted_history_nasdaq_eod_extension"
PRIMARY = "massive_stocks_basic_eod"
REL = "03_source_data/equity_research/market_feed.local"
CURRENT = REL + "/current.json"
SCHEMA = "equity_unadjusted_market_history_v1"
FIELDS = ("open", "high", "low", "close", "volume")


class BackupError(ValueError):
    pass


def sessions(start: date, end: date) -> list[date]:
    result = []
    while start <= end:
        if is_us_market_session_date(start):
            result.append(start)
        start += timedelta(days=1)
    return result


def checked_bars(bars: object, end: date) -> list[dict]:
    """Require the full same one-year session sequence, not just two closes."""
    if not isinstance(bars, list):
        raise BackupError("backup_history_invalid")
    expected = sessions(end - timedelta(weeks=52), end)
    if [b.get("session_date") for b in bars if isinstance(b, dict)] != [str(d) for d in expected] or len(bars) != len(expected):
        raise BackupError("backup_history_session_sequence_invalid")
    for bar in bars:
        if any(type(bar.get(k)) not in (int, float) or not math.isfinite(bar[k]) for k in FIELDS):
            raise BackupError("backup_history_numeric_invalid")
        if (min(bar[k] for k in FIELDS[:4]) <= 0 or bar["volume"] < 0
                or not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]):
            raise BackupError("backup_history_ohlcv_invalid")
    return bars


def checked_bundle(bundle: object, tickers: list[str]) -> dict:
    if (not isinstance(bundle, dict) or bundle.get("schema_version") != SCHEMA
            or bundle.get("price_basis") != "unadjusted" or bundle.get("data_source") not in {PRIMARY, SOURCE}
            or set(bundle.get("tickers", {})) != set(tickers) or len(set(tickers)) != len(tickers)):
        raise BackupError("backup_baseline_scope_or_basis_invalid")
    try:
        end = date.fromisoformat(bundle["market_session"])
        observed = datetime.fromisoformat(bundle["generated_at"])
        if observed.tzinfo is None or observed > now_et() or end > observed.date():
            raise ValueError()
        for ticker, row in bundle["tickers"].items():
            if not row.get("source_url", "").startswith(("https://api.massive.com/", "https://api.nasdaq.com/")):
                raise ValueError()
            checked_bars(row["bars"], end)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("backup_baseline_invalid") from None
    return bundle


def enabled(root: Path) -> bool:
    path = root / "01_policies/market_data_feeds.json"
    if not path.exists():
        return False  # Old offline fixtures and pre-adoption checkouts.
    policy = json.loads(path.read_text())
    if (policy.get("schema_version") != "equity_market_data_feeds_v1"
            or policy.get("primary") != PRIMARY or policy.get("backup") != SOURCE
            or policy.get("backup_origin") != "https://api.nasdaq.com"
            or policy.get("no_email_or_execution") is not True):
        raise BackupError("market_feed_policy_invalid")
    return policy.get("backup_enabled") is True


def _load_retained_baseline(root: Path) -> dict:
    pointer = json.loads((root / CURRENT).read_text())
    name = pointer.get("history_path", "")
    if (pointer.get("schema_version") != "equity_market_history_pointer_v1"
            or re.fullmatch(r"history/[a-f0-9]{64}\.json", name) is None
            or Path(name).stem != pointer.get("history_sha256")):
        raise BackupError("backup_history_locator_invalid")
    path = root / REL / name
    if path.is_symlink() or sha256_file(path) != pointer.get("history_sha256"):
        raise BackupError("backup_history_hash_mismatch")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("tickers"), dict):
        raise BackupError("backup_baseline_scope_or_basis_invalid")
    bundle = checked_bundle(value, list(value["tickers"]))
    if pointer.get("snapshot_sha256") != bundle.get("snapshot_sha256"):
        raise BackupError("backup_snapshot_binding_invalid")
    verify_history_sources(root, bundle)
    return bundle


def load_baseline(root: Path, tickers: list[str]) -> dict:
    return checked_bundle(_load_retained_baseline(root), tickers)


def _seed_held_primary_history(root: Path, base: dict, tickers: list[str],
                               held_only_tickers: list[str] | tuple[str, ...], primary_client) -> tuple[dict, list[dict]]:
    """Extend in-memory scope using complete primary unadjusted observations.

    The retained pointer and canonical files are untouched. Newly held symbols
    cannot inherit Nasdaq's historical adjustment basis or enter the candidate
    universe. Their original primary observations remain bound to the eventual
    whole-batch publication alongside the existing baseline lineage.
    """
    retained, requested = set(base["tickers"]), set(tickers)
    missing = requested - retained
    if requested == retained and len(requested) == len(tickers):
        return base, []
    if (not retained < requested or len(requested) != len(tickers)
            or not missing <= set(held_only_tickers) or primary_client is None):
        raise BackupError("backup_baseline_scope_or_basis_invalid")
    result, receipts = copy.deepcopy(base), []
    end = date.fromisoformat(base["market_session"])
    start = end - timedelta(weeks=52)
    for ticker in sorted(missing):
        if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) is None:
            raise BackupError("backup_primary_seed_scope_invalid")
        try:
            observed = primary_client.fetch_daily_bars(ticker, start_date=start, end_date=end)
        except MassiveB2Error as exc:
            raise BackupError("backup_primary_seed_" + exc.code) from None
        bars = [{"session_date": str(bar["session_date"]),
                 **{key: bar[key] for key in FIELDS}} for bar in observed]
        checked_bars(bars, end)
        url = f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}?adjusted=false"
        observation = {"schema_version": "equity_primary_held_history_seed_v1", "ticker": ticker,
            "kind": "labelled_normalized_provider_observation_not_original_http_response",
            "price_basis": "unadjusted", "source_url": url, "observed_at": now_et().isoformat(),
            "market_session": str(end), "bars": bars}
        raw = (json.dumps(observation, indent=2, sort_keys=True) + "\n").encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = root / REL / "responses" / (digest + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and path.read_bytes() != raw):
            raise BackupError("backup_primary_seed_observation_conflict")
        if not path.exists():
            path.write_bytes(raw)
        receipts.append({"ticker": ticker, "source_url": url, "observed_at": observation["observed_at"],
            "path": str(path.relative_to(root)), "sha256": digest, "price_basis": "unadjusted",
            "kind": observation["kind"]})
        result["tickers"][ticker] = {"source_url": url, "bars": bars}
    return checked_bundle(result, tickers), receipts


def verify_history_sources(root: Path, bundle: dict) -> None:
    """Retain a verifiable chain back to the original unadjusted baseline."""
    seen = set()
    current = bundle
    while True:
        for source in current.get("observations", []):
            path = Path(source["path"])
            if (path.is_absolute() or ".." in path.parts or not str(path).startswith(REL + "/responses/")
                    or sha256_file(root / path) != source["sha256"]):
                raise BackupError("backup_retained_source_changed")
        parent = current.get("parent_history_sha256")
        if not parent:
            if current["data_source"] != PRIMARY:
                raise BackupError("backup_primary_baseline_missing")
            return
        if re.fullmatch(r"[a-f0-9]{64}", str(parent)) is None or parent in seen or len(seen) >= 512:
            raise BackupError("backup_history_lineage_invalid")
        seen.add(parent)
        path = root / REL / "history" / (parent + ".json")
        if path.is_symlink() or sha256_file(path) != parent:
            raise BackupError("backup_parent_history_changed")
        previous = json.loads(path.read_text())
        if previous["market_session"] >= current["market_session"]:
            raise BackupError("backup_history_lineage_clock_invalid")
        current = previous


def _number(value: object, *, volume: bool = False) -> float:
    if not isinstance(value, str) or re.fullmatch(r"\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", value) is None:
        raise BackupError("nasdaq_numeric_invalid")
    try:
        number = Decimal(value.replace("$", "").replace(",", ""))
    except InvalidOperation:
        raise BackupError("nasdaq_numeric_invalid") from None
    if not number.is_finite() or number < 0 or (not volume and number == 0) or (volume and number != number.to_integral_value()):
        raise BackupError("nasdaq_numeric_invalid")
    return float(number)


def normalize(payload: object, ticker: str, start: date, end: date) -> list[dict]:
    if (not isinstance(payload, dict) or payload.get("status", {}).get("rCode") != 200
            or payload.get("status", {}).get("bCodeMessage") not in (None, [])
            or not isinstance(payload.get("data"), dict) or payload["data"].get("symbol") != ticker):
        raise BackupError("nasdaq_response_invalid")
    data = payload["data"]
    table = data.get("tradesTable") or {}
    raw_rows = table.get("rows")
    if (not isinstance(raw_rows, list) or type(data.get("totalRecords")) is not int
            or data["totalRecords"] != len(raw_rows) or table.get("headers", {}).get("close") != "Close/Last"):
        raise BackupError("nasdaq_partial_or_schema_invalid")
    result = []
    try:
        for row in raw_rows:
            day = datetime.strptime(row["date"], "%m/%d/%Y").date()
            result.append({"session_date": str(day), **{k: _number(row[k], volume=k == "volume") for k in FIELDS}})
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("nasdaq_row_invalid") from None
    # The public endpoint returns descending sessions. Never silently sort away
    # duplicates or disorder, and never accept pagination/truncated histories.
    if [b["session_date"] for b in result] != [str(d) for d in reversed(sessions(start, end))]:
        raise BackupError("nasdaq_session_sequence_invalid")
    result.reverse()
    for bar in result:
        if not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
            raise BackupError("nasdaq_ohlc_invalid")
    return result


class NasdaqHistoricalClient:
    """No key, redirect, retry or paging. One paced bounded request per ticker."""
    def __init__(self, root: Path, *, get=None, sleep=time.sleep, monotonic=time.monotonic):
        self.root, self.get, self.sleep, self.clock = root, get, sleep, monotonic
        self.last = None
        self.receipts = []

    def fetch(self, ticker: str, asset_class: str, start: date, end: date) -> tuple[list[dict], str]:
        if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) is None or asset_class not in {"stocks", "etf"} or start >= end:
            raise BackupError("nasdaq_request_scope_invalid")
        query = urlencode(dict(assetclass=asset_class, fromdate=str(start), todate=str(end), limit=5000))
        url = f"https://api.nasdaq.com/api/quote/{quote(ticker, safe='.-')}/historical?{query}"
        if self.last is not None:
            self.sleep(max(0, 1.0 - (self.clock() - self.last)))
        self.last = self.clock()
        observed = now_et().isoformat()
        try:
            if self.get:
                raw = self.get(url)
            else:
                req = Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (compatible; personal equity research)"})
                with build_opener(_NoRedirectHandler()).open(req, timeout=8) as response:
                    if response.status != 200:
                        raise BackupError("nasdaq_http_failed")
                    raw = response.read(2_000_001)
            if not isinstance(raw, bytes) or len(raw) > 2_000_000:
                raise BackupError("nasdaq_response_size_invalid")
            payload = json.loads(raw)
        except BackupError:
            raise
        except Exception:
            raise BackupError("nasdaq_request_failed") from None
        # Retain original public response bytes even when normalized admission
        # fails. No authorization header or credential enters this provider.
        digest = hashlib.sha256(raw).hexdigest()
        target = self.root / REL / "responses" / (digest + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != raw:
            raise BackupError("nasdaq_retained_response_conflict")
        if not target.exists():
            target.write_bytes(raw)
        self.receipts.append({"ticker": ticker, "source_url": url, "observed_at": observed,
            "path": str(target.relative_to(self.root)), "sha256": digest, "price_field": "Close/Last"})
        return normalize(payload, ticker, start, end), url


def recover(root: Path, tickers: list[str], asset_classes: dict[str, str], end: date, *, client=None,
            primary_client=None, held_only_tickers: list[str] | tuple[str, ...] = ()) -> dict:
    base = _load_retained_baseline(root)
    baseline_end = date.fromisoformat(base["market_session"])
    if baseline_end >= end:
        raise BackupError("backup_requires_a_new_session")
    base, primary_receipts = _seed_held_primary_history(root, base, tickers, held_only_tickers, primary_client)
    client = client or NasdaqHistoricalClient(root)
    result = copy.deepcopy(base)
    result.update(data_source=SOURCE, market_session=str(end), generated_at=now_et().isoformat(),
                  kind="retained_unadjusted_history_with_observed_nasdaq_new_sessions", parent_history_sha256=None)
    pointer = json.loads((root / CURRENT).read_text())
    result["parent_history_sha256"] = pointer["history_sha256"]
    start = date.fromisoformat(next(iter(base["tickers"].values()))["bars"][-2]["session_date"])
    for ticker in tickers:
        extension, url = client.fetch(ticker, asset_classes[ticker], start, end)
        prior = {b["session_date"]: b for b in base["tickers"][ticker]["bars"]}
        overlap = [b for b in extension if b["session_date"] <= str(baseline_end)]
        if len(overlap) != 2 or any(b["session_date"] not in prior or
                abs(Decimal(str(b["close"])) - Decimal(str(prior[b["session_date"]]["close"]))) > Decimal("0.005") for b in overlap):
            raise BackupError("backup_overlap_price_basis_conflict")
        # Never replace prior historical OHLCV with potentially adjusted data.
        bars = [*base["tickers"][ticker]["bars"], *[b for b in extension if b["session_date"] > str(baseline_end)]]
        bars = [b for b in bars if date.fromisoformat(b["session_date"]) >= end - timedelta(weeks=52)]
        checked_bars(bars, end)
        result["tickers"][ticker] = {"source_url": url, "bars": bars}
    result["observations"] = [*primary_receipts, *client.receipts]
    result.pop("held_only_primary_scope_additions", None)
    if primary_receipts:
        result["held_only_primary_scope_additions"] = sorted(row["ticker"] for row in primary_receipts)
    result["generated_at"] = now_et().isoformat()
    return checked_bundle(result, tickers)


def pointer_for(root: Path, bundle: dict, snapshot_hash: str) -> dict:
    bundle = {**bundle, "snapshot_sha256": snapshot_hash}
    raw = (json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = root / REL / "history" / (digest + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise BackupError("backup_history_archive_conflict")
    if not path.exists():
        path.write_bytes(raw)
    return {"schema_version": "equity_market_history_pointer_v1", "history_path": "history/" + digest + ".json",
        "history_sha256": digest, "snapshot_sha256": snapshot_hash,
        "market_session": bundle["market_session"], "data_source": bundle["data_source"]}


def verify_binding(root: Path, tickers: list[str], rows: list[dict], snapshot_hash: str) -> bool:
    try:
        bundle = load_baseline(root, tickers)
        if bundle.get("snapshot_sha256") != snapshot_hash:
            return False
        for row in rows:
            bars = bundle["tickers"][row["ticker"]]["bars"]
            if (row["market_session_date"] != bundle["market_session"]
                    or abs(float(row["last_price"]) - bars[-1]["close"]) > 0.000051):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def publish(root: Path, files: dict[Path, bytes], bundle: dict, snapshot: Path) -> None:
    """Retain prior bytes, then publish under the caller's pipeline lock.

    Interrupted publication is detected by existing coherence/hash guards. A
    caught error restores only files this batch changed; the prepared receipt
    and original bytes survive a crash for bounded operator recovery.
    """
    snapshot_hash = hashlib.sha256(files[snapshot]).hexdigest()
    pointer = pointer_for(root, bundle, snapshot_hash)
    pointer_path = root / CURRENT
    files = {**files, pointer_path: (json.dumps(pointer, indent=2, sort_keys=True) + "\n").encode()}
    before = {p: p.read_bytes() if p.exists() else None for p in files}
    run = root / REL / "publications" / (now_et().strftime("%Y%m%dT%H%M%S%f"))
    run.mkdir(parents=True)
    for i, (p, raw) in enumerate(before.items()):
        if raw is not None:
            (run / f"before-{i}.bin").write_bytes(raw)
    receipt = {"status": "prepared", "prepared_at": now_et().isoformat(),
        "files": [{"path": str(p.relative_to(root)), "before_sha256": hashlib.sha256(before[p]).hexdigest() if before[p] is not None else None,
                   "after_sha256": hashlib.sha256(raw).hexdigest(), "backup": f"before-{i}.bin" if before[p] is not None else None}
                  for i, (p, raw) in enumerate(files.items())]}
    atomic_write_json(run / "receipt.json", receipt)
    written = []
    try:
        for path, raw in files.items():
            atomic_write_text(path, raw.decode("utf-8"))
            written.append(path)
        if any(p.read_bytes() != raw for p, raw in files.items()):
            raise BackupError("market_publication_readback_failed")
        receipt.update(status="published", completed_at=now_et().isoformat())
        atomic_write_json(run / "receipt.json", receipt)
    except Exception:
        for p in reversed(written):
            if p.read_bytes() != files[p]:
                raise BackupError("market_publication_recovery_conflict") from None
            if before[p] is None:
                p.unlink()
            else:
                atomic_write_text(p, before[p].decode("utf-8"))
        receipt.update(status="rolled_back", completed_at=now_et().isoformat())
        atomic_write_json(run / "receipt.json", receipt)
        raise


def recover_interrupted_publications(root: Path) -> None:
    """Restore only recognised pre/post bytes from a prepared transaction."""
    allowed = {"03_source_data/equity_research/" + name for name in
               ("market_data_snapshot.csv", "market_data_quality_report.csv", "candidates_with_market_data.csv", "tactical_price_history.local.json")}
    allowed.add(CURRENT)
    for path in sorted((root / REL / "publications").glob("*/receipt.json")):
        receipt = json.loads(path.read_text())
        if receipt.get("status") != "prepared":
            continue
        rows = receipt.get("files", [])
        if not rows or len(rows) > len(allowed) or len({r.get("path") for r in rows}) != len(rows):
            raise BackupError("market_recovery_receipt_invalid")
        originals = {}
        for row in rows:
            if row.get("path") not in allowed:
                raise BackupError("market_recovery_scope_invalid")
            target = root / row["path"]
            actual = sha256_file(target) if target.exists() else None
            if actual not in {row["before_sha256"], row["after_sha256"]}:
                raise BackupError("market_recovery_input_changed")
            backup = row.get("backup")
            if backup is None:
                originals[target] = None
            else:
                if re.fullmatch(r"before-\d+\.bin", backup) is None:
                    raise BackupError("market_recovery_backup_invalid")
                raw = (path.parent / backup).read_bytes()
                if hashlib.sha256(raw).hexdigest() != row["before_sha256"]:
                    raise BackupError("market_recovery_backup_invalid")
                originals[target] = raw
        for target, raw in originals.items():
            if raw is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write_text(target, raw.decode("utf-8"))
        receipt.update(status="recovered_after_interruption", completed_at=now_et().isoformat())
        atomic_write_json(path, receipt)
