#!/usr/bin/env python3
"""Small deterministic, noncanonical thesis/expectations research companion.

No model, brokerage, credentials, external requests, or decision modifications.
Questions are research hypotheses, not claims that those hypotheses are true.
The reverse valuation is explicitly conditional; missing inputs stay unknown.
"""
from __future__ import annotations

import math
from typing import Any

from phase5r_daily_common import (
    ROOT, FUNDAMENTALS_PATH, atomic_write_json, atomic_write_text,
    canonical_sha256, iso_now, read_csv, read_json,
)
from track_phase5r_recommendation_outcomes import append_jsonl, jsonl

REPORT = ROOT / "08_reviews/current/phase5r_research_questions.local.md"
STATE = ROOT / "04_research/realtime_stock_picker_phase5r/phase5r_research_questions.local.json"
HISTORY = ROOT / "04_research/realtime_stock_picker_phase5r/phase5r_research_question_events.local.jsonl"
METRICS = (
    "latest_period_end", "revenue_latest", "revenue_yoy_pct", "ttm_revenue",
    "net_margin_pct", "ttm_free_cash_flow", "cash_latest", "debt_latest",
    "diluted_shares_latest", "share_dilution_pct", "data_quality",
    "valuation_input_quality", "valuation_input_limitations", "data_quality_reasons",
)
QUESTIONS = {
    "IOT": [
        "增长是否来自可持续的客户扩张，而非一次性因素？核对下次官方收入、客户与留存披露；缺少客户指标时不能仅用总收入回答。",
        "增长能否转化为股东现金收益？分别核对经营现金流、资本支出、股份支付与股数变化，不能把调整后利润等同于现金。",
        "销售效率与客户/行业集中是否改变？用下次官方费用和业务风险披露反证；未披露则保持未知。",
    ],
    "RBRK": [
        "经常性收入增长是否能兑现为持续收入与回款？核对下次官方订阅/ARR定义、收入及现金流，不混用三者。",
        "经营杠杆是否改善并抵消稀释？用同期间收入、GAAP费用、现金流和股份支付核对；年度证据不直接证明单季趋势。",
        "合作伙伴/渠道与客户集中是否上升？核对下一份官方集中度披露；旧风险重复出现不算新增发现。",
    ],
    "SPY": [
        "广泛市场核心配置是否仍符合资金用途与持有期限？短期价格变化不独立构成长期假设破坏。",
        "现金储备、整股粒度与核心目标能否同时满足？按当前账户确定性比较，目标偏离不等同于硬风险违规。",
        "基金结构、费用或跟踪条件是否出现官方披露变化？没有基金层证据时不生成公司估值或公司盈利判断。",
    ],
}


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def reverse_expectations(valuation: dict[str, Any]) -> list[dict[str, Any]]:
    """Solve required revenue for explicit terminal-multiple/return sensitivities.

    Equity hurdle is price appreciation, not total return. Net debt and shares
    held constant; no interim distributions. Neither a forecast nor DCF.
    """
    required = {key: number(valuation.get(key)) for key in (
        "current_price", "diluted_shares", "cash", "debt", "revenue_ttm_or_proxy",
    )}
    if valuation.get("status") != "complete" or any(value is None for value in required.values()):
        return []
    price, shares, cash, debt, revenue = (required[key] for key in required)
    if price <= 0 or shares <= 0 or revenue <= 0 or cash < 0 or debt < 0:
        return []
    results = []
    for scenario, raw_multiple in sorted(valuation.get("scenario_multiples", {}).items()):
        multiple = number(raw_multiple)
        if multiple is None or multiple <= 0:
            continue
        for years in (3, 5):
            for hurdle in (0, 12, 15):
                terminal_ev = price * (1 + hurdle / 100) ** years * shares + debt - cash
                if terminal_ev <= 0:
                    continue
                required_revenue = terminal_ev / multiple
                results.append({
                    "scenario": scenario, "years": years, "price_hurdle_pct": hurdle,
                    "terminal_ev_revenue_multiple": multiple,
                    "required_revenue": round(required_revenue, 2),
                    "required_revenue_cagr_pct": round(((required_revenue / revenue) ** (1 / years) - 1) * 100, 4),
                })
    return results


