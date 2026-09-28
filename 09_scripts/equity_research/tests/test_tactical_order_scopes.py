from __future__ import annotations

import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from test_tactical_review import fixture
from tactical_review import build_tactical_review


def historical_sell():
    return {"order_id": "historical-one", "ticker": "OLD", "side": "sell", "quantity": 1,
            "remaining_quantity": 1, "limit_price": 50, "status": "pending", "time_in_force": "DAY",
            "session_date": "2026-09-21", "record_scope": "unresolved_historical_reservation",
            "current_status_verified": False, "last_verified_at": "2026-09-21T12:00:00-04:00",
            "current_inventory_presence": "not_shown_in_current_no_orders_page"}


def current_no_orders():
    values = fixture()
    values["decision"]["held_positions"] = [{"ticker": "OLD", "current_shares": 1}]
    orders = values["open_orders"]
    orders["orders"] = [historical_sell()]
    orders["current_inventory_observation"] = {"as_of": values["current"].isoformat(),
        "complete": True, "orders_shown": [], "statement": "No orders shown.",
        "source": {"path": "observation.json", "sha256": "b" * 64}}
    orders["broker_balance_observation"] = {"amount_usd": 100, "settled_cash_verified": False,
        "planning_cash_reconciled": False, "source": {"path": "observation.json", "sha256": "b" * 64}}
    return values


class TacticalOrderScopeTests(unittest.TestCase):
    def test_observed_current_order_must_match_every_commitment_and_validity_field(self):
        for field, replacement in (("quantity", 2), ("limit_price", 250), ("stop_price", 45),
            ("order_type", "market"), ("time_in_force", "GTD"), ("session_date", "2026-09-24"),
            ("expiration_date", "2026-12-31")):
            with self.subTest(field=field):
                values = current_no_orders(); orders = values["open_orders"]
                row = {"order_id": "current-buy", "ticker": "BUYER", "side": "buy", "quantity": 1,
                    "remaining_quantity": 1, "limit_price": 100, "status": "pending", "order_type": "limit",
                    "time_in_force": "DAY", "session_date": "2026-09-23", "current_status_verified": True}
                orders["orders"] = [row]
                observed = copy.deepcopy(row); observed[field] = replacement
                orders["current_inventory_observation"]["orders_shown"] = [observed]
                result = build_tactical_review(**values)
                self.assertFalse(result["open_orders"]["complete"])
                self.assertIn("current_inventory_order_facts_conflict", result["open_orders"]["global_blockers"])

    def test_null_or_nonstring_order_identity_cannot_become_a_verified_string(self):
        for identity in (None, False, 123, {}, [], " "):
            with self.subTest(identity=identity):
                values = current_no_orders(); orders = values["open_orders"]
                row = orders["orders"][0]
                row.pop("record_scope"); row.update(order_id=identity, session_date="2026-09-23", current_status_verified=True)
                orders["current_inventory_observation"]["orders_shown"] = [copy.deepcopy(row)]
                result = build_tactical_review(**values)
                self.assertFalse(result["open_orders"]["complete"])
                self.assertIn("open_orders_unconfirmed", result["blockers"])

    def test_observed_empty_inventory_keeps_old_sell_local_and_preserves_unknowns(self):
        values = current_no_orders()
        before = copy.deepcopy(values)
        result = build_tactical_review(**values)
        orders = result["open_orders"]
        self.assertTrue(orders["complete"])
        self.assertNotIn("open_orders_unconfirmed", result["blockers"])
        self.assertEqual(orders["active_tickers"], ["OLD"])
        self.assertIn("sell_order_terminal_status_unverified", orders["ticker_blockers"]["OLD"])
        self.assertEqual(orders["orders"][0]["review_status"], "expired_pending_verification")
        self.assertFalse(orders["orders"][0]["current_status_verified"])
        self.assertTrue(next(x for x in result["drafts"] if x["ticker"] == "TEST")["eligible"])
        self.assertEqual(orders["current_inventory_observation"], values["open_orders"]["current_inventory_observation"])
        self.assertEqual(orders["broker_balance_observation"], values["open_orders"]["broker_balance_observation"])
        orders["current_inventory_observation"]["complete"] = False
        self.assertEqual(values, before)

    def test_unknown_inventory_buy_commitments_and_contradictions_remain_global(self):
        for mutation in ("stale", "incomplete", "future_observation", "stale_observation", "buy", "duplicate",
                         "overreserved", "negative", "terminal_remaining", "current_order_conflicts_empty",
                         "observation_wrong_type", "malformed_observed_row", "terminal_invalid_side",
                         "observed_order_conflict"):
            with self.subTest(mutation=mutation):
                values = current_no_orders(); orders = values["open_orders"]; row = orders["orders"][0]
                if mutation == "stale": orders["as_of"] = "2026-09-21T12:00:00-04:00"
                elif mutation == "incomplete": orders["complete"] = False
                elif mutation == "future_observation": orders["current_inventory_observation"]["as_of"] = "2026-09-23T12:00:00-04:00"
                elif mutation == "stale_observation": orders["current_inventory_observation"]["as_of"] = "2026-09-21T12:00:00-04:00"
                elif mutation == "buy": row["side"] = "buy"
                elif mutation == "duplicate": orders["orders"].append(copy.deepcopy(row))
                elif mutation == "overreserved": row.update(quantity=2, remaining_quantity=2)
                elif mutation == "negative": row["remaining_quantity"] = -1
                elif mutation == "terminal_remaining": row["status"] = "filled"
                elif mutation == "current_order_conflicts_empty": row.pop("record_scope"); row["current_status_verified"] = True
                elif mutation == "observation_wrong_type": orders["current_inventory_observation"] = []
                elif mutation == "malformed_observed_row": orders["current_inventory_observation"]["orders_shown"] = ["unknown"]
                elif mutation == "terminal_invalid_side": row.update(status="filled", remaining_quantity=0, side={})
                elif mutation == "observed_order_conflict":
                    row.pop("record_scope"); row.update(current_status_verified=True, session_date="2026-09-23")
                    observed = copy.deepcopy(row); observed["side"] = "buy"
                    orders["current_inventory_observation"]["orders_shown"] = [observed]
                result = build_tactical_review(**values)
                self.assertFalse(result["open_orders"]["complete"])
                self.assertIn("open_orders_unconfirmed", result["blockers"])
                self.assertFalse(next(x for x in result["drafts"] if x["ticker"] == "TEST")["eligible"])


if __name__ == "__main__":
    unittest.main()
