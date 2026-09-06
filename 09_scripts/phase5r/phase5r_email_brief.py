"""Deterministic, action-first email presentation; no I/O or model authority.

The decision artifact owns eligibility, arithmetic and stability. This module
only projects that artifact into one shared text/HTML view. Global holds take
precedence over lower-level proposals, which remain in the full local report.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


EMAIL_BRIEF_VERSION = "phase5r_action_email_v2"
_NUMBER = r"-?\d+(?:\.\d+)?"
_SOURCE_HOSTS = {"sec.gov", "www.sec.gov", "data.sec.gov"}
_BLOCKED_CODES = {"account_conflict_hold", "data_gate_hold", "fundamental_weakening_review"}
_LABELS = {
    "account_conflict_hold": ("需核对账户", "先核对账户，暂停仓位方案"),
    "data_gate_hold": ("等待数据恢复", "数据未齐，暂停仓位方案"),
    "fundamental_weakening_review": ("需复核基本面", "先复核经营变化，暂停新增方案"),
    "action_review_candidate": ("有方案待复核", "有仓位方案需要你判断"),
    "pending_new_position_stability": ("等待第二次确认", "新增方案尚未完成稳定性确认"),
    "hold_no_new_position": ("无交易待办", "本次没有新增仓位方案"),
}


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def number(value: Any, places: int = 2, *, trim: bool = False) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "待确认"
    try:
        text = f"{parsed.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):,.{places}f}"
    except InvalidOperation:
        return "待确认"
    return text.rstrip("0").rstrip(".") if trim and "." in text else text


def money(value: Any) -> str:
    return "$" + number(value) if _decimal(value) is not None else "待确认"


def percent(value: Any, places: int = 2) -> str:
    return number(value, places) + "%" if _decimal(value) is not None else "待确认"


def shares(value: Any) -> str:
    return number(value, 4, trim=True)


def _comparison_weight(value: str, threshold: str) -> str:
    # Extra precision only when two decimals would hide which side of a cap
    # the deterministic value is on. Display rounding never changes the rule.
    return percent(value, 4 if number(value) == number(threshold) else 2)


def _time(value: Any) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return "待确认"
        return timestamp.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "待确认"


def _is_core(row: dict[str, Any]) -> bool:
    return row.get("asset_role") == "core_allocation" or row.get("valuation_applicability") == "not_applicable_broad_market_etf"


def _valuation(row: dict[str, Any]) -> str:
    if _is_core(row):
        return "宽基 ETF，按核心配置规则评估"
    values = [row.get(f"valuation_{band}_price") for band in ("bear", "base", "bull")]
    if all(_decimal(value) is not None and _decimal(value) > 0 for value in values):
        return "低 / 中 / 高情景：" + " / ".join(money(value) for value in values) + "；是条件估算，不是价格预测或承诺回报"
    return "估值证据不足，暂不提供价格区间"


def _action_kind(row: dict[str, Any]) -> str:
    action = str(row.get("action", "")).lower()
    if any(word in action for word in ("trim", "reduce")):
        return "减仓复核"
    if any(word in action for word in ("exit", "sell")):
        return "退出复核"
    if any(word in action for word in ("add", "buy", "core_allocation_tranche")):
        return "新增复核"
    return "持仓不变"


def _reason(row: dict[str, Any]) -> str:
    """Translate known deterministic templates, never invent a company thesis."""
    reason = str(row.get("reason", ""))
    hard = re.search(rf"Dynamic weight ({_NUMBER})% exceeds the ({_NUMBER})% hard cap", reason)
    if hard:
        return f"权重 {_comparison_weight(hard[1], hard[2])} 超过 {percent(hard[2])} 硬上限；这是集中度复核，不代表对公司经营的负面判断。"
    valuation = re.search(rf"Dynamic weight ({_NUMBER})% exceeds the ({_NUMBER})% default cap, current price \$({_NUMBER}) is above the \$({_NUMBER}) bull scenario, expected upside is ({_NUMBER})%, and reward/risk is ({_NUMBER})", reason)
    if valuation:
        return (f"权重 {_comparison_weight(valuation[1], valuation[2])} 超过 {percent(valuation[2])} 默认线，且参考收盘 {money(valuation[3])} 高于高情景 {money(valuation[4])}；"
                f"中情景价差 {percent(valuation[5])}，情景收益/风险比 {number(valuation[6])}。这些是条件估算，不是预期收益保证。")
    if reason.startswith("Current research score requires an independent exit review"):
        return "确定性研究评分触发退出复核；需要核对经营假设是否确实被新证据削弱，不能仅凭评分判断。"
    if re.search(r"[\u4e00-\u9fff]", reason):
        return reason
    return "确定性规则形成复核候选；简要触发依据尚未完整，需查阅本地决策报告后再判断。"


def _safe_source(value: Any) -> str:
    text = str(value or "")
    try:
        url = urlsplit(text)
        if (url.scheme != "https" or url.hostname not in _SOURCE_HOSTS
                or url.username or url.password or url.port is not None
                or any(ord(char) < 33 for char in text)):
            return ""
    except ValueError:
        return ""
    return text


def _conflict_tasks(decision: dict[str, Any]) -> list[str]:
    conflicts = decision.get("account_conflicts", [])
    pending = decision.get("pending_execution_summaries", [])
    tasks = []
    if pending or any(str(item).startswith("pending_execution:") for item in conflicts):
        tickers = "、".join(sorted({str(row.get("ticker", "")) for row in pending if row.get("ticker")}))
        tasks.append(f"核对{tickers + ' ' if tickers else ''}待处理订单：请告知仍未成交、已成交还是已撤单；已成交时提供股数、价格及净到账或含费总支出。")
    if any(not str(item).startswith("pending_execution:") for item in conflicts):
        tasks.append("本地成交与持仓/现金记录尚未完全对齐，需先完成账户核对；已报告的成交不用重复记账。")
    return tasks or ["本地账户记录存在冲突，需核对已确认的持仓、现金与成交状态。"]


def build_email_view(decision: dict[str, Any]) -> dict[str, Any]:
    code = str(decision.get("decision_code", ""))
    label, title = _LABELS.get(code, ("需核对报告", "报告状态待核对"))
    held = decision.get("held_positions", [])
    watch = decision.get("watch_candidates", [])
    events = decision.get("material_events", [])
    global_block = bool(decision.get("account_conflicts")) or code in _BLOCKED_CODES
    gates_passed = all(decision.get(key, {}).get("passed") is True for key in ("market_gate", "evidence_gate", "fundamental_gate"))
    global_block = global_block or not gates_passed
    action_allowed = code == "action_review_candidate" and not global_block
    pending = set(decision.get("pending_stability_candidates", []))
    eligible = set(decision.get("eligible_action_review_candidates", [])) if action_allowed else set()
    eligible_new = set(decision.get("eligible_new_position_review_candidates", [])) if action_allowed else set()
    tasks: list[str] = []
    plans: list[dict[str, str]] = []
    if decision.get("account_conflicts") or code == "account_conflict_hold":
        label, title = _LABELS["account_conflict_hold"]
        tasks = _conflict_tasks(decision)
        summary = "当前只处理账户核对；仓位调整方案暂停展示。"
    elif not gates_passed or code == "data_gate_hold":
        label, title = _LABELS["data_gate_hold"]
        tasks = ["当前没有可复核的交易方案；等待行情或官方数据恢复，系统按既有流程复核。"]
        summary = "资料未通过校验，本邮件不提供增减仓数量或价格方案。"
    elif code == "fundamental_weakening_review":
        names = "、".join(decision.get("fundamental_gate", {}).get("weakening_tickers", [])) or "相关持仓"
        tasks = [f"复核 {names} 的最新官方收入变化，以及它是否削弱原有持有理由。"]
        summary = "这是经营假设复核，不是自动减仓信号。"
    elif code not in _LABELS:
        tasks = ["报告状态未识别，需先核对系统输出；不展示仓位方案。"]
        summary = "当前结论不能作为交易依据。"
    else:
        for row in held:
            ticker = str(row.get("ticker", ""))
            if ticker not in eligible or ticker in pending:
                continue
            kind = _action_kind(row)
            if kind == "持仓不变":
                continue
            if kind == "新增复核" and int(decision.get("action_stability_distinct_closes", 0) or 0) < 2:
                tasks.append(f"{ticker} 尚未满足两个不同有效收盘日的稳定性条件；当前不需要交易确认。")
                continue
            change = _decimal(row.get("whole_shares_to_change"))
            target = _decimal(row.get("target_shares"))
            if change is None or change <= 0 or target is None or target < 0:
                tasks.append(f"{ticker} 的{kind}数量尚不完整，需先补齐记录；不展示股数方案。")
                continue
            verb = "增加" if kind == "新增复核" else "减少"
            plans.append({
                "ticker": ticker, "title": f"{ticker} · {kind}",
                "scenario": f"待判断情景：{verb} {shares(change)} 股，持仓 {shares(row.get('current_shares'))} → {shares(target)} 股。尚未执行。",
                "reason": _reason(row),
                "limit": "仅为研究复核；实际价格、费用及税费可能改变结果。" + ("" if _is_core(row) else " " + _valuation(row)),
            })
        for row in watch:
            ticker = str(row.get("ticker", ""))
            if ticker not in eligible_new or ticker in pending:
                continue
            count = int(decision.get("new_candidate_stability_distinct_closes", 0) or 0)
            quantity, price = _decimal(row.get("suggested_whole_shares")), _decimal(row.get("maximum_review_price"))
            if count < 2 or quantity is None or quantity <= 0 or price is None or price <= 0:
                tasks.append(f"{ticker} 的新增方案条件尚未完整；继续等待，不展示可执行式数量。")
                continue
            plans.append({
                "ticker": ticker, "title": f"{ticker} · 新增复核",
                "scenario": f"待判断上限：{shares(quantity)} 股；复核价格上限 {money(price)}，不是已提交订单。",
                "reason": f"已通过现行确定性准入条件，并在 {count} 个不同有效收盘日保持一致。",
                "limit": _valuation(row) + "；实际价格、费用和现金约束仍需核对。",
            })
        if plans:
            tasks.insert(0, f"有 {len(plans)} 项仓位研究方案需要你判断；不是下单指令。")
            summary = "复核触发依据与限制后，由你独立决定是否采取任何交易。"
        elif pending:
            label, title = _LABELS["pending_new_position_stability"]
            tasks.append("、".join(sorted(pending)) + " 尚未满足稳定性或数据条件；当前不需要交易确认。")
            summary = "系统等待下一个不同的有效收盘；重复刷新不算第二次确认。"
        elif events:
            names = "、".join(sorted({str(row.get("ticker", "")) for row in events if row.get("ticker")}))
            label, title = "有文件待复核", "新增文件待复核"
            tasks.append(f"复核 {names or '下方'} 本次新纳入的官方文件是否影响原有研究判断；仓位方案不变。")
            summary = "本次需要的是研究复核，不是交易确认。"
        elif tasks:
            label, title = "需补齐方案", "方案资料尚未完整"
            summary = "方案细节仍待补齐，不能仅凭本邮件执行。"
        else:
            tasks.append("没有需要你确认的交易方案；继续按既有条件观察。")
            summary = "确定性规则本次没有形成新的仓位调整建议。"

    plan_tickers = {row["ticker"] for row in plans}
    positions = []
    for row in held:
        ticker = str(row.get("ticker", ""))
        if global_block:
            state = "仅供核对" if decision.get("account_conflicts") or code == "account_conflict_hold" else "方案暂停"
        elif ticker in plan_tickers:
            state = _action_kind(row)
        elif ticker in pending:
            state = "等待确认"
        else:
            state = "持仓不变" if row.get("action") == "hold" else "仅观察"
        positions.append({"ticker": ticker, "quantity": shares(row.get("current_shares")) + " 股", "weight": percent(row.get("current_weight_pct")), "price": money(row.get("current_price")), "state": state})

    account = decision.get("account", {})
    account_lines = [
        f"本地账户估值 {money(account.get('account_total_value'))} · 持仓市值 {money(account.get('invested_capital'))}",
        f"现金 {money(account.get('cash_available'))}（{percent(account.get('cash_pct'))}），其中预留 {money(account.get('cash_reserved'))}。预留金额不是全部现金。",
    ]
    if decision.get("account_conflicts") or code == "account_conflict_hold":
        account_lines.append("以上是待核对的本地账面记录，不是已确认券商余额；未成交订单不计作持仓变化。")
    else:
        account_lines.append("账户估值 = 本地现金 + 已记录股数按参考收盘计值；不是实时券商余额。")

    incomplete = [str(row.get("ticker", "")) for row in held if not _is_core(row) and _valuation(row).startswith("估值证据不足")]
    quality = " · ".join(f"{name}：{'通过' if decision.get(key, {}).get('passed') is True else '未通过'}" for key, name in (("market_gate", "行情"), ("evidence_gate", "官方资料"), ("fundamental_gate", "基础财务")))
    limitations = []
    if incomplete:
        limitations.append("、".join(incomplete) + " 估值证据不足；基础财务校验通过不代表估值完整。")
    core_gap = [str(row.get("ticker", "")) for row in watch if "whole_share_target_gap" in str(row.get("gate_blockers", ""))]
    if core_gap and not global_block:
        limitations.append("、".join(core_gap) + " 的目标配置缺口不足一整股；这不等于现金买不起。")

    documents = []
    held_tickers = {str(row.get("ticker", "")) for row in held}
    ordered_events = sorted(events, key=lambda row: (row.get("ticker") not in held_tickers, str(row.get("ticker", "")), str(row.get("accession_number", ""))))
    for row in ordered_events:
        documents.append({"title": f"{row.get('ticker', '')} · {row.get('form', '')} · 披露日 {row.get('filing_date', '待确认')}", "url": _safe_source(row.get("source_url"))})

    receipt = ""
    fill = decision.get("recent_applied_execution", {})
    if fill and not decision.get("account_conflicts") and code != "account_conflict_hold":
        verb = "卖出" if fill.get("side") == "sell" else "买入" if fill.get("side") == "buy" else "成交"
        receipt = f"最近已入账（不是待办）：{fill.get('fill_date', '')} {fill.get('ticker', '')} {verb} {shares(fill.get('shares'))} 股，成交价 {money(fill.get('fill_price'))}。"
        net = _decimal(fill.get("net_cash_change"))
        if net is not None:
            receipt += (" 净到账 " if net >= 0 else " 含费总支出 ") + money(abs(net)) + "。"

    next_step = "出现新的官方证据、账户变化或满足稳定性条件时重新评估。"
    if code == "account_conflict_hold" or decision.get("account_conflicts"):
        next_step = "账户状态核对完成后重新生成方案；没有交易截止时刻。"
    elif not gates_passed:
        next_step = "等待下一次合格数据刷新；数据不足期间不升级交易方案。"
    elif plans:
        next_step = "复核前再次核对最新价格、股数、现金及费用；邮件不是实时行情或限时交易通知。"
    next_date = str(decision.get("next_scheduled_review", ""))
    if next_date:
        next_step += f" 例行研究复核：{next_date}；这是研究日期，不是交易期限。"
    return {
        "version": EMAIL_BRIEF_VERSION, "cycle": str(decision.get("cycle_date", "")),
        "label": label, "title": title, "summary": summary, "tasks": tasks, "plans": plans,
        "positions": positions, "account_lines": account_lines, "quality": quality,
        "limitations": limitations, "documents": documents, "receipt": receipt,
        "as_of": (f"{'已核验参考收盘' if decision.get('market_gate', {}).get('passed') is True else '待核验目标收盘'}："
                  f"{decision.get('market_gate', {}).get('expected_market_session') or '待确认'}（非实时） · 生成：{_time(decision.get('generated_at'))} 美东"),
        "next_step": next_step,
        "ai_note": "依据：确定性研究规则与已记录账户。AI 实验不参与本邮件的结论或发送资格。仅供研究；不会连接券商或自动下单。",
    }


def email_subject(decision: dict[str, Any], *, correction: bool = False) -> str:
    view = build_email_view(decision)
    prefix = "[Phase 5R 更正版]" if correction else "[Phase 5R]"
    return f"{prefix} {view['label']}｜{view['cycle']}"


def render_email(decision: dict[str, Any]) -> tuple[str, str, str]:
    view = build_email_view(decision)
    subject = email_subject(decision)
    lines = [subject, "", view["title"], view["summary"], view["as_of"], "", "需要你处理"]
    lines.extend("- " + item for item in view["tasks"])
    for plan in view["plans"]:
        lines.extend(["", plan["title"], plan["scenario"], "依据：" + plan["reason"], "限制：" + plan["limit"]])
    lines.extend(["", "持仓与现金"])
    lines.extend(f"- {row['ticker']}：{row['quantity']} · {row['weight']} · 参考收盘 {row['price']} · {row['state']}" for row in view["positions"])
    lines.extend(view["account_lines"])
    if view["receipt"]:
        lines.append(view["receipt"])
    lines.extend(["", "证据与限制", view["quality"], *view["limitations"]])
    if view["documents"]:
        lines.append("本次新纳入的官方文件（披露日不一定是今天）：")
        lines.extend(f"- {row['title']}\n  {row['url'] or '来源链接待核验'}" for row in view["documents"])
    lines.extend(["", "下一步", view["next_step"], "", view["ai_note"]])

    esc = lambda value: html.escape(str(value), quote=True)
    paragraph = lambda value: f'<p style="margin:8px 0;line-height:1.65">{esc(value)}</p>'
    heading = lambda value: f'<h2 style="font-size:17px;line-height:1.4;margin:24px 0 10px;color:#172b3a">{esc(value)}</h2>'
    content = [
        '<p style="margin:0 0 12px;font-size:12px;letter-spacing:1px;color:#526170">PHASE 5R · 研究提醒</p>',
        f'<p style="margin:0 0 8px;color:#365366;font-size:13px;font-weight:700">{esc(view["label"])}</p>',
        f'<h1 style="margin:0 0 12px;font-size:24px;line-height:1.4;color:#172b3a">{esc(view["title"])}</h1>',
        paragraph(view["summary"]),
        '<p style="margin:12px 0 20px;font-size:12px;line-height:1.6;color:#526170">' + '<br>'.join(esc(part) for part in view["as_of"].split(" · ")) + '</p>',
        '<div style="background:#eef4f6;border-left:3px solid #365366;padding:12px 16px">',
        '<h2 style="margin:0 0 8px;font-size:16px">需要你处理</h2>',
        *[paragraph(item) for item in view["tasks"]], '</div>',
    ]
    for plan in view["plans"]:
        content.extend([heading(plan["title"]), paragraph(plan["scenario"]), paragraph("依据：" + plan["reason"]), paragraph("限制：" + plan["limit"])])
    content.append(heading("持仓与现金"))
    content.append('<table style="width:100%;border-collapse:collapse;font-size:14px;line-height:1.55"><caption style="text-align:left;font-size:12px;color:#526170;padding-bottom:8px">已记录持仓 · 权重按参考收盘计算</caption><thead><tr>')
    for header in ("标的", "持仓 / 权重", "参考收盘", "本次状态"):
        content.append(f'<th scope="col" style="text-align:left;padding:9px 4px;border-bottom:1px solid #ced8de;font-size:12px;color:#526170">{header}</th>')
    content.append('</tr></thead><tbody>')
    for row in view["positions"]:
        style = 'style="padding:12px 4px;border-bottom:1px solid #e5eaee;text-align:left;vertical-align:top"'
        content.append(f'<tr><th scope="row" {style}>{esc(row["ticker"])}</th><td {style}>{esc(row["quantity"])}<br><span style="font-size:12px;color:#526170">{esc(row["weight"])}</span></td><td {style}>{esc(row["price"])}</td><td {style}>{esc(row["state"])}</td></tr>')
    content.append('</tbody></table>')
    content.extend(paragraph(item) for item in view["account_lines"])
    if view["receipt"]:
        content.append(paragraph(view["receipt"]))
    content.extend([heading("证据与限制"), paragraph(view["quality"])])
    content.extend(paragraph(item) for item in view["limitations"])
    if view["documents"]:
        content.append(paragraph("本次新纳入的官方文件（披露日不一定是今天）："))
        for row in view["documents"]:
            label = esc(row["title"])
            link = f'<a href="{esc(row["url"])}" style="color:#245d76;text-decoration:underline">{label}（SEC）</a>' if row["url"] else label + "（来源链接待核验）"
            content.append(f'<p style="margin:8px 0;line-height:1.65">{link}</p>')
    content.extend([heading("下一步"), paragraph(view["next_step"]), f'<p style="margin:24px 0 0;border-top:1px solid #e5eaee;padding-top:14px;font-size:12px;color:#526170;line-height:1.65">{esc(view["ai_note"])}</p>'])
    document = ('<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{esc(subject)}</title></head><body style="margin:0;background:#f3f5f7;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\',\'Microsoft YaHei\',sans-serif;color:#172b3a;font-size:15px">'
                '<div style="display:none;font-size:1px;color:#f3f5f7;max-height:0;overflow:hidden">' + esc(view["summary"]) + '</div>'
                '<div style="max-width:640px;margin:0 auto;background:#ffffff;padding:24px 16px;overflow-wrap:break-word">'
                + ''.join(content) + '</div></body></html>\n')
    return subject, "\n".join(lines) + "\n", document
