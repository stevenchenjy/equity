import { money, timeLabel, type CapitalDeploymentEscalation, type DeploymentGate, type Snapshot } from './domain';
const labels:Record<string,string>={ACTIONABLE_BUY:'买入',ACTIONABLE_ADD:'加仓',HOLD:'持有',REDUCE_REVIEW:'减仓复核',EXIT_REVIEW:'退出复核',NO_ACTION:'不操作',BLOCKED:'暂不可给出新交易'};
const routeLabels:Record<string,string>={existing_quality_holding:'加仓现有高质量持仓',researched_growth_candidate:'新建研究最充分的成长仓位',diversified_core_growth:'增加分散的核心 / 成长配置'};
const gateLabels:Record<DeploymentGate['category'],string>={evidence:'证据',valuation:'估值',price:'价格',risk:'风险',policy:'政策',account:'账户完整性'};
const escalationLabels:Record<CapitalDeploymentEscalation['status'],string>={active:'已触发：立即复核最佳资金用途',monitoring:'继续监测连续交易日与现金',actionable_available:'已有符合条件的资金部署草案',account_integrity_blocked:'账户完整性门槛未通过',cash_target_met:'现金未达到显著超额触发标准',history_unverified:'连续交易日记录尚未核实',session_unverified:'当前交易日证据尚未核实'};
const isGlobalGate=(gate:DeploymentGate)=>gate.scope==='global'||!gate.ticker;
function uniqueDeploymentGates(gates:DeploymentGate[]) {
  const unique=new Map<string,DeploymentGate>();
  for(const gate of gates){
    const key=`${isGlobalGate(gate)?'global':gate.ticker}:${gate.code}`;
    if(!unique.has(key))unique.set(key,gate);
  }
  return [...unique.values()];
}
const tickerDeploymentGates=(gates:DeploymentGate[],ticker:string)=>uniqueDeploymentGates(gates.filter(gate=>!isGlobalGate(gate)&&gate.ticker===ticker));
function DeploymentGates({gates,attributeTicker=false}:{gates:DeploymentGate[];attributeTicker?:boolean}) {
  return gates.length?<ul>{gates.map((gate,i)=><li key={gate.code+i}><strong>{attributeTicker?`${isGlobalGate(gate)?'全局':gate.ticker} · `:''}{gateLabels[gate.category]} · {gate.code}</strong>：{gate.evidence_required}{gate.resolver?`（处理方：${gate.resolver}）`:''}</li>)}</ul>:null;
}
function DeploymentEscalation({summary,draftTickers=[]}:{summary:CapitalDeploymentEscalation;draftTickers?:string[]}) {
  const ranked=summary.ranked_capital_uses.slice(0,3);
  const allGates=uniqueDeploymentGates(summary.gates);
  const globalGates=allGates.filter(isGlobalGate);
  const globalCodes=new Set(globalGates.map(gate=>gate.code));
  const tickerBlockers=(blockers:string[])=>blockers.filter(code=>!globalCodes.has(code));
  const accountBlockers=summary.account_integrity_blockers.filter(code=>!globalCodes.has(code));
  const pendingResearch=summary.research_requests.filter(request=>!request.completed);
  const closest=summary.closest_candidate;
  const closestGates=closest?tickerDeploymentGates(closest.gates,closest.ticker):[];
  const closestBlockers=closest?tickerBlockers(closest.blockers):[];
  return <section className="capital-action" aria-label="连续两日资金部署升级"><h3>连续两日资金部署升级</h3>
    <p><strong>{escalationLabels[summary.status]??summary.status}</strong></p>
    <p>连续无买入 / 加仓草案：{summary.consecutive_no_action_sessions===null?'尚未核实':`${summary.consecutive_no_action_sessions} 个交易日`} · 触发要求 {summary.required_sessions} 个交易日。{summary.observation_session?` 本次交易日 ${summary.observation_session}。`:''}</p>
    <p>未分配现金 {money(summary.cash.uncommitted_cash_usd)} · 批准现金目标 {summary.cash.cash_target_pct===null?'待核实':`${summary.cash.cash_target_pct}%`}（{money(summary.cash.cash_target_usd)}） · 超出目标 {money(summary.cash.excess_cash_usd)}。{summary.cash.material_excess_cash_pct===null?' 显著超额标准待核实。':` 显著超额标准：账户价值的 ${summary.cash.material_excess_cash_pct}%。`}</p>
    <p>{summary.explanation}</p>
    {summary.session_history_reason?<p>交易日记录：{summary.session_history_reason}</p>:null}
    {accountBlockers.length?<p><strong>账户完整性阻挡：</strong>{accountBlockers.join('；')}</p>:null}
    <DeploymentGates gates={globalGates}/>
    <h4>三类资金用途比较</h4><ul>{summary.routes.map(route=><li key={route.route}><strong>{routeLabels[route.route]??route.label}</strong>：{route.closest_candidate?`${route.closest_candidate.ticker} · ${route.closest_candidate.eligible?'通过部署门槛':'尚未通过部署门槛'}`:'暂无纳入的候选'}{route.blockers.length?`；${route.blockers.join('；')}`:''}</li>)}</ul>
    {ranked.length?<><h4>当前优先顺序</h4><ol>{ranked.map(candidate=>{
      const gates=tickerDeploymentGates(candidate.gates,candidate.ticker);
      const blockers=tickerBlockers(candidate.blockers);
      return <li key={candidate.route+candidate.ticker}><strong>{candidate.ticker} · {routeLabels[candidate.route]??candidate.route}</strong> — {candidate.eligible?draftTickers.includes(candidate.ticker)?'通过部署门槛，完整条件草案见行动区':'通过部署门槛；等待当前有效的完整草案':'暂不部署'}<DeploymentGates gates={gates}/>{!gates.length?<p>{blockers.length?blockers.join('；'):globalGates.length?'全局门槛见上方。':''}</p>:null}</li>;
    })}</ol></>:null}
    {closest?<p><strong>最接近部署条件：</strong>{closest.ticker} · {routeLabels[closest.route]??closest.route}；{closest.eligible?'已通过部署门槛。':closestGates.length?closestGates.map(gate=>`${gateLabels[gate.category]}：${gate.evidence_required}`).join('；'):closestBlockers.length?closestBlockers.join('；'):globalGates.length?'全局门槛见上方。':''}</p>:null}
    {pendingResearch.length?<><h4>待完成研究{summary.triggered?'（立即）':''}</h4><p>优先候选：{summary.research_priority_tickers.join('、')}。以下工作仍待完成；研究排队不代表结论已得到验证。</p>{pendingResearch.map(request=>{
      const gates=tickerDeploymentGates(request.required_work,request.ticker);
      const blockers=tickerBlockers(request.blockers);
      return <div key={request.ticker}><strong>{request.ticker} · {request.urgency==='immediate'?'立即处理':'常规处理'}</strong><DeploymentGates gates={gates}/>{!gates.length?<p>{blockers.length?blockers.join('；'):globalGates.length?'全局门槛见上方。':''}</p>:null}</div>;
    })}</>:null}
    {allGates.length>globalGates.length?<details><summary>完整现金保留门槛（证据 / 估值 / 价格 / 风险 / 政策 / 账户）</summary><DeploymentGates gates={allGates} attributeTicker/></details>:null}
  </section>;
}
export function CapitalActions({data}:{data:Snapshot}) {
  const c=data.capital_decision;
  const escalation=data.capital_deployment_escalation;
  if(!c)return <section className="capital-actions"><h2>今天做什么</h2><strong>暂无当前有效的完整交易草案</strong><p>等待完整决策重算；不要沿用历史数量或过期 DAY 委托。</p>{escalation?<DeploymentEscalation summary={escalation}/>:null}</section>;
  const actionable=c.decisions.filter(r=>r.order_draft);
  const held=new Set(data.positions.map(r=>r.ticker));
  const primary=c.decisions.filter(r=>r.order_draft||held.has(r.ticker));
  const dependencies=c.dependencies?.filter(d=>d.scope==='global')??[];
  const accountCheck=dependencies.some(d=>d.category==='C')||c.global_blockers.some(b=>/account|cash|order_inventory|earlier_instruction_execution/.test(b));
  const publicCheck=dependencies.some(d=>d.category==='A'||d.category==='B');
  return <section className="capital-actions" aria-label="今天做什么"><h2>今天做什么</h2><p className="capital-headline">{actionable.length?'完整条件订单草案':'本轮不新增仓位 · 买入 / 加仓 0 股'}</p>
    {accountCheck?<p>你现在需要做的：更新账户记录中的现金、持仓、完整挂单及可执行资金。若已有本日邮件，须核对其后实际成交或未成交的状态；假设成交不能作为第二次下单的资金依据。</p>:null}
    {publicCheck?<p>系统正在等待或处理所需公开数据，完整刷新后自动重算；不需要你手算研究结论。</p>:null}
    {dependencies.length?<details><summary>具体缺少什么、由谁处理</summary><ul>{dependencies.map((d,i)=><li key={d.code+i}>{d.category} · {d.evidence_required}</li>)}</ul></details>:null}
    {!actionable.length&&escalation?<DeploymentEscalation summary={escalation}/>:null}
    {primary.map(r=><article key={r.ticker} className={'capital-action '+(r.order_draft?r.order_draft.side==='sell'?'capital-sell':'capital-buy':'')}><h3>{labels[r.decision]??r.decision} · {r.ticker}</h3>{r.order_draft?<>
      <p className="capital-headline">{r.shares} 股 · 约 {money(r.estimated_notional)}</p>
      <dl className="condition-grid"><div><dt>委托条件</dt><dd>{r.order_draft.side==='sell'?'SELL':'BUY'} {r.order_draft.entry_order_type} {r.order_draft.side==='sell'&&r.order_draft.entry_order_type!=='STOP'?'≥':'≤'} {money(r.order_draft.side==='sell'?r.order_draft.exit_price:r.order_draft.entry_limit)} · {r.order_draft.time_in_force}</dd></div><div><dt>有效时间</dt><dd>{timeLabel(r.order_draft.entry_window.starts_at)} — {timeLabel(r.order_draft.entry_window.ends_at)}</dd></div>
      <div><dt>失效与风险</dt><dd>{r.order_draft.side==='sell'?'卖出限价不保护下跌；止损可能跳空':r.order_draft.invalidation_price===null?'核心用途没有价格止损；全部本金仍有风险':`失效价 ${money(r.order_draft.invalidation_price)}`}</dd><dd>计划风险 {money(r.order_draft.planned_total_loss)} · {r.order_draft.planned_account_risk_pct}%</dd></div>
      <div><dt>仓位与现金</dt><dd>{r.order_draft.portfolio_weight_before}% → {r.order_draft.portfolio_weight_after}%</dd><dd>{money(r.order_draft.cash_before)} → 约 {money(r.order_draft.estimated_cash_after)}（费用前）</dd></div></dl>
      <p>{r.order_draft.trigger_rule}</p><p>复核：{r.order_draft.initial_reassessment_price===null?'':money(r.order_draft.initial_reassessment_price)+' · '}{r.order_draft.reassessment_rule}</p>
      <ul>{r.order_draft.cancel_conditions.map(v=><li key={v}>{v}</li>)}</ul><p>{r.thesis_summary}</p><small>{r.order_draft.cost_assumption}</small>
    </>:<><p>{r.reasons.join('；')}</p>{r.dependencies.length?<details><summary>缺少的具体证据与处理方</summary><ul>{r.dependencies.map((v,i)=><li key={v.code+i}>{v.category} · {v.evidence_required}</li>)}</ul></details>:null}</>}</article>)}
    {actionable.length&&escalation?<DeploymentEscalation summary={escalation} draftTickers={actionable.map(row=>row.ticker)}/>:null}
    <p className="form-hint">参考行情 {c.market_data_timestamp}，非实时。系统不连接券商或下单。请阅读完整草案后自行在 Chase 执行；条件不符就跳过。</p>
    <details><summary>研究背景与其余候选（与行动分开）</summary>{c.decisions.filter(r=>!primary.includes(r)).map(r=><p key={r.ticker}><strong>{r.ticker} · {labels[r.decision]??r.decision}</strong><br/>{[...r.reasons,...r.blockers].join('；')}</p>)}</details>
  </section>;
}
