from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import Any

from _support import materialized, rehash
from phase5r_daily_common import canonical_sha256
from phase5r_llm_contract import ContractError
from phase5r_llm_provider import FixtureProvider, ProviderResult
from run_phase5r_llm_shadow import (
    _analyst_packet_view,
    _assert_semantic_references_visible,
    execute_shadow,
    load_registry,
)


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
        del schema, instructions
        self.inputs[role] = copy.deepcopy(input_payload)
        payload = copy.deepcopy(self.responses[role])
        return ProviderResult(
            payload=payload,
            metadata={
                "transport": "fixture",
                "credential_read": False,
                "tools_enabled": False,
                "role": role,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "input_sha256": canonical_sha256(input_payload),
                "output_sha256": canonical_sha256(payload),
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
        for claim in responses["analyst"]["claims"]:
            if cited_source["source_id"] in claim["source_ids"]:
                claim["cited_excerpt_sha256"] = [
                    cited_source["content_sha256"]
                    if source_id == cited_source["source_id"]
                    else cited_hash
                    for source_id, cited_hash in zip(
                        claim["source_ids"],
                        claim["cited_excerpt_sha256"],
                        strict=True,
                    )
                ]

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

        self.assertNotIn("packet", analyst_input)
        self.assertEqual(
            analyst_input["packet_view"]["packet_identity"]["packet_id"],
            packet["packet_id"],
        )
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

    def test_semantic_views_hide_c9_answers_and_scores(self) -> None:
        packet, responses, closes = materialized("g01_stable_hold")
        packet["entities"][0]["deterministic_recommendation"] = (
            "DO_NOT_LEAK_ENTITY_RECOMMENDATION"
        )
        packet["gates"].update(
            {
                "deterministic_transition_eligible_tickers": ["TST"],
                "deterministic_transition_pending_tickers": ["TST"],
                "deterministic_action_stability_distinct_closes": 99,
            }
        )
        packet["research_context"] = [
            {
                "ticker": "TST",
                "recommendation_label": "DO_NOT_LEAK_RESEARCH_LABEL",
                "recommended_action": "DO_NOT_LEAK_RESEARCH_ACTION",
                "deterministic_conviction_score": "9.9",
                "source_id": "research-context:TST:fixture",
            }
        ]
        packet["source_catalog"].append(
            {
                "source_id": "research-context:TST:fixture",
                "source_type": "derived_research_context",
                "ticker": "TST",
                "accepted_at": "2026-07-23T18:00:00-04:00",
                "source_url": "",
                "content_sha256": hashlib.sha256(
                    b"DO_NOT_LEAK_RESEARCH_SOURCE"
                ).hexdigest(),
                "locator": {"dataset": "phase5r_c5_c9", "ticker": "TST"},
                "authority": "derived_not_primary",
                "excerpt_text": "DO_NOT_LEAK_RESEARCH_SOURCE",
            }
        )
        packet["calculations"].append(
            {
                "calculation_id": "calc:c9_score:TST:fixture",
                "ticker": "TST",
                "metric": "account_aware_conviction_score",
                "value": "9.9",
                "recomputed_value": "9.9",
                "unit": "score_0_to_10",
                "period": "2026-07-23",
                "formula": "DO_NOT_LEAK_C9_CALCULATION",
                "source_ids": ["research-context:TST:fixture"],
                "reconciled": True,
            }
        )
        packet = rehash(packet)
        _replace_packet_id(responses, packet["packet_id"])

        provider = RecordingFixtureProvider(responses)
        execute_shadow(
            packet,
            provider,
            load_registry(),
            distinct_valid_closes=closes,
        )

        serialized_inputs = json.dumps(provider.inputs, sort_keys=True)
        for sentinel in (
            "DO_NOT_LEAK_ENTITY_RECOMMENDATION",
            "DO_NOT_LEAK_RESEARCH_LABEL",
            "DO_NOT_LEAK_RESEARCH_ACTION",
            "DO_NOT_LEAK_RESEARCH_SOURCE",
            "DO_NOT_LEAK_C9_CALCULATION",
        ):
            self.assertNotIn(sentinel, serialized_inputs)
        for role in ("analyst", "committee", "critic"):
            role_view = provider.inputs[role]["packet_view"]
            self.assertNotIn(
                "deterministic_transition_eligible_tickers",
                role_view["gates"],
            )
            self.assertNotIn(
                "deterministic_transition_pending_tickers",
                role_view["gates"],
            )
            self.assertNotIn(
                "allowed_classifications_by_ticker",
                role_view["gates"],
            )
        self.assertNotIn(
            "deterministic_recommendation",
            _analyst_packet_view(packet)["entities"][0],
        )

        with self.assertRaisesRegex(
            ContractError,
            "hidden semantic source reference",
        ):
            _assert_semantic_references_visible(
                packet,
                {
                    "source_ids": ["research-context:TST:fixture"],
                    "calculation_ids": [],
                },
                role="analyst",
            )
        with self.assertRaisesRegex(
            ContractError,
            "hidden semantic calculation reference",
        ):
            _assert_semantic_references_visible(
                packet,
                {
                    "source_ids": [],
                    "calculation_ids": ["calc:c9_score:TST:fixture"],
                },
                role="committee",
            )

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
