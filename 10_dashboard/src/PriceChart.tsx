import { useEffect, useId, useState } from 'react';
import type { Plan } from './domain';
import { expired, money } from './domain';

type Bar = {session_date: string; open: number; high: number; low: number; close: number; volume: number};
type Fill = {id:string; date:string; time:string; side:string; shares:string; price:number};
type Chart = {bars:Bar[]; fills:Fill[]; market_session:string; source:string; source_url:string; adjusted:boolean};

export default function PriceChart({ ticker, plan, now, offline }: {ticker:string; plan?:Plan; now:number; offline:boolean}) {
  const [chart,setChart]=useState<Chart|null>(null), [error,setError]=useState(''), [index,setIndex]=useState<number|null>(null);
  const id=useId();
  useEffect(()=>{
    const controller=new AbortController(); setChart(null); setError(''); setIndex(null);
    fetch('/api/chart?ticker='+encodeURIComponent(ticker),{cache:'no-store',signal:controller.signal}).then(async response=>{
      const r=await response.json(); if(!response.ok) throw new Error('当前日线缓存未通过校验，等待公共行情刷新。');
      setChart(r);
    }).catch(e=>{if(e.name!=='AbortError')setError(e.message)});
    return ()=>controller.abort();
  },[ticker]);
  if(!chart) return <div className="chart-loading" role="status">{error || '正在读取已校验日线…'}</div>;
  const bars=chart.bars.map(b=>({...b,open:Number(b.open),high:Number(b.high),low:Number(b.low),close:Number(b.close),volume:Number(b.volume)}));
  const draft=plan && !expired(plan,now) && plan.status==='current' && !offline ? plan.draft : null;
  const lines=draft ? ['limit_price','stop_price'].flatMap(key=>{
    const v=Number(draft[key]); return Number.isFinite(v)&&v>0 ? [{label:key==='limit_price'?'当前计划限价':'当前计划触发价',value:v}] : [];
  }) : [];
  const shownFills=chart.fills.filter(f=>bars.some(b=>b.session_date===f.date));
  const outside=chart.fills.filter(f=>!bars.some(b=>b.session_date===f.date));
  const low=Math.min(...bars.map(b=>b.low),...lines.map(l=>l.value),...shownFills.map(f=>f.price));
  const high=Math.max(...bars.map(b=>b.high),...lines.map(l=>l.value),...shownFills.map(f=>f.price));
  const pad=Math.max((high-low)*.14,high*.004), min=low-pad, max=high+pad;
  const x=(i:number)=>26+(i+.5)*616/bars.length, y=(v:number)=>24+(max-v)/(max-min)*212;
  const selected=bars[index ?? bars.length-1], maxVolume=Math.max(...bars.map(b=>b.volume),1);
  const interact=(clientX:number,svg:SVGSVGElement)=>{const r=svg.getBoundingClientRect();setIndex(Math.max(0,Math.min(bars.length-1,Math.floor(((clientX-r.left)/r.width*720-26)/616*bars.length))))};
  return <section className="price-chart" aria-label={`${ticker} 日 K 线`}>
    <div className="chart-heading"><h3>日 K 线 <span>20 个交易日</span></h3><span className="status">非实时</span></div>
    <p className="chart-values" aria-live="polite"><strong>{selected.session_date}</strong><span>开 {money(selected.open)}</span><span>高 {money(selected.high)}</span><span>低 {money(selected.low)}</span><span>收 {money(selected.close)}</span></p>
    <svg viewBox="0 0 720 322" role="img" aria-labelledby={id} tabIndex={0} onPointerMove={e=>interact(e.clientX,e.currentTarget)} onPointerDown={e=>interact(e.clientX,e.currentTarget)} onPointerLeave={()=>setIndex(null)}
      onKeyDown={e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();setIndex(i=>Math.max(0,Math.min(bars.length-1,(i??bars.length-1)+(e.key==='ArrowLeft'?-1:1))))}}}>
      <title id={id}>{ticker}：日线蜡烛图与成交量。左右方向键或触摸查看日期；公共价格未经复权，用户报告成交点单独标示。</title>
      {[0,1,2,3,4].map(i=>{const value=max-(max-min)*i/4;return <g key={i}><line x1="26" x2="642" y1={y(value)} y2={y(value)} stroke="#edf1ee"/><text x="654" y={y(value)+4} fill="#6f7c74" fontSize="11">{value.toFixed(2)}</text></g>})}
      {bars.map((b,i)=>{const color=b.close>=b.open?'#245d48':'#b16b55';return <g key={b.session_date}><line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke={color}/><rect x={x(i)-7} y={Math.min(y(b.open),y(b.close))} width="14" height={Math.max(1,Math.abs(y(b.open)-y(b.close)))} fill={color}/><rect x={x(i)-7} y={286-b.volume/maxVolume*30} width="14" height={b.volume/maxVolume*30} fill={color} opacity=".25"/></g>})}
      {lines.map(l=><g key={l.label}><line x1="26" x2="642" y1={y(l.value)} y2={y(l.value)} stroke="#a87626" strokeDasharray="5 4"/><text x="30" y={y(l.value)-5} fontSize="11" fill="#8e621e">{l.label} {l.value.toFixed(2)}</text></g>)}
      {shownFills.map(f=>{const i=bars.findIndex(b=>b.session_date===f.date);return <g key={f.id}><circle cx={x(i)} cy={y(f.price)} r="5" fill={f.side==='buy'?'#245d48':'#b16b55'} stroke="white" strokeWidth="2"/><title>{f.side==='buy'?'买入':'卖出'} {f.shares} 股，{money(f.price)}；{f.date} {f.time||'仅日期'} ET，用户报告</title></g>})}
      {index!==null?<line x1={x(index)} x2={x(index)} y1="16" y2="286" stroke="#95a69b" strokeDasharray="3 4"/>:null}
      {[0,5,10,15,19].map(i=><text key={i} x={x(i)} y="308" fontSize="11" textAnchor="middle" fill="#6f7c74">{bars[i].session_date.slice(5)}</text>)}
    </svg>
    <p className="chart-footnote">行情截至 {chart.market_session} · 未复权 · 下方为成交量。触摸或左右键查看日线。</p>
    {!draft?<p className="form-hint">当前方案已过期或待核对，图上不显示历史委托价作为当前条件。</p>:null}
    {chart.fills.length?<div className="chart-fills"><strong>用户报告的成交</strong>{chart.fills.map(f=><p key={f.id}>{f.date} {f.time?`大致 ${f.time} ET`:'仅记录日期'} · {f.side==='buy'?'买入':'卖出'} {f.shares} 股 · {money(f.price)}{outside.includes(f)?' · 在当前日线范围之外':''}</p>)}</div>:null}
    <details className="source-details"><summary>行情来源</summary><p>{chart.source}</p><a href={chart.source_url} target="_blank" rel="noreferrer">公共日线来源</a></details>
  </section>;
}
