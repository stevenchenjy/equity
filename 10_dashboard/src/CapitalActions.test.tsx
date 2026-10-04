import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import {CapitalActions} from './CapitalActions';
import type {Snapshot} from './domain';
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
