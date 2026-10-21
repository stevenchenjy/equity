import {useState} from 'react';
import type {EarningsEvent, EarningsEventView, Snapshot} from './domain';

const statusLabels:Record<EarningsEvent['status'],string> = {
  detected:'Detected', awaiting_research:'Awaiting research', research_in_progress:'Research in progress',
  reviewed_without_entry:'Reviewed without entry', eligible_conditional_plan:'Eligible conditional plan — see action cards',
  elapsed_unreviewed:'Elapsed without pre-event review', cancelled:'Cancelled', schedule_conflict:'Schedule conflict',
};
const sessionLabels:Record<EarningsEvent['session'],string> = {
  after_close:'after close', before_open:'before open', time_unknown:'time unconfirmed',
};
const eventTime=(value:string|null|undefined)=>{
  if(!value||!Number.isFinite(Date.parse(value)))return 'Unverified';
  return new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(value))+' ET';
};
export function earningsStatus(row:EarningsEvent,report:EarningsEventView,data:Snapshot,unavailable:boolean):string {
  const admitted=data.capital_decision?.decisions.some(candidate=>candidate.ticker===row.ticker
    &&['ACTIONABLE_BUY','ACTIONABLE_ADD'].includes(candidate.decision)&&candidate.shares>0&&candidate.order_draft?.side==='buy');
  if(row.status==='eligible_conditional_plan'&&(unavailable||report.status!=='ready'||row.timing!=='pre_event'||!admitted))return 'Research in progress — current conditional plan unverified';
  return statusLabels[row.status]??'Research state unverified';
}
const safeSource=(url:string)=>{try{return new URL(url).protocol==='https:'}catch{return false}};

