from __future__ import annotations

import copy
import unittest

from _support import materialized, rehash
from phase5r_llm_contract import (
    ContractError,
    _expected_verified_close_session,
    validate_analyst,
    validate_committee,
    validate_critic,
    validate_packet,
)


class ContractTests(unittest.TestCase):
    def test_verified_close_uses_last_open_session_on_weekend(self) -> None:
        self.assertEqual(
            _expected_verified_close_session("2026-08-01"),
            "2026-07-31",
        )
        self.assertEqual(
            _expected_verified_close_session("2026-07-31"),
            "2026-07-31",
        )
        with self.assertRaisesRegex(ContractError, "cycle_date"):
            _expected_verified_close_session("2026-08-01T00:00:00Z")

    def test_verified_close_uses_prior_session_before_market_close(self) -> None:
        self.assertEqual(
            _expected_verified_close_session(
                "2026-08-31",
                "2026-08-31T12:30:00-04:00",
            ),
            "2026-08-28",
        )
        self.assertEqual(
            _expected_verified_close_session(
                "2026-08-31",
                "2026-08-31T16:30:00-04:00",
            ),
            "2026-08-31",
        )

    def test_base_fixture_satisfies_all_closed_contracts(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        self.assertIs(validate_packet(packet), packet)
        self.assertIs(validate_analyst(packet, responses["analyst"]), responses["analyst"])
        self.assertIs(
            validate_committee(
                packet,
                responses["committee"],
                responses["analyst"],
            ),
            responses["committee"],
        )
        self.assertIs(
            validate_critic(
                packet,
                responses["committee"],
                responses["critic"],
                responses["analyst"],
            ),
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

    def test_market_action_grade_is_bound_to_explicit_ticker_membership(
        self,
    ) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        for enabled, tickers in (
            (True, []),
            (False, ["TST"]),
            (True, ["ALT"]),
        ):
            with self.subTest(enabled=enabled, tickers=tickers):
                candidate = copy.deepcopy(packet)
                candidate["gates"]["market_data_action_grade"] = enabled
                candidate["gates"]["market_data_action_grade_tickers"] = tickers
                with self.assertRaises(ContractError):
                    validate_packet(rehash(candidate))

        candidate = copy.deepcopy(packet)
        candidate["gates"]["market_data_action_grade"] = False
        candidate["gates"].pop("market_data_action_grade_tickers")
        self.assertEqual(
            validate_packet(rehash(candidate))["gates"].get(
                "market_data_action_grade_tickers",
                [],
            ),
            [],
        )

    def test_c9_allowed_classification_map_is_exact_and_role_safe(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        mutations = (
            {},
            {"TST": ["hold_existing"]},
            {"TST": ["hold_existing", "watchlist", "abstain"]},
            {
                "TST": [
                    "hold_existing",
                    "abstain",
                    "abstain",
                ]
            },
            {"TST": ["hold_existing", "abstain"], "ALT": ["abstain"]},
        )
        for allowed in mutations:
            with self.subTest(allowed=allowed):
                candidate = copy.deepcopy(packet)
                candidate["gates"][
                    "allowed_classifications_by_ticker"
                ] = allowed
                with self.assertRaisesRegex(
                    ContractError,
                    "allowed classifications",
                ):
                    validate_packet(rehash(candidate))

    def test_return_objective_cannot_become_quota_guarantee_or_override(
        self,
    ) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        for field in (
            "monthly_or_annual_quota",
            "return_guarantee",
            "risk_gates_override_allowed",
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(packet)
                candidate["portfolio_constraints"]["return_objective"][field] = True
                with self.assertRaisesRegex(
                    ContractError,
                    "return objective",
                ):
                    validate_packet(rehash(candidate))

    def test_portfolio_constraints_are_exact_bounded_and_manual(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        mutations = (
            (
                "zero hard cap",
                lambda row: row.__setitem__(
                    "active_stock_hard_cap_pct",
                    0,
                ),
                "portfolio cap",
            ),
            (
                "targets do not sum to one hundred",
                lambda row: row.__setitem__("cash_target_pct", 9),
                "targets must sum to 100",
            ),
            (
                "automatic execution",
                lambda row: row.__setitem__("manual_execution_only", False),
                "execution must remain manual",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                candidate = copy.deepcopy(packet)
                mutate(candidate["portfolio_constraints"])
                with self.assertRaisesRegex(ContractError, message):
                    validate_packet(rehash(candidate))

    def test_analyst_claim_is_bound_to_nonempty_cited_excerpt(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        analyst = copy.deepcopy(responses["analyst"])
        analyst["claims"][0]["cited_excerpt_sha256"][0] = "0" * 64
        with self.assertRaisesRegex(ContractError, "excerpt binding mismatch"):
            validate_analyst(packet, analyst)
        analyst = copy.deepcopy(responses["analyst"])
        analyst["claims"][0]["rationale"] = ""
        with self.assertRaisesRegex(ContractError, "rationale must be non-empty"):
            validate_analyst(packet, analyst)

    def test_analyst_as_of_must_exactly_match_packet(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        analyst = copy.deepcopy(responses["analyst"])
        analyst["as_of_et"] = "2026-07-23T18:30:01-04:00"
        with self.assertRaisesRegex(ContractError, "exactly match"):
            validate_analyst(packet, analyst)

    def test_committee_claim_links_and_entity_coverage_are_exact(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        committee = copy.deepcopy(responses["committee"])
        committee["ticker_decisions"][0]["claim_ids"] = []
        with self.assertRaisesRegex(ContractError, "requires analyst claim_ids"):
            validate_committee(packet, committee, responses["analyst"])

        packet["entities"].append(
            {
                **copy.deepcopy(packet["entities"][0]),
                "ticker": "ALT",
                "role": "candidate",
                "position_weight_band": "not_held",
                "position_weight_pct_rounded": "0.0",
            }
        )
        packet = rehash(packet)
        committee = copy.deepcopy(responses["committee"])
        committee["packet_id"] = packet["packet_id"]
        with self.assertRaisesRegex(ContractError, "exactly match"):
            validate_committee(packet, committee)

    def test_critic_ticker_reviews_are_authoritative_and_exact(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        critic = copy.deepcopy(responses["critic"])
        critic["ticker_reviews"] = []
        with self.assertRaisesRegex(ContractError, "exactly match"):
            validate_critic(packet, responses["committee"], critic)

        critic = copy.deepcopy(responses["critic"])
        critic["approved_source_ids"] = []
        with self.assertRaisesRegex(ContractError, "sorted per-ticker union"):
            validate_critic(packet, responses["committee"], critic)


if __name__ == "__main__":
    unittest.main()
