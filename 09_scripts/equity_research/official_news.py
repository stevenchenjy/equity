"""Bounded official RSS/Atom ingestion; fetched text is evidence, never instructions.

Only source identity, a plain-text title, publication time and an official URL
are retained. Announcements are unclassified review items, never buy signals.
Failures preserve history but do not become a successful 'no news' observation.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from daily_common import ROOT, atomic_write_json, canonical_sha256, read_json

MANIFEST_PATH = ROOT / "01_policies" / "official_news_sources.json"
EVENTS_PATH = ROOT / "03_source_data" / "equity_research" / "official_news_events.local.json"
STATUS_PATH = ROOT / "03_source_data" / "equity_research" / "official_news_status.local.json"
LOCK_PATH = ROOT / "00_project_control" / "run_logs" / "official_news.lock"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 4000
USER_AGENT = "Phase5R/1.0 (personal public issuer research; RSS reader)"


class NewsError(ValueError):
    """A finite failure code that cannot expose arbitrary provider content."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            result = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            raise NewsError("invalid_publication_time") from None
    if result.tzinfo is None:
        raise NewsError("timezone_missing")
    return result.astimezone(timezone.utc)


def canonical_url(value: str, hosts: list[str]) -> str:
    try:
        # Some issuer feeds wrap HTML-escaped URLs in CDATA; normalize once.
        value = unescape(value.strip())
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.hostname not in hosts
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or not parts.path.startswith("/")
                or any(ord(ch) < 33 for ch in value)):
            raise NewsError("nonofficial_or_unsafe_url")
        return urlunsplit(("https", parts.hostname, parts.path, parts.query, ""))
    except ValueError:
        raise NewsError("nonofficial_or_unsafe_url") from None


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "phase5r_official_news_sources_v1":
        raise NewsError("invalid_manifest")
    for key, lower, upper in (("max_age_hours", 1, 72), ("event_lookback_days", 1, 30),
                              ("retention_days", 7, 365), ("request_timeout_seconds", 1, 20),
                              ("maximum_attempts", 1, 3)):
        if type(value.get(key)) is not int or not lower <= value[key] <= upper:
            raise NewsError("invalid_manifest_bounds")
    sources = value.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 30:
        raise NewsError("invalid_manifest_sources")
    ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise NewsError("invalid_manifest_source")
        sid = source.get("source_id", "")
        hosts = source.get("allowed_hosts")
        if (not re.fullmatch(r"[a-z0-9_]{1,64}", sid) or sid in ids
                or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", source.get("ticker", ""))
                or source.get("format") != "rss_atom"
                or type(source.get("required")) is not bool
                or not isinstance(hosts, list) or not hosts
                or any(not isinstance(h, str) or not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", h) for h in hosts)):
            raise NewsError("invalid_manifest_source")
        canonical_url(source["url"], hosts)
        ids.add(sid)
    return value


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts: list[str]):
        self.hosts = hosts

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        canonical_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_feed(source: dict[str, Any], manifest: dict[str, Any], *,
               opener: Any = None, sleep: Callable[[float], None] = time.sleep) -> bytes:
    url = canonical_url(source["url"], source["allowed_hosts"])
    opener = opener or urllib.request.build_opener(OfficialRedirect(source["allowed_hosts"]))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        "Accept-Encoding": "identity"})
    for attempt in range(manifest["maximum_attempts"]):
        try:
            with opener.open(request, timeout=manifest["request_timeout_seconds"]) as response:
                canonical_url(response.geturl(), source["allowed_hosts"])
                if response.status != 200:
                    raise NewsError("unexpected_http_status")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise NewsError("response_too_large")
                return payload
        except urllib.error.HTTPError as exc:
            retry = exc.code == 429 or 500 <= exc.code <= 599
            code = "http_rate_limited" if exc.code == 429 else "http_error"
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            retry, code = True, "network_unavailable"
        if not retry or attempt + 1 == manifest["maximum_attempts"]:
            raise NewsError(code) from None
        sleep(float(attempt + 1))
    raise NewsError("network_unavailable")


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def clean_title(value: str) -> str:
    parser = _PlainText()
    parser.feed(unescape(value))
    parser.close()
    title = " ".join(" ".join(parser.parts).split())
    title = "".join(ch for ch in title if ord(ch) >= 32 and ord(ch) != 127)
    if not title or len(title) > 1000:
        raise NewsError("invalid_title")
    return title


