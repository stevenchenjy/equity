import {useEffect, useRef, useState} from 'react';
import type {EarningsEventView, Snapshot, StrategyFramework} from './domain';
import {requestJSON} from './feedbackRequest';
import EarningsEvents from './EarningsEvents';
import StrategyFrameworkPanel from './StrategyFramework';

export type ResearchResponse = {
  schema_version:'equity_dashboard_research_response_v1';
  account_version:string; snapshot_id:string; earnings_events:EarningsEventView|null;
  strategy_framework:StrategyFramework|null;
};

export function matchingResearchDetails(response:ResearchResponse|null,data:Snapshot):ResearchResponse|null {
  return response?.schema_version==='equity_dashboard_research_response_v1'
    &&response.account_version===data.account_version&&response.snapshot_id===data.snapshot_id
    &&(!response.earnings_events||response.earnings_events.schema_version==='equity_earnings_event_view_v1')
    &&(!response.strategy_framework||response.strategy_framework.schema_version==='equity_strategy_framework_v1')
    ?response:null;
}

export function projectResearchDetails(response:ResearchResponse|null,data:Snapshot,now:number):Snapshot|null {
  const details=matchingResearchDetails(response,data);
  if(!details)return null;
  // Deferred source validation can finish after a draft expires, even if the
  // account and publication identities remain unchanged. Current action status
  // comes only from the primary capital contract and its live deadline.
  const actions=new Map((data.capital_decision_status==='current'?data.capital_decision?.decisions??[]:[])
    .filter(row=>row.shares>0&&row.order_draft&&Number.isFinite(Date.parse(row.order_draft.entry_window.ends_at))
      &&now<Date.parse(row.order_draft.entry_window.ends_at)).map(row=>[row.ticker,row]));
  const strategy=details.strategy_framework;
  const events=details.earnings_events;
  return {...data,strategy_framework:strategy?{...strategy,decisions:strategy.decisions.map(row=>{
    const action=actions.get(row.ticker);
    if(row.classification==='valid_action'&&!action)return {...row,classification:'data_unavailable',eligible_quantity:0,
      next_step:'Current action status requires a validated, unexpired primary capital card.'};
    return {...row,eligible_quantity:action?.shares??0};
  })}:null,earnings_events:events?{...events,events:events.events.map(row=>{
    const action=actions.get(row.ticker);
    if(row.status==='eligible_conditional_plan'&&(!action||action.order_draft?.side!=='buy'
      ||row.timing!=='pre_event'||!row.research_deadline_at||now>=Date.parse(row.research_deadline_at)))
      return {...row,status:'research_in_progress',next_step:'Current event action status requires a validated, unexpired primary capital card.'};
    return row;
  })}:undefined};
}

export async function readResearchDetails(signal:AbortSignal):Promise<ResearchResponse> {
  const {ok,body}=await requestJSON<ResearchResponse>('/api/research-details',{cache:'no-store'},
    {signal,timeoutMs:90000});
  if(!ok||body.schema_version!=='equity_dashboard_research_response_v1')throw new Error('Detailed research is unavailable. Account records and decision cards remain available.');
  return body;
}

export default function ResearchDetails({data,now,unavailable=false}:{data:Snapshot;now:number;unavailable?:boolean}) {
  const [response,setResponse]=useState<ResearchResponse|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const controller=useRef<AbortController|null>(null);
  useEffect(()=>()=>controller.current?.abort(),[data.account_version,data.snapshot_id]);
  const load=async()=>{
    if(controller.current)return;
    const active=new AbortController();controller.current=active;setBusy(true);setError('');
    try {
      const result=await readResearchDetails(active.signal);
      if(!active.signal.aborted){
        if(!matchingResearchDetails(result,data))throw new Error('The account or decision changed during this read. Refresh detailed research.');
        setResponse(result);
      }
    }catch(e){if(!active.signal.aborted)setError(e instanceof Error?e.message:'Detailed research could not load.');}
    finally {if(controller.current===active){controller.current=null;setBusy(false);}}
  };
  const details=matchingResearchDetails(response,data);
  const detailedData=projectResearchDetails(response,data,now);
  return <section aria-label="Detailed research loading">
    <h2>Detailed research</h2>
    <p className="panel-lead">Strategy studies, the full earnings calendar and source review load separately from your account and decision cards.</p>
    <button className="secondary" onClick={()=>void load()} disabled={busy}>{busy?'Validating research sources…':details?'Refresh detailed research':'Load detailed research'}</button>
    {busy?<p role="status">Validating retained strategy, calendar and company sources. You can keep using your account, decisions and forms.</p>:null}
    {error?<p className="field-error" role="alert">{error}</p>:null}
    {detailedData?<><p className="panel-lead">This is a dated research view bound to the displayed account and decision.</p><StrategyFrameworkPanel data={detailedData} now={now} unavailable={unavailable||busy||Boolean(error)}/><EarningsEvents data={detailedData} unavailable={unavailable||busy||Boolean(error)}/></>:null}
  </section>;
}
