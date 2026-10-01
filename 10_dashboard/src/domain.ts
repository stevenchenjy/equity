export type FeedbackStatus = 'skipped' | 'pending' | 'partial' | 'filled' | 'cancelled' | 'account';
export type SummaryPoint = {label: string; text: string};
export type Plan = {
  ticker: string; plan_id: string; version: number; record_hash: string; action: string;
  status: 'expired' | 'pending' | 'current' | 'unverified'; expires_at: string | null;
  blockers: string[]; instruction: string; reason: string; counterargument: string;
  purpose: Record<string, unknown>; sources: { path: string; sha256: string }[];
  draft: Record<string, unknown> | null; historical_draft: Record<string, unknown> | null;
  eligible_quantity: number;
  display_summary?: {reason: SummaryPoint[]; counterargument: SummaryPoint[]; conditions: SummaryPoint[]} | null;
};
export type Snapshot = {
  schema_version: string; mode: string; server_now: string; generated_at: string; cycle_date: string;
  market_session: string; stale: boolean; snapshot_id: string; account_version: string; research_ready?: boolean;
  account: { account_total_value: number | null; cash_available: number; invested_capital: number | null;
    last_updated: string; cash_basis: string; settled_cash_verified: boolean };
  positions: { ticker: string; shares: number; price: number | null; weight: number | null; role: string }[];
  plans: Plan[];
  candidates: { ticker: string; label: string; status: string; price: number;
    quantity: number; maximum_review_price: number | null; blockers: string; invalidation: string; valuation_source: string | null }[];
  orders: { as_of: string; complete: boolean; fresh: boolean; rows: Record<string, unknown>[] };
  global_blockers: string[];
};
export type Feedback = {
  ticker: string; side: 'buy' | 'sell'; status: FeedbackStatus; shares: string;
  amount: string; amount_mode: 'price' | 'gross' | 'net'; fee_status: 'known' | 'unknown'; fees: string;
  date: string; time: string; notes: string; order_type: string; order_price: string; stop_price: string;
  time_in_force: string; remaining: string; linked_order: string; prior_partial: boolean;
  cash: string; holdings: { ticker: string; shares: string; entry_price?: string }[]; inventory_complete: boolean;
  not_in_account?: boolean; account_observed?: boolean; no_open_orders?: boolean; terminal_confirmed?: boolean; partial_recorded?: boolean;
  orders_match?: boolean; observed_order_ids?: string[];
};
export type DemoRecord = {
  schema_version: 'equity_dashboard_demo_v1'; id: string; recorded_at: string;
  production_effect: false; stage: 'demo_complete' | 'demo_pending'; missing: string[];
  snapshot_id: string | null; account_version: string | null;
  plan: { plan_id: string; version: number; record_hash: string } | null;
  event_time_precision: 'approximate' | 'date_only';
  feedback: Feedback;
};
export const STORAGE_KEY = 'equity-dashboard-demo-v1';
export const statusNames: Record<FeedbackStatus, string> = {
  skipped: '未操作', pending: '已挂单', partial: '部分成交', filled: '全部成交', cancelled: '已撤单', account: '账户核对',
};
export const defaults = (ticker = 'SPY', date = easternDate()): Feedback => ({
  ticker, side: 'buy', status: 'filled', shares: '', amount: '', amount_mode: 'price', fee_status: 'unknown',
  fees: '', date, time: '', notes: '', order_type: 'LIMIT', order_price: '', stop_price: '', time_in_force: 'DAY',
  remaining: '', linked_order: '', prior_partial: false, cash: '', holdings: [], inventory_complete: false,
});
export type FormalRecord = {
  id: string; revision: number; recorded_at: string; feedback: Feedback; missing: string[];
  stage: 'pending' | 'applied' | 'applying' | 'recovery_conflict'; research_status: 'queued' | 'running' | 'passed' | 'degraded' | 'failed' | 'not_needed';
  account_version_before: string; plan: {plan_id: string; version: number; record_hash: string} | null;
  production_effect: boolean; order_id?: string; execution_id?: string; error?: string;
  email_version_id?:string|null;
  correction?: {record_id:string;reason:string}|null;
  corrected_by?:string[];
};
export type ReviewRequest = {
  id:string; status:'queued'|'running'|'blocked'|'completed'; question:string; tickers:string[];
  account_version:string; snapshot_id:string; created_at:string; updated_at:string;
  review_account_version?:string; review_snapshot_id?:string;
  receipt?:{path:string;sha256:string;summary:string}; receipt_verified?:boolean;
};
export function validStoredFeedback(value:unknown):value is Feedback {
  if(!value||typeof value!=='object')return false;
  const f=value as Record<string,unknown>;
  const strings=['ticker','side','status','shares','amount','amount_mode','fee_status','fees','date','time','notes','order_type','order_price','stop_price','time_in_force','remaining','linked_order','cash'];
  return strings.every(k=>typeof f[k]==='string') && Object.hasOwn(statusNames,String(f.status))
    && ['buy','sell'].includes(String(f.side)) && ['price','gross','net'].includes(String(f.amount_mode))
    && ['known','unknown'].includes(String(f.fee_status)) && typeof f.prior_partial==='boolean'
    && typeof f.inventory_complete==='boolean' && Array.isArray(f.holdings)
    && f.holdings.every(h=>h&&typeof h.ticker==='string'&&typeof h.shares==='string'&&(h.entry_price===undefined||typeof h.entry_price==='string'));
}
export function initialFeedback(data:Snapshot|null,ticker:string,status:FeedbackStatus='filled'):Feedback {
  const f=defaults(ticker,data?easternDate(Date.parse(data.server_now)):easternDate());
  return status==='account' ? {...f,status,cash:data?String(data.account.cash_available):'',
    holdings:data?.positions.map(p=>({ticker:p.ticker,shares:String(p.shares)}))??[],account_observed:false} : {...f,status};
}
export function editableFeedback(feedback:Feedback):Feedback {
  // Earlier CLI records omit fields unrelated to the reported operation.
  return {...defaults(feedback.ticker),...feedback,holdings:feedback.holdings??[],not_in_account:false};
}
export function matchesHistory(record:Pick<FormalRecord,'id'|'feedback'|'stage'|'correction'>,query:string,status:string,stage:string):boolean {
  if(status!=='all'&&record.feedback.status!==status || stage!=='all'&&record.stage!==stage)return false;
  const f=record.feedback;
  const haystack=[record.id,f.ticker,f.date,f.time,f.notes,statusNames[f.status],f.side==='buy'?'买入':'卖出',
    ...(f.holdings??[]).map(h=>h.ticker),record.correction?.reason??''].join(' ').toLocaleLowerCase();
  return query.trim().toLocaleLowerCase().split(/\s+/).every(word=>haystack.includes(word));
}
export function easternDate(now = Date.now()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}
export const money = (value: number | null | undefined): string => value == null ? '待核对' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
export const timeLabel = (value: string | null | undefined): string => {
  if (!value || !Number.isFinite(Date.parse(value))) return '未记录';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'America/New_York', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)) + ' ET';
};
export function expired(plan: Plan, now: number): boolean {
  return plan.status === 'expired' || !plan.expires_at || !Number.isFinite(Date.parse(plan.expires_at)) || now >= Date.parse(plan.expires_at);
}

