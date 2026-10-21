import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import EarningsEvents, {earningsPage, orderedUpcoming, EARNINGS_PAGE_SIZE} from './EarningsEvents';
import {CapitalActions} from './CapitalActions';
import type {EarningsEvent, EarningsEventView, Snapshot} from './domain';

const event:EarningsEvent={event_id:'independent-event',ticker:'LOWM',company_name:'Low momentum issuer',event_date:'2026-10-22',session:'after_close',event_at:'2026-10-22T16:00:00-04:00',research_deadline_at:'2026-10-22T09:30:00-04:00',first_detected_at:'2026-10-21T08:00:00-04:00',timing:'pre_event',status:'awaiting_research',date_confidence:'exchange_calendar_estimate',research_state:'not_reviewed',blockers:['Expectations and downside valuation are incomplete'],next_step:'Complete the company case before the announcement.',sources:[{source_url:'https://www.nasdaq.com/market-activity/earnings',sha256:'a'.repeat(64),path:'retained/source.json',available_at:'2026-10-21T08:00:00-04:00'}]};
const report:EarningsEventView={schema_version:'equity_earnings_event_view_v1',generated_at:'2026-10-21T09:00:00-04:00',status:'ready',coverage:{scope:'US exchange calendar',horizon_start:'2026-10-21',horizon_end:'2026-11-04',days_requested:15,days_verified:15,failed_dates:[]},events:[event],capital_authority:false,automatic_action_allowed:false};
const data={positions:[],earnings_events:report,capital_decision:{action:'NO_NEW_POSITION',decisions:[],global_blockers:[]}} as unknown as Snapshot;
test('independent event panel displays deadline, estimate and exact research dependency separately from action cards',()=>{
  const html=renderToStaticMarkup(<><CapitalActions data={data}/><EarningsEvents data={data}/></>);
  for(const expected of ['Upcoming earnings research','LOWM','Awaiting research','9:30 AM ET','15/15 dates verified','Exchange estimate','Expectations and downside valuation are incomplete','Evidence and timing','First detected'])assert.ok(html.includes(expected),expected);
  assert.ok(html.indexOf('今天做什么')<html.indexOf('Upcoming earnings research'));
  assert.doesNotMatch(html,/BUY LIMIT|capital-buy/);
});
test('retained eligible label is suppressed while refreshing, stale or lacking a positive capital contract',()=>{
  for(const [unavailable,status] of [[true,'ready'],[false,'stale'],[false,'ready']] as const){
    const value={...data,earnings_events:{...report,status,events:[{...event,status:'eligible_conditional_plan'}]}} as Snapshot;
    const html=renderToStaticMarkup(<EarningsEvents data={value} unavailable={unavailable}/>);
    assert.doesNotMatch(html,/Eligible conditional plan — see action cards/);
    assert.match(html,/current conditional plan unverified/);
    assert.doesNotMatch(html,/BUY LIMIT|capital-buy/);
  }
});
test('a positive current capital plan may be referenced without generating another action card',()=>{
  const value={...data,earnings_events:{...report,events:[{...event,status:'eligible_conditional_plan'}]},capital_decision:{...data.capital_decision!,decisions:[{ticker:'LOWM',decision:'ACTIONABLE_BUY',shares:1,order_draft:{side:'buy'}}]}} as Snapshot;
  const html=renderToStaticMarkup(<EarningsEvents data={value}/>);
  assert.match(html,/Eligible conditional plan — see action cards/);
  assert.doesNotMatch(html,/BUY LIMIT|capital-buy/);
});
test('all retained events are discoverable and failed dates remain explicit',()=>{
  const value={...data,earnings_events:{...report,status:'partial',coverage:{...report.coverage,days_verified:14,failed_dates:['2026-10-24']},events:Array.from({length:9},(_,i)=>({...event,event_id:String(i),ticker:`EV${i}`}))}} as Snapshot;
  const html=renderToStaticMarkup(<EarningsEvents data={value}/>);
  assert.match(html,/Browse all 9 upcoming events/);assert.match(html,/9 retained events/);assert.match(html,/14\/15 dates verified/);assert.match(html,/2026-10-24/);assert.match(html,/aria-expanded="false"/);
  assert.ok(html.includes('EV2'));assert.ok(!html.includes('EV3'));
});
test('more than100 events retain every page while past events cannot crowd out impending deadlines',()=>{
  const elapsed=Array.from({length:150},(_,i)=>({...event,event_id:`old-${i}`,ticker:`OLD${i}`,event_date:'2026-10-20',timing:'post_event',status:'elapsed_unreviewed'} as EarningsEvent));
  const future=Array.from({length:123},(_,i)=>({...event,event_id:`new-${i}`,ticker:`NEW${i}`,research_deadline_at:new Date(Date.parse('2026-10-22T09:00:00-04:00')+i*60000).toISOString()}));
  const events=[...elapsed,...[...future].reverse()];
  const upcoming=orderedUpcoming(events);
  assert.equal(upcoming.length,123);assert.equal(upcoming[0].ticker,'NEW0');assert.equal(upcoming[122].ticker,'NEW122');
  assert.equal(EARNINGS_PAGE_SIZE,50);
  assert.deepEqual([0,1,2].map(page=>earningsPage(upcoming,page).length),[50,50,23]);
  assert.deepEqual([0,1,2].flatMap(page=>earningsPage(upcoming,page)).map(row=>row.event_id),future.map(row=>row.event_id));
  assert.equal(earningsPage(upcoming,99).length,23);
  const value={...data,earnings_events:{...report,events}} as Snapshot;
  const html=renderToStaticMarkup(<EarningsEvents data={value}/>);
  assert.match(html,/273 retained events/);assert.match(html,/123 upcoming events/);assert.match(html,/Elapsed \/ other retained events \(150\)/);
  assert.ok(html.includes('NEW0'));assert.ok(!html.includes('OLD0'));assert.ok(!html.includes('NEW3'));
});
test('unknown or estimated release time does not masquerade as an exact midnight announcement',()=>{
  for(const session of ['time_unknown','after_close'] as const){
    const value={...data,earnings_events:{...report,events:[{...event,session,event_at:'2026-10-22T00:00:00-04:00'}]}} as Snapshot;
    const html=renderToStaticMarkup(<EarningsEvents data={value}/>);
    assert.match(html,/exact release time unconfirmed/);assert.doesNotMatch(html,/12:00 AM/);
    assert.match(html,/Research deadline/);assert.match(html,/9:30 AM ET/);
  }
});
test('completed current event reviews beyond100 pending leads appear first without changing capital action cards',()=>{
  const pending=Array.from({length:150},(_,i)=>({...event,event_id:`pending-${i}`,ticker:`PENDING${i}`}));
  const reviewed=['LRCX','META'].map(ticker=>({...event,event_id:ticker,ticker,status:'reviewed_without_entry' as const,event_date:'2026-10-23',research_deadline_at:'2026-10-23T09:30:00-04:00',next_step:'Reviewed event case: reject pre-event entry; downside valuation is insufficient.'}));
  const events=[...pending,...reviewed];
  const ordered=orderedUpcoming(events);
  assert.deepEqual(ordered.slice(0,2).map(row=>row.ticker),['LRCX','META']);
  assert.equal(ordered.length,152);
  const value={...data,earnings_events:{...report,events}} as Snapshot;
  const before=renderToStaticMarkup(<CapitalActions data={data}/>);
  const html=renderToStaticMarkup(<EarningsEvents data={value}/>);
  for(const expected of ['LRCX','META','Reviewed without entry','reject pre-event entry','reviewed outcomes first, then research deadline','Browse all 152 upcoming events'])assert.ok(html.includes(expected),expected);
  assert.ok(html.indexOf('LRCX')<html.indexOf('PENDING0'));
  assert.equal(renderToStaticMarkup(<CapitalActions data={value}/>),before);
  assert.doesNotMatch(html,/BUY LIMIT|capital-buy/);
});
test('expanded source-bound review preserves unknown and negative cases with safe official evidence links',()=>{
  const event_review={event_id:event.event_id,expectations_case:'Consensus expectations are unknown.',priced_in_assessment:'No evidence establishes that growth is priced in.',valuation_case:'Company-specific valuation is incomplete; do not enter.',downside_case:'Downside can exceed the planned loss.',recheck_condition:'Recheck only after sourced results and a completed valuation.',sources:[{source_url:'https://investor.atmeta.com/investor-news/',sha256:'b'.repeat(64),path:'meta.html'},{source_url:'javascript:alert(1)',sha256:'c'.repeat(64),path:'invalid'}]};
  const html=renderToStaticMarkup(<EarningsEvents data={{...data,earnings_events:{...report,events:[{...event,status:'reviewed_without_entry',event_review}]}}}/>);
  for(const point of [event_review.expectations_case,event_review.priced_in_assessment,event_review.valuation_case,event_review.downside_case,event_review.recheck_condition])assert.ok(html.includes(point),point);
  assert.match(html,/<details><summary>Evidence and timing<\/summary>[\s\S]*Source-bound earnings review/);
  assert.match(html,/href="https:\/\/investor.atmeta.com\/investor-news\/"/);
  assert.match(html,/Review source URL unverified/);assert.doesNotMatch(html,/href="javascript:/);
});
