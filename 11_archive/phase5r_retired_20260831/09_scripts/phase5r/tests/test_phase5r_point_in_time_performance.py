from __future__ import annotations

import calendar
import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_point_in_time_performance import (
    PerformanceEvidenceError,
    block_bootstrap_twr_ci,
    build_monthly_performance_ledger_row,
    cash_dividend_receipt,
    cash_drag_receipt,
    compare_required_baselines,
    delisting_recovery_receipt,
    evaluate_time_weighted_periods,
    maximum_drawdown_pct,
    modeled_transaction_cost_receipt,
    rolling_monthly_performance_receipt,
    select_next_session_paper_fill,
    split_adjustment_receipt,
    turnover_receipt,
)


def _monthly_rows(
    returns: list[str],
    *,
    start_year: int = 2021,
    start_month: int = 1,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for offset, period_return in enumerate(returns):
        absolute_month = start_year * 12 + start_month - 1 + offset
        year, zero_based_month = divmod(absolute_month, 12)
        month = zero_based_month + 1
        last_day = calendar.monthrange(year, month)[1]
        period_id = f"{year:04d}-{month:02d}"
        rows.append(
            build_monthly_performance_ledger_row(
                period_id=period_id,
                start_utc=f"{period_id}-01T00:00:00Z",
                end_utc=(
                    f"{period_id}-{last_day:02d}T23:59:59Z"
                ),
                net_return_pct=period_return,
                source_ids=[f"paper-ledger:{period_id}"],
            )
        )
    return rows


class PointInTimePerformanceTests(unittest.TestCase):
    def test_paper_fill_uses_first_session_strictly_after_decision(self) -> None:
        receipt = select_next_session_paper_fill(
            decision_id="decision-001",
            ticker="tst",
            decided_at_utc="2026-07-24T20:30:00Z",
            sessions=[
                {
                    "session_date": "2026-07-24",
                    "open_utc": "2026-07-24T13:30:00Z",
                    "open_price": "10",
                    "currency": "USD",
                    "source_ids": ["market:TST:2026-07-24"],
                },
                {
                    "session_date": "2026-07-27",
                    "open_utc": "2026-07-27T13:30:00Z",
                    "open_price": "10.50",
                    "currency": "USD",
                    "source_ids": ["market:TST:2026-07-27"],
                },
                {
                    "session_date": "2026-07-28",
                    "open_utc": "2026-07-28T13:30:00Z",
                    "open_price": "11",
                    "currency": "USD",
                    "source_ids": ["market:TST:2026-07-28"],
                },
            ],
        )
        self.assertEqual(
            receipt["selected_session"]["session_date"],
            "2026-07-27",
        )
        self.assertEqual(receipt["selected_session"]["open_price"], "10.5000")
        self.assertTrue(receipt["simulation_only"])
        self.assertFalse(receipt["broker_or_execution_capability"])

    def test_paper_fill_fails_when_no_future_session_is_supplied(self) -> None:
        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "no supplied market-session",
        ):
            select_next_session_paper_fill(
                decision_id="decision-001",
                ticker="TST",
                decided_at_utc="2026-07-24T20:30:00Z",
                sessions=[
                    {
                        "session_date": "2026-07-24",
                        "open_utc": "2026-07-24T13:30:00Z",
                        "open_price": "10",
                        "currency": "USD",
                        "source_ids": ["market:TST:2026-07-24"],
                    }
                ],
            )

    def test_modeled_cost_is_explicit_and_decimal_safe(self) -> None:
        receipt = modeled_transaction_cost_receipt(
            absolute_paper_notional="1000",
            fixed_fee="1",
            spread_bps="10",
            slippage_bps="5",
        )
        self.assertEqual(receipt["variable_cost"], "1.50")
        self.assertEqual(receipt["total_modeled_cost"], "2.50")
        with self.assertRaisesRegex(PerformanceEvidenceError, "decimal string"):
            modeled_transaction_cost_receipt(absolute_paper_notional=1000.0)

    def test_twr_neutralizes_after_close_flow_and_deducts_cost(self) -> None:
        receipt = evaluate_time_weighted_periods(
            [
                {
                    "period_id": "p1",
                    "start_utc": "2026-01-01T00:00:00Z",
                    "end_utc": "2026-01-31T23:59:59Z",
                    "opening_nav": "1000",
                    "gross_closing_nav": "1100",
                    "modeled_cost": "10",
                    "external_flow_after_close": "500",
                    "source_ids": ["ledger:p1"],
                },
                {
                    "period_id": "p2",
                    "start_utc": "2026-02-01T00:00:00Z",
                    "end_utc": "2026-02-28T23:59:59Z",
                    "opening_nav": "1590",
                    "gross_closing_nav": "1749",
                    "modeled_cost": "0",
                    "external_flow_after_close": "0",
                    "source_ids": ["ledger:p2"],
                },
            ]
        )
        self.assertEqual(receipt["periods"][0]["net_return_pct"], "9.0000")
        self.assertEqual(receipt["periods"][1]["net_return_pct"], "10.0000")
        self.assertEqual(receipt["net_twr_pct"], "19.9000")
        self.assertEqual(receipt["gross_twr_pct"], "21.0000")
        self.assertEqual(receipt["total_modeled_cost"], "10.00")
        self.assertEqual(receipt["total_external_flow"], "500.00")
        self.assertFalse(receipt["future_performance_claim"])

    def test_twr_rejects_unreconciled_flow_boundary(self) -> None:
        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "does not reconcile",
        ):
            evaluate_time_weighted_periods(
                [
                    {
                        "period_id": "p1",
                        "start_utc": "2026-01-01T00:00:00Z",
                        "end_utc": "2026-01-31T23:59:59Z",
                        "opening_nav": "1000",
                        "gross_closing_nav": "1100",
                        "modeled_cost": "10",
                        "external_flow_after_close": "500",
                        "source_ids": ["ledger:p1"],
                    },
                    {
                        "period_id": "p2",
                        "start_utc": "2026-02-01T00:00:00Z",
                        "end_utc": "2026-02-28T23:59:59Z",
                        "opening_nav": "1600",
                        "gross_closing_nav": "1700",
                        "modeled_cost": "0",
                        "external_flow_after_close": "0",
                        "source_ids": ["ledger:p2"],
                    },
                ]
            )

    def test_cash_drag_is_reported_against_fully_invested_counterfactual(self) -> None:
        receipt = cash_drag_receipt(
            [
                {
                    "period_id": "p1",
                    "cash_weight": "0.50",
                    "invested_sleeve_return_pct": "10",
                    "cash_return_pct": "0",
                }
            ]
        )
        self.assertEqual(receipt["portfolio_twr_with_cash_pct"], "5.0000")
        self.assertEqual(
            receipt["fully_invested_counterfactual_twr_pct"],
            "10.0000",
        )
        self.assertEqual(receipt["cash_drag_pct"], "5.0000")

    def test_corporate_action_receipts_require_explicit_inputs(self) -> None:
        split = split_adjustment_receipt(
            shares_before="10",
            reference_price_before="100",
            split_numerator="2",
            split_denominator="1",
            effective_at_utc="2026-03-01T00:00:00Z",
            source_ids=["issuer:TST:split"],
        )
        self.assertEqual(split["shares_after"], "20.00000000")
        self.assertEqual(split["reference_price_after"], "50.0000")
        self.assertEqual(split["market_value_before"], split["market_value_after"])

        dividend = cash_dividend_receipt(
            shares_eligible="20",
            dividend_per_share="1.50",
            announced_at_utc="2026-03-01T00:00:00Z",
            ex_date_utc="2026-03-15T00:00:00Z",
            pay_date_utc="2026-03-30T00:00:00Z",
            source_ids=["issuer:TST:dividend"],
        )
        self.assertEqual(dividend["cash_amount"], "30.00")

        delisting = delisting_recovery_receipt(
            shares="20",
            recovery_per_share="2",
            effective_at_utc="2026-04-01T00:00:00Z",
            recovery_available_at_utc="2026-04-10T00:00:00Z",
            evaluation_as_of_utc="2026-04-30T00:00:00Z",
            source_ids=["exchange:TST:delisting"],
        )
        self.assertEqual(delisting["terminal_value"], "40.00")
        self.assertTrue(delisting["recovery_was_explicit_input"])

    def test_future_delisting_outcome_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "not available by evaluation as-of",
        ):
            delisting_recovery_receipt(
                shares="20",
                recovery_per_share="2",
                effective_at_utc="2026-04-01T00:00:00Z",
                recovery_available_at_utc="2026-05-10T00:00:00Z",
                evaluation_as_of_utc="2026-04-30T00:00:00Z",
                source_ids=["exchange:TST:delisting"],
            )

    def test_drawdown_and_one_way_turnover(self) -> None:
        self.assertEqual(maximum_drawdown_pct(["10", "-20", "5"]), "20.0000")
        turnover = turnover_receipt(
            [
                {
                    "as_of": "2026-01-01",
                    "weights": {"TST": "0.50", "CASH": "0.50"},
                },
                {
                    "as_of": "2026-02-01",
                    "weights": {"TST": "0.60", "NEW": "0.20", "CASH": "0.20"},
                },
            ]
        )
        self.assertEqual(turnover["total_turnover_pct"], "30.0000")
        self.assertEqual(
            turnover["transitions"][0]["one_way_turnover_pct"],
            "30.0000",
        )

    def test_terminal_total_loss_is_retained_without_survivorship_bias(
        self,
    ) -> None:
        performance = evaluate_time_weighted_periods(
            [
                {
                    "period_id": "bankruptcy",
                    "start_utc": "2026-01-01T00:00:00Z",
                    "end_utc": "2026-01-31T23:59:59Z",
                    "opening_nav": "1000",
                    "gross_closing_nav": "0",
                    "modeled_cost": "0",
                    "external_flow_after_close": "0",
                    "source_ids": ["issuer:TST:zero-recovery"],
                }
            ]
        )
        self.assertEqual(performance["net_twr_pct"], "-100.0000")
        self.assertEqual(performance["maximum_drawdown_pct"], "100.0000")
        self.assertEqual(maximum_drawdown_pct(["-100"]), "100.0000")
        bootstrap = block_bootstrap_twr_ci(
            ["-100", "5"],
            iterations=100,
            block_size=1,
            seed=17,
        )
        self.assertEqual(bootstrap["point_estimate_twr_pct"], "-100.0000")

        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "below -100%",
        ):
            maximum_drawdown_pct(["-100.01"])

    def test_required_baselines_are_complete_and_date_aligned(self) -> None:
        strategy = [
            {"period_id": "p1", "return_pct": "10"},
            {"period_id": "p2", "return_pct": "-5"},
        ]
        baselines = {
            "SPY": [
                {"period_id": "p1", "return_pct": "5"},
                {"period_id": "p2", "return_pct": "-2"},
            ],
            "QQQ": [
                {"period_id": "p1", "return_pct": "8"},
                {"period_id": "p2", "return_pct": "-4"},
            ],
            "XLK": [
                {"period_id": "p1", "return_pct": "7"},
                {"period_id": "p2", "return_pct": "-3"},
            ],
            "C9": [
                {"period_id": "p1", "return_pct": "9"},
                {"period_id": "p2", "return_pct": "-5"},
            ],
        }
        comparison = compare_required_baselines(
            strategy_returns=strategy,
            baseline_returns=baselines,
        )
        self.assertEqual(comparison["strategy"]["twr_pct"], "4.5000")
        self.assertEqual(
            set(comparison["baselines"]),
            {"SPY", "QQQ", "XLK", "C9"},
        )
        self.assertFalse(comparison["future_performance_claim"])

        incomplete = dict(baselines)
        del incomplete["C9"]
        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "exactly SPY, QQQ, XLK, and C9",
        ):
            compare_required_baselines(
                strategy_returns=strategy,
                baseline_returns=incomplete,
            )

        misaligned = {name: list(rows) for name, rows in baselines.items()}
        misaligned["SPY"] = [
            {"period_id": "different", "return_pct": "5"},
            {"period_id": "p2", "return_pct": "-2"},
        ]
        with self.assertRaisesRegex(PerformanceEvidenceError, "do not align"):
            compare_required_baselines(
                strategy_returns=strategy,
                baseline_returns=misaligned,
            )

    def test_block_bootstrap_interface_is_seeded_and_measurement_only(self) -> None:
        first = block_bootstrap_twr_ci(
            ["1", "-1", "2", "-2", "1", "0"],
            iterations=250,
            block_size=2,
            confidence_pct="90",
            seed=77,
        )
        second = block_bootstrap_twr_ci(
            ["1", "-1", "2", "-2", "1", "0"],
            iterations=250,
            block_size=2,
            confidence_pct="90",
            seed=77,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["method"], "circular_block_bootstrap")
        self.assertEqual(first["observations"], 6)
        self.assertEqual(first["iterations"], 250)
        self.assertFalse(first["future_performance_claim"])
        self.assertLessEqual(
            float(first["lower_twr_pct"]),
            float(first["upper_twr_pct"]),
        )

    def test_rolling_sixty_month_receipt_measures_objective_without_quota(
        self,
    ) -> None:
        rows = _monthly_rows(["1"] * 60)
        receipt = rolling_monthly_performance_receipt(
            ledger_id="paper-ledger-v1",
            policy_id="frozen-policy-v1",
            policy_sha256="a" * 64,
            evaluation_as_of_utc="2026-01-15T00:00:00Z",
            monthly_rows=rows,
        )
        self.assertEqual(receipt["ledger_row_count"], 60)
        self.assertEqual(len(receipt["rolling_windows"]["12"]), 49)
        self.assertEqual(len(receipt["rolling_windows"]["36"]), 25)
        self.assertEqual(len(receipt["rolling_windows"]["60"]), 1)
        self.assertEqual(
            receipt["rolling_windows"]["60"][0][
                "annualized_cagr_pct"
            ],
            "12.6825",
        )
        self.assertEqual(
            receipt["return_objective_assessment"]["status"],
            "within_aspirational_range",
        )
        self.assertFalse(
            receipt["return_objective_assessment"]["return_guarantee"]
        )
        self.assertFalse(
            receipt["return_objective_assessment"][
                "risk_gates_override_allowed"
            ]
        )
        self.assertEqual(
            receipt["dispersion"]["sortino_status"],
            "undefined_no_downside_deviation",
        )
        self.assertEqual(
            receipt["drawdown_and_recovery"]["maximum_drawdown_pct"],
            "0.0000",
        )
        self.assertEqual(len(receipt["receipt_sha256"]), 64)
        self.assertFalse(receipt["broker_or_execution_capability"])

    def test_monthly_ledger_hash_gaps_and_future_rows_fail_closed(
        self,
    ) -> None:
        rows = _monthly_rows(["1", "2", "3"])
        tampered = copy.deepcopy(rows)
        tampered[1]["net_return_pct"] = "99.000000"
        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "row hash mismatch",
        ):
            rolling_monthly_performance_receipt(
                ledger_id="paper-ledger-v1",
                policy_id="frozen-policy-v1",
                policy_sha256="b" * 64,
                evaluation_as_of_utc="2021-12-31T00:00:00Z",
                monthly_rows=tampered,
            )

        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "must be consecutive",
        ):
            rolling_monthly_performance_receipt(
                ledger_id="paper-ledger-v1",
                policy_id="frozen-policy-v1",
                policy_sha256="b" * 64,
                evaluation_as_of_utc="2021-12-31T00:00:00Z",
                monthly_rows=[rows[0], rows[2]],
            )

        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "future-available",
        ):
            rolling_monthly_performance_receipt(
                ledger_id="paper-ledger-v1",
                policy_id="frozen-policy-v1",
                policy_sha256="b" * 64,
                evaluation_as_of_utc="2021-02-15T00:00:00Z",
                monthly_rows=rows,
            )

        with self.assertRaisesRegex(
            PerformanceEvidenceError,
            "must match start and end calendar month",
        ):
            build_monthly_performance_ledger_row(
                period_id="2021-01",
                start_utc="2021-02-01T00:00:00Z",
                end_utc="2021-02-28T23:59:59Z",
                net_return_pct="1",
                source_ids=["paper-ledger:mislabeled"],
            )

    def test_short_history_does_not_claim_five_year_objective(self) -> None:
        receipt = rolling_monthly_performance_receipt(
            ledger_id="paper-ledger-v1",
            policy_id="frozen-policy-v1",
            policy_sha256="c" * 64,
            evaluation_as_of_utc="2026-01-15T00:00:00Z",
            monthly_rows=_monthly_rows(["1"] * 59),
        )
        self.assertEqual(
            receipt["return_objective_assessment"]["status"],
            "insufficient_60_month_history",
        )
        self.assertIsNone(
            receipt["return_objective_assessment"][
                "latest_60_month_annualized_cagr_pct"
            ]
        )
        self.assertEqual(receipt["rolling_windows"]["60"], [])

    def test_rolling_ledger_retains_terminal_total_loss(self) -> None:
        returns = ["1"] * 59 + ["-100"]
        receipt = rolling_monthly_performance_receipt(
            ledger_id="paper-ledger-v1",
            policy_id="frozen-policy-v1",
            policy_sha256="d" * 64,
            evaluation_as_of_utc="2026-01-15T00:00:00Z",
            monthly_rows=_monthly_rows(returns),
        )
        self.assertEqual(receipt["total_twr_pct"], "-100.0000")
        self.assertEqual(
            receipt["rolling_windows"]["60"][0][
                "annualized_cagr_pct"
            ],
            "-100.0000",
        )
        self.assertEqual(
            receipt["drawdown_and_recovery"]["maximum_drawdown_pct"],
            "100.0000",
        )
        self.assertEqual(
            receipt["return_objective_assessment"]["status"],
            "below_aspirational_range",
        )


if __name__ == "__main__":
    unittest.main()
