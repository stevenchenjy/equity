"""Bounded objective research, isolated from canonical financial admission.

Reuse the production SEC fact selector and raw-byte verifier. Outside-universe
issuer rows live only in this research store. Cache-only runs never call a
provider; network runs reserve each issuer/session attempt before requesting.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import time
import urllib.request

from daily_common import atomic_write_json, canonical_sha256, read_json, now_et
from earnings_incorporation import retain_sec_response
from long_horizon_research import source_facts
from opportunity_contract import BASE_REL, POLICY_REL, AUTHORITY, inside, require, retain_input, validate_policy
from opportunity_triggers import verified_financial_sources
from refresh_daily_evidence import (fundamental_row, recent_filings,
    current_submission_entity_name, SEC_SUBMISSIONS_URL, SEC_COMPANYFACTS_URL,
    sec_user_agent_failure_reason)
from workflow_evaluation import aware

EVIDENCE_REL = BASE_REL / "objective"
ATTEMPTS_REL = BASE_REL / "fetch_attempts.json"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_sec(root: Path, url: str, current: datetime, metrics: dict) -> tuple[dict, dict]:
    """Fixed public SEC endpoints; no retry, secret, redirect or unbounded read."""
    require(re.fullmatch(r"https://data\.sec\.gov/(submissions/CIK\d{10}\.json|api/xbrl/companyfacts/CIK\d{10}\.json)", url), "research_sec_url_invalid")
    agent = os.environ.get("PHASE5R_SEC_USER_AGENT", "")
    require(sec_user_agent_failure_reason(agent) is None, "research_sec_user_agent_unavailable")
    require(metrics["network_requests"] < metrics["request_limit"], "research_request_budget_exceeded")
    metrics["network_requests"] += 1
    request = urllib.request.Request(url, headers={"User-Agent": agent,
        "Accept": "application/json", "Accept-Encoding": "identity"})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        raw = response.read(30 * 1024 * 1024 + 1)
    require(len(raw) <= 30 * 1024 * 1024, "research_sec_response_oversize")
    data = json.loads(raw)
    require(isinstance(data, dict), "research_sec_response_invalid")
    receipt = retain_sec_response(raw, url=url, retrieved_at=now_et().isoformat(), root=root)
    require(bool(receipt), "research_sec_receipt_missing")
    return data, receipt


def validate_dossier(dossier: dict, root: Path, current: datetime, max_age: int) -> dict:
    from opportunity_contract import validate_receipts
    require(dossier.get("schema_version") == "equity_opportunity_objective_v1"
        and all(dossier.get(k) is False for k in AUTHORITY), "research_objective_contract_invalid")
    require(dossier.get("dossier_hash") == canonical_sha256({k: v for k, v in dossier.items() if k != "dossier_hash"}), "research_dossier_hash_invalid")
    require(timedelta(0) <= current-aware(dossier["observed_at"]) <= timedelta(hours=max_age), "research_dossier_stale")
    validate_receipts(dossier["sources"], root=root, current=current)
    require(dossier["financial_row"]["ticker"] == dossier["ticker"], "research_dossier_identity_invalid")
    row = dossier["financial_row"]
    cik = int(row["cik"])
    primary = {r["source_url"]: r for r in dossier["sources"] if r.get("source_url")}
    sub_url, facts_url = SEC_SUBMISSIONS_URL.format(cik=cik), SEC_COMPANYFACTS_URL.format(cik=cik)
    require(sub_url in primary and facts_url in primary, "research_dossier_primary_sources_missing")
    sub = read_json(inside(root, primary[sub_url]["path"]))
    facts = read_json(inside(root, primary[facts_url]["path"]))
    current_submission_entity_name(sub, ticker=dossier["ticker"], cik=cik)
    require(int(facts.get("cik", -1)) == cik, "research_dossier_primary_identity_conflict")
    if dossier["scope"] == "noncanonical_official_issuer_research_only":
        filings = recent_filings(sub, as_of=aware(row["fetched_at"]).date())
        selected = fundamental_row(dossier["ticker"], cik, facts, row["fetched_at"],
            acceptance_by_accession={f["accession_number"]: f["accepted_at"] for f in filings})
        require(selected == row, "research_dossier_selector_binding_invalid")
    elif dossier["scope"] == "existing_canonical_fact_observations_research_attachment":
        selections = [read_json(inside(root, r["path"])) for r in dossier["sources"] if not r.get("source_url")]
        require(any(s.get("ticker") == dossier["ticker"] and s.get("financial_selection_sha256") == canonical_sha256(row)
            and s.get("submissions", {}).get("raw_sha256") == primary[sub_url]["sha256"]
            and s.get("companyfacts", {}).get("raw_sha256") == primary[facts_url]["sha256"] for s in selections), "research_dossier_canonical_selection_unbound")
    else:
        raise ValueError("research_dossier_scope_invalid")
    require(dossier["facts"] == source_facts(row, dossier["observed_at"]), "research_dossier_fact_contract_invalid")
    return dossier


def _seal(root: Path, ticker: str, row: dict, sources: list, current: datetime, scope: str) -> dict:
    maximum_age = validate_policy(read_json(root / POLICY_REL))["research_source_max_age_hours"]
    previous = read_json(root / EVIDENCE_REL / (ticker+".json"), {})
    if previous and {k: v for k, v in previous.get("financial_row", {}).items() if k != "fetched_at"} == {k: v for k, v in row.items() if k != "fetched_at"}:
        try:
            return validate_dossier(previous, root, current, maximum_age)
        except (ValueError, KeyError, OSError, TypeError):
            pass
    facts = source_facts(row, current.isoformat())
    dossier = {"schema_version": "equity_opportunity_objective_v1", "ticker": ticker,
        "observed_at": current.isoformat(), "financial_row": row, "facts": facts,
        "sources": sources, "scope": scope, "investment_conviction": "not_assessed",
        "facts_available": [k for k, v in facts.items() if v["value"] is not None],
        "missing_evidence": [k for k, v in facts.items() if v["value"] is None]
            + ["business_durability", "counterevidence", "company_specific_valuation"],
        "canonical_fields_admitted": 0, **AUTHORITY}
    dossier["dossier_hash"] = canonical_sha256(dossier)
    validate_dossier(dossier, root, current, maximum_age)
    atomic_write_json(root / EVIDENCE_REL / "history" / (dossier["dossier_hash"] + ".json"), dossier)
    atomic_write_json(root / EVIDENCE_REL / (ticker + ".json"), dossier)
    return dossier


def objective_research(root: Path, item: dict, *, current: datetime, policy: dict,
                       canonical_rows: dict, market_session: str, allow_network: bool,
                       metrics: dict, fetcher=request_sec) -> tuple[dict | None, str]:
    ticker = item["ticker"]
    if item["instrument_kind"] == "etf":
        return None, "issuer_prospectus_and_structure_review_required"
    if ticker in canonical_rows:
        row = canonical_rows[ticker]
        try:
            sources = verified_financial_sources(root, row, current, policy["research_source_max_age_hours"])
            dossier = _seal(root, ticker, row, sources, current, "existing_canonical_fact_observations_research_attachment")
            return (dossier if dossier["facts_available"] else None), ("source_bound_objective_attachment" if dossier["facts_available"] else "canonical_financial_period_or_provenance_unresolved")
        except (ValueError, KeyError, OSError, TypeError):
            return None, "canonical_official_fact_source_binding_unverified"
    dossier_path = root / EVIDENCE_REL / (ticker + ".json")
    previous = read_json(dossier_path, {})
    if previous:
        try:
            return validate_dossier(previous, root, current, policy["research_source_max_age_hours"]), "retained_research_only_objective_evidence"
        except (ValueError, KeyError, OSError, TypeError):
            # Preserve the version; a failed current validation is not negative
            # business evidence and may be resolved by another official fetch.
            pass
    if not allow_network:
        return None, "official_issuer_sources_not_cached_network_refresh_required"
    if metrics["external_issuers_attempted"] >= policy["external_issuers_per_fetch"]:
        return None, "bounded_external_research_capacity_wait"
    if sec_user_agent_failure_reason(os.environ.get("PHASE5R_SEC_USER_AGENT", "")):
        return None, "research_sec_user_agent_unavailable"
    attempts = read_json(root / ATTEMPTS_REL, {"schema_version": "equity_opportunity_fetch_attempts_v1", "attempts": {}})
    require(attempts.get("schema_version") == "equity_opportunity_fetch_attempts_v1"
        and isinstance(attempts.get("attempts"), dict), "research_fetch_attempt_store_invalid")
    for identity, attempt in attempts["attempts"].items():
        require(identity == attempt.get("ticker", "")+":"+attempt.get("market_session", "")
            and attempt.get("status") in {"reserved", "completed", "failed"}
            and type(attempt.get("network_requests")) is int and 0 <= attempt["network_requests"] <= 2
            and all(attempt.get(k) is False for k in AUTHORITY), "research_fetch_attempt_contract_invalid")
    key = ticker + ":" + market_session
    if key in attempts["attempts"]:
        return None, attempts["attempts"][key].get("reason_code", "prior_issuer_session_fetch_attempt_requires_next_close")
    cik = read_json(root / "03_source_data/equity_research/sec_ticker_map.local.json", {}).get(ticker)
    if type(cik) is not int or cik <= 0:
        return None, "verified_issuer_cik_mapping_required"
    # Reserve durably before requesting. A crash can strand an attempt, never
    # create an unbounded retry on the next scheduler tick.
    attempts["attempts"][key] = {"ticker": ticker, "market_session": market_session,
        "reserved_at": current.isoformat(), "status": "reserved", "network_requests": 0,
        "reason_code": "prior_issuer_session_fetch_attempt_requires_next_close", **AUTHORITY}
    atomic_write_json(root / ATTEMPTS_REL, attempts)
    metrics["external_issuers_attempted"] += 1
    before_requests = metrics["network_requests"]
    try:
        submissions, sub_receipt = fetcher(root, SEC_SUBMISSIONS_URL.format(cik=cik), current, metrics)
        sources = [retain_input(root, inside(root, sub_receipt["raw_path"]),
            available_at=sub_receipt["retrieved_at"], source_url=sub_receipt["source_url"])]
        attempts["attempts"][key].update(sources=sources,
            network_requests=metrics["network_requests"]-before_requests)
        atomic_write_json(root / ATTEMPTS_REL, attempts)
        current_submission_entity_name(submissions, ticker=ticker, cik=cik)
        filings = recent_filings(submissions, as_of=current.date())
        time.sleep(0.20)
        companyfacts, facts_receipt = fetcher(root, SEC_COMPANYFACTS_URL.format(cik=cik), current, metrics)
        sources.append(retain_input(root, inside(root, facts_receipt["raw_path"]),
            available_at=facts_receipt["retrieved_at"], source_url=facts_receipt["source_url"]))
        attempts["attempts"][key].update(sources=sources,
            network_requests=metrics["network_requests"]-before_requests)
        atomic_write_json(root / ATTEMPTS_REL, attempts)
        require(int(companyfacts.get("cik", -1)) == cik, "research_companyfacts_identity_conflict")
        selection_clock = max(current, aware(sub_receipt["retrieved_at"]), aware(facts_receipt["retrieved_at"]))
        row = fundamental_row(ticker, cik, companyfacts, selection_clock.isoformat(),
            acceptance_by_accession={f["accession_number"]: f["accepted_at"] for f in filings})
        dossier = _seal(root, ticker, row, sources, selection_clock, "noncanonical_official_issuer_research_only")
        reason = "source_bound_objective_attachment" if dossier["facts_available"] else "issuer_financial_period_or_provenance_unresolved"
        attempts["attempts"][key].update(status="completed", reason_code=reason,
            dossier_hash=dossier["dossier_hash"], sources=sources)
        return (dossier if dossier["facts_available"] else None), reason
    except (ValueError, KeyError, OSError, TypeError):
        reason = "official_issuer_source_fetch_or_validation_failed"
        attempts["attempts"][key].update(status="failed", reason_code=reason)
        return None, reason
    finally:
        attempts["attempts"][key]["network_requests"] = metrics["network_requests"]-before_requests
        atomic_write_json(root / ATTEMPTS_REL, attempts)
