"""Narrow, hash-bound status handoff after an official-evidence soft failure.

This is communication continuity, never an investment-data fallback. It only
admits newly recomposed, zero-order artifacts; no prior successful draft is read.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from daily_common import sha256_file

ARTIFACTS = {
    "decision": "04_research/company_research/daily_decision.json",
    "text": "07_automation/email_briefs/daily_email_brief.txt",
    "html": "07_automation/email_briefs/daily_email_brief.html",
}
SCHEMA = "equity_limited_status_handoff_v1"


def _zero(value) -> bool:
    try:
        number = Decimal(str(value))
        return number.is_finite() and number == 0
    except (ValueError, InvalidOperation):
        return False


def validate_limited_decision(decision: dict, state: dict, *, root: Path, current: datetime) -> None:
    """Preserve failed evidence, current source bindings and every execution gate."""
    from workflow_integrity import validate_published_workflow
    from delivery_followthrough import validate_followthrough
    from email_brief import render_email

    start = datetime.fromisoformat(state["started_at"])
    generated = datetime.fromisoformat(decision["generated_at"])
    completed = datetime.fromisoformat(state.get("research_completed_at", state["completed_at"]))
    if (any(stamp.tzinfo is None for stamp in (start, generated, completed, current))
            or not start <= generated <= completed <= current
            or decision.get("cycle_date") != state.get("cycle_date")):
        raise ValueError("limited_status_decision_not_from_current_refresh")
    market = decision.get("market_gate", {})
    if (market.get("passed") is not True or market.get("complete_close_verified") is not True
            or market.get("failures") or market.get("expected_market_session") != state.get("expected_market_session")):
        raise ValueError("limited_status_market_not_validated")
    if decision.get("evidence_gate", {}).get("passed") is not False:
        raise ValueError("limited_status_missing_failed_evidence_gate")
    if not decision.get("workflow_integrity") or not decision.get("capital_decision"):
        raise ValueError("limited_status_current_contract_required")
    capital = decision["capital_decision"]
    if "evidence_gate_failed" not in capital.get("global_blockers", []):
        raise ValueError("limited_status_evidence_blocker_missing")
    if decision.get("automatic_action_allowed") is not False or any(
            decision.get("boundaries", {}).get(key) is not False
            for key in ("broker_connected", "broker_account_read", "order_code_created", "trade_placed")):
        raise ValueError("limited_status_execution_boundary_invalid")
    if (decision.get("eligible_action_review_candidates") or decision.get("eligible_new_position_review_candidates")
            or any(row.get("order_draft") or not _zero(row.get("shares"))
                   or row.get("decision") not in {"BLOCKED", "NO_ACTION", "HOLD"}
                   for row in capital.get("decisions", []))
            or any(row.get("eligible") is True for row in decision.get("tactical_review", {}).get("drafts", []))
            or any(not _zero(row.get("eligible_quantity", 0))
                   for row in decision.get("plan_continuity", {}).get("plans", []))):
        raise ValueError("limited_status_positive_order_not_allowed")
    validate_published_workflow(decision, root=root, current=current)
    validate_followthrough(decision, root=root, current=current)
    _, plain, html = render_email(decision)
    if ((root / ARTIFACTS["text"]).read_text() != plain
            or (root / ARTIFACTS["html"]).read_text() != html):
        raise ValueError("limited_status_brief_mismatch")


def validate_failure_shape(state: dict) -> None:
    from run_daily_refresh import STEP_SPECS, ADVISORY_STEPS
    if (state.get("schema_version") != "phase5r_daily_refresh_state_v1"
            or state.get("outcome") != "degraded_decision_created"
            or state.get("decision_created") is not True or state.get("hard_failures")
            or state.get("soft_failures") != ["official_evidence"]):
        raise ValueError("limited_status_failure_not_supported")
    steps = state.get("steps", [])
    if not isinstance(steps, list) or len(steps) != len(STEP_SPECS):
        raise ValueError("limited_status_steps_incomplete")
    rows = {row.get("name"): row for row in steps}
    if set(rows) != {name for name, _, _ in STEP_SPECS}:
        raise ValueError("limited_status_steps_incomplete")
    for name, script, allowed in STEP_SPECS:
        row = rows[name]
        if row.get("script") != script or row.get("allowed_to_fail") is not allowed:
            raise ValueError("limited_status_step_identity_invalid")
        if name == "official_evidence":
            if row.get("exit_code") == 0:
                raise ValueError("limited_status_failure_missing")
        elif name not in ADVISORY_STEPS and (row.get("exit_code") != 0 or row.get("outcome") != "passed"):
            raise ValueError("limited_status_required_stage_failed")
    if any(state.get(key) is not False for key in
           ("email_attempted", "email_sent", "broker_connected", "broker_account_read", "order_code_created")):
        raise ValueError("limited_status_refresh_boundary_invalid")


def make_limited_handoff(state: dict, *, root: Path, current: datetime) -> dict:
    validate_failure_shape(state)
    contents = {key: (root / path).read_bytes() for key, path in ARTIFACTS.items()}
    decision = json.loads(contents["decision"])
    validate_limited_decision(decision, state, root=root, current=current)
    hashes = {key: hashlib.sha256(raw).hexdigest() for key, raw in contents.items()}
    if any(hashes[key] != sha256_file(root / path) for key, path in ARTIFACTS.items()):
        raise ValueError("limited_status_artifact_changed_during_validation")
    return {"schema_version": SCHEMA, "mode": "limited_status_only",
            "new_order_authority": False, "failure": "official_evidence",
            "artifact_sha256": hashes}


def validate_limited_handoff(state: dict, *, root: Path, current: datetime) -> None:
    receipt = state.get("limited_status_handoff")
    if not isinstance(receipt, dict) or receipt != make_limited_handoff(state, root=root, current=current):
        raise ValueError("limited_status_handoff_missing_or_changed")