def parse_feed(payload: bytes, source: dict[str, Any], *, now: datetime) -> list[dict[str, Any]]:
    if len(payload) > MAX_RESPONSE_BYTES or re.search(br"<!\s*(?:DOCTYPE|ENTITY)", payload, re.I):
        raise NewsError("unsafe_or_oversized_xml")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        raise NewsError("invalid_feed_xml") from None
    atom = "{http://www.w3.org/2005/Atom}"
    if root.tag == "rss" and root.find("channel") is not None:
        entries = root.findall("./channel/item")
        is_atom = False
    elif root.tag == atom + "feed":
        entries, is_atom = root.findall(atom + "entry"), True
    else:
        raise NewsError("unsupported_feed_document")
    if len(entries) > 1000:
        raise NewsError("too_many_feed_entries")
    events: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if is_atom:
            title = "".join(entry.find(atom + "title").itertext()) if entry.find(atom + "title") is not None else ""
            links = [link for link in entry.findall(atom + "link") if link.get("rel", "alternate") == "alternate"]
            url = links[0].get("href", "") if links else ""
            published = entry.findtext(atom + "published") or entry.findtext(atom + "updated") or ""
        else:
            title = entry.findtext("title") or ""
            url = entry.findtext("link") or ""
            published = entry.findtext("pubDate") or ""
        url = canonical_url(url, source["allowed_hosts"])
        published_at = timestamp(published)
        if published_at > now + timedelta(minutes=5):
            raise NewsError("future_publication_time")
        event_id = hashlib.sha256((source["ticker"] + "\n" + url).encode()).hexdigest()
        events[event_id] = {"event_id": event_id, "source_id": source["source_id"],
            "ticker": source["ticker"], "title": clean_title(title), "url": url,
            "published_at": published_at.isoformat(), "direction": "unknown",
            "review_required": True, "investment_signal": False,
            "source_type": "official_issuer_announcement"}
    return sorted(events.values(), key=lambda x: (x["published_at"], x["event_id"]), reverse=True)


def read_official_news_status(*, now: datetime | None = None,
        manifest_path: Path = MANIFEST_PATH, status_path: Path = STATUS_PATH,
        events_path: Path = EVENTS_PATH) -> dict[str, Any]:
    """Read and age receipts offline. A failed latest attempt is never fresh."""
    now = now or utc_now()
    manifest = load_manifest(manifest_path)
    saved = read_json(status_path, {})
    event_doc = read_json(events_path, {})
    matched = (saved.get("manifest_sha256") == canonical_sha256(manifest)
               and saved.get("events_sha256") == canonical_sha256(event_doc)
               and event_doc.get("schema_version") == "phase5r_official_news_events_v1")
    source_states = {r["source_id"]: r for r in saved.get("sources", []) if isinstance(r, dict) and "source_id" in r}
    states = []
    for source in manifest["sources"]:
        prior = source_states.get(source["source_id"], {})
        freshness = "missing"
        if matched and prior.get("last_success_at"):
            try:
                age = (now - timestamp(prior["last_success_at"])).total_seconds()
                freshness = "fresh" if 0 <= age <= manifest["max_age_hours"] * 3600 else "stale"
            except NewsError:
                freshness = "stale"
        if prior.get("last_attempt_status") == "failed":
            freshness = "failed"
        states.append({**prior, "source_id": source["source_id"], "ticker": source["ticker"],
            "url": source["url"], "required": source["required"], "freshness": freshness})
    failures = [r["source_id"] for r in states if r["required"] and r["freshness"] != "fresh"]
    fresh_sources = {r["source_id"] for r in states if r["freshness"] == "fresh"}
    events = []
    if matched:
        for event in event_doc.get("events", []):
            try:
                if 0 <= (now - timestamp(event["published_at"])).total_seconds() <= manifest["event_lookback_days"] * 86400:
                    events.append({**event, "source_fresh": event.get("source_id") in fresh_sources,
                                   "direction": "unknown", "investment_signal": False})
            except (KeyError, TypeError, NewsError):
                continue
    return {"schema_version": "phase5r_official_news_status_v1",
        "status": "missing" if not saved else "degraded" if failures or not matched else "ok",
        "checked_at": now.isoformat(), "last_attempt_at": saved.get("last_attempt_at", ""),
        "required_coverage_complete": not failures and matched,
        "failed_or_stale_sources": failures, "sources": states, "recent_events": events,
        "recent_event_count": len(events), "new_event_count": saved.get("new_event_count", 0),
        "coverage_scope": "configured_official_issuer_sources_only",
        "investment_signal": False}


