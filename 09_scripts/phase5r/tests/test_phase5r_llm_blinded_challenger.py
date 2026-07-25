from __future__ import annotations

import copy
import json
import unittest

from _support import materialized
from phase5r_llm_blinded_challenger import (
    build_blinded_challenger_input,
    execute_blinded_challenger,
)
from phase5r_llm_contract import (
    CHALLENGER_SCHEMA_VERSION,
    ContractError,
    adjudicate,
    compare_blinded_challenger,
    response_schema,
    validate_challenger,
    validate_critic,
)
from phase5r_llm_provider import (
    AnthropicMessagesProvider,
    FixtureProvider,
    ProviderError,
)


def _challenger_from_committee(
    committee: dict[str, object],
) -> dict[str, object]:
    challenger = copy.deepcopy(committee)
    challenger["schema_version"] = CHALLENGER_SCHEMA_VERSION
    challenger["committee_proposal_seen"] = False
    challenger["independent_precommitment"] = True
    return challenger


class _FakeAnthropicMessages:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(copy.deepcopy(kwargs))
        return {
            "id": "msg_test_001",
            "model": kwargs["model"],
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(self.payload),
                }
            ],
            "usage": {
                "input_tokens": 123,
                "output_tokens": 45,
            },
        }


class _FakeAnthropicClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.messages = _FakeAnthropicMessages(payload)


class BlindedChallengerTests(unittest.TestCase):
    def test_challenger_input_hash_is_independent_of_committee_output(
        self,
    ) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        first = build_blinded_challenger_input(
            packet,
            responses["analyst"],
        )
        mutated_committee = copy.deepcopy(responses["committee"])
        mutated_committee["headline"] = "A completely different proposal"
        mutated_committee["ticker_decisions"][0][
            "rationale"
        ] = "Different committee-only text"
        second = build_blinded_challenger_input(
            packet,
            responses["analyst"],
        )
        self.assertEqual(first, second)
        self.assertNotIn("committee", first)
        self.assertNotIn("critic", first)

    def test_exact_blinded_agreement_preserves_transition_research(
        self,
    ) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        challenger = _challenger_from_committee(
            responses["committee"]
        )
        bundle = execute_blinded_challenger(
            packet=packet,
            analyst=responses["analyst"],
            committee=responses["committee"],
            critic=responses["critic"],
            provider=FixtureProvider({"challenger": challenger}),
            model="fixture-cross-family",
            reasoning_effort="high",
            expected_transport="fixture",
            distinct_valid_closes=closes,
        )
        self.assertEqual(
            bundle["comparison"]["ticker_comparisons"][0][
                "agreement_type"
            ],
            "exact",
        )
        self.assertEqual(
            bundle["adjudication"]["research_classification"],
            "paper_trade_candidate",
        )
        self.assertTrue(
            bundle["adjudication"]["blinded_challenger_present"]
        )
        self.assertFalse(
            bundle["challenger_input_binding"][
                "committee_proposal_included"
            ]
        )
        self.assertFalse(
            bundle["boundaries"]["provider_credentials_read_by_repository"]
        )

    def test_transition_disagreement_abstains_without_cross_ticker_upgrade(
        self,
    ) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        challenger = _challenger_from_committee(
            responses["committee"]
        )
        challenger["portfolio_classification"] = "hold_existing"
        challenger["material_thesis_break"] = False
        challenger["ticker_decisions"][0].update(
            {
                "classification": "hold_existing",
                "thesis_direction": "stable",
                "human_review_needed": False,
            }
        )
        comparison = compare_blinded_challenger(
            packet,
            responses["analyst"],
            responses["committee"],
            challenger,
        )
        self.assertEqual(
            comparison["ticker_comparisons"][0]["agreement_type"],
            "transition_disagreement",
        )
        self.assertEqual(
            comparison["research_classification_ceiling"],
            "abstain",
        )
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            challenger=challenger,
            require_blinded_challenger_for_transitions=True,
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["research_classification"], "abstain")
        self.assertTrue(result["human_review_required"])
        self.assertFalse(
            comparison["challenger_can_upgrade"]
        )

    def test_required_missing_challenger_fails_transition_closed(self) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            require_blinded_challenger_for_transitions=True,
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["research_classification"], "abstain")
        self.assertIn(
            "challenger_required_but_missing:TST",
            result["reasons"],
        )

    def test_challenger_schema_is_closed_and_declares_blindness(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        challenger = _challenger_from_committee(
            responses["committee"]
        )
        validate_challenger(
            packet,
            challenger,
            responses["analyst"],
        )
        challenger["committee_proposal_seen"] = True
        with self.assertRaises(ContractError):
            validate_challenger(
                packet,
                challenger,
                responses["analyst"],
            )

    def test_critic_cannot_downgrade_without_failed_check_and_issue(
        self,
    ) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        critic = copy.deepcopy(responses["critic"])
        critic["verdict"] = "revise"
        critic["downgrade_to"] = "abstain"
        critic["ticker_reviews"][0]["verdict"] = "revise"
        critic["ticker_reviews"][0]["downgrade_to"] = "abstain"
        critic["ticker_reviews"][0]["issues"] = []
        with self.assertRaisesRegex(
            ContractError,
            "failed critic check",
        ):
            validate_critic(
                packet,
                responses["committee"],
                critic,
                responses["analyst"],
            )

    def test_anthropic_adapter_uses_strict_tool_free_injected_client(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        challenger = _challenger_from_committee(
            responses["committee"]
        )
        client = _FakeAnthropicClient(challenger)
        provider = AnthropicMessagesProvider(client, max_tokens=4096)
        result = provider.generate(
            role="challenger",
            model="claude-fable-5",
            reasoning_effort="high",
            schema=response_schema("challenger"),
            instructions="Return the blinded decision.",
            input_payload={"packet_view": {"packet_id": packet["packet_id"]}},
        )
        request = client.messages.calls[0]
        self.assertEqual(request["tools"], [])
        self.assertEqual(
            request["output_config"]["format"]["type"],
            "json_schema",
        )
        self.assertEqual(
            request["output_config"]["effort"],
            "high",
        )
        self.assertEqual(
            result.metadata["transport"],
            "anthropic_messages_injected_client",
        )
        self.assertFalse(result.metadata["credential_read"])
        self.assertFalse(result.metadata["tools_enabled"])
        self.assertEqual(result.metadata["usage"]["input_tokens"], 123)

        with self.assertRaises(ProviderError):
            provider.generate(
                role="committee",
                model="claude-fable-5",
                reasoning_effort="high",
                schema=response_schema("committee"),
                instructions="invalid role",
                input_payload={},
            )


if __name__ == "__main__":
    unittest.main()
