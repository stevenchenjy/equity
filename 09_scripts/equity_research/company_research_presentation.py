"""Source-verified company judgments for display, without order authority."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from daily_common import read_json, sha256_file, latest_published_market_session
from valuation_input_bundle import validate_and_materialize_bundle, _verified_source


def admission_details(proof: dict | None, *, root: Path) -> dict | None:
    """Recover authored method/horizon only for the exact current admission."""
    if not proof or proof.get('status') != 'admitted_current': return None
    from company_valuation import STORE_REL, validate_store
    try:
        record = validate_store(read_json(root / STORE_REL, {})).get(proof.get('ticker'))
        if not record or any(record[key] != proof.get(key) for key in
                ('record_sha256', 'model_sha256', 'review_record_sha256')): return None
        return record
    except (OSError, ValueError, KeyError, TypeError):
        return None


def presentation_case(view: dict, *, root: Path, current: datetime,
                      quote: dict, minimum_reward_to_risk: Decimal,
                      admission: dict | None = None) -> dict | None:
    """Display a verified judgment even when its valuation is unresolved.

    Reopened or expired records retain their dated conclusion and dependencies,
    but never acquire current scenario numbers. This projection cannot clear
    company, entry, sizing, current-source or model-admission requirements.
    """
    record = view.get('review_record')
    if not record or view.get('validation_errors'):
        return None
    try:
        reviewed = datetime.fromisoformat(record['reviewed_at'].replace('Z', '+00:00'))
        due = datetime.fromisoformat(record['next_review_at'].replace('Z', '+00:00'))
        if reviewed.tzinfo is None or due.tzinfo is None or reviewed > current:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    pending = list(view.get('reopen_reasons', []))
    current_review = (view.get('status') in {'reviewed', 'monitor'}
                      and not pending and current < due)
    if current >= due and 'scheduled_company_review_due' not in pending:
        pending.append('scheduled_company_review_due')
    news = view.get('news_review', {})
    if not news.get('coverage_complete'):
        pending.append('configured_issuer_news_coverage_incomplete')
    if news.get('status') != 'current':
        pending.append('issuer_news_impact_review_incomplete')
    model = record.get('valuation_model')
    conditions = []
    for key in ('business_case', 'per_share_economics', 'valuation', 'portfolio_role_and_alternatives'):
        conditions.extend(record.get(key, {}).get('unresolved', []))
    conditions.extend(record.get('unresolved_questions', []))
    conditions.extend(record.get('invalidation_conditions', []))
    countercase = (model or {}).get('countercase_reason') or '；'.join(
        claim['statement'] for claim in record.get('claims', []) if claim.get('stance') == 'contradictory')
    case = {
        'schema_version': 'equity_company_case_presentation_v1', 'ticker': record['ticker'],
        'review_id': record['review_id'], 'review_version': record['version'],
        'reviewed_at': record['reviewed_at'], 'next_review_at': record['next_review_at'],
        'conclusion': view.get('conclusion') or record['conclusion'],
        'review_status': 'current' if current_review else 'reassessment_required',
        'business_case_status': view.get('business_case_status'),
        'valuation_readiness': view.get('valuation_readiness'),
        'method': record.get('valuation', {}).get('summary', '公司估值未完成'),
        'horizon': '估值期限尚未完成' if not model else '尚未验证当前模型期限',
        'countercase': countercase, 'review_conditions': list(dict.fromkeys(conditions)),
        'reference_price': None, 'reference_close': None, 'live_quote': False,
        'scenario_prices': None, 'base_upside_pct': None, 'scenario_reward_to_risk': None,
        'minimum_reward_to_risk': float(minimum_reward_to_risk),
        'valuation_only_review_ceiling': None, 'review_ceiling_is_order_price': False,
        'model_admission_status': 'no_completed_model' if not model else 'research_model_unverified',
        'pending_requirements': pending, 'model_relative_path': (model or {}).get('relative_path'),
        'model_sha256': (model or {}).get('sha256'), 'automatic_action_allowed': False,
    }
    try:
        price = Decimal(str(quote.get('last_price', '')))
        valid_quote = (price.is_finite() and price > 0 and quote.get('data_quality_label') == 'ok'
            and quote.get('market_session_date') == latest_published_market_session(current).isoformat())
        if valid_quote:
            case.update(reference_price=float(price), reference_close=quote['market_session_date'])
        else:
            pending.append('current_completed_close_unverified')
    except (InvalidOperation, ValueError, TypeError):
        valid_quote = False
        pending.append('current_completed_close_unverified')
    if not model:
        pending.append('company_specific_valuation_incomplete')
    elif current_review:
        try:
            path = (root / model['relative_path']).resolve()
            if not path.is_relative_to(root.resolve()) or sha256_file(path) != model['sha256']:
                raise ValueError('research_model_source_unverified')
            bundle = read_json(path)
            receipts, _ = validate_and_materialize_bundle(bundle, packet_as_of=record['reviewed_at'],
                active_tickers={record['ticker']}, project_root=root)
            if len(receipts) != 1 or not receipts[0]['sufficiency']['scenario_sufficient']:
                raise ValueError('research_model_inputs_incomplete')
            original = next(r for r in bundle['records'] if r['ticker'] == record['ticker'])
            cases = {'bear': Decimal(original['inputs']['downside_price_assumption']['value']),
                     'base': Decimal(original['inputs']['target_price_assumption']['value'])}
            method, horizon = '', ''
            for source in original['sources']:
                if source['source_type'] != 'human_valuation_scenario':
                    continue
                verified, _ = _verified_source(source, ticker=record['ticker'],
                    packet_as_of=reviewed, project_root=root)
                document = json.loads(verified['excerpt_text'])
                if isinstance(document, dict):
                    if isinstance(document.get('method'), str): method = document['method']
                    if isinstance(document.get('horizon'), str): horizon = document['horizon']
                found = []

                def walk(node):
                    if isinstance(node, dict):
                        if node.get('case') == 'bull':
                            for key in ('research_value_per_share', 'price', 'implied_price', 'implied_equity_value_per_share'):
                                if key in node: found.append(Decimal(str(node[key])))
                        for value in node.values(): walk(value)
                    elif isinstance(node, list):
                        for value in node: walk(value)

                walk(document)
                if found and len(set(found)) == 1: cases['bull'] = found[0]
            if (any(not value.is_finite() or value < 0 for value in cases.values())
                    or cases['bear'] >= cases['base'] or ('bull' in cases and cases['base'] > cases['bull'])):
                raise ValueError('research_model_prices_invalid')
            case.update(method=method or (admission or {}).get('method', model['assumptions_reason']),
                horizon=horizon or (admission or {}).get('horizon', 'Reviewed source-bound scenario horizon'),
                model_admission_status='admitted_current' if admission else 'research_only_pending_admission')
            if valid_quote:
                rr = (cases['base'] - price) / (price - cases['bear']) if price > cases['bear'] else None
                ceiling = (cases['base'] + minimum_reward_to_risk * cases['bear']) / (1 + minimum_reward_to_risk)
                case.update(scenario_prices={k: float(v) for k, v in cases.items()},
                    base_upside_pct=float((cases['base'] / price - 1) * 100),
                    scenario_reward_to_risk=float(rr) if rr is not None else None,
                    valuation_only_review_ceiling=float(ceiling))
            if not admission:
                pending.append('company_model_not_admitted')
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation, StopIteration):
            pending.append('research_model_source_unverified')
            case['review_status'] = 'reassessment_required'
    elif model:
        pending.append('company_model_requires_reassessment')
    case['pending_requirements'] = list(dict.fromkeys(pending))
    return case


def case_lines(case: dict, *, shares: int, order_side: str | None = None) -> list[str]:
    current = case.get('review_status', 'current') == 'current'
    lines = [case['conclusion'] if current else '保留的历史判断（须重新复核，不能作为当前交易指令）：' + case['conclusion'],
        f"当前{'卖出订单草案' if order_side == 'sell' else '新增订单'}股数：{shares} 股。研究判断与完整交易草案分别校验。"]
    if case.get('reference_price') is not None:
        lines.append(f"参考收盘：{case['reference_close']} · ${case['reference_price']:.2f} · 非实时。")
    else:
        lines.append('当前已完成收盘未核验；不提供现价估值或订单价格。')
    prices = case.get('scenario_prices')
    if prices:
        lines.extend([
            '悲观／基准／乐观情景：' + ' / '.join(f"${prices[k]:.2f}" if k in prices else '未核验' for k in ('bear', 'base', 'bull')) + '；分析假设，不是保证价格。',
            f"基准上涨空间 {case['base_upside_pct']:.2f}%；情景收益／风险比 " + (f"{case['scenario_reward_to_risk']:.2f}" if case['scenario_reward_to_risk'] is not None else '未核验') + f"，现行最低要求 {case['minimum_reward_to_risk']:.2f}。",
            f"估值复核参考上限 ${case['valuation_only_review_ceiling']:.2f}，不是买入限价或订单。"])
    else:
        lines.append('当前悲观／基准／乐观估值未完成或需要重新复核；没有可用的估值买入价。')
    statuses = {'admitted_current':'已准入当前生产估值。',
        'research_only_pending_admission':'已记录研究模型，生产估值准入待完成。',
        'no_completed_model':'公司特定估值尚未完成；当前没有完整模型。',
        'research_model_unverified':'原研究模型需要重新核验；不展示当前情景价格。'}
    labels = {'configured_issuer_news_coverage_incomplete':'官方新闻覆盖',
        'issuer_news_impact_review_incomplete':'新闻影响复核', 'company_model_not_admitted':'公司模型准入',
        'company_specific_valuation_incomplete':'公司特定估值', 'scheduled_company_review_due':'公司复核已到期',
        'company_model_requires_reassessment':'模型须随公司判断重新复核',
        'current_completed_close_unverified':'当前已完成收盘', 'research_model_source_unverified':'原模型与来源核验'}
    lines.extend(['方法：' + case['method'], '期限：' + case['horizon'],
        '反方证据：' + case['countercase'],
        ('原复核期限已到期／需重新复核：' if not current else '下一次复核：') + case['next_review_at'] + '；重大公司证据或价格变化时提前复核。',
        *('复核条件：' + text for text in case['review_conditions']),
        '模型状态：' + statuses.get(case['model_admission_status'], '未核验。') +
        (' 待完成：' + '、'.join(labels.get(v, v) for v in case['pending_requirements']) if case['pending_requirements'] else '')])
    return lines
