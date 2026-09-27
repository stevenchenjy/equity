"""Brief English cards for the maintained workflow, without raw diagnostics."""
from __future__ import annotations
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
    terminal=[]
    for row in orders.get('orders',[]):
        status=row.get('status','unknown')
        if status in {'filled','cancelled','canceled','expired','rejected'}:
            terminal.append(f"{row.get('ticker')} {status}")
            continue
        label={'open':'open in snapshot','pending':'pending in snapshot','partial_fill':'partially filled in snapshot'}.get(status,'unconfirmed')
        order_lines.append(f"{row.get('ticker')}: recorded {row.get('side','order')} {quantity(row.get('quantity'))}; remaining {quantity(row.get('remaining_quantity'))}; "
                           f"limit {price(row.get('limit_price'))}; {row.get('time_in_force','unconfirmed')} — {label}.")
    if terminal:
        order_lines.append("Historical terminal records: " + "; ".join(terminal) + ". These are not new instructions.")
    order_lines.append("Replacement: confirm cancellation and available shares first. A target limit does not protect against a decline; no fill means exposure remains.")
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
