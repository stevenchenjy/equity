import { cloneElement, useEffect, useId, useRef, useState } from 'react';
import type { FormEvent, ReactElement, ReactNode } from 'react';
import { AlertCircle, ArrowLeft, ArrowUpRight, CheckCircle2, ClipboardList, Clock3, FileText, PencilLine, Plus, RefreshCw, Trash2, Wallet, X } from 'lucide-react';
import { appendRecord, defaults, editableFeedback, initialFeedback, matchesHistory, validStoredFeedback, planReference, easternDate, expired, makeDemoRecord, money, parseRecords, statusNames, STORAGE_KEY, timeLabel, validateFeedback } from './domain';
import type { DemoRecord, Feedback, FeedbackStatus, FormalRecord, Plan, ReviewRequest, Snapshot } from './domain';
import PriceChart from './PriceChart';
import ResearchSection from './ResearchSection';

type Page = 'today' | 'account' | 'feedback' | 'history' | 'detail';
const pages = [
  { id: 'today' as const, name: '今日方案', icon: FileText },
  { id: 'account' as const, name: '我的账户', icon: Wallet },
  { id: 'feedback' as const, name: '填写反馈', icon: PencilLine },
  { id: 'history' as const, name: '记录历史', icon: Clock3 },
];
const errorNames: Record<string, string> = {
  runtime_refresh_in_progress: '研究流程正在更新，请稍后重试。',
  research_inputs_changed: '账户或研究输入已变化，正在等待完整研究快照。',
  decision_price_snapshot_mismatch: '研究与行情快照不一致，等待重新生成。',
  snapshot_changed_during_read: '读取期间数据发生变化，请重新加载。',
};
const actionNames: Record<string, string> = { hold: '继续持有', watch: '观察', protect_review: '持仓保护', reduce_review: '减仓复核', exit_review: '退出复核', buy_review: '买入复核', add_review: '加仓复核' };
const blockerNames: Record<string, string> = { valuation: '估值证据', score: '综合研究', upside: '价格空间', reward_to_risk: '风险回报', entry: '入场条件', fresh_quote_and_available_shares_required: '即时价格、剩余股数与挂单待核对' };
const blockerText = (text: string) => text.split(',').filter(Boolean).map(v => blockerNames[v] ?? v.replaceAll('_', ' ')).join('、') || '以当前研究依据为准';
const formalErrors: Record<string,string> = {
  complete_account_correction_required:'账户更正需要完整的现金、持仓与来源核对，请补齐后重试。', invalid_account_correction:'请填写有效的更正原因并核对原始记录。', correction_reference_not_applied:'原始记录尚未应用到账户，请补全原始记录。', invalid_review_request:'请核对复审问题和股票代码。',
  invalid_holdings:'请核对持仓代码、正整数股数和每股成本。', future_event:'日期或时间晚于当前美东时间，请重新核对。', invalid_event_date:'请填写有效的发生日期和时间。', plan_reference_changed:'计划版本已经更新，请核对最新页面后重新预览。', preview_required:'预览与当前账户不一致，请重新预览后保存。', net_amount_less_than_fees:'净金额与费用不匹配，请检查金额口径。', order_facts_conflict:'对应订单的标的或买卖方向不一致。', fill_exceeds_remaining_order:'本次成交股数超过该订单剩余数量。',
  review_snapshot_changed:'研究版本已经更新，请核对最新页面后重新提交复审请求。',
  account_version_changed:'账户已变化，请更新视图，核对最新现金和股数后重新预览。',
  runtime_refresh_in_progress:'研究流程正在运行。请稍后用同一个请求重试。',
  request_id_reused:'请求编号已用于另一笔记录，请核对历史。', record_revision_changed:'这条记录已被更新，请重新打开历史。',
  insufficient_recorded_shares:'卖出股数超过当前记录的持仓。', insufficient_recorded_cash:'当前记录的现金不足。',
  active_order_not_found:'找不到仍有效的对应订单，请先登记或核对订单。', remaining_order_conflict:'剩余股数与已记录订单不一致。',
  order_still_has_remaining_shares:'该订单仍有剩余股数，请使用部分成交。', recovery_conflict:'中断恢复发现外部修改，已暂停写入，需要核对账户。',
};
const researchNames:Record<string,string>={queued:'等待重算',running:'正在重算',passed:'重算完成',degraded:'重算有缺口',failed:'重算失败，可重试',not_needed:'无需重算'};
const reviewNames:Record<string,string>={queued:'等待分析师复审',running:'分析师处理中',blocked:'有待解决的条件',completed:'复审完成'};
const reviewStorage='equity-dashboard-review-request-v1';
async function post(path:string,payload:unknown) {
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json(); if(!response.ok) throw Object.assign(new Error((formalErrors[result.error] ?? `登记未确认：${result.error}`)+(Array.isArray(result.details?.missing)?' 待补齐：'+result.details.missing.join('、'):'') ),{code:result.error});
  return result;
}
type RequestPayload = {request_id:string; record_id?:string; revision?:number; feedback:Feedback; account_version:string; snapshot_id:string; plan:FormalRecord['plan'];preview_hash?:string; email_version_id?:string|null; correction?:FormalRecord['correction']};
type Preview = {missing:string[];changes:null|{cash_before:number;cash_after:number;ticker?:string;shares_before?:number;shares_after?:number;fill_price?:number;holdings_after:{ticker:string;shares:string}[]};preview_hash:string};
const PENDING_REQUEST='equity-dashboard-submission-v1';

function AuditTrail({id,review=false}:{id:string;review?:boolean}) {
  const [events,setEvents]=useState<Record<string,unknown>[]|null>(null),[error,setError]=useState('');
  const load=async()=>{try{const r=await fetch(`${review?'/api/review-requests':'/api/feedback'}/events?id=${encodeURIComponent(id)}`,{cache:'no-store'});if(!r.ok)throw new Error();const body=await r.json();setEvents(body.events);setError('')}catch{setError('审计记录暂时无法读取。')}};
  return <details className="source-details" onToggle={e=>{if(e.currentTarget.open)void load()}}><summary>查看处理轨迹</summary>{error?<p role="alert">{error}</p>:events?events.map((e,i)=><p key={i}>修订 {String(e.revision??i+1)} · {String(e.stage??reviewNames[String(e.status)]??'记录状态')} · {timeLabel(String(e.updated_at??e.recorded_at??''))}<small>{e.account_version_before?'此前账户 '+String(e.account_version_before).slice(0,12):'原请求账户 '+String(e.account_version??'').slice(0,12)}</small></p>):<p>正在读取轨迹…</p>}</details>;
}

