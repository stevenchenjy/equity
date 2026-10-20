"""Action-first presentation of the admitted capital contract; no sizing logic."""
from __future__ import annotations
from capital_decision import BUY, validate
from datetime import datetime
from decimal import Decimal, InvalidOperation


def action_lines(row):
    p=row.get('order_draft')
    if not p:
        return [*row.get('reasons',[]), *[f"Required ({d['category']}): {d['evidence_required']} [{d['code']}]" for d in row.get('dependencies',[])]]
    selling=p.get('side')=='sell'
    order_line=(f"Exit: SELL {p['entry_order_type']} {'trigger ≤' if p['entry_order_type']=='STOP' else '≥'} ${p['exit_price']:.2f} · {p['time_in_force']} · {row['shares']} shares" if selling else f"Entry: {p['entry_order_type']} ≤ ${p['entry_limit']:.2f} · {p['time_in_force']} · {row['shares']} shares")
    lines=[order_line,
           f"When: {p['entry_window']['starts_at']} through {p['entry_window']['ends_at']}",
           f"Trigger: {p['trigger_rule']}",
           f"Capital: approximately ${row['estimated_notional']:.2f}; weight {p['portfolio_weight_before']:.2f}% → {p['portfolio_weight_after']:.2f}%",
           f"Cash: ${p['cash_before']:.2f} → estimated ${p['estimated_cash_after']:.2f} before fees"]
    if selling:
        lines.append(f"Remaining risk reference: ${p['planned_total_loss']:.2f}; a sell limit gives no downside protection and a stop can gap. Proceeds are conditional, not confirmed cash.")
    elif p['risk_model']=='observed_price_invalidation':
        lines.append(f"Invalidate: ${p['invalidation_price']:.2f}; planned loss ${p['planned_total_loss']:.2f} ({p['planned_account_risk_pct']:.2f}%); gaps can exceed it.")
        lines.append(f"Initial target/review: ${p['initial_reassessment_price']:.2f}")
    else:
        lines.append(f"Risk: no price stop is prescribed for this core purpose; full ${p['planned_total_loss']:.2f} principal ({p['planned_account_risk_pct']:.2f}%) is exposed. This is not a 0.5% tactical loss plan.")
    lines.extend([f"Invalidation rule: {p['invalidation_rule']}",f"Reassessment: {p['reassessment_rule']}",*[f"Cancel: {c}" for c in p['cancel_conditions']],f"Reason: {row['thesis_summary']}",f"Costs: {p['cost_assumption']}"])
    return lines


