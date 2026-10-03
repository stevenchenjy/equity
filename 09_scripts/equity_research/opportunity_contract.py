"""Authoritative research-only contracts, journal replay and transitions.

An atomic store contains the whole append-only journal. Views never become input
state. Historical receipts address immutable source bytes, not today's reports.
"""
from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from daily_common import atomic_write_json, canonical_sha256, read_json, sha256_file
from workflow_evaluation import aware

BASE_REL = Path("04_research/company_research/opportunities.local")
STORE_REL = BASE_REL / "store.json"
REPORT_REL = BASE_REL / "report.json"
MARKDOWN_REL = Path("08_reviews/current/research_opportunities.local.md")
POLICY_REL = Path("01_policies/research_opportunity_policy.json")
AUTHORITY = {"capital_authority": False, "canonical_admission": False,
             "automatic_action_allowed": False, "execution_authority": False}
FAMILIES = frozenset({"market", "business", "catalyst", "request", "experiment"})
TERMINAL = frozenset({"rejected", "economics_failed", "expired"})
STATES = frozenset({"queued", "researching", "evidence_attached", "data_blocked",
    "insufficient_evidence", "research_supported", "eligibility_review", "deferred_capacity"}) | TERMINAL
# Owner and permitted source states belong here, not in reports/CLI adapters.
TRANSITIONS = {
    "researching": ("objective_research", {"queued", "data_blocked", "insufficient_evidence", "evidence_attached"}),
    "evidence_attached": ("objective_research", {"researching"}),
    "data_blocked": ("objective_research", {"queued", "researching", "evidence_attached", "insufficient_evidence", "data_blocked", "research_supported", "eligibility_review"}),
    "insufficient_evidence": ("analyst_assessment", set(STATES)),
    "research_supported": ("analyst_assessment", {"evidence_attached", "insufficient_evidence", "research_supported"}),
    "rejected": ("analyst_assessment", set(STATES) - TERMINAL),
    "economics_failed": ("analyst_assessment", {"evidence_attached", "research_supported", "eligibility_review", "insufficient_evidence"}),
    "eligibility_review": ("analyst_assessment", {"research_supported"}),
    "expired": ("research_orchestration", set(STATES) - TERMINAL),
    "queued": ("research_orchestration", {"deferred_capacity"}),
    "deferred_capacity": ("research_orchestration", {"queued", "data_blocked", "evidence_attached", "insufficient_evidence"}),
}
TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")
HEX = re.compile(r"[a-f0-9]{64}")


def require(value: Any, code: str) -> None:
    if not value:
        raise ValueError(code)


def inside(root: Path, locator: str) -> Path:
    require(isinstance(locator, str) and locator and not Path(locator).is_absolute(), "research_path_invalid")
    path = (root / locator).resolve()
    require(path.is_relative_to(root.resolve()), "research_path_escape")
    return path


def validate_policy(policy: dict) -> dict:
    require(isinstance(policy, dict) and policy.get("schema_version") == "equity_research_opportunity_policy_v1", "research_policy_invalid")
    limits = {"active_capacity": (1, 100), "new_opportunities_per_run": (1, 20),
        "discovery_stock_limit": (1, 10), "discovery_etf_limit": (0, 10),
        "external_issuers_per_fetch": (0, 3), "research_source_max_age_hours": (1, 72),
        "stale_after_market_sessions": (1, 20)}
    for key, (low, high) in limits.items():
        require(type(policy.get(key)) is int and low <= policy[key] <= high, "research_work_limit_invalid")
    for key in ("capital_authority", "automatic_action_allowed", "canonical_admission"):
        require(policy.get(key) is False, "research_policy_authority_violation")
    require(policy["new_opportunities_per_run"] <= policy["active_capacity"], "research_capacity_invalid")
    return policy


def retain_input(root: Path, path: Path, *, available_at: str, source_url: str = "") -> dict:
    """Preserve exact bytes before a producer can overwrite its current output."""
    aware(available_at)
    require(path.resolve().is_relative_to(root.resolve()), "research_path_escape")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    relative = BASE_REL / "inputs" / digest
    destination = root / relative
    if destination.exists():
        require(sha256_file(destination) == digest, "research_input_history_corrupt")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            import os
            os.fsync(stream.fileno())
    return {"path": str(relative), "sha256": digest, "available_at": available_at,
            "source_url": source_url, "original_locator": str(path.resolve().relative_to(root.resolve()))}


def validate_receipts(receipts: list, *, root: Path, current: datetime) -> None:
    require(isinstance(receipts, list) and bool(receipts), "research_receipts_missing")
    for receipt in receipts:
        require(isinstance(receipt, dict) and HEX.fullmatch(str(receipt.get("sha256", ""))), "research_receipt_invalid")
        require(aware(receipt["available_at"]) <= current, "research_source_from_future")
        require(sha256_file(inside(root, receipt["path"])) == receipt["sha256"], "research_source_changed")


def validate_observation(packet: dict, *, root: Path, current: datetime) -> dict:
    require(packet.get("schema_version") == "equity_research_observation_v1", "research_observation_schema")
    require(TICKER.fullmatch(str(packet.get("ticker", ""))) and packet.get("family") in FAMILIES, "research_observation_identity")
    require(packet.get("instrument_kind") in {"stock", "etf"}, "research_instrument_invalid")
    require(all(packet.get(k) is False for k in AUTHORITY), "research_observation_authority_violation")
    detected = aware(packet["detected_at"])
    require(aware(packet["available_at"]) <= detected <= current, "research_observation_clock_invalid")
    require(isinstance(packet.get("missing_evidence"), list) and isinstance(packet.get("evidence"), dict), "research_evidence_contract")
    require(packet.get("evidence_key") == canonical_sha256(packet["evidence"]), "research_evidence_identity")
    key = {k: packet[k] for k in ("ticker", "family", "trigger", "evidence_key")}
    require(packet.get("observation_id") == canonical_sha256(key), "research_observation_hash")
    require(isinstance(packet.get("producer"), dict) and bool(packet["producer"].get("implementation_sha256"))
        and bool(packet["producer"].get("policy_sha256")), "research_producer_unbound")
    validate_receipts(packet["sources"], root=root, current=detected)
    return packet


