"""Source-verified company judgments for display, without order authority."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from daily_common import read_json, sha256_file
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
    record = view.get('review_record')
    if (not record or view.get('status') not in {'reviewed', 'monitor'}
            or view.get('validation_errors') or view.get('reopen_reasons')
            or datetime.fromisoformat(record['next_review_at'].replace('Z', '+00:00')) <= current):
        return None
    model = record.get('valuation_model')
    if not model: return None
    try:
        path = (root / model['relative_path']).resolve()
        if not path.is_relative_to(root.resolve()) or sha256_file(path) != model['sha256']:
            return None
        bundle = read_json(path)
        receipts, _ = validate_and_materialize_bundle(bundle, packet_as_of=record['reviewed_at'],
            active_tickers={record['ticker']}, project_root=root)
        if len(receipts) != 1 or not receipts[0]['sufficiency']['scenario_sufficient']: return None
        original = next(r for r in bundle['records'] if r['ticker'] == record['ticker'])
        cases = {'bear': Decimal(original['inputs']['downside_price_assumption']['value']),
                 'base': Decimal(original['inputs']['target_price_assumption']['value'])}
        method, horizon = '', ''
        for source in original['sources']:
            if source['source_type'] != 'human_valuation_scenario': continue
            verified, _ = _verified_source(source, ticker=record['ticker'],
                packet_as_of=datetime.fromisoformat(record['reviewed_at'].replace('Z', '+00:00')), project_root=root)
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
        if any(not v.is_finite() or v < 0 for v in cases.values()): return None
        if cases['bear'] >= cases['base'] or ('bull' in cases and cases['base'] > cases['bull']): return None
        price = Decimal(str(quote.get('last_price', '')))
        if not price.is_finite() or price <= 0 or quote.get('data_quality_label') != 'ok': return None
        rr = (cases['base'] - price) / (price - cases['bear']) if price > cases['bear'] else None
        ceiling = (cases['base'] + minimum_reward_to_risk * cases['bear']) / (1 + minimum_reward_to_risk)
        news = view.get('news_review', {})
        pending = []
        if not news.get('coverage_complete'): pending.append('configured_issuer_news_coverage_incomplete')
        if news.get('status') != 'current': pending.append('issuer_news_impact_review_incomplete')
        if not admission: pending.append('company_model_not_admitted')
        conditions = []
        for key in ('business_case', 'valuation', 'portfolio_role_and_alternatives'):
            conditions.extend(record.get(key, {}).get('unresolved', []))
        return {
            'schema_version': 'equity_company_case_presentation_v1', 'ticker': record['ticker'],
            'review_id': record['review_id'], 'review_version': record['version'],
            'reviewed_at': record['reviewed_at'], 'next_review_at': record['next_review_at'],
            'conclusion': view.get('conclusion') or record['conclusion'],
            'business_case_status': view.get('business_case_status'),
            'method': method or (admission or {}).get('method', model['assumptions_reason']),
            'horizon': horizon or (admission or {}).get('horizon', 'Reviewed source-bound scenario horizon'),
            'countercase': model['countercase_reason'], 'review_conditions': conditions,
            'reference_price': float(price), 'reference_close': quote['market_session_date'],
            'live_quote': False, 'scenario_prices': {k: float(v) for k, v in cases.items()},
            'base_upside_pct': float((cases['base'] / price - 1) * 100),
            'scenario_reward_to_risk': float(rr) if rr is not None else None,
            'minimum_reward_to_risk': float(minimum_reward_to_risk),
            'valuation_only_review_ceiling': float(ceiling), 'review_ceiling_is_order_price': False,
            'model_admission_status': 'admitted_current' if admission else 'research_only_pending_admission',
            'pending_requirements': pending, 'model_relative_path': model['relative_path'],
            'model_sha256': model['sha256'], 'automatic_action_allowed': False,
        }
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation, StopIteration):
        return None


def case_lines(case: dict, *, shares: int) -> list[str]:
    prices = case['scenario_prices']
    return [
        case['conclusion'],
        f"当前新增订单股数：{shares} 股。研究判断与完整交易草案分别校验。",
        f"参考收盘：{case['reference_close']} · ${case['reference_price']:.2f} · 非实时。",
        '悲观／基准／乐观情景：' + ' / '.join(f"${prices[k]:.2f}" if k in prices else '未核验' for k in ('bear', 'base', 'bull')) + '；分析假设，不是保证价格。',
        f"基准上涨空间 {case['base_upside_pct']:.2f}%；情景收益／风险比 " + (f"{case['scenario_reward_to_risk']:.2f}" if case['scenario_reward_to_risk'] is not None else '未核验') + f"，现行最低要求 {case['minimum_reward_to_risk']:.2f}。",
        f"估值复核参考上限 ${case['valuation_only_review_ceiling']:.2f}，不是买入限价或订单。",
        '方法：' + case['method'], '期限：' + case['horizon'],
        '反方证据：' + case['countercase'],
        '下一次复核：' + case['next_review_at'] + '；重大公司证据或价格变化时提前复核。',
        *('复核条件：' + text for text in case['review_conditions']),
        ('模型状态：已准入当前生产估值。' if case['model_admission_status'] == 'admitted_current' else '模型状态：已记录研究模型，生产估值准入待完成。') +
        (' 待完成：' + '、'.join({'configured_issuer_news_coverage_incomplete':'官方新闻覆盖',
            'issuer_news_impact_review_incomplete':'新闻影响复核', 'company_model_not_admitted':'公司模型准入'}.get(v,v)
            for v in case['pending_requirements']) if case['pending_requirements'] else ''),
    ]