def optional_rotation_cards(decision):
    """Prominent dated owner review; never manufacture capital order drafts."""
    current = datetime.fromisoformat(decision['generated_at'])
    c = decision['capital_decision']
    policy = decision.get('allocation_policy', {})
    core = set(policy.get('core_tickers', []))
    held = {row['ticker']: row for row in decision.get('held_positions', [])}
    result = []
    for plan in decision.get('plan_continuity', {}).get('plans', []):
        review = plan.get('conditional_rotation_review')
        if (not review or plan.get('status') != 'maintained' or plan.get('blockers')
                or decision.get('plan_continuity', {}).get('global_blockers')
                or decision.get('workflow_integrity', {}).get('global_blockers')):
            continue
        buy, sell = review['buy'], review['sell']
        ends = datetime.fromisoformat(review['ends_at'])
        if (review.get('optional') is not True or review.get('human_execution_only') is not True
                or review.get('sequence') != 'buy_fully_then_sell' or current >= ends
                or not {buy['ticker'], sell['ticker']} <= core
                or policy.get('core_minimum_pct') != review['minimum_combined_core_pct']):
            continue
        assessment = review.get('assessment')
        if assessment:
            reason = assessment['reason'] if assessment['decision'] != 'proceed' else ''
            session = decision.get('market_gate', {}).get('expected_market_session')
            if not reason:
                from daily_common import last_completed_market_session
                if (assessment['market_session'] != session
                        or session != last_completed_market_session(current).isoformat()
                        or decision.get('market_gate', {}).get('passed') is not True
                        or assessment.get('market_snapshot', {}).get('sha256') != c.get('source_bindings', {}).get(
                            '03_source_data/equity_research/market_data_snapshot.csv')):
                    reason = 'The latest required validated close has not received a current rotation assessment.'
            if not reason:
                prices = assessment.get('prices', {})
                try:
                    q, s = Decimal(str(prices[buy['ticker']])), Decimal(str(prices[sell['ticker']]))
                    if not q.is_finite() or not s.is_finite() or min(q, s) <= 0:
                        raise ValueError('price_unverified')
                    if q > Decimal(str(buy['maximum_price'])) or s < Decimal(str(sell['minimum_price'])):
                        reason = 'The latest validated closing prices do not meet both unchanged price limits. Do not chase the rotation.'
                except (KeyError, ValueError, InvalidOperation):
                    reason = 'A coherent validated price pair is unavailable; do not substitute old or unverified quotes.'
            if reason:
                result.append(dict(title='Skip the rotation', group='action', kind='inactive',
                    headline='No QQQM purchase or SPY sale is recommended by this review',
                    body='Reason: '+reason+'\n'
                         +f"Limits remain fixed: QQQM buy maximum ${float(buy['maximum_price']):.2f}; SPY sell minimum ${float(sell['minimum_price']):.2f}. Do not raise the buy limit or lower the sell floor.\n"
                         +'Next step: The scheduled morning analyst must reassess the latest validated close and the sequencing/concentration risk before any positive action cards return.\n'
                         +'Holdings: Keep the locally recorded holdings unless you report actual changes. No order or fill is inferred.', sources=[]))
                continue
        try:
            unchanged = all(Decimal(str(held.get(ticker, {}).get('current_shares', 0))) == Decimal(str(qty))
                            for ticker, qty in review['expected_holdings'].items())
            available = min(Decimal(str(c['planning_cash'])) - Decimal(str(c['mandatory_reserve'])),
                            Decimal(str(c['estimated_uncommitted_cash_after'])))
            cost = Decimal(str(buy['quantity'])) * Decimal(str(buy['maximum_price']))
            if not unchanged or not available.is_finite() or available < cost:
                continue
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue
        from investment_plans import stamp
        start, end = stamp(review['starts_at']), stamp(review['ends_at'])
        window = f"{start:%Y-%m-%d %H:%M}–{end:%H:%M} ET"
        result.extend([
            dict(title=f"OPTIONAL ROTATION · BUY {buy['quantity']} shares {buy['ticker']}", group='action', kind='buy',
                headline=f"Buy first · LIMIT ≤ ${float(buy['maximum_price']):.2f} · Skip unfavorable conditions",
                body=f"Window: {window}. Decide only within this window; this system has created or submitted no order.\n"
                     + f"Price: At most ${float(buy['maximum_price']):.2f} per share. Do not chase or automatically raise the limit. The {review['reference_close']} close is the historical basis for this proposed limit; check current executable quotes.\n"
                     + f"Sequence: Optional first step: buy {buy['quantity']} shares {buy['ticker']}, at most ${float(cost):.2f} total; LIMIT / DAY. All shares must actually fill before considering the sale. Do not sell {sell['ticker']} after only a partial buy fill.\n"
                     + "Before acting: Required morning market data must pass verification; resolve unrecorded account or order changes, confirm execution funds, and decide whether you want the more concentrated growth-index exposure. Skip the rotation if prices, spreads or volatility feel too aggressive.",
                sources=[]),
            dict(title=f"PAIRED SECOND STEP · SELL {sell['quantity']} share {sell['ticker']}", group='action', kind='sell',
                headline=f"Only after all {buy['quantity']} {buy['ticker']} shares fill · LIMIT ≥ ${float(sell['minimum_price']):.2f}",
                body=f"Price: At least ${float(sell['minimum_price']):.2f} per share; LIMIT / DAY. Both price limits must hold; do not execute the sale independently.\n"
                     + f"Allocation: Recalculate at current prices: combined {sell['ticker']} + {buy['ticker']} must remain at least {review['minimum_combined_core_pct']}% after the pair.\n"
                     + f"Deadline: {end:%Y-%m-%d %H:%M} ET. Manually cancel unfilled orders you will no longer monitor, then reassess; no automatic extension.\n"
                     + f"If the sale does not fill: {review['incomplete_pair_rule']}", sources=[]),
            dict(title='SKIP CONDITIONS · No obligation to complete the rotation', group='action', kind='inactive',
                headline='Keep existing holdings if nothing fills; record only actual fills',
                body='\n'.join(review['skip_conditions'])+'\n'+review['rationale'], sources=[]),
        ])
    return result


