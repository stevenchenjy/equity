from __future__ import annotations

from copy import deepcopy
import unittest

from _support import SCRIPT_DIR, materialized, rehash  # noqa: F401
from phase5r_evidence_freshness import (
    EvidenceFreshnessError,
    build_evidence_freshness_receipt,
    freshness_action_review_reasons,
    validate_evidence_freshness_receipt,
)
from phase5r_llm_contract import adjudicate


AS_OF = "2026-07-26T18:00:00Z"


def current_inputs() -> dict[str, object]:
    return {
        "ticker": "TST",
        "as_of_utc": AS_OF,
        "sec_scan": {
            "status_artifact_sha256": "1" * 64,
            "completed_through_utc": "2026-07-25T18:00:00Z",
            "ticker_scanned": True,
            "complete": True,
        },
        "market": {
            "observed_at_utc": "2026-07-24T20:15:00Z",
            "market_session_date": "2026-07-24",
            "expected_market_session_date": "2026-07-24",
            "complete_close": True,
        },
        "valuation": {
            "valuation_receipt_sha256": "2" * 64,
            "receipt_as_of_utc": AS_OF,
            "market_input_at_utc": "2026-07-24T20:15:00Z",
            "market_session_date": "2026-07-24",
            "expected_market_session_date": "2026-07-24",
            "scenario_refreshed_at_utc": "2026-07-25T20:00:00Z",
            "complete": True,
        },
        # The filing may be old.  The current SEC scan, rather than filing age,
        # determines transition freshness.
        "durable_sec_source_ids": ["sec:TST:10-K:2024"],
    }


def receipt(**overrides: object) -> dict[str, object]:
    values = current_inputs()
    values.update(overrides)
    return build_evidence_freshness_receipt(**values)  # type: ignore[arg-type]