function ReviewPanel({data,ticker,requests,error,onSaved,onDirty}:{data:Snapshot;ticker?:string;requests:ReviewRequest[];error:string;onSaved:()=>void;onDirty:(dirty:boolean)=>void}) {
  const [question,setQuestion]=useState(''),[symbols,setSymbols]=useState(ticker??''),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[receipt,setReceipt]=useState<ReviewRequest|null>(null);
  const pending=useRef<{request_id:string;account_version:string;snapshot_id:string;tickers:string[];question:string}|null>(null);
  const base=useRef(data);
  const symbolsRef=useRef<HTMLInputElement>(null),questionRef=useRef<HTMLTextAreaElement>(null);
  const [validation,setValidation]=useState<{symbols?:string;question?:string}>({});
  const [unconfirmed,setUnconfirmed]=useState(false);
  useEffect(()=>{try{const raw=localStorage.getItem(reviewStorage);if(raw){const p=JSON.parse(raw);if(typeof p.request_id!=='string'||typeof p.question!=='string'||!Array.isArray(p.tickers)||p.tickers.some((t:unknown)=>typeof t!=='string')||typeof p.account_version!=='string'||typeof p.snapshot_id!=='string')throw new Error();pending.current=p;setQuestion(p.question);setSymbols(p.tickers.join(', '));setUnconfirmed(true)}}catch{setMessage('未确认的复审请求无法读取，请先核对下方历史。')}},[]);
  const submit=async(event:FormEvent)=>{
    event.preventDefault();if(busy)return;
    const tickers=[...new Set(symbols.trim().toUpperCase().split(/[\s,，]+/).filter(Boolean))];
    const invalidSymbols=tickers.length>20||tickers.some(t=>! /^[A-Z][A-Z0-9.\-]{0,11}$/.test(t));
    const invalidQuestion=question.trim().length<5||question.length>2000;
    setValidation({symbols:invalidSymbols?'最多填写 20 个有效股票代码，用逗号或空格分隔。':undefined,question:invalidQuestion?'请填写 5–2000 个字符的复审问题。':undefined});
    if(invalidSymbols||invalidQuestion){setMessage('');(invalidSymbols?symbolsRef:questionRef).current?.focus();return;}
    setBusy(true);setMessage('');
    try{
      pending.current??={request_id:crypto.randomUUID(),account_version:base.current.account_version,snapshot_id:base.current.snapshot_id,tickers,question:question.trim()};
      localStorage.setItem(reviewStorage,JSON.stringify(pending.current));setUnconfirmed(true);onDirty(false);
      const r=await post('/api/review-requests',pending.current) as ReviewRequest;
      localStorage.removeItem(reviewStorage);pending.current=null;setUnconfirmed(false);setReceipt(r);onDirty(false);onSaved();
    }catch(e){
      if(e instanceof Error&&'code' in e&&!['feedback_result_unknown_retry_same_request','runtime_refresh_in_progress','recovery_conflict'].includes(String(e.code))){pending.current=null;setUnconfirmed(false);localStorage.removeItem(reviewStorage);base.current=data;}
      setMessage(e instanceof TypeError?'连接中断，请恢复连接后用原请求重试。':e instanceof Error?e.message:'请求未确认，请用原请求重试。');
    }finally{setBusy(false)}
  };
  return <section className="review-request-panel"><h2>请求研究复审</h2><p className="panel-lead">告诉分析师需要重新核对什么。请求由现有 Codex 分析师流程处理，状态会显示在这里。</p>
    <form onSubmit={submit}><fieldset disabled={busy||unconfirmed||Boolean(receipt)} className="form-fields"><Field label="复审标的（留空为整个账户）" error={validation.symbols}><input ref={symbolsRef} value={symbols} placeholder="例如 SPY, RBRK" onChange={e=>{setSymbols(e.target.value);setValidation(v=>({...v,symbols:undefined}));onDirty(true)}}/></Field><Field label="希望核对的问题" error={validation.question}><textarea ref={questionRef} rows={3} maxLength={2000} value={question} placeholder="例如持仓变化后，重新检查保护条件和当前可执行的方案" onChange={e=>{setQuestion(e.target.value);setValidation(v=>({...v,question:undefined}));onDirty(true)}}/></Field></fieldset>
      {message?<p role="alert" className="field-error">{message}</p>:null}{unconfirmed?<p className="form-hint">请求结果尚未确认。使用原编号重试，不会重复创建。</p>:null}
      {receipt?<p className="receipt" role="status">请求已接收 · {reviewNames[requests.find(r=>r.id===receipt.id)?.status??receipt.status]}。接收不代表分析已完成。</p>:<button className="primary" disabled={busy}>{busy?'提交中…':unconfirmed?'用原请求重试':'提交复审请求'}</button>}
      {receipt?<button className="secondary" type="button" onClick={()=>{setReceipt(null);setQuestion('');base.current=data}}>提出另一个问题</button>:null}
    </form>{error?<p className="field-error" role="alert">{error}</p>:null}<div className="review-list">{requests.slice(0,10).map(r=><details key={r.id}><summary><span>{r.tickers.join('、')||'整个账户'}</span><span className="status">{reviewNames[r.status]}</span></summary><p>{r.question}</p><small>提交 {timeLabel(r.created_at)} · 更新 {timeLabel(r.updated_at)}</small>{r.receipt?<><p>{r.receipt.summary}</p><small>{r.receipt_verified?'分析回执哈希已核验':'回执未通过核验，请重新检查'} · {r.receipt.sha256.slice(0,12)}</small></>:null}<AuditTrail id={r.id} review/><small>请求 {r.id}</small></details>)}</div>
  </section>;
}

function DemoNotice({ compact = false }: { compact?: boolean }) {
  return <div className="notice"><AlertCircle size={19} /><span>{compact ? '演示记录 · 不更新真实账户' : '演示模式 · 表单记录不会更新真实持仓。'}</span></div>;
}

function Summary({ data }: { data: Snapshot }) {
  return <div className="account-strip">
    <div><span>账户估值</span><strong>{money(data.account.account_total_value)}</strong></div>
    <div><span>现金</span><strong>{money(data.account.cash_available)}</strong></div>
    <div><span>已投资</span><strong>{money(data.account.invested_capital)}</strong></div>
    <p>研究与账户数据均有独立时间。<small>{data.account.cash_basis==='ledger_estimate'?'现金按成交台账推算':'现金为所有者记录'}，结算资金{data.account.settled_cash_verified ? '已核对' : '待核对'}。</small></p>
  </div>;
}

function Field({ label, error, children, className = '' }: { label: string; error?: string; children: ReactNode; className?: string }) {
  const id = useId();
  return <div className={`field ${className}`}><label htmlFor={id}>{label}</label>{cloneElement(children as ReactElement<{ id?: string; 'aria-describedby'?: string; 'aria-invalid'?:boolean }>, { id, 'aria-invalid':Boolean(error), 'aria-describedby': error ? `${id}-error` : undefined })}{error ? <small id={`${id}-error`} className="field-error" role="alert">{error}</small> : null}</div>;
}

