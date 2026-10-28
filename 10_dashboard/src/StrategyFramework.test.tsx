import test from 'node:test';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import StrategyFrameworkPanel, {swingReviewState} from './StrategyFramework';
import {CapitalActions} from './CapitalActions';
import type {Snapshot, StrategyFramework, SwingResearch, SwingResearchCandidate, SwingReviewWindow, SwingCoverage, SwingBenchmarks} from './domain';

const now=Date.parse('2026-10-28T08:00:00-04:00');
const framework:StrategyFramework={schema_version:'equity_strategy_framework_v1',generated_at:'2026-10-28T09:45:00-04:00',
  status:'ready',automatic_action_allowed:false,
  strategies:[{strategy_id:'growth',label:'Reviewed growth',horizon:'Four reported quarters',status:'active',capital_authority:true,
    description:'Company-specific cash and valuation cases.'},{strategy_id:'swing',label:'Swing research',horizon:'5–14 sessions',status:'experimental',capital_authority:false}],
  decisions:[{ticker:'CASE',strategy_id:'growth',horizon:'Four reported quarters',classification:'justified_no_action',
    canonical_decision:'NO_ACTION',eligible_quantity:0,blockers:[],reason:'Completed case rejects this price.',next_step:'Reassess a new official result.',resolver:'analyst',review_at:null},
  {ticker:'HELD',strategy_id:'growth',horizon:'One year',classification:'plan_expired',canonical_decision:'HOLD',eligible_quantity:0,
    blockers:['review_due'],reason:'The bounded holding review expired.',next_step:'Reassess the original thesis.',resolver:'analyst',review_at:'2026-10-27T15:30:00-04:00'}],
  analyst_handoff:[{ticker:'HELD',classification:'plan_expired',reason:'Deadline elapsed.',next_step:'Reassess without renewing the former draft.',resolver:'analyst'}]};
const swing:SwingResearch={schema_version:'equity_swing_research_v1',status:'experimental_current',research_only:true,capital_authority:false,actionable_quantity:0,
  candidates:[{ticker:'SETUP',setup:'pullback_reclaim',state:'research_setup',horizon_sessions:[5,10,14],source_session:'2026-10-27',
    first_observed_at:'2026-10-27T21:00:00-04:00',entry_session:'2026-10-28',entry_trigger:101.23,max_entry:101.7,invalidation:97.31,
    profit_reference:109.07,profit_reference_kind:'hypothetical_2R_not_observed_resistance',review_deadline:'2026-10-28T09:30:00-04:00',
    skip_reasons:['Skip a gap above the ceiling.'],evidence_quality:'validated_completed_daily_OHLCV_only',thesis:'Daily pullback regained the reference.',
    catalyst_status:'requires_analyst_direction_review',uncertainty:['Spreads and intraday sequence remain unverified.'],actionable_quantity:0,capital_authority:false,research_only:true}]};
const snapshot={expected_market_session:'2026-10-27',market_current:true,strategy_framework:framework} as Snapshot;

