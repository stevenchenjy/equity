from __future__ import annotations

import copy
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import intraday_prices as feed
import market_backup as backup

ET = ZoneInfo("America/New_York")


def moment(value="2026-10-22T11:01:00-04:00"):
    return datetime.fromisoformat(value).astimezone(ET)


def payload(ticker="MSFT", price="$500.00", change="-10.00", pct="-1.96%", stamp="Oct 22, 2026 11:00 AM ET", asset="STOCKS"):
    return {"data": {"symbol": ticker, "assetClass": asset, "marketStatus": "Open",
            "primaryData": {"lastSalePrice": price, "netChange": change, "percentageChange": pct,
                            "lastTradeTimestamp": stamp, "isRealTime": True, "currency": None}},
            "status": {"rCode": 200, "bCodeMessage": None}}


def seed_admitted_history(root: Path) -> dict:
    """Admit synthetic retained source bytes for an already-written test CSV.

    Uses the real one-year history format and content-addressed pointer. The
    production validator is never patched or replaced by this fixture helper.
    """
    path = root / feed.BASELINE
    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    session = rows[0]["market_session_date"]
    end = date.fromisoformat(session)
    histories, observations = {}, []
    for row in rows:
        ticker, close = row["ticker"], float(row["last_price"])
        bars = [{"session_date": str(day), "open": close, "high": close + 1,
                 "low": close - 1, "close": close, "volume": 1000.0}
                for day in backup.sessions(end - timedelta(weeks=52), end)]
        original = json.dumps({"kind": "synthetic_test_normalized_provider_observation", "ticker": ticker, "bars": bars}).encode()
        digest = hashlib.sha256(original).hexdigest()
        source_path = f"{backup.REL}/responses/{digest}.json"
        (root / source_path).parent.mkdir(parents=True, exist_ok=True)
        (root / source_path).write_bytes(original)
        observations.append({"path": source_path, "sha256": digest})
        histories[ticker] = {"source_url": "https://api.massive.com/retained-test-observation", "bars": bars}
    generated = datetime.fromisoformat(session + "T16:30:00").replace(tzinfo=ET).isoformat()
    value = {"schema_version": backup.SCHEMA, "market_session": session,
             "generated_at": generated, "data_source": backup.PRIMARY,
             "price_basis": "unadjusted", "tickers": histories, "observations": observations}
    pointer = backup.pointer_for(root, value, hashlib.sha256(path.read_bytes()).hexdigest())
    feed.atomic_write_json(root / backup.CURRENT, pointer)
    return pointer


class IntradayPricesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.current = moment()
        self.scope = {"MSFT": "stocks", "SPY": "etf"}
        self.write_baseline()

    def tearDown(self):
        self.temp.cleanup()

    def write_baseline(self, session="2026-10-21", duplicate=False):
        path = self.root / feed.BASELINE
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"ticker": "MSFT", "last_price": "510", "market_session_date": session, "data_quality_label": "ok"},
                {"ticker": "SPY", "last_price": "770", "market_session_date": session, "data_quality_label": "ok"}]
        if duplicate:
            rows.append(rows[0])
        with path.open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        seed_admitted_history(self.root)

    def client(self, values=None):
        values = values or {"MSFT": payload(), "SPY": payload("SPY", "$760.00", "-10.00", "-1.30%", asset="ETF")}
        def get(url):
            ticker = url.split("/quote/")[1].split("/")[0]
            value = values[ticker]
            return value if isinstance(value, bytes) else json.dumps(value).encode()
        return feed.NasdaqIntradayClient(self.root, get=get, sleep=lambda _: None, now=lambda: self.current)

    def collect(self, values=None, **kwargs):
        return feed.collect(self.root, self.scope, account_version="account-1", claim_id="claim-1",
                            current=self.current, client=self.client(values), **kwargs)

    def validate(self, snapshot, **kwargs):
        return feed.validate_snapshot(self.root, snapshot, current=self.current,
                                     account_version="account-1", symbols=self.scope, claim_id="claim-1", **kwargs)

    def test_complete_scope_binds_raw_receipts_and_canonical_previous_close(self):
        before = (self.root / feed.BASELINE).read_bytes()
        result = self.collect()
        self.assertEqual(result["status"], "current")
        self.assertEqual(set(result["rows"]), set(self.scope))
        self.assertEqual(result["expires_at"], "2026-10-22T11:05:00-04:00")
        self.assertEqual(result["rows"]["MSFT"]["previous_close"], 510)
        self.assertEqual(self.validate(result), result)
        self.assertEqual(feed.load_current(self.root, current=self.current), result)
        self.assertEqual((self.root / feed.BASELINE).read_bytes(), before)

    def test_a_failed_latest_attempt_fences_a_previous_fresh_success(self):
        previous = self.collect()
        bad = payload(); bad["data"]["primaryData"]["isRealTime"] = False
        latest = self.collect({"MSFT": bad, "SPY": payload("SPY", "$760.00", "-10.00", "-1.30%", asset="ETF")})
        self.assertEqual(latest["status"], "partial")
        with self.assertRaisesRegex(feed.IntradayPriceError, "latest_attempt_changed"):
            self.validate(previous)
        with self.assertRaisesRegex(feed.IntradayPriceError, "complete_current_scope_required"):
            feed.load_current(self.root, current=self.current)

    def test_closed_market_does_not_fetch_or_admit_date_only_eod(self):
        client = Mock()
        result = feed.collect(self.root, self.scope, account_version="a", claim_id="c",
                              current=moment("2026-10-22T20:55:00-04:00"), client=client)
        client.fetch.assert_not_called()
        self.assertEqual(result["status"], "market_closed")
        self.assertFalse(result["complete"])
        self.assertEqual(result["rows"], {})

    def test_holiday_and_early_close_never_admit_regular_session_marks(self):
        for stamp in ("2026-11-26T11:00:00-05:00", "2026-11-27T13:01:00-05:00"):
            self.assertFalse(feed.market_open(moment(stamp)))
        self.assertTrue(feed.market_open(moment("2026-11-27T12:59:00-05:00")))

    def test_missing_time_is_rejected_even_with_provider_real_time_flag(self):
        value = payload(stamp="Oct 22, 2026")
        with self.assertRaisesRegex(feed.IntradayPriceError, "trade_time_missing"):
            feed.normalize(value, "MSFT", "stocks", 510, self.current)

    def test_delayed_or_unknown_delay_is_rejected(self):
        for flag in (False, None, "true", 1):
            value = payload(); value["data"]["primaryData"]["isRealTime"] = flag
            with self.assertRaisesRegex(feed.IntradayPriceError, "delay_unverified"):
                feed.normalize(value, "MSFT", "stocks", 510, self.current)

    def test_timestamps_are_eastern_with_actual_dst_offset(self):
        result = feed.normalize(payload(), "MSFT", "stocks", 510, self.current)
        self.assertEqual(result["trade_at"], "2026-10-22T11:00:00-04:00")
        with self.assertRaisesRegex(feed.IntradayPriceError, "trade_time_missing"):
            feed.normalize(payload(stamp="Oct 22, 2026 11:00 AM UTC"), "MSFT", "stocks", 510, self.current)

    def test_stale_future_wrong_session_and_extended_hours_rejected(self):
        for stamp, reason in (("Oct 22, 2026 10:55 AM ET", "price_stale"),
                              ("Oct 22, 2026 11:02 AM ET", "future_timestamp"),
                              ("Oct 21, 2026 11:00 AM ET", "trade_session_invalid"),
                              ("Oct 22, 2026 9:29 AM ET", "trade_session_invalid")):
            with self.assertRaisesRegex(feed.IntradayPriceError, reason):
                feed.normalize(payload(stamp=stamp), "MSFT", "stocks", 510, self.current)

    def test_after_hours_and_wrong_symbol_asset_are_rejected(self):
        for field, replacement in (("marketStatus", "After-Hours"), ("symbol", "AMZN"), ("assetClass", "ETF")):
            value = payload(); value["data"][field] = replacement
            with self.assertRaisesRegex(feed.IntradayPriceError, "symbol_asset_or_session_conflict"):
                feed.normalize(value, "MSFT", "stocks", 510, self.current)

    def test_previous_close_conflict_and_malformed_numbers_are_rejected(self):
        for field, replacement, reason in (("lastSalePrice", "$501", "previous_close_conflict"),
                                            ("lastSalePrice", "$0", "numeric_invalid"),
                                            ("lastSalePrice", "NaN", "numeric_invalid"),
                                            ("percentageChange", "-20%", "percentage_conflict")):
            value = payload(); value["data"]["primaryData"][field] = replacement
            with self.assertRaisesRegex(feed.IntradayPriceError, reason):
                feed.normalize(value, "MSFT", "stocks", 510, self.current)

    def test_duplicate_missing_or_stale_canonical_rows_block_complete_mark(self):
        self.write_baseline(duplicate=True)
        result = self.collect()
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("canonical_previous_close_unavailable", result["failures"]["MSFT"])
        self.write_baseline(session="2026-10-20")
        result = self.collect()
        self.assertEqual(result["status"], "unavailable")

    def test_changed_baseline_is_detected_at_read_time(self):
        result = self.collect()
        path = self.root / feed.BASELINE
        path.write_text(path.read_text().replace("510", "511"))
        with self.assertRaisesRegex(feed.IntradayPriceError, "canonical_previous_close_unavailable"):
            self.validate(result)

    def test_quality_label_alone_cannot_replace_admitted_market_history(self):
        (self.root / backup.CURRENT).unlink()
        client = Mock()
        result = feed.collect(self.root, self.scope, account_version="a", claim_id="c", current=self.current, client=client)
        client.fetch.assert_not_called()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(set(result["failures"].values()), {"intraday_canonical_previous_close_unavailable"})

    def test_full_scope_retained_original_eod_sources_are_revalidated(self):
        result = self.collect()
        bindings = result["baseline"]["source_bindings"]
        self.assertTrue(any(row["path"] == backup.CURRENT for row in bindings))
        self.assertTrue(any("/history/" in row["path"] for row in bindings))
        original = next(row for row in bindings if "/responses/" in row["path"])
        (self.root / original["path"]).write_bytes(b"changed retained EOD response")
        with self.assertRaisesRegex(feed.IntradayPriceError, "canonical_previous_close_unavailable"):
            self.validate(result)

    def test_admitted_history_hash_change_is_not_accepted_from_csv_label(self):
        pointer = json.loads((self.root / backup.CURRENT).read_bytes())
        path = self.root / backup.REL / pointer["history_path"]
        path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(self.collect()["status"], "unavailable")

    def test_fresh_snapshot_hash_does_not_admit_close_conflicting_with_retained_bar(self):
        pointer = json.loads((self.root / backup.CURRENT).read_bytes())
        value = json.loads((self.root / backup.REL / pointer["history_path"]).read_bytes())
        csv_path = self.root / feed.BASELINE
        csv_path.write_text(csv_path.read_text().replace("510", "511"))
        new_pointer = backup.pointer_for(self.root, value, hashlib.sha256(csv_path.read_bytes()).hexdigest())
        feed.atomic_write_json(self.root / backup.CURRENT, new_pointer)
        self.assertEqual(self.collect()["status"], "unavailable")

    def test_invalid_unselected_history_prevents_partial_universe_provenance(self):
        self.scope = {"MSFT": "stocks"}
        pointer = json.loads((self.root / backup.CURRENT).read_bytes())
        value = json.loads((self.root / backup.REL / pointer["history_path"]).read_bytes())
        value["tickers"]["SPY"]["bars"].pop(30)
        new_pointer = backup.pointer_for(self.root, value, hashlib.sha256((self.root / feed.BASELINE).read_bytes()).hexdigest())
        feed.atomic_write_json(self.root / backup.CURRENT, new_pointer)
        self.assertEqual(self.collect()["status"], "unavailable")

    def test_corrupt_original_http_bytes_are_detected(self):
        result = self.collect()
        path = self.root / result["rows"]["MSFT"]["source"]["response"]["path"]
        path.write_bytes(b"{}")
        with self.assertRaisesRegex(feed.IntradayPriceError, "retained_source_invalid"):
            self.validate(result)

    def test_changed_account_claim_scope_and_price_cannot_be_admitted(self):
        result = self.collect()
        for key, replacement in (("account_version", "account-2"), ("claim_id", "claim-2")):
            args = dict(current=self.current, account_version="account-1", claim_id="claim-1", symbols=self.scope)
            args[key] = replacement
            with self.assertRaisesRegex(feed.IntradayPriceError, "snapshot_binding_changed"):
                feed.validate_snapshot(self.root, result, **args)
        forged = copy.deepcopy(result); forged["rows"]["MSFT"]["price"] = 1
        with self.assertRaisesRegex(feed.IntradayPriceError, "content_binding_invalid"):
            self.validate(forged)

    def test_immutable_historical_receipt_remains_verifiable_after_failed_attempt(self):
        previous = self.collect()
        bad = payload(); bad["data"]["primaryData"]["isRealTime"] = False
        self.collect({"MSFT": bad, "SPY": payload("SPY", "$760.00", "-10.00", "-1.30%", asset="ETF")})
        self.assertEqual(feed.validate_snapshot(self.root, previous, current=self.current, require_latest=False), previous)
        with self.assertRaisesRegex(feed.IntradayPriceError, "complete_current_scope_required"):
            feed.load_current(self.root, current=self.current, require_latest=False)

    def test_early_close_caps_expiry_before_normal_five_minute_age(self):
        self.current = moment("2026-11-27T12:59:30-05:00")
        self.write_baseline(session="2026-11-25")
        values = {"MSFT": payload(stamp="Nov 27, 2026 12:59 PM ET"),
                  "SPY": payload("SPY", "$760.00", "-10.00", "-1.30%", stamp="Nov 27, 2026 12:59 PM ET", asset="ETF")}
        # The retained-history validator uses its own clock; this fixture moves
        # that clock, rather than bypassing any source or admission validator.
        with unittest.mock.patch.object(backup, "now_et", return_value=self.current):
            result = self.collect(values)
            self.assertEqual(result["expires_at"], "2026-11-27T13:00:00-05:00")
            self.assertEqual(self.validate(result), result)

    def test_failed_request_keeps_original_attempt_and_no_prior_price_fallback(self):
        def timeout(_):
            raise TimeoutError("provider details must not become an invented mark")
        client = feed.NasdaqIntradayClient(self.root, get=timeout, sleep=lambda _: None, now=lambda: self.current)
        result = feed.collect(self.root, self.scope, account_version="a", claim_id="c", current=self.current, client=client)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["rows"], {})
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(set(result["failures"].values()), {"intraday_request_failed"})

    def test_price_expires_at_read_time_and_never_rolls_into_next_session(self):
        result = self.collect()
        with self.assertRaisesRegex(feed.IntradayPriceError, "price_stale"):
            feed.validate_snapshot(self.root, result, current=self.current + timedelta(minutes=5))
        with self.assertRaisesRegex(feed.IntradayPriceError, "snapshot_clock_invalid|price_stale"):
            feed.validate_snapshot(self.root, result, current=self.current + timedelta(days=1))

    def test_malformed_original_json_is_retained_with_explicit_failure(self):
        result = self.collect({"MSFT": b"not json", "SPY": b"{}"})
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("intraday_json_invalid", result["failures"]["MSFT"])
        self.assertTrue((self.root / result["attempts"][0]["response"]["path"]).exists())
        self.assertEqual(feed.load_latest(self.root), result)

    def test_symbol_scope_cannot_duplicate_or_redirect(self):
        for scope in ({"../MSFT": "stocks"}, {"MSFT": "index"}, {}):
            with self.assertRaisesRegex(feed.IntradayPriceError, "scope_invalid"):
                feed.collect(self.root, scope, account_version="a", claim_id="c", current=self.current)

    def test_offline_unavailable_snapshot_has_same_schema_no_network_or_price_fallback(self):
        self.collect()
        with unittest.mock.patch.object(feed.NasdaqIntradayClient, "fetch", side_effect=AssertionError("no network")):
            result = feed.record_unavailable(self.root, self.scope, account_version="account-1", claim_id="offline",
                                             reason="intraday_not_collected_in_offline_recomposition", current=self.current)
        self.assertEqual(result["schema_version"], feed.SCHEMA)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["rows"], {})
        self.assertEqual(result["attempts"], [])
        self.assertEqual(set(result["failures"]), set(self.scope))
        self.assertEqual(feed.load_latest(self.root), result)
        with self.assertRaisesRegex(feed.IntradayPriceError, "complete_current_scope_required"):
            feed.load_current(self.root, current=self.current)

    def test_offline_unavailable_reason_requires_bounded_clear_text(self):
        for reason in (None, float("nan"), "", " ", "bad\nnew line", "a" * 301):
            with self.assertRaisesRegex(feed.IntradayPriceError, "unavailable_reason_invalid"):
                feed.record_unavailable(self.root, self.scope, account_version="a", claim_id="c", reason=reason, current=self.current)

    def test_parent_symlinks_cannot_redirect_observation_writes_or_reads(self):
        result = self.collect()
        responses = self.root / feed.REL / "responses"
        moved = self.root / "outside-responses"
        responses.rename(moved)
        responses.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(feed.IntradayPriceError, "retained_source_invalid"):
            self.validate(result)
        before = {path.name: path.read_bytes() for path in moved.iterdir()}
        failed = self.collect()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(set(failed["failures"].values()), {"intraday_unsafe_source_path"})
        self.assertEqual({path.name: path.read_bytes() for path in moved.iterdir()}, before)

    def test_oversized_response_retains_truncation_label_and_never_admits_a_mark(self):
        client = self.client({"MSFT": b"x" * 2_000_001, "SPY": b"{}"})
        result = feed.collect(self.root, self.scope, account_version="a", claim_id="c", current=self.current, client=client)
        self.assertEqual(result["status"], "unavailable")
        http = json.loads((self.root / result["attempts"][0]["path"]).read_bytes())
        self.assertTrue(http["response_truncated"])
        self.assertEqual(http["response_bytes_read"], 2_000_001)
        self.assertEqual(http["error"], "intraday_response_size_invalid")

    def test_batch_timestamp_skew_preserves_rows_but_withholds_portfolio_mark(self):
        values = {"MSFT": payload(stamp="Oct 22, 2026 10:57 AM ET"),
                  "SPY": payload("SPY", "$760.00", "-10.00", "-1.30%", asset="ETF")}
        result = self.collect(values)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["complete"])
        self.assertEqual(set(result["rows"]), set(self.scope))
        self.assertEqual(result["failures"]["__scope__"], "intraday_batch_timestamp_skew")
        # A counterfactual stored current wrapper must pass the same span check.
        result.pop("snapshot_path"); result.pop("snapshot_sha256")
        result.update(status="current", complete=True, failures={})
        forged = feed._publish(self.root, result)
        with self.assertRaisesRegex(feed.IntradayPriceError, "batch_timestamp_skew"):
            self.validate(forged)


if __name__ == "__main__":
    unittest.main()
