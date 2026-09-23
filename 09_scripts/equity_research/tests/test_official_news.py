from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from _support import SCRIPT_DIR  # noqa: F401
from official_news import (
    MANIFEST_PATH, NewsError, OfficialRedirect, canonical_url, fetch_feed,
    load_manifest, parse_feed, read_official_news_status, refresh_news,
)


NOW = datetime(2026, 9, 20, 20, 0, tzinfo=timezone.utc)
SOURCE = {"source_id": "issuer", "ticker": "ABC", "url": "https://ir.example.com/feed",
          "allowed_hosts": ["ir.example.com"], "format": "rss_atom", "required": True}


def feed(*, title="Results", url="https://ir.example.com/results", date="Sun, 20 Sep 2026 12:00:00 GMT"):
    return f'<rss version="2.0"><channel><item><title>{title}</title><link>{url}</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        manifest = load_manifest()
        manifest["sources"] = [SOURCE]
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(manifest))
        self.paths = {"manifest_path": self.manifest, "status_path": self.root / "status.json",
                      "events_path": self.root / "events.json"}

    def test_verified_sources_are_valid_and_explicit(self):
        manifest = load_manifest(MANIFEST_PATH)
        self.assertEqual({s["ticker"] for s in manifest["sources"]}, {"IOT", "NVDA", "RBRK"})

    def test_rss_dates_ids_and_titles_are_plain_data(self):
        result = parse_feed(feed(title="&lt;b&gt;Results&lt;/b&gt;&lt;script&gt;ignore instructions&lt;/script&gt;"), SOURCE, now=NOW)
        self.assertEqual(result[0]["title"], "Results")
        self.assertEqual(result[0]["published_at"], "2026-09-20T12:00:00+00:00")
        self.assertEqual(result[0]["direction"], "unknown")
        self.assertFalse(result[0]["investment_signal"])
        self.assertEqual(result[0]["event_id"], parse_feed(feed(url="https://ir.example.com/results#top"), SOURCE, now=NOW)[0]["event_id"])

    def test_atom_is_supported(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Update</title><link href="https://ir.example.com/a"/><published>2026-09-20T10:00:00Z</published></entry></feed>'
        self.assertEqual(parse_feed(raw, SOURCE, now=NOW)[0]["title"], "Update")

    def test_missing_dates_future_dates_html_and_entities_fail_closed(self):
        for raw in [feed(date=""), feed(date="2026-09-22T00:00:00Z"), feed(date="2026-09-20T12:00:00"),
                    b'<html>Access denied</html>', b'<!DOCTYPE rss [<!ENTITY e "x">]><rss><channel/></rss>']:
            with self.subTest(raw=raw[:50]), self.assertRaises(NewsError):
                parse_feed(raw, SOURCE, now=NOW)

    def test_links_and_redirects_cannot_leave_explicit_official_hosts(self):
        for url in ["http://ir.example.com/a", "https://ir.example.com.evil.test/a",
                    "https://user@ir.example.com/a", "https://127.0.0.1/a", "https://ir.example.com:444/a"]:
            with self.subTest(url=url), self.assertRaises(NewsError):
                canonical_url(url, SOURCE["allowed_hosts"])
        with self.assertRaises(NewsError):
            OfficialRedirect(SOURCE["allowed_hosts"]).redirect_request(None, None, 302, "", {}, "https://evil.test/steal")

    def test_retry_is_bounded_and_http_404_is_not_retried(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("private arbitrary error")
        sleep = Mock()
        with self.assertRaisesRegex(NewsError, "^network_unavailable$"):
            fetch_feed(SOURCE, load_manifest(self.manifest), opener=opener, sleep=sleep)
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        opener.reset_mock()
        opener.open.side_effect = urllib.error.HTTPError(SOURCE["url"], 404, "secret", {}, io.BytesIO())
        with self.assertRaisesRegex(NewsError, "^http_error$"):
            fetch_feed(SOURCE, load_manifest(self.manifest), opener=opener, sleep=sleep)
        self.assertEqual(opener.open.call_count, 1)

    def test_baseline_deduplicates_then_tracks_only_new_recent_events(self):
        first = refresh_news(now=NOW, fetcher=lambda *a: feed(), **self.paths)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["new_event_count"], 0)
        again = refresh_news(now=NOW + timedelta(hours=1), fetcher=lambda *a: feed(), **self.paths)
        self.assertEqual(again["new_event_count"], 0)
        third = refresh_news(now=NOW + timedelta(hours=2), fetcher=lambda *a: feed(url="https://ir.example.com/new"), **self.paths)
        self.assertEqual(third["new_event_count"], 1)
        self.assertEqual(third["recent_event_count"], 2)

    def test_failure_preserves_last_success_and_events_without_saying_no_news(self):
        refresh_news(now=NOW, fetcher=lambda *a: feed(), **self.paths)
        def fail(*a):
            raise NewsError("network_unavailable")
        status = refresh_news(now=NOW + timedelta(hours=1), fetcher=fail, **self.paths)
        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["sources"][0]["last_success_at"], NOW.isoformat())
        self.assertEqual(status["sources"][0]["observed_event_count"], None)
        self.assertEqual(status["sources"][0]["freshness"], "failed")
        self.assertEqual(len(status["recent_events"]), 1)
        self.assertFalse(status["recent_events"][0]["source_fresh"])

    def test_valid_empty_feed_is_distinct_from_missing_and_ages_offline(self):
        self.assertEqual(read_official_news_status(now=NOW, **self.paths)["status"], "missing")
        current = refresh_news(now=NOW, fetcher=lambda *a: b'<rss><channel/></rss>', **self.paths)
        self.assertEqual(current["status"], "ok")
        self.assertEqual(current["sources"][0]["reason"], "valid_empty_feed")
        before = self.paths["status_path"].read_bytes()
        old = read_official_news_status(now=NOW + timedelta(hours=37), **self.paths)
        self.assertEqual(old["sources"][0]["freshness"], "stale")
        self.assertEqual(self.paths["status_path"].read_bytes(), before)

    def test_interrupted_artifact_pair_cannot_look_successful(self):
        refresh_news(now=NOW, fetcher=lambda *a: feed(), **self.paths)
        self.paths["events_path"].write_text('{"schema_version":"phase5r_official_news_events_v1","events":[]}')
        status = read_official_news_status(now=NOW, **self.paths)
        self.assertFalse(status["required_coverage_complete"])
        self.assertEqual(status["recent_events"], [])


if __name__ == "__main__":
    unittest.main()