class EvidenceFreshnessTests(unittest.TestCase):
    def test_current_weekend_receipt_keeps_last_expected_close_current(
        self,
    ) -> None:
        value = receipt()
        self.assertTrue(value["sec_scan"]["current"])
        self.assertTrue(value["market"]["current"])
        self.assertTrue(value["valuation"]["current"])
        self.assertTrue(value["transition_freshness"]["all_current"])
        self.assertEqual(
            value["durable_sec_source_ids"],
            ["sec:TST:10-K:2024"],
        )
        self.assertFalse(
            value["guardrails"]["durable_sec_evidence_age_limit_applied"]
        )
        self.assertEqual(validate_evidence_freshness_receipt(value), value)

    def test_expired_sec_watermark_blocks_transition_not_durable_evidence(
        self,
    ) -> None:
        inputs = current_inputs()
        inputs["sec_scan"] = {
            **inputs["sec_scan"],  # type: ignore[arg-type]
            "completed_through_utc": "2026-07-23T17:59:59Z",
        }
        value = build_evidence_freshness_receipt(
            **inputs  # type: ignore[arg-type]
        )
        self.assertFalse(value["sec_scan"]["current"])
        self.assertIn(
            "sec_scan_watermark_expired",
            value["sec_scan"]["blocked_reasons"],
        )
        self.assertEqual(
            value["durable_sec_source_ids"],
            ["sec:TST:10-K:2024"],
        )
        self.assertEqual(
            freshness_action_review_reasons(
                value,
                ticker="TST",
                require_market_and_valuation=True,
            ),
            ["transition_sec_scan_not_current:TST"],
        )

    def test_market_and_valuation_freshness_are_ticker_scoped(self) -> None:
        first = receipt()
        second_market = deepcopy(current_inputs()["market"])
        second_market["market_session_date"] = "2026-07-23"
        second = receipt(ticker="ALT", market=second_market)
        self.assertTrue(first["market"]["current"])
        self.assertFalse(second["market"]["current"])
        self.assertEqual(
            freshness_action_review_reasons(
                second,
                ticker="ALT",
                require_market_and_valuation=True,
            ),
            ["transition_market_not_current:ALT"],
        )

    def test_expired_scenario_blocks_valuation_freshness_only(self) -> None:
        inputs = current_inputs()
        inputs["valuation"] = {
            **inputs["valuation"],  # type: ignore[arg-type]
            "scenario_refreshed_at_utc": "2026-07-19T17:59:59Z",
        }
        value = build_evidence_freshness_receipt(
            **inputs  # type: ignore[arg-type]
        )
        self.assertTrue(value["sec_scan"]["current"])
        self.assertTrue(value["market"]["current"])
        self.assertFalse(value["valuation"]["current"])
        self.assertIn(
            "valuation_scenario_expired",
            value["valuation"]["blocked_reasons"],
        )

    def test_risk_reduction_can_require_current_scan_without_valuation(
        self,
    ) -> None:
        inputs = current_inputs()
        inputs["valuation"] = {
            "valuation_receipt_sha256": "",
            "receipt_as_of_utc": "",
            "market_input_at_utc": "",
            "market_session_date": "",
            "expected_market_session_date": "",
            "scenario_refreshed_at_utc": "",
            "complete": False,
        }
        value = build_evidence_freshness_receipt(
            **inputs  # type: ignore[arg-type]
        )
        self.assertEqual(
            freshness_action_review_reasons(
                value,
                ticker="TST",
                require_market_and_valuation=False,
            ),
            [],
        )
        self.assertEqual(
            freshness_action_review_reasons(
                value,
                ticker="TST",
                require_market_and_valuation=True,
            ),
            ["transition_valuation_not_current:TST"],
        )

    def test_missing_receipt_fails_action_review(self) -> None:
        self.assertEqual(
            freshness_action_review_reasons(
                None,
                ticker="TST",
                require_market_and_valuation=True,
            ),
            ["transition_freshness_receipt_missing:TST"],
        )

    def test_tampering_is_rejected_by_deterministic_recomputation(self) -> None:
        value = receipt()
        value["market"]["current"] = False
        with self.assertRaisesRegex(
            EvidenceFreshnessError,
            "does not match deterministic recomputation",
        ):
            validate_evidence_freshness_receipt(value)

    def test_future_observation_is_rejected(self) -> None:
        inputs = current_inputs()
        inputs["sec_scan"] = {
            **inputs["sec_scan"],  # type: ignore[arg-type]
            "completed_through_utc": "2026-07-26T18:00:01Z",
        }
        with self.assertRaisesRegex(
            EvidenceFreshnessError,
            "later than the receipt as-of",
        ):
            build_evidence_freshness_receipt(
                **inputs  # type: ignore[arg-type]
            )

    def test_legacy_non_transition_packet_without_receipt_is_compatible(
        self,
    ) -> None:
        packet, responses, closes = materialized("g01_stable_hold")
        del packet["evidence_freshness"]
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
        self.assertEqual(decision["research_classification"], "hold_existing")
        self.assertEqual(decision["classification"], "hold_existing")
        self.assertEqual(decision["action_review_status"], "not_applicable")
        self.assertNotIn(
            "transition_freshness_receipt_missing:TST",
            decision["action_review_reasons"],
        )

    def test_legacy_transition_without_receipt_blocks_action_only(
        self,
    ) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        del packet["evidence_freshness"]
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
            "transition_freshness_receipt_missing:TST",
            decision["action_review_reasons"],
        )
        self.assertNotIn(
            "transition_freshness_receipt_missing:TST",
            decision["research_reasons"],
        )
        self.assertTrue(decision["validation_passed"])

    def test_expired_scan_receipt_blocks_action_without_erasing_research(
        self,
    ) -> None:
        packet, responses, closes = materialized("g08_add_second_close")
        current = packet["evidence_freshness"][0]
        expired = build_evidence_freshness_receipt(
            ticker="TST",
            as_of_utc=current["as_of_utc"],
            sec_scan={
                "status_artifact_sha256": current["sec_scan"][
                    "status_artifact_sha256"
                ],
                "completed_through_utc": "2026-07-20T22:20:00Z",
                "ticker_scanned": True,
                "complete": True,
            },
            market={
                key: current["market"][key]
                for key in (
                    "observed_at_utc",
                    "market_session_date",
                    "expected_market_session_date",
                    "complete_close",
                )
            },
            valuation={
                key: current["valuation"][key]
                for key in (
                    "valuation_receipt_sha256",
                    "receipt_as_of_utc",
                    "market_input_at_utc",
                    "market_session_date",
                    "expected_market_session_date",
                    "scenario_refreshed_at_utc",
                    "complete",
                )
            },
            durable_sec_source_ids=current["durable_sec_source_ids"],
        )
        packet["evidence_freshness"][0] = expired
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
        self.assertIn(
            "transition_sec_scan_not_current:TST",
            decision["action_review_reasons"],
        )
        self.assertNotIn(
            "transition_sec_scan_not_current:TST",
            decision["research_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