def whole_share_diagnostics(summary: dict[str, Any], weights: list[dict[str, Any]], account: dict[str, Any]) -> list[dict[str, Any]]:
    total = number(summary.get("account_total_value"))
    if total is None or total <= 0:
        return []
    deployable = number(summary.get("deployable_cash"))
    results = []
    for row in weights:
        price, shares = number(row.get("latest_price")), number(row.get("current_shares"))
        if price is None or shares is None or price <= 0 or shares < 0:
            continue
        core = row.get("asset_role") == "core_allocation"
        target = number(account.get("core_allocation_target_pct" if core else "single_stock_default_cap_pct"))
        hard = None if core else number(account.get("single_stock_hard_cap_pct"))
        value = shares * price
        results.append({
            "ticker": row.get("ticker"), "target_kind": "core_target" if core else "default_position_limit",
            "current_weight_pct": round(value / total * 100, 4),
            "one_share_weight_pct": round(price / total * 100, 4),
            "minus_one_share_weight_pct": round(max(0, shares - 1) * price / total * 100, 4),
            "plus_one_share_weight_pct": round((shares + 1) * price / total * 100, 4),
            "one_share_reduction_fraction_pct": round(min(1, 1 / shares) * 100, 4) if shares else None,
            "target_pct": target, "hard_cap_pct": hard,
            "above_target_dollars": round(max(0, value - total * target / 100), 2) if target is not None else None,
            "additional_capital_to_reach_target_without_share_change": round(max(0, value / (target / 100) - total), 2) if target and target > 0 else None,
            "cash_can_fund_one_share": deployable >= price if deployable is not None else None,
            "not_a_trade_plan": True,
        })
    return results


