from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import create_phase5r_daily_decision_and_brief as composer
import send_phase5r_daily_email as sender
from phase5r_email_brief import EMAIL_BRIEF_VERSION, build_email_view, email_subject, render_email


def decision_fixture() -> dict:
    return {
        "cycle_date": "2026-09-01", "generated_at": "2026-09-01T12:45:00-04:00",
        "email_brief_version": EMAIL_BRIEF_VERSION,
        "headline": "Legacy detailed headline", "decision_code": "hold_no_new_position",
        "decision_fingerprint": "unchanged", "automatic_action_allowed": False,
        "decision_changed": False, "account_conflicts": [], "material_events": [],
        "eligible_action_review_candidates": [], "eligible_new_position_review_candidates": [],
        "pending_stability_candidates": [], "action_stability_distinct_closes": 0,
        "new_candidate_stability_distinct_closes": 0,
        "market_gate": {"passed": True, "expected_market_session": "2026-08-31"},
        "evidence_gate": {"passed": True},
        "fundamental_gate": {"passed": True, "weakening_tickers": []},
        "held_positions": [{
            "ticker": "RBRK", "asset_role": "active_stock", "action": "hold",
            "current_shares": "2.0000", "current_price": "87.18", "current_weight_pct": "7.2527",
            "target_shares": "1", "whole_shares_to_change": "1",
            "valuation_bear_price": "41.61", "valuation_base_price": "64.06", "valuation_bull_price": "86.50",
            "reason": "Dynamic weight 7.2527% exceeds the 6.00% default cap, current price $87.18 is above the $86.50 bull scenario, expected upside is -26.52%, and reward/risk is 0.00; reducing 1 whole share(s) is the minimum default-cap review scenario.",
        }],
        "watch_candidates": [],
        "account": {"account_total_value": "2404.06", "invested_capital": "1086.68", "cash_available": "1317.38", "cash_pct": "54.7981", "cash_reserved": "500.00"},
        "capital_allocation": {"post_review_cash": "1441.35", "proposed_deployment_value": 0},
        "next_scheduled_review": "2026-09-02",
        "notification_policy": {"event_driven": True, "weekly_summary_weekday": "friday", "unchanged_daily_email": False},
        "notification_policy_evaluation": {"is_weekend": False, "weekly_summary_due": False, "prior_decision_present": True, "first_material_baseline": False, "long_term_fundamental_weakening": False, "scheduler_time_gate_applied": False},
        "send_recommended": False, "send_reason": "unchanged_daily_email_suppressed",
        "boundaries": {"broker_connected": False, "broker_account_read": False, "order_code_created": False, "trade_placed": False},
    }


def action_fixture() -> dict:
    decision = decision_fixture()
    decision.update(decision_code="action_review_candidate", eligible_action_review_candidates=["RBRK"])
    decision["held_positions"][0]["action"] = "trim_review"
    return decision


