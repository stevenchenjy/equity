#!/usr/bin/env python3
"""Evaluate the Phase 5R model contracts against immutable offline fixtures.

The evaluator uses only :class:`FixtureProvider`, never builds a live packet,
never invokes Codex or a network client, and writes only beneath an explicitly
provided output directory outside the project tree.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from phase5r_daily_common import ROOT, canonical_sha256
from phase5r_llm_contract import (
    ContractError,
    decimal_round,
    reconcile_calculations,
    validate_packet,
)
from phase5r_llm_provider import FixtureProvider, ProviderError
from run_phase5r_llm_shadow import execute_shadow, load_registry


DEFAULT_MANIFEST = (
    ROOT / "08_reviews" / "phase5r_llm_eval_cases" / "v1" / "manifest.json"
)
REPORT_JSON = "phase5r_llm_evaluation_report.json"
REPORT_MARKDOWN = "phase5r_llm_evaluation_report.md"
_TOKEN = "$PACKET_ID"
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"fixture JSON is unreadable: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"fixture JSON must be an object: {path.name}")
    return payload


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    if set(manifest) != {"schema_version", "base_fixture", "cases"}:
        raise ContractError("evaluation manifest fields do not match")
    if manifest["schema_version"] != "phase5r_llm_eval_manifest_v1":
        raise ContractError("evaluation manifest version mismatch")
    if not isinstance(manifest["cases"], list) or not manifest["cases"]:
        raise ContractError("evaluation manifest must contain cases")
    case_ids = [str(row.get("case_id", "")) for row in manifest["cases"]]
    if any(not value for value in case_ids) or len(case_ids) != len(set(case_ids)):
        raise ContractError("evaluation case IDs must be non-empty and unique")
    return manifest


def _replace_token(value: Any, packet_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_token(child, packet_id) for key, child in value.items()}
    if isinstance(value, list):
        return [_replace_token(child, packet_id) for child in value]
    return packet_id if value == _TOKEN else value


def _committee_decision(responses: dict[str, Any]) -> dict[str, Any]:
    return responses["committee"]["ticker_decisions"][0]


def _set_transition(
    responses: dict[str, Any],
    classification: str,
    *,
    thesis_direction: str,
    material_break: bool = False,
) -> None:
    committee = responses["committee"]
    decision = _committee_decision(responses)
    committee["portfolio_classification"] = classification
    committee["material_thesis_break"] = material_break
    committee["headline"] = f"Fixture research classification: {classification}"
    committee["decisive_advice"] = (
        "Escalate this research classification for independent human review."
    )
    decision["classification"] = classification
    decision["thesis_direction"] = thesis_direction
    decision["human_review_needed"] = True
    responses["critic"]["downgrade_to"] = classification


def _apply_scenario(
    scenario: str,
    packet: dict[str, Any],
    responses: dict[str, Any],
) -> int:
    decision = _committee_decision(responses)
    calculation_id = "calc:revenue_yoy:TST:CY2026Q1"
    distinct_valid_closes = 1

    if scenario == "stable_hold":
        pass
    elif scenario == "missing_material_citation":
        responses["analyst"]["claims"][0]["source_ids"] = []
    elif scenario == "unknown_source_locator":
        decision["source_ids"] = ["sec:TST:unknown-source"]
    elif scenario == "valid_numeric_reconciliation":
        responses["analyst"]["claims"][0]["calculation_ids"] = [calculation_id]
        decision["calculation_ids"] = [calculation_id]
    elif scenario == "numeric_mismatch":
        decision["calculation_ids"] = [calculation_id]
        packet["calculations"][0]["value"] = "31.52"
        packet["calculations"][0]["reconciled"] = False
    elif scenario == "unit_period_mismatch":
        decision["calculation_ids"] = [calculation_id]
        packet["calculations"][0]["unit"] = ""
        packet["calculations"][0]["period"] = ""
        packet["calculations"][0]["inputs"][1]["unit"] = "USD_thousands"
        packet["calculations"][0]["inputs"][1]["period"] = "CY2025YTD"
    elif scenario == "add_first_close":
        _set_transition(
            responses,
            "paper_trade_candidate",
            thesis_direction="strengthening",
        )
    elif scenario == "add_second_close":
        _set_transition(
            responses,
            "paper_trade_candidate",
            thesis_direction="strengthening",
        )
        distinct_valid_closes = 2
    elif scenario == "critic_disagreement":
        _set_transition(responses, "trim_review", thesis_direction="weakening")
        critic = responses["critic"]
        critic["verdict"] = "revise"
        critic["downgrade_to"] = "hold_existing"
        critic["action_proportionality_pass"] = False
        critic["approved_source_ids"] = []
        critic["issues"] = [
            {
                "severity": "high",
                "issue": "The proposed transition is disproportionate to the evidence.",
                "source_ids": ["sec:TST:10Q:2026Q1:0"],
            }
        ]
    elif scenario == "material_thesis_break":
        _set_transition(
            responses,
            "exit_review",
            thesis_direction="broken",
            material_break=True,
        )
        analyst_claim = responses["analyst"]["claims"][0]
        analyst_claim["stance"] = "weakens"
        analyst_claim["materiality"] = "high"
        analyst_claim["time_horizon"] = "long_term"
        analyst_claim["claim"] = (
            "Primary-source evidence shows a material long-term thesis break."
        )
        decision["rationale"] = (
            "The primary filing contains a material long-term thesis break."
        )
    elif scenario == "stale_market_data":
        packet["gates"]["market_data_current"] = False
        packet["market_observations"][0]["bar_state"] = "intraday_or_unverified"
    elif scenario == "prompt_injection":
        analyst = responses["analyst"]
        analyst["prompt_injection_detected"] = True
        analyst["claims"][0]["claim"] = (
            "The filing contains hostile text telling the reader to ignore policy."
        )
        committee = responses["committee"]
        committee["portfolio_classification"] = "abstain"
        committee["data_sufficiency"] = "insufficient"
        committee["confidence_pct"] = 0
        committee["headline"] = "Prompt injection detected"
        committee["decisive_advice"] = "Do not use the model result."
        decision.update(
            {
                "classification": "abstain",
                "thesis_direction": "unclear",
                "source_ids": [],
                "calculation_ids": [],
                "confidence_pct": 0,
                "human_review_needed": True,
            }
        )
        critic = responses["critic"]
        critic.update(
            {
                "verdict": "reject",
                "downgrade_to": "abstain",
                "factual_grounding_pass": False,
                "citation_integrity_pass": False,
                "numeric_reconciliation_pass": False,
                "long_term_reasoning_pass": False,
                "action_proportionality_pass": False,
                "policy_boundary_pass": False,
                "approved_source_ids": [],
                "issues": [
                    {
                        "severity": "critical",
                        "issue": "Untrusted evidence contained an instruction-like payload.",
                        "source_ids": ["sec:TST:10Q:2026Q1:0"],
                    }
                ],
            }
        )
    else:
        raise ContractError(f"unknown evaluation scenario: {scenario}")
    return distinct_valid_closes


def materialize_case(
    manifest_path: Path,
    manifest: dict[str, Any],
    case: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    fixture_root = manifest_path.parent.resolve()
    base_path = (fixture_root / str(manifest["base_fixture"])).resolve()
    try:
        base_path.relative_to(fixture_root)
    except ValueError as exc:
        raise ContractError("base fixture escapes the fixture root") from exc
    base = _read_json(base_path)
    if set(base) != {"packet", "responses"}:
        raise ContractError("base fixture must contain packet and responses")
    packet = copy.deepcopy(base["packet"])
    responses = copy.deepcopy(base["responses"])
    packet["decision_fingerprint"] = f"fixture:{case['case_id']}"
    distinct_valid_closes = _apply_scenario(
        str(case["scenario"]), packet, responses
    )
    unsigned = copy.deepcopy(packet)
    unsigned.pop("packet_id", None)
    packet_id = canonical_sha256(unsigned)
    packet["packet_id"] = packet_id
    responses = _replace_token(responses, packet_id)
    return packet, responses, distinct_valid_closes


def verify_source_integrity(packet: dict[str, Any], fixture_root: Path) -> None:
    """Verify point-in-time, hash, and locator integrity without network access."""

    validate_packet(packet)
    try:
        as_of = datetime.fromisoformat(str(packet["as_of_et"]))
    except ValueError as exc:
        raise ContractError("packet source check: invalid as_of_et") from exc
    if as_of.tzinfo is None:
        raise ContractError("packet source check: as_of_et must be timezone-aware")
    known_tickers = {row["ticker"] for row in packet["entities"]}
    fixture_root = fixture_root.resolve()
    for index, source in enumerate(packet["source_catalog"]):
        path = f"packet.source_catalog[{index}]"
        if source.get("ticker") not in known_tickers:
            raise ContractError(f"{path}: source ticker is not in entities")
        digest = str(source.get("content_sha256", ""))
        if _HEX_SHA256.fullmatch(digest) is None:
            raise ContractError(f"{path}: content_sha256 is invalid")
        locator = source.get("locator")
        if not isinstance(locator, dict):
            raise ContractError(f"{path}: locator must be an object")
        accepted_at = str(source.get("accepted_at", ""))
        if accepted_at:
            try:
                accepted = datetime.fromisoformat(accepted_at)
            except ValueError as exc:
                raise ContractError(f"{path}: accepted_at is invalid") from exc
            if accepted.tzinfo is None or accepted > as_of:
                raise ContractError(f"{path}: future or timezone-naive source")
        fixture_path = locator.get("fixture_path")
        if fixture_path is None:
            continue
        source_path = (fixture_root / str(fixture_path)).resolve()
        try:
            source_path.relative_to(fixture_root)
        except ValueError as exc:
            raise ContractError(f"{path}: fixture path escapes root") from exc
        if source_path.is_symlink() or not source_path.is_file():
            raise ContractError(f"{path}: fixture source is missing or symlinked")
        content = source_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ContractError(f"{path}: source hash mismatch")
        start = locator.get("char_start")
        end = locator.get("char_end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > len(content)
        ):
            raise ContractError(f"{path}: source span is invalid")


def verify_numeric_integrity(packet: dict[str, Any]) -> None:
    """Reconcile values and independently check the fixture's formula inputs."""

    calculation_ids = [
        str(row.get("calculation_id", "")) for row in packet["calculations"]
    ]
    reconcile_calculations(packet, calculation_ids)
    for row in packet["calculations"]:
        if row.get("metric") != "revenue_yoy_pct":
            continue
        inputs = row.get("inputs", [])
        if not isinstance(inputs, list) or len(inputs) != 2:
            raise ContractError("revenue YoY calculation requires two inputs")
        current, prior = inputs
        if current.get("unit") != "USD" or prior.get("unit") != "USD":
            raise ContractError("revenue YoY input units mismatch")
        current_period = re.fullmatch(r"CY(\d{4})Q([1-4])", str(current.get("period")))
        prior_period = re.fullmatch(r"CY(\d{4})Q([1-4])", str(prior.get("period")))
        if (
            current_period is None
            or prior_period is None
            or current_period.group(2) != prior_period.group(2)
            or int(current_period.group(1)) - 1 != int(prior_period.group(1))
        ):
            raise ContractError("revenue YoY input periods mismatch")
        current_value = Decimal(str(current["value"]))
        prior_value = Decimal(str(prior["value"]))
        if prior_value == 0:
            raise ContractError("revenue YoY prior value is zero")
        recomputed = decimal_round(
            (current_value / prior_value - Decimal("1")) * Decimal("100")
        )
        if recomputed != decimal_round(row.get("recomputed_value")):
            raise ContractError("revenue YoY formula recomputation mismatch")