def cards(decision, view=None):
    c=decision['capital_decision'];validate(c,current=datetime.fromisoformat(decision['generated_at']))
    result=[]
    rotations=optional_rotation_cards(decision)
    skip_rotation=any(r['title']=='Skip the rotation' for r in rotations)
    actionable=[r for r in c['decisions'] if r['order_draft']]
    result.append(dict(title="TODAY'S ACTION",group='action',kind='buy' if actionable else 'inactive',
                       headline='Skip the rotation' if skip_rotation else 'OPTIONAL CONDITIONAL ROTATION · You may skip' if rotations else 'EXACT CONDITIONAL ORDER DRAFTS' if actionable else 'NO NEW POSITION',
                       body='Do not force the SPY / QQQM pair. Its fixed limits and original deadline remain unchanged.' if skip_rotation else 'Read the paired BUY / SELL conditions first. Skip unfavorable prices or excessive risk. You decide and place any orders yourself.' if rotations else 'Review the complete drafts below, then manually enter any approved order in Chase.' if actionable else
                       'Buy/add 0 new shares in this cycle. The exact reasons and next steps follow.',sources=[]))
    result.extend(rotations)
    for side in ('buy', 'sell'):
        if not rotations and not any(r['order_draft'].get('side') == side for r in actionable):
            result.append(dict(title=side.upper()+' — none', group='action', kind='inactive',
                headline='0 shares · no current order price',
                body='No complete current conditional '+side+' draft passes the required checks. No order is requested by this update.', sources=[]))
    for row in [*actionable,*[r for r in c['decisions'] if r['decision'] in {'REDUCE_REVIEW','EXIT_REVIEW','HOLD'} and not r['order_draft']]]:
        label={'ACTIONABLE_BUY':'BUY','ACTIONABLE_ADD':'ADD','REDUCE_REVIEW':'REDUCE REVIEW','EXIT_REVIEW':'EXIT REVIEW','HOLD':'HOLD'}[row['decision']]
        result.append(dict(title=f"{label} — {row['ticker']}",group='action',kind='buy' if row['decision'] in BUY else 'sell' if 'REVIEW' in row['decision'] else 'inactive',
                           headline=f"{row['shares']} shares · approx. ${row['estimated_notional']:.2f}" if row.get('order_draft') else 'No new order draft',
                           body='\n'.join(action_lines(row)),sources=[]))
    # Global C checks belong to the action decision, without repeating each ticker.
    checks=[d for d in c['dependencies'] if d['scope']=='global']
    if checks:
        tasks={d['category']:d['evidence_required'] for d in checks}
        labels={'A':'System next step','B':'Await public evidence','C':'Your next step before any trade','D':'Analyst next step','E':'Strategy/execution requirement'}
        result.append(dict(title='WHY NO NEW CAPITAL / NEXT STEP',group='action',kind='inactive',headline='',body='\n'.join(labels[k]+': '+v for k,v in tasks.items()),sources=[]))
    escalation=decision.get('capital_deployment_escalation')
    if escalation:
        cash=escalation['cash']
        lines=[escalation['explanation'],
               f"Status: {escalation['status']}; consecutive verified no-buy/add sessions: {escalation['consecutive_no_action_sessions']}; history: {escalation['session_history_reason']}.",
               f"Cash above approved target: ${cash['excess_cash_usd']:.2f}; material review trigger: {cash['material_excess_cash_pct']} percentage points of portfolio value." if cash['excess_cash_usd'] is not None else 'Cash excess is unverified.']
        for route in escalation['routes']:
            nearest=route.get('closest_candidate')
            lines.append(route['label']+': '+(nearest['ticker'] if nearest else 'unavailable')+'; '+route['status']+'.')
            if not nearest:lines.extend('Policy gate: '+code for code in route['blockers'])
            elif nearest['gates']:
                lines.extend(f"{nearest['ticker']} / {g['category']}: {g['code']} — {g['evidence_required']}" for g in nearest['gates'])
        nearest=escalation.get('closest_candidate')
        if nearest:lines.append('Closest to eligibility: '+nearest['ticker']+'; readiness comparison only, subject to every gate above.')
        immediate=[r['ticker'] for r in escalation['research_requests'] if r['urgency']=='immediate']
        lines.append('Immediate priority research: '+(', '.join(immediate) or 'No active escalation request; account/data checks or normal research remain.')+' Queued work is not completed analysis.')
        result.append(dict(title='CAPITAL DEPLOYMENT ESCALATION',group='background',kind='inactive',headline='',body='\n'.join(lines),sources=[]))
    for row in c['decisions']:
        if row['decision'] in {'NO_ACTION','BLOCKED'} and row['ticker'] in {r['ticker'] for r in decision.get('held_positions',[])}:
            result.append(dict(title=f"{row['decision']} — {row['ticker']}",group='action',kind='inactive',headline='0 new shares; no renewed expired order',body='\n'.join(action_lines(row)),sources=[]))
    from delivery_followthrough import continuation_lines
    continuation=continuation_lines(decision.get('delivery_followthrough',{}))
    if continuation:result.append(dict(title='Earlier email — labelled completion scenario',group='background',kind='',body='\n'.join(continuation),sources=[]))
    result.append(dict(title='Cash and research progress',group='background',kind='',body=f"Cash: ${c['planning_cash']:.2f}; mandatory reserve ${c['mandatory_reserve']:.2f}. Planning cash is not broker buying power.\n"+
                        f"Research queue: {decision.get('research_opportunities',{}).get('metrics',{}).get('research_queue_size','unverified')} retained opportunities.\n"+
                        'Automatic objective collectors, valuation recomposition and the source-bound analyst continue working. Successful source collection does not complete an investment case.',sources=[]))
    if 'massive_unadjusted_history_nasdaq_eod_extension' in decision.get('market_gate', {}).get('data_sources', []):
        result.append(dict(title='Market data source', group='background', kind='', sources=[],
            body='Validated Nasdaq backup for the latest completed session, with retained unadjusted Massive history. Complete configured coverage and overlapping closes passed; dated EOD observations, not live execution quotes.'))
    import json
    by_ticker = {r['ticker']: r for r in c['decisions']}
    from company_research_presentation import case_lines
    presented = set()
    for row in c['decisions']:
        case = row.get('research_case')
        if not case: continue
        presented.add(row['ticker'])
        research = decision.get('long_horizon_research', {})
        review = research.get('candidate_views', {}).get(row['ticker'], research.get('views', {}).get(row['ticker'], {})).get('review_record', {})
        result.append(dict(title='公司研究与配置判断 — ' + row['ticker'], group='background', kind='',
            body='\n'.join(case_lines(case, shares=row['shares'], order_side=(row.get('order_draft') or {}).get('side'))),
            sources=[source['url'] for source in review.get('sources', [])
                     if str(source.get('url', '')).startswith('https://')]))
    for watch in decision.get('watch_candidates', []):
        if watch['ticker'] in presented: continue
        if watch.get('valuation_method') != 'admitted_source_bound_company_model':
            continue
        try:
            proof = json.loads(watch.get('company_valuation_admission', '{}'))
            if not proof.get('record_sha256'):
                continue
        except (TypeError, ValueError):
            continue
        row = by_ticker.get(watch['ticker'], {})
        result.append(dict(title='Company valuation — '+watch['ticker'], group='background', kind='', sources=[],
            body=f"Admitted company model v{proof['version']}; horizon: {watch.get('valuation_horizon', 'unverified')}.\n"+
                 'Bear/base/bull scenarios: ' + ' / '.join(f"${float(watch['valuation_'+case+'_price']):.2f}" for case in ('bear','base','bull')) + '; analyst assumptions, not guaranteed prices.\n'+
                 f"At the dated reference close ${watch['current_price']}: base-scenario gap {watch['expected_upside_pct']}%, scenario reward/risk {watch['reward_to_risk_estimate']}.\n"+
                 f"Valuation-only review ceiling: ${watch['maximum_review_price'] or 'unverified'}; this is not a cleared buy limit. Company support, current evidence, a maintained allocation plan and all remaining gates still apply.\n"+
                 f"Current decision: {row.get('decision', 'unverified')}; proposed shares {row.get('shares', 0)}. Allocation judgment and counterevidence remain in the retained company case."))
    allocation=decision.get('allocation_policy',{})
    if allocation.get('core_tickers') and allocation.get('core_minimum_pct') is not None:
        core_weight=allocation.get('core_weight_pct')
        observed=f"{float(core_weight):.2f}%" if core_weight is not None else 'unverified'
        result.append(dict(title='Index-core allocation policy',group='background',kind='',sources=[],
            body='指数底仓（'+' + '.join(allocation['core_tickers'])+'）合计至少 '
                 +f"{float(allocation['core_minimum_pct']):.0f}%；当前合计 {observed}。"
                 +'两只基金共用一个底仓目标，不要求各占 30%，也不自动换仓。'
                 +f"个股合计上限 {float(allocation['stock_maximum_pct']):.0f}%；其余现行风险规则不变。"))
    authority=c.get('account_authority',{})
    if authority.get('local_planning_enabled'):
        result.append(dict(title='Account planning basis',group='background',kind='',body='Owner-approved local records govern conditional plans.\n'+'\n'.join(authority['execution_checks']),sources=[]))
    blocked=[r for r in c['decisions'] if r['decision'] in {'NO_ACTION','BLOCKED'}]
    result.append(dict(title='Candidate decisions — research detail',group='background',kind='',body='\n'.join(f"{r['ticker']} — {r['decision']}: "+'; '.join(r['reasons']+r['blockers']) for r in blocked) or 'No additional candidates.',sources=[]))
    return sorted(result, key=lambda item: item['group'] != 'action')


def markdown(decision):
    return '\n\n'.join('## '+r['title']+'\n\n'+(r.get('headline','')+'\n\n' if r.get('headline') else '')+r['body'] for r in cards(decision))
