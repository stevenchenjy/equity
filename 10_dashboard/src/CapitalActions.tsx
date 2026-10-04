import { money, timeLabel, type Snapshot } from './domain';
const labels:Record<string,string>={ACTIONABLE_BUY:'买入',ACTIONABLE_ADD:'加仓',HOLD:'持有',REDUCE_REVIEW:'减仓复核',EXIT_REVIEW:'退出复核',NO_ACTION:'不操作',BLOCKED:'暂不可给出新交易'};
export function CapitalActions({data}:{data:Snapshot}) {
  const c=data.capital_decision;
  if(!c)return <section className="capital-actions"><h2>今天做什么</h2><strong>暂无当前有效的完整交易草案</strong><p>等待完整决策重算；不要沿用历史数量或过期 DAY 委托。</p></section>;
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
    {primary.map(r=><article key={r.ticker} className={'capital-action '+(r.order_draft?r.order_draft.side==='sell'?'capital-sell':'capital-buy':'')}><h3>{labels[r.decision]??r.decision} · {r.ticker}</h3>{r.order_draft?<>
      <p className="capital-headline">{r.shares} 股 · 约 {money(r.estimated_notional)}</p>
      <dl className="condition-grid"><div><dt>委托条件</dt><dd>{r.order_draft.side==='sell'?'SELL':'BUY'} {r.order_draft.entry_order_type} {r.order_draft.side==='sell'&&r.order_draft.entry_order_type!=='STOP'?'≥':'≤'} {money(r.order_draft.side==='sell'?r.order_draft.exit_price:r.order_draft.entry_limit)} · {r.order_draft.time_in_force}</dd></div><div><dt>有效时间</dt><dd>{timeLabel(r.order_draft.entry_window.starts_at)} — {timeLabel(r.order_draft.entry_window.ends_at)}</dd></div>
      <div><dt>失效与风险</dt><dd>{r.order_draft.side==='sell'?'卖出限价不保护下跌；止损可能跳空':r.order_draft.invalidation_price===null?'核心用途没有价格止损；全部本金仍有风险':`失效价 ${money(r.order_draft.invalidation_price)}`}</dd><dd>计划风险 {money(r.order_draft.planned_total_loss)} · {r.order_draft.planned_account_risk_pct}%</dd></div>
      <div><dt>仓位与现金</dt><dd>{r.order_draft.portfolio_weight_before}% → {r.order_draft.portfolio_weight_after}%</dd><dd>{money(r.order_draft.cash_before)} → 约 {money(r.order_draft.estimated_cash_after)}（费用前）</dd></div></dl>
      <p>{r.order_draft.trigger_rule}</p><p>复核：{r.order_draft.initial_reassessment_price===null?'':money(r.order_draft.initial_reassessment_price)+' · '}{r.order_draft.reassessment_rule}</p>
      <ul>{r.order_draft.cancel_conditions.map(v=><li key={v}>{v}</li>)}</ul><p>{r.thesis_summary}</p><small>{r.order_draft.cost_assumption}</small>
    </>:<><p>{r.reasons.join('；')}</p>{r.dependencies.length?<details><summary>缺少的具体证据与处理方</summary><ul>{r.dependencies.map((v,i)=><li key={v.code+i}>{v.category} · {v.evidence_required}</li>)}</ul></details>:null}</>}</article>)}
    <p className="form-hint">参考行情 {c.market_data_timestamp}，非实时。系统不连接券商或下单。请阅读完整草案后自行在 Chase 执行；条件不符就跳过。</p>
    <details><summary>研究背景与其余候选（与行动分开）</summary>{c.decisions.filter(r=>!primary.includes(r)).map(r=><p key={r.ticker}><strong>{r.ticker} · {labels[r.decision]??r.decision}</strong><br/>{[...r.reasons,...r.blockers].join('；')}</p>)}</details>
  </section>;
}
