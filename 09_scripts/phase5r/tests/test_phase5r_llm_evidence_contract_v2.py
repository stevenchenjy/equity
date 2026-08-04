from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import unittest

from _support import materialized
from phase5r_llm_contract import (
    ContractError,
    validate_analyst,
    validate_committee,
    validate_critic,
    validate_packet,
)
from phase5r_llm_evidence_contract_v2 import (
    ANALYST_EVIDENCE_BINDINGS_V2_SCHEMA_VERSION,
    COMMITTEE_TICKER_DECISIONS_V2_SCHEMA_VERSION,
    CRITIC_COVERAGE_V2_SCHEMA_VERSION,
    EVIDENCE_METADATA_V2_SCHEMA_VERSION,
    EVIDENCE_SOURCE_TEXTS_V2_SCHEMA_VERSION,
    EvidenceContractV2Error,
    _committee_claims_by_ticker,
    evaluate_critic_incremental_value_v2,
    validate_analyst_evidence_bindings_v2,
    validate_critic_coverage_v2,
    validate_evidence_metadata_v2,
)


_SIDECAR_IMPORT_ALLOWLISTS = {
    "phase5r_llm_internal_quality.py": {"re", "typing"},
    "phase5r_llm_evidence_contract_v2.py": {
        "datetime",
        "hashlib",
        "json",
        "re",
        "typing",
        "phase5r_llm_internal_quality",
    },
    "phase5r_llm_evidence_contract_v2_handoff.py": {
        "datetime",
        "decimal",
        "hashlib",
        "json",
        "math",
        "os",
        "pathlib",
        "stat",
        "typing",
        "zoneinfo",
        "phase5r_llm_evidence_contract_v2",
    },
    "phase5r_assertion_span_contract_v3.py": {
        "hashlib",
        "re",
        "typing",
        "unicodedata",
    },
}
_FORBIDDEN_SIDECAR_IMPORT_ROOTS = {
    "http",
    "requests",
    "socket",
    "ssl",
    "subprocess",
    "urllib",
    "phase5r_llm_provider",
    "run_phase5r_model_pilot",
    "run_phase5r_model_pilot_v2",
    "run_phase5r_model_pilot_v3",
    "run_phase5r_model_pilot_v4",
    "run_phase5r_model_pilot_v5",
    "run_phase5r_model_pilot_v6",
    "run_phase5r_model_pilot_v7",
    "run_phase5r_model_pilot_v8_qualification",
    "run_phase5r_model_pilot_v9",
    "run_phase5r_model_pilot_v10",
}


