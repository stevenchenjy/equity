from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import send_phase5r_daily_email as sender
from phase5r_email_brief import render_email
from test_phase5r_email_brief import decision_fixture


def owner_review_fixture():
    decision = decision_fixture()
    decision["owner_requested_research"] = {
        "mode": "explicit_one_off_research",
        "decision_fingerprint": decision["decision_fingerprint"],
        "request_id": "owner-review-20260901-01",
        "reviewed_at": "2026-09-01T19:55:00-04:00",
        "market_as_of": "2026-09-01",
        "sections": [{"title": "PANW 与持仓复核", "body": "先复核实际账户。\n限价和有效期以本次方案为准。",
                      "sources": ["https://stockanalysis.com/stocks/panw/history/",
                                  "https://www.investor.gov/introduction-investing/investing-basics/investment-products/stocks"]}],
    }
    return decision


@contextmanager
def delivery_fixture():
    with tempfile.TemporaryDirectory(prefix="phase5r-owner-review-") as directory, ExitStack() as stack:
        root = Path(directory)
        for key, filename in (("DAILY_DECISION_JSON_PATH", "decision.json"),
                              ("DAILY_BRIEF_TEXT_PATH", "brief.txt"),
                              ("DAILY_BRIEF_HTML_PATH", "brief.html"),
                              ("DAILY_DELIVERY_LEDGER_PATH", "ledger.csv"),
                              ("DAILY_DELIVERY_LOCK_PATH", "delivery.lock")):
            stack.enter_context(patch.object(sender, key, root / filename))
        stack.enter_context(patch.object(sender, "now_et", return_value=datetime(2026, 9, 1, 20, tzinfo=ZoneInfo("America/New_York"))))
        stack.enter_context(patch.object(sender, "cycle_date", return_value="2026-09-01"))
        stack.enter_context(patch.object(sender, "delivery_guard", return_value=(True, "delivery_enabled", {}, {})))
        stack.enter_context(patch.object(sender, "log_daily_run"))
        config = stack.enter_context(patch.object(sender, "load_config", return_value={
            "smtp_username": "sender@example.com", "smtp_app_password": "offline-test-password",
            "sender_name": "Offline Research", "recipient_email": "recipient@example.com",
        }))
        smtp = stack.enter_context(patch.object(sender.smtplib, "SMTP"))
        yield config, smtp


def save_decision(decision):
    _, text, html = render_email(decision)
    sender.DAILY_DECISION_JSON_PATH.write_text(json.dumps(decision), encoding="utf-8")
    sender.DAILY_BRIEF_TEXT_PATH.write_text(text, encoding="utf-8")
    sender.DAILY_BRIEF_HTML_PATH.write_text(html, encoding="utf-8")