export function planReference(plan: Plan | undefined): FormalRecord['plan'] {
  return plan && typeof plan.plan_id==='string' && plan.plan_id.length>0 && Number.isSafeInteger(plan.version) && plan.version>0
    && typeof plan.record_hash==='string' && /^[0-9a-f]{64}$/.test(plan.record_hash)
    ? {plan_id:plan.plan_id,version:plan.version,record_hash:plan.record_hash} : null;
}
const symbol = /^[A-Z][A-Z0-9.\-]{0,11}$/;
const numeric = (value: string) => /^-?\d+(\.\d+)?$/.test(value.trim()) && Number.isFinite(Number(value));
export function validateFeedback(f: Feedback, today = easternDate()): { errors: Record<string, string>; missing: string[] } {
  const errors: Record<string, string> = {}, missing: string[] = [];
  if (f.status !== 'account' && !symbol.test(f.ticker.trim().toUpperCase())) errors.ticker = '请输入有效的股票代码';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date) || Number.isNaN(Date.parse(f.date)) || new Date(f.date).toISOString().slice(0, 10) !== f.date || f.date > today) errors.date = '请选择有效且不晚于今天的日期';
  if (f.time && !/^([01]\d|2[0-3]):[0-5]\d$/.test(f.time)) errors.time = '时间格式为 HH:MM，美东时间';
  const positiveShares = (key: string, v: string) => {
    if (!v.trim()) missing.push(key === 'remaining' ? '剩余挂单股数' : '股数');
    else if (!numeric(v) || Number(v) <= 0 || !Number.isSafeInteger(Number(v))) errors[key] = '请填写正整数股数';
  };
  const amount = (key: string, v: string, label: string, zero = false) => {
    if (!v.trim()) missing.push(label);
    else if (!numeric(v) || (zero ? Number(v) < 0 : Number(v) <= 0)) errors[key] = zero ? '金额须为零或正数' : '金额须为正数';
  };
  if (f.status === 'filled' || f.status === 'partial') {
    positiveShares('shares', f.shares); amount('amount', f.amount, f.amount_mode === 'price' ? '成交单价' : '成交金额');
    if (f.fee_status === 'known') amount('fees', f.fees, '费用', true); else missing.push('费用');
    if (f.status === 'partial') positiveShares('remaining', f.remaining);
  }
  if (f.status === 'pending') {
    positiveShares('shares', f.shares);
    if (['LIMIT', 'STOP_LIMIT'].includes(f.order_type)) amount('order_price', f.order_price, '委托限价');
    if (['STOP', 'STOP_LIMIT'].includes(f.order_type)) amount('stop_price', f.stop_price, '触发价');
    if (f.time_in_force === 'unknown') missing.push('订单有效期');
  }
  if (f.status === 'cancelled') {
    if (!f.linked_order.trim()) missing.push('对应订单');
    if (f.prior_partial) missing.push('撤单前的部分成交记录');
  }
  if (f.status === 'account') {
    amount('cash', f.cash, '现金', true);
    const seen = new Set<string>();
    f.holdings.forEach((row, i) => {
      const t = row.ticker.trim().toUpperCase();
      if (!symbol.test(t) || seen.has(t)) errors[`holding-${i}-ticker`] = '股票代码须有效且不重复';
      if (!numeric(row.shares) || Number(row.shares) <= 0 || !Number.isSafeInteger(Number(row.shares))) errors[`holding-${i}-shares`] = '持仓须为正整数股数；清仓请移除此行';
      seen.add(t);
    });
    if (!f.inventory_complete) missing.push('完整挂单核对');
  }
  return { errors, missing };
}
export function makeDemoRecord(f: Feedback, snapshot: Snapshot | null, id: string = crypto.randomUUID(), now = new Date()): DemoRecord {
  const check = validateFeedback(f, easternDate(now.getTime()));
  if (Object.keys(check.errors).length) throw new Error('反馈字段未通过校验');
  const plan = snapshot?.plans.find(p => p.ticker === f.ticker.trim().toUpperCase());
  const normalized = { ...f, ticker: f.ticker.trim().toUpperCase(), holdings: f.holdings.map(r => ({ ...r, ticker: r.ticker.trim().toUpperCase() })) };
  if (!['filled', 'partial'].includes(f.status)) Object.assign(normalized, { amount: '', fees: '', fee_status: 'unknown', remaining: '' });
  if (f.status !== 'pending') Object.assign(normalized, { order_price: '', stop_price: '' });
  if (!['filled', 'partial', 'pending'].includes(f.status)) normalized.shares = '';
  if (f.status !== 'account') Object.assign(normalized, { cash: '', holdings: [], inventory_complete: false });
  if (f.fee_status === 'unknown') normalized.fees = '';
  return {
    schema_version: 'equity_dashboard_demo_v1', id, recorded_at: now.toISOString(), production_effect: false,
    stage: check.missing.length ? 'demo_pending' : 'demo_complete', missing: check.missing,
    snapshot_id: snapshot?.snapshot_id ?? null, account_version: snapshot?.account_version ?? null,
    plan: planReference(plan),
    event_time_precision: f.time ? 'approximate' : 'date_only',
    feedback: normalized,
  };
}
export function parseRecords(raw: string | null): DemoRecord[] {
  if (raw === null) return [];
  let value: unknown;
  try { value = JSON.parse(raw); }
  catch { throw new Error('试填存储格式无效，请先清除本地试填记录'); }
  const strings = ['ticker', 'side', 'status', 'shares', 'amount', 'amount_mode', 'fee_status', 'fees', 'date', 'time', 'notes', 'order_type', 'order_price', 'stop_price', 'time_in_force', 'remaining', 'linked_order', 'cash'];
  if (!Array.isArray(value) || value.length > 200 || value.some(r => {
    if (!r || r.schema_version !== 'equity_dashboard_demo_v1' || r.production_effect !== false || typeof r.id !== 'string' || !r.id || typeof r.recorded_at !== 'string' || !Number.isFinite(Date.parse(r.recorded_at))) return true;
    if (!['demo_complete', 'demo_pending'].includes(r.stage) || !['approximate', 'date_only'].includes(r.event_time_precision) || !Array.isArray(r.missing) || r.missing.some((m: unknown) => typeof m !== 'string')) return true;
    if ([r.snapshot_id, r.account_version].some(v => v !== null && typeof v !== 'string')) return true;
    if (r.plan !== null && (!r.plan || typeof r.plan.plan_id !== 'string' || !Number.isSafeInteger(r.plan.version) || r.plan.version < 1 || typeof r.plan.record_hash !== 'string')) return true;
    const f = r.feedback;
    return !f || !Object.hasOwn(statusNames, f.status) || strings.some(k => typeof f[k] !== 'string')
      || !['buy', 'sell'].includes(f.side) || !['price', 'gross', 'net'].includes(f.amount_mode) || !['known', 'unknown'].includes(f.fee_status)
      || typeof f.prior_partial !== 'boolean' || typeof f.inventory_complete !== 'boolean'
      || !Array.isArray(f.holdings) || f.holdings.some((h: { ticker: unknown; shares: unknown }) => !h || typeof h.ticker !== 'string' || typeof h.shares !== 'string');
  }) || new Set(value.map(r => r.id)).size !== value.length) throw new Error('试填存储格式无效，请先清除本地试填记录');
  return value as DemoRecord[];
}
export function appendRecord(records: DemoRecord[], record: DemoRecord): DemoRecord[] {
  if (records.some(r => r.id === record.id)) return records;
  if (records.length >= 200) throw new Error('试填记录已达 200 条，请先清除或导出');
  return [...records, record];
}
