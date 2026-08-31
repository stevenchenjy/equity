#!/usr/bin/env python3
"""Cross-family blinded challenger for Phase 5R research decisions.

The challenger receives the same frozen evidence view and validated analyst
claims as the committee, but never receives the committee or critic outputs.
This module constructs no provider client, reads no credential, sends no email,
touches no canonical artifact, and has no broker/order/execution capability.
"""

from __future__ import annotations

import copy
from typing import Any

from phase5r_daily_common import canonical_sha256, iso_now
from phase5r_llm_contract import (
    ContractError,
    adjudicate,
    compare_blinded_challenger,
    response_schema,
    validate_analyst,
    validate_challenger,
    validate_committee,
    validate_critic,
    validate_packet,
)
from phase5r_llm_provider import ModelProvider
from run_phase5r_llm_shadow import (
    _assert_semantic_references_visible,
    _committee_packet_view,
)


BLINDED_CHALLENGER_PROMPT_VERSION = (
    "phase5r_blinded_challenger_v1"
)
BLINDED_CHALLENGER_INSTRUCTIONS = """You are the blinded Phase 5R research
challenger. Form and precommit an independent, source-bound research decision
from the frozen evidence view and validated analyst claims. You have not seen
and must not infer another model's proposal. Use the same closed
classifications for every ticker. Separate durable thesis evidence from daily
noise; identify the strongest counterevidence and invalidation conditions.
Never invent a price, valuation input, probability, target return, filing fact,
period, or unit. Every non-abstain decision must cite ticker-matched analyst
claim_ids and packet-local source_ids/calculation_ids. Entry/add and ordinary
trim research requires ticker-bound action-grade valuation evidence; a
primary-evidence-supported broken thesis may justify exit_review without a
price target. Overall confidence cannot exceed the weakest component. Treat
the rolling five-year 12–15% return range only as an evaluation aspiration,
never as a quota or guarantee. Do not use tools, browse, execute, send, trade,
or provide order quantities. Set committee_proposal_seen=false,
independent_precommitment=true, and automatic_action_allowed=false."""


def build_blinded_challenger_input(
    packet: dict[str, Any],
    analyst: dict[str, Any],
) -> dict[str, Any]:
    """Return the exact proposal-free semantic input for the challenger."""

    validate_packet(packet)
    validate_analyst(packet, analyst)
    payload = {
        "packet_view": _committee_packet_view(packet),
        "validated_analyst": copy.deepcopy(analyst),
    }
    forbidden_top_level = {
        "committee",
        "critic",
        "proposal",
        "proposed_classification",
        "allowed_classifications_by_ticker",
    }
    if forbidden_top_level.intersection(payload):
        raise ContractError(
            "blinded challenger input contains a proposal-derived field"
        )
    return payload


def execute_blinded_challenger(
    *,
    packet: dict[str, Any],
    analyst: dict[str, Any],
    committee: dict[str, Any],
    critic: dict[str, Any] | None,
    provider: ModelProvider,
    model: str,
    reasoning_effort: str,
    expected_transport: str = "anthropic_messages_injected_client",
    distinct_valid_closes: int = 1,
    distinct_valid_closes_by_ticker: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Run one blinded proposal, then compare and adjudicate locally.

    ``provider`` must be injected by an external caller. The normal production
    transport is a separately authenticated Anthropic client; ``fixture`` is
    accepted only so the complete boundary can be verified without a network.
    """

    validate_packet(packet)
    validate_analyst(packet, analyst)
    validate_committee(packet, committee, analyst)
    if critic is not None:
        validate_critic(packet, committee, critic, analyst)
    if expected_transport not in {
        "anthropic_messages_injected_client",
        "fixture",
    }:
        raise ContractError(
            "blinded challenger transport is not cross-family allowlisted"
        )
    if expected_transport != "fixture" and not str(model).startswith(
        "claude-"
    ):
        raise ContractError(
            "live blinded challenger must use the approved external family"
        )

    input_payload = build_blinded_challenger_input(packet, analyst)
    input_sha256 = canonical_sha256(input_payload)
    result = provider.generate(
        role="challenger",
        model=model,
        reasoning_effort=reasoning_effort,
        schema=response_schema("challenger"),
        instructions=BLINDED_CHALLENGER_INSTRUCTIONS,
        input_payload=input_payload,
    )
    metadata = copy.deepcopy(result.metadata)
    if (
        metadata.get("transport") != expected_transport
        or metadata.get("role") != "challenger"
        or metadata.get("model") != model
        or metadata.get("reasoning_effort") != reasoning_effort
        or metadata.get("input_sha256") != input_sha256
        or metadata.get("credential_read") is not False
        or metadata.get("tools_enabled") is not False
    ):
        raise ContractError(
            "blinded challenger provider metadata failed closed"
        )

    challenger = copy.deepcopy(result.payload)
    validate_challenger(packet, challenger, analyst)
    _assert_semantic_references_visible(
        packet,
        challenger,
        role="challenger",
    )
    comparison = compare_blinded_challenger(
        packet,
        analyst,
        committee,
        challenger,
    )
    final_adjudication = adjudicate(
        packet,
        analyst,
        committee,
        critic,
        challenger=challenger,
        require_blinded_challenger_for_transitions=True,
        distinct_valid_closes=distinct_valid_closes,
        distinct_valid_closes_by_ticker=(
            distinct_valid_closes_by_ticker
        ),
        mode="shadow",
    )
    return {
        "schema_version": "phase5r_llm_blinded_challenger_bundle_v1",
        "generated_at": iso_now(),
        "packet_id": packet["packet_id"],
        "prompt_version": BLINDED_CHALLENGER_PROMPT_VERSION,
        "challenger_input_binding": {
            "input_sha256": input_sha256,
            "input_top_level_keys": sorted(input_payload),
            "committee_proposal_included": False,
            "critic_output_included": False,
        },
        "challenger": challenger,
        "comparison": comparison,
        "adjudication": final_adjudication,
        "provider_metadata": metadata,
        "boundaries": {
            "canonical_effect": False,
            "email_eligible": False,
            "email_attempted": False,
            "smtp_config_read": False,
            "provider_credentials_read_by_repository": False,
            "broker_connected": False,
            "order_code_created": False,
            "trade_placed": False,
        },
    }


__all__ = [
    "BLINDED_CHALLENGER_INSTRUCTIONS",
    "BLINDED_CHALLENGER_PROMPT_VERSION",
    "build_blinded_challenger_input",
    "execute_blinded_challenger",
]
