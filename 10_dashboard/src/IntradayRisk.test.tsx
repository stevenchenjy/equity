import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import IntradayRiskPanel,{intradayDisplayCurrent} from './IntradayRisk';
import type {IntradayRisk,Snapshot} from './domain';
const risk:IntradayRisk={schema_version:'intraday_portfolio_risk_v1',status:'current',generated_at:'2026-10-22T15:31:00-04:00',session_date:'2026-10-22',mark_as_of:'2026-10-22T15:30:20-04:00',expires_at:'2026-10-22T15:35:20-04:00',baseline_session:'2026-10-21',portfolio_nav:'1980',baseline_portfolio_nav:'2000',value_change_usd:'-20',value_change_pct:'-1',cash_usd:'1000',positions:[{ticker:'SPY',shares:2,price:490,price_as_of:'2026-10-22T15:30:20-04:00',price_change_pct:-2,weight_pct:49.4949,source:'Massive',delay_label:'Real-time entitlement; observed last trade',status:'current'}],allocation:{core_weight_pct:49.4949,stock_weight_pct:0,cash_weight_pct:50.5051},plan_conditions:[{ticker:'SPY',condition:'Retain the existing core minimum.',status:'met'}],reassessment_triggers:[],dependencies:[],limitations:['A last trade is not an executable quote.']};
const data={intraday_portfolio_risk:risk,account:{account_total_value:2000,cash_available:1000},positions:[]} as unknown as Snapshot;
const now=Date.parse('2026-10-22T15:32:00-04:00');
test('validated marks show price-only NAV alongside explicit close/cash/source/time, without order language',()=>{
  const html=renderToStaticMarkup(<IntradayRiskPanel data={data} now={now}/>);
  for(const text of ['Intraday portfolio risk','Validated observation','$1,980.00','$2,000.00','-$20.00','-1.00%','Planning cash $1,000.00 is unchanged','same recorded holdings','not the account&#x27;s actual daily return','Massive','3:30:20 PM ET','Real-time entitlement','Retain the existing core minimum','All existing entry gates'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/BUY LIMIT|SELL LIMIT|order_draft|2% loss limit/);
});
test('browser clock expires an observation even if API has not been refreshed',()=>{
  const later=Date.parse(risk.expires_at!);
  assert.equal(intradayDisplayCurrent(risk,later),false);
  const html=renderToStaticMarkup(<IntradayRiskPanel data={data} now={later}/>);
  assert.match(html,/Expired observation/);assert.match(html,/complete current portfolio valuation.*unavailable/);
  for(const price of ['$1,980.00','-$20.00','$490.00','49.49%'])assert.ok(!html.includes(price),price);
  assert.ok(html.includes('Planning cash $1,000.00 is unchanged'));
});
test('partial, future timestamp, unavailable and corrupted expiry suppress aggregate and current price claims',()=>{
  for(const [report,clock,unavailable] of [[{...risk,status:'partial'},now,false],[risk,Date.parse('2026-10-22T15:29:00-04:00'),false],[risk,now,true],[{...risk,expires_at:'invalid'},now,false]] as const){
    const html=renderToStaticMarkup(<IntradayRiskPanel data={{...data,intraday_portfolio_risk:report}} now={clock} unavailable={unavailable}/>);
    assert.doesNotMatch(html,/Validated observation|\$1,980\.00|\$490\.00/);
    assert.match(html,/complete current portfolio valuation.*unavailable/);
  }
});
test('legacy decisions show no invented intraday section and unknown cash is not zero',()=>{
  assert.equal(renderToStaticMarkup(<IntradayRiskPanel data={{} as Snapshot} now={now}/>),'');
  const html=renderToStaticMarkup(<IntradayRiskPanel data={{...data,intraday_portfolio_risk:{...risk,status:'unavailable',cash_usd:null,positions:[],dependencies:['SPY quote missing']}}} now={now}/>);
  assert.match(html,/Planning cash Unverified/);assert.match(html,/SPY quote missing/);assert.doesNotMatch(html,/\$0\.00/);
});

test('client expiry also withdraws retained price-crossing labels before the next API poll',()=>{
  const crossing={ticker:'SPY',kind:'recorded_stop_review',condition:'Existing stop reference crossed.',status:'price_condition_met_reassessment_required',reference_price:495,observed_price:490};
  const report={...risk,plan_conditions:[crossing],reassessment_triggers:[crossing]};
  const fresh=renderToStaticMarkup(<IntradayRiskPanel data={{...data,intraday_portfolio_risk:report}} now={now}/>);
  assert.match(fresh,/Reference \$495\.00; observed \$490\.00/);
  const stale=renderToStaticMarkup(<IntradayRiskPanel data={{...data,intraday_portfolio_risk:report}} now={Date.parse(risk.expires_at!)}/>);
  assert.match(stale,/price-dependent condition is unverified at the current clock/);
  assert.doesNotMatch(stale,/Existing stop reference crossed|price condition met|\$495\.00|\$490\.00/);
});

test('original numerical tactical limits are visible without treating portfolio price change as a new loss budget',()=>{
  const report={...risk,tactical_limits:{ordinary_risk_pct:0.5,event_risk_pct:0.25,combined_risk_pct:2,max_position_pct:5,min_reward_to_risk:2,existing_planned_risk_usd:0,combined_planned_risk_pct:0,combined_status:'within_existing_budget'}};
  const html=renderToStaticMarkup(<IntradayRiskPanel data={{...data,intraday_portfolio_risk:report}} now={now}/>);
  for(const value of ['Ordinary risk 0.50%','event risk 0.25%','combined risk 2.00%','position maximum 5.00%','minimum reward/risk 2R','Recorded planned tactical loss $0.00'])assert.ok(html.includes(value),value);
  assert.doesNotMatch(html,/portfolio loss threshold|2% loss limit/);
  const expired=renderToStaticMarkup(<IntradayRiskPanel data={{...data,intraday_portfolio_risk:report}} now={Date.parse(risk.expires_at!)}/>);
  assert.match(expired,/Current tactical exposure relative to marked value is unverified/);
  assert.doesNotMatch(expired,/Recorded planned tactical loss \$0\.00/);
});
