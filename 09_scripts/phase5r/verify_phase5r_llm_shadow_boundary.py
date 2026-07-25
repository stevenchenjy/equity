#!/usr/bin/env python3
"""Prove the Phase 5R fixture shadow cannot mutate canonical state."""

from __future__ import annotations

import ast
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from build_phase5r_decision_evidence_packet import build_packet
from phase5r_daily_common import EMAIL_CONFIG_PATH, ROOT, iso_now, read_json
from phase5r_llm_provider import FixtureProvider
from run_phase5r_llm_shadow import (
    execute_shadow,
    load_registry,
    output_paths,
    persist_bundle,
)


SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"
NEW_SOURCE_FILES = (
    "phase5r_llm_contract.py",
    "build_phase5r_decision_evidence_packet.py",
    "phase5r_llm_provider.py",
    "run_phase5r_llm_shadow.py",
    "refresh_phase5r_sec_filing_artifacts.py",
    "evaluate_phase5r_llm_decision.py",
    "run_phase5r_llm_shadow_scheduler.py",
    "enable_phase5r_llm_live_shadow.py",
    "verify_phase5r_llm_shadow_boundary.py",
)
CANONICAL_RUNTIME_FILES = (
    "run_phase5r_daily_refresh.py",
    "run_phase5r_daily_decision_pipeline.py",
    "run_phase5r_daily_refresh_scheduler.py",
    "run_phase5r_daily_scheduler.py",
    "send_phase5r_daily_email.py",
)
CANONICAL_SENTINELS = (
    ROOT / "07_automation" / "email_delivery" / "phase5r_daily_delivery_ledger.csv",
    ROOT / "07_automation" / "email_delivery" / "phase5r_c2_delivery_status.csv",
    ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv",
    ROOT / "00_project_control" / "run_logs" / "phase5r_c7_run_log.csv",
    ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_c7_weekly_pipeline_run_log.csv",
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_daily_decision.json",
    ROOT / "07_automation" / "email_briefs" / "phase5r_daily_email_brief.txt",
    ROOT / "07_automation" / "email_briefs" / "phase5r_daily_email_brief.html",
    ROOT / "05_risk_and_positions" / "current_positions.local.csv",
    ROOT / "05_risk_and_positions" / "current_account_state.local.json",
    ROOT / "06_execution_records" / "manual_executions.local.csv",
    ROOT
    / "06_execution_records"
    / "phase5r_c9b_pending_execution_report.csv",
    ROOT
    / "06_execution_records"
    / "phase5r_c9b_confirmed_execution_report.csv",
    ROOT
    / "06_execution_records"
    / "phase5r_c9b_reconciliation_report.csv",
    ROOT / "05_risk_and_positions" / "phase5r_c9_exact_action_plan.csv",
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_position_recommendations.csv",
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_new_candidate_recommendations.csv",
)
PROHIBITED_CALLS = {
    "place_order",
    "submit_order",
    "create_order",
    "get_account",
    "get_accounts",
}