test('framework distinguishes completed rejection, expired hold and experimental route without making drafts',()=>{
  const before=JSON.stringify(framework);
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={snapshot} now={now}/>);
  for(const text of ['Strategy and decision readiness','Completed no-entry / hold judgment','Plan expired','CASE · WAIT','HELD · WAIT','Other research states','scheduled analyst']){
    if(text==='Other research states')continue;
    assert.ok(html.includes(text),text);
  }
  assert.match(html,/Four reported quarters/);assert.match(html,/Research only · no capital authority/);
  assert.doesNotMatch(html,/BUY LIMIT|SELL LIMIT|HELD · HOLD|[1-9]+ shares authorized/);
  assert.equal(JSON.stringify(framework),before);
});
test('current experimental setup shows complete research levels and its noncapital limits',()=>{
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:swing}}} now={now}/>);
  for(const text of ['Pullback reclaim','$101.23','$101.70','$97.31','$109.07','5 / 10 / 14','Hypothetical 2R','no capital authority','Skip a gap','Spreads'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/BUY LIMIT|SELL LIMIT|capital-buy|capital-sell/);
});
test('expired, stale-session and invalid-authority research setup cannot display current levels',()=>{
  for(const changed of [
    {...swing,status:'waiting_on_data',candidates:[]} as SwingResearch,
    {...swing,candidates:swing.candidates.map(r=>({...r,source_session:'2026-10-26'}))},
    {...swing,candidates:swing.candidates.map(r=>({...r,review_deadline:'2026-10-28T07:59:00-04:00'}))},
    {...swing,capital_authority:true} as unknown as SwingResearch,
  ]){
    const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:changed}}} now={now}/>);
    assert.doesNotMatch(html,/\$101\.23|\$101\.70|\$97\.31|\$109\.07|BUY LIMIT/);
    assert.match(html,/WAIT/);
  }
});
test('no-opportunity and failed dashboard read retain clear WAIT without invented opportunity',()=>{
  const noSetup=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:{...swing,candidates:[]}}}} now={now}/>);
  assert.match(noSetup,/No qualifying setup/);assert.doesNotMatch(noSetup,/SETUP|\$101/);
  const failed=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:swing}}} now={now} unavailable/>);
  assert.match(failed,/Current source\/session validation is unavailable/);assert.doesNotMatch(failed,/\$101\.23/);
});
test('elapsed entries and zero mature evidence are explicit rather than reported as a new empty screen',()=>{
  const view={...swing,candidates:[],expired_candidates_suppressed:2,performance:{observations:12,outcomes:0},
    blockers:['Original source binding must be restored.']};
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_research:view}}} now={now}/>);
  for(const text of ['elapsed entry windows','2 expired setup cards','12 recorded ticker/session observations','0 matured horizon records',
    'Profitability and a reliable win rate remain unestablished','Original source binding must be restored.'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/No qualifying setup|12 wins|12 trades|BUY LIMIT/);
});
test('failed current read withholds old canonical quantities and prices',()=>{
  const old={positions:[],capital_decision:{decisions:[{ticker:'OLD',order_draft:{side:'buy',entry_limit:999},shares:1234}]}} as unknown as Snapshot;
  const html=renderToStaticMarkup(<CapitalActions data={old} unavailable/>);
  assert.match(html,/WAIT/);assert.doesNotMatch(html,/1234|999|BUY LIMIT|OLD/);
});
test('older publications without framework remain compatible and invalid authority is hidden',()=>{
  assert.equal(renderToStaticMarkup(<StrategyFrameworkPanel data={{} as Snapshot} now={now}/>),'');
  const invalid={...framework,automatic_action_allowed:true} as unknown as StrategyFramework;
  assert.equal(renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:invalid}} now={now}/>),'');
});
test('recorded holdings retain exact purpose and invalidation without renewing an expired instruction',()=>{
  const purpose={strategy:'Original multi-quarter cash-return case.',holding_period_justification:'Hold only while the recorded cash thesis survives.',
    failure_condition:'Reassess verified funding impairment.',exit_rule:'A supported adverse conclusion needs a fresh priced exit draft.',
    entry_validity:'No addition without an independently supported plan.'};
  const data={...snapshot,positions:[{ticker:'HELD',shares:2,price:100,weight:5,role:'growth'}],
    plans:[{ticker:'HELD',plan_id:'synthetic-held-7',version:7,record_hash:'a'.repeat(64),action:'hold',status:'current',
      expires_at:'2026-10-28T09:45:00-04:00',purpose,blockers:[],instruction:'Synthetic bounded holding review.',
      reason:'Original sourced purpose.',counterargument:'Cash return could disappoint.',sources:[],draft:null,historical_draft:null,eligible_quantity:0}]} as Snapshot;
  const before=JSON.stringify(data);
  const current=renderToStaticMarkup(<StrategyFrameworkPanel data={data} now={now}/>);
  assert.match(current,/Current bounded purpose record|2 recorded shares/);
  for(const text of Object.values(purpose))assert.ok(current.includes(text),text);
  const after=renderToStaticMarkup(<StrategyFrameworkPanel data={data} now={Date.parse('2026-10-28T09:45:00-04:00')}/>);
  assert.match(after,/Reassessment required — retained purpose is historical/);
  assert.doesNotMatch(after,/Current bounded purpose record|BUY LIMIT|SELL LIMIT/);
  assert.equal(JSON.stringify(data),before);
});

