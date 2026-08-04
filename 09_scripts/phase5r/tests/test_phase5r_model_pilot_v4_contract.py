from __future__ import annotations

import copy
import unittest

from _support import materialized
from phase5r_llm_contract import ContractError, ANALYST_SCHEMA, validate_analyst, validate_schema
from phase5r_model_pilot_v4_contract import (
    SOURCE_ID_ONLY_ASSESSMENT_INSTRUCTIONS,
    hydrate_cited_excerpt_hashes,
    source_id_only_assessment_schema,
)


def source_id_only_payload() -> tuple[dict[str, object], dict[str, object]]:
    packet, responses, _ = materialized("g01_stable_hold")
    payload = copy.deepcopy(responses["analyst"])
    payload.update(
        {
            "evidence_direction": "stable",
            "research_classification": "hold_existing",
            "decisive_advice": "Keep the shadow research classification.",
            "long_term_case": "The frozen evidence supports continued review.",
            "confidence_pct": 60,
            "automatic_action_allowed": False,
            "canonical_effect": False,
            "email_eligible": False,
        }
    )
    for claim in payload["claims"]:
        claim.pop("cited_excerpt_sha256")
    return packet, payload


class ReplacementPilotV4ContractTests(unittest.TestCase):
    def test_source_id_only_prompt_never_asks_model_to_emit_hashes(self) -> None:
        self.assertIn("source_ids", SOURCE_ID_ONLY_ASSESSMENT_INSTRUCTIONS)
        self.assertIn(
            "Do not output cited_excerpt_sha256",
            SOURCE_ID_ONLY_ASSESSMENT_INSTRUCTIONS,
        )
        self.assertIn(
            "numeric or calculated claim",
            SOURCE_ID_ONLY_ASSESSMENT_INSTRUCTIONS,
        )

    def test_schema_prohibits_model_supplied_excerpt_hashes(self) -> None:
        schema = source_id_only_assessment_schema()
        claim = schema["properties"]["claims"]["items"]
        self.assertNotIn("cited_excerpt_sha256", claim["properties"])
        self.assertNotIn("cited_excerpt_sha256", claim["required"])
        packet, payload = source_id_only_payload()
        validate_schema(payload, schema)
        invalid = copy.deepcopy(payload)
        invalid["claims"][0]["cited_excerpt_sha256"] = ["0" * 64]
        with self.assertRaisesRegex(ContractError, "unexpected fields"):
            validate_schema(invalid, schema)

    def test_adapter_derives_hashes_and_closed_validator_still_passes(self) -> None:
        packet, payload = source_id_only_payload()
        enriched = hydrate_cited_excerpt_hashes(packet, payload)
        source_map = {
            row["source_id"]: row["content_sha256"]
            for row in packet["source_catalog"]
        }
        for claim in enriched["claims"]:
            self.assertEqual(
                claim["cited_excerpt_sha256"],
                [source_map[source_id] for source_id in claim["source_ids"]],
            )
        base = {
            field: enriched[field] for field in ANALYST_SCHEMA["required"]
        }
        self.assertIs(validate_analyst(packet, base), base)

    def test_unknown_source_remains_rejected_before_validation(self) -> None:
        packet, payload = source_id_only_payload()
        payload["claims"][0]["source_ids"] = ["not-in-frozen-packet"]
        with self.assertRaisesRegex(ContractError, "not in frozen packet"):
            hydrate_cited_excerpt_hashes(packet, payload)


if __name__ == "__main__":
    unittest.main()
