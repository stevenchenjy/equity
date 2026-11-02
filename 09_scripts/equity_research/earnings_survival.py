"""Prospective earnings-survival observations; offline, append-only, zero capital.

Admitted prices/features come from active_swing_research. This separate study
does not alter frozen swing cohorts, discover quotes, recommend or execute trades.
Release confirmation is a source-bound analyst intake, not a calendar inference.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import ExitStack
import csv
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
import hashlib
import json
import math
import os
from pathlib import Path
import re

from daily_common import ET, ExclusiveFileLock, is_us_market_session_date
from investment_plans import regular_close

VERSION = "earnings-survival-forward-v1-20261101"
SCHEMA = "equity_earnings_survival_study_v1"
RELEASE_SCHEMA = "equity_earnings_survival_release_v1"
POLICY = Path("01_policies/earnings_survival.json")
OUTPUT = Path("08_reviews/earnings_survival.local")
AUTHORITY = {"research_only": True, "capital_authority": False,
             "actionable_quantity": 0, "automatic_action_allowed": False}


class StudyError(ValueError):
    pass


def _require(ok, code):
    if not ok:
        raise StudyError(code)


def _bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return _digest(_bytes(value))


def _aware(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        _require(parsed.tzinfo is not None, "survival_timezone_required")
        return parsed.astimezone(ET)
    except (ValueError, TypeError):
        raise StudyError("survival_aware_clock_required") from None


def _file(root, relative):
    rel, root = Path(relative), Path(root).resolve()
    _require(not rel.is_absolute() and ".." not in rel.parts and bool(rel.parts), "survival_source_path_invalid")
    path = root / rel
    _require(path.resolve().is_relative_to(root) and not path.is_symlink() and path.is_file(), "survival_source_not_regular")
    return path.read_bytes()


def _retain(root, raw):
    digest = _digest(raw)
    path = Path(root) / OUTPUT / "inputs" / digest
    _require(path.resolve().is_relative_to(Path(root).resolve()) and not path.is_symlink(), "survival_retained_path_escape")
    if path.exists():
        _require(not path.is_symlink() and path.read_bytes() == raw, "survival_retained_input_changed")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
    return digest


def _policy(root):
    raw = _file(root, POLICY)
    value = json.loads(raw)
    _require(value.get("schema_version") == "equity_earnings_survival_policy_v1"
             and value.get("version") == VERSION and all(value.get(k) == v for k, v in AUTHORITY.items())
             and value.get("primary_horizon_sessions") == 5
             and value.get("secondary_horizons_sessions") == [10, 14]
             and value.get("one_way_cost_bps") == [10, 25, 50]
             and value.get("post_release_breakout_window_sessions") == 5, "survival_policy_unverified")
    return value, raw


def _implementation(root):
    directory = Path(__file__).resolve().parent
    pending = ["earnings_survival.py", "run_earnings_survival.py", "active_swing_research.py", "frozen_swing_runtime.py"]
    files = {}
    while pending:
        name = pending.pop()
        if name in files: continue
        raw = (directory / name).read_bytes(); files[name] = _digest(raw)
        for node in ast.walk(ast.parse(raw)):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for module in modules:
                dependency = module.split(".")[0] + ".py"
                if (directory / dependency).is_file() and dependency not in files: pending.append(dependency)
    files["01_policies/swing_runtime_v3.json"] = _digest(_file(root, "01_policies/swing_runtime_v3.json"))
    return _hash(files), files


def _open(session):
    return datetime.combine(date.fromisoformat(session), time(9, 30), ET)


def _sessions(start, count):
    day, result = date.fromisoformat(start), []
    while len(result) < count:
        if is_us_market_session_date(day):
            result.append(day.isoformat())
        day += timedelta(days=1)
    return result


def _next_open(clock):
    clock = _aware(clock)
    day = clock.date()
    while not is_us_market_session_date(day) or _open(day.isoformat()) <= clock:
        day += timedelta(days=1)
    return day.isoformat()


def _load(root, current):
    path = Path(root) / OUTPUT / "ledger.jsonl"
    if not path.exists():
        return []
    rows, previous, last, seen = [], "", None, set()
    for line in _file(root, OUTPUT / "ledger.jsonl").splitlines():
        row = json.loads(line)
        clock = _aware(row["recorded_at"])
        _require(row.get("record_hash") == _hash({k: v for k, v in row.items() if k != "record_hash"})
                 and row.get("previous_hash") == previous and row.get("record_hash") not in seen
                 and row.get("version") == VERSION and clock <= current and (last is None or clock >= last)
                 and all(row.get(k) == v for k, v in AUTHORITY.items()), "survival_ledger_integrity_failure")
        for digest in row.get("input_hashes", []):
            _require(re.fullmatch(r"[a-f0-9]{64}", digest) is not None
                     and _digest(_file(root / OUTPUT, Path("inputs") / digest)) == digest,
                     "survival_retained_input_changed")
        _require(row.get("kind") in {"registration", "release_confirmation", "preregistration", "pre_event_screen", "signal", "survival_breakout", "event_evaluation", "outcome", "timing_scope", "timing_link", "timing_window_closed"},
                 "survival_unknown_record_kind")
        if row["kind"] in {"preregistration", "pre_event_screen"}:
            _require(_aware(row["first_observed_at"]) == clock and regular_close(row["source_session"]) <= clock
                     and clock < _aware(row["event"]["research_deadline_at"])
                     and row["ticker"] == row["event"]["ticker"] and row["event_id"] == row["event"]["event_id"],
                     "survival_pre_event_capture_unverified")
        elif row["kind"] == "signal":
            _require(row["entry_session"] == _next_open(clock) and _aware(row["first_observed_at"]) == clock
                     and regular_close(row["source_session"]) <= clock, "survival_first_future_open_unverified")
        elif row["kind"] == "release_confirmation":
            source = _file(root / OUTPUT, Path("inputs") / row["input_hashes"][0])
            parsed = parse_release_document(source)
            _require(parsed["release_at"] == row["release_at"] and parsed["url"] == row["url"]
                     and parsed["title"] == row["title"] and _aware(row["document_observed_at"]) == clock
                     and _aware(row["release_at"]) <= _aware(row["official_news_observed_at"]) <= clock,
                     "survival_release_receipt_or_publication_unverified")
        elif row["kind"] == "survival_breakout":
            signal = next((r for r in rows if r["kind"] == "signal" and r["signal_id"] == row["signal_id"]), None)
            pre = next((r for r in rows if r["record_hash"] == row["preregistration_record_hash"] and r["kind"] == "preregistration"), None)
            confirmation = next((r for r in rows if r["record_hash"] == row["release_confirmation_record_hash"] and r["kind"] == "release_confirmation"), None)
            _require(bool(signal and pre and confirmation) and pre["event_id"] == confirmation["event_id"] == row["event_id"]
                     and _aware(pre["first_observed_at"]) < _aware(confirmation["release_at"])
                     and _aware(signal["first_observed_at"]) >= _aware(confirmation["document_observed_at"])
                     and row["first_observed_at"] == signal["first_observed_at"], "survival_treatment_point_in_time_unverified")
        elif row["kind"] == "outcome":
            signal = next((r for r in rows if r["kind"] == "signal" and r["signal_id"] == row["signal_id"]), None)
            _require(bool(signal) and row["horizon_sessions"] in [5, 10, 14]
                     and regular_close(_sessions(signal["entry_session"], row["horizon_sessions"])[-1]) <= clock,
                     "survival_outcome_future_or_unbound")
        elif row["kind"] in {"timing_scope", "timing_link", "timing_window_closed"}:
            signal = next((r for r in rows if r["kind"] == "signal" and r["signal_id"] == row["signal_id"]), None)
            _require(bool(signal) and _aware(signal["first_observed_at"]) <= clock, "survival_timing_signal_unbound")
            if row["kind"] == "timing_link" and row["state"] == "condition_observed":
                _require(_aware(row["quote_observed_at"]) > _aware(signal["first_observed_at"])
                         and _aware(row["quote_trade_at"]) > _aware(signal["first_observed_at"])
                         and _aware(row["active_recorded_at"]) <= clock, "survival_timing_pre_capture_quote_borrowed")
        rows.append(row); seen.add(row["record_hash"]); previous, last = row["record_hash"], clock
    if rows:
        _require(rows[0]["kind"] == "registration" and rows[0]["implementation_sha256"] == _implementation(root)[0]
                 and rows[0]["policy_sha256"] == _digest(_file(root, POLICY)), "survival_frozen_version_identity_changed")
    return rows


def _add(rows, body, current):
    value = {**body, "version": VERSION, "recorded_at": current.isoformat(),
             "previous_hash": rows[-1]["record_hash"] if rows else "", **AUTHORITY}
    value["record_hash"] = _hash(value)
    rows.append(value)


def _append(root, before, rows):
    path = Path(root) / OUTPUT / "ledger.jsonl"
    _require(path.resolve().is_relative_to(Path(root).resolve()) and not path.is_symlink(), "survival_ledger_path_escape")
    _require((path.read_bytes() if path.exists() else b"") == before, "survival_concurrent_history_change")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(b"".join(_bytes(row) for row in rows)); handle.flush(); os.fsync(handle.fileno())


class _Article(HTMLParser):
    def __init__(self):
        super().__init__(); self.published = set(); self.canonical = set(); self.title = []; self.in_title = False
        self.in_json = False; self.json_text = []; self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property", attrs.get("name", "")).lower()
            if key in {"article:published_time", "datepublished"} and attrs.get("content"):
                self.published.add(attrs["content"])
            if key == "og:url" and attrs.get("content"):
                self.canonical.add(attrs["content"])
        if tag == "link" and attrs.get("rel", "").lower() == "canonical" and attrs.get("href"):
            self.canonical.add(attrs["href"])
        if tag == "title": self.in_title = True
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.in_json = True; self.json_text = []

    def handle_endtag(self, tag):
        if tag == "title": self.in_title = False
        if tag == "script" and self.in_json:
            self.scripts.append("".join(self.json_text)); self.in_json = False

    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        if self.in_json: self.json_text.append(data)


def parse_release_document(raw):
    """Accept only explicit publication metadata, never a guessed/date-only time."""
    _require(100 <= len(raw) <= 2 * 1024 * 1024, "survival_release_document_size")
    parser = _Article(); text = raw.decode("utf-8"); parser.feed(text)
    def visit(value):
        if isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if any(t in {"Article", "NewsArticle", "PressRelease"} for t in types) and value.get("datePublished"):
                parser.published.add(value["datePublished"])
            for child in value.values():
                if isinstance(child, (dict, list)): visit(child)
    for script in parser.scripts:
        try: visit(json.loads(script))
        except json.JSONDecodeError: raise StudyError("survival_release_structured_data_invalid") from None
    _require(bool(parser.published), "survival_actual_publication_metadata_missing")
    clocks = set()
    for value in parser.published:
        _require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)", value) is not None,
                 "survival_precise_publication_timezone_required")
        clocks.add(_aware(value).isoformat())
    title = " ".join(" ".join(parser.title).split())
    _require(len(clocks) == 1 and len(parser.canonical) == 1, "survival_release_metadata_ambiguous")
    _require(re.search(r"\b(reports?|announces?|releases?)\b.*\b(results|earnings)\b", title, re.I)
             and not re.search(r"\b(will|webcast|schedules?)\b|\bto\s+(report|announce|release)\b", title, re.I),
             "survival_actual_results_headline_required")
    return {"release_at": next(iter(clocks)), "url": next(iter(parser.canonical)), "title": title}


def _events(root, current):
    from earnings_events import event_observations
    return event_observations(root, current=current)


def _context(root, current):
    import active_swing_research as active
    return active.research_context(root, current)


def _features(bars):
    import active_swing_research as active
    return active.features(bars)


def _timing_records(root, current):
    import active_swing_research as active
    return active.validated_records(root, current)


def _baseline(root, baseline, bindings, current):
    import active_swing_research as active
    if hasattr(active, "baseline_context"):
        return active.baseline_context(root, baseline, bindings, current)
    return {"status": "unverified", "comparability": "unverified", "observed_canonical": {}, "observed_tactical": {}}


def _confirmation(root, proposal, current):
    from official_news import canonical_url, load_manifest
    from issuer_news_queue import read_queue
    _require(proposal.get("schema_version") == RELEASE_SCHEMA and len(proposal.get("reviewer", "").strip()) >= 3
             and len(proposal.get("reasoning", "").strip()) >= 80, "survival_release_review_required")
    events, _ = _events(root, current)
    if not any(event["event_id"] == proposal.get("event_id") for event in events):
        events += [row["event"] for row in _load(root, current) if row["kind"] == "preregistration"]
    matches = [event for event in events if event["event_id"] == proposal.get("event_id") and event["ticker"] == proposal.get("ticker")]
    _require(len(matches) == 1, "survival_exact_calendar_event_required")
    event = matches[0]
    _require(proposal.get("fiscal_period_label") == event["fiscal_period_label"], "survival_release_period_mismatch")
    raw = _file(root, proposal.get("document_path", ""))
    _require(_digest(raw) == proposal.get("document_sha256"), "survival_release_document_hash_mismatch")
    parsed = parse_release_document(raw)
    manifest_raw = _file(root, "01_policies/official_news_sources.json")
    manifest = load_manifest(Path(root) / "01_policies/official_news_sources.json")
    hosts = sorted({host for source in manifest["sources"] if source["ticker"] == event["ticker"] for host in source["allowed_hosts"]})
    url = canonical_url(proposal.get("url", ""), hosts)
    _require(canonical_url(parsed["url"], hosts) == url and _aware(parsed["release_at"]) <= current,
             "survival_release_url_or_future_clock")
    if "release_at" in proposal:
        _require(_aware(proposal["release_at"]) == _aware(parsed["release_at"]), "survival_proposed_release_clock_not_source_metadata")
    evidence = proposal.get("fiscal_period_evidence", "")
    body = raw.decode("utf-8")
    _require(isinstance(evidence, str) and 20 <= len(evidence) <= 1500 and evidence in body
             and re.search(r"\b" + re.escape(event["ticker"]) + r"\b", body) is not None,
             "survival_release_ticker_period_evidence_required")
    try:
        month = datetime.strptime(event["fiscal_period_label"], "%b/%Y")
    except (ValueError, TypeError):
        raise StudyError("survival_calendar_period_format_unsupported") from None
    month_names = {month.strftime("%B"), month.strftime("%b")}
    if month.month == 9: month_names.add("Sept")
    period_pattern = (r"\b(?:quarter|period|months|year)\s+(?:ended|ending)\s+(?:" + "|".join(month_names)
                      + r")\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?" + str(month.year) + r"\b")
    primary_statement = r"\b(?:financial\s+|operating\s+)?results\s+(?:for|of)\s+(?:the\s+)?" + period_pattern[2:]
    _require(re.search(period_pattern, evidence, re.I) is not None
             and (re.search(period_pattern, parsed["title"], re.I) is not None
                  or re.search(primary_statement, body, re.I) is not None),
             "survival_document_period_not_independently_bound")
    queue = read_queue(Path(root))
    news = [row for row in queue if row["kind"] == "observed_event" and row["event_id"] == proposal.get("official_news_event_id")
            and row["ticker"] == event["ticker"] and row["event"]["url"] == url
            and _aware(row["event"]["published_at"]) == _aware(parsed["release_at"])
            and _aware(row["recorded_at"]) <= current
            and " ".join(row["event"]["title"].split()).lower() in parsed["title"].lower()]
    _require(len(news) == 1, "survival_corroborating_official_news_receipt_required")
    return {"kind": "release_confirmation", "event_id": event["event_id"], "ticker": event["ticker"],
            "fiscal_period_label": event["fiscal_period_label"], **parsed,
            "document_observed_at": current.isoformat(), "official_news_observed_at": news[0]["recorded_at"],
            "reviewer": proposal["reviewer"], "reasoning": proposal["reasoning"],
            "proposal_sha256": _hash(proposal), "document_sha256": _digest(raw),
            "source_bound_analyst_confirmation": True, "calendar_estimate_is_release_clock": False}, [raw, manifest_raw, _bytes(news[0]), _bytes(event), _bytes(proposal)]


def confirm_release(root, proposal, current, *, apply=False):
    """Check by default. Apply requires the caller's runtime/pipeline lock order."""
    root, current = Path(root), _aware(current)
    try:
        value, raws = _confirmation(root, proposal, current)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        if apply:
            with ExclusiveFileLock(root / OUTPUT / "study.lock"):
                proposal_hash = _retain(root, _bytes(proposal))
                reason = str(exc) if isinstance(exc, StudyError) else "survival_release_evidence_unverified"
                receipt = {"proposal_sha256": proposal_hash, "reason": reason, "recorded_at": current.isoformat(), **AUTHORITY}
                path = root / OUTPUT / "rejected_release_attempts" / (_hash(receipt) + ".json")
                _require(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(), "survival_rejection_path_escape")
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    with path.open("xb") as handle: handle.write(_bytes(receipt))
        raise
    if not apply:
        return {**value, "check_only": True, **AUTHORITY}
    with ExclusiveFileLock(root / OUTPUT / "study.lock"):
        rows = _load(root, current); before = _file(root, OUTPUT / "ledger.jsonl") if rows else b""; start = len(rows)
        _register(root, rows, current)
        previous = [row for row in rows if row["kind"] == "release_confirmation" and row["event_id"] == value["event_id"]]
        if previous:
            _require(previous[0]["document_sha256"] == value["document_sha256"]
                     and previous[0]["release_at"] == value["release_at"], "survival_release_conflict_requires_new_reviewed_version")
            return previous[0]
        value["input_hashes"] = [_retain(root, raw) for raw in raws]
        _add(rows, value, current); _append(root, before, rows[start:])
        return rows[-1]


