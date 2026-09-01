#!/usr/bin/env python3
"""Cache selected SEC primary documents with deterministic text provenance.

The default-safe ``--check`` mode performs no network request and writes no
files. Public SEC retrieval is possible only through explicit ``--refresh``.
This module is independent of the daily pipeline and has no email, SMTP,
account, broker, order, model, or credential integration.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlsplit

from phase5r_active_config import load_active_config
from phase5r_daily_common import cycle_date


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_LEDGER_PATH = (
    ROOT / "03_source_data" / "phase5r" / "phase5r_daily_evidence_ledger.csv"
)
ARTIFACT_ROOT = ROOT / "02_filings" / "phase5r_daily"
INDEX_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_filing_artifact_index.json"
)

INDEX_SCHEMA_VERSION = "phase5r_sec_filing_artifact_index_v1"
PARSER_ID = "phase5r_sec_text_normalizer"
PARSER_VERSION = "1.0.0"
SELECTION_POLICY = "latest_filing_date_per_ticker_plus_current_material_v2"
ALLOWED_SEC_HOSTS = frozenset({"sec.gov", "www.sec.gov"})
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "application/xml",
        "text/xml",
    }
)
MAX_RAW_BYTES = 25 * 1024 * 1024
DEFAULT_CHUNK_CHARS = 4_000
DEFAULT_CHUNK_OVERLAP = 200
# Stay conservatively below the SEC's published fair-access ceiling. This is
# start-to-start pacing for network misses only; verified cache hits do not
# sleep or make a request.
SEC_MIN_REQUEST_INTERVAL_SECONDS = 0.2
SAFE_PATH_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
ACCESSION_PATTERN = re.compile(r"\d{10}-\d{2}-\d{6}")
CIK_PATTERN = re.compile(r"\d{1,10}")
REQUIRED_LEDGER_FIELDS = {
    "detected_at",
    "cycle_date",
    "ticker",
    "cik",
    "form",
    "filing_date",
    "accession_number",
    "primary_document",
    "source_url",
    "is_new",
    "material_event",
}
BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "caption",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "ix:hidden"})


class ArtifactError(ValueError):
    """A fail-closed validation error for source or cached artifacts."""


@dataclass(frozen=True)
class FetchResult:
    raw_bytes: bytes
    content_type: str
    charset: str


Fetcher = Callable[[str, str, int], FetchResult]


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in SKIP_TAGS:
            self.skip_depth += 1
        elif self.skip_depth == 0 and normalized in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
        elif self.skip_depth == 0 and normalized in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, content)


def normalize_whitespace(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", normalized)
    lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def decode_bytes(raw_bytes: bytes, charset: str) -> str:
    requested = (charset or "utf-8").strip().lower()
    try:
        codecs.lookup(requested)
    except LookupError:
        requested = "utf-8"
    return raw_bytes.decode(requested, errors="replace")


def normalize_document(
    raw_bytes: bytes, content_type: str, charset: str = "utf-8"
) -> str:
    media_type = content_type.strip().lower()
    if media_type not in ALLOWED_CONTENT_TYPES:
        raise ArtifactError(f"unsupported SEC content type: {media_type or 'missing'}")
    decoded = decode_bytes(raw_bytes, charset)
    if media_type == "text/plain":
        normalized = normalize_whitespace(decoded)
    else:
        parser = _VisibleTextParser()
        parser.feed(decoded)
        parser.close()
        normalized = normalize_whitespace("".join(parser.parts))
    if not normalized:
        raise ArtifactError("SEC primary document normalized to empty text")
    return normalized


def build_chunks(
    normalized_text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    if max_chars <= 0 or overlap < 0 or overlap >= max_chars:
        raise ValueError("chunk contract requires max_chars > overlap >= 0")
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(normalized_text):
        end = min(len(normalized_text), start + max_chars)
        content = normalized_text[start:end]
        chunks.append(
            {
                "index": len(chunks),
                "char_start": start,
                "char_end": end,
                "sha256": sha256_text(content),
            }
        )
        if end == len(normalized_text):
            break
        start = end - overlap
    return chunks


def require_safe_token(value: str, label: str) -> str:
    token = value.strip()
    if (
        not SAFE_PATH_TOKEN.fullmatch(token)
        or token in {".", ".."}
        or "/" in token
        or "\\" in token
    ):
        raise ArtifactError(f"unsafe {label}")
    return token


def validate_source_url(url: str, *, cik: str, accession: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise ArtifactError("invalid SEC primary-document URL") from exc
    if (
        parsed.scheme.lower() != "https"
        or host not in ALLOWED_SEC_HOSTS
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ArtifactError("SEC URL violates HTTPS host allowlist")
    decoded_path = unquote(parsed.path)
    if decoded_path != parsed.path or "\\" in decoded_path:
        raise ArtifactError("SEC URL contains encoded or unsafe path characters")
    segments = [part for part in decoded_path.split("/") if part]
    if len(segments) != 6 or segments[:3] != ["Archives", "edgar", "data"]:
        raise ArtifactError("SEC URL is not a primary-document archive path")
    url_cik, url_accession, document_name = segments[3:]
    if not url_cik.isdigit() or int(url_cik) != int(cik):
        raise ArtifactError("SEC URL CIK does not match ledger")
    if url_accession != accession.replace("-", ""):
        raise ArtifactError("SEC URL accession does not match ledger")
    require_safe_token(document_name, "primary document name")
    return parsed.geturl()


def source_id_for(row: dict[str, str]) -> str:
    identity = f"{row['cik']}|{row['accession']}|{row['url']}"
    suffix = sha256_text(identity)[:16]
    return f"sec-{row['cik']}-{row['accession']}-{suffix}"


def normalize_ledger_row(row: dict[str, str]) -> dict[str, str]:
    ticker = require_safe_token(row.get("ticker", "").strip().upper(), "ticker")
    cik = row.get("cik", "").strip()
    if not CIK_PATTERN.fullmatch(cik) or int(cik) <= 0:
        raise ArtifactError(f"invalid CIK for {ticker}")
    cik = str(int(cik))
    accession = row.get("accession_number", "").strip()
    if not ACCESSION_PATTERN.fullmatch(accession):
        raise ArtifactError(f"invalid accession for {ticker}")
    try:
        filing_day = date.fromisoformat(row.get("filing_date", "").strip())
    except ValueError as exc:
        raise ArtifactError(f"invalid filing date for {ticker}") from exc
    try:
        ledger_cycle_day = date.fromisoformat(
            row.get("cycle_date", "").strip()
        )
    except ValueError as exc:
        raise ArtifactError(f"invalid cycle date for {ticker}") from exc
    form = row.get("form", "").strip()
    if not form or len(form) > 32 or re.search(r"[^A-Za-z0-9 /-]", form):
        raise ArtifactError(f"invalid filing form for {ticker}")
    url = validate_source_url(
        row.get("source_url", ""), cik=cik, accession=accession
    )
    primary_document = require_safe_token(
        row.get("primary_document", "").strip(), "primary document"
    )
    if urlsplit(url).path.rsplit("/", 1)[-1] != primary_document:
        raise ArtifactError("primary document does not match source URL")
    normalized = {
        "detected_at": row.get("detected_at", "").strip(),
        "cycle_date": ledger_cycle_day.isoformat(),
        "ticker": ticker,
        "cik": cik,
        "accession": accession,
        "form": form,
        "filing_date": filing_day.isoformat(),
        "primary_document": primary_document,
        "url": url,
        "is_new": row.get("is_new", "").strip().lower(),
        "material_event": row.get("material_event", "").strip().lower(),
    }
    normalized["source_id"] = source_id_for(normalized)
    return normalized


def read_evidence_ledger(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ArtifactError(f"SEC evidence ledger missing: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = REQUIRED_LEDGER_FIELDS - fields
        if missing:
            raise ArtifactError(
                "SEC evidence ledger missing fields: " + ",".join(sorted(missing))
            )
        return [dict(row) for row in reader]


def select_filing_rows(
    rows: Iterable[dict[str, str]],
    *,
    as_of: date | None = None,
    material_lookback_days: int = 7,
) -> list[dict[str, str]]:
    if material_lookback_days not in range(1, 31):
        raise ArtifactError("material filing lookback is invalid")
    deduplicated: dict[str, dict[str, str]] = {}
    for raw_row in rows:
        row = normalize_ledger_row(raw_row)
        existing = deduplicated.get(row["source_id"])
        if existing is None or row["detected_at"] > existing["detected_at"]:
            deduplicated[row["source_id"]] = row
    if not deduplicated:
        raise ArtifactError("SEC evidence ledger has no selectable filings")

    latest_dates: dict[str, str] = {}
    for row in deduplicated.values():
        latest_dates[row["ticker"]] = max(
            row["filing_date"], latest_dates.get(row["ticker"], "")
        )
    selected: list[dict[str, str]] = []
    for row in deduplicated.values():
        current_material = bool(
            row["is_new"] == "yes"
            and row["material_event"] == "yes"
        )
        if as_of is not None and current_material:
            filing_age = (as_of - date.fromisoformat(row["filing_date"])).days
            current_material = bool(
                row["cycle_date"] == as_of.isoformat()
                and 0 <= filing_age <= material_lookback_days
            )
        if (
            row["filing_date"] == latest_dates[row["ticker"]]
            or current_material
        ):
            selected.append(row)
    return sorted(
        selected,
        key=lambda item: (
            item["ticker"],
            item["filing_date"],
            item["accession"],
            item["url"],
        ),
    )


def artifact_paths(
    artifact_root: Path, row: dict[str, str]
) -> tuple[Path, Path, Path]:
    ticker = require_safe_token(row["ticker"], "ticker")
    accession = require_safe_token(row["accession"], "accession")
    root_resolved = artifact_root.resolve()
    directory = (artifact_root / ticker / accession).resolve()
    if root_resolved != directory and root_resolved not in directory.parents:
        raise ArtifactError("artifact path escaped SEC filing root")
    return (
        directory,
        directory / "primary_document.raw",
        directory / "normalized_text.txt",
    )


def display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def fetch_sec_document(
    url: str, user_agent: str, max_bytes: int = MAX_RAW_BYTES
) -> FetchResult:
    normalized_user_agent = user_agent.strip()
    if (
        not normalized_user_agent
        or len(normalized_user_agent) > 256
        or "\r" in normalized_user_agent
        or "\n" in normalized_user_agent
    ):
        raise ArtifactError("SEC User-Agent is invalid")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": normalized_user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain,application/xml,text/xml",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        requested_url = urlsplit(url)
        final_url = urlsplit(response.geturl())
        final_host = (final_url.hostname or "").lower()
        if (
            final_host not in ALLOWED_SEC_HOSTS
            or final_url.scheme.lower() != "https"
            or final_url.path != requested_url.path
            or final_url.query
            or final_url.fragment
        ):
            raise ArtifactError("SEC redirect violates host or primary-document path")
        content_encoding = response.headers.get("Content-Encoding", "identity").lower()
        if content_encoding not in {"", "identity"}:
            raise ArtifactError("compressed SEC response is not accepted")
        content_type = response.headers.get_content_type().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ArtifactError(f"unsupported SEC content type: {content_type}")
        charset = response.headers.get_content_charset() or "utf-8"
        declared_length = response.headers.get("Content-Length", "").strip()
        if declared_length:
            try:
                declared_bytes = int(declared_length)
            except ValueError as exc:
                raise ArtifactError("invalid SEC Content-Length") from exc
            if declared_bytes > max_bytes:
                raise ArtifactError("SEC primary document exceeds size cap")
        parts: list[bytes] = []
        total = 0
        while True:
            part = response.read(64 * 1024)
            if not part:
                break
            total += len(part)
            if total > max_bytes:
                raise ArtifactError("SEC primary document exceeds size cap")
            parts.append(part)
    raw_bytes = b"".join(parts)
    if not raw_bytes:
        raise ArtifactError("SEC primary document is empty")
    return FetchResult(raw_bytes, content_type, charset)


def load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": INDEX_SCHEMA_VERSION, "artifacts": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError("SEC artifact index is unreadable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != INDEX_SCHEMA_VERSION
        or not isinstance(payload.get("artifacts"), list)
    ):
        raise ArtifactError("SEC artifact index schema is invalid")
    return payload


def _entry_identity_matches(
    entry: dict[str, Any], row: dict[str, str], raw_path: Path, text_path: Path, project_root: Path
) -> bool:
    expected = {
        "source_id": row["source_id"],
        "ticker": row["ticker"],
        "cik": row["cik"],
        "accession": row["accession"],
        "form": row["form"],
        "filing_date": row["filing_date"],
        "url": row["url"],
        "raw_path": display_path(raw_path, project_root),
        "normalized_path": display_path(text_path, project_root),
    }
    return all(entry.get(key) == value for key, value in expected.items())


def raw_cache_is_valid(entry: dict[str, Any], raw_path: Path) -> bool:
    if not raw_path.is_file() or raw_path.stat().st_size > MAX_RAW_BYTES:
        return False
    content_type = str(entry.get("content_type", "")).lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        return False
    return sha256_bytes(raw_path.read_bytes()) == entry.get("raw_sha256")


def complete_cache_entry(
    entry: dict[str, Any],
    row: dict[str, str],
    raw_path: Path,
    text_path: Path,
    project_root: Path,
) -> dict[str, Any] | None:
    if not _entry_identity_matches(entry, row, raw_path, text_path, project_root):
        return None
    if (
        entry.get("parser_id") != PARSER_ID
        or entry.get("parser_version") != PARSER_VERSION
        or not raw_cache_is_valid(entry, raw_path)
        or not text_path.is_file()
    ):
        return None
    try:
        normalized_text = text_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if (
        sha256_text(normalized_text) != entry.get("normalized_sha256")
        or len(normalized_text) != entry.get("normalized_chars")
        or build_chunks(normalized_text) != entry.get("chunks")
    ):
        return None
    cached = dict(entry)
    cached["cache_status"] = "hit"
    return cached


def build_entry(
    row: dict[str, str],
    result: FetchResult,
    *,
    raw_path: Path,
    text_path: Path,
    project_root: Path,
    fetched_at: str,
    cache_status: str,
) -> tuple[dict[str, Any], str]:
    if len(result.raw_bytes) > MAX_RAW_BYTES:
        raise ArtifactError("SEC primary document exceeds size cap")
    normalized_text = normalize_document(
        result.raw_bytes, result.content_type, result.charset
    )
    entry: dict[str, Any] = {
        "source_id": row["source_id"],
        "ticker": row["ticker"],
        "cik": row["cik"],
        "accession": row["accession"],
        "form": row["form"],
        "filing_date": row["filing_date"],
        "url": row["url"],
        "primary_document": row["primary_document"],
        "raw_path": display_path(raw_path, project_root),
        "normalized_path": display_path(text_path, project_root),
        "raw_sha256": sha256_bytes(result.raw_bytes),
        "normalized_sha256": sha256_text(normalized_text),
        "raw_bytes": len(result.raw_bytes),
        "normalized_chars": len(normalized_text),
        "content_type": result.content_type.lower(),
        "charset": result.charset or "utf-8",
        "parser_id": PARSER_ID,
        "parser_version": PARSER_VERSION,
        "chunk_chars": DEFAULT_CHUNK_CHARS,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "chunks": build_chunks(normalized_text),
        "fetched_at": fetched_at,
        "cache_status": cache_status,
    }
    return entry, normalized_text


def materialize_entry(
    row: dict[str, str],
    result: FetchResult,
    *,
    raw_path: Path,
    text_path: Path,
    project_root: Path,
    fetched_at: str,
    cache_status: str,
    write_raw: bool,
) -> dict[str, Any]:
    entry, normalized_text = build_entry(
        row,
        result,
        raw_path=raw_path,
        text_path=text_path,
        project_root=project_root,
        fetched_at=fetched_at,
        cache_status=cache_status,
    )
    if write_raw:
        atomic_write_bytes(raw_path, result.raw_bytes)
    atomic_write_bytes(text_path, normalized_text.encode("utf-8"))
    return entry


def _index_payload(
    *,
    ledger_path: Path,
    project_root: Path,
    artifacts: list[dict[str, Any]],
    cache_hits: int,
    reparsed: int,
    network_fetches: int,
) -> dict[str, Any]:
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "ledger_path": display_path(ledger_path, project_root),
        "ledger_sha256": sha256_bytes(ledger_path.read_bytes()),
        "selection_policy": SELECTION_POLICY,
        "parser_id": PARSER_ID,
        "parser_version": PARSER_VERSION,
        "max_raw_bytes": MAX_RAW_BYTES,
        "chunk_chars": DEFAULT_CHUNK_CHARS,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "selected_count": len(artifacts),
        "cache_hit_count": cache_hits,
        "reparsed_count": reparsed,
        "network_fetch_count": network_fetches,
        "artifacts": artifacts,
        "boundaries": {
            "public_sec_only": True,
            "email_used": False,
            "smtp_used": False,
            "account_read": False,
            "broker_used": False,
            "order_code_created": False,
            "model_used": False,
            "api_key_used": False,
        },
    }


def refresh_artifacts(
    *,
    ledger_path: Path = EVIDENCE_LEDGER_PATH,
    artifact_root: Path = ARTIFACT_ROOT,
    index_path: Path = INDEX_PATH,
    project_root: Path = ROOT,
    fetcher: Fetcher = fetch_sec_document,
    user_agent: str,
    request_interval_seconds: float = SEC_MIN_REQUEST_INTERVAL_SECONDS,
    monotonic_clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    as_of: date | None = None,
    material_lookback_days: int = 7,
) -> dict[str, Any]:
    if request_interval_seconds < 0:
        raise ArtifactError("SEC request interval is invalid")
    selected = select_filing_rows(
        read_evidence_ledger(ledger_path),
        as_of=as_of,
        material_lookback_days=material_lookback_days,
    )
    prior = load_index(index_path)
    prior_by_id = {
        str(entry.get("source_id")): entry
        for entry in prior.get("artifacts", [])
        if isinstance(entry, dict) and entry.get("source_id")
    }
    artifacts: list[dict[str, Any]] = []
    cache_hits = 0
    reparsed = 0
    network_fetches = 0
    last_network_request_started: float | None = None

    for row in selected:
        _, raw_path, text_path = artifact_paths(artifact_root, row)
        prior_entry = prior_by_id.get(row["source_id"], {})
        cached = complete_cache_entry(
            prior_entry, row, raw_path, text_path, project_root
        )
        if cached is not None:
            artifacts.append(cached)
            cache_hits += 1
            continue

        identity_matches = _entry_identity_matches(
            prior_entry, row, raw_path, text_path, project_root
        )
        if identity_matches and raw_cache_is_valid(prior_entry, raw_path):
            raw_bytes = raw_path.read_bytes()
            result = FetchResult(
                raw_bytes=raw_bytes,
                content_type=str(prior_entry["content_type"]),
                charset=str(prior_entry.get("charset", "utf-8")),
            )
            entry = materialize_entry(
                row,
                result,
                raw_path=raw_path,
                text_path=text_path,
                project_root=project_root,
                fetched_at=str(prior_entry.get("fetched_at", "")) or utc_now(),
                cache_status="reparsed",
                write_raw=False,
            )
            artifacts.append(entry)
            reparsed += 1
            continue

        request_started = monotonic_clock()
        if last_network_request_started is not None:
            wait_seconds = max(
                0.0,
                request_interval_seconds
                - (request_started - last_network_request_started),
            )
            if wait_seconds:
                sleeper(wait_seconds)
                request_started = monotonic_clock()
        last_network_request_started = request_started
        result = fetcher(row["url"], user_agent, MAX_RAW_BYTES)
        entry = materialize_entry(
            row,
            result,
            raw_path=raw_path,
            text_path=text_path,
            project_root=project_root,
            fetched_at=utc_now(),
            cache_status="fetched",
            write_raw=True,
        )
        artifacts.append(entry)
        network_fetches += 1

    payload = _index_payload(
        ledger_path=ledger_path,
        project_root=project_root,
        artifacts=artifacts,
        cache_hits=cache_hits,
        reparsed=reparsed,
        network_fetches=network_fetches,
    )
    atomic_write_json(index_path, payload)
    return payload


def check_artifacts(
    *,
    ledger_path: Path = EVIDENCE_LEDGER_PATH,
    artifact_root: Path = ARTIFACT_ROOT,
    index_path: Path = INDEX_PATH,
    project_root: Path = ROOT,
    as_of: date | None = None,
    material_lookback_days: int = 7,
) -> dict[str, int]:
    selected = select_filing_rows(
        read_evidence_ledger(ledger_path),
        as_of=as_of,
        material_lookback_days=material_lookback_days,
    )
    prior = load_index(index_path)
    prior_by_id = {
        str(entry.get("source_id")): entry
        for entry in prior.get("artifacts", [])
        if isinstance(entry, dict) and entry.get("source_id")
    }
    complete = 0
    reparsable = 0
    missing = 0
    for row in selected:
        _, raw_path, text_path = artifact_paths(artifact_root, row)
        entry = prior_by_id.get(row["source_id"], {})
        if (
            complete_cache_entry(entry, row, raw_path, text_path, project_root)
            is not None
        ):
            complete += 1
        elif _entry_identity_matches(
            entry, row, raw_path, text_path, project_root
        ) and raw_cache_is_valid(entry, raw_path):
            reparsable += 1
        else:
            missing += 1
    return {
        "selected": len(selected),
        "complete_cache": complete,
        "reparsable_cache": reparsable,
        "missing_cache": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--user-agent",
        default=os.environ.get(
            "PHASE5R_SEC_USER_AGENT",
            "Phase5R-LocalResearch/1.0 research-contact@localhost",
        ),
        help="SEC-compliant public-research User-Agent; never treated as a secret",
    )
    args = parser.parse_args()
    try:
        current_cycle = date.fromisoformat(cycle_date())
        material_lookback_days = load_active_config()["notifications"][
            "new_filing_lookback_calendar_days"
        ]
        if args.check:
            summary = check_artifacts(
                as_of=current_cycle,
                material_lookback_days=material_lookback_days,
            )
            print(
                "sec_artifact_check=passed "
                f"selected={summary['selected']} "
                f"complete_cache={summary['complete_cache']} "
                f"reparsable_cache={summary['reparsable_cache']} "
                f"missing_cache={summary['missing_cache']} "
                "network_used=false files_written=false"
            )
            return 0
        payload = refresh_artifacts(
            user_agent=args.user_agent,
            as_of=current_cycle,
            material_lookback_days=material_lookback_days,
        )
        print(
            "sec_artifact_refresh=passed "
            f"selected={payload['selected_count']} "
            f"cache_hits={payload['cache_hit_count']} "
            f"reparsed={payload['reparsed_count']} "
            f"network_fetches={payload['network_fetch_count']} "
            "email_used=false smtp_used=false account_read=false "
            "broker_used=false order_code_created=false model_used=false "
            "api_key_used=false"
        )
        return 0
    except (ArtifactError, OSError) as exc:
        print(
            f"sec_artifact_result=failed error_type={type(exc).__name__} "
            "email_used=false smtp_used=false account_read=false "
            "broker_used=false order_code_created=false model_used=false"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
