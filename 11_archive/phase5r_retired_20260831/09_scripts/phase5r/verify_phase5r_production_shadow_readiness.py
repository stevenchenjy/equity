#!/usr/bin/env python3
"""Verify Phase 5R production-shadow-v1's offline safety boundary.

This verifier reads only the new production-shadow source/state and current
sanitized daily readiness inputs.  It never constructs a provider, reads a
credential, invokes a browser/network, opens v10/pilot artifacts, or changes a
canonical workflow result.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import phase5r_production_shadow_v1 as shadow
from phase5r_daily_common import ROOT


SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"
SOURCE_FILES = (
    "phase5r_production_shadow_v1.py",
    # The active runner uses only OpenAIResponsesProvider from this shared
    # adapter, but scan the imported adapter too so the safety report does not
    # imply an unchecked execution dependency.
    "phase5r_llm_provider.py",
    "run_phase5r_production_shadow.py",
    "record_phase5r_production_shadow_human_assessment.py",
    "phase5r_production_shadow_email_gate.py",
    "send_phase5r_production_shadow_email.py",
    "run_phase5r_daily_refresh.py",
    "run_phase5r_daily_refresh_scheduler.py",
    "run_phase5r_daily_decision_pipeline.py",
    "run_phase5r_runtime_scheduler.py",
)
FORBIDDEN_IMPORT_ROOTS = {"smtplib", "requests", "urllib", "webbrowser", "selenium"}
FORBIDDEN_CALLS = {
    "place_order",
    "submit_order",
    "create_order",
    "get_account",
    "get_accounts",
    "sendmail",
}
FORBIDDEN_HISTORICAL_MARKERS = (
    "run_phase5r_model_pilot",
    "run_phase5r_llm_shadow",
    "run_phase5r_future_v2_offline_integration",
    "replacement_v",
    "phase5r_model_pilot_v",
)
REQUIRED_OPENAI_SDK_VERSION = "2.49.0"


def _sdk_runtime_status() -> dict[str, Any]:
    """Inspect only local package metadata; never construct a client."""

    try:
        import openai
    except Exception:
        return {
            "available": False,
            "version": None,
            "reason": "openai_sdk_unavailable",
        }
    version = getattr(openai, "__version__", None)
    if version != REQUIRED_OPENAI_SDK_VERSION:
        return {
            "available": False,
            "version": version if isinstance(version, str) else None,
            "reason": "openai_sdk_version_mismatch",
        }
    return {"available": True, "version": version, "reason": None}


def static_boundary_violations() -> list[str]:
    violations: list[str] = []
    for filename in SOURCE_FILES:
        path = SCRIPT_DIR / filename
        if not path.is_file() or path.is_symlink():
            violations.append(f"missing_or_unsafe:{filename}")
            continue
        source = path.read_text(encoding="utf-8")
        lowered = source.lower()
        for marker in FORBIDDEN_HISTORICAL_MARKERS:
            if marker in lowered:
                violations.append(f"historical_reference:{filename}:{marker}")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            violations.append(f"syntax_error:{filename}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for name in names:
                    if name.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
                        violations.append(f"forbidden_import:{filename}:{name}")
            if isinstance(node, ast.Call):
                called = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if called in FORBIDDEN_CALLS:
                    violations.append(f"forbidden_call:{filename}:{called}")
    if shadow.maximum_provider_cost_usd() > shadow.DAILY_COST_CAP_USD:
        violations.append("configured_request_cost_exceeds_daily_cap")
    if shadow.SDK_MAX_RETRIES != 0:
        violations.append("sdk_retry_not_zero")
    if shadow.MAX_OUTPUT_TOKENS <= 0:
        violations.append("output_cap_invalid")
    return violations


def verify_readiness() -> dict[str, Any]:
    violations = static_boundary_violations()
    readiness = shadow.check_current_readiness()
    sdk = _sdk_runtime_status()
    capacity = shadow.provider_attempt_capacity()
    if readiness.get("ready") is not True:
        overall_reason = readiness.get("reason")
    elif sdk["available"] is not True:
        overall_reason = sdk["reason"]
    elif capacity["available"] is not True:
        overall_reason = capacity["reason"]
    else:
        overall_reason = "fresh_current_packet_sdk_and_reservation_capacity_passed"
    return {
        "schema_version": "phase5r_production_shadow_readiness_v1",
        "static_boundary_passed": not violations,
        "static_boundary_violations": violations,
        "provider_adapter_source_scanned": True,
        "current_freshness_ready": readiness.get("ready") is True,
        "openai_sdk": sdk,
        "provider_attempt_capacity": capacity,
        "authentication": "not_probed_without_provider_call",
        "ready_for_one_provider_attempt": (
            readiness.get("ready") is True
            and sdk["available"] is True
            and capacity["available"] is True
        ),
        "current_readiness_reason": overall_reason,
        "pricing_valid_through": shadow.PRICING_VALID_THROUGH,
        "maximum_configured_cost_usd": str(shadow.maximum_provider_cost_usd()),
        "daily_cost_cap_usd": str(shadow.DAILY_COST_CAP_USD),
        "monthly_cost_cap_usd": str(shadow.MONTHLY_COST_CAP_USD),
        "sdk_max_retries": shadow.SDK_MAX_RETRIES,
        "canonical_effect": False,
        "provider_constructed": False,
        "provider_called": False,
        "email_attempted": False,
        "broker_or_account_access": False,
    }


def main() -> int:
    result = verify_readiness()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["static_boundary_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
