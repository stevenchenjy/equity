from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import canonical_sha256, recommendation_notification_fingerprint
from issuer_news_queue import QUEUE_REL, merge_news_context, read_queue, record_review_states
from thesis_evidence import apply_issuer_news_review, seal_review, stable_news_event, validate_news_reviews
from workflow_integrity import current_news_context, news_meaning, thesis_meaning


class IssuerNewsQueueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = datetime.fromisoformat("2026-09-24T21:02:00+00:00")
        self.later = datetime.fromisoformat("2026-10-02T21:02:00+00:00")
        self.event = {"event_id": "issuer:abc:product", "source_id": "abc-ir", "ticker": "ABC",
            "source_type": "official_issuer_announcement", "title": "ABC launches new product",
            "url": "https://investor.example.com/product", "published_at": "2026-09-24T21:01:00+00:00",
            "source_fresh": True}
        self.news = {"status": "ok", "required_coverage_complete": True, "unconfigured_held_tickers": [],
            "sources": [{"source_id": "abc-ir", "ticker": "ABC", "freshness": "fresh",
                "url": "https://investor.example.com/feed", "response_sha256": "a" * 64,
                "last_success_at": self.now.isoformat()}], "recent_events": [deepcopy(self.event)]}
        self.record = seal_review({"ticker": "ABC", "review_id": "review-abc-1", "reviewed_at": "2026-09-24T21:00:00+00:00"})

    def view(self, news, *, current=None, record=None):
        record = record or self.record
        view = {"status": "reviewed", "review_record": record, "review_record_sha256": record["record_sha256"],
                "validation_errors": [], "reopen_reasons": [], "business_case_status": "provisionally_supported"}
        apply_issuer_news_review(view, ticker="ABC", news=news, current=current or self.now)
        return view

    def aged_feed(self):
        news = deepcopy(self.news)
        news["recent_events"] = []
        news["sources"][0]["last_success_at"] = self.later.isoformat()
        return news

    def acknowledge(self, event=None):
        event = stable_news_event(event or self.event)
        return seal_review({"ticker": "ABC", "review_id": "review-abc-2", "reviewed_at": self.later.isoformat(),
            "reviewed_news_events": [{"event": event, "event_sha256": canonical_sha256(event),
                "assessment": "Headline triaged; product adoption remains an open research question.",
                "review_scope": "issuer_headline_triage"}]})

    def test_pending_survives_week_ageout_without_semantic_churn(self):
        before = merge_news_context(self.news, root=self.root, current=self.now, persist=True)
        before_view = self.view(before)
        record_review_states({"ABC": before_view}, root=self.root, current=self.now)
        payload = (self.root / QUEUE_REL).read_bytes()
        after = merge_news_context(self.aged_feed(), root=self.root, current=self.later)
        after_view = self.view(after, current=self.later)
        self.assertEqual(after_view["status"], "reassess")
        self.assertEqual(after_view["news_review"]["status"], "pending_new_material_news")
        self.assertEqual(news_meaning(before), news_meaning(after))
        self.assertEqual(thesis_meaning({"views": {"ABC": before_view}}), thesis_meaning({"views": {"ABC": after_view}}))
        from test_email_brief import decision_fixture
        def notification(news, view):
            decision = decision_fixture()
            decision["workflow_integrity"] = {"blockers": []}
            decision["long_horizon_research"] = {"views": {"ABC": view}}
            decision["evidence_coverage"] = {"official_news": news}
            return recommendation_notification_fingerprint(decision)
        self.assertEqual(notification(before, before_view), notification(after, after_view))
        self.assertEqual(payload, (self.root / QUEUE_REL).read_bytes())

    def test_feed_failure_and_unrelated_later_review_cannot_clear_known_pending(self):
        news = merge_news_context(self.news, root=self.root, current=self.now, persist=True)
        record_review_states({"ABC": self.view(news)}, root=self.root, current=self.now)
        stale = self.aged_feed()
        stale["status"] = "degraded"
        stale["sources"][0]["freshness"] = "failed"
        later_review = seal_review({"ticker": "ABC", "review_id": "unrelated-2", "reviewed_at": self.later.isoformat()})
        merged = merge_news_context(stale, root=self.root, current=self.later)
        view = self.view(merged, current=self.later, record=later_review)
        self.assertEqual(view["status"], "reassess")
        self.assertEqual(view["business_case_status"], "provisionally_supported")
        self.assertFalse(view["news_review"]["coverage_complete"])
        self.assertEqual(view["news_review"]["pending_events"][0]["reason"], "new_material_news_after_review")

    def test_exact_ack_resolves_after_window_and_remains_resolved(self):
        merge_news_context(self.news, root=self.root, current=self.now, persist=True)
        context = merge_news_context(self.aged_feed(), root=self.root, current=self.later)
        record = self.acknowledge()
        with patch("official_news.read_official_news_status", return_value=self.aged_feed()):
            validate_news_reviews(record, self.root, self.later.isoformat(), admission=True)
        view = self.view(context, current=self.later, record=record)
        self.assertEqual(view["news_review"]["status"], "current")
        record_review_states({"ABC": view}, root=self.root, current=self.later)
        after = merge_news_context(self.aged_feed(), root=self.root, current=self.later)
        self.assertEqual(self.view(after, current=self.later)["news_review"]["status"], "current")
        self.assertEqual(read_queue(self.root)[-1]["review_record_sha256"], record["record_sha256"])

    def test_wrong_hash_does_not_ack_and_changed_content_reopens(self):
        context = merge_news_context(self.news, root=self.root, current=self.now, persist=True)
        wrong = deepcopy(self.event)
        wrong["title"] = "Different event content"
        wrong_record = self.acknowledge(wrong)
        record_review_states({"ABC": self.view(context, current=self.later, record=wrong_record)}, root=self.root, current=self.later)
        self.assertFalse(any(row["kind"] == "review_acknowledged" for row in read_queue(self.root)))
        record = self.acknowledge()
        record_review_states({"ABC": self.view(context, current=self.later, record=record)}, root=self.root, current=self.later)
        revised = deepcopy(self.news)
        revised["recent_events"][0]["title"] = "ABC withdraws new product"
        revised["sources"][0]["last_success_at"] = self.later.isoformat()
        merged = merge_news_context(revised, root=self.root, current=self.later, persist=True)
        view = self.view(merged, current=self.later, record=record)
        self.assertEqual(view["status"], "reassess")
        self.assertEqual(view["news_review"]["pending_events"][0]["reason"], "reviewed_news_content_changed")
        with patch("official_news.read_official_news_status", return_value=revised):
            with self.assertRaisesRegex(ValueError, "content changed"):
                validate_news_reviews(record, self.root, self.later.isoformat(), admission=True)

    def test_repeated_collection_and_view_reads_do_not_append(self):
        merge_news_context(self.news, root=self.root, current=self.now, persist=True)
        path = self.root / QUEUE_REL
        before = path.read_bytes()
        changed_clock = deepcopy(self.news)
        changed_clock["sources"][0]["last_success_at"] = self.later.isoformat()
        changed_clock["recent_events"][0]["last_seen_at"] = self.later.isoformat()
        merge_news_context(changed_clock, root=self.root, current=self.later, persist=True)
        with patch("workflow_integrity.read_official_news_status", return_value=self.aged_feed()):
            current_news_context({}, root=self.root, current=self.later)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(len(read_queue(self.root)), 1)

    def test_readonly_validation_sees_new_event_without_writing(self):
        with patch("workflow_integrity.read_official_news_status", return_value=self.news):
            context = current_news_context({}, root=self.root, current=self.now)
        self.assertEqual(len(context["review_events"]), 1)
        self.assertFalse((self.root / QUEUE_REL).exists())
        self.assertFalse((self.root / QUEUE_REL.with_suffix(".lock")).exists())

    def test_unverified_source_never_enters_queue_and_future_receipt_not_used(self):
        news = deepcopy(self.news)
        news["sources"][0]["response_sha256"] = "unverified"
        result = merge_news_context(news, root=self.root, current=self.now, persist=True)
        self.assertFalse(result["review_events"])
        self.assertFalse((self.root / QUEUE_REL).exists())
        merge_news_context(self.news, root=self.root, current=self.now, persist=True)
        prior = datetime.fromisoformat("2026-09-24T21:01:30+00:00")
        result = merge_news_context({}, root=self.root, current=prior)
        self.assertFalse(result["review_events"])

    def test_corrupt_queue_fails_closed_in_publication_context(self):
        merge_news_context(self.news, root=self.root, current=self.now, persist=True)
        path = self.root / QUEUE_REL
        row = json.loads(path.read_text())
        row["event"]["title"] = "Unrecorded change"
        path.write_text(json.dumps(row) + "\n")
        with patch("workflow_integrity.read_official_news_status", return_value=self.aged_feed()):
            with self.assertRaisesRegex(ValueError, "chain_invalid"):
                current_news_context({}, root=self.root, current=self.later)


if __name__ == "__main__":
    unittest.main()
