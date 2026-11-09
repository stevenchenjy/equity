"""Adverse input and plan-state regressions for independent held-risk visibility."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import held_position_risk as risk


class HeldRiskEdgeCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime.fromisoformat("2026-11-06T10:00:00-05:00")
        self.write_csv(risk.POSITIONS, [{"ticker": "AAA", "shares_optional": "1", "entry_price": "100"}])
        self.write_csv(risk.MARKET, [{"ticker": "AAA", "last_price": "90", "market_session_date": "2026-11-05",
            "data_timestamp": "2026-11-06T08:00:00-05:00", "data_source": "admitted_test_close", "data_quality_label": "ok"}])
        self.write_csv(risk.QUALITY, [{"ticker": "AAA", "usable_for_scoring": "yes"}])
        self.decision = {"market_gate": {"failures": []}, "capital_decision": {"decisions": [
            {"ticker": "AAA", "decision": "HOLD", "blockers": [], "order_draft": None}]}}
        self.context = {"status": "current", "global_blockers": [], "ticker_blockers": {}, "plans": [{
            "ticker": "AAA", "status": "maintained", "role": "long_term_growth", "blockers": [],
            "purpose": {"failure_condition": "Review on evidence of economic impairment."},
            "reason": "A dated existing-purpose review supports continued exposure.",
            "review_at": "2026-11-06T13:45:00-05:00", "valid_until": "2026-11-06T16:00:00-05:00"}]}

    def write_csv(self, relative, rows):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def build(self):
        with patch.object(risk, "load_plan_context", return_value=self.context):
            return risk.build(self.decision, root=self.root, current=self.now)

    def test_legacy_plan_without_purpose_keeps_observation_available(self):
        # Legacy evaluated plans contain the key with null, not an absent key.
        self.context["plans"][0]["purpose"] = None
        report = self.build()
        self.assertEqual(report["holdings"][0]["basis_price_change_pct"], -10)
        self.assertFalse(report["trading_eligibility_granted"])
        self.assertIn("AAA", risk.cards({"held_position_risk": report})[0]["body"])

    def test_real_legacy_ledger_context_with_null_optional_purpose(self):
        from test_investment_plans import ledger, record
        row = record(ticker="AAA", role="long_term_growth")
        row.update(recorded_at="2026-11-06T09:00:00-05:00", effective_at="2026-11-06T09:00:00-05:00",
            account_observed_at="2026-11-06T09:00:00-05:00", review_at="2026-11-06T13:45:00-05:00",
            valid_until="2026-11-06T16:00:00-05:00", action="hold", state="maintained",
            expected_shares=1, proposed_change_shares=0, order_draft=None)
        (self.root / "receipt.json").write_bytes(b"receipt")
        (self.root / "05_risk_and_positions/investment_plans.local.json").write_text(json.dumps(ledger(row)))
        (self.root / risk.ORDERS).write_text(json.dumps({"as_of": "2026-11-06T09:00:00-05:00",
            "complete": True, "orders": [], "cash_confirmed": True,
            "existing_tactical_risk_confirmed": True, "existing_tactical_risk_usd": 0}))
        context = risk.load_plan_context(self.root, [{"ticker": "AAA", "current_shares": "1"}], self.now)
        self.assertEqual(context["plans"][0]["status"], "maintained", context)
        self.assertIsNone(context["plans"][0]["purpose"])
        report = risk.build(self.decision, root=self.root, current=self.now)
        self.assertEqual(report["holdings"][0]["basis_price_change_pct"], -10)
        self.assertEqual(report["holdings"][0]["state"], "REVIEWED_HOLD")

    def test_due_review_is_not_misrepresented_as_expired_plan(self):
        plan = self.context["plans"][0]
        plan.update(status="review_due", review_at="2026-11-06T09:45:00-05:00")
        row = self.build()["holdings"][0]
        self.assertIn(row["state"], {"REVIEW_REQUIRED", "REVIEW_DUE"})
        self.assertEqual(row["plan_state"], "review_due")

    def test_malformed_inventory_is_not_an_empty_reviewed_portfolio(self):
        (self.root / risk.POSITIONS).write_bytes(b"\xff")
        report = self.build()
        self.assertFalse(report["inventory_available"])
        body = risk.cards({"held_position_risk": report})[0]["body"]
        self.assertIn("UNVERIFIED", body)

    def test_fractional_quantity_is_not_verified_whole_share_inventory(self):
        self.write_csv(risk.POSITIONS, [{"ticker": "AAA", "shares_optional": "1.5", "entry_price": "100"}])
        row = self.build()["holdings"][0]
        self.assertEqual(row["state"], "UNVERIFIED")
        self.assertIsNone(row["unrealized_change_usd"])

    def test_colon_in_global_provenance_failure_cannot_admit_mark(self):
        self.decision["market_gate"]["failures"] = ["market_feed_source_hash_mismatch:retained_history"]
        row = self.build()["holdings"][0]
        self.assertIsNone(row["quote"])
        self.assertEqual(row["state"], "UNVERIFIED")

    def test_unrelated_ticker_failure_preserves_verified_position(self):
        self.write_csv(risk.POSITIONS, [{"ticker": "AAA", "shares_optional": "1", "entry_price": "100"},
            {"ticker": "BBB", "shares_optional": "2", "entry_price": "50"}])
        self.decision["market_gate"]["failures"] = ["BBB:market_row_missing"]
        row = self.build()["holdings"][0]
        self.assertEqual(row["quote"]["price"], 90)
        self.assertEqual(row["basis_price_change_pct"], -10)


if __name__ == "__main__":
    unittest.main()
