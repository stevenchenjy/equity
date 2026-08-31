#!/usr/bin/env python3
"""Generate one concise current Phase 5R production status artifact."""

from __future__ import annotations

import json
import os
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from phase5r_active_config import ACTIVE_CONFIG_PATH, load_active_config
from phase5r_daily_common import (
    ACCOUNT_STATE_PATH,
    DAILY_DECISION_JSON_PATH,
    DAILY_REFRESH_STATE_PATH,
    EVIDENCE_STATUS_PATH,
    MARKET_SNAPSHOT_PATH,
    ROOT,
    atomic_write_json,
    atomic_write_text,
    iso_now,
    read_csv,
    read_json,
)


STATUS_JSON_PATH = ROOT / "00_project_control" / "phase5r_current_production_status.local.json"
STATUS_MD_PATH = ROOT / "00_project_control" / "phase5r_current_production_status.local.md"
VALUATION_PATH = ROOT / "04_data" / "phase5r" / "phase5r_valuation_scenarios.local.json"
SNAPSHOT_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_snapshots.local.jsonl"
)
OUTCOME_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_outcomes.local.csv"
)
OBSERVATION_PATH = (
    ROOT / "00_project_control" / "phase5r_production_shadow_v1"
    / "observation_state.json"
)
SHADOW_LEDGER_PATH = (
    ROOT / "08_reviews" / "phase5r_production_shadow_v1"
    / "ledger" / "production_shadow_ledger.jsonl"
)


def jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def shadow_cost() -> str:
    total = Decimal("0")
    if SHADOW_LEDGER_PATH.exists():
        for line in SHADOW_LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line).get("metered_cost_usd")
                if value not in {None, "", "unknown"}:
                    total += Decimal(str(value))
            except (json.JSONDecodeError, InvalidOperation, AttributeError):
                continue
    return format(total, ".6f")


def model_authorization_is_blocker(
    config: dict[str, Any],
    observation: dict[str, Any],
    environment: dict[str, str] | None = None,
) -> bool:
    active_environment = os.environ if environment is None else environment
    model_status = str(config.get("model_policy", {}).get("status", ""))
    return (
        not model_status.startswith("removed_from_active_production_path_")
        and not active_environment.get("OPENAI_API_KEY")
        and observation.get("completed_review_count", 0) < 10
    )


