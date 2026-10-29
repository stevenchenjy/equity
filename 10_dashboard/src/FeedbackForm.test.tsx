import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import {FeedbackForm,FeedbackReceipt,FeedbackDate,ResearchReadStatus,readCurrentSnapshot,readFeedbackSnapshot,currentFeedbackRecord,pendingFeedbackForEdit} from './App';
import {defaults, editableFeedback, matchingOrders, orderLabel} from './domain';
import type {FeedbackStatus, FormalRecord, Snapshot} from './domain';
import {errorCode,requestJSON} from './feedbackRequest';

const data={server_now:'2026-10-17T10:00:00-04:00',account:{cash_available:4000},positions:[],candidates:[],plans:[],orders:{rows:[]}} as unknown as Snapshot;
function markup(status:FeedbackStatus='filled',wide=false,rows:Record<string,unknown>[]=[]){
  return renderToStaticMarkup(<FeedbackForm data={{...data,orders:{...data.orders,rows}}} ticker="ABC" initialStatus={status} wide={wide} onSaved={()=>{}} onFormalSaved={()=>{}} onDirty={()=>{}} storageError=""/>);
}
test('quick and full entry forms remove unnecessary fields and repeated instructions',()=>{
  for(const wide of [false,true])for(const status of ['filled','partial','pending','cancelled','account'] as FeedbackStatus[]){
    const html=markup(status,wide);
    assert.doesNotMatch(html,/金额口径|已确认费用|大致时间|type="time"|订单编号|股数是本次新增成交量|连续部分成交请逐次填写|真实操作请用正式登记/);
    assert.match(html,/日期/);assert.match(html,/预览登记结果/);
    if(status==='filled'||status==='partial'){assert.match(html,/成交总额（USD）/);assert.match(html,/股数/);assert.doesNotMatch(html,/订单类型|name="fees"|name="amount_mode"/);}
  }
});
test('new entries use owner-confirmed zero fees and dates without inventing a time',()=>{
  const f=defaults('ABC','2026-10-17');
  assert.equal(f.entry_mode,'simple_total');assert.equal(f.amount_mode,'net');assert.equal(f.fee_status,'known');assert.equal(f.fees,'0');assert.equal(f.time,'');assert.equal(f.order_type,'UNSPECIFIED');
});
test('default fill has exactly five visible inputs; optional scenarios stay collapsed',()=>{
  for(const wide of [false,true]){
    const html=markup('filled',wide);
    assert.match(html,/<details class="feedback-options"><summary>其他情况/);
    const visible=html.replace(/<details class="feedback-options">[\s\S]*?<\/details>/,'');
    assert.deepEqual([...visible.matchAll(/<(?:input|select|textarea)\b[^>]*name="([^"]+)"/g)].map(m=>m[1]),['ticker','side','shares','amount','date']);
    assert.doesNotMatch(visible,/订单类型|执行状态|备注|试填|尚未计入|费用|金额口径|对应订单/);
  }
  assert.match(markup('pending'),/订单类型/);
  assert.match(markup('partial'),/剩余挂单股数/);
});
test('order choices use readable terms without asking for raw identifiers',()=>{
  const row={order_id:'opaque-private-order-123',ticker:'ABC',side:'buy',status:'partially_filled',remaining_quantity:'2',order_type:'LIMIT',limit_price:'99',time_in_force:'DAY'};
  assert.doesNotMatch(markup('partial',false,[row]),/name="linked_order"/);
  const html=markup('partial',false,[row,{...row,order_id:'another-private-id',limit_price:'98'}]);
  assert.match(html,/对应挂单/);assert.match(html,/剩余 2 股/);assert.match(html,/LIMIT \$99/);
  assert.doesNotMatch(orderLabel(row),/opaque-private/);
  assert.equal(matchingOrders(defaults('ABC'),[row,{...row,side:'sell'},{...row,record_scope:'unresolved_historical_reservation'},{...row,status:'filled'}]).length,1);
});
test('editing a historical fee or amount basis preserves its economic interpretation',()=>{
  const old={...defaults('ABC'),entry_mode:undefined,amount_mode:'net' as const,amount:'201',fee_status:'known' as const,fees:'1',time:'13:45'};
  const editable=editableFeedback(old);
  assert.equal(editable.entry_mode,undefined);assert.equal(editable.amount_mode,'net');assert.equal(editable.amount,'201');assert.equal(editable.fees,'1');assert.equal(editable.time,'13:45');
  assert.equal(editable.not_in_account,false);
});

test('accepted receipt follows durable research status without confusing failure with a failed save',()=>{
  const saved={id:'first-fill',revision:2,stage:'applied',production_effect:true,missing:[],research_status:'queued'} as unknown as FormalRecord;
  for(const [status,label] of [['running','正在重算'],['passed','重算完成'],['failed','重算失败，可重试'],['degraded','重算有缺口']] as const){
    const html=renderToStaticMarkup(<FeedbackReceipt saved={saved} records={[{...saved,research_status:status}]}/>);
    assert.match(html,/账户记录已应用/);assert.ok(html.includes(label));assert.doesNotMatch(html,/等待重算/);
  }
  const fallback=renderToStaticMarkup(<FeedbackReceipt saved={saved} records={[{...saved,id:'other-fill',research_status:'passed'},{...saved,revision:1,research_status:'passed'}]}/>);
  assert.match(fallback,/等待重算/);
});

test('a saved pending edit has recovery controls and does not imply that research applied the account',()=>{
  const saved={id:'synthetic-pending-record',revision:2,stage:'pending',production_effect:false,
    missing:['A later transaction is already accounted for; reconcile the current account first.'],research_status:'passed'} as unknown as FormalRecord;
  const html=renderToStaticMarkup(<FeedbackReceipt saved={saved} records={[]} onEditPending={()=>{}} onViewHistory={()=>{}}/>);
  assert.match(html,/Record saved — account not updated/);
  assert.match(html,/It has not changed cash or shares/);
  assert.match(html,/Research refresh completed; account application is still pending/);
  assert.match(html,/<button class="secondary" type="button">Review saved record<\/button>/);
  assert.match(html,/<button class="text-button" type="button">View saved history<\/button>/);
  assert.match(html,/Record synthetic-pending-record · revision 2/);
  assert.doesNotMatch(html,/账户记录已应用|处理中|disabled/);
});

test('resuming acknowledged pending feedback retains its record identity and latest durable revision',()=>{
  const saved={id:'saved-record',revision:2,stage:'pending'} as FormalRecord;
  const newer={...saved,revision:4};
  const records=[{...saved,revision:3},{...newer,id:'unrelated-record',revision:20},newer];
  assert.equal(currentFeedbackRecord(saved,records),newer);
  assert.equal(pendingFeedbackForEdit(saved,records),newer);
  assert.equal(pendingFeedbackForEdit(saved,records)?.id,'saved-record');
  assert.equal(pendingFeedbackForEdit(saved,records)?.revision,4);
  assert.equal(pendingFeedbackForEdit(saved,[{...saved,revision:1}]),saved);
});

test('a later applied receipt cannot be reopened as a pending edit',()=>{
  const saved={id:'saved-record',revision:2,stage:'pending',production_effect:false,missing:['old missing detail'],research_status:'passed'} as unknown as FormalRecord;
  const applied={...saved,revision:3,stage:'applied',production_effect:true,missing:[]} as FormalRecord;
  assert.equal(pendingFeedbackForEdit(saved,[applied]),null);
  const html=renderToStaticMarkup(<FeedbackReceipt saved={saved} records={[applied]} onEditPending={()=>{}} onViewHistory={()=>{}}/>);
  assert.match(html,/账户记录已应用/);
  assert.match(html,/View saved history/);
  assert.doesNotMatch(html,/Review saved record|account application is still pending/);
});

test('owner-corrected execution date is visible without rewriting the original feedback date',()=>{
  const record={id:'old-applied-record',revision:1,feedback:{...defaults('TST','2026-09-10'),shares:'1',amount:'20'},effective_date:'2026-09-15',
    execution_date_correction:{original_date:'2026-09-10',corrected_date:'2026-09-15',record_id:'owner-reconciliation',revision:3,recorded_at:'2026-10-29T11:00:00-04:00',reason:'Owner corrected the date of the existing purchase.',owner_source:{path:'private/owner-receipt.json',sha256:'a'.repeat(64)}}} as FormalRecord;
  const original=JSON.stringify(record.feedback);
  const html=renderToStaticMarkup(<FeedbackDate record={record}/>);
  assert.match(html,/Event date 2026-09-15/);
  assert.match(html,/Owner-corrected execution date/);
  assert.match(html,/2026-09-10 → 2026-09-15/);
  assert.match(html,/original saved date remains/);
  assert.match(html,/Correction record owner-reconciliation · revision 3/);
  assert.equal(JSON.stringify(record.feedback),original);
  const old=renderToStaticMarkup(<FeedbackDate record={{...record,effective_date:undefined,execution_date_correction:undefined}}/>);
  assert.match(old,/Event date 2026-09-10/);assert.doesNotMatch(old,/Owner-corrected/);
});

test('feedback bootstrap reads only the lightweight committed-account endpoint',async()=>{
  const originalFetch=globalThis.fetch;const calls:string[]=[];
  const account={...data,schema_version:'equity_dashboard_snapshot_v1',feedback_context_only:true,account_version:'new-committed-account',snapshot_id:'exact-current-decision',research_ready:false};
  try {
    globalThis.fetch=async input=>{
      calls.push(String(input));
      // The slow research route must never be a prerequisite for intake.
      if(String(input)==='/api/snapshot')return new Promise<Response>(()=>{});
      assert.equal(String(input),'/api/feedback/snapshot');
      return new Response(JSON.stringify(account),{status:200});
    };
    const current=await readFeedbackSnapshot();
    assert.deepEqual(calls,['/api/feedback/snapshot']);assert.equal(current.account_version,'new-committed-account');
    for(const wide of [false,true]){
      const html=renderToStaticMarkup(<FeedbackForm data={current} ticker="ABC" wide={wide} onSaved={()=>{}} onFormalSaved={()=>{}} onDirty={()=>{}} storageError=""/>);
      assert.match(html,/<button class="primary save-button" type="submit">预览登记结果/);
      assert.doesNotMatch(html,/正式记录已接纳|核对本次登记/);
    }
  } finally {globalThis.fetch=originalFetch}
});

test('an unverified account response cannot enable a new preview',async()=>{
  const originalFetch=globalThis.fetch;
  try {
    globalThis.fetch=async()=>new Response(JSON.stringify({...data,schema_version:'equity_dashboard_snapshot_v1'}),{status:200});
    await assert.rejects(readFeedbackSnapshot(),/account preview format does not match/);
    const html=renderToStaticMarkup(<FeedbackForm data={null} ticker="ABC" onSaved={()=>{}} onFormalSaved={()=>{}} onDirty={()=>{}} storageError=""/>);
    assert.match(html,/<button class="primary save-button" type="submit" disabled="">预览登记结果/);
  } finally {globalThis.fetch=originalFetch}
});

test('healthy research slower than the intake deadline can finish without blocking account intake',async context=>{
  const originalFetch=globalThis.fetch;context.mock.timers.enable({apis:['setTimeout']});
  const research={...data,schema_version:'equity_dashboard_snapshot_v1',snapshot_id:'slow-valid-research'};
  const account={...research,feedback_context_only:true,snapshot_id:'fast-committed-account'};
  let researchSettled=false;
  try {
    globalThis.fetch=async input=>String(input)==='/api/snapshot'
      ? new Promise<Response>(resolve=>setTimeout(()=>resolve(new Response(JSON.stringify(research),{status:200})),33727))
      : new Response(JSON.stringify(account),{status:200});
    const result=readCurrentSnapshot().then(value=>{researchSettled=true;return {value,error:null}},error=>{researchSettled=true;return {value:null,error}});
    assert.equal((await readFeedbackSnapshot()).snapshot_id,'fast-committed-account');
    context.mock.timers.tick(15000);
    for(let i=0;i<6;i++)await Promise.resolve();
    assert.equal(researchSettled,false);
    context.mock.timers.tick(18727);
    const completed=await result;
    assert.equal(completed.error,null);assert.equal(completed.value?.snapshot_id,'slow-valid-research');
  } finally {globalThis.fetch=originalFetch;context.mock.timers.reset()}
});

test('only full research gets 90s; stalled intake and save bodies retain the 15s boundary',async context=>{
  const originalFetch=globalThis.fetch;context.mock.timers.enable({apis:['setTimeout']});
  const cases=[
    {url:'/api/snapshot',limit:90000,load:()=>readCurrentSnapshot(),code:'request_timeout'},
    {url:'/api/feedback/snapshot',limit:15000,load:()=>readFeedbackSnapshot(),code:'request_timeout'},
    {url:'/api/feedback',limit:15000,load:()=>requestJSON('/api/feedback',{method:'POST',body:'synthetic-original-request'},{mutation:true}),code:'feedback_result_unknown_retry_same_request'},
  ];
  try {
    for(const item of cases){
      let signal:AbortSignal|null|undefined;let settled=false;let calls=0;
      globalThis.fetch=async(input,init)=>{calls++;assert.equal(String(input),item.url);signal=init?.signal;return {ok:true,status:200,json:()=>new Promise(()=>{})} as Response};
      const result=item.load().then(()=>{settled=true;return null},error=>{settled=true;return error});
      context.mock.timers.tick(item.limit-1);
      for(let i=0;i<6;i++)await Promise.resolve();
      assert.equal(settled,false);
      context.mock.timers.tick(1);
      assert.equal(errorCode(await result),item.code);assert.equal(signal?.aborted,true);assert.equal(calls,1);
    }
  } finally {globalThis.fetch=originalFetch;context.mock.timers.reset()}
});

test('a research read failure does not label available feedback intake as broken',()=>{
  for(const runtimeUpdating of [false,true]){
    const html=renderToStaticMarkup(<ResearchReadStatus feedbackPage accountAvailable error="Research request timed out" runtimeUpdating={runtimeUpdating} hasResearchData={false}/>);
    assert.match(html,/role="status"/);assert.match(html,/Research view has not updated\. Your recorded account is available for action logging\./);
    assert.doesNotMatch(html,/role="alert"|error-banner|当前视图未能更新/);
  }
  for(const [feedbackPage,accountAvailable] of [[false,true],[true,false]]){
    const html=renderToStaticMarkup(<ResearchReadStatus feedbackPage={feedbackPage} accountAvailable={accountAvailable} error="Research request timed out" runtimeUpdating={false} hasResearchData={false}/>);
    assert.match(html,/role="alert"/);assert.match(html,/Research request timed out/);
    assert.doesNotMatch(html,/Your recorded account is available/);
  }
  assert.equal(renderToStaticMarkup(<ResearchReadStatus feedbackPage accountAvailable error="" runtimeUpdating={false} hasResearchData={false}/>),'');
});
