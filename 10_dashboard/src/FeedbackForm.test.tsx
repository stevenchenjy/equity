import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import {FeedbackForm} from './App';
import {defaults, editableFeedback, matchingOrders, orderLabel} from './domain';
import type {FeedbackStatus, Snapshot} from './domain';

const data={server_now:'2026-10-17T10:00:00-04:00',account:{cash_available:4000},positions:[],candidates:[],plans:[],orders:{rows:[]}} as unknown as Snapshot;
function markup(status:FeedbackStatus='filled',wide=false,rows:Record<string,unknown>[]=[]){
  return renderToStaticMarkup(<FeedbackForm data={{...data,orders:{...data.orders,rows}}} ticker="ABC" initialStatus={status} wide={wide} onSaved={()=>{}} onFormalSaved={()=>{}} onDirty={()=>{}} storageError=""/>);
}
test('quick and full entry forms remove unnecessary fields and repeated instructions',()=>{
  for(const wide of [false,true])for(const status of ['filled','partial','pending','cancelled','account'] as FeedbackStatus[]){
    const html=markup(status,wide);
    assert.doesNotMatch(html,/金额口径|已确认费用|大致时间|type="time"|订单编号|股数是本次新增成交量|连续部分成交请逐次填写|真实操作请用正式登记/);
    assert.match(html,/日期/);assert.match(html,/预览登记结果/);
    if(status==='filled'||status==='partial'){assert.match(html,/成交单价/);assert.match(html,/成交股数/);assert.doesNotMatch(html,/name="fees"|name="amount_mode"/);}
  }
});
test('new entries use owner-confirmed zero fees and dates without inventing a time',()=>{
  const f=defaults('ABC','2026-10-17');
  assert.equal(f.entry_mode,'simple');assert.equal(f.amount_mode,'price');assert.equal(f.fee_status,'known');assert.equal(f.fees,'0');assert.equal(f.time,'');
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
