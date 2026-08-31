from __future__ import annotations

import unittest

import run_phase5r_model_pilot as v1
from run_phase5r_model_pilot_v2 import (
    _redacted_provider_metadata,
    check_v2_readiness,
    execute_model_pilot_v2,
)


class ReplacementPilotV2Tests(unittest.TestCase):
    def test_preflight_is_read_only_and_bounded(self) -> None:
        result = check_v2_readiness()
        self.assertTrue(result["passed"])
        self.assertFalse(result["provider_constructed"])
        self.assertFalse(result["network_used"])
        self.assertFalse(result["files_written"])
        self.assertEqual(result["new_model_calls"], 26)
        self.assertEqual(result["new_reserved_usd"], "4.53024")
        self.assertEqual(result["cumulative_reserved_usd"], "4.7346925")
        self.assertFalse(result["canonical_effect"])
        self.assertFalse(result["email_effect"])

    def test_executor_refuses_without_explicit_user_authorization(self) -> None:
        with self.assertRaisesRegex(v1.PilotStop, "explicit interactive"):
            execute_model_pilot_v2(
                provider_factory=lambda: None,  # type: ignore[arg-type]
                explicit_user_authorization=False,
            )

    def test_provider_response_identifier_is_redacted_before_persistence(self) -> None:
        metadata = _redacted_provider_metadata(
            {"provider_response_id": "resp_sensitive_identifier", "usage": {}}
        )
        self.assertNotIn("provider_response_id", metadata)
        self.assertRegex(metadata["provider_response_id_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
