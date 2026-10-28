import type {Snapshot, StrategyReadiness, SwingResearch, SwingResearchCandidate, SwingReviewWindow, SwingCoverage, SwingBenchmarks} from './domain';
import {money, timeLabel} from './domain';

const readinessLabels:Record<StrategyReadiness['classification'],string>={
  valid_action:'Conditional action available',justified_no_action:'Completed no-entry / hold judgment',
  research_incomplete:'Research incomplete',plan_expired:'Plan expired — reassessment due',
  data_unavailable:'Current evidence unavailable',strategy_not_adopted:'Experimental — capital not authorized',
};
const actionLabels:Record<string,string>={ACTIONABLE_BUY:'BUY',ACTIONABLE_ADD:'ADD',HOLD:'HOLD',
  REDUCE_REVIEW:'REDUCE',EXIT_REVIEW:'EXIT',NO_ACTION:'WAIT',BLOCKED:'WAIT'};
const setupLabels:Record<string,string>={breakout:'Breakout',pullback_reclaim:'Pullback reclaim',trend_continuation:'Trend continuation'};
const price=(value:number|null)=>typeof value==='number'&&Number.isFinite(value)&&value>0?money(value):'Not established';
const count=(value:unknown)=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?value:null;

export function swingReviewState(row:SwingResearchCandidate,now:number,expectedSession:string|undefined) {
  const authority=row.research_only===true&&row.capital_authority===false&&row.actionable_quantity===0;
  const validity=row.validity;
  const windows=(row.timing?.review_windows??[]).filter(window=>Number.isFinite(Date.parse(window.starts_at))
    &&Number.isFinite(Date.parse(window.ends_at))&&Date.parse(window.starts_at)<Date.parse(window.ends_at));
  const start=Date.parse(validity?.starts_at??'');
  const end=Date.parse(validity?.ends_at??'');
  const valid=authority&&Number.isFinite(now)&&row.source_session===expectedSession&&validity?.session===row.entry_session
    &&Number.isFinite(start)&&Number.isFinite(end)&&start<end&&windows.length>0;
  const currentWindow=windows.find(window=>now>=Date.parse(window.starts_at)&&now<Date.parse(window.ends_at));
  const nextWindow=windows.find(window=>now<Date.parse(window.starts_at));
  if(!valid)return {state:'unverified',referenceLevelsVisible:false,quoteCurrent:false,currentWindow,nextWindow};
  if(now>=end)return {state:'expired',referenceLevelsVisible:false,quoteCurrent:false,currentWindow,nextWindow};
  if(row.timing?.permanent_for_signal_day===true&&row.timing.state==='invalidation_observed')
    return {state:'invalidation_observed',referenceLevelsVisible:true,quoteCurrent:false,currentWindow,nextWindow};
  if(now<start)return {state:'before_review_window',referenceLevelsVisible:true,quoteCurrent:false,currentWindow,nextWindow};
  if(!currentWindow)return {state:'between_review_windows',referenceLevelsVisible:true,quoteCurrent:false,currentWindow,nextWindow};
  const quote=row.timing?.quote_observation;
  const quoteCurrent=Boolean(row.timing?.current_quote_status==='current'&&quote&&quote.execution_quote===false&&Number.isFinite(quote.price)&&quote.price>0
    &&Number.isFinite(Date.parse(quote.trade_at))&&Number.isFinite(Date.parse(quote.observed_at))
    &&Date.parse(quote.trade_at)<=now&&Date.parse(quote.observed_at)<=now&&now<Date.parse(quote.expires_at));
  const state=row.timing?.state==='invalidation_observed'?'invalidation_observed'
    :quoteCurrent&&['condition_observed','outside_entry_band'].includes(row.timing?.state??'')?row.timing!.state:'awaiting_fresh_quote';
  return {state,referenceLevelsVisible:true,quoteCurrent,currentWindow,nextWindow};
}

function ReviewWindows({windows}:{windows:SwingReviewWindow[]}) {
  return <ul className="swing-review-windows">{windows.map(window=><li key={window.id}>
    <strong>{window.id==='morning'?'Morning':'Afternoon'} review:</strong> {timeLabel(window.starts_at)} — {timeLabel(window.ends_at)}
  </li>)}</ul>;
}

