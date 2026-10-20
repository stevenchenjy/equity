import type {CapitalDecision} from './domain';
import {money, timeLabel} from './domain';
const pendingLabels:Record<string,string> = {configured_issuer_news_coverage_incomplete:'官方新闻覆盖',
  issuer_news_impact_review_incomplete:'新闻影响复核', company_model_not_admitted:'公司模型准入',
  company_specific_valuation_incomplete:'公司特定估值',scheduled_company_review_due:'公司复核已到期',
  company_model_requires_reassessment:'模型须重新复核',current_completed_close_unverified:'当前已完成收盘',
  research_model_source_unverified:'原模型与来源核验'};
const modelLabels:Record<string,string>={admitted_current:'该公司模型已接入当前生产估值。',
  research_only_pending_admission:'已记录研究模型；生产估值准入仍待完成。',
  no_completed_model:'公司特定估值尚未完成；当前没有完整模型。',
  research_model_unverified:'原研究模型需要重新核验；不展示当前情景价格。'};

export default function CompanyCase({row}:{row:CapitalDecision['decisions'][number]}) {
  const c=row.research_case;
  if(!c)return null;
  return <article className="company-case" aria-label={`${row.ticker} 公司估值与配置判断`}>
    <h3>{row.ticker} · 公司估值与配置判断</h3>
    <p className="capital-headline">本轮{row.order_draft?.side==='sell'?'卖出':'新增'}订单草案：{row.shares} 股</p>
    {c.review_status==='reassessment_required'?<p role="status">保留的历史判断须重新复核，不能作为当前交易指令。</p>:null}
    <p className="company-conclusion">{c.conclusion}</p>
    <p className="form-hint">{c.reference_price!==null?<>参考收盘 {c.reference_close} · {money(c.reference_price)} · 非实时。</>:<>当前已完成收盘未核验；不提供现价估值或订单价格。</>}</p>
    <dl className="condition-grid">
      <div><dt>悲观／基准／乐观估值</dt><dd>{c.scenario_prices?<>{money(c.scenario_prices.bear)} / {money(c.scenario_prices.base)} / {money(c.scenario_prices.bull)}；分析假设，不是保证价格。</>:<>未完成或须重新复核；没有可用的估值买入价。</>}</dd><dd>{c.horizon}</dd></div>
      {c.scenario_prices?<><div><dt>现价下的价格判断</dt><dd>基准上涨空间 {c.base_upside_pct===null?'未核验':c.base_upside_pct.toFixed(2)+'%'}</dd><dd>收益／风险 {c.scenario_reward_to_risk===null?'未核验':c.scenario_reward_to_risk.toFixed(2)} · 最低要求 {c.minimum_reward_to_risk.toFixed(2)}</dd></div>
      <div><dt>重新研究的价格参考</dt><dd>{money(c.valuation_only_review_ceiling)}</dd><dd>估值复核上限；不是买入限价或订单。</dd></div></>:null}
      <div><dt>{c.review_status==='reassessment_required'?'原复核期限／须重新复核':'下一次复核'}</dt><dd>{timeLabel(c.next_review_at)}</dd><dd>重大公司证据或价格变化时提前复核。</dd></div>
    </dl>
    {c.review_conditions.length?<ul>{c.review_conditions.map((condition,i)=><li key={i}>{condition}</li>)}</ul>:null}
    <p className="form-hint">{modelLabels[c.model_admission_status]??'模型状态未核验。'}研究判断与完整交易草案分别校验。</p>
    {c.pending_requirements.length?<p>仍待完成：{c.pending_requirements.map(v=>pendingLabels[v]??v).join('；')}</p>:null}
    {c.research_reasoning?<details className="summary-original"><summary>价格预期、分歧与损失路径</summary><p className="form-hint">记录于 {timeLabel(c.research_reasoning.authored_at)}；价格条件沿用所列日期。</p>{c.research_reasoning.lines.map((line,i)=><p key={i}>{line}</p>)}</details>:null}
    <details><summary>估值方法与反方证据</summary><p>{c.method}</p><p>{c.countercase}</p><small>研究版本 {c.review_version} · {timeLabel(c.reviewed_at)}</small></details>
  </article>;
}
