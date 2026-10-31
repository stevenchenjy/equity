"""Compact email projection of admitted decisions; no research or eligibility logic.

Full cases, every candidate outcome and collection diagnostics remain in the
capital report/dashboard. This projection never ranks an unreviewed screen as
an investment opportunity or turns a review ceiling into an order price.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from capital_decision import validate
from capital_presentation import action_lines, optional_rotation_cards


DIRECT_VERSION = "equity_direct_action_email_v5"


def _quantity(value):
    return format(Decimal(str(value)).normalize(), "f")


def _readable_execution(text):
    """Repair joined English words/numbers without changing any numeric token."""
    text = re.sub(r"\b(selling|sell|buying|buy|from|to|the|all|with|only|minimum|below|above|at|after|before|leave|remain|remainder|filled|limit|expired|old|October|November)(?=\d)",
                  r"\1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=\d)(?=(?:EST|EDT|stop|close|shares?|only)\b)", " ", text)
    text = re.sub(r"\bA(?=\d+-share)", "A ", text)
    text = re.sub(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?=[A-Z][a-z]+\d)", r"\1, ", text)
    text = re.sub(r"(January|February|March|April|May|June|July|August|September|October|November|December)(?=\d)", r"\1 ", text)
    text = re.sub(r"(?<=\w)([<>]=?)(?=\d)", r" \1 ", text)
    text = text.replace("pending-settlement footnote", "pending-settlement (P) footnote")
    return text


def direct_action(decision, row):
    """Exact email-only execution projection; authored conditions are not cut.

    The full capital presentation remains unchanged. Unknown future conditions
    survive verbatim, rather than being summarized by a length limit.
    """
    draft = row.get("order_draft") or {}
    if not draft:
        label = {"ACTIONABLE_BUY": "BUY", "ACTIONABLE_ADD": "ADD",
                 "REDUCE_REVIEW": "REDUCE REVIEW", "EXIT_REVIEW": "EXIT REVIEW"}[row["decision"]]
        return label + " — " + row["ticker"], action_lines(row)
    selling = draft["side"] == "sell"
    stopping = draft["entry_order_type"] == "STOP"
    price = draft["exit_price"] if selling else draft["entry_limit"]
    quantity = _quantity(row["shares"])
    title = f"{draft['side'].upper()} {quantity} {row['ticker']} — {draft['entry_order_type']} {'≤' if stopping or not selling else '≥'} ${price:.2f} · {draft['time_in_force']}"
    start = datetime.fromisoformat(draft["entry_window"]["starts_at"]).astimezone(ZoneInfo("America/New_York"))
    end = datetime.fromisoformat(draft["entry_window"]["ends_at"]).astimezone(ZoneInfo("America/New_York"))
    window = f"{start:%b} {start.day}, {start:%Y} · {start:%H:%M}–{end:%H:%M} {end:%Z}"
    if start.date() != end.date():
        window = f"{start:%Y-%m-%d %H:%M %Z}–{end:%Y-%m-%d %H:%M %Z}"
    lines = ["When: " + window + ". Conditional manual order in Chase."]
    # Remove only exact engine-generated wrappers. Authored sentences, including
    # future company-specific exceptions, survive intact on separate lines.
    wrappers = (
        f"SELL LIMIT at or above ${price:.2f}; verify current quote and available shares before submission. ",
        "；仅为未提交的研究计划，先核验报价、订单和剩余股数。",
        " A target limit does not protect a decline. Stop execution can gap below the trigger.",
        " Reassess by " + draft["entry_window"]["ends_at"] + "; if no fill, the remaining exposure and original purpose persist.",
    )
    for key in ("trigger_rule", "invalidation_rule", "reassessment_rule"):
        text = draft[key]
        for wrapper in wrappers:
            if text.startswith(wrapper):
                text = text[len(wrapper):]
            elif text.endswith(wrapper):
                text = text[:-len(wrapper)]
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
            if sentence and sentence not in lines:
                lines.append(_readable_execution(sentence))
    if selling:
        lines.append("Risk: A stop can gap below its trigger." if stopping else "Risk: A sell limit gives no downside protection.")
    elif draft["risk_model"] in {"observed_price_invalidation", "reviewed_thesis_invalidation"}:
        lines.append(f"Risk: invalidate ${draft['invalidation_price']:.2f}; planned loss ${draft['planned_total_loss']:.2f} "
                     f"({draft['planned_account_risk_pct']:.2f}%); gaps can exceed it.")
        lines.append(f"Target / review: ${draft['initial_reassessment_price']:.2f}.")
    else:
        lines.append(f"Risk: no price stop; full ${draft['planned_total_loss']:.2f} principal "
                     f"({draft['planned_account_risk_pct']:.2f}%) remains exposed.")
    if row.get("position_purpose", {}).get("time_exit_session"):
        lines.append("Time exit session: " + row["position_purpose"]["time_exit_session"] + ".")
    # These engine-owned guards are rendered together once. Additional authored
    # cancellation conditions are retained exactly and cannot disappear.
    standard = {
        "Skip if current holdings or order inventory differs, or shares are already reserved.",
        "Never duplicate a pending exit; confirm cancellation before replacement.",
        "This draft expires at " + draft["entry_window"]["ends_at"] + ".",
        "Expected proceeds are conditional and unsettled; no new purchase is funded by an assumed sale.",
    }
    lines += ["Additional condition: " + value for value in draft["cancel_conditions"] if value not in standard]
    lines.append(("Verify actual holdings, sellable shares, settlement and orders; skip changed or reserved shares. " if selling else
                  "Verify executable funds, current holdings and orders; skip if the entry conditions or available funds fail. ") +
                 "Do not duplicate or replace a pending order without confirming cancellation. "
                 "No fill or spendable proceeds are assumed.")
    standard_exit_cost = "Proceeds at the stated price are an estimate before costs, not a fill or settled buying power."
    if draft["cost_assumption"] == standard_exit_cost:
        lines.append("Estimated proceeds exclude costs.")
    else:
        lines.append("Costs: " + draft["cost_assumption"])
    return title, lines


def displayed_action(decision, row):
    """Version-bound exact strings required by both delivery receipt readers."""
    if decision.get("email_brief_version") == DIRECT_VERSION:
        return direct_action(decision, row)
    label = {"ACTIONABLE_BUY": "BUY", "ACTIONABLE_ADD": "ADD",
             "REDUCE_REVIEW": "REDUCE REVIEW", "EXIT_REVIEW": "EXIT REVIEW"}[row["decision"]]
    return label + " — " + row["ticker"], action_lines(row)


def direct_subject(decision):
    rows = [row for row in decision["capital_decision"]["decisions"] if row.get("order_draft")]
    if rows:
        return " / ".join(direct_action(decision, row)[0] for row in rows)
    rotations = optional_rotation_cards(decision)
    if any(card.get("kind") in {"buy", "sell"} for card in rotations):
        return rotations[0]["title"] + " · " + rotations[0].get("headline", "")
    return "No new trade"


def direct_cards(decision):
    """Action, one unchanged inventory, bounded reason and material blockers."""
    contract = decision["capital_decision"]
    validate(contract, current=datetime.fromisoformat(decision["generated_at"]))
    rows = contract["decisions"]
    held = {row["ticker"]: row for row in decision.get("held_positions", [])}
    result = []
    actionable = [row for row in rows if row.get("order_draft")]
    for row in actionable:
        title, lines = direct_action(decision, row)
        result.append(section(title, lines, group="action",
                              kind="sell" if row["order_draft"]["side"] == "sell" else "buy"))
    rotations = optional_rotation_cards(decision)
    if not actionable and not any(card.get("kind") in {"buy", "sell"} for card in rotations):
        result.append(section("No new trade", ["Buy/add 0; no current priced order passes the required checks."],
                              group="action", kind="inactive"))
    result.extend(rotations)
    checks = ["Current blocker: " + str(code).replace("_", " ") for code in contract.get("global_blockers", [])]
    checks += ["Required: " + item["evidence_required"] for item in contract.get("dependencies", [])
               if item.get("scope") == "global"]
    if checks:
        result.append(section("Required checks", list(dict.fromkeys(checks)), group="action", kind="inactive"))
    for row in rows:
        if row["ticker"] in held and not row.get("order_draft") and row["decision"] in {"BLOCKED", "NO_ACTION", "REDUCE_REVIEW", "EXIT_REVIEW"}:
            result.append(section(row["decision"].replace("_", " ") + " — " + row["ticker"], action_lines(row),
                                  group="action", kind="inactive"))
    from delivery_followthrough import continuation_lines, continuation_requires_reconciliation
    continuity = decision.get("delivery_followthrough", {})
    if continuation_requires_reconciliation(continuity):
        result.append(section("Earlier order — reconcile before replacing", continuation_lines(continuity),
                              group="action", kind="inactive"))
    holds = [row for row in rows if row["decision"] == "HOLD" and not row.get("order_draft") and row["ticker"] in held]
    if holds:
        inventory = "; ".join(row["ticker"] + " " + _quantity(held[row["ticker"]]["current_shares"])
                              + (" share" if Decimal(str(held[row["ticker"]]["current_shares"])) == 1 else " shares") for row in holds)
        result.append(section("Unchanged holdings", [inventory + ". Add 0 / sell 0 for these holdings."]))
    reasons = []
    for row in actionable:
        # Only complete short authored sentences qualify for the compact reason;
        # longer analysis stays in the report. Execution conditions above are
        # never subject to this presentation budget.
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", str(row.get("thesis_summary", "")))[:1]:
            if sentence and len(sentence.split()) <= 28 and sentence not in reasons:
                reasons.append(_readable_execution(sentence))
            if len(reasons) == 2:
                break
        if len(reasons) == 2:
            break
    if reasons:
        result[-1]["body"] += "\n" + " ".join(reasons)
    # Genuine triggered portfolio conditions remain visible; unavailable or
    # untriggered monitoring diagnostics are retained only in the full report.
    risk = decision.get("intraday_portfolio_risk", {})
    material = [entry for key in ("plan_conditions", "reassessment_triggers")
                for entry in risk.get(key, []) if isinstance(entry, dict)
                and entry.get("status") in {"triggered", "breached", "requires_reassessment"}]
    if material:
        result.append(section("Risk condition — reassess", [str(entry.get("ticker", "Portfolio")) + ": "
            + str(entry.get("message") or entry.get("condition") or entry.get("description") or "Current plan requires reassessment.")
            for entry in material], group="action", kind="inactive"))
    return result


def section(title, lines, *, group="background", kind="", headline="", sources=()):
    return dict(title=title, body="\n".join(lines), group=group, kind=kind,
                headline=headline, sources=list(dict.fromkeys(sources)))


def current_priorities(decision):
    """Use only the already admitted, current authored order, never queue rank."""
    review = decision.get("analyst_priority_review", {})
    if (review.get("schema_version") != "equity_priority_review_context_v1"
            or review.get("status") != "current"):
        return []
    return review.get("entries", [])[:3]


def subject_label(decision):
    if any(row.get("order_draft") or row.get("decision") in {"REDUCE_REVIEW", "EXIT_REVIEW"}
           for row in decision.get("capital_decision", {}).get("decisions", [])):
        return "Conditional action"
    if any(card.get("kind") in {"buy", "sell"} for card in optional_rotation_cards(decision)):
        return "Conditional rotation review"
    return "Company attention" if current_priorities(decision) else "No new trade"


def held_earnings_card(decision):
    """Nearest retained held-company catalysts, never the raw calendar queue."""
    report = decision.get("earnings_events", {})
    if report.get("schema_version") != "equity_earnings_event_view_v1":
        return None
    try:
        current = datetime.fromisoformat(decision["generated_at"])
        if current.tzinfo is None:
            return None
        current = current.astimezone(ZoneInfo("America/New_York"))
    except (KeyError, TypeError, ValueError):
        return None
    held = {row["ticker"] for row in decision.get("held_positions", [])}
    upcoming = []
    unresolved_timing = []
    for row in report.get("events", []):
        if (not isinstance(row, dict) or row.get("ticker") not in held
                or row.get("status") == "cancelled" or row.get("timing") not in {None, "pre_event"}):
            continue
        try:
            event_date = date.fromisoformat(row["event_date"])
        except (KeyError, TypeError, ValueError):
            unresolved_timing.append(row)
            continue
        if event_date < current.date():
            continue
        try:
            event_at = datetime.fromisoformat(str(row.get("event_at", "")).replace("Z", "+00:00"))
            if event_at.tzinfo is None:
                event_at = None
        except ValueError:
            event_at = None
        if event_at is not None and event_at <= current:
            continue
        upcoming.append((event_date, event_at.timestamp() if event_at else float("inf"), row, event_at))
    if not upcoming and not unresolved_timing:
        return None
    upcoming.sort(key=lambda item: (item[0], item[1], str(item[2].get("ticker")), str(item[2].get("event_id", ""))))
    lines = ["Held-company event risk; a calendar date is not a buy signal or a confirmed release time."]
    sources = []
    selected = upcoming[:3]
    for event_date, _, row, event_at in selected:
        timing = ("recorded event time " + str(row["event_at"]) if event_at else
                  "exact event time unverified (" + str(row.get("session") or "session unverified").replace("_", " ") + ")")
        confidence = str(row.get('date_confidence') or 'unverified').replace('_', ' ')
        lines.append(f"{row['ticker']}: {event_date.isoformat()}; {timing}; date confidence: {confidence}.")
        deadline = row.get("research_deadline_at")
        due = row.get("status") in {"review_due", "reassessment_due"} or "earnings_event_review_due" in row.get("blockers", [])
        try:
            parsed = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            due = due or (parsed.tzinfo is not None and parsed <= current)
        except ValueError:
            pass
        state = str(row.get("status") or "unverified").replace("_", " ")
        if row.get("status") == "eligible_conditional_plan":
            state = "event review recorded; any current draft is shown separately in action cards"
        lines.append(f"Research state: {state}; {'recheck due' if due else 'no due recheck recorded'}. "
                     f"Research deadline: {deadline or 'unverified'}; this is not the event release time or a holding-plan extension.")
        from email_brief import _safe_source
        retained = [*row.get("sources", []), *(row.get("event_review") or {}).get("sources", [])]
        event_links = []
        for source in retained:
            url = source.get("source_url", source.get("url", "")) if isinstance(source, dict) else ""
            try:
                host = urlsplit(url).hostname
            except (TypeError, ValueError):
                continue
            safe = _safe_source(url, {host}) if host else ""
            if safe and safe not in event_links:
                event_links.append(safe)
        sources.extend(event_links[:2])
    if unresolved_timing:
        remaining = 3 - len(selected)
        shown_unknown = unresolved_timing[:remaining]
        names = "; ".join(str(row["ticker"]) + " — event date/time unverified; research deadline "
                          + str(row.get("research_deadline_at") or "unverified") for row in shown_unknown)
        if names:
            lines.append("Timing dependency: " + names + ". Verify the retained schedule before relying on it.")
        if len(unresolved_timing) > len(shown_unknown):
            lines.append(f"Additional unresolved held-event timing records: {len(unresolved_timing) - len(shown_unknown)}; verify the retained schedules on the dashboard.")
    lines.append("Detailed expectations, downside cases and all retained source receipts remain on the dashboard. No trigger, price or order is created by this event warning.")
    return section("Upcoming events in your holdings", lines, group="attention", sources=sources)


def cards(decision):
    contract = decision["capital_decision"]
    validate(contract, current=datetime.fromisoformat(decision["generated_at"]))
    rows = contract["decisions"]
    actionable = [row for row in rows if row.get("order_draft")]
    adverse = [row for row in rows if not row.get("order_draft")
               and row["decision"] in {"REDUCE_REVIEW", "EXIT_REVIEW"}]
    rotations = optional_rotation_cards(decision)
    positive_rotation = any(card.get("kind") in {"buy", "sell"} for card in rotations)
    result = [section("Decision", [
        "Read the complete conditional drafts below; you decide and manually execute any order in Chase."
        if actionable or positive_rotation else
        "No new buy/add or priced sell draft passes the current checks. No order is requested.",
    ], group="action", kind="inactive" if not actionable and not positive_rotation else "",
        headline=subject_label(decision).upper())]
    result.extend(rotations)
    for row in [*actionable, *adverse]:
        side = (row.get("order_draft") or {}).get("side")
        label = {"ACTIONABLE_BUY": "BUY", "ACTIONABLE_ADD": "ADD",
                 "REDUCE_REVIEW": "REDUCE REVIEW", "EXIT_REVIEW": "EXIT REVIEW"}[row["decision"]]
        result.append(section(label + " — " + row["ticker"], action_lines(row),
            group="action", kind="sell" if side == "sell" or row in adverse else "buy",
            headline=f"{row['shares']} shares · approx. ${row['estimated_notional']:.2f}"
            if row.get("order_draft") else "No current priced order — assessment required"))

    # Never hide account integrity, execution reconciliation or a withdrawn draft
    # to meet a cosmetic length limit. These are owner-relevant conditions.
    global_checks = [item for item in contract.get("dependencies", []) if item.get("scope") == "global"]
    if global_checks or contract.get("global_blockers"):
        lines = ["Current blocker: " + str(code).replace("_", " ")
                 for code in contract.get("global_blockers", [])]
        lines += ["Required: " + item["evidence_required"] for item in global_checks]
        result.append(section("Required before any new trade", list(dict.fromkeys(lines)),
                              group="action", kind="inactive"))
    held = {row["ticker"]: row for row in decision.get("held_positions", [])}
    incomplete_held = [row for row in rows if row["ticker"] in held
                       and row["decision"] in {"BLOCKED", "NO_ACTION"}]
    for row in incomplete_held:
        incomplete = row["decision"] == "BLOCKED"
        result.append(section(("Holding decision incomplete — " if incomplete else "No additional action — ")
            + row["ticker"], action_lines(row), group="action", kind="inactive",
            headline="No expired order is renewed" if incomplete else "0 new shares · current conclusion retained"))

    from delivery_followthrough import continuation_lines
    continuation = continuation_lines(decision.get("delivery_followthrough", {}))
    if continuation:
        result.append(section("Earlier instructions — reconcile before replacing", continuation,
                              group="action", kind="inactive"))

    entries = current_priorities(decision)
    if entries:
        review = decision["analyst_priority_review"]
        for rank, entry in enumerate(entries, 1):
            result.append(section(f"{rank}. {entry['ticker']} — why it deserves attention", [
                "Analyst judgment: " + entry["reason"],
                "Decisive next step: " + entry["next_step"],
                f"Reviewed {review.get('reviewed_at')}; valid through {review.get('next_review_at')}.",
                "Research priority is not a cleared buy or a prediction of high returns.",
            ], group="attention", sources=[s.get("source_url", "") for s in entry.get("sources", [])
                                           if str(s.get("source_url", "")).startswith("https://")]))
    else:
        result.append(section("Opportunity shortlist", [
            "No current source-bound analyst shortlist is available. The analyst must complete the selection; a screen or unfinished queue is not a high-potential recommendation.",
        ], group="attention"))

    held_events = held_earnings_card(decision)
    if held_events:
        result.append(held_events)

    holds = [row for row in rows if row["decision"] == "HOLD" and not row.get("order_draft")]
    if holds:
        positions = "; ".join(f"{row['ticker']} {held[row['ticker']].get('current_shares', 'unverified')} recorded shares"
                              for row in holds if row["ticker"] in held)
        lines = ["These existing holdings are unchanged: " + positions
                 + ". For these holdings only: add 0 / sell 0. Separate action cards govern any other ticker."]
        plans = {p["ticker"]: p for p in decision.get("plan_continuity", {}).get("plans", [])}
        for row in holds:
            plan = plans.get(row["ticker"], {})
            lines.append(f"{row['ticker']}: review {row.get('review_at') or plan.get('review_at') or 'unverified'}; "
                         f"plan validity ends {plan.get('valid_until') or 'unverified'}.")
            if row.get("reassessment_rule"):
                lines.append(row["ticker"] + " — change this decision if: " + row["reassessment_rule"])
        result.append(section("Existing holdings — one summary", lines))

    counts = Counter(row["decision"] for row in rows)
    cash_lines = [f"Recorded planning cash: ${contract['planning_cash']:.2f}; mandatory reserve ${contract['mandatory_reserve']:.2f}. "
                  "Unallocated cash is not a recommendation to retain that percentage.",
                  f"Candidate outcomes: {counts['BLOCKED']} need evidence or an admitted current plan; "
                  f"{counts['NO_ACTION']} have no eligible action. These states are distinct; neither is a buy list.",
                  "Full company cases, all candidate outcomes, sources and research work remain on the dashboard/local report."]
    authority = contract.get("account_authority", {})
    if authority.get("local_planning_enabled"):
        cash_lines.append("Owner-approved local records govern these conditional drafts.")
        cash_lines.extend(authority.get("execution_checks", []))
    result.append(section("Cash and supporting information", cash_lines))
    return result


def intraday_card(decision):
    """Keep dated marks and actual risk flags, omitting untriggered plan copies."""
    from email_brief import intraday_risk_card
    full = intraday_risk_card(decision)
    if full is None:
        return None
    report = decision["intraday_portfolio_risk"]
    lines = full["body"].splitlines()
    prefixes = ("Observation status:", "Prices as of", "Reference close:",
                "Portfolio marked value:", "Price-only change:", "A complete current portfolio",
                "Marked allocation:", "Risk reassessment:", "Unverified dependency:")
    compact = [line for line in lines if line.startswith(prefixes)]
    for condition in report.get("plan_conditions", []):
        if isinstance(condition, dict) and condition.get("status") in {"triggered", "breached", "requires_reassessment"}:
            compact.append("Existing plan condition: " + condition.get("ticker", "Portfolio") + " — "
                           + str(condition.get("condition", condition.get("description", "unverified")))
                           + " (" + condition["status"].replace("_", " ") + ").")
    compact.append("Exact immutable observation, individual marks and unchanged plan conditions remain on the dashboard/local report. Price monitoring alone creates no new instruction or email.")
    return section(full["title"], compact)
