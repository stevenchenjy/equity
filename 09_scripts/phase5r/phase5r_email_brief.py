"""Deterministic, action-first email presentation; public display configuration only, no model authority.

The decision artifact owns eligibility, arithmetic and stability. This module
only projects that artifact into one shared text/HTML view. Global holds take
precedence over lower-level proposals, which remain in the full local report.
"""

from __future__ import annotations

from equity_naming import DISPLAY_NAMES, brand_name, subject_prefix

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
_RESEARCH_HOSTS = _SOURCE_HOSTS | {
    "ir.rubrik.com", "www.rubrik.com", "nvidianews.nvidia.com", "investor.nvidia.com",
    "stockanalysis.com", "www.paloaltonetworks.com", "investors.paloaltonetworks.com",
    "www.investor.gov", "www.finra.org", "www.federalreserve.gov",
    "www.samsara.com", "investors.samsara.com",
    "www.chase.com", "chase.com", "www.jpmorgan.com",
    "newsroom.servicenow.com", "abc.xyz", "investor.tsmc.com", "pr.tsmc.com", "newsroom.arm.com",
    "investors.applovin.com", "investor.atmeta.com", "developers.meta.com",
    "investors.rocketlabcorp.com", "rocketlabcorp.com", "investor.servicenow.com",
    "www.invesco.com", "www.vaneck.com", "www.ssga.com", "www.bls.gov",
    "www.bea.gov", "www.irs.gov", "www.nasdaq.com", "ir.amd.com",
    "newsroom.amd.com", "www.ismworld.org",
}
_UNCONFIRMED_CASH_BASES = {"ledger_estimate", "owner_assumption", "owner_assumed", "planning_assumption"}
_HYPOTHETICAL_BLOCKERS = {"cash_not_confirmed", "existing_tactical_risk_unconfirmed", "open_orders_unconfirmed",
                          "event_calendar_unconfirmed", "existing_order_requires_reconciliation"}
