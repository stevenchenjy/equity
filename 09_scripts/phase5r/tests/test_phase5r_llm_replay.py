from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _support import MANIFEST_PATH, manifest, materialized
from evaluate_phase5r_llm_decision import evaluate_manifest, write_report


EXPECTED_CASE_IDS = {
    "g01_stable_hold",
    "g02_missing_material_citation",
    "g03_unknown_source_locator",
    "g04_valid_numeric_reconciliation",
    "g05_numeric_mismatch",
    "g06_unit_period_mismatch",
    "g07_add_first_close",
    "g08_add_second_close",
    "g09_critic_disagreement",
    "g10_material_thesis_break",
    "g11_stale_market_data",
    "g12_prompt_injection",
}


class ReplayTests(unittest.TestCase):
    def test_manifest_covers_exact_g01_to_g12_matrix(self) -> None:
        case_ids = {row["case_id"] for row in manifest()["cases"]}
        self.assertEqual(case_ids, EXPECTED_CASE_IDS)

    def test_packet_ids_are_unique_and_repeatable(self) -> None:
        first = {case_id: materialized(case_id)[0]["packet_id"] for case_id in EXPECTED_CASE_IDS}
        second = {case_id: materialized(case_id)[0]["packet_id"] for case_id in EXPECTED_CASE_IDS}
        self.assertEqual(first, second)
        self.assertEqual(len(set(first.values())), len(first))

    def test_all_golden_cases_pass(self) -> None:
        report = evaluate_manifest(MANIFEST_PATH)
        self.assertTrue(report["all_passed"], report["results"])
        self.assertEqual(report["case_count"], 12)
        self.assertEqual(report["passed_count"], 12)
        self.assertEqual(report["failed_count"], 0)
        self.assertFalse(report["network_invoked"])
        self.assertFalse(report["codex_invoked"])
        self.assertFalse(report["email_invoked"])
        self.assertFalse(report["c7_invoked"])
        self.assertFalse(report["canonical_effect"])

    def test_report_writes_only_injected_output_directory(self) -> None:
        report = evaluate_manifest(MANIFEST_PATH)
        with tempfile.TemporaryDirectory(prefix="phase5r-replay-") as directory:
            output = Path(directory)
            write_report(output, report)
            files = sorted(path.name for path in output.iterdir())
            self.assertEqual(
                files,
                [
                    "phase5r_llm_evaluation_report.json",
                    "phase5r_llm_evaluation_report.md",
                ],
            )
            payload = json.loads(
                (output / "phase5r_llm_evaluation_report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(payload["all_passed"])
            serialized = json.dumps(payload, sort_keys=True)
            self.assertNotIn("SMTP_CANARY_DO_NOT_LEAK", serialized)


if __name__ == "__main__":
    unittest.main()
