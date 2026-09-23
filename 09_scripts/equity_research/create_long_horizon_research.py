#!/usr/bin/env python3
"""Create offline research sensitivities; reads public snapshots, never refreshes them."""
from __future__ import annotations

from equity_naming import report_heading

import argparse
from pathlib import Path

from daily_common import ROOT, atomic_write_json, atomic_write_text, iso_now, read_csv, read_json
from long_horizon_research import build_long_horizon_report

REPORT_REL = Path("04_research/company_research/long_horizon_research.local.json")
MARKDOWN_REL = Path("08_reviews/current/long_horizon_research.local.md")
POLICY_REL = Path("01_policies/long_horizon_research_policy.json")
SIGNAL_LABELS = {
    "revenue_contraction": "收入同比下降", "latest_growth_below_ttm": "最新收入增速低于 TTM",
    "elevated_share_dilution": "股数稀释超过复核线", "negative_free_cash_flow": "TTM 自由现金流为负",
    "revenue_growth_slowdown": "收入增速较前季放缓", "net_margin_deterioration": "净利率较前季下降",
    "fcf_margin_deterioration": "现金流率较前季下降",
}
FIELD_LABELS = {"debt_latest": "可核验的同期总债务", "cash_latest": "可核验的同期现金",
    "ttm_free_cash_flow": "可核验的 TTM 自由现金流", "ttm_free_cash_flow_margin_pct": "可核验的 TTM 现金流率",
    "share_dilution_pct": "可核验的股数稀释", "ttm_revenue": "可核验的 TTM 收入",
    "diluted_shares_latest": "可核验的摊薄股数", "current_completed_close": "有效已完成收盘价",
    "prior_distinct_quarter_for_sequential_comparison": "前季可比数字，尚不能判断环比趋势",
    "quarterly_financial_period_for_sequential_comparison": "季度口径证据；年度数字不代替季度比较",
    "adjacent_comparable_quarter_for_sequential_comparison": "相邻且口径一致的季度证据"}


def missing_label(value: str) -> str:
    prefix, _, field = value.partition(":")
    if prefix == "unresolved_business_evidence":
        return field
    if prefix == "unresolved_financial_evidence":
        return FIELD_LABELS.get(field, field)
    if prefix == "sequential_comparison":
        return "前季可比证据：" + FIELD_LABELS.get(field, field)
    return FIELD_LABELS.get(value, value)


def display(value: object, digits: int = 2) -> str:
    return "未知" if value is None else f"{value:.{digits}f}" if isinstance(value, (int, float)) else str(value)