def _register(root, rows, current):
    if not rows:
        _, raw = _policy(root)
        implementation, dependencies = _implementation(root)
        _add(rows, {"kind": "registration", "policy_sha256": _digest(raw),
                    "implementation_sha256": implementation, "implementation_dependencies": dependencies,
                    "input_hashes": [_retain(root, raw)]}, current)


def _net(entry, close, costs):
    return {str(cost): round((close * (1 - cost / 10000) / (entry * (1 + cost / 10000)) - 1) * 100, 6) for cost in costs}


def _planning(root, baseline, current):
    """Source-bound ceiling diagnostic, never an eligible or executable quantity."""
    unavailable = {"status": "unavailable", "dependency": "current_source_bound_capital_and_account_context_required"}
    if not isinstance(baseline, dict): return unavailable, []
    try:
        from capital_decision import validate
        contract = baseline["capital_decision"]
        validate(contract, current=current, root=Path(root))
        relative = ["05_risk_and_positions/current_account_state.local.json", "05_risk_and_positions/current_positions.local.csv",
                    "03_source_data/equity_research/market_data_snapshot.csv", "01_policies/tactical_trade_policy.json"]
        raws = [_file(root, path) for path in relative]
        _require(all(contract["source_bindings"].get(path) == _digest(raw) for path, raw in zip(relative, raws)),
                 "survival_planning_source_binding_changed")
        account, policy = json.loads(raws[0]), json.loads(raws[3])
        held = list(csv.DictReader(raws[1].decode().splitlines()))
        prices = {r["ticker"]: float(r["last_price"]) for r in csv.DictReader(raws[2].decode().splitlines())}
        quantities = {r["ticker"]: float(r["shares_optional"]) for r in held}
        cash = float(account["cash_available"])
        nav = cash + sum(qty * prices[ticker] for ticker, qty in quantities.items())
        _require(all(math.isfinite(v) and v >= 0 for v in [cash, nav, *quantities.values(), *prices.values()]) and nav > 0,
                 "survival_planning_numbers_invalid")
        _require(abs(float(baseline["account"]["account_total_value"]) - nav) < .011
                 and policy.get("event_risk_pct") == .25 and policy.get("max_position_pct") == 5,
                 "survival_planning_nav_or_policy_unverified")
        remaining = float(contract["estimated_uncommitted_cash_after"])
        _require(0 <= remaining <= cash, "survival_uncommitted_cash_invalid")
        risk = baseline.get("tactical_review", {}).get("risk_budget", {})
        return {"status": "source_bound_planning_ceiling_only", "planning_nav": round(nav, 2),
                "uncommitted_cash_upper_bound": remaining, "event_risk_pct": policy["event_risk_pct"],
                "max_position_pct": policy["max_position_pct"], "held_values": {t: q * prices[t] for t, q in quantities.items()},
                "open_risk_status": "unknown" if risk.get("open_risk_usd") is None else "requires_independent_current_order_and_risk_review",
                "capital_contract_sha256": contract["content_sha256"], "source_bindings": {p: _digest(r) for p, r in zip(relative, raws)},
                "execution_funds_verified": False, "actual_quantity": 0}, [*raws, _bytes(contract)]
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return unavailable, []


