import test from 'node:test';
import assert from 'node:assert/strict';
import { defaults } from './domain';
import type { Snapshot } from './domain';
import { errorCode, preparePreview, requestJSON, waitForResearch } from './feedbackRequest';
import type { RequestPayload, Preview } from './feedbackRequest';

const busy=()=>Object.assign(new Error('research busy'),{code:'runtime_refresh_in_progress'});
const payload=():RequestPayload=>({request_id:'same-original-request',feedback:{...defaults('XYZ','2026-10-16'),shares:'1',amount:'50'},account_version:'old',snapshot_id:'old',plan:null});
const snapshot=(account_version='after-first-fill')=>({schema_version:'equity_dashboard_snapshot_v1',account_version,snapshot_id:'current-'+account_version,plans:[],account:{cash_available:900}} as unknown as Snapshot);
const preview:Preview={missing:[],changes:{cash_before:900,cash_after:850,ticker:'XYZ',shares_before:0,shares_after:1,fill_price:50,holdings_after:[]},preview_hash:'verified-preview'};
const options=()=>({signal:new AbortController().signal,onWaiting:()=>{},delay:async()=>{}});

test('next fill waits for the first refresh then previews against accepted cash without saving',async()=>{
  let reads=0,previews=0,waits=0;
  const original=payload();
  const result=await preparePreview(original,async()=>{if(++reads<3)throw busy();return snapshot()},async p=>{
    previews++;
    assert.equal(p.account_version,'after-first-fill');assert.equal(p.snapshot_id,'current-after-first-fill');
    assert.deepEqual(p.feedback,original.feedback);assert.equal(p.request_id,original.request_id);
    return preview;
  },{...options(),onWaiting:()=>{waits++}});
  assert.equal(previews,1);assert.equal(waits,2);assert.equal(reads,3);
  assert.equal(result.preview.changes?.cash_before,900);assert.equal(result.payload.preview_hash,'verified-preview');
  assert.equal(original.account_version,'old');
});

test('a lock starting between snapshot and preview re-reads the account after release',async()=>{
  let reads=0,calls=0;
  const result=await preparePreview(payload(),async()=>snapshot(String(++reads)),async p=>{
    if(++calls===1)throw busy();
    assert.equal(p.account_version,'2');return preview;
  },options());
  assert.equal(reads,2);assert.equal(result.payload.account_version,'2');
});

test('confirmed submission retries the identical request and stops at its saved receipt',async()=>{
  const submitted={...payload(),preview_hash:'owner-confirmed'};
  const before=JSON.stringify(submitted);let calls=0;
  const result=await waitForResearch(async()=>{
    assert.equal(JSON.stringify(submitted),before);
    if(++calls<3)throw busy();
    return {id:submitted.request_id,stage:'applied'};
  },options());
  assert.equal(calls,3);assert.equal(result.id,submitted.request_id);
});

test('real account conflicts and unknown network outcomes are never retried or rebased',async()=>{
  for(const error of [Object.assign(new Error('changed'),{code:'account_version_changed'}),new TypeError('network lost')]){
    let calls=0;
    await assert.rejects(waitForResearch(async()=>{calls++;throw error},options()),e=>e===error);
    assert.equal(calls,1);
  }
});

test('waiting is bounded and an explicit stop prevents another request',async()=>{
  let calls=0;
  await assert.rejects(waitForResearch(async()=>{calls++;throw busy()},{...options(),attempts:2}),/输入已保留/);
  assert.equal(calls,2);
  const controller=new AbortController();calls=0;
  await assert.rejects(waitForResearch(async()=>{calls++;throw busy()},{...options(),signal:controller.signal,delay:async()=>controller.abort()}),e=>e instanceof Error&&e.name==='AbortError');
  assert.equal(calls,1);
});

test('leaving during a snapshot read cannot start an abandoned preview',async()=>{
  const controller=new AbortController();let previews=0;
  await assert.rejects(preparePreview(payload(),async()=>{controller.abort();return snapshot()},async()=>{previews++;return preview},{...options(),signal:controller.signal}),e=>e instanceof Error&&e.name==='AbortError');
  assert.equal(previews,0);
});