def render_report(report: dict) -> str:
    companies = sorted(report["companies"].items(), key=lambda item: (not item[1].get("held"), item[0]))
    lines = [report_heading("long_horizon"), "", f"生成：{report['generated_at']}；市场日期：{report.get('market_session_date') or '缺失/不一致'}。", "",
        "此报告区分已披露事实、未验证商业假设与明确的敏感性参数。数值变化触发研究复核，不自动证明投资逻辑失效，也不授权交易。",
        "3/5 年情景采用假设的收入增长、期末现金流率、年度稀释与期末现金流倍数；不是公司预测、概率加权回报或目标价。",
        "现金流为经营现金流减资本开支的杠杆后代理指标，采用股权 P/FCF 倍数，不另加现金或减债务；不含分红/中途分配，不等于可分配股东现金。", "",
        "| 公司 | 研究状态 | 最新收入同比 | TTM 收入同比 | 股数同比 | 数值复核信号 |", "| --- | --- | ---: | ---: | ---: | --- |"]
    for ticker, row in companies:
        facts = row.get("facts", {})
        values = [display(facts.get(key, {}).get("value")) for key in ("revenue_yoy_pct", "ttm_revenue_yoy_pct", "share_dilution_pct")]
        readiness = "宽基核心，适用核心配置政策" if row["readiness"] == "not_applicable_core" else "研究尚未完成"
        signals = "、".join(SIGNAL_LABELS.get(x["code"], x["code"]) for x in row["review_signals"]) or "未触发；假设仍待验证"
        lines.append(f"| {ticker} | {readiness} | {' | '.join(values)} | {signals} |")
    lines += ["", "## 当前持仓的倍增条件", "",
        "下表是五年 2×/3× 价格对应的收入 CAGR 最小至最大需求，范围来自三个明确参数组合，并非置信区间。历史一年增速不能证明未来五年可持续。",
        "", "| 持仓 | 已知 TTM 增速 | 5 年 2× 所需收入 CAGR | 5 年 3× 所需收入 CAGR | 可实现性 |",
        "| --- | ---: | --- | --- | --- |"]
    for ticker, row in companies:
        if not row.get("held") or row["readiness"] == "not_applicable_core":
            continue
        diagnostic = row["hurdle_diagnostic"]
        ranges = {item["price_hurdle_multiple"]: item for item in diagnostic["required_revenue_growth_ranges"] if item["years"] == 5}
        cells = []
        for hurdle in (2, 3):
            item = ranges.get(hurdle)
            cells.append(f"{item['minimum_required_revenue_cagr_pct']:.2f}%–{item['maximum_required_revenue_cagr_pct']:.2f}%" if item else "证据不足，未计算")
        lines.append(f"| {ticker} | {display(diagnostic['historical_ttm_growth_pct'])}% | {' | '.join(cells)} | 尚未由公司经营证据证明 |")
    lines += ["", "high 信心 / 6% 高确信度层级保留，当前不会因数据完整而自动启用。", "", "## 基本面研究候选队列", "", "此顺序仅分配研究注意力，与单日涨跌和成交量无关；不代表买入排序。", ""]
    for row in report["candidate_queue"]:
        lines.append(f"- {row['ticker']}：观察增速 {display(row['observed_growth_pct'])}%；FCF 率 {display(row['observed_fcf_margin_pct'])}%；稀释 {display(row['observed_dilution_pct'])}%；期间 {row['financial_period_end']}。")
    coverage = report["coverage"]
    lines += ["", f"覆盖：{coverage['fundamental_rows']} 条基本面；应覆盖公司 {coverage['required_company_count']} 家；缺失：{', '.join(coverage['missing_company_rows']) or '无'}；质量未通过：{', '.join(coverage['unusable_company_rows']) or '无'}。"]
    for ticker, row in companies:
        if row["readiness"] == "not_applicable_core":
            continue
        reference = row["market_reference"]
        dated = row["facts"]["revenue_latest"]
        lines += ["", f"## {ticker}", "",
            f"市场参考：${display(reference['price'])}，{reference['market_session_date']}；财务期间截至 {dated['financial_period_end'] or '未知'}，证据抓取 {dated['fetched_at'] or '未知'}。",
            "", "待验证的商业假设：", ""]
        lines += [f"- {text}" for text in row["thesis"]["hypotheses"]]
        lines += ["", "需要反证检查的条件（不是自动退出条件）：", ""]
        lines += [f"- {text}" for text in row["thesis"]["invalidation_checks"]]
        lines += ["", "当前数值复核：", ""]
        lines += [f"- {SIGNAL_LABELS.get(item['code'], item['code'])}：{item['observations']}。这要求研究复核，不自动证明投资逻辑失效。" for item in row["review_signals"]] or ["- 无数值阈值触发；商业逻辑仍待验证。"]
        lines += ["", "未完成证据：", ""]
        lines += [f"- {missing_label(item)}" for item in dict.fromkeys(row["missing_evidence"])]
        source = row["facts"]["revenue_latest"]["source_url"]
        if source:
            lines += ["", f"原始证据：[SEC companyfacts]({source})；各字段来源、官方可得时间和财务期间保存在 JSON。"]
        scenarios = row["sensitivity_scenarios"]
        if not scenarios["forward"]:
            lines += ["", "情景未计算：" + "、".join(missing_label(item) for item in scenarios["missing_inputs"]) + "。缺少证据不补零。"]
            continue
        lines += ["", f"参数来源：{scenarios['assumption_source']}，生效 {scenarios['assumption_date']}；均为显式敏感性假设，尚无公司特定前瞻证据。",
            "", "| 敏感性 | 年数 | 收入 CAGR / 杠杆后 FCF 率 / 年稀释 / P/FCF | 条件期末价格 | 价格倍数 | 年价格变化 |", "| --- | ---: | --- | ---: | ---: | ---: |"]
        for item in scenarios["forward"]:
            a = item["assumptions"]
            lines.append(f"| {item['sensitivity']} | {item['years']} | {a['revenue_cagr_pct']}% / {a['terminal_fcf_margin_pct']}% / {a['annual_dilution_pct']}% / {a['terminal_price_to_fcf_multiple']}× | {item['terminal_price']:.2f} | {item['price_multiple']:.2f}× | {item['price_cagr_pct']:.2f}% |")
        lines += ["", "| 敏感性 | 年数 | 目标价格倍数 | 所需收入 CAGR |", "| --- | ---: | ---: | ---: |"]
        for item in scenarios["reverse_hurdles"]:
            lines.append(f"| {item['sensitivity']} | {item['years']} | {item['price_hurdle_multiple']}× | {display(item['required_revenue_cagr_pct'])}% |")
        lines += ["", "这些反解只回答给定稀释、现金流率和期末倍数需要多少收入增长；可实现性尚未由公司经营证据证明。"]
    return "\n".join(lines)+"\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT, help="Read-only root for existing research inputs")
    parser.add_argument("--output-root", type=Path, default=ROOT, help="Root receiving the two research artifacts")
    args = parser.parse_args()
    input_root, output_root = args.input_root.resolve(), args.output_root.resolve()
    policy = read_json(ROOT/POLICY_REL)
    output = output_root/REPORT_REL
    report = build_long_horizon_report(
        read_csv(input_root/"03_source_data/equity_research/daily_fundamentals.csv"),
        read_csv(input_root/"05_risk_and_positions/current_positions.local.csv"),
        read_csv(input_root/"03_source_data/equity_research/market_data_snapshot.csv"),
        policy, iso_now(), previous_report=read_json(output, {}),
        universe=read_csv(input_root/"03_source_data/equity_research/universe_seed.csv"),
    )
    atomic_write_json(output, report)
    atomic_write_text(output_root/MARKDOWN_REL, render_report(report))
    print(f"long_horizon_companies={len(report['companies'])} fundamental_candidates={len(report['candidate_queue'])} automatic_action_allowed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
