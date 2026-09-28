"""Read and present recurring work without granting decision authority."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

BACKLOG_REL = Path("04_research/company_research/research_backlog.local.json")


def work_health(payload: Any, refresh: dict, *, current: datetime, step: str) -> dict:
    """A prior success file cannot conceal a failed or stale scheduled step."""
    result = dict(payload) if isinstance(payload, dict) else {}
    present = bool(result)
    fresh = False
    try:
        stamp = datetime.fromisoformat(str(result.get("generated_at", "")).replace("Z", "+00:00"))
        fresh = stamp.tzinfo is not None and stamp <= current and stamp.astimezone(current.tzinfo).date() == current.date()
    except (ValueError, TypeError):
        pass
    result["freshness"] = "current" if fresh else "stale_or_unverified"
    if not fresh:
        result["status"] = "stale_or_unverified" if present else "missing_or_invalid"
    rows = refresh.get("steps", [])
    latest = next((r for r in reversed(rows) if isinstance(r, dict) and r.get("name") == step), {}) if isinstance(rows, list) else {}
    if (refresh.get("cycle_date") == current.date().isoformat()
            and isinstance(latest.get("exit_code"), int) and latest["exit_code"] != 0):
        result.update(status="failed", failure_code="current_refresh_step_failed", refresh_step_exit_code=latest["exit_code"])
    result["automatic_action_allowed"] = False
    return result


def read_backlog_summary(root: Path, *, current: datetime, refresh: dict | None = None) -> dict:
    try:
        from research_backlog import validate_report
        raw = json.loads((root / BACKLOG_REL).read_text())
        validate_report(raw, root=root, current=current)
        # Receipts and complete history stay in the private backlog artifact.
        result = {k: raw[k] for k in ("schema_version", "status", "generated_at", "priority_queue",
                  "selected_tickers", "completion_summary", "failure_code", "attempt_summary", "counts",
                  "attempts_latest_run", "objective_dossiers_completed", "financial_fields_completed",
                  "canonical_numeric_updates") if k in raw}
    except (OSError, ValueError, TypeError):
        result = {"status": "missing_or_invalid"}
    result = work_health(result, refresh or {}, current=current, step="research_backlog")
    attempt_path = root / "08_reviews/research_backlog.local/last_run.json"
    if attempt_path.exists():
        try:
            attempt = json.loads(attempt_path.read_text())
            start = datetime.fromisoformat(attempt["started_at"])
            end = datetime.fromisoformat(attempt["completed_at"])
            if (attempt.get("schema_version") != "equity_research_backlog_run_v1"
                    or start.tzinfo is None or end.tzinfo is None or not start <= end <= current
                    or type(attempt.get("exit_code")) is not int):
                raise ValueError("invalid_attempt")
            generated = datetime.fromisoformat(str(result.get("generated_at", "")))
            if generated.tzinfo is None:
                raise ValueError("invalid_generation")
            if attempt["exit_code"] != 0 and end >= generated:
                result.update(status="failed", failure_code="latest_backlog_attempt_failed", latest_attempt=attempt)
        except (OSError, ValueError, TypeError, KeyError):
            result.update(status="unverified", failure_code="backlog_attempt_receipt_invalid")
    return result


def _money(value: Any) -> str:
    try:
        amount = Decimal(str(value))
        return f"${amount:,.2f}" if amount.is_finite() and amount >= 0 else "unverified"
    except (InvalidOperation, ValueError, TypeError):
        return "unverified"


def cash_lines(decision: dict) -> list[str]:
    queue = decision.get("capital_work_queue", {})
    if not queue:
        return []
    cash = queue.get("cash_explanation", {})
    if queue.get("status") != "current" or cash.get("status") != "planning_only":
        return ["Cash follow-through is unverified; the prior work history is retained. No new allocation is implied."]
    scope = decision.get("workflow_integrity", {})
    reasons = []
    if scope.get("global_blockers", scope.get("blockers", [])):
        reasons.append("account-wide verification")
    if scope.get("ticker_blockers"):
        reasons.append("ticker-specific plan or research checks")
    if queue.get("top_opportunities"):
        reasons.append("entry and valuation conditions")
    return [f"Cash use: {_money(cash.get('strategic_reserve_usd'))} retained reserve; "
            f"{_money(cash.get('unallocated_research_cash_usd'))} awaiting qualified opportunities.",
            "Pending checks: " + (", ".join(reasons) or "the existing evidence and execution checks")
            + ". Reasons overlap; they are not additional dollar allocations.",
            f"Next routine research window: {queue.get('next_automatic_review_at') or 'unverified'} "
            f"(schedule as of {queue.get('generated_at') or decision.get('generated_at') or 'unverified'}). "
            "Earlier publication slots are conditional recovery checks, skipped after a successful refresh. "
            "Start depends on host availability and scheduler polling; execution funds still require confirmation."]


def research_lines(decision: dict, *, detailed: bool = False) -> list[str]:
    queue = decision.get("capital_work_queue", {})
    backlog = decision.get("research_backlog", {})
    lines = []
    if backlog:
        selected = [r for r in backlog.get("priority_queue", []) if isinstance(r, dict) and r.get("ticker")]
        names = ", ".join(r["ticker"] for r in selected[:3])
        lines.append(f"Objective research: {backlog.get('status', 'unverified')}" + (f"; priority work: {names}" if names else "")
                     + ". Official numerical evidence can be completed automatically; thesis and valuation judgments remain separate.")
        if backlog.get("status") == "ready" and backlog.get("freshness") == "current":
            completed_names = ", ".join(backlog.get("selected_tickers", []))
            lines.append(f"This run: {backlog.get('objective_dossiers_completed', 0)} source-bound dossiers; "
                         f"{backlog.get('financial_fields_completed', 0)} financial fields completed"
                         + (f"; processed {completed_names}" if completed_names else "")
                         + ". These are research outputs, not completed investment cases.")
        if detailed:
            for row in selected[:3]:
                fields = ", ".join(v.replace("_", " ") for v in row.get("financial_gaps_remaining", []))
                reasons = ", ".join(v.replace("_", " ") for v in row.get("priority_reasons", []))
                lines.append(f"- {row['ticker']}: financial gaps {fields or 'none identified in this check'}; "
                             f"{row.get('manual_gap_count', 'unverified')} reasoning gaps. Priority: {reasons or 'recorded backlog order'}.")
    if queue.get("status") == "current":
        if queue.get("plan_reassessment_status") == "unverified":
            lines.append("Plan reassessment coverage is unverified; retained tasks remain unresolved historical work.")
        for row in queue.get("top_opportunities", [])[:3]:
            lines.append(f"{row['ticker']} next: {row['next_step']}")
        pending = queue.get("plan_reassessment_queue", [])
        if pending:
            lines.append("Plan reassessment queue: " + ", ".join(r["ticker"] for r in pending)
                         + ". Original purposes and deadlines remain recorded; expiry does not renew a plan.")
            if detailed:
                for row in pending:
                    lines.append(f"- {row['ticker']} ({row['source_status']}): {row['next_step']} "
                                 f"Next review: {row['next_review_at']}; original deadline: "
                                 f"{row.get('original_time_exit_at') or row.get('original_review_at') or 'unverified'}.")
    elif queue:
        lines.append("Recurring opportunity and reassessment queue is unverified; inspect the current status before relying on it.")
    return lines


def report_section(decision: dict) -> str:
    return "\n\n".join(["## 现金后续工作与每日研究优先项", *cash_lines(decision), *research_lines(decision, detailed=True)])