def main() -> int:
    config = load_active_config()
    refresh = read_json(DAILY_REFRESH_STATE_PATH, {})
    evidence = read_json(EVIDENCE_STATUS_PATH, {})
    decision = read_json(DAILY_DECISION_JSON_PATH, {})
    account = read_json(ACCOUNT_STATE_PATH, {})
    valuation = read_json(VALUATION_PATH, {"records": []})
    observation = read_json(OBSERVATION_PATH, {})
    market_rows = read_csv(MARKET_SNAPSHOT_PATH)
    valid_market = [row for row in market_rows if row.get("data_quality_label") in {"ok", "partial"}]
    sessions = sorted({row.get("market_session_date", "") for row in valid_market if row.get("market_session_date")})
    blockers: list[str] = []
    if refresh.get("outcome") != "passed":
        blockers.append("deterministic_refresh_not_fully_passed")
    if not valid_market:
        blockers.append("current_market_snapshot_invalid")
    if evidence.get("scan_status") != "ok":
        blockers.append(str(evidence.get("reason") or "official_evidence_refresh_not_ok"))
    if model_authorization_is_blocker(config, observation):
        blockers.append("optional_openai_shadow_authorization_absent")
    completed_valuations = sum(
        row.get("status") == "complete" for row in valuation.get("records", [])
        if isinstance(row, dict)
    )
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unavailable"
    status: dict[str, Any] = {
        "schema_version": "phase5r_current_production_status_v1",
        "generated_at": iso_now(),
        "active_config": str(ACTIVE_CONFIG_PATH.relative_to(ROOT)),
        "git_commit": commit,
        "deterministic_refresh": {
            "outcome": refresh.get("outcome", "missing"),
            "completed_at": refresh.get("completed_at", ""),
            "hard_failures": refresh.get("hard_failures", []),
            "soft_failures": refresh.get("soft_failures", []),
        },
        "market": {
            "latest_completed_session": sessions[-1] if sessions else "",
            "valid_rows": len(valid_market),
            "total_rows": len(market_rows),
        },
        "official_evidence": {
            "status": evidence.get("scan_status", "missing"),
            "reason": evidence.get("reason", ""),
            "held_coverage_complete": evidence.get("held_coverage_complete", False),
            "last_success_at": evidence.get("last_success_at", ""),
        },
        "decision": {
            "code": decision.get("decision_code", "missing"),
            "headline": decision.get("headline", ""),
            "send_recommended": decision.get("send_recommended", False),
            "send_reason": decision.get("send_reason", ""),
            "next_review": decision.get("next_scheduled_review", ""),
        },
        "account": {
            "cash_available": account.get("cash_available"),
            "cash_reserved": account.get("cash_reserved"),
            "position_truth": "manual local cash and whole shares",
            "last_manual_update": account.get("last_updated", ""),
        },
        "valuation": {
            "complete_records": completed_valuations,
            "total_records": len(valuation.get("records", [])),
            "policy": valuation.get("policy", ""),
        },
        "outcomes": {
            "recommendation_snapshots": jsonl_count(SNAPSHOT_PATH),
            "evaluated_horizon_rows": len(read_csv(OUTCOME_PATH)),
        },
        "model": {
            "status": config["model_policy"]["status"],
            "completed_real_shadow_observations": observation.get("completed_review_count", 0),
            "target_real_shadow_observations": 10,
            "metered_cost_usd": shadow_cost(),
            "monthly_hard_cap_usd": config["model_policy"]["monthly_hard_cap_usd"],
            "api_authorized_in_this_runtime": bool(os.environ.get("OPENAI_API_KEY")),
        },
        "blockers": sorted(set(blockers)),
        "boundaries": config["boundaries"],
    }
    atomic_write_json(STATUS_JSON_PATH, status)
    lines = [
        "# Phase 5R current production status",
        "",
        f"Generated: `{status['generated_at']}`",
        "",
        f"- Deterministic refresh: `{status['deterministic_refresh']['outcome']}`.",
        f"- Market: `{status['market']['valid_rows']}/{status['market']['total_rows']}` valid rows; latest completed session `{status['market']['latest_completed_session'] or 'none'}`.",
        f"- SEC evidence: `{status['official_evidence']['status']}`; held coverage `{status['official_evidence']['held_coverage_complete']}`.",
        f"- Decision: `{status['decision']['code']}`; email `{status['decision']['send_reason'] or 'not generated'}`.",
        f"- Valuation: `{status['valuation']['complete_records']}/{status['valuation']['total_records']}` complete records.",
        f"- Outcome evidence: `{status['outcomes']['recommendation_snapshots']}` snapshots, `{status['outcomes']['evaluated_horizon_rows']}` evaluated horizon rows.",
        f"- Optional model: `{status['model']['completed_real_shadow_observations']}/10` real observations; metered cost `${status['model']['metered_cost_usd']}`; monthly hard cap `${status['model']['monthly_hard_cap_usd']}`.",
        f"- Current blockers: `{', '.join(status['blockers']) or 'none'}`.",
        "- Boundaries: research only; no broker read, automatic order, or trade placement.",
        "",
        "This generated file and `phase5r_active_production_config.json` are the current authority. Older pilot registries and dated reports are historical evidence only.",
    ]
    atomic_write_text(STATUS_MD_PATH, "\n".join(lines) + "\n")
    print(
        f"current_status_written=true refresh={refresh.get('outcome', 'missing')} "
        f"blockers={len(status['blockers'])} broker_connected=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