def _ceiling(planning, ticker, entry, stop):
    if planning.get("status") != "source_bound_planning_ceiling_only": return planning
    result = {k: v for k, v in planning.items() if k != "held_values"}
    if not 0 < stop < entry:
        return {**result, "status": "invalid_price_invalidation_relationship", "whole_share_upper_bound": 0}
    nav = planning["planning_nav"]
    room = max(0, nav * planning["max_position_pct"] / 100 - planning["held_values"].get(ticker, 0))
    ceilings = {"cash": math.floor(planning["uncommitted_cash_upper_bound"] / entry),
                "name_headroom": math.floor(room / entry),
                "event_planned_loss": math.floor((nav * planning["event_risk_pct"] / 100) / (entry - stop))}
    return {**result, "price_reference": entry, "invalidation_reference": stop,
            "name_headroom_usd": room, "event_planned_loss_budget_usd": nav * planning["event_risk_pct"] / 100,
            "whole_share_ceilings": ceilings, "whole_share_upper_bound": min(ceilings.values()),
            "combined_risk_eligible_quantity": None, "actual_quantity": 0,
            "limitations": "Upper bound only; combined open risk, aggregate allocation, current execution cash/orders, spreads and future entry price remain independent. No capital or stop execution is cleared."}


def _future_quote_ceiling(signal, price):
    frozen = signal.get("planning_feasibility", {})
    if frozen.get("status") != "source_bound_planning_ceiling_only": return frozen
    stop = frozen["invalidation_reference"]
    if not 0 < stop < price:
        return {"status": "invalid_price_invalidation_relationship", "actual_quantity": 0}
    ceilings = {"cash": math.floor(frozen["uncommitted_cash_upper_bound"] / price),
                "name_headroom": math.floor(frozen["name_headroom_usd"] / price),
                "event_planned_loss": math.floor(frozen["event_planned_loss_budget_usd"] / (price - stop))}
    return {"status": "historical_frozen_account_ceiling_only", "account_diagnostic_as_of": signal["first_observed_at"],
            "price_reference": price, "invalidation_reference": stop, "whole_share_ceilings": ceilings,
            "whole_share_upper_bound": min(ceilings.values()), "combined_risk_eligible_quantity": None,
            "current_execution_cash_verified": False, "actual_quantity": 0}


