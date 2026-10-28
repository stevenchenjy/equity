"""Synthetic original-HTTP integration; no quote/admission validator is mocked.

All market prices, holdings and HTTP bodies below are explicitly synthetic test
fixtures in a temporary store. The injected transport never contacts a network.
The genuine canonical history, original-response, quote, engine and replay
validators are used end to end.
"""
from __future__ import annotations

import copy
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from _support import SCRIPT_DIR
import account_access
import intraday_prices as feed
import market_backup
import swing_candidate_quotes as quotes
import swing_research as legacy
import swing_research_v2 as engine


def stamp(value):
    return datetime.fromisoformat(value).astimezone(legacy.ET)


class SwingQuoteReplayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-swing-replay-")
        self.root = Path(self.temporary.name)
        self.first = stamp("2026-09-23T10:00:00-04:00")
        self.requests = []
        for relative in (legacy.POLICY, engine.POLICY):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((SCRIPT_DIR.parents[1] / relative).read_bytes())
        universe = self.root / legacy.UNIVERSE
        universe.parent.mkdir(parents=True, exist_ok=True)
        universe.write_text("ticker,company_name,sector,is_benchmark\nMSFT,Synthetic Microsoft,Technology,no\nSPY,Synthetic SPY,ETF,yes\n")
        holdings = self.root / legacy.HOLDINGS
        holdings.parent.mkdir(parents=True, exist_ok=True)
        holdings.write_text("ticker,shares_optional\nMSFT,1\nSPY,1\n")
        (holdings.parent / "current_account_state.local.json").write_text('{"cash_available":1000,"fixture":"synthetic"}')
        (holdings.parent / "current_open_orders.local.json").write_text('{"orders":[],"fixture":"synthetic"}')
        end = date(2026, 9, 22)
        self.msft = [{"session_date": str(day), "open": 500., "high": 501., "low": 498., "close": 500., "volume": 1000.}
                     for day in market_backup.sessions(end - timedelta(weeks=52), end)]
        self.msft[-1].update(open=505., high=511., low=505., close=510., volume=3000.)
        self._write_market(self.msft)

    def tearDown(self):
        export=os.environ.get("EQUITY_SWING_REPLAY_FIXTURE_EXPORT")
        if export:
            target=Path(export)/self._testMethodName
            if target.exists():raise RuntimeError("synthetic replay fixture export must not overwrite prior evidence")
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(self.root,target)
            (target/"SYNTHETIC_FIXTURE_NOT_REAL_MARKET_OR_ACCOUNT.txt").write_text(
                "Original-HTTP synthetic integration fixture; all prices, holdings, account changes and modeled paths are invented test inputs. No network or broker was contacted. No result is investment-performance evidence.\n")
        self.temporary.cleanup()

    def _write_market(self, msft):
        session = msft[-1]["session_date"]
        cutoff=date.fromisoformat(session)-timedelta(weeks=52)
        msft=[row for row in msft if date.fromisoformat(row["session_date"])>=cutoff]
        source_clock = stamp(session + "T16:30:00-04:00")
        spy = [{"session_date": row["session_date"], "open": 770., "high": 771., "low": 769., "close": 770., "volume": 1000.} for row in msft]
        snapshot = self.root / feed.BASELINE
        rows = [{"ticker": ticker, "last_price": bars[-1]["close"], "market_session_date": session,
                 "data_quality_label": "ok", "data_timestamp": source_clock.isoformat()}
                for ticker, bars in (("MSFT", msft), ("SPY", spy))]
        with snapshot.open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        observations, histories = [], {}
        for ticker, bars in (("MSFT", msft), ("SPY", spy)):
            raw = json.dumps({"kind": "synthetic_normalized_unadjusted_provider_fixture_not_real_prices", "ticker": ticker, "bars": bars}, sort_keys=True).encode()
            digest = hashlib.sha256(raw).hexdigest()
            relative = f"{market_backup.REL}/responses/{digest}.json"
            path = self.root / relative;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(raw)
            observations.append({"path": relative, "sha256": digest})
            histories[ticker] = {"source_url": f"https://api.massive.com/synthetic-fixture/{ticker}", "bars": bars}
        bundle = {"schema_version": market_backup.SCHEMA, "market_session": session, "generated_at": source_clock.isoformat(),
                  "data_source": market_backup.PRIMARY, "price_basis": "unadjusted", "tickers": histories, "observations": observations}
        pointer = market_backup.pointer_for(self.root, bundle, hashlib.sha256(snapshot.read_bytes()).hexdigest())
        feed.atomic_write_json(self.root / market_backup.CURRENT, pointer)
        # This is the genuine full-history/source-lineage admission, without patching it.
        admitted = market_backup.load_baseline(self.root, ["MSFT", "SPY"])
        self.assertEqual(admitted["market_session"], session)
        return pointer

    def _client(self, clock, msft_price):
        def get(url):
            self.requests.append(url)
            ticker = url.split("/quote/")[1].split("/")[0]
            previous = 510. if ticker == "MSFT" else 770.
            price = msft_price if ticker == "MSFT" else 760.
            change = price - previous
            payload = {"synthetic_test_fixture": True,
                       "data": {"symbol": ticker, "assetClass": "STOCKS" if ticker == "MSFT" else "ETF", "marketStatus": "Open",
                                "primaryData": {"lastSalePrice": f"${price:.2f}", "netChange": f"{change:+.2f}",
                                                "percentageChange": f"{change / previous * 100:+.2f}%",
                                                "lastTradeTimestamp": clock.strftime("%b %d, %Y %I:%M:%S %p ET"),
                                                "isRealTime": True, "currency": "USD"}},
                       "status": {"rCode": 200, "bCodeMessage": None}}
            return json.dumps(payload).encode()
        return feed.NasdaqIntradayClient(self.root, get=get, sleep=lambda _: None, now=lambda: clock)

    def _held_and_candidate_quote(self, clock, price):
        version = account_access.capture_version(self.root)
        held = feed.collect(self.root, {"MSFT": "stocks", "SPY": "etf"}, account_version=version,
                            claim_id="synthetic-held-" + clock.isoformat(), current=clock, client=self._client(clock, price))
        self.assertEqual(held["status"], "current")
        before = len(self.requests)
        context = quotes.collect(self.root, current=clock, claim_id="synthetic-swing-" + clock.isoformat(),
                                 symbols={"MSFT": "stocks"}, client=self._client(clock, price))
        self.assertEqual(context["status"], "current")
        self.assertEqual(context["held_marks_reused"], 1)
        self.assertEqual(context["request_count"], 0)
        self.assertEqual(len(self.requests), before)
        self.assertEqual(quotes.revalidate_quote_context(self.root, context, clock), context)
        return context

    def _capture_original_window(self):
        first = engine.build(self.root, self.first, capture=True)
        self.assertEqual(first["status"], "experimental_current")
        self.assertTrue(first["candidates"])
        self.assertEqual(engine.quote_targets(self.root, self.first), ["MSFT"])
        outside_clock = self.first + timedelta(seconds=10)
        outside = self._held_and_candidate_quote(outside_clock, 514.)
        rejected = engine.build(self.root, outside_clock + timedelta(seconds=10), capture=True, candidate_quote_context=outside)
        self.assertEqual(rejected["candidates"][0]["timing"]["state"], "outside_entry_band")
        entry_clock = self.first + timedelta(minutes=3, seconds=10)
        entered = self._held_and_candidate_quote(entry_clock, 511.)
        current = engine.build(self.root, entry_clock + timedelta(seconds=10), capture=True, candidate_quote_context=entered)
        self.assertEqual(current["candidates"][0]["timing"]["state"], "condition_observed")
        delay_clock = self.first + timedelta(minutes=6, seconds=20)
        delayed = self._held_and_candidate_quote(delay_clock, 512.)
        result = engine.build(self.root, delay_clock + timedelta(seconds=10), capture=True, candidate_quote_context=delayed)
        self.assertEqual(result["status"], "experimental_current")
        rows = engine._load(self.root, delay_clock + timedelta(seconds=10));engine._verify(self.root, rows)
        transitions = [row for row in rows if row["kind"] == "window_evaluation"]
        self.assertEqual([row["state"] for row in transitions], ["outside_entry_band", "condition_observed"])
        checks = [row for row in rows if row["kind"] == "delay_evaluation"]
        self.assertEqual(checks[0]["delay_minutes"], 3)
        self.assertEqual(checks[0]["actual_delay_seconds"], 190)
        self.assertEqual(checks[0]["quote_observation"]["price"], 512.)
        return first, entered, delayed, rows

    def test_original_http_window_cohort_survives_new_close_account_and_matures(self):
        first, entered, delayed, rows = self._capture_original_window()
        ledger = self.root / engine.OUTPUT / "ledger.jsonl";original_prefix = ledger.read_bytes()
        original_hashes = {row["record_hash"] for row in rows}
        dates = ["2026-09-23", *legacy._sessions_after(date(2026, 9, 23), 5)]
        forward = [{"session_date": day, "open": 512. + i, "high": 515. + i, "low": 508. + i,
                    "close": 513. + i, "volume": 1100.} for i, day in enumerate(dates)]
        future_bars = self.msft + forward
        self._write_market(future_bars)
        account = self.root / "05_risk_and_positions/current_account_state.local.json"
        account.write_text('{"cash_available":1300,"fixture":"synthetic changed account"}')
        (self.root / legacy.HOLDINGS).write_text("ticker,shares_optional\nMSFT,2\nSPY,1\n")
        # The original full held-account version and complete EOD/source bytes
        # must replay even though every active pointer now belongs to a later close.
        original_clock = legacy._aware(entered["generated_at"])
        self.assertEqual(quotes.revalidate_quote_context(self.root, entered, original_clock, require_latest=False), entered)
        future_clock = stamp("2026-09-30T17:00:00-04:00")
        engine._verify(self.root, engine._load(self.root, future_clock))
        result = engine.build(self.root, future_clock, capture=True)
        self.assertEqual(result["status"], "experimental_current")
        new_rows = engine._load(self.root, future_clock);engine._verify(self.root, new_rows)
        self.assertTrue(ledger.read_bytes().startswith(original_prefix))
        self.assertTrue(original_hashes.issubset({row["record_hash"] for row in new_rows}))
        outcomes = [row for row in new_rows if row["kind"] == "outcome"]
        delayed_outcome = next(row for row in outcomes if row.get("delay_minutes") == 3)
        self.assertEqual(delayed_outcome["entry_price"], 512.)
        self.assertEqual(delayed_outcome["actual_observation_delay_seconds"], 190)
        self.assertEqual(delayed_outcome["horizon_sessions"], 5)
        self.assertFalse(delayed_outcome["actual_fill"])
        self.assertFalse(delayed_outcome["performance_eligible"])
        next_session = stamp("2026-10-01T10:00:00-04:00")
        self.assertEqual(quotes.read_quote_context(self.root, next_session)["tickers"], {})
        with self.assertRaises(ValueError): quotes.revalidate_quote_context(self.root, delayed, next_session)
        # Historical verification is never a way to turn the original mark live.
        stale_view = engine.revalidate_projection(self.root, first, next_session)
        self.assertEqual(stale_view["candidates"], [])

    def test_changed_archived_original_is_rejected_without_rewriting_cohort(self):
        _, entered, _, _ = self._capture_original_window()
        ledger = self.root / engine.OUTPUT / "ledger.jsonl";before = ledger.read_bytes()
        original = quotes._source(self.root, entered["source"])
        account = next(row for row in original["baseline"]["input_archives"]
                       if row["original_path"] == "05_risk_and_positions/current_account_state.local.json")
        (self.root / account["archive_path"]).write_bytes(b"synthetic archive corruption")
        clock = legacy._aware(entered["generated_at"])
        with self.assertRaises(ValueError): quotes.revalidate_quote_context(self.root, entered, clock, require_latest=False)
        with self.assertRaises(ValueError): engine._verify(self.root, engine._load(self.root, clock + timedelta(minutes=10)))
        self.assertEqual(ledger.read_bytes(), before)


if __name__ == "__main__": unittest.main()