const reviewWindows:SwingReviewWindow[]=[{id:'morning',starts_at:'2026-10-28T09:45:00-04:00',ends_at:'2026-10-28T10:45:00-04:00'},
  {id:'afternoon',starts_at:'2026-10-28T14:45:00-04:00',ends_at:'2026-10-28T15:20:00-04:00'}];
const reviewCandidate:SwingResearchCandidate={...swing.candidates[0],review_deadline:'2026-10-28T15:20:00-04:00',
  validity:{session:'2026-10-28',starts_at:reviewWindows[0].starts_at,ends_at:reviewWindows[1].ends_at},
  timing:{state:'before_review_window',review_windows:reviewWindows,current_quote_status:'unavailable',required_conditions:['A current last sale must meet the frozen entry band.'],last_evaluated_at:'2026-10-28T08:00:00-04:00'}};
const reviewView:SwingResearch={...swing,schema_version:'equity_swing_research_v2',version:'daily-swing-review-windows-v2-20261028',
  review_windows:reviewWindows,candidates:[reviewCandidate],performance:{observations:31,outcomes:0,performance_eligible_paths:0,corporate_action_review_required:0}};
const renderReview=(view:SwingResearch,clock:string,unavailable=false,expected='2026-10-27')=>renderToStaticMarkup(
  <StrategyFrameworkPanel data={{...snapshot,expected_market_session:expected,strategy_framework:{...framework,swing_research:view}}}
    now={Date.parse(clock)} unavailable={unavailable}/>);