def _link_timing(root, rows, current, active_rows):
    """Import evidence, never historical entries preceding this study's capture."""
    signals = [r for r in rows if r["kind"] == "signal"]
    observations = [r for r in active_rows if r.get("kind") == "observation"]
    for signal in signals:
        original = json.loads(_file(root / OUTPUT, Path("inputs") / signal["dataset_sha256"]))
        original_bars = original["series"][signal["ticker"]]["bars"][-51:]
        matching = [r for r in observations if r.get("ticker") == signal["ticker"] and r.get("source_session") == signal["source_session"]
                    and r.get("price_basis") == signal["price_basis"] and r.get("bars_at_observation") == original_bars
                    and all(r.get("inputs", {}).get(k) == signal["data_bindings"].get(k)
                            and signal["data_bindings"].get(k) is not None for k in ("dataset_sha256", "implementation_sha256"))]
        if len(matching) != 1: continue
        observation = matching[0]
        scope = next((r for r in rows if r["kind"] == "timing_scope" and r["signal_id"] == signal["signal_id"]), None)
        if scope is None:
            source_hash = _retain(root, _bytes(observation))
            _add(rows, {"kind": "timing_scope", "signal_id": signal["signal_id"], "ticker": signal["ticker"],
                        "active_observation_id": observation["observation_id"], "active_observation_record_hash": observation["record_hash"],
                        "review_windows": observation["review_windows"], "input_hashes": [source_hash]}, current)
        capture = _aware(signal["first_observed_at"])
        candidates = [r for r in active_rows if r.get("kind") in {"window_evaluation", "delay_evaluation"}
                      and r.get("observation_id") == observation["observation_id"]]
        first_invalidation = next((r for r in candidates if r.get("state") == "invalidation_observed"), None)
        for record in candidates:
            if _aware(record["recorded_at"]) < capture: continue
            if any(r["kind"] == "timing_link" and r["signal_id"] == signal["signal_id"]
                   and r["active_record_hash"] == record["record_hash"] for r in rows): continue
            state, quote = record["state"], record.get("quote_observation")
            window = next((w for w in observation["review_windows"] if w["id"] == record.get("window_id")), None)
            if window is None: continue
            anchor = None
            if record["kind"] == "delay_evaluation":
                anchor = next((r for r in candidates if r["record_hash"] == record.get("first_entry_observation_record_hash")), None)
                anchor_quote = anchor.get("quote_observation") if anchor else None
                if not anchor_quote or _aware(anchor_quote["observed_at"]) <= capture:
                    state = "delay_anchor_before_study_capture_or_unavailable"
            if quote:
                trade, observed, evaluated = (_aware(quote["trade_at"]), _aware(quote["observed_at"]), _aware(record["recorded_at"]))
                if observed <= capture or trade <= capture:
                    state = "quote_precedes_study_capture_not_borrowed"
                elif not (_aware(window["starts_at"]) <= trade <= observed <= evaluated < _aware(window["ends_at"])
                          and (evaluated - trade).total_seconds() <= 300 and evaluated < _aware(quote["expires_at"])):
                    state = "stale_or_outside_window_quote_unavailable"
            elif state == "condition_observed":
                state = "qualifying_state_without_source_quote_unavailable"
            if (state == "condition_observed" and first_invalidation
                    and _aware(first_invalidation["recorded_at"]) <= _aware(record["recorded_at"])):
                state = "invalidated_before_study_entry"
            raw_hash = _retain(root, _bytes(record))
            body = {"kind": "timing_link", "signal_id": signal["signal_id"], "ticker": signal["ticker"],
                    "active_observation_id": observation["observation_id"], "active_record_hash": record["record_hash"],
                    "active_recorded_at": record["recorded_at"], "active_kind": record["kind"], "window_id": record["window_id"],
                    "delay_minutes": record.get("delay_minutes"), "state": state,
                    "source_state": record["state"], "input_hashes": [raw_hash], "actual_delay_seconds": record.get("actual_delay_seconds"),
                    "prior_invalidation_record_hash": first_invalidation["record_hash"] if first_invalidation else None,
                    "current_entry_or_execution": False, "window_return_status": "post_entry_stop_path_and_matched_quotes_not_qualified"}
            if quote and _aware(quote["observed_at"]) > capture and _aware(quote["trade_at"]) > capture:
                body.update(quote_price=quote["price"], quote_trade_at=quote["trade_at"], quote_observed_at=quote["observed_at"],
                            quote_expires_at=quote["expires_at"], planning_feasibility=_future_quote_ceiling(signal, quote["price"]))
            _add(rows, body, current)
        for window in observation["review_windows"]:
            if current < _aware(window["ends_at"]): continue
            links = [r for r in rows if r["kind"] == "timing_link" and r["signal_id"] == signal["signal_id"] and r["window_id"] == window["id"]]
            state = ("elapsed_before_study_capture_not_tested" if _aware(window["ends_at"]) <= capture else
                     "qualifying_nominal_observation_retained" if any(r["state"] == "condition_observed" for r in links) else
                     "observed_without_qualifying_entry" if links else "missed_no_observation_after_study_capture")
            previous = [r for r in rows if r["kind"] == "timing_window_closed" and r["signal_id"] == signal["signal_id"] and r["window_id"] == window["id"]]
            if not previous or previous[-1]["state"] != state:
                _add(rows, {"kind": "timing_window_closed", "signal_id": signal["signal_id"], "ticker": signal["ticker"],
                            "window_id": window["id"], "state": state, "ends_at": window["ends_at"]}, current)