_TRADING_RULES = (
    "规则 1｜入场前写明催化剂或价格形态、失效条件、止盈和复核日期；3–5 个交易日未兑现则复核，不把失败短线自动改成长持。",
    "规则 2｜普通短线计划风险不超过组合的 0.5%，事件交易不超过 0.25%；股数还受整股、现金、预留和仓位上限约束。止损遇跳空可能超过计划损失。",
    "规则 3｜预期目标价差至少覆盖计划风险的 2 倍（2R）；没有可核验依据或条件未满足时，本次新增 0 股、NO TRADE，不为交易而交易。",
    "规则 4｜长期核心仓与短线仓分别记录；卖出后仅按事先写明且重新核验的条件买回，不自动补仓，也不保证能在更低价买回。",
)
_BLOCKED_CODES = {"account_conflict_hold", "data_gate_hold", "fundamental_weakening_review"}
_LABELS = {
    "account_conflict_hold": ("需核对账户", "先核对账户，暂停仓位方案"),
    "data_gate_hold": ("等待数据恢复", "数据未齐，暂停仓位方案"),
    "fundamental_weakening_review": ("需复核基本面", "先复核经营变化，暂停新增方案"),
    "action_review_candidate": ("有方案待复核", "有仓位方案需要你判断"),
    "pending_new_position_stability": ("等待稳定性确认", "新增方案尚未完成稳定性确认"),
    "hold_no_new_position": ("无交易待办", "本次没有新增仓位方案"),
    "hold_pending_research": ("持仓研究待补齐", "暂维持仓位，补齐长期研究依据"),
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


def _safe_source(value: Any, allowed_hosts: set[str] | None = None) -> str:
    text = str(value or "")
    try:
        url = urlsplit(text)
        if (url.scheme != "https" or url.hostname not in (allowed_hosts or _SOURCE_HOSTS)
                or url.username or url.password or url.port is not None
                or any(ord(char) < 33 for char in text)):
            return ""
    except ValueError:
        return ""
    return text


def _owner_research(decision: dict[str, Any]) -> list[dict[str, Any]]:
    """Optional explicit-request appendix, never read by the decision composer.

    A new daily composition drops this appendix. It supplies no action,
    eligibility, arithmetic, or SHADOW evaluation evidence.
    """
    review = decision.get("owner_requested_research")
    if review is None:
        return []
    if (not isinstance(review, dict) or review.get("mode") != "explicit_one_off_research"
            or not decision.get("decision_fingerprint")
            or review.get("decision_fingerprint") != decision["decision_fingerprint"]):
        raise ValueError("owner_research_snapshot_mismatch")
    sections = review.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 6:
        raise ValueError("owner_research_sections_invalid")
    result = []
    for section in sections:
        if (not isinstance(section, dict)
                or any(not isinstance(section.get(key), str) or not section[key].strip()
                       for key in ("title", "body"))
                or len(section["title"]) > 100 or len(section["body"]) > 2400):
            raise ValueError("owner_research_content_invalid")
        sources = section.get("sources", [])
        if not isinstance(sources, list) or len(sources) > 4:
            raise ValueError("owner_research_sources_invalid")
        if any(not _safe_source(url, _RESEARCH_HOSTS) for url in sources):
            raise ValueError("owner_research_source_not_allowed")
        result.append({"title": section["title"], "body": section["body"], "sources": sources})
    return result


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


def _tactical_view(
    decision: dict[str, Any], plans: list[dict[str, str]], *, global_block: bool
) -> list[dict[str, Any]]:
    """Project optional short-term evidence without granting new eligibility.

    Malformed or incomplete additions fail closed, while the existing canonical
    long-term view remains independently governed by its original guards.
    """
    review = decision.get("tactical_review")
    no_trade = "短线 NO TRADE：本次新增 0 股、暂不设新委托。"
    if not isinstance(review, dict):
        return [{"title": "本次短线与订单复核", "lines": [
            no_trade, "缺少可核验的短线行情历史、完整订单快照及入场/退出依据；补齐后再复核，不编造价格。",
        ]}]

    sections = []
    account_value = _decimal(decision.get("account", {}).get("account_total_value"))
    blockers = review.get("blockers", [])
    blockers = blockers if isinstance(blockers, list) else ["malformed_review"]
    next_session = str(review.get("next_session") or "待确认")
    market_session = str(review.get("market_session") or "待确认")
    lines = [f"复核时间：{_time(review.get('as_of'))} 美东；行情交易日：{market_session}（非实时）；适用交易日：{next_session}。",
             "配置复核与短线草案是不同研究情景；同一标的的股数不能相加或叠加委托，实际操作前重新核对共同现金和风险预算。"]
    if global_block or review.get("global_gates_passed") is not True:
        lines.append(no_trade + "账户、现金、证据或现行准入条件尚未全部通过；观察价不是实际委托。")
    if blockers:
        lines.append("尚缺条件：" + "；".join(str(item) for item in blockers))
    sections.append({"title": "本次短线与订单复核", "lines": lines})

    orders = review.get("open_orders")
    if not isinstance(orders, dict):
        orders = {}
    order_lines = [f"订单快照：{_time(orders.get('as_of'))} 美东；完整性：{'已记录完整清单' if orders.get('complete') is True else '未确认完整'}。"]
    order_rows = orders.get("orders", [])
    if not isinstance(order_rows, list) or not order_rows:
        order_lines.append("订单明细缺失；不能把未见订单理解为没有订单。")
        order_rows = []
    for order in order_rows:
        if not isinstance(order, dict):
            order_lines.append("订单记录格式不完整，状态待核对。")
            continue
        status = str(order.get("status") or "unknown").lower()
        tif = str(order.get("time_in_force") or "待确认").upper()
        observed = {"open": "当时为未完成", "cancelled": "当时显示已撤单", "canceled": "当时显示已撤单",
                    "filled": "当时显示已成交", "expired": "当时显示已到期"}.get(status, "当时状态待确认")
        review_status = str(order.get("review_status") or "unknown")
        order_day = str(order.get("session_date") or str(orders.get("as_of") or "")[:10])
        stale_day = tif == "DAY" and status == "open" and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", order_day)) and order_day < next_session
        if stale_day or "expired" in review_status or "stale" in review_status:
            current = "时效或快照已过期，最终状态待核对；不能据此认定成交或撤单"
        else:
            current = "最终状态仍需券商核对；快照不证明当前仍开放"
        side = {"buy": "买入", "sell": "卖出"}.get(str(order.get("side") or "").lower(), "方向待确认")
        order_lines.append(f"{order.get('ticker', '待确认')}：已记录{side} {shares(order.get('remaining_quantity', order.get('quantity')))} 股；限价 {money(order.get('limit_price'))}；{tif}；{observed}；{current}。")
        if order.get("expiration_date"):
            order_lines.append(f"记录的到期日期：{order['expiration_date']}。")
        if order.get("review_reason"):
            order_lines.append("复核依据：" + str(order["review_reason"]))
    order_lines.append("已记录订单股数不是本次新增建议；替换前先确认撤单和剩余数量，未成交不改变持仓。")
    sections.append({"title": "已记录订单的状态与时效", "lines": order_lines})

    canonical = {row["ticker"] for row in plans}
    caps = {}
    for row in decision.get("held_positions", []):
        if isinstance(row, dict) and _action_kind(row) == "新增复核":
            caps[str(row.get("ticker", ""))] = _decimal(row.get("whole_shares_to_change"))
    for row in decision.get("watch_candidates", []):
        if isinstance(row, dict):
            caps[str(row.get("ticker", ""))] = _decimal(row.get("suggested_whole_shares"))
    drafts = review.get("drafts", [])
    if not isinstance(drafts, list):
        drafts = []
    if not drafts:
        sections.append({"title": "短线候选", "lines": [no_trade, "没有具备完整价格、风险和退出依据的短线草案。"]})
    for draft in drafts:
        if not isinstance(draft, dict):
            sections.append({"title": "短线候选记录待核验", "lines": [no_trade, "草案格式不完整，需补齐数据。"]})
            continue
        ticker = str(draft.get("ticker") or "待确认")
        entry, stop, target = (_decimal(draft.get(key)) for key in ("entry_price", "stop_price", "target_price"))
        qty, rr = _decimal(draft.get("quantity")), _decimal(draft.get("reward_to_risk"))
        evidence = draft.get("price_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        history_ok = (evidence.get("validated") is True and evidence.get("history_session") == market_session
                      and bool(re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("snapshot_sha256") or ""))))
        levels_ok = (history_ok and entry is not None and stop is not None and target is not None
                     and 0 < stop < entry < target and rr is not None and rr > 0)
        actual_rr = (target - entry) / (entry - stop) if levels_ok else None
        risk_ok = bool(levels_ok and rr >= 2 and actual_rr >= 2 and abs(rr - actual_rr) <= Decimal("0.02"))
        required = ("entry_rule", "invalidation_rule", "time_exit_session", "reentry_rule", "price_basis")
        details_ok = all(isinstance(draft.get(key), str) and draft[key].strip() for key in required)
        session_ok = (bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", next_session))
                      and draft.get("session_date") == next_session and draft.get("time_in_force") == "DAY")
        try:
            exit_day = datetime.strptime(str(draft.get("time_exit_session", ""))[:10], "%Y-%m-%d").date()
            session_ok = session_ok and exit_day >= datetime.strptime(next_session, "%Y-%m-%d").date()
        except ValueError:
            session_ok = False
        cap = caps.get(ticker)
        draft_blockers = draft.get("blockers", [])
        eligible = (not global_block and review.get("global_gates_passed") is True
                    and review.get("research_only") is True and review.get("automatic_action_allowed") is False
                    and orders.get("complete") is True and not blockers and not draft_blockers
                    and ticker in canonical and draft.get("eligible") is True
                    and draft.get("classification") == "real-trade candidate" and draft.get("side") == "buy"
                    and qty is not None and qty > 0 and qty == qty.to_integral_value()
                    and cap is not None and qty <= cap and risk_ok and details_ok and session_ok
                    and account_value is not None and account_value > 0
                    and qty * entry <= account_value * Decimal("0.05")
                    and qty * (entry - stop) <= account_value * Decimal("0.005")
                    and market_session == decision.get("market_gate", {}).get("expected_market_session"))
        row_lines = [f"{ticker} · {'有条件的人工作业草案（real-trade candidate）' if eligible else '观察名单（watchlist）'}；适用日期：{draft.get('session_date') or next_session}。"]
        if eligible:
            row_lines.append(f"待人工判断：新增 {shares(qty)} 股；限价不高于 {money(entry)}；DAY；尚未提交或执行。")
        else:
            row_lines.append(no_trade)
        if levels_ok and details_ok:
            row_lines.extend([
                ("草案价格：" if eligible else "仅供观察的价格情景（非委托）：")
                + f"入场上限 {money(entry)}；失效/止损参考 {money(stop)}；目标 {money(target)}；收益/风险 {number(actual_rr)}R。",
                "入场条件：" + draft["entry_rule"], "失效条件：" + draft["invalidation_rule"],
                "时间退出：" + draft["time_exit_session"], "再次买回：" + draft["reentry_rule"],
                "价格依据：" + draft["price_basis"],
            ])
            if eligible:
                row_lines.append(f"按上述入场上限的计划风险：{money(qty * (entry - stop))}；跳空或滑点可能扩大损失。")
            hypothetical = _decimal(draft.get("hypothetical_quantity"))
            assumptions = draft.get("hypothetical_assumptions", [])
            all_blockers = set(str(item) for item in blockers)
            if isinstance(draft_blockers, list):
                all_blockers.update(str(item) for item in draft_blockers)
            else:
                all_blockers.add("malformed_review")
            hypothetical_risk_pct = Decimal("0.0025") if draft.get("event_risk") is True or "event_calendar_unconfirmed" in all_blockers else Decimal("0.005")
            canonical_tickers = set(decision.get("eligible_action_review_candidates", [])) | set(decision.get("eligible_new_position_review_candidates", []))
            hypothetical_ok = (not eligible and qty == 0 and risk_ok and session_ok
                               and review.get("research_only") is True and review.get("automatic_action_allowed") is False
                               and bool(all_blockers) and all_blockers <= _HYPOTHETICAL_BLOCKERS
                               and not decision.get("account_conflicts") and decision.get("decision_code") not in _BLOCKED_CODES
                               and all(decision.get(key, {}).get("passed") is True for key in ("market_gate", "evidence_gate", "fundamental_gate"))
                               and ticker in canonical_tickers and ticker not in set(decision.get("pending_stability_candidates", []))
                               and isinstance(assumptions, list) and bool(assumptions)
                               and hypothetical is not None and hypothetical > 0 and hypothetical == hypothetical.to_integral_value()
                               and cap is not None and hypothetical <= cap
                               and account_value is not None and account_value > 0
                               and hypothetical * entry <= account_value * Decimal("0.05")
                               and hypothetical * (entry - stop) <= account_value * hypothetical_risk_pct)
            if hypothetical_ok:
                row_lines.append(f"独立假设情景：{shares(hypothetical)} 股、金额不超过 {money(hypothetical * entry)}；实际合格新增仍为 0 股。")
                row_lines.append("仅在以下假设经确认且所有条件仍成立时重新评估：" + "；".join(str(item) for item in assumptions))
        else:
            row_lines.append("行情历史或入场、止损、目标、时间退出、买回依据未齐/格式无效；不提供完整价格草案。")
        if draft_blockers:
            row_lines.append("未通过：" + ("；".join(str(item) for item in draft_blockers) if isinstance(draft_blockers, list) else "草案条件格式待核对"))
        sections.append({"title": ticker + " · 短线复核", "lines": row_lines})
    return sections


