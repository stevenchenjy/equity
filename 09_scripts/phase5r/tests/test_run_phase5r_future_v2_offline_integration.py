from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_phase5r_future_v2_offline_integration as workflow
from phase5r_assertion_span_contract_v3 import ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION
from test_phase5r_llm_evidence_contract_v2_handoff import (
    EvidenceContractV2HandoffTests,
    _raw_sha256,
    _write_json,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FutureV2OfflineIntegrationTests(unittest.TestCase):
    def _write_span_bundle(self, root: Path, artifacts: dict[str, object]) -> Path:
        packet = artifacts["packet"]
        source_texts = artifacts["source_texts"]
        analyst_response = artifacts["analyst_response"]
        claim = analyst_response["claims"][0]
        sources = [
            {
                "source_id": source["source_id"],
                "excerpt_text": source["excerpt_text"],
                "excerpt_utf8_sha256": _sha256_text(source["excerpt_text"]),
            }
            for source in source_texts["sources"]
        ]
        assertion = claim["claim"]
        bundle = {
            "schema_version": ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION,
            "packet_id": packet["packet_id"],
            "canonical_effect": False,
            "sources": sources,
            "assertions": [
                {
                    "assertion_id": claim["claim_id"],
                    "assertion_text": assertion,
                    "assertion_utf8_sha256": _sha256_text(assertion),
                    "cited_source_ids": claim["source_ids"],
                }
            ],
            "anchor_reviews": [
                {
                    "assertion_id": claim["claim_id"],
                    "procedure_disposition": "anchor_not_available",
                    "anchors": [],
                    "anchor_absence_code": "excerpt_scope_insufficient",
                }
            ],
        }
        path = root / workflow.ASSERTION_SPAN_FILENAME
        _write_json(path, bundle)
        return path

    def _fixture(self, root: Path) -> tuple[Path, Path, dict[str, Path]]:
        handoff_root = root / "handoffs"
        handoff_root.mkdir()
        handoff = handoff_root / "synthetic-handoff"
        handoff.mkdir()
        helper = EvidenceContractV2HandoffTests()
        artifacts, paths = helper._write_fixture(handoff)
        self._write_span_bundle(handoff, artifacts)
        approvals = root / "owner-approvals"
        approvals.mkdir()
        approval_path = approvals / "synthetic-approval.json"
        _write_json(
            approval_path,
            helper._owner_approval_reference(_raw_sha256(paths["manifest"])),
        )
        return handoff, approval_path, paths

    def test_workflow_writes_only_noncanonical_outputs_from_a_local_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            handoff, approval_path, paths = self._fixture(root)
            before = {
                path: path.read_bytes()
                for path in (*paths.values(), handoff / workflow.ASSERTION_SPAN_FILENAME, approval_path)
            }
            with (
                patch.object(workflow, "HANDOFF_ROOT", root / "handoffs"),
                patch.object(workflow, "OWNER_APPROVAL_ROOT", root / "owner-approvals"),
                patch.object(workflow, "OUTPUT_ROOT", root / "outputs"),
            ):
                result = workflow.run_future_v2_offline_integration(
                    handoff_directory=handoff,
                    owner_approval_reference_path=approval_path,
                    run_id="synthetic-001",
                )
            after = {path: path.read_bytes() for path in before}
            output = Path(result["output_directory"])
            report = json.loads(
                (output / "future_v2_offline_integration_report.json").read_text(
                    encoding="utf-8"
                )
            )
            disagreement = json.loads(
                (output / "future_v2_disagreement_log.json").read_text(encoding="utf-8")
            )
            report_markdown_created = (
                output / "future_v2_offline_integration_report.md"
            ).is_file()

        self.assertEqual(before, after)
        self.assertFalse(result["canonical_effect"])
        self.assertFalse(result["provider_or_network_used"])
        self.assertFalse(result["execution_authority"])
        self.assertEqual(result["procedure_status"], "incomplete")
        self.assertFalse(report["canonical_effect"])
        self.assertFalse(report["claim_span_checks"]["canonical_effect"])
        self.assertFalse(report["independent_human_review_satisfied"])
        self.assertEqual(report["claim_span_checks"]["anchor_not_available_count"], 1)
        self.assertEqual(report["disagreement_summary"]["material_issue_count"], 2)
        self.assertFalse(disagreement["canonical_effect"])
        self.assertFalse(disagreement["execution_authority"])
        self.assertTrue(report_markdown_created)

    def test_workflow_rejects_a_handoff_outside_its_future_only_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            handoff, approval_path, _ = self._fixture(root)
            with (
                patch.object(workflow, "HANDOFF_ROOT", root / "different-handoffs"),
                patch.object(workflow, "OWNER_APPROVAL_ROOT", root / "owner-approvals"),
                patch.object(workflow, "OUTPUT_ROOT", root / "outputs"),
            ):
                with self.assertRaisesRegex(
                    workflow.FutureV2OfflineIntegrationError,
                    "dedicated future-v2 root",
                ):
                    workflow.run_future_v2_offline_integration(
                        handoff_directory=handoff,
                        owner_approval_reference_path=approval_path,
                        run_id="synthetic-002",
                    )

    def test_workflow_refuses_to_overwrite_a_previous_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            handoff, approval_path, _ = self._fixture(root)
            with (
                patch.object(workflow, "HANDOFF_ROOT", root / "handoffs"),
                patch.object(workflow, "OWNER_APPROVAL_ROOT", root / "owner-approvals"),
                patch.object(workflow, "OUTPUT_ROOT", root / "outputs"),
            ):
                workflow.run_future_v2_offline_integration(
                    handoff_directory=handoff,
                    owner_approval_reference_path=approval_path,
                    run_id="synthetic-003",
                )
                with self.assertRaisesRegex(
                    workflow.FutureV2OfflineIntegrationError,
                    "output directory already exists",
                ):
                    workflow.run_future_v2_offline_integration(
                        handoff_directory=handoff,
                        owner_approval_reference_path=approval_path,
                        run_id="synthetic-003",
                    )


if __name__ == "__main__":
    unittest.main()