test('v2 premarket blueprint retains dated conditions and actual owner review windows without current price claims',()=>{
  const html=renderReview(reviewView,'2026-10-28T08:00:00-04:00');
  for(const text of ['Before the review window','Morning review:','09:45','10:45','Afternoon review:','14:45','15:20',
    '$101.23','Dated daily reference trigger','Current entry price is unverified','Not sized for execution · zero approved shares'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/Validated last-sale observation|BUY LIMIT|capital-buy/);
});
test('v2 post-open reference remains useful in the morning window with a separately validated quote condition',()=>{
  const row={...reviewCandidate,timing:{...reviewCandidate.timing!,state:'condition_observed' as const,current_quote_status:'current',
    quote_observation:{price:101.55,trade_at:'2026-10-28T09:49:00-04:00',observed_at:'2026-10-28T09:49:01-04:00',expires_at:'2026-10-28T09:54:00-04:00',execution_quote:false as const}}};
  const view={...reviewView,candidates:[row]};
  const html=renderReview(view,'2026-10-28T09:50:00-04:00');
  for(const text of ['Entry-band condition observed','$101.55','$101.23','Current review: morning','not an executable bid/ask or a fill'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/entry window expired|BUY LIMIT|SELL LIMIT/);
});
test('v2 midday retains a bounded blueprint and names the afternoon review instead of inventing an elapsed fill',()=>{
  const html=renderReview(reviewView,'2026-10-28T12:30:00-04:00');
  assert.match(html,/Between review windows/);assert.match(html,/Next review begins 10\/28 14:45 ET/);
  assert.match(html,/\$101\.23/);assert.match(html,/current execution quotes/);
  assert.doesNotMatch(html,/before the first future open|Validated last-sale observation|BUY LIMIT/);
});
test('v2 browser clock progress expires quote indications before daily reference conditions and then expires the blueprint',()=>{
  const row={...reviewCandidate,timing:{...reviewCandidate.timing!,state:'condition_observed' as const,current_quote_status:'current',
    quote_observation:{price:101.55,trade_at:'2026-10-28T09:49:00-04:00',observed_at:'2026-10-28T09:49:01-04:00',expires_at:'2026-10-28T09:54:00-04:00',execution_quote:false as const}}};
  const before=JSON.stringify(row);
  assert.equal(swingReviewState(row,Date.parse('2026-10-28T09:53:59-04:00'),'2026-10-27').state,'condition_observed');
  assert.equal(swingReviewState(row,Date.parse('2026-10-28T09:54:00-04:00'),'2026-10-27').state,'awaiting_fresh_quote');
  const quoteExpired=renderReview({...reviewView,candidates:[row]},'2026-10-28T09:54:00-04:00');
  assert.match(quoteExpired,/\$101\.23|Current entry price is unverified/);
  assert.doesNotMatch(quoteExpired,/\$101\.55|Entry-band condition observed/);
  const expired=renderReview({...reviewView,candidates:[row]},'2026-10-28T15:20:00-04:00');
  assert.match(expired,/research entry window expired/);
  assert.doesNotMatch(expired,/\$101\.23|\$101\.55|\$97\.31|\$109\.07/);
  assert.equal(JSON.stringify(row),before);
});
test('v2 stale source and failed-refresh states withhold levels independently of an available prior quote',()=>{
  const stale=renderReview(reviewView,'2026-10-28T10:00:00-04:00',false,'2026-10-28');
  assert.match(stale,/source session or timing is unverified/);assert.doesNotMatch(stale,/\$101\.23|BUY LIMIT/);
  const failed=renderReview(reviewView,'2026-10-28T10:00:00-04:00',true);
  assert.match(failed,/Current source\/session validation is unavailable/);assert.doesNotMatch(failed,/\$101\.23|BUY LIMIT/);
});
test('v2 no-opportunity keeps review windows and zero qualified evidence explicit without fabricated setup prices',()=>{
  const html=renderReview({...reviewView,candidates:[]},'2026-10-28T14:50:00-04:00');
  for(const text of ['No qualifying setup','Morning review:','Afternoon review:','31 recorded ticker/session observations',
    '0 matured horizon records','Effectiveness-qualified paths: 0'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/SETUP|\$101\.23|BUY LIMIT|31 wins|31 trades/);
});
test('v2 unverified or future quotes never become validated marks; retained adverse observations require reassessment',()=>{
  for(const change of [{current_quote_status:'unavailable'},
    {quote_observation:{price:101.55,trade_at:'2026-10-28T10:01:00-04:00',observed_at:'2026-10-28T10:01:01-04:00',expires_at:'2026-10-28T10:06:00-04:00',execution_quote:false as const}}]){
    const row={...reviewCandidate,timing:{...reviewCandidate.timing!,state:'condition_observed' as const,...change}};
    const html=renderReview({...reviewView,candidates:[row]},'2026-10-28T10:00:00-04:00');
    assert.doesNotMatch(html,/Validated last-sale observation|\$101\.55/);
  }
  const row={...reviewCandidate,timing:{...reviewCandidate.timing!,state:'invalidation_observed' as const}};
  const html=renderReview({...reviewView,candidates:[row]},'2026-10-28T10:00:00-04:00');
  assert.match(html,/prior invalidation observation is retained/);assert.match(html,/requires reassessment/);
});
test('v2 keeps frozen entry and exit rules distinct from an adopted execution instruction',()=>{
  const row={...reviewCandidate,entry_rule:'Synthetic source rule: evaluate the captured morning or afternoon band.',
    exit_rule:'Synthetic source rule: compare the stop, hypothetical 2R and 5/10/14-session exits.'};
  const html=renderReview({...reviewView,candidates:[row]},'2026-10-28T10:00:00-04:00');
  assert.ok(html.includes(row.entry_rule));assert.ok(html.includes(row.exit_rule));
  assert.match(html,/do not establish an order, a fill or an adopted stop-loss instruction/);
  assert.doesNotMatch(html,/BUY LIMIT|SELL STOP/);
});
const outsideCoverage:SwingCoverage={schema_version:'equity_swing_coverage_v1',generated_at:'2026-10-28T08:00:00-04:00',status:'waiting_on_data',
  research_only:true,capital_authority:false,actionable_quantity:0,automatic_action_allowed:false,current_discovery_status:'unavailable',
  latest_provider_failure:{failure_code:'authentication_failed',http_status:403},coverage:{required_session:'2026-10-27',required_history_sessions:51,cached_grouped_files:51},
  admitted_history_tickers:['OUT1','OUT2'],blockers:['current_broad_discovery_unavailable:authentication_failed'],candidates:[{
    ticker:'OUT1',name:'Synthetic outside issuer',discovery_session:'2026-10-20',first_seen_at:'2026-10-21T09:00:00-04:00',dated_screen_rank:7,
    source_status:'dated_market_strength_lead',history_status:'admitted_unadjusted_research_only',next_step:'Review the independently recovered history and issuer countercase.',
    resolver:'experimental_swing_research',source_ids:['retained-original-source-id'],current_price:null,research_only:true,capital_authority:false,actionable_quantity:0},
  {ticker:'OLD',discovery_session:'2026-10-19',dated_screen_rank:10,source_status:'dated_market_strength_lead',history_status:'current_51_session_history_unavailable',
    next_step:'Obtain a source-bound current history.',resolver:'public_data',source_ids:[],current_price:null,research_only:true,capital_authority:false,actionable_quantity:0}]};
test('coverage separates focused admitted research histories from failed broad discovery and dated leads',()=>{
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_coverage:outsideCoverage}}} now={now}/>);
  for(const text of ['Broad daily-screen status:','unavailable','authentication_failed','HTTP 403','Independently admitted research histories: 2',
    'Focused history recovery does not establish complete broad-market coverage','History admitted for experimental research',
    'Dated research lead — current setup evidence remains unverified','dated screen position 7','retained-original-source-id',
    'current_broad_discovery_unavailable:authentication_failed'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/BUY LIMIT|best stock|high-potential|\$0\.00/);
});
test('failed current read cannot reuse admitted coverage or cached file counts as current opportunity proof',()=>{
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_coverage:outsideCoverage}}} now={now} unavailable/>);
  assert.match(html,/Current admitted research-history count is unverified/);
  assert.match(html,/unverified at this read/);
  assert.doesNotMatch(html,/Independently admitted research histories: 2|History admitted for experimental research/);
  assert.match(html,/File counts do not establish current admission/);
});
test('sticky source-day invalidation is not revived by a later window or a fresh quote',()=>{
  const row={...reviewCandidate,timing:{...reviewCandidate.timing!,state:'invalidation_observed' as const,permanent_for_signal_day:true,
    current_quote_status:'not_used_after_day_invalidation',quote_observation:null,
    historical_invalidation:{recorded_at:'2026-10-28T09:50:00-04:00',record_hash:'d'.repeat(64),observed_at:'2026-10-28T09:49:59-04:00',price:97.2}}};
  const html=renderReview({...reviewView,candidates:[row]},'2026-10-28T14:50:00-04:00');
  for(const text of ['signal was invalidated for its source day','later bounce or a fresh quote cannot renew','No further entry window remains',
    'historical evidence, not a current mark','d'.repeat(64)])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/Entry-band condition observed|Validated last-sale observation|\$97\.20|BUY LIMIT/);
});
test('latest read-time study counts are labelled separately and do not rewrite the original publication',()=>{
  const view={...reviewView,read_time_performance:{observations:33,outcomes:2,performance_eligible_paths:1,corporate_action_review_required:1},
    read_time_study_proof:{record_count:45,ledger_sha256:'e'.repeat(64),original_projection_generated_at:'2026-10-28T08:00:00-04:00',original_projection_sha256:'f'.repeat(64)}};
  const before=JSON.stringify(view);
  const html=renderReview(view,'2026-10-28T14:50:00-04:00');
  for(const text of ['33 recorded ticker/session observations','2 matured horizon records','Effectiveness-qualified paths: 1',
    'source-validated at this read','original publication remains dated'])assert.ok(html.includes(text),text);
  assert.equal(JSON.stringify(view),before);
  assert.match(renderReview(view,'2026-10-28T14:50:00-04:00',true),/last successful read and have not been revalidated now/);
});
test('complete cached adjusted files remain provisional rather than becoming admitted technical histories',()=>{
  const view={...outsideCoverage,admitted_history_tickers:[],provisional_history_tickers:['OUT1','OUT2'],provisional_technical_history_admitted:false as const};
  const html=renderToStaticMarkup(<StrategyFrameworkPanel data={{...snapshot,strategy_framework:{...framework,swing_coverage:view}}} now={now}/>);
  assert.match(html,/Independently admitted research histories: 0/);
  assert.match(html,/Provisional provider-adjusted histories: 2/);
  assert.match(html,/excluded from technical-history admission/);
  assert.doesNotMatch(html,/Independently admitted research histories: 2|History admitted for experimental research/);
});
const benchmarkZero:SwingBenchmarks={schema_version:'equity_swing_benchmarks_v1',generated_at:'2026-10-28T08:00:00-04:00',status:'pending_forward_evidence',
  protocol:{version:'synthetic-benchmark-v1',sha256:'a'.repeat(64),benchmarks:['SPY','QQQM'],horizons:[5,10,14],costs_bps:[10,25,50]},
  stock_source:{path:'08_reviews/synthetic/stock-ledger.jsonl',sha256:'b'.repeat(64),records:33,observations:33,outcomes:0},
  summary:{unique_stock_outcomes:0,unique_matched_stock_outcomes:0,comparison_pairs:0,raw_pairs:0,reviewed_pairs:0,unique_reviewed_stock_outcomes:0,
    pending_stock_horizons:3,unmatched_pairs:0,missed_or_skipped_windows:0,qualified_strategy_paths:0,genuine_entry_count:0,paired_entry_count:0,unpaired_entry_count:0},
  groups:[{benchmark:'SPY',entry_method:'benchmark_future_open',horizon_sessions:5,cohort:'selected',raw_pairs:0,reviewed_pairs:0,
    raw_mean_excess_price_path_pct_by_cost_bps:{'10':null,'25':null,'50':null},reviewed_mean_excess_price_path_pct_by_cost_bps:{'10':null,'25':null,'50':null}}],
  dependencies:[{code:'forward_horizon_pending',count:3}],profitability_established:false,reliable_win_rate:null,research_only:true,
  automatic_action_allowed:false,capital_authority:false,actionable_quantity:0,execution_quote:false};