class OwnerReviewDeliveryTests(unittest.TestCase):
    def test_concurrent_artifact_replacement_cannot_change_review_or_ledger_hashes(self):
        decision = owner_review_fixture()
        request_id = decision["owner_requested_research"]["request_id"]
        _, expected_text, expected_html = render_email(decision)
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            expected_hashes = {
                key: sender.sha256_file(path) for key, path in (
                    ("decision_sha256", sender.DAILY_DECISION_JSON_PATH),
                    ("brief_text_sha256", sender.DAILY_BRIEF_TEXT_PATH),
                    ("brief_html_sha256", sender.DAILY_BRIEF_HTML_PATH))
            }
            def replace_after_validation():
                sender.DAILY_DECISION_JSON_PATH.write_text('{"replacement": true}', encoding="utf-8")
                sender.DAILY_BRIEF_TEXT_PATH.write_text("replacement text", encoding="utf-8")
                sender.DAILY_BRIEF_HTML_PATH.write_text("<p>replacement HTML</p>", encoding="utf-8")
                return config.return_value
            config.side_effect = replace_after_validation
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 0)
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(message.get_body(preferencelist=("plain",)).get_content(), expected_text)
            self.assertEqual(message.get_body(preferencelist=("html",)).get_content(), expected_html)
            for row in sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH):
                self.assertEqual({key: row[key] for key in expected_hashes}, expected_hashes)
            self.assertNotEqual(sender.sha256_file(sender.DAILY_BRIEF_TEXT_PATH), expected_hashes["brief_text_sha256"])

    def test_holiday_weekend_uses_valid_market_sessions_not_calendar_age(self):
        decision = owner_review_fixture()
        review = decision["owner_requested_research"]
        request_id = review["request_id"]
        for hour in (10, 12):
            current = datetime(2026, 9, 8, hour, tzinfo=ZoneInfo("America/New_York"))
            review["reviewed_at"] = current.isoformat()
            with patch.object(sender, "now_et", return_value=current):
                review["market_as_of"] = "2026-09-04"
                sender.validate_owner_review(decision, request_id)
                for invalid in ("2026-09-03", "2026-09-05", "2026-09-07", "2026-09-08"):
                    review["market_as_of"] = invalid
                    with self.subTest(hour=hour, market_date=invalid):
                        with self.assertRaisesRegex(ValueError, "market_date_out_of_range"):
                            sender.validate_owner_review(decision, request_id)

    def test_suppressed_schedule_can_send_one_explicit_review_without_changing_policy(self):
        decision = owner_review_fixture()
        request_id = decision["owner_requested_research"]["request_id"]
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            before = sender.DAILY_DECISION_JSON_PATH.read_bytes()
            legacy_config = copy.deepcopy(sender.load_active_config())
            legacy_config["notifications"].pop("regular_delivery_mode", None)
            with patch.object(sender, "load_active_config", return_value=legacy_config):
                self.assertEqual(sender.send_once(smtp), 0)
            config.assert_not_called()
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 0)
            self.assertEqual(sender.DAILY_DECISION_JSON_PATH.read_bytes(), before)
            rows = sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)
            self.assertEqual([row["status"] for row in rows], ["owner_review_send_claimed", "owner_review_sent"])
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertIn("[Phase 5R 应请求复核]", str(message["Subject"]))
            self.assertIn("2026-09-01", str(message["Subject"]))
            config.reset_mock()
            # Changed research cannot turn the same user request into a new send.
            decision["owner_requested_research"]["sections"][0]["body"] += "\n补充了内容。"
            save_decision(decision)
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 0)
            config.assert_not_called()
            # A genuinely distinct request can review the same market again.
            second_id = request_id + "-next"
            decision["owner_requested_research"]["request_id"] = second_id
            save_decision(decision)
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=second_id), 0)
            self.assertEqual(smtp.call_count, 2)
            self.assertFalse(json.loads(sender.DAILY_DECISION_JSON_PATH.read_text())["send_recommended"])

    def test_claim_precedes_smtp_and_unknown_blocks_replay_before_config(self):
        decision = owner_review_fixture()
        request_id = decision["owner_requested_research"]["request_id"]
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            def fail_after_claim(*args, **kwargs):
                rows = sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)
                self.assertEqual(rows[-1]["status"], "owner_review_send_claimed")
                raise OSError("uncertain SMTP connection")
            smtp.side_effect = fail_after_claim
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 1)
            self.assertEqual(sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)[-1]["status"], "owner_review_delivery_unknown")
            config.reset_mock()
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 0)
            config.assert_not_called()
            self.assertEqual(smtp.call_count, 1)

    def test_owner_clock_override_preserves_maintenance_and_operational_guards(self):
        decision = owner_review_fixture()
        request_id = decision["owner_requested_research"]["request_id"]
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            for reason in ("maintenance_inhibit_active", "before_operational_from"):
                with patch.object(sender, "delivery_guard", return_value=(False, reason, {}, {})):
                    self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 2)
            config.assert_not_called()
            with patch.object(sender, "delivery_guard", return_value=(False, "before_daily_decision_time", {}, {})):
                self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 0)

    def test_owner_binding_dates_and_policy_fail_before_credentials(self):
        base = owner_review_fixture()
        request_id = base["owner_requested_research"]["request_id"]
        mutations = [
            ("request_id", "other-request"),
            ("reviewed_at", "2026-09-01T19:55:00"),
            ("reviewed_at", "2026-09-01T12:00:00-04:00"),
            ("reviewed_at", "2026-08-31T23:55:00-04:00"),
            ("reviewed_at", "2026-09-01T20:05:00-04:00"),
            ("market_as_of", "2026-09-02"),
            ("market_as_of", "2026-08-28"),
        ]
        with delivery_fixture() as (config, smtp):
            for field, value in mutations:
                decision = copy.deepcopy(base)
                decision["owner_requested_research"][field] = value
                save_decision(decision)
                with self.subTest(field=field, value=value):
                    self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 2)
            decision = copy.deepcopy(base)
            decision["send_recommended"] = True
            save_decision(decision)
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 2)
            save_decision(base)
            sender.DAILY_BRIEF_HTML_PATH.write_text("<p>stale body</p>", encoding="utf-8")
            self.assertEqual(sender.send_once(smtp, owner_review_request_id=request_id), 2)
            config.assert_not_called()
            smtp.assert_not_called()

    def test_current_review_may_bind_prior_cycle_but_not_older_or_legacy(self):
        decision = owner_review_fixture()
        request_id = decision["owner_requested_research"]["request_id"]
        with delivery_fixture():
            decision["cycle_date"] = "2026-08-31"
            decision["generated_at"] = "2026-08-31T12:45:00-04:00"
            save_decision(decision)
            self.assertEqual(sender.validate_decision(owner_review_request_id=request_id), decision)
            decision["cycle_date"] = "2026-08-30"
            save_decision(decision)
            with self.assertRaisesRegex(ValueError, "cycle_out_of_range"):
                sender.validate_decision(owner_review_request_id=request_id)
            decision = owner_review_fixture()
            del decision["email_brief_version"]
            save_decision(decision)
            with self.assertRaisesRegex(ValueError, "requires_bound_brief"):
                sender.validate_decision(owner_review_request_id=request_id)

    def test_request_key_dedupe_is_global_and_ignores_normal_delivery_states(self):
        request_id = "owner-review-request"
        for status in sender.OWNER_REVIEW_DELIVERY_STATUSES:
            rows = [{"cycle_date": "2026-08-01", "status": status,
                     "reason": "claim;" + sender.owner_review_request_key(request_id)}]
            self.assertFalse(sender.owner_review_eligibility(rows, request_id)[0])
        self.assertTrue(sender.owner_review_eligibility([{"status": "sent"}], request_id)[0])

    def test_dated_research_precedes_old_table_and_newlines_remain_visible(self):
        decision = owner_review_fixture()
        subject, text, html = render_email(decision)
        self.assertIn("应请求复核", subject)
        for body in (text, html):
            self.assertLess(body.index("本次请求的个股研究"), body.index("原定时报告参考持仓（旧收盘）"))
            self.assertIn("2026-09-01 19:55", body)
            self.assertIn("2026-08-31", body)
        self.assertIn("white-space:pre-line", html)
        self.assertIn("行情参考来源", html)
        self.assertIn("官方研究来源", html)

    def test_extended_sources_use_exact_https_hosts(self):
        decision = owner_review_fixture()
        sources = decision["owner_requested_research"]["sections"][0]["sources"]
        for host in ("www.rubrik.com", "www.chase.com", "chase.com", "www.jpmorgan.com",
                     "newsroom.servicenow.com", "abc.xyz", "investor.tsmc.com", "pr.tsmc.com", "newsroom.arm.com"):
            sources[:] = [f"https://{host}/official-source"]
            self.assertIn(f'href="https://{host}/official-source"', render_email(decision)[2])
        for url in ("http://stockanalysis.com/stocks/panw/", "https://stockanalysis.com.evil.example/",
                    "https://user@www.finra.org/", "https://www.federalreserve.gov:443/"):
            sources[:] = [url]
            with self.assertRaisesRegex(ValueError, "source_not_allowed"):
                render_email(decision)


if __name__ == "__main__":
    unittest.main()
