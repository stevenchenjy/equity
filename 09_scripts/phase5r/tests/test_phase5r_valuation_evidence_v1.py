from __future__ import annotations

from copy import deepcopy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_valuation_evidence_v1 import (
    ValuationEvidenceError,
    build_valuation_evidence_v1,
    validate_valuation_evidence_v1,
    valuation_packet_calculations,
)


AS_OF = "2026-07-25T20:00:00Z"


def item(
    value: str,
    unit: str,
    *,
    period: str,
    source_id: str,
    kind: str = "observation",
    available_at: str = "2026-07-24T20:00:00Z",
) -> dict[str, object]:
    return {
        "value": value,
        "unit": unit,
        "period": period,
        "available_at_utc": available_at,
        "source_ids": [source_id],
        "evidence_kind": kind,
    }


def complete_inputs() -> dict[str, dict[str, object]]:
    return {
        "share_price": item(
            "10",
            "USD_per_share",
            period="2026-07-24 close",
            source_id="market:TST:2026-07-24",
        ),
        "diluted_shares": item(
            "100",
            "shares",
            period="TTM ended 2026-06-30",
            source_id="sec:TST:2026-Q2",
        ),
        "cash_and_equivalents": item(
            "200",
            "USD",
            period="2026-06-30",
            source_id="sec:TST:2026-Q2",
        ),
        "total_debt": item(
            "100",
            "USD",
            period="2026-06-30",
            source_id="sec:TST:2026-Q2",
        ),
        "revenue_ttm": item(
            "400",
            "USD",
            period="TTM ended 2026-06-30",
            source_id="calc:TST:revenue-ttm",
        ),
        "free_cash_flow_ttm": item(
            "40",
            "USD",
            period="TTM ended 2026-06-30",
            source_id="calc:TST:fcf-ttm",
        ),
        "prior_diluted_shares": item(
            "80",
            "shares",
            period="TTM ended 2025-06-30",
            source_id="sec:TST:2025-Q2",
            available_at="2025-07-24T20:00:00Z",
        ),
        "target_price_assumption": item(
            "15",
            "USD_per_share",
            period="research scenario at 2026-07-25",
            source_id="scenario:TST:base",
            kind="scenario_assumption",
        ),
        "downside_price_assumption": item(
            "8",
            "USD_per_share",
            period="research scenario at 2026-07-25",
            source_id="scenario:TST:bear",
            kind="scenario_assumption",
        ),
    }


