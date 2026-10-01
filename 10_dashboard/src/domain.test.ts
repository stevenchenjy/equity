import assert from 'node:assert/strict';
import test from 'node:test';
import { appendRecord, defaults, editableFeedback, initialFeedback, matchesHistory, validStoredFeedback, planReference, expired, makeDemoRecord, parseRecords, validateFeedback } from './domain.ts';
import type { Plan, Snapshot, FormalRecord } from './domain.ts';

const at = new Date('2026-09-30T14:00:00-04:00');
test('Unknown fee stays unknown and creates an incomplete demo, even for a net amount', () => {
  const f = { ...defaults('ABC', '2026-09-30'), shares: '2', amount: '200', amount_mode: 'net' as const, time: '13:45' };
  const record = makeDemoRecord(f, null, 'event-1', at);
  assert.equal(record.production_effect, false);
  assert.equal(record.stage, 'demo_pending');
  assert.deepEqual(record.missing, ['费用']);
  assert.equal(record.feedback.fees, '');
  assert.equal(record.event_time_precision, 'approximate');
});
test('Explicit zero fee is valid, but fractional or negative share inputs are rejected', () => {
  const f = { ...defaults('ABC', '2026-09-30'), shares: '2', amount: '100', fee_status: 'known' as const, fees: '0' };
  assert.equal(makeDemoRecord(f, null, 'event-1', at).stage, 'demo_complete');
  assert.ok(validateFeedback({ ...f, shares: '1.5' }, '2026-09-30').errors.shares);
  assert.ok(validateFeedback({ ...f, amount: '-5' }, '2026-09-30').errors.amount);
});
test('Partial fill needs remaining inventory; cancelling a partially filled order keeps reconciliation pending', () => {
  const f = { ...defaults('ABC', '2026-09-30'), status: 'partial' as const, shares: '1', amount: '100', fee_status: 'known' as const, fees: '0' };
  assert.deepEqual(validateFeedback(f, '2026-09-30').missing, ['剩余挂单股数']);
  const cancel = { ...f, status: 'cancelled' as const, linked_order: 'order-1', prior_partial: true };
  assert.deepEqual(makeDemoRecord(cancel, null, 'event-2', at).missing, ['撤单前的部分成交记录']);
});
test('Changing a fill to a pending order strips old fill amounts instead of preserving assumed fills', () => {
  const f = { ...defaults('ABC', '2026-09-30'), status: 'pending' as const, shares: '1', amount: '100', fees: '5', fee_status: 'known' as const, order_price: '95' };
  const record = makeDemoRecord(f, null, 'event-1', at);
  assert.equal(record.feedback.amount, '');
  assert.equal(record.feedback.fees, '');
  assert.equal(record.feedback.order_price, '95');
});
test('An empty complete account snapshot represents an all-cash account in the demo', () => {
  const f = { ...defaults('ABC', '2026-09-30'), status: 'account' as const, cash: '1200', holdings: [], inventory_complete: true };
  assert.equal(makeDemoRecord(f, null, 'event-1', at).stage, 'demo_complete');
  assert.ok(validateFeedback({ ...f, holdings: [{ ticker: 'ABC', shares: '1' }, { ticker: 'ABC', shares: '2' }] }, '2026-09-30').errors['holding-1']);
});
test('Invalid dates and future feedback are rejected', () => {
  const f = { ...defaults('ABC', '2026-09-30'), status: 'skipped' as const };
  assert.ok(validateFeedback({ ...f, date: '2026-02-30' }, '2026-09-30').errors.date);
  assert.ok(validateFeedback({ ...f, date: '2026-10-01' }, '2026-09-30').errors.date);
});
test('Record IDs are idempotent and production-looking storage is refused', () => {
  const record = makeDemoRecord({ ...defaults('ABC', '2026-09-30'), status: 'skipped' }, null, 'event-1', at);
  assert.equal(appendRecord([record], record).length, 1);
  assert.throws(() => parseRecords(JSON.stringify([{ ...record, production_effect: true }])));
  assert.throws(() => parseRecords(JSON.stringify([{ ...record, plan: { plan_id: { unexpected: 'object' }, version: 1, record_hash: 'hash' } }])));
  assert.throws(() => parseRecords(JSON.stringify([{ ...record, feedback: { ...record.feedback, notes: {} } }])));
  assert.throws(() => parseRecords(JSON.stringify([record, record])));
  assert.throws(() => parseRecords('{'), /演示存储格式无效/);
  assert.deepEqual(parseRecords(JSON.stringify([record])), [record]);
});
test('Frontend hides a previously current plan as soon as its deadline arrives', () => {
  const plan = { status: 'current', expires_at: '2026-09-30T15:30:00-04:00' } as Plan;
  assert.equal(expired(plan, Date.parse('2026-09-30T15:29:59-04:00')), false);
  assert.equal(expired(plan, Date.parse('2026-09-30T15:30:00-04:00')), true);
  assert.equal(expired({...plan,expires_at:'invalid'},at.getTime()),true);
});

