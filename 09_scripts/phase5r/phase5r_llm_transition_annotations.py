#!/usr/bin/env python3
"""Validate frozen, independently dual-reviewed replay annotations.

The real-source replay corpus deliberately contains no investment-decision
labels.  Provider quality may be scored only after a separate annotation file
has been completed by at least two independent human reviewers and frozen by
content hashes.  This module performs that offline validation and derives the
smaller annotation objects consumed by the provider replay gate.

It has no provider, network, email, SMTP, broker, order, or canonical-decision
capability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from phase5r_daily_common import ROOT
from phase5r_llm_contract import (
    ContractError,
    NO_ACTION_CLASSIFICATIONS,
    RESEARCH_CLASSIFICATIONS,
    TRANSITION_CLASSIFICATIONS,
    _assert_no_imperative_action_language,
    _assert_no_sensitive_markers,
)
from verify_phase5r_llm_provider_replay_gate import (
    CORPUS_MANIFEST_PATH,
    MANIFEST_SCHEMA_VERSION,
    MINIMUM_MATERIAL_TRANSITIONS,
    MINIMUM_REAL_ISSUERS,
    MINIMUM_REAL_PACKETS,
    REFERENCE_RUBRIC_VERSION,
    ReplayGateError,
    _load_corpus,
    canonical_sha256,
    sha256_bytes,
)


ANNOTATION_SET_SCHEMA_VERSION = "phase5r_material_transition_annotation_set_v2"
DEFAULT_RUBRIC_PATH = (
    ROOT
    / "00_project_control"
    / "phase5r_llm_transition_annotation_rubric.md"
)
DEFAULT_ANNOTATION_PATH = (
    ROOT
    / "08_reviews"
    / "phase5r_llm_transition_annotations"
    / "v1"
    / "phase5r_material_transition_annotations.json"
)
MAX_ANNOTATION_BYTES = 16 * 1024 * 1024
MAX_RUBRIC_BYTES = 512 * 1024
MAX_RATIONALE_CHARS = 20_000
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class AnnotationError(ValueError):
    """A frozen annotation set is absent, stale, or not independently reviewed."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AnnotationError("annotation value cannot be canonically serialized") from exc
    return rendered.encode("utf-8")


