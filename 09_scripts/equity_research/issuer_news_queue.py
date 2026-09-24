"""Private source-bound issuer-news continuity; collectors never infer a view.

The rolling feed is an admission window, not a resolution policy. Verified
headlines remain until their exact content is explicitly acknowledged by a
validated authored review. Reads and publication validation never write.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from daily_common import ExclusiveFileLock, canonical_sha256

QUEUE_REL = Path("04_research/company_research/issuer_news_review_queue.local.jsonl")
SCHEMA = "issuer_news_review_queue_v1"


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("issuer_news_queue_timestamp_requires_timezone")
    return parsed


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def read_queue(root: Path) -> list[dict[str, Any]]:
    """Fail closed on broken provenance/chain; never silently clear a queue."""
    from thesis_evidence import stable_news_event, substantive_news
    path = root / QUEUE_REL
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("issuer_news_queue_not_regular")
    rows, previous, observed = [], "", {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        body = {key: value for key, value in row.items() if key != "record_sha256"}
        if (row.get("schema_version") != SCHEMA or row.get("previous_sha256") != previous
                or row.get("record_sha256") != canonical_sha256(body)):
            raise ValueError("issuer_news_queue_chain_invalid")
        recorded = _time(row["recorded_at"])
        if rows and recorded < _time(rows[-1]["recorded_at"]):
            raise ValueError("issuer_news_queue_chronology_invalid")
        identity = (row["event_id"], row["event_sha256"])
        if row["kind"] == "observed_event":
            event, source = row["event"], row["source_receipt"]
            if (event != stable_news_event(event) or event["event_id"] != row["event_id"]
                    or event["ticker"] != row["ticker"] or canonical_sha256(event) != row["event_sha256"]
                    or event["source_type"] != "official_issuer_announcement" or not substantive_news(event)
                    or source["source_id"] != event["source_id"] or source["ticker"] != event["ticker"]
                    or not _hash(source["response_sha256"]) or not source["url"].startswith("https://")
                    or not _time(event["published_at"]) <= _time(source["last_success_at"]) <= recorded):
                raise ValueError("issuer_news_queue_source_invalid")
            observed[identity] = row
        elif row["kind"] in {"review_acknowledged", "reassessment_required"}:
            if identity not in observed or row["ticker"] != observed[identity]["ticker"]:
                raise ValueError("issuer_news_queue_review_event_unverified")
            if not _hash(row["review_record_sha256"]) or not row["review_id"]:
                raise ValueError("issuer_news_queue_review_identity_invalid")
        else:
            raise ValueError("issuer_news_queue_kind_invalid")
        rows.append(row)
        previous = row["record_sha256"]
    return rows


def _append(path: Path, rows: list[dict[str, Any]], body: dict[str, Any], current: datetime) -> None:
    if rows and current < _time(rows[-1]["recorded_at"]):
        raise ValueError("issuer_news_queue_clock_regressed")
    row = body | {"schema_version": SCHEMA, "recorded_at": current.isoformat(),
                  "previous_sha256": rows[-1]["record_sha256"] if rows else ""}
    row["record_sha256"] = canonical_sha256(row)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("issuer_news_queue_not_private_regular")
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    rows.append(row)


def _verified_current(news: dict[str, Any], current: datetime) -> list[dict[str, Any]]:
    from thesis_evidence import stable_news_event, substantive_news
    sources = {row.get("source_id"): row for row in news.get("sources", [])}
    verified = []
    for event in news.get("recent_events", []):
        source = sources.get(event.get("source_id"), {})
        if (event.get("source_type") != "official_issuer_announcement" or not substantive_news(event)
                or event.get("source_fresh") is not True or source.get("freshness") != "fresh"
                or source.get("ticker") != event.get("ticker") or not _hash(source.get("response_sha256"))
                or not str(source.get("url", "")).startswith("https://")):
            continue
        stable = stable_news_event(event)
        if not _time(stable["published_at"]) <= _time(source["last_success_at"]) <= current:
            continue
        verified.append({"kind": "observed_event", "event_id": stable["event_id"], "ticker": stable["ticker"],
            "event_sha256": canonical_sha256(stable), "event": stable,
            "source_receipt": {key: source[key] for key in ("source_id", "ticker", "url", "response_sha256", "last_success_at")}})
    return verified


def merge_news_context(news: dict[str, Any], *, root: Path, current: datetime, persist: bool = False) -> dict[str, Any]:
    """Merge retained identities and current verified observations, idempotently."""
    current_events = _verified_current(news, current)
    path = root / QUEUE_REL
    if persist and current_events:
        with ExclusiveFileLock(path.with_suffix(".lock")):
            rows = read_queue(root)
            latest = {row["event_id"]: row["event_sha256"] for row in rows if row["kind"] == "observed_event"}
            for event in current_events:
                if latest.get(event["event_id"]) != event["event_sha256"]:
                    _append(path, rows, event, current)
                    latest[event["event_id"]] = event["event_sha256"]
    else:
        rows = read_queue(root)
    latest, acknowledged, required = {}, {}, {}
    for row in rows:
        if _time(row["recorded_at"]) > current:
            continue
        if row["kind"] == "observed_event":
            latest[row["event_id"]] = row["event"] | {"source_verified_at_admission": True}
        elif row["kind"] == "review_acknowledged":
            acknowledged.setdefault(row["event_id"], set()).add(row["event_sha256"])
        elif row["kind"] == "reassessment_required":
            required.setdefault(row["event_id"], set()).add(row["event_sha256"])
    for row in current_events:
        latest[row["event_id"]] = row["event"] | {"source_verified_at_admission": True}
    # Unverified headlines stay in recent_events for collection diagnostics;
    # they cannot replace verified payloads or establish maintained research.
    result = deepcopy(news)
    result["review_events"] = sorted(latest.values(), key=lambda row: (row.get("published_at", ""), row.get("event_id", "")))
    result["reviewed_event_hashes"] = {key: sorted(value) for key, value in sorted(acknowledged.items())}
    result["reassessment_event_hashes"] = {key: sorted(value) for key, value in sorted(required.items())}
    result["review_queue"] = {"status": "verified" if rows else "empty", "retained_event_count": len(latest),
                              "unresolved_events_do_not_expire": True}
    return result


def record_review_states(views: dict[str, Any], *, root: Path, current: datetime) -> None:
    """Producer-only: bind exact acknowledgments to already validated reviews."""
    path = root / QUEUE_REL
    # Do not create a queue/lock merely because a readonly-derived view exists.
    if not path.exists():
        return
    with ExclusiveFileLock(path.with_suffix(".lock")):
        rows = read_queue(root)
        observed = {(row["event_id"], row["event_sha256"]) for row in rows if row["kind"] == "observed_event"}
        recorded = {(row["kind"], row["event_id"], row["event_sha256"]) for row in rows}
        for ticker, view in views.items():
            record = view.get("review_record") or {}
            if (view.get("validation_errors") or not record or record.get("ticker") != ticker
                    or record.get("record_sha256") != view.get("review_record_sha256")
                    or record["record_sha256"] != canonical_sha256({key: value for key, value in record.items() if key != "record_sha256"})
                    or _time(record["reviewed_at"]) > current):
                continue
            actions = [("review_acknowledged", row["event"]["event_id"], row["event_sha256"])
                       for row in record.get("reviewed_news_events", [])]
            actions += [("reassessment_required", row["event_id"], row["event_sha256"])
                        for row in view.get("news_review", {}).get("pending_events", [])
                        if row.get("reason") in {"new_material_news_after_review", "reviewed_news_content_changed", "unresolved_material_news_review"}]
            for kind, event_id, digest in actions:
                if (event_id, digest) not in observed or (kind, event_id, digest) in recorded:
                    continue
                _append(path, rows, {"kind": kind, "event_id": event_id, "event_sha256": digest, "ticker": ticker,
                    "review_id": record["review_id"], "review_record_sha256": record["record_sha256"]}, current)
                recorded.add((kind, event_id, digest))


def retained_verified_events(root: Path, *, current: datetime) -> dict[str, Any]:
    """Allow a dated explicit review after the rolling feed window has ended."""
    context = merge_news_context({}, root=root, current=current)
    return {row["event_id"]: row for row in context["review_events"]}
