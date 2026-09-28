"""Brief English cards for the maintained workflow, without raw diagnostics."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from work_queue_reporting import cash_lines as work_cash_lines, research_lines as work_research_lines


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
    summary = ["Automatic status update: this is not a fresh analyst review or a replacement for your maintained plan."]
    if blocked:
        summary.append("Action: resolve the account or data verification problem. New trade drafts are withheld.")
    elif decision.get("fundamental_gate", {}).get("weakening_tickers"):
        summary.append("Action: reassess the business evidence for " + ", ".join(decision['fundamental_gate']['weakening_tickers']) + ". No automatic exit.")
        if allowed:
            summary.append("Separately eligible proposals are listed below for review; none has been submitted.")
    elif allowed:
        summary.append("Action: review the eligible proposals below; none has been submitted.")
    else:
        summary.append("New trades: zero newly eligible buy or sell proposals. Existing exit/protection plans remain separate.")
    unresolved = [p['ticker'] for p in plans if p.get('status') != 'maintained' or p.get('blockers')]
    if unresolved:
        summary.append("Needs confirmation: " + ", ".join(unresolved) + ". Check broker holdings, fills and outstanding orders before acting.")
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
    order_lines=[f"Order snapshot: {orders.get('as_of') or 'unavailable'}; current broker status must be rechecked."]
    observation = orders.get('current_inventory_observation', {})
    if (isinstance(observation, dict) and observation.get('complete') is True
            and observation.get('orders_shown') == [] and observation.get('as_of')):
        order_lines.append(f"Broker page observation at {observation['as_of']}: no orders shown then. "
                           "Recheck before acting; this does not establish older tickets' terminal outcomes.")
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
        order_lines.append(f"{ticker} eligible research proposal: change up to {quantity(qty)} shares; action {actions.get(row.get('action'), 'entry review' if ticker not in held else 'position review')}; "
                           f"maximum entry/review price {price(row.get('maximum_review_price'))}. Verify direction, current quote, funds and complete plan before any order; not submitted.")
    for draft in decision.get('tactical_review',{}).get('drafts',[]):
        if not blocked and not estimated and draft.get('eligible') is True and draft.get('ticker') in allowed:
            order_lines.append(f"{draft['ticker']} tactical draft: {quantity(draft.get('quantity'))} shares; entry/max {price(draft.get('entry_price'))}, "
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
        "Next: resolve the outstanding plan/order checks above. Full diagnostics remain in the local research report; no trades have been placed."]))
    return sections