def _exact_keys(value: Any, expected: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AnnotationError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        extra = ",".join(sorted(actual - expected))
        raise AnnotationError(
            f"{label} fields differ (missing={missing or 'none'}; "
            f"extra={extra or 'none'})"
        )
    return value


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise AnnotationError(f"{label} must be a lowercase SHA-256")
    return value


def _timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise AnnotationError(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AnnotationError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise AnnotationError(f"{label} must include a timezone")
    return parsed


def _rationale(
    text_value: Any,
    digest_value: Any,
    *,
    label: str,
) -> str:
    if (
        not isinstance(text_value, str)
        or not text_value.strip()
        or len(text_value) > MAX_RATIONALE_CHARS
    ):
        raise AnnotationError(
            f"{label} must be inspectable non-empty UTF-8 text"
        )
    digest = _sha256(digest_value, label=f"{label} hash")
    if hashlib.sha256(text_value.encode("utf-8")).hexdigest() != digest:
        raise AnnotationError(f"{label} hash does not match its text")
    try:
        _assert_no_sensitive_markers(text_value, label)
        _assert_no_imperative_action_language(
            {
                "headline": text_value,
                "decisive_advice": "",
                "long_term_portfolio_case": "",
                "dissent": [],
                "ticker_decisions": [],
            }
        )
    except ContractError as exc:
        raise AnnotationError(
            f"{label} crosses the public research boundary"
        ) from exc
    return text_value


def _validate_rubric(value: Any) -> dict[str, str]:
    rubric = _exact_keys(
        value,
        {"version", "relative_path", "file_sha256"},
        label="annotation rubric binding",
    )
    expected_relative = DEFAULT_RUBRIC_PATH.relative_to(ROOT).as_posix()
    if (
        rubric["version"] != REFERENCE_RUBRIC_VERSION
        or rubric["relative_path"] != expected_relative
    ):
        raise AnnotationError("annotation rubric path or version is not frozen")
    expected_hash = _sha256(
        rubric["file_sha256"], label="annotation rubric file hash"
    )
    rubric_path = ROOT / expected_relative
    if rubric_path.is_symlink():
        raise AnnotationError("annotation rubric must not be a symlink")
    try:
        metadata = rubric_path.stat()
        raw = rubric_path.read_bytes()
    except OSError as exc:
        raise AnnotationError("annotation rubric is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > MAX_RUBRIC_BYTES
    ):
        raise AnnotationError("annotation rubric is not a valid regular file")
    if sha256_bytes(raw) != expected_hash:
        raise AnnotationError("annotation rubric raw-byte hash mismatch")
    return {
        "version": str(rubric["version"]),
        "relative_path": str(rubric["relative_path"]),
        "file_sha256": expected_hash,
    }


def _read_annotation_file(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise AnnotationError("annotation file must not be a symlink")
    try:
        metadata = path.stat()
    except OSError as exc:
        raise AnnotationError("frozen annotation file is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > MAX_ANNOTATION_BYTES
    ):
        raise AnnotationError("annotation file is not a valid private regular file")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnnotationError("annotation file is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise AnnotationError("annotation file must contain one JSON object")
    return payload, raw


def _source_ids(value: Any, *, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise AnnotationError(f"{label} must be a non-empty sorted unique list")
    return value


def validate_annotation_set(
    *,
    annotation_path: Path,
    corpus: Any,
    expected_file_sha256: str | None = None,
    minimum_transitions: int = MINIMUM_MATERIAL_TRANSITIONS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return gate annotations after validating the separate dual-review file.

    ``expected_file_sha256`` is mandatory for an external inference run.  It is
    optional for the read-only readiness check because the annotation document
    also carries a canonical self-hash.  Supplying it binds operator approval to
    the exact bytes reviewed.
    """

    payload, raw = _read_annotation_file(annotation_path)
    raw_sha = sha256_bytes(raw)
    if expected_file_sha256 is not None:
        _sha256(expected_file_sha256, label="expected annotation file hash")
        if raw_sha != expected_file_sha256:
            raise AnnotationError("annotation file hash differs from acknowledged hash")
    _exact_keys(
        payload,
        {
            "schema_version",
            "generated_at",
            "corpus_manifest_sha256",
            "corpus_schema_version",
            "rubric",
            "frozen",
            "annotation_method",
            "records",
            "review_statistics",
            "annotation_set_sha256",
        },
        label="annotation set",
    )
    if (
        payload["schema_version"] != ANNOTATION_SET_SCHEMA_VERSION
        or payload["corpus_schema_version"] != MANIFEST_SCHEMA_VERSION
        or payload["frozen"] is not True
        or payload["annotation_method"] != "independent_dual_review"
    ):
        raise AnnotationError("annotation set is not a frozen dual-review set")
    rubric = _validate_rubric(payload["rubric"])
    generated_at = _timestamp(
        payload["generated_at"], label="annotation set generated-at"
    )
    if payload["corpus_manifest_sha256"] != corpus.manifest_sha256:
        raise AnnotationError("annotation set corpus-manifest binding is stale")
    claimed_set_hash = _sha256(
        payload["annotation_set_sha256"], label="annotation set hash"
    )
    unsigned_set = dict(payload)
    unsigned_set.pop("annotation_set_sha256")
    if canonical_sha256(unsigned_set) != claimed_set_hash:
        raise AnnotationError("annotation set hash does not match its content")

    records = payload["records"]
    if not isinstance(records, list):
        raise AnnotationError("annotation records must be a list")
    derived: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    record_hashes: set[str] = set()
    total_independent_reviews = 0
    minimum_reviewers_per_record: int | None = None
    initial_unanimous_count = 0
    initial_disagreement_count = 0
    adjudicated_count = 0
    for index, item in enumerate(records):
        record = _exact_keys(
            item,
            {
                "case_id",
                "transition_fingerprint",
                "prior_packet_id",
                "current_packet_id",
                "is_material_transition",
                "reference_classification",
                "reference_thesis_direction",
                "evidence_source_ids",
                "consensus_rationale",
                "consensus_rationale_sha256",
                "reviewer_attestations",
                "adjudication",
                "record_sha256",
            },
            label=f"annotation record {index}",
        )
        case_id = str(record["case_id"])
        case = corpus.transitions.get(case_id)
        if case is None or case_id in case_ids:
            raise AnnotationError("annotation case is unknown or duplicated")
        case_ids.add(case_id)
        if (
            record["transition_fingerprint"] != case["transition_fingerprint"]
            or record["prior_packet_id"] != case["prior_packet_id"]
            or record["current_packet_id"] != case["current_packet_id"]
        ):
            raise AnnotationError("annotation record is not bound to its transition")
        if (
            record["is_material_transition"] is not True
            or record["reference_classification"]
            not in {"paper_trade_candidate", "trim_review", "exit_review"}
            or record["reference_thesis_direction"]
            not in {"strengthening", "weakening", "broken"}
        ):
            raise AnnotationError("annotation record is not a material transition")
        evidence_ids = _source_ids(
            record["evidence_source_ids"],
            label=f"annotation record {index} evidence",
        )
        _rationale(
            record["consensus_rationale"],
            record["consensus_rationale_sha256"],
            label=f"annotation record {index} consensus rationale",
        )
        consensus_rationale = str(record["consensus_rationale_sha256"])
        pair = (
            corpus.packets[str(record["prior_packet_id"])],
            corpus.packets[str(record["current_packet_id"])],
        )
        available_sources = set(pair[0].source_ids) | set(pair[1].source_ids)
        if (
            not set(evidence_ids).issubset(available_sources)
            or pair[0].primary_source_id not in evidence_ids
            or pair[1].primary_source_id not in evidence_ids
        ):
            raise AnnotationError(
                "annotation evidence must include both SEC primary sources"
            )

        attestations = record["reviewer_attestations"]
        if not isinstance(attestations, list) or len(attestations) < 2:
            raise AnnotationError("each annotation needs at least two reviewer attestations")
        reviewer_ids: set[str] = set()
        attestation_hashes: set[str] = set()
        attested_evidence: set[str] = set()
        initial_labels: set[tuple[bool, str, str]] = set()
        for reviewer_index, value in enumerate(attestations):
            attestation = _exact_keys(
                value,
                {
                    "reviewer_id_sha256",
                    "reviewed_at",
                    "is_material_transition",
                    "reference_classification",
                    "reference_thesis_direction",
                    "evidence_source_ids",
                    "reviewer_rationale",
                    "reviewer_rationale_sha256",
                    "attestation_sha256",
                },
                label=f"annotation record {index} reviewer {reviewer_index}",
            )
            reviewer_id = _sha256(
                attestation["reviewer_id_sha256"],
                label="reviewer identity hash",
            )
            if reviewer_id in reviewer_ids:
                raise AnnotationError("reviewer identities must be independent")
            reviewer_ids.add(reviewer_id)
            reviewed_at = _timestamp(
                attestation["reviewed_at"], label="review timestamp"
            )
            if reviewed_at > generated_at:
                raise AnnotationError("review timestamp follows annotation freeze time")
            reviewer_material = attestation["is_material_transition"]
            reviewer_classification = attestation["reference_classification"]
            reviewer_direction = attestation["reference_thesis_direction"]
            if not isinstance(reviewer_material, bool):
                raise AnnotationError("reviewer material-transition label is invalid")
            if reviewer_classification not in RESEARCH_CLASSIFICATIONS:
                raise AnnotationError("reviewer classification is outside the rubric")
            if reviewer_direction not in {
                "strengthening",
                "weakening",
                "broken",
                "unchanged",
            }:
                raise AnnotationError("reviewer thesis direction is outside the rubric")
            if reviewer_material and (
                reviewer_classification not in TRANSITION_CLASSIFICATIONS
                or reviewer_direction == "unchanged"
            ):
                raise AnnotationError(
                    "reviewer material-transition labels are internally inconsistent"
                )
            if not reviewer_material and (
                reviewer_classification not in NO_ACTION_CLASSIFICATIONS
                or reviewer_direction != "unchanged"
            ):
                raise AnnotationError(
                    "reviewer no-change labels are internally inconsistent"
                )
            initial_labels.add(
                (
                    reviewer_material,
                    str(reviewer_classification),
                    str(reviewer_direction),
                )
            )
            reviewer_sources = _source_ids(
                attestation["evidence_source_ids"],
                label="reviewer evidence",
            )
            if (
                not set(reviewer_sources).issubset(available_sources)
                or pair[0].primary_source_id not in reviewer_sources
                or pair[1].primary_source_id not in reviewer_sources
            ):
                raise AnnotationError(
                    "each reviewer must cite both SEC primary sources"
                )
            attested_evidence.update(reviewer_sources)
            _rationale(
                attestation["reviewer_rationale"],
                attestation["reviewer_rationale_sha256"],
                label=(
                    f"annotation record {index} reviewer "
                    f"{reviewer_index} rationale"
                ),
            )
            claimed_attestation_hash = _sha256(
                attestation["attestation_sha256"],
                label="reviewer attestation hash",
            )
            unsigned_attestation = dict(attestation)
            unsigned_attestation.pop("attestation_sha256")
            if canonical_sha256(unsigned_attestation) != claimed_attestation_hash:
                raise AnnotationError(
                    "reviewer attestation hash does not match its content"
                )
            if claimed_attestation_hash in attestation_hashes:
                raise AnnotationError("duplicate reviewer attestation content")
            attestation_hashes.add(claimed_attestation_hash)
        total_independent_reviews += len(reviewer_ids)
        minimum_reviewers_per_record = (
            len(reviewer_ids)
            if minimum_reviewers_per_record is None
            else min(minimum_reviewers_per_record, len(reviewer_ids))
        )
        consensus_label = (
            bool(record["is_material_transition"]),
            str(record["reference_classification"]),
            str(record["reference_thesis_direction"]),
        )
        adjudication = _exact_keys(
            record["adjudication"],
            {
                "required",
                "adjudicator_id_sha256",
                "adjudicated_at",
                "adjudication_rationale",
                "adjudication_rationale_sha256",
                "adjudication_sha256",
            },
            label=f"annotation record {index} adjudication",
        )
        if not isinstance(adjudication["required"], bool):
            raise AnnotationError("adjudication required flag is invalid")
        initially_unanimous = len(initial_labels) == 1
        if initially_unanimous:
            initial_unanimous_count += 1
            if next(iter(initial_labels)) != consensus_label:
                raise AnnotationError(
                    "unanimous reviewer label differs from consensus"
                )
            if (
                adjudication["required"] is not False
                or any(
                    adjudication[field] != ""
                    for field in (
                        "adjudicator_id_sha256",
                        "adjudicated_at",
                        "adjudication_rationale",
                        "adjudication_rationale_sha256",
                    )
                )
            ):
                raise AnnotationError(
                    "unanimous review must not claim an adjudication"
                )
        else:
            initial_disagreement_count += 1
            adjudicated_count += 1
            if adjudication["required"] is not True:
                raise AnnotationError(
                    "reviewer disagreement requires independent adjudication"
                )
            adjudicator_id = _sha256(
                adjudication["adjudicator_id_sha256"],
                label="adjudicator identity hash",
            )
            if adjudicator_id in reviewer_ids:
                raise AnnotationError(
                    "adjudicator must be independent of initial reviewers"
                )
            adjudicated_at = _timestamp(
                adjudication["adjudicated_at"],
                label="adjudication timestamp",
            )
            if adjudicated_at > generated_at:
                raise AnnotationError(
                    "adjudication timestamp follows annotation freeze time"
                )
            _rationale(
                adjudication["adjudication_rationale"],
                adjudication["adjudication_rationale_sha256"],
                label=f"annotation record {index} adjudication rationale",
            )
        claimed_adjudication_hash = _sha256(
            adjudication["adjudication_sha256"],
            label="adjudication content hash",
        )
        unsigned_adjudication = dict(adjudication)
        unsigned_adjudication.pop("adjudication_sha256")
        if canonical_sha256(unsigned_adjudication) != claimed_adjudication_hash:
            raise AnnotationError(
                "adjudication hash does not match its content"
            )
        if set(evidence_ids) != attested_evidence:
            raise AnnotationError(
                "consensus evidence must equal the union of reviewer evidence"
            )

        claimed_record_hash = _sha256(
            record["record_sha256"], label="annotation record hash"
        )
        unsigned_record = dict(record)
        unsigned_record.pop("record_sha256")
        if canonical_sha256(unsigned_record) != claimed_record_hash:
            raise AnnotationError("annotation record hash does not match its content")
        if claimed_record_hash in record_hashes:
            raise AnnotationError("duplicate annotation record content")
        record_hashes.add(claimed_record_hash)

        fingerprint = str(record["transition_fingerprint"])
        annotation: dict[str, Any] = {
            "annotation_id": f"annotation:{fingerprint[:24]}",
            "case_id": case_id,
            "transition_fingerprint": fingerprint,
            "prior_packet_id": record["prior_packet_id"],
            "current_packet_id": record["current_packet_id"],
            "is_material_transition": True,
            "reference_classification": record["reference_classification"],
            "reference_thesis_direction": record["reference_thesis_direction"],
            "rubric_version": REFERENCE_RUBRIC_VERSION,
            "annotation_method": "independent_dual_review",
            "independent_reviewer_count": len(reviewer_ids),
            "reviewer_agreement": True,
            "evidence_source_ids": evidence_ids,
            "rationale_sha256": consensus_rationale,
            "provider_quality_scoring_eligible": True,
        }
        annotation["annotation_sha256"] = canonical_sha256(annotation)
        derived.append(annotation)

    if len(derived) < minimum_transitions:
        raise AnnotationError(
            f"dual-reviewed material-transition minimum unmet: "
            f"{len(derived)} < {minimum_transitions}"
        )
    record_count = len(derived)
    review_statistics = {
        "record_count": record_count,
        "independent_review_count_total": total_independent_reviews,
        "minimum_reviewers_per_record": minimum_reviewers_per_record or 0,
        "initial_unanimous_count": initial_unanimous_count,
        "initial_disagreement_count": initial_disagreement_count,
        "initial_exact_agreement_pct": round(
            100.0 * initial_unanimous_count / record_count,
            4,
        ),
        "adjudicated_count": adjudicated_count,
        "unresolved_disagreement_count": 0,
        "final_consensus_count": record_count,
        "final_consensus_pct": 100.0,
    }
    if payload["review_statistics"] != review_statistics:
        raise AnnotationError(
            "annotation review statistics are forged, stale, or incomplete"
        )
    return derived, {
        "annotation_file_sha256": raw_sha,
        "annotation_set_sha256": claimed_set_hash,
        "annotation_count": len(derived),
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "rubric": rubric,
        "review_statistics": review_statistics,
        "frozen": True,
        "independent_dual_review": True,
    }


def check_annotation_readiness(
    *,
    manifest_path: Path = CORPUS_MANIFEST_PATH,
    annotation_path: Path = DEFAULT_ANNOTATION_PATH,
    minimum_packets: int = MINIMUM_REAL_PACKETS,
    minimum_issuers: int = MINIMUM_REAL_ISSUERS,
    minimum_transitions: int = MINIMUM_MATERIAL_TRANSITIONS,
) -> dict[str, Any]:
    """Read only the corpus and annotations; never invoke or write anything."""

    try:
        corpus = _load_corpus(
            manifest_path.expanduser().resolve(),
            minimum_packets=minimum_packets,
            minimum_issuers=minimum_issuers,
        )
        annotations, metadata = validate_annotation_set(
            annotation_path=annotation_path.expanduser().resolve(),
            corpus=corpus,
            minimum_transitions=minimum_transitions,
        )
    except (
        AnnotationError,
        ReplayGateError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as exc:
        return {
            "ready": False,
            "issues": [str(exc)],
            "packet_count": 0,
            "annotation_count": 0,
            "annotation_file_sha256": "",
            "provider_invoked": False,
            "network_invoked": False,
            "files_written": False,
        }
    return {
        "ready": True,
        "issues": [],
        "packet_count": len(corpus.packets),
        "annotation_count": len(annotations),
        "annotation_file_sha256": metadata["annotation_file_sha256"],
        "provider_invoked": False,
        "network_invoked": False,
        "files_written": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--manifest", type=Path, default=CORPUS_MANIFEST_PATH)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATION_PATH)
    args = parser.parse_args()
    result = check_annotation_readiness(
        manifest_path=args.manifest,
        annotation_path=args.annotations,
    )
    print(
        f"transition_annotations={'ready' if result['ready'] else 'blocked'} "
        f"packets={result['packet_count']} "
        f"annotations={result['annotation_count']} "
        f"issues={len(result['issues'])} "
        "provider_invoked=false network_invoked=false files_written=false"
    )
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
