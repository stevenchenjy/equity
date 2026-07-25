from __future__ import annotations

import unittest
from decimal import Decimal

from _support import FIXTURE_ROOT, evaluated, materialized, rehash
from evaluate_phase5r_llm_decision import verify_numeric_integrity
from phase5r_llm_contract import ContractError, decimal_round


class NumericTests(unittest.TestCase):
    def test_decimal_examples_round_exactly(self) -> None:
        yoy = (Decimal("478844000") / Decimal("366884000") - 1) * 100
        margin = Decimal("44508000") / Decimal("478844000") * 100
        negative_margin = Decimal("-41853000") / Decimal("387068000") * 100
        self.assertEqual(decimal_round(yoy), Decimal("30.52"))
        self.assertEqual(decimal_round(margin), Decimal("9.29"))
        self.assertEqual(decimal_round(negative_margin), Decimal("-10.81"))

    def test_valid_numeric_fixture_reconciles(self) -> None:
        packet, _, _ = materialized("g04_valid_numeric_reconciliation")
        verify_numeric_integrity(packet)
        self.assertTrue(evaluated("g04_valid_numeric_reconciliation")["passed"])

    def test_numeric_mismatch_fails_closed(self) -> None:
        packet, _, _ = materialized("g05_numeric_mismatch")
        with self.assertRaisesRegex(ContractError, "not reconciled"):
            verify_numeric_integrity(packet)
        result = evaluated("g05_numeric_mismatch")
        self.assertEqual(result["actual"]["safe_classification"], "abstain")
        self.assertFalse(result["actual"]["validation_passed"])

    def test_unit_and_period_mismatch_fails_closed(self) -> None:
        packet, _, _ = materialized("g06_unit_period_mismatch")
        with self.assertRaises(ContractError):
            verify_numeric_integrity(packet)
        result = evaluated("g06_unit_period_mismatch")
        self.assertEqual(result["actual"]["safe_classification"], "abstain")

    def test_zero_prior_value_is_rejected(self) -> None:
        packet, _, _ = materialized("g04_valid_numeric_reconciliation")
        packet["calculations"][0]["inputs"][1]["value"] = "0"
        with self.assertRaisesRegex(ContractError, "prior value is zero"):
            verify_numeric_integrity(rehash(packet))

    def test_nonfinite_decimal_is_rejected_by_core(self) -> None:
        with self.assertRaises(ContractError):
            decimal_round("NaN")


if __name__ == "__main__":
    unittest.main()
