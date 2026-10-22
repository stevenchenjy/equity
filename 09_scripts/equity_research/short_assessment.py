"""Bounded, source-bound intraday analyst handoffs; no sender or trade authority.

The clock reserves work, not analytical completion. A chat worker uses the
existing writers and later completes this receipt. Unchanged inputs, closed
sessions and busy refresh locks never start a second full research pipeline.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from contextlib import ExitStack
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

from daily_common import (ET, ROOT, ExclusiveFileLock, atomic_write_json,
                          canonical_sha256, is_us_market_session_date,
                          read_json, sha256_file)
from investment_plans import CALENDAR_SOURCE, regular_close
from account_access import ACCOUNT_INPUTS
from workflow_inputs import WORKFLOW_INPUTS

SCHEMA = "equity_short_assessment_v1"
STATE_REL = Path("00_project_control/run_logs/short_assessment.local.json")
LOCK_REL = Path("00_project_control/run_logs/short_assessment.lock")
RECEIPTS_REL = Path("08_reviews/analyst_followthrough.local/short_assessments")
SLOTS = ("09:30", "11:00", "12:30", "14:00", "15:30")
SLOT_GRACE = timedelta(minutes=15)
MAX_DURATION = timedelta(minutes=10)
PUBLIC_MAX_AGE = timedelta(minutes=75)
AUTHORITY = {"automatic_action_allowed": False, "execution_authority": False,
             "canonical_admission": False, "email_sent": False, "trade_placed": False}
MUTABLE_STORES = (
    "05_risk_and_positions/investment_plans.local.json",
    "04_research/company_research/thesis_dossiers.local.json",
    "04_data/equity_research/company_valuation_admissions.local.json",
    "04_data/equity_research/valuation_research_inputs.local.json",
    "04_research/company_research/opportunities.local/store.json",
    "04_research/company_research/priority_reviews.local.json",
)
ACCOUNT_MARKET = (*ACCOUNT_INPUTS,
    "03_source_data/equity_research/market_data_snapshot.csv",
    "03_source_data/equity_research/market_feed.local/current.json",
)
OTHER_INPUTS = (
    "03_source_data/equity_research/daily_evidence_ledger.csv",
    "03_source_data/equity_research/earnings_incorporation_status.local.json",
    "04_data/equity_research/valuation_scenarios.local.json",
    "04_research/company_research/issuer_news_review_queue.local.jsonl",
    "06_execution_records/dashboard_feedback_pending.local.json",
)


def _recomposition_step(root: Path) -> dict:
    return {"operation": "full_no_send_recomposition", "release_mutation_locks_first": True,
            "cwd": str(root), "argv": ["/usr/bin/env", "PHASE5R_FULL_REFRESH_REUSE_ONLY_20260901_7C31=1",
                str(Path.home() / "Library/Application Support/EquityResearch/bin/dailyrefresh_launcher.py")],
            "investment_amendment_required": False,
            "then": "Inspect the typed current decision and exact final text/HTML, then complete this claim. A failed research gate remains effective."}


def _validated_publication(root: Path, current: datetime) -> dict:
    from workflow_integrity import validate_published_workflow
    from delivery_assessments import delivery_policy_context, priority_review_context
    from email_brief import render_email
    decision = _read(root, "04_research/company_research/daily_decision.json")
    if (decision.get("workflow_integrity", {}).get("schema_version") != "equity_workflow_integrity_v1"
            or decision.get("assessment_delivery_policy") != delivery_policy_context(root)
            or decision.get("analyst_priority_review") != priority_review_context(root, current=current)):
        raise ValueError("short_assessment_typed_current_publication_required")
    validate_published_workflow(decision, root=root, current=current)
    _subject, text, html = render_email(decision)
    for path, expected in (("07_automation/email_briefs/daily_email_brief.txt", text),
                           ("07_automation/email_briefs/daily_email_brief.html", html)):
        if _inside(root, path).read_text(encoding="utf-8") != expected:
            raise ValueError("short_assessment_final_email_recomposition_required")
    return decision


def aware(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
        return stamp.astimezone(ET)
    except (ValueError, TypeError):
        raise ValueError("short_assessment_aware_timestamp_required") from None


def market_session(current: datetime) -> dict:
    local = aware(current)
    day = local.date()
    result = {"session_date": day.isoformat(), "market_open": False,
              "calendar_source": CALENDAR_SOURCE, "open_at": None, "close_at": None}
    if not is_us_market_session_date(day):
        return {**result, "reason": "exchange_closed"}
    try:
        close = regular_close(day.isoformat())
    except ValueError:
        return {**result, "reason": "exchange_calendar_unverified"}
    opened = datetime.combine(day, time(9, 30), ET)
    return {**result, "open_at": opened.isoformat(), "close_at": close.isoformat(),
            "market_open": opened <= local < close,
            "reason": "open" if opened <= local < close else "outside_regular_session"}


def due_slot(current: datetime) -> dict:
    local = aware(current)
    session = market_session(local)
    if not session["market_open"]:
        return {"outcome": "not_due", "reason": session["reason"], "session": session}
    close = aware(session["close_at"])
    for clock in reversed(SLOTS):
        start = datetime.combine(local.date(), time.fromisoformat(clock), ET)
        if start < close and start <= local < min(start + SLOT_GRACE, close):
            return {"outcome": "due", "slot": clock, "slot_id": local.date().isoformat() + "/" + clock,
                    "scheduled_at": start.isoformat(), "session": session}
    return {"outcome": "not_due", "reason": "outside_slot_grace_no_catchup", "session": session}


def _configured_due(root: Path, current: datetime) -> dict:
    notifications = _read(root, "00_project_control/active_production_config.json").get("notifications", {})
    effective = notifications.get("delivery_assessment_effective_from")
    if not effective or aware(current).date().isoformat() < effective:
        return {"outcome": "not_due", "reason": "short_assessments_not_active"}
    if (notifications.get("short_assessment_slots_et") != list(SLOTS)
            or notifications.get("short_assessment_budget_minutes") != 10):
        raise ValueError("short_assessment_configuration_invalid")
    return due_slot(current)


def _inside(root: Path, relative: Any) -> Path:
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or ".." in Path(relative).parts):
        raise ValueError("short_assessment_source_path_invalid")
    candidate = root / relative
    if (candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve())
            or not candidate.is_file()):
        raise ValueError("short_assessment_source_not_regular")
    return candidate


def _hashes(root: Path, paths) -> dict:
    return {str(p): sha256_file(_inside(root, str(p))) if (root / p).exists() else None for p in paths}


def _read(root: Path, relative: str, default=None):
    return read_json(root / relative, {} if default is None else default)


def _state(root: Path) -> dict:
    value = _read(root, str(STATE_REL), {"schema_version": SCHEMA, "slots": {}, "last_completed_fingerprint": None})
    if value.get("schema_version") != SCHEMA or not isinstance(value.get("slots"), dict):
        raise ValueError("short_assessment_state_invalid")
    return value


def _save_receipt(root: Path, receipt: dict) -> None:
    # Each transition is immutable; the slot state only points at its latest receipt.
    relative = RECEIPTS_REL / receipt["claim_id"] / (receipt["transition_id"] + ".json")
    if (root / relative).exists():
        raise ValueError("short_assessment_receipt_already_exists")
    atomic_write_json(root / relative, receipt)
    receipt["receipt_path"] = str(relative)


def _transition(root: Path, row: dict, current: datetime, **changes) -> dict:
    result = {**row, **changes, "transition_id": uuid.uuid4().hex,
              "recorded_at": current.isoformat(), **AUTHORITY}
    result.pop("receipt_path", None)
    _save_receipt(root, result)
    return result


def _record_missed(root: Path, state: dict, current: datetime) -> None:
    session = market_session(current)
    if not session["market_open"]:
        return
    for clock in SLOTS:
        scheduled = datetime.combine(current.date(), time.fromisoformat(clock), ET)
        slot_id = current.date().isoformat() + "/" + clock
        if scheduled + SLOT_GRACE <= current and slot_id not in state["slots"]:
            state["slots"][slot_id] = _transition(root, {
                "claim_id": uuid.uuid4().hex, "slot_id": slot_id,
                "scheduled_at": scheduled.isoformat(), "status": "missed",
                "started_at": None, "ended_at": current.isoformat()}, current,
                reason="missed_slot_not_replayed")


def _resumable_work(state: dict, current: datetime) -> bool:
    pending = state.get("pending_work", {})
    if pending.get("status") == "continue_analysis":
        return True
    next_review = pending.get("next_review_at")
    return bool(next_review and aware(next_review) <= current)


def _public_due(root: Path, current: datetime) -> bool:
    for relative, key in (("03_source_data/equity_research/official_news_status.local.json", "last_attempt_at"),
                          ("03_source_data/equity_research/earnings_events.local/last_run.json", "completed_at")):
        value = _read(root, relative)
        try:
            age = current - aware(value[key])
            if not timedelta(0) <= age <= PUBLIC_MAX_AGE:
                return True
        except (KeyError, ValueError):
            return True
    return False


def refresh_public_handoff(root: Path, current: datetime, *, runner: Callable = subprocess.run) -> dict:
    """Explicit bounded news/calendar GETs only; never Massive or a full refresh."""
    if not _public_due(root, current):
        return {"status": "retained_recent_observations", "network_attempted": False, "children": []}
    children = []
    for script, timeout in (("refresh_official_news.py", 90), ("refresh_earnings_events.py", 90)):
        command = [sys.executable, str(root / "09_scripts/equity_research" / script), "--refresh"]
        try:
            child = runner(command, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout, check=False)
            code = child.returncode
        except (OSError, subprocess.TimeoutExpired):
            code = 124
        children.append({"script": script, "exit_code": code, "timeout_seconds": timeout})
    return {"status": "completed" if all(r["exit_code"] == 0 for r in children) else "failed_or_incomplete",
            "network_attempted": True, "children": children,
            "coverage_is_analytical_completion": False}


def build_context(root: Path, current: datetime, *, handoff: dict | None = None) -> dict:
    from earnings_events import summary as earnings_summary
    from official_news import read_official_news_status
    from workflow_integrity import news_meaning
    errors = []
    try:
        news = read_official_news_status(now=current,
            manifest_path=root / "01_policies/official_news_sources.json",
            status_path=root / "03_source_data/equity_research/official_news_status.local.json",
            events_path=root / "03_source_data/equity_research/official_news_events.local.json")
        news_value = news_meaning(news)
    except (OSError, ValueError, KeyError, TypeError):
        news_value = {"status": "unverified"}
        errors.append("official_news_unverified")
    try:
        earnings = earnings_summary(root, current=current)
        # Raw calendar polling hashes/clocks are not new research. A changed
        # company/date/session, deadline crossing or review remains meaningful.
        events = [{k: e.get(k) for k in ("event_id", "ticker", "event_date", "session", "event_at",
            "research_deadline_at", "status", "timing", "schedule_version", "assessment_sha256")}
            for e in earnings.get("events", [])]
        events.sort(key=lambda row: str(row["event_id"]))
        earnings_value = {"status": earnings.get("status"), "events": events,
                          "failed_dates": earnings.get("coverage", {}).get("failed_dates", [])}
        upcoming = sorted((e for e in earnings.get("events", []) if e.get("timing") == "pre_event"),
                          key=lambda e: (str(e.get("research_deadline_at")), str(e.get("ticker"))))[:6]
    except (OSError, ValueError, KeyError, TypeError):
        earnings_value = {"status": "unverified", "events": []}
        upcoming = []
        errors.append("earnings_calendar_unverified")
    decision = _read(root, "04_research/company_research/daily_decision.json")
    stores = _hashes(root, MUTABLE_STORES)
    stable = {"account_market": _hashes(root, ACCOUNT_MARKET), "stores": stores,
        "other_inputs": _hashes(root, OTHER_INPUTS), "news": news_value,
        "earnings": {"status": earnings_value["status"], "event_count": len(earnings_value["events"]),
                     "semantic_sha256": canonical_sha256(earnings_value)},
        "due_reviews": decision.get("workflow_evaluation", {}).get("thesis_review", {}),
        "capital_priorities": decision.get("capital_deployment_escalation", {}).get("research_priority_tickers", []),
        "public_handoff_failed": bool(handoff and handoff.get("status") == "failed_or_incomplete")}
    fingerprint = canonical_sha256(stable)
    return {"schema_version": SCHEMA, "observed_at": current.isoformat(),
        "input_fingerprint": fingerprint, "input_bindings": stable,
        "public_handoff": handoff or {"status": "offline_only", "network_attempted": False},
        "evidence_errors": errors, "market_data_is_intraday_quote": False,
        "attention_context": {"upcoming_earnings": [{k: event.get(k) for k in (
            "event_id", "ticker", "company_name", "research_deadline_at", "status", "blockers", "next_step", "sources")}
            for event in upcoming], "capital_priority_tickers": stable["capital_priorities"],
            "account_market_paths": list(ACCOUNT_MARKET),
            "official_news_events_path": "03_source_data/equity_research/official_news_events.local.json",
            "full_earnings_store_path": "03_source_data/equity_research/earnings_events.local.json"},
        "scope": {"maximum_items": 2, "maximum_minutes": 10,
                  "order": ["urgent_held_risk", "imminent_earnings", "decision_relevant_changed_evidence"],
                  "longer_work": "Retain exact dependencies and carry work to a later full review."},
        **AUTHORITY}


def _mutation_locks(root: Path, *, runtime_lock: Path | None = None):
    # Full refresh uses this same order. Short work never waits for its lock.
    stack = ExitStack()
    try:
        stack.enter_context(ExclusiveFileLock(runtime_lock or root.parent / ".locks/equity-research-runtime.lock"))
        stack.enter_context(ExclusiveFileLock(root / "00_project_control/run_logs/daily_pipeline.lock"))
    except BaseException:
        stack.close()
        raise
    return stack


def check(root: Path, current: datetime) -> dict:
    current = aware(current)
    result = _configured_due(root, current)
    if result["outcome"] != "due":
        return result
    state = _state(root)
    row = state["slots"].get(result["slot_id"])
    if row and row.get("status") in {"claimed", "completed", "unchanged", "expired", "failed"}:
        return {**result, "outcome": "already_reserved", "status": row["status"], "claim_id": row["claim_id"]}
    active = next((r for r in state["slots"].values()
        if r.get("status") == "claimed" and aware(r["expires_at"]) > current), None)
    return {**result, "outcome": "assessment_in_progress" if active else "due",
            "active_claim_id": active.get("claim_id") if active else None}


def claim(root: Path, current: datetime, *, refresh_public: bool = False,
          runtime_lock: Path | None = None, runner: Callable = subprocess.run,
          clock: Callable[[], datetime] | None = None) -> dict:
    current = aware(current)
    result = _configured_due(root, current)
    if result["outcome"] != "due":
        if result.get("reason") == "outside_slot_grace_no_catchup":
            with ExclusiveFileLock(root / LOCK_REL):
                state = _state(root)
                _record_missed(root, state, current)
                atomic_write_json(root / STATE_REL, state)
        return result
    with ExclusiveFileLock(root / LOCK_REL):
        result = check(root, current)
        if result["outcome"] != "due":
            return result
        state = _state(root)
        _record_missed(root, state, current)
        try:
            mutations = _mutation_locks(root, runtime_lock=runtime_lock)
        except RuntimeError:
            # Keep a pending attempt, not a consumed claim, for retry within the
            # same 15-minute grace period. No long wait or cross-session catchup.
            row = {"claim_id": uuid.uuid4().hex, "slot_id": result["slot_id"],
                   "status": "pending_refresh_lock", "started_at": current.isoformat()}
            row = _transition(root, row, current, reason="research_refresh_busy")
            state["slots"][result["slot_id"]] = row
            atomic_write_json(root / STATE_REL, state)
            return {**result, "outcome": "pending_refresh_lock", "receipt": row}
        with mutations:
            for slot_id, old in list(state["slots"].items()):
                if old.get("status") == "claimed" and aware(old["expires_at"]) <= current:
                    state["slots"][slot_id] = _transition(root, old, current, status="expired",
                        ended_at=current.isoformat(), reason="assessment_deadline_elapsed_preserve_pending_work")
            claim_id = uuid.uuid4().hex
            expiry = min(current + MAX_DURATION, aware(result["session"]["close_at"]))
            row = {"claim_id": claim_id, "slot_id": result["slot_id"], "status": "claimed",
                   "started_at": current.isoformat(), "expires_at": expiry.isoformat(),
                   "scheduled_at": result["scheduled_at"], "session": result["session"]}
            publication_before = _hashes(root, sorted(WORKFLOW_INPUTS))
            prior_recomposition_pending = state.get("publication_recomposition_pending")
            row["publication_inputs_before"] = publication_before
            row["publication_recomposition_required"] = bool(prior_recomposition_pending)
            # Reserve before any public read; interruption retains this receipt.
            row = _transition(root, row, current)
            state["slots"][result["slot_id"]] = row
            if refresh_public:
                # A crash between a collector's atomic write and this parent's
                # read-back cannot silently lose the publication repair duty.
                state["publication_recomposition_pending"] = {"from_claim_id": claim_id,
                    "observed_at": current.isoformat(), "status": "public_refresh_in_progress"}
            atomic_write_json(root / STATE_REL, state)
            handoff = refresh_public_handoff(root, current, runner=runner) if refresh_public else None
            observed = aware(clock()) if clock else current
            publication_after = _hashes(root, sorted(WORKFLOW_INPUTS))
            public_changes = {path: {"before": publication_before[path], "after": digest}
                              for path, digest in publication_after.items() if publication_before[path] != digest}
            try:
                _validated_publication(root, observed)
                publication_error = None
            except (OSError, ValueError, KeyError, TypeError) as error:
                publication_error = str(error) or "current_publication_unverified"
            required = bool(public_changes or prior_recomposition_pending or publication_error)
            if required:
                state["publication_recomposition_pending"] = {"from_claim_id": claim_id,
                    "observed_at": observed.isoformat(), "changed_inputs": public_changes}
            else:
                state.pop("publication_recomposition_pending", None)
            atomic_write_json(root / STATE_REL, state)
            context = build_context(root, observed, handoff=handoff)
            context["pending_work"] = state.get("pending_work")
            row = _transition(root, row, observed, context=context,
                publication_input_changes=public_changes, publication_recomposition_required=required,
                publication_inputs_after=publication_after,
                publication_validation_error=publication_error,
                required_next_step=_recomposition_step(root) if required else None)
            if observed >= expiry:
                row = _transition(root, row, observed, status="expired", ended_at=observed.isoformat(),
                                  reason="public_handoff_exhausted_assessment_budget")
            elif (context["input_fingerprint"] == state.get("last_completed_fingerprint")
                  and not _resumable_work(state, observed) and not required):
                row = _transition(root, row, observed, status="unchanged", ended_at=observed.isoformat(),
                                  reason="no_changed_decision_relevant_inputs")
            state["slots"][result["slot_id"]] = row
            atomic_write_json(root / STATE_REL, state)
            return {**result, "outcome": row["status"], "receipt": row,
                    "publication_recomposition_required": required,
                    "required_next_step": row.get("required_next_step")}


def _sources(root: Path, sources: Any, *, current: datetime) -> None:
    if not isinstance(sources, list) or not sources:
        raise ValueError("short_assessment_sources_required")
    for source in sources:
        if (not isinstance(source, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", "")))
                or aware(source.get("available_at")) > current):
            raise ValueError("short_assessment_source_invalid")
        if sha256_file(_inside(root, source.get("path"))) != source["sha256"]:
            raise ValueError("short_assessment_source_changed")


def _accepted_record(root: Path, amendment: dict, *, started: datetime, current: datetime) -> None:
    store = _read(root, amendment["path"])
    identity = amendment.get("record_identity")
    candidates = [record for record in store.get("records", store.get("events", []))
                  if isinstance(record, dict) and identity in {
                      record.get("record_hash"), record.get("record_sha256"), canonical_sha256(record)}]
    if len(candidates) != 1:
        raise ValueError("short_assessment_accepted_record_identity_unverified")
    record = candidates[0]
    recorded = record.get("recorded_at", record.get("reviewed_at", store.get("prepared_at_utc")))
    if not started <= aware(recorded) <= current:
        raise ValueError("short_assessment_accepted_record_not_from_this_claim")


def _zero_order_publication(decision: dict) -> bool:
    if decision.get("eligible_action_review_candidates") or decision.get("eligible_new_position_review_candidates"):
        return False
    if any(row.get("order_draft") for row in decision.get("capital_decision", {}).get("decisions", [])):
        return False
    if any(row.get("eligible") is True for row in decision.get("tactical_review", {}).get("drafts", [])):
        return False
    return True


def complete(root: Path, proposal: dict, current: datetime, *, runtime_lock: Path | None = None) -> dict:
    current = aware(current)
    if proposal.get("schema_version") != SCHEMA or any(proposal.get(k) is not False for k in AUTHORITY):
        raise ValueError("short_assessment_result_authority_invalid")
    if proposal.get("outcome") not in {"no_action", "unresolved", "accepted_amendments"}:
        raise ValueError("short_assessment_result_outcome_invalid")
    with ExclusiveFileLock(root / LOCK_REL), _mutation_locks(root, runtime_lock=runtime_lock):
        state = _state(root)
        match = [(s, r) for s, r in state["slots"].items() if r.get("claim_id") == proposal.get("claim_id")]
        if len(match) != 1 or match[0][1].get("status") != "claimed":
            raise ValueError("short_assessment_live_claim_required")
        slot_id, row = match[0]
        if not aware(row["started_at"]) <= current <= aware(row["expires_at"]):
            raise ValueError("short_assessment_completion_outside_budget")
        items = proposal.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 2:
            raise ValueError("short_assessment_one_or_two_items_required")
        for item in items:
            if any(not isinstance(item.get(k), str) or not item[k].strip()
                   for k in ("ticker", "conclusion", "rationale", "next_step")):
                raise ValueError("short_assessment_substantive_item_required")
            _sources(root, item.get("sources"), current=current)
        continuation = proposal.get("continuation", {})
        if (not isinstance(continuation, dict) or continuation.get("status") not in {
                "complete", "continue_analysis", "waiting_on_external_dependency"}
                or not isinstance(continuation.get("next_step"), str) or not continuation["next_step"].strip()
                or (proposal["outcome"] == "unresolved" and continuation["status"] == "complete")):
            raise ValueError("short_assessment_explicit_continuation_required")
        next_review = continuation.get("next_review_at")
        if next_review and not current < aware(next_review) <= current + timedelta(hours=48):
            raise ValueError("short_assessment_next_review_invalid")
        items_digest = canonical_sha256(items)
        if (continuation["status"] == "continue_analysis" and items_digest == state.get("last_items_sha256")):
            raise ValueError("short_assessment_unchanged_analytical_receipt_not_progress")
        original = row["context"]["input_bindings"]
        if _hashes(root, ACCOUNT_MARKET) != original["account_market"]:
            raise ValueError("short_assessment_account_or_market_changed_reassess_required")
        actual_stores = _hashes(root, MUTABLE_STORES)
        changed = {path for path, digest in actual_stores.items() if digest != original["stores"].get(path)}
        accepted = proposal.get("accepted_amendments", [])
        if (not isinstance(accepted, list) or {r.get("path") for r in accepted if isinstance(r, dict)} != changed
                or len(accepted) != len(changed)):
            raise ValueError("short_assessment_amendment_receipts_incomplete")
        for amendment in accepted:
            if (amendment.get("sha256") != actual_stores[amendment["path"]]
                    or not isinstance(amendment.get("record_identity"), str)
                    or not amendment["record_identity"].strip()):
                raise ValueError("short_assessment_accepted_record_binding_invalid")
            _accepted_record(root, amendment, started=aware(row["started_at"]), current=current)
        if bool(changed) != (proposal["outcome"] == "accepted_amendments"):
            raise ValueError("short_assessment_actual_amendments_mismatch")
        publication = None
        publication_inputs_changed = (_hashes(root, sorted(WORKFLOW_INPUTS))
                                      != row.get("publication_inputs_after", row.get("publication_inputs_before")))
        if changed or row.get("publication_recomposition_required") or publication_inputs_changed:
            from workflow_integrity import validate_published_workflow
            from email_brief import render_email
            from run_daily_refresh import STEP_SPECS
            from delivery_assessments import delivery_policy_context, priority_review_context, STORE_REL as PRIORITY_STORE
            decision = _read(root, "04_research/company_research/daily_decision.json")
            generated = aware(decision.get("generated_at"))
            if not aware(row["started_at"]) <= generated <= current:
                raise ValueError("short_assessment_post_amendment_recomposition_required" if changed else
                                 "short_assessment_post_public_handoff_recomposition_required")
            if (decision.get("workflow_integrity", {}).get("schema_version") != "equity_workflow_integrity_v1"
                    or decision.get("assessment_delivery_policy") != delivery_policy_context(root)
                    or decision.get("analyst_priority_review") != priority_review_context(root, current=current)):
                # The common validator deliberately accepts dated legacy
                # artifacts without a contract. A new short completion cannot.
                raise ValueError("short_assessment_typed_current_publication_required")
            if str(PRIORITY_STORE) in changed and decision["analyst_priority_review"].get("status") != "current":
                raise ValueError("short_assessment_accepted_priority_not_current_in_publication")
            refresh = _read(root, "00_project_control/run_logs/daily_refresh_state.local.json")
            passed = refresh.get("outcome") == "passed"
            safe_degraded = (not changed and refresh.get("outcome") == "degraded_decision_created"
                             and refresh.get("decision_created") is True and _zero_order_publication(decision))
            if (not (passed or safe_degraded) or refresh.get("market_snapshot_mode") != "reuse_validated_snapshot"
                    or refresh.get("email_attempted") is not False or refresh.get("email_sent") is not False
                    or not aware(row["started_at"]) <= aware(refresh.get("started_at"))
                    <= generated <= aware(refresh.get("completed_at")) <= current
                    or {step["name"] for step in refresh.get("steps", [])} != {spec[0] for spec in STEP_SPECS}
                    or (not safe_degraded and any(step.get("exit_code") != 0 and not step.get("allowed_to_fail")
                           for step in refresh.get("steps", [])))):
                raise ValueError("short_assessment_full_no_send_refresh_required")
            validate_published_workflow(decision, root=root, current=current)
            _subject, text, html = render_email(decision)
            for path, expected in (("07_automation/email_briefs/daily_email_brief.txt", text),
                                   ("07_automation/email_briefs/daily_email_brief.html", html)):
                if _inside(root, path).read_text(encoding="utf-8") != expected:
                    raise ValueError("short_assessment_final_email_recomposition_required")
            publication = {"decision_sha256": sha256_file(root / "04_research/company_research/daily_decision.json"),
                           "generated_at": generated.isoformat(), "email_sent": False,
                           "refresh_outcome": refresh["outcome"], "fully_passed_research": passed,
                           "safe_degraded_zero_order": safe_degraded}
        # Even an unchanged/no-amendment result cannot retire work against a
        # missing publication, externally changed input or newly expired gate.
        if publication is None:
            _validated_publication(root, current)
        # Nothing here sends email or claims that an analyst dossier completed a
        # valuation. The scheduled sender evaluates accepted current semantics.
        updated = _transition(root, row, current, status="completed", ended_at=current.isoformat(),
            result=proposal, publication=publication)
        state["slots"][slot_id] = updated
        state["pending_work"] = {**continuation, "tickers": [item["ticker"] for item in items],
                                 "from_claim_id": row["claim_id"]}
        state["last_items_sha256"] = items_digest
        if publication is not None:
            state.pop("publication_recomposition_pending", None)
        state["last_completed_fingerprint"] = build_context(root, current,
            handoff=row["context"].get("public_handoff"))["input_fingerprint"]
        atomic_write_json(root / STATE_REL, state)
        return updated