def main() -> int:
    positions = read_csv(ROOT / "05_risk_and_positions/current_positions.local.csv")
    facts = {row["ticker"]: row for row in read_csv(FUNDAMENTALS_PATH)}
    valuations = {row["ticker"]: row for row in read_json(ROOT / "04_data/phase5r/phase5r_valuation_scenarios.local.json", {}).get("records", [])}
    summary_rows = read_csv(ROOT / "05_risk_and_positions/phase5r_c9_current_portfolio_summary.csv")
    weights = read_csv(ROOT / "05_risk_and_positions/phase5r_c9_dynamic_position_weights.csv")
    account = read_json(ROOT / "05_risk_and_positions/current_account_state.local.json", {})
    prior = read_json(STATE, {}).get("companies", {})
    seen = {row.get("event_id") for row in jsonl(HISTORY)}
    companies = {}
    generated = iso_now()
    for position in sorted(positions, key=lambda row: row["ticker"]):
        ticker = position["ticker"]
        fact, valuation = facts.get(ticker, {}), valuations.get(ticker, {})
        observation = {key: fact.get(key, "") for key in METRICS}
        previous = prior.get(ticker, {}).get("observation", {})
        changed = [key for key in METRICS if observation[key] != previous.get(key, "")]
        evidence_status = "first_observation" if ticker not in prior else "changed" if changed else "no_material_numeric_change"
        companies[ticker] = {
            "questions_are_unproven_hypotheses": True,
            "questions": QUESTIONS.get(ticker, [
                "增长由什么可持续经营因素驱动？", "现金转化与股数稀释是否改善？", "什么官方证据会反驳目前判断？",
            ]),
            "observation": observation, "changed_fields": changed,
            "evidence_status": evidence_status,
            "source_url": fact.get("source_url", ""),
            "field_provenance": fact.get("field_provenance_json", ""),
            "reverse_expectations": reverse_expectations(valuation),
            "valuation_status": valuation.get("status", "not_applicable_or_missing"),
            "next_evidence": "next official periodic disclosure; no fabricated calendar date",
            "semantic_thesis_resolution": "unresolved; numerical deltas alone do not resolve business hypotheses",
        }
        event_id = canonical_sha256({"ticker": ticker, "observation": observation})
        if event_id not in seen:
            append_jsonl(HISTORY, {"event_id": event_id, "observed_at": generated, "ticker": ticker, "observation": observation})
            seen.add(event_id)
    diagnostics = whole_share_diagnostics(summary_rows[0] if summary_rows else {}, weights, account)
    atomic_write_json(STATE, {
        "schema_version": "phase5r_research_questions_v1", "generated_at": generated,
        "companies": companies, "whole_share_diagnostics": diagnostics,
        "canonical_influence_allowed": False, "automatic_action_allowed": False,
    })
    lines = [
        "# 持仓研究：假设、变化、价格预期与组合约束", "", f"生成：{generated}", "",
        "这是确定性研究伴随报告，不是交易建议，不改变生产判断、通知资格或风险阈值。",
        "公司问题是待验证假设，不能因被列出就视为已成立。没有新变化，不重复生成新的发现。", "",
        "反向情景只解算在既定期末收入倍数下实现0%/12%/15%年价格变化所需收入增速；",
        "12%/15%仅对应既有研究目标的敏感性，不是预测或承诺。假设净债务和股数不变、无期间分配；",
        "不等于DCF或总回报估计。3/5年及收入倍数均为情景参数，不能用这些解代替公司经营预测。", "",
    ]
    for ticker, row in companies.items():
        lines.extend([f"## {ticker}", "", f"变化：{row['evidence_status']}；字段：{', '.join(row['changed_fields']) or '无'}。", ""])
        lines.extend(f"- {question}" for question in row["questions"])
        lines.extend(["", f"已知事实：`{row['observation']}`", f"估值输入状态：`{row['valuation_status']}`。", f"证据：[官方来源]({row['source_url']})" if row["source_url"] else "公司层官方证据未提供/不适用。", ""])
        if row["reverse_expectations"]:
            lines.extend(["基础期末倍数下的所需收入增速（不是预测）：", "", "| 年数 | 年价格变化情景 | 所需收入年增速 |", "| --- | --- | --- |"])
            lines.extend(f"| {item['years']} | {item['price_hurdle_pct']}% | {item['required_revenue_cagr_pct']:.2f}% |" for item in row["reverse_expectations"] if item["scenario"] == "base")
        else:
            lines.append("价格隐含预期：输入不足或不适用，未计算；不补零、不编造前瞻假设。")
        lines.extend(["", "下一条验证证据：下次官方定期披露；已知数值变化不能自动证明或推翻全部商业假设。", ""])
    lines.extend(["## 整股约束的研究情景", "", "以下±1股只展示离散粒度，不是建议动作；核心目标不是自动授权的超额容忍带。", "", "| 标的 | 当前权重 | 减1股权重 | 加1股权重 | 目标/默认线 | 硬上限 | 超过目标金额 |", "| --- | --- | --- | --- | --- | --- | --- |"])
    lines.extend(f"| {row['ticker']} | {row['current_weight_pct']}% | {row['minus_one_share_weight_pct']}% | {row['plus_one_share_weight_pct']}% | {row['target_pct']}% | {row['hard_cap_pct'] if row['hard_cap_pct'] is not None else '未定义，不作假设'} | ${row['above_target_dollars']} |" for row in diagnostics)
    lines.extend(["", "目标偏离、换手、资金贡献与硬风险分别比较。软容忍带或技术择时政策未作修改。", ""])
    atomic_write_text(REPORT, "\n".join(lines))
    print(f"research_questions_updated=true companies={len(companies)} model_calls=0 canonical_effect=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