def _watch_view(
    decision: dict[str, Any], plans: list[dict[str, str]], *, gates_passed: bool
) -> list[dict[str, str]]:
    """Expose the actual nonheld shortlist without creating new eligibility."""
    held = {str(row.get("ticker", "")) for row in decision.get("held_positions", [])}
    eligible_plans = {row["ticker"]: row for row in plans if row["ticker"] not in held}
    pending = set(decision.get("pending_stability_candidates", []))
    session = str(decision.get("market_gate", {}).get("expected_market_session") or "待确认")
    translations = {
        "valuation": ("估值证据未齐，合理买入上限尚无法确认", "补齐来源可核验的估值情景"),
        "score": ("研究评分未达准入线", "在新证据下重新评估研究评分"),
        "confidence": ("证据置信度未达准入线", "补齐能提高结论可信度的官方证据"),
        "upside": ("上行情景尚未通过准入校验", "重算估值对应的上行空间"),
        "reward_to_risk": ("情景收益与风险比尚未通过准入校验", "重算下行情景与收益风险比"),
        "entry": ("入场条件未满足", "等待入场条件通过复核"),
        "portfolio_fit": ("与现有组合的匹配度未达要求", "重新评估行业重叠和组合集中度"),
        "whole_share_affordability": ("现金或整股仓位约束尚不支持新增", "核对可用资金、现金储备和整股仓位上限"),
        "whole_share_target_gap": ("目标配置缺口不足一整股", "等待实际配置缺口足以容纳一整股"),
        "one_candidate_attention_limit": ("本轮新增个股复核名额已占用", "等待下一轮候选排序与复核名额"),
        "market_quality": ("行情质量未通过校验", "等待合格行情刷新"),
        "price_range": ("参考价未通过核心配置的价格区间条件", "等待价格区间条件通过复核"),
        "review_capacity": ("本轮配置复核容量不足", "等待配置复核容量恢复"),
        "maintenance": ("维护状态阻断新增方案", "等待维护状态解除"),
    }
    result = []
    seen = set()
    for row in decision.get("watch_candidates", []):
        ticker = str(row.get("ticker", ""))
        if not ticker or ticker in held or ticker in seen:
            continue
        seen.add(ticker)
        reference = (f"参考收盘 {money(row.get('current_price'))}（{session}；非实时）"
                     if decision.get("market_gate", {}).get("passed") is True
                     else f"待核验参考价 {money(row.get('current_price'))}（目标收盘日期 {session}；非实时）")
        plan = eligible_plans.get(ticker)
        if plan:
            result.append({"ticker": ticker, "title": ticker + " · 新增复核候选", "reference": reference,
                           "instruction": plan["scenario"], "reason": plan["reason"],
                           "next_step": plan["limit"] + "；提交前核对最新价格、可用现金及未成交委托。"})
            continue
        reasons, conditions = [], []
        if decision.get("account_conflicts") or decision.get("decision_code") == "account_conflict_hold":
            reasons.append("账户记录存在待核对项")
            conditions.append("先核对账户与未成交委托")
        elif not gates_passed or decision.get("decision_code") == "data_gate_hold":
            reasons.append("本次全局数据校验未通过")
            conditions.append("先恢复合格行情与官方数据")
        elif decision.get("decision_code") == "fundamental_weakening_review":
            reasons.append("当前优先复核持仓基本面变化，新增方案暂停")
            conditions.append("先完成持仓基本面复核")
        elif decision.get("account", {}).get("cash_basis") in _UNCONFIRMED_CASH_BASES:
            reasons.append("现金仍为账本估算或用户指定的规划假设，精确新增股数尚未获准展示")
            conditions.append("实际交易前校准可用现金与仓位分母")
        blockers = {item.strip() for item in str(row.get("gate_blockers", "")).split(",") if item.strip()}
        if not _is_core(row) and _valuation(row).startswith("估值证据不足"):
            blockers.add("valuation")
        for key, (reason, condition) in translations.items():
            if key in blockers:
                reasons.append(reason)
                conditions.append(condition)
        if blockers - translations.keys():
            reasons.append("另有准入阻断项待核对")
            conditions.append("核对本地决策中的其余准入条件")
        if ticker in pending or row.get("action") == "pending_second_distinct_close":
            count = int(row.get("stability_distinct_closes", decision.get("new_candidate_stability_distinct_closes", 0)) or 0)
            required = int(row.get("required_distinct_closes", 2) or 2)
            reasons.append(f"尚未完成 {required} 个不同有效收盘日确认（当前 {count} 个）")
            conditions.append("等待下一个不同的有效收盘；重复刷新不算新确认")
        if not reasons:
            reasons.append("当前没有通过完整校验的新增方案")
            conditions.append("补齐准入依据、股数和价格方案后重新评估")
        if not _is_core(row) and not any("有效收盘" in item for item in conditions):
            conditions.append("准入条件通过后仍须满足两个不同有效收盘日的稳定性要求")
        invalidation = str(row.get("invalidation", "")).strip()
        if invalidation == "reassess on evidence break or valuation/risk conflict":
            conditions.append("证据失效或估值与风险出现冲突时提前复核")
        elif invalidation == "Review immediately because a complete thesis and invalidation rule are pending.":
            conditions.append("先补齐持有逻辑与失效条件")
        elif invalidation:
            conditions.append("原记录的失效条件：" + invalidation)
        result.append({"ticker": ticker, "title": ticker + " · 观察名单（watchlist）", "reference": reference,
                       "instruction": "本次建议新增 0 股；暂不设买入委托。",
                       "reason": "；".join(reasons) + "。", "next_step": "；".join(conditions) + "。"})
    return result


