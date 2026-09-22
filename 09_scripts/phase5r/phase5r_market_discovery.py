#!/usr/bin/env python3
"""Independent US-listed common-stock/ETF discovery; no execution or eligibility.

Network requires --refresh and uses only official Massive grouped/reference
endpoints. The caller serializes this job with the existing runtime lock.
Successful provider batches are cached; incomplete refreshes never expose an
old shortlist as current. All names need separate due diligence and risk checks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from phase5r_daily_common import (ET, ROOT, atomic_write_json,
    is_us_market_session_date, latest_published_market_session, now_et)

SCHEMA = "phase5r_market_discovery_v1"
BASE = "https://api.massive.com"
CACHE_RELATIVE = Path("03_source_data/phase5r/market_discovery.local")
MAX_BYTES = 16 * 1024 * 1024
MAX_CALLS = 50
MAX_PAGES = 25
MAX_ROWS = 40000
# Conservative integrity checks, not official exchange population counts.
MIN_COMMON_STOCKS = 2000
MIN_ETFS = 1000
MIN_GROUPED_ROWS = 5000
PACE_SECONDS = 13.0
TIMEOUT_SECONDS = 15.0
EXCHANGES = {"XNAS", "XNYS", "ARCX", "BATS", "XASE"}
TICKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-^/]{0,24}")
EXCLUDED_ETF = re.compile(
    r"\b(leveraged|leverage|inverse|short|ultra|ultrapro|ultrashort|options?|"
    r"covered.call|buy.?write|buffer|defined.outcome|daily|single.stock|"
    r"yieldmax|defiance|graniteshares|direxion|proshares|t.rex|tradr|"
    r"accelerated|bear|bull)\b|\b[2-9]x\b", re.I)
FAILURES = {"authentication_missing", "authentication_failed", "rate_limited",
    "request_failed", "response_oversize", "invalid_response", "invalid_pagination",
    "request_budget_exceeded", "metadata_incomplete", "bars_incomplete",
    "cache_invalid", "benchmark_missing", "local_unavailable", "local_stale",
    "unexpected_failure", "rate_state_invalid", "coverage_incomplete"}
PRICE_BASIS = "Massive Stocks Basic published EOD grouped OHLCV; adjusted=true (split-adjusted), include_otc=false; separate from unadjusted canonical order-price data"


class DiscoveryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in FAILURES else "unexpected_failure"
        super().__init__(self.code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_get(path: str, headers: dict[str, str], timeout: float) -> Any:
    try:
        with build_opener(NoRedirect()).open(
            Request(BASE + path, headers=headers), timeout=timeout
        ) as response:
            if response.status != 200:
                raise DiscoveryError("request_failed")
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        code = "authentication_failed" if error.code in {401, 403} else "rate_limited" if error.code == 429 else "request_failed"
        raise DiscoveryError(code) from None
    except (OSError, URLError):
        raise DiscoveryError("request_failed") from None
    if len(raw) > MAX_BYTES:
        raise DiscoveryError("response_oversize")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise DiscoveryError("invalid_response") from None


def _number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DiscoveryError("invalid_response")
    if value < 0 or (positive and value == 0):
        raise DiscoveryError("invalid_response")
    return float(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _read(path: Path) -> Any:
    if path.stat().st_size > MAX_BYTES:
        raise DiscoveryError("cache_invalid")
    return json.loads(path.read_text(encoding="utf-8"))


def _cache_write(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, {"payload": payload, "sha256": _digest(payload)})


def _cache_read(path: Path) -> dict[str, Any]:
    try:
        wrapper = _read(path)
        value = wrapper["payload"]
        if not isinstance(value, dict) or wrapper["sha256"] != _digest(value):
            raise DiscoveryError("cache_invalid")
        return value
    except (OSError, ValueError, TypeError, KeyError):
        raise DiscoveryError("cache_invalid") from None


def published_sessions(current: datetime | None = None, count: int = 21) -> list[date]:
    candidate = latest_published_market_session(current or now_et())
    sessions = []
    while len(sessions) < count:
        if is_us_market_session_date(candidate):
            sessions.append(candidate)
        candidate -= timedelta(days=1)
    return list(reversed(sessions))


def validated_next_path(url: Any) -> str:
    if not isinstance(url, str) or len(url) > 4096:
        raise DiscoveryError("invalid_pagination")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "api.massive.com"
            or parsed.path != "/v3/reference/tickers" or parsed.fragment
            or parsed.username or parsed.password):
        raise DiscoveryError("invalid_pagination")
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise DiscoveryError("invalid_pagination") from None
    # Provider cursors encode the original filters. Never forward an apiKey,
    # additional filter, alternate endpoint or user-selected URL.
    if set(query) != {"cursor"} or len(query["cursor"]) != 1 or not re.fullmatch(r"[A-Za-z0-9_\-=+/]{1,3500}", query["cursor"][0]):
        raise DiscoveryError("invalid_pagination")
    return parsed.path + "?" + urlencode({"cursor": query["cursor"][0]})


class DiscoveryClient:
    """One shared request budget and persistent pacing for both endpoint types."""
    def __init__(self, api_key: str, *, state_path: Path, http_get: Callable = _http_get,
                 clock: Callable = time.time, sleep: Callable = time.sleep):
        if not isinstance(api_key, str) or not api_key or any(c.isspace() or ord(c) < 33 for c in api_key):
            raise DiscoveryError("authentication_missing")
        self._key, self._http_get = api_key, http_get
        self._clock, self._sleep, self._state_path = clock, sleep, state_path
        self.calls = 0
        # A different existing provider client may just have finished. Always
        # wait a full interval on process start as well as preserving our state.
        self._last = clock()
        if state_path.exists():
            try:
                last = _number(_read(state_path)["last_request_started"])
                if last > clock() + PACE_SECONDS:
                    raise DiscoveryError("rate_state_invalid")
                self._last = max(last, self._last)
            except (OSError, ValueError, KeyError, TypeError, DiscoveryError):
                raise DiscoveryError("rate_state_invalid") from None

    @classmethod
    def from_environment(cls, *, state_path: Path, **kwargs):
        return cls(os.environ.get("MASSIVE_API_KEY", ""), state_path=state_path, **kwargs)

    def request(self, path: str) -> dict[str, Any]:
        if self.calls >= MAX_CALLS:
            raise DiscoveryError("request_budget_exceeded")
        if not path.startswith(("/v3/reference/tickers?", "/v2/aggs/grouped/locale/us/market/stocks/")):
            raise DiscoveryError("request_failed")
        delay = PACE_SECONDS - (self._clock() - self._last)
        if delay > 0:
            self._sleep(delay)
        self._last = self._clock()
        atomic_write_json(self._state_path, {"last_request_started": self._last})
        self.calls += 1
        try:
            payload = self._http_get(path, {"Accept": "application/json", "Authorization": "Bearer " + self._key,
                "User-Agent": "Equity-Market-Discovery/1.0"}, TIMEOUT_SECONDS)
        except DiscoveryError:
            raise
        except Exception:
            raise DiscoveryError("request_failed") from None
        if not isinstance(payload, dict) or payload.get("status") != "OK":
            raise DiscoveryError("invalid_response")
        return payload

    def fetch_metadata(self, session: date) -> dict[str, Any]:
        rows: dict[str, dict[str, Any]] = {}
        pages = 0
        for kind in ("CS", "ETF"):
            path = "/v3/reference/tickers?" + urlencode({"market": "stocks", "locale": "us", "active": "true",
                "type": kind, "date": session.isoformat(), "limit": 1000, "sort": "ticker", "order": "asc"})
            seen_paths = set()
            while path:
                if path in seen_paths or pages >= MAX_PAGES:
                    raise DiscoveryError("metadata_incomplete")
                seen_paths.add(path)
                payload = self.request(path)
                page = payload.get("results")
                if (not isinstance(page, list) or len(page) > 1000 or not page
                        or payload.get("count", len(page)) != len(page)):
                    raise DiscoveryError("metadata_incomplete")
                for raw in page:
                    if not isinstance(raw, dict):
                        raise DiscoveryError("invalid_response")
                    ticker = raw.get("ticker")
                    if (not isinstance(ticker, str) or not TICKER.fullmatch(ticker)
                            or ticker in rows or raw.get("active") is not True
                            or raw.get("type") != kind or raw.get("market") != "stocks"
                            or raw.get("locale") != "us" or not isinstance(raw.get("name"), str)
                            or not 0 < len(raw["name"]) <= 500):
                        raise DiscoveryError("invalid_response")
                    rows[ticker] = {k: raw.get(k, "") for k in ("ticker", "name", "type", "primary_exchange", "currency_name")}
                pages += 1
                next_url = payload.get("next_url")
                path = validated_next_path(next_url) if next_url else ""
        metadata = {"session": session.isoformat(), "complete": True, "pages": pages, "rows": rows}
        validate_metadata(metadata, session)
        return metadata

    def fetch_grouped(self, session: date) -> dict[str, Any]:
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{session.isoformat()}?adjusted=true&include_otc=false"
        payload = self.request(path)
        return normalize_grouped(payload, session)


def normalize_grouped(payload: dict[str, Any], session: date) -> dict[str, Any]:
    raw_rows = payload.get("results")
    if (payload.get("status") != "OK" or payload.get("adjusted") is not True or payload.get("next_url")
            or not isinstance(raw_rows, list) or not 0 < len(raw_rows) <= MAX_ROWS
            or payload.get("resultsCount") != len(raw_rows)):
        raise DiscoveryError("bars_incomplete")
    if len(raw_rows) < MIN_GROUPED_ROWS:
        raise DiscoveryError("coverage_incomplete")
    rows = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise DiscoveryError("invalid_response")
        ticker = raw.get("T")
        if not isinstance(ticker, str) or not TICKER.fullmatch(ticker) or ticker in rows or raw.get("otc", False) is not False:
            raise DiscoveryError("invalid_response")
        try:
            stamp = _number(raw.get("t"), positive=True)
            actual = datetime.fromtimestamp(stamp / 1000, timezone.utc).astimezone(ET).date()
        except (OverflowError, OSError, ValueError):
            raise DiscoveryError("invalid_response") from None
        if actual != session:
            raise DiscoveryError("bars_incomplete")
        values = {key: _number(raw.get(key), positive=key != "v") for key in ("o", "h", "l", "c", "v")}
        if not values["l"] <= min(values["o"], values["c"]) <= max(values["o"], values["c"]) <= values["h"]:
            raise DiscoveryError("invalid_response")
        rows[ticker] = values
    return {"session": session.isoformat(), "complete": True, "adjusted": True, "rows": rows}


def validate_metadata(metadata: dict[str, Any], session: date,
                      previous: dict[str, Any] | None = None) -> None:
    rows = metadata.get("rows")
    if (metadata.get("session") != str(session) or metadata.get("complete") is not True
            or not isinstance(rows, dict) or not rows):
        raise DiscoveryError("metadata_incomplete")
    counts = Counter(row.get("type") for row in rows.values())
    if counts["CS"] < MIN_COMMON_STOCKS or counts["ETF"] < MIN_ETFS:
        raise DiscoveryError("coverage_incomplete")
    if previous:
        prior = Counter(row.get("type") for row in previous.get("rows", {}).values())
        if any(counts[kind] < .8 * prior[kind] for kind in ("CS", "ETF")) or len(rows) < .8 * len(previous.get("rows", {})):
            raise DiscoveryError("coverage_incomplete")


def _previous_metadata(directory: Path, session: date) -> dict[str, Any] | None:
    for path in sorted(directory.glob("metadata-*.local.json"), reverse=True):
        day = path.name[len("metadata-"):-len(".local.json")]
        if day < str(session):
            result = _cache_read(path)
            validate_metadata(result, date.fromisoformat(day))
            return result
    return None


def _empty(session: date, status: str, code: str, as_of: str = "") -> dict[str, Any]:
    return {"schema_version": SCHEMA, "status": status, "complete": False, "as_of_session": as_of,
        "expected_session": session.isoformat(), "failure_code": code, "price_basis": PRICE_BASIS,
        "fetched_at": "", "coverage": {}, "top_stocks": [], "top_etfs": [], "all_stocks": [], "all_etfs": [],
        "methodology": "Independent market discovery; no portfolio or watchlist input to ranking.",
        "limitations": ["Discovery unavailable or stale; no current market-wide shortlist is asserted."]}


def build_report(metadata: dict[str, Any], bars_by_session: dict[str, dict[str, Any]],
                 session: date, legacy_tickers: set[str] | None = None) -> dict[str, Any]:
    sessions = []
    cursor = session
    while len(sessions) < 21:
        if is_us_market_session_date(cursor):
            sessions.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    sessions.reverse()
    validate_metadata(metadata, session)
    if set(bars_by_session) != set(sessions):
        raise DiscoveryError("bars_incomplete")
    for day in sessions:
        data = bars_by_session[day]
        if data.get("session") != day or data.get("complete") is not True or data.get("adjusted") is not True or not isinstance(data.get("rows"), dict):
            raise DiscoveryError("bars_incomplete")
        if len(data["rows"]) < MIN_GROUPED_ROWS:
            raise DiscoveryError("coverage_incomplete")
    try:
        benchmark = [bars_by_session[day]["rows"]["SPY"]["c"] for day in sessions]
        spy5, spy20 = (benchmark[-1] / benchmark[-6] - 1) * 100, (benchmark[-1] / benchmark[0] - 1) * 100
    except (KeyError, ZeroDivisionError, TypeError):
        raise DiscoveryError("benchmark_missing") from None
    exclusions: Counter = Counter()
    ranked = {"CS": [], "ETF": []}
    with_history = 0
    for ticker, meta in metadata["rows"].items():
        kind = meta.get("type")
        reason = ""
        if kind not in ranked:
            reason = "unsupported_type"
        elif meta.get("primary_exchange") not in EXCHANGES or meta.get("currency_name", "").lower() != "usd":
            reason = "exchange_or_currency"
        elif kind == "ETF" and EXCLUDED_ETF.search(meta.get("name", "")):
            reason = "complex_etf_name_screen"
        if reason:
            exclusions[reason] += 1
            continue
        try:
            bars = [bars_by_session[day]["rows"][ticker] for day in sessions]
        except KeyError:
            exclusions["missing_21_session_history"] += 1
            continue
        with_history += 1
        close = bars[-1]["c"]
        average_dollar = sum(b["c"] * b["v"] for b in bars[-20:]) / 20
        average_volume = sum(b["v"] for b in bars[:-1]) / 20
        if close < 5:
            exclusions["price_below_5"] += 1
            continue
        if average_dollar < 20_000_000 or average_volume <= 0:
            exclusions["liquidity_below_20m"] += 1
            continue
        # Cached adjusted observations may straddle a subsequently announced
        # split. Large discontinuities receive research review, not a top rank.
        if any(abs(bars[i]["c"] / bars[i-1]["c"] - 1) > .25 for i in range(1, 21)):
            exclusions["large_discontinuity_review"] += 1
            continue
        ret5 = (close / bars[-6]["c"] - 1) * 100
        ret20 = (close / bars[0]["c"] - 1) * 100
        relative_volume = bars[-1]["v"] / average_volume
        rs5, rs20 = ret5 - spy5, ret20 - spy20
        # A disclosed prioritization heuristic. Capping volume's contribution
        # prevents one unusual print from dominating; no theme/holding inputs.
        score = .35 * rs5 + .50 * rs20 + 1.5 * (min(relative_volume, 3) - 1)
        ranked[kind].append({"ticker": ticker, "name": meta["name"], "close": round(close, 4),
            "return_5d_pct": round(ret5, 4), "return_20d_pct": round(ret20, 4),
            "relative_strength_5d_pct": round(rs5, 4), "relative_strength_20d_pct": round(rs20, 4),
            "relative_volume": round(relative_volume, 4), "average_dollar_volume_20d": round(average_dollar, 2),
            "score": round(score, 6), "classification": "watchlist", "research_status": "unresearched_discovery",
            "etf_structure_verified": False})
    # Seed membership enters only after independent ranking. It cannot affect
    # eligibility, order, prices, components, or score.
    legacy = legacy_tickers or set()
    all_ranked = []
    for kind in ranked:
        ranked[kind].sort(key=lambda row: (-row["score"], row["ticker"]))
        for rank, row in enumerate(ranked[kind], 1):
            row["rank"] = rank
            row["in_legacy_universe"] = row["ticker"] in legacy
        all_ranked.extend(ranked[kind])
    coverage = {"metadata_count": len(metadata["rows"]),
        "common_stock_count": sum(r.get("type") == "CS" for r in metadata["rows"].values()),
        "etf_count": sum(r.get("type") == "ETF" for r in metadata["rows"].values()),
        "latest_grouped_count": len(bars_by_session[sessions[-1]]["rows"]),
        "with_21_bars_count": with_history, "screen_eligible_count": len(all_ranked),
        "stock_screen_eligible_count": len(ranked["CS"]), "etf_screen_eligible_count": len(ranked["ETF"]),
        "excluded_counts": dict(sorted(exclusions.items())), "legacy_count": len(legacy),
        "screen_eligible_outside_legacy_count": sum(not r["in_legacy_universe"] for r in all_ranked)}
    return {"schema_version": SCHEMA, "status": "complete", "complete": True,
        "as_of_session": session.isoformat(), "expected_session": session.isoformat(), "failure_code": "",
        "fetched_at": "", "price_basis": PRICE_BASIS, "coverage": coverage,
        "top_stocks": ranked["CS"][:10], "top_etfs": ranked["ETF"][:10],
        "all_stocks": ranked["CS"], "all_etfs": ranked["ETF"],
        "methodology": "Stock/ETF ranks separate. Score = 0.35*5-session excess return vs SPY + 0.50*20-session excess return vs SPY + 1.5*(min(relative volume,3)-1). Relative volume uses prior 20 sessions. No watchlist, theme or holding bonus.",
        "limitations": ["Broad screening is not comprehensive fundamental or catalyst research; no order is cleared.",
            "Common stocks and ETFs only; ADRs, OTC and other security types are outside this defined scope.",
            "Complete means all reference pages and 21 grouped sessions received, not that every instrument traded every session.",
            "All ETFs require prospectus/structure verification; name screening cannot prove absence of leverage, options or inverse exposure.",
            "Historical adjusted bars are cached; discontinuities over 25% are excluded for corporate-action review; subtler actions can remain.",
            "Heuristic momentum ranking is not a backtested strategy, expected return or ranking of fundamental growth quality; fresh quotes and separate portfolio checks are required.",
            "Completeness sanity floors: at least 2,000 common stocks, 1,000 ETFs and 5,000 grouped rows per session; a reference-population decline over 20% requires investigation."]}


def refresh_discovery(root: Path = ROOT, current: datetime | None = None, *, client: DiscoveryClient | None = None) -> dict[str, Any]:
    current = current or now_et()
    sessions = published_sessions(current)
    session = sessions[-1]
    directory = root / CACHE_RELATIVE
    directory.mkdir(parents=True, exist_ok=True)
    try:
        metadata_path = directory / f"metadata-{session}.local.json"
        if metadata_path.exists():
            metadata = _cache_read(metadata_path)
        else:
            client = client or DiscoveryClient.from_environment(state_path=directory / "request-pacing.local.json")
            metadata = client.fetch_metadata(session)
            validate_metadata(metadata, session, _previous_metadata(directory, session))
            _cache_write(metadata_path, metadata)
        validate_metadata(metadata, session, _previous_metadata(directory, session))
        history = {}
        for day in sessions:
            path = directory / f"grouped-{day}.local.json"
            if path.exists():
                history[day.isoformat()] = _cache_read(path)
            else:
                client = client or DiscoveryClient.from_environment(state_path=directory / "request-pacing.local.json")
                history[day.isoformat()] = client.fetch_grouped(day)
                _cache_write(path, history[day.isoformat()])
        legacy = set()
        seed = root / "03_source_data/phase5r/phase5r_universe_seed.csv"
        if seed.exists():
            with seed.open(newline="", encoding="utf-8") as handle:
                legacy = {row["ticker"] for row in csv.DictReader(handle)}
        report = build_report(metadata, history, session, legacy)
        report["fetched_at"] = current.isoformat(timespec="seconds")
        report["provider_requests_this_run"] = client.calls if client else 0
        _cache_write(directory / "latest.local.json", report)
        return report
    except Exception as error:
        code = error.code if isinstance(error, DiscoveryError) else "unexpected_failure"
        report = _empty(session, "unavailable", code)
        report["fetched_at"] = current.isoformat(timespec="seconds")
        _cache_write(directory / "latest.local.json", report)
        return report


def load_discovery(root: Path = ROOT, current: datetime | None = None) -> dict[str, Any]:
    expected = latest_published_market_session(current or now_et())
    try:
        report = _cache_read(root / CACHE_RELATIVE / "latest.local.json")
        if report.get("schema_version") != SCHEMA:
            raise DiscoveryError("cache_invalid")
        if report.get("status") != "complete" or report.get("complete") is not True:
            return _empty(expected, "unavailable", str(report.get("failure_code", "local_unavailable")))
        if report.get("as_of_session") != expected.isoformat():
            return _empty(expected, "stale", "local_stale", str(report.get("as_of_session", "")))
        if not isinstance(report.get("coverage"), dict) or not isinstance(report.get("top_stocks"), list) or not isinstance(report.get("top_etfs"), list):
            raise DiscoveryError("cache_invalid")
        coverage = report["coverage"]
        for field in ("metadata_count", "common_stock_count", "etf_count", "latest_grouped_count",
                      "screen_eligible_count", "stock_screen_eligible_count", "etf_screen_eligible_count"):
            if type(coverage.get(field)) is not int or coverage[field] < 0:
                raise DiscoveryError("cache_invalid")
        if (coverage["common_stock_count"] < MIN_COMMON_STOCKS or coverage["etf_count"] < MIN_ETFS
                or coverage["latest_grouped_count"] < MIN_GROUPED_ROWS
                or coverage["common_stock_count"] + coverage["etf_count"] != coverage["metadata_count"]
                or coverage["stock_screen_eligible_count"] + coverage["etf_screen_eligible_count"] != coverage["screen_eligible_count"]
                or report.get("expected_session") != expected.isoformat()):
            raise DiscoveryError("coverage_incomplete")
        return report
    except Exception:
        return _empty(expected, "unavailable", "local_unavailable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Explicit official public-data refresh; caller holds runtime lock")
    args = parser.parse_args()
    report = refresh_discovery() if args.refresh else load_discovery()
    print(json.dumps({key: report[key] for key in ("status", "as_of_session", "expected_session", "failure_code", "coverage")}, sort_keys=True))
    # Unavailable discovery is a disclosed research limitation, not permission
    # to block the independent canonical holdings/risk report.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
