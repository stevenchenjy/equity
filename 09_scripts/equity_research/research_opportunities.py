"""Durable attention orchestration; existing decision/risk modules retain capital."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
import copy
import time

from daily_common import (ExclusiveFileLock, atomic_write_json, atomic_write_text,
    canonical_sha256, is_us_market_session_date, latest_published_market_session,
    read_csv, read_json, sha256_file, ET)
from opportunity_contract import (AUTHORITY, BASE_REL, STORE_REL, REPORT_REL, POLICY_REL,
    MARKDOWN_REL, TERMINAL, empty_store, replay, append_event, transition, publish_store,
    retain_input, validate_policy, require)
from opportunity_triggers import collect_triggers
from opportunity_evidence import EVIDENCE_REL, objective_research
from workflow_evaluation import aware
from account_authority import load_authority, project_research_requirements


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


def priority(item: dict, held: set[str]) -> tuple:
    """One authoritative attention priority used by intake and backlog adapter."""
    observations = item.get("observations", [item])
    families = {p["family"] for p in observations}
    adverse = any(p["family"] == "catalyst" and p["evidence"].get("event", {}).get("direction") == "negative" for p in observations)
    tier = 0 if item["ticker"] in held or adverse else 1 if "catalyst" in families else 2 if families & {"business", "request"} else 3
    rank = min((p["evidence"].get("metrics", {}).get("rank", 999) for p in observations), default=999)
    return (tier, rank, item.get("first_seen_at", item.get("detected_at", "")), item["ticker"])


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


def intake(root: Path, *, current: datetime) -> dict:
    start = time.monotonic()
    policy = validate_policy(read_json(root / POLICY_REL))
    with ExclusiveFileLock(root / BASE_REL / "store.lock"):
        previous = read_json(root / STORE_REL, empty_store())
        items = replay(previous, root=root, current=current)
        store, metrics = copy.deepcopy(previous), _base_metrics()
        held = held_tickers(root)
        for identity, item in items.items():
            if item["state"] not in TERMINAL and item["ticker"] not in held and elapsed_sessions(item["last_evidence_at"], current) >= policy["stale_after_market_sessions"]:
                transition(store, identity, "expired", owner="research_orchestration", reason="research_evidence_stale_without_reassessment",
                    sources=item["first_observation"]["sources"], blockers=["new_evidence_and_recorded_reassessment_required"], current=current)
                metrics["expired"] += 1
        packets, diagnostics = collect_triggers(root, current=current, policy=policy)
        seen = {p["observation_id"] for i in items.values() for p in i["observations"]}
        by_ticker = {i["ticker"]: identity for identity, i in items.items()}
        admitted = 0
        for p in sorted(packets, key=lambda i: priority(i, held)):
            if p["observation_id"] in seen:
                metrics["duplicate_packets_skipped"] += 1
                continue
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
        # Rank the complete pool before allocating scarce research attention.
        # A newly observed held/adverse item can displace lower-priority work;
        # its original evidence/unfinished task remains retained as deferred.
        for item in sorted(replay(store).values(), key=lambda i: priority(i, held)):
            if item["state"] != "deferred_capacity" or admitted >= policy["new_opportunities_per_run"]:
                continue
            active = [i for i in replay(store).values() if i["state"] not in TERMINAL | {"deferred_capacity"}]
            if len(active) >= policy["active_capacity"]:
                victims = [i for i in active if priority(i, held)[0] > 0 and i["state"] in {"queued", "data_blocked", "evidence_attached", "insufficient_evidence"}]
                if priority(item, held)[0] != 0 or not victims:
                    continue
                victim = max(victims, key=lambda i: priority(i, held))
                transition(store, victim["opportunity_id"], "deferred_capacity", owner="research_orchestration",
                    reason="research_capacity_reserved_for_held_or_adverse_work", sources=victim["observations"][-1]["sources"],
                    blockers=["bounded_research_capacity"], current=current)
            transition(store, item["opportunity_id"], "queued", owner="research_orchestration", reason="bounded_attention_admission",
                sources=item["observations"][-1]["sources"], blockers=[], current=current)
            admitted += 1
            metrics["new_opportunities"] += 1
        publish_store(root, store, previous=previous, current=current)
        metrics["duration_seconds"] = round(time.monotonic()-start, 4)
        return publish_view(root, store, current=current, metrics=metrics, diagnostics=diagnostics)


def objective(root: Path, *, current: datetime, allow_network: bool = False, clock=None) -> dict:
    start = time.monotonic()
    clock = clock or (lambda: current)
    policy = validate_policy(read_json(root / POLICY_REL))
    with ExclusiveFileLock(root / BASE_REL / "store.lock"):
        previous = read_json(root / STORE_REL, empty_store())
        replay(previous, root=root, current=current)
        store, metrics = copy.deepcopy(previous), _base_metrics()
        metrics["request_limit"] = 2*policy["external_issuers_per_fetch"]
        config = read_json(root / "00_project_control/active_production_config.json", {})
        budget = config.get("workflow", {}).get("objective_research_max_tickers", 3)
        # Reuse the authoritative work-budget bounds without inventing another
        # canonical research quota. Already attempted issuers consume this run.
        from research_backlog import MAX_WORK_BUDGET
        require(type(budget) is int and 1 <= budget <= MAX_WORK_BUDGET, "research_work_budget_invalid")
        backlog = read_json(root / "04_research/company_research/research_backlog.local.json", {})
        completed = len(backlog.get("selected_tickers", [])) if backlog.get("generated_at", "")[:10] == current.date().isoformat() else 0
        remaining = max(0, budget-completed)
        rows = {r["ticker"]: r for r in read_csv(root / "03_source_data/equity_research/daily_fundamentals.csv")}
        market_session = latest_published_market_session(current).isoformat()
        held = held_tickers(root)
        prior_report = read_json(root / REPORT_REL, {})
        from capital_escalation import research_priorities
        escalation_rank = {ticker: i for i, ticker in enumerate(research_priorities(root, current))}
        for item in sorted(replay(store).values(), key=lambda i:
                (escalation_rank.get(i["ticker"], len(escalation_rank)), *priority(i, held))):
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
        item["attention_priority_key"] = list(priority(item, held))
        item["stage_durations_seconds"] = {
            "detection_to_research": (aware(item["research_started_at"])-aware(item["first_seen_at"])).total_seconds() if item["research_started_at"] else None,
            "research_to_objective": (aware(item["objective_completed_at"])-aware(item["research_started_at"])).total_seconds() if item["objective_completed_at"] and item["research_started_at"] else None,
            "detection_to_assessment": (aware(item["assessment_at"])-aware(item["first_seen_at"])).total_seconds() if item["assessment_at"] else None}
        project_research_requirements(item, authority)
    items.sort(key=lambda i: tuple(i["attention_priority_key"]))
    active = [i for i in items if i["state"] not in TERMINAL | {"deferred_capacity"}]
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
    atomic_write_json(root / BASE_REL / "run_history" / (canonical_sha256({"generated_at": report["generated_at"], "metrics": metrics})+".json"), report)
    atomic_write_text(root / MARKDOWN_REL, render_report(report))
    return report


def read_report(root: Path, *, current: datetime) -> dict:
    report = read_json(root / REPORT_REL, {})
    require(report.get("schema_version") == "equity_research_opportunity_report_v1"
        and all(report.get(k) is False for k in AUTHORITY), "research_opportunity_report_invalid")
    require(report.get("report_hash") == canonical_sha256({k: v for k, v in report.items() if k != "report_hash"}), "research_opportunity_report_hash_invalid")
    require(report["store_sha256"] == sha256_file(root / STORE_REL), "research_opportunity_report_stale_store")
    clock = aware(report["generated_at"])
    require(clock <= current and current-clock <= timedelta(hours=24), "research_opportunity_report_stale_clock")
    require(report.get("account_authority", {'mode': 'verified_snapshot', 'local_planning_enabled': False})
        == load_authority(root, current), "research_opportunity_report_account_authority_changed")
    replay(read_json(root / STORE_REL), root=root, current=current)
    return report


def summary(root: Path, *, current: datetime) -> dict:
    try:
        for stage in ("intake", "objective"):
            marker = read_json(root / BASE_REL / ("last_"+stage+"_run.json"), {})
            if marker and marker.get("exit_code") != 0:
                return {"status": "failed_or_incomplete", "reason": "latest_research_"+stage+"_run_did_not_complete",
                    "last_run": marker, "report_path": str(MARKDOWN_REL), **AUTHORITY}
        report = read_report(root, current=current)
        return {"status": "ready", "generated_at": report["generated_at"], "report_path": str(MARKDOWN_REL),
            "store_sha256": report["store_sha256"], "metrics": report["metrics"],
            "priority_queue": [{k: i[k] for k in ("ticker", "state", "first_seen_at", "queue_age_hours", "reason_code", "blockers", "owner")} for i in report["priority_queue"][:10]],
            # Work priority is bounded; final decision coverage is not limited
            # to the next ten research jobs. Keep every active candidate visible.
            "decision_candidates": [{**{k: i[k] for k in ("ticker", "state", "reason_code", "blockers", "owner")},
                "instrument_kind": i.get("first_observation", {}).get("instrument_kind"),
                "company_name": i.get("first_observation", {}).get("evidence", {}).get("metrics", {}).get("name"),
                "identity_source_observation": i.get("first_observation", {}).get("observation_id")}
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