def refresh_news(*, now: datetime | None = None, manifest_path: Path = MANIFEST_PATH,
        status_path: Path = STATUS_PATH, events_path: Path = EVENTS_PATH,
        fetcher: Callable[..., bytes] = fetch_feed) -> dict[str, Any]:
    now = now or utc_now()
    manifest = load_manifest(manifest_path)
    prior_status = read_json(status_path, {})
    prior_events = read_json(events_path, {})
    if prior_events and prior_events.get("schema_version") != "phase5r_official_news_events_v1":
        raise NewsError("invalid_prior_events")
    events = {row["event_id"]: row for row in prior_events.get("events", [])}
    prior_states = {row["source_id"]: row for row in prior_status.get("sources", [])}
    new_ids: list[str] = []
    states = []
    for source in manifest["sources"]:
        sid = source["source_id"]
        prior = prior_states.get(sid, {})
        state = {"source_id": sid, "ticker": source["ticker"], "url": source["url"],
            "required": source["required"], "last_attempt_at": now.isoformat(),
            "last_success_at": prior.get("last_success_at", ""),
            "consecutive_failures": prior.get("consecutive_failures", 0)}
        try:
            payload = fetcher(source, manifest)
            observed = parse_feed(payload, source, now=now)
            for event in observed:
                old = events.get(event["event_id"])
                event["first_seen_at"] = old.get("first_seen_at", now.isoformat()) if old else now.isoformat()
                event["last_seen_at"] = now.isoformat()
                # First successful poll establishes a baseline; a historical
                # backlog cannot trigger a burst of new-event notifications.
                if old is None and prior.get("last_success_at") and 0 <= (now - timestamp(event["published_at"])).total_seconds() <= manifest["event_lookback_days"] * 86400:
                    new_ids.append(event["event_id"])
                events[event["event_id"]] = event
            state.update({"last_attempt_status": "ok", "last_success_at": now.isoformat(),
                "response_sha256": hashlib.sha256(payload).hexdigest(), "consecutive_failures": 0,
                "observed_event_count": len(observed), "reason": "events_observed" if observed else "valid_empty_feed",
                "baseline_initialized": not bool(prior.get("last_success_at"))})
        except (NewsError, OSError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, NewsError) else "source_read_failed"
            state.update({"last_attempt_status": "failed", "reason": reason,
                "consecutive_failures": state["consecutive_failures"] + 1,
                "observed_event_count": None})
        states.append(state)
    retained = [event for event in events.values()
                if 0 <= (now - timestamp(event["published_at"])).total_seconds() <= manifest["retention_days"] * 86400]
    retained.sort(key=lambda event: (event["published_at"], event["event_id"]), reverse=True)
    if len(retained) > MAX_EVENTS:
        raise NewsError("event_retention_capacity_exceeded")
    event_doc = {"schema_version": "phase5r_official_news_events_v1", "updated_at": now.isoformat(),
        "events": retained, "investment_signal": False}
    status = {"schema_version": "phase5r_official_news_status_v1", "last_attempt_at": now.isoformat(),
        "manifest_sha256": canonical_sha256(manifest), "events_sha256": canonical_sha256(event_doc),
        "new_event_count": len(new_ids), "new_event_ids": sorted(new_ids), "sources": states}
    atomic_write_json(events_path, event_doc)
    atomic_write_json(status_path, status)
    return read_official_news_status(now=now, manifest_path=manifest_path,
                                    status_path=status_path, events_path=events_path)
