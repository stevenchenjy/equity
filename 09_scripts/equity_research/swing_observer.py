"""Public observation in the owner's existing review windows; no analyst slot.

The installed bounded poll observes at most three already selected research
stocks. It never runs the full pipeline, renews a plan, sends, or trades. Every
mutation uses the existing nonblocking runtime/pipeline locks and defers to an
active short claim. The canonical account and delivery inputs are untouched.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, time
import hashlib
import json
from pathlib import Path
import uuid

from daily_common import ET, ExclusiveFileLock, atomic_write_json, now_et
from investment_plans import regular_close
import intraday_prices
import swing_candidate_quotes

REL = "00_project_control/run_logs/swing_observer.local"
WINDOWS = ((time(9, 45), time(10, 45)), (time(14, 45), time(15, 20)))
POLL_INTERVAL_SECONDS = 180
MAX_WORKER_SECONDS = 75


def due_window(current: datetime) -> dict | None:
    current = intraday_prices._now(current)
    if not intraday_prices.market_open(current):
        return None
    close = regular_close(current.date().isoformat())
    for index, (start, end) in enumerate(WINDOWS):
        begins = datetime.combine(current.date(), start, ET)
        ends = min(datetime.combine(current.date(), end, ET), close)
        if begins <= current < ends:
            return {"id": f"{current.date()}/{'morning' if index == 0 else 'afternoon'}",
                    "starts_at": begins.isoformat(), "ends_at": ends.isoformat()}
    return None


def _configuration(root: Path) -> None:
    state = json.loads((root / "00_project_control/active_decision_state.yaml").read_bytes())
    inhibit = json.loads((root / "07_automation/scheduler/maintenance_inhibit.local.json").read_bytes())
    required = {"current_workflow": "daily_decision", "active_pipeline": "phase5r_daily",
                "broker_connection_allowed": "no", "order_code_allowed": "no", "manual_execution_only": "yes"}
    if any(state.get(k) != v for k, v in required.items()):
        raise ValueError("swing_observer_active_boundary_unverified")
    if inhibit.get("active") is not False or inhibit.get("allowed_pipeline") != "phase5r_daily":
        raise ValueError("swing_observer_maintenance_inhibit")


def active_claim(root: Path, current: datetime) -> str | None:
    path = root / "00_project_control/run_logs/short_assessment.local.json"
    if not path.exists():
        return None
    state = json.loads(path.read_bytes())
    for row in state.get("slots", {}).values():
        if row.get("status") == "claimed":
            if intraday_prices._stamp(row["expires_at"]) > current:
                return str(row.get("claim_id", "active_short"))
    return None


def _receipt(root: Path, value: dict) -> dict:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = intraday_prices._safe_target(root, f"{REL}/receipts/{digest}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("swing_observer_receipt_conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    atomic_write_json(intraday_prices._safe_target(root, f"{REL}/current.json"), {
        "receipt": {"path": str(path.relative_to(root)), "sha256": digest},
        "status": value["status"], "completed_at": value["completed_at"]})
    return value


def run(root: Path, *, current=None, clock=now_et, runtime_lock=None,
        collector=None, builder=None, targets=None) -> dict:
    root = Path(root)
    current = intraday_prices._now(current or clock())
    result = {"schema_version": "equity_swing_observer_receipt_v1", "started_at": current.isoformat(),
              "status": "outside_review_window", "network_attempted": False,
              "research_slot_consumed": False, "fully_passed_research": False,
              "capital_authority": False, "email_sent": False, "trade_placed": False}
    window = due_window(current)
    if not window:
        return result
    result["window"] = window
    _configuration(root)
    if active_claim(root, current):
        return dict(result, status="deferred_active_short_claim")
    runtime_lock = Path(runtime_lock) if runtime_lock else root.parent / ".locks/equity-research-runtime.lock"
    with ExitStack() as locks:
        try:
            locks.enter_context(ExclusiveFileLock(runtime_lock))
            locks.enter_context(ExclusiveFileLock(root / "00_project_control/run_logs/daily_pipeline.lock"))
        except RuntimeError:
            return dict(result, status="deferred_mutation_lock")
        actual = intraday_prices._now(clock())
        if not due_window(actual) or active_claim(root, actual):
            return dict(result, status="deferred_changed_window_or_claim")
        _configuration(root)
        from swing_research_v2 import build as default_builder, quote_targets as default_targets
        builder, targets = builder or default_builder, targets or default_targets
        collector = collector or swing_candidate_quotes.collect
        identity = "swing-observer-" + uuid.uuid4().hex
        # An interrupted new attempt must never revive a preceding good mark.
        swing_candidate_quotes.record_failure(root, current=actual, claim_id=identity,
                                              reason="swing_observation_in_progress")
        try:
            # Freeze actual first detection before observing a possible entry.
            before = builder(root, current=actual, capture=True)
            selected = targets(root, actual, limit=swing_candidate_quotes.MAX_TARGETS) if before.get("status") == "experimental_current" else []
            if before.get("status") != "experimental_current":
                after = before
                reason = str((before.get("blockers") or ["swing_study_source_unavailable"])[0])[:300]
                result.update(status="waiting_on_data", targets=[], quote_status="unavailable", failure=reason)
                swing_candidate_quotes.record_failure(root, current=intraday_prices._now(clock()),
                                                      claim_id=identity, reason=reason)
            elif selected:
                observed = collector(root, current=intraday_prices._now(clock()), claim_id=identity)
                result.update(network_attempted=observed.get("request_count", 0) > 0, targets=selected,
                              quote_status=observed["status"], quote_source=observed.get("source"))
                after = builder(root, current=intraday_prices._now(clock()), capture=True,
                                candidate_quote_context=observed)
            else:
                after = before
                result.update(targets=[], quote_status="no_candidates")
            if before.get("status") == "experimental_current":
                result["status"] = ("observed" if observed.get("status") in {"current", "partial"}
                                    else "unavailable_quotes") if selected else "no_candidates"
            result.update(study_status=after.get("status"), study_version=after.get("version"),
                          analysis_completed=False)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            result.update(status="failed", failure=str(exc), analysis_completed=False)
            swing_candidate_quotes.record_failure(root, current=intraday_prices._now(clock()),
                                                  claim_id=identity, reason=str(exc)[:300] or "swing_observer_failed")
        result["completed_at"] = intraday_prices._now(clock()).isoformat()
        return _receipt(root, result)
