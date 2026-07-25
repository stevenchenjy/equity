#!/usr/bin/env python3
"""Create an explicitly incomplete human-review template for replay transitions.

No classification, thesis direction, evidence conclusion, reviewer identity, or
rationale is inferred by this script.  The resulting template is intentionally
invalid for provider replay until independent reviewers complete it and a
separate freeze step computes the record and annotation-set hashes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from phase5r_daily_common import ROOT, iso_now
from phase5r_llm_transition_annotations import (
    ANNOTATION_SET_SCHEMA_VERSION,
)
from verify_phase5r_llm_provider_replay_gate import (
    CORPUS_MANIFEST_PATH,
    MANIFEST_SCHEMA_VERSION,
    MINIMUM_REAL_PACKETS,
    REFERENCE_RUBRIC_VERSION,
    _load_corpus,
)


ANNOTATION_ROOT = (
    ROOT / "08_reviews" / "phase5r_llm_transition_annotations"
)
DEFAULT_TEMPLATE_PATH = (
    ANNOTATION_ROOT / "v1" / "phase5r_material_transition_annotations.template.json"
)


def build_incomplete_template(corpus: Any) -> dict[str, Any]:
    """Return transition bindings with all judgment fields left incomplete."""

    records: list[dict[str, Any]] = []
    for case_id in sorted(corpus.transitions):
        case = corpus.transitions[case_id]
        records.append(
            {
                "case_id": case_id,
                "transition_fingerprint": case["transition_fingerprint"],
                "prior_packet_id": case["prior_packet_id"],
                "current_packet_id": case["current_packet_id"],
                "is_material_transition": None,
                "reference_classification": None,
                "reference_thesis_direction": None,
                "evidence_source_ids": [],
                "consensus_rationale_sha256": "",
                "reviewer_attestations": [],
                "record_sha256": "",
            }
        )
    return {
        "schema_version": ANNOTATION_SET_SCHEMA_VERSION,
        "generated_at": iso_now(),
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "corpus_schema_version": MANIFEST_SCHEMA_VERSION,
        "rubric_version": REFERENCE_RUBRIC_VERSION,
        "frozen": False,
        "annotation_method": "independent_dual_review",
        "records": records,
        "annotation_set_sha256": "",
    }


def _exclusive_write_json(path: Path, payload: dict[str, Any]) -> None:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ANNOTATION_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("annotation template must stay under the review root") from exc
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("O_NOFOLLOW is required for annotation template output")
    descriptor = os.open(
        resolved,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        rendered = (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        os.write(descriptor, rendered)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-incomplete-template", action="store_true", required=True)
    parser.add_argument("--manifest", type=Path, default=CORPUS_MANIFEST_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_TEMPLATE_PATH)
    args = parser.parse_args()
    corpus = _load_corpus(
        args.manifest.expanduser().resolve(),
        minimum_packets=MINIMUM_REAL_PACKETS,
    )
    template = build_incomplete_template(corpus)
    _exclusive_write_json(args.output, template)
    print(
        f"annotation_template_created=true transitions={len(template['records'])} "
        "frozen=false provider_quality_eligible=false model_invoked=false "
        "network_invoked=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