def _timing_summary(rows, signals, blockers):
    scopes = [r for r in rows if r["kind"] == "timing_scope"]
    links = [r for r in rows if r["kind"] == "timing_link"]
    unique = {(r["signal_id"], r["window_id"]) for r in links if r["state"] == "condition_observed" and r["active_kind"] == "window_evaluation"}
    closed = {}
    for row in rows:
        if row["kind"] == "timing_window_closed": closed[(row["signal_id"], row["window_id"])] = row["state"]
    states = Counter(r["state"] for r in links)
    result = {"status": "source_unavailable" if blockers else "retained_actual_observations" if links else "waiting_on_forward_owner_window_observations" if signals else "no_registered_breakout_signals",
            "matched_source_observations": len(scopes), "unmatched_source_signals": len(signals) - len(scopes),
            "unique_setup_windows_with_qualifying_marks": len(unique), "window_evaluation_records": sum(r["active_kind"] == "window_evaluation" for r in links),
            "states": dict(sorted(states.items())), "closed_window_states": dict(Counter(closed.values())),
            "delay_cohorts": [{"delay_minutes": delay, "records": sum(r["delay_minutes"] == delay for r in links),
                               "qualifying_marks": sum(r["delay_minutes"] == delay and r["state"] == "condition_observed" for r in links)} for delay in [3, 5, 10]],
            "observations": [{k: r.get(k) for k in ("signal_id", "ticker", "window_id", "delay_minutes", "state", "active_record_hash", "active_recorded_at", "quote_observed_at", "quote_expires_at", "actual_delay_seconds", "planning_feasibility")} for r in links[-12:]],
            "interpretation": "Source-bound historical last sales after study capture only; delay variants are not independent setups, current entries, owner response or fills. EOD primary paths remain separate; window stop/benchmark outcomes are unqualified."}
    if blockers:
        for key in ("matched_source_observations", "unmatched_source_signals", "unique_setup_windows_with_qualifying_marks", "window_evaluation_records"):
            result[key] = None
        result.update(states={}, closed_window_states={}, delay_cohorts=[], observations=[], dependencies=blockers)
    return result


def _signal(ticker, item, dataset, bindings, clock, baseline, feature):
    identity = _hash({"version": VERSION, "ticker": ticker, "session": dataset["market_session"]})
    return {"kind": "signal", "signal_id": identity, "ticker": ticker, "source_session": dataset["market_session"],
            "first_observed_at": clock.isoformat(), "entry_session": _next_open(clock), "features": feature,
            "price_basis": item["price_basis"], "dataset_sha256": _hash(dataset), "data_bindings": bindings,
            "baseline_eligibility": {"status": baseline.get("status", "unverified"),
                                     "comparability": baseline.get("comparability", "unverified"),
                                     "canonical": baseline.get("observed_canonical", {}).get(ticker),
                                     "existing_tactical": baseline.get("observed_tactical", {}).get(ticker)},
            "ordinary_breakout": True, "actual_fill": False}