function SwingTimingStatus({row,now,expectedSession}:{row:SwingResearchCandidate;now:number;expectedSession:string|undefined}) {
  const state=swingReviewState(row,now,expectedSession);
  const labels:Record<string,string>={before_review_window:'Before the review window — dated research conditions retained',
    between_review_windows:'Between review windows — reassess at the next available window',
    awaiting_fresh_quote:'Review window open — current quote and entry verification required',
    condition_observed:'Entry-band condition observed — research review still required',
    outside_entry_band:'WAIT — observed price is outside the entry conditions',
    invalidation_observed:'WAIT — observed invalidation requires reassessment',
    expired:'WAIT — the research entry window expired',unverified:'WAIT — source session or timing is unverified'};
  const invalidated=row.timing?.permanent_for_signal_day===true&&state.state==='invalidation_observed';
  return <div className={`swing-timing${invalidated?' swing-invalidated':''}`} role="status"><strong>{invalidated?'WAIT — this signal was invalidated for its source day':labels[state.state]}</strong>
    {row.timing?.review_windows?<ReviewWindows windows={row.timing.review_windows}/>:null}
    {invalidated?<p>No further entry window remains for this source-day signal.</p>
      :state.currentWindow?<p>Current review: {state.currentWindow.id}. This clock state does not authorize an order.</p>
      :state.nextWindow?<p>Next review begins {timeLabel(state.nextWindow.starts_at)}.</p>:null}
    {state.quoteCurrent&&row.timing?.quote_observation?<p>Validated last-sale observation {money(row.timing.quote_observation.price)} at {timeLabel(row.timing.quote_observation.trade_at)}; expires {timeLabel(row.timing.quote_observation.expires_at)}.{row.timing.quote_observation.source_label?` Source: ${row.timing.quote_observation.source_label}.`:''} It is not an executable bid/ask or a fill.</p>
      :invalidated?<p>A later bounce or a fresh quote cannot renew this source-day setup. A new source-day observation and reassessment are required.</p>
      :<p>Current entry price is unverified. Frozen daily reference conditions do not establish a live rebound, execution price or available funds.</p>}
    {row.timing?.state==='invalidation_observed'&&!state.quoteCurrent?<p>A prior invalidation observation is retained for reassessment; its expired quote is not a current mark.</p>:null}
    {row.timing?.required_conditions.length?<ul>{row.timing.required_conditions.map(condition=><li key={condition}>{condition}</li>)}</ul>:null}
    {row.timing?.historical_invalidation?<small>Retained invalidation observation: {timeLabel(row.timing.historical_invalidation.observed_at)} · source record {row.timing.historical_invalidation.record_hash}. This is historical evidence, not a current mark.</small>:null}
    {row.timing?.last_evaluated_at?<small>Price-condition projection evaluated {timeLabel(row.timing.last_evaluated_at)}; this timestamp does not establish completed analyst research.</small>:null}
  </div>;
}

function HeldPurpose({data,now,unavailable}:{data:Snapshot;now:number;unavailable:boolean}) {
  const held=(data.positions??[]).filter(row=>Number.isFinite(row.shares)&&row.shares>0);
  if(!held.length)return null;
  const plans=new Map((data.plans??[]).map(plan=>[plan.ticker,plan]));
  const fields=[['strategy','Original investment purpose'],['holding_period_justification','Original holding rationale'],
    ['failure_condition','Original evidence / invalidation conditions'],['exit_rule','Original exit and reassessment rule'],
    ['entry_validity','Original addition conditions']] as const;
  return <details className="held-purpose"><summary>Original purpose and management conditions for recorded holdings</summary>
    <p>Recorded ownership, a maintained investment purpose and a current trade proposal are separate. Expiry requires reassessment; it does not prove a sale or renew a HOLD instruction.</p>
    {held.map(position=>{
      const plan=plans.get(position.ticker);
      const end=plan?.expires_at?Date.parse(plan.expires_at):NaN;
      const current=!unavailable&&plan?.status==='current'&&Number.isFinite(end)&&now<end;
      const purpose=plan?.purpose??{};
      const available=fields.filter(([key])=>typeof purpose[key]==='string'&&String(purpose[key]).trim());
      return <article className="held-purpose-row" key={position.ticker}>
        <h4>{position.ticker} · {position.shares} recorded share{position.shares===1?'':'s'}</h4>
        <p><strong>{current?'Current bounded purpose record':'Reassessment required — retained purpose is historical'}</strong></p>
        {plan?<small>Original review / validity deadline: {timeLabel(plan.expires_at)} · plan version {plan.version}. These source conditions do not create a new order.</small>
          :<p>No maintained purpose record is available in this verified view. The scheduled analyst must establish it; ownership alone does not complete the investment case.</p>}
        {available.length?<dl>{available.map(([key,label])=><div key={key}><dt>{label}</dt><dd>{String(purpose[key])}</dd></div>)}</dl>
          :plan?<p>The retained record does not establish structured purpose and management conditions.</p>:null}
      </article>;
    })}
  </details>;
}

