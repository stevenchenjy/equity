import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import ResearchDetails,{matchingResearchDetails,readResearchDetails,projectResearchDetails} from './ResearchDetails';
import type {ResearchResponse} from './ResearchDetails';
import type {Snapshot} from './domain';
import {readFeedbackSnapshot} from './App';
import {errorCode} from './feedbackRequest';

const data={account_version:'current-account',snapshot_id:'current-publication'} as Snapshot;
const response={schema_version:'equity_dashboard_research_response_v1',account_version:data.account_version,snapshot_id:data.snapshot_id,
  earnings_events:{schema_version:'equity_earnings_event_view_v1',status:'ready',generated_at:'2026-10-30T20:00:00-04:00',
    coverage:{},capital_authority:false,automatic_action_allowed:false,events:[]},strategy_framework:null} as ResearchResponse;

test('optional earnings sources are not requested during primary account/decision rendering',()=>{
  const html=renderToStaticMarkup(<ResearchDetails data={data} now={Date.now()}/>);
  assert.match(html,/Load detailed research/);
  assert.match(html,/load separately from your account and decision cards/);
  assert.doesNotMatch(html,/eligible_conditional_plan|Validating earnings sources/);
});

test('deferred reports require both exact account and decision identities',()=>{
  assert.equal(matchingResearchDetails(response,data),response);
  for(const changes of [{account_version:'prior-account'},{snapshot_id:'prior-publication'},{schema_version:'unknown'}]){
    assert.equal(matchingResearchDetails({...response,...changes} as ResearchResponse,data),null);
  }
});

test('deferred positive statuses follow the primary capital contract and clock, without mutating retained research',()=>{
  const now=Date.parse('2026-10-30T10:00:00-04:00');
  const draft={side:'buy',entry_window:{starts_at:'2026-10-30T09:30:00-04:00',ends_at:'2026-10-30T10:30:00-04:00'}};
  const current={...data,capital_decision_status:'current',capital_decision:{decisions:[{ticker:'ABC',shares:1,order_draft:draft}]}} as Snapshot;
  const positive={...response,strategy_framework:{schema_version:'equity_strategy_framework_v1',decisions:[{ticker:'ABC',classification:'valid_action',eligible_quantity:1}]},
    earnings_events:{...response.earnings_events!,events:[{ticker:'ABC',status:'eligible_conditional_plan',timing:'pre_event',research_deadline_at:'2026-10-30T16:00:00-04:00'}]}} as ResearchResponse;
  const original=JSON.stringify(positive);
  assert.equal(projectResearchDetails(positive,current,now)?.strategy_framework?.decisions[0].classification,'valid_action');
  for(const [snapshot,clock] of [[{...current,capital_decision:null},now],[{...current,capital_decision_status:'recompose_required'},now],[current,Date.parse(draft.entry_window.ends_at)]] as const){
    const projected=projectResearchDetails(positive,snapshot,clock)!;
    assert.equal(projected.strategy_framework?.decisions[0].classification,'data_unavailable');
    assert.equal(projected.strategy_framework?.decisions[0].eligible_quantity,0);
    assert.equal(projected.earnings_events?.events[0].status,'research_in_progress');
  }
  assert.equal(JSON.stringify(positive),original);
});

test('a stalled optional research read can time out while account intake remains available',async context=>{
  context.mock.timers.enable({apis:['setTimeout']});const original=globalThis.fetch;const calls:string[]=[];
  try{
    globalThis.fetch=async input=>{
      calls.push(String(input));
      if(String(input)==='/api/research-details')return {ok:true,json:()=>new Promise(()=>{})} as Response;
      return new Response(JSON.stringify({...data,schema_version:'equity_dashboard_snapshot_v1',feedback_context_only:true}),{status:200});
    };
    const earnings=readResearchDetails(new AbortController().signal).then(()=>null,error=>error);
    assert.equal((await readFeedbackSnapshot()).account_version,data.account_version);
    context.mock.timers.tick(90000);
    assert.equal(errorCode(await earnings),'request_timeout');
    assert.deepEqual(calls,['/api/research-details','/api/feedback/snapshot']);
  }finally{globalThis.fetch=original;context.mock.timers.reset()}
});

test('optional research failure never returns a retained positive report',async()=>{
  const original=globalThis.fetch;
  try{
    globalThis.fetch=async()=>new Response(JSON.stringify({error:'snapshot_changed_during_read'}),{status:503});
    await assert.rejects(readResearchDetails(new AbortController().signal),/Account records and decision cards remain available/);
  }finally{globalThis.fetch=original}
});
