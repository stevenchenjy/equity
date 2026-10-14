import type {CapitalDecision} from './domain';
import {money, timeLabel} from './domain';
const pendingLabels:Record<string,string> = {configured_issuer_news_coverage_incomplete:'官方新闻覆盖',
  issuer_news_impact_review_incomplete:'新闻影响复核', company_model_not_admitted:'公司模型准入'};

export default function CompanyCase({row}:{row:CapitalDecision['decisions'][number]}) {
  const c=row.research_case;
  if(!c)return null;
  return <article className="company-case" aria-label={`${row.ticker} 公司估值与配置判断`}>
    <h3>{row.ticker} · 公司估值与配置判断</h3>
    <p className="capital-headline">本轮新增订单草案：{row.shares} 股</p>
    <p className="company-conclusion">{c.conclusion}</p>
    <p className="form-hint">参考收盘 {c.reference_close} · {money(c.reference_price)} · 非实时。情景价格是分析假设。</p>
    <dl className="condition-grid">
      <div><dt>悲观／基准／乐观估值</dt><dd>{money(c.scenario_prices.bear)} / {money(c.scenario_prices.base)} / {money(c.scenario_prices.bull)}</dd><dd>{c.horizon}</dd></div>
      <div><dt>现价下的价格判断</dt><dd>基准上涨空间 {c.base_upside_pct.toFixed(2)}%</dd><dd>收益／风险 {c.scenario_reward_to_risk===null?'未核验':c.scenario_reward_to_risk.toFixed(2)} · 最低要求 {c.minimum_reward_to_risk.toFixed(2)}</dd></div>
      <div><dt>重新研究的价格参考</dt><dd>{money(c.valuation_only_review_ceiling)}</dd><dd>估值复核上限；不是买入限价或订单。</dd></div>
      <div><dt>下一次复核</dt><dd>{timeLabel(c.next_review_at)}</dd><dd>重大公司证据或价格变化时提前复核。</dd></div>
    </dl>
    {c.review_conditions.length?<ul>{c.review_conditions.map((condition,i)=><li key={i}>{condition}</li>)}</ul>:null}
    <p className="form-hint">{c.model_admission_status==='admitted_current'?'该公司模型已接入当前生产估值。':'已记录研究模型；生产估值准入仍待完成。'}研究判断与完整交易草案分别校验。</p>
    {c.pending_requirements.length?<p>仍待完成：{c.pending_requirements.map(v=>pendingLabels[v]??v).join('；')}</p>:null}
    <details><summary>估值方法与反方证据</summary><p>{c.method}</p><p>{c.countercase}</p><small>研究版本 {c.review_version} · {timeLabel(c.reviewed_at)}</small></details>
  </article>;
}
