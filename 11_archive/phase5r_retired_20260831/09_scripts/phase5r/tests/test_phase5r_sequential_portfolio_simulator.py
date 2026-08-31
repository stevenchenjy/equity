from __future__ import annotations

import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_daily_common import canonical_sha256
from phase5r_point_in_time_performance import (
    rolling_monthly_performance_receipt,
)
from phase5r_sequential_portfolio_simulator import (
    SequentialSimulationError,
    build_decision_snapshot,
    build_market_period_receipt,
    build_sequential_simulation_policy,
    simulate_sequential_portfolio,
)


def _bounds(period_id: str) -> tuple[str, str]:
    last_day = {
        "01": "31",
        "02": "28",
        "03": "31",
    }[period_id[-2:]]
    return (
        f"{period_id}-01T00:00:00Z",
        f"{period_id}-{last_day}T23:59:59Z",
    )


def _external_evidence(label: str, available_at: str) -> dict[str, str]:
    return {
        "evidence_id": f"evidence:{label}",
        "available_at_utc": available_at,
        "content_sha256": canonical_sha256({"evidence": label}),
    }


def _decision(
    *,
    period_id: str,
    decided_at: str,
    action: str,
    target_weights: dict[str, str] | None = None,
    evidence_receipts: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    start, end = _bounds(period_id)
    return build_decision_snapshot(
        decision_id=f"decision:{period_id}",
        decided_at_utc=decided_at,
        period_id=period_id,
        period_start_utc=start,
        period_end_utc=end,
        action=action,
        action_reason=f"synthetic-{action}-test",
        target_weights=target_weights or {},
        evidence_receipts=evidence_receipts
        or [_external_evidence(period_id, decided_at)],
        source_ids=[f"decision-source:{period_id}"],
    )


def _market(
    *,
    ticker: str,
    period_id: str,
    start_price: str,
    end_price: str,
    terminal_event: bool = False,
    terminal_reason: str = "none",
    recovery: str = "0",
) -> dict[str, object]:
    start, end = _bounds(period_id)
    return build_market_period_receipt(
        receipt_id=f"market:{ticker}:{period_id}",
        ticker=ticker,
        period_id=period_id,
        period_start_utc=start,
        period_end_utc=end,
        available_at_utc=end,
        start_price=start_price,
        end_price=end_price,
        terminal_event=terminal_event,
        terminal_reason=terminal_reason,
        terminal_cash_recovery_per_unit=recovery,
        source_ids=[f"price-source:{ticker}:{period_id}"],
    )


def _policy(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "policy_id": "synthetic-policy",
        "fixed_cost_per_changed_asset": "0",
        "spread_bps": "0",
        "slippage_bps": "0",
        "max_position_weight": "0.70",
        "max_gross_exposure": "0.80",
        "min_cash_weight": "0.20",
        "max_one_way_turnover": "0.80",
        "max_positions": 4,
        "modeled_cash_return_pct": "0",
    }
    values.update(overrides)
    return build_sequential_simulation_policy(**values)


def _simulate(
    *,
    policy: dict[str, object],
    decisions: list[dict[str, object]],
    receipts: list[dict[str, object]],
    initial_cash: str = "1000",
) -> dict[str, object]:
    return simulate_sequential_portfolio(
        simulation_id="synthetic-sequential-test",
        evaluation_as_of_utc="2026-04-01T00:00:00Z",
        initial_cash=initial_cash,
        policy=policy,
        decision_snapshots=decisions,
        market_receipts=receipts,
    )


class SequentialPortfolioSimulatorTests(unittest.TestCase):
    def test_sequential_costed_returns_emit_compatible_monthly_ledger(
        self,
    ) -> None:
        policy = _policy(
            fixed_cost_per_changed_asset="1",
            spread_bps="10",
            slippage_bps="10",
        )
        decisions = [
            _decision(
                period_id="2026-01",
                decided_at="2025-12-31T12:00:00Z",
                action="rebalance",
                target_weights={"AAA": "0.50", "CASH": "0.50"},
            ),
            _decision(
                period_id="2026-02",
                decided_at="2026-01-31T12:00:00Z",
                action="hold",
            ),
        ]
        receipt = _simulate(
            policy=policy,
            decisions=decisions,
            receipts=[
                _market(
                    ticker="AAA",
                    period_id="2026-01",
                    start_price="100",
                    end_price="110",
                ),
                _market(
                    ticker="AAA",
                    period_id="2026-02",
                    start_price="110",
                    end_price="99",
                ),
            ],
        )
        january, february = receipt["periods"]
        self.assertEqual(january["absolute_paper_allocation_change"], "500.00000000")
        self.assertEqual(january["one_way_turnover"], "0.5000000000")
        self.assertEqual(january["modeled_cost"], "2.00000000")
        self.assertEqual(january["net_return_pct"], "4.800000")
        self.assertEqual(february["changed_assets"], [])
        self.assertEqual(february["modeled_cost"], "0.00000000")
        self.assertEqual(february["net_return_pct"], "-5.248092")
        self.assertEqual(
            february["action_semantics"],
            "affirmatively_preserve_opening_allocations_with_zero_change",
        )

        performance = rolling_monthly_performance_receipt(
            ledger_id="simulator-ledger",
            policy_id=policy["policy_id"],
            policy_sha256=policy["policy_sha256"],
            evaluation_as_of_utc="2026-04-01T00:00:00Z",
            monthly_rows=receipt["monthly_ledger_rows"],
        )
        self.assertEqual(performance["ledger_row_count"], 2)
        self.assertEqual(
            performance["ledger_sha256"],
            receipt["monthly_ledger_sha256"],
        )
        unsigned = dict(receipt)
        claimed_hash = unsigned.pop("receipt_sha256")
        self.assertEqual(claimed_hash, canonical_sha256(unsigned))
        self.assertTrue(receipt["simulation_only"])
        self.assertFalse(receipt["broker_or_execution_capability"])
        self.assertFalse(receipt["network_or_model_access"])

    def test_decision_builder_blocks_effective_period_and_evidence_lookahead(
        self,
    ) -> None:
        start, end = _bounds("2026-01")
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "strictly before",
        ):
            build_decision_snapshot(
                decision_id="late",
                decided_at_utc=start,
                period_id="2026-01",
                period_start_utc=start,
                period_end_utc=end,
                action="abstain",
                action_reason="late",
                target_weights={},
                evidence_receipts=[
                    _external_evidence("late", "2025-12-31T00:00:00Z")
                ],
                source_ids=["decision-source:late"],
            )
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "evidence was not available",
        ):
            build_decision_snapshot(
                decision_id="lookahead",
                decided_at_utc="2025-12-31T12:00:00Z",
                period_id="2026-01",
                period_start_utc=start,
                period_end_utc=end,
                action="abstain",
                action_reason="lookahead",
                target_weights={},
                evidence_receipts=[
                    _external_evidence(
                        "future",
                        "2025-12-31T13:00:00Z",
                    )
                ],
                source_ids=["decision-source:lookahead"],
            )

    def test_market_receipt_cross_binding_blocks_forged_early_availability(
        self,
    ) -> None:
        january_market = _market(
            ticker="AAA",
            period_id="2026-01",
            start_price="100",
            end_price="110",
        )
        decisions = [
            _decision(
                period_id="2026-01",
                decided_at="2025-12-31T12:00:00Z",
                action="rebalance",
                target_weights={"AAA": "0.50", "CASH": "0.50"},
            ),
            _decision(
                period_id="2026-02",
                decided_at="2026-01-31T12:00:00Z",
                action="hold",
                evidence_receipts=[
                    {
                        "evidence_id": january_market["receipt_id"],
                        "available_at_utc": "2026-01-31T11:00:00Z",
                        "content_sha256": january_market["receipt_sha256"],
                    }
                ],
            ),
        ]
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "availability mismatch",
        ):
            _simulate(
                policy=_policy(),
                decisions=decisions,
                receipts=[
                    january_market,
                    _market(
                        ticker="AAA",
                        period_id="2026-02",
                        start_price="110",
                        end_price="110",
                    ),
                ],
            )

    def test_policy_decision_and_market_hash_tampering_is_rejected(self) -> None:
        policy = _policy()
        decision = _decision(
            period_id="2026-01",
            decided_at="2025-12-31T12:00:00Z",
            action="rebalance",
            target_weights={"AAA": "0.50", "CASH": "0.50"},
        )
        market = _market(
            ticker="AAA",
            period_id="2026-01",
            start_price="100",
            end_price="100",
        )
        cases: list[tuple[str, dict[str, object], list[dict[str, object]], list[dict[str, object]]]] = []

        bad_policy = copy.deepcopy(policy)
        bad_policy["spread_bps"] = "1"
        cases.append(("policy", bad_policy, [decision], [market]))

        bad_decision = copy.deepcopy(decision)
        bad_decision["action_reason"] = "tampered"
        cases.append(("decision", policy, [bad_decision], [market]))

        bad_market = copy.deepcopy(market)
        bad_market["end_price"] = "120"
        cases.append(("market", policy, [decision], [bad_market]))

        for label, candidate_policy, decisions, receipts in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    SequentialSimulationError,
                    "hash or canonical payload mismatch",
                ):
                    _simulate(
                        policy=candidate_policy,
                        decisions=decisions,
                        receipts=receipts,
                    )

    def test_target_position_turnover_and_post_cost_cash_limits_are_hard(
        self,
    ) -> None:
        too_concentrated = _decision(
            period_id="2026-01",
            decided_at="2025-12-31T12:00:00Z",
            action="rebalance",
            target_weights={"AAA": "0.80", "CASH": "0.20"},
        )
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "max_position_weight",
        ):
            _simulate(
                policy=_policy(),
                decisions=[too_concentrated],
                receipts=[],
            )

        with self.assertRaisesRegex(
            SequentialSimulationError,
            "max_one_way_turnover",
        ):
            _simulate(
                policy=_policy(max_one_way_turnover="0.40"),
                decisions=[
                    _decision(
                        period_id="2026-01",
                        decided_at="2025-12-31T12:00:00Z",
                        action="rebalance",
                        target_weights={"AAA": "0.50", "CASH": "0.50"},
                    )
                ],
                receipts=[],
            )

        with self.assertRaisesRegex(
            SequentialSimulationError,
            "max_gross_exposure",
        ):
            _simulate(
                policy=_policy(
                    max_position_weight="0.50",
                    max_gross_exposure="0.70",
                ),
                decisions=[
                    _decision(
                        period_id="2026-01",
                        decided_at="2025-12-31T12:00:00Z",
                        action="rebalance",
                        target_weights={
                            "AAA": "0.40",
                            "BBB": "0.40",
                            "CASH": "0.20",
                        },
                    )
                ],
                receipts=[],
            )

        with self.assertRaisesRegex(
            SequentialSimulationError,
            "post-cost allocation violates policy",
        ):
            _simulate(
                policy=_policy(
                    fixed_cost_per_changed_asset="10",
                    max_position_weight="0.80",
                ),
                decisions=[too_concentrated],
                receipts=[],
            )

    def test_hold_and_abstain_are_distinct_zero_change_states(self) -> None:
        decisions = [
            _decision(
                period_id="2026-01",
                decided_at="2025-12-31T12:00:00Z",
                action="rebalance",
                target_weights={"AAA": "0.50", "CASH": "0.50"},
            ),
            _decision(
                period_id="2026-02",
                decided_at="2026-01-31T12:00:00Z",
                action="hold",
            ),
            _decision(
                period_id="2026-03",
                decided_at="2026-02-28T12:00:00Z",
                action="abstain",
            ),
        ]
        receipt = _simulate(
            policy=_policy(),
            decisions=decisions,
            receipts=[
                _market(
                    ticker="AAA",
                    period_id=period_id,
                    start_price="100",
                    end_price="100",
                )
                for period_id in ("2026-01", "2026-02", "2026-03")
            ],
        )
        hold = receipt["periods"][1]
        abstain = receipt["periods"][2]
        self.assertEqual(hold["changed_assets"], [])
        self.assertEqual(abstain["changed_assets"], [])
        self.assertEqual(hold["one_way_turnover"], "0.0000000000")
        self.assertEqual(abstain["one_way_turnover"], "0.0000000000")
        self.assertNotEqual(
            hold["action_semantics"],
            abstain["action_semantics"],
        )

    def test_turnover_uses_half_l1_while_cost_uses_both_allocation_legs(
        self,
    ) -> None:
        receipt = _simulate(
            policy=_policy(),
            decisions=[
                _decision(
                    period_id="2026-01",
                    decided_at="2025-12-31T12:00:00Z",
                    action="rebalance",
                    target_weights={"AAA": "0.50", "CASH": "0.50"},
                ),
                _decision(
                    period_id="2026-02",
                    decided_at="2026-01-31T12:00:00Z",
                    action="rebalance",
                    target_weights={"BBB": "0.50", "CASH": "0.50"},
                ),
            ],
            receipts=[
                _market(
                    ticker="AAA",
                    period_id="2026-01",
                    start_price="100",
                    end_price="100",
                ),
                _market(
                    ticker="BBB",
                    period_id="2026-02",
                    start_price="50",
                    end_price="50",
                ),
            ],
        )
        rotation = receipt["periods"][1]
        self.assertEqual(rotation["one_way_turnover"], "0.5000000000")
        self.assertEqual(
            rotation["absolute_paper_allocation_change"],
            "1000.00000000",
        )
        self.assertEqual(rotation["changed_assets"], ["AAA", "BBB"])

    def test_missing_market_receipt_for_held_asset_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "missing market receipt",
        ):
            _simulate(
                policy=_policy(),
                decisions=[
                    _decision(
                        period_id="2026-01",
                        decided_at="2025-12-31T12:00:00Z",
                        action="rebalance",
                        target_weights={"AAA": "0.50", "CASH": "0.50"},
                    )
                ],
                receipts=[],
            )

    def test_terminal_zero_recovery_retains_exact_total_loss(self) -> None:
        policy = _policy(
            max_position_weight="1",
            max_gross_exposure="1",
            min_cash_weight="0",
            max_one_way_turnover="1",
        )
        receipt = _simulate(
            policy=policy,
            decisions=[
                _decision(
                    period_id="2026-01",
                    decided_at="2025-12-31T12:00:00Z",
                    action="rebalance",
                    target_weights={"CASH": "0", "TST": "1"},
                )
            ],
            receipts=[
                _market(
                    ticker="TST",
                    period_id="2026-01",
                    start_price="10",
                    end_price="0",
                    terminal_event=True,
                    terminal_reason="bankruptcy",
                    recovery="0",
                )
            ],
        )
        period = receipt["periods"][0]
        self.assertEqual(period["net_return_pct"], "-100.000000")
        self.assertTrue(period["terminal_events"][0]["terminal_total_loss"])
        self.assertEqual(
            receipt["monthly_ledger_rows"][0]["net_return_pct"],
            "-100.000000",
        )
        self.assertEqual(receipt["final_state"]["total_paper_nav"], "0.00000000")
        self.assertEqual(receipt["terminal_tickers"], ["TST"])

    def test_terminal_ticker_cannot_reenter_a_later_period(self) -> None:
        decisions = [
            _decision(
                period_id="2026-01",
                decided_at="2025-12-31T12:00:00Z",
                action="rebalance",
                target_weights={"CASH": "0.50", "TST": "0.50"},
            ),
            _decision(
                period_id="2026-02",
                decided_at="2026-01-31T12:00:00Z",
                action="rebalance",
                target_weights={"CASH": "0.50", "TST": "0.50"},
            ),
        ]
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "terminal ticker cannot re-enter",
        ):
            _simulate(
                policy=_policy(),
                decisions=decisions,
                receipts=[
                    _market(
                        ticker="TST",
                        period_id="2026-01",
                        start_price="10",
                        end_price="0",
                        terminal_event=True,
                        terminal_reason="delisting",
                        recovery="0",
                    )
                ],
            )

    def test_market_drift_breach_cannot_be_silently_held(self) -> None:
        decisions = [
            _decision(
                period_id="2026-01",
                decided_at="2025-12-31T12:00:00Z",
                action="rebalance",
                target_weights={"AAA": "0.50", "CASH": "0.50"},
            ),
            _decision(
                period_id="2026-02",
                decided_at="2026-01-31T12:00:00Z",
                action="hold",
            ),
        ]
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "cannot silently carry",
        ):
            _simulate(
                policy=_policy(max_position_weight="0.60"),
                decisions=decisions,
                receipts=[
                    _market(
                        ticker="AAA",
                        period_id="2026-01",
                        start_price="100",
                        end_price="200",
                    )
                ],
            )

    def test_terminal_receipt_requires_explicit_zero_end_price(self) -> None:
        with self.assertRaisesRegex(
            SequentialSimulationError,
            "zero end_price",
        ):
            _market(
                ticker="TST",
                period_id="2026-01",
                start_price="10",
                end_price="1",
                terminal_event=True,
                terminal_reason="liquidation",
                recovery="1",
            )


if __name__ == "__main__":
    unittest.main()
