"""Local planning authority must reach both approved index-core entry paths."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from account_authority import POLICY_REL, SCHEMA
from core_entry import eligible_core_tranche
from daily_common import canonical_sha256


class IndexCoreLocalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch("account_common.is_core_allocation_ticker", side_effect=lambda ticker: ticker in {"SPY", "QQQM"}).start()

    def policy(self, **changes):
        value = {
            "schema_version": SCHEMA, "mode": "owner_local_ledger",
            "approved_at": "2026-09-22T09:00:00-04:00",
            "owner_instruction": "Use local records for conditional manual plans.",
            "automatic_execution": False, "broker_observation_claimed": False,
        }
        value.update(changes)
        value["content_sha256"] = canonical_sha256(value)
        path = self.root / POLICY_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def fixture(self, ticker):
        decision = {
            "generated_at": "2026-09-23T09:20:00-04:00", "cycle_date": "2026-09-23",
            "decision_code": "action_review_candidate",
            "eligible_new_position_review_candidates": [ticker],
            "account": {"cash_basis": "ledger_estimate", "cash_available": "3000",
                        "cash_confirmed": False, "broker_buying_power_verified": False},
            "held_positions": [{"ticker": ticker, "current_shares": 1}],
            "plan_continuity": {"plans": [{"ticker": ticker, "role": "broad_core",
                "status": "maintained", "current_shares": 1,
                "review_at": "2026-09-23T10:30:00-04:00"}]},
            "market_gate": {"passed": True, "bar_state": "complete_close"},
            "evidence_gate": {"passed": True}, "fundamental_gate": {"passed": True},
            "known_orders": {"complete": False, "cash_confirmed": False, "orders": []},
        }
        row = {"ticker": ticker, "action": "core_allocation_tranche_review",
               "human_confirmation_required": "yes",
               "valuation_applicability": "not_applicable_broad_market_etf",
               "suggested_whole_shares": 1, "maximum_review_price": "100",
               "stability_distinct_closes": 2, "required_distinct_closes": 2}
        return decision, row

    def test_approved_local_ledger_allows_both_core_funds_without_inventing_broker_facts(self):
        self.policy()
        for ticker in ("SPY", "QQQM"):
            with self.subTest(ticker=ticker):
                decision, row = self.fixture(ticker)
                original = copy.deepcopy((decision, row))
                result = eligible_core_tranche(decision, row, root=self.root)
                self.assertEqual(result, {"ticker": ticker, "quantity": 1, "max_price": "100",
                    "session_date": "2026-09-23", "review_at": "2026-09-23T10:30:00-04:00",
                    "held_before": 1})
                self.assertEqual((decision, row), original)
                self.assertFalse(decision["account"]["cash_confirmed"])
                self.assertFalse(decision["known_orders"]["complete"])

    def test_local_ledger_label_or_in_memory_flag_without_private_approval_is_insufficient(self):
        for ticker in ("SPY", "QQQM"):
            with self.subTest(ticker=ticker):
                decision, row = self.fixture(ticker)
                decision["account_record_authority"] = {"local_planning_enabled": True}
                self.assertIsNone(eligible_core_tranche(decision, row, root=self.root))

    def test_invalid_private_approval_does_not_admit_core_entry(self):
        self.policy(broker_observation_claimed=True)
        for ticker in ("SPY", "QQQM"):
            decision, row = self.fixture(ticker)
            self.assertIsNone(eligible_core_tranche(decision, row, root=self.root))

    def test_real_account_contradiction_remains_effective_with_local_authority(self):
        self.policy()
        for ticker in ("SPY", "QQQM"):
            decision, row = self.fixture(ticker)
            decision["account_conflicts"] = ["known_order_exceeds_available_shares"]
            self.assertIsNone(eligible_core_tranche(decision, row, root=self.root))


if __name__ == "__main__":
    unittest.main()
