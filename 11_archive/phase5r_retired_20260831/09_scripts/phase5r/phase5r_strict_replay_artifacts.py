#!/usr/bin/env python3
"""Acquire and verify strict point-in-time artifacts for a small replay pilot.

The refresh path uses only public SEC endpoints and an explicitly supplied
User-Agent.  The check path is offline and read-only.  Neither path can invoke
a model, send email, read SMTP configuration, access a broker/account, create
orders, or affect the canonical daily decision.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

from prepare_phase5r_llm_replay_corpus import (
    CORPUS_ROOT,
    DEFAULT_CANDIDATE_PADDING,
    DEFAULT_MAX_STORAGE_BYTES,
    DEFAULT_SEC_REQUESTS_PER_SECOND,
    LEDGER_PATH,
    MAX_PRIMARY_BYTES,
    CorpusError,
    Fetcher,
    HttpResult,
    RequestLimiter,
    atomic_write_bytes,
    atomic_write_json,
    canonical_sha256,
    fetch_public_resource,
    filing_paths,
    read_ledger,
    safe_relative_path,
    safe_token,
    select_candidate_rows,
    sha256_bytes,
    storage_budget_scope,
)


ROOT = Path(__file__).resolve().parents[2]

SUBMISSION_SCHEMA_VERSION = "phase5r_sec_submission_snapshot_v1"
COMPANYFACTS_SCHEMA_VERSION = "phase5r_sec_companyfacts_snapshot_v1"
EXHIBIT_MANIFEST_SCHEMA_VERSION = "phase5r_sec_exhibit_manifest_v1"
XBRL_RECONCILIATION_SCHEMA_VERSION = (
    "phase5r_sec_xbrl_accession_reconciliation_v1"
)
STRICT_COMPLETION_SCHEMA_VERSION = "phase5r_strict_pilot_completion_v1"
INDEX_PARSER_VERSION = "phase5r_sec_document_table_v1"

DEFAULT_PILOT_PACKETS = 10
MAX_SUBMISSION_BYTES = 25 * 1024 * 1024
MAX_COMPANYFACTS_BYTES = 50 * 1024 * 1024
MAX_EXHIBIT_BYTES = MAX_PRIMARY_BYTES
MAX_INDEX_DOCUMENT_ROWS = 1_000

DATA_SEC_HOST = "data.sec.gov"
ARCHIVE_SEC_HOSTS = frozenset({"sec.gov", "www.sec.gov"})
JSON_CONTENT_TYPES = frozenset(
    {"application/json", "text/json", "application/octet-stream"}
)
EXHIBIT_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "application/xml",
        "text/xml",
        "application/pdf",
        "application/octet-stream",
        "image/gif",
        "image/jpeg",
        "image/png",
    }
)
XBRL_FORMS = frozenset(
    {
        "10-K",
        "10-K/A",
        "10-Q",
        "10-Q/A",
        "20-F",
        "20-F/A",
        "40-F",
        "40-F/A",
    }
)
EXHIBIT_DISCOVERY_FORMS = frozenset({"6-K", "6-K/A", "8-K", "8-K/A"})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass
class AcquisitionContext:
    user_agent: str
    limiter: RequestLimiter
    fetcher: Fetcher = fetch_public_resource
    request_count: int = 0

    def fetch(
        self,
        *,
        url: str,
        maximum_bytes: int,
        allowed_hosts: frozenset[str],
        allowed_content_types: frozenset[str],
    ) -> HttpResult:
        self.limiter.wait()
        result = self.fetcher(url, self.user_agent, maximum_bytes)
        self.request_count += 1
        if result.final_url != url:
            raise CorpusError("SEC redirect changed strict-artifact identity")
        try:
            parsed = urlsplit(result.final_url)
            port = parsed.port
        except ValueError as exc:
            raise CorpusError("strict-artifact SEC URL is invalid") from exc
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() not in allowed_hosts
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise CorpusError("strict-artifact SEC URL escaped its allowlist")
        if (
            not result.raw_bytes
            or len(result.raw_bytes) > maximum_bytes
            or result.content_type not in allowed_content_types
        ):
            raise CorpusError("strict-artifact SEC response violates its contract")
        return result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> Any:
        raise CorpusError(f"{label} contains non-finite JSON number: {value}")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise CorpusError(f"{label} must be a JSON object")
    return payload


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return _json_object(path.read_bytes(), label=path.name)
    except (OSError, CorpusError):
        return None


def _regular_file_bytes(
    path: Path, *, maximum_bytes: int, allow_empty: bool = False
) -> bytes | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        size = path.stat().st_size
        if size < 0 or size > maximum_bytes or (size == 0 and not allow_empty):
            return None
        return path.read_bytes()
    except OSError:
        return None


def _valid_timestamp(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _self_hash_verified(
    payload: dict[str, Any], field: str
) -> bool:
    stored = payload.get(field)
    unsigned = dict(payload)
    unsigned.pop(field, None)
    return bool(
        isinstance(stored, str)
        and SHA256_PATTERN.fullmatch(stored)
        and canonical_sha256(unsigned) == stored
    )


def submissions_url(cik: str) -> str:
    return (
        "https://data.sec.gov/submissions/"
        f"CIK{int(cik):010d}.json"
    )


def companyfacts_url(cik: str) -> str:
    return (
        "https://data.sec.gov/api/xbrl/companyfacts/"
        f"CIK{int(cik):010d}.json"
    )


def submission_paths(corpus_root: Path, cik: str) -> dict[str, Path]:
    directory = corpus_root / "sec_submissions" / f"CIK{int(cik):010d}"
    return {
        "directory": directory,
        "raw": directory / "submissions.raw.json",
        "metadata": directory / "source_metadata.json",
    }


def companyfacts_paths(
    corpus_root: Path, ticker: str
) -> dict[str, Path]:
    directory = corpus_root / "xbrl" / safe_token(ticker, "ticker")
    return {
        "directory": directory,
        "raw": directory / "companyfacts.raw.json",
        "metadata": directory / "source_metadata.json",
    }


def _snapshot_status(
    *,
    raw_path: Path,
    metadata_path: Path,
    ticker: str,
    cik: str,
    url: str,
    schema_version: str,
    source_role: str,
    maximum_bytes: int,
    payload_identity: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    raw = _regular_file_bytes(raw_path, maximum_bytes=maximum_bytes)
    metadata = _read_json_object(metadata_path)
    status: dict[str, Any] = {
        "path": str(raw_path),
        "metadata_path": str(metadata_path),
        "present": raw is not None,
        "bytes": len(raw) if raw is not None else 0,
        "sha256": sha256_bytes(raw) if raw is not None else None,
        "metadata_identity_verified": False,
        "payload_identity_verified": False,
        "hash_verified": False,
        "verified": False,
    }
    if raw is None or metadata is None:
        return status
    expected_keys = {
        "schema_version",
        "ticker",
        "cik",
        "url",
        "content_type",
        "charset",
        "raw_sha256",
        "raw_bytes",
        "retrieved_at",
        "source_role",
    }
    metadata_identity = bool(
        set(metadata) == expected_keys
        and metadata.get("schema_version") == schema_version
        and metadata.get("ticker") == ticker
        and str(metadata.get("cik")) == cik
        and metadata.get("url") == url
        and metadata.get("source_role") == source_role
        and metadata.get("content_type") in JSON_CONTENT_TYPES
        and isinstance(metadata.get("charset"), str)
        and bool(metadata.get("charset"))
        and metadata.get("raw_bytes") == len(raw)
        and _valid_timestamp(metadata.get("retrieved_at"))
    )
    digest = sha256_bytes(raw)
    hash_verified = metadata.get("raw_sha256") == digest
    try:
        payload = _json_object(raw, label=raw_path.name)
        identity_verified = payload_identity(payload)
    except (CorpusError, TypeError, ValueError):
        identity_verified = False
    status.update(
        {
            "metadata_identity_verified": metadata_identity,
            "payload_identity_verified": identity_verified,
            "hash_verified": hash_verified,
            "verified": bool(
                metadata_identity and identity_verified and hash_verified
            ),
        }
    )
    return status


def validate_submission_snapshot(
    *,
    raw_path: Path,
    metadata_path: Path,
    ticker: str,
    cik: str,
) -> dict[str, Any]:
    return _snapshot_status(
        raw_path=raw_path,
        metadata_path=metadata_path,
        ticker=ticker,
        cik=cik,
        url=submissions_url(cik),
        schema_version=SUBMISSION_SCHEMA_VERSION,
        source_role="current_submission_history_cross_check_only",
        maximum_bytes=MAX_SUBMISSION_BYTES,
        payload_identity=lambda payload: (
            str(int(str(payload.get("cik", "0")))) == cik
            and isinstance(payload.get("filings"), dict)
            and isinstance(payload["filings"].get("recent"), dict)
        ),
    )


def validate_companyfacts_snapshot(
    *,
    raw_path: Path,
    metadata_path: Path,
    ticker: str,
    cik: str,
) -> dict[str, Any]:
    return _snapshot_status(
        raw_path=raw_path,
        metadata_path=metadata_path,
        ticker=ticker,
        cik=cik,
        url=companyfacts_url(cik),
        schema_version=COMPANYFACTS_SCHEMA_VERSION,
        source_role="current_companyfacts_cross_check_only_not_historical",
        maximum_bytes=MAX_COMPANYFACTS_BYTES,
        payload_identity=lambda payload: (
            str(int(str(payload.get("cik", "0")))) == cik
            and isinstance(payload.get("facts"), dict)
            and bool(payload["facts"])
        ),
    )


def _materialize_snapshot(
    *,
    context: AcquisitionContext,
    raw_path: Path,
    metadata_path: Path,
    ticker: str,
    cik: str,
    url: str,
    schema_version: str,
    source_role: str,
    maximum_bytes: int,
    validator: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    current = validator(
        raw_path=raw_path,
        metadata_path=metadata_path,
        ticker=ticker,
        cik=cik,
    )
    if current["verified"]:
        return current
    result = context.fetch(
        url=url,
        maximum_bytes=maximum_bytes,
        allowed_hosts=frozenset({DATA_SEC_HOST}),
        allowed_content_types=JSON_CONTENT_TYPES,
    )
    payload = _json_object(result.raw_bytes, label=schema_version)
    try:
        payload_cik = str(int(str(payload.get("cik", "0"))))
    except ValueError as exc:
        raise CorpusError("SEC JSON payload CIK is invalid") from exc
    if payload_cik != cik:
        raise CorpusError("SEC JSON payload CIK does not match selected issuer")
    atomic_write_bytes(raw_path, result.raw_bytes)
    atomic_write_json(
        metadata_path,
        {
            "schema_version": schema_version,
            "ticker": ticker,
            "cik": cik,
            "url": url,
            "content_type": result.content_type,
            "charset": result.charset,
            "raw_sha256": sha256_bytes(result.raw_bytes),
            "raw_bytes": len(result.raw_bytes),
            "retrieved_at": utc_now(),
            "source_role": source_role,
        },
    )
    verified = validator(
        raw_path=raw_path,
        metadata_path=metadata_path,
        ticker=ticker,
        cik=cik,
    )
    if not verified["verified"]:
        raise CorpusError("materialized SEC JSON snapshot failed validation")
    return verified


def materialize_submission_snapshot(
    *,
    context: AcquisitionContext,
    corpus_root: Path,
    ticker: str,
    cik: str,
) -> dict[str, Any]:
    paths = submission_paths(corpus_root, cik)
    return _materialize_snapshot(
        context=context,
        raw_path=paths["raw"],
        metadata_path=paths["metadata"],
        ticker=ticker,
        cik=cik,
        url=submissions_url(cik),
        schema_version=SUBMISSION_SCHEMA_VERSION,
        source_role="current_submission_history_cross_check_only",
        maximum_bytes=MAX_SUBMISSION_BYTES,
        validator=validate_submission_snapshot,
    )


def materialize_companyfacts_snapshot(
    *,
    context: AcquisitionContext,
    corpus_root: Path,
    ticker: str,
    cik: str,
) -> dict[str, Any]:
    paths = companyfacts_paths(corpus_root, ticker)
    return _materialize_snapshot(
        context=context,
        raw_path=paths["raw"],
        metadata_path=paths["metadata"],
        ticker=ticker,
        cik=cik,
        url=companyfacts_url(cik),
        schema_version=COMPANYFACTS_SCHEMA_VERSION,
        source_role="current_companyfacts_cross_check_only_not_historical",
        maximum_bytes=MAX_COMPANYFACTS_BYTES,
        validator=validate_companyfacts_snapshot,
    )


class _FilingDocumentTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_target_table = False
        self.table_depth = 0
        self.in_row = False
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.cell_href: str | None = None
        self.row_cells: list[dict[str, str | None]] = []
        self.rows: list[dict[str, Any]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "table":
            if self.in_target_table:
                self.table_depth += 1
            elif attributes.get("summary") == "Document Format Files":
                self.in_target_table = True
                self.table_depth = 1
            return
        if not self.in_target_table:
            return
        if tag == "tr":
            self.in_row = True
            self.row_cells = []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.cell_parts = []
            self.cell_href = None
        elif tag == "a" and self.in_cell and self.cell_href is None:
            href = attributes.get("href")
            if isinstance(href, str):
                self.cell_href = href

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.in_target_table:
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_target_table = False
            return
        if not self.in_target_table:
            return
        if tag in {"td", "th"} and self.in_cell:
            text = re.sub(r"\s+", " ", " ".join(self.cell_parts)).strip()
            self.row_cells.append({"text": text, "href": self.cell_href})
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self._finish_row()
            self.in_row = False

    def _finish_row(self) -> None:
        if len(self.row_cells) < 5:
            return
        sequence, description, document_cell, document_type, size = (
            self.row_cells[:5]
        )
        if sequence["text"].lower() == "seq":
            return
        href = document_cell["href"]
        document = document_cell["text"]
        if not href or not document:
            return
        size_text = size["text"].replace(",", "").strip()
        if size_text and not size_text.isdigit():
            raise CorpusError("SEC filing index declares a non-numeric size")
        self.rows.append(
            {
                "sequence": sequence["text"],
                "description": description["text"],
                "document": document,
                "type": document_type["text"],
                "declared_size_bytes": int(size_text) if size_text else None,
                "href": href,
            }
        )


def _archive_document_url(
    href: str, *, cik: str, accession: str, document: str
) -> str:
    try:
        parsed = urlsplit(href.strip())
    except ValueError as exc:
        raise CorpusError("SEC filing-index document link is invalid") from exc
    if parsed.scheme:
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() not in ARCHIVE_SEC_HOSTS
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise CorpusError("SEC filing-index document link escaped allowlist")
        path = parsed.path
        query = parsed.query
    else:
        if not href.startswith("/") or parsed.netloc or parsed.fragment:
            raise CorpusError("SEC filing-index document link is not absolute")
        path = parsed.path
        query = parsed.query
    if path == "/ix":
        query_values = parse_qs(query, strict_parsing=True)
        if set(query_values) != {"doc"} or len(query_values["doc"]) != 1:
            raise CorpusError("SEC inline-XBRL link query is invalid")
        path = query_values["doc"][0]
        query = ""
    if query:
        raise CorpusError("SEC archive document link has an unexpected query")
    decoded = unquote(path)
    if decoded != path or "\\" in decoded:
        raise CorpusError("SEC archive document link has unsafe encoding")
    segments = [part for part in path.split("/") if part]
    if (
        len(segments) != 6
        or segments[:3] != ["Archives", "edgar", "data"]
        or not segments[3].isdigit()
        or int(segments[3]) != int(cik)
        or segments[4] != accession.replace("-", "")
        or segments[5] != document
    ):
        raise CorpusError("SEC archive document identity mismatch")
    safe_token(document, "SEC exhibit document")
    return f"https://www.sec.gov{path}"


def _document_name_from_href(href: str) -> str:
    try:
        parsed = urlsplit(href.strip())
    except ValueError as exc:
        raise CorpusError("SEC filing-index document link is invalid") from exc
    path = parsed.path
    if path == "/ix":
        query_values = parse_qs(parsed.query, strict_parsing=True)
        if set(query_values) != {"doc"} or len(query_values["doc"]) != 1:
            raise CorpusError("SEC inline-XBRL link query is invalid")
        path = query_values["doc"][0]
    decoded = unquote(path)
    if decoded != path or "\\" in decoded:
        raise CorpusError("SEC archive document link has unsafe encoding")
    document = Path(path).name
    return safe_token(document, "SEC index document")


def parse_filing_index_documents(
    index_raw: bytes, *, cik: str, accession: str
) -> list[dict[str, Any]]:
    parser = _FilingDocumentTableParser()
    try:
        parser.feed(index_raw.decode("utf-8", errors="replace"))
        parser.close()
    except (CorpusError, ValueError) as exc:
        raise CorpusError("SEC filing document table is malformed") from exc
    if not parser.rows or len(parser.rows) > MAX_INDEX_DOCUMENT_ROWS:
        raise CorpusError("SEC filing index document-row count is invalid")
    normalized: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in parser.rows:
        document = _document_name_from_href(str(row["href"]))
        url = _archive_document_url(
            str(row["href"]),
            cik=cik,
            accession=accession,
            document=document,
        )
        if url in seen_urls:
            raise CorpusError("SEC filing index repeats a document URL")
        seen_urls.add(url)
        normalized.append(
            {
                "sequence": str(row["sequence"]),
                "description": str(row["description"]),
                "document": document,
                "type": str(row["type"]),
                "declared_size_bytes": row["declared_size_bytes"],
                "url": url,
            }
        )
    return normalized


def _exhibit_rows(
    index_raw: bytes, *, cik: str, accession: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = parse_filing_index_documents(
        index_raw, cik=cik, accession=accession
    )
    exhibits = [
        row for row in rows if str(row["type"]).upper().startswith("EX-")
    ]
    return rows, exhibits


def _exhibit_filename(sequence: str, document: str) -> str:
    normalized_sequence = re.sub(r"[^A-Za-z0-9_-]", "_", sequence) or "none"
    return safe_token(
        f"{normalized_sequence}_{document}", "local SEC exhibit filename"
    )


def materialize_exhibit_manifest(
    *,
    context: AcquisitionContext,
    corpus_root: Path,
    row: dict[str, str],
    index_raw: bytes,
    index_sha256: str,
) -> dict[str, Any]:
    filing_directory = filing_paths(corpus_root, row)["directory"]
    exhibit_directory = filing_directory / "exhibits"
    manifest_path = exhibit_directory / "exhibit_manifest.json"
    current = validate_exhibit_manifest(
        manifest_path=manifest_path,
        exhibit_directory=exhibit_directory,
        corpus_root=corpus_root,
        row=row,
        index_raw=index_raw,
        index_sha256=index_sha256,
    )
    if current["verified"]:
        return current

    document_rows, exhibits = _exhibit_rows(
        index_raw, cik=row["cik"], accession=row["accession"]
    )
    documents: list[dict[str, Any]] = []
    for exhibit in exhibits:
        local_path = exhibit_directory / _exhibit_filename(
            exhibit["sequence"], exhibit["document"]
        )
        raw: bytes | None = None
        prior_manifest = _read_json_object(manifest_path)
        if prior_manifest is not None:
            prior = next(
                (
                    item
                    for item in prior_manifest.get("documents", [])
                    if isinstance(item, dict)
                    and item.get("url") == exhibit["url"]
                    and item.get("sha256")
                    and item.get("relative_path")
                    == safe_relative_path(local_path, corpus_root)
                ),
                None,
            )
            if prior is not None:
                candidate = _regular_file_bytes(
                    local_path, maximum_bytes=MAX_EXHIBIT_BYTES
                )
                if (
                    candidate is not None
                    and sha256_bytes(candidate) == prior.get("sha256")
                ):
                    raw = candidate
                    content_type = str(prior.get("content_type", ""))
                    charset = str(prior.get("charset", "utf-8"))
        if raw is None:
            result = context.fetch(
                url=exhibit["url"],
                maximum_bytes=MAX_EXHIBIT_BYTES,
                allowed_hosts=ARCHIVE_SEC_HOSTS,
                allowed_content_types=EXHIBIT_CONTENT_TYPES,
            )
            raw = result.raw_bytes
            content_type = result.content_type
            charset = result.charset
            atomic_write_bytes(local_path, raw)
        declared_size = exhibit["declared_size_bytes"]
        if declared_size is not None and declared_size != len(raw):
            raise CorpusError("SEC exhibit bytes differ from filing-index size")
        documents.append(
            {
                **exhibit,
                "relative_path": safe_relative_path(local_path, corpus_root),
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
                "content_type": content_type,
                "charset": charset,
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": EXHIBIT_MANIFEST_SCHEMA_VERSION,
        "parser_version": INDEX_PARSER_VERSION,
        "ticker": row["ticker"],
        "cik": row["cik"],
        "accession": row["accession"],
        "source_filing_index_sha256": index_sha256,
        "source_document_table_sha256": canonical_sha256(document_rows),
        "source_document_count": len(document_rows),
        "discovered_exhibit_count": len(exhibits),
        "discovery_complete": True,
        "documents": documents,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    atomic_write_json(manifest_path, manifest)
    verified = validate_exhibit_manifest(
        manifest_path=manifest_path,
        exhibit_directory=exhibit_directory,
        corpus_root=corpus_root,
        row=row,
        index_raw=index_raw,
        index_sha256=index_sha256,
    )
    if not verified["verified"]:
        raise CorpusError("materialized SEC exhibit manifest failed validation")
    return verified


def validate_exhibit_manifest(
    *,
    manifest_path: Path,
    exhibit_directory: Path,
    corpus_root: Path,
    row: dict[str, str],
    index_raw: bytes,
    index_sha256: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "present": False,
        "discovery_complete": False,
        "binding_verified": False,
        "declared_file_count": 0,
        "verified_file_count": 0,
        "invalid_or_missing_file_count": 0,
        "verified": False,
    }
    payload = _read_json_object(manifest_path)
    if payload is None:
        return result
    result["present"] = True
    expected_keys = {
        "schema_version",
        "parser_version",
        "ticker",
        "cik",
        "accession",
        "source_filing_index_sha256",
        "source_document_table_sha256",
        "source_document_count",
        "discovered_exhibit_count",
        "discovery_complete",
        "documents",
        "manifest_sha256",
    }
    try:
        document_rows, expected_exhibits = _exhibit_rows(
            index_raw, cik=row["cik"], accession=row["accession"]
        )
    except CorpusError:
        return result
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return result
    result["declared_file_count"] = len(documents)
    binding_verified = bool(
        set(payload) == expected_keys
        and payload.get("schema_version") == EXHIBIT_MANIFEST_SCHEMA_VERSION
        and payload.get("parser_version") == INDEX_PARSER_VERSION
        and payload.get("ticker") == row["ticker"]
        and str(payload.get("cik")) == row["cik"]
        and payload.get("accession") == row["accession"]
        and payload.get("source_filing_index_sha256") == index_sha256
        and payload.get("source_document_table_sha256")
        == canonical_sha256(document_rows)
        and payload.get("source_document_count") == len(document_rows)
        and payload.get("discovered_exhibit_count") == len(expected_exhibits)
        and payload.get("discovery_complete") is True
        and _self_hash_verified(payload, "manifest_sha256")
    )
    invalid = 0
    verified = 0
    if len(documents) != len(expected_exhibits):
        invalid += abs(len(documents) - len(expected_exhibits)) or 1
    for index, expected in enumerate(expected_exhibits):
        if index >= len(documents) or not isinstance(documents[index], dict):
            invalid += 1
            continue
        document = documents[index]
        expected_document_keys = {
            "sequence",
            "description",
            "document",
            "type",
            "declared_size_bytes",
            "url",
            "relative_path",
            "sha256",
            "bytes",
            "content_type",
            "charset",
        }
        if (
            set(document) != expected_document_keys
            or any(document.get(key) != value for key, value in expected.items())
            or document.get("content_type") not in EXHIBIT_CONTENT_TYPES
            or not isinstance(document.get("charset"), str)
        ):
            invalid += 1
            continue
        relative = Path(str(document.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            invalid += 1
            continue
        path = corpus_root / relative
        try:
            path.resolve().relative_to(exhibit_directory.resolve())
        except ValueError:
            invalid += 1
            continue
        raw = _regular_file_bytes(path, maximum_bytes=MAX_EXHIBIT_BYTES)
        if (
            raw is None
            or document.get("bytes") != len(raw)
            or document.get("sha256") != sha256_bytes(raw)
            or (
                expected["declared_size_bytes"] is not None
                and expected["declared_size_bytes"] != len(raw)
            )
        ):
            invalid += 1
            continue
        verified += 1
    result.update(
        {
            "discovery_complete": bool(
                binding_verified and invalid == 0
            ),
            "binding_verified": binding_verified,
            "verified_file_count": verified,
            "invalid_or_missing_file_count": invalid,
            "verified": bool(binding_verified and invalid == 0),
        }
    )
    return result


def _iter_companyfacts(
    payload: dict[str, Any],
) -> Iterable[dict[str, Any]]:
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise CorpusError("Company Facts payload lacks facts")
    ordinal = 0
    for namespace in sorted(facts):
        concepts = facts[namespace]
        if not isinstance(concepts, dict):
            raise CorpusError("Company Facts namespace is invalid")
        for concept in sorted(concepts):
            definition = concepts[concept]
            if not isinstance(definition, dict):
                raise CorpusError("Company Facts concept is invalid")
            units = definition.get("units")
            if not isinstance(units, dict):
                raise CorpusError("Company Facts concept units are invalid")
            for unit in sorted(units):
                records = units[unit]
                if not isinstance(records, list):
                    raise CorpusError("Company Facts unit records are invalid")
                for source_index, record in enumerate(records):
                    ordinal += 1
                    if not isinstance(record, dict):
                        raise CorpusError("Company Facts record is invalid")
                    value = record.get("val")
                    if (
                        isinstance(value, bool)
                        or value is None
                        or isinstance(value, (list, dict))
                        or (
                            isinstance(value, float)
                            and not math.isfinite(value)
                        )
                    ):
                        raise CorpusError("Company Facts value is invalid")
                    yield {
                        "source_ordinal": ordinal,
                        "source_unit_index": source_index,
                        "namespace": namespace,
                        "concept": concept,
                        "label": str(definition.get("label", "")),
                        "unit": unit,
                        "start": record.get("start"),
                        "end": record.get("end"),
                        "val": value,
                        "accn": str(record.get("accn", "")),
                        "filed": str(record.get("filed", "")),
                        "form": str(record.get("form", "")),
                        "fy": record.get("fy"),
                        "fp": record.get("fp"),
                        "frame": record.get("frame"),
                    }


def build_xbrl_reconciliation(
    *,
    row: dict[str, str],
    accepted_at_et: str,
    primary_raw: bytes,
    companyfacts_raw: bytes,
) -> dict[str, Any]:
    try:
        accepted = datetime.fromisoformat(accepted_at_et)
    except ValueError as exc:
        raise CorpusError("XBRL reconciliation acceptance time is invalid") from exc
    if accepted.tzinfo is None:
        raise CorpusError("XBRL reconciliation acceptance time lacks timezone")
    accepted_day = accepted.date()
    companyfacts = _json_object(
        companyfacts_raw, label="SEC Company Facts"
    )
    try:
        payload_cik = str(int(str(companyfacts.get("cik", "0"))))
    except ValueError as exc:
        raise CorpusError("Company Facts CIK is invalid") from exc
    if payload_cik != row["cik"]:
        raise CorpusError("Company Facts CIK does not match filing")

    all_facts = list(_iter_companyfacts(companyfacts))
    exact_filed_days: set[date] = set()
    for fact in all_facts:
        if fact["accn"] != row["accession"]:
            continue
        try:
            exact_filed_days.add(date.fromisoformat(fact["filed"]))
        except ValueError as exc:
            raise CorpusError("Company Facts filed date is invalid") from exc
    if len(exact_filed_days) != 1:
        raise CorpusError(
            "accession-bound Company Facts have no single SEC filed date"
        )
    exact_filed_day = next(iter(exact_filed_days))
    # Company Facts can assign the following calendar day to an accession
    # accepted late in the SEC filing-index day.  Exact accession identity is
    # authoritative; tolerate only that one-day convention, never a later
    # revision.
    if exact_filed_day > accepted_day + timedelta(days=1):
        raise CorpusError(
            "accession-bound Company Facts postdate acceptance by over one day"
        )

    selected: list[dict[str, Any]] = []
    raw_record_count = len(all_facts)
    excluded_future_count = 0
    excluded_other_accession_count = 0
    for fact in all_facts:
        try:
            filed_day = date.fromisoformat(fact["filed"])
        except ValueError as exc:
            raise CorpusError("Company Facts filed date is invalid") from exc
        if fact["accn"] != row["accession"]:
            if filed_day > accepted_day:
                excluded_future_count += 1
            else:
                excluded_other_accession_count += 1
            continue
        if filed_day != exact_filed_day:
            raise CorpusError(
                "accession-bound Company Facts filed dates conflict"
            )
        if filed_day > accepted_day + timedelta(days=1):
            excluded_future_count += 1
            continue
        fact_record = dict(fact)
        fact_record["fact_id"] = canonical_sha256(fact_record)
        selected.append(fact_record)
    selected.sort(
        key=lambda fact: (
            fact["namespace"],
            fact["concept"],
            fact["unit"],
            str(fact["start"]),
            str(fact["end"]),
            fact["source_ordinal"],
        )
    )
    if not selected:
        raise CorpusError("no accession-bound Company Facts survived PIT filter")
    primary_lower = primary_raw.lower()
    matched_concepts = sorted(
        {
            fact["concept"]
            for fact in selected
            if fact["concept"].encode("utf-8").lower() in primary_lower
        }
    )
    if not matched_concepts:
        raise CorpusError(
            "accession-bound Company Facts do not appear in the primary filing"
        )
    reconciliation: dict[str, Any] = {
        "schema_version": XBRL_RECONCILIATION_SCHEMA_VERSION,
        "ticker": row["ticker"],
        "cik": row["cik"],
        "accession": row["accession"],
        "form": row["form"],
        "accepted_at_et": accepted_at_et,
        "selection_rule": (
            "exact_accession_with_sec_filed_date_at_most_acceptance_plus_one_day_v1"
        ),
        "source_primary_sha256": sha256_bytes(primary_raw),
        "source_companyfacts_sha256": sha256_bytes(companyfacts_raw),
        "source_companyfacts_url": companyfacts_url(row["cik"]),
        "raw_unit_record_count": raw_record_count,
        "excluded_future_record_count": excluded_future_count,
        "excluded_other_accession_record_count": (
            excluded_other_accession_count
        ),
        "matching_fact_count": len(selected),
        "facts_sha256": canonical_sha256(selected),
        "primary_matched_concepts": matched_concepts,
        "primary_concept_match_count": len(matched_concepts),
        "future_facts_excluded": True,
        "facts": selected,
    }
    reconciliation["reconciliation_sha256"] = canonical_sha256(
        reconciliation
    )
    return reconciliation


def validate_xbrl_reconciliation(
    *,
    path: Path,
    row: dict[str, str],
    accepted_at_et: str,
    primary_raw: bytes,
    companyfacts_raw: bytes,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "present": False,
        "identity_verified": False,
        "primary_binding_verified": False,
        "companyfacts_binding_verified": False,
        "future_facts_excluded": False,
        "matching_fact_count": 0,
        "verified": False,
    }
    payload = _read_json_object(path)
    if payload is None:
        return result
    result["present"] = True
    try:
        expected = build_xbrl_reconciliation(
            row=row,
            accepted_at_et=accepted_at_et,
            primary_raw=primary_raw,
            companyfacts_raw=companyfacts_raw,
        )
    except CorpusError:
        return result
    identity = bool(
        payload.get("schema_version") == XBRL_RECONCILIATION_SCHEMA_VERSION
        and payload.get("ticker") == row["ticker"]
        and str(payload.get("cik")) == row["cik"]
        and payload.get("accession") == row["accession"]
        and payload.get("form") == row["form"]
        and payload.get("accepted_at_et") == accepted_at_et
    )
    primary_binding = (
        payload.get("source_primary_sha256") == sha256_bytes(primary_raw)
    )
    companyfacts_binding = (
        payload.get("source_companyfacts_sha256")
        == sha256_bytes(companyfacts_raw)
    )
    exact = payload == expected
    result.update(
        {
            "identity_verified": identity,
            "primary_binding_verified": primary_binding,
            "companyfacts_binding_verified": companyfacts_binding,
            "future_facts_excluded": (
                payload.get("future_facts_excluded") is True
            ),
            "matching_fact_count": payload.get("matching_fact_count", 0),
            "verified": bool(
                exact
                and identity
                and primary_binding
                and companyfacts_binding
                and payload.get("future_facts_excluded") is True
                and isinstance(payload.get("matching_fact_count"), int)
                and payload["matching_fact_count"] > 0
                and _self_hash_verified(
                    payload, "reconciliation_sha256"
                )
            ),
        }
    )
    return result


def materialize_xbrl_reconciliation(
    *,
    corpus_root: Path,
    row: dict[str, str],
    accepted_at_et: str,
    primary_raw: bytes,
    companyfacts_raw: bytes,
) -> dict[str, Any]:
    path = filing_paths(corpus_root, row)["directory"] / (
        "xbrl_reconciliation.json"
    )
    current = validate_xbrl_reconciliation(
        path=path,
        row=row,
        accepted_at_et=accepted_at_et,
        primary_raw=primary_raw,
        companyfacts_raw=companyfacts_raw,
    )
    if current["verified"]:
        return current
    payload = build_xbrl_reconciliation(
        row=row,
        accepted_at_et=accepted_at_et,
        primary_raw=primary_raw,
        companyfacts_raw=companyfacts_raw,
    )
    atomic_write_json(path, payload)
    verified = validate_xbrl_reconciliation(
        path=path,
        row=row,
        accepted_at_et=accepted_at_et,
        primary_raw=primary_raw,
        companyfacts_raw=companyfacts_raw,
    )
    if not verified["verified"]:
        raise CorpusError("materialized XBRL reconciliation failed validation")
    return verified


def _load_filing_sources(
    corpus_root: Path, row: dict[str, str]
) -> tuple[bytes, bytes, dict[str, Any]]:
    paths = filing_paths(corpus_root, row)
    metadata = _read_json_object(paths["metadata"])
    primary = _regular_file_bytes(
        paths["primary"], maximum_bytes=MAX_PRIMARY_BYTES
    )
    index_raw = _regular_file_bytes(
        paths["index"], maximum_bytes=5 * 1024 * 1024
    )
    if metadata is None or primary is None or index_raw is None:
        raise CorpusError("strict pilot filing source is incomplete")
    if (
        metadata.get("ticker") != row["ticker"]
        or str(metadata.get("cik")) != row["cik"]
        or metadata.get("accession") != row["accession"]
        or metadata.get("primary_url") != row["source_url"]
        or metadata.get("index_url") != row["index_url"]
        or metadata.get("primary_raw_sha256") != sha256_bytes(primary)
        or metadata.get("index_raw_sha256") != sha256_bytes(index_raw)
        or not _valid_timestamp(metadata.get("accepted_at_et"))
    ):
        raise CorpusError("strict pilot filing source binding is invalid")
    return primary, index_raw, metadata


def _exhibit_scope(row: dict[str, str], items: Iterable[str] = ()) -> bool:
    return row["form"] in EXHIBIT_DISCOVERY_FORMS or "9.01" in set(items)


def _pilot_rows(
    *,
    ledger_path: Path,
    target_packet_count: int,
    candidate_padding: int,
    pilot_packet_count: int,
    ledger_snapshot_sha256: str | None = None,
    ledger_snapshot_distinct_accessions: int | None = None,
) -> list[dict[str, str]]:
    if pilot_packet_count <= 0 or pilot_packet_count > target_packet_count:
        raise CorpusError("pilot packet count must be within target packets")
    selected = select_candidate_rows(
        read_ledger(
            ledger_path,
            expected_snapshot_sha256=ledger_snapshot_sha256,
            expected_snapshot_distinct_accessions=(
                ledger_snapshot_distinct_accessions
            ),
        ),
        target_packet_count=target_packet_count,
        candidate_padding=candidate_padding,
    )
    if len(selected) < pilot_packet_count:
        raise CorpusError("insufficient deterministic pilot candidates")
    return selected[:pilot_packet_count]


def audit_strict_pilot(
    *,
    ledger_path: Path = LEDGER_PATH,
    corpus_root: Path = CORPUS_ROOT,
    target_packet_count: int = DEFAULT_PILOT_PACKETS,
    candidate_padding: int = DEFAULT_CANDIDATE_PADDING,
    pilot_packet_count: int = DEFAULT_PILOT_PACKETS,
    ledger_snapshot_sha256: str | None = None,
    ledger_snapshot_distinct_accessions: int | None = None,
) -> dict[str, Any]:
    rows = _pilot_rows(
        ledger_path=ledger_path,
        target_packet_count=target_packet_count,
        candidate_padding=candidate_padding,
        pilot_packet_count=pilot_packet_count,
        ledger_snapshot_sha256=ledger_snapshot_sha256,
        ledger_snapshot_distinct_accessions=(
            ledger_snapshot_distinct_accessions
        ),
    )
    issuer_submission: dict[tuple[str, str], dict[str, Any]] = {}
    issuer_companyfacts: dict[tuple[str, str], dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for row in rows:
        identity = (row["ticker"], row["cik"])
        if identity not in issuer_submission:
            paths = submission_paths(corpus_root, row["cik"])
            issuer_submission[identity] = validate_submission_snapshot(
                raw_path=paths["raw"],
                metadata_path=paths["metadata"],
                ticker=row["ticker"],
                cik=row["cik"],
            )
        missing: list[str] = []
        if not issuer_submission[identity]["verified"]:
            missing.append("raw_submission_snapshot")
        try:
            primary, index_raw, metadata = _load_filing_sources(
                corpus_root, row
            )
        except CorpusError:
            records.append(
                {
                    "ticker": row["ticker"],
                    "cik": row["cik"],
                    "accession": row["accession"],
                    "form": row["form"],
                    "missing_artifacts": sorted(
                        set(missing + ["filing_source"])
                    ),
                    "locally_complete": False,
                }
            )
            continue
        if _exhibit_scope(row):
            exhibit_directory = filing_paths(corpus_root, row)[
                "directory"
            ] / "exhibits"
            exhibits = validate_exhibit_manifest(
                manifest_path=exhibit_directory / "exhibit_manifest.json",
                exhibit_directory=exhibit_directory,
                corpus_root=corpus_root,
                row=row,
                index_raw=index_raw,
                index_sha256=sha256_bytes(index_raw),
            )
            if not exhibits["verified"]:
                missing.append("exhibits")
        if row["form"] in XBRL_FORMS:
            if identity not in issuer_companyfacts:
                paths = companyfacts_paths(corpus_root, row["ticker"])
                issuer_companyfacts[identity] = validate_companyfacts_snapshot(
                    raw_path=paths["raw"],
                    metadata_path=paths["metadata"],
                    ticker=row["ticker"],
                    cik=row["cik"],
                )
            companyfacts_source = issuer_companyfacts[identity]
            if not companyfacts_source["verified"]:
                missing.append("xbrl_companyfacts")
            else:
                companyfacts_raw = companyfacts_paths(
                    corpus_root, row["ticker"]
                )["raw"].read_bytes()
                xbrl = validate_xbrl_reconciliation(
                    path=filing_paths(corpus_root, row)["directory"]
                    / "xbrl_reconciliation.json",
                    row=row,
                    accepted_at_et=str(metadata["accepted_at_et"]),
                    primary_raw=primary,
                    companyfacts_raw=companyfacts_raw,
                )
                if not xbrl["verified"]:
                    missing.append("xbrl_reconciliation")
        records.append(
            {
                "ticker": row["ticker"],
                "cik": row["cik"],
                "accession": row["accession"],
                "form": row["form"],
                "missing_artifacts": sorted(set(missing)),
                "locally_complete": not missing,
            }
        )
    complete_count = sum(record["locally_complete"] for record in records)
    report: dict[str, Any] = {
        "schema_version": STRICT_COMPLETION_SCHEMA_VERSION,
        "mode": "offline_read_only_check",
        "target_packet_count": pilot_packet_count,
        "selected_cohort_sha256": canonical_sha256(
            [
                {
                    "ticker": row["ticker"],
                    "cik": row["cik"],
                    "accession": row["accession"],
                    "form": row["form"],
                }
                for row in rows
            ]
        ),
        "locally_complete_packet_count": complete_count,
        "readiness_gate_passed": complete_count == pilot_packet_count,
        "records": records,
        "boundaries": {
            "network_used": False,
            "files_written": False,
            "model_used": False,
            "provider_used": False,
            "email_used": False,
            "smtp_used": False,
            "broker_used": False,
            "account_read": False,
            "order_code_created": False,
            "canonical_decision_effect": False,
        },
    }
    report["audit_sha256"] = canonical_sha256(report)
    return report


def complete_strict_pilot(
    *,
    user_agent: str,
    ledger_path: Path = LEDGER_PATH,
    corpus_root: Path = CORPUS_ROOT,
    target_packet_count: int = DEFAULT_PILOT_PACKETS,
    candidate_padding: int = DEFAULT_CANDIDATE_PADDING,
    pilot_packet_count: int = DEFAULT_PILOT_PACKETS,
    sec_requests_per_second: float = DEFAULT_SEC_REQUESTS_PER_SECOND,
    maximum_storage_bytes: int = DEFAULT_MAX_STORAGE_BYTES,
    fetcher: Fetcher = fetch_public_resource,
) -> dict[str, Any]:
    if not user_agent.strip() or "\n" in user_agent or "\r" in user_agent:
        raise CorpusError("strict pilot refresh requires a declared User-Agent")
    rows = _pilot_rows(
        ledger_path=ledger_path,
        target_packet_count=target_packet_count,
        candidate_padding=candidate_padding,
        pilot_packet_count=pilot_packet_count,
    )
    context = AcquisitionContext(
        user_agent=user_agent.strip(),
        limiter=RequestLimiter(sec_requests_per_second),
        fetcher=fetcher,
    )
    with storage_budget_scope(corpus_root, maximum_storage_bytes):
        for ticker, cik in sorted(
            {(row["ticker"], row["cik"]) for row in rows}
        ):
            materialize_submission_snapshot(
                context=context,
                corpus_root=corpus_root,
                ticker=ticker,
                cik=cik,
            )
        for ticker, cik in sorted(
            {
                (row["ticker"], row["cik"])
                for row in rows
                if row["form"] in XBRL_FORMS
            }
        ):
            materialize_companyfacts_snapshot(
                context=context,
                corpus_root=corpus_root,
                ticker=ticker,
                cik=cik,
            )
        for row in rows:
            primary, index_raw, metadata = _load_filing_sources(
                corpus_root, row
            )
            if _exhibit_scope(row):
                materialize_exhibit_manifest(
                    context=context,
                    corpus_root=corpus_root,
                    row=row,
                    index_raw=index_raw,
                    index_sha256=sha256_bytes(index_raw),
                )
            if row["form"] in XBRL_FORMS:
                companyfacts_raw = companyfacts_paths(
                    corpus_root, row["ticker"]
                )["raw"].read_bytes()
                materialize_xbrl_reconciliation(
                    corpus_root=corpus_root,
                    row=row,
                    accepted_at_et=str(metadata["accepted_at_et"]),
                    primary_raw=primary,
                    companyfacts_raw=companyfacts_raw,
                )
        audit = audit_strict_pilot(
            ledger_path=ledger_path,
            corpus_root=corpus_root,
            target_packet_count=target_packet_count,
            candidate_padding=candidate_padding,
            pilot_packet_count=pilot_packet_count,
        )
        if not audit["readiness_gate_passed"]:
            raise CorpusError("strict pilot remained incomplete after refresh")
        receipt: dict[str, Any] = {
            "schema_version": STRICT_COMPLETION_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "mode": "explicit_public_sec_strict_pilot_refresh",
            "target_packet_count": pilot_packet_count,
            "selected_cohort_sha256": audit["selected_cohort_sha256"],
            "request_count": context.request_count,
            "network_used": context.request_count > 0,
            "declared_user_agent_used": True,
            "user_agent_retained": False,
            "maximum_storage_bytes": maximum_storage_bytes,
            "readiness_gate_passed": True,
            "audit_sha256": audit["audit_sha256"],
            "boundaries": {
                "model_used": False,
                "provider_used": False,
                "email_used": False,
                "smtp_used": False,
                "broker_used": False,
                "account_read": False,
                "order_code_created": False,
                "canonical_decision_effect": False,
                "shadow_scheduler_installed": False,
            },
        }
        receipt["completion_sha256"] = canonical_sha256(receipt)
        atomic_write_json(
            corpus_root / "strict_pilot_completion.json", receipt
        )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--refresh", action="store_true")
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS_ROOT)
    parser.add_argument(
        "--target-packets", type=int, default=DEFAULT_PILOT_PACKETS
    )
    parser.add_argument(
        "--candidate-padding", type=int, default=DEFAULT_CANDIDATE_PADDING
    )
    parser.add_argument(
        "--pilot-packets", type=int, default=DEFAULT_PILOT_PACKETS
    )
    parser.add_argument("--user-agent", default="")
    parser.add_argument(
        "--sec-requests-per-second",
        type=float,
        default=DEFAULT_SEC_REQUESTS_PER_SECOND,
    )
    parser.add_argument(
        "--max-storage-bytes",
        type=int,
        default=DEFAULT_MAX_STORAGE_BYTES,
    )
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            report = audit_strict_pilot(
                ledger_path=args.ledger,
                corpus_root=args.corpus_root,
                target_packet_count=args.target_packets,
                candidate_padding=args.candidate_padding,
                pilot_packet_count=args.pilot_packets,
            )
            print(
                json.dumps(
                    report,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            return (
                0
                if report["readiness_gate_passed"]
                or not args.require_ready
                else 1
            )
        if not args.user_agent:
            parser.error("--refresh requires --user-agent")
        receipt = complete_strict_pilot(
            user_agent=args.user_agent,
            ledger_path=args.ledger,
            corpus_root=args.corpus_root,
            target_packet_count=args.target_packets,
            candidate_padding=args.candidate_padding,
            pilot_packet_count=args.pilot_packets,
            sec_requests_per_second=args.sec_requests_per_second,
            maximum_storage_bytes=args.max_storage_bytes,
        )
        print(
            "strict_pilot_refresh=passed "
            f"packets={receipt['target_packet_count']} "
            f"sec_requests={receipt['request_count']} "
            "model_used=false provider_used=false email_used=false "
            "smtp_used=false broker_used=false account_read=false "
            "order_code_created=false canonical_decision_effect=false"
        )
        return 0
    except (CorpusError, OSError, UnicodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": STRICT_COMPLETION_SCHEMA_VERSION,
                    "error_type": type(exc).__name__,
                    "boundaries": {
                        "model_used": False,
                        "provider_used": False,
                        "email_used": False,
                        "smtp_used": False,
                        "broker_used": False,
                        "account_read": False,
                        "order_code_created": False,
                        "canonical_decision_effect": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
