from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

import phase5r_assertion_span_contract_v3 as module
from phase5r_assertion_span_contract_v3 import (
    ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION,
    AssertionSpanV3Error,
    evaluate_assertion_span_procedure_v3,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _anchor(
    *,
    source_id: str,
    excerpt_text: str,
    span_text: str,
    assertion_text_anchor: str,
) -> dict[str, object]:
    excerpt_raw = excerpt_text.encode("utf-8")
    span_raw = span_text.encode("utf-8")
    start = excerpt_raw.index(span_raw)
    end = start + len(span_raw)
    return {
        "source_id": source_id,
        "excerpt_utf8_sha256": _sha256_text(excerpt_text),
        "start_utf8_byte": start,
        "end_utf8_byte": end,
        "span_utf8_sha256": hashlib.sha256(span_raw).hexdigest(),
        "assertion_text_anchor": assertion_text_anchor,
    }


def _valid_inputs() -> tuple[dict[str, object], dict[str, object]]:
    excerpt = "Àlpha revenue was $10 million in 2026."
    assertion = "Àlpha revenue was $10 million in 2026."
    packet = {
        "packet_id": "synthetic-v3-001",
        "source_catalog": [
            {
                "source_id": "S-1",
                "content_sha256": _sha256_text(excerpt),
            }
        ],
    }
    bundle = {
        "schema_version": ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "canonical_effect": False,
        "sources": [
            {
                "source_id": "S-1",
                "excerpt_text": excerpt,
                "excerpt_utf8_sha256": _sha256_text(excerpt),
            }
        ],
        "assertions": [
            {
                "assertion_id": "A-1",
                "assertion_text": assertion,
                "assertion_utf8_sha256": _sha256_text(assertion),
                "cited_source_ids": ["S-1"],
            }
        ],
        "anchor_reviews": [
            {
                "assertion_id": "A-1",
                "procedure_disposition": "span_anchored",
                "anchors": [
                    _anchor(
                        source_id="S-1",
                        excerpt_text=excerpt,
                        span_text="Àlpha revenue",
                        assertion_text_anchor="Àlpha revenue",
                    ),
                    _anchor(
                        source_id="S-1",
                        excerpt_text=excerpt,
                        span_text="$10 million",
                        assertion_text_anchor="$10 million",
                    ),
                    _anchor(
                        source_id="S-1",
                        excerpt_text=excerpt,
                        span_text="2026",
                        assertion_text_anchor="2026",
                    ),
                    _anchor(
                        source_id="S-1",
                        excerpt_text=excerpt,
                        span_text=assertion,
                        assertion_text_anchor=assertion,
                    ),
                ],
                "anchor_absence_code": None,
            }
        ],
    }
    return packet, bundle


def _comparative_inputs() -> tuple[dict[str, object], dict[str, object]]:
    excerpt = "Revenue was up from $10 to $20 in 2026."
    assertion = "Revenue was up from $10 to $20 in 2026."
    packet = {
        "packet_id": "synthetic-v3-comparative",
        "source_catalog": [
            {
                "source_id": "S-comparative",
                "content_sha256": _sha256_text(excerpt),
            }
        ],
    }
    bundle = {
        "schema_version": ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "canonical_effect": False,
        "sources": [
            {
                "source_id": "S-comparative",
                "excerpt_text": excerpt,
                "excerpt_utf8_sha256": _sha256_text(excerpt),
            }
        ],
        "assertions": [
            {
                "assertion_id": "A-comparative",
                "assertion_text": assertion,
                "assertion_utf8_sha256": _sha256_text(assertion),
                "cited_source_ids": ["S-comparative"],
            }
        ],
        "anchor_reviews": [
            {
                "assertion_id": "A-comparative",
                "procedure_disposition": "span_anchored",
                "anchors": [
                    _anchor(
                        source_id="S-comparative",
                        excerpt_text=excerpt,
                        span_text="Revenue",
                        assertion_text_anchor="Revenue",
                    ),
                    _anchor(
                        source_id="S-comparative",
                        excerpt_text=excerpt,
                        span_text="up from $10 to",
                        assertion_text_anchor="up from $10 to",
                    ),
                    _anchor(
                        source_id="S-comparative",
                        excerpt_text=excerpt,
                        span_text="$20",
                        assertion_text_anchor="$20",
                    ),
                    _anchor(
                        source_id="S-comparative",
                        excerpt_text=excerpt,
                        span_text="2026",
                        assertion_text_anchor="2026",
                    ),
                    _anchor(
                        source_id="S-comparative",
                        excerpt_text=excerpt,
                        span_text=assertion,
                        assertion_text_anchor=assertion,
                    ),
                ],
                "anchor_absence_code": None,
            }
        ],
    }
    return packet, bundle


def _single_source_inputs(
    *,
    packet_id: str,
    excerpt: str,
    assertion: str,
    anchor_specs: list[tuple[str, str]],
) -> tuple[dict[str, object], dict[str, object]]:
    source_id = "S-custom"
    assertion_id = "A-custom"
    packet = {
        "packet_id": packet_id,
        "source_catalog": [
            {"source_id": source_id, "content_sha256": _sha256_text(excerpt)}
        ],
    }
    bundle = {
        "schema_version": ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION,
        "packet_id": packet_id,
        "canonical_effect": False,
        "sources": [
            {
                "source_id": source_id,
                "excerpt_text": excerpt,
                "excerpt_utf8_sha256": _sha256_text(excerpt),
            }
        ],
        "assertions": [
            {
                "assertion_id": assertion_id,
                "assertion_text": assertion,
                "assertion_utf8_sha256": _sha256_text(assertion),
                "cited_source_ids": [source_id],
            }
        ],
        "anchor_reviews": [
            {
                "assertion_id": assertion_id,
                "procedure_disposition": "span_anchored",
                "anchors": [
                    _anchor(
                        source_id=source_id,
                        excerpt_text=excerpt,
                        span_text=span_text,
                        assertion_text_anchor=assertion_text_anchor,
                    )
                    for span_text, assertion_text_anchor in anchor_specs
                ],
                "anchor_absence_code": None,
            }
        ],
    }
    return packet, bundle


class AssertionSpanV3Tests(unittest.TestCase):
    def test_decimal_points_are_not_sentence_boundaries_but_word_periods_are(self) -> None:
        self.assertFalse(module._is_sentence_delimiter("Revenue was 0.10%.", 13))
        self.assertFalse(module._is_sentence_delimiter("Revenue was .10%.", 12))
        self.assertTrue(module._is_sentence_delimiter("Revenue fell.10%", 12))
        for delimiter in ("\r", "。", "…", "？", "！", "؛", "।"):
            with self.subTest(delimiter=delimiter):
                self.assertTrue(module._is_sentence_delimiter(delimiter, 0))

    def test_valid_multibyte_utf8_span_bundle_is_nonsemantic_and_noncanonical(self) -> None:
        packet, bundle = _valid_inputs()
        before = copy.deepcopy(bundle)

        result = evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        self.assertEqual(bundle, before)
        self.assertEqual(result["procedure_status"], "completed")
        self.assertEqual(result["assertion_count"], 1)
        self.assertEqual(result["span_anchored_count"], 1)
        self.assertEqual(result["anchor_not_available_count"], 0)
        self.assertEqual(
            result["packet_source_hash_binding_status"],
            "validated_but_not_upstream_verified",
        )
        self.assertEqual(
            result["assertion_origin_status"], "caller_supplied_unverified"
        )
        self.assertEqual(result["semantic_status"], "not_assessed")
        self.assertEqual(result["citation_accuracy_status"], "not_assessed")
        self.assertEqual(result["substantive_recommendation"], "not_established")
        self.assertFalse(result["canonical_effect"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["provider_or_network_used_by_verifier"])

    def test_anchor_not_available_is_incomplete_not_a_semantic_conclusion(self) -> None:
        packet, bundle = _valid_inputs()
        review = bundle["anchor_reviews"][0]
        review["procedure_disposition"] = "anchor_not_available"
        review["anchors"] = []
        review["anchor_absence_code"] = "not_localizable_in_cited_excerpt"

        result = evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        self.assertEqual(result["procedure_status"], "incomplete")
        self.assertEqual(result["span_anchored_count"], 0)
        self.assertEqual(result["anchor_not_available_count"], 1)
        self.assertEqual(result["semantic_status"], "not_assessed")
        self.assertEqual(result["substantive_recommendation"], "not_established")

    def test_anchor_offsets_hashes_and_utf8_boundaries_fail_closed(self) -> None:
        packet, bundle = _valid_inputs()
        broken = bundle["anchor_reviews"][0]["anchors"][0]
        broken["start_utf8_byte"] = 1
        with self.assertRaisesRegex(AssertionSpanV3Error, "UTF-8 boundaries"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        broken = bundle["anchor_reviews"][0]["anchors"][0]
        broken["end_utf8_byte"] = 1
        with self.assertRaisesRegex(AssertionSpanV3Error, "UTF-8 boundaries"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        broken = bundle["anchor_reviews"][0]["anchors"][1]
        broken["end_utf8_byte"] = 10_000
        with self.assertRaisesRegex(AssertionSpanV3Error, "invalid UTF-8 byte range"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        broken = bundle["anchor_reviews"][0]["anchors"][1]
        broken["excerpt_utf8_sha256"] = "0" * 64
        with self.assertRaisesRegex(AssertionSpanV3Error, "stale excerpt UTF-8 hash"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        broken = bundle["anchor_reviews"][0]["anchors"][1]
        broken["span_utf8_sha256"] = "0" * 64
        with self.assertRaisesRegex(AssertionSpanV3Error, "span UTF-8 hash mismatch"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_anchor_must_reference_an_assertion_cited_source(self) -> None:
        packet, bundle = _valid_inputs()
        other_excerpt = "Other source text."
        packet["source_catalog"].append(
            {
                "source_id": "S-2",
                "content_sha256": _sha256_text(other_excerpt),
            }
        )
        bundle["sources"].append(
            {
                "source_id": "S-2",
                "excerpt_text": other_excerpt,
                "excerpt_utf8_sha256": _sha256_text(other_excerpt),
            }
        )
        broken = bundle["anchor_reviews"][0]["anchors"][0]
        broken["source_id"] = "S-2"
        broken["excerpt_utf8_sha256"] = _sha256_text(other_excerpt)
        broken["start_utf8_byte"] = 0
        broken["end_utf8_byte"] = len("Other".encode("utf-8"))
        broken["span_utf8_sha256"] = _sha256_text("Other")
        broken["assertion_text_anchor"] = "Other"

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "source_id is not cited by assertion"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_anchor_review_coverage_and_disposition_shapes_fail_closed(self) -> None:
        packet, bundle = _valid_inputs()
        bundle["anchor_reviews"].append(copy.deepcopy(bundle["anchor_reviews"][0]))
        with self.assertRaisesRegex(AssertionSpanV3Error, "exactly cover assertion_ids"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        review = bundle["anchor_reviews"][0]
        review["procedure_disposition"] = "anchor_not_available"
        review["anchor_absence_code"] = "not_localizable_in_cited_excerpt"
        with self.assertRaisesRegex(
            AssertionSpanV3Error, "anchor_not_available requires empty anchors"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        review = bundle["anchor_reviews"][0]
        review["anchors"] = []
        with self.assertRaisesRegex(
            AssertionSpanV3Error, "span_anchored requires anchors"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_stated_numbers_units_and_periods_must_have_literal_anchors(self) -> None:
        packet, bundle = _valid_inputs()
        anchors = bundle["anchor_reviews"][0]["anchors"]
        anchors[:] = [anchors[0], anchors[2]]

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_up_from_to_comparative_cue_requires_a_literal_anchor(self) -> None:
        packet, bundle = _comparative_inputs()
        result = evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)
        self.assertEqual(result["procedure_status"], "completed")

        packet, bundle = _comparative_inputs()
        bundle["anchor_reviews"][0]["anchors"].pop()
        with self.assertRaisesRegex(
            AssertionSpanV3Error, "need one atomic literal anchor"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_strong_comparative_direction_verbs_cannot_borrow_an_opposite_direction(
        self,
    ) -> None:
        for verb in (
            "surged",
            "jumped",
            "plunged",
            "doubled",
            "halved",
            "expanded",
            "contracted",
            "accelerated",
            "slowed",
            "narrowed",
            "widened",
            "outperformed",
        ):
            with self.subTest(verb=verb):
                packet, bundle = _single_source_inputs(
                    packet_id=f"synthetic-v3-direction-{verb}",
                    excerpt="Revenue declined 10%.",
                    assertion=f"Revenue {verb} 10%.",
                    anchor_specs=[("Revenue", "Revenue"), ("10%", "10%")],
                )

                with self.assertRaisesRegex(
                    AssertionSpanV3Error,
                    "required deterministic text anchors are missing",
                ):
                    evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_numeric_sentence_content_cannot_hide_direction_behind_a_modifier(self) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-hidden-direction",
            excerpt="Revenue declined approximately 10%.",
            assertion="Revenue accelerated approximately 10%.",
            anchor_specs=[
                ("Revenue", "Revenue"),
                ("approximately", "approximately"),
                ("10%", "10%"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error,
            "required deterministic text anchors are missing",
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_calendar_and_fiscal_periods_also_cover_their_assertion_sentence(self) -> None:
        for period in ("2026", "Q1FY26"):
            with self.subTest(period=period):
                packet, bundle = _single_source_inputs(
                    packet_id=f"synthetic-v3-period-direction-{period}",
                    excerpt=f"Revenue declined in {period}.",
                    assertion=f"Revenue accelerated in {period}.",
                    anchor_specs=[("Revenue", "Revenue"), (period, period)],
                )

                with self.assertRaisesRegex(
                    AssertionSpanV3Error,
                    "required deterministic text anchors are missing",
                ):
                    evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_short_qualifiers_and_spaced_or_bare_periods_cannot_be_omitted(self) -> None:
        cases = (
            (
                "synthetic-v3-quarter-abbreviation",
                "Revenue rose 10% y/y.",
                "Revenue rose 10% q/q.",
                [("Revenue", "Revenue"), ("rose", "rose"), ("10%", "10%")],
            ),
            (
                "synthetic-v3-tax-qualifier",
                "Revenue rose 10% inc tax.",
                "Revenue rose 10% ex tax.",
                [
                    ("Revenue", "Revenue"),
                    ("rose", "rose"),
                    ("10%", "10%"),
                    ("tax", "tax"),
                ],
            ),
            (
                "synthetic-v3-spaced-period",
                "CY 26 revenue rose 10%.",
                "FY 26 revenue rose 10%.",
                [
                    ("26", "26"),
                    ("revenue", "revenue"),
                    ("rose", "rose"),
                    ("10%", "10%"),
                ],
            ),
            (
                "synthetic-v3-bare-period",
                "CY revenue grew.",
                "FY revenue grew.",
                [("revenue", "revenue"), ("grew", "grew")],
            ),
        )
        for packet_id, excerpt, assertion, anchor_specs in cases:
            with self.subTest(packet_id=packet_id):
                packet, bundle = _single_source_inputs(
                    packet_id=packet_id,
                    excerpt=excerpt,
                    assertion=assertion,
                    anchor_specs=anchor_specs,
                )

                with self.assertRaisesRegex(
                    AssertionSpanV3Error,
                    "required deterministic text anchors are missing",
                ):
                    evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_numeric_sentence_content_cannot_hide_a_trailing_relation_word(self) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-trailing-direction",
            excerpt="Revenue was 10% worse.",
            assertion="Revenue was 10% better.",
            anchor_specs=[("Revenue", "Revenue"), ("10%", "10%")],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error,
            "required deterministic text anchors are missing",
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_required_tokens_need_one_atomic_literal_anchor(self) -> None:
        excerpt = "Revenue fell. Margin rose. Costs were 10%."
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-cross-sentence-assembly",
            excerpt=excerpt,
            assertion="Revenue rose 10%.",
            anchor_specs=[
                ("Revenue", "Revenue"),
                ("rose", "rose"),
                ("10%", "10%"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error,
            "need one atomic literal anchor",
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        same_sentence_excerpt = "Revenue fell, while Margin rose 10%."
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-cross-clause-assembly",
            excerpt=same_sentence_excerpt,
            assertion="Revenue rose 10%.",
            anchor_specs=[
                ("Revenue", "Revenue"),
                ("rose", "rose"),
                ("10%", "10%"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error,
            "need one atomic literal anchor",
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-cross-sentence-span",
            excerpt=excerpt,
            assertion="Revenue rose 10%.",
            anchor_specs=[
                (excerpt, "Revenue"),
                (excerpt, "rose"),
                (excerpt, "10%"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error,
            "anchor span must remain within one source sentence",
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        unicode_excerpt = "Revenue fell。Margin rose。Costs were 10%。"
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-unicode-cross-sentence-span",
            excerpt=unicode_excerpt,
            assertion="Revenue rose 10%。",
            anchor_specs=[
                (unicode_excerpt, "Revenue"),
                (unicode_excerpt, "rose"),
                (unicode_excerpt, "10%"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error,
            "anchor span must remain within one source sentence",
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-decimal-trailing-direction",
            excerpt="Revenue was 0.10% worse.",
            assertion="Revenue was 0.10% better.",
            anchor_specs=[("Revenue", "Revenue"), ("0.10%", "0.10%")],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error,
            "required deterministic text anchors are missing",
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_unanchored_999_percent_cannot_receive_completed_procedure_status(self) -> None:
        excerpt = "Current operating margin excerpt."
        assertion = "Operating margin was 999 percent."
        packet = {
            "packet_id": "synthetic-v3-unanchored-number",
            "source_catalog": [
                {"source_id": "S-margin", "content_sha256": _sha256_text(excerpt)}
            ],
        }
        bundle = {
            "schema_version": ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION,
            "packet_id": packet["packet_id"],
            "canonical_effect": False,
            "sources": [
                {
                    "source_id": "S-margin",
                    "excerpt_text": excerpt,
                    "excerpt_utf8_sha256": _sha256_text(excerpt),
                }
            ],
            "assertions": [
                {
                    "assertion_id": "A-margin",
                    "assertion_text": assertion,
                    "assertion_utf8_sha256": _sha256_text(assertion),
                    "cited_source_ids": ["S-margin"],
                }
            ],
            "anchor_reviews": [
                {
                    "assertion_id": "A-margin",
                    "procedure_disposition": "span_anchored",
                    "anchors": [
                        _anchor(
                            source_id="S-margin",
                            excerpt_text=excerpt,
                            span_text="operating margin",
                            assertion_text_anchor="Operating margin",
                        )
                    ],
                    "anchor_absence_code": None,
                }
            ],
        }

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_shared_number_and_unit_without_shared_metric_text_cannot_complete(self) -> None:
        packet, bundle = _valid_inputs()
        excerpt = "Operating margin was 999 percent."
        assertion = "Revenue was 999 percent."
        packet["source_catalog"][0]["content_sha256"] = _sha256_text(excerpt)
        bundle["sources"][0]["excerpt_text"] = excerpt
        bundle["sources"][0]["excerpt_utf8_sha256"] = _sha256_text(excerpt)
        bundle["assertions"][0]["assertion_text"] = assertion
        bundle["assertions"][0]["assertion_utf8_sha256"] = _sha256_text(assertion)
        bundle["anchor_reviews"][0]["anchors"] = [
            _anchor(
                source_id="S-1",
                excerpt_text=excerpt,
                span_text="was",
                assertion_text_anchor="was",
            ),
            _anchor(
                source_id="S-1",
                excerpt_text=excerpt,
                span_text="999 percent",
                assertion_text_anchor="999 percent",
            ),
        ]

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "meaningful literal assertion overlap"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_numeric_anchor_cannot_match_a_different_larger_literal_by_substring(self) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-number-boundary",
            excerpt="Revenue was 100 million in 2026.",
            assertion="Revenue was 10 million in 2026.",
            anchor_specs=[
                ("Revenue", "Revenue"),
                ("100", "10"),
                ("million", "million"),
                ("2026", "2026"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "assertion_text_anchor is absent"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_two_character_fragment_cannot_count_as_meaningful_literal_overlap(self) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-fragment",
            excerpt="Fiscal results were released.",
            assertion="Company filed bankruptcy.",
            anchor_specs=[("Fi", "fi")],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "assertion_text_anchor is absent"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_casefold_expansion_is_not_treated_as_a_literal_anchor(self) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-casefold",
            excerpt="Straße revenue was 10 million in 2026.",
            assertion="Strasse revenue was 10 million in 2026.",
            anchor_specs=[("Straße", "Strasse")],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "assertion_text_anchor is absent from excerpt span"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_rose_multiple_bps_and_fiscal_quarter_cues_require_literal_anchors(self) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-cue-coverage",
            excerpt="EPS rose 3x, or 100 bps, in FY26 Q1.",
            assertion="EPS rose 3x, or 100 bps, in FY26 Q1.",
            anchor_specs=[
                ("EPS", "EPS"),
                ("3x", "3x"),
                ("100 bps", "100 bps"),
                ("FY26", "FY26"),
                ("Q1", "Q1"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        bundle["anchor_reviews"][0]["anchors"].append(
            _anchor(
                source_id="S-custom",
                excerpt_text="EPS rose 3x, or 100 bps, in FY26 Q1.",
                span_text="EPS rose 3x, or 100 bps, in FY26 Q1.",
                assertion_text_anchor="EPS rose 3x, or 100 bps, in FY26 Q1.",
            )
        )
        result = evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)
        self.assertEqual(result["procedure_status"], "completed")

    def test_textual_number_cannot_borrow_a_different_quantitys_unit_anchor(self) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-textual-number",
            excerpt="Revenue was two million in 2026.",
            assertion="Revenue was one million in 2026.",
            anchor_specs=[
                ("Revenue", "Revenue"),
                ("million", "million"),
                ("2026", "2026"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_compact_billion_and_million_quantities_cannot_borrow_metric_anchors(
        self,
    ) -> None:
        for suffix in ("bn", "m"):
            with self.subTest(suffix=suffix):
                packet, bundle = _single_source_inputs(
                    packet_id=f"synthetic-v3-compact-{suffix}",
                    excerpt=f"Revenue rose 11{suffix}.",
                    assertion=f"Revenue rose 10{suffix}.",
                    anchor_specs=[
                        ("Revenue", "Revenue"),
                        ("rose", "rose"),
                    ],
                )

                with self.assertRaisesRegex(
                    AssertionSpanV3Error,
                    "required deterministic text anchors are missing",
                ):
                    evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_numeric_literal_boundaries_reject_thousands_signs_and_unicode_extensions(
        self,
    ) -> None:
        cases = (
            ("Revenue was $10.", "Revenue was $10,000.", "$10,000", "$10"),
            ("Margin was 10%.", "Margin was -10%.", "-10%", "10%"),
            ("Revenue was 10.", "Revenue was 0.10.", "10", "10"),
            ("Revenue was 10.", "Revenue was .10.", "10", "10"),
            ("Revenue was 10.", "Revenue was .10.", ".10", "10"),
            ("Revenue was $10.", "Revenue was ($10).", "$10", "$10"),
            ("Revenue was $10.", "Revenue was ($10).", "($10)", "$10"),
            (
                "Revenue was $10 million.",
                "Revenue was ($10 million).",
                "$10",
                "$10",
            ),
            ("Revenue was $10.", "Revenue was - $10.", "$10", "$10"),
            ("Margin was 10.", "Margin was <10.", "10", "10"),
            ("Margin was 10.", "Margin was 10%.", "10", "10"),
            ("Revenue was ١٠.", "Revenue was ١٠٠.", "١٠٠", "١٠"),
            ("Dose was 10.", "Dose was 10μg.", "10μg", "10"),
        )
        for index, (assertion, excerpt, source_anchor, assertion_anchor) in enumerate(cases):
            with self.subTest(assertion=assertion):
                packet, bundle = _single_source_inputs(
                    packet_id=f"synthetic-v3-numeric-boundary-{index}",
                    excerpt=excerpt,
                    assertion=assertion,
                    anchor_specs=[
                        (assertion.split()[0], assertion.split()[0]),
                        (source_anchor, assertion_anchor),
                    ],
                )

                with self.assertRaisesRegex(
                    AssertionSpanV3Error,
                    "assertion_text_anchor is absent from excerpt span",
                ):
                    evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_scientific_compact_and_forecast_tokens_cannot_borrow_different_values(
        self,
    ) -> None:
        cases = (
            ("1e6", "2e6"),
            ("1.2e-3", "2.2e-3"),
            ("10B", "11B"),
            ("10K", "11K"),
            ("10MM", "11MM"),
            ("2026E", "2027E"),
            ("FY26E", "FY27E"),
            ("2026Q1", "2027Q1"),
            ("CY2026", "CY2027"),
            ("Q1FY26", "Q2FY26"),
            ("FY26Q1", "FY26Q2"),
            ("H1FY26", "H2FY26"),
            ("٢٠٢٦", "٢٠٢٧"),
        )
        for index, (asserted_value, excerpt_value) in enumerate(cases):
            with self.subTest(asserted_value=asserted_value):
                packet, bundle = _single_source_inputs(
                    packet_id=f"synthetic-v3-financial-token-{index}",
                    excerpt=f"Revenue was {excerpt_value}.",
                    assertion=f"Revenue was {asserted_value}.",
                    anchor_specs=[("Revenue", "Revenue")],
                )

                with self.assertRaisesRegex(
                    AssertionSpanV3Error,
                    "required deterministic text anchors are missing",
                ):
                    evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_adjacent_and_spaced_dose_units_require_the_exact_literal_quantity(
        self,
    ) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-adjacent-dose-unit",
            excerpt="Dose was 10μg.",
            assertion="Dose was 10mg.",
            anchor_specs=[("Dose", "Dose")],
        )
        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-spaced-dose-unit",
            excerpt="Dose was 10 g.",
            assertion="Dose was 10 mg.",
            anchor_specs=[("Dose", "Dose"), ("10", "10")],
        )
        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_half_year_period_cannot_borrow_another_half_with_the_same_fiscal_year(
        self,
    ) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-half-year-period",
            excerpt="Revenue was H2 FY26.",
            assertion="Revenue was H1 FY26.",
            anchor_specs=[("Revenue", "Revenue"), ("FY26", "FY26")],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_literal_anchor_rejects_hyphen_unicode_word_and_combining_mark_fragments(
        self,
    ) -> None:
        cases = (
            ("Profit improved.", "The non-profit improved.", "profit"),
            ("Alpha revenue improved.", "alphaβ revenue improved.", "alpha"),
            ("Cafe revenue improved.", "Cafe\u0301 revenue improved.", "Cafe"),
        )
        for index, (assertion, excerpt, fragment) in enumerate(cases):
            with self.subTest(fragment=fragment):
                packet, bundle = _single_source_inputs(
                    packet_id=f"synthetic-v3-literal-fragment-{index}",
                    excerpt=excerpt,
                    assertion=assertion,
                    anchor_specs=[(fragment, fragment)],
                )

                with self.assertRaisesRegex(
                    AssertionSpanV3Error,
                    "assertion_text_anchor is absent from excerpt span",
                ):
                    evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_textual_number_phrase_cannot_be_assembled_from_separate_anchors(
        self,
    ) -> None:
        packet, bundle = _single_source_inputs(
            packet_id="synthetic-v3-textual-number-phrase",
            excerpt=(
                "Revenue was one item; a hundred units were reported; "
                "a million shares were outstanding."
            ),
            assertion="Revenue was one hundred million.",
            anchor_specs=[
                ("Revenue", "Revenue"),
                ("one", "one"),
                ("hundred", "hundred"),
                ("million", "million"),
            ],
        )

        with self.assertRaisesRegex(
            AssertionSpanV3Error, "required deterministic text anchors are missing"
        ):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_source_and_assertion_values_are_snapshotted_before_anchor_evaluation(self) -> None:
        packet, bundle = _valid_inputs()
        original_assertion_map = module._assertion_map

        def assertion_map_then_mutate(
            *args: object, **kwargs: object
        ) -> tuple[list[str], dict[str, dict[str, object]]]:
            result = original_assertion_map(*args, **kwargs)
            bundle["sources"][0]["excerpt_text"] = "Replacement text outside the packet."
            bundle["assertions"][0]["assertion_text"] = "Replacement assertion."
            return result

        with patch.object(
            module,
            "_assertion_map",
            side_effect=assertion_map_then_mutate,
        ):
            result = evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        self.assertEqual(result["procedure_status"], "completed")

    def test_extra_semantic_or_authority_fields_and_canonical_effect_are_rejected(self) -> None:
        packet, bundle = _valid_inputs()
        bundle["semantic_support"] = "supported"
        with self.assertRaisesRegex(AssertionSpanV3Error, "field mismatch"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        bundle["canonical_effect"] = True
        with self.assertRaisesRegex(AssertionSpanV3Error, "canonical_effect must remain false"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_source_hash_and_exact_packet_source_coverage_are_required(self) -> None:
        packet, bundle = _valid_inputs()
        bundle["sources"][0]["excerpt_text"] = "Substituted excerpt."
        with self.assertRaisesRegex(AssertionSpanV3Error, "excerpt UTF-8 hash mismatch"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

        packet, bundle = _valid_inputs()
        packet["source_catalog"].append(
            {"source_id": "S-2", "content_sha256": _sha256_text("Other source.")}
        )
        with self.assertRaisesRegex(AssertionSpanV3Error, "exactly cover packet source_ids"):
            evaluate_assertion_span_procedure_v3(packet=packet, bundle=bundle)

    def test_module_imports_only_standard_library_modules(self) -> None:
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module.split(".")[0])

        self.assertEqual(
            imported_modules,
            {"__future__", "hashlib", "re", "typing", "unicodedata"},
        )


if __name__ == "__main__":
    unittest.main()
