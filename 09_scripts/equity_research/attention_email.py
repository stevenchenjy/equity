"""Compact email projection of admitted decisions; no research or eligibility logic.

Full cases, every candidate outcome and collection diagnostics remain in the
capital report/dashboard. This projection never ranks an unreviewed screen as
an investment opportunity or turns a review ceiling into an order price.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from capital_decision import validate
from capital_presentation import action_lines, optional_rotation_cards


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
