#!/usr/bin/env python3
"""Build and validate frozen dual-human claim-entailment reviews.

Citation reviews are bound to exact analyst claim hashes, so they can only be
completed after provider inference is quarantined.  The collector emits an
incomplete template; a provider-free finalize step validates the completed
artifact with this module and with the independent replay gate.

This module has no provider, network, email, SMTP, broker, order, or canonical
decision capability.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

from phase5r_llm_contract import (
    ContractError,
    _assert_no_imperative_action_language,
    _assert_no_sensitive_markers,
)
from verify_phase5r_llm_provider_replay_gate import (
    CITATION_REVIEW_SET_SCHEMA_VERSION,
    canonical_sha256,
    sha256_bytes,
)


REVIEW_METHOD = "independent_dual_human_review"
MAX_REVIEW_FILE_BYTES = 32 * 1024 * 1024
MAX_RATIONALE_CHARS = 20_000
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class CitationReviewError(ValueError):
    """A citation review set is absent, stale, incomplete, or non-human."""


def _exact_keys(value: Any, expected: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CitationReviewError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        extra = ",".join(sorted(actual - expected))
        raise CitationReviewError(
            f"{label} fields differ (missing={missing or 'none'}; "
            f"extra={extra or 'none'})"
        )
    return value


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise CitationReviewError(f"{label} must be a lowercase SHA-256")
    return value


def _sorted_ids(
    value: Any,
    *,
    label: str,
    allow_empty: bool = False,
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        qualifier = "" if allow_empty else "non-empty "
        raise CitationReviewError(
            f"{label} must be a {qualifier}sorted unique list"
        )
    return value


def _safe_rationale(text: Any, digest: Any, *, label: str) -> str:
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > MAX_RATIONALE_CHARS
    ):
        raise CitationReviewError(
            f"{label} must be inspectable non-empty UTF-8 text"
        )
    claimed = _sha256(digest, label=f"{label} hash")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != claimed:
        raise CitationReviewError(f"{label} hash does not match its text")
    try:
        _assert_no_sensitive_markers(text, label)
        _assert_no_imperative_action_language(
            {
                "headline": text,
                "decisive_advice": "",
                "long_term_portfolio_case": "",
                "dissent": [],
                "ticker_decisions": [],
            }
        )
    except ContractError as exc:
        raise CitationReviewError(
            f"{label} crosses the research-only boundary"
        ) from exc
    return text


def claim_evidence_bundle_sha256(
    expected_claims: list[dict[str, Any]],
) -> str:
    """Recompute the exact bundle identity used by the offline replay gate."""

    rows = [
        {
            "case_id": str(claim["case_id"]),
            "replay_packet_id": str(claim["packet_id"]),
            "runtime_packet_id": str(claim["runtime_packet_id"]),
            "claim_id": str(claim["claim_id"]),
            "claim_text_sha256": str(claim["claim_text_sha256"]),
            "cited_source_ids": sorted(claim["cited_source_ids"]),
            "materiality": str(claim["materiality"]),
        }
        for claim in expected_claims
    ]
    return canonical_sha256(
        sorted(rows, key=lambda row: (row["case_id"], row["claim_id"]))
    )


def build_citation_review_template(
    *,
    expected_claims: list[dict[str, Any]],
    corpus_manifest_sha256: str,
    annotation_set_sha256: str,
    generated_at: str,
) -> dict[str, Any]:
    """Return an intentionally incomplete artifact with no fabricated labels."""

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for claim in sorted(
        expected_claims,
        key=lambda row: (str(row["case_id"]), str(row["claim_id"])),
    ):
        key = (str(claim["case_id"]), str(claim["claim_id"]))
        if key in seen:
            raise CitationReviewError("expected citation claim is duplicated")
        seen.add(key)
        claim_text = str(claim["claim_text"])
        if (
            not claim_text.strip()
            or sha256_bytes(claim_text.encode("utf-8"))
            != claim["claim_text_sha256"]
        ):
            raise CitationReviewError("expected citation claim hash is stale")
        records.append(
            {
                "case_id": key[0],
                "packet_id": str(claim["packet_id"]),
                "claim_id": key[1],
                "claim_text_sha256": str(claim["claim_text_sha256"]),
                "cited_source_ids": sorted(claim["cited_source_ids"]),
                "reviewed_source_ids": [],
                "entailment_pass": None,
                "reviewers": [],
                "review_sha256": "",
            }
        )
    return {
        "schema_version": CITATION_REVIEW_SET_SCHEMA_VERSION,
        "generated_at": generated_at,
        "corpus_manifest_sha256": _sha256(
            corpus_manifest_sha256,
            label="corpus manifest hash",
        ),
        "annotation_set_sha256": _sha256(
            annotation_set_sha256,
            label="annotation set hash",
        ),
        "claim_evidence_bundle_sha256": claim_evidence_bundle_sha256(
            expected_claims
        ),
        "frozen": False,
        "review_method": REVIEW_METHOD,
        "records": records,
        "review_set_sha256": "",
    }


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise CitationReviewError("citation review file must not be a symlink")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise CitationReviewError("citation review file is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > MAX_REVIEW_FILE_BYTES
        or metadata.st_mode & 0o022
    ):
        raise CitationReviewError(
            "citation review file must be a private, non-writable regular file"
        )
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CitationReviewError(
            "citation review file is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise CitationReviewError("citation review file must contain one object")
    return payload, raw


def validate_citation_review_set(
    *,
    review_path: Path,
    expected_claims: list[dict[str, Any]],
    corpus_manifest_sha256: str,
    annotation_set_sha256: str,
    expected_file_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return exact gate review rows after independent human validation."""

    expected_raw = _sha256(
        expected_file_sha256,
        label="acknowledged citation review file hash",
    )
    payload, raw = _read_json(review_path)
    raw_hash = sha256_bytes(raw)
    if raw_hash != expected_raw:
        raise CitationReviewError(
            "citation review file differs from its acknowledged raw hash"
        )
    _exact_keys(
        payload,
        {
            "schema_version",
            "generated_at",
            "corpus_manifest_sha256",
            "annotation_set_sha256",
            "claim_evidence_bundle_sha256",
            "frozen",
            "review_method",
            "records",
            "review_set_sha256",
        },
        label="citation review set",
    )
    expected_bundle = claim_evidence_bundle_sha256(expected_claims)
    if (
        payload["schema_version"] != CITATION_REVIEW_SET_SCHEMA_VERSION
        or payload["corpus_manifest_sha256"] != corpus_manifest_sha256
        or payload["annotation_set_sha256"] != annotation_set_sha256
        or payload["claim_evidence_bundle_sha256"] != expected_bundle
        or payload["frozen"] is not True
        or payload["review_method"] != REVIEW_METHOD
    ):
        raise CitationReviewError(
            "citation review set is not frozen or its evidence binding is stale"
        )
    claimed_set_hash = _sha256(
        payload["review_set_sha256"],
        label="citation review set hash",
    )
    unsigned = dict(payload)
    unsigned.pop("review_set_sha256")
    if canonical_sha256(unsigned) != claimed_set_hash:
        raise CitationReviewError("citation review-set content hash mismatch")

    expected_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in expected_claims:
        key = (str(claim["case_id"]), str(claim["claim_id"]))
        if key in expected_by_key:
            raise CitationReviewError("expected citation claim is duplicated")
        expected_by_key[key] = claim
    records = payload["records"]
    if not isinstance(records, list):
        raise CitationReviewError("citation review records must be a list")
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(records):
        record = _exact_keys(
            value,
            {
                "case_id",
                "packet_id",
                "claim_id",
                "claim_text_sha256",
                "cited_source_ids",
                "reviewed_source_ids",
                "entailment_pass",
                "reviewers",
                "review_sha256",
            },
            label=f"citation review record {index}",
        )
        key = (str(record["case_id"]), str(record["claim_id"]))
        expected = expected_by_key.get(key)
        if expected is None or key in seen:
            raise CitationReviewError(
                "citation review claim identity is missing or duplicated"
            )
        seen.add(key)
        cited = _sorted_ids(
            record["cited_source_ids"],
            label="citation review cited sources",
        )
        reviewed = _sorted_ids(
            record["reviewed_source_ids"],
            label="citation review inspected sources",
        )
        known = set(expected["known_source_ids"])
        required = set(expected["required_review_source_ids"])
        if (
            record["packet_id"] != expected["packet_id"]
            or record["claim_text_sha256"] != expected["claim_text_sha256"]
            or cited != expected["cited_source_ids"]
            or not set(reviewed).issubset(known)
            or not required.issubset(reviewed)
            or record["entailment_pass"] is not True
        ):
            raise CitationReviewError(
                "citation review is stale, incomplete, or did not pass"
            )
        reviewers = record["reviewers"]
        if not isinstance(reviewers, list) or len(reviewers) < 2:
            raise CitationReviewError(
                "each claim requires two independent human reviewers"
            )
        reviewer_ids: set[str] = set()
        for reviewer_index, reviewer_value in enumerate(reviewers):
            reviewer = _exact_keys(
                reviewer_value,
                {
                    "reviewer_id_sha256",
                    "reviewer_kind",
                    "entailed",
                    "rationale",
                    "rationale_sha256",
                },
                label=(
                    f"citation review {index} reviewer {reviewer_index}"
                ),
            )
            reviewer_id = _sha256(
                reviewer["reviewer_id_sha256"],
                label="citation reviewer identity hash",
            )
            if reviewer_id in reviewer_ids:
                raise CitationReviewError(
                    "citation reviewer identities must be independent"
                )
            reviewer_ids.add(reviewer_id)
            if (
                reviewer["reviewer_kind"] != "human"
                or reviewer["entailed"] is not True
            ):
                raise CitationReviewError(
                    "citation review must be independently human-attested"
                )
            _safe_rationale(
                reviewer["rationale"],
                reviewer["rationale_sha256"],
                label=f"citation reviewer {reviewer_index} rationale",
            )
        claimed_review_hash = _sha256(
            record["review_sha256"],
            label="citation review content hash",
        )
        unsigned_review = dict(record)
        unsigned_review.pop("review_sha256")
        if canonical_sha256(unsigned_review) != claimed_review_hash:
            raise CitationReviewError("citation review content hash is stale")
    if seen != set(expected_by_key):
        raise CitationReviewError(
            "citation reviews do not cover every material analyst claim"
        )
    binding = {
        "review_file_sha256": raw_hash,
        "review_set_sha256": claimed_set_hash,
        "claim_evidence_bundle_sha256": expected_bundle,
        "review_count": len(records),
        "frozen": True,
        "review_method": REVIEW_METHOD,
        "independent_dual_review": True,
    }
    return records, binding
