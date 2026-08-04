from __future__ import annotations

import copy
import unittest

import run_phase5r_model_pilot as v1
from phase5r_llm_contract import ContractError, validate_schema
from phase5r_model_pilot_v5_contract import (
    SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS,
    hydrate_source_locked_assessment,
    source_locked_assessment_schema,
)


V5_PACKET_ID = "7777624168bbc66d4622ef9c2366382a168941a0daa4ad0abce053fd913d303d"


def packet_context() -> v1.PacketContext:
    _policy, contexts, _unused, _audit, _sentinels = v1._readiness_components()
    return next(context for context in contexts if context.packet_id == V5_PACKET_ID)


def source_locked_payload() -> dict[str, object]:
    return {
        "claims": [
            {
                "claim": "The frozen primary evidence supports continued human research review.",
                "stance": "uncertain",
                "time_horizon": "long_term",
                "materiality": "medium",
                "rationale": "The conclusion remains limited to the frozen primary evidence.",
                "fact_type": "fact",
                "evidence_origin": "management_reported",
                "unit": "qualitative",
                "period": "long_term",
            }
        ],
        "ticker_coverage": [
            {
                "official_evidence_sufficient": True,
                "contradictory_evidence": False,
                "missing_evidence": [],
            }
        ],
        "unresolved_questions": [],
        "evidence_direction": "unclear",
        "research_classification": "abstain",
        "decisive_advice": "Keep the output in shadow research only.",
        "long_term_case": "The frozen primary evidence alone does not establish a conclusion.",
        "confidence_pct": 50,
    }


class ReplacementPilotV5ContractTests(unittest.TestCase):
    def test_source_locked_schema_omits_deterministic_fields(self) -> None:
        schema = source_locked_assessment_schema()
        self.assertNotIn("packet_id", schema["properties"])
        claim = schema["properties"]["claims"]["items"]
        self.assertNotIn("source_ids", claim["properties"])
        self.assertEqual(
            claim["properties"]["evidence_origin"]["enum"],
            ["management_reported", "independently_reported"],
        )
        self.assertIn("no digits in claim text", SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS)

    def test_adapter_injects_the_single_primary_source_and_closed_fields(self) -> None:
        context = packet_context()
        payload = source_locked_payload()
        validate_schema(payload, source_locked_assessment_schema())
        enriched = hydrate_source_locked_assessment(context.runtime_packet, payload)
        source = context.runtime_packet["source_catalog"][0]
        claim = enriched["claims"][0]
        self.assertEqual(claim["source_ids"], [source["source_id"]])
        self.assertEqual(claim["cited_excerpt_sha256"], [source["content_sha256"]])
        self.assertEqual(claim["calculation_ids"], [])
        self.assertIs(v1._validate_assessment(context, enriched), enriched)

    def test_model_cannot_supply_source_or_calculation_choices(self) -> None:
        payload = source_locked_payload()
        invalid = copy.deepcopy(payload)
        invalid["claims"][0]["source_ids"] = ["untrusted-source"]
        with self.assertRaisesRegex(ContractError, "unexpected fields"):
            validate_schema(invalid, source_locked_assessment_schema())


if __name__ == "__main__":
    unittest.main()