const renderBenchmark=(view:SwingBenchmarks,unavailable=false)=>renderToStaticMarkup(<StrategyFrameworkPanel
  data={{...snapshot,strategy_framework:{...framework,swing_benchmarks:view}}} now={now} unavailable={unavailable}/>);
test('zero-matured benchmark evidence has explicit pending counts and no invented zero excess return',()=>{
  const html=renderBenchmark(benchmarkZero);
  for(const text of ['Matched SPY / QQQM evaluation','No matured stock-horizon outcome','Pending stock horizons: 3',
    'Qualified strategy execution paths: 0','Unestablished','forward_horizon_pending'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/0\.00 pp|win rate: 0|BUY LIMIT|SELL STOP/);
});
test('benchmark counts use unique source denominators rather than sums across overlapping groups',()=>{
  const group={...benchmarkZero.groups![0],raw_pairs:1,raw_mean_excess_price_path_pct_by_cost_bps:{'10':1.25,'25':.75,'50':-.3}};
  const view={...benchmarkZero,status:'raw_comparisons_available' as const,
    summary:{...benchmarkZero.summary!,unique_stock_outcomes:1,unique_matched_stock_outcomes:1,comparison_pairs:2,raw_pairs:2},
    groups:[group,{...group,cohort:'all_common_stocks'},{...group,benchmark:'QQQM'},{...group,benchmark:'QQQM',cohort:'all_common_stocks'}]};
  const html=renderBenchmark(view);
  assert.match(html,/<dt>Source\/time-matched pairs<\/dt><dd>2<\/dd>/);
  assert.match(html,/Distinct matched stock-horizon outcomes: 1/);
  for(const text of ['+1.25 pp','+0.75 pp','-0.30 pp','percentage points','groups overlap'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/\+1\.25%|win rate:|BUY LIMIT/);
});
test('reviewed fixed paths remain separate from qualified strategy execution and adoption',()=>{
  const view={...benchmarkZero,status:'reviewed_comparisons_available' as const,
    summary:{...benchmarkZero.summary!,unique_stock_outcomes:1,unique_matched_stock_outcomes:1,comparison_pairs:2,reviewed_pairs:2,unique_reviewed_stock_outcomes:1},
    groups:benchmarkZero.groups!.map(group=>({...group,reviewed_pairs:2,reviewed_mean_excess_price_path_pct_by_cost_bps:{'10':.5,'25':0,'50':-.5}}))};
  const html=renderBenchmark(view);
  for(const text of ['Reviewed fixed-path pairs','+0.50 pp','0.00 pp','-0.50 pp','Qualified strategy execution paths: 0',
    'strategy promotion remain unestablished'])assert.ok(html.includes(text),text);
});
test('read-time benchmark overlay is labelled and leaves original sealed summary unchanged',()=>{
  const view={...benchmarkZero,read_time_summary:{...benchmarkZero.summary!,unique_stock_outcomes:1,unique_matched_stock_outcomes:1,comparison_pairs:2,raw_pairs:2},
    read_time_groups:[],read_time_dependencies:[{code:'owner_window_pair_missing',count:1}],
    read_time_proof:{generated_at:'2026-10-28T14:50:00-04:00',stock_ledger_sha256:'c'.repeat(64),comparison_ledger_sha256:'d'.repeat(64),
      protocol_sha256:'a'.repeat(64),original_projection_sha256:'e'.repeat(64)}};
  const before=JSON.stringify(view);const html=renderBenchmark(view);
  assert.match(html,/<dt>Source\/time-matched pairs<\/dt><dd>2<\/dd>/);
  assert.match(html,/Comparison counts were revalidated/);assert.match(html,/original sealed publication/);
  assert.ok(html.includes('owner_window_pair_missing'));assert.equal(JSON.stringify(view),before);
});
test('unmatched owner-window data cannot acquire assumed benchmark entries or zero returns',()=>{
  const view={...benchmarkZero,summary:{...benchmarkZero.summary!,unique_stock_outcomes:2,pending_stock_horizons:0,unmatched_pairs:4,missed_or_skipped_windows:1},
    groups:[],dependencies:[{code:'owner_window_pair_span_exceeds_120_seconds',count:1},{code:'paired_quote_missing',count:3}]};
  const html=renderBenchmark(view);
  for(const text of ['source/time-matched benchmark comparison remains unavailable','unmatched matured comparisons: 4',
    'missed or skipped owner windows: 1','owner_window_pair_span_exceeds_120_seconds','paired_quote_missing'])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/0\.00 pp|Matched stock-versus-benchmark paths are available/);
});
test('benchmark proof failure and failed dashboard read withhold old comparison results',()=>{
  for(const [view,unavailable] of [[{...benchmarkZero,status:'unverified',summary:{...benchmarkZero.summary!,comparison_pairs:999}},false],[benchmarkZero,true]] as const){
    const html=renderBenchmark(view as SwingBenchmarks,unavailable);
    assert.match(html,/Current benchmark source proof is unavailable/);assert.match(html,/Unverified/);
    assert.doesNotMatch(html,/<dd>999<\/dd>|0\.00 pp|Raw excess price path/);
  }
});
test('unpaired genuine owner-window entries remain visible before any outcome matures',()=>{
  const view={...benchmarkZero,summary:{...benchmarkZero.summary!,genuine_entry_count:1,paired_entry_count:0,unpaired_entry_count:1,nonqualifying_window_transitions:2},
    supplemental_poll:{status:'waiting_on_paired_observations',failure:'paired_quote_missing',completed_at:'2026-10-28T09:49:00-04:00',source:{path:'08_reviews/synthetic/poll.json',sha256:'c'.repeat(64)}}};
  const html=renderBenchmark(view);
  assert.match(html,/<dt>Entries missing matched benchmark observations<\/dt><dd>1<\/dd>/);
  assert.match(html,/<dt>Unique stock-horizon outcomes<\/dt><dd>0<\/dd>/);
  for(const text of ['waiting_on_paired_observations','paired_quote_missing','08_reviews/synthetic/poll.json','c'.repeat(64),
    'Retained nonqualifying window transitions: 2','Pairing gaps are visible before','b'.repeat(64)])assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/undefined|0\.00 pp|win rate: 0/);
});
test('latest source-bound paired poll overlays an earlier pending publication without inventing a mature outcome',()=>{
  const view={...benchmarkZero,read_time_summary:{...benchmarkZero.summary!,genuine_entry_count:1,paired_entry_count:1,unpaired_entry_count:0},
    supplemental_poll:{status:'waiting_on_paired_observations'},read_time_supplemental_poll:{status:'paired',completed_at:'2026-10-28T14:50:00-04:00',source:{path:'08_reviews/synthetic/latest-poll.json',sha256:'d'.repeat(64)}},
    read_time_proof:{generated_at:'2026-10-28T14:50:00-04:00',stock_ledger_sha256:'b'.repeat(64),comparison_ledger_sha256:'e'.repeat(64),protocol_sha256:'a'.repeat(64),original_projection_sha256:'f'.repeat(64)}};
  const html=renderBenchmark(view);
  assert.match(html,/Latest read-time poll.*status: paired/);
  assert.match(html,/<dt>Entries with matched benchmark observations<\/dt><dd>1<\/dd>/);
  assert.match(html,/No matured stock-horizon outcome/);assert.doesNotMatch(html,/status: waiting_on_paired_observations|undefined/);
});
test('comparison source proof labels a not-yet-created ledger and retains a present full hash',()=>{
  const proof={generated_at:'2026-10-28T14:50:00-04:00',stock_ledger_sha256:'b'.repeat(64),protocol_sha256:'a'.repeat(64),original_projection_sha256:'f'.repeat(64)};
  for(const comparison_ledger_sha256 of [null,undefined]){
    const html=renderBenchmark({...benchmarkZero,read_time_summary:benchmarkZero.summary,read_time_proof:{...proof,comparison_ledger_sha256}});
    assert.match(html,/comparison ledger not yet created \(no matched outcomes\)/);assert.doesNotMatch(html,/comparison ledger \.|undefined/);
  }
  const html=renderBenchmark({...benchmarkZero,read_time_summary:benchmarkZero.summary,read_time_proof:{...proof,comparison_ledger_sha256:'e'.repeat(64)}});
  assert.ok(html.includes('comparison ledger '+'e'.repeat(64)));assert.doesNotMatch(html,/not yet created/);
});
