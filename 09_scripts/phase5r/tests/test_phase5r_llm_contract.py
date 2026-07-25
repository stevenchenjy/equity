from __future__ import annotations

import copy
import unittest

from _support import materialized, rehash
from phase5r_llm_contract import (
    ContractError,
    validate_analyst,
    validate_committee,
    validate_critic,
    validate_packet,
)


class ContractTests(unittest.TestCase):
    def test_base_fixture_satisfies_all_closed_contracts(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        self.assertIs(validate_packet(packet), packet)
        self.assertIs(validate_analyst(packet, responses["analyst"]), responses["analyst"])
        self.assertIs(
            validate_committee(packet, responses["committee"]),
            responses["committee"],
        )
        self.assertIs(
            validate_critic(packet, responses["committee"], responses["critic"]),
            responses["critic"],
        )

    def test_packet_hash_tampering_is_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["gates"]["market_data_current"] = False
        with self.assertRaisesRegex(ContractError, "packet_id"):
            validate_packet(packet)

    def test_unknown_committee_field_is_rejected(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        response = copy.deepcopy(responses["committee"])
        response["unexpected"] = "blocked"
        with self.assertRaisesRegex(ContractError, "unexpected fields"):
            validate_committee(packet, response)

    def test_unknown_classification_is_rejected(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        response = copy.deepcopy(responses["committee"])
        response["portfolio_classification"] = "buy_now"
        with self.assertRaisesRegex(ContractError, "outside enum"):
            validate_committee(packet, response)

    def test_out_of_range_confidence_is_rejected(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        response = copy.deepcopy(responses["committee"])
        response["confidence_pct"] = 101
        with self.assertRaisesRegex(ContractError, "0..100"):
            validate_committee(packet, response)

    def test_automatic_action_boundary_cannot_be_enabled(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        response = copy.deepcopy(responses["committee"])
        response["automatic_action_allowed"] = True
        with self.assertRaises(ContractError):
            validate_committee(packet, response)

    def test_rehashed_fail_closed_packet_is_structurally_valid(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["gates"]["market_data_current"] = False
        self.assertIs(validate_packet(rehash(packet))["gates"]["market_data_current"], False)


if __name__ == "__main__":
    unittest.main()
