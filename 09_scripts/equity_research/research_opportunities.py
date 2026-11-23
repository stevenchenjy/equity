"""Durable attention orchestration; existing decision/risk modules retain capital."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
import copy
import json
import time

from daily_common import (ExclusiveFileLock, atomic_write_json, atomic_write_text,
    canonical_sha256, is_us_market_session_date, latest_published_market_session,
    read_csv, read_json, sha256_file, ET)
from opportunity_contract import (AUTHORITY, BASE_REL, STORE_REL, REPORT_REL, POLICY_REL,
    MARKDOWN_REL, TERMINAL, empty_store, replay, append_event, transition, transition_batch, publish_store,
    retain_input, retain_history_json, validate_policy, validate_observation, validate_journal, require, inside)
from opportunity_triggers import collect_triggers, packet
from opportunity_evidence import EVIDENCE_REL, objective_research
from workflow_evaluation import aware
from account_authority import load_authority, project_research_requirements
from validation_cache import content_proof_scope, file_hash_validation, read_hashed_bytes, resolved_sha256


@dataclass(frozen=True)
class _ReportProof:
    report_digest: str
    store_digest: str
    latest_event: datetime | None
    receipts: tuple[tuple[str, str], ...]
    publication_bytes: bytes | None = None


_REPORT_PROOFS = ContextVar("opportunity_report_operation_proofs", default=None)


@contextmanager
def report_proof_scope():
    """Reuse the mathematical proof of the same bytes for one invocation.

    Each reader verifies actual report and journal bytes and every original
    retained locator, with a fresh mutation fence, live account and clock.
    No report object, decision or delivery eligibility is shared.
    """
    if _REPORT_PROOFS.get() is not None:
        yield
        return
    token = _REPORT_PROOFS.set({})
    try:
        with content_proof_scope():
            yield
    finally:
        _REPORT_PROOFS.reset(token)


def held_tickers(root: Path) -> set[str]:
    result = set()
    for row in read_csv(root / "05_risk_and_positions/current_positions.local.csv"):
        try:
            shares = float(row.get("shares_optional", row.get("current_shares", row.get("shares", "0"))))
        except (TypeError, ValueError):
            continue
        if shares > 0:
            result.add(row["ticker"])
    return result


def upcoming_earnings(item: dict, current: datetime | None = None) -> dict | None:
    """Nearest actionable research deadline, never an investment conclusion.

    A real intake clock is required for a priority boost. Retained post-event,
    contradictory or canceled leads remain evidence without urgent priority.
    """
    if current is None:
        return None
    candidates = []
    observations = item.get("observations", [item])
    # A later schedule observation supersedes its earlier schedule version.
    # Keep every version in the journal instead of erasing changed dates.
    latest = {}
    for observation in observations:
        if observation.get("trigger") == "upcoming_earnings_calendar":
            event = observation.get("evidence", {}).get("event", {})
            latest[event.get("event_id", observation.get("observation_id"))] = event
    for event in latest.values():
        try:
            if (event.get("status") in {"schedule_conflict", "cancelled", "canceled", "unverified", "elapsed", "past", "elapsed_unreviewed"}
                    or event.get("timing", "pre_event") != "pre_event" or event.get("blockers")):
                continue
            if event.get("date_confidence") in {"conflicting", "conflict", "unverified"}:
                continue
            deadline = aware(event["research_deadline_at"])
            event_time = aware(event["event_at"]) if event.get("event_at") else None
            if deadline <= current or event_time is not None and event_time <= current:
                continue
            # Unknown session times must not imply that an event is still
            # upcoming after its dated research cutoff has elapsed.
            if aware(event["first_detected_at"]) > current:
                continue
            candidates.append((deadline, event))
        except (ValueError, KeyError, TypeError):
            continue
    return min(candidates, key=lambda pair: pair[0])[1] if candidates else None


def priority(item: dict, held: set[str], *, current: datetime | None = None) -> tuple:
    """One authoritative attention priority used by intake and backlog adapter."""
    observations = item.get("observations", [item])
    event = upcoming_earnings(item, current)
    families = {p["family"] for p in observations if p.get("trigger") != "upcoming_earnings_calendar"}
    if event:
        families.add("catalyst")
    adverse = any(p["family"] == "catalyst" and p["evidence"].get("event", {}).get("direction") == "negative" for p in observations)
    tier = 0 if item["ticker"] in held or adverse else 1 if "catalyst" in families else 2 if families & {"business", "request"} else 3
    rank = min((p["evidence"].get("metrics", {}).get("rank", 999) for p in observations), default=999)
    deadline = aware(event["research_deadline_at"]).isoformat() if event else "9999-12-31"
    return (tier, deadline, rank, item.get("first_seen_at", item.get("detected_at", "")), item["ticker"])


def work_priority(item: dict, held: set[str], *, current: datetime,
                  escalation_rank: dict[str, int]) -> tuple:
    """Urgent held risk, dated event work, then ordinary capital escalation."""
    base = priority(item, held, current=current)
    event = upcoming_earnings(item, current)
    urgent = event and aware(event["research_deadline_at"]) - current <= timedelta(hours=48)
    bucket = 0 if base[0] == 0 else 1 if urgent else 2
    return (bucket, base[1] if urgent else "", escalation_rank.get(item["ticker"], len(escalation_rank)), *base)


def negative_assessment_wait(item: dict, *, current: datetime, market_session_date: str | None) -> bool:
    """Defer duplicate research only from an already validated attention view.

    A negative analyst assessment never completes canonical gaps or authorizes a
    trade. A newer observed source, completed close, or its recorded review date
    puts the work back in the queue; unknown context cannot suppress research.
    """
    assessment = item.get("assessment", {})
    if (item.get("state") not in {"rejected", "economics_failed"}
            or assessment.get("conclusion") != item.get("state")
            or assessment.get("valuation_status") not in {"reviewed", "failed"}):
        return False
    try:
        assessed = aware(assessment["assessed_at"])
        terminal = item["transitions"][-1]
        if (terminal.get("owner") != "analyst_assessment" or terminal.get("to_state") != item["state"]
                or not assessed <= aware(terminal["recorded_at"]) <= current
                or aware(item["last_evidence_at"]) > aware(terminal["recorded_at"])
                or current >= aware(assessment["next_review_at"])):
            return False
        # The caller supplies an actual canonical close, not an expected
        # provider availability date or a newly timestamped old snapshot.
        session = date.fromisoformat(str(market_session_date))
        close = datetime.combine(session, datetime.min.time().replace(hour=16), ET)
        return close <= assessed
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def elapsed_sessions(start: str, current: datetime) -> int:
    cursor, last, count = aware(start).date()+timedelta(days=1), latest_published_market_session(current), 0
    while cursor <= last:
        count += int(is_us_market_session_date(cursor))
        cursor += timedelta(days=1)
    return count


def _base_metrics() -> dict:
    return {"new_opportunities": 0, "rediscovery_updates": 0, "duplicate_packets_skipped": 0,
        "expired": 0, "objective_items_processed": 0, "objective_attachments_accepted": 0,
        "new_research_numeric_fields": 0, "canonical_fields_admitted": 0,
        "network_requests": 0, "external_issuers_attempted": 0, "request_limit": 0,
        "analyst_assessments_completed": 0, "attempts": []}


def _earnings_schedule_evidence(evidence: dict) -> dict:
    # A row can move when other issuers are reordered. Keep its exact digest
    # and all schedule/evidence fields in the comparison and retain the full
    # position locator in every admitted observation.
    stable = {k: v for k, v in evidence.items() if k != "prior_schedule_observation_id"}
    stable["event"] = {k: v for k, v in evidence["event"].items() if k != "row_index"}
    return stable


def _queue_transitions(items: dict, held: set[str], policy: dict, *, current: datetime) -> tuple[list, int]:
    """Plan the existing ordered queue changes without replaying per change.

    Only local lifecycle fields change during this plan. Evidence, the held
    set and the review clock stay fixed, so each attention key is computed
    once. The durable batch still validates the whole journal and its sources.
    """
    planned = {identity: dict(item) for identity, item in items.items()}
    keys = {identity: priority(item, held, current=current) for identity, item in planned.items()}
    inactive = TERMINAL | {"deferred_capacity"}
    active = [item for item in planned.values() if item["state"] not in inactive]
    changes = []

    def key(item):
        return keys[item["opportunity_id"]]

    def stage(item, target, reason, blockers):
        changes.append({"identity": item["opportunity_id"], "target": target,
            "owner": "research_orchestration", "reason": reason,
            "sources": item["observations"][-1]["sources"], "blockers": blockers})
        item.update(state=target, owner="research_orchestration", reason_code=reason, blockers=blockers)

    while len(active) > policy["active_capacity"]:
        victims = [item for item in active if key(item)[0] > 0
            and item["state"] in {"queued", "data_blocked", "evidence_attached", "insufficient_evidence"}]
        if not victims:
            break
        stage(max(victims, key=key), "deferred_capacity",
            "research_capacity_rebalanced_after_analyst_review", ["bounded_research_capacity"])
        active = [item for item in planned.values() if item["state"] not in inactive]

    # The old loop iterates a snapshot even after each replay. A victim that
    # becomes deferred during admission is not a new candidate in this run.
    candidates = [item for item in sorted(planned.values(), key=key) if item["state"] == "deferred_capacity"]
    admitted = 0
    for item in candidates:
        if admitted >= policy["new_opportunities_per_run"]:
            break
        if len(active) >= policy["active_capacity"]:
            victims = [other for other in active if key(other)[0] > 0 and key(other) > key(item)
                and other["state"] in {"queued", "data_blocked", "evidence_attached", "insufficient_evidence"}]
            event = upcoming_earnings(item, current)
            urgent = event and aware(event["research_deadline_at"]) - current <= timedelta(hours=48)
            if not (key(item)[0] == 0 or urgent) or not victims:
                continue
            stage(max(victims, key=key), "deferred_capacity",
                "research_capacity_reserved_for_held_or_adverse_work" if not urgent
                else "research_capacity_reserved_for_pre_earnings_deadline", ["bounded_research_capacity"])
        stage(item, "queued", "bounded_attention_admission", [])
        active = [other for other in planned.values() if other["state"] not in inactive]
        admitted += 1
    return changes, admitted


@content_proof_scope()
def intake(root: Path, *, current: datetime) -> dict:
    start = time.monotonic()
    policy = validate_policy(read_json(root / POLICY_REL))
    with ExclusiveFileLock(root / BASE_REL / "store.lock"):
        previous = read_json(root / STORE_REL, empty_store())
        items = replay(previous, root=root, current=current)
        # Events are append-only. Candidate transitions append new records and
        # never edit an existing event, so only the event list needs isolation.
        store, metrics = {**previous, "events": list(previous["events"])}, _base_metrics()
        held = held_tickers(root)
        expirations = []
        for identity, item in items.items():
            if item["state"] not in TERMINAL and item["ticker"] not in held and elapsed_sessions(item["last_evidence_at"], current) >= policy["stale_after_market_sessions"]:
                expirations.append({"identity": identity, "target": "expired", "owner": "research_orchestration",
                    "reason": "research_evidence_stale_without_reassessment", "sources": item["first_observation"]["sources"],
                    "blockers": ["new_evidence_and_recorded_reassessment_required"]})
                metrics["expired"] += 1
        if expirations:
            transition_batch(store, expirations, root=root, current=current)
        seen = {p["observation_id"] for i in items.values() for p in i["observations"]}
        by_ticker = {i["ticker"]: identity for identity, i in items.items()}
        latest_schedules = {(i["ticker"], p["evidence"]["event"]["event_id"]): p
            for i in items.values() for p in i["observations"]
            if p.get("trigger") == "upcoming_earnings_calendar"}
        # These small lookup projections contain everything intake still
        # needs. Release the full copied history before collecting new leads.
        del items, expirations
        packets, diagnostics = collect_triggers(root, current=current, policy=policy,
            known_schedule_ids={event_id for _, event_id in latest_schedules})
        for p in sorted(packets, key=lambda i: priority(i, held, current=current)):
            schedule_key = ((p["ticker"], p["evidence"]["event"]["event_id"])
                if p.get("trigger") == "upcoming_earnings_calendar" else None)
            latest = latest_schedules.get(schedule_key)
            duplicate = p["observation_id"] in seen
            if ((latest and _earnings_schedule_evidence(latest["evidence"]) == _earnings_schedule_evidence(p["evidence"]))
                    or duplicate and not latest):
                metrics["duplicate_packets_skipped"] += 1
                continue
            if duplicate:
                # A recovery can match an earlier original schedule. Bind
                # this newly observed state to the immediately prior state
                # rather than rewriting history or discarding it as old.
                evidence = {**p["evidence"], "prior_schedule_observation_id": latest["observation_id"]}
                p = packet(ticker=p["ticker"], family=p["family"], trigger=p["trigger"],
                    evidence=evidence, sources=p["sources"], current=aware(p["detected_at"]),
                    produced_by=p["producer"], kind=p["instrument_kind"], missing=p["missing_evidence"])
                validate_observation(p, root=root, current=current)
            identity = by_ticker.get(p["ticker"])
            if identity:
                append_event(store, {"kind": "observed", "opportunity_id": identity,
                    "recorded_at": current.isoformat(), "observation": p, "owner": "research_orchestration",
                    "reason_code": "changed_evidence_first_seen_preserved"})
                metrics["rediscovery_updates"] += 1
            else:
                identity = canonical_sha256({"first_observation_id": p["observation_id"], "ticker": p["ticker"]})
                append_event(store, {"kind": "detected", "opportunity_id": identity,
                    "recorded_at": current.isoformat(), "observation": p, "owner": "research_orchestration",
                    "to_state": "deferred_capacity", "reason_code": "research_capacity_wait",
                    "blockers": ["bounded_research_capacity"]})
                by_ticker[p["ticker"]] = identity
            seen.add(p["observation_id"])
            if schedule_key:
                latest_schedules[schedule_key] = p
        del seen, by_ticker, latest_schedules, packets
        # A separately accepted analyst review can move deferred work into an
        # active state. Reconcile that real lifecycle transition before new
        # admissions; preserve its assessment and the displaced unfinished work.
        current_items = replay(store)
        changes, admitted = _queue_transitions(current_items, held, policy, current=current)
        if changes:
            transition_batch(store, changes, root=root, current=current)
        metrics["new_opportunities"] += admitted
        # Publication performs its own complete source-bound replay. Do not
        # retain another full materialized history while that proof is built.
        del current_items, changes
        publish_store(root, store, previous=previous, current=current)
        metrics["duration_seconds"] = round(time.monotonic()-start, 4)
        return publish_view(root, store, current=current, metrics=metrics, diagnostics=diagnostics)


@content_proof_scope()
def objective(root: Path, *, current: datetime, allow_network: bool = False, clock=None) -> dict:
    start = time.monotonic()
    clock = clock or (lambda: current)
    policy = validate_policy(read_json(root / POLICY_REL))
    with ExclusiveFileLock(root / BASE_REL / "store.lock"):
        previous = read_json(root / STORE_REL, empty_store())
        initial_items = replay(previous, root=root, current=current)
        store, metrics = {**previous, "events": list(previous["events"])}, _base_metrics()
        metrics["request_limit"] = 2*policy["external_issuers_per_fetch"]
        config = read_json(root / "00_project_control/active_production_config.json", {})
        budget = config.get("workflow", {}).get("objective_research_max_tickers", 3)
        # Reuse the authoritative work-budget bounds without inventing another
        # canonical research quota. Already attempted issuers consume this run.
        from research_backlog import MAX_WORK_BUDGET
        require(type(budget) is int and 1 <= budget <= MAX_WORK_BUDGET, "research_work_budget_invalid")
        backlog = read_json(root / "04_research/company_research/research_backlog.local.json", {})
        same_cycle = backlog.get("generated_at", "")[:10] == current.date().isoformat()
        canonical_attempted = set(backlog.get("selected_tickers", [])) if same_cycle else set()
        completed = len(canonical_attempted)
        remaining = max(0, budget-completed)
        rows = {r["ticker"]: r for r in read_csv(root / "03_source_data/equity_research/daily_fundamentals.csv")}
        market_session = latest_published_market_session(current).isoformat()
        held = held_tickers(root)
        prior_report = read_json(root / REPORT_REL, {})
        from capital_escalation import research_priorities
        escalation_rank = {ticker: i for i, ticker in enumerate(research_priorities(root, current))}
        reserved = set(backlog.get("reserved_external_event_tickers", [])) if same_cycle else set()
        def objective_priority(item):
            base = work_priority(item, held, current=current, escalation_rank=escalation_rank)
            # Canonical held work already performed must not consume the
            # isolated external slots a second time through an attachment.
            bucket = 0 if base[0] == 0 and item["ticker"] not in canonical_attempted else 1 if item["ticker"] in reserved else 2
            return (bucket, *base)
        for item in sorted(initial_items.values(), key=objective_priority):
            if item["state"] in TERMINAL | {"deferred_capacity"}:
                continue
            if metrics["objective_items_processed"] >= remaining:
                break
            task_started = clock()
            requests_before = metrics["network_requests"]
            dossier, reason = objective_research(root, item, current=task_started, policy=policy,
                canonical_rows=rows, market_session=market_session, allow_network=allow_network, metrics=metrics)
            task_completed = max(clock(), aware(dossier["observed_at"]) if dossier else task_started)
            latest_attachment = next((t for t in reversed(item["transitions"]) if t["to_state"] == "evidence_attached"), {})
            unchanged = ((dossier and latest_attachment.get("reason_code") == "objective_dossier:"+dossier["dossier_hash"]
                and item["state"] not in {"queued", "data_blocked"})
                or (not dossier and item["state"] == "data_blocked" and item["reason_code"] == reason and requests_before == metrics["network_requests"]))
            if unchanged:
                metrics["unchanged_items_skipped"] = metrics.get("unchanged_items_skipped", 0)+1
                continue
            metrics["objective_items_processed"] += 1
            attempt = {"ticker": item["ticker"], "reason_code": reason, "status": "source_bound" if dossier else "unverified",
                "dossier_hash": dossier.get("dossier_hash", "") if dossier else "", "canonical_fields_admitted": 0}
            metrics["attempts"].append(attempt)
            if not item["research_started_at"] and item["state"] in {"queued", "data_blocked", "evidence_attached", "insufficient_evidence"}:
                transition(store, item["opportunity_id"], "researching", owner="objective_research", reason="objective_source_inspection_started",
                    sources=item["first_observation"]["sources"], blockers=[], current=task_started)
            if dossier:
                src = retain_input(root, root / EVIDENCE_REL / "history" / (dossier["dossier_hash"]+".json"), available_at=dossier["observed_at"])
                if item["state"] in {"research_supported", "eligibility_review"}:
                    transition(store, item["opportunity_id"], "data_blocked", owner="objective_research", reason="changed_objective_evidence_requires_recorded_reassessment",
                        sources=[src], blockers=["current_business_and_valuation_reassessment"], current=task_completed)
                if replay(store)[item["opportunity_id"]]["state"] != "researching":
                    transition(store, item["opportunity_id"], "researching", owner="objective_research", reason="source_bound_objective_work_started",
                        sources=item["first_observation"]["sources"], blockers=[], current=task_completed)
                transition(store, item["opportunity_id"], "evidence_attached", owner="objective_research", reason="objective_dossier:"+dossier["dossier_hash"],
                    sources=[src], blockers=dossier["missing_evidence"], current=task_completed)
                metrics["objective_attachments_accepted"] += 1
                metrics["new_research_numeric_fields"] += len(dossier["facts_available"]) if not latest_attachment else 0
            elif item["state"] != "data_blocked" or item["reason_code"] != reason:
                transition(store, item["opportunity_id"], "data_blocked", owner="objective_research", reason=reason,
                    sources=item["observations"][-1]["sources"], blockers=[reason], current=task_completed)
        del initial_items
        final_current = max(clock(), aware(store["events"][-1]["recorded_at"]) if store["events"] else current)
        publish_store(root, store, previous=previous, current=final_current)
        metrics["duration_seconds"] = round(time.monotonic()-start, 4)
        metrics["shared_objective_work_budget"] = budget
        metrics["canonical_issuers_attempted_before_intake"] = completed
        report = publish_view(root, store, current=final_current, metrics=metrics, diagnostics=prior_report.get("diagnostics", {}))
        # The backlog's non-authoritative view must expose the accepted progress
        # from this same full refresh, without another objective pass.
        from research_backlog import refresh_attention_view
        refresh_attention_view(root, final_current)
        return report


def publish_view(root: Path, store: dict, *, current: datetime, metrics: dict, diagnostics: dict) -> dict:
    items = list(replay(store, root=root, current=current).values())
    authority = load_authority(root, current)
    held = held_tickers(root)
    for item in items:
        families = {}
        for observation in item["observations"]:
            families[observation["family"]] = observation
        item["evidence_families"] = {key: {"status": "observed" if key in families else "unassessed",
            "latest_observation": families.get(key)} for key in ("market", "business", "catalyst")}
        item["evidence_families"].update(economics={"status": "unassessed"},
            data_confidence={"status": "source_bound_observations_only", "investment_conviction": "not_assessed"},
            execution={"status": "existing_production_contracts_required", "capital_authority": False})
        attachment = next((t for t in reversed(item["transitions"]) if t["to_state"] == "evidence_attached"), {})
        item["objective_status"], item["research_objective_facts"] = "not_attached", {}
        if attachment:
            from opportunity_contract import inside
            from opportunity_evidence import validate_dossier
            try:
                dossier = read_json(inside(root, attachment["sources"][0]["path"]))
                validate_dossier(dossier, root, current, read_json(root / POLICY_REL)["research_source_max_age_hours"])
                item["objective_status"], item["research_objective_facts"] = "source_bound", dossier["facts"]
            except (OSError, ValueError, KeyError, TypeError):
                item["objective_status"] = "unverified"
        assessment = next((t for t in reversed(item["transitions"]) if t["owner"] == "analyst_assessment" and t["reason_code"].startswith("recorded_assessment:")), {})
        if assessment:
            from opportunity_contract import inside
            view = read_json(inside(root, assessment["sources"][0]["path"]))
            item["assessment"] = view
            item["evidence_families"]["economics"]["status"] = view["valuation_status"]
            item["evidence_families"]["data_confidence"] = {"status": view["data_confidence"], "investment_conviction": view["investment_conviction"]}
        item["queue_age_hours"] = round((current-aware(item["first_seen_at"])).total_seconds()/3600, 4)
        item["attention_priority_key"] = list(priority(item, held, current=current))
        event = upcoming_earnings(item, current)
        if event:
            item["upcoming_earnings"] = {k: event.get(k) for k in ("event_id", "event_date", "session", "event_at",
                "research_deadline_at", "first_detected_at", "date_confidence")}
        item["stage_durations_seconds"] = {
            "detection_to_research": (aware(item["research_started_at"])-aware(item["first_seen_at"])).total_seconds() if item["research_started_at"] else None,
            "research_to_objective": (aware(item["objective_completed_at"])-aware(item["research_started_at"])).total_seconds() if item["objective_completed_at"] and item["research_started_at"] else None,
            "detection_to_assessment": (aware(item["assessment_at"])-aware(item["first_seen_at"])).total_seconds() if item["assessment_at"] else None}
        project_research_requirements(item, authority)
    items.sort(key=lambda i: tuple(i["attention_priority_key"]))
    active = [i for i in items if i["state"] not in TERMINAL | {"deferred_capacity"}]
    capacity = validate_policy(read_json(root / POLICY_REL))["active_capacity"]
    diagnostics = copy.deepcopy(diagnostics)
    diagnostics["capacity"] = {"configured_active_capacity": capacity, "active_count": len(active),
        "protected_active_count": sum(priority(i, held, current=current)[0] == 0 for i in active),
        "capacity_debt": max(0, len(active) - capacity),
        "status": "protected_or_nondeferable_work_exceeds_capacity" if len(active) > capacity else "within_capacity"}
    reassess = [i for i in items if i["state"] in TERMINAL and i["transitions"]
        and aware(i["last_evidence_at"]) > max(aware(t["recorded_at"]) for t in i["transitions"] if t["to_state"] in TERMINAL)]
    report = {"schema_version": "equity_research_opportunity_report_v1", "generated_at": current.isoformat(),
        "store_sha256": sha256_file(root / STORE_REL), "journal_head": store["events"][-1]["record_hash"] if store["events"] else "",
        "opportunities": items, "priority_queue": active, "reassessment_queue": reassess[:3], "diagnostics": diagnostics,
        "account_authority": authority,
        "metrics": {**metrics, "research_queue_size": len(active), "total_retained_opportunities": len(items),
            "average_queue_age_hours": round(sum(i["queue_age_hours"] for i in active)/len(active), 4) if active else 0,
            "states": dict(Counter(i["state"] for i in items)), "closed_new_evidence_reassessment_count": len(reassess),
            "ever_admitted_distinct_opportunities": sum(i["initial_state"] == "queued" or any(t["to_state"] == "queued" for t in i["transitions"]) for i in items)}, **AUTHORITY}
    from opportunity_measurement import measure_paths
    report["prospective_measurement"] = measure_paths(root, items, current=current)
    report["report_hash"] = canonical_sha256(report)
    atomic_write_json(root / REPORT_REL, report)
    retain_history_json(root / BASE_REL / "run_history" / (canonical_sha256(report)+".json"), report)
    atomic_write_text(root / MARKDOWN_REL, render_report(report))
    return report


def _read_bound_json(path: Path, digest: str | None = None, *,
                     mismatch: str = "research_report_input_changed_during_read") -> tuple[dict, str]:
    # Hash the very bytes being decoded. Independent pre-claim validations can
    # outlive the first transaction and must not inherit a read/replace race.
    raw, actual = read_hashed_bytes(path)
    require(digest is None or actual == digest, mismatch)
    return json.loads(raw), actual


def _publication_report(report: dict) -> dict:
    """Keep only the fields read by decision, event and swing publication."""
    def fields(record, keys):
        return {key: record[key] for key in keys if key in record}

    visible = fields(report, ("schema_version", "generated_at", "store_sha256", "report_hash",
                              "account_authority", "metrics", *AUTHORITY))
    queue_fields = ("ticker", "state", "reason_code", "blockers", "owner", "first_seen_at",
                    "last_evidence_at", "queue_age_hours", "upcoming_earnings", "assessment",
                    "opportunity_id", "first_observation")
    for name in ("priority_queue", "reassessment_queue"):
        visible[name] = [fields(row, queue_fields) for row in report[name]]
    visible["opportunities"] = []
    for row in report["opportunities"]:
        item = fields(row, ("ticker", "state", "first_seen_at", "last_evidence_at", "research_started_at",
                            "reason_code", "blockers", "assessment"))
        item["transitions"] = row.get("transitions", [])[-1:]
        item["observations"] = []
        for observed in row.get("observations", []):
            if observed.get("family") == "market" and observed.get("instrument_kind") == "stock":
                item["observations"].append(observed)
                continue
            event = observed.get("evidence", {}).get("event")
            if isinstance(event, dict) and event.get("event_id"):
                item["observations"].append({"evidence": {"event": fields(event,
                    ("event_id", "row_sha256", "schedule_version"))}, "sources": observed.get("sources", [])})
        visible["opportunities"].append(item)
    return visible


def read_report(root: Path, *, current: datetime, publication_view: bool = False) -> dict:
    """Validate the full report and journal; optionally return publication's view.

    Within an operation, only immutable bytes of the compact view are shared.
    A reader gets an isolated object after new path, source and clock checks.
    """
    proofs = _REPORT_PROOFS.get()
    root = root.resolve()
    with file_hash_validation():
        prior = proofs.get(root) if proofs is not None else None
        first_proof = proofs is not None and prior is None
        if first_proof:
            report, report_digest = _read_bound_json(root / REPORT_REL)
            store_digest, same, cached = None, False, None
        else:
            report_digest = sha256_file(root / REPORT_REL) if proofs is not None else None
            store_digest = sha256_file(root / STORE_REL)
            same = prior and (prior.report_digest, prior.store_digest) == (report_digest, store_digest)
            cached = prior.publication_bytes if same and publication_view else None
            if cached is not None:
                report = json.loads(cached)
            elif proofs is not None:
                report, _ = _read_bound_json(root / REPORT_REL, report_digest)
            else:
                report = read_json(root / REPORT_REL, {})
        require(report.get("schema_version") == "equity_research_opportunity_report_v1"
            and all(report.get(k) is False for k in AUTHORITY), "research_opportunity_report_invalid")
        if not first_proof:
            require(report["store_sha256"] == store_digest, "research_opportunity_report_stale_store")
        clock = aware(report["generated_at"])
        require(clock <= current and current-clock <= timedelta(hours=24), "research_opportunity_report_stale_clock")
        require(report.get("account_authority", {'mode': 'verified_snapshot', 'local_planning_enabled': False})
            == load_authority(root, current), "research_opportunity_report_account_authority_changed")
        if same:
            proof = prior
            require(proof.latest_event is None or proof.latest_event <= current, "research_journal_clock_regression")
            for locator, digest in proof.receipts:
                require(resolved_sha256(root, locator, inside) == digest, "research_source_changed")
        else:
            require(report.get("report_hash") == canonical_sha256({k: v for k, v in report.items() if k != "report_hash"}), "research_opportunity_report_hash_invalid")
            if first_proof:
                require(isinstance(report["store_sha256"], str), "research_opportunity_report_stale_store")
                journal, store_digest = _read_bound_json(root / STORE_REL, report["store_sha256"],
                    mismatch="research_opportunity_report_stale_store")
            elif proofs is not None:
                journal, store_digest = _read_bound_json(root / STORE_REL, store_digest)
            else:
                journal = read_json(root / STORE_REL)
            validate_journal(journal, root=root, current=current)
            if proofs is not None:
                events = journal["events"]
                # The journal validator checks observation receipts for detections
                # and updates, and event receipts for transitions.
                receipts = sorted({(r["path"], r["sha256"]) for event in events
                    for r in (event["sources"] if event["kind"] == "transition" else event["observation"]["sources"])})
                for locator, digest in receipts:
                    require(resolved_sha256(root, locator, inside) == digest, "research_source_changed")
                proof = _ReportProof(report_digest, store_digest,
                    aware(events[-1]["recorded_at"]) if events else None, tuple(receipts))
        if publication_view and cached is None:
            report = _publication_report(report)
            if proofs is not None:
                proof = replace(proof, publication_bytes=json.dumps(report, ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8"))
    if proofs is not None:
        proofs[root] = proof
    return report


def summary(root: Path, *, current: datetime) -> dict:
    try:
        for stage in ("intake", "objective"):
            marker = read_json(root / BASE_REL / ("last_"+stage+"_run.json"), {})
            if marker and marker.get("exit_code") != 0:
                return {"status": "failed_or_incomplete", "reason": "latest_research_"+stage+"_run_did_not_complete",
                    "last_run": marker, "report_path": str(MARKDOWN_REL), **AUTHORITY}
        report = read_report(root, current=current, publication_view=True)
        return {"status": "ready", "generated_at": report["generated_at"], "report_path": str(MARKDOWN_REL),
            "store_sha256": report["store_sha256"], "metrics": report["metrics"],
            "priority_queue": [{**{k: i[k] for k in ("ticker", "state", "first_seen_at", "queue_age_hours", "reason_code", "blockers", "owner")},
                **({"upcoming_earnings": i["upcoming_earnings"]} if i.get("upcoming_earnings") else {})}
                for i in report["priority_queue"][:10]],
            # Work priority is bounded; final decision coverage is not limited
            # to the next ten research jobs. Keep every active candidate visible.
            "decision_candidates": [{**{k: i[k] for k in ("ticker", "state", "reason_code", "blockers", "owner")},
                "instrument_kind": i.get("first_observation", {}).get("instrument_kind"),
                "company_name": (i.get("first_observation", {}).get("evidence", {}).get("metrics", {}).get("name")
                    or i.get("first_observation", {}).get("evidence", {}).get("event", {}).get("company_name")),
                "identity_source_observation": i.get("first_observation", {}).get("observation_id"),
                "eligible_quantity": 0,
                **({"upcoming_earnings": i["upcoming_earnings"]} if i.get("upcoming_earnings") else {})}
                for i in report["priority_queue"]],
            "reassessment_queue": [{k: i[k] for k in ("ticker", "state", "last_evidence_at", "reason_code")} for i in report["reassessment_queue"]], **AUTHORITY}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unverified", "reason": "research_opportunity_current_store_or_report_unverified", "report_path": str(MARKDOWN_REL), **AUTHORITY}


def render_report(report: dict) -> str:
    lines = ["# Research opportunities", "", "Research attention only. Prices are dated observations; no buy/sell instruction or capital approval.",
        "Updated: "+report["generated_at"], "", "| Ticker | State | First detected | Age hours | Owner | Blockers / next evidence |",
        "|---|---|---|---:|---|---|"]
    for item in report["opportunities"]:
        lines.append(f"| {item['ticker']} | {item['state']} | {item['first_seen_at']} | {item['queue_age_hours']} | {item['owner']} | {', '.join(item['blockers']) or item['reason_code']} |")
    lines += ["", "## Evidence and timing", ""]
    for item in report["opportunities"]:
        first = item["first_observation"]
        lines.append(f"- {item['ticker']}: first trigger `{first['trigger']}`; source available {first['available_at']}; original observation `{first['observation_id']}`; families {', '.join(sorted({o['family'] for o in item['observations']}))}; research began {item['research_started_at'] or 'not started'}; objective attachment {item['objective_completed_at'] or 'not completed'}; assessment {item['assessment_at'] or 'not recorded'}.")
    lines += ["", "## Workload", "", str(report["metrics"]), "", "## Experimental boundary", "",
        f"{len(report['diagnostics'].get('experiment_review_only', []))} current experimental observations remain review-only without explicit owner approval for research use. Frozen histories and production eligibility remain separate.", ""]
    lines += ["## Closed opportunities with changed evidence", "",
        ", ".join(i["ticker"] for i in report["reassessment_queue"]) or "None.", "Recorded analyst reassessment is required before reopening; old rejection/expiry and first-seen evidence remain retained.", ""]
    return "\n".join(lines)