function SwingCoveragePanel({view,unavailable}:{view:SwingCoverage;unavailable:boolean}) {
  if(view.schema_version!=='equity_swing_coverage_v1')return null;
  const authority=view.research_only===true&&view.capital_authority===false&&view.actionable_quantity===0
    &&view.automatic_action_allowed===false;
  const current=authority&&!unavailable;
  const required=view.required_session??view.coverage?.required_session;
  const admitted=current&&Array.isArray(view.admitted_history_tickers)?view.admitted_history_tickers:null;
  const leads=authority?(view.candidates??[]).slice(0,3):[];
  return <section className="swing-coverage" aria-label="Market coverage and outside-universe research">
    <h3>Market coverage and outside-universe research</h3>
    <p><strong>Broad daily-screen status:</strong> {current?view.current_discovery_status??view.status:'unverified at this read'}{required?` · required close ${required}`:''}.</p>
    {view.latest_provider_failure?.failure_code?<p><strong>Latest provider dependency:</strong> {view.latest_provider_failure.failure_code}{view.latest_provider_failure.http_status?` · HTTP ${view.latest_provider_failure.http_status}`:''}.</p>:null}
    {view.latest_provider_failure?.original_http_evidence==='not_retained_by_older_collector'?<p className="form-hint">An older provider attempt lacks retained original HTTP evidence; no successful fetch is inferred.</p>:null}
    <p>{admitted===null?'Current admitted research-history count is unverified.':`Independently admitted research histories: ${admitted.length}${admitted.length&&required?` · admitted close ${required}`:''}.`} Focused history recovery does not establish complete broad-market coverage, reviewed company quality or capital eligibility.</p>
    {view.coverage?.cached_grouped_files!==undefined?<p className="form-hint">Retained grouped-history files: {view.coverage.cached_grouped_files}{view.coverage.required_history_sessions?` / ${view.coverage.required_history_sessions}`:''}. File counts do not establish current admission.</p>:null}
    {current&&view.focused_recovery_status?<p className="form-hint">Focused recovery status: {view.focused_recovery_status}.</p>:null}
    {view.provisional_history_tickers?.length?<p>Provisional provider-adjusted histories: {view.provisional_history_tickers.length}. Cross-fetch basis consistency remains unverified; these are excluded from technical-history admission.</p>:null}
    {!current?<p role="status">Current coverage is unverified. Retained leads below remain dated research work; they are not current trade opportunities.</p>:null}
    {leads.length?<><h4>Bounded outside-universe research leads</h4><p className="form-hint">These are research leads in retained screen order, not a ranking of expected investment returns.</p>{leads.map(row=>{
      const historyCurrent=current&&admitted?.includes(row.ticker)&&row.research_only===true&&row.capital_authority===false&&row.actionable_quantity===0;
      return <article key={row.ticker} className="outside-research-lead"><h4>{row.ticker}{row.name?` · ${row.name}`:''}</h4>
        <p><strong>{historyCurrent?'History admitted for experimental research — company and entry review still required':'Dated research lead — current setup evidence remains unverified'}</strong></p>
        <small>Discovery session {row.discovery_session??'unverified'}{row.first_seen_at?` · first retained detection ${timeLabel(row.first_seen_at)}`:''}{typeof row.dated_screen_rank==='number'?` · dated screen position ${row.dated_screen_rank}`:''}.</small>
        <p>{row.next_step}</p><small>Research resolver: {row.resolver}. No current price or capital quantity is supplied by this coverage view.</small>
        {row.history_status||row.source_ids?.length?<details><summary>Retained history dependency and source identities</summary>
          {row.history_status?<p>{row.history_status}</p>:null}{row.source_ids?.length?<ul>{row.source_ids.map((id,index)=><li key={`${id}:${index}`}>{id}</li>)}</ul>:null}
        </details>:null}
      </article>;
    })}</>:<p>No verified outside-universe lead is available in this bounded coverage view. Missing coverage does not establish that no opportunity exists.</p>}
    {view.blockers?.length?<details><summary>Exact coverage dependencies</summary><ul>{view.blockers.map(reason=><li key={reason}>{reason}</li>)}</ul></details>:null}
  </section>;
}

