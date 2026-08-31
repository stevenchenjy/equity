from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from phase5r_llm_provider import ProviderError, ProviderResult
from run_phase5r_model_pilot import PilotStop, _load_journal
from run_phase5r_model_pilot_v8_qualification import (
    V8_JOURNAL_NAME,
    check_v8_qualification_readiness,
    execute_v8_qualification,
)


class _OfflineQualificationProvider:
    offline_test_provider = True
    max_output_tokens = 3_800

    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure

    def count_input_tokens(self, **kwargs: object) -> int:
        del kwargs
        return 7

    def generate(self, **kwargs: object) -> ProviderResult:
        del kwargs
        if self.failure is not None:
            raise self.failure
        return ProviderResult(
            payload={"qualification": "passed"},
            metadata={
                "transport": "test_fixture",
                "model": "gpt-5.6-sol",
                "resolved_model": "gpt-5.6-sol",
                "requested_service_tier": "default",
                "resolved_service_tier": "default",
                "request_timeout_seconds": 120,
                "billing_scope_attestation": (
                    "global_standard_no_regional_processing"
                ),
                "credential_read": False,
                "tools_enabled": False,
                "store": False,
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 1,
                    "cached_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )


class V8QualificationTests(unittest.TestCase):
    def test_readiness_is_offline_and_sealed(self) -> None:
        readiness = check_v8_qualification_readiness()

        self.assertTrue(readiness["passed"])
        self.assertEqual(readiness["planned_model_calls"], 3)
        self.assertEqual(readiness["maximum_usd"], "0.8712")
        self.assertEqual(readiness["training_budget_usd"], "15.00")
        self.assertFalse(readiness["provider_constructed"])
        self.assertFalse(readiness["network_used"])
        self.assertFalse(readiness["files_written"])

    def test_fixture_qualification_completes_without_persisting_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            quarantine_root = Path(temporary) / "quarantine"
            quarantine_root.mkdir(mode=0o700)
            output_root = quarantine_root / "v8_qualification"
            completion = execute_v8_qualification(
                provider_factory=_OfflineQualificationProvider,
                explicit_user_authorization=True,
                output_root=output_root,
                allow_test_provider=True,
                test_quarantine_root=quarantine_root,
            )

            self.assertTrue(completion["passed"])
            self.assertEqual(completion["physical_model_calls"], 3)
            self.assertFalse(completion["collection_authorized"])
            self.assertEqual(list((output_root / "responses").iterdir()), [])

    def test_failure_persists_only_the_safe_provider_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            quarantine_root = Path(temporary) / "quarantine"
            quarantine_root.mkdir(mode=0o700)
            output_root = quarantine_root / "v8_qualification"
            failure = ProviderError(
                "canary-text-that-must-not-be-persisted",
                failure_code="api_rate_limited",
            )

            with self.assertRaises(PilotStop):
                execute_v8_qualification(
                    provider_factory=lambda: _OfflineQualificationProvider(
                        failure=failure
                    ),
                    explicit_user_authorization=True,
                    output_root=output_root,
                    allow_test_provider=True,
                    test_quarantine_root=quarantine_root,
                )

            events = _load_journal(
                output_root / V8_JOURNAL_NAME,
                plan_sha256=check_v8_qualification_readiness()[
                    "execution_plan_sha256"
                ],
            )
            failed = next(
                event
                for event in events
                if event["event_kind"] == "call_outcome_unknown"
            )
            self.assertEqual(
                failed["details"]["provider_failure_code"],
                "api_rate_limited",
            )
            self.assertNotIn(
                "canary-text-that-must-not-be-persisted",
                json.dumps(events, sort_keys=True),
            )


if __name__ == "__main__":
    unittest.main()