class EmailPresentationTests(unittest.TestCase):
    def test_account_conflict_overrides_even_stale_eligible_trim(self) -> None:
        decision = action_fixture()
        decision["account_conflicts"] = ["pending_execution:TEST"]
        decision["pending_execution_summaries"] = [{"ticker": "RBRK"}]
        subject, text, html = render_email(decision)
        self.assertIn("需核对账户", subject)
        self.assertIn("仍未成交、已成交还是已撤单", text)
        self.assertIn("不是已确认券商余额", text)
        self.assertIn("仅供核对", text)
        for content in (text, html):
            for forbidden in ("减少 1 股", "1441.35", "$1,441.35", "减仓复核", "已通过现行确定性准入条件"):
                self.assertNotIn(forbidden, content)

    def test_failed_data_gate_masks_plans_and_does_not_claim_verified_close(self) -> None:
        decision = action_fixture()
        decision["market_gate"]["passed"] = False
        subject, text, _ = render_email(decision)
        self.assertIn("等待数据恢复", subject)
        self.assertIn("待核验目标收盘", text)
        self.assertNotIn("已核验参考收盘", text)
        self.assertNotIn("减少 1 股", text)

    def test_weakening_is_research_review_not_automatic_trim(self) -> None:
        decision = action_fixture()
        decision["decision_code"] = "fundamental_weakening_review"
        decision["fundamental_gate"]["weakening_tickers"] = ["RBRK"]
        subject, text, _ = render_email(decision)
        self.assertIn("需复核基本面", subject)
        self.assertIn("经营假设复核", text)
        self.assertNotIn("减少 1 股", text)

    def test_eligible_trim_keeps_exact_scenario_reason_and_adjacent_limit(self) -> None:
        subject, text, html = render_email(action_fixture())
        self.assertIn("有方案待复核", subject)
        self.assertIn("减少 1 股，持仓 2 → 1 股。尚未执行", text)
        self.assertIn("高于高情景 $86.50", text)
        self.assertIn("费用及税费可能改变结果", text)
        self.assertIn("不是价格预测或承诺回报", text)
        self.assertIn("收益/风险比 0.00", text)
        self.assertIn("中情景价差 -26.52%", html)

    def test_hard_cap_reason_is_not_a_fabricated_company_thesis(self) -> None:
        decision = action_fixture()
        decision["held_positions"][0]["reason"] = "Dynamic weight 8.2527% exceeds the 8.00% hard cap; reducing 1 whole share(s) is the minimum current-price scenario at or below the cap."
        text = render_email(decision)[1]
        self.assertIn("集中度复核", text)
        self.assertIn("不代表对公司经营的负面判断", text)

    def test_display_rounding_does_not_hide_a_threshold_crossing(self) -> None:
        decision = action_fixture()
        decision["held_positions"][0]["reason"] = "Dynamic weight 8.0001% exceeds the 8.00% hard cap"
        self.assertIn("8.0001% 超过 8.00%", render_email(decision)[1])

    def test_ineligible_add_cannot_be_presented_as_a_complete_plan(self) -> None:
        decision = action_fixture()
        decision["held_positions"][0]["action"] = "add_review"
        decision["action_stability_distinct_closes"] = 1
        view = build_email_view(decision)
        self.assertFalse(view["plans"])
        self.assertEqual(view["label"], "需补齐方案")
        self.assertIn("当前不需要交易确认", " ".join(view["tasks"]))

    def test_hold_is_not_a_confirmation_task_and_does_not_show_raw_fields(self) -> None:
        subject, text, html = render_email(decision_fixture())
        self.assertIn("无交易待办", subject)
        self.assertIn("没有需要你确认的交易方案", text)
        for raw in ("medium_conviction", "watch_only", "$n/a", "no_allocation", "human_confirmation", "月度模型硬上限", "$0.0", "7.2527%"):
            self.assertNotIn(raw, text + html)
        self.assertIn("2 股 · 7.25%", text)

    def test_pending_add_does_not_show_trade_quantity_or_request_approval(self) -> None:
        decision = action_fixture()
        decision["held_positions"][0]["action"] = "add_review"
        decision["pending_stability_candidates"] = ["RBRK"]
        decision["action_stability_distinct_closes"] = 1
        text = render_email(decision)[1]
        self.assertIn("重复刷新不算第二次确认", text)
        self.assertIn("当前不需要交易确认", text)
        self.assertNotIn("增加 1 股", text)

    def test_new_position_requires_two_closes_and_complete_positive_scenario(self) -> None:
        decision = action_fixture()
        decision["eligible_action_review_candidates"] = []
        decision["eligible_new_position_review_candidates"] = ["SPY"]
        decision["watch_candidates"] = [{"ticker": "SPY", "asset_role": "core_allocation", "suggested_whole_shares": "1", "maximum_review_price": "765.11"}]
        for count, qty, price in ((1, "1", "765.11"), (2, "0", "765.11"), (2, "1", "")):
            decision["new_candidate_stability_distinct_closes"] = count
            decision["watch_candidates"][0].update(suggested_whole_shares=qty, maximum_review_price=price)
            self.assertFalse(build_email_view(decision)["plans"])
        decision["new_candidate_stability_distinct_closes"] = 2
        decision["watch_candidates"][0].update(suggested_whole_shares="1", maximum_review_price="765.11")
        text = render_email(decision)[1]
        self.assertIn("复核价格上限 $765.11", text)
        self.assertIn("不是已提交订单", text)
        self.assertIn("宽基 ETF", text)

    def test_missing_valuation_is_not_global_financial_data_failure(self) -> None:
        decision = decision_fixture()
        decision["held_positions"][0]["valuation_base_price"] = ""
        text = render_email(decision)[1]
        self.assertIn("基础财务：通过", text)
        self.assertIn("基础财务校验通过不代表估值完整", text)
        self.assertIn("RBRK 估值证据不足", text)

    def test_etf_omits_company_valuation_and_distinguishes_allocation_gap_from_cash(self) -> None:
        decision = decision_fixture()
        decision["held_positions"][0].update(ticker="SPY", asset_role="core_allocation", valuation_base_price="")
        decision["watch_candidates"] = [{"ticker": "SPY", "gate_blockers": "whole_share_target_gap"}]
        text = render_email(decision)[1]
        self.assertNotIn("SPY 估值证据不足", text)
        self.assertIn("不等于现金买不起", text)

    def test_unknown_numbers_do_not_become_zero_and_utc_is_converted_to_et(self) -> None:
        decision = decision_fixture()
        decision["account"]["cash_available"] = ""
        decision["generated_at"] = "2026-09-01T16:45:00Z"
        text = render_email(decision)[1]
        self.assertIn("现金 待确认", text)
        self.assertNotIn("现金 $0", text)
        self.assertIn("2026-09-01 12:45 美东", text)
        decision["generated_at"] = "2026-09-01T16:45:00"
        self.assertIn("生成：待确认", render_email(decision)[1])

    def test_newly_ingested_document_has_actual_disclosure_date_and_safe_link(self) -> None:
        decision = decision_fixture()
        decision["material_events"] = [{"ticker": "SMCI", "form": "10-K", "filing_date": "2026-08-31", "source_url": "https://www.sec.gov/Archives/edgar/data/1/report.htm"}]
        subject, text, html = render_email(decision)
        self.assertIn("有文件待复核", subject)
        self.assertIn("披露日 2026-08-31", text)
        self.assertIn("披露日不一定是今天", text)
        self.assertIn('href="https://www.sec.gov/Archives/', html)
        for unsafe in ("javascript:alert(1)", "https://www.sec.gov.evil.example/a", "https://user:password@www.sec.gov/a", "https://www.sec.gov/a\nspoof"):
            decision["material_events"][0]["source_url"] = unsafe
            self.assertNotIn('href=', render_email(decision)[2])

    def test_html_escaping_semantic_table_and_shared_view(self) -> None:
        decision = decision_fixture()
        decision["held_positions"][0]["ticker"] = '<script>alert("x")</script>'
        _, text, html = render_email(decision)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('lang="zh-CN"', html)
        self.assertIn('scope="col"', html)
        self.assertIn('scope="row"', html)
        for section in ("需要你处理", "持仓与现金", "证据与限制", "下一步"):
            self.assertIn(section, text)
            self.assertIn(section, html)

    def test_render_is_pure_and_ai_experiment_cannot_change_the_email(self) -> None:
        decision = decision_fixture()
        before = copy.deepcopy(decision)
        expected = render_email(decision)
        self.assertEqual(decision, before)
        decision["shadow_llm"] = {"recommendation": "BUY RBRK", "self_grade": "excellent"}
        self.assertEqual(render_email(decision), expected)
        self.assertIn("AI 实验不参与本邮件的结论或发送资格", expected[1])

    def test_recent_applied_fill_is_separate_from_pending_tasks(self) -> None:
        decision = decision_fixture()
        decision["recent_applied_execution"] = {"ticker": "RBRK", "side": "sell", "shares": "1", "fill_date": "2026-09-01", "fill_price": "92.15", "net_cash_change": "92.15"}
        text = render_email(decision)[1]
        self.assertIn("最近已入账（不是待办）", text)
        self.assertIn("净到账 $92.15", text)
        del decision["recent_applied_execution"]["net_cash_change"]
        self.assertNotIn("净到账", render_email(decision)[1])

    def test_unknown_status_fails_closed_without_inventing_hold(self) -> None:
        decision = action_fixture()
        decision["decision_code"] = "unrecognized"
        view = build_email_view(decision)
        self.assertFalse(view["plans"])
        self.assertIn("不能作为交易依据", view["summary"])


