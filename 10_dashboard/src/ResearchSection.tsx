import type { SummaryPoint } from './domain';

// Unreviewed future versions retain every source sentence instead of reusing old summaries.
export function originalPoints(originals: {label?: string; text: string}[]): SummaryPoint[] {
  return originals.flatMap(({label, text}) => text.trim().split(/(?<=[.!?。！？])\s+(?=[A-Z\u3400-\u9fff])/u)
    .filter(Boolean).map((sentence, index) => ({label: index === 0 ? label ?? '' : '', text: sentence})));
}

export default function ResearchSection({title, points, originals, historical=false, wide=false}: {
  title: string; points?: SummaryPoint[]; originals: {label?: string; text: string}[]; historical?: boolean; wide?: boolean;
}) {
  if (!originals.some(p=>p.text.trim())) return null;
  return <section className={`research-summary${wide?' research-summary-wide':''}`}>
    <h3>{title}</h3>
    {historical?<p className="summary-context">历史方案 · 以下价格、数量与日期仅供回看，等待新复审。</p>:null}
    {!points?<p className="summary-context">摘要待更新，先按原文要点展示。</p>:null}
    <ul className="summary-points">{(points??originalPoints(originals)).map((p,i)=><li key={i}>{p.label?<strong>{p.label}：</strong>:null}{p.text}</li>)}</ul>
    <details className="summary-original"><summary>查看完整原文</summary>{originals.filter(p=>p.text.trim()).map((p,i)=><p key={i}>{p.label?<strong>{p.label} · </strong>:null}{p.text}</p>)}</details>
  </section>;
}
