from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import _support
import market_discovery as md

NOW = datetime(2026, 9, 22, 14, tzinfo=md.ET)
DAYS = md.published_sessions(NOW)
SESSION = DAYS[-1]


def raw_meta(ticker, kind="CS"):
    return {"ticker": ticker, "name": ticker + " Company", "active": True,
        "type": kind, "market": "stocks", "locale": "us", "currency_name": "usd", "primary_exchange": "XNYS"}


def fixtures():
    meta = {"session": str(SESSION), "complete": True, "rows": {}}
    for ticker, kind in (("AAA", "CS"), ("BBB", "CS"), ("SPY", "ETF"), ("QQQ", "ETF")):
        row = raw_meta(ticker, kind)
        meta["rows"][ticker] = {k: row[k] for k in ("ticker", "name", "type", "currency_name", "primary_exchange")}
    days = {}
    for i, day in enumerate(DAYS):
        rows = {}
        for ticker, change in (("AAA", 1.0), ("BBB", .4), ("SPY", .1), ("QQQ", .3)):
            close = 100 + i * change
            rows[ticker] = {"o": close, "c": close, "l": close-1, "h": close+1, "v": 1_000_000}
        days[str(day)] = {"session": str(day), "complete": True, "adjusted": True, "rows": rows}
    return meta, days


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        # Tiny fixture universes are deliberate; production floors remain strict.
        for name in ("MIN_COMMON_STOCKS", "MIN_ETFS", "MIN_GROUPED_ROWS"):
            patcher = patch.object(md, name, 1)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_production_breadth_and_reference_collapse_guards(self):
        meta, days = fixtures()
        with patch.object(md, "MIN_COMMON_STOCKS", 2000), patch.object(md, "MIN_ETFS", 1000):
            with self.assertRaises(md.DiscoveryError) as ctx: md.build_report(meta, days, SESSION)
            self.assertEqual(str(ctx.exception), "coverage_incomplete")
        prior = deepcopy(meta)
        for i in range(8):
            prior["rows"]["C"+str(i)] = deepcopy(prior["rows"]["AAA"])
        with self.assertRaises(md.DiscoveryError) as ctx: md.validate_metadata(meta, SESSION, prior)
        self.assertEqual(str(ctx.exception), "coverage_incomplete")
        with patch.object(md, "MIN_GROUPED_ROWS", 5000):
            with self.assertRaises(md.DiscoveryError) as ctx: md.build_report(meta, days, SESSION)
            self.assertEqual(str(ctx.exception), "coverage_incomplete")

    def test_published_not_same_day_and_weekend_calendar(self):
        self.assertEqual(SESSION.isoformat(), "2026-09-21")
        self.assertEqual(len(DAYS), 21)
        self.assertNotIn("2026-09-07", [str(d) for d in DAYS])
        self.assertEqual(md.published_sessions(datetime(2026, 9, 22, 9, tzinfo=md.ET))[-1].isoformat(), "2026-09-18")

    def test_reference_cursor_only_same_origin(self):
        good = "https://api.massive.com/v3/reference/tickers?cursor=abcDEF123_-"
        self.assertTrue(md.validated_next_path(good).endswith("cursor=abcDEF123_-"))
        for bad in (good.replace("https", "http"), good.replace("api.massive.com", "evil.example"),
                    good + "&apiKey=secret", good + "&limit=1000", good + "#x",
                    good.replace("/v3/reference/tickers", "/v2/other"),
                    good.replace("api.massive.com", "user@api.massive.com"),
                    good.replace("api.massive.com", "api.massive.com:443")):
            with self.subTest(bad=bad), self.assertRaises(md.DiscoveryError):
                md.validated_next_path(bad)

    def test_reference_pagination_complete_and_shared_pacing(self):
        responses = [
            {"status": "OK", "results": [raw_meta("AAA")], "count": 1,
                "next_url": "https://api.massive.com/v3/reference/tickers?cursor=page2"},
            {"status": "OK", "results": [raw_meta("BBB")], "count": 1},
            {"status": "OK", "results": [raw_meta("SPY", "ETF")], "count": 1}]
        clock = [100.0]
        calls = []
        def request(path, headers, timeout):
            calls.append((path, dict(headers), timeout, clock[0]))
            return responses.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            client = md.DiscoveryClient("test-token", state_path=Path(tmp)/"pace.json", http_get=request,
                clock=lambda: clock[0], sleep=lambda n: clock.__setitem__(0, clock[0]+n))
            result = client.fetch_metadata(SESSION)
            self.assertEqual(len(result["rows"]), 3)
            self.assertEqual(client.calls, 3)
            self.assertEqual([r[3] for r in calls], [113, 126, 139])
            self.assertTrue(all("test-token" not in r[0] and r[1]["Authorization"] == "Bearer test-token" for r in calls))
            self.assertNotIn("test-token", (Path(tmp)/"pace.json").read_text())
            self.assertEqual(client._state_path.name, "pace.json")

    def test_repeated_cursor_and_truncated_page_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for response in (
                {"status": "OK", "results": [raw_meta("AAA")], "count": 2},
                {"status": "OK", "results": [], "count": 0},
                {"status": "OK", "results": [raw_meta("AAA")], "count": 1,
                    "next_url": "https://evil.example/v3/reference/tickers?cursor=x"}):
                client = md.DiscoveryClient("test", state_path=Path(tmp)/"pace.json", http_get=lambda *a: response,
                    clock=lambda: 1000, sleep=lambda n: None)
                with self.assertRaises(md.DiscoveryError):
                    client.fetch_metadata(SESSION)

    def test_grouped_rejects_date_duplicate_partial_invalid_ohlc_and_basis(self):
        stamp = int(datetime.combine(SESSION, datetime.min.time(), tzinfo=md.ET).timestamp()*1000)
        raw = {"T": "SPY", "o": 100, "h": 101, "l": 99, "c": 100, "v": 1000, "t": stamp}
        good = {"status": "OK", "adjusted": True, "resultsCount": 1, "results": [raw]}
        self.assertEqual(md.normalize_grouped(good, SESSION)["rows"]["SPY"]["c"], 100)
        variants = []
        for key, value in (("adjusted", False), ("resultsCount", 2), ("next_url", "https://api.massive.com/x")):
            v = deepcopy(good); v[key] = value; variants.append(v)
        for key, value in (("t", stamp-86400000), ("c", 200), ("v", float("nan")), ("otc", True)):
            v = deepcopy(good); v["results"][0][key] = value; variants.append(v)
        duplicate = deepcopy(good); duplicate["results"] *= 2; duplicate["resultsCount"] = 2; variants.append(duplicate)
        for value in variants:
            with self.assertRaises(md.DiscoveryError): md.normalize_grouped(value, SESSION)

    def test_rank_invariant_to_watchlist_and_input_order(self):
        meta, days = fixtures()
        first = md.build_report(meta, days, SESSION, {"AAA"})
        meta["rows"] = dict(reversed(list(meta["rows"].items())))
        second = md.build_report(meta, days, SESSION, {"BBB", "QQQ"})
        for key in ("top_stocks", "top_etfs"):
            clean = lambda rows: [{k:v for k,v in row.items() if k != "in_legacy_universe"} for row in rows]
            self.assertEqual(clean(first[key]), clean(second[key]))
        self.assertEqual(first["top_stocks"][0]["ticker"], "AAA")
        self.assertEqual(first["coverage"]["screen_eligible_count"], 4)
        self.assertEqual(first["coverage"]["screen_eligible_outside_legacy_count"], 3)
        self.assertTrue(all(row["research_status"] == "unresearched_discovery" for row in first["all_stocks"]))
        self.assertNotIn("quantity", json.dumps(first))

    def test_filters_exclusions_no_fake_complete_history(self):
        meta, days = fixtures()
        meta["rows"]["QQQ"]["name"] = "Daily 2x Leveraged Fund"
        days[str(DAYS[0])]["rows"].pop("BBB")
        report = md.build_report(meta, days, SESSION)
        self.assertEqual(report["coverage"]["excluded_counts"]["complex_etf_name_screen"], 1)
        self.assertEqual(report["coverage"]["excluded_counts"]["missing_21_session_history"], 1)
        del days[str(DAYS[1])]
        with self.assertRaises(md.DiscoveryError): md.build_report(meta, days, SESSION)

    def test_missing_or_stale_benchmark_cannot_rank(self):
        meta, days = fixtures()
        days[str(DAYS[1])]["rows"].pop("SPY")
        with self.assertRaises(md.DiscoveryError): md.build_report(meta, days, SESSION)

    def test_cache_digest_and_local_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root/md.CACHE_RELATIVE/"latest.local.json"
            report = md.build_report(*fixtures(), SESSION)
            md._cache_write(path, report)
            self.assertEqual(md.load_discovery(root, NOW)["status"], "complete")
            with patch.object(md, "MIN_COMMON_STOCKS", 2000), patch.object(md, "MIN_ETFS", 1000):
                self.assertEqual(md.load_discovery(root, NOW)["status"], "unavailable")
            stale = md.load_discovery(root, NOW+timedelta(days=1))
            self.assertEqual(stale["status"], "stale"); self.assertEqual(stale["top_stocks"], [])
            wrapper = json.loads(path.read_text()); wrapper["payload"]["top_stocks"][0]["score"] = 999
            path.write_text(json.dumps(wrapper))
            self.assertEqual(md.load_discovery(root, NOW)["status"], "unavailable")

    def test_refresh_reuses_cache_and_failure_never_falls_back_to_old_shortlist(self):
        meta, days = fixtures()
        class Fake:
            calls = 0
            def fetch_metadata(self, day): self.calls += 1; return deepcopy(meta)
            def fetch_grouped(self, day): self.calls += 1; return deepcopy(days[str(day)])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); client = Fake()
            first = md.refresh_discovery(root, NOW, client=client)
            self.assertTrue(first["complete"]); self.assertEqual(client.calls, 22)
            second = md.refresh_discovery(root, NOW, client=client)
            self.assertTrue(second["complete"]); self.assertEqual(client.calls, 22)
            (root/md.CACHE_RELATIVE/f"grouped-{DAYS[0]}.local.json").write_text("bad")
            failed = md.refresh_discovery(root, NOW, client=client)
            self.assertFalse(failed["complete"]); self.assertEqual(failed["top_stocks"], [])
            self.assertEqual(md.load_discovery(root, NOW)["status"], "unavailable")

    def test_held_only_coverage_changes_comparison_but_never_independent_rank(self):
        meta, days = fixtures()
        class Fake:
            calls = 0
            def fetch_metadata(self, day): self.calls += 1; return deepcopy(meta)
            def fetch_grouped(self, day): self.calls += 1; return deepcopy(days[str(day)])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "03_source_data/equity_research/universe_seed.csv"
            seed.parent.mkdir(parents=True)
            seed.write_text("ticker,theme\nBBB,Irrelevant\n")
            baseline = md.refresh_discovery(root, NOW, client=Fake())
            positions = root / "05_risk_and_positions/current_positions.local.csv"
            positions.parent.mkdir(parents=True)
            positions.write_text("ticker,current_shares,current_value,cash\nAAA,INVALID_SHARES,INVALID_VALUE,INVALID_CASH\n")
            compared = md.refresh_discovery(root, NOW, client=Fake())
            self.assertTrue(baseline["complete"] and compared["complete"])
            strip_flags = lambda rows: [{k:v for k,v in row.items() if k != "in_legacy_universe"} for row in rows]
            self.assertEqual(strip_flags(baseline["all_stocks"]), strip_flags(compared["all_stocks"]))
            self.assertFalse(baseline["all_stocks"][0]["in_legacy_universe"])
            self.assertTrue(compared["all_stocks"][0]["in_legacy_universe"])
            self.assertEqual(compared["coverage"]["screen_eligible_outside_legacy_count"],
                             baseline["coverage"]["screen_eligible_outside_legacy_count"]-1)
            self.assertNotIn("INVALID_", json.dumps(compared))

    def test_network_exception_is_sanitized_and_budget_is_finite(self):
        def bad(*args): raise RuntimeError("SECRET_TOKEN https://bad.example")
        with tempfile.TemporaryDirectory() as tmp:
            client = md.DiscoveryClient("SECRET_TOKEN", state_path=Path(tmp)/"pace.json", http_get=bad, sleep=lambda n: None)
            with self.assertRaises(md.DiscoveryError) as ctx: client.request("/v3/reference/tickers?x=y")
            self.assertEqual(str(ctx.exception), "request_failed")
            self.assertNotIn("SECRET", str(ctx.exception))
            client.calls = md.MAX_CALLS
            with self.assertRaises(md.DiscoveryError) as ctx: client.request("/v3/reference/tickers?x=y")
            self.assertEqual(str(ctx.exception), "request_budget_exceeded")

    def test_oversize_http_and_redirect_are_rejected(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, size): return b"x" * size
        class Opener:
            def open(self, *a, **kw): return Response()
        with patch.object(md, "build_opener", return_value=Opener()), patch.object(md, "MAX_BYTES", 100):
            with self.assertRaises(md.DiscoveryError) as ctx: md._http_get("/v3/reference/tickers?x=y", {}, 1)
            self.assertEqual(str(ctx.exception), "response_oversize")
        self.assertIsNone(md.NoRedirect().redirect_request(None,None,302,"",{},"https://evil.example"))


if __name__ == "__main__": unittest.main()