class EmailArtifactBindingTests(unittest.TestCase):
    def test_subject_and_alternative_bodies_share_renderer_without_smtp(self) -> None:
        decision = decision_fixture()
        subject, text, html = render_email(decision)
        with tempfile.TemporaryDirectory(prefix="phase5r-email-mime-") as directory:
            root = Path(directory)
            text_path, html_path = root / "brief.txt", root / "brief.html"
            text_path.write_text(text, encoding="utf-8")
            html_path.write_text(html, encoding="utf-8")
            config = {"sender_name": "Offline Test", "smtp_username": "sender@example.com", "recipient_email": "recipient@example.com", "smtp_app_password": "offline-secret-never-sent"}
            with patch.object(sender, "DAILY_BRIEF_TEXT_PATH", text_path), patch.object(sender, "DAILY_BRIEF_HTML_PATH", html_path), patch.object(sender.smtplib, "SMTP", side_effect=AssertionError("network prohibited")):
                message = sender.build_message(config, decision)
                correction = sender.build_message(config, decision, correction=True)
            self.assertEqual(str(message["Subject"]), subject)
            self.assertEqual(str(correction["Subject"]), email_subject(decision, correction=True))
            self.assertEqual(message.get_body(preferencelist=("plain",)).get_content(), text)
            self.assertEqual(message.get_body(preferencelist=("html",)).get_content(), html)

    def test_sender_rejects_stale_body_before_any_config_or_smtp_access(self) -> None:
        decision = decision_fixture()
        _, text, html = render_email(decision)
        with tempfile.TemporaryDirectory(prefix="phase5r-email-binding-") as directory, ExitStack() as stack:
            root = Path(directory)
            decision_path, text_path, html_path = root / "decision.json", root / "brief.txt", root / "brief.html"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            text_path.write_text(text, encoding="utf-8")
            html_path.write_text(html, encoding="utf-8")
            for key, value in (("DAILY_DECISION_JSON_PATH", decision_path), ("DAILY_BRIEF_TEXT_PATH", text_path), ("DAILY_BRIEF_HTML_PATH", html_path)):
                stack.enter_context(patch.object(sender, key, value))
            stack.enter_context(patch.object(sender, "now_et", return_value=datetime(2026, 9, 1, 13, 30, tzinfo=ZoneInfo("America/New_York"))))
            stack.enter_context(patch.object(sender, "cycle_date", return_value="2026-09-01"))
            stack.enter_context(patch.object(sender, "load_config", side_effect=AssertionError("no credentials")))
            stack.enter_context(patch.object(sender.smtplib, "SMTP", side_effect=AssertionError("no SMTP")))
            self.assertEqual(sender.validate_decision(), decision)
            for stale_path, valid in ((text_path, text), (html_path, html)):
                stale_path.write_text("Old conflicting report", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "daily_brief_decision_mismatch"):
                    sender.validate_decision()
                stale_path.write_text(valid, encoding="utf-8")
            decision["email_brief_version"] = "unknown-future-format"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "daily_brief_version_unsupported"):
                sender.validate_decision()

    def test_applied_receipt_uses_structured_reconciliation_not_historical_notes(self) -> None:
        current = datetime(2026, 9, 5, tzinfo=ZoneInfo("America/New_York"))
        filled = {"execution_id": "fill", "ticker": "RBRK", "order_status": "filled", "canonical_state_applied": "yes", "fill_date": "2026-09-04", "side": "sell", "shares": "1", "fill_price": "92.15", "notes": "Historically not yet applied"}
        reconciliation = {"execution_id": "fill", "reconciliation_status": "applied", "canonical_state_applied": "yes", "cash_before": "1317.38", "selected_cash_after": "1409.53", "cash_reconciliation_difference": "-0.00"}
        with patch.object(composer, "read_csv", side_effect=lambda path: [filled] if path == composer.CONFIRMED_EXECUTION_PATH else [reconciliation]):
            self.assertEqual(composer.recent_applied_execution(current)["net_cash_change"], "92.15")
            reconciliation["cash_before"] = ""
            self.assertNotIn("net_cash_change", composer.recent_applied_execution(current))
            filled["fill_date"] = "2026-08-01"
            self.assertEqual(composer.recent_applied_execution(current), {})


if __name__ == "__main__":
    unittest.main()
