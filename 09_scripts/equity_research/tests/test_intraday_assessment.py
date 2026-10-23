from __future__ import annotations

import copy
import json
from datetime import timedelta
import unittest
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR  # noqa: F401
import intraday_assessment as integration
import intraday_prices as feed
import short_assessment as short
import test_intraday_portfolio_risk as risk_tests


class IntradayIntegrationTests(unittest.TestCase):
    setUp = risk_tests.IntradayPortfolioRiskTests.setUp
    write = risk_tests.IntradayPortfolioRiskTests.write
    csv = risk_tests.IntradayPortfolioRiskTests.csv
    plans = risk_tests.IntradayPortfolioRiskTests.plans
    snapshot = risk_tests.IntradayPortfolioRiskTests.snapshot
    def test_explicit_collection_retains_immutable_risk_and_offline_recomposition_has_no_http(self):
        snapshot = self.snapshot()
        with patch.object(feed, "collect", return_value=snapshot) as collect:
            first = integration.recompose(self.root, current=self.now, collect=True, client=Mock(), claim_id="claim-risk")
        self.assertEqual(first["status"], "current", first)
        collect.assert_called_once()
        source = first["source"]
        retained = self.root / source["path"]
        self.assertEqual(json.loads(retained.read_bytes()), first["assessment"])
        with patch.object(feed, "collect", side_effect=AssertionError("offline HTTP")):
            second = integration.recompose(self.root, current=self.now)
        self.assertEqual(second["source"], source)
        view = integration.publication_context(self.root, self.now)
        self.assertEqual(view["portfolio_nav"], 386)
        self.assertEqual(integration.attention(self.root, self.now)["assessment_source"], source)
        self.assertFalse(view["email_authorized"])
        self.assertEqual(integration.attention(self.root, self.now+timedelta(minutes=6))["status"], "expired")
        self.assertEqual(integration.publication_context(self.root, self.now+timedelta(minutes=6))["portfolio_nav"], 386)

    def test_closed_collection_is_truthful_and_does_not_fetch(self):
        client = Mock()
        receipt = integration.recompose(self.root, current=self.now.replace(hour=21), collect=True, client=client)
        client.fetch.assert_not_called()
        self.assertEqual(receipt["assessment"]["status"], "unavailable")
        self.assertIsNone(receipt["assessment"]["portfolio_nav"])
        self.assertFalse(receipt["email_sent"])

    def test_receipt_tamper_cannot_create_a_current_mark(self):
        self.snapshot()
        receipt = integration.recompose(self.root, current=self.now)
        path = self.root / receipt["source"]["path"]
        path.write_text("{}")
        value = integration.publication_context(self.root, self.now)
        self.assertEqual(value["status"], "unavailable")
        self.assertEqual(value["new_order_quantities"], 0)

    def test_invalid_quantity_and_parent_symlink_cannot_write_a_receipt(self):
        self.csv("05_risk_and_positions/current_positions.local.csv", [{"ticker":"SPY","shares_optional":"NaN"}])
        with self.assertRaisesRegex(ValueError, "positive_inventory_required"):
            integration.held_symbols(self.root)
        store = self.root / integration.HISTORY
        target = self.root / "other"
        target.mkdir()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "path_unsafe"):
            integration._retain(self.root, {})

    def test_short_handoff_collects_prices_despite_recent_news_and_keeps_fixed_timeouts(self):
        runner = Mock(return_value=Mock(returncode=0))
        with patch.object(short, "_public_due", return_value=False):
            result = short.refresh_public_handoff(self.root, self.now, runner=runner, claim_id="real-claim")
        command = runner.call_args.args[0]
        self.assertIn("run_intraday_assessment.py", command[1])
        self.assertEqual(command[-1], "real-claim")
        self.assertEqual(runner.call_args.kwargs["timeout"], 105)
        self.assertEqual(len(result["children"]), 1)
        self.assertFalse(result["coverage_is_analytical_completion"])

    def test_same_prices_with_new_quote_clock_do_not_change_resumable_work(self):
        self.snapshot()
        integration.recompose(self.root, current=self.now)
        with patch("official_news.read_official_news_status", return_value={"status":"ok","sources":[],"recent_events":[]}), patch("earnings_events.summary", return_value={"status":"ready","events":[],"coverage":{}}):
            first = short.build_context(self.root, self.now)
            view = integration.attention(self.root, self.now)
            later = copy.deepcopy(view)
            for row in later["positions"]:
                row["price_as_of"] = (self.now+timedelta(seconds=10)).isoformat()
                row["source"] = {"sha256":"changed-raw-clock-receipt"}
            with patch.object(integration, "attention", return_value=later):
                second = short.build_context(self.root, self.now+timedelta(seconds=10))
        self.assertEqual(first["input_fingerprint"], second["input_fingerprint"])

    def test_corrupt_optional_receipt_does_not_abort_independent_short_research(self):
        path = self.root / integration.CURRENT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid-json")
        value = integration.attention(self.root, self.now)
        self.assertEqual(value["status"], "unavailable")
        self.assertIsNone(value["assessment_source"])

    def test_raw_price_risk_cannot_create_changed_advice_or_mutate_capital(self):
        from delivery_assessments import advice_meaning_key
        from test_email_brief import decision_fixture
        self.snapshot()
        receipt = integration.recompose(self.root, current=self.now)
        decision = decision_fixture()
        original = copy.deepcopy(decision)
        before = advice_meaning_key(decision)
        decision["intraday_portfolio_risk"] = receipt["assessment"]
        self.assertEqual(advice_meaning_key(decision), before)
        self.assertEqual(decision["account"], original["account"])
        self.assertEqual(decision.get("capital_decision"), original.get("capital_decision"))
        self.assertEqual(receipt["assessment"]["new_order_quantities"], 0)

    def test_offline_recompose_preserves_dated_observation_but_not_expired_live_marks(self):
        self.snapshot()
        first = integration.recompose(self.root, current=self.now)
        later = self.now + timedelta(minutes=7)
        second = integration.recompose(self.root, current=later)
        self.assertEqual(second["assessment"], first["assessment"])
        self.assertEqual(second["source"], first["source"])
        self.assertEqual(integration.publication_context(self.root, later)["portfolio_nav"], 386)
        self.assertEqual(integration.attention(self.root, later)["status"], "expired")
        self.snapshot(broken="AAA")
        failed = integration.recompose(self.root, current=self.now)
        self.assertEqual(failed["assessment"]["status"], "partial")
        self.assertIsNone(failed["assessment"]["portfolio_nav"])

    def test_subsecond_observation_requires_truthful_full_precision_publication_clock(self):
        self.now += timedelta(microseconds=500000)
        self.snapshot()
        integration.recompose(self.root, current=self.now)
        truncated = self.now.replace(microsecond=0)
        self.assertEqual(integration.publication_context(self.root, truncated)["status"], "unavailable")
        self.assertEqual(integration.publication_context(self.root, self.now)["status"], "current")
