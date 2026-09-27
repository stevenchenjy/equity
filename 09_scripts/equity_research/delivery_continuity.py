"""Delivery-only comparison against what the owner actually received.

Research fingerprints, current plan states, and eligibility are not changed.
Clock aging and unreviewed scanner churn stay in reports, not repeat emails.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from daily_common import canonical_sha256, recommendation_notification_fingerprint

MARKER = "delivery_meaning_v1="
RECEIPTS = {prefix + state for prefix in ("", "owner_review_", "correction_")
            for state in ("send_claimed", "sent", "delivery_unknown")}
CLOCK_STATES = {"maintained", "review_due", "expired_pending_verification",
                "time_exit_due_pending_verification"}
CLOCK_BLOCKERS = (CLOCK_STATES - {"maintained"}) | {
    "order_snapshot_requires_recheck",
    "sell_order_terminal_status_unverified",
}


def delivery_meaning_key(decision: dict[str, Any]) -> str:
    value = copy.deepcopy(decision)
    # Only genuinely eligible entries count as a new trading decision. Reviewed
    # company changes remain in workflow_meaning even when no entry is eligible.
    eligible = set(value.get("eligible_new_position_review_candidates", []))
    value["watch_candidates"] = [r for r in value.get("watch_candidates", []) if r.get("ticker") in eligible]
    value.pop("independent_market_discovery", None)
    tactical = value.get("tactical_review", {})
    tactical["drafts"] = [r for r in tactical.get("drafts", []) if r.get("eligible") is True]
    if not tactical["drafts"]:
        # Rejected entry diagnostics are not a changed recommendation. Market,
        # evidence and account gates are still hashed independently below.
        tactical["blockers"] = []
    if "open_orders" in tactical:
        # Freshness/expiry can make the same recorded order list incomplete.
        # Actual order facts remain hashed; eligibility changes are retained.
        # This projection never changes the real completeness/sizing guard.
        tactical["open_orders"]["complete"] = False
    for order in tactical.get("open_orders", {}).get("orders", []):
        # Actual broker status/quantity/price remain; a local aging label is not
        # evidence of an execution, cancellation, or replacement.
        order.pop("review_status", None)
    for row in value.get("plan_continuity", {}).get("plans", []):
        if row.get("status") in CLOCK_STATES:
            row["status"] = "retained_plan"
            # The immutable record hash binds the original action; the runtime
            # projection can relabel it reconcile_plan when its clock expires.
            row["action"] = "retained_record"
            row["blockers"] = [b for b in row.get("blockers", []) if b != "order_snapshot_requires_recheck"]
    # Scope maps repeat some derived clock labels. Normalize them only for
    # delivery comparison; proposal eligibility, raw orders, account changes
    # and the production/publication gates remain independently bound.
    for context in (value.get("plan_continuity", {}), value.get("workflow_integrity", {})):
        for field in ("blockers", "global_blockers"):
            if field in context:
                context[field] = [b for b in context[field] if b not in CLOCK_BLOCKERS]
        for field in ("ticker_blockers", "strategy_blockers"):
            context[field] = {name: kept for name, codes in context.get(field, {}).items()
                              if (kept := [b for b in codes if b not in CLOCK_BLOCKERS])}
    context = value.get("plan_continuity", {})
    if context.get("status") in {"current", "needs_reconciliation"}:
        context["status"] = "retained_context"
    # Financial refreshes for an unrelated screened-out company are not a
    # changed portfolio conclusion. Held/reviewed companies remain covered.
    relevant = {r.get("ticker") for r in value.get("held_positions", [])} | eligible
    relevant.update(value.get("long_horizon_research", {}).get("candidate_views", {}))
    incorporation = value.get("earnings_incorporation", {})
    if "companies" in incorporation:
        incorporation["companies"] = {k: v for k, v in incorporation["companies"].items() if k in relevant}
    # Share/cash changes matter even if eligibility is blocked. Price-marked
    # account totals do not: a planning estimate must not look like a deposit.
    account = value.get("account", {})
    quantities = sorted((r.get("ticker"), str(r.get("current_shares")))
                        for r in value.get("held_positions", []))
    facts = {key: account.get(key) for key in ("cash_available", "cash_reserved", "cash_basis")}
    return MARKER + canonical_sha256({"recommendation": recommendation_notification_fingerprint(value),
                                     "shares": quantities, "cash": facts})


def covered_by_last_delivery(rows: list[dict[str, str]], decision: dict[str, Any], *,
                             current: datetime, archive_dir: Path) -> bool:
    """Compare only the latest receipt, never search past a changed risk alert.

Legacy migration accepts only an archived decision whose exact bytes match the
receipt's SHA-256. Unknown/missing evidence does not suppress a message.
"""
    candidates = []
    for index, row in enumerate(rows):
        if row.get("status") not in RECEIPTS:
            continue
        try:
            stamp = datetime.fromisoformat(row.get("timestamp", "").replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp > current:
                continue
        except (ValueError, TypeError):
            continue
        candidates.append((stamp, index, row))
    if not candidates:
        return False
    row = max(candidates, key=lambda item: (item[0], item[1]))[2]
    prior = next((part for part in row.get("reason", "").split(";")
                  if re.fullmatch(MARKER + r"[0-9a-f]{64}", part)), None)
    if prior is None:
        digest = row.get("decision_sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return False
        try:
            raw = (archive_dir / (digest + ".json")).read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                return False
            prior = delivery_meaning_key(json.loads(raw))
        except (OSError, ValueError, TypeError, KeyError):
            return False
    return prior == delivery_meaning_key(decision)
