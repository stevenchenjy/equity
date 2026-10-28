from __future__ import annotations

import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_intraday_prices as fixtures
import intraday_prices as feed
import swing_candidate_quotes as quotes


class CandidateQuotesTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IntradayPricesTests()
        self.fixture.setUp()
        self.root, self.current = self.fixture.root, self.fixture.current
        self.scope = {"MSFT": "stocks"}

    def tearDown(self):
        self.fixture.tearDown()

    def collect(self, values=None):
        return quotes.collect(self.root, current=self.current, claim_id="fixture-candidate",
                              client=self.fixture.client(values), symbols=self.scope)

    def test_source_bound_mark_rederived_without_changing_eod_or_held_pointer(self):
        before = (self.root / feed.BASELINE).read_bytes()
        value = self.collect()
        self.assertEqual(value["status"], "current")
        self.assertEqual(value["tickers"]["MSFT"]["price"], 500)
        self.assertEqual(value["request_count"], 1)
        self.assertEqual(quotes.revalidate_quote_context(self.root, value, self.current), value)
        self.assertEqual(quotes.read_quote_context(self.root, self.current), value)
        self.assertEqual((self.root / feed.BASELINE).read_bytes(), before)
        self.assertFalse((self.root / feed.CURRENT).exists())
        self.assertFalse(value["capital_authority"])
        self.assertEqual(value["actionable_quantity"], 0)

    def test_fresh_complete_held_scope_is_reused_without_redundant_fetch(self):
        from account_access import capture_version
        feed.collect(self.root, self.fixture.scope, current=self.current,
                     account_version=capture_version(self.root), claim_id="held-fixture", client=self.fixture.client())
        no_network = Mock()
        value = quotes.collect(self.root, current=self.current, claim_id="reuse",
                               client=no_network, symbols=self.scope)
        no_network.fetch.assert_not_called()
        self.assertEqual(value["status"], "current")
        self.assertEqual(value["held_marks_reused"], 1)
        self.assertEqual(value["request_count"], 0)

    def test_changed_account_fences_held_reuse(self):
        self.fixture.collect()
        with patch("account_access.capture_version", return_value="changed-account"):
            value = self.collect()
        self.assertEqual(value["held_marks_reused"], 0)
        self.assertEqual(value["request_count"], 1)

    def test_no_candidates_premarket_afterhours_and_earlyclose_make_zero_requests(self):
        for stamp, scope, status in (
            ("2026-10-22T11:01:00-04:00", {}, "no_candidates"),
            ("2026-10-22T08:45:00-04:00", self.scope, "market_closed"),
            ("2026-10-22T16:01:00-04:00", self.scope, "market_closed"),
            ("2026-11-27T13:01:00-05:00", self.scope, "market_closed")):
            client = Mock()
            result = quotes.collect(self.root, current=fixtures.moment(stamp), claim_id="closed",
                                    client=client, symbols=scope)
            client.fetch.assert_not_called()
            self.assertEqual(result["status"], status)
            self.assertEqual(result["tickers"], {})

    def test_failed_latest_and_pending_interrupt_fence_old_good_quote(self):
        good = self.collect()
        bad = fixtures.payload(); bad["data"]["primaryData"]["isRealTime"] = False
        latest = self.collect({"MSFT": bad})
        self.assertEqual(latest["status"], "unavailable")
        self.assertEqual(quotes.read_quote_context(self.root, self.current)["tickers"], {})
        with self.assertRaisesRegex(ValueError, "latest_attempt_changed"):
            quotes.revalidate_quote_context(self.root, good, self.current)
        self.assertEqual(quotes.revalidate_quote_context(self.root, good, self.current,
                                                       require_latest=False), good)
        quotes.record_failure(self.root, current=self.current, claim_id="interrupted", reason="in_progress")
        self.assertEqual(quotes.read_quote_context(self.root, self.current)["tickers"], {})

    def test_browser_read_time_expiry_never_rolls_into_another_session(self):
        value = self.collect()
        for clock in (fixtures.moment("2026-10-22T11:05:00-04:00"), self.current + timedelta(days=1)):
            read = quotes.read_quote_context(self.root, clock)
            self.assertEqual(read["tickers"], {})
            with self.assertRaisesRegex(ValueError, "changed_or_expired"):
                quotes.revalidate_quote_context(self.root, value, clock)

    def test_wrong_symbol_delay_dateonly_future_or_conflicting_close_is_rejected(self):
        replacements = []
        bad = fixtures.payload(); bad["data"]["symbol"] = "NVDA"; replacements.append(bad)
        bad = fixtures.payload(); bad["data"]["primaryData"]["isRealTime"] = False; replacements.append(bad)
        replacements += [fixtures.payload(stamp="Oct22,2026"), fixtures.payload(stamp="Oct 22, 2026 11:02 AM ET"), fixtures.payload(change="-1.00")]
        for item in replacements:
            with self.subTest(item=item):
                result = self.collect({"MSFT": item})
                self.assertEqual(result["tickers"], {})
                self.assertEqual(result["status"], "unavailable")

    def test_missing_or_changed_baseline_cannot_admit_quality_labels(self):
        value = self.collect()
        path = self.root / feed.BASELINE
        path.write_text(path.read_text().replace("510", "511"))
        self.assertEqual(quotes.read_quote_context(self.root, self.current)["tickers"], {})
        result = self.collect()
        self.assertEqual(result["tickers"], {})
        self.assertEqual(result["request_count"], 0)

    def test_history_available_only_after_original_clock_cannot_support_a_quote(self):
        pointer = json.loads((self.root / feed.market_backup.CURRENT).read_bytes())
        history = json.loads((self.root / feed.market_backup.REL / pointer["history_path"]).read_bytes())
        history["generated_at"] = (self.current + timedelta(minutes=1)).isoformat()
        changed = feed.market_backup.pointer_for(self.root, history, feed._sha((self.root / feed.BASELINE).read_bytes()))
        feed.atomic_write_json(self.root / feed.market_backup.CURRENT, changed)
        result = self.collect()
        self.assertEqual(result["tickers"], {})
        self.assertEqual(result["request_count"], 0)
        snapshot = quotes._source(self.root, result["source"])
        self.assertIn("not_available_at_observation", snapshot["failures"]["MSFT"])

    def test_raw_http_and_retained_snapshot_tampering_are_detected(self):
        value = self.collect()
        source = value["tickers"]["MSFT"]["source"]
        (self.root / source["response"]["path"]).write_bytes(b"{}")
        self.assertEqual(quotes.read_quote_context(self.root, self.current)["tickers"], {})
        with self.assertRaisesRegex(ValueError, "changed_or_expired"):
            quotes.revalidate_quote_context(self.root, value, self.current)

    def test_arbitrary_projection_price_or_study_baseline_is_not_trusted(self):
        value = self.collect()
        changed = copy.deepcopy(value); changed["tickers"]["MSFT"]["price"] = 1
        with self.assertRaisesRegex(ValueError, "changed_or_expired"):
            quotes.revalidate_quote_context(self.root, changed, self.current)
        for binding in ({"snapshot_sha256": "0"*64}, {"history_sha256": "0"*64}, {"market_session": "2026-10-20"}):
            with self.assertRaisesRegex(ValueError, "study_baseline_changed"):
                quotes.revalidate_quote_context(self.root, value, self.current, baseline_bindings=binding)

    def test_scope_is_bounded_stocks_only_and_safe(self):
        for scope in ({"../MSFT": "stocks"}, {"SPY": "etf"}, {"A": "stocks", "B": "stocks", "C": "stocks", "D": "stocks"}):
            with self.assertRaisesRegex(ValueError, "scope_invalid"):
                quotes.collect(self.root, current=self.current, claim_id="bad", symbols=scope)

    def test_source_symlinks_cannot_redirect_candidate_writes(self):
        target = self.root / quotes.REL
        target.parent.mkdir(parents=True, exist_ok=True)
        outside = self.root / "outside"; outside.mkdir()
        target.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unsafe_source_path"):
            self.collect()
        self.assertEqual(list(outside.iterdir()), [])

    def test_outside_history_reader_can_supply_its_own_current_close_without_seed_expansion(self):
        proof = self.root / "research-primary.original"; proof.write_bytes(b"explicit synthetic source proof")
        import hashlib
        digest = hashlib.sha256(proof.read_bytes()).hexdigest()
        module = types.ModuleType("swing_candidate_history")
        module.admitted = lambda *a, **kw: {"histories": {"OUT": {
            "bars": [{"session_date": "2026-10-21", "close": 510}],
            "price_basis": "unadjusted", "common_stock_verified": True,
            "source_available_at": "2026-10-21T20:00:00-04:00",
            "source_bindings": {"research-primary.original": digest}}}}
        original = (self.root / feed.BASELINE).read_bytes()
        with patch.dict(sys.modules, swing_candidate_history=module):
            result = quotes.collect(self.root, current=self.current, claim_id="outside",
                symbols={"OUT": "stocks"}, client=self.fixture.client({"OUT": fixtures.payload("OUT")}))
            self.assertEqual(result["status"], "current")
            self.assertEqual(result["tickers"]["OUT"]["baseline_close"], 510)
            self.assertEqual(quotes.revalidate_quote_context(self.root, result, self.current), result)
            proof.write_bytes(b"changed source")
            self.assertEqual(quotes.read_quote_context(self.root, self.current)["tickers"], {})
        self.assertEqual((self.root / feed.BASELINE).read_bytes(), original)

    def test_historical_quote_replay_uses_original_close_after_next_eod_replacement(self):
        value = self.collect()
        # A new required close must fence the old live context, while the old
        # timestamped observation remains replayable for forward evaluation.
        self.fixture.write_baseline(session="2026-10-22")
        self.assertEqual(quotes.read_quote_context(self.root, self.current)["tickers"], {})
        self.assertEqual(quotes.revalidate_quote_context(self.root, value, self.current,
                                                       require_latest=False), value)
        snapshot = quotes._source(self.root, value["source"])
        archive = snapshot["baseline"]["input_archives"][0]
        (self.root / archive["archive_path"]).write_bytes(b"corrupt original archive")
        with self.assertRaisesRegex(ValueError, "archive_hash_changed"):
            quotes.revalidate_quote_context(self.root, value, self.current, require_latest=False)

    def test_historical_held_reuse_keeps_original_account_and_scope_after_account_changes(self):
        from account_access import capture_version
        feed.collect(self.root, self.fixture.scope, current=self.current,
                     account_version=capture_version(self.root), claim_id="held-fixture", client=self.fixture.client())
        value = quotes.collect(self.root, current=self.current, claim_id="held-reuse",
                               client=Mock(), symbols=self.scope)
        self.assertEqual(value["held_marks_reused"], 1)
        p = self.root / "05_risk_and_positions/current_account_state.local.json"
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{"fixture_changed_account":true}')
        self.assertEqual(quotes.read_quote_context(self.root, self.current)["tickers"], {})
        self.assertEqual(quotes.revalidate_quote_context(self.root, value, self.current,
                                                       require_latest=False), value)

    def test_unadmitted_outside_history_cannot_be_substituted_with_an_observed_price(self):
        module = types.ModuleType("swing_candidate_history")
        module.admitted = lambda *a, **kw: {"histories": {}, "ticker_blockers": {"OUT": "source incomplete"}}
        client = Mock()
        with patch.dict(sys.modules, swing_candidate_history=module):
            result = quotes.collect(self.root, current=self.current, claim_id="missing-outside",
                                    symbols={"OUT": "stocks"}, client=client)
        client.fetch.assert_not_called()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["tickers"], {})


if __name__ == "__main__":
    unittest.main()
