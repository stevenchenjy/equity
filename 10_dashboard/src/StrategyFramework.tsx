import type {Snapshot, StrategyReadiness, SwingResearch} from './domain';
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
  const authorizedResearch=view.schema_version==='equity_swing_research_v1'&&view.research_only===true
    &&view.capital_authority===false&&view.actionable_quantity===0;
  const current=authorizedResearch&&view.status==='experimental_current'&&!unavailable;
  const candidates=current?view.candidates:[];
  const expired=count(view.expired_candidates_suppressed)??0;
  const elapsedObservations=count(view.coverage?.expired_entry_observations)??0;
  const observations=count(view.performance?.observations);
  const outcomes=count(view.performance?.outcomes);
  const blockers=[...new Set([...(view.blockers??[]),...(view.dependencies??[])])];
  return <section className="swing-research" aria-label="Experimental swing research">
    <div className="strategy-section-heading"><h3>5–14-session swing research</h3><span className="status amber">Experimental · no capital authority</span></div>
    <p>These are prospective daily-bar research setups. No shares are authorized, no orders are assumed, and a setup is not a recommendation to trade.</p>
    {!current?<p role="status"><strong>WAIT:</strong> Current source/session validation is unavailable. Setup price levels are withheld.</p>
      :!candidates.length?<p><strong>WAIT:</strong> {expired?'Previously captured setups have elapsed entry windows; none remains current.':'No qualifying setup is retained for the current validated source session.'} No trade is forced.</p>:null}
    {expired?<p>{expired} expired setup card{expired===1?' was':'s were'} suppressed at read time. Expired entries are not replayed.</p>:null}
    {elapsedObservations?<p className="form-hint">{elapsedObservations} captured ticker/session observation{elapsedObservations===1?' has':'s have'} an elapsed first-entry open. This count includes screened observations and is not a count of trades.</p>:null}
    <p className="swing-evidence"><strong>Prospective evidence:</strong> {observations===null?'Observation count unavailable':`${observations} recorded ticker/session observations`}; {outcomes===null?'matured horizon count unavailable':`${outcomes} matured horizon records`}. Profitability and a reliable win rate remain unestablished. Repeated horizons are not independent trades.</p>
    {candidates.map(row=>{
      const end=Date.parse(row.review_deadline);
      const fresh=row.research_only===true&&row.capital_authority===false&&row.actionable_quantity===0
        &&row.source_session===data.expected_market_session&&Number.isFinite(end)&&now<end;
      return <article className="swing-setup" key={`${row.ticker}:${row.setup}`}>
        <h4>{row.ticker} · {setupLabels[row.setup]??row.setup}</h4>
        <p><strong>{fresh?'Research setup — WAIT for review':'WAIT — dated setup requires reassessment'}</strong></p>
        <p>{row.thesis}</p>
        <p className="form-hint">Source close {row.source_session} · {row.horizon_sessions.join(' / ')} trading-session evaluation horizons · next possible entry session {row.entry_session}.</p>
        {fresh?<dl className="condition-grid">
          <div><dt>Observed entry trigger</dt><dd>{price(row.entry_trigger)}</dd><dd>Maximum research entry {price(row.max_entry)}; skip a gap above it.</dd></div>
          <div><dt>Price invalidation</dt><dd>{price(row.invalidation)}</dd><dd>Daily bars do not prove intraday sequencing or a fill.</dd></div>
          <div><dt>Profit reference</dt><dd>{price(row.profit_reference)}</dd><dd>Hypothetical 2R evaluation reference; not a forecast or observed resistance.</dd></div>
          <div><dt>Setup review deadline</dt><dd>{timeLabel(row.review_deadline)}</dd><dd>Review before the first future open. An elapsed entry window is not replayed.</dd></div>
        </dl>:<p>Expired or unverified levels are withheld. This does not renew the setup.</p>}
        {fresh&&row.time_exits?.length?<p>Prospective time exits: {row.time_exits.map(exit=>`${exit.holding_sessions} sessions → ${exit.session}`).join('; ')}. These are comparison horizons, not assumed holdings.</p>:null}
        {row.skip_reasons.length?<p><strong>Skip conditions:</strong> {row.skip_reasons.join('; ')}</p>:null}
        <p className="form-hint">Evidence: {row.evidence_quality.replaceAll('_',' ')}. Catalyst: {row.catalyst_status.replaceAll('_',' ')}.</p>
        {row.uncertainty.length?<details><summary>Uncertainty and execution limits</summary><ul>{row.uncertainty.map(v=><li key={v}>{v}</li>)}</ul></details>:null}
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
    {view.swing_research?<SwingSetups view={view.swing_research} data={data} now={now} unavailable={unavailable}/>:null}
  </section>;
}