function BenchmarkEvaluation({view,unavailable}:{view:SwingBenchmarks;unavailable:boolean}) {
  if(view.schema_version!=='equity_swing_benchmarks_v1')return null;
  const allowed=view.research_only===true&&view.capital_authority===false&&view.actionable_quantity===0
    &&view.automatic_action_allowed===false&&view.execution_quote===false&&view.profitability_established===false;
  const protocol=view.protocol;
  const protocolVerified=Array.isArray(protocol?.benchmarks)&&protocol.benchmarks.length===2&&protocol.benchmarks.includes('SPY')&&protocol.benchmarks.includes('QQQM')
    &&Array.isArray(protocol.horizons)&&protocol.horizons.length>0&&protocol.horizons.every(value=>Number.isFinite(value)&&value>0)
    &&Array.isArray(protocol.costs_bps)&&protocol.costs_bps.length>0&&protocol.costs_bps.every(value=>Number.isFinite(value)&&value>=0);
  const current=allowed&&protocolVerified&&!unavailable&&['pending_forward_evidence','raw_comparisons_available','reviewed_comparisons_available'].includes(view.status);
  const readTime=Boolean(view.read_time_summary&&view.read_time_proof);
  const summary=current?(readTime?view.read_time_summary:view.summary):undefined;
  const groups=current?(readTime?view.read_time_groups:view.groups)??[]:[];
  const dependencies=(readTime?view.read_time_dependencies:view.dependencies)??[];
  const poll=readTime?view.read_time_supplemental_poll:view.supplemental_poll;
  const metric=(value:unknown)=>count(value)===null?'Unverified':String(count(value));
  const excess=(value:unknown,pairs:number)=>pairs>0&&typeof value==='number'&&Number.isFinite(value)
    ?`${value>0?'+':''}${value.toFixed(2)} pp`:'Unestablished';
  const costs=Array.isArray(protocol?.costs_bps)?protocol.costs_bps:[];
  const matched=count(summary?.comparison_pairs);
  const available=count(summary?.unique_stock_outcomes);
  const methodLabels:Record<string,string>={benchmark_future_open:'First future open (modeled)',
    observed_owner_window_mark_not_fill:'Matched owner-window marks',
    observed_owner_window_delay_3_minutes_mark_not_fill:'Owner window + 3 minutes',
    observed_owner_window_delay_5_minutes_mark_not_fill:'Owner window + 5 minutes',
    observed_owner_window_delay_10_minutes_mark_not_fill:'Owner window + 10 minutes'};
  return <section className="matched-benchmarks" aria-label="Matched SPY and QQQM evaluation">
    <h3>Matched SPY / QQQM evaluation</h3>
    {!current?<p role="status">Current benchmark source proof is unavailable. Comparison results are withheld until the stock path, benchmark history and timing can be validated.</p>
      :available===null||matched===null?<p>The current source ledger does not establish the comparison counts. Results remain unverified.</p>
      :available===0?<p>No matured stock-horizon outcome is available for a matched comparison yet. Investment effectiveness remains unestablished.</p>
      :matched===0?<p>Matured stock-horizon outcomes exist; a source/time-matched benchmark comparison remains unavailable.</p>
      :<p>Matched stock-versus-benchmark paths are available for research review. Realized portfolio performance and investment edge remain unestablished.</p>}
    <dl className="benchmark-summary benchmark-entry-summary" aria-label="Owner-window entry pairing">
      <div><dt>Observed qualifying entry variants</dt><dd>{metric(summary?.genuine_entry_count)}</dd></div>
      <div><dt>Entries with matched benchmark observations</dt><dd>{metric(summary?.paired_entry_count)}</dd></div>
      <div><dt>Entries missing matched benchmark observations</dt><dd>{metric(summary?.unpaired_entry_count)}</dd></div>
    </dl>
    <p className="form-hint">Pairing gaps are visible before the 5 / 10 / 14-session outcomes mature. These source-bound entry variants are observations, not independent trades or fills.</p>
    <dl className="benchmark-summary">
      <div><dt>Unique stock-horizon outcomes</dt><dd>{metric(summary?.unique_stock_outcomes)}</dd></div>
      <div><dt>Source/time-matched pairs</dt><dd>{metric(summary?.comparison_pairs)}</dd></div>
      <div><dt>Raw pairs awaiting joint review</dt><dd>{metric(summary?.raw_pairs)}</dd></div>
      <div><dt>Reviewed fixed-path pairs</dt><dd>{metric(summary?.reviewed_pairs)}</dd></div>
    </dl>
    <p className="form-hint">Distinct matched stock-horizon outcomes: {metric(summary?.unique_matched_stock_outcomes)} · distinct reviewed stock-horizon outcomes: {metric(summary?.unique_reviewed_stock_outcomes)}.</p>
    <p className="form-hint">Counts use the source ledger's distinct stock-outcome identities. Per-benchmark, entry-method and horizon groups overlap; adding the rows would not produce a count of independent trades.</p>
    <p>Pending stock horizons: {metric(summary?.pending_stock_horizons)} · unmatched matured comparisons: {metric(summary?.unmatched_pairs)} · missed or skipped owner windows: {metric(summary?.missed_or_skipped_windows)}.</p>
    {summary?.nonqualifying_window_transitions!==undefined?<p className="form-hint">Retained nonqualifying window transitions: {metric(summary.nonqualifying_window_transitions)}. A later qualifying observation can recover a window without erasing its earlier transition.</p>:null}
    <p>Qualified strategy execution paths: {metric(summary?.qualified_strategy_paths)}. A reliable win rate, profitability and strategy promotion remain unestablished. Capital authority remains zero.</p>
    {current&&readTime?<small>Comparison counts were revalidated at {timeLabel(view.read_time_proof?.generated_at)}. The original sealed publication and its source observations remain unchanged.</small>:null}
    <p className="form-hint">Raw excess values are stock-minus-benchmark price-path differences in percentage points under the declared cost sensitivities. Reviewed comparisons require both stock and benchmark source/corporate-action review. Matched owner-window marks require the protocol's timing proof and do not establish execution fills.</p>
    {groups.length?<details><summary>Matched horizons, entry methods and cost sensitivities</summary>
      <p>One-way cost assumptions: {costs.map(cost=>`${cost} bps`).join(' / ')} for each side of both paths. Horizons stay separate.</p>
      <div className="table-scroll benchmark-table-scroll" tabIndex={0} aria-label="Benchmark comparison groups"><table className="benchmark-table"><thead><tr>
        <th>Benchmark / horizon</th><th>Entry method / cohort</th><th>Raw / reviewed pairs</th><th>Raw excess price path</th><th>Reviewed fixed-path excess</th>
      </tr></thead><tbody>{groups.map((group,index)=><tr key={`${group.benchmark}:${group.entry_method}:${group.horizon_sessions}:${group.cohort}:${index}`}>
        <td>{group.benchmark} · {group.horizon_sessions} sessions</td><td>{methodLabels[group.entry_method]??group.entry_method.replaceAll('_',' ')}<br/>{group.cohort.replaceAll('_',' ')}</td>
        <td>{group.raw_pairs} / {group.reviewed_pairs}</td>
        <td>{costs.map(cost=><div key={cost}>{cost} bps: {excess(group.raw_mean_excess_price_path_pct_by_cost_bps?.[String(cost)],group.raw_pairs)}</div>)}</td>
        <td>{costs.map(cost=><div key={cost}>{cost} bps: {excess(group.reviewed_mean_excess_price_path_pct_by_cost_bps?.[String(cost)],group.reviewed_pairs)}</div>)}</td>
      </tr>)}</tbody></table></div>
    </details>:null}
    {dependencies.length?<details><summary>Unmatched owner-window and source dependencies</summary><ul>{dependencies.map((item,index)=><li key={`${item.code}:${index}`}>{item.code} · {item.count}</li>)}</ul><p>Unmatched or missing observations retain their dependency. They do not acquire an assumed benchmark entry or a zero return.</p></details>:null}
    <details><summary>Supplemental paired-observation poll</summary>
      <p>{readTime?'Latest read-time poll':'Original publication poll'} status: {current?poll?.status??'not_yet_verified':'unverified at this read'}.</p>
      {poll?.completed_at?<small>Dated poll completed {timeLabel(poll.completed_at)}. This is an operational receipt, not proof of a fill or a matured outcome.</small>:null}
      {poll?.failure?<p>Retained poll dependency: {poll.failure}</p>:null}
      {poll?.source?<small>Retained poll source {poll.source.path} · SHA-256 {poll.source.sha256}</small>:null}
      {poll?.observer_source?<small>Original stock-observer source {poll.observer_source.path} · SHA-256 {poll.observer_source.sha256}</small>:null}
    </details>
    {protocolVerified&&protocol?<details><summary>Comparison protocol and source proof</summary><p>{protocol.version} · horizons {protocol.horizons.join(' / ')} trading sessions.</p><small>Original comparison publication {timeLabel(view.generated_at)} · protocol SHA-256 {protocol.sha256}</small>
      {view.stock_source?<small>Original stock ledger SHA-256 {view.stock_source.sha256} · {view.stock_source.records} records.</small>:null}
      {readTime?<small>Read-time stock ledger {view.read_time_proof?.stock_ledger_sha256} · comparison ledger {view.read_time_proof?.comparison_ledger_sha256}.</small>:null}
    </details>:null}
  </section>;
}

