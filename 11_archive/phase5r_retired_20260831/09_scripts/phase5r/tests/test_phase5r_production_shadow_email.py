from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import phase5r_production_shadow_v1 as shadow
import send_phase5r_production_shadow_email as shadow_email


TRADING_DAY = "2026-08-04"
RUN_ID = "20260804-123000-aaaaaaaaaaaa"


def _raw(value: dict[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write(path: Path, value: dict[str, object]) -> str:
    raw = _raw(value)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _result(manifest_sha256: str, model_input_sha256: str) -> dict[str, object]:
    return {
        "schema_version": shadow.RESULT_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "trading_day": TRADING_DAY,
        "completed_at_et": "2026-08-04T16:20:00-04:00",
        "outcome": "completed",
        "input_manifest_sha256": manifest_sha256,
        "deterministic_decision_code": "hold_no_new_position",
        "agreement_status": "agree",
        "valuation_status": "unavailable",
        "valuation_actionable": False,
        "valuation_conclusion": "abstain",
        "summary": "The supplied official excerpt supports a bounded revenue observation.",
        "summary_claim_ids": ["claim-a"],
        "claims": [
            {
                "claim_id": "claim-a",
                "ticker": "AAA",
                "claim": "Acme reported revenue.",
                "materiality": "low",
                "source_ids": ["sec-aaa-1"],
            }
        ],
        "citation_assessments": [
            {
                "claim_id": "claim-a",
                "semantic_support": "supported",
                "citation_accuracy": "accurate",
                "period_unit_valid": True,
                "notes": "literal_anchor_and_source_match",
            }
        ],
        "citation_anchors": [
            {
                "claim_id": "claim-a",
                "source_id": "sec-aaa-1",
                "anchor_text": "Acme reported revenue",
            }
        ],
        "positive_findings": [
            {"finding": "Acme reported revenue.", "source_ids": ["sec-aaa-1"]}
        ],
        "negative_findings": [],
        "missing_or_contradictory_evidence": ["valuation_evidence_absent"],
        "contradictory_claim_pairs": [],
        "overclaim_findings": [],
        "confidence_calibration": {
            "confidence_pct": 40,
            "calibration": "low",
            "claim_ids": ["claim-a"],
        },
        "proposed_classification_adjustment": {
            "ticker": "AAA",
            "classification": "hold_existing",
            "claim_ids": ["claim-a"],
        },
        "holding_period_considerations": ["maintain_long_term_research_horizon"],
        "next_review_conditions": ["new_official_filing"],
        "provider": {
            "requested_model": shadow.MODEL,
            "reasoning_effort": shadow.REASONING_EFFORT,
            "store": False,
            "tools_enabled": False,
            "input_payload_canonical_sha256": model_input_sha256,
        },
        "metered_cost_usd": "0.010000",
        "validation": {
            "future_v2_citation_binding_status": "completed",
            "citation_quality": "passed",
            "assertion_span_procedure_status": "completed",
            "span_anchored_count": 1,
            "assertion_count": 1,
            "postcall_span_bundle_raw_sha256": "b" * 64,
            "future_v2_artifact_raw_sha256": {},
            "semantic_truth_established": False,
            "reviewer_independence_established": False,
            "committee_execution_occurred": False,
            "critic_execution_occurred": False,
            "self_assessment_projection": True,
        },
        "canonical_effect": False,
        "independent_human_review_satisfied": False,
        "email_or_scheduler_effect": False,
        "broker_or_account_access": False,
        "order_or_position_effect": False,
        "human_usefulness_status": "awaiting_human_assessment",
    }


class ProductionShadowEmailTests(unittest.TestCase):
    def _artifacts(self, root: Path) -> tuple[Path, Path, Path]:
        reports = root / "reports"
        validations = root / "validations"
        handoffs = root / "handoffs"
        for parent in (reports, validations, handoffs):
            (parent / RUN_ID).mkdir(parents=True)
        model_input = {"schema_version": "fixture", "sources": [], "boundaries": {}}
        model_input_sha = _write(handoffs / RUN_ID / "model_input.json", model_input)
        manifest = {
            "schema_version": shadow.MANIFEST_SCHEMA_VERSION,
            "run_id": RUN_ID,
            "trading_day": TRADING_DAY,
            "status": "validated_offline_pre_provider",
            "artifact_sha256": {"model_input": model_input_sha},
        }
        manifest_sha = _write(handoffs / RUN_ID / "production_shadow_manifest.json", manifest)
        result = _result(manifest_sha, shadow.canonical_sha256(model_input))
        _write(reports / RUN_ID / "production_shadow_result.json", result)
        _write(
            validations / RUN_ID / "production_shadow_validation.json",
            {
                "schema_version": shadow.VALIDATION_SCHEMA_VERSION,
                "run_id": RUN_ID,
                "status": "completed",
                "future_v2_citation_binding_status": "completed",
                "assertion_span_procedure_status": "completed",
                "canonical_effect": False,
                "provider_or_network_used_by_validator": False,
            },
        )
        (reports / RUN_ID / "production_shadow_daily_report.md").write_text(
            shadow._result_markdown(result), encoding="utf-8"
        )
        return reports, validations, handoffs

    def test_check_requires_external_runtime_and_never_reads_legacy_smtp_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            checked = shadow_email.external_runtime_check()
        self.assertFalse(checked["ready"])
        self.assertEqual(checked["reason"], "external_mail_runtime_not_configured")
        source = Path(shadow_email.__file__).read_text(encoding="utf-8")
        self.assertNotIn("smtplib", source)
        self.assertNotIn("phase5r_email_config.local.json", source)

    def test_validated_report_is_sent_once_with_hash_chained_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports, validations, handoffs = self._artifacts(root)
            receipt = root / "ledger" / "email_receipts.jsonl"
            lock = root / "control" / "email.lock"
            exposure = {
                "daily_metered_usd": "0.010000",
                "monthly_metered_usd": "0.010000",
                "daily_reserved_usd": "0.500000",
                "monthly_reserved_usd": "0.500000",
            }
            with (
                patch.object(shadow, "REPORT_ROOT", reports),
                patch.object(shadow, "VALIDATION_ROOT", validations),
                patch.object(shadow, "HANDOFF_ROOT", handoffs),
                patch.object(shadow_email, "RECEIPT_PATH", receipt),
                patch.object(shadow_email, "LOCK_PATH", lock),
                patch.object(shadow_email, "cycle_date", return_value=TRADING_DAY),
                patch.object(shadow, "current_cost_exposure", return_value=exposure),
                patch.object(
                    shadow_email,
                    "external_runtime_check",
                    return_value={
                        "ready": True,
                        "reason": None,
                        "runtime": Path("/private/tmp/phase5r-mail-runtime"),
                        "external_runtime_invoked": True,
                    },
                ),
                patch.object(shadow_email, "_runtime_delivery", return_value=True) as delivery,
            ):
                first = shadow_email.send_run(RUN_ID)
                second = shadow_email.send_run(RUN_ID)
            lines = receipt.read_text(encoding="utf-8").splitlines()
        self.assertEqual(first["outcome"], "sent")
        self.assertEqual(second["outcome"], "deduplicated")
        self.assertEqual(delivery.call_count, 1)
        self.assertEqual([json.loads(line)["event_type"] for line in lines], ["send_claimed", "sent"])
        self.assertNotIn(shadow_email.RECIPIENT, "\n".join(lines))

    def test_report_with_email_or_scheduler_effect_is_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports, validations, handoffs = self._artifacts(root)
            result_path = reports / RUN_ID / "production_shadow_result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["email_or_scheduler_effect"] = True
            _write(result_path, result)
            (reports / RUN_ID / "production_shadow_daily_report.md").write_text(
                shadow._result_markdown(result), encoding="utf-8"
            )
            with (
                patch.object(shadow, "REPORT_ROOT", reports),
                patch.object(shadow, "VALIDATION_ROOT", validations),
                patch.object(shadow, "HANDOFF_ROOT", handoffs),
                patch.object(shadow_email, "cycle_date", return_value=TRADING_DAY),
            ):
                with self.assertRaisesRegex(
                    shadow_email.MailBoundaryError, "shadow_result_not_eligible"
                ):
                    shadow_email._validated_report(RUN_ID)


if __name__ == "__main__":
    unittest.main()
