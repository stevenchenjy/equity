from __future__ import annotations

import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from email_brief import build_email_view, render_email
from test_email_brief import decision_fixture


def tactical_fixture() -> dict:
    decision = decision_fixture()
    decision.update(cycle_date="2026-09-22", generated_at="2026-09-22T18:00:00-04:00",
                    decision_code="action_review_candidate", eligible_new_position_review_candidates=["NVDA"],
                    new_candidate_stability_distinct_closes=2)
    decision["market_gate"]["expected_market_session"] = "2026-09-22"
    decision["account"]["account_total_value"] = "5865"
    decision["watch_candidates"] = [{"ticker": "NVDA", "suggested_whole_shares": "1", "maximum_review_price": "223",
                                      "current_price": "228.87", "valuation_bear_price": "200",
                                      "valuation_base_price": "250", "valuation_bull_price": "280"}]
    decision["tactical_review"] = {
        "schema_version": "phase5r_tactical_review_v1", "as_of": "2026-09-22T18:00:00-04:00",
        "market_session": "2026-09-22", "next_session": "2026-09-23", "global_gates_passed": True,
        "blockers": [], "research_only": True, "automatic_action_allowed": False,
        "risk_budget": {"account_value": "5865"},
        "open_orders": {"as_of": "2026-09-22T15:17:00-04:00", "complete": True, "orders": [
            {"ticker": "RKLB", "side": "buy", "quantity": 3, "remaining_quantity": 3, "limit_price": "70",
             "status": "open", "time_in_force": "DAY", "session_date": "2026-09-22",
             "review_status": "expired_status_unknown"}]},
        "drafts": [{"ticker": "NVDA", "side": "buy", "classification": "real-trade candidate", "eligible": True,
                    "quantity": 1, "entry_price": "223", "stop_price": "217.75", "target_price": "233.50",
                    "reward_to_risk": "2", "session_date": "2026-09-23", "time_in_force": "DAY",
                    "entry_rule": "回踩后重新站上入场位", "invalidation_rule": "跌破原形态",
                    "time_exit_session": "2026-09-25 15:45 ET", "reentry_rule": "重新形成且核验新形态",
                    "price_basis": "S&P 2026-09-22 日线；分析选定的观察位",
                    "price_evidence": {"validated": True, "history_session": "2026-09-22", "snapshot_sha256": "a" * 64},
                    "blockers": []}],
    }
    return decision


