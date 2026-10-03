"""Prospective observation paths, including deferred/rejected names; no trades.

Entry is the next market session after actual detection, never the historical
signal close. Costs and horizons are frozen in the first observation's producer
contract. Missing delisted, benchmark or corporate-action coverage stays unknown.
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import math

from daily_common import (is_us_market_session_date, latest_published_market_session,
    atomic_write_json, canonical_sha256, read_json)
from market_discovery import CACHE_RELATIVE, DiscoveryError, _cache_read
from opportunity_contract import AUTHORITY, BASE_REL, require, retain_input, validate_receipts
from workflow_evaluation import aware


def measure_paths(root: Path, items: list, *, current: datetime) -> dict:
    last = latest_published_market_session(current)
    results, cache = [], {}
    path = root / BASE_REL / "forward_outcomes.json"
    store = read_json(path, {"schema_version": "equity_opportunity_forward_outcomes_v1", "outcomes": [], **AUTHORITY})
    require(store.get("schema_version") == "equity_opportunity_forward_outcomes_v1" and all(store.get(k) is False for k in AUTHORITY), "research_forward_store_invalid")
    for recorded in store["outcomes"]:
        require(recorded.get("record_hash") == canonical_sha256({k: v for k, v in recorded.items() if k != "record_hash"}), "research_forward_outcome_changed")
        validate_receipts(recorded["sources"], root=root, current=current)
    recorded_by = {(r["opportunity_id"], r["horizon_sessions"]): r for r in store["outcomes"]}
    require(len(recorded_by) == len(store["outcomes"]), "research_forward_duplicate_outcome")
    changed = False
    for item in items:
        first = item["first_observation"]
        if first["family"] != "market":
            continue
        contract = first["producer"]["measurement_contract"]
        entry = aware(first["detected_at"]).date()+timedelta(days=1)
        while not is_us_market_session_date(entry):
            entry += timedelta(days=1)
        row = {"opportunity_id": item["opportunity_id"], "ticker": item["ticker"],
            "actual_detection_at": first["detected_at"], "model_entry_session": entry.isoformat(),
            "current_research_state": item["state"], "first_discovery_rank": first["evidence"]["metrics"]["rank"],
            "was_maintained_at_detection": first["evidence"]["metrics"]["in_legacy_universe"],
            "was_in_research_queue_at_detection": item["ticker"] in first.get("baseline_at_detection", {}).get("existing_research_queue", []),
            "measurement_contract": contract, "outcomes": [], **AUTHORITY}
        sessions, cursor = [], entry
        while len(sessions) < max(contract["horizons_market_sessions"]):
            if is_us_market_session_date(cursor):
                sessions.append(cursor)
            cursor += timedelta(days=1)
        for horizon in contract["horizons_market_sessions"]:
            end = sessions[horizon-1]
            outcome = {"horizon_sessions": horizon, "exit_session": end.isoformat(), "status": "pending_forward_observation"}
            previous = recorded_by.get((item["opportunity_id"], horizon))
            if end <= last:
                try:
                    def rows(day):
                        if day not in cache:
                            cache[day] = _cache_read(root / CACHE_RELATIVE / (f"grouped-{day}.local.json"))
                        data = cache[day]
                        if data.get("session") != str(day) or data.get("complete") is not True or data.get("adjusted") is not True:
                            raise ValueError("unverified_discovery_bar")
                        return data["rows"]
                    entry_rows, exit_rows = rows(entry), rows(end)
                    a, b = float(entry_rows[item["ticker"]]["o"]), float(exit_rows[item["ticker"]]["c"])
                    spy_a, spy_b = float(entry_rows["SPY"]["o"]), float(exit_rows["SPY"]["c"])
                    if min(a, b, spy_a, spy_b) <= 0 or not all(math.isfinite(v) for v in (a,b,spy_a,spy_b)):
                        raise ValueError("invalid_price")
                    gross, benchmark = (b/a-1)*100, (spy_b/spy_a-1)*100
                    outcome.update(status="observed_hypothetical_path", gross_price_change_pct=round(gross, 4),
                        spy_price_change_pct=round(benchmark, 4), excess_price_change_pct=round(gross-benchmark, 4),
                        net_cost_sensitivities=[{"one_way_bps": cost,
                            "net_price_change_pct": round((b*(1-cost/10000)/(a*(1+cost/10000))-1)*100, 4)} for cost in contract["one_way_cost_bps"]])
                    values = {"entry_open": a, "exit_close": b, "spy_entry_open": spy_a, "spy_exit_close": spy_b,
                        "entry_session": str(entry), "exit_session": str(end), "measurement_contract": contract}
                    if previous:
                        if previous["price_values_sha256"] != canonical_sha256(values):
                            outcome = {**outcome, "status": "correction_review_required", "original_outcome": previous}
                        else:
                            outcome = {k: v for k, v in previous.items() if k != "sources"}
                    else:
                        outcome.update(opportunity_id=item["opportunity_id"], recorded_at=current.isoformat(),
                            price_values_sha256=canonical_sha256(values), price_values=values,
                            sources=[retain_input(root, root / CACHE_RELATIVE / (f"grouped-{day}.local.json"), available_at=current.isoformat()) for day in {entry,end}], **AUTHORITY)
                        outcome["record_hash"] = canonical_sha256(outcome)
                        store["outcomes"].append(outcome)
                        changed = True
                except (OSError, ValueError, KeyError, TypeError, DiscoveryError):
                    outcome["status"] = "missing_or_unverified_forward_coverage"
                    if previous:
                        outcome["original_outcome"] = previous
            row["outcomes"].append(outcome)
        results.append(row)
    if changed:
        atomic_write_json(root / BASE_REL / "forward_outcome_history" / (canonical_sha256(store)+".json"), store)
        atomic_write_json(path, store)
    return {"schema_version": "equity_opportunity_prospective_measurement_v1", "observations": results,
        "status": "forward_observation_in_progress", "network_requests": 0,
        "interpretation": "Engineering/routing measurement and hypothetical adjusted price paths; no observed fills, total returns, independent samples or validated investment edge.",
        "limitations": ["Adjusted discovery prices are not canonical execution prices.",
            "One-share next-session open is a hypothetical liquidity/fill assumption; no live quote or attainable fill is established.",
            "Costs are per-side sensitivities, not measured executions; taxes and distributions are excluded.",
            "Correlated names/overlapping paths are not independent trials; missing coverage never becomes a negative return.",
            "No current production strategy or experiment promotion follows from these measurements."], **AUTHORITY}
