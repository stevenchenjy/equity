"""Conservative local inline-XBRL fallback when companyfacts lags a report.

Only allowlisted, consolidated standard-taxonomy numeric facts are admitted.
An already cached official report must match its artifact index hash, accession,
CIK and fiscal period. No network, custom-tag guesses or missing-as-zero values.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from daily_common import read_json

NS = {"xbrli": "http://www.xbrl.org/2003/instance", "ix": "http://www.xbrl.org/2013/inlineXBRL"}
MAX_BYTES = 25 * 1024 * 1024
REPORT_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def verified_artifact(root: Path, artifact: dict[str, Any]) -> bytes:
    locator = artifact.get("raw_path", "")
    path = (root / locator).resolve()
    if not locator or Path(locator).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("report_cache_locator_invalid")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != artifact.get("raw_sha256"):
        raise ValueError("report_cache_hash_mismatch")
    return raw


def inline_report_facts(raw: bytes, *, artifact: dict[str, Any], cik: int,
                        filing: dict[str, str], allowed_tags: set[str]) -> tuple[list[dict[str, Any]], str]:
    if len(raw) > MAX_BYTES or re.search(br"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("unsupported_report_xml")
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("unsupported_report_xml") from None
    contexts = {}
    for ctx in tree.findall('.//xbrli:context', NS):
        if any(el.tag.rsplit('}', 1)[-1] in {"segment", "scenario", "explicitMember", "typedMember"} for el in ctx.iter()):
            continue
        identifier = ctx.findtext('xbrli:entity/xbrli:identifier', namespaces=NS)
        if not identifier or not identifier.isdigit() or int(identifier) != cik:
            continue
        period = ctx.find('xbrli:period', NS)
        if period is None:
            continue
        fields = {el.tag.rsplit('}', 1)[-1]: el.text for el in period}
        end = fields.get('endDate') or fields.get('instant')
        try:
            date.fromisoformat(end or '')
            if fields.get('startDate'):
                date.fromisoformat(fields['startDate'])
        except (TypeError, ValueError):
            continue
        contexts[ctx.get('id')] = {"end": end, **({"start": fields['startDate']} if fields.get('startDate') else {})}
    units = {}
    for unit in tree.findall('.//xbrli:unit', NS):
        measures = list(unit)
        if len(measures) == 1 and measures[0].tag == '{'+NS['xbrli']+'}measure':
            text = measures[0].text or ''
            name = text.rsplit(':', 1)[-1]
            if name in {'USD', 'shares'}:
                units[unit.get('id')] = name
    period_ends = set()
    for item in tree.findall('.//ix:nonNumeric', NS):
        if item.get('name') == 'dei:DocumentPeriodEndDate' and item.get('contextRef') in contexts:
            period_ends.add(contexts[item.get('contextRef')]['end'])
    if len(period_ends) != 1:
        raise ValueError("report_period_unverified")
    report_end = period_ends.pop()
    if filing.get('report_date') and report_end != filing['report_date']:
        raise ValueError("report_period_identity_conflict")
    result: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    conflicts: set[tuple[str, str, str, str]] = set()
    for item in tree.findall('.//ix:nonFraction', NS):
        full_tag = item.get('name', '')
        if ':' not in full_tag:
            continue
        taxonomy, tag = full_tag.split(':', 1)
        context = contexts.get(item.get('contextRef'))
        unit = units.get(item.get('unitRef'))
        if taxonomy not in {'us-gaap', 'ifrs-full', 'dei'} or tag not in allowed_tags or not context or not unit:
            continue
        if item.get('continuedAt') or any(k.endswith('}nil') and v == 'true' for k, v in item.attrib.items()):
            continue
        fmt = item.get('format', '').rsplit(':', 1)[-1].lower()
        if fmt not in {'', 'num-dot-decimal', 'numdotdecimal', 'zerodash', 'numdash'}:
            continue
        text = ''.join(item.itertext()).strip().replace(',', '').replace('\u00a0', '')
        if fmt in {'zerodash', 'numdash'} and text in {'—', '–', '-'}:
            text = '0'  # Explicit reported dash-transform, not absent disclosure.
        try:
            scale = int(item.get('scale', '0'))
            if not -12 <= scale <= 12 or item.get('sign', '') not in {'', '-'}:
                continue
            value = Decimal(text) * (Decimal(10) ** scale)
            if item.get('sign') == '-':
                value = -value
            if not value.is_finite() or not math.isfinite(float(value)):
                continue
        except (InvalidOperation, ValueError):
            continue
        key = (taxonomy+':'+tag, unit, context.get('start', ''), context['end'])
        fact = {**context, 'val': float(value), 'form': filing['form'],
                'filed': filing['filing_date'], 'accn': filing['accession_number'],
                '_source_url': artifact['url'], '_raw_path': artifact['raw_path'],
                '_raw_sha256': artifact['raw_sha256'], '_context_id': item.get('contextRef'),
                '_fact_id': item.get('id', ''), '_taxonomy': taxonomy, '_tag': tag, '_unit': unit}
        if key in result and result[key]['val'] != fact['val']:
            conflicts.add(key)
        else:
            result[key] = fact
    return [v for k, v in result.items() if k not in conflicts], report_end


def supplement_cached_latest_report(payload: dict[str, Any], *, ticker: str, cik: int,
        filings: list[dict[str, str]], root: Path, as_of: datetime,
        allowed_tags: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    reports = [r for r in filings if r.get('form') in REPORT_FORMS
               and r.get('accepted_at') and datetime.fromisoformat(r['accepted_at'].replace('Z', '+00:00')) <= as_of]
    if not reports:
        return payload, {'status': 'no_report_metadata'}
    latest = max(reports, key=lambda r: (r.get('report_date', ''), r['accepted_at']))
    end = latest.get('report_date', '')
    raw_latest = max((str(f.get('end', '')) for tax in payload.get('facts', {}).values()
                      for tag in tax.values() for arr in tag.get('units', {}).values() for f in arr
                      if f.get('form') in REPORT_FORMS), default='')
    diagnostic = {'status': 'companyfacts_current', 'raw_latest_period_end': raw_latest,
                  'latest_report_accession': latest['accession_number'], 'latest_report_period_end': end}
    # Missing metadata cannot justify silently treating companyfacts as current.
    if end and raw_latest >= end:
        return payload, diagnostic
    index = read_json(root / '03_source_data/equity_research/sec_filing_artifact_index.json', {})
    artifacts = [a for a in index.get('artifacts', []) if a.get('ticker') == ticker
                 and a.get('accession') == latest['accession_number'] and a.get('form') == latest['form']
                 and str(a.get('cik', '')).lstrip('0') == str(cik)]
    if len(artifacts) != 1:
        return payload, {**diagnostic, 'status': 'latest_report_cache_pending'}
    artifact = artifacts[0]
    expected_prefix = f"https://www.sec.gov/Archives/edgar/data/{cik}/{latest['accession_number'].replace('-', '')}/"
    if artifact.get('url') != expected_prefix + latest['primary_document']:
        return payload, {**diagnostic, 'status': 'report_source_identity_conflict'}
    try:
        facts, end = inline_report_facts(verified_artifact(root, artifact), artifact=artifact,
                                       cik=cik, filing=latest, allowed_tags=allowed_tags)
    except (OSError, ValueError) as exc:
        return payload, {**diagnostic, 'status': str(exc) if isinstance(exc, ValueError) else 'report_cache_unavailable'}
    if not facts:
        return payload, {**diagnostic, 'status': 'report_supported_facts_unavailable'}
    merged = copy.deepcopy(dict(payload))
    for fact in facts:
        arr = merged.setdefault('facts', {}).setdefault(fact['_taxonomy'], {}).setdefault(
            fact['_tag'], {}).setdefault('units', {}).setdefault(fact['_unit'], [])
        # Never replace a different existing fact from the same filing.
        existing = [f for f in arr if f.get('accn') == fact['accn']
                    and f.get('start', '') == fact.get('start', '') and f.get('end') == fact['end']]
        if existing and any(f.get('val') != fact['val'] for f in existing):
            return payload, {**diagnostic, 'status': 'companyfacts_report_value_conflict'}
        if not existing:
            arr.append(fact)
    return merged, {**diagnostic, 'status': 'verified_inline_report_supplement',
                    'latest_report_period_end': end, 'admitted_fact_count': len(facts),
                    'source_url': artifact['url'], 'raw_sha256': artifact['raw_sha256'],
                    'raw_path': artifact['raw_path']}
