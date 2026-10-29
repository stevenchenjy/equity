import { planReference } from './domain';
import type { Feedback, FormalRecord, Snapshot } from './domain';

export type RequestPayload = {request_id:string; record_id?:string; revision?:number; feedback:Feedback; account_version:string; snapshot_id:string; plan:FormalRecord['plan'];preview_hash?:string; email_version_id?:string|null; correction?:FormalRecord['correction']};
export type Preview = {missing:string[];changes:null|{cash_before:number;cash_after:number;ticker?:string;shares_before?:number;shares_after?:number;fill_price?:number;linked_order?:Record<string,unknown>;holdings_after:{ticker:string;shares:string}[]};preview_hash:string};
type Waiting = {signal:AbortSignal; onWaiting:(elapsedSeconds:number)=>void; attempts?:number; delay?:()=>Promise<void>};
export const errorCode = (error:unknown) => error instanceof Error && 'code' in error ? String(error.code) : '';

type RequestOptions = {signal?:AbortSignal; timeoutMs?:number; mutation?:boolean};

// Bound both the network request and body parsing. Aborting fetch alone is not
// enough when a connection or a response reader never settles. A timed-out save
// has an unknown outcome; callers must retain its original idempotency key.
export async function requestJSON<T=Record<string,unknown>>(path:string, init:RequestInit={}, options:RequestOptions={}) {
  options.signal?.throwIfAborted();
  const controller=new AbortController();
  const timeoutMs=options.timeoutMs??15000;
  let timer:ReturnType<typeof setTimeout>|undefined;
  let stop:(()=>void)|undefined;
  const boundary=new Promise<never>((_resolve,reject)=>{
    stop=()=>{const reason=options.signal?.reason??new DOMException('Request stopped.','AbortError');controller.abort(reason);reject(reason)};
    if(options.signal?.aborted){stop();return}
    options.signal?.addEventListener('abort',stop,{once:true});
    timer=setTimeout(()=>{
      const error=Object.assign(new Error(options.mutation
        ? 'The save result is not confirmed. Your original request is kept; check history and retry that request.'
        : 'The request timed out. Your input is kept; please try again.'),
      {code:options.mutation?'feedback_result_unknown_retry_same_request':'request_timeout'});
      controller.abort(error);reject(error);
    },timeoutMs);
  });
  try {
    return await Promise.race([boundary,(async()=>{
      const response=await fetch(path,{...init,signal:controller.signal});
      const body=await response.json() as T;
      return {ok:response.ok,status:response.status,body};
    })()]);
  } finally {
    if(timer!==undefined)clearTimeout(timer);
    if(stop)options.signal?.removeEventListener('abort',stop);
  }
}

function pause(signal:AbortSignal) {
  return new Promise<void>((resolve,reject)=>{
    signal.throwIfAborted();
    const abort=()=>{clearTimeout(timer);reject(signal.reason)};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve()},3000);
    signal.addEventListener('abort',abort,{once:true});
  });
}

// Retry only an explicit busy response. Unknown network outcomes retain the
// original submitted request for manual recovery, never a newly generated ID.
export async function waitForResearch<T>(work:()=>Promise<T>, options:Waiting):Promise<T> {
  const attempts=options.attempts??100;
  const started=Date.now();
  for(let attempt=0;attempt<attempts;attempt++) {
    options.signal.throwIfAborted();
    try {return await work()}
    catch(error) {
      if(errorCode(error)!=='runtime_refresh_in_progress')throw error;
      if(attempt===attempts-1)throw Object.assign(new Error('后台更新尚未完成，输入已保留。稍后可继续。'),{code:'runtime_refresh_in_progress'});
      options.onWaiting(Math.floor((Date.now()-started)/1000));
      await (options.delay?options.delay():pause(options.signal));
    }
  }
  throw new Error('invalid_retry_bound');
}

// Every new preview uses a fresh coherent account, including a fill accepted
// just before its research refresh. Preparing a preview never submits a fill.
export async function preparePreview(payload:RequestPayload, load:(signal:AbortSignal)=>Promise<Snapshot>, preview:(p:RequestPayload,signal:AbortSignal)=>Promise<Preview>, options:Waiting) {
  return waitForResearch(async()=>{
    const snapshot=await load(options.signal);
    options.signal.throwIfAborted();
    const current={...payload,account_version:snapshot.account_version,snapshot_id:snapshot.snapshot_id,
      plan:planReference(snapshot.plans.find(p=>p.ticker===payload.feedback.ticker.toUpperCase()))};
    const result=await preview(current,options.signal);
    return {snapshot,preview:result,payload:{...current,preview_hash:result.preview_hash}};
  },options);
}
