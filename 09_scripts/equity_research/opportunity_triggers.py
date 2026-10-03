"""Adapters from validated existing observations to research attention only.

Strength/volume remain one correlated market packet. Positive business changes
reuse source_facts and existing review thresholds, with comparable quarters.
No adapter reads available cash, position limits or order eligibility.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import subprocess

from daily_common import canonical_sha256, read_csv, read_json, sha256_file
from earnings_incorporation import CACHE_REL, _verified_raw
from investment_plans import regular_close
from long_horizon_research import source_facts
from market_discovery import CACHE_RELATIVE, load_discovery
from opportunity_contract import (AUTHORITY, POLICY_REL, TICKER, inside, require,
    retain_input, validate_observation, validate_receipts)
from workflow_evaluation import aware


def producer(root: Path, policy: dict) -> dict:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
            text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unavailable_explicit_file_binding"
    return {"module": "opportunity_triggers", "commit": commit,
        "implementation_sha256": sha256_file(Path(__file__)), "policy_sha256": canonical_sha256(policy),
        "measurement_contract": {"version": "research_observation_path_v1",
            "horizons_market_sessions": read_json(root / "00_project_control/active_production_config.json", {}).get("outcome_tracking", {}).get("horizons_market_sessions", [1, 5, 20, 60]),
            "one_way_cost_bps": read_json(root / "01_policies/momentum_experiment.json")["one_way_cost_bps"],
            "scope": "prospective hypothetical one-share adjusted price path; no simulated position in account",
            "baseline": "existing maintained universe and research queue at detection"}}


def packet(*, ticker: str, family: str, trigger: str, evidence: dict, sources: list,
           current: datetime, produced_by: dict, kind: str = "stock", missing: list | None = None) -> dict:
    result = {"schema_version": "equity_research_observation_v1", "ticker": ticker,
        "family": family, "trigger": trigger, "evidence": evidence,
        "evidence_key": canonical_sha256(evidence), "sources": sources,
        "available_at": max((r["available_at"] for r in sources), key=aware),
        "detected_at": current.isoformat(), "producer": produced_by,
        "instrument_kind": kind, "missing_evidence": missing or [], **AUTHORITY}
    result["observation_id"] = canonical_sha256({k: result[k] for k in ("ticker", "family", "trigger", "evidence_key")})
    return result


def verified_financial_sources(root: Path, row: dict, current: datetime, max_age: int) -> list:
    """Reuse the SEC selector's raw-byte and identity contracts; never guess facts."""
    ticker = row["ticker"]
    path = root / CACHE_REL / f"{ticker}.selection.json"
    selection = read_json(path, {})
    require(selection.get("ticker") == ticker and selection.get("financial_selection_sha256") == canonical_sha256(row), "research_financial_selection_unbound")
    stamp = aware(selection["selected_at"])
    require(stamp <= current, "research_financial_selection_future")
    sources = []
    for key in ("submissions", "companyfacts"):
        receipt = selection[key]
        raw = _verified_raw(root, receipt)
        require(raw is not None, "research_financial_raw_unverified")
        retrieved = aware(receipt["retrieved_at"])
        require(timedelta(0) <= current - retrieved <= timedelta(hours=max_age), "research_financial_source_stale")
        require(int(raw.get("cik", -1)) == int(row["cik"]) == int(selection["cik"]), "research_financial_identity_conflict")
        if key == "submissions":
            require(ticker in [str(t).upper() for t in raw.get("tickers", [])], "research_ticker_identity_conflict")
        sources.append(retain_input(root, inside(root, receipt["raw_path"]),
            available_at=receipt["retrieved_at"], source_url=receipt["source_url"]))
    sources.append(retain_input(root, path, available_at=selection["selected_at"]))
    return sources