def _release_session(release):
    clock = _aware(release)
    if is_us_market_session_date(clock.date()) and _open(clock.date().isoformat()) <= clock < regular_close(clock.date().isoformat()):
        return None
    return _next_open(clock)


def _advance(root, rows, current, context, events, baseline, policy, retain, planning):
    dataset, bindings = context["dataset"], context["bindings"]
    features = context["features"]
    source_session, series = dataset["market_session"], dataset["series"]
    _require(regular_close(source_session) <= current, "survival_completed_session_required")
    inputs = [_hash(dataset), *context.get("planning_input_hashes", [])]
    if retain:
        _retain(root, _bytes(dataset))
        for path, digest in bindings.get("source_hashes", {}).items():
            raw = _file(root, path)
            _require(_digest(raw) == digest, "survival_admitted_source_changed")
            inputs.append(_retain(root, raw))
    known = {(row["kind"], row.get("event_id"), row.get("ticker"), row.get("source_session")) for row in rows}
    prereg = {row["event_id"]: row for row in rows if row["kind"] == "preregistration"}
    confirmations = {row["event_id"]: row for row in rows if row["kind"] == "release_confirmation"}
    for event in events:
        ticker, event_id = event["ticker"], event["event_id"]
        if (event_id in prereg or current >= _aware(event["research_deadline_at"]) or event.get("blockers")
                or event.get("timing") != "pre_event" or event.get("status") != "detected"): continue
        if event_id in confirmations and current >= _aware(confirmations[event_id]["release_at"]): continue
        if ("pre_event_screen", event_id, ticker, source_session) in known: continue
        item = series.get(ticker)
        if not item or not item.get("common_stock"):
            continue
        feature = features[ticker]
        selected = (feature["sma20"] > feature["sma50"] and feature["close"] > feature["sma20"]
                    and feature["observed_five_session_low"] < feature["close"] <= feature["prior_19_session_high"])
        body = {"kind": "preregistration" if selected else "pre_event_screen", "event_id": event_id, "ticker": ticker,
                "source_session": source_session, "first_observed_at": current.isoformat(), "selected": selected,
                "support": feature["observed_five_session_low"], "resistance": feature["prior_19_session_high"],
                "event": event, "features": feature, "dataset_sha256": _hash(dataset), "input_hashes": inputs}
        if retain:
            event_inputs = [_retain(root, _bytes(event))]
            for source in event.get("sources", []):
                event_raw = _file(root, source["path"])
                _require(_digest(event_raw) == source["sha256"], "survival_calendar_source_changed")
                event_inputs.append(_retain(root, event_raw))
            body["input_hashes"] = [*inputs, *event_inputs]
        _add(rows, body, current)
        if selected: prereg[event_id] = rows[-1]
    signals = {row["signal_id"]: row for row in rows if row["kind"] == "signal"}
    for ticker, item in sorted(series.items()):
        if item.get("common_stock") and features[ticker]["selected"]["breakout"]:
            body = _signal(ticker, item, dataset, bindings, current, baseline, features[ticker])
            body["planning_feasibility"] = _ceiling(planning, ticker, body["features"]["close"], body["features"]["observed_five_session_low"])
            if body["signal_id"] not in signals:
                body["input_hashes"] = inputs; _add(rows, body, current); signals[body["signal_id"]] = rows[-1]
    for event_id, pre in prereg.items():
        if any(row["kind"] == "survival_breakout" and row["event_id"] == event_id for row in rows): continue
        confirmation = confirmations.get(event_id)
        if any(row["kind"] == "event_evaluation" and row["event_id"] == event_id and row["state"] == "failed_frozen_support" for row in rows):
            state = "failed_frozen_support"
        elif not confirmation:
            state = "actual_results_release_confirmation_required"
        elif _aware(pre["first_observed_at"]) >= _aware(confirmation["release_at"]):
            state = "ineligible_capture_not_before_actual_release"
        else:
            first = _release_session(confirmation["release_at"])
            state = "intraday_release_path_unavailable" if first is None else "awaiting_first_post_release_completed_session"
            if first and source_session >= first:
                days = _sessions(first, policy["post_release_breakout_window_sessions"])
                item = series.get(pre["ticker"])
                lookup = {bar["session_date"]: bar for bar in item["bars"]} if item else {}
                through = [day for day in days if day <= source_session]
                if any(day not in lookup for day in through): state = "post_release_history_unavailable"
                elif any(lookup[day]["low"] < pre["support"] for day in through): state = "failed_frozen_support"
                elif source_session > days[-1]: state = "expired_or_missed_breakout_window"
                else:
                    feature = features[pre["ticker"]]
                    state = "survived_waiting_for_breakout"
                    if feature["selected"]["breakout"] and feature["close"] > pre["resistance"]:
                        signal = _signal(pre["ticker"], item, dataset, bindings, current, baseline, feature)
                        _require(signal["signal_id"] in signals, "survival_ordinary_baseline_binding_missing")
                        actual = signals[signal["signal_id"]]
                        if _aware(actual["first_observed_at"]) < _aware(confirmation["document_observed_at"]):
                            state = "missed_release_confirmation_before_signal_capture"
                        else:
                            _add(rows, {"kind": "survival_breakout", "event_id": event_id, "ticker": pre["ticker"],
                                       "signal_id": signal["signal_id"], "preregistration_record_hash": pre["record_hash"],
                                       "release_confirmation_record_hash": confirmation["record_hash"], "source_session": source_session,
                                       "first_observed_at": actual["first_observed_at"],
                                       "planning_feasibility": _ceiling(planning, pre["ticker"], feature["close"], pre["support"]),
                                       "input_hashes": inputs}, current)
                            state = "survival_breakout_observed"
        confirmation_hash = confirmation["record_hash"] if confirmation else None
        prior = [row for row in rows if row["kind"] == "event_evaluation" and row["event_id"] == event_id]
        if (not prior or prior[-1]["source_session"] != source_session or prior[-1]["state"] != state
                or prior[-1].get("release_confirmation_record_hash") != confirmation_hash):
            _add(rows, {"kind": "event_evaluation", "event_id": event_id, "ticker": pre["ticker"],
                       "source_session": source_session, "state": state, "release_confirmation_record_hash": confirmation_hash,
                       "input_hashes": inputs}, current)
    existing = {(row.get("signal_id"), row.get("horizon_sessions")) for row in rows if row["kind"] == "outcome"}
    for identity, signal in signals.items():
        for horizon in [5, 10, 14]:
            if (identity, horizon) in existing: continue
            days = _sessions(signal["entry_session"], horizon)
            if regular_close(days[-1]) > current: continue
            item = series.get(signal["ticker"])
            lookup = {bar["session_date"]: bar for bar in item["bars"]} if item else {}
            if any(day not in lookup for day in days): continue
            original = json.loads(_file(root / OUTPUT, Path("inputs") / signal["dataset_sha256"]))
            old_bars = original["series"][signal["ticker"]]["bars"]
            if (item["price_basis"] != signal["price_basis"]
                    or any(bar["session_date"] in lookup and bar != lookup[bar["session_date"]] for bar in old_bars)):
                _add(rows, {"kind": "outcome", "signal_id": identity, "ticker": signal["ticker"], "horizon_sessions": horizon,
                           "primary_endpoint": horizon == 5, "status": "original_history_correction_review_required",
                           "matched_benchmarks": {}, "input_hashes": inputs, "actual_fill": False,
                           "risk_managed_strategy_qualified": False}, current)
                continue
            entry, close = lookup[days[0]]["open"], lookup[days[-1]]["close"]
            stock = _net(entry, close, policy["one_way_cost_bps"]); comparisons, missing = {}, []
            for ticker in ["SPY", "QQQM"]:
                benchmark = series.get(ticker)
                values = {bar["session_date"]: bar for bar in benchmark["bars"]} if benchmark else {}
                if (not benchmark or benchmark.get("price_basis") != signal["price_basis"]
                        or any(day not in values for day in days)):
                    missing.append(ticker); continue
                net = _net(values[days[0]]["open"], values[days[-1]]["close"], policy["one_way_cost_bps"])
                comparisons[ticker] = {"benchmark_price_cost_sensitivity_pct": net,
                                       "excess_price_path_pct_points": {cost: round(stock[cost] - net[cost], 6) for cost in stock}}
            _add(rows, {"kind": "outcome", "signal_id": identity, "ticker": signal["ticker"], "horizon_sessions": horizon,
                       "primary_endpoint": horizon == 5, "entry_session": days[0], "exit_session": days[-1],
                       "entry_price": entry, "exit_price": close, "stock_price_cost_sensitivity_pct": stock,
                       "dataset_sha256": _hash(dataset),
                       "matched_benchmarks": comparisons, "missing_benchmarks": missing, "input_hashes": inputs,
                       "status": "unreviewed_fixed_horizon_price_path", "corporate_action_review_required": True,
                       "entry_day_exit_ordering_status": "not_evaluated_fixed_horizon_only", "actual_fill": False,
                       "risk_managed_strategy_qualified": False}, current)