const deadlineValue=(row:EarningsEvent)=>{
  const value=Date.parse(row.research_deadline_at??'');
  return Number.isFinite(value)?value:Number.POSITIVE_INFINITY;
};
export function orderedUpcoming(events:EarningsEvent[]):EarningsEvent[] {
  return events.filter(row=>row.timing==='pre_event'&&row.status!=='cancelled')
    .sort((a,b)=>Number(!['eligible_conditional_plan','reviewed_without_entry'].includes(a.status))-Number(!['eligible_conditional_plan','reviewed_without_entry'].includes(b.status))
      ||deadlineValue(a)-deadlineValue(b)||a.event_date.localeCompare(b.event_date)||a.ticker.localeCompare(b.ticker)||a.event_id.localeCompare(b.event_id));
}
export const EARNINGS_PAGE_SIZE=50;
export function earningsPage(events:EarningsEvent[],page:number):EarningsEvent[] {
  const safePage=Math.max(0,Math.min(Math.trunc(page),Math.max(0,Math.ceil(events.length/EARNINGS_PAGE_SIZE)-1)));
  return events.slice(safePage*EARNINGS_PAGE_SIZE,(safePage+1)*EARNINGS_PAGE_SIZE);
}
function EventTable({rows,report,data,unavailable}:{rows:EarningsEvent[];report:EarningsEventView;data:Snapshot;unavailable:boolean}) {
  return <div className="table-scroll"><table><thead><tr><th>Company / event</th><th>Research deadline</th><th>Research status and next step</th></tr></thead><tbody>{rows.map(row=><tr key={row.event_id}>
      <td data-label="Company / event"><strong>{row.ticker}</strong><br/>{row.company_name}<br/>{row.event_date} · {sessionLabels[row.session]??'time unconfirmed'}<br/><small>{row.date_confidence==='issuer_confirmed'?'Issuer-confirmed':'Exchange estimate — issuer confirmation required'}</small></td>
      <td data-label="Research deadline">{eventTime(row.research_deadline_at)}<br/><small>First detected {eventTime(row.first_detected_at)}</small></td>
      <td data-label="Research status and next step"><strong>{earningsStatus(row,report,data,unavailable)}</strong><p>{row.next_step}</p>{row.blockers.length?<p>Research dependency: {row.blockers.join('; ')}</p>:null}
        <details><summary>Evidence and timing</summary><p>Research state: {row.research_state}. Observation timing: {row.timing}. Release timing: {sessionLabels[row.session]??'time unconfirmed'}; {row.date_confidence==='issuer_confirmed'&&row.session!=='time_unknown'&&row.event_at?eventTime(row.event_at):'exact release time unconfirmed'}.</p>
          {row.event_review?<section aria-label="Source-bound earnings review"><h3>Source-bound earnings review</h3>
            <p><strong>Expectations:</strong> {row.event_review.expectations_case}</p><p><strong>Priced-in assessment:</strong> {row.event_review.priced_in_assessment}</p>
            <p><strong>Valuation:</strong> {row.event_review.valuation_case}</p><p><strong>Downside:</strong> {row.event_review.downside_case}</p><p><strong>Recheck condition:</strong> {row.event_review.recheck_condition}</p>
            <ul>{row.event_review.sources.map((source,index)=><li key={source.sha256+index}>{safeSource(source.source_url)?<a href={source.source_url} target="_blank" rel="noreferrer">Reviewed primary source {index+1}</a>:<span>Review source URL unverified</span>}<br/><small>SHA-256 {source.sha256}</small></li>)}</ul>
          </section>:null}
          {row.sources.length?<ul>{row.sources.map((source,index)=><li key={source.sha256+index}>{safeSource(source.source_url)?<a href={source.source_url} target="_blank" rel="noreferrer">Primary calendar / issuer source {index+1}</a>:<span>Source URL unverified</span>}<br/><small>Available {eventTime(source.available_at)} · SHA-256 {source.sha256}</small></li>)}</ul>:<p>No verified source receipt is available.</p>}
        </details>
      </td>
    </tr>)}</tbody></table></div>;
}
function Pagination({count,page,onChange,label}:{count:number;page:number;onChange:(page:number)=>void;label:string}) {
  const safePage=Math.min(page,Math.max(0,Math.ceil(count/EARNINGS_PAGE_SIZE)-1));
  return <div className="earnings-pagination" aria-label={label}><span>{safePage*EARNINGS_PAGE_SIZE+1}–{Math.min((safePage+1)*EARNINGS_PAGE_SIZE,count)} of {count}</span>
    <button className="text-button" onClick={()=>onChange(Math.max(0,safePage-1))} disabled={safePage===0}>Previous</button>
    <button className="text-button" onClick={()=>onChange(safePage+1)} disabled={(safePage+1)*EARNINGS_PAGE_SIZE>=count}>Next</button></div>;
}
export default function EarningsEvents({data,unavailable=false}:{data:Snapshot;unavailable?:boolean}) {
  const [expanded,setExpanded]=useState(false),[page,setPage]=useState(0),[historyPage,setHistoryPage]=useState(0),[historyOpen,setHistoryOpen]=useState(false);
  const report=data.earnings_events;
  if(!report||report.schema_version!=='equity_earnings_event_view_v1')return null;
  const coverage=report.coverage;
  const upcoming=orderedUpcoming(report.events);
  const history=report.events.filter(row=>row.timing!=='pre_event'||row.status==='cancelled')
    .sort((a,b)=>b.event_date.localeCompare(a.event_date)||a.ticker.localeCompare(b.ticker));
  const rows=expanded?earningsPage(upcoming,page):upcoming.slice(0,3);
  return <section className="candidate-section earnings-events" aria-label="Upcoming earnings research">
    <h2>Upcoming earnings research</h2>
    <p className="panel-lead">Independent of momentum rank. Calendar detection creates research work; it does not authorize a trade.</p>
    <p className="panel-lead">Coverage: {coverage.scope??'unverified scope'} · {coverage.horizon_start??'unknown'} — {coverage.horizon_end??'unknown'} · {coverage.days_verified??0}/{coverage.days_requested??0} dates verified · {report.events.length} retained events.</p>
    <p className="panel-lead">{upcoming.length} upcoming events, reviewed outcomes first, then research deadline. {history.length} elapsed, cancelled or timing-unverified events retained separately.</p>
    {report.status!=='ready'?<p className="summary-context" role="status">Calendar status: {report.status}. Missing or stale coverage is not evidence that no company reports.</p>:null}
    {unavailable?<p className="summary-context" role="status">Research is refreshing or this view could not update. Retained event research is shown without conditional-plan eligibility.</p>:null}
    {coverage.failed_dates?.length?<p className="summary-context">Unverified calendar dates: {coverage.failed_dates.join(', ')}.</p>:null}
    {rows.length?<EventTable rows={rows} report={report} data={data} unavailable={unavailable}/>:<p className="empty compact">{report.status==='ready'?'No upcoming event was detected in the verified calendar coverage.':'No verified upcoming event is available in this retained coverage.'}</p>}
    {upcoming.length>3?<button className="text-button expand-button" onClick={()=>{setExpanded(value=>!value);setPage(0)}} aria-expanded={expanded}>{expanded?'Show fewer events':`Browse all ${upcoming.length} upcoming events`}</button>:null}
    {expanded&&upcoming.length>0?<Pagination count={upcoming.length} page={page} onChange={setPage} label="Upcoming event pages"/>:null}
    {history.length?<details className="earnings-history" onToggle={event=>setHistoryOpen(event.currentTarget.open)}><summary>Elapsed / other retained events ({history.length})</summary>
      {historyOpen?<><EventTable rows={earningsPage(history,historyPage)} report={report} data={data} unavailable={true}/><Pagination count={history.length} page={historyPage} onChange={setHistoryPage} label="Retained event pages"/></>:null}
    </details>:null}
    <p className="panel-lead">Research statuses remain separate from buy/sell action cards. A completed review can reject entry; an estimated date needs issuer confirmation before a pre-event plan.</p>
  </section>;
}
