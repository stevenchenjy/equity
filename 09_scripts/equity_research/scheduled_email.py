"""Brief English cards for the maintained workflow, without raw diagnostics."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from work_queue_reporting import cash_lines as work_cash_lines, research_lines as work_research_lines


def eligible_core_tranche(decision: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    """A same-session, exact core review that can be displayed and continued.

    This is a conditional human draft, never execution authority.  An ordinary
    optimistic screen row cannot acquire an order side through presentation.
    """
    from investment_plans import regular_close

    ticker = row.get("ticker")
    if (decision.get("decision_code") != "action_review_candidate"
            or ticker not in decision.get("eligible_new_position_review_candidates", [])
            or row.get("action") != "core_allocation_tranche_review"
            or row.get("human_confirmation_required") != "yes"
            or row.get("valuation_applicability") != "not_applicable_broad_market_etf"
            or row.get("gate_blockers") or row.get("workflow_global_blockers")
            or row.get("workflow_ticker_blockers")
            or decision.get("account_conflicts")
            or decision.get("account", {}).get("cash_basis") != "owner_recorded"
            or decision.get("plan_continuity", {}).get("block_new_capital") is True
            or decision.get("plan_continuity", {}).get("global_blockers")
            or decision.get("workflow_integrity", {}).get("global_blockers")
            or ticker in decision.get("workflow_integrity", {}).get("blocked_tickers", [])
            or ticker in decision.get("workflow_integrity", {}).get("ticker_blockers", {})
            or not all(decision.get(k, {}).get("passed") is True for k in
                       ("market_gate", "evidence_gate", "fundamental_gate"))
            or decision.get("market_gate", {}).get("bar_state") != "complete_close"):
        return None
    try:
        generated = datetime.fromisoformat(decision["generated_at"])
        session = decision["cycle_date"]
        qty = Decimal(str(row["suggested_whole_shares"]))
        cap = Decimal(str(row["maximum_review_price"]))
        planning_cash = Decimal(str(decision["account"]["cash_available"]))
        held = next(p for p in decision["held_positions"] if p["ticker"] == ticker)
        held_before = Decimal(str(held["current_shares"]))
        maintained = next(p for p in decision["plan_continuity"]["plans"] if p["ticker"] == ticker)
        review = datetime.fromisoformat(maintained["review_at"])
        if (generated.tzinfo is None or generated.date().isoformat() != session
                or generated >= regular_close(session) or review.tzinfo is None
                or review <= generated or maintained.get("status") != "maintained"
                or maintained.get("role") != "broad_core"
                or Decimal(str(maintained.get("current_shares", held_before))) != held_before
                or qty <= 0 or qty != qty.to_integral_value() or cap <= 0
                or not cap.is_finite() or not qty.is_finite()
                or not planning_cash.is_finite() or planning_cash < qty * cap
                or held_before < 0 or held_before != held_before.to_integral_value()
                or int(row.get("stability_distinct_closes", 0)) < int(row.get("required_distinct_closes", 2))):
            return None
    except (KeyError, StopIteration, TypeError, ValueError, InvalidOperation):
        return None
    return {"ticker": ticker, "quantity": int(qty), "max_price": str(cap),
            "session_date": session, "review_at": maintained["review_at"],
            "held_before": int(held_before)}


def core_tranche_line(draft: dict[str, Any]) -> str:
    from email_brief import money, shares
    unit = "share" if draft["quantity"] == 1 else "shares"
    return (f"Core conditional draft — {draft['ticker']}: buy {shares(draft['quantity'])} additional {unit}; "
            f"LIMIT; max {money(draft['max_price'])}; DAY; session {draft['session_date']}; "
            f"review {draft['review_at']}.")


def owner_check_window(decision: dict[str, Any]) -> str:
    try:
        hour = datetime.fromisoformat(decision["generated_at"]).hour
        return "14:45–15:20 ET" if hour >= 11 else "09:45–10:45 or 14:45–15:20 ET"
    except (KeyError, TypeError, ValueError):
        return "the next market-hours check"


def core_tranche_steps(draft: dict[str, Any], window: str) -> list[str]:
    from email_brief import money
    cap = money(draft["max_price"])
    unit = "share" if draft["held_before"] == 1 else "shares"
    return [
        f"When: at your {window} check on {draft['session_date']}, while the regular market is open.",
        f"Check first: current quote at or below {cap}; broker confirms the recorded {draft['held_before']} {unit}, "
        "no conflicting order, and buying power and settlement rules cover the purchase plus costs. "
        "Also check for material new evidence against the core case.",
        f"Then: if every check passes, you may decide whether to submit the {draft['quantity']}-share "
        f"DAY LIMIT buy at no more than {cap}. Otherwise skip; do not raise the cap or reuse this draft "
        f"after {draft['session_date']}. Review the resulting core exposure by {draft['review_at']}. "
        "This system has submitted no order.",
    ]


def cards(decision: dict[str, Any], view: dict[str, Any]) -> list[dict[str, Any]]:
    from email_brief import money, shares, _safe_source, _RESEARCH_HOSTS

    def price(value):
        return money(value) if value not in (None, "") and money(value).startswith("$") else "unconfirmed"

    def quantity(value):
        return shares(value) if value not in (None, "") else "unconfirmed"

    def section(title, lines, sources=()):
        return {"title": title, "body": "\n".join(lines), "sources": list(sources)}

    continuity = decision.get("plan_continuity", {})
    plans = continuity.get("plans", [])
    account = decision.get("account", {})
    gates = all(decision.get(k, {}).get("passed") is True for k in ("market_gate", "evidence_gate", "fundamental_gate"))
    blocked = bool(decision.get("account_conflicts")) or not gates
    estimated = account.get("cash_basis") in {"ledger_estimate", "owner_assumption", "owner_assumed", "planning_assumption"}
    allowed = {p['ticker'] for p in view['plans']}
    from delivery_followthrough import continuation_lines, continuation_requires_reconciliation
    followthrough = decision.get('delivery_followthrough', {})
    reconcile_delivery = continuation_requires_reconciliation(followthrough)
    check_window = owner_check_window(decision)
    if reconcile_delivery:
        # Delivery continuation cannot spend cash or sell shares twice while
        # canonical records still describe the pre-assumption portfolio.
        allowed = set()
    summary = ["This brief uses the maintained research and plan records with the latest validated close; it is not a live broker view."]
    if reconcile_delivery:
        summary.append("Follow-up: earlier instructions require reconciliation. Additional portfolio-changing drafts are withheld from potentially pre-execution records until actual holdings, fills, cash and orders are reconciled; no new order quantity is supplied here.")
        if followthrough.get('status') == 'prior_action_not_structured':
            names = followthrough.get('unstructured_candidate_tickers', [])
            if names:
                summary.append(f"At your {check_window} check: verify actual " + ", ".join(names)
                    + " shares, fills and all open orders. The earlier up-to candidate did not specify a completed purchase; "
                      "do not repeat it or assume a fill. Reassess a new buy only after those facts are recorded.")
    elif blocked:
        summary.append("Action: resolve the account or data verification problem. New trade drafts are withheld.")
    elif decision.get("fundamental_gate", {}).get("weakening_tickers"):
        summary.append("Action: reassess the business evidence for " + ", ".join(decision['fundamental_gate']['weakening_tickers']) + ". No automatic exit.")
        if allowed:
            summary.append("Separately eligible proposals are listed below for review; none has been submitted.")
    elif allowed:
        core = [eligible_core_tranche(decision, row) for row in decision.get('watch_candidates', [])
                if row.get('ticker') in allowed]
        core = [draft for draft in core if draft]
        if core:
            summary.append("Today's conditional decision: consider the exact core draft below; otherwise skip. No order has been submitted.")
            for draft in core:
                summary.append(core_tranche_line(draft))
                summary.extend(core_tranche_steps(draft, check_window))
        else:
            summary.append("Action: review the eligible proposals below; no order has been submitted.")
    else:
        summary.append("New trades: zero newly eligible buy or sell proposals. Existing exit/protection plans remain separate.")
    if reconcile_delivery and blocked:
        summary.append("Account or data verification is also unresolved. These independent blockers remain in force.")
    unresolved = [p['ticker'] for p in plans if p.get('status') != 'maintained' or p.get('blockers')]
    if unresolved:
        summary.append(f"During your {check_window} account check, reconcile "
                       + ", ".join(unresolved) + " holdings, fills, available shares and orders. "
                       "Do not reuse expired sell or protection prices.")
    sections = [section("What needs your attention", summary)]

    states = {'maintained':'plan retained', 'review_due':'review due; no fill confirmed',
              'expired_pending_verification':'dated plan expired; outcome unconfirmed',
              'time_exit_due_pending_verification':'exit deadline passed; outcome unconfirmed',
              'completed_observed':'completion observed', 'position_changed_pending_verification':'share count changed; reconcile',
              'position_absent_pending_verification':'position absent; verify the outcome'}
    actions = {'hold':'retain holding', 'protect_review':'protection review', 'exit_review':'exit review',
               'trim_review':'trim review', 'watch':'watch'}
    held = {r['ticker']:r for r in decision.get('held_positions', [])}
    lines = []
    if reconcile_delivery:
        lines.append("Recorded holdings below are the last maintained account observations. They are not adjusted by the separate assumed-execution scenario.")
    for p in plans:
        ticker=p['ticker']; row=held.get(ticker,{})
        intent = actions.get(p.get('action'), 'reconcile the prior plan')
        if p.get('action') == 'reconcile_plan':
            draft = p.get('historical_order_draft') or {}
            intent = ('previous protection review' if draft.get('type') == 'STOP' else
                      'previous sell review' if draft.get('side') == 'sell' else
                      'previous hold/watch plan' if not p.get('proposed_change_shares') else 'reconcile the prior plan')
        lines.append(f"{ticker}: {quantity(row.get('current_shares', p.get('current_shares')))} held; reference {price(row.get('current_price'))}. "
                     f"Recorded intent: {intent}; {states.get(p.get('status'), 'verification required')}.")
        deadline = p.get('time_exit_at') or p.get('review_at')
        if deadline:
            lines.append(f"{ticker} original {'exit/review' if p.get('time_exit_at') else 'review'} time: {deadline}.")
    for ticker,row in held.items():
        if ticker not in {p['ticker'] for p in plans}:
            lines.append(f"{ticker}: {quantity(row.get('current_shares'))} held; reference {price(row.get('current_price'))}; maintained plan missing, reconcile first.")
    lines.append("Expired prices and DAY drafts are not renewed. A passed deadline does not prove a sale or cancel the need to reconcile.")
    sections.append(section("Holdings and retained plans", lines))

    orders=decision.get('tactical_review',{}).get('open_orders',{})
    order_lines=continuation_lines(followthrough)
    order_lines.append(f"Order snapshot: {orders.get('as_of') or 'unavailable'}; current broker status must be rechecked.")
    observation = orders.get('current_inventory_observation', {})
    no_active_orders_observed = (isinstance(observation, dict) and observation.get('complete') is True
            and observation.get('orders_shown') == [] and observation.get('as_of'))
    if no_active_orders_observed:
        order_lines.append(f"Current active orders: none observed at {observation['as_of']}. "
                           "Recheck before placing an order; terminal rows and older tickets remain historical records.")
    terminal=[]
    for row in orders.get('orders',[]):
        status=row.get('status','unknown')
        if status in {'filled','cancelled','canceled','expired','rejected'}:
            terminal.append(f"{row.get('ticker')} {status}")
            continue
        if row.get('record_scope') == 'unresolved_historical_reservation':
            order_lines.append(f"{row.get('ticker')}: unresolved historical {row.get('side','order')} record; "
                               f"original quantity {quantity(row.get('quantity'))}; limit {price(row.get('limit_price'))}; "
                               f"{row.get('time_in_force','unconfirmed')}; last verified {row.get('last_verified_at') or 'unavailable'}. "
                               f"Local conservative reservation: {quantity(row.get('remaining_quantity'))} shares; "
                               "this is not a current broker-reported pending order or remaining quantity. Historical terminal status still needs evidence.")
            if row.get('current_inventory_presence') == 'not_shown_in_current_no_orders_page':
                order_lines.append(f"{row.get('ticker')}: not shown in the no-orders page observed at {orders.get('as_of') or 'an unverified time'}. "
                                   "That observation does not establish the old ticket's exact terminal status.")
            continue
        if (row.get('current_status_verified') is False
                or row.get('review_status') in {'expired_pending_verification','unknown_pending_verification'}):
            order_lines.append(f"{row.get('ticker')}: prior {row.get('side','order')} {quantity(row.get('quantity'))}; "
                               f"limit {price(row.get('limit_price'))}; {row.get('time_in_force','unconfirmed')}. "
                               "Current status and remaining quantity are unverified; the recorded pending state is historical.")
            continue
        label={'open':'open in snapshot','pending':'pending in snapshot','partial_fill':'partially filled in snapshot'}.get(status,'unconfirmed')
        order_lines.append(f"{row.get('ticker')}: recorded {row.get('side','order')} {quantity(row.get('quantity'))}; remaining {quantity(row.get('remaining_quantity'))}; "
                           f"limit {price(row.get('limit_price'))}; {row.get('time_in_force','unconfirmed')} — {label}.")
    if terminal:
        order_lines.append("Historical terminal records: " + "; ".join(terminal) + ". These are not new instructions.")
    if any(row.get('status') in {'open', 'pending', 'partial_fill', 'partially_filled'}
           for row in orders.get('orders', []) if isinstance(row, dict)):
        order_lines.append("Replacement: confirm cancellation and available shares first. A target limit does not protect against a decline; no fill means exposure remains.")
    # Maintained analyst plans have their own source-bound authority. The
    # workflow intentionally clears baseline held-position eligibility; this
    # display must neither hide a valid retained draft nor renew an expired one.
    for plan in plans:
        if (continuity.get('schema_version') != 'equity_plan_continuity_v1'
                or plan.get('status') != 'maintained'
                or plan.get('action') not in {'protect_review', 'exit_review', 'trim_review'}
                or plan.get('automatic_action_allowed') is not False
                or plan.get('validity') != 'research_only_requires_current_verification'
                or not re.fullmatch(r'[0-9a-f]{64}', str(plan.get('record_hash', '')))):
            continue
        if reconcile_delivery:
            order_lines.append(f"{plan['ticker']}: retained {plan.get('action', 'plan').replace('_', ' ')} context remains recorded. This follow-up does not repeat an additive order or cancel earlier protection; reconcile before any replacement.")
            continue
        draft = plan.get('historical_order_draft')
        try:
            from investment_plans import regular_close
            def positive(value):
                result = Decimal(str(value))
                if not result.is_finite() or result <= 0:
                    raise ValueError('invalid_draft_value')
                return result
            if (not isinstance(draft, dict) or draft.get('side') != 'sell'
                    or draft.get('type') not in {'STOP', 'LIMIT', 'MARKETABLE_LIMIT'}
                    or draft.get('time_in_force') != 'DAY'):
                continue
            qty = positive(draft['quantity'])
            held_qty = positive(held.get(plan['ticker'], {}).get('current_shares', plan.get('current_shares')))
            if qty != qty.to_integral_value() or qty != positive(plan['proposed_change_shares']) or qty > held_qty:
                continue
            generated = datetime.fromisoformat(decision['generated_at'])
            review = datetime.fromisoformat(plan['review_at'])
            if (generated.tzinfo is None or review.tzinfo is None
                    or generated >= review or generated >= regular_close(draft['session_date'])):
                continue
            if plan.get('time_exit_at'):
                exit_at = datetime.fromisoformat(plan['time_exit_at'])
                if exit_at.tzinfo is None or generated >= exit_at:
                    continue
            positive(draft['stop_price'] if draft['type'] == 'STOP' else draft['limit_price'])
            for field in ('limit_price', 'stop_price'):
                if draft.get(field) is not None:
                    positive(draft[field])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        levels = '; '.join(f"{label} {price(draft[field])}" for field, label in
                           (('limit_price', 'limit'), ('stop_price', 'stop')) if draft.get(field) is not None)
        order_lines.append(f"Maintained conditional plan — {plan['ticker']}: sell {quantity(qty)} shares; "
            f"{draft['type']}; {levels}; {draft['time_in_force']}; session {draft['session_date']}; "
            f"review {plan['review_at']}" + (f"; exit/review {plan['time_exit_at']}" if plan.get('time_exit_at') else '')
            + ". Recorded analyst draft, not submitted; this does not create new canonical trade eligibility. "
              "Verify a fresh quote, available shares and current orders before any manual action.")
        purpose = plan.get('purpose') if isinstance(plan.get('purpose'), dict) else {}
        for field, label in (('entry_validity', 'Validity'), ('failure_condition', 'Failure condition'), ('exit_rule', 'Exit rule')):
            if isinstance(purpose.get(field), str) and purpose[field].strip():
                order_lines.append(f"{plan['ticker']} {label.lower()}: {purpose[field]}")
        blocker_labels = {'fresh_quote_and_available_shares_required': 'fresh quote and available shares',
            'order_snapshot_requires_recheck': 'current order inventory recheck',
            'cash_not_confirmed_for_tactical_execution': 'cash confirmation for tactical execution',
            'existing_tactical_risk_unconfirmed': 'existing tactical risk confirmation',
            'sell_order_terminal_status_unverified': 'historical sell-ticket terminal evidence',
            'outstanding_sell_reserves_current_shares': 'shares reserved by the unresolved sell record'}
        known = sorted(set(plan.get('blockers', []) + continuity.get('global_blockers', [])))
        if known:
            order_lines.append(f"{plan['ticker']} outstanding checks: " + '; '.join(
                blocker_labels.get(code, str(code).replace('_', ' ')) for code in known) + ".")
    # Reuse the existing presentation gate; never expose rejected/stale positive
    # quantities just because a lower-level screen has an optimistic number.
    for ticker in sorted(allowed):
        candidate_origin = ticker in decision.get('eligible_new_position_review_candidates', [])
        source_rows = decision.get('watch_candidates', []) if candidate_origin else decision.get('held_positions', [])
        row=next((r for r in source_rows if r.get('ticker')==ticker),{})
        qty=row.get('suggested_whole_shares') if candidate_origin else row.get('whole_shares_to_change')
        core_draft = eligible_core_tranche(decision, row) if candidate_origin else None
        if core_draft:
            order_lines.append(f"{ticker}: the conditional buy review and today's exact checks are at the top of this brief; "
                               "do not place a second order from this section.")
        else:
            order_lines.append(f"{ticker} research candidate: up to {quantity(qty)} shares at a dated review ceiling of "
                f"{price(row.get('maximum_review_price'))}. A complete same-session direction and conditions are not recorded here; "
                "do not place an order from this summary. A separately validated tactical draft, if present below, has its own conditions.")
    for draft in decision.get('tactical_review',{}).get('drafts',[]):
        if not reconcile_delivery and not blocked and not estimated and draft.get('eligible') is True and draft.get('ticker') in allowed:
            order_lines.append(f"{draft['ticker']} tactical draft: " + ("buy " if "delivery_followthrough" in decision else "") + f"{quantity(draft.get('quantity'))} shares; entry/max {price(draft.get('entry_price'))}, "
                 f"stop {price(draft.get('stop_price'))}, target {price(draft.get('target_price'))}, planned risk {price(draft.get('planned_risk_usd'))}; "
                 f"{draft.get('order_type')}, {draft.get('time_in_force')}, session {draft.get('session_date')}; exit/review {draft.get('time_exit_session')}. "
                 "Only after its entry trigger and current account checks pass. Gaps can exceed planned loss.")
    sections.append(section("Orders and proposals", order_lines))

    cash_lines=[f"{'Planning scenario' if estimated else 'Local account record'}: total {price(account.get('account_total_value'))}; "
                f"cash {price(account.get('cash_available'))}; reserve {price(account.get('cash_reserved'))}.",
                "These local figures do not establish current broker buying power or settled cash. Planning cash is not a confirmed deposit."]
    cash_lines.extend(work_cash_lines(decision))
    sections.append(section("Cash",cash_lines))

    watch=[r['ticker'] for r in decision.get('watch_candidates',[]) if r.get('ticker') not in held and r.get('ticker') not in allowed]
    discovery=decision.get('independent_market_discovery',{})
    research=[]
    research.extend(work_research_lines(decision))
    if watch:
        research.append("Nonheld watch: " + ", ".join(watch) + ". Zero new shares; evidence, valuation, sizing or eligibility remains incomplete.")
    for group,label in [('top_stocks','Stock screen'),('top_etfs','ETF screen')]:
        names=[r['ticker'] for r in discovery.get(group,[])[:3]]
        if names: research.append(label+": "+', '.join(names)+". Research queue only; no buy orders.")
    research.append("Discovery: " + ("completed price/liquidity screen, not full-market fundamental research." if discovery.get('complete') is True else "incomplete or unavailable; do not substitute the watchlist for a market-wide scan."))
    views=decision.get('long_horizon_research',{}).get('views',{})
    pending=sum(len(v.get('news_review',{}).get('pending_events',[])) for v in views.values())
    incomplete=[t for t,v in views.items() if v.get('valuation_readiness')!='reviewed_scenarios']
    if pending: research.append(f"Unresolved evidence: {pending} issuer announcements still need impact review.")
    if incomplete: research.append("Valuation incomplete: "+', '.join(sorted(incomplete))+". Financial checks do not establish an attractive price.")
    coverage=decision.get('evidence_coverage',{}).get('official_news',{})
    if coverage and coverage.get('required_coverage_complete') is not True:
        research.append("Official news coverage is incomplete; missing coverage is not evidence of no news.")
    research.append("Recheck: after verified company evidence, valuation or a maintained plan changes. Ranking movement alone is not a new investment conclusion.")
    links=[]
    for event in decision.get('material_events',[]):
        research.append(f"New filing for review: {event.get('ticker','unknown')}, {event.get('form','filing')}, disclosed {event.get('filing_date','unconfirmed')}.")
        url=_safe_source(event.get('source_url'),_RESEARCH_HOSTS)
        if url: links.append(url)
    sections.append(section("Research queue and evidence", research,links))
    sections.append(section("Rules and next step",[
        "Before entry: define catalyst, trigger/max price, invalidation, target, share count and exit date; keep core and tactical holdings separate.",
        "Tactical limits: planned loss at most 0.5% per ordinary trade, 0.25% for event exposure, 2% combined; initial exposure at most 5% per name. Use actual account value; gaps can exceed limits.",
        "Require at least 2:1 plausible reward/risk; review within 3–5 sessions. No automatic buybacks, averaging down or conversion of a failed short trade into a long-term holding.",
        ("Next: resolve the outstanding plan/order checks above. Full diagnostics remain in the local research report; "
         + ("this system has placed no trades. Your actual execution status comes from account records, not this report."
            if "delivery_followthrough" in decision else "no trades have been placed."))]))
    return sections
