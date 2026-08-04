from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import phase5r_llm_evidence_contract_v2_handoff as handoff_module
from phase5r_llm_evidence_contract_v2 import EVIDENCE_METADATA_V2_SCHEMA_VERSION
from phase5r_llm_evidence_contract_v2_handoff import (
    FUTURE_V2_HANDOFF_SCHEMA_VERSION,
    FUTURE_V2_OWNER_APPROVAL_REFERENCE_SCHEMA_VERSION,
    RAW_BYTES_HASH_RULE,
    EvidenceContractV2HandoffError,
    verify_future_v2_handoff,
)
from test_phase5r_llm_evidence_contract_v2 import (
    _analyst_bindings,
    _analyst_response,
    _committee_response,
    _committee_ticker_decisions,
    _critic_coverage,
    _metadata,
    _packet,
    _source_texts,
)


_ARTIFACT_NAMES = (
    "packet",
    "source_texts",
    "analyst_response",
    "metadata",
    "analyst_bindings",
    "committee_response",
    "committee_ticker_decisions",
    "critic_coverage",
)
_FILENAMES = {
    "manifest": "future_v2_handoff_manifest.json",
    "packet": "packet.json",
    "source_texts": "evidence_source_texts_v2.json",
    "analyst_response": "analyst_response.json",
    "metadata": "evidence_metadata_v2.json",
    "analyst_bindings": "analyst_evidence_bindings_v2.json",
    "committee_response": "committee_response.json",
    "committee_ticker_decisions": "committee_ticker_decisions.json",
    "critic_coverage": "critic_coverage_v2.json",
}


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )


