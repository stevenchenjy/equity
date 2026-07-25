from __future__ import annotations

import copy
import unittest

from _support import FIXTURE_ROOT, materialized, rehash
from evaluate_phase5r_llm_decision import verify_source_integrity
from phase5r_llm_contract import (
    ContractError,
    validate_analyst,
    validate_committee,
)


class CitationTests(unittest.TestCase):
    def test_primary_source_hash_span_and_time_are_valid(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        verify_source_integrity(packet, FIXTURE_ROOT)

    def test_missing_material_claim_citation_is_rejected(self) -> None:
        packet, responses, _ = materialized("g02_missing_material_citation")
        with self.assertRaisesRegex(ContractError, "at least one packet-local source"):
            validate_analyst(packet, responses["analyst"])

    def test_unknown_packet_local_source_is_rejected(self) -> None:
        packet, responses, _ = materialized("g03_unknown_source_locator")
        with self.assertRaisesRegex(ContractError, "unknown source ids"):
            validate_committee(packet, responses["committee"])

    def test_source_hash_mismatch_is_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["source_catalog"][0]["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            ContractError, "(?:excerpt digest|source hash) mismatch"
        ):
            verify_source_integrity(rehash(packet), FIXTURE_ROOT)

    def test_future_source_is_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["source_catalog"][0]["accepted_at"] = "2026-07-24T09:00:00-04:00"
        with self.assertRaisesRegex(ContractError, "future"):
            verify_source_integrity(rehash(packet), FIXTURE_ROOT)

    def test_path_traversal_locator_is_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["source_catalog"][0]["locator"]["fixture_path"] = (
            "../../../../07_automation/email_delivery/"
            "phase5r_email_config.local.json"
        )
        with self.assertRaisesRegex(ContractError, "escapes root"):
            verify_source_integrity(rehash(packet), FIXTURE_ROOT)

    def test_invalid_span_is_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["source_catalog"][0]["locator"]["char_end"] = 999999
        with self.assertRaisesRegex(ContractError, "span is invalid"):
            verify_source_integrity(rehash(packet), FIXTURE_ROOT)


if __name__ == "__main__":
    unittest.main()
