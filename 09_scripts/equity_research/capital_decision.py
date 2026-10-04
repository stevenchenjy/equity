"""Single final capital-decision adapter over existing reviewed policy owners.

A conditional manual draft is complete decision work, not trade execution.
Research opportunities cannot authorize capital. Missing inputs cannot acquire
quantity through a renderer, historical plan or hypothetical tactical scenario.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from daily_common import canonical_sha256, sha256_file, read_json, atomic_write_json, last_completed_market_session
from production_strategies import REGISTRY, select
from decision_dependencies import classify
from tactical_review import review_open_orders
from investment_plans import regular_close
from workflow_integrity import reviewed_candidate_ready
from core_entry import eligible_core_tranche

SCHEMA = 'equity_capital_decision_v1'
OUTCOMES = {'ACTIONABLE_BUY','ACTIONABLE_ADD','HOLD','REDUCE_REVIEW','EXIT_REVIEW','NO_ACTION','BLOCKED'}
BUY = {'ACTIONABLE_BUY','ACTIONABLE_ADD'}
EXITS = {'REDUCE_REVIEW','EXIT_REVIEW'}
INPUTS = {
 REGISTRY, '00_project_control/active_production_config.json', '01_policies/tactical_trade_policy.json',
 '05_risk_and_positions/current_account_state.local.json','05_risk_and_positions/current_positions.local.csv',
 '05_risk_and_positions/current_open_orders.local.json','05_risk_and_positions/investment_plans.local.json',
 '04_research/company_research/thesis_dossiers.local.json','04_data/equity_research/valuation_scenarios.local.json',
 '03_source_data/equity_research/market_data_snapshot.csv',
 '07_automation/email_delivery/daily_delivery_ledger.csv',
 '05_risk_and_positions/manual_account_snapshot.local.json',
}
# These are observed failures of reviewed numerical conditions, not absent facts.
CONDITION_FAILURES = {'score','confidence','upside','reward_to_risk','entry','portfolio_fit','whole_share_target_gap',
 'canonical_buy_not_eligible','observed_target_has_no_upside','reward_to_risk_below_minimum','entry_above_canonical_maximum',
 'cash_or_risk_budget_below_one_share','cash_concentration_or_risk_budget_below_one_share','not_in_canonical_eligible_set'}


def num(value: Any) -> Decimal:
    try:v = Decimal(str(value))
    except (ValueError,TypeError,InvalidOperation) as exc:raise ValueError('invalid_capital_number') from exc
    if not v.is_finite():
        raise ValueError('nonfinite_capital_input')
    return v


def money(v: Decimal) -> float:
    return float(v.quantize(Decimal('0.01')))


def codes(value: Any) -> list[str]:
    return [s.strip() for s in value.split(',') if s.strip()] if isinstance(value,str) else list(value or [])


def binding(root: Path) -> dict:
    return {p:sha256_file(root/p) if (root/p).is_file() else None for p in sorted(INPUTS)}


def meaning(contract: dict) -> dict:
    # Publication clock and artifact hashes do not cause duplicate daily alerts.
    result=deepcopy(contract)
    for k in ('generated_at','content_sha256','source_bindings'): result.pop(k,None)
    for row in result.get('decisions',[]):
        row.pop('decision_timestamp',None)
    return result


def build(decision: dict, *, root: Path, current: datetime, strategies: dict | None=None,
          config: dict | None=None, orders: dict | None=None) -> dict:
    current=current.astimezone(ZoneInfo('America/New_York'))
    config=config or read_json(root/'00_project_control/active_production_config.json')
    account=decision.get('account',{})
    held={r['ticker']:r for r in decision.get('held_positions',[])}
    watch={r['ticker']:r for r in decision.get('watch_candidates',[])}
    plans={r['ticker']:r for r in decision.get('plan_continuity',{}).get('plans',[])}
    opportunities={r['ticker']:r for r in decision.get('research_opportunities',{}).get('priority_queue',[]) if r.get('ticker')}
    gates=decision.get('workflow_integrity',{})
    global_codes=list(gates.get('global_blockers', gates.get('blockers',[])))
    from delivery_followthrough import continuation_requires_reconciliation
    if continuation_requires_reconciliation(decision.get('delivery_followthrough', {})):
        # Receipt uncertainty requires actual execution/account evidence. The
        # hypothetical fill quantities themselves never enter sizing.
        global_codes.append('earlier_instruction_execution_unreconciled')
    for gate in ('market_gate','evidence_gate','fundamental_gate'):
        if decision.get(gate,{}).get('passed') is not True:global_codes.append(gate+'_failed')
    expected=decision.get('market_gate',{}).get('expected_market_session')
    if expected != last_completed_market_session(current).isoformat():global_codes.append('latest_completed_session_missing')
    orders=orders if orders is not None else read_json(root/'05_risk_and_positions/current_open_orders.local.json',{})
    order_review=review_open_orders(orders,current,current.date(),list(held.values()))
    # Fresh orders are checked here for every capital action, even when no plan exists.
    global_codes.extend(order_review['global_blockers'])
    try:
        total,cash,reserve=(num(account[k]) for k in ('account_total_value','cash_available','cash_reserved'))
        if not total>0 or not 0<=reserve<=cash<=total:raise ValueError('invalid_account_arithmetic')
        confirmed=(account.get('cash_basis') in {'owner_confirmed','broker_confirmed'} or
                   account.get('cash_basis')=='owner_recorded' and orders.get('cash_confirmed') is True and order_review['complete'])
        if not confirmed:global_codes.append('planning_cash_unverified')
        try:
            updated=datetime.fromisoformat(account['last_updated'])
            completed_close=regular_close(last_completed_market_session(current).isoformat())
            if updated.tzinfo is None or not 0 <= (current-updated).total_seconds() <= 86400 or updated < completed_close:
                global_codes.append('current_account_snapshot_stale')
        except (KeyError,TypeError,ValueError):global_codes.append('current_account_snapshot_time_unverified')
    except (KeyError,ValueError,TypeError,InvalidOperation):
        total,cash,reserve=Decimal(0),Decimal(0),Decimal(0);global_codes.append('shared_account_values_unverified')
    global_codes=sorted(set(global_codes))
    cash_remaining=max(Decimal(0),cash-reserve-num(order_review['cash_reservation_usd']))
    tactical={r['ticker']:r for r in decision.get('tactical_review',{}).get('drafts',[])}
    risk_budget=decision.get('tactical_review',{}).get('risk_budget',{})
    try:risk_remaining=max(Decimal(0),num(risk_budget.get('combined_usd',0))-num(risk_budget.get('open_risk_usd',0)))
    except (ValueError,InvalidOperation):risk_remaining=Decimal(0)
    active_value=sum(num(r.get('current_price',0))*num(r.get('current_shares',0)) for r in held.values() if r.get('asset_role')!='core_allocation')
    core_value=sum(num(r.get('current_price',0))*num(r.get('current_shares',0)) for r in held.values() if r.get('asset_role')=='core_allocation')
    cfg=config['account']; rows=[]; dependencies=[]
    for code in global_codes: dependencies.append(classify(code,scope='global'))
    eligible=set(decision.get('eligible_new_position_review_candidates',[]))|set(decision.get('eligible_action_review_candidates',[]))
    for ticker in dict.fromkeys([*held,*watch,*opportunities]):
        h,w,p=held.get(ticker,{}),watch.get(ticker,{}),plans.get(ticker,{})
        entry_codes=codes(w.get('gate_blockers'))
        local=sorted(set(codes(gates.get('ticker_blockers',{}).get(ticker))+codes(p.get('blockers'))+codes(order_review.get('ticker_blockers',{}).get(ticker)))-set(global_codes))
        row=dict(ticker=ticker,decision='NO_ACTION',decision_timestamp=current.isoformat(),market_data_timestamp=expected,
                 shares=0,estimated_notional=0,order_draft=None,blockers=[],reasons=[],confidence=w.get('confidence','unverified'),
                 thesis_summary='',key_evidence=[],strategy_source=None)
        if h:
            status=p.get('status')
            if status=='maintained' and p.get('action') in {'hold','hold_watch','maintain','watch'} and not local:
                row.update(decision='HOLD',reasons=[p.get('instruction') or 'Maintain the source-bound existing purpose through its recorded review.'],
                           thesis_summary=p.get('reason',''),reassessment_rule=p.get('purpose',{}).get('exit_rule',''),review_at=p.get('review_at'))
            elif p.get('action') in {'exit_review','sell_review','trim_review','reduce_review','protect_review'}:
                row['decision']='EXIT_REVIEW' if p['action'] in {'exit_review','sell_review'} else 'REDUCE_REVIEW'
                row['reasons']=[p.get('instruction','Review the evidenced held-position risk.')]
                exit_strategy, exit_errors = select(root,'maintained_exit',strategies)
                exit_issues = [c for c in local if c != 'fresh_quote_and_available_shares_required'] + order_review['global_blockers'] + exit_errors
                exit_issues += [c for c in global_codes if 'account' in c or c == 'earlier_instruction_execution_unreconciled']
                if ticker in order_review['active_tickers']: exit_issues.append('existing_order_requires_reconciliation')
                raw=p.get('order_draft') or p.get('historical_order_draft') or {}
                try:
                    qty=num(raw['quantity']); existing=num(h['current_shares']); reference=num(h['current_price'])
                    kind=raw['type']; price=num(raw['stop_price'] if kind=='STOP' else raw['limit_price'])
                    close=regular_close(raw['session_date']); review=datetime.fromisoformat(p['review_at'])
                    end=min(close,review)
                    if p.get('status')!='maintained' or raw.get('side')!='sell' or kind not in {'LIMIT','MARKETABLE_LIMIT','STOP'} or raw.get('time_in_force')!='DAY' or not 0<qty<=existing or qty!=qty.to_integral_value() or price<=0 or current>=end:
                        raise ValueError('maintained_exit_draft_invalid')
                    if kind=='STOP' and price>=reference:exit_issues.append('exit_stop_already_breached_reassessment_required')
                    if not exit_issues:
                        loss_per=max(Decimal(0),reference-price) if kind=='STOP' else reference
                        amount=price*qty; loss=loss_per*qty
                        row.update(shares=int(qty),estimated_notional=money(amount),strategy_source={'strategy_id':exit_strategy['strategy_id'],'version':exit_strategy['version'],'adapter':'maintained_exit','authority':exit_strategy['authority']},
                            thesis_summary=p.get('reason') or p['instruction'],key_evidence=[str(p.get('record_hash','validated maintained plan'))],
                            order_draft=dict(side='sell',entry_order_type=kind,entry_limit=None,exit_price=money(price),
                             entry_window={'session':raw['session_date'],'starts_at':datetime.fromisoformat(raw['session_date']+'T09:30:00').replace(tzinfo=current.tzinfo).isoformat(),'ends_at':end.isoformat()},time_in_force='DAY',
                             invalidation_price=money(price) if kind=='STOP' else None,
                             risk_model='conditional_exit_stop' if kind=='STOP' else 'conditional_exit_limit_no_downside_protection',
                             planned_loss_per_share=money(loss_per),planned_total_loss=money(loss),planned_account_risk_pct=round(float(loss/total*100),4),
                             initial_reassessment_price=money(price),reassessment_rule='Reassess by '+end.isoformat()+'; if no fill, the remaining exposure and original purpose persist.',
                             invalidation_rule='A target limit does not protect a decline. Stop execution can gap below the trigger.',
                             trigger_rule=('SELL STOP trigger at or below ' if kind=='STOP' else 'SELL LIMIT at or above ')+f'${price:.2f}; verify current quote and available shares before submission.',
                             portfolio_weight_before=round(float(existing*reference/total*100),4),portfolio_weight_after=round(float((existing-qty)*reference/total*100),4),
                             cash_before=money(cash_remaining),estimated_cash_after=money(cash_remaining+amount),account_value=money(total),
                             cancel_conditions=['Skip if current holdings or order inventory differs, or shares are already reserved.','Never duplicate a pending exit; confirm cancellation before replacement.','This draft expires at '+end.isoformat()+'.','Expected proceeds are conditional and unsettled; no new purchase is funded by an assumed sale.'],
                             price_basis='Source-bound maintained exit level, not a live quote.',cost_assumption='Proceeds at the stated price are an estimate before costs, not a fill or settled buying power.',automatic_action_allowed=False))
                except (KeyError,ValueError,TypeError,InvalidOperation,ZeroDivisionError):exit_issues.append('maintained_exit_draft_requires_current_shares_price_and_validity')
                row['blockers']=sorted(set(exit_issues))
            elif status != 'maintained' or local:
                row.update(decision='BLOCKED',blockers=sorted(set(local or ['current_held_plan_reassessment_required'])),
                           reasons=['No fresh bounded holding instruction; the scheduled analyst must reassess the original purpose. Expiry does not prove a sale.'])
            else:
                row.update(decision='HOLD',reasons=[p.get('instruction') or 'No supported change in the existing position purpose.'])
        if ticker in eligible:
            core=w.get('valuation_applicability')=='not_applicable_broad_market_etf' or h.get('asset_role')=='core_allocation'
            adapter='core_tranche' if core else 'reviewed_tactical'
            strategy,errors=select(root,adapter,strategies)
            issues=global_codes+local+entry_codes+errors
            numeric_reasons=[]
            if ticker in order_review['active_tickers']:issues.append('existing_order_requires_reconciliation')
            if h and not core and p.get('role')!='tactical':issues.append('position_purpose_change_requires_recorded_reassessment')
            if not core and not reviewed_candidate_ready(decision.get('long_horizon_research',{}).get('candidate_views',{}).get(ticker,decision.get('long_horizon_research',{}).get('views',{}).get(ticker,{}))):
                issues.append('maintained_company_research_incomplete')
            draft=eligible_core_tranche(decision,w) if core else tactical.get(ticker)
            if not draft or (not core and draft.get('eligible') is not True):
                issues+=codes((draft or {}).get('blockers')) or ['strategy_entry_and_risk_contract_unavailable']
            if not issues:
                try:
                    entry=num(draft['max_price'] if core else draft['entry_price'])
                    before_qty=num(h.get('current_shares',0)); before_value=before_qty*num(h.get('current_price',entry))
                    qty=int(draft['quantity']); session=draft['session_date']
                    close=regular_close(session)
                    if current>=close or qty<=0 or entry<=0:raise ValueError('draft_invalid_or_expired')
                    if not core and (draft.get('hypothetical_quantity') or draft.get('time_in_force')!='DAY'):raise ValueError('hypothetical_or_undated_draft')
                    cap=num(cfg['core_target_pct'] if core else min(cfg['single_stock_hard_cap_pct'],decision['tactical_review']['risk_policy']['max_position_pct']))
                    limit_value=total*cap/100-before_value
                    role_room=total*num(cfg['core_target_pct'] if core else cfg['research_risk_limits']['active_stock_hard_cap_pct'])/100-(core_value if core else active_value)
                    per_loss=entry if core else entry-num(draft['stop_price'])
                    if per_loss<=0:raise ValueError('price_invalidation_invalid')
                    ceilings=[qty,int((cash_remaining/entry).to_integral_value(rounding=ROUND_FLOOR)),int((max(Decimal(0),min(limit_value,role_room))/entry).to_integral_value(rounding=ROUND_FLOOR))]
                    if not core:ceilings.extend([int((risk_remaining/per_loss).to_integral_value(rounding=ROUND_FLOOR)),int((num(draft['risk_limit_usd'])/per_loss).to_integral_value(rounding=ROUND_FLOOR))])
                    qty=max(0,min(ceilings))
                    if qty==0:
                        issues.append('cash_concentration_or_risk_budget_below_one_share')
                        numeric_reasons.append(f'0 shares: limit ${entry:.2f}; uncommitted cash ${cash_remaining:.2f}; name/role headroom ${max(Decimal(0),min(limit_value,role_room)):.2f}; whole-share ceilings {ceilings} (canonical, cash, concentration'+(', combined risk, per-trade risk' if not core else '')+').')
                        if not core:numeric_reasons.append(f'Planned loss per share ${per_loss:.2f}; remaining combined risk ${risk_remaining:.2f}; per-trade budget ${num(draft["risk_limit_usd"]):.2f}.')
                    else:
                        amount=entry*qty; loss=per_loss*qty
                        window={'session':session,'starts_at':datetime.fromisoformat(session+'T09:30:00').replace(tzinfo=current.tzinfo).isoformat(),'ends_at':close.isoformat()}
                        proposed=dict(side='buy',entry_order_type='LIMIT',entry_limit=money(entry),entry_window=window,time_in_force='DAY',
                          invalidation_price=None if core else draft['stop_price'],planned_loss_per_share=money(per_loss),planned_total_loss=money(loss),
                          planned_account_risk_pct=round(float(loss/total*100),4),risk_model='unlevered_principal_exposure_no_price_stop' if core else 'observed_price_invalidation',
                          initial_reassessment_price=None if core else draft['target_price'],
                          reassessment_rule=p.get('purpose',{}).get('exit_rule','') if core else 'Review at the observed target; exit/reassess no later than '+draft['time_exit_session']+' close. No purpose conversion.',
                          invalidation_rule=p.get('purpose',{}).get('invalidation','Core case/material fund evidence or allocation policy failure requires reassessment; no tactical price stop is prescribed.') if core else draft['invalidation_rule'],
                          portfolio_weight_before=round(float(before_value/total*100),4),portfolio_weight_after=round(float((before_value+amount)/total*100),4),
                          cash_before=money(cash_remaining),estimated_cash_after=money(cash_remaining-amount),account_value=money(total),
                          cancel_conditions=['Skip if current holdings, complete order inventory or execution funds differ from the recorded inputs.',
                          'Skip if the current executable quote or estimated all-in cost exceeds the limit/budget; no chasing.',
                          'Skip on material adverse evidence or any failed strategy/data/risk gate.',
                          'Do not use after '+close.isoformat()+'; DAY expiry never renews this draft.',
                          'Entry requires a live quote/spread/market-status check by the owner; no real-time evidence is claimed.'],
                          trigger_rule='Only while quote is at or below the limit and all dated core conditions hold.' if core else draft['entry_rule'],
                          cost_assumption='Commission and regulatory/execution costs not independently observed here; estimated notional excludes fees. Any positive cost must fit confirmed funds and risk budget.',
                          price_basis='Completed market publication; not a live quote.',automatic_action_allowed=False)
                        row.update(decision='ACTIONABLE_ADD' if before_qty else 'ACTIONABLE_BUY',shares=qty,estimated_notional=money(amount),order_draft=proposed,
                                   strategy_source={'strategy_id':strategy['strategy_id'],'version':strategy['version'],'adapter':adapter,'authority':strategy['authority']},
                                   position_purpose={'role':'broad_core' if core else 'tactical','strategy_horizon':'core_investment' if core else 'multi_day_trend','time_exit_session':None if core else draft['time_exit_session']},
                                   thesis_summary=p.get('reason') if core else w.get('strongest_positive_evidence','Reviewed canonical company case and source-bound observed tactical plan.'),
                                   key_evidence=[str(w.get('strongest_positive_evidence') or 'Validated strategy-specific evidence'),str(w.get('strongest_negative_evidence') or 'Recorded counterevidence remains relevant')],
                                   reasons=['All existing eligibility gates passed; exact size is capped by shared cash, portfolio headroom and strategy risk.'])
                        cash_remaining-=amount
                        if core:core_value+=amount
                        else:active_value+=amount;risk_remaining-=loss
                except (KeyError,ValueError,TypeError,InvalidOperation):issues.append('strategy_numeric_entry_or_risk_contract_invalid')
            if issues:
                missing=[c for c in issues if c not in CONDITION_FAILURES]
                row.update(decision='BLOCKED' if missing else 'NO_ACTION',shares=0,estimated_notional=0,order_draft=None,blockers=sorted(set(issues)) if missing else [],reasons=numeric_reasons or (['No complete admissible capital draft under the existing rules.'] if missing else ['Observed conditions do not permit a new position: '+', '.join(sorted(set(issues)))]))
        elif not h:
            observed=sorted(set(local+entry_codes)-set(global_codes)) or codes(opportunities.get(ticker,{}).get('blockers')) or ['not_in_canonical_eligible_set']
            # A supported research opportunity still needs its investment case; never promote it here.
            missing=[c for c in observed if c not in CONDITION_FAILURES]
            row.update(decision='BLOCKED' if missing else 'NO_ACTION',blockers=sorted(set(global_codes+missing)) if missing else [],
                       reasons=observed if not missing else ['Research has not supplied a complete current investment case and entry contract.'])
        row['dependencies']=[classify(c,ticker=ticker) for c in row['blockers']]
        dependencies.extend(row['dependencies']);rows.append(row)
    result=dict(schema_version=SCHEMA,generated_at=current.isoformat(),market_data_timestamp=expected,
                action='EXACT_CONDITIONAL_DRAFTS' if any(r['decision'] in BUY for r in rows) else 'NO_NEW_POSITION',
                decisions=rows,global_blockers=global_codes,dependencies=dependencies,
                planning_cash=money(cash),mandatory_reserve=money(reserve),estimated_uncommitted_cash_after=money(cash_remaining),
                source_bindings=binding(root),automatic_action_allowed=False,broker_connected=False,order_placed=False,
                execution='Owner reads the complete conditional draft and manually enters any real order in Chase.')
    result['content_sha256']=canonical_sha256(result)
    validate(result,current=current)
    return result


def validate(value: dict, *, current: datetime, root: Path | None=None) -> None:
    if value.get('schema_version')!=SCHEMA or value.get('content_sha256')!=canonical_sha256({k:v for k,v in value.items() if k!='content_sha256'}):raise ValueError('capital_decision_content_invalid')
    if value.get('automatic_action_allowed') is not False or value.get('broker_connected') is not False or value.get('order_placed') is not False:raise ValueError('capital_decision_execution_authority_invalid')
    if root is not None and value.get('source_bindings')!=binding(root):raise ValueError('capital_decision_inputs_changed_recompose_required')
    for row in value.get('decisions',[]):
        if row.get('decision') not in OUTCOMES:raise ValueError('capital_decision_outcome_invalid')
        if type(row.get('shares')) is not int or row['shares'] < 0:raise ValueError('capital_decision_quantity_invalid')
        if row['decision'] not in BUY and not (row['decision'] in EXITS and row.get('order_draft')):
            if row.get('shares') or row.get('order_draft'):raise ValueError('nonactionable_capital_quantity')
            if not row.get('reasons'):raise ValueError('capital_decision_reason_missing')
            continue
        p=row['order_draft']
        if p.get('automatic_action_allowed') is not False or p.get('side') != ('buy' if row['decision'] in BUY else 'sell'):
            raise ValueError('capital_draft_execution_authority_invalid')
        if p.get('risk_model') not in {'observed_price_invalidation','unlevered_principal_exposure_no_price_stop','conditional_exit_stop','conditional_exit_limit_no_downside_protection'}:raise ValueError('capital_draft_risk_model_invalid')
        required={'entry_order_type','entry_limit','entry_window','time_in_force','invalidation_price','planned_loss_per_share','planned_total_loss','planned_account_risk_pct','initial_reassessment_price','reassessment_rule','portfolio_weight_before','portfolio_weight_after','cash_before','estimated_cash_after','cancel_conditions','risk_model','account_value','trigger_rule'}
        if not required.issubset(p) or row.get('blockers') or not row.get('strategy_source') or not row.get('thesis_summary') or not row.get('key_evidence') or not p['cancel_conditions'] or not p['reassessment_rule']:raise ValueError('capital_draft_required_fields_missing')
        if root is not None:
            source=row['strategy_source']; strategy, errors=select(root, source['adapter'])
            if errors or any(source.get(k) != strategy.get(k) for k in ('strategy_id','version','authority')):
                raise ValueError('capital_draft_strategy_admission_invalid')
        selling=p.get('side')=='sell'
        qty,entry,loss,total=(num(x) for x in (row['shares'],p['exit_price'] if selling else p['entry_limit'],p['planned_loss_per_share'],p['account_value']))
        if qty<=0 or qty!=qty.to_integral_value() or min(entry,total)<=0 or loss<0 or (not selling and loss==0) or p['time_in_force']!='DAY' or p['entry_order_type'] not in ({'LIMIT','MARKETABLE_LIMIT','STOP'} if selling else {'LIMIT'}):raise ValueError('capital_draft_numeric_invalid')
        if money(qty*entry)!=row['estimated_notional'] or money(qty*loss)!=p['planned_total_loss'] or money(num(p['cash_before'])+qty*entry*(1 if selling else -1))!=p['estimated_cash_after'] or num(p['estimated_cash_after'])<0:raise ValueError('capital_draft_arithmetic_invalid')
        if abs(num(p['planned_account_risk_pct'])-num(p['planned_total_loss'])/total*100)>Decimal('0.0001'):raise ValueError('capital_draft_risk_invalid')
        if p['risk_model']=='observed_price_invalidation' and (not 0<num(p['invalidation_price'])<entry<num(p['initial_reassessment_price']) or money(entry-num(p['invalidation_price']))!=money(loss)):raise ValueError('capital_draft_invalidation_invalid')
        if p['risk_model']=='unlevered_principal_exposure_no_price_stop' and (p['invalidation_price'] is not None or entry!=loss):raise ValueError('core_risk_model_invalid')
        end=datetime.fromisoformat(p['entry_window']['ends_at']);start=datetime.fromisoformat(p['entry_window']['starts_at'])
        if end.tzinfo is None or start.tzinfo is None or end<=start or current>=end:raise ValueError('capital_draft_expired')


def publish(root: Path, value: dict) -> None:
    atomic_write_json(root/'08_reviews/current/capital_decision.local.json',value)