function FeedbackForm({ data, ticker, onSaved, onFormalSaved, editing, emailVersion, wide = false, storageError, initialStatus='filled', correction, onDirty }: { data: Snapshot | null; ticker: string; onSaved: (record: DemoRecord) => void; onFormalSaved:()=>void; editing?:FormalRecord|null; emailVersion?:string|null; wide?: boolean; storageError: string; initialStatus?:FeedbackStatus; correction?:FormalRecord|null; onDirty:(dirty:boolean)=>void }) {
  const [form, setForm] = useState<Feedback>(() => editing ? editableFeedback(editing.feedback) : initialFeedback(data,ticker,initialStatus));
  const [demo,setDemo]=useState(false), [busy,setBusy]=useState(false), [preview,setPreview]=useState<Preview|null>(null), [formalReceipt,setFormalReceipt]=useState<FormalRecord|null>(null);
  const [unconfirmed,setUnconfirmed]=useState<RequestPayload|null>(null);
  const base=useRef<Snapshot|null>(data), pending=useRef<RequestPayload|null>(null);
  const [correctionReason,setCorrectionReason]=useState('');
  const formRef=useRef<HTMLFormElement>(null);
  const holdingErrorId=useId();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [receipt, setReceipt] = useState<DemoRecord | null>(null);
  const submitting = useRef(false);
  const savedSignature = useRef<string | null>(null);
  useEffect(()=>{if(!base.current&&data)base.current=data},[data]);
  useEffect(()=>{try {const raw=localStorage.getItem(PENDING_REQUEST);if(raw){const p=JSON.parse(raw) as RequestPayload;if(typeof p.request_id==='string'&&/^[0-9a-f-]{36}$/.test(p.request_id)&&validStoredFeedback(p.feedback)&&(!p.correction||(typeof p.correction.record_id==='string'&&typeof p.correction.reason==='string'&&p.correction.reason.length<=1500))&&typeof p.account_version==='string'&&/^[0-9a-f]{64}$/.test(p.account_version)){pending.current=p;setUnconfirmed(p);setForm(p.feedback);setCorrectionReason(p.correction?.reason??'')}else throw new Error('invalid pending form')}}catch{setErrors({save:'未确认的请求无法读取，请先核对正式历史。'})}},[]);
  useEffect(() => { if(!pending.current){setForm(editing?editableFeedback(editing.feedback):initialFeedback(data,ticker,initialStatus));setReceipt(null);setFormalReceipt(null);setPreview(null);base.current=data;} }, [ticker,editing,initialStatus,correction]);
  const set = <K extends keyof Feedback>(key: K, value: Feedback[K]) => { onDirty(true); savedSignature.current = null;pending.current=null; setForm(f => ({ ...f, [key]: value })); setErrors({}); setReceipt(null); setFormalReceipt(null);setPreview(null); };
  const filled = form.status === 'filled' || form.status === 'partial';
  const today = data ? easternDate(Date.parse(data.server_now)) : easternDate();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current || savedSignature.current === JSON.stringify(form)) return;
    const result = validateFeedback(form, today);
    setErrors(result.errors);
    if(correction&&!unconfirmed&&!correctionReason.trim())result.errors.correction='请说明需要更正的原因';
    setErrors(result.errors);
    if (Object.keys(result.errors).length) { requestAnimationFrame(()=>formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()); return; }
    submitting.current = true;setBusy(true);
    try {
      if(demo){
        if (storageError) throw new Error(storageError);
        const record = makeDemoRecord(form, data);
        onSaved(record); savedSignature.current = JSON.stringify(form); setReceipt(record);onDirty(false);
      } else {
        if(!base.current)throw new Error('请等待账户快照后再填写。');
        if(!pending.current){
          const plan=base.current.plans.find(p=>p.ticker===form.ticker.toUpperCase());
          const payload:RequestPayload={request_id:crypto.randomUUID(),feedback:form,account_version:base.current.account_version,snapshot_id:base.current.snapshot_id,
            plan:planReference(plan),...(correction?{correction:{record_id:correction.id,reason:correctionReason.trim()}}:{}),email_version_id:editing?(editing.email_version_id??null):(emailVersion??null),...(editing?{record_id:editing.id,revision:editing.revision}:{})};
          const result=await post('/api/feedback/preview',payload) as Preview;
          payload.preview_hash=result.preview_hash; pending.current=payload; setPreview(result); return;
        }
        const payload=pending.current;
        localStorage.setItem(PENDING_REQUEST,JSON.stringify(payload));setUnconfirmed(payload);onDirty(false);
        const record=await post('/api/feedback',payload) as FormalRecord;
        localStorage.removeItem(PENDING_REQUEST);setUnconfirmed(null);pending.current=null;setPreview(null);setFormalReceipt(record);onDirty(false);onFormalSaved();
      }
    } catch (e) {
      if(e instanceof Error && 'code' in e && !['feedback_result_unknown_retry_same_request','runtime_refresh_in_progress','recovery_conflict'].includes(String(e.code))){pending.current=null;setUnconfirmed(null);setPreview(null);localStorage.removeItem(PENDING_REQUEST);}
      setErrors({ save: e instanceof TypeError?'连接中断，提交结果尚未确认。恢复连接后请用原请求重试。':e instanceof Error ? e.message : '浏览器未能保存，请检查存储权限' });
    }
    finally { submitting.current = false;setBusy(false); }
  };
  const numericInput = (key: 'shares' | 'amount' | 'fees' | 'order_price' | 'stop_price' | 'remaining' | 'cash', placeholder = '请输入') => <input inputMode="decimal" value={form[key]} placeholder={placeholder} onChange={e => set(key, e.target.value)} aria-invalid={Boolean(errors[key])} />;
  return <form ref={formRef} className={`feedback-form ${wide ? 'wide-form' : ''}`} onSubmit={submit} noValidate>
    <>{correction?<div className="correction-notice"><strong>更正当前账户</strong><p>关联记录 {correction.id.slice(0,8)}。请按 Chase 当前显示填写完整现金和持仓；原始成交与历史将保留。</p></div>:null}{emailVersion||editing?.email_version_id?<p className="form-hint">关联历史邮件 {(editing?.email_version_id??emailVersion)?.slice(0,8)}；登记使用当前账户。</p>:null}</><div className="form-mode"><strong>{editing?'补全正式记录':demo?'隔离试填':'正式登记'}</strong>{!editing&&!correction?<label><input type="checkbox" checked={demo} disabled={busy||Boolean(unconfirmed)||Boolean(preview)||Boolean(formalReceipt)} onChange={e=>{setDemo(e.target.checked);setPreview(null);pending.current=null;setReceipt(null);setFormalReceipt(null)}}/>演示模式</label>:null}</div>
    {formalReceipt?<div className="receipt" role="status"><CheckCircle2 size={21}/><div><strong>{formalReceipt.stage==='pending'?'记录已保存，待补全':'正式记录已接纳'}</strong><p>{formalReceipt.missing.length?formalReceipt.missing.join('、'):formalReceipt.production_effect?'账户记录已应用。':'未操作反馈已记录。'}</p><small>{researchNames[formalReceipt.research_status]} · 可在正式历史查看</small>{formalReceipt.order_id?<p>订单编号 {formalReceipt.order_id}</p>:null}</div></div>:null}
    <fieldset disabled={busy||Boolean(preview)||Boolean(unconfirmed)||Boolean(formalReceipt)} className="form-fields">
    {receipt ? <div className="receipt" role="status"><CheckCircle2 size={21} /><div><strong>演示记录已保存</strong><p>{receipt.stage === 'demo_pending' ? `待补全：${receipt.missing.join('、')}` : '信息齐全，可在记录历史中查看。'}</p><small>实际账户未更新 · 研究未重算</small></div><button type="button" className="icon-button" aria-label="关闭保存回执" onClick={() => setReceipt(null)}><X size={18} /></button></div> : null}
    {correction?<Field label="更正原因" error={errors.correction}><textarea rows={2} maxLength={1500} value={correctionReason} onChange={e=>{setCorrectionReason(e.target.value);onDirty(true);setErrors({})}} placeholder="例如重复登记；当前账户已按券商核对"/></Field>:null}
    {form.status !== 'account' ? <div className="fields-row">
      <Field label="当前标的" error={errors.ticker}><input list={wide ? 'tickers-wide' : 'tickers-quick'} value={form.ticker} placeholder="例如 SPY" onChange={e => set('ticker', e.target.value.toUpperCase())} /></Field>
      <Field label="买卖方向"><select value={form.side} onChange={e => set('side', e.target.value as 'buy' | 'sell')}><option value="buy">买入</option><option value="sell">卖出</option></select></Field>
    </div> : null}
    <datalist id={wide ? 'tickers-wide' : 'tickers-quick'}>{[...new Set([...(data?.positions.map(p => p.ticker) ?? []), ...(data?.candidates.map(p => p.ticker) ?? [])])].map(t => <option key={t} value={t} />)}</datalist>
    <Field label="执行状态"><select disabled={Boolean(correction)} value={form.status} onChange={e => {const status=e.target.value as FeedbackStatus;set('status',status);if(status==='account'&&!editing&&data)setForm(f=>({...f,cash:String(data.account.cash_available),holdings:data.positions.map(p=>({ticker:p.ticker,shares:String(p.shares)})),account_observed:false,inventory_complete:false,no_open_orders:false,orders_match:false}));}}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
    {filled ? <>
      <div className="fields-row"><Field label="成交股数" error={errors.shares}>{numericInput('shares', '实际成交股数')}</Field><Field label={form.amount_mode === 'price' ? '成交单价' : form.amount_mode === 'gross' ? '成交总金额' : '实际扣款 / 到账'} error={errors.amount}>{numericInput('amount', 'USD')}</Field></div>
      <div className="fields-row"><Field label="金额口径"><select value={form.amount_mode} onChange={e => set('amount_mode', e.target.value as Feedback['amount_mode'])}><option value="price">每股成交单价</option><option value="gross">总金额 · 未扣费用</option><option value="net">扣款 / 到账 · 含费用</option></select></Field><Field label="费用"><select value={form.fee_status} onChange={e => set('fee_status', e.target.value as Feedback['fee_status'])}><option value="unknown">暂时未知</option><option value="known">已确认金额</option></select></Field></div>
      {form.fee_status === 'known' ? <Field label="已确认费用" error={errors.fees}>{numericInput('fees', '确认无费用时填写 0')}</Field> : <p className="form-hint">未知信息可以稍后补全。</p>}
      {form.status === 'partial' ? <Field label="剩余挂单股数" error={errors.remaining}>{numericInput('remaining')}</Field> : null}
      {!demo?<><Field label="订单类型"><select value={form.order_type} onChange={e=>set('order_type',e.target.value)}>{['LIMIT','MARKET','STOP','STOP_LIMIT'].map(t=><option key={t}>{t}</option>)}</select></Field><Field label={form.status==='partial'?'对应已记录订单编号':'对应订单编号（独立成交可留空）'}><input value={form.linked_order} onChange={e=>set('linked_order',e.target.value)} list="known-orders"/></Field><datalist id="known-orders">{data?.orders.rows.filter(r=>['open','pending','partial_fill'].includes(String(r.status))).map(r=><option key={String(r.order_id)} value={String(r.order_id)}>{String(r.ticker)} {String(r.remaining_quantity??r.quantity)} 股</option>)}</datalist><p className="form-hint">股数是本次新增成交量。连续部分成交请逐次填写本次股数。</p><label className="check-field"><input type="checkbox" checked={form.not_in_account??false} onChange={e=>set('not_in_account',e.target.checked)}/>这笔成交尚未计入上方显示的当前账户</label></>:null}
    </> : null}
    {form.status === 'pending' ? <>
      <div className="fields-row"><Field label="委托股数" error={errors.shares}>{numericInput('shares')}</Field><Field label="订单类型"><select value={form.order_type} onChange={e => set('order_type', e.target.value)}><option>LIMIT</option><option>MARKET</option><option>STOP</option><option>STOP_LIMIT</option></select></Field></div>
      {['LIMIT', 'STOP_LIMIT'].includes(form.order_type) ? <Field label="委托限价" error={errors.order_price}>{numericInput('order_price')}</Field> : null}
      {['STOP', 'STOP_LIMIT'].includes(form.order_type) ? <Field label="触发价" error={errors.stop_price}>{numericInput('stop_price')}</Field> : null}
      <Field label="有效期"><select value={form.time_in_force} onChange={e => set('time_in_force', e.target.value)}><option>DAY</option><option>GTC</option><option value="unknown">待核对</option></select></Field>
      <p className="form-hint">此处记录你已提交的订单；挂单状态不会记为成交。</p>
    </> : null}
    {form.status === 'cancelled' ? <>
      <Field label="对应订单"><input value={form.linked_order} placeholder="订单编号或描述" onChange={e => set('linked_order', e.target.value)} /></Field>
      <label className="check-field"><input type="checkbox" checked={form.prior_partial} onChange={e => set('prior_partial', e.target.checked)} />撤单前已有部分成交</label>
      {form.prior_partial ? <p className="form-hint">部分成交需另行登记，撤单只涉及剩余数量。</p> : null}
      {!demo?<><label className="check-field"><input type="checkbox" checked={form.terminal_confirmed??false} onChange={e=>set('terminal_confirmed',e.target.checked)}/>券商已显示撤单完成</label>{form.prior_partial?<label className="check-field"><input type="checkbox" checked={form.partial_recorded??false} onChange={e=>set('partial_recorded',e.target.checked)}/>撤单前成交已单独登记并计入账户</label>:null}</>:null}
    </> : null}
    {form.status === 'account' ? <>
      <Field label="当前现金" error={errors.cash}>{numericInput('cash', 'USD，按账户实际显示填写')}</Field>
      <div className="holdings-editor"><span className="field-label">完整持仓列表</span>{form.holdings.map((row, index) => <div key={index}><div className="holding-edit-row"><input aria-label={`持仓 ${index + 1} 股票代码`} aria-invalid={Boolean(errors[`holding-${index}-ticker`])} aria-describedby={errors[`holding-${index}-ticker`]?`${holdingErrorId}-${index}-ticker`:undefined} value={row.ticker} placeholder="股票代码" onChange={e => set('holdings', form.holdings.map((r, i) => i === index ? { ...r, ticker: e.target.value.toUpperCase() } : r))} /><input aria-label={`持仓 ${index + 1} 股数`} aria-invalid={Boolean(errors[`holding-${index}-shares`])} aria-describedby={errors[`holding-${index}-shares`]?`${holdingErrorId}-${index}-shares`:undefined} value={row.shares} inputMode="numeric" placeholder="股数" onChange={e => set('holdings', form.holdings.map((r, i) => i === index ? { ...r, shares: e.target.value } : r))} /><button type="button" className="icon-button" aria-label={`移除持仓 ${index + 1}`} onClick={() => set('holdings', form.holdings.filter((_, i) => i !== index))}><X size={17} /></button></div>{!demo&&row.ticker?<Field label={`${row.ticker} 每股成本（新标的必填；已有持仓可留空）`}><input inputMode="decimal" value={row.entry_price??''} placeholder="按账户显示的每股成本填写" onChange={e=>set('holdings',form.holdings.map((r,i)=>i===index?{...r,entry_price:e.target.value}:r))}/></Field>:null}{['ticker','shares'].map(field=>errors[`holding-${index}-${field}`]?<small key={field} id={`${holdingErrorId}-${index}-${field}`} className="field-error" role="alert">{errors[`holding-${index}-${field}`]}</small>:null)}</div>)}
      <button className="text-button" type="button" onClick={() => set('holdings', [...form.holdings, { ticker: '', shares: '' }])}><Plus size={16} />添加持仓</button><small>列表为空表示全现金账户。</small></div>
      <label className="check-field"><input type="checkbox" checked={form.inventory_complete} onChange={e => set('inventory_complete', e.target.checked)} />已核对全部当前挂单</label>
      {!demo?<><label className="check-field"><input type="checkbox" checked={form.account_observed??false} onChange={e=>set('account_observed',e.target.checked)}/>现金和持仓是当前账户完整列表</label>{form.inventory_complete?<><label className="check-field"><input type="checkbox" checked={form.no_open_orders??false} onChange={e=>{set('no_open_orders',e.target.checked);set('orders_match',false)}}/>券商当前挂单列表为空</label>{!form.no_open_orders?<><p className="form-hint">已记录的当前挂单：{data?.orders.rows.filter(r=>['open','pending','partial_fill','partially_filled'].includes(String(r.status))&&r.record_scope!=='unresolved_historical_reservation').map(r=>`${r.ticker} ${r.side==='buy'?'买入':'卖出'} ${r.remaining_quantity??r.quantity} 股 (${r.order_id})`).join('；')||'无；有挂单请先逐笔登记'}</p><label className="check-field"><input type="checkbox" checked={form.orders_match??false} onChange={e=>{set('orders_match',e.target.checked);set('observed_order_ids',data?.orders.rows.filter(r=>['open','pending','partial_fill','partially_filled'].includes(String(r.status))&&r.record_scope!=='unresolved_historical_reservation').map(r=>String(r.order_id))??[])}}/>券商全部当前挂单与此列表完全一致</label></>:null}</>:null}<p className="form-hint">有挂单时请先逐笔登记。未知挂单状态可以保存反馈，研究继续等待核对。</p></>:null}
    </> : null}
    <div className="fields-row"><Field label="日期" error={errors.date}><input type="date" value={form.date} max={today} onChange={e => set('date', e.target.value)} /></Field><Field label="大致时间" error={errors.time}><input type="time" value={form.time} onChange={e => set('time', e.target.value)} /></Field></div>
    <Field label="备注（可选）"><textarea rows={2} value={form.notes} maxLength={1500} placeholder={form.status === 'skipped' ? '例如价格没到，或暂时不想操作' : '补充说明，时间按美东时间填写'} onChange={e => set('notes', e.target.value)} /></Field>
    </fieldset>
    {preview?<div className="submission-preview" role="status"><strong>{preview.missing.length?'将保存为待补全记录':'核对本次登记'}</strong>{preview.missing.length?<p>待补全：{preview.missing.join('、')}。当前现金和持仓暂不改变。</p>:preview.changes?<><p>现金 {money(preview.changes.cash_before)} → {money(preview.changes.cash_after)}</p>{preview.changes.ticker?<p>{preview.changes.ticker}：{preview.changes.shares_before} → {preview.changes.shares_after} 股</p>:<p>完整持仓：{preview.changes.holdings_after.map(r=>`${r.ticker} ${r.shares} 股`).join('；')||'全现金'}</p>}</>:null}<button className="text-button" type="button" disabled={busy||Boolean(unconfirmed)} onClick={()=>{pending.current=null;setPreview(null)}}>返回修改</button></div>:null}
    {unconfirmed&&!formalReceipt?<p className="notice">提交结果尚未确认。请用原请求重试；刷新后仍可恢复这个请求。</p>:null}
    {errors.save ? <p className="field-error" role="alert">{errors.save}</p> : null}
    <button className="primary save-button" type="submit" disabled={busy || (demo&&Boolean(storageError)) || Boolean(receipt)||Boolean(formalReceipt)||(!demo&&!data)}>{busy?'处理中…':demo?'保存演示记录':unconfirmed?'用原请求重试':preview?'确认保存正式记录':'预览登记结果'}</button>
    {!demo&&!preview&&!unconfirmed&&errors.save?<button className="text-button" type="button" onClick={()=>{base.current=data;set('not_in_account',false)}}>核对最新账户后重新预览</button>:null}
    <p className="storage-note">{demo?'仅保存到此浏览器。':'保存至这台 Mac 的正式记录，手机与 Mac 共用。'}</p>
    {formalReceipt&&!editing&&!correction?<button className="secondary" type="button" onClick={()=>{setForm(defaults(ticker));setFormalReceipt(null);setErrors({});base.current=data}}>登记另一笔操作</button>:null}
  </form>;
}

