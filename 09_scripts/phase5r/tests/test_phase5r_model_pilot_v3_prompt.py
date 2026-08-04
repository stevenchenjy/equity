from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from _support import materialized
from phase5r_llm_contract import ContractError, validate_analyst
from phase5r_model_pilot_v3_prompt import (
    CITATION_BINDING_APPENDIX,
    assessment_instructions,
)


ROOT = Path(__file__).resolve().parents[3]
V3_PLAN_PATH = (
    ROOT
    / "08_reviews"
    / "phase5r_model_pilot"
    / "replacement_v3"
    / "phase5r_model_pilot_v3_plan.json"
)


class ReplacementPilotV3PromptTests(unittest.TestCase):
    def test_plan_binds_the_exact_prompt_only_repair(self) -> None:
        plan = json.loads(V3_PLAN_PATH.read_text(encoding="utf-8"))
        change = plan["diagnostic_change"]
        self.assertEqual(change["instruction_appendix"], list(CITATION_BINDING_APPENDIX))
        self.assertFalse(change["validator_or_schema_relaxation"])
        self.assertFalse(change["retry_of_v2"])

    def test_prompt_explicitly_requires_verbatim_ordered_citation_binding(self) -> None:
        instructions = assessment_instructions()
        self.assertIn("source_ids", instructions)
        self.assertIn("cited_excerpt_sha256", instructions)
        self.assertIn("verbatim", instructions)
        self.assertIn("same one-to-one order", instructions)
        self.assertIn("Do not invent, truncate, recompute, or substitute", instructions)

    def test_excerpt_binding_contract_remains_closed(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        invalid = copy.deepcopy(responses["analyst"])
        invalid["claims"][0]["cited_excerpt_sha256"][0] = "0" * 64
        with self.assertRaisesRegex(ContractError, "excerpt binding mismatch"):
            validate_analyst(packet, invalid)


if __name__ == "__main__":
    unittest.main()
