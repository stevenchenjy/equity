from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import Any

from _support import materialized, rehash
from phase5r_llm_contract import ContractError
from phase5r_llm_provider import FixtureProvider, ProviderResult
from run_phase5r_llm_shadow import execute_shadow, load_registry


class RecordingFixtureProvider:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = copy.deepcopy(responses)
        self.inputs: dict[str, dict[str, Any]] = {}

    def generate(
        self,
        *,
        role: str,
        model: str,
        reasoning_effort: str,
        schema: dict[str, Any],
        instructions: str,
        input_payload: dict[str, Any],
    ) -> ProviderResult:
        del model, reasoning_effort, schema, instructions
        self.inputs[role] = copy.deepcopy(input_payload)
        return ProviderResult(
            payload=copy.deepcopy(self.responses[role]),
            metadata={
                "transport": "fixture",
                "credential_read": False,
                "tools_enabled": False,
                "role": role,
            },
        )


def _replace_packet_id(responses: dict[str, Any], packet_id: str) -> None:
    for role in ("analyst", "committee", "critic"):
        responses[role]["packet_id"] = packet_id


class RoleScopedProviderInputTests(unittest.TestCase):
    def test_provider_input_byte_budget_fails_before_any_call(self) -> None:
        packet, responses, closes = materialized("g01_stable_hold")
        packet["entities"][0]["thesis"] = "x" * (600 * 1024)
        packet = rehash(packet)
        _replace_packet_id(responses, packet["packet_id"])
        provider = RecordingFixtureProvider(responses)
        with self.assertRaisesRegex(ContractError, "byte budget"):
            execute_shadow(
                packet,
                provider,
                load_registry(),
                distinct_valid_closes=closes,
            )
        self.assertEqual(provider.inputs, {})

    def test_each_role_receives_only_its_authorized_evidence(self) -> None:
        packet, responses, closes = materialized("g04_valid_numeric_reconciliation")
        cited_source = packet["source_catalog"][0]
        cited_excerpt = "CITED_EXCERPT_SENTINEL_5R"
        cited_source["excerpt_text"] = cited_excerpt
        cited_source["content_sha256"] = hashlib.sha256(
            cited_excerpt.encode("utf-8")
        ).hexdigest()

        unrelated_source = copy.deepcopy(packet["source_catalog"][1])
        unrelated_excerpt = "UNREFERENCED_EXCERPT_SENTINEL_5R"
        unrelated_source.update(
            {
                "source_id": "market:TST:unreferenced-sentinel",
                "excerpt_text": unrelated_excerpt,
                "content_sha256": hashlib.sha256(
                    unrelated_excerpt.encode("utf-8")
                ).hexdigest(),
            }
        )
        packet["source_catalog"].append(unrelated_source)
        packet = rehash(packet)
        _replace_packet_id(responses, packet["packet_id"])

        provider = RecordingFixtureProvider(responses)
        bundle = execute_shadow(
            packet,
            provider,
            load_registry(),
            distinct_valid_closes=closes,
        )

        self.assertEqual(set(provider.inputs), {"analyst", "committee", "critic"})
        analyst_input = provider.inputs["analyst"]
        committee_input = provider.inputs["committee"]
        critic_input = provider.inputs["critic"]

        self.assertEqual(analyst_input, {"packet": packet})
        self.assertIn(cited_excerpt, json.dumps(analyst_input))
        self.assertIn(unrelated_excerpt, json.dumps(analyst_input))

        committee_serialized = json.dumps(committee_input, sort_keys=True)
        self.assertNotIn("packet", committee_input)
        self.assertNotIn(cited_excerpt, committee_serialized)
        self.assertNotIn(unrelated_excerpt, committee_serialized)
        self.assertNotIn("excerpt_text", committee_serialized)
        self.assertEqual(
            committee_input["packet_view"]["packet_identity"]["packet_id"],
            packet["packet_id"],
        )

        critic_view = critic_input["packet_view"]
        critic_serialized = json.dumps(critic_input, sort_keys=True)
        self.assertNotIn("packet", critic_input)
        self.assertIn(cited_excerpt, critic_serialized)
        self.assertIn(unrelated_excerpt, critic_serialized)
        self.assertEqual(
            [row["source_id"] for row in critic_view["cited_sources"]],
            ["sec:TST:10Q:2026Q1:0"],
        )
        self.assertEqual(
            [
                row["calculation_id"]
                for row in critic_view["referenced_calculations"]
            ],
            ["calc:revenue_yoy:TST:CY2026Q1"],
        )
        self.assertEqual(
            [
                row["source_id"]
                for row in critic_view[
                    "uncited_sources_for_omission_check"
                ]
                if row["source_id"]
                == "market:TST:unreferenced-sentinel"
            ],
            ["market:TST:unreferenced-sentinel"],
        )
        self.assertTrue(bundle["adjudication"]["validation_passed"])

    def test_role_scoping_does_not_change_existing_fixture_result(self) -> None:
        packet, responses, closes = materialized("g01_stable_hold")
        fixture_bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=closes,
        )
        recording_bundle = execute_shadow(
            packet,
            RecordingFixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=closes,
        )
        for field in (
            "outcome",
            "model_run_id",
            "packet_id",
            "decision_fingerprint",
            "analyst",
            "committee",
            "critic",
            "adjudication",
            "boundaries",
        ):
            self.assertEqual(recording_bundle[field], fixture_bundle[field])


if __name__ == "__main__":
    unittest.main()