function HistoryFeedback({ feedback: f }: { feedback: Feedback }) {
  const unknown = (value: string) => value || '未知';
  if (f.status === 'account') return <>
    <p>当前现金 {unknown(f.cash)} USD</p>
    <p>完整持仓：{f.holdings.length ? f.holdings.map(h => `${h.ticker} ${h.shares} 股`).join('；') : '全现金，无持仓'}</p>
    <p>全部挂单：{f.inventory_complete ? '已核对' : '待核对'}</p>
  </>;
  if (f.status === 'pending') return <>
    <p>委托 {unknown(f.shares)} 股 · {f.order_type} · 有效期 {f.time_in_force === 'unknown' ? '待核对' : f.time_in_force}</p>
    {['LIMIT', 'STOP_LIMIT'].includes(f.order_type) ? <p>委托限价 {unknown(f.order_price)} USD</p> : null}
    {['STOP', 'STOP_LIMIT'].includes(f.order_type) ? <p>触发价 {unknown(f.stop_price)} USD</p> : null}
    <p>此记录是挂单反馈，未记为成交。</p>
  </>;
  if (f.status === 'cancelled') return <>
    <p>对应订单：{unknown(f.linked_order)}</p>
    <p>撤单前部分成交：{f.prior_partial ? '有，需另行登记核对' : '未报告'}</p>
  </>;
  if (f.status === 'skipped') return <p>未报告订单或成交。</p>;
  return <>
    <p>成交股数 {unknown(f.shares)} · {f.amount_mode === 'price' ? '每股成交单价' : f.amount_mode === 'gross' ? '成交总金额' : '实际扣款 / 到账'} {unknown(f.amount)} USD</p>
    <p>费用 {f.fee_status === 'known' ? unknown(f.fees) : '未知'}{f.fee_status === 'known' ? ' USD' : ''}</p>
    {f.status === 'partial' ? <p>剩余挂单 {unknown(f.remaining)} 股，未记为成交。</p> : null}
  </>;
}

