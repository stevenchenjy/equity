"""Actual source-bound fixtures for the independent risk notice detector."""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import canonical_sha256, latest_published_market_session
import held_position_risk as held
import risk_review_alerts as alerts
from test_intraday_prices import seed_admitted_history
from test_investment_plans import ledger, record

NOW = datetime.fromisoformat("2026-11-06T14:00:00-05:00")


def write_json(root, relative, value):
    path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def write_csv(root, relative, rows):
    path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def seed_risk_fixture(root: Path, *, price=90, current=NOW) -> dict:
    """One real valid current plan/history/account; no production validator mocks.

    Returns a freshly built artifact. Change the retained fixture files then
    call alerts.build(root,current) for expiry, unavailable or recurrence cases.
    """
    observed = current.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
    session = latest_published_market_session(current).isoformat()
    collected = current.replace(hour=16, minute=30, second=0, microsecond=0).replace(
        year=int(session[:4]), month=int(session[5:7]), day=int(session[8:])).isoformat()
    account = {"account_total_value": 1000, "prior_account_value": 1000, "new_external_cash": 0,
        "cash_available": 100, "cash_reserved": 0, "investment_horizon_years": 1,
        "cash_needed_within_three_years": "no", "core_allocation_target_pct": 30,
        "active_stock_target_pct": 70, "active_stock_hard_cap_pct": 70, "cash_target_pct": 0,
        "single_stock_default_cap_pct": None, "single_stock_hard_cap_pct": None,
        "last_updated": observed, "cash_basis": "ledger_estimate", "core_minimum_pct": 30}
    write_json(root, alerts.ACCOUNT, account)
    authority = {"schema_version": "equity_account_record_authority_v1", "mode": "owner_local_ledger",
        "approved_at": observed, "owner_instruction": "Use local records for conditional manual research.",
        "automatic_execution": False, "broker_observation_claimed": False}
    authority["content_sha256"] = canonical_sha256(authority)
    write_json(root, "05_risk_and_positions/account_record_policy.local.json", authority)
    write_csv(root, held.POSITIONS, [{"ticker": "AAA", "shares_optional": "1", "entry_price": "100"}])
    write_csv(root, held.MARKET, [{"ticker": "AAA", "last_price": str(price), "market_session_date": session,
        "data_timestamp": collected, "data_quality_label": "ok", "data_source": alerts.market_backup.PRIMARY}])
    write_csv(root, held.QUALITY, [{"ticker": "AAA", "usable_for_scoring": "yes"}])
    seed_admitted_history(root)
    write_json(root, held.ORDERS, {"schema_version": "phase5r_open_orders_v1", "as_of": observed,
        "orders": [], "complete": True, "cash_confirmed": True,
        "existing_tactical_risk_confirmed": True, "existing_tactical_risk_usd": 0})
    (root / "receipt.json").write_bytes(b"receipt")
    plan = record(ticker="AAA", role="long_term_growth")
    plan.update(recorded_at=observed, effective_at=observed,
        account_observed_at=observed, review_at=current.replace(hour=15, minute=30, second=0, microsecond=0).isoformat(),
        valid_until=current.replace(hour=15, minute=0, second=0, microsecond=0).isoformat(), action="hold", state="maintained",
        expected_shares=1, proposed_change_shares=0, order_draft=None, time_exit_at=None,
        strategy_horizon="long_term_growth")
    plan["purpose"] = {key: "Existing current sourced company review."
        for key in ("strategy", "holding_period_justification", "entry_validity", "failure_condition", "exit_rule")}
    plan["purpose"]["sources"] = plan["sources"]
    plan["reviewed_allocation"] = {key: "Existing source-bound allocation review."
        for key in ("rationale", "downside_case", "portfolio_overlap", "alternatives")}
    plan["reviewed_allocation"].update(target_position_pct=20, maximum_entry_price=100,
        invalidation_price=95, reassessment_price=120, reviewed_at=plan["recorded_at"], sources=plan["sources"])
    write_json(root, alerts.PLAN, ledger(plan))
    return alerts.build(root, current)


class RiskReviewAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.first = seed_risk_fixture(self.root)

    def build(self, current=NOW):
        return alerts.build(self.root, current)

    def change_price(self, price):
        rows = held._csv(self.root, held.MARKET); rows[0]["last_price"] = str(price)
        write_csv(self.root, held.MARKET, rows); seed_admitted_history(self.root)

    def test_real_current_plan_crossing_is_source_bound_review_only(self):
        alerts.validate_current(self.first, self.root, NOW)
        active = [x for x in self.first["conditions"] if x["active"]]
        self.assertEqual([(x["trigger"], x["kind"]) for x in active], [(alerts.CROSSED, "company_invalidation")])
        self.assertEqual(self.first["risk_rows"][0]["basis_price_change_pct"], -10)
        self.assertEqual(active[0]["observation_at"], "2026-11-05T16:00:00-05:00")
        self.assertFalse(self.first["email_authorized"])
        self.assertFalse(self.first["automatic_action_allowed"])
        self.assertIn("receipt.json", self.first["source_bindings"])
        self.assertTrue(any("responses/" in x for x in self.first["source_bindings"]))
        self.assertNotIn("order_draft", json.dumps(self.first))

    def test_clock_recomputes_expiry_without_any_new_canonical_decision(self):
        later = NOW + timedelta(hours=1)
        expired = self.build(later)
        active = [x for x in expired["conditions"] if x["active"]]
        self.assertEqual([x["trigger"] for x in active], [alerts.UNAVAILABLE])
        self.assertEqual(expired["risk_rows"][0]["plan_state"], "expired_pending_verification")
        self.assertEqual(expired["risk_rows"][0]["conditions"], [])
        self.assertNotIn('"reference": 95', json.dumps(expired))
        with self.assertRaisesRegex(ValueError, "current_projection_changed"):
            alerts.validate_current(self.first, self.root, later)

    def test_later_send_clock_accepts_same_verified_state_without_freezing_time(self):
        alerts.validate_current(self.first, self.root, NOW + timedelta(seconds=1, microseconds=73))
        expired_at = NOW + timedelta(hours=1)
        expired = self.build(expired_at)
        alerts.validate_current(expired, self.root, expired_at + timedelta(seconds=1, microseconds=73))

    def test_inter_build_source_change_cannot_pass_on_unchanged_derived_facts(self):
        original = alerts.build
        calls = 0
        def build_then_change(root, current):
            nonlocal calls
            value = original(root, current)
            calls += 1
            if calls == 1:
                # Same parsed account/holding facts, different exact bytes after
                # recorded-time recomposition but before the current check.
                with (root / alerts.ACCOUNT).open("a") as handle:
                    handle.write("\n")
            return value
        with patch.object(alerts, "build", side_effect=build_then_change), self.assertRaisesRegex(ValueError, "current_projection_changed"):
            alerts.validate_current(self.first, self.root, NOW + timedelta(seconds=1))

    def test_ordinary_price_clock_and_basis_changes_do_not_create_new_episode(self):
        key = alerts.episode_keys(self.first)
        self.change_price(89)
        write_csv(self.root, held.POSITIONS, [{"ticker": "AAA", "shares_optional": "1", "entry_price": "101"}])
        changed = self.build(NOW + timedelta(minutes=1))
        self.assertEqual(alerts.episode_keys(changed), key)
        self.assertNotEqual(changed["content_sha256"], self.first["content_sha256"])
        with self.assertRaisesRegex(ValueError, "recomposition_mismatch"):
            alerts.validate_current(self.first, self.root, NOW)

    def test_recollecting_same_close_does_not_freshen_condition_observation(self):
        rows = held._csv(self.root, held.MARKET)
        rows[0]["data_timestamp"] = NOW.isoformat()
        write_csv(self.root, held.MARKET, rows); seed_admitted_history(self.root)
        later = self.build()
        self.assertEqual([c["observation_at"] for c in later["conditions"]],
                         [c["observation_at"] for c in self.first["conditions"]])

    def test_explicit_verified_recovery_then_same_condition_recross(self):
        key = alerts.episode_keys(self.first)[0]
        self.change_price(100)
        recovery = self.build()
        self.assertNotIn(key, alerts.episode_keys(recovery))
        self.assertIn(key, alerts.recovered_episode_keys(recovery))
        self.change_price(90)
        self.assertIn(key, alerts.episode_keys(self.build()))

    def test_absence_bad_quote_and_missing_plan_never_recover_crossing(self):
        key = alerts.episode_keys(self.first)[0]
        (self.root / held.QUALITY).unlink()
        unavailable = self.build()
        self.assertNotIn(key, alerts.recovered_episode_keys(unavailable))
        self.assertIsNone(unavailable["risk_rows"][0]["quote"])
        self.assertEqual([c["trigger"] for c in unavailable["conditions"] if c["active"]], [alerts.UNAVAILABLE])
        (self.root / alerts.PLAN).unlink()
        self.assertNotIn(key, alerts.recovered_episode_keys(self.build()))

    def test_corrupt_inventory_cannot_invent_owned_exposure(self):
        for qty in ("-1", "NaN", "1.5", "", "true"):
            with self.subTest(qty=qty):
                write_csv(self.root, held.POSITIONS, [{"ticker": "AAA", "shares_optional": qty, "entry_price": "100"}])
                with self.assertRaisesRegex(ValueError, "inventory_invalid"):
                    self.build()
        (self.root / held.POSITIONS).write_bytes(b"\xff")
        with self.assertRaises(ValueError): self.build()

    def test_partial_held_scope_preserves_independently_bound_quote(self):
        write_csv(self.root, held.POSITIONS, [{"ticker": "AAA", "shares_optional": "1", "entry_price": "100"},
            {"ticker": "BBB", "shares_optional": "2", "entry_price": "50"}])
        result = self.build()
        self.assertEqual([row["ticker"] for row in result["risk_rows"]], ["AAA", "BBB"])
        self.assertEqual(result["risk_rows"][0]["quote"]["price"], 90)
        self.assertIsNone(result["risk_rows"][1]["quote"])
        self.assertEqual(len(alerts.episode_keys(result)), 2)

    def test_market_lineage_tampering_removes_all_invalid_prices(self):
        pointer = json.loads((self.root / alerts.market_backup.CURRENT).read_text())
        history = self.root / alerts.market_backup.REL / pointer["history_path"]
        history.write_text(history.read_text() + " ")
        result = self.build()
        self.assertIsNone(result["risk_rows"][0]["quote"])
        self.assertIsNone(result["risk_rows"][0]["basis_price_change_pct"])
        self.assertEqual([c["trigger"] for c in result["conditions"] if c["active"]], [alerts.UNAVAILABLE])

    def test_changed_source_cannot_keep_approved_condition(self):
        (self.root / "receipt.json").write_bytes(b"changed")
        result = self.build()
        self.assertTrue(alerts.episode_keys(result))
        self.assertFalse(any(c["trigger"] == alerts.CROSSED for c in result["conditions"]))

    def test_unavailable_episode_stable_across_reason_and_deadline_churn(self):
        first = self.build(NOW + timedelta(hours=1))
        (self.root / held.QUALITY).unlink()
        second = self.build(NOW + timedelta(hours=2))
        self.assertEqual(alerts.episode_keys(first), alerts.episode_keys(second))

    def test_optional_intraday_absence_or_unavailable_does_not_create_alert(self):
        self.change_price(100)
        self.assertEqual(alerts.episode_keys(self.build()), [])
        write_json(self.root, alerts.INTRADAY, {"status": "expired", "failure": "routine overnight absence"})
        self.assertEqual(alerts.episode_keys(self.build()), [])
        write_json(self.root, alerts.INTRADAY, {"assessment": {"source_bindings": None}})
        self.assertEqual(alerts.episode_keys(self.build()), [])

    def test_current_stop_must_reach_its_existing_start_and_never_survive_expiry(self):
        payload = json.loads((self.root / alerts.PLAN).read_text())
        row = payload["records"][0]
        row.update(action="protect_review", proposed_change_shares=1,
            order_draft={"side": "sell", "type": "STOP", "stop_price": 95, "quantity": 1,
                "time_in_force": "DAY", "session_date": NOW.date().isoformat(), "starts_at": "2026-11-06T14:30:00-05:00"})
        row["record_hash"] = canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
        write_json(self.root, alerts.PLAN, payload)
        before = self.build()
        self.assertFalse(any(c["kind"] == "recorded_stop_reference" for c in before["conditions"]))
        current = self.build(NOW + timedelta(minutes=45))
        self.assertTrue(any(c["kind"] == "recorded_stop_reference" and c["active"] for c in current["conditions"]))
        expired = self.build(NOW + timedelta(hours=1))
        self.assertFalse(any(c["trigger"] == alerts.CROSSED for c in expired["conditions"]))

    def test_approved_partial_stop_retains_exact_reference_share_scope(self):
        payload = json.loads((self.root / alerts.PLAN).read_text())
        row = payload["records"][0]
        row.update(action="protect_review", expected_shares=4, proposed_change_shares=1,
            order_draft={"side": "sell", "type": "STOP", "stop_price": 95, "quantity": 1,
                "time_in_force": "DAY", "session_date": NOW.date().isoformat()})
        row["record_hash"] = canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
        write_json(self.root, alerts.PLAN, payload)
        write_csv(self.root, held.POSITIONS, [{"ticker": "AAA", "shares_optional": "4", "entry_price": "100"}])
        value = self.build()
        alerts.validate_current(value, self.root, NOW)
        stop = next(c for c in value["conditions"] if c["kind"] == "recorded_stop_reference")
        self.assertTrue(stop["active"])
        self.assertEqual(stop["recorded_shares"], 4)
        self.assertEqual(stop["reference_shares"], 1)
        self.assertIn("1 of 4 recorded shares", stop["summary"])

    def test_unresolved_expired_episode_stays_identical_across_dates(self):
        first = self.build(NOW + timedelta(hours=1))
        later = self.build(NOW + timedelta(days=3))
        self.assertEqual(alerts.episode_keys(first), alerts.episode_keys(later))

    def test_daily_visible_coverage_has_identical_semantic_keys(self):
        decision = {"market_gate": alerts._market_gate(self.root, NOW)}
        decision["held_position_risk"] = held.build(decision, root=self.root, current=NOW)
        self.assertEqual(alerts.coverage_from_decision(decision), alerts.episode_keys(self.first))
        self.assertEqual(alerts.coverage_state_from_decision(decision)["recovered"], alerts.recovered_episode_keys(self.first))

    def test_concurrent_source_change_fails_entire_artifact(self):
        original = alerts._projection
        def changing(*args):
            (self.root / "receipt.json").write_bytes(b"changed")
            return original(*args)
        with patch.object(alerts, "_projection", side_effect=changing), self.assertRaisesRegex(ValueError, "inputs_changed"):
            self.build()

    def test_future_clock_and_tampered_archive_fail(self):
        with self.assertRaisesRegex(ValueError, "future"):
            alerts.validate_current(self.first, self.root, NOW - timedelta(seconds=1))
        altered = deepcopy(self.first); altered["conditions"][0]["active"] = True
        with self.assertRaisesRegex(ValueError, "archive_invalid"):
            alerts.validate_archive(altered)
        alerts.validate_archive(self.first)  # Historical read needs no mutable sources.

    def test_resealed_archive_cannot_add_order_or_falsify_condition_arithmetic(self):
        for target in ("top", "row", "condition", "arithmetic"):
            altered = deepcopy(self.first)
            if target == "top": altered["order_draft"] = {"shares": 1}
            elif target == "row": altered["risk_rows"][0]["order_draft"] = {"shares": 1}
            elif target == "condition": altered["conditions"][0]["order_draft"] = {"shares": 1}
            else:
                altered["conditions"][0]["observed_price"] = 10000
            altered["content_sha256"] = canonical_sha256({k: v for k, v in altered.items() if k != "content_sha256"})
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "archive_invalid"):
                alerts.validate_archive(altered)

    def test_real_intraday_crossing_has_clock_then_expires_without_optional_missing_event(self):
        from test_intraday_portfolio_risk import IntradayPortfolioRiskTests
        import intraday_assessment as store
        import intraday_portfolio_risk as intraday
        fixture = IntradayPortfolioRiskTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        root, current = fixture.root, fixture.now
        positions = held._csv(root, held.POSITIONS)
        for row in positions: row["entry_price"] = "100"
        write_csv(root, held.POSITIONS, positions)
        quotes = held._csv(root, held.MARKET)
        for row in quotes:
            row.update(data_source=alerts.market_backup.PRIMARY, data_timestamp="2026-10-21T16:30:00-04:00")
        write_csv(root, held.MARKET, quotes)
        write_csv(root, held.QUALITY, [{"ticker": row["ticker"], "usable_for_scoring": "yes"} for row in quotes])
        seed_admitted_history(root)
        payload = json.loads((root / alerts.PLAN).read_text())
        row = payload["records"][1]
        row["strategy_horizon"] = "long_term_growth"
        row["purpose"] = {key: "Existing sourced company case."
            for key in ("strategy", "holding_period_justification", "entry_validity", "failure_condition", "exit_rule")}
        row["purpose"]["sources"] = row["sources"]
        row["reviewed_allocation"] = {key: "Existing sourced allocation judgment."
            for key in ("rationale", "downside_case", "portfolio_overlap", "alternatives")}
        row["reviewed_allocation"].update(target_position_pct=20, maximum_entry_price=100, invalidation_price=95,
            reassessment_price=120, reviewed_at=row["recorded_at"], sources=row["sources"])
        row["record_hash"] = canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
        write_json(root, alerts.PLAN, payload)
        self.assertEqual(alerts.episode_keys(alerts.build(root, current)), [])
        assessment = intraday.assess(root, fixture.snapshot(), current)
        source = store._retain(root, assessment)
        write_json(root, store.CURRENT, {"schema_version": store.SCHEMA, "generated_at": current.isoformat(),
            "status": assessment["status"], "source": source, "assessment": assessment})
        observed = alerts.build(root, current)
        alerts.validate_current(observed, root, current)
        active = [c for c in observed["conditions"] if c["active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["kind"], "company_invalidation")
        self.assertEqual(active[0]["observed_price"], 90)
        self.assertEqual(active[0]["observation_at"], "2026-10-22T11:00:00-04:00")
        self.assertEqual(active[0]["expires_at"], assessment["expires_at"])
        self.assertEqual(observed["risk_rows"][0]["quote"]["price"], 100)
        later = alerts.build(root, current + timedelta(minutes=6))
        self.assertEqual(alerts.episode_keys(later), [])
        # An old pre-crossing close is not a verified recovery from a later live
        # crossing. The same condition stays unknown until a new usable mark.
        self.assertNotIn(active[0]["episode_key"], alerts.recovered_episode_keys(later))
        with self.assertRaisesRegex(ValueError, "current_projection_changed"):
            alerts.validate_current(observed, root, current + timedelta(minutes=6))


if __name__ == "__main__":
    unittest.main()