class TacticalEmailTests(unittest.TestCase):
    def test_four_rules_and_missing_evidence_no_trade_always_have_body_parity(self) -> None:
        for body in render_email(decision_fixture())[1:]:
            for rule in ("规则 1", "规则 2", "规则 3", "规则 4", "0.5%", "0.25%", "2R", "3–5"):
                self.assertIn(rule, body)
            self.assertIn("短线 NO TRADE：本次新增 0 股", body)
            self.assertIn("不编造价格", body)

    def test_verified_canonical_candidate_has_complete_dated_draft(self) -> None:
        decision = tactical_fixture()
        before = copy.deepcopy(decision)
        for body in render_email(decision)[1:]:
            for value in ("新增 1 股；限价不高于 $223.00；DAY", "$217.75", "$233.50", "2.00R",
                          "2026-09-23", "2026-09-25 15:45 ET", "再次买回", "计划风险：$5.25"):
                self.assertIn(value, body)
        self.assertEqual(decision, before)

    def test_stale_day_order_keeps_observed_status_without_inferred_fill_or_cancel(self) -> None:
        for body in render_email(tactical_fixture())[1:]:
            self.assertIn("订单快照：2026-09-22 15:17 美东", body)
            self.assertIn("当时为未完成", body)
            self.assertIn("最终状态待核对；不能据此认定成交或撤单", body)
            self.assertNotIn("当时显示已成交", body)
            self.assertNotIn("当时显示已撤单", body)

    def test_global_or_canonical_blocks_cannot_be_bypassed_by_tactical_payload(self) -> None:
        mutations = {
            "data": lambda d: d["market_gate"].update(passed=False),
            "cash": lambda d: d["account"].update(cash_basis="owner_assumption"),
            "account": lambda d: d.update(account_conflicts=["unresolved"]),
            "not_eligible": lambda d: d.update(eligible_new_position_review_candidates=[]),
            "oversized": lambda d: d["tactical_review"]["drafts"][0].update(quantity=2),
            "stale_session": lambda d: d["tactical_review"]["drafts"][0].update(session_date="2026-09-21"),
            "incomplete_orders": lambda d: d["tactical_review"]["open_orders"].update(complete=False),
            "tactical_position_cap": lambda d: d["account"].update(account_total_value="3000"),
            "missing_time_exit": lambda d: d["tactical_review"]["drafts"][0].update(time_exit_session="eventually"),
            "inconsistent_risk": lambda d: d["tactical_review"]["drafts"][0].update(reward_to_risk="20"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                decision = tactical_fixture()
                mutate(decision)
                tactical = build_email_view(decision)["tactical_sections"]
                text = str(tactical)
                self.assertIn("短线 NO TRADE：本次新增 0 股", text)
                self.assertNotIn("待人工判断：新增", text)

    def test_missing_or_malformed_price_evidence_never_renders_price_draft(self) -> None:
        for evidence in (None, {}, {"validated": False, "history_session": "2026-09-22", "snapshot_sha256": "a" * 64},
                         {"validated": True, "history_session": "2026-09-21", "snapshot_sha256": "a" * 64}):
            with self.subTest(evidence=evidence):
                decision = tactical_fixture()
                decision["tactical_review"]["drafts"][0]["price_evidence"] = evidence
                text = str(build_email_view(decision)["tactical_sections"])
                self.assertIn("NO TRADE", text)
                self.assertNotIn("$217.75", text)
        decision = tactical_fixture()
        decision["tactical_review"]["drafts"] = [None, "bad", {"ticker": "NVDA", "entry_price": "NaN"}]
        self.assertIn("格式不完整", str(build_email_view(decision)["tactical_sections"]))

    def test_low_reward_to_risk_is_an_observation_not_an_eligible_draft(self) -> None:
        decision = tactical_fixture()
        decision["tactical_review"]["drafts"][0].update(target_price="229", reward_to_risk="1.14", blockers=["reward_to_risk"])
        text = str(build_email_view(decision)["tactical_sections"])
        self.assertIn("仅供观察的价格情景（非委托）", text)
        self.assertIn("1.14R", text)
        self.assertIn("NO TRADE", text)

    def test_hypothetical_shares_stay_separate_and_cannot_hide_another_failed_gate(self) -> None:
        decision = tactical_fixture()
        decision["account"]["cash_basis"] = "ledger_estimate"
        review = decision["tactical_review"]
        review.update(global_gates_passed=False, blockers=["cash_not_confirmed", "existing_tactical_risk_unconfirmed"])
        review["drafts"][0].update(quantity=0, eligible=False, hypothetical_quantity=1,
                                    hypothetical_assumptions=["现金已核对", "既有短线风险已核对"])
        text = str(build_email_view(decision)["tactical_sections"])
        self.assertIn("独立假设情景：1 股", text)
        self.assertIn("实际合格新增仍为 0 股", text)
        review["blockers"].extend(["open_orders_unconfirmed", "event_calendar_unconfirmed"])
        review["open_orders"]["complete"] = False
        self.assertIn("独立假设情景：1 股", str(build_email_view(decision)["tactical_sections"]))
        review["drafts"][0]["blockers"] = ["valuation"]
        self.assertNotIn("独立假设情景：1 股", str(build_email_view(decision)["tactical_sections"]))

    def test_markup_is_escaped_and_cash_label_does_not_invent_ledger_arithmetic(self) -> None:
        decision = tactical_fixture()
        decision["account"]["cash_basis"] = "owner_assumption"
        decision["tactical_review"]["drafts"][0]["ticker"] = '<img src="x">'
        _, text, html = render_email(decision)
        self.assertIn('<img src="x">', text)
        self.assertNotIn('<img src="x">', html)
        self.assertIn("&lt;img", html)
        self.assertIn("用户指定的规划现金假设", text)
        self.assertNotIn("原账本扣除已报告支出", text)

    def test_official_source_allowlist_remains_exact(self) -> None:
        decision = decision_fixture()
        decision["owner_requested_research"] = {
            "mode": "explicit_one_off_research", "decision_fingerprint": decision["decision_fingerprint"],
            "sections": [{"title": "官方来源", "body": "资料复核", "sources": ["https://www.bea.gov/news/schedule"]}],
        }
        self.assertIn('href="https://www.bea.gov/news/schedule"', render_email(decision)[2])
        decision["owner_requested_research"]["sections"][0]["sources"] = ["https://www.bea.gov.evil.example/news"]
        with self.assertRaisesRegex(ValueError, "source_not_allowed"):
            render_email(decision)

    def test_actual_tactical_module_payload_preserves_capped_quantity_in_renderer(self) -> None:
        from tactical_review import build_tactical_review
        from test_tactical_review import fixture
        values = fixture()
        decision = decision_fixture()
        decision.update(values["decision"])
        decision.update(decision_code="action_review_candidate", new_candidate_stability_distinct_closes=2)
        decision["tactical_review"] = build_tactical_review(**values)
        text = str(build_email_view(decision)["tactical_sections"])
        self.assertIn("待人工判断：新增 4 股", text)
        self.assertIn("$102.00", text)
        self.assertIn("股数不能相加或叠加委托", text)


if __name__ == "__main__":
    unittest.main()