def positive_changes(row: dict, current: datetime, thresholds: dict) -> list[dict]:
    """Quarter-to-quarter changes in comparable YoY growth/margin, not forecasts."""
    facts = source_facts(row, current.isoformat())
    if row.get("financial_period_type") not in {"quarter", "quarterly"}:
        return []
    try:
        days = (date.fromisoformat(row["latest_period_end"]) - date.fromisoformat(row["prior_quarter_period_end"])).days
    except (KeyError, ValueError):
        return []
    if not 50 <= days <= 140:
        return []
    result = []
    for latest, prior, threshold_key, code in (
        ("revenue_yoy_pct", "revenue_yoy_prior_quarter_pct", "revenue_yoy_slowdown_percentage_points", "revenue_growth_acceleration"),
        ("net_margin_pct", "net_margin_prior_quarter_pct", "net_margin_decline_percentage_points", "net_margin_improvement"),
    ):
        a, b = facts[latest], facts[prior]
        if a["value"] is None or b["value"] is None:
            continue
        if (a["provenance"].get("unit") != b["provenance"].get("unit")
                or not a["provenance"].get("unit")
                or b["provenance"].get("end") != row["prior_quarter_period_end"]):
            continue
        # Derived comparable fields are selected together by the existing
        # period-bound SEC selector; retain all tags/units/components.
        change = a["value"] - b["value"]
        if change >= thresholds[threshold_key] and change > 0:
            result.append({"code": code, "change_percentage_points": round(change, 4),
                "current": {k: v for k, v in a.items() if k != "fetched_at"},
                "previous": {**{k: v for k, v in b.items() if k != "fetched_at"}, "financial_period_end": row["prior_quarter_period_end"]},
                "current_period_end": row["latest_period_end"],
                "previous_period_end": row["prior_quarter_period_end"],
                "threshold_source": "01_policies/long_horizon_research_policy.json:" + threshold_key,
                "interpretation": "Research comparable operating change and counterevidence; no confidence or eligibility promotion."})
    return result


def validate_approval(record: dict, *, root: Path, current: datetime) -> dict:
    """Maturity alone cannot grant research use; owner receipt and review bind it."""
    require(record.get("schema_version") == "equity_experiment_research_approval_v1"
        and record.get("scope") == "research_attention_only" and record.get("owner_authorized") is True,
        "experiment_research_approval_missing")
    require(all(record.get(k) is False for k in AUTHORITY), "experiment_approval_authority_violation")
    require(aware(record["approved_at"]) <= current, "experiment_approval_future")
    for name in ("owner_receipt", "review_receipt"):
        validate_receipts([record[name]], root=root, current=aware(record["approved_at"]))
    owner = json.loads(inside(root, record["owner_receipt"]["path"]).read_text())
    require(owner.get("origin") == "owner" and owner.get("scope") == "research_attention_only"
        and owner.get("experiment_version") == record.get("experiment_version") and bool(owner.get("instruction")), "experiment_owner_instruction_unverified")
    review = read_json(inside(root, record["review_receipt"]["path"]))
    from momentum_experiment_review import SCHEMA, build_review, POLICY as REVIEW_POLICY
    from momentum_experiment import OUTPUT as EXPERIMENT_OUTPUT, POLICY as EXPERIMENT_POLICY
    require(review.get("schema_version") == SCHEMA and aware(review["generated_at"]) <= aware(record["approved_at"]), "experiment_review_receipt_invalid")
    validate_receipts(record.get("review_inputs", []), root=root, current=aware(record["approved_at"]))
    inputs = {r["original_locator"]: r for r in record["review_inputs"]}
    expected = {str(REVIEW_POLICY), str(EXPERIMENT_POLICY), str(EXPERIMENT_OUTPUT / "ledger.jsonl"),
        str(EXPERIMENT_OUTPUT / "report.json"), str(EXPERIMENT_OUTPUT / "status.json")}
    require(set(inputs) == expected and len(inputs) == len(record["review_inputs"])
        and {name: r["sha256"] for name, r in inputs.items()} == review.get("source_hashes"), "experiment_review_sources_unbound")
    original = {name: inside(root, r["path"]).read_bytes() for name, r in inputs.items()}
    ledger = [json.loads(line) for line in original[str(EXPERIMENT_OUTPUT / "ledger.jsonl")].splitlines() if line.strip()]
    rebuilt = build_review(policy=json.loads(original[str(REVIEW_POLICY)]),
        frozen_policy=json.loads(original[str(EXPERIMENT_POLICY)]), records=ledger,
        experiment_report=json.loads(original[str(EXPERIMENT_OUTPUT / "report.json")]),
        experiment_status=json.loads(original[str(EXPERIMENT_OUTPUT / "status.json")]),
        ledger_sha256=inputs[str(EXPERIMENT_OUTPUT / "ledger.jsonl")]["sha256"],
        current=aware(review["generated_at"]), input_hashes=review["source_hashes"])
    require(rebuilt == review, "experiment_review_does_not_match_retained_inputs")
    require(review.get("automatic_promotion") is False and review.get("automatic_action_allowed") is False,
        "experiment_review_authority_invalid")
    cohorts = review.get("cohorts", [])
    require(any(c.get("experiment_version") == record["experiment_version"]
        and c.get("complete") is True and c.get("policy_sha256") == record.get("policy_sha256") for c in cohorts), "experiment_review_cohort_incomplete")
    from frozen_momentum_runtime import load_registry, verified_snapshot
    archive = load_registry(root).get(record["experiment_version"])
    require(archive is not None, "experiment_research_version_unregistered")
    reviewed_observations = [r for r in ledger if r.get("kind") == "observation"
        and r["experiment_version"] == record["experiment_version"]]
    require(reviewed_observations and all(r["policy_sha256"] == record["policy_sha256"]
        and r["inputs"].get("implementation_sha256") == canonical_sha256(archive["implementation_files"])
        for r in reviewed_observations), "experiment_review_implementation_not_registered_binding")
    with verified_snapshot(archive, repository=root) as (snapshot, pinned_policy):
        require(pinned_policy.get("version") == record["experiment_version"]
            and canonical_sha256(pinned_policy) == record["policy_sha256"], "experiment_research_policy_not_registered_binding")
    require(isinstance(record.get("allowed_dispositions"), list) and bool(record["allowed_dispositions"]), "experiment_research_trigger_definition_missing")
    require(set(record["allowed_dispositions"]) <= {r["disposition"] for r in ledger
        if r.get("kind") == "observation" and r["experiment_version"] == record["experiment_version"]}, "experiment_research_disposition_not_observed")
    require(record.get("approval_id") == canonical_sha256({k: v for k, v in record.items() if k != "approval_id"}), "experiment_approval_hash_invalid")
    return record