def evaluate_case(
    manifest_path: Path,
    manifest: dict[str, Any],
    case: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    packet, responses, closes = materialize_case(manifest_path, manifest, case)
    fixture_root = manifest_path.parent.resolve()
    preflight_issues: list[str] = []
    try:
        verify_source_integrity(packet, fixture_root)
    except ContractError as exc:
        preflight_issues.append(str(exc))
    try:
        verify_numeric_integrity(packet)
    except ContractError as exc:
        preflight_issues.append(str(exc))

    try:
        bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            registry,
            distinct_valid_closes=closes,
        )
    except (ContractError, ProviderError, OSError, ValueError) as exc:
        execution_outcome = "contract_error"
        raw_classification = "abstain"
        validation_passed = False
        raw_human_review = True
        error_type = type(exc).__name__
    else:
        adjudication = bundle["adjudication"]
        execution_outcome = bundle["outcome"]
        raw_classification = adjudication["effective_classification"]
        validation_passed = adjudication["validation_passed"]
        raw_human_review = adjudication["human_review_required"]
        error_type = ""
        if any(
            metadata.get("transport") != "fixture"
            or metadata.get("credential_read") is not False
            or metadata.get("tools_enabled") is not False
            for metadata in bundle["provider_metadata"]
        ):
            preflight_issues.append("provider metadata boundary violation")
        if any(value is not False for value in bundle["boundaries"].values()):
            preflight_issues.append("shadow bundle boundary violation")

    safe_classification = (
        raw_classification if validation_passed and not preflight_issues else "abstain"
    )
    human_review_required = (
        raw_human_review or not validation_passed or bool(preflight_issues)
    )
    actual = {
        "execution_outcome": execution_outcome,
        "raw_classification": raw_classification,
        "safe_classification": safe_classification,
        "validation_passed": validation_passed,
        "human_review_required": human_review_required,
    }
    expected = case["expected"]
    passed = actual == expected
    return {
        "case_id": case["case_id"],
        "scenario": case["scenario"],
        "tags": case["tags"],
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "preflight_issues": preflight_issues,
        "error_type": error_type,
        "packet_id": packet["packet_id"],
    }


