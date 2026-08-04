from __future__ import annotations

import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
