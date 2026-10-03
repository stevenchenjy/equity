#!/usr/bin/env python3
"""Validate and append an analyst opportunity assessment; no canonical effects."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import copy

from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, canonical_sha256, now_et, read_json
from opportunity_contract import (AUTHORITY, BASE_REL, STORE_REL, empty_store, replay,
    require, retain_input, transition, publish_store, validate_receipts)
from research_opportunities import publish_view, _base_metrics
from workflow_evaluation import aware

CONCLUSIONS = {"supported": "research_supported", "unresolved": "insufficient_evidence",
    "rejected": "rejected", "economics_failed": "economics_failed", "reopen": "insufficient_evidence"}


def validate_assessment(proposal: dict, *, root: Path, current: datetime, item: dict) -> dict:
    require(proposal.get("schema_version") == "equity_opportunity_assessment_v1"
        and all(proposal.get(k) is False for k in AUTHORITY), "research_assessment_authority_or_schema_invalid")
    require(proposal.get("opportunity_id") == item["opportunity_id"] and proposal.get("ticker") == item["ticker"], "research_assessment_identity_invalid")
    stamp, next_review = aware(proposal["assessed_at"]), aware(proposal["next_review_at"])
    policy = read_json(root / "01_policies/long_horizon_research_policy.json")
    maximum = policy["maintained_reviews"]["maximum_review_interval_days"]
    require(stamp <= current and stamp < next_review <= stamp+timedelta(days=maximum), "research_assessment_clock_invalid")
    require(proposal.get("conclusion") in CONCLUSIONS and proposal.get("origin") in {"analyst", "owner"}, "research_assessment_conclusion_invalid")
    require(isinstance(proposal.get("hypothesis"), str) and bool(proposal["hypothesis"].strip())
        and bool(proposal.get("reasoning")) and isinstance(proposal.get("missing_evidence"), list), "research_assessment_reasoning_missing")
    require(proposal.get("data_confidence") in {"verified_partial", "verified_complete", "unverified"}
        and proposal.get("investment_conviction") in {"not_assessed", "tentative", "developing", "supported"}, "research_confidence_contract_invalid")
    require(proposal.get("valuation_status") in {"unassessed", "pending", "reviewed", "failed"}, "research_valuation_status_invalid")
    for name in ("supporting_points", "counterpoints"):
        require(isinstance(proposal.get(name), list) and bool(proposal[name]), "research_support_and_counterevidence_required")
        for point in proposal[name]:
            require(bool(point.get("point")) and point.get("evidence_kind") in {"fact", "interpretation", "unknown"}, "research_point_invalid")
            validate_receipts(point["sources"], root=root, current=stamp)
    if proposal["conclusion"] == "supported":
        require(item["state"] in {"evidence_attached", "insufficient_evidence", "research_supported"}
            and proposal["data_confidence"] != "unverified", "research_supported_requires_objective_evidence")
        require(any(p.get("evidence_kind") == "fact" and any(r.get("source_url", "").startswith("https://data.sec.gov/")
            or r.get("source_url", "").startswith("https://www.sec.gov/Archives/") for r in p["sources"])
            for p in proposal["supporting_points"]), "research_supported_requires_primary_company_evidence")
        from opportunity_contract import inside
        from opportunity_evidence import validate_dossier
        attachment = next((t for t in reversed(item["transitions"]) if t["to_state"] == "evidence_attached"), {})
        require(bool(attachment), "research_supported_objective_attachment_missing")
        dossier = read_json(inside(root, attachment["sources"][0]["path"]))
        validate_dossier(dossier, root, stamp, read_json(root / "01_policies/research_opportunity_policy.json")["research_source_max_age_hours"])
        admitted = {r["sha256"] for r in dossier["sources"] if r.get("source_url")}
        require(any(p["evidence_kind"] == "fact" and any(r["sha256"] in admitted for r in p["sources"]) for p in proposal["supporting_points"]), "research_supported_primary_evidence_not_in_objective_contract")
    if proposal["conclusion"] == "reopen":
        require(item["state"] in {"expired", "rejected", "economics_failed"}
            and bool(proposal.get("reassessment_reason")), "research_reopen_requires_recorded_reassessment")
    require(type(proposal.get("request_eligibility_review", False)) is bool, "research_handoff_invalid")
    if proposal.get("request_eligibility_review"):
        require(proposal["conclusion"] == "supported" and proposal["valuation_status"] == "reviewed", "research_handoff_requires_separate_economic_review")
    return proposal


def apply_assessment(root: Path, proposal: dict, *, current: datetime, apply: bool = False) -> dict:
    with ExclusiveFileLock(root / BASE_REL / "store.lock"):
        previous = read_json(root / STORE_REL, empty_store())
        items = replay(previous, root=root, current=current)
        item = items[proposal["opportunity_id"]]
        validate_assessment(proposal, root=root, current=current, item=item)
        if not apply:
            return {"status": "validated", **AUTHORITY}
        digest = canonical_sha256(proposal)
        # An interrupted/repeated analyst request is idempotent by its exact
        # accepted proposal, not by today's regenerated report.
        if any(t.get("reason_code") == "recorded_assessment:"+digest for t in item["transitions"]):
            return {"status": "already_recorded", **AUTHORITY}
        path = root / BASE_REL / "assessments" / (digest+".json")
        atomic_write_json(path, proposal)
        source = retain_input(root, path, available_at=proposal["assessed_at"])
        store = copy.deepcopy(previous)
        transition(store, item["opportunity_id"], CONCLUSIONS[proposal["conclusion"]], owner="analyst_assessment",
            reason="recorded_assessment:"+digest, sources=[source], blockers=proposal["missing_evidence"], current=current)
        if proposal.get("request_eligibility_review"):
            transition(store, item["opportunity_id"], "eligibility_review", owner="analyst_assessment",
                reason="existing_production_contract_review_required", sources=[source],
                blockers=["canonical_admission_and_current_evidence", "existing_account_risk_and_execution_contracts"], current=current)
        publish_store(root, store, previous=previous, current=current)
        metrics = _base_metrics(); metrics["analyst_assessments_completed"] = 1
        diagnostics = read_json(root / BASE_REL / "report.json", {}).get("diagnostics", {})
        publish_view(root, store, current=current, metrics=metrics, diagnostics=diagnostics)
        return {"status": "recorded", "assessment_id": digest, **AUTHORITY}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = apply_assessment(args.root, read_json(args.input), current=now_et(), apply=args.apply)
    print(f"research_assessment={result['status']} canonical_effect=false email_sent=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
