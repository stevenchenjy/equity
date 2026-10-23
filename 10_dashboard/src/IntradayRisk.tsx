import type {IntradayNumber, IntradayRisk, Snapshot} from './domain';

const numeric=(value:IntradayNumber|undefined):number|null=>{
  if(value===null||value===undefined||value==='')return null;
  const result=Number(value);return Number.isFinite(result)?result:null;
};
const dollars=(value:IntradayNumber|undefined)=>{
  const parsed=numeric(value);return parsed===null?'Unverified':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(parsed);
};
const percentage=(value:IntradayNumber|undefined)=>{
  const parsed=numeric(value);return parsed===null?'Unverified':parsed.toFixed(2)+'%';
};
const timestamp=(value:string|undefined)=>{
  if(!value||!Number.isFinite(Date.parse(value)))return 'Unverified';
  return new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'}).format(new Date(value))+' ET';
};
export function intradayDisplayCurrent(report:IntradayRisk,now:number,unavailable=false):boolean {
  const observed=Date.parse(report.mark_as_of??''),expires=Date.parse(report.expires_at??'');
  return !unavailable&&['validated','current'].includes(report.status)&&Number.isFinite(observed)&&Number.isFinite(expires)
    &&Number.isFinite(now)&&now>=observed&&now<expires;
}
function conditions(report:IntradayRisk,current:boolean):{label:string;message:string}[] {
  return [['plan_conditions','Existing plan condition'],['reassessment_triggers','Risk reassessment']].flatMap(([key,label])=>{
    const rows=report[key as 'plan_conditions'|'reassessment_triggers'];
    return (Array.isArray(rows)?rows:[]).flatMap(row=>{
      if(typeof row==='string')return [{label,message:row}];
      const text=row.message??row.condition??row.description;
      if(!text)return [];
      if(!current&&['recorded_stop_review','allocation','tactical_budget'].includes(row.kind??''))
        return [{label,message:`${row.ticker??'Portfolio'}: this price-dependent condition is unverified at the current clock. Refresh the observation before assessing a crossing.`}];
      const reference=current&&numeric(row.reference_price)!==null?` Reference ${dollars(row.reference_price)}; observed ${dollars(row.observed_price)}.`:'';
      return [{label,message:`${row.ticker??'Portfolio'}: ${text} (${(row.status??'unverified').replaceAll('_',' ')}).${reference}`}];
    });
  });
}
export default function IntradayRiskPanel({data,now,unavailable=false}:{data:Snapshot;now:number;unavailable?:boolean}) {
  const report=data.intraday_portfolio_risk;
  if(!report||report.schema_version!=='intraday_portfolio_risk_v1')return null;
  const current=intradayDisplayCurrent(report,now,unavailable);
  const expired=Number.isFinite(Date.parse(report.expires_at??''))&&now>=Date.parse(report.expires_at!);
  const status=unavailable?'View unavailable':expired?'Expired observation':['validated','current'].includes(report.status)&&!current?'Unverified observation':report.status;
  const allocation=report.allocation;
  return <section className="candidate-section intraday-risk" aria-label="Intraday portfolio risk">
    <h2>Intraday portfolio risk</h2>
    <p className="panel-lead"><strong>{current?'Validated observation':status}</strong> · Prices as of {timestamp(report.mark_as_of)} · Expires {timestamp(report.expires_at)}.</p>
    <p className="panel-lead">Session {report.session_date??'unverified'} · Reference close {report.baseline_session??'unverified'}. These are dated observations, not a streaming quote.</p>
    {current?<div className="account-strip">
      <div><span>Intraday marked value</span><strong>{dollars(report.portfolio_nav)}</strong></div>
      <div><span>Same-inventory close value</span><strong>{dollars(report.baseline_portfolio_nav)}</strong></div>
      <div><span>Price-only change</span><strong>{dollars(report.value_change_usd)} · {percentage(report.value_change_pct)}</strong></div>
      <p>Both values use the same recorded holdings and planning cash. This is not the account's actual daily return or peak drawdown.</p>
    </div>:<p className="summary-context" role="status">A complete current portfolio valuation and price-only change are unavailable. Partial or expired marks do not establish a portfolio loss.</p>}
    <p className="panel-lead">Planning cash {dollars(report.cash_usd)} is unchanged. The closing-value account summary and recorded holdings remain separate.</p>
    {current&&allocation?<p className="panel-lead">Marked allocation: index core {percentage(allocation.core_weight_pct)} · individual stocks {percentage(allocation.stock_weight_pct)} · cash {percentage(allocation.cash_weight_pct)}. Existing allocation and risk rules remain unchanged.</p>:null}
    {current&&report.concentration?.largest_stock_ticker?<p className="panel-lead">Largest individual stock: {report.concentration.largest_stock_ticker} at {percentage(report.concentration.largest_stock_weight_pct)}. No fixed single-stock cap; ETF/stock economic overlap is not measured by these weights.</p>:null}
    {report.positions?.length?<div className="table-scroll"><table><thead><tr><th>Recorded holding</th><th>Observed price</th><th>Price-only change / weight</th><th>Source and timestamp</th></tr></thead><tbody>{report.positions.map(row=>{
      const marked=current&&['validated','current'].includes(row.status);
      return <tr key={row.ticker}><td data-label="Recorded holding"><strong>{row.ticker}</strong><br/>{numeric(row.shares)??'Unverified'} recorded shares</td>
        <td data-label="Observed price">{marked?dollars(row.price):'Unverified'}<br/><small>{marked?'Validated observation':expired?'Expired observation':'Unverified observation'}</small></td>
        <td data-label="Price-only change / weight">{marked?percentage(row.price_change_pct):'Unverified'} / {marked?percentage(row.weight_pct):'Unverified'}</td>
        <td data-label="Source and timestamp">{row.source??'Source unverified'} · {row.delay_label??'Delay unverified'}<br/><small>{timestamp(row.price_as_of)}</small></td></tr>;
    })}</tbody></table></div>:null}
    {report.tactical_limits?<details className="source-details"><summary>Existing tactical risk limits</summary>
      <p>Ordinary risk {percentage(report.tactical_limits.ordinary_risk_pct)} · event risk {percentage(report.tactical_limits.event_risk_pct)} · combined risk {percentage(report.tactical_limits.combined_risk_pct)} · tactical position maximum {percentage(report.tactical_limits.max_position_pct)} · minimum reward/risk {numeric(report.tactical_limits.min_reward_to_risk)??'Unverified'}R.</p>
      <p>{current?`Recorded planned tactical loss ${dollars(report.tactical_limits.existing_planned_risk_usd)}; ${percentage(report.tactical_limits.combined_planned_risk_pct)} of marked value. Current status: ${(report.tactical_limits.combined_status??'unverified').replaceAll('_',' ')}.`:'Current tactical exposure relative to marked value is unverified.'} Planned risk is not a guaranteed maximum loss.</p>
    </details>:null}
    {conditions(report,current).length?<details className="source-details"><summary>Existing risk and plan conditions</summary>{conditions(report,current).map((row,index)=><p key={index}><strong>{row.label}:</strong> {row.message}</p>)}</details>:null}
    {report.dependencies?.length?<p className="summary-context">Unverified dependencies: {report.dependencies.join('; ')}.</p>:null}
    {report.limitations?.length?<details className="source-details"><summary>Scope and evidence limits</summary>{report.limitations.map((line,index)=><p key={index}>{line}</p>)}</details>:null}
    <p className="panel-lead">Price monitoring alone creates no buy/sell instruction and no extra email. All existing entry gates and human execution rules remain in force.</p>
  </section>;
}
