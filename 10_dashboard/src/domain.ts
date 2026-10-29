export type FeedbackStatus = 'skipped' | 'pending' | 'partial' | 'filled' | 'cancelled' | 'account';
export type SummaryPoint = {label: string; text: string};
export type CompanyResearchCase = {
  ticker:string; review_version:number; reviewed_at:string; next_review_at:string; conclusion:string;
  review_status?:'current'|'reassessment_required'; valuation_readiness?:string;
  method:string; horizon:string; countercase:string; review_conditions:string[];
  reference_price:number|null; reference_close:string|null; live_quote:false;
  scenario_prices:{bear:number;base:number;bull?:number}|null; base_upside_pct:number|null;
  scenario_reward_to_risk:number|null; minimum_reward_to_risk:number; valuation_only_review_ceiling:number|null;
  review_ceiling_is_order_price:false; model_admission_status:string; pending_requirements:string[];
  research_reasoning?:{authored_at:string; lines:string[]; automatic_action_allowed:false};
};
export type Plan = {
  ticker: string; plan_id: string; version: number; record_hash: string; action: string;
  status: 'expired' | 'pending' | 'current' | 'unverified'; expires_at: string | null;
  blockers: string[]; instruction: string; reason: string; counterargument: string;
  purpose: Record<string, unknown>; sources: { path: string; sha256: string }[];
  draft: Record<string, unknown> | null; historical_draft: Record<string, unknown> | null;
  eligible_quantity: number;
  asset_role?: string;
  display_summary?: {reason: SummaryPoint[]; counterargument: SummaryPoint[]; conditions: SummaryPoint[]} | null;
};
export type CapitalDecision = {
  action:string; generated_at:string; market_data_timestamp:string; planning_cash:number; mandatory_reserve:number;
  global_blockers:string[];
  account_authority?:{mode:string;local_planning_enabled:boolean;execution_checks?:string[]};
  read_time_projection?:{status:'dated_research';source_content_sha256:string|null;required_market_session:string;
    reference_market_session:string|null;canonical_contract:false;protective_exit_rules_unchanged:true};
  dependencies?:{category:string;code:string;scope:string;evidence_required:string}[];
  decisions:{ticker:string;decision:string;shares:number;estimated_notional:number;reasons:string[];blockers:string[];thesis_summary:string;
    research_case?:CompanyResearchCase;
    dependencies:{category:string;code:string;evidence_required:string}[];
    order_draft:null|{side?:string;exit_price?:number;entry_order_type:string;entry_limit:number|null;entry_window:{starts_at:string;ends_at:string};time_in_force:string;
      invalidation_price:number|null;invalidation_rule:string;planned_total_loss:number;planned_account_risk_pct:number;risk_model:string;
      initial_reassessment_price:number|null;reassessment_rule:string;portfolio_weight_before:number;portfolio_weight_after:number;
      cash_before:number;estimated_cash_after:number;trigger_rule:string;cancel_conditions:string[];cost_assumption:string};}[];
};
export type StrategyReadiness = {
  ticker:string;strategy_id:string;horizon:string;
  classification:'valid_action'|'justified_no_action'|'research_incomplete'|'plan_expired'|'data_unavailable'|'strategy_not_adopted';
  canonical_decision:string;eligible_quantity:number;blockers:string[];reason:string;next_step:string;
  resolver:string;review_at:string|null;accepted_records?:unknown[];price_levels_current?:boolean;
};
export type SwingReviewWindow = {id:'morning'|'afternoon';starts_at:string;ends_at:string};
export type SwingTiming = {
  state:'before_review_window'|'within_review_window'|'between_review_windows'|'expired'|'condition_observed'
    |'awaiting_fresh_quote'|'outside_entry_band'|'invalidation_observed';
  review_windows:SwingReviewWindow[];current_window?:unknown;next_window?:unknown;current_quote_status:string;
  quote_observation?:{price:number;trade_at:string;observed_at:string;expires_at:string;execution_quote:false;source_label?:string}|null;
  permanent_for_signal_day?:boolean;
  historical_invalidation?:{recorded_at:string;record_hash:string;observed_at:string;price:number};
  required_conditions:string[];last_evaluated_at:string;
};
export type SwingResearchCandidate = {
  ticker:string;setup:string;state:string;horizon_sessions:number[];source_session:string;
  first_observed_at:string;entry_session:string;entry_trigger:number|null;max_entry:number|null;
  invalidation:number|null;profit_reference:number|null;profit_reference_kind:string;review_deadline:string;
  time_exits?:{holding_sessions:number;session:string}[];
  entry_rule?:string;exit_rule?:string;growth_quality_status?:string;
  validity?:{starts_at:string;ends_at:string;session:string};timing?:SwingTiming;
  skip_reasons:string[];evidence_quality:string;thesis:string;catalyst_status:string;uncertainty:string[];
  actionable_quantity:0;capital_authority:false;research_only:true;
};
export type SwingResearch = {
  schema_version:'equity_swing_research_v1'|'equity_swing_research_v2';status:'experimental_current'|'waiting_on_data'|'failed';
  version?:string;
  review_windows?:SwingReviewWindow[];rank_status?:string;selection_basis?:string;
  research_only:true;capital_authority:false;actionable_quantity:0;generated_at?:string;
  dependencies?:string[];limitations?:string[];
  blockers?:string[];expired_candidates_suppressed?:number;additional_setup_count?:number;
  coverage?:Record<string,unknown>;counts?:Record<string,unknown>;performance?:Record<string,unknown>;adoption?:Record<string,unknown>;
  read_time_performance?:Record<string,unknown>;
  read_time_study_proof?:{record_count:number;ledger_sha256:string;original_projection_generated_at:string;original_projection_sha256:string};
  candidates:SwingResearchCandidate[];
};
export type StrategyFramework = {
  schema_version:'equity_strategy_framework_v1';generated_at:string;status:string;automatic_action_allowed:false;
  validation_error?:string|null;
  strategies:{strategy_id:string;label?:string;name?:string;horizon:string;status:string;capital_authority:boolean;description?:string}[];
  decisions:StrategyReadiness[];
  analyst_handoff:{ticker:string;classification?:string;reason?:string;next_step:string;resolver:string;review_at?:string|null}[];
  swing_research?:SwingResearch;
  swing_coverage?:SwingCoverage;
  swing_benchmarks?:SwingBenchmarks;
};
export type SwingBenchmarkSummary = {
  unique_stock_outcomes:number;unique_matched_stock_outcomes:number;comparison_pairs:number;raw_pairs:number;reviewed_pairs:number;
  unique_reviewed_stock_outcomes:number;pending_stock_horizons:number;unmatched_pairs:number;
  missed_or_skipped_windows:number;qualified_strategy_paths:number;
  genuine_entry_count?:number;paired_entry_count?:number;unpaired_entry_count?:number;nonqualifying_window_transitions?:number;
};
export type SwingBenchmarkGroup = {
  benchmark:string;entry_method:string;horizon_sessions:number;cohort:string;raw_pairs:number;reviewed_pairs:number;
  raw_mean_excess_price_path_pct_by_cost_bps:Record<string,number|null>;
  reviewed_mean_excess_price_path_pct_by_cost_bps:Record<string,number|null>;
};
export type SwingBenchmarkDependency = {code:string;count:number};
export type SwingBenchmarkPoll = {status:string;failure?:string;started_at?:string;completed_at?:string;request_count?:number|null;paired_entries?:number;
  source?:{path:string;sha256:string};observer_source_status?:string;observer_source?:{path:string;sha256:string}|null};
