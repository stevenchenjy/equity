"""Read-only broad-market swing coverage and retained opportunity continuity.

Outside-universe technical histories require separately retained unadjusted
original sources. Mixed-fetch adjusted grouped data remains provisional. This module never expands canonical prices, account scope,
capital eligibility, network requests or an opportunity journal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import io
import math

from daily_common import canonical_sha256, sha256_file
import market_discovery as discovery

SCHEMA = "equity_swing_coverage_v1"
HISTORY_SESSIONS = 51
MAX_CANDIDATES = 6
IMPLEMENTATION = "09_scripts/equity_research/swing_coverage.py"
UNIVERSE = "03_source_data/equity_research/universe_seed.csv"
HOLDINGS = "05_risk_and_positions/current_positions.local.csv"
AUTHORITY = {"research_only": True, "capital_authority": False,
             "actionable_quantity": 0, "automatic_action_allowed": False}


def _clock(current: datetime) -> datetime:
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("swing_coverage_aware_clock_required")
    return current.astimezone(discovery.ET)


def _scope(root: Path) -> tuple[set[str], dict]:
    tickers, bindings = set(), {}
    for rel in (UNIVERSE, HOLDINGS):
        path = root / rel
        if path.is_symlink() or not path.is_file():
            if rel == HOLDINGS and not path.exists():
                continue
            raise ValueError("swing_coverage_canonical_scope_unverified")
        raw = path.read_bytes()
        bindings[rel] = sha256_file(path)
        rows = list(csv.DictReader(io.StringIO(raw.decode())))
        names = [str(r.get("ticker", "")).strip().upper() for r in rows]
        if (rel == UNIVERSE and not names) or any(not name for name in names) or len(set(names)) != len(names):
            raise ValueError("swing_coverage_canonical_scope_unverified")
        tickers.update(names)
    return tickers, bindings


def _continuity(root: Path, current: datetime) -> tuple[dict, dict, str]:
    path = root / "04_research/company_research/opportunities.local/report.json"
    if not path.exists():
        return {}, {}, "not_yet_recorded"
    try:
        from research_opportunities import read_report
        report = read_report(root, current=current)
        by = {row["ticker"]: row for row in report["opportunities"]}
        return by, {str(path.relative_to(root)): sha256_file(path),
                    "04_research/company_research/opportunities.local/store.json": report["store_sha256"]}, "validated"
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {}, "unverified"


def _historical_leads(items: dict, canonical: set[str]) -> list[dict]:
    leads = []
    for ticker, item in items.items():
        if ticker in canonical:
            continue
        observations = [row for row in item.get("observations", [])
                        if row.get("family") == "market" and row.get("instrument_kind") == "stock"]
        if not observations:
            continue
        observed = observations[-1]
        metrics = observed.get("evidence", {}).get("metrics", {})
        leads.append(dict(ticker=ticker, name=metrics.get("name", ticker),
                          first_seen_at=item.get("first_seen_at"), state=item.get("state"),
                          discovery_session=observed.get("evidence", {}).get("market_session"),
                          dated_screen_rank=metrics.get("rank"), observation_id=observed.get("observation_id"),
                          detected_at=observed.get("detected_at"), source_ids=[r.get("sha256") for r in observed.get("sources", [])],
                          source_status="dated_market_strength_lead"))
    # Newest source session first; the original rank orders attention only.
    leads.sort(key=lambda row: (str(row.get("discovery_session") or ""), str(row.get("detected_at") or "")), reverse=True)
    if leads:
        latest = leads[0]["discovery_session"]
        leads.sort(key=lambda row: (row.get("discovery_session") != latest,
                                   row.get("dated_screen_rank") if type(row.get("dated_screen_rank")) is int else 999999,
                                   row["ticker"]))
    return leads


def _bar(row: dict, session: str) -> dict:
    values = {}
    for key, name in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
        value = row.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or key != "v" and value == 0:
            raise ValueError("swing_outside_history_numeric_unverified")
        values[name] = float(value)
    if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
        raise ValueError("swing_outside_history_ohlcv_unverified")
    return {"session_date": session, **values}


def _grouped_provisional(root: Path, current: datetime, limit: int = MAX_CANDIDATES) -> dict:
    """Inspect grouped coverage; cross-fetch adjustment consistency is unproved.

    Even a complete series remains provisional and cannot feed technical setup
    evaluation. A failed latest broad attempt withholds its current prices.
    """
    root, current = Path(root), _clock(current)
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("swing_outside_history_limit_invalid")
    days = [str(day) for day in discovery.published_sessions(current, count=HISTORY_SESSIONS)]
    paths = {day: discovery.CACHE_RELATIVE / f"grouped-{day}.local.json" for day in days}
    missing = [day for day, rel in paths.items() if not (root / rel).is_file()]
    coverage = {"required_session": days[-1], "history_start": days[0], "required_history_sessions": HISTORY_SESSIONS,
                "cached_grouped_files": HISTORY_SESSIONS - len(missing), "missing_grouped_sessions": missing,
                "cached_files_are_not_admitted_history": True}
    result = dict(schema_version=SCHEMA, generated_at=current.isoformat(), status="waiting_on_data", histories={},
                  candidates=[], source_bindings={}, coverage=coverage, blockers=[], **AUTHORITY)
    try:
        canonical, bindings = _scope(root)
        latest_path = root / discovery.CACHE_RELATIVE / "latest.local.json"
        latest = discovery._cache_read(latest_path)
        bindings[str(latest_path.relative_to(root))] = sha256_file(latest_path)
        admitted = discovery.load_discovery(root, current)
        result.update(source_bindings=bindings, current_discovery_status=admitted.get("status"),
                      latest_provider_failure=latest.get("failure_detail") or {"failure_code": latest.get("failure_code", ""),
                          "original_http_evidence": "not_retained_by_older_collector" if latest.get("failure_code") else "not_applicable"})
        if admitted.get("status") != "complete" or admitted.get("complete") is not True:
            result["blockers"].append("current_broad_discovery_unavailable:" + str(admitted.get("failure_code", "unverified")))
            return result
        fetched = datetime.fromisoformat(str(admitted.get("fetched_at", "")))
        if fetched.tzinfo is None or fetched > current or fetched.date().isoformat() < days[-1]:
            raise ValueError("outside_swing_discovery_clock_unverified")
        metadata_rel = discovery.CACHE_RELATIVE / f"metadata-{days[-1]}.local.json"
        metadata = discovery._cache_read(root / metadata_rel)
        discovery.validate_metadata(metadata, discovery.date.fromisoformat(days[-1]))
        bindings[str(metadata_rel)] = sha256_file(root / metadata_rel)
        if missing:
            result["blockers"].append("outside_swing_51_consecutive_sessions_missing")
            return result
        histories = {}
        source_series = {}
        for day, rel in paths.items():
            payload = discovery._cache_read(root / rel)
            if (payload.get("session") != day or payload.get("complete") is not True or payload.get("adjusted") is not True
                    or not isinstance(payload.get("rows"), dict) or len(payload["rows"]) < discovery.MIN_GROUPED_ROWS):
                raise ValueError("outside_swing_grouped_session_or_basis_unverified")
            source_series[day] = payload
            bindings[str(rel)] = sha256_file(root / rel)
        rebuilt = discovery.build_report(metadata, {day: source_series[day] for day in days[-21:]},
                                         discovery.date.fromisoformat(days[-1]), canonical)
        for key in ("coverage", "all_stocks", "top_stocks", "all_etfs", "top_etfs"):
            if admitted.get(key) != rebuilt.get(key):
                raise ValueError("outside_swing_discovery_not_bound_to_grouped_history")
        outside = [row for row in rebuilt["all_stocks"] if row["ticker"] not in canonical]
        selected, ticker_blockers = [], {}
        for row in outside[:limit * 3]:
            ticker = row["ticker"]
            try:
                bars = [_bar(source_series[day]["rows"].get(ticker, {}), day) for day in days]
                # Reuse discovery's existing discontinuity review boundary on
                # the longer research window. Never infer or synthesize a split.
                if any(abs(bars[i]["close"] / bars[i-1]["close"] - 1) > .25 for i in range(1, len(bars))):
                    raise ValueError("outside_swing_large_discontinuity_review")
            except ValueError as exc:
                ticker_blockers[ticker] = str(exc)
                continue
            histories[ticker] = dict(ticker=ticker, name=row.get("name", ticker), bars=bars,
                source_session=days[-1], discovery_session=days[-1], dated_screen_rank=row["rank"],
                price_basis="split_adjusted", data_source="massive_grouped_adjusted_research",
                instrument_kind="stock", security_type="CS", common_stock_verified=True,
                source_available_at=admitted["fetched_at"],
                basis_consistency="provider_declared_only_corporate_action_review_required",
                source_bindings=dict(bindings), canonical_admission=False, corporate_action_review_required=True,
                interpretation="Provider-declared adjusted daily batches; cross-fetch corporate-action consistency remains unverified. Not canonical order-price or full total-return evidence.", **AUTHORITY)
            selected.append(row)
            if len(selected) == limit:
                break
        # Refuse a generation assembled across a concurrent refresh.
        if any(sha256_file(root / rel) != digest for rel, digest in bindings.items()):
            raise ValueError("outside_swing_sources_changed_during_read")
        result["blockers"].append("outside_swing_grouped_cross_fetch_basis_consistency_unverified")
        result.update(status="provisional_research_only", histories=histories, candidates=selected, source_bindings=bindings,
                      ticker_blockers=ticker_blockers, bounded_outside_candidates_considered=min(len(outside), limit * 3),
                      screened_count=rebuilt["coverage"]["stock_screen_eligible_count"],
                      outside_canonical_count=sum(row["ticker"] not in canonical for row in rebuilt["all_stocks"]))
        return result
    except (OSError, ValueError, KeyError, TypeError, discovery.DiscoveryError) as exc:
        result["histories"] = {}
        result["blockers"].append(str(exc) if isinstance(exc, (ValueError, discovery.DiscoveryError)) else "outside_swing_sources_unverified")
        return result



def admitted_histories(root: Path, current: datetime, limit: int = MAX_CANDIDATES) -> dict:
    """Return focused source-validated histories independently of broad failure.

    The broader screen and its dated leads are distinct from these at-most-six
    private histories. No whole-market success, canonical scope or capital
    authority is inferred from a successful focused recovery.
    """
    root, current = Path(root), _clock(current)
    result = _grouped_provisional(root, current, limit)
    provisional = result.pop("histories")
    from swing_candidate_history import admitted
    focused = admitted(root, current, limit)
    result["provisional_history_tickers"] = sorted(provisional)
    result["provisional_technical_history_admitted"] = False
    result["focused_recovery_status"] = focused["status"]
    result["focused_ticker_blockers"] = focused["ticker_blockers"]
    result["histories"] = focused["histories"]
    result["coverage"]["focused_admitted_history_count"] = len(focused["histories"])
    result["coverage"]["focused_scope_is_not_whole_market_coverage"] = True
    result["status"] = "focused_research_ready" if focused["histories"] else "waiting_on_data"
    for history in focused["histories"].values():
        result["source_bindings"].update(history["source_bindings"])
    return result


def build(root: Path, current: datetime, limit: int = MAX_CANDIDATES) -> dict:
    root, current = Path(root), _clock(current)
    result = admitted_histories(root, current, limit)
    histories = result.pop("histories")
    current_candidates = result.pop("candidates")
    items, continuity_bindings, continuity_status = _continuity(root, current)
    try:
        canonical, scope_bindings = _scope(root)
    except (OSError, ValueError, UnicodeError):
        canonical, scope_bindings = set(), {}
        items = {}
        result["blockers"].append("swing_coverage_canonical_scope_unverified")
    result["source_bindings"].update(scope_bindings)
    result["source_bindings"].update(continuity_bindings)
    result["continuity_status"] = continuity_status
    retained = _historical_leads(items, canonical)
    by_ticker = {row["ticker"]: row for row in retained}
    leads = []
    for ticker, history in histories.items():
        row = dict(by_ticker.get(ticker, {}))
        row.update(ticker=ticker, name=history.get("name", ticker),
                   discovery_session=history.get("discovery_session"),
                   first_seen_at=history.get("first_seen_at"),
                   dated_screen_rank=history.get("dated_screen_rank"),
                   state=items.get(ticker, {}).get("state", "retained_focused_research"),
                   source_status="current_focused_unadjusted_research_history",
                   source_session=history["source_session"],
                   source_ids=list(history["source_bindings"].values()))
        leads.append(row)
    leads.extend(row for row in retained if row["ticker"] not in histories)
    if not leads:
        leads = [dict(ticker=row["ticker"], name=row.get("name", row["ticker"]),
                      discovery_session=result["coverage"]["required_session"],
                      first_seen_at=None, dated_screen_rank=row["rank"],
                      state="not_yet_recorded", source_status="provisional_current_screen_basis_unverified",
                      source_ids=list(result["source_bindings"].values())) for row in current_candidates]
    leads = leads[:limit]
    tasks = []
    for row in leads:
        ready = row["ticker"] in histories
        row.update(current_price=None, history_status="admitted_focused_unadjusted_research_only" if ready else "current_coherent_51_session_history_unavailable",
                   next_step=("Evaluate the admitted daily setup, current issuer/event counterevidence and execution feasibility in the experimental swing lane; no capital proposal follows from a screen."
                              if ready else "Retain this dated market-strength lead. The bounded public full-review collector can obtain and validate its unadjusted baseline plus the current Nasdaq session with two-close overlap; evaluate the setup and issuer/event countercase only after coherent history admission, without expanding canonical capital authority."),
                   resolver="experimental_swing_research" if ready else "bounded_candidate_history_then_sourced_analyst", **AUTHORITY)
        tasks.append({k: row.get(k) for k in ("ticker", "first_seen_at", "discovery_session", "source_status", "next_step", "resolver", "source_ids")})
    result.update(candidates=leads, analyst_handoff=tasks, admitted_history_tickers=sorted(histories),
                  implementation_sha256=sha256_file(Path(__file__)),
                  interpretation="Dated market-strength leads are research attention, not reviewed growth companies or current buy suggestions. Failed current discovery never revives old prices.")
    result["content_sha256"] = canonical_sha256(result)
    return result


def revalidate_projection(root: Path, view: dict, current: datetime) -> dict:
    """Rebuild read-only rather than trust a saved coverage/readiness boolean."""
    # Current sources and journal ancestry are rechecked by the same builder;
    # callers never reuse numerical levels from an older coverage view.
    return build(root, current)