class ValuationEvidenceV1Tests(unittest.TestCase):
    def test_complete_receipt_uses_decimal_math_and_provenance(self) -> None:
        receipt = build_valuation_evidence_v1(
            ticker="tst",
            as_of_utc=AS_OF,
            inputs=complete_inputs(),
        )
        calculations = {
            row["calculation_id"]: row for row in receipt["calculations"]
        }
        self.assertEqual(calculations["market_cap"]["value"], "1000.00")
        self.assertEqual(calculations["net_debt"]["value"], "-100.00")
        self.assertEqual(calculations["enterprise_value"]["value"], "900.00")
        self.assertEqual(calculations["ev_to_revenue"]["value"], "2.2500")
        self.assertEqual(
            calculations["free_cash_flow_margin_pct"]["value"],
            "10.00",
        )
        self.assertEqual(
            calculations["free_cash_flow_yield_pct"]["value"],
            "4.00",
        )
        self.assertEqual(calculations["ev_to_free_cash_flow"]["value"], "22.5000")
        self.assertEqual(calculations["dilution_pct"]["value"], "25.00")
        self.assertEqual(calculations["target_upside_pct"]["value"], "50.00")
        self.assertEqual(calculations["downside_change_pct"]["value"], "-20.00")
        self.assertEqual(calculations["reward_to_risk"]["value"], "2.5000")
        self.assertEqual(
            calculations["enterprise_value"]["source_ids"],
            ["market:TST:2026-07-24", "sec:TST:2026-Q2"],
        )
        self.assertTrue(receipt["sufficiency"]["decision_sufficient"])
        self.assertTrue(
            receipt["guardrails"]["action_grade_valuation_permitted"]
        )
        self.assertEqual(validate_valuation_evidence_v1(receipt), receipt)
        projected = valuation_packet_calculations(receipt)
        self.assertEqual(
            projected[0]["calculation_id"],
            "valuation:TST:market_cap",
        )
        self.assertTrue(all(row["ticker"] == "TST" for row in projected))
        self.assertTrue(all(row["reconciled"] is True for row in projected))
        self.assertTrue(
            all(
                row["valuation_receipt_sha256"]
                == receipt["receipt_sha256"]
                for row in projected
            )
        )

    def test_missing_share_count_fails_closed_and_is_not_invented(self) -> None:
        inputs = complete_inputs()
        del inputs["diluted_shares"]
        receipt = build_valuation_evidence_v1(
            ticker="TST",
            as_of_utc=AS_OF,
            inputs=inputs,
        )
        calculation_ids = {
            row["calculation_id"] for row in receipt["calculations"]
        }
        self.assertNotIn("market_cap", calculation_ids)
        self.assertNotIn("enterprise_value", calculation_ids)
        self.assertIn(
            "diluted_shares",
            receipt["sufficiency"]["missing_core_input_ids"],
        )
        self.assertFalse(receipt["sufficiency"]["valuation_sufficient"])
        self.assertFalse(receipt["sufficiency"]["decision_sufficient"])
        self.assertFalse(
            receipt["guardrails"]["action_grade_valuation_permitted"]
        )

    def test_missing_target_or_downside_blocks_reward_to_risk(self) -> None:
        inputs = complete_inputs()
        del inputs["target_price_assumption"]
        receipt = build_valuation_evidence_v1(
            ticker="TST",
            as_of_utc=AS_OF,
            inputs=inputs,
        )
        self.assertTrue(receipt["sufficiency"]["valuation_sufficient"])
        self.assertFalse(receipt["sufficiency"]["scenario_sufficient"])
        self.assertFalse(receipt["sufficiency"]["decision_sufficient"])
        self.assertNotIn(
            "reward_to_risk",
            {row["calculation_id"] for row in receipt["calculations"]},
        )

    def test_invalid_scenario_prices_are_explicitly_blocked(self) -> None:
        inputs = complete_inputs()
        inputs["target_price_assumption"]["value"] = "9"
        inputs["downside_price_assumption"]["value"] = "11"
        receipt = build_valuation_evidence_v1(
            ticker="TST",
            as_of_utc=AS_OF,
            inputs=inputs,
        )
        self.assertFalse(receipt["sufficiency"]["scenario_sufficient"])
        self.assertIn(
            "target_not_above_share_price",
            receipt["sufficiency"]["blocked_reasons"],
        )
        self.assertIn(
            "downside_not_below_share_price",
            receipt["sufficiency"]["blocked_reasons"],
        )

    def test_negative_fcf_is_preserved_not_rewritten(self) -> None:
        inputs = complete_inputs()
        inputs["free_cash_flow_ttm"]["value"] = "-20"
        receipt = build_valuation_evidence_v1(
            ticker="TST",
            as_of_utc=AS_OF,
            inputs=inputs,
        )
        calculations = {
            row["calculation_id"]: row for row in receipt["calculations"]
        }
        self.assertEqual(
            calculations["free_cash_flow_margin_pct"]["value"],
            "-5.00",
        )
        self.assertEqual(
            calculations["free_cash_flow_yield_pct"]["value"],
            "-2.00",
        )
        self.assertNotIn("ev_to_free_cash_flow", calculations)
        self.assertTrue(receipt["sufficiency"]["valuation_sufficient"])

    def test_wrong_unit_kind_or_future_availability_is_rejected(self) -> None:
        cases = []
        wrong_unit = complete_inputs()
        wrong_unit["diluted_shares"]["unit"] = "USD"
        cases.append(wrong_unit)
        wrong_kind = complete_inputs()
        wrong_kind["target_price_assumption"]["evidence_kind"] = "observation"
        cases.append(wrong_kind)
        future = complete_inputs()
        future["cash_and_equivalents"][
            "available_at_utc"
        ] = "2026-07-26T00:00:00Z"
        cases.append(future)
        for inputs in cases:
            with self.subTest(inputs=inputs):
                with self.assertRaises(ValuationEvidenceError):
                    build_valuation_evidence_v1(
                        ticker="TST",
                        as_of_utc=AS_OF,
                        inputs=inputs,
                    )

    def test_unknown_inputs_and_binary_floats_are_rejected(self) -> None:
        inputs = complete_inputs()
        inputs["invented_target_multiple"] = item(
            "99",
            "multiple",
            period="unknown",
            source_id="model:invented",
        )
        with self.assertRaisesRegex(
            ValuationEvidenceError,
            "unknown valuation input ids",
        ):
            build_valuation_evidence_v1(
                ticker="TST",
                as_of_utc=AS_OF,
                inputs=inputs,
            )

        inputs = complete_inputs()
        inputs["share_price"]["value"] = 10.0
        with self.assertRaisesRegex(ValuationEvidenceError, "decimal string"):
            build_valuation_evidence_v1(
                ticker="TST",
                as_of_utc=AS_OF,
                inputs=inputs,
            )

    def test_tampered_calculation_or_digest_fails_recomputation(self) -> None:
        receipt = build_valuation_evidence_v1(
            ticker="TST",
            as_of_utc=AS_OF,
            inputs=complete_inputs(),
        )
        tampered = deepcopy(receipt)
        tampered["calculations"][0]["value"] = "999999.00"
        with self.assertRaisesRegex(
            ValuationEvidenceError,
            "deterministic recomputation",
        ):
            validate_valuation_evidence_v1(tampered)


if __name__ == "__main__":
    unittest.main()