function ReadinessRow({row,unavailable=false}:{row:StrategyReadiness;unavailable?:boolean}) {
  const pending=unavailable&&row.classification==='valid_action';
  const waiting=pending||['plan_expired','data_unavailable','research_incomplete','strategy_not_adopted'].includes(row.classification);
  return <article className="strategy-readiness-row">
    <h4>{row.ticker} · {waiting?'WAIT':actionLabels[row.canonical_decision]??'WAIT'}</h4>
    <p><strong>{pending?'Current action requires verification':readinessLabels[row.classification]??'Current state unverified'}</strong></p>
    <p className="form-hint">{row.strategy_id} · {row.horizon}</p>
    <p>{row.reason}</p>
    <p><strong>Next step:</strong> {row.next_step}</p>
    <small>{row.resolver?`Owner: ${row.resolver}. `:''}{row.review_at?`Review ${timeLabel(row.review_at)}.`:''}</small>
  </article>;
}

function SwingSetups({view,data,now,unavailable}:{view:SwingResearch;data:Snapshot;now:number;unavailable:boolean}) {
  const reviewWindowsVersion=view.schema_version==='equity_swing_research_v2';
  const authorizedResearch=['equity_swing_research_v1','equity_swing_research_v2'].includes(view.schema_version)&&view.research_only===true
    &&view.capital_authority===false&&view.actionable_quantity===0;
  const current=authorizedResearch&&view.status==='experimental_current'&&!unavailable;
  const candidates=current?view.candidates:[];
  const expired=count(view.expired_candidates_suppressed)??0;
  const elapsedObservations=count(view.coverage?.expired_entry_observations)??0;
  const performance=view.read_time_performance??view.performance;
  const observations=count(performance?.observations);
  const outcomes=count(performance?.outcomes);
  const qualified=count(performance?.performance_eligible_paths);
  const actionReview=count(performance?.corporate_action_review_required);
  const blockers=[...new Set([...(view.blockers??[]),...(view.dependencies??[])])];
  return <section className="swing-research" aria-label="Experimental swing research">
    <div className="strategy-section-heading"><h3>5–14-session swing research</h3><span className="status amber">Experimental · no capital authority</span></div>
    <p>These are prospective daily-bar research setups. No shares are authorized, no orders are assumed, and a setup is not a recommendation to trade.</p>
    {reviewWindowsVersion?<p>Daily reference conditions may remain useful after the open during their named review windows. A fresh last sale can verify a current price condition; it cannot prove an intraday rebound path, bid/ask execution or a broker fill.</p>:null}
    {reviewWindowsVersion&&view.review_windows?.length?<ReviewWindows windows={view.review_windows}/>:null}
    {reviewWindowsVersion?<p className="form-hint">{view.selection_basis??'Selected setups follow the frozen daily-bar screen. Their order is not a ranking of expected profit.'} Business quality, catalyst direction and executable position size still require their own review.</p>:null}
    {!current?<p role="status"><strong>WAIT:</strong> Current source/session validation is unavailable. Setup price levels are withheld.</p>
      :!candidates.length?<p><strong>WAIT:</strong> {expired?'Previously captured setups have elapsed entry windows; none remains current.':'No qualifying setup is retained for the current validated source session.'} No trade is forced.</p>:null}
    {expired?<p>{expired} expired setup card{expired===1?' was':'s were'} suppressed at read time. Expired entries are not replayed.</p>:null}
    {elapsedObservations?<p className="form-hint">{elapsedObservations} captured ticker/session observation{elapsedObservations===1?' has':'s have'} an elapsed first-entry open. This count includes screened observations and is not a count of trades.</p>:null}
    <p className="swing-evidence"><strong>Prospective evidence:</strong> {observations===null?'Observation count unavailable':`${observations} recorded ticker/session observations`}; {outcomes===null?'matured horizon count unavailable':`${outcomes} matured horizon records`}. Profitability and a reliable win rate remain unestablished. Repeated horizons are not independent trades.</p>
    {view.read_time_performance?<p className="form-hint">{unavailable?'Retained study counts come from the last successful read and have not been revalidated now.':'These study counts were source-validated at this read.'} The original publication remains dated{view.read_time_study_proof?.original_projection_generated_at?` ${timeLabel(view.read_time_study_proof.original_projection_generated_at)}`:''}; no earlier email or observation is rewritten.</p>:null}
    {qualified!==null?<p className="form-hint">Effectiveness-qualified paths: {qualified}.{actionReview!==null?` Corporate-action reviews still required: ${actionReview}.`:''} Unadjusted price paths and software passes are not verified economic returns.</p>:null}
    {candidates.map(row=>{
      const end=Date.parse(row.review_deadline);
      const legacyFresh=row.research_only===true&&row.capital_authority===false&&row.actionable_quantity===0
        &&row.source_session===data.expected_market_session&&Number.isFinite(end)&&now<end;
      const timing=reviewWindowsVersion?swingReviewState(row,now,data.expected_market_session):null;
      const levelsVisible=timing?timing.referenceLevelsVisible:legacyFresh;
      return <article className="swing-setup" key={`${row.ticker}:${row.setup}`}>
        <h4>{row.ticker} · {setupLabels[row.setup]??row.setup}</h4>
        <p><strong>{levelsVisible?'Research setup — WAIT for a validated capital proposal':'WAIT — dated setup requires reassessment'}</strong></p>
        <p>{row.thesis}</p>
        <p className="form-hint">Source close {row.source_session} · {row.horizon_sessions.join(' / ')} trading-session evaluation horizons · research entry session {row.entry_session}.</p>
        {reviewWindowsVersion?<SwingTimingStatus row={row} now={now} expectedSession={data.expected_market_session}/>:null}
        {levelsVisible?<dl className="condition-grid">
          <div><dt>{reviewWindowsVersion?'Dated daily reference trigger':'Observed entry trigger'}</dt><dd>{price(row.entry_trigger)}</dd><dd>Maximum research entry {price(row.max_entry)}; skip above it. These are research conditions, not current execution quotes.</dd></div>
          <div><dt>Price invalidation</dt><dd>{price(row.invalidation)}</dd><dd>Daily bars do not prove intraday sequencing or a fill.</dd></div>
          <div><dt>Profit reference</dt><dd>{price(row.profit_reference)}</dd><dd>Hypothetical 2R evaluation reference; not a forecast or observed resistance.</dd></div>
          <div><dt>Setup review deadline</dt><dd>{timeLabel(row.review_deadline)}</dd><dd>{reviewWindowsVersion?'The dated blueprint ends at its named deadline. Recheck current price and every unresolved condition within a valid review window.':'Review before the first future open. An elapsed entry window is not replayed.'}</dd></div>
          {reviewWindowsVersion?<div><dt>Capital position size</dt><dd>Not sized for execution · zero approved shares</dd><dd>Strategy adoption, current cash, allocation, risk and a separate complete human-review proposal remain required.</dd></div>:null}
        </dl>:<p>Expired or unverified levels are withheld. This does not renew the setup.</p>}
        {levelsVisible&&row.time_exits?.length?<p>Prospective time exits: {row.time_exits.map(exit=>`${exit.holding_sessions} sessions → ${exit.session}`).join('; ')}. These are comparison horizons, not assumed holdings.</p>:null}
        {row.skip_reasons.length?<p><strong>Skip conditions:</strong> {row.skip_reasons.join('; ')}</p>:null}
        <p className="form-hint">Evidence: {row.evidence_quality.replaceAll('_',' ')}. Catalyst: {row.catalyst_status.replaceAll('_',' ')}.</p>
        {row.uncertainty.length?<details><summary>Uncertainty and execution limits</summary><ul>{row.uncertainty.map(v=><li key={v}>{v}</li>)}</ul></details>:null}
        {reviewWindowsVersion&&(row.entry_rule||row.exit_rule)?<details><summary>Frozen entry and exit evaluation rules</summary>
          {row.entry_rule?<p>{row.entry_rule}</p>:null}{row.exit_rule?<p>{row.exit_rule}</p>:null}
          <p>These research rules do not establish an order, a fill or an adopted stop-loss instruction.</p>
        </details>:null}
      </article>;
    })}
    {blockers.length?<ul>{blockers.map(v=><li key={v}>{v}</li>)}</ul>:null}
    {view.additional_setup_count?<p className="form-hint">{view.additional_setup_count} additional retained setups are omitted from this bounded view; the research store preserves them.</p>:null}
    {view.limitations?.length?<details><summary>Research limitations</summary><ul>{view.limitations.map(v=><li key={v}>{v}</li>)}</ul></details>:null}
    {view.adoption?<details><summary>Evidence required before strategy adoption</summary><p>Forward observations, execution feasibility, costs, missed entries and adverse outcomes must be reviewed. Software validation does not establish profitability. Capital eligibility remains under the existing approved strategies.</p></details>:null}
  </section>;
}