def evaluate_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = load_manifest(manifest_path)
    registry = load_registry()
    results = [
        evaluate_case(manifest_path, manifest, case, registry)
        for case in manifest["cases"]
    ]
    passed_count = sum(1 for row in results if row["passed"])
    return {
        "schema_version": "phase5r_llm_evaluation_report_v1",
        "manifest": str(manifest_path),
        "mode": "offline_fixture",
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "all_passed": passed_count == len(results),
        "network_invoked": False,
        "codex_invoked": False,
        "email_invoked": False,
        "c7_invoked": False,
        "live_refresh_invoked": False,
        "canonical_effect": False,
        "results": results,
    }


def _safe_output_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ContractError("evaluation output directory must be outside the project")
    lowered = str(resolved).lower()
    if any(marker in lowered for marker in ("smtp", "email_delivery", "launchagents")):
        raise ContractError("evaluation output directory matches a sensitive path")
    return resolved


def write_report(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir = _safe_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / REPORT_JSON).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Phase 5R Offline Model Evaluation",
        "",
        f"- Cases: `{report['case_count']}`",
        f"- Passed: `{report['passed_count']}`",
        f"- Failed: `{report['failed_count']}`",
        "- Network invoked: `no`",
        "- Codex invoked: `no`",
        "- Email/C7/live refresh invoked: `no`",
        "- Canonical effect: `no`",
        "",
        "| Case | Result | Safe classification |",
        "| --- | --- | --- |",
    ]
    for row in report["results"]:
        lines.append(
            f"| {row['case_id']} | {'PASS' if row['passed'] else 'FAIL'} | "
            f"{row['actual']['safe_classification']} |"
        )
    (output_dir / REPORT_MARKDOWN).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--provider", choices=("fixture",), default="fixture")
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    del args.provider, args.offline

    report = evaluate_manifest(args.manifest)
    write_report(args.output_dir, report)
    print(
        f"evaluation_cases={report['case_count']} "
        f"passed={report['passed_count']} failed={report['failed_count']} "
        "network_invoked=false codex_invoked=false email_invoked=false "
        "c7_invoked=false canonical_effect=false"
    )
    return 0 if report["all_passed"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
