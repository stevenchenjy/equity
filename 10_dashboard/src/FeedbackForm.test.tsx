import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import {FeedbackForm,FeedbackReceipt,readFeedbackSnapshot} from './App';
import {defaults, editableFeedback, matchingOrders, orderLabel} from './domain';
import type {FeedbackStatus, FormalRecord, Snapshot} from './domain';

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