export default function StrategyFrameworkPanel({data,now,unavailable=false}:{data:Snapshot;now:number;unavailable?:boolean}) {
  const view=data.strategy_framework;
  if(!view||view.schema_version!=='equity_strategy_framework_v1'||view.automatic_action_allowed!==false)return null;
  const rows=view.decisions??[];
  const shown=rows.filter(row=>row.classification==='valid_action'||row.classification==='plan_expired'
    ||row.classification==='justified_no_action').slice(0,6);
  const remaining=rows.filter(row=>!shown.includes(row));
  return <section className="strategy-framework" aria-label="Strategy and decision readiness">
    <h2>Strategy and decision readiness</h2>
    <p>Growth valuations and short-term price setups use different horizons. Only a complete, current capital card above can authorize a conditional human-review draft.</p>
    {view.status!=='ready'?<p role="status"><strong>WAIT — readiness is unverified.</strong> {view.validation_error??'Current source and capital bindings must be verified before restoring an analyst handoff.'}</p>:null}
    <div className="strategy-overview">{view.strategies.map(strategy=><article key={strategy.strategy_id}>
      <h3>{strategy.label??strategy.name??strategy.strategy_id}</h3><p>{strategy.horizon}</p>
      <span className={`status ${strategy.capital_authority?'':'amber'}`}>{strategy.capital_authority?'Approved route · all gates still apply':'Research only · no capital authority'}</span>
      {strategy.description?<p>{strategy.description}</p>:null}
    </article>)}</div>
    {unavailable?<p role="status">The current dashboard read is unavailable. Previous reasoning remains dated; no new action is implied.</p>:null}
    {shown.map(row=><ReadinessRow row={row} unavailable={unavailable} key={`${row.ticker}:${row.strategy_id}`}/>)}
    {remaining.length?<details><summary>Other research states and dependencies</summary>{remaining.map(row=><ReadinessRow row={row} unavailable={unavailable} key={`${row.ticker}:${row.strategy_id}`}/>)}</details>:null}
    {view.analyst_handoff.length?<details className="analyst-handoff"><summary>What the scheduled analyst must resolve next</summary><ol>{view.analyst_handoff.map((task,i)=><li key={`${task.ticker}:${i}`}><strong>{task.ticker}</strong> — {task.next_step}{task.reason?<p>{task.reason}</p>:null}<small>{task.resolver}{task.review_at?` · review ${timeLabel(task.review_at)}`:''}</small></li>)}</ol><p>Queued work is not completed analysis or an investment recommendation.</p></details>:null}
    <HeldPurpose data={data} now={now} unavailable={unavailable}/>
    {view.swing_coverage?<SwingCoveragePanel view={view.swing_coverage} unavailable={unavailable}/>:null}
    {view.swing_research?<SwingSetups view={view.swing_research} data={data} now={now} unavailable={unavailable}/>:null}
    {view.swing_benchmarks?<BenchmarkEvaluation view={view.swing_benchmarks} unavailable={unavailable}/>:null}
  </section>;
}