def build_email_view(decision: dict[str, Any]) -> dict[str, Any]:
    code = str(decision.get("decision_code", ""))
    label, title = _LABELS.get(code, ("需核对报告", "报告状态待核对"))
    held = decision.get("held_positions", [])
    watch = decision.get("watch_candidates", [])
    events = decision.get("material_events", [])
    account = decision.get("account", {})
    estimated_cash = account.get("cash_basis") in _UNCONFIRMED_CASH_BASES
    global_block = bool(decision.get("account_conflicts")) or code in _BLOCKED_CODES
    gates_passed = all(decision.get(key, {}).get("passed") is True for key in ("market_gate", "evidence_gate", "fundamental_gate"))
    global_block = global_block or not gates_passed or estimated_cash
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
    elif estimated_cash:
        label, title = "资金区间研究", "持仓已更新，按资金范围评估"
        summary = "现金沿用账本估算或用户指定的规划假设；研究继续，暂不展示依赖精确现金的交易股数。"
        tasks = ["本次无需补交精确现金即可阅读研究；实际交易前核对券商可用资金和最终仓位比例。"]
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
            required = int(decision.get("market_regime", {}).get("required_distinct_closes", 2) or 2)
            if kind == "新增复核" and int(decision.get("action_stability_distinct_closes", 0) or 0) < required:
                tasks.append(f"{ticker} 尚未满足 {required} 个不同有效收盘日的稳定性条件；当前不需要交易确认。")
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
            count = int(row.get("stability_distinct_closes", decision.get("new_candidate_stability_distinct_closes", 0)) or 0)
            required = int(row.get("required_distinct_closes", 2) or 2)
            quantity, price = _decimal(row.get("suggested_whole_shares")), _decimal(row.get("maximum_review_price"))
            if count < required or quantity is None or quantity <= 0 or price is None or price <= 0:
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
    if code == "hold_pending_research" and not plans:
        summary = "当前维持仓位；长期持有逻辑或估值仍待研究补齐，不能把暂未调整理解为已完成投资论证。"

    plan_tickers = {row["ticker"] for row in plans}
    positions = []
    for row in held:
        ticker = str(row.get("ticker", ""))
        if global_block:
            state = ("仅供核对" if decision.get("account_conflicts") or code == "account_conflict_hold"
                     else "区间研究" if estimated_cash else "方案暂停")
        elif ticker in plan_tickers:
            state = _action_kind(row)
        elif ticker in pending:
            state = "等待确认"
        else:
            state = "持仓不变，研究待补齐" if row.get("action") == "hold_pending_research" else "持仓不变" if row.get("action") == "hold" else "仅观察"
        positions.append({"ticker": ticker, "quantity": shares(row.get("current_shares")) + " 股", "weight": percent(row.get("current_weight_pct")), "price": money(row.get("current_price")), "state": state})

    account_lines = [
        f"{'账本情景总值' if estimated_cash else '本地账户估值'} {money(account.get('account_total_value'))} · 持仓市值 {money(account.get('invested_capital'))}",
        f"{'账本现金估算' if estimated_cash else '现金'} {money(account.get('cash_available'))}（{percent(account.get('cash_pct'))}），其中预留 {money(account.get('cash_reserved'))}。预留金额不是全部现金。",
    ]
    if decision.get("account_conflicts") or code == "account_conflict_hold":
        account_lines.append("以上是待核对的本地账面记录，不是已确认券商余额；未成交订单不计作持仓变化。")
    else:
        account_lines.append("账户估值 = 本地现金 + 已记录股数按参考收盘计值；不是实时券商余额。")
    if estimated_cash:
        account_lines.append("现金及上表权重基于本地账本估算或用户指定的规划现金假设，尚非券商已确认的可用或已结算资金；未核对的出入金不自动计入；银行备用资金未计入账户。")
    funding_lines = []
    low, high = _decimal(account.get("planning_capital_min")), _decimal(account.get("planning_capital_max"))
    if low is not None and high is not None and 0 < low <= high:
        funding_lines.append(f"可支持的研究资金规模：{money(low)}–{money(high)}。这是配置情景分母，不是已到账现金，也不是对当前净资产的确认。")
        for row in held:
            if _is_core(row):
                continue
            quantity, price = _decimal(row.get("current_shares")), _decimal(row.get("current_price"))
            if quantity is not None and price is not None:
                value = quantity * price
                funding_lines.append(f"{row.get('ticker', '')}：按 {money(low)} 分母约 {percent(value / low * 100)}；按 {money(high)} 分母约 {percent(value / high * 100)}。")
        funding_lines.append("情景比较不改变现有集中度门槛；新增资金只有实际转入并记录后，才进入生产现金与仓位计算。")

    incomplete = [str(row.get("ticker", "")) for row in held if not _is_core(row) and _valuation(row).startswith("估值证据不足")]
    quality = " · ".join(f"{name}：{'通过' if decision.get(key, {}).get('passed') is True else '未通过'}" for key, name in (("market_gate", "行情"), ("evidence_gate", "官方资料"), ("fundamental_gate", "基础财务")))
    limitations = []
    regime = decision.get("market_regime", {})
    if regime:
        limitations.append(f"市场环境：{regime.get('regime', 'unknown')}；新增方案需 {regime.get('required_distinct_closes', 2)} 个不同有效收盘确认；不因市场价格状态独立退出长期持仓。")
    news = decision.get("evidence_coverage", {}).get("official_news", {})
    if news:
        limitations.append(f"官方新闻覆盖：{news.get('status', 'missing')}；公告出现不代表利好，抓取失败也不代表没有事件。")
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
    if estimated_cash and gates_passed and not decision.get("account_conflicts"):
        next_step = "继续按官方证据研究；资金实际转入或准备交易时再校准现金，不因本次余额未精确核对而要求立即增减仓。"
    next_date = str(decision.get("next_scheduled_review", ""))
    if next_date:
        next_step += f" 例行研究复核：{next_date}；这是研究日期，不是交易期限。"
    return {
        "version": EMAIL_BRIEF_VERSION, "cycle": str(decision.get("cycle_date", "")),
        "label": label, "title": title, "summary": summary, "tasks": tasks, "plans": plans,
        "positions": positions, "account_lines": account_lines, "quality": quality,
        "watchlist": _watch_view(decision, plans, gates_passed=gates_passed),
        "funding_lines": funding_lines,
        "trading_rules": list(_TRADING_RULES),
        "tactical_sections": _tactical_view(decision, plans, global_block=global_block),
        "limitations": limitations, "documents": documents, "receipt": receipt,
        "as_of": (f"{'已核验参考收盘' if decision.get('market_gate', {}).get('passed') is True else '待核验目标收盘'}："
                  f"{decision.get('market_gate', {}).get('expected_market_session') or '待确认'}（非实时） · 生成：{_time(decision.get('generated_at'))} 美东"),
        "next_step": next_step,
        "ai_note": "依据：确定性研究规则与已记录账户。AI 实验不参与本邮件的结论或发送资格。仅供研究；不会连接券商或自动下单。",
    }


