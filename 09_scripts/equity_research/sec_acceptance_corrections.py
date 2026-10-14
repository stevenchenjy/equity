"""Source-bound corrections for conflicting SEC acceptance clocks.

The immutable submissions index and extensions are observations, not a source
of permission to guess a timezone. A correction needs an exact accession in a
retained current submissions response AND agreement between the official SGML
header and filing index. The header/index clock is EDGAR Eastern time. Original
records and the time at which this independent proof became known are retained.
Only current readers use this separately versioned layer; frozen replay inputs
are never rewritten or automatically opted into it.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from daily_common import atomic_write_json, canonical_sha256, read_json
from sec_acceptance import (AcceptanceReconciliationError, IDENTITY_FIELDS,
    make_acceptance_record, normalize_acceptance_timestamp,
    reconcile_current_acceptance_records, validate_acceptance_record)

CORRECTIONS_REL = Path('03_source_data/equity_research/sec_acceptance_corrections')
PROOFS_REL = Path('02_filings/sec_acceptance_proofs')
SCHEMA = 'sec_acceptance_header_correction_v1'
EASTERN = ZoneInfo('America/New_York')
MAX_BYTES = 25 * 1024 * 1024


class CorrectionError(AcceptanceReconciliationError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CorrectionError('SEC acceptance correction ' + message)


def _time(value: Any) -> datetime:
    normalized = normalize_acceptance_timestamp(value)
    _require(bool(normalized), 'timestamp missing')
    return datetime.fromisoformat(normalized)


def _raw(source: dict[str, Any], root: Path, url: str) -> bytes:
    _require(set(source) == {'url', 'raw_path', 'raw_sha256', 'observed_at'}, 'source fields differ')
    _require(source['url'] == url, 'source URL differs from exact SEC accession')
    relative = Path(source['raw_path'])
    _require(not relative.is_absolute() and relative.is_relative_to(PROOFS_REL)
             and '..' not in relative.parts, 'proof path invalid')
    path = root / relative
    _require(path.resolve().is_relative_to((root / PROOFS_REL).resolve()), 'proof escaped root')
    raw = path.read_bytes()
    _require(0 < len(raw) <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == source['raw_sha256'],
             'raw proof hash or size differs')
    _time(source['observed_at'])
    return raw


def _unique(pattern: str, text: str, label: str) -> str:
    matches = re.findall(pattern, text, flags=re.M | re.I)
    _require(len(matches) == 1, label + ' missing or ambiguous')
    return matches[0].strip()


def _parsed_proof(*, historical: dict[str, str], observed: dict[str, str],
                  form: str, entity_name: str, sources: dict[str, Any], root: Path) -> dict[str, str]:
    old, current = map(validate_acceptance_record, (historical, observed))
    _require(all(old[k] == current[k] for k in IDENTITY_FIELDS), 'non-time identity differs')
    _require(set(sources) == {'submissions', 'header', 'index'}, 'proof families differ')
    cik, accession = current['cik'], current['accession_number']
    prefix = f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/{accession}'
    sub = json.loads(_raw(sources['submissions'], root, current['source_url']))
    _require(str(sub.get('cik', '')).lstrip('0') == cik
             and current['ticker'] in sub.get('tickers', [])
             and sub.get('name', '').strip() == entity_name, 'submissions issuer identity differs')
    recent = sub.get('filings', {}).get('recent', {})
    indices = [i for i, a in enumerate(recent.get('accessionNumber', [])) if a == accession]
    _require(len(indices) == 1, 'submissions accession missing or duplicated')
    i = indices[0]
    def at(key: str) -> str:
        rows = recent.get(key, [])
        _require(isinstance(rows, list) and i < len(rows), 'submissions array malformed')
        return str(rows[i])
    _require(at('form') == form and at('filingDate') == current['filing_date']
             and normalize_acceptance_timestamp(at('acceptanceDateTime')) == current['accepted_at'],
             'submissions observation differs')
    header_page = _raw(sources['header'], root, prefix + '-index-headers.html').decode('utf-8')
    # The official headers endpoint also has a machine-tag HTML comment. Parse
    # its single human-readable PRE representation, not both copies at once.
    header = html.unescape(_unique(r'(?s)<PRE>(.*?)</PRE>', header_page, 'header PRE'))
    # Only the SEC header, never a document body containing quoted old metadata.
    header = header.split('</SEC-HEADER>', 1)[0]
    _require('<SEC-HEADER>' in header, 'SGML header absent')
    raw_clock = _unique(r'<ACCEPTANCE-DATETIME>(\d{14})\s*', header, 'SGML accepted clock')
    _require(_unique(r'^ACCESSION NUMBER:\s*(\S+)\s*$', header, 'SGML accession') == accession,
             'SGML accession differs')
    _require(_unique(r'^CONFORMED SUBMISSION TYPE:\s*(\S+)\s*$', header, 'SGML form') == form,
             'SGML form differs')
    _require(_unique(r'^FILED AS OF DATE:\s*(\d{8})\s*$', header, 'SGML filed date')
             == current['filing_date'].replace('-', ''), 'SGML filed date differs')
    _require('FILER:' in header, 'SGML filer absent')
    filer = header.split('FILER:', 1)[1].split('FILING VALUES:', 1)[0]
    _require(str(int(_unique(r'^\s*CENTRAL INDEX KEY:\s*(\d+)\s*$', filer, 'SGML filer CIK'))) == cik,
             'SGML filer identity differs')
    # SEC spelling/punctuation may vary; CIK is exact, names compared as words.
    name = _unique(r'^\s*COMPANY CONFORMED NAME:\s*(.+)$', filer, 'SGML issuer name')
    words = lambda value: re.sub(r'[^A-Z0-9]', '', value.upper())
    _require(words(name) == words(entity_name), 'SGML issuer name differs')
    index = _raw(sources['index'], root, prefix + '-index.html').decode('utf-8')
    index_clock = _unique(r'<div class="infoHead">Accepted</div>\s*<div class="info">([^<]+)</div>',
                          index, 'index accepted clock')
    _require(datetime.strptime(index_clock, '%Y-%m-%d %H:%M:%S').strftime('%Y%m%d%H%M%S') == raw_clock,
             'independent archive clocks disagree')
    _require(f'Form {form}</strong>' in index and accession in index
             and f'CIK={int(cik):010d}' in index, 'index identity differs')
    filed = _unique(r'<div class="infoHead">Filing Date</div>\s*<div class="info">([^<]+)</div>', index, 'index filed date')
    _require(filed == current['filing_date'], 'index filed date differs')
    wall = datetime.strptime(raw_clock, '%Y%m%d%H%M%S')
    instant = wall.replace(tzinfo=EASTERN)
    # Ambiguous or nonexistent DST clocks have no automatic admission path.
    _require(instant.utcoffset() == wall.replace(tzinfo=EASTERN, fold=1).utcoffset()
             and instant.astimezone(timezone.utc).astimezone(EASTERN).replace(tzinfo=None) == wall,
             'EDGAR clock is DST ambiguous or nonexistent')
    canonical = instant.astimezone(timezone.utc).isoformat(timespec='milliseconds')
    corrected = make_acceptance_record(**{k: current[k] for k in IDENTITY_FIELDS}, accepted_at=canonical)
    return corrected


def make_correction(*, historical: dict[str, str], observed: dict[str, str], form: str,
                    entity_name: str, sources: dict[str, Any], root: Path,
                    admitted_at: str) -> dict[str, Any]:
    corrected = _parsed_proof(historical=historical, observed=observed, form=form,
                              entity_name=entity_name, sources=sources, root=root)
    admitted = _time(admitted_at)
    _require(admitted <= datetime.now(timezone.utc), 'admission is in the future')
    _require(all(_time(source['observed_at']) <= admitted for source in sources.values()),
             'proof observed in the future')
    _require(_time(observed['accepted_at']) <= admitted
             and _time(corrected['accepted_at']) <= min(_time(s['observed_at']) for s in sources.values()),
             'accepted timestamp after observation/admission')
    unsigned = {'original': historical, 'observed_submissions': observed,
        'corrected': corrected, 'form': form, 'entity_name': entity_name,
        'sources': sources, 'admitted_at': normalize_acceptance_timestamp(admitted_at),
        'decision': 'independent_edgar_header_and_index_clock',
        'clock_basis': 'America/New_York', 'historical_observations_unchanged': True}
    return {**unsigned, 'correction_sha256': canonical_sha256(unsigned)}


def load_corrections(root: Path, historical_records: list[dict[str, Any]],
                     *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    historical = {r['accession_number']: validate_acceptance_record({k:v for k,v in r.items()
                   if k in {'accession_number','ticker','cik','filing_date','accepted_at','source_url','record_sha256'}})
                  for r in historical_records}
    paths = list((root / CORRECTIONS_REL).glob('sec_acceptance_correction_v*.json'))
    paths.sort(key=lambda p: int(_unique(r'sec_acceptance_correction_v([1-9]\d*)\.json', p.name, 'version')))
    previous = ''
    records: list[dict[str, Any]] = []
    validated: list[dict[str, Any]] = []
    for version, path in enumerate(paths, 1):
        artifact = read_json(path)
        _require(set(artifact) == {'schema_version','version','previous_artifact_sha256','records','artifact_sha256'}, 'artifact fields differ')
        unsigned = {k:v for k,v in artifact.items() if k != 'artifact_sha256'}
        _require(artifact['schema_version'] == SCHEMA and artifact['version'] == version
                 and path.name == f'sec_acceptance_correction_v{version}.json'
                 and artifact['previous_artifact_sha256'] == previous
                 and artifact['artifact_sha256'] == canonical_sha256(unsigned), 'artifact chain/hash differs')
        _require(isinstance(artifact['records'], list) and bool(artifact['records']), 'empty correction artifact')
        for correction in artifact['records']:
            _require(set(correction) == {'original','observed_submissions','corrected','form','entity_name','sources','admitted_at',
                'decision','clock_basis','historical_observations_unchanged','correction_sha256'}, 'record fields differ')
            original = historical.get(correction['original']['accession_number'])
            _require(original == correction['original'], 'original immutable binding differs')
            rebuilt = make_correction(historical=original, observed=correction['observed_submissions'], form=correction['form'],
                entity_name=correction['entity_name'], sources=correction['sources'], root=root, admitted_at=correction['admitted_at'])
            _require(rebuilt == correction, 'record hash/content differs')
            same = [r for r in validated if r['original']['accession_number'] == original['accession_number']]
            _require(all(r['corrected'] == correction['corrected'] for r in same), 'authoritative archive timestamp changed')
            _require(not any(r['correction_sha256'] == correction['correction_sha256'] for r in validated), 'duplicate correction')
            validated.append(correction)
            if as_of is None or _time(correction['admitted_at']) <= as_of:
                records.append(correction)
        previous = artifact['artifact_sha256']
    return records


def correction_for(record: dict[str, Any], corrections: list[dict[str, Any]]) -> dict[str, Any] | None:
    row = validate_acceptance_record({k:v for k,v in record.items() if k in {
        'accession_number','ticker','cik','filing_date','accepted_at','source_url','record_sha256'}})
    matches = [c for c in corrections if c['original']['accession_number'] == row['accession_number']]
    for correction in reversed(matches):
        if row in [correction['original'], correction['observed_submissions'], correction['corrected']]:
            return correction
    _require(not matches, 'current submission changed beyond admitted proof')
    return None


def corrected_record(record: dict[str, Any], corrections: list[dict[str, Any]]) -> dict[str, Any]:
    correction = correction_for(record, corrections)
    if not correction:
        return record
    # Do not carry an extension_record_sha256 onto a derived record whose core
    # clock changed. The original extension remains independently validated in
    # the historical map; current consumers need only its issuer/form identity.
    return {**correction['corrected'], **{k:record[k] for k in ('form','entity_name') if k in record}}


def current_corrections(root: Path, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    """Optional current layer, with full immutable-index/extension validation."""
    if not list((root / CORRECTIONS_REL).glob('sec_acceptance_correction_v*.json')):
        return []
    from sec_acceptance import load_immutable_acceptance_index
    from sec_acceptance_extensions import load_extension_artifacts, extension_acceptance_records, raw_file_sha256
    path = root / '03_source_data/equity_research/sec_submission_acceptance_index.json'
    historical = load_immutable_acceptance_index(path)['records']
    extensions = load_extension_artifacts(historical_index_sha256=raw_file_sha256(path),
        directory=root / '03_source_data/equity_research/sec_acceptance_extensions')
    return load_corrections(root, [*historical, *extension_acceptance_records(extensions)], as_of=as_of)


def correct_filings(filings: list[dict[str, str]], *, ticker: str, cik: int,
                    root: Path, as_of: datetime | None = None) -> list[dict[str, str]]:
    corrections = current_corrections(root, as_of=as_of)
    if not corrections:
        return filings
    result = []
    for filing in filings:
        record = make_acceptance_record(ticker=ticker, cik=cik, accession_number=filing['accession_number'],
            filing_date=filing['filing_date'], accepted_at=filing['accepted_at'],
            source_url=f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
        correction = correction_for(record, corrections)
        if correction:
            _require(filing['form'] == correction['form'], 'current filing form differs')
            result.append({**filing, 'accepted_at': correction['corrected']['accepted_at']})
        else:
            result.append(filing)
    return result


def retained_receipt_clock_valid(*, receipt: dict[str, Any], canonical_accepted_at: str,
                                 ticker: str, cik: int, accession: str,
                                 root: Path, as_of: datetime) -> bool:
    """Validate an unchanged old source receipt, never admit a new false clock."""
    try:
        old, canonical, fetched = map(_time, (receipt.get('accepted_at'), canonical_accepted_at, receipt.get('fetched_at')))
        if not canonical <= fetched <= as_of:
            return False
        if old == canonical:
            return True
        proofs = current_corrections(root, as_of=as_of)
        for proof in reversed(proofs):
            corrected = proof['corrected']
            if (corrected['ticker'] == ticker and int(corrected['cik']) == cik
                    and corrected['accession_number'] == accession and _time(corrected['accepted_at']) == canonical
                    and fetched < _time(proof['admitted_at'])
                    and old in {_time(proof['original']['accepted_at']), _time(proof['observed_submissions']['accepted_at'])}):
                return True
        return False
    except (ValueError, OSError, KeyError, TypeError):
        return False


def reconcile_with_corrections(*, historical_records: list[dict[str, Any]], current_records: list[dict[str, Any]],
                               reconciled_at: str, corrections: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_accession = {r['accession_number']: r for r in historical_records}
    _require(len(by_accession) == len(historical_records), 'historical accession duplicated')
    _require(len({r['accession_number'] for r in current_records}) == len(current_records), 'current accession duplicated')
    reconcile_current_acceptance_records(historical_records=historical_records,
        current_records=[], reconciled_at=reconciled_at)
    uncorrected = []
    for row in current_records:
        correction = correction_for(row, corrections)
        if correction:
            original = by_accession.get(row['accession_number'])
            _require(original == correction['original'] and row == correction['corrected'], 'current corrected record differs')
            _require(_time(correction['admitted_at']) <= _time(reconciled_at), 'correction after reconciliation')
        else:
            uncorrected.append(row)
    return reconcile_current_acceptance_records(historical_records=historical_records,
        current_records=uncorrected, reconciled_at=reconciled_at)


def write_corrections(root: Path, new_records: list[dict[str, Any]], historical_records: list[dict[str, Any]],
                      *, staged_roots: dict[str, Path] | None = None) -> None:
    # Caller holds the existing SEC extension lock. Verify all prior proof bytes
    # before publishing a new chain member, and no-op exact retries.
    existing = load_corrections(root, historical_records)
    by_hash = {r['correction_sha256']: r for r in existing}
    for record in new_records:
        prior = by_hash.get(record['correction_sha256'])
        _require(prior is None or prior == record, 'retry conflicts with retained correction')
    hashes = set(by_hash)
    new_records = [r for r in new_records if r['correction_sha256'] not in hashes]
    if not new_records:
        return
    historical = {r['accession_number']: r for r in historical_records}
    seen = set(hashes)
    for correction in new_records:
        _require(correction['original'] == historical.get(correction['original']['accession_number']), 'original immutable binding differs')
        rebuilt = make_correction(historical=correction['original'], observed=correction['observed_submissions'],
            form=correction['form'], entity_name=correction['entity_name'], sources=correction['sources'],
            root=(staged_roots or {}).get(correction['correction_sha256'], root), admitted_at=correction['admitted_at'])
        _require(rebuilt == correction and correction['correction_sha256'] not in seen, 'proposed correction differs or duplicated')
        _require(all(r['corrected'] == correction['corrected'] for r in existing
            if r['original']['accession_number'] == correction['original']['accession_number']), 'authoritative archive timestamp changed')
        seen.add(correction['correction_sha256'])
    # Failed issuer attempts keep their evidence in a private staging namespace.
    # Only a fully validated/admitted batch can publish public active proofs.
    for correction in new_records:
        stage = (staged_roots or {}).get(correction['correction_sha256'])
        if stage is None:
            continue
        for source in correction['sources'].values():
            receipt = retain_proof((stage / source['raw_path']).read_bytes(), url=source['url'],
                observed_at=source['observed_at'], root=root)
            _require(receipt == source, 'staged proof differs at publication')
    paths = list((root / CORRECTIONS_REL).glob('sec_acceptance_correction_v*.json'))
    previous = read_json(root / CORRECTIONS_REL / f'sec_acceptance_correction_v{len(paths)}.json')['artifact_sha256'] if paths else ''
    unsigned = {'schema_version': SCHEMA, 'version': len(paths)+1,
        'previous_artifact_sha256': previous, 'records': new_records}
    path = root / CORRECTIONS_REL / f'sec_acceptance_correction_v{len(paths)+1}.json'
    _require(not path.exists(), 'version already exists')
    atomic_write_json(path, {**unsigned, 'artifact_sha256': canonical_sha256(unsigned)})
    load_corrections(root, historical_records)


def retain_proof(raw: bytes, *, url: str, observed_at: str, root: Path) -> dict[str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    path = root / PROOFS_REL / f'{digest}.raw'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _require(path.read_bytes() == raw, 'content-addressed proof differs')
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'url': url, 'raw_path': path.relative_to(root).as_posix(), 'raw_sha256': digest,
            'observed_at': normalize_acceptance_timestamp(observed_at)}


def fetch_correction(*, historical: dict[str, str], observed: dict[str, str], form: str,
                     entity_name: str, submissions_receipt: dict[str, Any], user_agent: str,
                     root: Path, observed_at: str) -> tuple[dict[str, Any], Path]:
    # The caller explicitly enabled public SEC collection. Reuse exact current
    # response bytes; do not refetch or serialize a conveniently edited JSON.
    raw_path = root / submissions_receipt['raw_path']
    raw = raw_path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == submissions_receipt['raw_sha256'], 'current raw response differs')
    staging_parent = root / '02_filings/sec_acceptance_staging.local'
    staging_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='proof-', dir=staging_parent))
    sources = {'submissions': retain_proof(raw, url=observed['source_url'],
               observed_at=submissions_receipt['retrieved_at'], root=stage)}
    accession, cik = observed['accession_number'], observed['cik']
    prefix = f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/{accession}'
    for kind, suffix in [('header', '-index-headers.html'), ('index', '-index.html')]:
        url = prefix + suffix
        request = urllib.request.Request(url, headers={'User-Agent': user_agent, 'Accept-Encoding': 'identity'})
        with urllib.request.urlopen(request, timeout=20) as response:
            _require(response.geturl() == url, 'redirected proof URL')
            raw = response.read(MAX_BYTES+1)
        _require(0 < len(raw) <= MAX_BYTES, 'archive proof size invalid')
        sources[kind] = retain_proof(raw, url=url,
            observed_at=datetime.now(timezone.utc).isoformat(), root=stage)
    correction = make_correction(historical=historical, observed=observed, form=form, entity_name=entity_name,
        sources=sources, root=stage, admitted_at=datetime.now(timezone.utc).isoformat())
    return correction, stage
