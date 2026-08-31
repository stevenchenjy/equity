from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_llm_transition_annotations import (
    ANNOTATION_SET_SCHEMA_VERSION,
    DEFAULT_RUBRIC_PATH,
    AnnotationError,
    check_annotation_readiness,
    validate_annotation_set,
)
from verify_phase5r_llm_provider_replay_gate import (
    MANIFEST_SCHEMA_VERSION,
    REFERENCE_RUBRIC_VERSION,
    canonical_sha256,
    sha256_bytes,
)


class TransitionAnnotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="phase5r-transition-annotations-"
        )
        self.root = Path(self.temporary.name)
        self.prior_id = "1" * 64
        self.current_id = "2" * 64
        self.fingerprint = "3" * 64
        self.case_id = f"transition:{self.fingerprint[:24]}"
        self.corpus = SimpleNamespace(
            manifest_sha256="4" * 64,
            transitions={
                self.case_id: {
                    "case_id": self.case_id,
                    "transition_fingerprint": self.fingerprint,
                    "prior_packet_id": self.prior_id,
                    "current_packet_id": self.current_id,
                }
            },
            packets={
                self.prior_id: SimpleNamespace(
                    source_ids=frozenset({"sec-primary:prior", "sec-index:prior"}),
                    primary_source_id="sec-primary:prior",
                ),
                self.current_id: SimpleNamespace(
                    source_ids=frozenset(
                        {"sec-primary:current", "sec-index:current"}
                    ),
                    primary_source_id="sec-primary:current",
                ),
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _hashed(value: dict[str, Any], field: str) -> dict[str, Any]:
        payload = copy.deepcopy(value)
        payload[field] = canonical_sha256(payload)
        return payload

    def _payload(self) -> dict[str, Any]:
        sources = ["sec-primary:current", "sec-primary:prior"]
        attestations: list[dict[str, Any]] = []
        for index in range(2):
            reviewer_rationale = (
                f"Reviewer {index} found a material long-term change in "
                "both cited primary filings."
            )
            attestation = {
                "reviewer_id_sha256": canonical_sha256(f"reviewer-{index}"),
                "reviewed_at": f"2026-07-24T1{index}:00:00+00:00",
                "is_material_transition": True,
                "reference_classification": "paper_trade_candidate",
                "reference_thesis_direction": "strengthening",
                "evidence_source_ids": sources,
                "reviewer_rationale": reviewer_rationale,
                "reviewer_rationale_sha256": hashlib.sha256(
                    reviewer_rationale.encode("utf-8")
                ).hexdigest(),
            }
            attestations.append(self._hashed(attestation, "attestation_sha256"))
        consensus_rationale = (
            "Both independent reviews agree that the current filing materially "
            "strengthens the long-term evidence relative to the prior filing."
        )
        adjudication = {
            "required": False,
            "adjudicator_id_sha256": "",
            "adjudicated_at": "",
            "adjudication_rationale": "",
            "adjudication_rationale_sha256": "",
        }
        adjudication = self._hashed(adjudication, "adjudication_sha256")
        record = {
            "case_id": self.case_id,
            "transition_fingerprint": self.fingerprint,
            "prior_packet_id": self.prior_id,
            "current_packet_id": self.current_id,
            "is_material_transition": True,
            "reference_classification": "paper_trade_candidate",
            "reference_thesis_direction": "strengthening",
            "evidence_source_ids": sources,
            "consensus_rationale": consensus_rationale,
            "consensus_rationale_sha256": hashlib.sha256(
                consensus_rationale.encode("utf-8")
            ).hexdigest(),
            "reviewer_attestations": attestations,
            "adjudication": adjudication,
        }
        record = self._hashed(record, "record_sha256")
        payload = {
            "schema_version": ANNOTATION_SET_SCHEMA_VERSION,
            "generated_at": "2026-07-24T12:00:00+00:00",
            "corpus_manifest_sha256": self.corpus.manifest_sha256,
            "corpus_schema_version": MANIFEST_SCHEMA_VERSION,
            "rubric": {
                "version": REFERENCE_RUBRIC_VERSION,
                "relative_path": DEFAULT_RUBRIC_PATH.relative_to(
                    DEFAULT_RUBRIC_PATH.parents[1]
                ).as_posix(),
                "file_sha256": hashlib.sha256(
                    DEFAULT_RUBRIC_PATH.read_bytes()
                ).hexdigest(),
            },
            "frozen": True,
            "annotation_method": "independent_dual_review",
            "records": [record],
            "review_statistics": {
                "record_count": 1,
                "independent_review_count_total": 2,
                "minimum_reviewers_per_record": 2,
                "initial_unanimous_count": 1,
                "initial_disagreement_count": 0,
                "initial_exact_agreement_pct": 100.0,
                "adjudicated_count": 0,
                "unresolved_disagreement_count": 0,
                "final_consensus_count": 1,
                "final_consensus_pct": 100.0,
            },
        }
        return self._hashed(payload, "annotation_set_sha256")

    def _write(self, payload: dict[str, Any]) -> tuple[Path, str]:
        path = self.root / "annotations.json"
        raw = (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        return path, sha256_bytes(raw)

    def test_valid_dual_review_derives_gate_annotation(self) -> None:
        path, raw_sha = self._write(self._payload())
        annotations, metadata = validate_annotation_set(
            annotation_path=path,
            corpus=self.corpus,
            expected_file_sha256=raw_sha,
            minimum_transitions=1,
        )
        self.assertEqual(len(annotations), 1)
        self.assertEqual(annotations[0]["independent_reviewer_count"], 2)
        self.assertTrue(annotations[0]["reviewer_agreement"])
        self.assertEqual(metadata["annotation_file_sha256"], raw_sha)

    def test_acknowledged_raw_hash_tamper_fails(self) -> None:
        path, _ = self._write(self._payload())
        with self.assertRaisesRegex(AnnotationError, "acknowledged hash"):
            validate_annotation_set(
                annotation_path=path,
                corpus=self.corpus,
                expected_file_sha256="f" * 64,
                minimum_transitions=1,
            )

    def test_duplicate_reviewer_identity_fails(self) -> None:
        payload = self._payload()
        record = payload["records"][0]
        second = record["reviewer_attestations"][1]
        second["reviewer_id_sha256"] = record["reviewer_attestations"][0][
            "reviewer_id_sha256"
        ]
        second.pop("attestation_sha256")
        second["attestation_sha256"] = canonical_sha256(second)
        record.pop("record_sha256")
        record["record_sha256"] = canonical_sha256(record)
        payload.pop("annotation_set_sha256")
        payload["annotation_set_sha256"] = canonical_sha256(payload)
        path, _ = self._write(payload)
        with self.assertRaisesRegex(AnnotationError, "independent"):
            validate_annotation_set(
                annotation_path=path,
                corpus=self.corpus,
                minimum_transitions=1,
            )

    def test_hash_only_consensus_rationale_fails(self) -> None:
        payload = self._payload()
        record = payload["records"][0]
        record["consensus_rationale"] = ""
        record.pop("record_sha256")
        record["record_sha256"] = canonical_sha256(record)
        payload.pop("annotation_set_sha256")
        payload["annotation_set_sha256"] = canonical_sha256(payload)
        path, _ = self._write(payload)
        with self.assertRaisesRegex(AnnotationError, "inspectable"):
            validate_annotation_set(
                annotation_path=path,
                corpus=self.corpus,
                minimum_transitions=1,
            )

    def test_stale_rubric_hash_fails(self) -> None:
        payload = self._payload()
        payload["rubric"]["file_sha256"] = "9" * 64
        payload.pop("annotation_set_sha256")
        payload["annotation_set_sha256"] = canonical_sha256(payload)
        path, _ = self._write(payload)
        with self.assertRaisesRegex(AnnotationError, "rubric raw-byte hash"):
            validate_annotation_set(
                annotation_path=path,
                corpus=self.corpus,
                minimum_transitions=1,
            )

    def test_missing_file_readiness_is_read_only_and_blocked(self) -> None:
        result = check_annotation_readiness(
            manifest_path=self.root / "missing-manifest.json",
            annotation_path=self.root / "missing-annotations.json",
            minimum_packets=1,
            minimum_transitions=1,
        )
        self.assertFalse(result["ready"])
        self.assertFalse(result["provider_invoked"])
        self.assertFalse(result["network_invoked"])
        self.assertFalse(result["files_written"])


if __name__ == "__main__":
    unittest.main()
