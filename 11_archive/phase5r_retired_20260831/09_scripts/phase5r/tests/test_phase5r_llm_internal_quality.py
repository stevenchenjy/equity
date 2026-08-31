from __future__ import annotations

import unittest

from phase5r_llm_internal_quality import (
    FUTURE_ANALYST_SCOPE_ADDENDUM,
    FUTURE_CRITIC_SCOPE_ADDENDUM,
    InternalQualityGuardError,
    evaluate_critic_incremental_value,
    lint_claim_evidence_scope,
)


def _codes(result: dict) -> set[str]:
    return {row["code"] for row in result["flags"]}


class InternalQualityGuardTests(unittest.TestCase):
    def test_comparative_claim_requires_baseline_and_period_check(self) -> None:
        result = lint_claim_evidence_scope(
            claim="Revenue rose and operating margin improved.",
            period="reported fiscal comparison",
            unit="millions and percentage of revenue",
            cited_excerpts=[
                {
                    "source_id": "sec-primary:synthetic:arm",
                    "excerpt_text": "Operating margin was 18 percent.",
                }
            ],
        )

        self.assertTrue(result["manual_review_required"])
        self.assertIn(
            "comparative_direction_requires_baseline_check", _codes(result)
        )
        self.assertIn("period_binding_not_visible_in_excerpt", _codes(result))
        self.assertFalse(result["canonical_effect"])
        self.assertFalse(result["repository_provider_called"])
        self.assertFalse(result["network_called"])

    def test_incorporated_material_terms_are_flagged_for_scope_review(self) -> None:
        result = lint_claim_evidence_scope(
            claim="The company disclosed specific pricing terms.",
            period="current report date",
            unit="not applicable",
            cited_excerpts=[
                {
                    "source_id": "sec-primary:synthetic:avgo",
                    "excerpt_text": "The attached press release announced pricing terms.",
                }
            ],
        )

        self.assertIn("incorporated_material_scope_check", _codes(result))

    def test_largest_customer_scope_is_flagged_without_calling_it_false(self) -> None:
        result = lint_claim_evidence_scope(
            claim="Dependence on the largest customer decreased.",
            period="nine months ended 2026",
            unit="percentage of total revenue",
            cited_excerpts=[
                {
                    "source_id": "sec-primary:synthetic:mu",
                    "excerpt_text": "One customer was 10 percent of revenue in 2026 and 16 percent in 2025.",
                }
            ],
        )

        self.assertIn(
            "scope_or_superlative_requires_explicit_support", _codes(result)
        )
        self.assertNotIn("unsupported", result)

    def test_malformed_citation_input_fails_closed(self) -> None:
        with self.assertRaisesRegex(InternalQualityGuardError, "source_id"):
            lint_claim_evidence_scope(
                claim="A supported fact.",
                period="current period",
                unit="dollars",
                cited_excerpts=[{"excerpt_text": "Source text."}],
            )

    def test_critic_incremental_value_is_not_established_without_reference(self) -> None:
        result = evaluate_critic_incremental_value(
            reference_material_issue_claim_ids=None,
            committee_issue_claim_ids=["claim-a"],
            critic_issue_claim_ids=["claim-b"],
        )

        self.assertFalse(result["reference_set_available"])
        self.assertEqual(result["incremental_value_status"], "not_established")
        self.assertFalse(result["canonical_effect"])

    def test_reference_overlap_does_not_establish_critic_incremental_value(self) -> None:
        result = evaluate_critic_incremental_value(
            reference_material_issue_claim_ids=["claim-a", "claim-b"],
            committee_issue_claim_ids=["claim-a"],
            critic_issue_claim_ids=["claim-b"],
        )

        self.assertEqual(result["identified_material_issue_claim_ids"], ["claim-b"])
        self.assertEqual(result["missed_material_issue_claim_ids"], ["claim-a"])
        self.assertEqual(result["incremental_material_issue_claim_ids"], ["claim-b"])
        self.assertEqual(
            result["incremental_value_status"],
            "not_established",
        )
        self.assertEqual(
            result["reference_alignment_status"],
            "observed_against_unverified_reference",
        )
        self.assertEqual(result["reviewer_independence_status"], "not_established")

    def test_future_prompt_addenda_preserve_evidence_scope_boundaries(self) -> None:
        self.assertIn("baseline, period, and unit", FUTURE_ANALYST_SCOPE_ADDENDUM)
        self.assertIn("attached or incorporated", FUTURE_CRITIC_SCOPE_ADDENDUM)


if __name__ == "__main__":
    unittest.main()