def _view(root, rows, current, policy_raw, context, events_coverage, blockers, timing_blockers=None):
    pre = [r for r in rows if r["kind"] == "preregistration"]
    signals = [r for r in rows if r["kind"] == "signal"]
    treatment = [r for r in rows if r["kind"] == "survival_breakout"]
    outcomes = [r for r in rows if r["kind"] == "outcome"]
    evaluations = {}
    for row in rows:
        if row["kind"] == "event_evaluation": evaluations[row["event_id"]] = row
    counts = Counter(row["state"] for row in evaluations.values())
    dependencies = Counter(blockers)
    dependencies.update(timing_blockers or [])
    if context: dependencies.update(context.get("blockers", []))
    dependencies.update({code: count for code, count in counts.items() if "required" in code or "unavailable" in code})
    dependencies.update({r["status"]: 1 for r in outcomes if "required" in r["status"]})
    if outcomes: dependencies["source_bound_corporate_action_and_economic_review_required"] += len(outcomes)
    confirmations = {r["event_id"]: r for r in rows if r["kind"] == "release_confirmation"}
    treatment_by_event = {r["event_id"]: r for r in treatment}
    candidates = [{"ticker": r["ticker"], "event_id": r["event_id"], "observation_id": r["record_hash"],
                   "support": r["support"], "resistance": r["resistance"], "first_observed_at": r["first_observed_at"],
                   "release_at": confirmations.get(r["event_id"], {}).get("release_at"),
                   "release_observed_at": confirmations.get(r["event_id"], {}).get("document_observed_at"),
                   "breakout_observed_at": treatment_by_event.get(r["event_id"], {}).get("first_observed_at"),
                   "planning_feasibility": treatment_by_event.get(r["event_id"], {}).get("planning_feasibility"),
                   "state": evaluations.get(r["event_id"], {}).get("state", "awaiting_post_event_review"), **AUTHORITY} for r in pre]
    path = Path(root) / OUTPUT / "ledger.jsonl"
    result = {"schema_version": SCHEMA, "version": VERSION, "generated_at": current.isoformat(),
              "status": "waiting_on_data" if blockers else "prospective_research_only",
              "registered_at": rows[0]["recorded_at"] if rows else None, "policy_sha256": _digest(policy_raw),
              "ledger_source": {"path": str(OUTPUT / "ledger.jsonl"), "sha256": _digest(path.read_bytes() if path.exists() else b""), "records": len(rows)},
              "source_bindings": context.get("bindings", {}).get("source_hashes", {}) if context else {},
              "event_coverage": events_coverage, "candidates": candidates,
              "summary": {"pre_event_candidates": len(pre), "ordinary_breakout_signals": len(signals),
                          "survival_breakout_signals": len(treatment), "failed_support": counts["failed_frozen_support"],
                          "expired_or_missed": counts["expired_or_missed_breakout_window"],
                          "unavailable": sum(count for code, count in counts.items() if "required" in code or "unavailable" in code),
                          "distinct_setup_ids": len(signals),
                          "matured_primary_paths": sum(r["horizon_sessions"] == 5 and r["status"] == "unreviewed_fixed_horizon_price_path" for r in outcomes),
                          "unavailable_primary_paths": sum(r["horizon_sessions"] == 5 and r["status"] != "unreviewed_fixed_horizon_price_path" for r in outcomes),
                          "matched_primary_paths": sum(r["horizon_sessions"] == 5 and len(r["matched_benchmarks"]) == 2 for r in outcomes),
                          "qualified_strategy_paths": 0},
              "baseline": {"ordinary_breakout_signals": len(signals),
                           "unknown_eligibility": sum(r["baseline_eligibility"]["status"] != "verified_current" for r in signals),
                           "interpretation": "Shared signal IDs, identical capture/future-open clocks and costs; overlapping cohort membership and horizons are not independent trials. Canonical eligibility is separate from economic outcome."},
              "signals": [{k: row[k] for k in ("signal_id", "ticker", "source_session", "first_observed_at", "entry_session", "baseline_eligibility", "planning_feasibility")} for row in signals[-12:]],
              "outcomes": outcomes[-12:], "dependencies": [{"code": code, "count": count} for code, count in sorted(dependencies.items())],
              "timing_usability": _timing_summary(rows, signals, timing_blockers or []),
              "delay_observations_status": "source_unavailable" if timing_blockers else "see_source_bound_timing_usability_no_elapsed_open_proxy",
              "feasibility": {**(context.get("planning_feasibility", {}) if context else {}), "portfolio_capacity": "unverified",
                              "managed_stop_path": "unverified", "actual_quantity": 0,
                              "interpretation": "Recorded planning ceilings are diagnostics only. No actionable quantity; fixed-horizon paths do not verify execution funds, owner response or managed-stop feasibility."},
              "profitability_established": False, "reliable_win_rate": None, **AUTHORITY}
    result["content_sha256"] = _hash(result)
    return result


