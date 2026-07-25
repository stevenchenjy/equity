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

    def test_overall_confidence_cannot_exceed_weakest_component(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        response = copy.deepcopy(responses["committee"])
        response["confidence_components"]["valuation_clarity_pct"] = 40
        with self.assertRaisesRegex(ContractError, "weakest component"):
            validate_committee(packet, response)

    def test_automatic_action_boundary_cannot_be_enabled(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        response = copy.deepcopy(responses["committee"])
        response["automatic_action_allowed"] = True
        with self.assertRaises(ContractError):
            validate_committee(packet, response)

    def test_imperative_trade_language_is_rejected(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        for advice in (
            "BUY TST NOW and sell the rest immediately.",
            "立即买入并清仓其他持仓。",
            "Place an order for TST.",
        ):
            with self.subTest(advice=advice):
                response = copy.deepcopy(responses["committee"])
                response["decisive_advice"] = advice
                with self.assertRaisesRegex(ContractError, "imperative"):
                    validate_committee(packet, response)

    def test_ticker_transition_cannot_hide_under_hold_portfolio(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        response = copy.deepcopy(responses["committee"])
        response["ticker_decisions"][0]["classification"] = "real_trade_candidate"
        response["ticker_decisions"][0]["human_review_needed"] = True
        with self.assertRaisesRegex(ContractError, "ticker transition"):
            validate_committee(packet, response)

    def test_ticker_transition_requires_human_review(self) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        response = copy.deepcopy(responses["committee"])
        response["ticker_decisions"][0]["human_review_needed"] = False
        with self.assertRaisesRegex(ContractError, "requires human review"):
            validate_committee(packet, response)

    def test_claim_and_decision_reject_cross_ticker_sources(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        packet["source_catalog"][0]["ticker"] = "OTHER"
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        with self.assertRaisesRegex(ContractError, "cross-ticker source"):
            validate_analyst(packet, responses["analyst"])
        with self.assertRaisesRegex(ContractError, "cross-ticker source"):
            validate_committee(packet, responses["committee"])

    def test_long_term_decision_requires_primary_ticker_evidence(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        packet["source_catalog"][0]["authority"] = (
            "secondary_public_market_context"
        )
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        with self.assertRaisesRegex(ContractError, "primary source"):
            validate_analyst(packet, responses["analyst"])
        with self.assertRaisesRegex(ContractError, "primary source"):
            validate_committee(packet, responses["committee"])

    def test_packet_rejects_secret_identity_and_account_currency_canaries(
        self,
    ) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        mutations = (
            ("SECRET_TOKEN_CANARY=abc123", "secret-like assignment"),
            ("canary.person@example.test", "email address"),
            ("Learning account balance is $2,000.00", "exact local/account"),
            ("/Users/canary/private.txt", "local path|sensitive/local"),
        )
        for value, expected in mutations:
            with self.subTest(value=value):
                candidate = copy.deepcopy(packet)
                candidate["entities"][0]["thesis"] = value
                with self.assertRaisesRegex(ContractError, expected):
                    validate_packet(rehash(candidate))

    def test_packet_rejects_forbidden_private_field(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["entities"][0]["account_balance"] = "redacted"
        with self.assertRaisesRegex(ContractError, "forbidden field"):
            validate_packet(rehash(packet))

    def test_rehashed_fail_closed_packet_is_structurally_valid(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["gates"]["market_data_current"] = False
        self.assertIs(validate_packet(rehash(packet))["gates"]["market_data_current"], False)


if __name__ == "__main__":
    unittest.main()
