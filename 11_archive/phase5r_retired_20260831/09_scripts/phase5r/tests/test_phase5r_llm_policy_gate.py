from __future__ import annotations

import copy
import unittest

from _support import evaluated, materialized, rehash
from phase5r_evidence_freshness import build_evidence_freshness_receipt
from phase5r_llm_contract import (
    ContractError,
    adjudicate,
    validate_committee,
    validate_critic,
)
from phase5r_llm_provider import FixtureProvider
from phase5r_valuation_evidence_v1 import (
    build_valuation_evidence_v1,
    valuation_packet_calculations,
)
from run_phase5r_llm_shadow import (
    apply_verified_close_stability,
    execute_shadow,
    load_registry,
)


def _add_synthetic_ticker_valuation(
    packet: dict[str, object],
    *,
    ticker: str,
    source_id: str,
) -> None:
    base_receipt = packet["valuation_evidence"][0]  # type: ignore[index]
    inputs = {
        row["input_id"]: {
            key: (
                [source_id]
                if key == "source_ids"
                else copy.deepcopy(value)
            )
            for key, value in row.items()
            if key != "input_id"
        }
        for row in base_receipt["input_receipts"]
    }
    receipt = build_valuation_evidence_v1(
        ticker=ticker,
        as_of_utc=base_receipt["as_of_utc"],
        inputs=inputs,
    )
    packet["valuation_evidence"].append(receipt)  # type: ignore[union-attr]
    packet["calculations"].extend(  # type: ignore[union-attr]
        valuation_packet_calculations(receipt)
    )
    packet["gates"]["valuation_action_grade_tickers"].append(ticker)  # type: ignore[index,union-attr]
    packet["gates"]["valuation_action_grade_tickers"].sort()  # type: ignore[index,union-attr]
    market_row = copy.deepcopy(packet["market_observations"][0])  # type: ignore[index]
    market_row["ticker"] = ticker
    market_row["source_id"] = source_id
    packet["market_observations"].append(market_row)  # type: ignore[union-attr]
    valuation_inputs = {
        row["input_id"]: row for row in receipt["input_receipts"]
    }
    scenario_times = sorted(
        valuation_inputs[input_id]["available_at_utc"]
        for input_id in (
            "target_price_assumption",
            "downside_price_assumption",
        )
    )
    base_freshness = packet["evidence_freshness"][0]  # type: ignore[index]
    packet["evidence_freshness"].append(  # type: ignore[union-attr]
        build_evidence_freshness_receipt(
            ticker=ticker,
            as_of_utc=base_freshness["as_of_utc"],
            sec_scan={
                key: base_freshness["sec_scan"][key]
                for key in (
                    "status_artifact_sha256",
                    "completed_through_utc",
                    "ticker_scanned",
                    "complete",
                )
            },
            market={
                "observed_at_utc": "2026-07-23T20:15:00Z",
                "market_session_date": market_row["market_session_date"],
                "expected_market_session_date": packet["gates"].get(  # type: ignore[union-attr]
                    "verified_close_session",
                    packet["cycle_date"],
                ),
                "complete_close": market_row["bar_state"] == "complete_close",
            },
            valuation={
                "valuation_receipt_sha256": receipt["receipt_sha256"],
                "receipt_as_of_utc": receipt["as_of_utc"],
                "market_input_at_utc": valuation_inputs["share_price"][
                    "available_at_utc"
                ],
                "market_session_date": valuation_inputs["share_price"][
                    "period"
                ],
                "expected_market_session_date": packet["gates"].get(  # type: ignore[union-attr]
                    "verified_close_session",
                    packet["cycle_date"],
                ),
                "scenario_refreshed_at_utc": scenario_times[-1],
                "complete": True,
            },
            durable_sec_source_ids=[source_id],
        )
    )


