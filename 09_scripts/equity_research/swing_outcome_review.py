"""Source-bound analyst qualification of immutable swing modeled price paths.

This writer records a reviewed judgment, not a mechanical proof that an issuer
had no corporate actions. It grants neither capital nor execution authority.
Unsupported action adjustments remain explicit dependencies. Call under the
documented runtime/pipeline lock order, then recompose without sending.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlparse

import swing_research as common

OUTPUT = Path("08_reviews/swing_research_v2.local")
STORE = OUTPUT / "outcome_reviews.jsonl"
SCHEMA = "equity_swing_outcome_review_v1"


def _sources(root, proposal, current, start, end):
    sources = proposal.get("sources", [])
    if not isinstance(sources, list) or not 2 <= len(sources) <= 8:
        raise common.SwingResearchError("outcome_review_two_primary_evidence_sources_required")
    roles, identities, raws = set(), set(), {}
    manifest = json.loads(common._file(root, "01_policies/official_news_sources.json"))
    allowed = {"www.sec.gov", "sec.gov", "api.nasdaq.com", "www.nasdaq.com", "nasdaq.com"}
    allowed.update(host for source in manifest.get("sources", []) for host in source.get("allowed_hosts", []))
    for source in sources:
        path = Path(source.get("path", ""))
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise common.SwingResearchError("outcome_review_source_locator_invalid")
        parsed = urlparse(source.get("url", ""))
        raw = common._file(root, path)
        excerpt = source.get("supporting_excerpt", "")
        if (parsed.scheme != "https" or parsed.hostname not in allowed
                or common._digest(raw) != source.get("sha256") or len(raw) < 100
                or not isinstance(excerpt, str) or not 40 <= len(excerpt) <= 1500
                or excerpt not in raw.decode("utf-8", errors="replace")):
            raise common.SwingResearchError("outcome_review_primary_source_unverified")
        observed = common._aware(source["available_at"])
        if observed > current or observed < end or source.get("coverage_from") != start or source.get("coverage_through") != end.date().isoformat():
            raise common.SwingResearchError("outcome_review_source_window_or_clock_unverified")
        if source.get("ticker") != proposal["ticker"] or len(source.get("coverage_explanation", "").strip()) < 80:
            raise common.SwingResearchError("outcome_review_ticker_and_coverage_reasoning_required")
        role = source.get("role")
        if role not in {"issuer_or_sec_corporate_action_review", "independent_exchange_corporate_action_review"}:
            raise common.SwingResearchError("outcome_review_independent_evidence_roles_required")
        exchange_hosts = {"api.nasdaq.com", "www.nasdaq.com", "nasdaq.com"}
        if (role == "independent_exchange_corporate_action_review" and parsed.hostname not in exchange_hosts
                or role == "issuer_or_sec_corporate_action_review" and parsed.hostname in exchange_hosts):
            raise common.SwingResearchError("outcome_review_independent_source_family_unverified")
        roles.add(role); identities.add((source["sha256"], source["url"])); raws[source["sha256"]] = raw
    if len(roles) != 2 or len(identities) < 2:
        raise common.SwingResearchError("outcome_review_independent_evidence_roles_required")
    return raws


def validate(root, proposal, current, *, history_current=None):
    """Validate exact outcome binding and authored evidence; no writes or network."""
    from swing_research_v2 import _load, _verify
    root, current = Path(root), common._aware(current)
    if (proposal.get("schema_version") != SCHEMA or not isinstance(proposal.get("reviewer"), str)
            or len(proposal["reviewer"].strip()) < 3 or common._aware(proposal.get("reviewed_at")) > current
            or len(proposal.get("reasoning", "").strip()) < 160 or len(proposal.get("limitations", "").strip()) < 80):
        raise common.SwingResearchError("outcome_review_authored_reasoning_and_clock_required")
    reviewed_at = common._aware(proposal["reviewed_at"])
    rows = _load(root, common._aware(history_current) if history_current else current); _verify(root, rows)
    matches = [row for row in rows if row["kind"] == "outcome" and row["record_hash"] == proposal.get("outcome_record_hash")]
    if len(matches) != 1:
        raise common.SwingResearchError("outcome_review_exact_immutable_outcome_required")
    outcome = matches[0]
    if reviewed_at < common._aware(outcome["recorded_at"]):
        raise common.SwingResearchError("outcome_review_cannot_predate_observed_outcome")
    observation = next(row for row in rows if row["kind"] == "observation" and row["observation_id"] == outcome["observation_id"])
    if (proposal.get("ticker") != outcome["ticker"] or proposal.get("observation_id") != outcome["observation_id"]
            or proposal.get("horizon_sessions") != outcome["horizon_sessions"]
            or proposal.get("entry_method") != outcome["entry_method"]
            or proposal.get("window_id") != outcome.get("window_id")
            or outcome.get("status") == "correction_review_required"):
        raise common.SwingResearchError("outcome_review_identity_or_correction_unresolved")
    start = observation["bars_at_observation"][0]["session_date"]
    end = common.regular_close(outcome["forward_bars"][-1]["session_date"])
    if current < end or proposal.get("coverage_from") != start or proposal.get("coverage_through") != end.date().isoformat():
        raise common.SwingResearchError("outcome_review_complete_signal_and_forward_window_required")
    conclusion = proposal.get("corporate_action_conclusion")
    if conclusion != "no_actions_identified_after_source_bound_review" or proposal.get("corporate_actions") != []:
        raise common.SwingResearchError("outcome_review_split_dividend_or_other_adjustment_requires_supported_method")
    if proposal.get("qualifying_method") != "source_bound_analyst_review_of_fixed_horizon_price_path_only":
        raise common.SwingResearchError("outcome_review_qualification_scope_invalid")
    raws = _sources(root, proposal, reviewed_at, start, end)
    values = outcome.get("raw_common_price_cost_sensitivity_pct_by_one_way_bps")
    if not isinstance(values, dict) or set(values) != {"10", "25", "50"}:
        raise common.SwingResearchError("outcome_review_fixed_horizon_path_unavailable")
    for value in values.values(): common._number(value)
    result = {"schema_version": SCHEMA, "recorded_at": current.isoformat(), "reviewed_at": proposal["reviewed_at"], "reviewer": proposal["reviewer"],
              "ticker": outcome["ticker"], "observation_id": outcome["observation_id"], "outcome_record_hash": outcome["record_hash"],
              "horizon_sessions": outcome["horizon_sessions"], "entry_method": outcome["entry_method"], "window_id": outcome.get("window_id"),
              "coverage_from": start, "coverage_through": end.date().isoformat(), "price_basis": outcome.get("price_basis", observation["price_basis"]),
              "qualification_scope": "source_bound_reviewed_fixed_horizon_modeled_price_path", "source_bound_analyst_judgment": True,
              "mechanical_proof_of_no_corporate_actions": False, "risk_managed_strategy_performance_qualified": False,
              "actual_fill_or_account_return": False, "reviewed_price_cost_sensitivity_pct_by_one_way_bps": values,
              "sources": proposal["sources"], "reasoning": proposal["reasoning"], "limitations": proposal["limitations"],
              "proposal_sha256": common._hash(proposal), "profitability_established": False, **common.AUTHORITY}
    return result, raws


def read_reviews(root, current):
    root, current = Path(root), common._aware(current)
    path = root / STORE
    if not path.exists(): return []
    rows, previous, seen = [], "", set()
    for line in common._file(root, STORE).splitlines():
        row = json.loads(line)
        if (row.get("record_hash") != common._hash({k:v for k,v in row.items() if k != "record_hash"})
                or row.get("previous_hash") != previous or row.get("proposal_sha256") in seen
                or common._aware(row["recorded_at"]) > current or any(row.get(k) != v for k,v in common.AUTHORITY.items())):
            raise common.SwingResearchError("outcome_review_history_integrity_failure")
        proposal_raw = common._file(root / OUTPUT, Path("review_inputs") / row["proposal_sha256"])
        proposal = json.loads(proposal_raw)
        if common._hash(proposal) != row["proposal_sha256"]:
            raise common.SwingResearchError("outcome_review_retained_proposal_changed")
        # Revalidate against the immutable original outcome and original review clock.
        expected, _ = validate(root, proposal, common._aware(row["recorded_at"]), history_current=current)
        if expected != {k:v for k,v in row.items() if k not in {"record_hash", "previous_hash"}}:
            raise common.SwingResearchError("outcome_review_projection_unverified")
        rows.append(row); previous = row["record_hash"]; seen.add(row["proposal_sha256"])
    return rows


def review(root, proposal, current, *, apply=False):
    """Apply is append-only and records exact rejected proposals where writable."""
    root, current = Path(root), common._aware(current)
    proposal_raw = common._json_bytes(proposal); identity = common._hash(proposal)
    try:
        value, raws = validate(root, proposal, current)
        if not apply: return value
        with common.ExclusiveFileLock(root / OUTPUT / "outcome_reviews.lock"):
            prior = read_reviews(root, current)
            existing = next((row for row in prior if row["proposal_sha256"] == identity), None)
            if existing: return existing
            for digest, raw in raws.items(): common._retain(root / OUTPUT / "review_sources" / digest, raw)
            common._retain(root / OUTPUT / "review_inputs" / identity, proposal_raw)
            before = (root / STORE).read_bytes() if (root / STORE).exists() else b""
            common._chain(prior, value); common._append(root / STORE, before, [prior[-1]])
            return prior[-1]
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        if apply:
            failure = {"proposal_sha256": identity, "reason": str(exc) if isinstance(exc, common.SwingResearchError) else "outcome_review_unverified", **common.AUTHORITY}
            common._retain(root / OUTPUT / "failed_review_inputs" / identity, proposal_raw)
            path = root / OUTPUT / "failed_reviews" / (common._hash(failure)+".json")
            if not path.exists(): common._retain(path, common._json_bytes({**failure, "recorded_at": current.isoformat()}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True); parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true"); args = parser.parse_args()
    result = review(args.root, json.loads(args.input.read_text()), common.now_et() if hasattr(common, "now_et") else datetime.now(common.ET), apply=args.apply)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
