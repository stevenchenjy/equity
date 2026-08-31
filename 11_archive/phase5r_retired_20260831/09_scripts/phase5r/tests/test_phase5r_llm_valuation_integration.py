from __future__ import annotations

import copy
import unittest

from _support import materialized, rehash
from phase5r_llm_contract import (
    ContractError,
    adjudicate,
    validate_committee,
    validate_packet,
)
from phase5r_valuation_evidence_v1 import (
    build_valuation_evidence_v1,
    valuation_packet_calculations,
)


def _without_target(packet: dict[str, object]) -> dict[str, object]:
    candidate = copy.deepcopy(packet)
    complete = candidate["valuation_evidence"][0]  # type: ignore[index]
    inputs = {
        row["input_id"]: {
            key: value
            for key, value in row.items()
            if key != "input_id"
        }
        for row in complete["input_receipts"]
        if row["input_id"] != "target_price_assumption"
    }
    receipt = build_valuation_evidence_v1(
        ticker="TST",
        as_of_utc=complete["as_of_utc"],
        inputs=inputs,
    )
    candidate["valuation_evidence"] = [receipt]
    candidate["gates"]["valuation_action_grade_tickers"] = []  # type: ignore[index]
    candidate["calculations"] = [  # type: ignore[index]
        row
        for row in candidate["calculations"]  # type: ignore[index]
        if not str(row["calculation_id"]).startswith("valuation:")
    ] + valuation_packet_calculations(receipt)
    return rehash(candidate)


def _bind_packet_id(
    responses: dict[str, dict[str, object]],
    packet_id: str,
) -> None:
    for response in responses.values():
        response["packet_id"] = packet_id


class ValuationPacketIntegrationTests(unittest.TestCase):
    def test_action_grade_list_cannot_exist_without_sufficient_receipt(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet = _without_target(packet)
        packet["gates"]["valuation_action_grade_tickers"] = ["TST"]
        with self.assertRaisesRegex(
            ContractError,
            "valuation action-grade tickers",
        ):
            validate_packet(rehash(packet))

    def test_nonzero_valuation_clarity_requires_reconciled_receipt(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        packet = _without_target(packet)
        _bind_packet_id(responses, packet["packet_id"])
        with self.assertRaisesRegex(
            ContractError,
            "valuation clarity must be zero",
        ):
            validate_committee(
                packet,
                responses["committee"],
                responses["analyst"],
            )

    def test_insufficient_ticker_valuation_blocks_transition(self) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        packet = _without_target(packet)
        _bind_packet_id(responses, packet["packet_id"])
        committee = responses["committee"]
        committee["confidence_components"]["valuation_clarity_pct"] = 0
        committee["confidence_pct"] = 0
        committee["ticker_decisions"][0]["calculation_ids"] = [
            "valuation:TST:free_cash_flow_yield_pct"
        ]
        result = adjudicate(
            packet,
            responses["analyst"],
            committee,
            responses["critic"],
            distinct_valid_closes=2,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertIn(
            "transition_confidence_sanity_failed:"
            "committee_component_at_or_below_1:TST:"
            "valuation_clarity_pct",
            result["reasons"],
        )
        self.assertEqual(
            result["ticker_decisions"][0]["research_classification"],
            "abstain",
        )
        self.assertEqual(
            result["ticker_decisions"][0]["action_review_status"],
            "not_applicable",
        )
        self.assertFalse(result["automatic_action_allowed"])
        self.assertTrue(result["human_review_required"])


if __name__ == "__main__":
    unittest.main()