class PolicyGateTests(unittest.TestCase):
    def test_golden_policy_matrix(self) -> None:
        expected = {
            "g01_stable_hold": "hold_existing",
            "g07_add_first_close": "hold_existing",
            "g08_add_second_close": "paper_trade_candidate",
            "g09_critic_disagreement": "hold_existing",
            "g10_material_thesis_break": "exit_review",
            "g11_stale_market_data": "hold_existing",
            "g12_prompt_injection": "abstain",
        }
        for case_id, classification in expected.items():
            with self.subTest(case_id=case_id):
                result = evaluated(case_id)
                self.assertTrue(result["passed"])
                self.assertEqual(
                    result["actual"]["safe_classification"], classification
                )

    def test_first_close_cannot_promote_candidate(self) -> None:
        result = evaluated("g07_add_first_close")
        self.assertEqual(result["actual"]["raw_classification"], "hold_existing")
        self.assertFalse(result["actual"]["human_review_required"])
        packet, responses, closes = materialized("g07_add_first_close")
        adjudication = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(
            adjudication["ticker_decisions"][0]["classification"],
            "hold_existing",
        )

    def test_second_close_transition_requires_human_review(self) -> None:
        result = evaluated("g08_add_second_close")
        self.assertEqual(
            result["actual"]["raw_classification"], "paper_trade_candidate"
        )
        self.assertTrue(result["actual"]["human_review_required"])

    def test_transition_requires_structurally_non_negligible_confidence(
        self,
    ) -> None:
        mutations = (
            (
                "committee_overall_zero",
                "transition_confidence_sanity_failed:"
                "committee_overall_at_or_below_1:TST",
            ),
            (
                "committee_component_placeholder",
                "transition_confidence_sanity_failed:"
                "committee_component_at_or_below_1:"
                "TST:evidence_coverage_pct",
            ),
            (
                "ticker_placeholder",
                "transition_confidence_sanity_failed:"
                "ticker_at_or_below_1:TST",
            ),
        )
        for case_id in (
            "g08_add_second_close",
            "g10_material_thesis_break",
        ):
            for mutation, expected_reason in mutations:
                with self.subTest(case_id=case_id, mutation=mutation):
                    packet, responses, closes = materialized(case_id)
                    committee = responses["committee"]
                    if mutation == "committee_overall_zero":
                        committee["confidence_pct"] = 0
                    elif mutation == "committee_component_placeholder":
                        committee["confidence_pct"] = 1
                        committee["confidence_components"][
                            "evidence_coverage_pct"
                        ] = 1
                    else:
                        committee["ticker_decisions"][0][
                            "confidence_pct"
                        ] = 1
                    result = adjudicate(
                        packet,
                        responses["analyst"],
                        committee,
                        responses["critic"],
                        distinct_valid_closes=closes,
                    )
                    decision = result["ticker_decisions"][0]
                    self.assertEqual(
                        decision["research_classification"],
                        "abstain",
                    )
                    self.assertNotIn(
                        decision["classification"],
                        {
                            "paper_trade_candidate",
                            "real_trade_candidate",
                            "trim_review",
                            "exit_review",
                        },
                    )
                    self.assertIn(
                        expected_reason,
                        decision["research_reasons"],
                    )
                    self.assertIn(expected_reason, result["reasons"])
                    self.assertFalse(result["validation_passed"])

    def test_candidate_cannot_bypass_deterministic_ticker_eligibility(
        self,
    ) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        packet["gates"]["deterministic_transition_eligible_tickers"] = []
        packet["gates"]["deterministic_transition_pending_tickers"] = ["TST"]
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=2,
            distinct_valid_closes_by_ticker={"TST": 2},
        )
        self.assertEqual(
            result["ticker_decisions"][0]["classification"],
            "hold_existing",
        )
        self.assertIn(
            "transition_eligibility_pending_or_unknown:TST",
            result["ticker_decisions"][0]["reasons"],
        )

    def test_secondary_market_data_cannot_unlock_buy_transition(self) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        packet["gates"]["market_data_action_grade"] = False
        packet["gates"]["market_data_action_grade_tickers"] = []
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        decision = result["ticker_decisions"][0]
        self.assertEqual(
            decision["research_classification"],
            "paper_trade_candidate",
        )
        self.assertEqual(decision["classification"], "hold_existing")
        self.assertEqual(decision["action_review_status"], "blocked")
        self.assertIn(
            "transition_gate_failed:market_data_action_grade",
            decision["action_review_reasons"],
        )
        self.assertNotIn(
            "transition_gate_failed:market_data_action_grade",
            decision["research_reasons"],
        )

    def test_stale_market_gate_is_visible_without_erasing_hold_research(
        self,
    ) -> None:
        packet, responses, closes = materialized("g11_stale_market_data")
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        decision = result["ticker_decisions"][0]
        self.assertEqual(
            decision["research_classification"],
            "hold_existing",
        )
        self.assertEqual(decision["classification"], "hold_existing")
        self.assertEqual(decision["action_review_status"], "not_applicable")
        self.assertIn(
            "action_gate_failed:market_data_current",
            decision["action_review_reasons"],
        )
        self.assertNotIn(
            "action_gate_failed:market_data_current",
            decision["research_reasons"],
        )

    def test_primary_source_thesis_break_can_reach_exit_review(self) -> None:
        packet, responses, closes = materialized("g10_material_thesis_break")
        packet["gates"]["market_data_action_grade"] = False
        packet["gates"]["market_data_action_grade_tickers"] = []
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "exit_review")
        self.assertNotIn(
            "transition_gate_failed:market_data_action_grade",
            result["reasons"],
        )

    def test_c9_action_cap_does_not_erase_model_exit_research(self) -> None:
        packet, responses, closes = materialized("g10_material_thesis_break")
        packet["gates"]["allowed_classifications_by_ticker"]["TST"] = [
            "hold_existing",
            "abstain",
        ]
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        decision = result["ticker_decisions"][0]
        self.assertEqual(decision["classification"], "hold_existing")
        self.assertEqual(
            decision["research_classification"],
            "exit_review",
        )
        self.assertEqual(
            decision["action_review_classification"],
            "hold_existing",
        )
        self.assertEqual(decision["action_review_status"], "blocked")
        self.assertEqual(result["research_classification"], "exit_review")
        self.assertEqual(
            result["action_review_classification"],
            "hold_existing",
        )
        self.assertFalse(result["action_review_aligned"])
        self.assertIn(
            "c9_classification_not_allowed:TST:exit_review",
            decision["reasons"],
        )
        self.assertTrue(result["human_review_required"])
        self.assertIn("C9 动作资格未完全通过", result["headline"])

    def test_self_declared_thesis_break_without_high_primary_claim_abstains(
        self,
    ) -> None:
        packet, responses, closes = materialized("g10_material_thesis_break")
        responses["analyst"]["claims"][0]["stance"] = "supports"
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertIn(
            "material_thesis_break_lacks_high_primary_support",
            result["reasons"],
        )

    def test_transition_requires_resolved_official_analyst_coverage(self) -> None:
        for mutation, expected_reason in (
            (
                {"official_evidence_sufficient": False},
                "transition_official_evidence_insufficient:TST",
            ),
            (
                {"contradictory_evidence": True},
                "transition_contradictory_evidence_unresolved:TST",
            ),
        ):
            with self.subTest(mutation=mutation):
                packet, responses, closes = materialized(
                    "g08_add_second_close"
                )
                responses["analyst"]["ticker_coverage"][0].update(mutation)
                result = adjudicate(
                    packet,
                    responses["analyst"],
                    responses["committee"],
                    responses["critic"],
                    distinct_valid_closes=closes,
                )
                self.assertEqual(
                    result["effective_classification"],
                    "abstain",
                )
                self.assertIn(expected_reason, result["reasons"])

    def test_all_non_abstain_decisions_require_resolved_official_evidence(
        self,
    ) -> None:
        for mutation, expected_reason in (
            (
                {"official_evidence_sufficient": False},
                "official_evidence_insufficient:TST",
            ),
            (
                {"contradictory_evidence": True},
                "contradictory_evidence_unresolved:TST",
            ),
        ):
            with self.subTest(mutation=mutation):
                packet, responses, closes = materialized("g01_stable_hold")
                responses["analyst"]["ticker_coverage"][0].update(mutation)
                result = adjudicate(
                    packet,
                    responses["analyst"],
                    responses["committee"],
                    responses["critic"],
                    distinct_valid_closes=closes,
                )
                self.assertEqual(result["effective_classification"], "abstain")
                self.assertFalse(result["validation_passed"])
                self.assertTrue(result["human_review_required"])
                self.assertIn(expected_reason, result["reasons"])

    def test_transition_with_unresolved_question_abstains(self) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        responses["analyst"]["unresolved_questions"] = [
            "A material long-term uncertainty is unresolved."
        ]
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertIn(
            "transition_has_unresolved_analyst_questions",
            result["reasons"],
        )

    def test_critic_can_downgrade_transition(self) -> None:
        result = evaluated("g09_critic_disagreement")
        self.assertEqual(result["actual"]["raw_classification"], "hold_existing")
        self.assertTrue(result["actual"]["human_review_required"])
        packet, responses, closes = materialized("g09_critic_disagreement")
        adjudication = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(
            adjudication["ticker_decisions"][0]["classification"],
            "hold_existing",
        )
        self.assertEqual(
            adjudication["headline"],
            "明确研究结论：继续持有研究状态",
        )
        self.assertLessEqual(adjudication["confidence_pct"], 50)

    def test_critic_cannot_upgrade(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        critic = copy.deepcopy(responses["critic"])
        critic["verdict"] = "revise"
        critic["downgrade_to"] = "exit_review"
        critic["ticker_reviews"][0]["verdict"] = "revise"
        critic["ticker_reviews"][0]["downgrade_to"] = "exit_review"
        with self.assertRaisesRegex(ContractError, "cannot upgrade"):
            validate_critic(packet, responses["committee"], critic)

    def test_critic_cannot_reverse_exit_into_entry_candidate(self) -> None:
        packet, responses, _ = materialized("g10_material_thesis_break")
        critic = copy.deepcopy(responses["critic"])
        critic["verdict"] = "revise"
        critic["downgrade_to"] = "real_trade_candidate"
        critic["ticker_reviews"][0]["verdict"] = "revise"
        critic["ticker_reviews"][0]["downgrade_to"] = (
            "real_trade_candidate"
        )
        with self.assertRaisesRegex(ContractError, "unsafe classification"):
            validate_critic(packet, responses["committee"], critic)

    def test_critic_downgrade_must_preserve_entity_role_lattice(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        critic = copy.deepcopy(responses["critic"])
        critic["verdict"] = "revise"
        critic["downgrade_to"] = "watchlist"
        critic["ticker_reviews"][0]["verdict"] = "revise"
        critic["ticker_reviews"][0]["downgrade_to"] = "watchlist"
        with self.assertRaisesRegex(
            ContractError,
            "invalid for entity role held",
        ):
            validate_critic(packet, responses["committee"], critic)

    def test_candidate_entity_cannot_be_trimmed_or_exited(self) -> None:
        for classification in ("trim_review", "exit_review"):
            with self.subTest(classification=classification):
                packet, responses, _ = materialized("g08_add_second_close")
                packet["entities"][0].update(
                    {
                        "role": "candidate",
                        "position_weight_band": "not_held",
                        "position_weight_pct_rounded": "0.0",
                    }
                )
                packet["gates"]["allowed_classifications_by_ticker"]["TST"] = [
                    "reject",
                    "watchlist",
                    "paper_trade_candidate",
                    "real_trade_candidate",
                    "abstain",
                ]
                packet = rehash(packet)
                responses["committee"]["packet_id"] = packet["packet_id"]
                committee = responses["committee"]
                committee["portfolio_classification"] = classification
                decision = committee["ticker_decisions"][0]
                decision["classification"] = classification
                decision["thesis_direction"] = "weakening"
                decision["human_review_needed"] = True
                with self.assertRaisesRegex(
                    ContractError,
                    "invalid for entity role candidate",
                ):
                    validate_committee(packet, committee)

    def test_material_break_on_held_ticker_does_not_block_other_candidate(
        self,
    ) -> None:
        packet, responses, _ = materialized("g10_material_thesis_break")
        second_entity = copy.deepcopy(packet["entities"][0])
        second_entity.update(
            {
                "ticker": "ALT",
                "role": "candidate",
                "position_weight_band": "not_held",
                "position_weight_pct_rounded": "0.0",
            }
        )
        packet["entities"].append(second_entity)
        packet["gates"]["allowed_classifications_by_ticker"]["ALT"] = [
            "reject",
            "watchlist",
            "paper_trade_candidate",
            "real_trade_candidate",
            "abstain",
        ]
        packet["gates"]["deterministic_transition_eligible_tickers"] = [
            "ALT"
        ]
        second_source = copy.deepcopy(packet["source_catalog"][0])
        second_source["source_id"] = "sec:ALT:10Q:2026Q1:0"
        second_source["ticker"] = "ALT"
        packet["source_catalog"].append(second_source)
        _add_synthetic_ticker_valuation(
            packet,
            ticker="ALT",
            source_id="sec:ALT:10Q:2026Q1:0",
        )
        packet = rehash(packet)
        responses["committee"]["packet_id"] = packet["packet_id"]
        second_decision = copy.deepcopy(
            responses["committee"]["ticker_decisions"][0]
        )
        second_decision.update(
            {
                "ticker": "ALT",
                "classification": "paper_trade_candidate",
                "thesis_direction": "strengthening",
                "source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["committee"]["ticker_decisions"].append(second_decision)
        validate_committee(packet, responses["committee"])

    def test_mixed_ticker_transitions_use_highest_risk_portfolio_label(
        self,
    ) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        second_entity = copy.deepcopy(packet["entities"][0])
        second_entity.update(
            {
                "ticker": "ALT",
                "role": "candidate",
                "position_weight_band": "not_held",
                "position_weight_pct_rounded": "0.0",
            }
        )
        packet["entities"].append(second_entity)
        packet["gates"]["allowed_classifications_by_ticker"]["ALT"] = [
            "reject",
            "watchlist",
            "paper_trade_candidate",
            "real_trade_candidate",
            "abstain",
        ]
        packet["gates"]["deterministic_transition_eligible_tickers"] = [
            "ALT"
        ]
        packet["gates"]["market_data_action_grade_tickers"].append("ALT")
        second_source = copy.deepcopy(packet["source_catalog"][0])
        second_source["source_id"] = "sec:ALT:10Q:2026Q1:0"
        second_source["ticker"] = "ALT"
        packet["source_catalog"].append(second_source)
        _add_synthetic_ticker_valuation(
            packet,
            ticker="ALT",
            source_id="sec:ALT:10Q:2026Q1:0",
        )
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        second_claim = copy.deepcopy(responses["analyst"]["claims"][0])
        second_claim["claim_id"] = "claim:ALT:primary"
        second_claim["ticker"] = "ALT"
        second_claim["source_ids"] = ["sec:ALT:10Q:2026Q1:0"]
        responses["analyst"]["claims"].append(second_claim)
        responses["analyst"]["ticker_coverage"].append(
            {
                "ticker": "ALT",
                "official_evidence_sufficient": True,
                "contradictory_evidence": False,
                "missing_evidence": [],
            }
        )
        first_decision = responses["committee"]["ticker_decisions"][0]
        first_decision["classification"] = "exit_review"
        first_decision["thesis_direction"] = "weakening"
        second_decision = copy.deepcopy(first_decision)
        second_decision.update(
            {
                "ticker": "ALT",
                "classification": "real_trade_candidate",
                "thesis_direction": "strengthening",
                "claim_ids": ["claim:ALT:primary"],
                "source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["committee"]["ticker_decisions"].append(second_decision)
        responses["committee"]["portfolio_classification"] = "exit_review"
        first_review = responses["critic"]["ticker_reviews"][0]
        first_review["downgrade_to"] = "exit_review"
        second_review = copy.deepcopy(first_review)
        second_review.update(
            {
                "ticker": "ALT",
                "downgrade_to": "real_trade_candidate",
                "approved_source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["critic"]["ticker_reviews"].append(second_review)
        responses["critic"]["downgrade_to"] = "exit_review"
        responses["critic"]["approved_source_ids"] = sorted(
            [
                "sec:TST:10Q:2026Q1:0",
                "sec:ALT:10Q:2026Q1:0",
            ]
        )
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "exit_review")
        self.assertEqual(
            {
                row["classification"] for row in result["ticker_decisions"]
            },
            {"exit_review", "real_trade_candidate"},
        )
        self.assertIn("多项行动复核", result["headline"])

    def test_broken_held_exit_survives_blocked_candidate_transition(
        self,
    ) -> None:
        packet, responses, _ = materialized("g10_material_thesis_break")
        second_entity = copy.deepcopy(packet["entities"][0])
        second_entity.update(
            {
                "ticker": "ALT",
                "role": "candidate",
                "position_weight_band": "not_held",
                "position_weight_pct_rounded": "0.0",
            }
        )
        packet["entities"].append(second_entity)
        packet["gates"]["allowed_classifications_by_ticker"]["ALT"] = [
            "reject",
            "watchlist",
            "paper_trade_candidate",
            "real_trade_candidate",
            "abstain",
        ]
        second_source = copy.deepcopy(packet["source_catalog"][0])
        second_source["source_id"] = "sec:ALT:10Q:2026Q1:0"
        second_source["ticker"] = "ALT"
        packet["source_catalog"].append(second_source)
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]

        second_claim = copy.deepcopy(responses["analyst"]["claims"][0])
        second_claim.update(
            {
                "claim_id": "claim:ALT:primary",
                "ticker": "ALT",
                "claim": "Primary evidence supports continued candidate research.",
                "stance": "supports",
                "source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["analyst"]["claims"].append(second_claim)
        responses["analyst"]["ticker_coverage"].append(
            {
                "ticker": "ALT",
                "official_evidence_sufficient": True,
                "contradictory_evidence": False,
                "missing_evidence": [],
            }
        )

        first_decision = responses["committee"]["ticker_decisions"][0]
        second_decision = copy.deepcopy(first_decision)
        second_decision.update(
            {
                "ticker": "ALT",
                "classification": "paper_trade_candidate",
                "thesis_direction": "strengthening",
                "claim_ids": ["claim:ALT:primary"],
                "source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["committee"]["ticker_decisions"].append(second_decision)

        first_review = responses["critic"]["ticker_reviews"][0]
        second_review = copy.deepcopy(first_review)
        second_review.update(
            {
                "ticker": "ALT",
                "downgrade_to": "paper_trade_candidate",
                "approved_source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["critic"]["ticker_reviews"].append(second_review)
        responses["critic"]["approved_source_ids"] = sorted(
            [
                "sec:TST:10Q:2026Q1:0",
                "sec:ALT:10Q:2026Q1:0",
            ]
        )

        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=2,
        )
        decisions = {
            row["ticker"]: row for row in result["ticker_decisions"]
        }
        self.assertEqual(result["effective_classification"], "exit_review")
        self.assertEqual(decisions["TST"]["classification"], "exit_review")
        self.assertEqual(
            decisions["ALT"]["research_classification"],
            "paper_trade_candidate",
        )
        self.assertEqual(decisions["ALT"]["classification"], "watchlist")
        self.assertEqual(
            decisions["ALT"]["action_review_status"],
            "blocked",
        )
        self.assertNotIn(
            "transition_gate_failed:market_data_action_grade_ticker:TST",
            decisions["TST"]["reasons"],
        )
        self.assertIn(
            "transition_gate_failed:market_data_action_grade_ticker:ALT",
            decisions["ALT"]["reasons"],
        )

    def test_missing_required_critic_returns_safe_abstain(self) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            None,
            distinct_valid_closes=closes,
        )
        self.assertTrue(result["critic_required"])
        self.assertEqual(result["effective_classification"], "abstain")

    def test_core_prompt_injection_always_sets_effective_abstain(self) -> None:
        packet, responses, closes = materialized("g01_stable_hold")
        responses["analyst"]["prompt_injection_detected"] = True
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")
        self.assertTrue(
            all(
                row["classification"] == "abstain"
                for row in result["ticker_decisions"]
            )
        )

    def test_core_numeric_failure_always_sets_effective_abstain(self) -> None:
        packet, responses, closes = materialized("g05_numeric_mismatch")
        result = adjudicate(
            packet,
            responses["analyst"],
            responses["committee"],
            responses["critic"],
            distinct_valid_closes=closes,
        )
        self.assertEqual(result["effective_classification"], "abstain")

    def test_live_stability_comes_from_hashed_canonical_packet_only(self) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        packet["gates"].update(
            {
                "deterministic_action_stability_distinct_closes": 2,
                "deterministic_transition_pending_tickers": [],
                "deterministic_transition_eligible_tickers": ["TST"],
                "verified_close_session": packet["cycle_date"],
            }
        )
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=0,
        )
        result = apply_verified_close_stability(packet, bundle)
        self.assertEqual(
            result["adjudication"]["effective_classification"],
            "paper_trade_candidate",
        )
        self.assertEqual(
            result["stability"]["source"],
            "hashed_canonical_daily_decision_packet",
        )
        packet["gates"]["deterministic_transition_eligible_tickers"] = []
        packet["gates"]["deterministic_transition_pending_tickers"] = ["TST"]
        packet["gates"]["deterministic_action_stability_distinct_closes"] = 1
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]
        bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=0,
        )
        result = apply_verified_close_stability(packet, bundle)
        self.assertEqual(
            result["adjudication"]["effective_classification"],
            "hold_existing",
        )

    def test_live_close_stability_isolated_per_candidate_ticker(self) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        second_entity = copy.deepcopy(packet["entities"][0])
        second_entity.update(
            {
                "ticker": "ALT",
                "role": "candidate",
                "position_weight_band": "not_held",
                "position_weight_pct_rounded": "0.0",
            }
        )
        packet["entities"].append(second_entity)
        packet["gates"]["allowed_classifications_by_ticker"]["ALT"] = [
            "reject",
            "watchlist",
            "paper_trade_candidate",
            "real_trade_candidate",
            "abstain",
        ]
        second_source = copy.deepcopy(packet["source_catalog"][0])
        second_source.update(
            {
                "source_id": "sec:ALT:10Q:2026Q1:0",
                "ticker": "ALT",
            }
        )
        packet["source_catalog"].append(second_source)
        _add_synthetic_ticker_valuation(
            packet,
            ticker="ALT",
            source_id="sec:ALT:10Q:2026Q1:0",
        )
        packet["gates"]["market_data_action_grade_tickers"].append("ALT")
        packet["gates"]["market_data_action_grade_tickers"].sort()
        packet["gates"].update(
            {
                "deterministic_action_stability_distinct_closes": 2,
                "deterministic_transition_pending_tickers": ["ALT"],
                "deterministic_transition_eligible_tickers": ["TST"],
                "verified_close_session": packet["cycle_date"],
            }
        )
        packet = rehash(packet)
        for response in responses.values():
            response["packet_id"] = packet["packet_id"]

        second_claim = copy.deepcopy(responses["analyst"]["claims"][0])
        second_claim.update(
            {
                "claim_id": "claim:ALT:primary",
                "ticker": "ALT",
                "source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["analyst"]["claims"].append(second_claim)
        responses["analyst"]["ticker_coverage"].append(
            {
                "ticker": "ALT",
                "official_evidence_sufficient": True,
                "contradictory_evidence": False,
                "missing_evidence": [],
            }
        )

        second_decision = copy.deepcopy(
            responses["committee"]["ticker_decisions"][0]
        )
        second_decision.update(
            {
                "ticker": "ALT",
                "claim_ids": ["claim:ALT:primary"],
                "source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["committee"]["ticker_decisions"].append(second_decision)

        second_review = copy.deepcopy(
            responses["critic"]["ticker_reviews"][0]
        )
        second_review.update(
            {
                "ticker": "ALT",
                "approved_source_ids": ["sec:ALT:10Q:2026Q1:0"],
            }
        )
        responses["critic"]["ticker_reviews"].append(second_review)
        responses["critic"]["approved_source_ids"] = sorted(
            [
                "sec:TST:10Q:2026Q1:0",
                "sec:ALT:10Q:2026Q1:0",
            ]
        )

        bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=0,
        )
        result = apply_verified_close_stability(packet, bundle)
        decisions = {
            row["ticker"]: row["classification"]
            for row in result["adjudication"]["ticker_decisions"]
        }
        self.assertEqual(decisions["TST"], "paper_trade_candidate")
        self.assertEqual(decisions["ALT"], "watchlist")
        self.assertEqual(
            result["stability"]["distinct_valid_closes_by_ticker"],
            {"ALT": 1, "TST": 2},
        )


if __name__ == "__main__":
    unittest.main()
