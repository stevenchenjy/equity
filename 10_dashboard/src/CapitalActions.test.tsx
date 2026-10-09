import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import {CapitalActions} from './CapitalActions';
import type {CapitalDeploymentEscalation, CapitalUse, DeploymentGate, Snapshot} from './domain';
const data={positions:[{ticker:'HELD'}],capital_decision:{action:'NO_NEW_POSITION',market_data_timestamp:'2026-10-02',global_blockers:['current_account_snapshot_stale'],decisions:[{ticker:'HELD',decision:'HOLD',shares:0,estimated_notional:0,reasons:['Maintain the recorded core purpose'],dependencies:[],blockers:[],order_draft:null},{ticker:'NEW',decision:'BLOCKED',shares:0,estimated_notional:0,reasons:['Company valuation incomplete'],dependencies:[],blockers:[],order_draft:null}]}} as unknown as Snapshot;
test('action precedes research and explains no new position',()=>{
 const html=renderToStaticMarkup(<CapitalActions data={data}/>);
 assert.ok(html.indexOf('今天做什么')<html.indexOf('研究背景'));assert.match(html,/买入 \/ 加仓 0 股/);assert.match(html,/持有/);assert.match(html,/Company valuation incomplete/);
});
test('missing or invalidated contract never displays a numerical buy',()=>{
 const html=renderToStaticMarkup(<CapitalActions data={{...data,capital_decision:null}}/>);
 assert.match(html,/暂无当前有效/);assert.doesNotMatch(html,/BUY LIMIT/);
});
test('exact buy and sell quantities, price inequality and risk appear before research',()=>{
 const draft={side:'buy',entry_order_type:'LIMIT',entry_limit:102,entry_window:{starts_at:'2026-10-05T09:30:00-04:00',ends_at:'2026-10-05T16:00:00-04:00'},time_in_force:'DAY',invalidation_price:98,planned_total_loss:16,planned_account_risk_pct:.16,risk_model:'observed_price_invalidation',initial_reassessment_price:120,reassessment_rule:'Review by the fifth session',portfolio_weight_before:0,portfolio_weight_after:4.08,cash_before:7900,estimated_cash_after:7492,trigger_rule:'Only after the observed trigger',cancel_conditions:['Skip above the limit'],cost_assumption:'Costs must fit confirmed funds'};
 const row={ticker:'NEW',decision:'ACTIONABLE_BUY',shares:4,estimated_notional:408,reasons:[],dependencies:[],blockers:[],thesis_summary:'Reviewed case',order_draft:draft};
 const snapshot={...data,capital_decision:{...data.capital_decision,global_blockers:[],decisions:[row]}} as unknown as Snapshot;
 const buy=renderToStaticMarkup(<CapitalActions data={snapshot}/>);
 assert.match(buy,/4 股/);assert.match(buy,/BUY LIMIT ≤ \$102\.00/);assert.match(buy,/DAY/);assert.match(buy,/计划风险 \$16\.00/);assert.match(buy,/失效价 \$98\.00/);assert.ok(buy.indexOf('BUY LIMIT')<buy.indexOf('研究背景'));
 const sell={...snapshot,capital_decision:{...snapshot.capital_decision,decisions:[{...row,ticker:'HELD',decision:'EXIT_REVIEW',shares:2,estimated_notional:204,order_draft:{...draft,side:'sell',exit_price:102,entry_limit:null,invalidation_price:null,risk_model:'conditional_exit_limit_no_downside_protection'}}]}} as unknown as Snapshot;
 const exit=renderToStaticMarkup(<CapitalActions data={sell}/>);
 assert.match(exit,/2 股/);assert.match(exit,/SELL LIMIT ≥ \$102\.00/);assert.match(exit,/capital-sell/);assert.doesNotMatch(exit,/BUY LIMIT/);
});
const gates:DeploymentGate[]=[
 {category:'valuation',code:'valuation_incomplete',scope:'candidate',ticker:'NEW',evidence_required:'Complete audited cash-flow valuation',resolver:'research'},
 {category:'price',code:'entry_above_review_price',scope:'candidate',ticker:'HELD',evidence_required:'Wait for the approved price window',resolver:'market'},
 {category:'policy',code:'core_target_satisfied',scope:'candidate',ticker:'CORE',evidence_required:'Core target already met; retain allocation limit',resolver:'policy'},
];
const uses:CapitalUse[]=gates.map((gate,i)=>({rank:i+1,ticker:gate.ticker!,route:['researched_growth_candidate','existing_quality_holding','diversified_core_growth'][i],decision:'BLOCKED',eligible:false,blockers:[gate.code],gates:[gate],research_ready:i!==0,canonical_score:90-i,order_draft:null,shares:0,estimated_notional:0}));
const escalation:CapitalDeploymentEscalation={schema_version:'equity_capital_deployment_escalation_v1',generated_at:'2026-10-08T18:00:00-04:00',status:'active',triggered:true,required_sessions:2,consecutive_no_action_sessions:2,session_history_status:'verified',session_history_reason:'October 7 and 8 completed sessions',observation_session:'2026-10-08',cash:{uncommitted_cash_usd:7900,account_value_usd:10000,cash_target_pct:10,cash_target_usd:1000,excess_cash_usd:6900,excess_cash_pct:69,material_excess_cash_pct:5,materially_above_target:true},account_integrity_blockers:[],gates,ranked_capital_uses:uses,routes:uses.map(use=>({route:use.route,label:use.route,status:'available',closest_candidate:use,blockers:[]})),closest_candidate:uses[0],admitted_order_drafts:[],research_priority_tickers:['NEW'],research_requests:[{ticker:'NEW',priority:1,urgency:'immediate',blockers:['valuation_incomplete'],required_work:[gates[0]],completed:false}],explanation:'Cash retained until the exact remaining gates are resolved.',automatic_action_allowed:false};
test('two-session escalation compares three routes and explains the exact gates retaining cash',()=>{
 const html=renderToStaticMarkup(<CapitalActions data={{...data,capital_deployment_escalation:escalation}}/>);
 assert.match(html,/已触发：立即复核最佳资金用途/);assert.match(html,/2 个交易日/);assert.match(html,/超出目标 \$6,900\.00/);
 for(const route of ['加仓现有高质量持仓','新建研究最充分的成长仓位','增加分散的核心 \/ 成长配置'])assert.match(html,new RegExp(route));
 assert.match(html,/估值 · valuation_incomplete/);assert.match(html,/价格 · entry_above_review_price/);assert.match(html,/政策 · core_target_satisfied/);
 assert.match(html,/最接近部署条件/);assert.match(html,/待完成研究（立即）/);assert.match(html,/研究排队不代表结论已得到验证/);assert.doesNotMatch(html,/BUY LIMIT/);
});
test('account-blocked escalation remains visible without a valid contract and never publishes summary-only quantities',()=>{
 const accountGate:DeploymentGate={category:'account',code:'account_snapshot_stale',scope:'global',evidence_required:'Confirm current account cash and complete order inventory',resolver:'owner'};
 const blocked={...escalation,status:'account_integrity_blocked',triggered:false,account_integrity_blockers:['account_snapshot_stale'],gates:[accountGate,...gates],admitted_order_drafts:[{ticker:'NEW',decision:'ACTIONABLE_BUY',shares:999,estimated_notional:99999,order_draft:null}]} as CapitalDeploymentEscalation;
 const html=renderToStaticMarkup(<CapitalActions data={{...data,capital_decision:null,capital_deployment_escalation:blocked}}/>);
 assert.match(html,/暂无当前有效的完整交易草案/);assert.match(html,/账户完整性门槛未通过/);assert.match(html,/账户完整性 · account_snapshot_stale/);assert.match(html,/Confirm current account cash and complete order inventory/);assert.doesNotMatch(html,/999 股|99,999|BUY LIMIT/);
});
test('global gates copied per ticker display once while the full disclosure preserves attributed ticker gates',()=>{
 const globalGates:DeploymentGate[]=[
  {category:'account',code:'account_snapshot_stale',scope:'global',evidence_required:'Confirm the latest complete account snapshot',resolver:'owner'},
  {category:'account',code:'order_inventory_incomplete',scope:'global',evidence_required:'Confirm every current open order',resolver:'owner'},
  {category:'evidence',code:'shared_snapshot_unverified',scope:'global',evidence_required:'Rebuild the shared source snapshot',resolver:'system'},
 ];
 const copiedUses=uses.map(use=>({...use,gates:[...globalGates.map(gate=>({...gate,ticker:use.ticker})),...use.gates],blockers:[...globalGates.map(gate=>gate.code),...use.blockers]}));
 const repeated={...escalation,status:'account_integrity_blocked',triggered:false,account_integrity_blockers:globalGates.filter(gate=>gate.category==='account').map(gate=>gate.code),gates:[...copiedUses.flatMap(use=>use.gates),...globalGates,...gates],ranked_capital_uses:copiedUses,closest_candidate:copiedUses[0],research_requests:[]} as CapitalDeploymentEscalation;
 const beforeRender=JSON.stringify(repeated);
 const html=renderToStaticMarkup(<CapitalActions data={{...data,capital_decision:null,capital_deployment_escalation:repeated}}/>);
 const comparisonIndex=html.indexOf('<h4>三类资金用途比较');
 const disclosureIndex=html.indexOf('<details><summary>完整现金保留门槛');
 assert.ok(comparisonIndex>0&&disclosureIndex>comparisonIndex);
 const globals=html.slice(0,comparisonIndex),candidates=html.slice(comparisonIndex,disclosureIndex),disclosure=html.slice(disclosureIndex);
 for(const gate of globalGates){
  assert.equal(globals.split(gate.evidence_required).length-1,1);
  assert.equal(globals.split(gate.code).length-1,1);
  assert.ok(!candidates.includes(gate.evidence_required));
  assert.ok(!candidates.includes(gate.code));
  assert.equal(disclosure.split(gate.code).length-1,1);
  assert.ok(disclosure.includes(`全局 · ${gate.category==='account'?'账户完整性':'证据'} · ${gate.code}`));
 }
 for(const gate of gates){
  assert.equal(disclosure.split(gate.code).length-1,1);
  assert.ok(disclosure.includes(`${gate.ticker} · ${gate.category==='valuation'?'估值':gate.category==='price'?'价格':'政策'} · ${gate.code}`));
 }
 assert.equal(JSON.stringify(repeated),beforeRender);
});
test('unverified history and an eligible summary cannot substitute for a current complete order contract',()=>{
 const eligible={...uses[0],eligible:true,gates:[],blockers:[]};
 const unverified={...escalation,status:'history_unverified',triggered:false,consecutive_no_action_sessions:null,ranked_capital_uses:[eligible],closest_candidate:eligible} as CapitalDeploymentEscalation;
 const html=renderToStaticMarkup(<CapitalActions data={{...data,capital_decision:null,capital_deployment_escalation:unverified}}/>);
 assert.match(html,/连续交易日记录尚未核实/);assert.match(html,/连续无买入 \/ 加仓草案：尚未核实/);assert.match(html,/等待当前有效的完整草案/);assert.doesNotMatch(html,/已触发：|完整条件草案见行动区|BUY LIMIT/);
});
test('escalation preserves a qualified full draft while adjacent candidate gates remain explicit',()=>{
 const draft={side:'buy',entry_order_type:'LIMIT',entry_limit:102,entry_window:{starts_at:'2026-10-09T09:30:00-04:00',ends_at:'2026-10-09T16:00:00-04:00'},time_in_force:'DAY',invalidation_price:98,planned_total_loss:16,planned_account_risk_pct:.16,initial_reassessment_price:120,reassessment_rule:'Review by the fifth session',portfolio_weight_before:0,portfolio_weight_after:4.08,cash_before:7900,estimated_cash_after:7492,trigger_rule:'Only after the observed trigger',cancel_conditions:['Skip above the limit'],cost_assumption:'Costs must fit confirmed funds'};
 const row={ticker:'ELIGIBLE',decision:'ACTIONABLE_BUY',shares:4,estimated_notional:408,reasons:[],dependencies:[],blockers:[],thesis_summary:'Reviewed case',order_draft:draft};
 const snapshot={...data,capital_deployment_escalation:escalation,capital_decision:{...data.capital_decision,global_blockers:[],decisions:[row,...data.capital_decision!.decisions]}} as unknown as Snapshot;
 const html=renderToStaticMarkup(<CapitalActions data={snapshot}/>);
 assert.match(html,/4 股 · 约 \$408\.00/);assert.match(html,/BUY LIMIT ≤ \$102\.00/);assert.match(html,/Skip above the limit/);assert.match(html,/估值 · valuation_incomplete/);assert.match(html,/价格 · entry_above_review_price/);assert.ok(html.indexOf('BUY LIMIT')<html.indexOf('连续两日资金部署升级'));assert.ok(html.indexOf('BUY LIMIT')<html.indexOf('研究背景'));
});
test('approved local planning keeps metadata out of action blockers and labels its basis separately',()=>{
 const snapshot={...data,capital_decision:{...data.capital_decision,global_blockers:[],account_authority:{mode:'owner_local_ledger',local_planning_enabled:true}}} as unknown as Snapshot;
 const html=renderToStaticMarkup(<CapitalActions data={snapshot}/>);
 assert.match(html,/按你批准的本地台账/);
 assert.match(html,/券商实时状态未被确认/);
 assert.doesNotMatch(html,/你现在需要做的：更新账户记录/);
 assert.match(html,/Company valuation incomplete/);
});