def empty_store() -> dict:
    return {"schema_version": "equity_research_opportunity_store_v1", "events": [], **AUTHORITY}


def replay(store: dict, *, root: Path | None = None, current: datetime | None = None) -> dict[str, dict]:
    require(store.get("schema_version") == "equity_research_opportunity_store_v1" and all(store.get(k) is False for k in AUTHORITY), "research_store_invalid")
    require(isinstance(store.get("events"), list), "research_journal_invalid")
    result, previous, ids, observations, last_clock = {}, "", set(), set(), None
    for event in store["events"]:
        require(event.get("previous_hash") == previous and event.get("record_hash") == canonical_sha256({k: v for k, v in event.items() if k != "record_hash"}), "research_journal_hash_invalid")
        require(all(event.get(k) is False for k in AUTHORITY), "research_journal_authority_violation")
        clock = aware(event["recorded_at"])
        require((current is None or clock <= current) and (last_clock is None or clock >= last_clock), "research_journal_clock_regression")
        identity, kind = event["opportunity_id"], event["kind"]
        if kind == "detected":
            packet = event["observation"]
            require(identity not in ids and packet["observation_id"] not in observations, "research_duplicate_detection")
            require(identity == canonical_sha256({"first_observation_id": packet["observation_id"], "ticker": packet["ticker"]}), "research_opportunity_identity")
            require(event["to_state"] in {"queued", "deferred_capacity"} and event["owner"] == "research_orchestration", "research_admission_transition_invalid")
            if root:
                validate_observation(packet, root=root, current=clock)
            ids.add(identity); observations.add(packet["observation_id"])
            result[identity] = {"opportunity_id": identity, "ticker": packet["ticker"], "instrument_kind": packet["instrument_kind"],
                "first_seen_at": packet["detected_at"], "first_observation": copy.deepcopy(packet),
                "observations": [copy.deepcopy(packet)], "initial_state": event["to_state"], "state": event["to_state"],
                "last_evidence_at": packet["detected_at"], "research_started_at": "", "objective_completed_at": "",
                "assessment_at": "", "transitions": [], "blockers": event.get("blockers", []),
                "owner": event["owner"], "reason_code": event["reason_code"], **AUTHORITY}
        elif kind == "observed":
            require(identity in result, "research_unknown_opportunity")
            packet = event["observation"]
            require(packet["ticker"] == result[identity]["ticker"] and packet["observation_id"] not in observations, "research_duplicate_observation")
            if root:
                validate_observation(packet, root=root, current=clock)
            observations.add(packet["observation_id"])
            result[identity]["observations"].append(copy.deepcopy(packet))
            result[identity]["last_evidence_at"] = packet["detected_at"]
        elif kind == "transition":
            require(identity in result and event["to_state"] in TRANSITIONS, "research_transition_invalid")
            item = result[identity]
            owner, allowed = TRANSITIONS[event["to_state"]]
            require(event["owner"] == owner and event["from_state"] == item["state"] and item["state"] in allowed, "research_transition_owner_or_state_invalid")
            require(bool(event.get("reason_code")) and isinstance(event.get("blockers"), list), "research_transition_reason_missing")
            if root:
                validate_receipts(event["sources"], root=root, current=clock)
            item.update(state=event["to_state"], owner=owner, reason_code=event["reason_code"], blockers=event["blockers"])
            item["transitions"].append(copy.deepcopy(event))
            if event["to_state"] == "researching" and not item["research_started_at"]:
                item["research_started_at"] = event["recorded_at"]
            if event["to_state"] == "evidence_attached" and not item["objective_completed_at"]:
                item["objective_completed_at"] = event["recorded_at"]
            if owner == "analyst_assessment":
                item["assessment_at"] = event["recorded_at"]
        else:
            raise ValueError("research_journal_kind_invalid")
        previous, last_clock = event["record_hash"], clock
    return result


def append_event(store: dict, event: dict) -> None:
    event = {**copy.deepcopy(event), **AUTHORITY, "previous_hash": store["events"][-1]["record_hash"] if store["events"] else ""}
    event["record_hash"] = canonical_sha256(event)
    store["events"].append(event)


def transition(store: dict, identity: str, target: str, *, owner: str, reason: str,
               sources: list, blockers: list, current: datetime) -> None:
    item = replay(store)[identity]
    append_event(store, {"kind": "transition", "opportunity_id": identity,
        "from_state": item["state"], "to_state": target, "owner": owner, "reason_code": reason,
        "sources": sources, "blockers": blockers, "recorded_at": current.isoformat()})
    replay(store)


def publish_store(root: Path, store: dict, *, previous: dict, current: datetime) -> None:
    require(store["events"][:len(previous["events"])] == previous["events"], "research_history_rewrite_forbidden")
    replay(store, root=root, current=current)
    old_path = root / STORE_REL
    require(read_json(old_path, empty_store()) == previous, "research_store_changed_before_publication")
    if store == previous and old_path.exists():
        return
    for payload in (previous, store):
        atomic_write_json(root / BASE_REL / "history" / (canonical_sha256(payload) + ".json"), payload)
    atomic_write_json(old_path, store)