function PlanDetail({ plan, now, offline, revision }: { plan: Plan; now: number; offline: boolean; revision:string }) {
  const outdated = expired(plan, now) || offline;
  return <div className="plan-detail">
    <div className="detail-title"><h2>{plan.ticker}</h2><span className={`status ${outdated ? 'amber' : ''}`}>{outdated ? '需复审' : plan.status === 'pending' ? '条件待核对' : '当前计划'}</span></div>
    <p className="detail-meta">{plan.plan_id} · v{plan.version} · 复审时间 {timeLabel(plan.expires_at)}</p>
    {outdated ? <div className="notice"><AlertCircle size={18} /><span>该计划已到复审时间或当前快照不可用，以下内容仅供回看。</span></div> : null}
    <PriceChart ticker={plan.ticker} plan={plan} now={now} offline={offline} revision={revision}/>
    {!outdated && plan.status==='current' && plan.draft?<div className="detail-section"><h3>当前结构化条件</h3><div className="condition-grid">{Object.entries({quantity:'股数',limit_price:'委托限价',stop_price:'触发价',order_type:'订单类型',time_in_force:'有效期',session_date:'适用交易日',expiration_date:'截止日期'}).map(([key,label])=>plan.draft?.[key]!=null?<p key={key}><span>{label}</span><strong>{String(plan.draft[key])}</strong></p>:null)}</div></div>:null}
    <div className="detail-section"><h3>{outdated ? '历史研究依据' : '当前研究依据'}</h3><p>{plan.instruction}</p></div>
    <div className="research-summary-grid">
      <ResearchSection title="判断理由" points={plan.display_summary?.reason} originals={[{text:plan.reason}]}/>
      <ResearchSection title="主要反对理由" points={plan.display_summary?.counterargument} originals={[{text:plan.counterargument}]}/>
      <ResearchSection title={outdated?'历史条件与退出依据':'条件与退出依据'} points={plan.display_summary?.conditions} historical={outdated} wide originals={[
        {label:'买入条件',text:typeof plan.purpose.entry_validity==='string'?plan.purpose.entry_validity:''},
        {label:'复审触发',text:typeof plan.purpose.failure_condition==='string'?plan.purpose.failure_condition:''},
        {label:'退出规则',text:typeof plan.purpose.exit_rule==='string'?plan.purpose.exit_rule:''},
      ]}/>
    </div>
    {plan.blockers.length ? <div className="detail-section"><h3>待核对条件</h3><ul>{plan.blockers.map(b => <li key={b}>{blockerNames[b] ?? b.replaceAll('_', ' ')}</li>)}</ul></div> : null}
    <details className="source-details"><summary>来源与版本记录（{plan.sources.length}）</summary>{plan.sources.map(s => <p key={s.path}>{s.path}<small>{s.sha256}</small></p>)}<small>计划哈希 {plan.record_hash}</small></details>
    <p className="detail-footer">条件来自已维护的研究计划。真实交易和订单状态由你报告。</p>
  </div>;
}

