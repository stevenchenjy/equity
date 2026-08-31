from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v7 as v7
from phase5r_llm_provider import ProviderResult
from test_phase5r_model_pilot_v6 import _V6FixtureProvider


class _V7FixtureProvider(_V6FixtureProvider):
    """Match the real carried v6 claim cardinality in critic fixtures."""

    def generate(self, **kwargs: object) -> ProviderResult:
        result = super().generate(**kwargs)
        if kwargs["role"] != "critic":
            return result
        input_payload = kwargs["input_payload"]
        source_id = input_payload["packet_evidence"]["source_catalog"][0]["source_id"]
        payload = copy.deepcopy(result.payload)
        payload["claim_reviews"] = [
            {
                "assessment_label": label,
                "claim_id": claim["claim_id"],
                "semantic_support": "supported",
                "citation_accuracy": "accurate",
                "issue": "No material issue identified.",
                "supporting_source_ids": [source_id],
            }
            for label, assessment_key in (("A", "assessment_A"), ("B", "assessment_B"))
            for claim in input_payload[assessment_key]["claims"]
        ]
        return ProviderResult(payload=payload, metadata=result.metadata)


class ReplacementPilotV7Tests(unittest.TestCase):
    def test_readiness_is_offline_and_source_v6_is_unchanged(self) -> None:
        root = v1.QUARANTINE_ROOT / "v6"
        paths = (
            root / "phase5r_model_pilot_v6_authorization.json",
            root / "phase5r_model_pilot_v6_execution_plan.json",
            root / "phase5r_model_pilot_v6_journal.jsonl",
        )
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        report = v7.check_v7_readiness()
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["planned_model_calls"], 19)
        self.assertEqual(report["worst_case_reserved_usd"], "3.86232")
        self.assertEqual(report["maximum_usd"], "4.824031")
        self.assertEqual(report["source_v6_receipts"], 10)
        self.assertFalse(report["provider_constructed"])
        self.assertFalse(report["network_used"])
        self.assertEqual(before, after)

    def test_fixture_v7_consumes_only_sealed_new_calls_and_stays_no_go(self) -> None:
        source_root = v1.QUARANTINE_ROOT / "v6"
        source_paths = (
            source_root / "phase5r_model_pilot_v6_authorization.json",
            source_root / "phase5r_model_pilot_v6_execution_plan.json",
            source_root / "phase5r_model_pilot_v6_journal.jsonl",
        )
        source_before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        }
        with tempfile.TemporaryDirectory() as temporary:
            quarantine = Path(temporary) / "quarantine"
            output = quarantine / "v7"
            quarantine.mkdir()
            completion = v7.execute_model_pilot_v7(
                provider_factory=_V7FixtureProvider,
                explicit_user_authorization=True,
                output_root=output,
                allow_test_provider=True,
                test_quarantine_root=quarantine,
            )
            self.assertEqual(completion["new_physical_model_calls"], 19)
            self.assertEqual(completion["cumulative_physical_model_calls"], 30)
            self.assertEqual(completion["usable_provider_outputs"], 29)
            self.assertEqual(
                completion["go_no_go"], "no_go_incomplete_30_output_protocol"
            )
            self.assertEqual(
                completion["anonymous_review_materials"],
                "not_generated_incomplete_frozen_30_call_protocol",
            )
            receipts = sorted((output / v1.RESPONSE_DIRECTORY_NAME).glob("*.json"))
            self.assertEqual(len(receipts), 19)
            self.assertFalse((output / "phase5r_model_pilot_v7_review.json").exists())
            self.assertTrue((output / v7.V7_REPORT_NAME).is_file())
            repeated = v7.execute_model_pilot_v7(
                provider_factory=_V7FixtureProvider,
                explicit_user_authorization=True,
                output_root=output,
                allow_test_provider=True,
                test_quarantine_root=quarantine,
            )
            self.assertEqual(
                repeated["completion_sha256"], completion["completion_sha256"]
            )
        source_after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        }
        self.assertEqual(source_before, source_after)


if __name__ == "__main__":
    unittest.main()
