"""A household decision is reproducible from dated account observations; execution is broker-specific."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from _support import PROJECT_ROOT, visible_html_text
import delivery_assessments as delivery
import household_planning as hp

NOW = datetime.fromisoformat("2026-11-18T09:45:00-05:00")
PREVIOUS = (NOW - timedelta(days=1)).isoformat()


class HouseholdPlanningTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        config = json.loads((PROJECT_ROOT / hp.CONFIG).read_bytes())
        self.write(hp.CONFIG, config)
        position = lambda quantity, value: dict(ticker="ABC", quantity_shares=quantity, market_value_usd=value)
        self.observation = dict(schema="private_brokerage_observation_v1", accounts={
            "chase": {"currency": "USD", "source": {"positions_and_balances_reported_asof_et": PREVIOUS},
                      "positions": [position("2", "200")], "balances_usd": {"cash_and_sweep_funds": "100",
                      "account_value": "300", "cash_available_to_trade": "100"}},
            "moomoo": {"currency": "USD", "source": {"local_screen_clock_et": PREVIOUS, "connection_notice": "Network Error"},
                       "positions": [position("1", "101")], "assets": {"displayed_total_assets_usd": "150"}}})
        raw = json.dumps(self.observation).encode()
        sha = hashlib.sha256(raw).hexdigest()
        self.broker_path = self.root / hp.SOURCE_DIR / (sha + ".json")
        self.broker_path.parent.mkdir(parents=True)
        self.broker_path.write_bytes(raw)
        self.write(hp.MANIFEST, dict(schema_version="equity_household_planning_input_v1", observed_at=PREVIOUS,
                   external_assets_usd="500.00", broker_observation_sha256=sha,
                   broker_observation_path=str(self.broker_path.relative_to(self.root))))
        self.write("05_risk_and_positions/current_account_state.local.json", {"cash_available": "100"})
        (self.root / "05_risk_and_positions/current_positions.local.csv").write_text("ticker,shares_optional\nABC,2\n")
        plan = b"Review one share of ABC when the bid is at least $100."
        sha_plan = hashlib.sha256(plan).hexdigest()
        plan_path = hp.SOURCE_DIR / (sha_plan+".md")
        (self.root / plan_path).write_bytes(plan)
        self.call = dict(ticker="ABC", broker="Chase", side="SELL", shares="1", price_usd="100",
                        price_relation="at_or_above", opens_at=NOW.isoformat(),
                        expires_at=(NOW+timedelta(hours=1)).isoformat(),
                        condition="Verify available shares and current bid.", next_check="Review results.")
        self.plan = dict(schema_version="equity_household_research_input_v1", authored_at=PREVIOUS,
                         broker_observation_sha256=sha, plan_source_path=str(plan_path), plan_source_sha256=sha_plan,
                         calls=[self.call])
        self.write(hp.RESEARCH_MANIFEST, self.plan)

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_combines_net_assets_once_and_retains_separate_shares(self):
        scope = hp.planning_context(self.root, NOW)
        self.assertTrue(scope["chase_ledger_matches"])
        self.assertTrue(scope["moomoo_provisional"])
        self.assertEqual(scope["household_total_usd"], "950.00")
        self.assertEqual(scope["positions"], [dict(ticker="ABC", chase_shares="2", moomoo_shares="1",
                                                    observed_value_usd="301.00", moomoo_value_usd="101.00")])
        hp.validate_archive(scope, NOW)
        self.write("05_risk_and_positions/current_account_state.local.json", {"cash_available": "600"})
        self.assertFalse(hp.planning_context(self.root, NOW)["chase_ledger_matches"])
        self.broker_path.write_bytes(b"{}")
        self.assertEqual(hp.planning_context(self.root, NOW)["reason"], "household_broker_observation_changed")

    def test_normal_brief_preserves_research_conditions_and_expiry(self):
        from email_brief import render_email
        from test_attention_email import AttentionEmailTests
        fixture = AttentionEmailTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.no_entry()
        d = fixture.decision
        d["email_brief_version"] = "equity_direct_action_email_v5"
        scope = d["household_planning"] = hp.planning_context(self.root, NOW)
        d["household_research"] = hp.research_context(self.root, NOW, scope)
        d["evidence_gate"] = {"passed": True}
        d["market_gate"]["passed"] = True
        _, text, doc = render_email(d)
        for body in (text, visible_html_text(doc)):
            for phrase in ("$950.00", "2 Chase / 1 Moomoo", "at or above $100.00",
                           "Approved order size: 0", "10:45 EST", "Verify available shares"):
                self.assertIn(phrase, body)
        d["market_gate"]["passed"] = False
        d["capital_decision"]["household_allocation"] = dict(status="marked", market_session="2026-11-17",
                    planning_total_usd=964, core_before_usd=0, stocks_before_usd=315)
        from daily_common import canonical_sha256
        contract = d["capital_decision"]
        contract["content_sha256"] = canonical_sha256({k:v for k,v in contract.items() if k != "content_sha256"})
        _, text, doc = render_email(d)
        for body in (text, visible_html_text(doc)):
            self.assertIn("market gate failed", body)
            self.assertIn("Approved order size: 0", body)
            self.assertIn("at or above $100.00", body)
            self.assertIn("$964.00 combined", body)
        d["account_conflicts"] = ["inventory differs"]
        self.assertNotIn("at or above $100.00", render_email(d)[1])
        d["account_conflicts"] = []
        d["household_research"] = hp.research_context(self.root, NOW + timedelta(hours=1), scope)
        _, text, doc = render_email(d)
        self.assertEqual(d["household_research"]["status"], "expired")
        self.assertNotIn("at or above $100.00", text + doc)
        self.call["shares"] = "3"
        self.write(hp.RESEARCH_MANIFEST, self.plan)
        self.assertEqual(hp.research_context(self.root, NOW, scope)["reason"], "household_research_insufficient_shares")

    def test_marks_shared_ticker_once_on_one_session_and_preserves_broker_cash(self):
        scope = hp.planning_context(self.root, NOW)
        latest = "2026-11-17"
        quote = dict(ticker="ABC", last_price="105", market_session_date=latest,
                     data_quality_label="ok", data_source="fixture", data_timestamp=PREVIOUS)
        basis = hp.marked_allocation(scope, [quote], latest, 310, 0, 210)
        self.assertEqual((basis["total"], basis["stocks"], basis["moomoo_total"]), (964,315,154))
        self.assertEqual(basis["moomoo_positions"]["ABC"], Decimal("105"))
        self.assertEqual(basis["chase_total"] - 210, 100)
        self.assertEqual(hp.marked_allocation(scope, [], latest, 310, 0, 210)["reason"], "household_moomoo_close_unverified_ABC")
        self.assertEqual(hp.marked_allocation(scope, [quote], latest, 300, 0, 200)["reason"], "household_chase_allocation_marks_conflict")
        quote["market_session_date"] = "2026-11-16"
        self.assertIn("unverified", hp.marked_allocation(scope, [quote], latest, 310, 0, 210)["reason"])

    def test_close_calendar_rejects_overnight_and_shortened_thanksgiving_session(self):
        scope = hp.planning_context(self.root, NOW)
        for start, end in (("2026-11-18T15:00:00-05:00", "2026-11-19T11:00:00-05:00"),
                           ("2026-11-27T12:30:00-05:00", "2026-11-27T13:30:00-05:00")):
            self.call.update(opens_at=start, expires_at=end)
            self.write(hp.RESEARCH_MANIFEST, self.plan)
            self.assertEqual(hp.research_context(self.root, NOW, scope)["reason"], "household_research_regular_session_required")

    def test_both_status_only_windows_revalidate_sources_and_exclude_conditions(self):
        for slot, moment in (("morning", NOW), ("afternoon", NOW.replace(hour=14, minute=45))):
            artifact = delivery.build_failure_brief(self.root, moment, slot, "daily_refresh_not_fully_passed")
            _, text, doc = delivery.render_failure_brief(artifact)
            delivery.validate_failure_brief(artifact, root=self.root, current=moment)
            for body in (text, visible_html_text(doc)):
                self.assertIn(slot, body)
                self.assertIn("$950.00", body)
                self.assertIn("Approved shares for this checkpoint: 0", body)
                self.assertNotIn("at or above $100", body)
        self.broker_path.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, "source_or_content_changed"):
            delivery.validate_failure_brief(artifact, root=self.root, current=moment)
        self.assertEqual(delivery.validate_failure_brief_archive(artifact), artifact)