def collect_triggers(root: Path, *, current: datetime, policy: dict) -> tuple[list, dict]:
    produced_by = producer(root, policy)
    packets, diagnostics = [], {"unverified": [], "experiment_review_only": [], "network_requests": 0}
    discovery = load_discovery(root, current)
    diagnostics["discovery_status"] = discovery["status"]
    diagnostics["discovery_candidates"] = discovery.get("coverage", {}).get("screen_eligible_count", 0)
    if discovery.get("complete") is True:
        clock = aware(discovery["fetched_at"])
        require(regular_close(discovery["as_of_session"]) <= clock <= current, "discovery_observation_clock_invalid")
        receipt = retain_input(root, root / CACHE_RELATIVE / "latest.local.json", available_at=discovery["fetched_at"])
        baseline_path = root / "04_research/company_research/research_backlog.local.json"
        baseline = read_json(baseline_path, {})
        baseline_sources = [retain_input(root, baseline_path, available_at=baseline["generated_at"])] if baseline else []
        baseline_tickers = [r["ticker"] for r in baseline.get("issuer_queue", [])]
        for name, limit, kind in (("top_stocks", policy["discovery_stock_limit"], "stock"), ("top_etfs", policy["discovery_etf_limit"], "etf")):
            for row in discovery[name][:limit]:
                if not TICKER.fullmatch(str(row.get("ticker", ""))):
                    diagnostics["unverified"].append({"ticker": row.get("ticker"), "reason": "research_ticker_syntax_unsupported"}); continue
                evidence = {"market_session": discovery["as_of_session"], "price_basis": discovery["price_basis"],
                    "market_context": {"methodology": discovery["methodology"], "coverage": discovery["coverage"]},
                    "metrics": row, "live_entry_verified": False}
                observation = packet(ticker=row["ticker"], family="market", trigger="independent_broad_discovery",
                    evidence=evidence, sources=[receipt, *baseline_sources], current=current, produced_by=produced_by, kind=kind,
                    missing=["business_quality", "catalyst_impact", "valuation", "canonical_admission", "live_execution_evidence"]
                    + (["issuer_structure_review"] if kind == "etf" else []))
                observation["baseline_at_detection"] = {"existing_research_queue": baseline_tickers,
                    "status": "retained_snapshot_not_current_capital_authority" if baseline else "unavailable"}
                packets.append(observation)
    threshold_policy = read_json(root / "01_policies/long_horizon_research_policy.json")
    for row in read_csv(root / "03_source_data/equity_research/daily_fundamentals.csv"):
        changes = positive_changes(row, current, threshold_policy["review_thresholds"])
        if not changes:
            continue
        try:
            sources = verified_financial_sources(root, row, current, policy["research_source_max_age_hours"])
            sources.append(retain_input(root, root / "01_policies/long_horizon_research_policy.json", available_at=current.isoformat()))
            packets.append(packet(ticker=row["ticker"], family="business", trigger="positive_comparable_business_change",
                evidence={"changes": changes, "financial_period_end": row["latest_period_end"]}, sources=sources,
                current=current, produced_by=produced_by, missing=["business_durability", "counterevidence", "valuation"]))
        except (ValueError, KeyError, OSError, TypeError):
            diagnostics["unverified"].append({"ticker": row["ticker"], "reason": "positive_change_source_binding_unverified"})
    news_path = root / "03_source_data/equity_research/official_news_events.local.json"
    news = read_json(news_path, {})
    for event in sorted(news.get("events", []), key=lambda r: str(r.get("published_at", "")), reverse=True)[:50]:
        if not event.get("review_required") or event.get("source_type") != "official_issuer_announcement":
            continue
        try:
            published = aware(event["published_at"])
            seen = aware(event["first_seen_at"])
            require(published <= seen <= current and current-published <= timedelta(days=7), "catalyst_clock_or_age_invalid")
            stable = {k: v for k, v in event.items() if k != "last_seen_at"}
            receipt = retain_input(root, news_path, available_at=seen.isoformat(), source_url=event["url"])
            packets.append(packet(ticker=event["ticker"], family="catalyst", trigger="official_event_impact_review",
                evidence={"event": stable, "impact": "unassessed", "observation_basis": "labelled official-news normalized receipt; original HTTP bytes not asserted"},
                sources=[receipt], current=current, produced_by=produced_by, missing=["event_impact_and_counterevidence"]))
        except (ValueError, KeyError, OSError, TypeError):
            diagnostics["unverified"].append({"ticker": event.get("ticker"), "reason": "issuer_event_unverified_or_stale"})
    requests_path = inside(root, policy["requests_store"])
    for request in read_json(requests_path, {"requests": []}).get("requests", [])[:24]:
        require(request.get("origin") == "owner" and bool(request.get("question")), "research_request_invalid")
        stamp = request["requested_at"]
        receipt = retain_input(root, requests_path, available_at=stamp)
        packets.append(packet(ticker=request["ticker"], family="request", trigger="owner_requested_research",
            evidence=request, sources=[receipt], current=current, produced_by=produced_by,
            kind=request.get("instrument_kind", "stock"), missing=["source_bound_company_research"]))
    experiment_path = root / "08_reviews/momentum_experiment.local/ledger.jsonl"
    if experiment_path.exists():
        import momentum_experiment as experiment
        from workflow_evaluation import read_jsonl
        rows = read_jsonl(experiment_path)
        experiment.validate_chain(rows, current)
        approvals = read_json(inside(root, policy["approval_store"]), {"approvals": []})
        approved = {}
        for record in approvals.get("approvals", []):
            validate_approval(record, root=root, current=current)
            approved[(record["experiment_version"], record["policy_sha256"])] = record
        # Only the newest session can request attention; historical missing or
        # unsuccessful observations stay in the original frozen study.
        observations = [r for r in rows if r.get("kind") == "observation"]
        latest = max((r["signal_session"] for r in observations), default="")
        for observation in [r for r in observations if r["signal_session"] == latest]:
            record = approved.get((observation["experiment_version"], observation["policy_sha256"]))
            if not record:
                diagnostics["experiment_review_only"].append({"ticker": observation["ticker"],
                    "experiment_version": observation["experiment_version"], "observation_id": observation["observation_id"],
                    "first_observed_at": observation["first_observed_at"], "disposition": observation["disposition"],
                    "reason": "explicit_owner_research_trigger_approval_required", **AUTHORITY})
                continue
            if observation["disposition"] not in record["allowed_dispositions"]:
                continue
            receipt = retain_input(root, experiment_path, available_at=observation["recorded_at"])
            packets.append(packet(ticker=observation["ticker"], family="experiment", trigger="approved_experiment_research_trigger",
                evidence={"observation": observation, "approval": record}, sources=[receipt, record["owner_receipt"], record["review_receipt"]],
                current=current, produced_by=produced_by, missing=["independent_business_case", "economics", "canonical_capital_contracts"]))
    for item in packets:
        validate_observation(item, root=root, current=current)
    diagnostics["trigger_packets"] = len(packets)
    return packets, diagnostics