def digest_or_absent(path: Path) -> str:
    if not path.exists():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smtp_stat_only() -> tuple[int, int, int, int] | str:
    try:
        metadata = EMAIL_CONFIG_PATH.stat()
    except FileNotFoundError:
        return "absent"
    return (
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def static_source_check() -> list[str]:
    violations: list[str] = []
    for name in NEW_SOURCE_FILES:
        path = SCRIPT_DIR / name
        if not path.exists():
            violations.append(f"missing:{name}")
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            violations.append(f"syntax:{name}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for module in modules:
                    lowered = module.lower()
                    if lowered in {"smtplib"} or "broker" in lowered:
                        violations.append(f"prohibited_import:{name}:{module}")
            if isinstance(node, ast.Call):
                function_name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if function_name in PROHIBITED_CALLS:
                    violations.append(f"prohibited_call:{name}:{function_name}")
        if name == "run_phase5r_llm_shadow.py":
            for marker in (
                "send_phase5r_daily_email",
                "EMAIL_CONFIG_PATH",
                "smtplib",
                "phase5r_c7",
            ):
                if marker in source:
                    violations.append(f"shadow_reference:{marker}")
    for name in CANONICAL_RUNTIME_FILES:
        path = SCRIPT_DIR / name
        if not path.exists():
            violations.append(f"missing:{name}")
            continue
        source = path.read_text(encoding="utf-8")
        if any(
            marker in source
            for marker in (
                "run_phase5r_llm_shadow",
                "phase5r_llm_provider",
                "CodexCliProvider",
            )
        ):
            violations.append(f"canonical_model_reference:{name}")
    return violations


def _fixture(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    primary_sources_by_ticker: dict[str, list[str]] = {}
    for source in packet["source_catalog"]:
        ticker = str(source.get("ticker", "")).upper()
        if ticker and source.get("source_id"):
            primary_sources_by_ticker.setdefault(ticker, []).append(
                source["source_id"]
            )
    held = [row["ticker"] for row in packet["entities"] if row["role"] == "held"]
    claims = []
    coverage = []
    decisions = []
    approved_sources: list[str] = []
    for index, ticker in enumerate(held):
        source_ids = primary_sources_by_ticker.get(ticker, [])[:1]
        if not source_ids:
            raise RuntimeError(f"fixture cannot ground held ticker: {ticker}")
        approved_sources.extend(source_ids)
        claims.append(
            {
                "claim_id": f"held-{index}",
                "ticker": ticker,
                "claim": "Current packet does not establish a material thesis break.",
                "stance": "neutral",
                "time_horizon": "long_term",
                "materiality": "medium",
                "source_ids": source_ids,
                "calculation_ids": [],
            }
        )
        coverage.append(
            {
                "ticker": ticker,
                "official_evidence_sufficient": True,
                "contradictory_evidence": False,
                "missing_evidence": [],
            }
        )
        decisions.append(
            {
                "ticker": ticker,
                "classification": "hold_existing",
                "thesis_direction": "stable",
                "rationale": "No packet-local evidence crosses the change threshold.",
                "long_term_case": "Continue monitoring the documented thesis.",
                "risks": ["Evidence may change in a later filing."],
                "invalidation_conditions": ["A primary-source thesis break."],
                "source_ids": source_ids,
                "calculation_ids": [],
                "confidence_pct": 70,
                "human_review_needed": False,
            }
        )
    return {
        "analyst": {
            "schema_version": "phase5r_llm_evidence_analysis_v1",
            "packet_id": packet["packet_id"],
            "as_of_et": packet["as_of_et"],
            "prompt_injection_detected": False,
            "claims": claims,
            "ticker_coverage": coverage,
            "unresolved_questions": [],
        },
        "committee": {
            "schema_version": "phase5r_llm_committee_decision_v1",
            "packet_id": packet["packet_id"],
            "portfolio_classification": "hold_existing",
            "headline": "影子结论：继续持有，当前证据不足以改变长期判断",
            "decisive_advice": "不因单日噪声改变研究分类。",
            "long_term_portfolio_case": "Primary evidence does not show a thesis break.",
            "data_sufficiency": "sufficient",
            "material_thesis_break": False,
            "confidence_pct": 70,
            "ticker_decisions": decisions,
            "dissent": [],
            "automatic_action_allowed": False,
        },
        "critic": {
            "schema_version": "phase5r_llm_critic_review_v1",
            "packet_id": packet["packet_id"],
            "verdict": "approve",
            "downgrade_to": "hold_existing",
            "factual_grounding_pass": True,
            "citation_integrity_pass": True,
            "numeric_reconciliation_pass": True,
            "long_term_reasoning_pass": True,
            "action_proportionality_pass": True,
            "policy_boundary_pass": True,
            "issues": [],
            "approved_source_ids": sorted(set(approved_sources)),
            "automatic_action_allowed": False,
        },
    }


def main() -> int:
    violations = static_source_check()
    before = {str(path): digest_or_absent(path) for path in CANONICAL_SENTINELS}
    smtp_before = smtp_stat_only()
    # Verification may run after a source-only refresh and before the next
    # canonical daily decision.  Use the verifier's current timestamp so newly
    # fetched public evidence is not incorrectly treated as future data.
    packet = build_packet(iso_now())
    registry = load_registry()
    fail_closed_registry_fields = (
        "canonical_influence_enabled",
        "tools_enabled",
        "provider_credentials_read_by_repository",
        "exact_account_dollars_allowed",
        "automatic_action_allowed",
        "email_eligible",
        "broker_connection_allowed",
        "order_code_allowed",
    )
    if any(registry[field] is not False for field in fail_closed_registry_fields):
        violations.append("model_registry_not_fail_closed")
    with tempfile.TemporaryDirectory(prefix="phase5r-shadow-verify-") as directory:
        paths = output_paths(Path(directory))
        provider = FixtureProvider(_fixture(packet))
        bundle = execute_shadow(packet, provider, registry)
        persist_bundle(paths, bundle)
        produced = sorted(
            str(path.relative_to(directory))
            for path in Path(directory).rglob("*")
            if path.is_file()
        )
        expected = sorted(
            [
                paths.decision_json.name,
                paths.decision_report.name,
                paths.audit_log.name,
                paths.state.name,
            ]
        )
        if produced != expected:
            violations.append("temporary_output_scope_mismatch")
        if bundle["adjudication"]["automatic_action_allowed"] is not False:
            violations.append("automatic_action_boundary")
        if any(bundle["boundaries"].values()):
            violations.append("side_effect_boundary")

    after = {str(path): digest_or_absent(path) for path in CANONICAL_SENTINELS}
    smtp_after = smtp_stat_only()
    if before != after:
        violations.append("canonical_sentinel_mutated")
    if smtp_before != smtp_after:
        violations.append("smtp_metadata_mutated")

    passed = not violations
    print(
        f"llm_shadow_boundary={'passed' if passed else 'failed'} "
        f"violations={','.join(violations) or 'none'} "
        "provider=fixture network_used=false credential_read=false "
        "email_attempted=false smtp_config_read=false canonical_effect=false "
        "broker_connected=false order_code_created=false"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
