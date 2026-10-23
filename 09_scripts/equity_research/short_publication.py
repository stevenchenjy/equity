"""Offline dependency closure after bounded public collection, never a sender.

This is a publication refresh, not a new completed company review or a passed
full research refresh. Actual analyst amendments still require the full chain.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, canonical_sha256, now_et, sha256_file
import short_assessment as short

SCHEMA = "equity_short_publication_refresh_v1"
STATE_REL = Path("00_project_control/run_logs/short_publication_refresh.local.json")
ARTIFACTS = ("04_research/company_research/daily_decision.json",
             "07_automation/email_briefs/daily_email_brief.txt",
             "07_automation/email_briefs/daily_email_brief.html")
# Rebuild the entire downstream decision closure. Collection, objective work,
# opportunity capital-escalation and experiments belong to the full review.
# No step here fetches network data or authors an analyst model/plan/thesis.
STEP_NAMES = ("market_refresh", "market_scoring", "earnings_event_discovery",
              "research_opportunity_intake", "earnings_incorporation",
              "current_research_baseline", "valuation_scenarios", "long_horizon_research",
              "research_backlog_view", "market_regime", "portfolio_outputs",
              "price_aware_review", "intraday_risk_projection", "daily_decision", "workflow_evaluation",
              "capital_allocation_validation", "evidence_packet", "current_status")


def _protected(root: Path, row: dict, current: datetime) -> dict:
    original = row["context"]["input_bindings"]
    account = short._hashes(root, short.ACCOUNT_MARKET)
    if account != original["account_market"]:
        raise ValueError("short_publication_account_or_market_changed")
    stores = short._hashes(root, short.MUTABLE_STORES)
    if stores.get(short.OPPORTUNITY_JOURNAL) is not None:
        from opportunity_contract import replay
        # A store's own hash cannot prove its retained original receipts still
        # exist. Recheck provenance even when the journal bytes did not change.
        replay(short._read(root, short.OPPORTUNITY_JOURNAL), root=root, current=current)
    changed = {p for p, digest in stores.items() if digest != original["stores"].get(p)}
    collector = None
    if short.OPPORTUNITY_JOURNAL in changed:
        collector = short._collector_journal_delta(root, row, current)
        if collector is not None:
            changed.remove(short.OPPORTUNITY_JOURNAL)
    if changed:
        raise ValueError("short_publication_analyst_amendment_requires_full_refresh")
    return {"account_market": account, "stores": stores, "collector_changes": collector}


def _live_row(root: Path, claim_id: str, current: datetime) -> dict:
    rows = [r for r in short._state(root)["slots"].values() if r.get("claim_id") == claim_id]
    if len(rows) != 1 or rows[0].get("status") != "claimed":
        raise ValueError("short_publication_live_claim_required")
    row = rows[0]
    if not short.aware(row["started_at"]) <= current < short.aware(row["expires_at"]):
        raise ValueError("short_publication_outside_claim_budget")
    return row


def _same_protected(before: dict, after: dict) -> bool:
    # Offline intake can append new source-validated collector observations.
    # _protected replays their full claim-bound chain; every analyst store and
    # account/market byte remains fixed.
    return (before["account_market"] == after["account_market"]
            and {k: v for k, v in before["stores"].items() if k != short.OPPORTUNITY_JOURNAL}
            == {k: v for k, v in after["stores"].items() if k != short.OPPORTUNITY_JOURNAL})


def validate_receipt(root: Path, row: dict, current: datetime) -> dict:
    """Revalidate evidence, current gates and exact artifacts at completion."""
    receipt = short._read(root, str(STATE_REL))
    value = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if (receipt.get("schema_version") != SCHEMA or receipt.get("claim_id") != row["claim_id"]
            or receipt.get("receipt_sha256") != canonical_sha256(value)
            or receipt.get("outcome") != "passed" or receipt.get("fully_passed_research") is not False
            or receipt.get("email_attempted") is not False or receipt.get("email_sent") is not False
            or receipt.get("market_snapshot_mode") != "reuse_validated_snapshot"
            or [s.get("name") for s in receipt.get("steps", [])] != list(STEP_NAMES)
            or any(s.get("exit_code") != 0 for s in receipt.get("steps", []))):
        raise ValueError("short_publication_valid_no_send_receipt_required")
    decision = short._validated_publication(root, current)
    generated = short.aware(decision.get("generated_at"))
    if not (short.aware(row["started_at"]) <= short.aware(receipt.get("started_at"))
            <= generated <= short.aware(receipt.get("completed_at")) <= current
            < short.aware(row["expires_at"])):
        raise ValueError("short_publication_receipt_outside_claim_budget")
    if short._hashes(root, ARTIFACTS) != receipt.get("artifacts"):
        raise ValueError("short_publication_artifact_changed")
    protected = _protected(root, row, current)
    if protected != receipt.get("protected_after") or not _same_protected(receipt["protected_before"], protected):
        raise ValueError("short_publication_protected_input_changed")
    return {"decision_sha256": receipt["artifacts"][ARTIFACTS[0]],
            "generated_at": generated.isoformat(), "email_sent": False,
            "refresh_outcome": "publication_dependency_closure_passed", "fully_passed_research": False,
            "safe_degraded_zero_order": False, "receipt_sha256": receipt["receipt_sha256"]}


def run(root: Path, claim_id: str, *, clock: Callable[[], datetime] = now_et,
        runtime_lock: Path | None = None, step_runner=None) -> dict:
    from run_daily_refresh import STEP_SPECS, CURRENT_STATUS_SPEC, MARKET_SNAPSHOT_REUSE, run_step
    if root.resolve() != ROOT.resolve() and step_runner is None:
        raise ValueError("short_publication_script_root_mismatch")
    runner = step_runner or run_step
    started = short.aware(clock())
    # Same order as the claim/completion writer; both locks are nonblocking.
    with ExclusiveFileLock(root / short.LOCK_REL), short._mutation_locks(root, runtime_lock=runtime_lock):
        row = _live_row(root, claim_id, started)
        protected = _protected(root, row, started)
        receipt = {"schema_version": SCHEMA, "claim_id": claim_id,
                   "started_at": started.isoformat(), "outcome": "running", "steps": [],
                   "protected_before": protected, "fully_passed_research": False,
                   "market_snapshot_mode": MARKET_SNAPSHOT_REUSE,
                   "email_attempted": False, "email_sent": False, "trade_placed": False}
        atomic_write_json(root / STATE_REL, receipt)
        specs = {s[0]: s for s in [*STEP_SPECS, CURRENT_STATUS_SPEC]}
        try:
            for name in STEP_NAMES:
                remaining = (short.aware(row["expires_at"]) - short.aware(clock())).total_seconds() - 5
                if remaining <= 0:
                    raise ValueError("short_publication_outside_claim_budget")
                spec = specs[name]
                result = runner(spec[0], spec[1], False, market_snapshot_mode=MARKET_SNAPSHOT_REUSE,
                                maximum_child_seconds=min(75, remaining))
                receipt["steps"].append(result)
                atomic_write_json(root / STATE_REL, receipt)
                if result.get("exit_code") != 0:
                    raise ValueError("short_publication_stage_failed:" + name)
            ended = short.aware(clock())
            _live_row(root, claim_id, ended)
            receipt.update(protected_after=_protected(root, row, ended), completed_at=ended.isoformat(),
                           artifacts=short._hashes(root, ARTIFACTS), outcome="passed")
            if not _same_protected(protected, receipt["protected_after"]):
                raise ValueError("short_publication_protected_input_changed")
            short._validated_publication(root, ended)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            receipt.update(outcome="failed", reason=str(error), completed_at=short.aware(clock()).isoformat())
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        immutable = root / short.RECEIPTS_REL / claim_id / ("publication-" + receipt["receipt_sha256"] + ".json")
        atomic_write_json(immutable, receipt)
        atomic_write_json(root / STATE_REL, receipt)
        return receipt