class EvidenceContractV2HandoffTests(unittest.TestCase):
    def _paths(self, root: Path) -> dict[str, Path]:
        return {label: root / filename for label, filename in _FILENAMES.items()}

    def _manifest(self, paths: dict[str, Path]) -> dict:
        return {
            "schema_version": FUTURE_V2_HANDOFF_SCHEMA_VERSION,
            "status": "validated_offline_noncanonical",
            "hash_rule": RAW_BYTES_HASH_RULE,
            "packet_id": _packet()["packet_id"],
            "artifact_sha256": {
                label: _raw_sha256(paths[label]) for label in _ARTIFACT_NAMES
            },
            "metadata_provenance": {
                "attested_method": "deterministic_curation",
                "attested_packet_local_excerpt_only": True,
                "attested_external_evidence_used": False,
                "attested_independent_human_review_satisfied": False,
                "attested_repository_initiated_provider_call_made": False,
            },
            "generation_provenance": {
                "generation_mode": "synthetic",
                "repository_initiated_provider_call_made": False,
                "repository_initiated_provider_call_authorized": False,
                "external_evidence_used": False,
                "tools_or_browse_used": False,
                "interactive_ai_session": None,
                "independence_status": "not_established",
            },
            "review_status": {
                "human_review_status": "not_performed",
                "counts_toward_original_human_review_requirement": False,
                "reviewer_independence_status": "not_established",
            },
            "boundaries": {
                "execution_prohibited": True,
                "provider_use_authorized": False,
                "network_use_authorized": False,
                "canonical_effect_authorized": False,
                "automatic_action_authorized": False,
                "broker_use_authorized": False,
                "email_effect_authorized": False,
                "blind_key_access_authorized": False,
                "unblinding_authorized": False,
            },
        }

    def _write_fixture(self, root: Path) -> tuple[dict[str, object], dict[str, Path]]:
        artifacts: dict[str, object] = {
            "packet": _packet(),
            "source_texts": _source_texts(),
            "analyst_response": _analyst_response(),
            "metadata": _metadata(),
            "analyst_bindings": _analyst_bindings(),
            "committee_response": _committee_response(),
            "committee_ticker_decisions": _committee_ticker_decisions(),
            "critic_coverage": _critic_coverage(),
        }
        paths = self._paths(root)
        for label, value in artifacts.items():
            _write_json(paths[label], value)
        _write_json(paths["manifest"], self._manifest(paths))
        return artifacts, paths

    def _rewrite_manifest(self, paths: dict[str, Path], manifest: dict) -> str:
        _write_json(paths["manifest"], manifest)
        return _raw_sha256(paths["manifest"])

    def _owner_approval_reference(self, manifest_sha256: str) -> dict:
        return {
            "schema_version": FUTURE_V2_OWNER_APPROVAL_REFERENCE_SCHEMA_VERSION,
            "record_type": "project_owner_noncanonical_internal_quality_approval",
            "policy_owner": "Synthetic Test Owner",
            "authority": "project_owner",
            "decision": "approved_noncanonical_internal_quality_only",
            "scope": "future_v2_noncanonical_internal_quality_only",
            "effective_at_et": "2026-08-03T12:00:00-04:00",
            "manifest_sha256": manifest_sha256,
            "packet_id": _packet()["packet_id"],
            "human_review_requirement_waived": False,
            "independent_human_review_satisfied": False,
            "canonical_authority_created": False,
            "blind_key_access_authorized": False,
            "unblinding_authorized": False,
            "repository_provider_call_authorized": False,
            "runtime_execution_authorized": False,
            "automatic_action_authorized": False,
            "broker_access_authorized": False,
            "email_effect_authorized": False,
            "revocation_authority": "project_owner",
        }

    def _verify(self, root: Path, expected_manifest_sha256: str) -> dict:
        return verify_future_v2_handoff(
            handoff_root=root,
            owner_approval_reference=self._owner_approval_reference(
                expected_manifest_sha256
            ),
        )

    def test_valid_raw_byte_frozen_handoff_is_scoped_to_integrity_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            result = self._verify(root, _raw_sha256(paths["manifest"]))

        self.assertEqual(result["procedure_status"], "completed")
        self.assertEqual(
            result["integrity_status"], "raw_bytes_and_contract_bindings_validated"
        )
        self.assertTrue(result["sidecar_integrity_validated"])
        self.assertEqual(result["substantive_status"], "not_established")
        self.assertEqual(
            result["normalized_metadata_status"],
            "hash_bound_but_not_semantically_verified",
        )
        self.assertEqual(result["substantive_recommendation"], "not_established")
        self.assertEqual(
            result["authority_status"], "noncanonical_internal_quality_only"
        )
        self.assertEqual(
            result["generation_provenance_status"], "attested_not_verified"
        )
        self.assertFalse(result["repository_initiated_provider_call_made_attested"])
        self.assertFalse(result["repository_initiated_provider_call_made_verified"])
        self.assertTrue(result["owner_approval_reference_schema_validated"])
        self.assertFalse(result["owner_identity_or_signature_verified"])
        self.assertEqual(result["human_review_status"], "not_performed")
        self.assertEqual(result["hash_rule"], RAW_BYTES_HASH_RULE)
        self.assertTrue(result["execution_prohibited"])
        for field in (
            "upstream_validation_verified",
            "semantic_validation_established",
            "numeric_reconciliation_established",
            "reviewer_independence_established",
            "verifier_provider_constructed",
            "verifier_network_used",
            "canonical_effect_authorized",
            "automatic_action_authorized",
            "broker_use_authorized",
            "email_effect_authorized",
            "blind_key_access_authorized",
            "unblinding_authorized",
            "independent_human_review_satisfied",
        ):
            self.assertFalse(result[field])

    def test_handoff_verification_does_not_mutate_any_input_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            before = {label: path.read_bytes() for label, path in paths.items()}
            result = self._verify(root, _raw_sha256(paths["manifest"]))
            after = {label: path.read_bytes() for label, path in paths.items()}

        self.assertTrue(result["sidecar_integrity_validated"])
        self.assertEqual(after, before)

    def test_raw_byte_change_is_rejected_even_when_json_still_parses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            paths["metadata"].write_bytes(paths["metadata"].read_bytes() + b" ")

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "raw artifact hash mismatch for metadata",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_cr_line_endings_before_json_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            paths["metadata"].write_bytes(
                paths["metadata"].read_bytes().replace(b"\n", b"\r\n")
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "metadata: text must be UTF-8 without BOM and LF-only",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_duplicate_json_keys_before_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            raw_metadata = paths["metadata"].read_text(encoding="utf-8")
            schema_line = (
                f'  "schema_version": "{EVIDENCE_METADATA_V2_SCHEMA_VERSION}",\n'
            )
            self.assertIn(schema_line, raw_metadata)
            paths["metadata"].write_text(
                raw_metadata.replace(schema_line, schema_line + schema_line, 1),
                encoding="utf-8",
                newline="\n",
            )
            expected_manifest_sha256 = self._rewrite_manifest(
                paths, self._manifest(paths)
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "metadata: expected strict UTF-8 JSON",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_nonstandard_json_constants_before_schema_validation(
        self,
    ) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                _, paths = self._write_fixture(root)
                raw_metadata = paths["metadata"].read_text(encoding="utf-8")
                packet_line = '  "packet_id": "packet-evidence-contract-v2",\n'
                self.assertIn(packet_line, raw_metadata)
                paths["metadata"].write_text(
                    raw_metadata.replace(
                        packet_line,
                        packet_line + f'  "synthetic_nonstandard": {constant},\n',
                        1,
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
                expected_manifest_sha256 = self._rewrite_manifest(
                    paths, self._manifest(paths)
                )

                with self.assertRaisesRegex(
                    EvidenceContractV2HandoffError,
                    "metadata: expected strict UTF-8 JSON",
                ):
                    self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_json_escaped_unpaired_unicode_surrogate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            raw_metadata = paths["metadata"].read_bytes()
            packet_line = b'  "packet_id": "packet-evidence-contract-v2",\n'
            self.assertIn(packet_line, raw_metadata)
            paths["metadata"].write_bytes(
                raw_metadata.replace(
                    packet_line,
                    packet_line + b'  "synthetic_unpaired": "\\ud800",\n',
                    1,
                )
            )
            expected_manifest_sha256 = self._rewrite_manifest(
                paths, self._manifest(paths)
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "metadata: expected strict UTF-8 JSON",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_json_exponent_overflow_before_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            raw_metadata = paths["metadata"].read_text(encoding="utf-8")
            packet_line = '  "packet_id": "packet-evidence-contract-v2",\n'
            self.assertIn(packet_line, raw_metadata)
            paths["metadata"].write_text(
                raw_metadata.replace(
                    packet_line,
                    packet_line + '  "synthetic_overflow": 1e1000000,\n',
                    1,
                ),
                encoding="utf-8",
                newline="\n",
            )
            expected_manifest_sha256 = self._rewrite_manifest(
                paths, self._manifest(paths)
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "metadata: expected strict UTF-8 JSON",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_json_float_underflow_and_non_roundtripping_values_before_schema_validation(
        self,
    ) -> None:
        for field_name, numeric_literal in (
            ("synthetic_underflow", "1e-1000000"),
            ("synthetic_negative_underflow", "-1e-1000000"),
            ("synthetic_precision_loss", "1.00000000000000001"),
            (
                "synthetic_non_roundtripping",
                "0.1000000000000000055511151231257827021181583404541015625",
            ),
            ("synthetic_excessive_zero_exponent", "0e1000000"),
            ("synthetic_folded_zero_exponent", "0.0e4097"),
            ("synthetic_negative_folded_zero_exponent", "-0.00e4098"),
            (
                "synthetic_zero_digit_padding",
                "0." + ("0" * (handoff_module._MAX_JSON_NUMBER_DIGITS + 1)) + "e1025",
            ),
        ):
            with self.subTest(numeric_literal=numeric_literal), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                _, paths = self._write_fixture(root)
                raw_metadata = paths["metadata"].read_text(encoding="utf-8")
                packet_line = '  "packet_id": "packet-evidence-contract-v2",\n'
                self.assertIn(packet_line, raw_metadata)
                paths["metadata"].write_text(
                    raw_metadata.replace(
                        packet_line,
                        packet_line
                        + f'  "{field_name}": {numeric_literal},\n',
                        1,
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
                expected_manifest_sha256 = self._rewrite_manifest(
                    paths, self._manifest(paths)
                )

                with self.assertRaisesRegex(
                    EvidenceContractV2HandoffError,
                    "metadata: expected strict UTF-8 JSON",
                ):
                    self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_excessively_long_json_integer_before_schema_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            raw_metadata = paths["metadata"].read_text(encoding="utf-8")
            packet_line = '  "packet_id": "packet-evidence-contract-v2",\n'
            self.assertIn(packet_line, raw_metadata)
            paths["metadata"].write_text(
                raw_metadata.replace(
                    packet_line,
                    packet_line
                    + '  "synthetic_long_integer": '
                    + ("9" * (handoff_module._MAX_JSON_NUMBER_DIGITS + 1))
                    + ",\n",
                    1,
                ),
                encoding="utf-8",
                newline="\n",
            )
            expected_manifest_sha256 = self._rewrite_manifest(
                paths, self._manifest(paths)
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "metadata: expected strict UTF-8 JSON",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_strict_json_float_policy_allows_shortest_decimal_roundtrips(self) -> None:
        self.assertEqual(handoff_module._strict_json_float("0.1"), 0.1)
        self.assertEqual(handoff_module._strict_json_float("5e-324"), 5e-324)

    def test_handoff_rejects_excessive_json_nesting_before_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            depth = handoff_module._MAX_JSON_NESTING_DEPTH + 1
            paths["metadata"].write_bytes(
                (b'{"nested":' * depth) + b"0" + (b"}" * depth) + b"\n"
            )
            expected_manifest_sha256 = self._rewrite_manifest(
                paths, self._manifest(paths)
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "metadata: expected strict UTF-8 JSON",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_manifest_requires_an_external_owner_approval_hash_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            manifest = self._manifest(paths)
            manifest["status"] = "invalidated"
            self._rewrite_manifest(paths, manifest)

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "manifest raw-byte hash mismatch",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_owner_approval_reference_cannot_grant_any_prohibited_authority(self) -> None:
        fields = (
            "human_review_requirement_waived",
            "independent_human_review_satisfied",
            "canonical_authority_created",
            "blind_key_access_authorized",
            "unblinding_authorized",
            "repository_provider_call_authorized",
            "runtime_execution_authorized",
            "automatic_action_authorized",
            "broker_access_authorized",
            "email_effect_authorized",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            for field in fields:
                with self.subTest(field=field):
                    approval = self._owner_approval_reference(
                        _raw_sha256(paths["manifest"])
                    )
                    approval[field] = True
                    with self.assertRaisesRegex(
                        EvidenceContractV2HandoffError,
                        f"{field}: must be False",
                    ):
                        verify_future_v2_handoff(
                            handoff_root=root,
                            owner_approval_reference=approval,
                        )

    def test_owner_reference_is_snapshotted_before_handoff_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            approval = self._owner_approval_reference("0" * 64)
            original_open_handoff_root = handoff_module._open_handoff_root

            def open_then_mutate_reference(handoff_root: Path) -> int:
                approval["manifest_sha256"] = expected_manifest_sha256
                return original_open_handoff_root(handoff_root)

            with patch.object(
                handoff_module,
                "_open_handoff_root",
                side_effect=open_then_mutate_reference,
            ):
                with self.assertRaisesRegex(
                    EvidenceContractV2HandoffError,
                    "manifest raw-byte hash mismatch",
                ):
                    verify_future_v2_handoff(
                        handoff_root=root,
                        owner_approval_reference=approval,
                    )

    def test_owner_reference_effective_at_et_requires_eastern_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            approval = self._owner_approval_reference(_raw_sha256(paths["manifest"]))
            approval["effective_at_et"] = "2026-08-03T16:00:00+00:00"

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "effective_at_et: must use America/New_York offset",
            ):
                verify_future_v2_handoff(
                    handoff_root=root,
                    owner_approval_reference=approval,
                )

    def test_owner_reference_fails_closed_when_eastern_timezone_data_is_unavailable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            approval = self._owner_approval_reference(_raw_sha256(paths["manifest"]))
            with patch.object(
                handoff_module,
                "ZoneInfo",
                side_effect=handoff_module.ZoneInfoNotFoundError("missing"),
            ):
                with self.assertRaisesRegex(
                    EvidenceContractV2HandoffError,
                    "America/New_York timezone data unavailable",
                ):
                    verify_future_v2_handoff(
                        handoff_root=root,
                        owner_approval_reference=approval,
                    )

    def test_invalid_owner_reference_is_rejected_before_handoff_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            approval = self._owner_approval_reference(_raw_sha256(paths["manifest"]))
            approval["canonical_authority_created"] = True
            with patch.object(
                handoff_module.os,
                "open",
                wraps=handoff_module.os.open,
            ) as open_mock:
                with self.assertRaisesRegex(
                    EvidenceContractV2HandoffError,
                    "canonical_authority_created: must be False",
                ):
                    verify_future_v2_handoff(
                        handoff_root=root,
                        owner_approval_reference=approval,
                    )

        self.assertEqual(open_mock.call_count, 0)

    def test_owner_packet_mismatch_is_rejected_before_artifact_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            approval = self._owner_approval_reference(_raw_sha256(paths["manifest"]))
            approval["packet_id"] = "different-packet"
            with patch.object(
                handoff_module.os,
                "open",
                wraps=handoff_module.os.open,
            ) as open_mock:
                with self.assertRaisesRegex(
                    EvidenceContractV2HandoffError,
                    "approval reference packet_id mismatch",
                ):
                    verify_future_v2_handoff(
                        handoff_root=root,
                        owner_approval_reference=approval,
                    )

        self.assertEqual(
            [call.args[0] for call in open_mock.call_args_list],
            [root, _FILENAMES["manifest"]],
        )

    def test_unblinding_is_rejected_by_the_manifest_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            manifest = self._manifest(paths)
            manifest["boundaries"]["unblinding_authorized"] = True
            expected_manifest_sha256 = self._rewrite_manifest(paths, manifest)

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "unblinding_authorized: must be False",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_all_sensitive_authorization_flags_fail_closed(self) -> None:
        fields = (
            "provider_use_authorized",
            "network_use_authorized",
            "canonical_effect_authorized",
            "automatic_action_authorized",
            "broker_use_authorized",
            "email_effect_authorized",
            "blind_key_access_authorized",
            "unblinding_authorized",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            for field in fields:
                with self.subTest(field=field):
                    manifest = self._manifest(paths)
                    manifest["boundaries"][field] = True
                    expected_manifest_sha256 = self._rewrite_manifest(paths, manifest)
                    with self.assertRaisesRegex(
                        EvidenceContractV2HandoffError,
                        f"{field}: must be False",
                    ):
                        self._verify(root, expected_manifest_sha256)

    def test_interactive_ai_provenance_requires_disclosure_and_nonindependence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            manifest = self._manifest(paths)
            manifest["generation_provenance"]["generation_mode"] = "interactive_ai_session"
            expected_manifest_sha256 = self._rewrite_manifest(paths, manifest)

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "interactive_ai_session: expected object",
            ):
                self._verify(root, expected_manifest_sha256)

            manifest = self._manifest(paths)
            manifest["generation_provenance"] = {
                "generation_mode": "interactive_ai_session",
                "repository_initiated_provider_call_made": False,
                "repository_initiated_provider_call_authorized": False,
                "external_evidence_used": False,
                "tools_or_browse_used": False,
                "interactive_ai_session": {
                    "provider": "test-provider",
                    "model_family": "test-family",
                    "review_date": "2026-08-03T12:00:00-04:00",
                    "reasoning_configuration": "test-disclosure",
                },
                "independence_status": "presumed_non_independent",
            }
            expected_manifest_sha256 = self._rewrite_manifest(paths, manifest)
            result = self._verify(root, expected_manifest_sha256)

        self.assertEqual(result["generation_mode"], "interactive_ai_session")
        self.assertTrue(result["interactive_ai_session_disclosure_validated"])
        self.assertEqual(
            result["reviewer_independence_status"], "presumed_non_independent"
        )
        self.assertFalse(result["reviewer_independence_status_verified"])

    def test_unknown_generation_provenance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            manifest = self._manifest(paths)
            manifest["generation_provenance"]["generation_mode"] = "unknown"
            expected_manifest_sha256 = self._rewrite_manifest(paths, manifest)

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError, "invalid generation_mode"
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_a_symlinked_fixed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            root = parent / "handoff"
            root.mkdir()
            _, paths = self._write_fixture(root)
            outside = parent / "outside.json"
            _write_json(outside, _packet())
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            paths["packet"].unlink()
            paths["packet"].symlink_to(outside)

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "packet: expected regular file",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_a_hard_linked_fixed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            root = parent / "handoff"
            root.mkdir()
            _, paths = self._write_fixture(root)
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            outside_packet = parent / "outside-packet.json"
            outside_packet.write_bytes(paths["packet"].read_bytes())
            paths["packet"].unlink()
            os.link(outside_packet, paths["packet"])

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "packet: hard-linked artifacts are prohibited",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_a_fifo_without_blocking(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo is unavailable on this platform")
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            root = parent / "handoff"
            root.mkdir()
            _, paths = self._write_fixture(root)
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            paths["packet"].unlink()
            os.mkfifo(paths["packet"])

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError, "packet: expected regular file"
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_an_oversized_artifact_before_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            with patch.object(handoff_module, "_MAX_ARTIFACT_BYTES", 4096):
                paths["metadata"].write_bytes(b" " * 4097)
                expected_manifest_sha256 = self._rewrite_manifest(
                    paths, self._manifest(paths)
                )

                with self.assertRaisesRegex(
                    EvidenceContractV2HandoffError,
                    "metadata: artifact exceeds maximum byte size",
                ):
                    self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_a_symlinked_root_or_missing_fixed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            root = parent / "handoff"
            root.mkdir()
            _, paths = self._write_fixture(root)
            root_link = parent / "handoff-link"
            root_link.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "handoff_root: expected regular directory",
            ):
                self._verify(root_link, _raw_sha256(paths["manifest"]))

            paths["source_texts"].unlink()
            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "source_texts: expected regular file",
            ):
                self._verify(root, _raw_sha256(paths["manifest"]))

            _, paths = self._write_fixture(root)
            paths["source_texts"].unlink()
            paths["source_texts"].mkdir()
            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "source_texts: expected regular file",
            ):
                self._verify(root, _raw_sha256(paths["manifest"]))

    def test_handoff_opens_only_fixed_artifacts_and_not_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, paths = self._write_fixture(root)
            bait = root / "unrelated_bait.json"
            _write_json(bait, {"not": "a handoff artifact"})
            with patch.object(handoff_module.os, "open", wraps=handoff_module.os.open) as open_mock:
                result = self._verify(root, _raw_sha256(paths["manifest"]))

        self.assertTrue(result["sidecar_integrity_validated"])
        opened_targets = [call.args[0] for call in open_mock.call_args_list]
        self.assertEqual(opened_targets[0], root)
        self.assertEqual(
            {str(target) for target in opened_targets[1:]}, set(_FILENAMES.values())
        )
        self.assertNotIn(bait.name, {str(target) for target in opened_targets[1:]})
        for call in open_mock.call_args_list[1:]:
            self.assertIn("dir_fd", call.kwargs)

    def test_opened_root_descriptor_resists_path_replacement_before_artifact_reads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            root = parent / "handoff"
            root.mkdir()
            _, paths = self._write_fixture(root)
            expected_manifest_sha256 = _raw_sha256(paths["manifest"])
            replacement = parent / "replacement"
            replacement.mkdir()
            preserved_root = parent / "preserved-root"
            original_open = handoff_module.os.open
            switched = False

            def open_then_replace_root(path: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal switched
                descriptor = original_open(path, flags, *args, **kwargs)
                if path == root and "dir_fd" not in kwargs and not switched:
                    root.rename(preserved_root)
                    root.symlink_to(replacement, target_is_directory=True)
                    switched = True
                return descriptor

            with patch.object(
                handoff_module.os,
                "open",
                side_effect=open_then_replace_root,
            ):
                result = self._verify(root, expected_manifest_sha256)

        self.assertTrue(switched)
        self.assertTrue(result["sidecar_integrity_validated"])

    def test_handoff_runs_the_linked_sidecar_validator_after_hash_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts, paths = self._write_fixture(root)
            invalid_bindings = copy.deepcopy(artifacts["analyst_bindings"])
            invalid_bindings["canonical_effect"] = True
            _write_json(paths["analyst_bindings"], invalid_bindings)
            expected_manifest_sha256 = self._rewrite_manifest(
                paths, self._manifest(paths)
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "sidecar validation failed: analyst_evidence_bindings_v2: canonical_effect",
            ):
                self._verify(root, expected_manifest_sha256)

    def test_handoff_rejects_a_rehashed_committee_response_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts, paths = self._write_fixture(root)
            substituted_committee = copy.deepcopy(artifacts["committee_response"])
            substituted_committee["ticker_decisions"][0]["rationale"] = "Substituted."
            _write_json(paths["committee_response"], substituted_committee)
            expected_manifest_sha256 = self._rewrite_manifest(
                paths, self._manifest(paths)
            )

            with self.assertRaisesRegex(
                EvidenceContractV2HandoffError,
                "sidecar validation failed: committee_ticker_decisions_v2: committee response hash mismatch",
            ):
                self._verify(root, expected_manifest_sha256)


if __name__ == "__main__":
    unittest.main()
