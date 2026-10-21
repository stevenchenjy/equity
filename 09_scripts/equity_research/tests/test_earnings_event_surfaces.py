import copy
import re
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from email_brief import build_email_view, earnings_research_card, render_email
from test_email_brief import decision_fixture


def event_report(status="ready"):
    return {"schema_version": "equity_earnings_event_view_v1", "generated_at": "2026-10-21T09:00:00-04:00",
            "status": status, "coverage": {"scope": "US listed common-stock exchange calendar", "horizon_start": "2026-10-21",
            "horizon_end": "2026-11-04", "days_requested": 15, "days_verified": 15, "failed_dates": []},
            "events": [{"event_id": "low-momentum-event", "ticker": "LOWM", "company_name": "Low momentum issuer",
            "event_date": "2026-10-22", "session": "after_close", "research_deadline_at": "2026-10-22T09:30:00-04:00",
            "timing": "pre_event", "status": "awaiting_research", "date_confidence": "exchange_calendar_estimate",
            "blockers": ["Company-specific expectations and downside case are incomplete"],
            "next_step": "Complete expectations, valuation and the no-entry countercase before the announcement."}],
            "capital_authority": False, "automatic_action_allowed": False}


class EarningsEventPresentationTests(unittest.TestCase):
    def decision(self):
        value = decision_fixture()
        value["plan_continuity"] = {"plans": [], "block_new_capital": False}
        value["workflow_integrity"] = {"global_blockers": []}
        value["earnings_events"] = event_report()
        return value

    def test_independent_pre_event_work_reaches_actual_text_html_separate_from_actions(self):
        decision = self.decision()
        before = copy.deepcopy(decision)
        _, plain, document = render_email(decision)
        for body in (plain, document):
            for required in ("Upcoming earnings research", "Independent of momentum rank", "LOWM", "Awaiting research",
                             "Research deadline: 2026-10-22T09:30:00-04:00", "exchange estimate; issuer confirmation required",
                             "expectations, valuation and the no-entry countercase", "15/15 dates verified"):
                self.assertIn(required, body)
            self.assertLess(body.index("What to do now"), body.index("Upcoming earnings research"))
            self.assertNotIn("LOWM: buy", body)
        self.assertEqual(decision, before)

    def test_reviewed_rejection_keeps_exact_dependency_and_partial_coverage(self):
        decision = self.decision()
        decision["earnings_events"]["status"] = "partial"
        decision["earnings_events"]["coverage"].update(days_verified=14, failed_dates=["2026-10-24"])
        row = decision["earnings_events"]["events"][0]
        row.update(status="reviewed_without_entry", blockers=["Current valuation does not cover event downside"],
                   next_step="Reject pre-event entry; revisit after the issuer releases its results.")
        for body in render_email(decision)[1:]:
            for required in ("Reviewed without entry", "Reject pre-event entry", "Current valuation does not cover event downside",
                             "14/15 dates verified", "Unverified calendar dates:", "2026-10-24"):
                self.assertIn(required, body)
            self.assertNotIn("Eligible conditional plan", body)

    def test_stale_or_unsupported_calendar_status_never_looks_like_an_entry(self):
        for report_status, capital in (("ready", {}), ("stale", {"decisions": [{"ticker": "LOWM", "decision": "ACTIONABLE_BUY", "shares": 1,
                                                                               "order_draft": {"side": "buy"}}]})):
            decision = self.decision()
            decision["earnings_events"]["status"] = report_status
            decision["earnings_events"]["events"][0]["status"] = "eligible_conditional_plan"
            decision["capital_decision"] = capital
            card = earnings_research_card(decision)
            self.assertNotIn("Eligible conditional plan", card["body"])
            self.assertIn("Research in progress", card["body"])

    def test_bounded_email_keeps_full_count_and_does_not_conflate_detection_with_review(self):
        decision = self.decision()
        decision["earnings_events"]["events"] = [{**decision["earnings_events"]["events"][0], "ticker": f"EV{i}",
            "research_deadline_at": f"2026-10-22T09:{i:02d}:00-04:00"} for i in range(12)]
        card = earnings_research_card(decision)
        self.assertIn("Showing 6 of 12 upcoming events", card["body"])
        self.assertIn("EV5:", card["body"])
        self.assertNotIn("EV6:", card["body"])
        self.assertNotIn("companies reviewed", card["body"])

    def test_elapsed_events_do_not_consume_upcoming_slots_and_deadlines_determine_order(self):
        decision = self.decision()
        sample = decision["earnings_events"]["events"][0]
        elapsed = [{**sample, "event_id": f"old-{i}", "ticker": f"OLD{i}", "event_date": "2026-10-20",
                    "timing": "post_event", "status": "elapsed_unreviewed"} for i in range(150)]
        upcoming = [{**sample, "event_id": f"new-{i}", "ticker": f"NEW{i}",
                     "research_deadline_at": f"2026-10-22T09:{i:02d}:00-04:00"} for i in reversed(range(10))]
        decision["earnings_events"]["events"] = elapsed + upcoming
        card = earnings_research_card(decision)["body"]
        self.assertIn("Upcoming research events: 10", card)
        self.assertIn("retained events: 150", card)
        self.assertIn("NEW5:", card)
        self.assertNotIn("NEW6:", card)
        self.assertNotIn("OLD0:", card)
        self.assertLess(card.index("NEW0:"), card.index("NEW1:"))

    def test_completed_event_outcomes_beyond_one_hundred_pending_leads_reach_email_without_changing_actions(self):
        decision = self.decision()
        sample = decision["earnings_events"]["events"][0]
        pending = [{**sample, "event_id": f"pending-{i}", "ticker": f"PENDING{i}"} for i in range(150)]
        decision["earnings_events"]["events"] = pending
        original_actions = render_email(decision)[1].split("Upcoming earnings research")[0]
        reviewed = [{**sample, "event_id": ticker, "ticker": ticker, "status": "reviewed_without_entry",
                     "event_date": "2026-10-23", "research_deadline_at": "2026-10-23T09:30:00-04:00",
                     "next_step": "Reviewed event case: reject pre-event entry because valuation does not cover downside."}
                    for ticker in ("LRCX", "META")]
        decision["earnings_events"]["events"] = pending + reviewed
        before = copy.deepcopy(decision)
        _, plain, document = render_email(decision)
        for body in (plain, document):
            self.assertIn("LRCX:", body)
            self.assertIn("META:", body)
            self.assertIn("Reviewed without entry", body)
            self.assertIn("reject pre-event entry", body)
            self.assertIn("reviewed outcomes first, then research deadline", body)
        self.assertLess(plain.index("LRCX:"), plain.index("PENDING0:"))
        self.assertEqual(plain.split("Upcoming earnings research")[0], original_actions)
        self.assertEqual(decision, before)

    def test_invalid_schema_cannot_render_as_verified_empty_coverage(self):
        decision = self.decision()
        decision["earnings_events"]["schema_version"] = "unknown"
        self.assertIsNone(earnings_research_card(decision))

    def test_reviewed_event_keeps_official_review_source_links_without_executing_remote_content(self):
        decision = self.decision()
        row = decision["earnings_events"]["events"][0]
        row.update(status="reviewed_without_entry", next_step="Valuation remains incomplete; do not enter.",
                   event_review={"sources": [{"source_url": "https://investor.atmeta.com/investor-news/"},
                                              {"source_url": "javascript:alert(1)"}]})
        _, plain, document = render_email(decision)
        self.assertIn("https://investor.atmeta.com/investor-news/", plain)
        self.assertIn('href="https://investor.atmeta.com/investor-news/"', document)
        self.assertIn("Valuation remains incomplete; do not enter.", plain)
        self.assertNotIn("javascript:", document)

    def test_earnings_precedes_large_background_without_changing_action_cards(self):
        decision = self.decision()
        cards = [{"title": "Unchanged action card", "body": "No new order. Existing conditions remain unchanged.",
                  "sources": [], "kind": "status", "group": "action"},
                 {"title": "Large retained background", "body": "Retained background " + "x" * 125_000,
                  "sources": [], "group": "background"}]
        baseline = copy.deepcopy(decision)
        baseline.pop("earnings_events")
        before = copy.deepcopy(decision)
        with patch("scheduled_email.cards", side_effect=lambda *_: copy.deepcopy(cards)):
            _, original_text, original_html = render_email(baseline)
            _, plain, document = render_email(decision)
        for body in (plain, document):
            self.assertGreater(len(body.encode()), 120_000)
            self.assertLess(body.index("Unchanged action card"), body.index("Upcoming earnings research"))
            self.assertLess(body.index("Upcoming earnings research"), body.index("Large retained background"))
            self.assertLess(len(body[:body.index("Upcoming earnings research")].encode()), 20_000)
        action_pattern = r'<div data-email-group="action".*?</div>'
        self.assertEqual(re.findall(action_pattern, original_html, re.S), re.findall(action_pattern, document, re.S))
        self.assertEqual(plain.split("Supporting information")[0], original_text.split("Supporting information")[0])
        self.assertEqual(decision, before)

    def test_legacy_compact_earnings_stays_after_order_section_before_large_discovery_background(self):
        decision = self.decision()
        decision.pop("workflow_integrity")
        view = build_email_view(decision)
        view["discovery"]["lines"] = ["Large discovery background " + "x" * 125_000]
        with patch("email_brief.build_email_view", return_value=view):
            _, plain, document = render_email(decision)
        for body in (plain, document):
            self.assertLess(body.index("订单与可复核方案"), body.index("Upcoming earnings research"))
            self.assertLess(body.index("Upcoming earnings research"), body.index("Large discovery background"))


if __name__ == "__main__":
    unittest.main()
