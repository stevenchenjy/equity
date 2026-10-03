"""Bounded, offline SEC research completion; never analyst signoff or trading.

The existing SEC collectors supply the network and immutable raw receipts. This
pass admits only supported consolidated facts from an already cached official
report. A bounded issuer work budget limits processing, not investment eligibility.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from daily_common import (ET, ExclusiveFileLock, atomic_write_csv, atomic_write_json,
    atomic_write_text, canonical_sha256, read_csv, read_json, sha256_file)
from earnings_incorporation import (CACHE_REL, MAX_AGE_HOURS, _time, _verified_raw,
    assess_company, write_selection_receipt)
from latest_report_facts import REPORT_FORMS, inline_report_facts, verified_artifact
from refresh_daily_evidence import FUNDAMENTAL_FIELDS, approved_inline_tags, fundamental_row, recent_filings
from workflow_evaluation import append_record, aware, read_jsonl

REPORT_REL = Path("04_research/company_research/research_backlog.local.json")
MARKDOWN_REL = Path("08_reviews/current/research_backlog.local.md")
HISTORY_REL = Path("04_research/company_research/research_backlog_history.local.jsonl")
DOSSIER_REL = Path("04_research/company_research/objective_evidence.local")
FUNDAMENTALS_REL = Path("03_source_data/equity_research/daily_fundamentals.csv")
LONG_HORIZON_REL = Path("04_research/company_research/long_horizon_research.local.json")
POSITIONS_REL = Path("05_risk_and_positions/current_positions.local.csv")
ARTIFACT_INDEX_REL = Path("03_source_data/equity_research/sec_filing_artifact_index.json")
TICKER = re.compile(r"[A-Z][A-Z0-9.]{0,9}")
EXCLUDED = frozenset({"SPY", "QQQ", "QQQM", "XLK", "XLI"})
OBJECTIVE_FIELDS = ("revenue_latest", "revenue_prior_year", "revenue_yoy_pct", "net_income_latest",
    "net_margin_pct", "cash_latest", "assets_latest", "liabilities_latest", "ttm_revenue",
    "ttm_revenue_prior_year", "ttm_revenue_yoy_pct", "ttm_operating_cash_flow", "ttm_capex",
    "ttm_free_cash_flow", "ttm_free_cash_flow_margin_pct", "diluted_shares_latest",
    "diluted_shares_prior_year", "share_dilution_pct", "debt_latest",
    "revenue_yoy_prior_quarter_pct", "net_margin_prior_quarter_pct")
REQUIRED_FIELDS = ("cash_latest", "ttm_revenue", "ttm_revenue_yoy_pct", "ttm_free_cash_flow",
    "ttm_free_cash_flow_margin_pct", "diluted_shares_latest", "share_dilution_pct", "debt_latest")
MAX_WORK_BUDGET = 10


def numeric(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _ticker(value):
    return isinstance(value, str) and bool(TICKER.fullmatch(value)) and value not in EXCLUDED


def _source_fingerprint(root: Path, ticker: str, row: dict, current: datetime) -> str:
    receipt = read_json(root / CACHE_REL / f"{ticker}.selection.json", {})
    artifacts = read_json(root / ARTIFACT_INDEX_REL, {}).get("artifacts", [])
    def actual_hash(locator):
        try:
            path = (root / locator).resolve()
            if not locator or Path(locator).is_absolute() or not path.is_relative_to(root.resolve()):
                return "invalid_path"
            return sha256_file(path)
        except (OSError, ValueError, TypeError):
            return "unavailable"
    sources = [receipt.get(k, {}) for k in ("submissions", "companyfacts")]
    # Re-polling unchanged bytes is not new research. A freshness transition,
    # changed identity, or changed actual bytes does require reassessment.
    return canonical_sha256({"financial": {k: v for k, v in row.items() if k != "fetched_at"},
        "receipt_binding_valid": receipt.get("financial_selection_sha256") == canonical_sha256(row),
        "receipt_identity": [receipt.get("schema_version"), receipt.get("ticker"), receipt.get("cik")],
        "selection_time_valid": bool(_time(receipt.get("selected_at")) and _time(receipt.get("selected_at")) <= current
            and all(_time(r.get("retrieved_at")) and _time(r.get("retrieved_at")) <= _time(receipt.get("selected_at")) for r in sources)),
        "material_ledger": [r for r in read_csv(root / "03_source_data/equity_research/daily_evidence_ledger.csv") if r.get("ticker") == ticker],
        # The collector updates last_seen_at on every successful poll of the
        # same announcement. That timestamp is collection activity, not new
        # accounting evidence. Keep all event identity/content, publication
        # and first-observation fields so genuine changes still reopen work.
        "official_news": [{k: v for k, v in r.items() if k != "last_seen_at"}
            for r in read_json(root / "03_source_data/equity_research/official_news_events.local.json", {}).get("events", [])
            if r.get("ticker") == ticker],
        "raw_sources": [{**{k: r.get(k) for k in ("raw_sha256", "raw_path", "source_url", "cik", "kind")},
            "actual_sha256": actual_hash(r.get("raw_path")),
            "fresh": bool(_time(r.get("retrieved_at")) and timedelta(0) <= current-_time(r.get("retrieved_at")) <= timedelta(hours=MAX_AGE_HOURS))}
            for r in sources],
        "artifacts": sorted(({**{k: a.get(k) for k in ("accession", "raw_sha256", "raw_path", "url", "cik", "fetched_at")},
            "actual_sha256": actual_hash(a.get("raw_path"))} for a in artifacts
            if a.get("ticker") == ticker and a.get("form") in REPORT_FORMS), key=canonical_sha256)})


def _source_refs(receipt: dict):
    return [{"kind": key, **{k: receipt.get(key, {}).get(k) for k in
        ("source_url", "raw_path", "raw_sha256", "retrieved_at", "cik")}}
        for key in ("submissions", "companyfacts")]


def complete_objective_data(*, root: Path, ticker: str, row: dict, current: datetime) -> dict:
    """Return an auditable dossier and a possible same-period additive patch."""
    result = {"schema_version": "equity_objective_evidence_v1", "ticker": ticker,
        "completed_at": current.isoformat(), "status": "unverified", "reason_code": "source_receipt_unverified",
        "source_fingerprint": _source_fingerprint(root, ticker, row, current), "source_provenance": [],
        "source_as_of": row.get("fetched_at", ""), "financial_period_end": row.get("latest_period_end", ""),
        "fields_completed": [], "objective_facts": {}, "remaining_financial_gaps": list(REQUIRED_FIELDS),
        "canonical_update": "not_applied", "automatic_action_allowed": False,
        "analyst_review_completed": False, "valuation_assumptions_created": False}
    receipt = read_json(root / CACHE_REL / f"{ticker}.selection.json", {})
    result["source_provenance"] = _source_refs(receipt)
    if (receipt.get("schema_version") != "financial_selection_receipt_v1"
            or receipt.get("ticker") != ticker or receipt.get("financial_selection_sha256") != canonical_sha256(row)):
        return result
    try:
        cik = int(row["cik"])
        if cik != receipt.get("cik") or not _ticker(ticker):
            return result
        sub = _verified_raw(root, receipt.get("submissions", {}))
        facts = _verified_raw(root, receipt.get("companyfacts", {}))
        retrievals = [_time(receipt.get(key, {}).get("retrieved_at", "")) for key in ("submissions", "companyfacts")]
        selected_at = _time(receipt.get("selected_at", ""))
        if sub is None or facts is None or any(t is None for t in retrievals):
            return result
        if (selected_at is None or selected_at > current or selected_at < max(retrievals)
                or any(not timedelta(0) <= current-t <= timedelta(hours=MAX_AGE_HOURS) for t in retrievals)):
            result["reason_code"] = "source_receipt_stale_or_future"
            return result
        filings = recent_filings(sub, as_of=current.astimezone(ET).date())
        reports = [f for f in filings if f.get("form") in REPORT_FORMS and aware(f["accepted_at"]) <= current]
        latest = max(reports, key=lambda f: (f.get("report_date", ""), f["accepted_at"]), default={})
        if not latest or not latest.get("report_date"):
            result["reason_code"] = "latest_report_unverified"
            return result
        if row.get("latest_period_end") != latest["report_date"]:
            result["reason_code"] = "latest_period_requires_existing_incorporation_workflow"
            return result
        assessment = assess_company(ticker, row, receipt, root=root, now=current,
            ledger=read_csv(root / "03_source_data/equity_research/daily_evidence_ledger.csv"),
            news=read_json(root / "03_source_data/equity_research/official_news_events.local.json", {}))
        # Missing values may be repaired, but a newer filing/release or an
        # unverified provenance chain cannot be bypassed by this data task.
        blockers = set(assessment["blocking_reasons"]) - {"selected_financial_data_incomplete"}
        if blockers:
            result.update(reason_code="existing_financial_selection_requires_reconciliation", blocking_reasons=sorted(blockers))
            return result
        provenance = json.loads(row.get("field_provenance_json", "{}"))
        result["objective_facts"] = {field: {"value": numeric(row.get(field)),
            "financial_period_end": row["latest_period_end"], "provenance": provenance.get(field, {})}
            for field in OBJECTIVE_FIELDS if numeric(row.get(field)) is not None and provenance.get(field)}
        result.update(status="objective_dossier_completed", reason_code="verified_cached_selection_attached",
            remaining_financial_gaps=[k for k in REQUIRED_FIELDS if numeric(row.get(k)) is None],
            latest_report_accession=latest["accession_number"], source_receipt_sha256=canonical_sha256(receipt))
        index = read_json(root / ARTIFACT_INDEX_REL, {})
        artifacts = [a for a in index.get("artifacts", []) if a.get("ticker") == ticker
            and a.get("accession") == latest["accession_number"] and a.get("form") == latest["form"]
            and str(a.get("cik", "")).lstrip("0") == str(cik)]
        if len(artifacts) != 1:
            result["reason_code"] = "latest_report_cache_missing_or_ambiguous"
            return result
        artifact = artifacts[0]
        expected_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{latest['accession_number'].replace('-', '')}/{latest['primary_document']}"
        artifact_time = _time(artifact.get("fetched_at", ""))
        if artifact.get("url") != expected_url or artifact_time is None or not aware(latest["accepted_at"]) <= artifact_time <= current:
            result["reason_code"] = "report_source_identity_or_time_unverified"
            return result
        values, end = inline_report_facts(verified_artifact(root, artifact), artifact=artifact,
            cik=cik, filing=latest, allowed_tags=approved_inline_tags())
        if end != row["latest_period_end"]:
            result["reason_code"] = "report_period_conflict"
            return result
        merged = copy.deepcopy(dict(facts))
        for value in values:
            arr = merged.setdefault("facts", {}).setdefault(value["_taxonomy"], {}).setdefault(
                value["_tag"], {}).setdefault("units", {}).setdefault(value["_unit"], [])
            existing = [v for v in arr if v.get("accn") == value["accn"]
                and v.get("start", "") == value.get("start", "") and v.get("end") == value["end"]]
            if existing and any(v.get("val") != value["val"] for v in existing):
                result["reason_code"] = "companyfacts_report_value_conflict"
                return result
            if not existing:
                arr.append(value)
        result["source_provenance"].append({"kind": "consolidated_inline_report", "source_url": expected_url,
            "raw_path": artifact["raw_path"], "raw_sha256": artifact["raw_sha256"],
            "retrieved_at": artifact["fetched_at"], "accepted_at": latest["accepted_at"], "cik": cik})
        # Record this new selection at actual completion time. Original source
        # retrieval/acceptance times remain separately immutable in receipts.
        candidate = fundamental_row(ticker, cik, merged, current.isoformat(),
            acceptance_by_accession={f["accession_number"]: f["accepted_at"] for f in filings})
        old_limits = set(filter(None, row.get("valuation_input_limitations", "").split(";")))
        new_limits = set(filter(None, candidate.get("valuation_input_limitations", "").split(";")))
        if (candidate["latest_period_end"] != row["latest_period_end"]
                or candidate.get("financial_period_type") != row.get("financial_period_type")
                or any(numeric(row.get(k)) is not None and numeric(candidate.get(k)) != numeric(row[k]) for k in OBJECTIVE_FIELDS)
                or not new_limits.issubset(old_limits)):
            result["reason_code"] = "existing_values_or_scope_require_reconciliation"
            return result
        completed = [k for k in OBJECTIVE_FIELDS if numeric(row.get(k)) is None and numeric(candidate.get(k)) is not None]
        if not completed:
            result["reason_code"] = "no_supported_numeric_gap_fill"
            return result
        candidate_provenance = json.loads(candidate["field_provenance_json"])
        if any(not candidate_provenance.get(k) for k in completed):
            result["reason_code"] = "derived_field_provenance_incomplete"
            return result
        result.update(reason_code="verified_same_period_numeric_gaps_completed", fields_completed=completed,
            proposed_fundamental=candidate, prior_fundamental_sha256=canonical_sha256(row),
            remaining_financial_gaps=[k for k in REQUIRED_FIELDS if numeric(candidate.get(k)) is None],
            selection_receipt_arguments={"ticker": ticker, "cik": cik, "fundamental": candidate,
                "filings": filings, "submissions_receipt": receipt["submissions"], "companyfacts_receipt": receipt["companyfacts"],
                "diagnostic": {"status": "verified_same_period_inline_gap_supplement", "latest_report_accession": latest["accession_number"],
                    "latest_report_period_end": end, "source_url": expected_url, "raw_sha256": artifact["raw_sha256"],
                    "raw_path": artifact["raw_path"], "fields_completed": completed}})
        result["objective_facts"].update({k: {"value": numeric(candidate[k]), "financial_period_end": end,
            "provenance": candidate_provenance[k]} for k in completed})
        return result
    except (ValueError, TypeError, KeyError, OSError):
        result["reason_code"] = "objective_source_validation_failed"
        return result


def build_backlog(*, fundamentals: list[dict], positions: list[dict], research: dict,
        dossiers: dict, current: datetime, previous: dict | None = None, max_tickers: int = 3,
        opportunities: list | None = None) -> dict:
    previous = previous or {}
    old_items = {r["gap_id"]: r for r in previous.get("items", [])}
    held = {r.get("ticker") for r in positions
        if (numeric(r.get("shares_optional", r.get("current_shares", r.get("shares")))) or 0) > 0}
    rows = {r["ticker"]: r for r in fundamentals if _ticker(r.get("ticker"))}
    observed_rows = dict(rows)
    attention = {r["ticker"]: r for r in opportunities or [] if _ticker(r.get("ticker"))}
    companies = research.get("companies", {})
    rank = {r["ticker"]: i for i, r in enumerate(research.get("candidate_queue", []))}
    items, groups = [], []
    for ticker in sorted(set(rows) | set(attention) | {t for t in companies if _ticker(t)} | {t for t in held if _ticker(t)}):
        row, company, dossier = rows.get(ticker, {}), companies.get(ticker, {}), dossiers.get(ticker, {})
        opportunity = attention.get(ticker, {})
        # Source-bound research-only facts can complete research gaps without
        # becoming rows in the canonical table or changing its authority.
        if not row and opportunity.get("objective_status") == "source_bound":
            row = {"ticker": ticker, **{k: v.get("value") for k, v in opportunity.get("research_objective_facts", {}).items()},
                "fetched_at": opportunity.get("objective_completed_at", "")}
            observed_rows[ticker] = row
        # Positions are current account evidence; a retained research memo's
        # held flag can describe a position that has since been closed.
        held_ticker = ticker in held
        reopen = company.get("maintained_view", {}).get("reopen_reasons", [])
        material_reopen = bool([v for v in reopen if v != "company_review_not_recorded"])
        gaps = [("objective_attachment", "auditable_numeric_dossier", "automatic_official_cache")]
        if opportunity.get("instrument_kind") == "etf" and not row:
            gaps.append(("reasoning", "issuer_structure_prospectus_and_portfolio_role", "analyst_research_required"))
        else:
            gaps += [("financial", k, "automatic_official_cache_then_scope_review") for k in REQUIRED_FIELDS if numeric(row.get(k)) is None]
        if opportunity:
            gaps.append(("reasoning", "recorded_opportunity_business_case_and_economics", "analyst_research_required"))
        gaps += [("reasoning", str(v), "analyst_research_required") for v in company.get("missing_evidence", [])
            if not str(v).startswith("unresolved_financial_evidence:") and str(v) not in REQUIRED_FIELDS]
        if "valuation_pending" in company.get("readiness", ""):
            gaps.append(("reasoning", "company_specific_valuation_and_alternative_comparison", "analyst_research_required"))
        ticker_items = []
        for kind, code, mode in dict.fromkeys(gaps):
            gap_id = canonical_sha256({"ticker": ticker, "kind": kind, "reason_code": code})
            completed = (kind == "objective_attachment" and (dossier.get("status") == "objective_dossier_completed" or opportunity.get("objective_status") == "source_bound"))
            state = "resolved_objective" if completed else "pending_research" if kind == "reasoning" else "pending_objective"
            if kind != "reasoning" and dossier.get("status") == "unverified":
                state = "unverified"
            item = {"gap_id": gap_id, "ticker": ticker, "kind": kind, "reason_code": code,
                "status": state, "completion_mode": mode, "source_as_of": row.get("fetched_at", ""),
                "source_provenance": dossier.get("source_provenance", []),
                "first_seen_at": old_items.get(gap_id, {}).get("first_seen_at", current.isoformat()),
                "last_checked_at": current.isoformat(), "next_step": "Completed source-bound numeric attachment; financial/analyst gaps remain separate." if completed
                    else "Assess company-specific evidence and counterevidence; record a reviewed thesis or valuation separately." if kind == "reasoning"
                    else "Use verified official cache; retain unknown if units, scope or consolidation cannot be established."}
            item["objective_fillability"] = ("analyst_reasoning_required" if kind == "reasoning" else "completed" if completed
                else "verified_patch_available" if code in dossier.get("fields_completed", [])
                else "no_supported_cached_fill" if kind == "financial" and dossier.get("status") == "objective_dossier_completed"
                else "source_unverified" if dossier.get("status") == "unverified" else "pending_cache_inspection")
            if item["objective_fillability"] == "no_supported_cached_fill":
                item["next_step"] = "Current verified cache does not establish this value; research official accounting scope or await supported disclosure. Missing is not zero."
            items.append(item); ticker_items.append(item)
        outstanding = [r for r in ticker_items if r["status"] != "resolved_objective"]
        reasons = (["existing_position_research"] if held_ticker else []) + (["maintained_view_reopened"] if material_reopen else [])
        if "valuation_pending" in company.get("readiness", ""):
            reasons.append("reviewed_business_case_valuation_incomplete")
        if ticker in rank:
            reasons.append("existing_fundamental_research_candidate")
        reasons.append("objective_data_and_reasoning_gaps_kept_separate")
        tier = 0 if held_ticker else 1 if material_reopen else 2 if "valuation_pending" in company.get("readiness", "") else 3
        if opportunity:
            reasons += ["durable_early_research_opportunity", "first_trigger:"+opportunity["first_observation"]["trigger"]]
            from research_opportunities import priority
            tier = min(tier, priority(opportunity, held)[0])
        groups.append({"ticker": ticker, "held": held_ticker, "priority_reasons": reasons,
            "gap_ids": [r["gap_id"] for r in outstanding], "status": "pending_research" if outstanding else "objective_portion_complete",
            "objective_gap_count": sum(r["kind"] != "reasoning" for r in outstanding),
            "manual_gap_count": sum(r["kind"] == "reasoning" for r in outstanding),
            "financial_gaps_remaining": [k for k in REQUIRED_FIELDS if numeric(row.get(k)) is None],
            "priority_key": [tier, rank.get(ticker, 999), ticker],
            **({"attention_state": opportunity["state"], "attention_first_seen_at": opportunity["first_seen_at"],
                "attention_queue_age_hours": opportunity.get("queue_age_hours"),
                "attention_blockers": opportunity["blockers"], "evidence_scope": "canonical" if ticker in rows else "research_only_no_canonical_admission"} if opportunity else {})})
    # Previously open numeric fields disappear from the current missing set
    # only when canonical data now supplies them; retain their resolution record.
    existing_ids = {r["gap_id"] for r in items}
    for gap_id, old in old_items.items():
        if gap_id in existing_ids:
            continue
        resolved = (old["kind"] == "financial" and numeric(observed_rows.get(old["ticker"], {}).get(old["reason_code"])) is not None)
        items.append({**old, "status": "resolved_objective" if resolved else "unverified",
            "last_checked_at": current.isoformat(), "next_step": "Canonical official numeric evidence now present." if resolved else "Coverage changed; historical gap preserved without assumed resolution."})
    groups.sort(key=lambda r: tuple(r["priority_key"]))
    for i, row in enumerate(groups, 1):
        row["priority_rank"] = i
    return {"schema_version": "equity_research_backlog_v1", "generated_at": current.isoformat(), "status": "ready",
        "automatic_action_allowed": False, "work_budget_tickers": max_tickers,
        "priority_basis": "Held and reopened research, then existing fundamental queue; workload order is not an investment ranking.",
        "priority_queue": [r for r in groups if r["gap_ids"] and (r["ticker"] in rows or r.get("attention_state") not in {"deferred_capacity", "expired", "rejected", "economics_failed"})][:max_tickers], "issuer_queue": groups, "items": items,
        "counts": dict(Counter(r["status"] for r in items)), "network_requests": 0,
        "analyst_reviews_completed": 0, "valuation_assumptions_created": 0}


def attention_rows(root: Path, current: datetime) -> list:
    if not (root / "04_research/company_research/opportunities.local/report.json").exists():
        return []  # Compatibility: no attention store exists before migration.
    from research_opportunities import read_report
    try:
        return read_report(root, current=current)["opportunities"]
    except (OSError, ValueError, KeyError, TypeError):
        return []  # Optional research failure never changes canonical authority.


def refresh_attention_view(root: Path, current: datetime) -> None:
    """Refresh derived backlog visibility after intake evidence; no extra work."""
    with ExclusiveFileLock(root / DOSSIER_REL / "backlog.lock"):
        report = read_json(root / REPORT_REL, {})
        if not report:
            return
        validate_report(report, root=root)
        fundamentals = read_csv(root / FUNDAMENTALS_REL)
        dossiers = {r["ticker"]: read_json(root / DOSSIER_REL / (r["ticker"]+".json"), {}) for r in fundamentals}
        view = build_backlog(fundamentals=fundamentals, positions=read_csv(root / POSITIONS_REL),
            research=read_json(root / LONG_HORIZON_REL, {}), dossiers=dossiers,
            current=current, previous=report, max_tickers=report["work_budget_tickers"], opportunities=attention_rows(root, current))
        report.update({k: view[k] for k in ("items", "issuer_queue", "priority_queue", "counts")})
        report["attention_view_updated_at"] = current.isoformat()
        report["report_hash"] = canonical_sha256({k: v for k, v in report.items() if k != "report_hash"})
        validate_report(report)
        atomic_write_json(root / REPORT_REL, report)
        atomic_write_text(root / MARKDOWN_REL, render_report(report))


def _append_history(path: Path, records: list, row: dict):
    previous = records[-1]["record_hash"] if records else ""
    row = {**row, "previous_hash": previous}
    row["record_hash"] = canonical_sha256(row)
    append_record(path, row); records.append(row)


def _history(path: Path):
    rows, previous = read_jsonl(path), ""
    for row in rows:
        if row.get("previous_hash") != previous or canonical_sha256({k: v for k, v in row.items() if k != "record_hash"}) != row.get("record_hash"):
            raise ValueError("research_backlog_history_invalid_preserve_records")
        if row.get("kind") not in {"run_started", "run_finished", "objective_attempt_started", "objective_attempt", "gap_progress"}:
            raise ValueError("research_backlog_history_invalid_preserve_records")
        aware(row.get("recorded_at"))
        previous = row["record_hash"]
    return rows


def validate_report(report: dict, *, root: Path | None = None, current: datetime | None = None) -> dict:
    """Reject malformed or changed reports; optional current-input verification.

    Consumers still check their current pipeline step outcome. A report hash
    binds a reproducible artifact; it is not an investment-evidence approval.
    """
    try:
        if (not isinstance(report, dict) or report.get("schema_version") != "equity_research_backlog_v1"
                or report.get("status") != "ready" or report.get("automatic_action_allowed") is not False
                or canonical_sha256({k: v for k, v in report.items() if k != "report_hash"}) != report.get("report_hash")):
            raise ValueError
        stamp = aware(report["generated_at"])
        if current and (stamp > current or stamp.astimezone(ET).date() != current.astimezone(ET).date()):
            raise ValueError
        for name in ("priority_queue", "issuer_queue", "items", "attempts_latest_run", "selected_tickers"):
            if not isinstance(report[name], list):
                raise ValueError
        states = {"resolved_objective", "pending_objective", "pending_research", "unverified"}
        for item in report["items"]:
            if (not isinstance(item, dict) or not _ticker(item.get("ticker")) or item.get("status") not in states
                    or item.get("kind") not in {"financial", "objective_attachment", "reasoning"}
                    or item.get("gap_id") != canonical_sha256({k: item[k] for k in ("ticker", "kind", "reason_code")})):
                raise ValueError
        if len({r["gap_id"] for r in report["items"]}) != len(report["items"]):
            raise ValueError
        for name in ("priority_queue", "issuer_queue"):
            for item in report[name]:
                if (not isinstance(item, dict) or not _ticker(item.get("ticker"))
                        or type(item.get("priority_rank")) is not int or item["priority_rank"] < 1
                        or not isinstance(item.get("gap_ids"), list) or not isinstance(item.get("priority_reasons"), list)
                        or not all(isinstance(v, str) for v in item["gap_ids"] + item["priority_reasons"])):
                    raise ValueError
        if not isinstance(report.get("counts"), dict) or report["counts"] != dict(Counter(r["status"] for r in report["items"])):
            raise ValueError
        if any(not isinstance(r, dict) or not _ticker(r.get("ticker")) for r in report["attempts_latest_run"]):
            raise ValueError
        budget = report.get("work_budget_tickers")
        if (type(budget) is not int or not 1 <= budget <= MAX_WORK_BUDGET
                or report["selected_tickers"] != [r["ticker"] for r in report["attempts_latest_run"]]
                or len(report["selected_tickers"]) > budget):
            raise ValueError
        for name in ("history_records", "objective_dossiers_completed", "financial_fields_completed", "canonical_numeric_updates"):
            if type(report[name]) is not int or report[name] < 0:
                raise ValueError
        if root:
            records = _history(root / HISTORY_REL)
            count = report["history_records"]
            if count > len(records) or (records[count-1]["record_hash"] if count else "") != report["history_head_hash"]:
                raise ValueError
            if sha256_file(root / FUNDAMENTALS_REL) != report["inputs"]["fundamentals_sha256_after"]:
                raise ValueError
        return report
    except (KeyError, TypeError, ValueError, OSError):
        raise ValueError("research_backlog_report_unverified") from None


def render_report(report: dict) -> str:
    lines = ["# Research backlog", "", f"Updated: {report['generated_at']}", "",
        "This queue assigns research work. It does not rank purchases, authorize trades, complete analyst judgments, or create valuation assumptions.",
        f"Automatic workload: at most {report['work_budget_tickers']} issuers per run; cached official sources only; {report['network_requests']} network requests.", "",
        "| Priority | Issuer | Objective gaps | Reasoning gaps | Why now |", "|---:|---|---:|---:|---|"]
    for row in report["priority_queue"]:
        lines.append(f"| {row['priority_rank']} | {row['ticker']} | {row['objective_gap_count']} | {row['manual_gap_count']} | {', '.join(row['priority_reasons'])} |")
    lines += ["", "## Objective work completed this run", ""]
    for row in report.get("attempts", []):
        fields = ", ".join(row["fields_completed"]) or "No additional financial field admitted"
        lines.append(f"- {row['ticker']}: {row['status']} / {row['reason_code']}; {fields}; canonical update: {row['canonical_update']}.")
    if not report.get("attempts"):
        lines.append("- No changed source set required another objective pass; prior dossiers and pending gaps are retained.")
    lines += ["", "## Financial evidence still missing", ""]
    for row in report["issuer_queue"]:
        if row["financial_gaps_remaining"]:
            lines.append(f"- {row['ticker']}: {', '.join(row['financial_gaps_remaining'])}.")
    lines += ["", "Business quality, durability, normalized cash generation, valuation and alternatives still require a recorded evidence-based assessment. An attached numeric dossier does not remove those gates.", ""]
    return "\n".join(lines)


def run(*, input_root: Path, output_root: Path, current: datetime, max_tickers: int = 3,
        apply_objective_updates: bool = False) -> dict:
    if type(max_tickers) is not int or not 1 <= max_tickers <= MAX_WORK_BUDGET:
        raise ValueError("research_work_budget_out_of_bounds")
    input_root, output_root = input_root.resolve(), output_root.resolve()
    if apply_objective_updates and input_root != output_root:
        raise ValueError("cross_root_objective_updates_forbidden")
    current = aware(current.isoformat())
    with ExclusiveFileLock(output_root / DOSSIER_REL / "backlog.lock"):
        path = input_root / FUNDAMENTALS_REL
        original_sha = sha256_file(path)
        fundamentals = read_csv(path)
        positions, research = read_csv(input_root / POSITIONS_REL), read_json(input_root / LONG_HORIZON_REL, {})
        previous = read_json(output_root / REPORT_REL, {})
        records = _history(output_root / HISTORY_REL)
        if previous:
            validate_report(previous)
            if aware(previous["generated_at"]) > current:
                raise ValueError("research_backlog_clock_regression")
            count = previous["history_records"]
            if count > len(records) or (records[count-1]["record_hash"] if count else "") != previous["history_head_hash"]:
                raise ValueError("research_backlog_report_history_mismatch")
        dossiers = {t: read_json(output_root / DOSSIER_REL / f"{t}.json", {}) for t in
            {r.get("ticker") for r in fundamentals if _ticker(r.get("ticker"))}}
        last_attempts = {r["ticker"]: r for r in records if r.get("kind") == "objective_attempt"}
        for ticker, dossier in dossiers.items():
            if not dossier:
                continue
            digest = canonical_sha256(dossier)
            immutable = read_json(output_root / DOSSIER_REL / "history" / f"{ticker}-{digest}.json", {})
            if (dossier.get("ticker") != ticker or dossier.get("schema_version") != "equity_objective_evidence_v1"
                    or last_attempts.get(ticker, {}).get("dossier_id") != digest or canonical_sha256(immutable) != digest):
                raise ValueError("research_backlog_dossier_history_unverified")
        fingerprints = {r["ticker"]: _source_fingerprint(input_root, r["ticker"], r, current)
            for r in fundamentals if _ticker(r.get("ticker"))}
        for ticker, dossier in list(dossiers.items()):
            if dossier and dossier.get("source_fingerprint") != fingerprints.get(ticker):
                # History is immutable; only this run's view reopens stale work.
                dossiers[ticker] = {**dossier, "status": "unverified", "reason_code": "source_set_changed_requires_reassessment"}
        initial = build_backlog(fundamentals=fundamentals, positions=positions, research=research,
            dossiers=dossiers, current=current, previous=previous, max_tickers=max_tickers,
            opportunities=attention_rows(input_root, current))
        by_ticker = {r["ticker"]: r for r in fundamentals}
        attempts, receipts, pending = [], [], []
        run_id = canonical_sha256({"started_at": current.isoformat(), "previous_hash": records[-1]["record_hash"] if records else "",
            "fundamentals_sha256": original_sha})
        _append_history(output_root / HISTORY_REL, records, {"kind": "run_started", "run_id": run_id,
            "recorded_at": current.isoformat(), "automatic_action_allowed": False})
        for group in initial["issuer_queue"]:
            ticker = group["ticker"]
            if ticker not in by_ticker and group.get("evidence_scope") == "research_only_no_canonical_admission" and not group["held"]:
                # Outside discoveries use the isolated objective issuer path;
                # empty canonical rows must not consume canonical work slots.
                continue
            row = by_ticker.get(ticker, {})
            fingerprint = fingerprints.get(ticker) or _source_fingerprint(input_root, ticker, row, current)
            applicable = apply_objective_updates and dossiers.get(ticker, {}).get("canonical_update") == "verified_patch_available_explicit_apply_flag_required"
            if last_attempts.get(ticker, {}).get("source_fingerprint") == fingerprint and not applicable:
                continue
            dossier = complete_objective_data(root=input_root, ticker=ticker, row=row, current=current)
            candidate = dossier.get("proposed_fundamental")
            if candidate and apply_objective_updates:
                by_ticker[ticker] = candidate
                receipts.append(dossier["selection_receipt_arguments"])
                dossier["canonical_update"] = "verified_numeric_patch_pending_publication"
            elif candidate:
                dossier["canonical_update"] = "verified_patch_available_explicit_apply_flag_required"
            pending.append(dossier)
            # Preserve the attempted evidence even if publication is interrupted.
            dossier_id = canonical_sha256(dossier)
            atomic_write_json(output_root / DOSSIER_REL / "history" / f"{ticker}-{dossier_id}.json", dossier)
            _append_history(output_root / HISTORY_REL, records, {"kind": "objective_attempt_started", "run_id": run_id,
                "recorded_at": current.isoformat(), "ticker": ticker, "source_fingerprint": fingerprint,
                "dossier_id": dossier_id, "automatic_action_allowed": False})
            if len(pending) >= max_tickers:
                break
        try:
            if receipts:
                if sha256_file(path) != original_sha:
                    raise ValueError("fundamentals_changed_during_research")
                # The downstream receipt gate fails closed if a crash interrupts
                # CSV/receipt publication. No reviewer record is written.
                atomic_write_csv(path, FUNDAMENTAL_FIELDS, [by_ticker[r["ticker"]] for r in fundamentals])
                for receipt in receipts:
                    write_selection_receipt(**receipt, root=input_root)
            for dossier in pending:
                ticker = dossier["ticker"]
                if dossier["canonical_update"] == "verified_numeric_patch_pending_publication":
                    dossier["canonical_update"] = "verified_numeric_patch_applied"
                    dossier["input_source_fingerprint"] = dossier["source_fingerprint"]
                    dossier["source_fingerprint"] = _source_fingerprint(input_root, ticker, by_ticker[ticker], current)
                dossier_id = canonical_sha256(dossier)
                atomic_write_json(output_root / DOSSIER_REL / "history" / f"{ticker}-{dossier_id}.json", dossier)
                atomic_write_json(output_root / DOSSIER_REL / f"{ticker}.json", dossier)
                dossiers[ticker] = dossier
                event = {"kind": "objective_attempt", "run_id": run_id, "recorded_at": current.isoformat(), "ticker": ticker,
                    "source_fingerprint": dossier["source_fingerprint"], "dossier_id": dossier_id,
                    **{k: dossier[k] for k in ("status", "reason_code", "fields_completed", "canonical_update")},
                    "automatic_action_allowed": False}
                attempts.append(event)
                _append_history(output_root / HISTORY_REL, records, event)
        except (ValueError, KeyError, TypeError, OSError):
            _append_history(output_root / HISTORY_REL, records, {"kind": "run_finished", "run_id": run_id,
                "recorded_at": current.isoformat(), "status": "failed", "reason_code": "objective_publication_failed",
                "automatic_action_allowed": False})
            raise
        report = build_backlog(fundamentals=list(by_ticker.values()), positions=positions, research=research,
            dossiers=dossiers, current=current, previous=initial, max_tickers=max_tickers,
            opportunities=attention_rows(input_root, current))
        old = {r["gap_id"]: r for r in previous.get("items", [])}
        for item in report["items"]:
            prior = old.get(item["gap_id"], {})
            if prior.get("status") != item["status"]:
                _append_history(output_root / HISTORY_REL, records, {"kind": "gap_progress", "recorded_at": current.isoformat(),
                    "gap_id": item["gap_id"], "ticker": item["ticker"], "from_status": prior.get("status", "not_recorded"),
                    "to_status": item["status"], "automatic_action_allowed": False})
        _append_history(output_root / HISTORY_REL, records, {"kind": "run_finished", "run_id": run_id,
            "recorded_at": current.isoformat(), "status": "success", "reason_code": "bounded_official_cache_research_completed",
            "objective_attempt_count": len(attempts), "automatic_action_allowed": False})
        report.update(attempts=attempts, attempts_latest_run=attempts, selected_tickers=[r["ticker"] for r in attempts],
            history_records=len(records), history_head_hash=records[-1]["record_hash"],
            objective_dossiers_completed=sum(r["status"] == "objective_dossier_completed" for r in attempts),
            financial_fields_completed=sum(len(r["fields_completed"]) for r in attempts),
            canonical_numeric_updates=len(receipts), apply_objective_updates=apply_objective_updates,
            input_root_read_only=input_root != output_root,
            source_as_of=research.get("generated_at", ""), inputs={"fundamentals_sha256_before": original_sha,
                "fundamentals_sha256_after": sha256_file(path)})
        report["completion_summary"] = {k: report[k] for k in ("objective_dossiers_completed", "financial_fields_completed", "canonical_numeric_updates")}
        report["attempt_summary"] = {"this_run": len(attempts), "history_total": sum(r.get("kind") == "objective_attempt" for r in records),
            "unverified_this_run": sum(r["status"] == "unverified" for r in attempts),
            "failed_runs": sum(r.get("kind") == "run_finished" and r.get("status") == "failed" for r in records)}
        report["report_hash"] = canonical_sha256(report)
        validate_report(report)
        atomic_write_json(output_root / REPORT_REL, report)
        atomic_write_text(output_root / MARKDOWN_REL, render_report(report))
        return report