export type SwingBenchmarks = {
  schema_version:'equity_swing_benchmarks_v1';generated_at:string;
  status:'pending_forward_evidence'|'raw_comparisons_available'|'reviewed_comparisons_available'|'unavailable'|'unverified';
  protocol?:{version:string;sha256:string;benchmarks:string[];horizons:number[];costs_bps:number[]};
  stock_source?:{path?:string;sha256:string;records:number;observations:number;outcomes:number};
  summary?:SwingBenchmarkSummary;groups?:SwingBenchmarkGroup[];dependencies?:SwingBenchmarkDependency[];
  read_time_summary?:SwingBenchmarkSummary;read_time_groups?:SwingBenchmarkGroup[];read_time_dependencies?:SwingBenchmarkDependency[];
  read_time_proof?:{generated_at:string;stock_ledger_sha256:string;comparison_ledger_sha256?:string|null;protocol_sha256:string;original_projection_sha256:string};
  supplemental_poll?:SwingBenchmarkPoll|null;read_time_supplemental_poll?:SwingBenchmarkPoll|null;
  profitability_established:false;reliable_win_rate:null;research_only:true;automatic_action_allowed:false;
  capital_authority:false;actionable_quantity:0;execution_quote:false;
};
export type SwingCoverage = {
  schema_version:'equity_swing_coverage_v1';generated_at:string;status:string;
  research_only:true;capital_authority:false;actionable_quantity:0;automatic_action_allowed:false;
  current_discovery_status?:string;required_session?:string;
  latest_provider_failure?:{failure_code?:string;http_status?:number;provider_status?:string;original_http_evidence?:string}|null;
  coverage?:{required_session?:string;required_history_sessions?:number;cached_grouped_files?:number;missing_grouped_sessions?:string[];
    focused_admitted_history_count?:number;focused_scope_is_not_whole_market_coverage?:boolean};
  admitted_history_tickers?:string[];blockers?:string[];
  provisional_history_tickers?:string[];provisional_technical_history_admitted?:false;focused_recovery_status?:string;
  candidates:{ticker:string;name?:string;discovery_session?:string;first_seen_at?:string|null;dated_screen_rank?:number;
    source_status:string;history_status?:string;state?:string;next_step:string;resolver:string;source_ids?:string[];
    current_price:null;research_only:true;capital_authority:false;actionable_quantity:0}[];
  analyst_handoff?:{ticker:string;next_step:string;resolver:string;source_ids?:string[]}[];
};
export type DeploymentGate = {
  code:string; category:'evidence'|'valuation'|'price'|'risk'|'policy'|'account';
  scope:string; ticker?:string|null; evidence_required:string; resolver:string;
};
export type CapitalUse = {
  rank:number; ticker:string; route:string; decision:string; eligible:boolean;
  blockers:string[]; gates:DeploymentGate[]; research_ready:boolean; canonical_score:number|null;
  order_draft:CapitalDecision['decisions'][number]['order_draft']; shares:number; estimated_notional:number;
};
export type CapitalDeploymentEscalation = {
  schema_version:string; generated_at:string;
  status:'active'|'monitoring'|'actionable_available'|'account_integrity_blocked'|'cash_target_met'|'history_unverified'|'session_unverified';
  triggered:boolean; required_sessions:number; consecutive_no_action_sessions:number|null;
  session_history_status:string; session_history_reason:string; observation_session:string|null;
  cash:{uncommitted_cash_usd:number|null;account_value_usd:number|null;cash_target_pct:number|null;
    cash_target_usd:number|null;excess_cash_usd:number|null;excess_cash_pct:number|null;
    material_excess_cash_pct:number|null;materially_above_target:boolean};
  account_integrity_blockers:string[]; gates:DeploymentGate[]; ranked_capital_uses:CapitalUse[];
  routes:{route:string;label:string;status:'available'|'unavailable';closest_candidate:CapitalUse|null;blockers:string[]}[];
  closest_candidate:CapitalUse|null; admitted_order_drafts:{ticker:string;decision:string;shares:number;
    estimated_notional:number;order_draft:CapitalDecision['decisions'][number]['order_draft']}[];
  research_priority_tickers:string[];
  research_requests:{ticker:string;priority:number;urgency:'immediate'|'normal';blockers:string[];
    required_work:DeploymentGate[];completed:boolean}[];
  explanation:string; automatic_action_allowed:false;
};
export type IntradayNumber = number | string | null;
export type IntradayRisk = {
  schema_version: 'intraday_portfolio_risk_v1'; status: string;
  generated_at?: string; session_date?: string; mark_as_of?: string; expires_at?: string;
  baseline_session?: string; portfolio_nav?: IntradayNumber; baseline_portfolio_nav?: IntradayNumber;
  value_change_usd?: IntradayNumber; value_change_pct?: IntradayNumber; cash_usd?: IntradayNumber;
  positions?: {ticker:string; shares:IntradayNumber; price:IntradayNumber; price_as_of?:string;
    baseline_price?:IntradayNumber; price_change_pct?:IntradayNumber; market_value?:IntradayNumber;
    weight_pct?:IntradayNumber; source?:string; delay_label?:string; status:string}[];
  allocation?: {core_weight_pct?:IntradayNumber;stock_weight_pct?:IntradayNumber;cash_weight_pct?:IntradayNumber;
    core_minimum_pct?:IntradayNumber;stock_maximum_pct?:IntradayNumber};
  concentration?: {largest_stock_ticker?:string|null;largest_stock_weight_pct?:IntradayNumber;overlap_assessed?:boolean};
  plan_conditions?: (string|{ticker?:string;condition?:string;message?:string;description?:string;status?:string;kind?:string;reference_price?:IntradayNumber;observed_price?:IntradayNumber})[];
  reassessment_triggers?: (string|{ticker?:string;condition?:string;message?:string;description?:string;status?:string;kind?:string;reference_price?:IntradayNumber;observed_price?:IntradayNumber})[];
  tactical_limits?: {ordinary_risk_pct?:IntradayNumber;event_risk_pct?:IntradayNumber;combined_risk_pct?:IntradayNumber;
    max_position_pct?:IntradayNumber;min_reward_to_risk?:IntradayNumber;existing_planned_risk_usd?:IntradayNumber;
    combined_planned_risk_pct?:IntradayNumber;existing_planned_risk_basis?:string;combined_status?:string};
  dependencies?: string[]; limitations?: string[];
};
export type Snapshot = {
  feedback_context_only?:boolean;
  strategy_framework?:StrategyFramework|null;
  intraday_portfolio_risk?: IntradayRisk | null;
  earnings_events?: EarningsEventView;
  account_authority?:CapitalDecision['account_authority'];
  schema_version: string; mode: string; server_now: string; generated_at: string; cycle_date: string;
  market_session: string; expected_market_session?: string; market_current?: boolean; market_sources?: string[]; stale: boolean; snapshot_id: string; account_version: string; research_ready?: boolean;
  account: { account_total_value: number | null; cash_available: number; invested_capital: number | null;
    last_updated: string; cash_basis: string; settled_cash_verified: boolean };
  positions: { ticker: string; shares: number; price: number | null; weight: number | null; role: string }[];
  allocation?: {core_tickers:string[];core_minimum_pct:number;core_target_pct:number;stock_maximum_pct:number;core_weight_pct:number|null;policy_version:string}|null;
  plans: Plan[];
  candidates: { ticker: string; label: string; status: string; price: number;
    quantity: number; maximum_review_price: number | null; blockers: string; invalidation: string; valuation_source: string | null }[];
  orders: { as_of: string; complete: boolean; fresh: boolean; rows: Record<string, unknown>[] };
  global_blockers: string[];
  capital_decision?:CapitalDecision|null; capital_decision_status?:string;
  capital_deployment_escalation?:CapitalDeploymentEscalation|null;
};
export type EarningsEventView = {
  schema_version: 'equity_earnings_event_view_v1'; generated_at: string;
  status: 'ready' | 'partial' | 'stale' | 'unverified' | 'missing';
  coverage: { scope?: string; horizon_start?: string; horizon_end?: string; days_requested?: number;
    days_verified?: number; failed_dates?: string[]; events_detected?: number; latest_fetch_at?: string };
  events: EarningsEvent[]; capital_authority: false; automatic_action_allowed: false;
};
export type EarningsEvent = {
  event_id: string; ticker: string; company_name: string; event_date: string;
  session: 'after_close' | 'before_open' | 'time_unknown'; event_at: string | null;
  research_deadline_at: string | null; first_detected_at: string;
  timing: 'pre_event' | 'post_event' | 'elapsed' | 'unverified';
  status: 'detected' | 'awaiting_research' | 'research_in_progress' | 'reviewed_without_entry'
    | 'eligible_conditional_plan' | 'elapsed_unreviewed' | 'cancelled' | 'schedule_conflict';
  date_confidence: 'exchange_calendar_estimate' | 'issuer_confirmed'; research_state: string;
  blockers: string[]; next_step: string;
  sources: { source_url: string; sha256: string; path: string; available_at: string }[];
  event_review?: {event_id: string; expectations_case: string; priced_in_assessment: string; valuation_case: string;
    downside_case: string; recheck_condition: string;
    sources: {source_url: string; sha256: string; path: string; available_at?: string}[]};
};
export type Feedback = {
  entry_mode?: 'simple' | 'simple_total'; order_link_mode?: 'independent';
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
  entry_mode: 'simple_total', ticker, side: 'buy', status: 'filled', shares: '', amount: '', amount_mode: 'net', fee_status: 'known',
  fees: '0', date, time: '', notes: '', order_type: 'UNSPECIFIED', order_price: '', stop_price: '', time_in_force: 'DAY',
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
  effective_date?:string;
  execution_date_correction?:{original_date:string;corrected_date:string;record_id:string;revision:number;recorded_at:string;reason:string;owner_source:{path:string;sha256:string}};
  historical_reconciliation?:{schema_version:'equity_owner_historical_fill_reconciliation_v1';[key:string]:unknown};
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
    && ['known','unknown'].includes(String(f.fee_status))
    && (f.entry_mode===undefined||f.entry_mode==='simple'||f.entry_mode==='simple_total')
    && (f.order_link_mode===undefined||f.order_link_mode==='independent') && typeof f.prior_partial==='boolean'
    && typeof f.inventory_complete==='boolean' && Array.isArray(f.holdings)
    && f.holdings.every(h=>h&&typeof h.ticker==='string'&&typeof h.shares==='string'&&(h.entry_price===undefined||typeof h.entry_price==='string'));
}
export function initialFeedback(data:Snapshot|null,ticker:string,status:FeedbackStatus='filled'):Feedback {
  const f=defaults(ticker,data?easternDate(Date.parse(data.server_now)):easternDate());
  return status==='account' ? {...f,status,cash:data?String(data.account.cash_available):'',
    holdings:data?.positions.map(p=>({ticker:p.ticker,shares:String(p.shares)}))??[],account_observed:false} : {...f,status,order_type:status==='pending'?'LIMIT':f.order_type};
}
export function editableFeedback(feedback:Feedback):Feedback {
  // Earlier CLI records omit fields unrelated to the reported operation.
  // Retain historical amount/time semantics; the owner confirmed this broker has no fees.
  // This only prepares an explicit new revision, never rewrites the original record.
  const f={...defaults(feedback.ticker),...feedback,amount_mode:feedback.amount_mode??'price',entry_mode:feedback.entry_mode,holdings:feedback.holdings??[],not_in_account:false};
  const revised:Feedback=f.fee_status==='unknown'||!f.fees ? {...f,fee_status:'known',fees:'0'} : Number(f.fees)===0?{...f,fees:'0'}:f;
  return revised.amount_mode==='price'&&revised.fees==='0'&&!revised.time ? {...revised,entry_mode:'simple'} : revised;
}
export function matchingOrders(f:Feedback,rows:Record<string,unknown>[]):Record<string,unknown>[] {
  return rows.filter(r=>['open','pending','partial_fill','partially_filled'].includes(String(r.status))
    &&r.record_scope!=='unresolved_historical_reservation'&&r.ticker===f.ticker.trim().toUpperCase()&&r.side===f.side);
}
export function orderLabel(r:Record<string,unknown>):string {
  const price=r.limit_price??r.order_price,stop=r.stop_price;
  const date=typeof r.session_date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(r.session_date)?` · ${r.session_date}`:'';
  return `${r.ticker} ${r.side==='buy'?'买入':'卖出'} · 剩余 ${r.remaining_quantity??r.quantity} 股 · ${r.order_type??''}${price?` $${price}`:''}${stop?` / 触发 $${stop}`:''} · ${r.time_in_force??''}${date}`;
}
export function matchesHistory(record:Pick<FormalRecord,'id'|'feedback'|'stage'|'correction'|'effective_date'|'execution_date_correction'>,query:string,status:string,stage:string):boolean {
  if(status!=='all'&&record.feedback.status!==status || stage!=='all'&&record.stage!==stage)return false;
  const f=record.feedback;
  const haystack=[record.id,f.ticker,f.date,f.time,f.notes,statusNames[f.status],f.side==='buy'?'买入':'卖出',
    ...(f.holdings??[]).map(h=>h.ticker),record.correction?.reason??'',record.effective_date??'',record.execution_date_correction?.original_date??'',record.execution_date_correction?.record_id??'',record.execution_date_correction?.reason??''].join(' ').toLocaleLowerCase();
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