def email_subject(
    decision: dict[str, Any], *, correction: bool = False, owner_review: bool = False
) -> str:
    view = build_email_view(decision)
    if owner_review:
        review = decision.get("owner_requested_research", {})
        review_date = _time(review.get("reviewed_at"))[:10]
        return f"{subject_prefix(owner_review=True)} 持仓计划与观察机会｜{review_date}"
    prefix = subject_prefix(correction=correction)
    return f"{prefix} {view['label']}｜{view['cycle']}"


def render_email(decision: dict[str, Any]) -> tuple[str, str, str]:
    view = build_email_view(decision)
    owner_research = _owner_research(decision)
    review = decision.get("owner_requested_research", {})
    dated_review = bool(owner_research and review.get("request_id"))
    subject = email_subject(decision, owner_review=dated_review)
    research_note = "以下为本次人工请求的研究解读，不覆盖确定性规则，不参与自动通知或 SHADOW 评估；下次自动刷新不沿用。"
    research_as_of = (f"本次复核：{_time(review.get('reviewed_at'))} 美东 · 研究行情日期：{review.get('market_as_of', '待确认')}（非实时）"
                      if dated_review else "本次人工请求研究；各项价格以正文标注日期为准。")
    baseline_title = ("原定时报告参考持仓（旧收盘）"
                      if dated_review and review.get("market_as_of") != decision.get("market_gate", {}).get("expected_market_session")
                      else "原定时报告参考持仓" if dated_review else "持仓与现金")
    lines = [subject]
    if owner_research:
        lines.extend(["", "本次请求的个股研究", research_as_of, research_note])
        for section in owner_research:
            lines.extend(["", section["title"], section["body"], *section["sources"]])
        lines.extend(["", "原定时报告背景（保留原生成日期与规则结论）"])
    lines.extend(["", view["title"], view["summary"], view["as_of"], "", "需要你处理"])
    lines.extend("- " + item for item in view["tasks"])
    for plan in view["plans"]:
        lines.extend(["", plan["title"], plan["scenario"], "依据：" + plan["reason"], "限制：" + plan["limit"]])
    lines.extend(["", "短线与长期仓的四条规则", *view["trading_rules"]])
    for section in view["tactical_sections"]:
        lines.extend(["", section["title"], *section["lines"]])
    lines.extend(["", baseline_title])
    lines.extend(f"- {row['ticker']}：{row['quantity']} · {row['weight']} · 参考收盘 {row['price']} · {row['state']}" for row in view["positions"])
    lines.extend(view["account_lines"])
    if view["receipt"]:
        lines.append(view["receipt"])
    if view["funding_lines"]:
        lines.extend(["", "资金范围情景", *view["funding_lines"]])
    lines.extend(["", "未持仓观察与新增计划", "仅列本次确定性候选清单；不是全市场机会排名。"])
    if not view["watchlist"]:
        lines.append("本次候选清单没有未持仓标的。")
    for row in view["watchlist"]:
        lines.extend(["", row["title"], row["reference"], row["instruction"],
                      "依据：" + row["reason"], "再次复核条件：" + row["next_step"]])
    lines.extend(["", "证据与限制", view["quality"], *view["limitations"]])
    if view["documents"]:
        lines.append("本次新纳入的官方文件（披露日不一定是今天）：")
        lines.extend(f"- {row['title']}\n  {row['url'] or '来源链接待核验'}" for row in view["documents"])
    lines.extend(["", "下一步", view["next_step"], "", view["ai_note"]])

    esc = lambda value: html.escape(str(value), quote=True)
    paragraph = lambda value: f'<p style="margin:8px 0;line-height:1.65">{esc(value)}</p>'
    heading = lambda value: f'<h2 style="font-size:17px;line-height:1.4;margin:24px 0 10px;color:#172b3a">{esc(value)}</h2>'
    content = [
        f'<p style="margin:0 0 12px;font-size:12px;letter-spacing:1px;color:#526170">{esc(brand_name())} · {esc(DISPLAY_NAMES["email_tagline"])}</p>',
    ]
    if owner_research:
        content.extend([heading("本次请求的个股研究"), paragraph(research_as_of), paragraph(research_note)])
        for section in owner_research:
            content.extend([heading(section["title"]),
                            '<p style="margin:8px 0;line-height:1.65;white-space:pre-line">' + esc(section["body"]) + '</p>'])
            for url in section["sources"]:
                host = urlsplit(url).hostname
                source_label = ("行情参考来源" if host == "stockanalysis.com"
                                else "券商订单说明来源" if host in {"www.chase.com", "chase.com", "www.jpmorgan.com"}
                                else "官方研究来源" if host in {"www.investor.gov", "www.finra.org", "www.federalreserve.gov",
                                                              "www.bea.gov", "www.bls.gov", "www.irs.gov", "www.ismworld.org",
                                                              "www.nasdaq.com", "www.invesco.com", "www.vaneck.com", "www.ssga.com",
                                                              "developers.meta.com", "rocketlabcorp.com"}
                                else "官方财报来源")
                content.append(f'<p><a style="color:#245d76" href="{esc(url)}">{esc(section["title"])} · {source_label}</a></p>')
        content.append(heading("原定时报告背景（保留原生成日期与规则结论）"))
    content.extend([
        f'<p style="margin:0 0 8px;color:#365366;font-size:13px;font-weight:700">{esc(view["label"])}</p>',
        f'<h1 style="margin:0 0 12px;font-size:24px;line-height:1.4;color:#172b3a">{esc(view["title"])}</h1>',
        paragraph(view["summary"]),
        '<p style="margin:12px 0 20px;font-size:12px;line-height:1.6;color:#526170">' + '<br>'.join(esc(part) for part in view["as_of"].split(" · ")) + '</p>',
        '<div style="background:#eef4f6;border-left:3px solid #365366;padding:12px 16px">',
        '<h2 style="margin:0 0 8px;font-size:16px">需要你处理</h2>',
        *[paragraph(item) for item in view["tasks"]], '</div>',
    ])
    for plan in view["plans"]:
        content.extend([heading(plan["title"]), paragraph(plan["scenario"]), paragraph("依据：" + plan["reason"]), paragraph("限制：" + plan["limit"])])
    content.append(heading("短线与长期仓的四条规则"))
    content.extend(paragraph(item) for item in view["trading_rules"])
    for section in view["tactical_sections"]:
        content.append(heading(section["title"]))
        content.extend(paragraph(item) for item in section["lines"])
    content.append(heading(baseline_title))
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
    if view["funding_lines"]:
        content.append(heading("资金范围情景"))
        content.extend(paragraph(item) for item in view["funding_lines"])
    content.extend([heading("未持仓观察与新增计划"), paragraph("仅列本次确定性候选清单；不是全市场机会排名。")])
    if not view["watchlist"]:
        content.append(paragraph("本次候选清单没有未持仓标的。"))
    for row in view["watchlist"]:
        content.extend([heading(row["title"]), paragraph(row["reference"]), paragraph(row["instruction"]),
                        paragraph("依据：" + row["reason"]), paragraph("再次复核条件：" + row["next_step"])])
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