test('Account check prefill uses current facts but requires fresh owner confirmation',()=>{
  const data={server_now:'2026-09-30T23:59:00-04:00',account:{cash_available:123},positions:[{ticker:'SPY',shares:2}]} as Snapshot;
  const f=initialFeedback(data,'SPY','account');
  assert.equal(f.date,'2026-09-30');assert.equal(f.cash,'123');assert.equal(f.account_observed,false);
  assert.deepEqual(f.holdings,[{ticker:'SPY',shares:'2'}]);assert.equal(f.inventory_complete,false);
});
test('Formal history search includes event date, owner notes and corrected holdings; filters combine',()=>{
  const r={id:'record-A',stage:'applied',feedback:{...defaults('SPY','2026-09-30'),status:'account',notes:'券商核对',holdings:[{ticker:'RBRK',shares:'1'}]},correction:{record_id:'old',reason:'重复登记'}} as FormalRecord;
  assert.equal(matchesHistory(r,'rbrk 2026-09-30','account','applied'),true);
  assert.equal(matchesHistory(r,'重复登记','all','all'),true);
  assert.equal(matchesHistory(r,'RBRK','filled','all'),false);
  assert.equal(matchesHistory(r,'unknown','all','all'),false);
});
test('Parseable corrupted pending form never becomes renderable feedback',()=>{
  assert.equal(validStoredFeedback({}),false);
  assert.equal(validStoredFeedback({...defaults(),holdings:[{ticker:'SPY',shares:{}}]}),false);
  assert.equal(validStoredFeedback({...defaults(),status:'unexpected'}),false);
  assert.equal(validStoredFeedback(defaults()),true);
});
test('Earlier sparse CLI fills remain searchable and editable without inventing confirmation',()=>{
  const r={id:'legacy-cli',stage:'applied',feedback:{ticker:'SPY',status:'filled',side:'buy',date:'2026-09-30',shares:'1',amount:'764',fee_status:'unknown'}} as FormalRecord;
  assert.equal(matchesHistory(r,'spy 2026-09-30','all','all'),true);
  assert.equal(matchesHistory(r,'rbrk','all','all'),false);
  const f=editableFeedback(r.feedback);assert.equal(validStoredFeedback(f),true);
  assert.equal(f.not_in_account,false);assert.equal(f.fee_status,'unknown');assert.deepEqual(f.holdings,[]);
});

test('A new holding without a versioned plan does not create an invalid plan reference', () => {
  assert.equal(planReference(undefined),null);
  assert.equal(planReference({ticker:"NEW",plan_id:null,version:null,record_hash:null} as unknown as Plan),null);
  assert.deepEqual(planReference({plan_id:"NEW-1",version:1,record_hash:"a".repeat(64)} as Plan),{plan_id:"NEW-1",version:1,record_hash:"a".repeat(64)});
});
