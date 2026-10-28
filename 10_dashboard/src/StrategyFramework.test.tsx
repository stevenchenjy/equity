import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import StrategyFrameworkPanel from './StrategyFramework';
import {CapitalActions} from './CapitalActions';
import type {Snapshot, StrategyFramework, SwingResearch} from './domain';

const now=Date.parse('2026-10-28T08:00:00-04:00');
const framework:StrategyFramework={schema_version:'equity_strategy_framework_v1',generated_at:'2026-10-28T09:45:00-04:00',
  status:'ready',automatic_action_allowed:false,
  strategies:[{strategy_id:'growth',label:'Reviewed growth',horizon:'Four reported quarters',status:'active',capital_authority:true,
    description:'Company-specific cash and valuation cases.'},{strategy_id:'swing',label:'Swing research',horizon:'5–14 sessions',status:'experimental',capital_authority:false}],
  decisions:[{ticker:'CASE',strategy_id:'growth',horizon:'Four reported quarters',classification:'justified_no_action',
    canonical_decision:'NO_ACTION',eligible_quantity:0,blockers:[],reason:'Completed case rejects this price.',next_step:'Reassess a new official result.',resolver:'analyst',review_at:null},
  {ticker:'HELD',strategy_id:'growth',horizon:'One year',classification:'plan_expired',canonical_decision:'HOLD',eligible_quantity:0,
    blockers:['review_due'],reason:'The bounded holding review expired.',next_step:'Reassess the original thesis.',resolver:'analyst',review_at:'2026-10-27T15:30:00-04:00'}],
  analyst_handoff:[{ticker:'HELD',classification:'plan_expired',reason:'Deadline elapsed.',next_step:'Reassess without renewing the former draft.',resolver:'analyst'}]};
const swing:SwingResearch={schema_version:'equity_swing_research_v1',status:'experimental_current',research_only:true,capital_authority:false,actionable_quantity:0,
  candidates:[{ticker:'SETUP',setup:'pullback_reclaim',state:'research_setup',horizon_sessions:[5,10,14],source_session:'2026-10-27',
    first_observed_at:'2026-10-27T21:00:00-04:00',entry_session:'2026-10-28',entry_trigger:101.23,max_entry:101.7,invalidation:97.31,
    profit_reference:109.07,profit_reference_kind:'hypothetical_2R_not_observed_resistance',review_deadline:'2026-10-28T09:30:00-04:00',
    skip_reasons:['Skip a gap above the ceiling.'],evidence_quality:'validated_completed_daily_OHLCV_only',thesis:'Daily pullback regained the reference.',
    catalyst_status:'requires_analyst_direction_review',uncertainty:['Spreads and intraday sequence remain unverified.'],actionable_quantity:0,capital_authority:false,research_only:true}]};
const snapshot={expected_market_session:'2026-10-27',market_current:true,strategy_framework:framework} as Snapshot;

test('framework distinguishes completed rejection, expired hold and experimental route without making drafts',()=>{
  const before=JSON.stringify(framework);
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={snapshot} now={now}/>);
  for(const text of ['Strategy and decision readiness','Completed no-entry / hold judgment','Plan expired','CASE · WAIT','HELD · WAIT','Other research states','scheduled analyst']){
    if(text==='Other research states')continue;
    assert.ok(html.includes(text),text);
  }
  assert.match(html,/Four reported quarters/);assert.match(html,/Research only · no capital authority/);
  assert.doesNotMatch(html,/BUY LIMIT|SELL LIMIT|HELD · HOLD|[1-9]+ shares authorized/);
  assert.equal(JSON.stringify(framework),before);
});
test('current experimental setup shows complete research levels and its noncapital limits',()=>{
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:swing}}} now={now}/>);
  for(const text of ['Pullback reclaim','$101.23','$101.70','$97.31','$109.07','5 / 10 / 14','Hypothetical 2R','no capital authority','Skip a gap','Spreads'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/BUY LIMIT|SELL LIMIT|capital-buy|capital-sell/);
});
test('expired, stale-session and invalid-authority research setup cannot display current levels',()=>{
  for(const changed of [
    {...swing,status:'waiting_on_data',candidates:[]} as SwingResearch,
    {...swing,candidates:swing.candidates.map(r=>({...r,source_session:'2026-10-26'}))},
    {...swing,candidates:swing.candidates.map(r=>({...r,review_deadline:'2026-10-28T07:59:00-04:00'}))},
    {...swing,capital_authority:true} as unknown as SwingResearch,
  ]){
    const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:changed}}} now={now}/>);
    assert.doesNotMatch(html,/\$101\.23|\$101\.70|\$97\.31|\$109\.07|BUY LIMIT/);
    assert.match(html,/WAIT/);
  }
});
test('no-opportunity and failed dashboard read retain clear WAIT without invented opportunity',()=>{
  const noSetup=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:{...swing,candidates:[]}}}} now={now}/>);
  assert.match(noSetup,/No qualifying setup/);assert.doesNotMatch(noSetup,/SETUP|\$101/);
  const failed=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:swing}}} now={now} unavailable/>);
  assert.match(failed,/Current source\/session validation is unavailable/);assert.doesNotMatch(failed,/\$101\.23/);
});
test('elapsed entries and zero mature evidence are explicit rather than reported as a new empty screen',()=>{
  const view={...swing,candidates:[],expired_candidates_suppressed:2,performance:{observations:12,outcomes:0},
    blockers:['Original source binding must be restored.']};
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:view}}} now={now}/>);
  for(const text of ['elapsed entry windows','2 expired setup cards','12 recorded ticker/session observations','0 matured horizon records',
    'Profitability and a reliable win rate remain unestablished','Original source binding must be restored.'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/No qualifying setup|12 wins|12 trades|BUY LIMIT/);
});
test('failed current read withholds old canonical quantities and prices',()=>{
  const old={positions:[],capital_decision:{decisions:[{ticker:'OLD',order_draft:{side:'buy',entry_limit:999},shares:1234}]}} as unknown as Snapshot;
  const html=renderToStaticMarkup(<CapitalActions data={old} unavailable/>);
  assert.match(html,/WAIT/);assert.doesNotMatch(html,/1234|999|BUY LIMIT|OLD/);
});
test('older publications without framework remain compatible and invalid authority is hidden',()=>{
  assert.equal(renderToStaticMarkup(<StrategyFrameworkPanel data={{} as Snapshot} now={now}/>),'');
  const invalid={...framework,automatic_action_allowed:true} as unknown as StrategyFramework;
  assert.equal(renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:invalid}} now={now}/>),'');
});
