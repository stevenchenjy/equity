"""Action-first presentation of the admitted capital contract; no sizing logic."""
from __future__ import annotations
from capital_decision import BUY, validate
from datetime import datetime


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


def cards(decision, view=None):
    c=decision['capital_decision'];validate(c,current=datetime.fromisoformat(decision['generated_at']))
    result=[]
    actionable=[r for r in c['decisions'] if r['order_draft']]
    result.append(dict(title="TODAY'S ACTION",group='action',kind='buy' if actionable else 'inactive',
                       headline='EXACT CONDITIONAL ORDER DRAFTS' if actionable else 'NO NEW POSITION',
                       body='Review the complete drafts below, then manually enter any approved order in Chase.' if actionable else
                       'Buy/add 0 new shares in this cycle. The exact reasons and next steps follow.',sources=[]))
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
        result.append(dict(title='CAPITAL DEPLOYMENT ESCALATION',group='action',kind='inactive',headline='',body='\n'.join(lines),sources=[]))
    for row in c['decisions']:
        if row['decision'] in {'NO_ACTION','BLOCKED'} and row['ticker'] in {r['ticker'] for r in decision.get('held_positions',[])}:
            result.append(dict(title=f"{row['decision']} — {row['ticker']}",group='action',kind='inactive',headline='0 new shares; no renewed expired order',body='\n'.join(action_lines(row)),sources=[]))
    from delivery_followthrough import continuation_lines
    continuation=continuation_lines(decision.get('delivery_followthrough',{}))
    if continuation:result.append(dict(title='Earlier email — labelled completion scenario',group='background',kind='',body='\n'.join(continuation),sources=[]))
    result.append(dict(title='Cash and research progress',group='background',kind='',body=f"Cash: ${c['planning_cash']:.2f}; mandatory reserve ${c['mandatory_reserve']:.2f}. Planning cash is not broker buying power.\n"+
                        f"Research queue: {decision.get('research_opportunities',{}).get('metrics',{}).get('research_queue_size','unverified')} retained opportunities.\n"+
                        'Automatic objective collectors, valuation recomposition and the source-bound analyst continue working. Successful source collection does not complete an investment case.',sources=[]))
    authority=c.get('account_authority',{})
    if authority.get('local_planning_enabled'):
        result.append(dict(title='Account planning basis',group='background',kind='',body='Owner-approved local records govern conditional plans.\n'+'\n'.join(authority['execution_checks']),sources=[]))
    blocked=[r for r in c['decisions'] if r['decision'] in {'NO_ACTION','BLOCKED'}]
    result.append(dict(title='Candidate decisions — research detail',group='background',kind='',body='\n'.join(f"{r['ticker']} — {r['decision']}: "+'; '.join(r['reasons']+r['blockers']) for r in blocked) or 'No additional candidates.',sources=[]))
    return result


def markdown(decision):
    return '\n\n'.join('## '+r['title']+'\n\n'+(r.get('headline','')+'\n\n' if r.get('headline') else '')+r['body'] for r in cards(decision))