def _source_import_roots_and_dynamic_imports(
    source_path: Path,
) -> tuple[set[str], list[ast.Call]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    dynamic_imports: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "__import__":
                dynamic_imports.append(node)
    imported_roots.discard("__future__")
    return imported_roots, dynamic_imports


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _current_period() -> dict[str, str]:
    return {
        "kind": "range",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
    }


def _baseline_period() -> dict[str, str]:
    return {
        "kind": "range",
        "start_date": "2025-01-01",
        "end_date": "2025-06-30",
    }


def _packet() -> dict:
    return {
        "packet_id": "packet-evidence-contract-v2",
        "source_catalog": [
            {
                "source_id": "S-current",
                "ticker": "TST",
                "content_sha256": _digest("Current operating margin excerpt."),
            },
            {
                "source_id": "S-baseline",
                "ticker": "TST",
                "content_sha256": _digest("Baseline operating margin excerpt."),
            },
            {
                "source_id": "S-scope",
                "ticker": "TST",
                "content_sha256": _digest("Customer concentration excerpt."),
            },
        ],
        "calculations": [
            {
                "calculation_id": "C-current",
                "ticker": "TST",
                "unit": "percentage of revenue",
                "period": "six months ended 2026-06-30",
            },
            {
                "calculation_id": "C-baseline",
                "ticker": "TST",
                "unit": "percentage of revenue",
                "period": "six months ended 2025-06-30",
            },
        ],
    }


def _source_texts() -> dict:
    return {
        "schema_version": EVIDENCE_SOURCE_TEXTS_V2_SCHEMA_VERSION,
        "packet_id": "packet-evidence-contract-v2",
        "sources": [
            {
                "source_id": "S-current",
                "excerpt_text": "Current operating margin excerpt.",
            },
            {
                "source_id": "S-baseline",
                "excerpt_text": "Baseline operating margin excerpt.",
            },
            {
                "source_id": "S-scope",
                "excerpt_text": "Customer concentration excerpt.",
            },
        ],
    }


def _metadata() -> dict:
    packet = _packet()
    source_hashes = {
        row["source_id"]: row["content_sha256"]
        for row in packet["source_catalog"]
    }
    return {
        "schema_version": EVIDENCE_METADATA_V2_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "source_texts_canonical_json_sha256": _canonical_digest(_source_texts()),
        "sources": [
            {
                "source_id": "S-current",
                "ticker": "TST",
                "content_sha256": source_hashes["S-current"],
                "metric_label": "operating_margin",
                "unit": "percent_of_revenue",
                "period": _current_period(),
                "supported_roles": ["claim", "period", "unit"],
            },
            {
                "source_id": "S-baseline",
                "ticker": "TST",
                "content_sha256": source_hashes["S-baseline"],
                "metric_label": "operating_margin",
                "unit": "percent_of_revenue",
                "period": _baseline_period(),
                "supported_roles": ["comparison_baseline"],
            },
            {
                "source_id": "S-scope",
                "ticker": "TST",
                "content_sha256": source_hashes["S-scope"],
                "metric_label": "customer_concentration",
                "unit": "percent_of_revenue",
                "period": _current_period(),
                "supported_roles": ["claim", "period", "unit", "entity_scope"],
            },
        ],
        "calculations": [
            {
                "calculation_id": "C-current",
                "ticker": "TST",
                "packet_unit": "percentage of revenue",
                "packet_period": "six months ended 2026-06-30",
                "metric_label": "operating_margin",
                "unit": "percent_of_revenue",
                "period": _current_period(),
            },
            {
                "calculation_id": "C-baseline",
                "ticker": "TST",
                "packet_unit": "percentage of revenue",
                "packet_period": "six months ended 2025-06-30",
                "metric_label": "operating_margin",
                "unit": "percent_of_revenue",
                "period": _baseline_period(),
            },
        ],
    }


def _analyst_bindings() -> dict:
    metadata = _metadata()
    analyst_response = _analyst_response()
    hashes = {row["source_id"]: row["content_sha256"] for row in metadata["sources"]}
    return {
        "schema_version": ANALYST_EVIDENCE_BINDINGS_V2_SCHEMA_VERSION,
        "packet_id": "packet-evidence-contract-v2",
        "analyst_response_sha256": _canonical_digest(analyst_response),
        "canonical_effect": False,
        "claims": [
            {
                "claim_id": "claim-margin",
                "analyst_claim_sha256": _canonical_digest(analyst_response["claims"][0]),
                "ticker": "TST",
                "materiality": "high",
                "metric_label": "operating_margin",
                "unit": "percent_of_revenue",
                "period": _current_period(),
                "claim_characteristics": ["quantitative", "comparative"],
                "lexical_scope_flags": [
                    "comparative_direction_requires_baseline_check",
                    "period_binding_not_visible_in_excerpt",
                ],
                "citation_bindings": [
                    {
                        "source_id": "S-current",
                        "cited_excerpt_sha256": hashes["S-current"],
                        "support_roles": ["claim", "period", "unit"],
                    },
                    {
                        "source_id": "S-baseline",
                        "cited_excerpt_sha256": hashes["S-baseline"],
                        "support_roles": ["comparison_baseline"],
                    },
                ],
                "evidence_period": {
                    "value": _current_period(),
                    "source_ids": ["S-current"],
                },
                "evidence_unit": {
                    "value": "percent_of_revenue",
                    "source_ids": ["S-current"],
                },
                "comparison_baseline": {
                    "metric_label": "operating_margin",
                    "unit": "percent_of_revenue",
                    "period": _baseline_period(),
                    "relationship": "same_period_prior_year",
                    "source_ids": ["S-baseline"],
                },
                "calculation_ids": ["C-current"],
            }
        ],
    }


def _analyst_response() -> dict:
    metadata = _metadata()
    hashes = {row["source_id"]: row["content_sha256"] for row in metadata["sources"]}
    return {
        "packet_id": "packet-evidence-contract-v2",
        "claims": [
            {
                "claim_id": "claim-margin",
                "ticker": "TST",
                "claim": "Operating margin improved relative to the prior year.",
                "materiality": "high",
                "source_ids": ["S-current", "S-baseline"],
                "cited_excerpt_sha256": [
                    hashes["S-current"],
                    hashes["S-baseline"],
                ],
                "calculation_ids": ["C-current"],
            }
        ],
    }


def _validate_analyst_bindings(analyst: dict, *, analyst_response: dict | None = None) -> dict:
    return validate_analyst_evidence_bindings_v2(
        _packet(),
        _metadata(),
        analyst,
        source_texts=_source_texts(),
        analyst_response=_analyst_response() if analyst_response is None else analyst_response,
    )


def _validate_critic(analyst: dict, critic: dict) -> dict:
    return validate_critic_coverage_v2(
        packet=_packet(),
        metadata=_metadata(),
        source_texts=_source_texts(),
        analyst_response=_analyst_response(),
        analyst_bindings=analyst,
        committee_response=_committee_response(),
        committee_ticker_decisions=_committee_ticker_decisions(),
        response=critic,
    )


def _committee_response() -> dict:
    return {
        "packet_id": "packet-evidence-contract-v2",
        "ticker_decisions": [
            {
                "ticker": "TST",
                "claim_ids": ["claim-margin"],
                "rationale": "Synthetic future-v2 committee fixture.",
            }
        ],
    }


def _committee_ticker_decisions() -> dict:
    committee_response = _committee_response()
    decision = committee_response["ticker_decisions"][0]
    return {
        "schema_version": COMMITTEE_TICKER_DECISIONS_V2_SCHEMA_VERSION,
        "packet_id": "packet-evidence-contract-v2",
        "committee_response_sha256": _canonical_digest(committee_response),
        "canonical_effect": False,
        "decisions": [
            {
                "ticker": "TST",
                "claim_ids": ["claim-margin"],
                "committee_decision_sha256": _canonical_digest(decision),
            }
        ],
    }


def _critic_coverage() -> dict:
    return {
        "schema_version": CRITIC_COVERAGE_V2_SCHEMA_VERSION,
        "packet_id": "packet-evidence-contract-v2",
        "canonical_effect": False,
        "ticker_reviews": [
            {
                "ticker": "TST",
                "verdict": "revise",
                "reviewed_claim_ids": ["claim-margin"],
                "factual_grounding_pass": True,
                "citation_integrity_pass": False,
                "numeric_reconciliation_pass": True,
                "long_term_reasoning_pass": True,
                "action_proportionality_pass": True,
                "policy_boundary_pass": True,
                "issues": [
                    {
                        "issue_id": "issue-period",
                        "issue_type": "period_binding",
                        "severity": "high",
                        "material": True,
                        "issue": "The stated period must be reconciled to the cited excerpt.",
                        "affected_claim_ids": ["claim-margin"],
                        "source_ids": ["S-current"],
                    },
                    {
                        "issue_id": "issue-comparison-baseline",
                        "issue_type": "comparison_baseline",
                        "severity": "high",
                        "material": True,
                        "issue": "The comparison baseline requires cited validation.",
                        "affected_claim_ids": ["claim-margin"],
                        "source_ids": ["S-baseline"],
                    }
                ],
            }
        ],
    }


class EvidenceContractV2Tests(unittest.TestCase):
    def test_future_sidecars_have_only_allowlisted_offline_imports(self) -> None:
        sidecar_directory = Path(__file__).resolve().parents[1]

        for filename, allowlist in _SIDECAR_IMPORT_ALLOWLISTS.items():
            with self.subTest(filename=filename):
                imported_roots, dynamic_imports = _source_import_roots_and_dynamic_imports(
                    sidecar_directory / filename
                )
                self.assertFalse(dynamic_imports)
                self.assertTrue(imported_roots <= allowlist)
                self.assertFalse(imported_roots & _FORBIDDEN_SIDECAR_IMPORT_ROOTS)

    def _validated_analyst(self) -> dict:
        packet = _packet()
        metadata = _metadata()
        analyst = _analyst_bindings()
        self.assertIs(
            validate_evidence_metadata_v2(
                packet, metadata, source_texts=_source_texts()
            ),
            metadata,
        )
        self.assertIs(
            validate_analyst_evidence_bindings_v2(
                packet,
                metadata,
                analyst,
                source_texts=_source_texts(),
                analyst_response=_analyst_response(),
            ),
            analyst,
        )
        return analyst

    def test_valid_metadata_and_comparative_claim_bindings_pass(self) -> None:
        self._validated_analyst()

    def test_metadata_requires_exact_packet_source_coverage(self) -> None:
        metadata = _metadata()
        metadata["sources"].pop()
        with self.assertRaisesRegex(EvidenceContractV2Error, "exactly cover"):
            validate_evidence_metadata_v2(
                _packet(), metadata, source_texts=_source_texts()
            )

    def test_metadata_rejects_source_hash_rebinding(self) -> None:
        metadata = _metadata()
        metadata["sources"][0]["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(EvidenceContractV2Error, "excerpt hash mismatch"):
            validate_evidence_metadata_v2(
                _packet(), metadata, source_texts=_source_texts()
            )

    def test_metadata_requires_hash_bound_complete_source_texts(self) -> None:
        source_texts = _source_texts()
        source_texts["sources"][0]["excerpt_text"] = "Substituted excerpt."
        with self.assertRaisesRegex(EvidenceContractV2Error, "excerpt text hash mismatch"):
            validate_evidence_metadata_v2(
                _packet(), _metadata(), source_texts=source_texts
            )

        metadata = _metadata()
        metadata["source_texts_canonical_json_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            EvidenceContractV2Error, "source-text canonical-json hash mismatch"
        ):
            validate_evidence_metadata_v2(
                _packet(), metadata, source_texts=_source_texts()
            )

    def test_metadata_requires_exact_calculation_coverage_and_packet_binding(self) -> None:
        metadata = _metadata()
        metadata["calculations"].pop()
        with self.assertRaisesRegex(EvidenceContractV2Error, "exactly cover"):
            validate_evidence_metadata_v2(
                _packet(), metadata, source_texts=_source_texts()
            )

        metadata = _metadata()
        metadata["calculations"][0]["packet_period"] = "different period"
        with self.assertRaisesRegex(EvidenceContractV2Error, "packet unit/period mismatch"):
            validate_evidence_metadata_v2(
                _packet(), metadata, source_texts=_source_texts()
            )

    def test_claim_rejects_stale_cited_excerpt_hash(self) -> None:
        analyst = _analyst_bindings()
        analyst["claims"][0]["citation_bindings"][0]["cited_excerpt_sha256"] = "0" * 64
        with self.assertRaisesRegex(EvidenceContractV2Error, "excerpt binding mismatch"):
            _validate_analyst_bindings(analyst)

    def test_claim_sidecar_is_bound_to_the_full_analyst_response_and_order(self) -> None:
        analyst = _analyst_bindings()
        analyst["analyst_response_sha256"] = "0" * 64
        with self.assertRaisesRegex(EvidenceContractV2Error, "analyst response hash mismatch"):
            _validate_analyst_bindings(analyst)

        analyst = _analyst_bindings()
        analyst_response = _analyst_response()
        analyst_response["claims"][0]["source_ids"].reverse()
        analyst_response["claims"][0]["cited_excerpt_sha256"].reverse()
        analyst["analyst_response_sha256"] = _canonical_digest(analyst_response)
        analyst["claims"][0]["analyst_claim_sha256"] = _canonical_digest(
            analyst_response["claims"][0]
        )
        with self.assertRaisesRegex(EvidenceContractV2Error, "must exactly match analyst claim"):
            _validate_analyst_bindings(analyst, analyst_response=analyst_response)

    def test_claim_rejects_period_value_or_source_mismatch(self) -> None:
        analyst = _analyst_bindings()
        analyst["claims"][0]["evidence_period"]["value"] = _baseline_period()
        with self.assertRaisesRegex(EvidenceContractV2Error, "exactly match claim"):
            _validate_analyst_bindings(analyst)

        analyst = _analyst_bindings()
        analyst["claims"][0]["evidence_period"]["source_ids"] = ["S-baseline"]
        with self.assertRaisesRegex(EvidenceContractV2Error, "period role"):
            _validate_analyst_bindings(analyst)

    def test_claim_rejects_unit_and_calculation_mismatch(self) -> None:
        analyst = _analyst_bindings()
        analyst["claims"][0]["unit"] = "percent"
        analyst["claims"][0]["evidence_unit"]["value"] = "percent"
        with self.assertRaisesRegex(EvidenceContractV2Error, "metric/unit/period mismatch"):
            _validate_analyst_bindings(analyst)

        analyst = _analyst_bindings()
        analyst["claims"][0]["calculation_ids"] = ["C-baseline"]
        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            "source/hash/calculation bindings must exactly match analyst claim|calculation metric/unit/period mismatch",
        ):
            _validate_analyst_bindings(analyst)

    def test_comparative_claim_requires_structured_baseline(self) -> None:
        analyst = _analyst_bindings()
        analyst["claims"][0]["comparison_baseline"] = None
        with self.assertRaisesRegex(EvidenceContractV2Error, "requires a baseline"):
            _validate_analyst_bindings(analyst)

        analyst = _analyst_bindings()
        analyst["claims"][0]["comparison_baseline"]["metric_label"] = "revenue"
        with self.assertRaisesRegex(EvidenceContractV2Error, "metric_label must match"):
            _validate_analyst_bindings(analyst)

        analyst = _analyst_bindings()
        analyst["claims"][0]["comparison_baseline"]["period"] = _current_period()
        with self.assertRaisesRegex(EvidenceContractV2Error, "distinct and dated"):
            _validate_analyst_bindings(analyst)

        analyst = _analyst_bindings()
        analyst["claims"][0]["comparison_baseline"]["period"] = {
            "kind": "range",
            "start_date": "2025-02-01",
            "end_date": "2025-07-31",
        }
        with self.assertRaisesRegex(EvidenceContractV2Error, "same_period_prior_year dates mismatch"):
            _validate_analyst_bindings(analyst)

    def test_lexical_scope_flags_prevent_characteristic_bypass(self) -> None:
        analyst = _analyst_bindings()
        analyst["claims"][0]["claim_characteristics"] = ["quantitative"]
        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            "claim_characteristics: missing lexical requirement comparative",
        ):
            _validate_analyst_bindings(analyst)

    def test_lexical_scope_flags_require_matching_critic_issues(self) -> None:
        analyst = self._validated_analyst()
        critic = _critic_coverage()
        critic["ticker_reviews"][0]["issues"] = [
            critic["ticker_reviews"][0]["issues"][0]
        ]
        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            r"lexical scope flags require typed issue\(s\).*comparison_baseline",
        ):
            _validate_critic(analyst, critic)

        critic = _critic_coverage()
        review = critic["ticker_reviews"][0]
        review["verdict"] = "approve"
        review["issues"] = []
        for field in (
            "factual_grounding_pass",
            "citation_integrity_pass",
            "numeric_reconciliation_pass",
            "long_term_reasoning_pass",
            "action_proportionality_pass",
            "policy_boundary_pass",
        ):
            review[field] = True
        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            r"lexical scope flags require typed issue\(s\)",
        ):
            _validate_critic(analyst, critic)

        analyst = _analyst_bindings()
        analyst["claims"][0]["lexical_scope_flags"] = []
        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            "lexical_scope_flags: must exactly match deterministic scope lint",
        ):
            _validate_analyst_bindings(analyst)

    def test_citation_bindings_fail_closed_on_duplicates_or_unsupported_roles(self) -> None:
        analyst = _analyst_bindings()
        analyst["claims"][0]["citation_bindings"].append(
            copy.deepcopy(analyst["claims"][0]["citation_bindings"][0])
        )
        with self.assertRaisesRegex(EvidenceContractV2Error, "source_ids must be unique"):
            _validate_analyst_bindings(analyst)

        analyst = _analyst_bindings()
        analyst["claims"][0]["citation_bindings"][0]["support_roles"].append(
            "entity_scope"
        )
        with self.assertRaisesRegex(EvidenceContractV2Error, "not supported by source metadata"):
            _validate_analyst_bindings(analyst)

    def test_claim_rejects_hash_valid_cross_ticker_citation(self) -> None:
        packet = _packet()
        packet["source_catalog"].append(
            {
                "source_id": "S-other",
                "ticker": "OTH",
                "content_sha256": _digest("Other ticker baseline excerpt."),
            }
        )
        source_texts = _source_texts()
        source_texts["sources"].append(
            {
                "source_id": "S-other",
                "excerpt_text": "Other ticker baseline excerpt.",
            }
        )
        metadata = _metadata()
        metadata["source_texts_canonical_json_sha256"] = _canonical_digest(source_texts)
        metadata["sources"].append(
            {
                "source_id": "S-other",
                "ticker": "OTH",
                "content_sha256": _digest("Other ticker baseline excerpt."),
                "metric_label": "operating_margin",
                "unit": "percent_of_revenue",
                "period": _baseline_period(),
                "supported_roles": ["comparison_baseline"],
            }
        )
        analyst_response = _analyst_response()
        analyst_response["claims"][0]["source_ids"] = ["S-current", "S-other"]
        analyst_response["claims"][0]["cited_excerpt_sha256"] = [
            _digest("Current operating margin excerpt."),
            _digest("Other ticker baseline excerpt."),
        ]
        analyst = _analyst_bindings()
        analyst["analyst_response_sha256"] = _canonical_digest(analyst_response)
        analyst["claims"][0]["analyst_claim_sha256"] = _canonical_digest(
            analyst_response["claims"][0]
        )
        analyst["claims"][0]["citation_bindings"][1] = {
            "source_id": "S-other",
            "cited_excerpt_sha256": _digest("Other ticker baseline excerpt."),
            "support_roles": ["comparison_baseline"],
        }
        analyst["claims"][0]["comparison_baseline"]["source_ids"] = ["S-other"]

        with self.assertRaisesRegex(EvidenceContractV2Error, "cross-ticker citation binding"):
            validate_analyst_evidence_bindings_v2(
                packet,
                metadata,
                analyst,
                source_texts=source_texts,
                analyst_response=analyst_response,
            )

    def test_critic_requires_exact_coverage_and_linked_issues(self) -> None:
        analyst = self._validated_analyst()
        critic = _critic_coverage()
        self.assertIs(
            _validate_critic(analyst, critic),
            critic,
        )

        critic = _critic_coverage()
        critic["ticker_reviews"][0]["reviewed_claim_ids"] = []
        with self.assertRaisesRegex(
            EvidenceContractV2Error, "expected a non-empty array|exactly match"
        ):
            _validate_critic(analyst, critic)

        critic = _critic_coverage()
        critic["ticker_reviews"][0]["issues"][0]["affected_claim_ids"] = [
            "unknown-claim"
        ]
        with self.assertRaisesRegex(EvidenceContractV2Error, "unknown affected"):
            _validate_critic(analyst, critic)

    def test_multi_claim_issue_requires_evidence_for_every_affected_claim(self) -> None:
        analyst_response = _analyst_response()
        source_hash = _digest("Customer concentration excerpt.")
        analyst_response["claims"].append(
            {
                "claim_id": "claim-customer-metric",
                "ticker": "TST",
                "claim": "A customer metric was disclosed.",
                "materiality": "high",
                "source_ids": ["S-scope"],
                "cited_excerpt_sha256": [source_hash],
                "calculation_ids": [],
            }
        )
        analyst = _analyst_bindings()
        analyst["claims"].append(
            {
                "claim_id": "claim-customer-metric",
                "analyst_claim_sha256": _canonical_digest(
                    analyst_response["claims"][1]
                ),
                "ticker": "TST",
                "materiality": "high",
                "metric_label": "customer_concentration",
                "unit": "percent_of_revenue",
                "period": _current_period(),
                "claim_characteristics": ["qualitative"],
                "lexical_scope_flags": [],
                "citation_bindings": [
                    {
                        "source_id": "S-scope",
                        "cited_excerpt_sha256": source_hash,
                        "support_roles": ["claim", "period", "unit"],
                    }
                ],
                "evidence_period": {
                    "value": _current_period(),
                    "source_ids": ["S-scope"],
                },
                "evidence_unit": {
                    "value": "percent_of_revenue",
                    "source_ids": ["S-scope"],
                },
                "comparison_baseline": None,
                "calculation_ids": [],
            }
        )
        analyst["analyst_response_sha256"] = _canonical_digest(analyst_response)

        committee_response = _committee_response()
        committee_response["ticker_decisions"][0]["claim_ids"].append(
            "claim-customer-metric"
        )
        committee_ticker_decisions = _committee_ticker_decisions()
        committee_ticker_decisions["committee_response_sha256"] = _canonical_digest(
            committee_response
        )
        committee_ticker_decisions["decisions"][0]["claim_ids"].append(
            "claim-customer-metric"
        )
        committee_ticker_decisions["decisions"][0]["committee_decision_sha256"] = (
            _canonical_digest(committee_response["ticker_decisions"][0])
        )

        critic = _critic_coverage()
        critic["ticker_reviews"][0]["reviewed_claim_ids"].append(
            "claim-customer-metric"
        )
        critic["ticker_reviews"][0]["issues"].append(
            {
                "issue_id": "issue-shared-without-shared-evidence",
                "issue_type": "citation_scope",
                "severity": "medium",
                "material": True,
                "issue": "A cited scope issue cannot borrow another claim's source.",
                "affected_claim_ids": ["claim-margin", "claim-customer-metric"],
                "source_ids": ["S-current"],
            }
        )

        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            "source_ids must include a cited source for every affected claim",
        ):
            validate_critic_coverage_v2(
                packet=_packet(),
                metadata=_metadata(),
                source_texts=_source_texts(),
                analyst_response=analyst_response,
                analyst_bindings=analyst,
                committee_response=committee_response,
                committee_ticker_decisions=committee_ticker_decisions,
                response=critic,
            )

        shared_issue = critic["ticker_reviews"][0]["issues"][-1]
        shared_issue["issue_type"] = "comparison_baseline"
        shared_issue["source_ids"] = ["S-baseline", "S-scope"]
        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            "source_ids lack required support role for every affected claim",
        ):
            validate_critic_coverage_v2(
                packet=_packet(),
                metadata=_metadata(),
                source_texts=_source_texts(),
                analyst_response=analyst_response,
                analyst_bindings=analyst,
                committee_response=committee_response,
                committee_ticker_decisions=committee_ticker_decisions,
                response=critic,
            )

    def test_committee_cannot_omit_an_analyst_claim_from_critic_coverage(self) -> None:
        analyst_response = _analyst_response()
        second_response_claim = copy.deepcopy(analyst_response["claims"][0])
        second_response_claim["claim_id"] = "claim-margin-second"
        analyst_response["claims"].append(second_response_claim)

        analyst = _analyst_bindings()
        second_binding = copy.deepcopy(analyst["claims"][0])
        second_binding["claim_id"] = "claim-margin-second"
        analyst["claims"].append(second_binding)
        analyst["analyst_response_sha256"] = _canonical_digest(analyst_response)
        for response_claim, binding in zip(
            analyst_response["claims"], analyst["claims"], strict=True
        ):
            binding["analyst_claim_sha256"] = _canonical_digest(response_claim)

        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            "committee_ticker_decisions_v2: must exactly cover analyst claim_ids",
        ):
            validate_critic_coverage_v2(
                packet=_packet(),
                metadata=_metadata(),
                source_texts=_source_texts(),
                analyst_response=analyst_response,
                analyst_bindings=analyst,
                committee_response=_committee_response(),
                committee_ticker_decisions=_committee_ticker_decisions(),
                response=_critic_coverage(),
            )

    def test_committee_rejects_a_hash_bound_cross_ticker_claim(self) -> None:
        committee_response = {
            "packet_id": _packet()["packet_id"],
            "ticker_decisions": [
                {
                    "ticker": "TST",
                    "claim_ids": ["claim-other"],
                    "rationale": "Synthetic cross-ticker decision.",
                }
            ],
        }
        decision = committee_response["ticker_decisions"][0]
        committee_ticker_decisions = {
            "schema_version": COMMITTEE_TICKER_DECISIONS_V2_SCHEMA_VERSION,
            "packet_id": _packet()["packet_id"],
            "committee_response_sha256": _canonical_digest(committee_response),
            "canonical_effect": False,
            "decisions": [
                {
                    "ticker": "TST",
                    "claim_ids": ["claim-other"],
                    "committee_decision_sha256": _canonical_digest(decision),
                }
            ],
        }
        with self.assertRaisesRegex(EvidenceContractV2Error, "cross-ticker claim_id"):
            _committee_claims_by_ticker(
                committee_ticker_decisions,
                committee_response=committee_response,
                claim_map={"claim-other": {"ticker": "OTH"}},
                packet_id=_packet()["packet_id"],
            )

    def test_critic_rejects_a_committee_summary_not_bound_to_full_response(self) -> None:
        analyst = self._validated_analyst()
        committee_response = _committee_response()
        committee_response["ticker_decisions"][0]["rationale"] = "Substituted."

        with self.assertRaisesRegex(
            EvidenceContractV2Error,
            "committee_ticker_decisions_v2: committee response hash mismatch",
        ):
            validate_critic_coverage_v2(
                packet=_packet(),
                metadata=_metadata(),
                source_texts=_source_texts(),
                analyst_response=_analyst_response(),
                analyst_bindings=analyst,
                committee_response=committee_response,
                committee_ticker_decisions=_committee_ticker_decisions(),
                response=_critic_coverage(),
            )

    def test_critic_rejects_source_and_pass_dimension_contradictions(self) -> None:
        analyst = self._validated_analyst()
        critic = _critic_coverage()
        critic["ticker_reviews"][0]["issues"][0]["source_ids"] = ["S-scope"]
        with self.assertRaisesRegex(EvidenceContractV2Error, "belong to affected claims"):
            _validate_critic(analyst, critic)

        critic = _critic_coverage()
        critic["ticker_reviews"][0]["citation_integrity_pass"] = True
        with self.assertRaisesRegex(EvidenceContractV2Error, "requires citation_integrity_pass false"):
            _validate_critic(analyst, critic)

        critic = _critic_coverage()
        critic["ticker_reviews"][0]["issues"][0]["source_ids"] = ["S-baseline"]
        with self.assertRaisesRegex(EvidenceContractV2Error, "lack required support role"):
            _validate_critic(analyst, critic)

    def test_critic_revalidates_analyst_and_disallows_approve_with_failed_dimension(self) -> None:
        analyst = self._validated_analyst()
        analyst["canonical_effect"] = True
        with self.assertRaisesRegex(EvidenceContractV2Error, "canonical_effect must remain false"):
            _validate_critic(analyst, _critic_coverage())

        analyst = self._validated_analyst()
        critic = _critic_coverage()
        critic["ticker_reviews"][0]["verdict"] = "approve"
        critic["ticker_reviews"][0]["issues"][0]["severity"] = "low"
        critic["ticker_reviews"][0]["issues"][0]["material"] = False
        with self.assertRaisesRegex(EvidenceContractV2Error, "approve verdict requires"):
            _validate_critic(analyst, critic)

    def test_critic_false_dimension_requires_matching_issue(self) -> None:
        analyst = self._validated_analyst()
        critic = _critic_coverage()
        critic["ticker_reviews"][0]["issues"] = []
        with self.assertRaisesRegex(EvidenceContractV2Error, "false but no matching"):
            _validate_critic(analyst, critic)

    def test_incremental_value_requires_known_independent_reference(self) -> None:
        result = evaluate_critic_incremental_value_v2(
            valid_claim_ids=["claim-margin"],
            committee_material_issue_claim_ids=[],
            critic_material_issue_claim_ids=["claim-margin"],
            reference_material_issue_claim_ids=None,
        )
        self.assertEqual(result["incremental_value_status"], "not_established")
        self.assertFalse(result["canonical_effect"])
        self.assertFalse(result["repository_provider_called"])
        self.assertFalse(result["network_called"])

        with self.assertRaisesRegex(EvidenceContractV2Error, "unknown claim_ids"):
            evaluate_critic_incremental_value_v2(
                valid_claim_ids=["claim-margin"],
                committee_material_issue_claim_ids=[],
                critic_material_issue_claim_ids=["claim-margin"],
                reference_material_issue_claim_ids=["unknown-claim"],
            )

        result = evaluate_critic_incremental_value_v2(
            valid_claim_ids=["claim-margin"],
            committee_material_issue_claim_ids=[],
            critic_material_issue_claim_ids=["claim-margin"],
            reference_material_issue_claim_ids=["claim-margin"],
        )
        self.assertEqual(
            result["incremental_value_status"], "not_established"
        )
        self.assertEqual(
            result["reference_alignment_status"],
            "observed_against_unverified_reference",
        )

    def test_v1_contracts_remain_unchanged_and_reject_v2_sidecars(self) -> None:
        for fixture_name in ("g01_stable_hold", "g08_add_second_close"):
            with self.subTest(fixture_name=fixture_name):
                packet, responses, _ = materialized(fixture_name)
                self.assertIs(validate_packet(packet), packet)
                self.assertIs(validate_analyst(packet, responses["analyst"]), responses["analyst"])
                self.assertIs(
                    validate_committee(packet, responses["committee"], responses["analyst"]),
                    responses["committee"],
                )
                self.assertIs(
                    validate_critic(
                        packet,
                        responses["committee"],
                        responses["critic"],
                        responses["analyst"],
                    ),
                    responses["critic"],
                )

        packet, _, _ = materialized("g01_stable_hold")
        with self.assertRaises(ContractError):
            validate_analyst(packet, _analyst_bindings())


if __name__ == "__main__":
    unittest.main()