def build(root, current, *, capture=False, baseline=None):
    root, current = Path(root), _aware(current)
    try:
        policy, raw = _policy(root)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return _view(root, [], current, b"", {}, {}, ["survival_current_policy_unavailable_or_invalid"])
    context, events, coverage, blockers, active_rows, timing_blockers = {}, [], {}, [], [], []
    try:
        active_rows = _timing_records(root, current)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        timing_blockers.append("active_owner_window_history_unavailable")
    try:
        context = _context(root, current)
        events, coverage = _events(root, current)
        baseline_context = _baseline(root, baseline, context["bindings"], current)
        planning, planning_raws = _planning(root, baseline, current)
        context["planning_feasibility"] = planning
        coverage = {**coverage, "admitted_common_stock_scope": sum(item.get("common_stock") is True for item in context["dataset"]["series"].values()),
                    "calendar_leads_outside_admitted_common_stock_history": sum(not context["dataset"]["series"].get(event["ticker"], {}).get("common_stock") for event in events),
                    "blocked_calendar_leads": sum(bool(event.get("blockers")) for event in events)}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        blockers.append(str(exc) if isinstance(exc, StudyError) else "admitted_swing_data_or_event_evidence_unavailable")
    def project():
        rows = _load(root, current)
        active_proofs = {row["record_hash"]: _hash(row) for row in active_rows}
        for row in rows:
            if row["kind"] not in {"timing_scope", "timing_link"}: continue
            source_id = row.get("active_record_hash", row.get("active_observation_record_hash"))
            if active_proofs.get(source_id) != row["input_hashes"][0]:
                if "retained_timing_source_no_longer_validated" not in timing_blockers:
                    timing_blockers.append("retained_timing_source_no_longer_validated")
        before = _file(root, OUTPUT / "ledger.jsonl") if rows else b""; start = len(rows)
        if capture and not blockers:
            _register(root, rows, current)
            context["planning_input_hashes"] = [_retain(root, source) for source in planning_raws]
            _advance(root, rows, current, context, events, baseline_context, policy, True, planning)
        if capture and rows and not timing_blockers: _link_timing(root, rows, current, active_rows)
        if capture and len(rows) > start: _append(root, before, rows[start:])
        return _view(root, rows, current, raw, context, coverage, blockers, timing_blockers)
    try:
        if capture:
            with ExclusiveFileLock(root / OUTPUT / "study.lock"): return project()
        return project()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        blockers.append(str(exc) if isinstance(exc, StudyError) else "survival_history_or_capture_unavailable")
        return _view(root, [], current, raw, context, coverage, blockers, timing_blockers)


def revalidate_projection(root, published, current):
    """Read-only current proof; an expired/tampered result cannot remain current."""
    current = _aware(current)
    try:
        _require(published.get("content_sha256") == _hash({k: v for k, v in published.items() if k != "content_sha256"})
                 and published.get("schema_version") == SCHEMA and published.get("version") == VERSION
                 and _aware(published["generated_at"]) <= current
                 and all(published.get(k) == v for k, v in AUTHORITY.items()), "survival_projection_integrity_failure")
        fresh = build(root, current, capture=False)
        _require(published["ledger_source"] == fresh["ledger_source"]
                 and published["policy_sha256"] == fresh["policy_sha256"]
                 and published["source_bindings"] == fresh["source_bindings"], "survival_projection_source_changed")
        return fresh
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return {"schema_version": SCHEMA, "version": VERSION, "generated_at": current.isoformat(), "status": "waiting_on_data",
                "candidates": [], "dependencies": [{"code": "survival_publication_proof_unverified", "count": 1}],
                "profitability_established": False, **AUTHORITY}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--confirm-release", type=Path)
    parser.add_argument("--apply", action="store_true", help="Append an accepted source-bound release confirmation")
    parser.add_argument("--capture", action="store_true", help="Append current prospective study observations")
    args = parser.parse_args()
    _require(not (args.apply and not args.confirm_release) and not (args.capture and args.confirm_release), "survival_cli_mode_invalid")
    current = datetime.now(ET)
    def run():
        if args.confirm_release:
            return confirm_release(args.root, json.loads(args.confirm_release.read_text()), current, apply=args.apply)
        return build(args.root, current, capture=args.capture)
    if args.apply or args.capture:
        # Match the established mutation order: external runtime, then pipeline.
        with ExitStack() as locks:
            locks.enter_context(ExclusiveFileLock(args.root.parent / ".locks/equity-research-runtime.lock"))
            locks.enter_context(ExclusiveFileLock(args.root / "00_project_control/run_logs/daily_pipeline.lock"))
            result = run()
    else: result = run()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
