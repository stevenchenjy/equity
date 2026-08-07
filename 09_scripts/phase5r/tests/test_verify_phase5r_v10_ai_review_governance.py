from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import verify_phase5r_v10_ai_review_governance as governance


class V10AiReviewGovernanceVerifierTests(unittest.TestCase):
    def test_frozen_v10_artifacts_pass_without_an_adoption_record(self) -> None:
        result = governance.verify()

        self.assertTrue(result["passed"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["adoption_record_status"], "not_provided")
        self.assertEqual(
            result["blind_key_boundary_incident_status"],
            "contained_non_substantive_boundary_contact",
        )
        self.assertEqual(
            result["internal_use_authorization_status"],
            "recorded_limited_noncanonical",
        )
        self.assertFalse(result["verifier_direct_blind_key_file_opened"])
        self.assertFalse(result["verifier_completion_record_read"])
        self.assertFalse(result["verifier_provider_constructed"])
        self.assertFalse(result["verifier_network_called"])

    def test_template_cannot_be_treated_as_an_adoption(self) -> None:
        result = governance.verify(
            adoption_record_path=(
                governance.ROOT
                / "01_policies/phase5r_v10_ai_assisted_review_adoption_record_template.json"
            )
        )

        self.assertFalse(result["passed"])
        self.assertIn("adoption_record_not_adopted", result["issues"])
        self.assertIn("adoption_record_policy_owner_missing", result["issues"])

    def test_raw_hash_pins_reject_a_replaced_artifact(self) -> None:
        original_sha256_file = governance._sha256_file

        def altered_hash(path):
            if path == governance.ANONYMOUS_REVIEW_PATH:
                return "0" * 64
            return original_sha256_file(path)

        with mock.patch.object(governance, "_sha256_file", side_effect=altered_hash):
            result = governance.verify()

        self.assertFalse(result["passed"])
        self.assertIn("anonymous_review_raw_file_hash_mismatch", result["issues"])

    def test_completed_adoption_record_uses_only_a_narrow_internal_waiver(self) -> None:
        result = governance.verify(
            adoption_record_path=(
                governance.ROOT
                / "00_project_control/phase5r_v10_ai_assisted_review_governance_adoption.json"
            )
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["adoption_record_status"], "provided")

    def test_adoption_rejects_a_waiver_that_claims_protocol_completion(self) -> None:
        completed = (
            governance.ROOT
            / "00_project_control/phase5r_v10_ai_assisted_review_governance_adoption.json"
        )
        record = json.loads(completed.read_text(encoding="utf-8"))
        record["human_review_protocol_completed"] = True
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid_adoption.json"
            path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = governance.verify(adoption_record_path=path)

        self.assertFalse(result["passed"])
        self.assertIn(
            "adoption_record_human_review_protocol_must_remain_incomplete",
            result["issues"],
        )


if __name__ == "__main__":
    unittest.main()