test('busy status reports actual elapsed time without changing the original request',async()=>{
  const originalNow=Date.now;let now=1000,calls=0;const elapsed:number[]=[];
  try {
    Date.now=()=>now;
    const result=await waitForResearch(async()=>{if(++calls<3)throw busy();return 'saved'},
      {...options(),onWaiting:seconds=>elapsed.push(seconds),delay:async()=>{now+=3000}});
    assert.equal(result,'saved');assert.deepEqual(elapsed,[0,3]);
  } finally {Date.now=originalNow}
});

test('a stalled fetch is bounded even when the network implementation ignores abort',async()=>{
  const originalFetch=globalThis.fetch;let requestSignal:AbortSignal|undefined;
  try {
    globalThis.fetch=async(_input,init)=>{requestSignal=init?.signal??undefined;return new Promise<Response>(()=>{})};
    await assert.rejects(requestJSON('/api/feedback/snapshot',{}, {timeoutMs:15}),e=>errorCode(e)==='request_timeout');
    assert.equal(requestSignal?.aborted,true);
  } finally {globalThis.fetch=originalFetch}
});

test('a response with a stalled JSON body has the same finite deadline',async()=>{
  const originalFetch=globalThis.fetch;
  try {
    globalThis.fetch=async()=>({ok:true,status:200,json:()=>new Promise(()=>{})}) as Response;
    await assert.rejects(requestJSON('/api/snapshot',{}, {timeoutMs:15}),e=>errorCode(e)==='request_timeout');
  } finally {globalThis.fetch=originalFetch}
});

test('timed-out confirmed saves retain the identical original payload and are not retried',async()=>{
  const originalFetch=globalThis.fetch,submitted={...payload(),preview_hash:'owner-confirmed'};
  const original=JSON.stringify(submitted);let calls=0;
  try {
    globalThis.fetch=async(_input,init)=>{calls++;assert.equal(init?.body,original);return new Promise<Response>(()=>{})};
    await assert.rejects(waitForResearch(()=>requestJSON('/api/feedback',{method:'POST',body:JSON.stringify(submitted)},{timeoutMs:15,mutation:true}),options()),
      e=>errorCode(e)==='feedback_result_unknown_retry_same_request');
    assert.equal(calls,1);assert.equal(JSON.stringify(submitted),original);
  } finally {globalThis.fetch=originalFetch}
});

test('stop cancels a hanging preview read before any preview or save request',async()=>{
  const originalFetch=globalThis.fetch,controller=new AbortController();let previews=0,calls=0;
  try {
    globalThis.fetch=async()=>{calls++;return new Promise<Response>(()=>{})};
    const task=preparePreview(payload(),async signal=>{
      const result=await requestJSON<Snapshot>('/api/feedback/snapshot',{}, {signal,timeoutMs:1000});return result.body;
    },async()=>{previews++;return preview},{...options(),signal:controller.signal});
    controller.abort();
    await assert.rejects(task,e=>e instanceof Error&&e.name==='AbortError');
    assert.equal(calls,1);assert.equal(previews,0);
  } finally {globalThis.fetch=originalFetch}
});

test('an already stopped request cannot start network activity',async()=>{
  const originalFetch=globalThis.fetch,controller=new AbortController();let calls=0;controller.abort();
  try {
    globalThis.fetch=async()=>{calls++;throw new Error('must not run')};
    await assert.rejects(requestJSON('/api/feedback/snapshot',{}, {signal:controller.signal}),e=>e instanceof Error&&e.name==='AbortError');
    assert.equal(calls,0);
  } finally {globalThis.fetch=originalFetch}
});

test('preview propagates one abort signal through the lightweight read and preview',async()=>{
  const controller=new AbortController();
  const result=await preparePreview(payload(),async signal=>{assert.equal(signal,controller.signal);return snapshot()},async(p,signal)=>{
    assert.equal(signal,controller.signal);assert.equal(p.request_id,'same-original-request');return preview;
  },{...options(),signal:controller.signal});
  assert.equal(result.payload.preview_hash,'verified-preview');
});