export default function App() {
  const [page, setPage] = useState<Page>('today');
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());
  const [selected, setSelected] = useState('SPY');
  const [showAll, setShowAll] = useState(false);
  const [storageError, setStorageError] = useState('');
  const [records, setRecords] = useState<DemoRecord[]>([]);
  const [formStatus,setFormStatus]=useState<FeedbackStatus>('filled'),[correction,setCorrection]=useState<FormalRecord|null>(null);
  const [dirty,setDirty]=useState(false),[pendingNavigation,setPendingNavigation]=useState<(()=>void)|null>(null);
  const [historyQuery,setHistoryQuery]=useState(''),[formalStatus,setFormalStatus]=useState('all'),[formalStage,setFormalStage]=useState('all');
  const [reviewRequests,setReviewRequests]=useState<ReviewRequest[]>([]);
  const [historyFilter, setHistoryFilter] = useState('all');
  const [confirmClear, setConfirmClear] = useState(false);
  const [formalRecords,setFormalRecords]=useState<FormalRecord[]>([]), [editing,setEditing]=useState<FormalRecord|null>(null), [formalError,setFormalError]=useState('');
  const [reviewError,setReviewError]=useState(''),[emailError,setEmailError]=useState('');
  const [emailContext,setEmailContext]=useState<string|null>(null);
  const [versions,setVersions]=useState<{id:string;timestamp:string;status:string}[]>([]), [oldVersion,setOldVersion]=useState<{id:string;generated_at:string;headline:string;advice:string;plans:Plan[];original_text:string|null;body_archive_verified:boolean}|null>(null);
  const historyRequest=useRef(0),versionRequest=useRef(0),reviewRequest=useRef(0);
  const loadReviews=async()=>{const id=++reviewRequest.current;try{const r=await fetch('/api/review-requests',{cache:'no-store'});if(!r.ok)throw new Error('复审请求读取失败');const v=await r.json();if(mounted.current&&id===reviewRequest.current){setReviewRequests(v.requests);setReviewError('')}}catch{if(mounted.current&&id===reviewRequest.current)setReviewError('复审请求暂时无法读取，请更新视图。')}};
  const loadRecords=async()=>{const id=++historyRequest.current;try{const r=await fetch('/api/feedback',{cache:'no-store'});const body=await r.json();if(!r.ok)throw new Error('正式历史读取失败，请稍后更新。');if(id!==historyRequest.current||!mounted.current)return;setFormalRecords(body.records);setFormalError('')}catch(e){if(id===historyRequest.current&&mounted.current)setFormalError(e instanceof Error?e.message:'正式历史不可用')}};
  const clock = useRef({ time: Date.now(), captured: performance.now() });
  const request = useRef(0);
  const mounted = useRef(true);
  const load = async () => {
    const id = ++request.current;
    setLoading(true);
    try {
      const response = await fetch('/api/snapshot', { cache: 'no-store' });
      const result = await response.json();
      if (!response.ok) throw new Error(errorNames[result.error] ?? '当前研究快照暂不可用，请稍后重试。');
      if (result.schema_version !== 'equity_dashboard_snapshot_v1') throw new Error('当前快照格式不匹配。');
      if (id !== request.current || !mounted.current) return;
      clock.current = { time: Date.parse(result.server_now), captured: performance.now() };
      setNow(clock.current.time); setData(result); setError('');
    } catch (e) { if (id === request.current && mounted.current) setError(e instanceof TypeError ? '无法连接工作台。请检查 Mac 服务与 Tailscale 连接。' : e instanceof Error ? e.message : '无法连接工作台。'); }
    finally { if (id === request.current && mounted.current) setLoading(false); }
  };
  useEffect(() => {
    mounted.current = true; void load();
    const poll = setInterval(() => { void load(); }, 60000);
    const tick = setInterval(() => setNow(clock.current.time + performance.now() - clock.current.captured), 1000);
    return () => { mounted.current = false; clearInterval(poll); clearInterval(tick); };
  }, []);
  useEffect(()=>{void loadRecords();void loadReviews();const poll=setInterval(()=>{void loadRecords();void loadReviews()},15000);return()=>clearInterval(poll)},[]);
  useEffect(()=>{if(page==='history'){fetch('/api/email-versions').then(r=>{if(!r.ok)throw new Error();return r.json()}).then(r=>setVersions(r.versions??[])).catch(()=>setEmailError('邮件版本读取失败'))}},[page]);
  useEffect(()=>{const key=new URLSearchParams(window.location.search).get('version');if(key){setPage('history');void openVersion(key)}else{const pub=new URLSearchParams(window.location.search).get('publication');if(pub){setPage('history');fetch('/api/email-publication?id='+encodeURIComponent(pub)).then(async r=>{const v=await r.json();if(!r.ok)throw new Error('该邮件版本尚未从发送台账确认，或归档绑定不唯一。');setOldVersion(v)}).catch(e=>setEmailError(e.message))}}},[]);
  const openVersion=async(id:string)=>{const generation=++versionRequest.current;setOldVersion(null);try{const r=await fetch('/api/email-version?id='+encodeURIComponent(id));const v=await r.json();if(!r.ok)throw new Error('邮件归档未通过校验。');if(generation!==versionRequest.current||!mounted.current)return;setOldVersion(v);setEmailError('')}catch(e){if(generation!==versionRequest.current)return;setEmailError(e instanceof Error?e.message:'邮件版本不可用')}};
  const formalSaved=()=>{void loadRecords();void load()};
  useEffect(() => {
    const read = () => { try { setRecords(parseRecords(localStorage.getItem(STORAGE_KEY))); setStorageError(''); } catch (e) { setStorageError(e instanceof Error ? e.message : '浏览器存储不可用'); } };
    read(); const changed = (event: StorageEvent) => { if (event.key === STORAGE_KEY) read(); };
    window.addEventListener('storage', changed); return () => window.removeEventListener('storage', changed);
  }, []);
  const save = (record: DemoRecord) => {
    const latest = parseRecords(localStorage.getItem(STORAGE_KEY));
    const next = appendRecord(latest, record);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); setRecords(next);
  };
  const clear = () => { try { localStorage.removeItem(STORAGE_KEY); setRecords([]); setStorageError(''); setConfirmClear(false); } catch { setStorageError('浏览器拒绝清除演示记录。'); } };
  const guard=(action:()=>void)=>{if(dirty)setPendingNavigation(()=>action);else action()};
  useEffect(()=>{if(!dirty)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirty]);
  const openDetail = (ticker: string) => guard(()=>{setDirty(false);setSelected(ticker); setPage('detail'); window.scrollTo({ top: 0 }); });
  const navigate = (next: Page,status:FeedbackStatus='filled') => {if(next===page)return;guard(()=>{setDirty(false);setPage(next);setEditing(null);setCorrection(null);setFormStatus(status);setEmailContext(null); window.scrollTo({ top: 0 });});};
  const plan = data?.plans.find(p => p.ticker === selected);
  const watched = data?.candidates.filter(c => !data.positions.some(p => p.ticker === c.ticker)) ?? [];
  const additions = data?.candidates.filter(c => c.quantity > 0 && !error && !data.stale && data.plans.some(p => p.ticker === c.ticker && !expired(p, now))) ?? [];
  const title = page === 'detail' ? '股票详情' : pages.find(p => p.id === page)!.name;
  const shownFormal=formalRecords.filter(r=>matchesHistory(r,historyQuery,formalStatus,formalStage));
  return <div className="app-shell"><a className="skip-link" href="#main-content">跳至主要内容</a>
    <aside className="sidebar"><div className="brand">Equity Research</div><nav aria-label="主导航">{pages.map(item => <button key={item.id} className={page === item.id || (page === 'detail' && item.id === 'today') ? 'selected' : ''} onClick={() => navigate(item.id)} aria-current={page === item.id ? 'page' : undefined}><item.icon size={21} /><span>{item.name}</span></button>)}</nav><div className="sidebar-footer">私人工作台<small>查看 · 登记 · 核对</small></div></aside>
    <div className="mobile-brand"><span className="brand">Equity Research</span><span>私人工作台</span></div>
    <main id="main-content" tabIndex={-1}>
      <header className="page-header"><div><h1>{title}</h1><p>{new Intl.DateTimeFormat('zh-CN', { timeZone: 'America/New_York', year: 'numeric', month: 'long', day: 'numeric' }).format(now)}</p></div><button className="secondary refresh-button" onClick={() => { void load();void loadRecords();void loadReviews(); }} disabled={loading}><RefreshCw size={18} className={loading ? 'spin' : ''} /><span>{loading ? '读取中' : '更新视图'}</span></button></header>
      <>{pendingNavigation?<div className="unsaved-confirm" role="alert"><p>表单有尚未保存的内容。离开后，这些内容会被清除。</p><button className="secondary" onClick={()=>setPendingNavigation(null)}>继续填写</button><button className="secondary" onClick={()=>{setDirty(false);pendingNavigation();setPendingNavigation(null)}}>放弃内容并离开</button></div>:null}</><div className="notice neutral"><ClipboardList size={18}/><span>{data?.mode==='verification'?'隔离验收账户 · 以下记录是模拟数据，不影响真实持仓。':'操作后填写表单，记录保存到 Mac；手机通过私人连接访问。'}</span></div>
      {data?.research_ready===false?<div className="notice"><Clock3 size={19}/><span>下方显示最新账户记录。研究尚未完成重算，旧数量方案已暂停。</span></div>:null}
      {error ? <div className="error-banner" role="alert"><AlertCircle size={19} /><div><strong>当前视图未能更新</strong><p>{error} {data ? '下方保留上次读取的数据，当前数量方案暂停展示。' : ''}</p></div></div> : null}
      {storageError ? <div className="error-banner" role="alert"><AlertCircle size={19} /><div><strong>演示记录存储异常</strong><p>{storageError}。可以在记录历史中清除损坏的演示存储。</p></div></div> : null}
      {data?.stale ? <div className="error-banner"><Clock3 size={19} /><p>这份研究生成于 {timeLabel(data.generated_at)}，并非今日研究。方案需重新复审。</p></div> : null}
      {page === 'today' ? <>
        {data ? <Summary data={data} /> : <div className="empty">{loading ? '正在读取生产研究快照…' : '当前没有可展示的完整研究快照。'}</div>}
        <div className="workspace"><section className="plan-column"><h2>当前方案</h2>
          {data?.plans.length ? data.plans.map(p => { const old = expired(p, now) || Boolean(error); return <article className="plan-row" key={`${p.ticker}:${p.plan_id??'unversioned'}`}><div className="plan-symbol"><button onClick={() => openDetail(p.ticker)}>{p.ticker}</button><span>{p.ticker === 'SPY' ? '宽基配置' : actionNames[p.action] ?? '持仓研究'}</span><small>{data.positions.find(v => v.ticker === p.ticker)?.shares ?? '—'} 股已记录</small></div><div className="plan-state"><span className={`status ${old ? 'amber' : ''}`}>{old ? '需复审' : p.status === 'pending' ? '条件待核对' : p.status === 'unverified' ? '依据待核对' : '当前计划'}</span><p>{old ? '计划已到复审时间' : p.blockers.length ? '先核对价格、剩余股数与挂单' : actionNames[p.action] ?? '以当前研究依据为准'}</p><small>复审 {timeLabel(p.expires_at)}</small></div><button className="secondary" onClick={() => openDetail(p.ticker)}>查看依据</button></article>; }) : <p className="empty compact">没有可展示的维护计划。</p>}
          {data ? <div className="addition-summary">{additions.length ? additions.map(c => <p key={c.ticker}><strong>{c.ticker} · 新增复核</strong><span>最多 {c.quantity} 股 · 最高复核价 {money(c.maximum_review_price)}</span><button className="text-button" onClick={() => openDetail(c.ticker)}>查看完整条件</button></p>) : <p>当前没有仍在有效期内的新增方案。</p>}</div> : null}
          {data ? <div className="candidate-section"><h2>观察名单</h2><div className="table-scroll"><table><thead><tr><th>股票</th><th>状态</th><th>主要缺口</th><th className="hide-small">参考收盘</th></tr></thead><tbody>{(showAll ? watched : watched.slice(0, 3)).map(c => <tr key={c.ticker}><td><button className="ticker-link" onClick={() => openDetail(c.ticker)}>{c.ticker}</button></td><td><span className="status">观察</span></td><td>{blockerText(c.blockers)}</td><td className="hide-small">{money(c.price)}</td></tr>)}</tbody></table></div>{watched.length > 3 ? <button className="text-button expand-button" onClick={() => setShowAll(v => !v)}>{showAll ? '收起观察名单' : `展开全部 ${watched.length} 个观察标的`}<ArrowUpRight size={16} /></button> : null}</div> : null}
        </section><aside className="feedback-panel"><h2>快速反馈</h2><p className="panel-lead">登记你已发生的操作。</p><FeedbackForm data={data} ticker={selected} onSaved={save} onFormalSaved={formalSaved} onDirty={setDirty} storageError={storageError} /></aside></div>
      </> : null}
      {page === 'feedback' ? <div className="standalone-form"><p className="page-lead">填写已发生的操作，或核对当前账户。未知信息可以稍后补全。</p><FeedbackForm key={editing?.id??correction?.id??formStatus} data={data} ticker={selected} onSaved={save} onFormalSaved={formalSaved} onDirty={setDirty} initialStatus={formStatus} correction={correction} editing={editing} emailVersion={emailContext} wide storageError={storageError} /></div> : null}
      {page === 'account' && data ? <><Summary data={data} /><div className="section-heading"><h2>当前记录的持仓</h2><button className="secondary" onClick={() => navigate('feedback','account')}><PencilLine size={16} />核对当前账户</button></div><div className="table-scroll"><table><thead><tr><th>股票</th><th>股数</th><th>参考收盘</th><th>持仓市值</th><th>占账户</th></tr></thead><tbody>{data.positions.map(p => <tr key={p.ticker}><td><button className="ticker-link" onClick={() => openDetail(p.ticker)}>{p.ticker}</button></td><td>{p.shares}</td><td>{money(p.price)}</td><td>{money(p.price===null?null:p.shares * p.price)}</td><td>{p.weight===null?'待估值':p.weight.toFixed(2)+'%'}</td></tr>)}</tbody></table></div><div className="account-notes"><p><span>账户最后更新</span>{timeLabel(data.account.last_updated)}</p><p><span>资金依据</span>{data.account.cash_basis === 'owner_recorded' ? '所有者记录' : '台账估算'} · 结算资金{data.account.settled_cash_verified ? '已核对' : '未核验'}</p><p><span>挂单最后核对</span>{timeLabel(data.orders.as_of)} · {data.orders.complete ? '当时列表完整' : '列表不完整'} · {data.orders.fresh ? '核对在 24 小时内' : '需要重新核对'}</p></div><ReviewPanel data={data} requests={reviewRequests} error={reviewError} onSaved={()=>void loadReviews()} onDirty={setDirty}/><h2 className="orders-title">记录中的订单</h2>{data.orders.rows.length ? <div className="order-list">{data.orders.rows.map((r, i) => <div key={String(r.order_id??i)}><strong>{String(r.ticker??'—')} · {r.side==='buy'?'买入':'卖出'}</strong><span>状态 {String(r.status??'未知')} · 委托 {String(r.quantity??'未知')} 股 · 剩余 {String(r.remaining_quantity??'未知')} 股</span><small>订单编号 {String(r.order_id??'未记录')}</small></div>)}</div> : <p className="empty compact">上次核对时没有记录中的订单；该观察不代表此刻的券商状态。</p>}</> : page === 'account' ? <p className="empty">当前账户快照不可用。</p> : null}
      {page === 'detail' ? <><button className="text-button back-button" onClick={() => navigate('today')}><ArrowLeft size={17} />返回今日方案</button>{plan ? <PlanDetail plan={plan} now={now} offline={Boolean(error)} revision={`${data?.snapshot_id}:${data?.account_version}`} /> : <><PriceChart ticker={selected} now={now} offline={Boolean(error)} revision={`${data?.snapshot_id}:${data?.account_version}`}/><p className="empty">该标的没有当前维护中的持仓计划。</p></>}</> : null}
      {page === 'history' ? <>
        <div className="section-heading"><div><h2>正式记录</h2><p className="panel-lead">Mac 与手机共用，显示最近 {formalRecords.length} 条（最多 500 条）。记录应用与研究完成分别显示。</p></div></div>
        {formalError?<p className="field-error" role="alert">{formalError}</p>:null}
        <div className="history-tools"><Field label="搜索正式记录"><input type="search" value={historyQuery} onChange={e=>setHistoryQuery(e.target.value)} placeholder="股票、日期、备注或记录编号"/></Field><Field label="操作类型"><select value={formalStatus} onChange={e=>setFormalStatus(e.target.value)}><option value="all">全部类型</option>{Object.entries(statusNames).map(([v,label])=><option value={v} key={v}>{label}</option>)}</select></Field><Field label="处理状态"><select value={formalStage} onChange={e=>setFormalStage(e.target.value)}><option value="all">全部状态</option><option value="pending">待补全</option><option value="applied">已接纳</option><option value="recovery_conflict">恢复待核对</option></select></Field></div><p className="form-hint" role="status">{shownFormal.length} 条匹配记录</p>
        {shownFormal.length?<div className="history-list">{shownFormal.map(r=><details className="history-record" key={r.id}><summary><span><strong>{r.feedback.status==='account'?'账户核对':r.feedback.ticker}</strong><small>{statusNames[r.feedback.status]}</small></span><span className={`status ${r.stage==='pending'?'amber':''}`}>{r.stage==='pending'?'待补全':r.stage==='applied'?'已接纳':'恢复待核对'}</span><small>{timeLabel(r.recorded_at)}</small></summary><div className="history-content"><p>{['applying','recovery_conflict'].includes(r.stage)?'账户写入待核对':r.production_effect?'账户已应用':'账户未应用'} · {researchNames[r.research_status]}</p><p>发生于 {r.feedback.date} {r.feedback.time?`大致 ${r.feedback.time}`:'时间未记录'} ET</p><HistoryFeedback feedback={r.feedback}/>{r.feedback.notes?<p>备注：{r.feedback.notes}</p>:null}{r.correction?<p>更正记录 {r.correction.record_id.slice(0,8)}：{r.correction.reason}</p>:null}{r.corrected_by?.length?<p>已有 {r.corrected_by.length} 条关联的账户更正，原始记录保留。</p>:null}{r.missing.length?<p>待补全：{r.missing.join('、')}</p>:null}{r.email_version_id?<p><a href={'/?version='+r.email_version_id}>关联的原始邮件版本</a></p>:null}{r.order_id?<p>订单编号 {r.order_id}</p>:null}{r.error?<p>{r.error}</p>:null}{r.stage==='pending'?<button className="secondary" onClick={()=>guard(()=>{setEditing(r);setCorrection(null);setSelected(r.feedback.ticker);setPage('feedback');window.scrollTo({top:0})})}>补全此记录</button>:null}{['failed','degraded'].includes(r.research_status)?<button className="secondary" onClick={()=>{post('/api/feedback/retry',{record_id:r.id}).then(()=>void loadRecords()).catch(e=>setFormalError(e.message))}}>重试研究刷新</button>:null}{r.stage==='applied'&&r.production_effect&&['filled','partial','account'].includes(r.feedback.status)?<button className="secondary" onClick={()=>guard(()=>{setCorrection(r);setEditing(null);setFormStatus('account');setPage('feedback');window.scrollTo({top:0})})}>通过账户核对更正</button>:null}<AuditTrail id={r.id}/><small>记录 {r.id} · 修订 {r.revision}</small></div></details>)}</div>:<p className="empty compact">{formalRecords.length?'没有匹配的正式记录。':'尚无正式表单记录。已有账户来自当前正式 CSV 与 JSON。'}</p>}
        {data?<ReviewPanel data={data} requests={reviewRequests} error={reviewError} onSaved={()=>void loadReviews()} onDirty={setDirty}/>:null}<div className="email-version-section">{emailError?<p className="field-error" role="alert">{emailError}</p>:null}<h2>邮件里的方案版本</h2><p className="panel-lead">从已发送台账核对原始归档，旧方案仅供回看。</p><select aria-label="邮件方案版本" value={oldVersion?.id??''} onChange={e=>{if(e.target.value)void openVersion(e.target.value);else {versionRequest.current++;setOldVersion(null)}}}><option value="">选择邮件版本</option>{versions.map(v=><option key={v.id} value={v.id}>{timeLabel(v.timestamp)} · {v.id.slice(0,8)}</option>)}</select>{oldVersion?<div className="historical-email"><span className="status amber">历史邮件版本</span><h3>{oldVersion.headline}</h3><p>{oldVersion.advice}</p><p>生成 {timeLabel(oldVersion.generated_at)} · 当前账户和方案以今日页面为准。</p>{oldVersion.plans.map((p,i)=><details key={i}><summary>{p.ticker} · v{p.version}</summary><p>{p.instruction}</p></details>)}<details className="source-details"><summary>查看这份邮件原文</summary>{oldVersion.body_archive_verified?<pre className="email-original">{oldVersion.original_text}</pre>:<p>此历史版本未保留可核验的邮件正文；上方仅展示原始决策归档。</p>}</details><a href={'/?version='+oldVersion.id}>此归档的私人页面链接</a><button className="secondary" onClick={()=>guard(()=>{setEmailContext(oldVersion.id);setEditing(null);setCorrection(null);setFormStatus('filled');setPage('feedback');window.scrollTo({top:0})})}>登记这份邮件后的实际操作</button></div>:null}</div>
        <div className="section-heading"><div><h2>此浏览器的演示记录</h2><p className="panel-lead">此浏览器中的试填历史，共 {records.length} 条。</p></div><button className="secondary" onClick={() => setConfirmClear(true)} disabled={!records.length && !storageError}><Trash2 size={16} />清除演示记录</button></div>
        {confirmClear ? <div className="clear-confirm"><p>清除此浏览器的全部演示记录？正式账户记录不会受影响。</p><button className="secondary" onClick={() => setConfirmClear(false)}>保留</button><button className="primary" onClick={clear}>确认清除</button></div> : null}
        <div className="history-filter"><label>筛选状态<select aria-label="筛选状态" value={historyFilter} onChange={e => setHistoryFilter(e.target.value)}><option value="all">全部状态</option>{Object.entries(statusNames).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label></div>
        {records.length ? <div className="history-list">{records.filter(r => historyFilter === 'all' || r.feedback.status === historyFilter).reverse().map(r => <details className="history-record" key={r.id}><summary><span><strong>{r.feedback.status === 'account' ? '账户核对' : r.feedback.ticker}</strong><small>{statusNames[r.feedback.status]}{r.feedback.status !== 'account' && r.feedback.status !== 'skipped' ? ` · ${r.feedback.side === 'buy' ? '买入' : '卖出'}` : ''}</small></span><span className={`status ${r.stage === 'demo_pending' ? 'amber' : ''}`}>{r.stage === 'demo_pending' ? '待补全' : '信息齐全'}</span><small>{r.feedback.date} {r.feedback.time ? `大致 ${r.feedback.time}` : '时间未记录'} ET</small></summary><div className="history-content"><p>登记时间 {timeLabel(r.recorded_at)} · 实际账户未更新 · 研究未重算</p>{r.missing.length ? <p>待补全：{r.missing.join('、')}</p> : null}<HistoryFeedback feedback={r.feedback} />{r.feedback.notes ? <p>{r.feedback.notes}</p> : null}{r.plan ? <p>关联计划 {r.plan.plan_id} · v{r.plan.version}</p> : null}<small>记录 ID {r.id}</small></div></details>)}</div> : <div className="empty history-empty"><ClipboardList size={32} /><h3>还没有演示记录</h3><p>试填一次反馈，提交结果会出现在这里。</p><button className="secondary" onClick={() => navigate('feedback')}>填写第一条反馈</button></div>}
      </> : null}
      <footer className="source-footer">{data ? <><span>行情截至 {data.market_session} · 非实时</span><span>研究生成 {timeLabel(data.generated_at)}</span><span>计划以有效时间为准。</span></> : <span>等待完整生产快照 · 演示记录独立保存</span>}</footer>
    </main>
  </div>;
}
