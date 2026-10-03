"""Run an explicitly registered experiment from immutable, verified Git bytes.

Live production helpers and report writers are not experiment identity. Capture
and evaluation use the same registered implementation, including its import
closure. A private staged run must succeed before any ledger append is admitted.
"""
from __future__ import annotations

import ast
from contextlib import ExitStack, contextmanager
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from uuid import uuid4

from daily_common import ExclusiveFileLock, atomic_write_json, atomic_write_text, canonical_sha256
from archived_momentum import DRIVER as OUTCOME_DRIVER
from momentum_price_coverage import PATH as OUTCOME_PRICES, load_outcome_prices

CONFIG = Path('01_policies/momentum_implementation_archives.json')
CODE_REPOSITORY = Path(__file__).resolve().parents[2]
HEX = re.compile(r'[0-9a-f]{64}')
DRIVER = r'''
import json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / '09_scripts/equity_research'))
import momentum_experiment as frozen
request=json.load(sys.stdin)
entry=getattr(frozen,request['entrypoint'])
report=entry(Path(request['root']), datetime.fromisoformat(request['current']), Path(request['output']))
print(json.dumps(report))
'''


def _execute_frozen(snapshot, request):
    process = subprocess.run([sys.executable, '-I', '-c', DRIVER, str(snapshot)],
                             input=json.dumps(request), text=True, capture_output=True,
                             timeout=180, check=True)
    return json.loads(process.stdout)


def _execute_outcomes(snapshot, request):
    process = subprocess.run([sys.executable, '-I', '-c', OUTCOME_DRIVER, str(snapshot)],
                             input=json.dumps(request), text=True, capture_output=True,
                             timeout=45, check=True)
    return json.loads(process.stdout)


def _supplement_outcomes(*, raw, records, snapshots, bindings, current, canonical_tickers, ledger):
    from momentum_experiment import append_chained
    completed = {r['observation_id'] for r in records if r['kind'] == 'outcome'}
    pending = [r for r in records if r['kind'] == 'observation'
               and r['observation_id'] not in completed and r['ticker'] not in canonical_tickers]
    coverage = {'required_tickers': sorted({r['ticker'] for r in pending}),
                'new_outcomes': 0, 'missing': {}, 'deferred': [],
                'canonical_effect': False, 'capture_allowed': False}
    if not pending:
        coverage['status'] = 'not_required'
        return coverage
    if raw is None:
        coverage.update(status='missing', missing={t: 'validated_current_forward_bars_required'
                                                  for t in coverage['required_tickers']})
        return coverage
    receipt, is_current = load_outcome_prices(raw, current)
    if not is_current:
        coverage.update(status='stale', missing={t: 'validated_current_forward_bars_required'
                                                for t in coverage['required_tickers']})
        return coverage
    coverage['status'] = 'current_outcomes_only'
    coverage['input_sha256'] = hashlib.sha256(raw).hexdigest()
    coverage['missing'] = {t: receipt['missing'].get(t, 'validated_current_forward_bars_required')
                           for t in coverage['required_tickers'] if t not in receipt['history']['tickers']}
    admitted = set(receipt['observation_ids'])
    for version in sorted({r['experiment_version'] for r in pending}):
        observations = [r for r in pending if r['experiment_version'] == version
                        and r['observation_id'] in admitted
                        and r['ticker'] in receipt['history']['tickers']]
        if not observations:
            continue
        request = {'observations': observations, 'market': receipt['market'],
                   'history': receipt['history'], 'current': current.isoformat(),
                   'commit': bindings[version]['git_commit'],
                   'inputs': {'market_sha256': receipt['market_sha256'],
                              'history_sha256': canonical_sha256(receipt['history']),
                              'supplement_sha256': coverage['input_sha256'],
                              'supplement_path': str(OUTCOME_PRICES),
                              'snapshot_format': receipt['snapshot_format'],
                              'scope': receipt['scope']}}
        try:
            response = _execute_outcomes(snapshots[version], request)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise ValueError('frozen_experiment_evaluation_failed') from exc
        if response.get('deferred'):
            coverage['deferred'].append({'experiment_version': version, **response['deferred']})
        returned = response['outcomes']
        expected = {r['observation_id'] for r in observations}
        identities = [r.get('observation_id') for r in returned]
        if (len(set(identities)) != len(identities) or not set(identities) <= expected
                or any(r.get('kind') != 'outcome' or r.get('experiment_version') != version
                       or r.get('automatic_action_allowed') is not False for r in returned)):
            raise ValueError('frozen_experiment_report_mismatch')
        for row in returned:
            append_chained(ledger, records, row)
            coverage['new_outcomes'] += 1
    return coverage


def _module_imports(nodes):
    """Import-time dependencies; function-local imports stay outside the entry API."""
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Import):
            yield from (a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split('.')[0]
        yield from _module_imports(ast.iter_child_nodes(node))


def load_registry(root):
    registry = json.loads((root / CONFIG).read_bytes())
    if registry.get('schema_version') != 'equity_frozen_implementation_archives_v1':
        raise ValueError('archive_config_invalid')
    archives = registry.get('archives')
    if not isinstance(archives, list) or not archives:
        raise ValueError('archive_config_invalid')
    versions = [a.get('experiment_version') for a in archives]
    if (any(not isinstance(v, str) or not v for v in versions)
            or len(set(versions)) != len(versions)):
        raise ValueError('archive_config_duplicate_or_invalid_version')
    return {a['experiment_version']: a for a in archives}


@contextmanager
def verified_snapshot(archive, repository=CODE_REPOSITORY):
    commit, files = archive.get('git_commit'), archive.get('runtime_files')
    legacy = archive.get('implementation_files')
    if (not isinstance(commit, str) or re.fullmatch(r'[0-9a-f]{40}', commit) is None
            or not isinstance(files, dict) or not files
            or canonical_sha256(files) != archive.get('runtime_sha256')
            or not isinstance(legacy, dict) or not legacy
            or any(files.get('09_scripts/equity_research/' + name) != digest
                   for name, digest in legacy.items())):
        raise ValueError('archive_implementation_mismatch')
    for relative, digest in files.items():
        path = Path(relative)
        if (path.is_absolute() or '..' in path.parts or not HEX.fullmatch(str(digest))
                or path.suffix not in {'.py', '.json'} or 'tests' in path.parts
                or not relative.startswith(('09_scripts/equity_research/', '01_policies/'))):
            raise ValueError('archive_config_invalid')
    try:
        content = subprocess.check_output(['git', 'archive', commit, *sorted(files)],
                                         cwd=repository, stderr=subprocess.DEVNULL, timeout=20)
        tree = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', commit,
                                        '09_scripts/equity_research'], cwd=repository,
                                       text=True, stderr=subprocess.DEVNULL, timeout=20).splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('archive_evaluation_failed') from exc
    local_modules = {Path(p).stem: p for p in tree if p.endswith('.py') and '/tests/' not in p}
    with tempfile.TemporaryDirectory(prefix='equity-frozen-runtime-') as directory:
        target = Path(directory)
        try:
            with tarfile.open(fileobj=io.BytesIO(content)) as bundle:
                members = {member.name: member for member in bundle.getmembers() if member.isfile()}
                if set(members) != set(files):
                    raise ValueError('archive_implementation_mismatch')
                for relative, digest in files.items():
                    raw = bundle.extractfile(members[relative]).read()
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise ValueError('archive_implementation_mismatch')
                    path = target / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
            required = {'momentum_experiment'}
            if 'archived_momentum.py' in legacy:
                required.add('archived_momentum')  # frozen _run's deliberate local import
            visited = set()
            while required:
                module = required.pop()
                if module in visited:
                    continue
                visited.add(module)
                relative = local_modules.get(module)
                if relative not in files:
                    raise ValueError('archive_runtime_dependency_missing')
                required.update(set(_module_imports(ast.parse((target / relative).read_bytes()).body))
                                & set(local_modules) - visited)
            for relative in ['01_policies/momentum_experiment.json',
                             *(['01_policies/equity_display_names.json'] if 'equity_naming' in visited else [])]:
                if relative not in files:
                    raise ValueError('archive_runtime_dependency_missing')
            policy = json.loads((target / '01_policies/momentum_experiment.json').read_bytes())
            if policy.get('version') != archive['experiment_version']:
                raise ValueError('archive_policy_mismatch')
            entrypoint = archive.get('entrypoint', '_run')
            if entrypoint not in {'_run', '_run_engine'}:
                raise ValueError('archive_entrypoint_invalid')
            functions = {n.name: n for n in ast.parse(
                (target / '09_scripts/equity_research/momentum_experiment.py').read_bytes()).body
                         if isinstance(n, ast.FunctionDef)}
            function = functions.get(entrypoint)
            if function is None or any(isinstance(n, ast.ImportFrom)
                                      and n.module == 'frozen_momentum_runtime'
                                      for n in ast.walk(function)):
                raise ValueError('archive_entrypoint_is_dispatcher')
        except tarfile.TarError as exc:
            raise ValueError('archive_evaluation_failed') from exc
        yield target, policy


def run_frozen(root, current, output, *, validate_chain, source_paths):
    """Validate all version bindings, stage a frozen run, then publish its append."""
    root, output = root.resolve(), output.resolve()
    tracked = [*source_paths, CONFIG]
    if (root / OUTCOME_PRICES).exists():
        tracked.append(OUTCOME_PRICES)
    originals = {path: (root / path).read_bytes() for path in tracked}
    dispatcher_sources = {name: (Path(__file__).parent / name).read_bytes()
                          for name in ('frozen_momentum_runtime.py', 'momentum_price_coverage.py',
                                       'archived_momentum.py', 'momentum_experiment.py', 'daily_common.py')}
    registry = load_registry(root)
    policy = json.loads(originals[Path('01_policies/momentum_experiment.json')])
    if policy['version'] not in registry:
        raise ValueError('experiment_version_unregistered')
    output.mkdir(parents=True, exist_ok=True)
    with ExclusiveFileLock(output / 'ledger.lock'), ExitStack() as stack:
        ledger = output / 'ledger.jsonl'
        before = ledger.read_bytes() if ledger.exists() else b''
        records = [json.loads(line) for line in before.splitlines() if line.strip()]
        validate_chain(records, current)
        versions = {r['experiment_version'] for r in records} | {policy['version']}
        if not versions <= set(registry):
            raise ValueError('experiment_version_unregistered')
        snapshots, bindings = {}, {}
        for version in sorted(versions):
            archive = registry[version]
            snapshot, frozen_policy = stack.enter_context(verified_snapshot(archive))
            snapshots[version] = snapshot
            binding = {key: archive[key] for key in ('git_commit', 'implementation_files',
                                                   'runtime_files', 'runtime_sha256')}
            binding['entrypoint'] = archive.get('entrypoint', '_run')
            binding['implementation_sha256'] = canonical_sha256(archive['implementation_files'])
            binding['policy_sha256'] = canonical_sha256(frozen_policy)
            bindings[version] = binding
            for row in records:
                if row['kind'] != 'observation' or row['experiment_version'] != version:
                    continue
                if (row['inputs'].get('implementation_files') != archive['implementation_files']
                        or row['inputs'].get('implementation_sha256') != binding['implementation_sha256']):
                    raise ValueError('archive_implementation_mismatch')
                if row['policy'] != frozen_policy:
                    raise ValueError('archive_policy_mismatch')
        if canonical_sha256(policy) != bindings[policy['version']]['policy_sha256']:
            raise ValueError('experiment_policy_changed_without_new_version')
        with tempfile.TemporaryDirectory(prefix='equity-momentum-stage-') as directory:
            stage = Path(directory)
            (stage / 'ledger.jsonl').write_bytes(before)
            request = {'root': str(root), 'current': current.isoformat(), 'output': str(stage),
                       'entrypoint': bindings[policy['version']]['entrypoint']}
            try:
                report = _execute_frozen(snapshots[policy['version']], request)
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                raise ValueError('frozen_experiment_evaluation_failed') from exc
            staged_records = [json.loads(line) for line in (stage / 'ledger.jsonl').read_bytes().splitlines()
                              if line.strip()]
            canonical = {row['ticker'] for row in report['current_observations']}
            coverage = _supplement_outcomes(raw=originals.get(OUTCOME_PRICES), records=staged_records,
                snapshots=snapshots, bindings=bindings, current=current,
                canonical_tickers=canonical, ledger=stage / 'ledger.jsonl')
            if coverage['new_outcomes']:
                try:
                    # Regenerate summary and review data using the same frozen
                    # code, after admitting the supplementary outcomes privately.
                    report = _execute_frozen(snapshots[policy['version']], request)
                except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                    raise ValueError('frozen_experiment_evaluation_failed') from exc
            report['outcome_price_coverage'] = coverage
            proposed = (stage / 'ledger.jsonl').read_bytes()
            result = [json.loads(line) for line in proposed.splitlines() if line.strip()]
            validate_chain(result, current)
            if not proposed.startswith(before) or result[:len(records)] != records:
                raise ValueError('experiment_ledger_hash_chain_invalid_preserve_evidence')
            if (report.get('software_run') != 'passed' or report.get('policy_version') != policy['version']
                    or report.get('ledger_sha256') != hashlib.sha256(proposed).hexdigest()
                    or report.get('automatic_action_allowed') is not False):
                raise ValueError('frozen_experiment_report_mismatch')
            if any((root / path).read_bytes() != raw for path, raw in originals.items()):
                raise ValueError('experiment_input_changed_during_read')
            if (ledger.read_bytes() if ledger.exists() else b'') != before:
                raise ValueError('experiment_input_changed_during_read')
            if any((Path(__file__).parent / name).read_bytes() != raw
                   for name, raw in dispatcher_sources.items()):
                raise ValueError('experiment_input_changed_during_read')
            provenance = {'schema_version': 'equity_frozen_runtime_execution_v1',
                'capture_version': policy['version'], 'bindings': bindings,
                'dispatcher_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'outcome_adapter_sha256': hashlib.sha256((Path(__file__).parent / 'archived_momentum.py').read_bytes()).hexdigest(),
                'python_version': sys.version, 'input_sha256': {
                    str(path): hashlib.sha256(raw).hexdigest() for path, raw in originals.items()},
                'prior_ledger_sha256': hashlib.sha256(before).hexdigest(),
                'result_ledger_sha256': hashlib.sha256(proposed).hexdigest(),
                'new_records': len(result) - len(records), 'recorded_at': current.isoformat(),
                'canonical_effect': False, 'automatic_action_allowed': False}
            artifacts = {}
            for path, raw in originals.items():
                digest = hashlib.sha256(raw).hexdigest()
                relative = Path('input_history') / digest
                retained = output / relative
                retained.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if retained.exists():
                    if retained.read_bytes() != raw:
                        raise ValueError('experiment_retained_input_mismatch')
                else:
                    atomic_write_text(retained, raw.decode('utf-8'))
                artifacts[str(path)] = {'sha256': digest, 'relative_to_experiment_output': str(relative)}
            provenance['input_artifacts'] = artifacts
            dispatcher_artifacts = {}
            for name, raw in dispatcher_sources.items():
                digest = hashlib.sha256(raw).hexdigest()
                relative = Path('input_history') / digest
                retained = output / relative
                if retained.exists() and retained.read_bytes() != raw:
                    raise ValueError('experiment_retained_input_mismatch')
                if not retained.exists():
                    atomic_write_text(retained, raw.decode('utf-8'))
                dispatcher_artifacts[name] = {'sha256': digest,
                    'relative_to_experiment_output': str(relative)}
            provenance['dispatcher_source_artifacts'] = dispatcher_artifacts
            receipt = output / 'publication_history' / (uuid4().hex + '.json')
            atomic_write_json(receipt, {'state': 'prepared', **provenance})
            report['frozen_execution'] = provenance
            # Preserve every prior byte. No staged append reaches production if
            # any registered dependency, archive or evaluation failed.
            atomic_write_text(ledger, proposed.decode('utf-8'))
            atomic_write_json(output / 'report.json', report)
            atomic_write_text(output / 'report.md', (stage / 'report.md').read_text()
                              + '\n## Reproducible execution\n\n'
                              + 'Capture and outcomes use registered frozen Git snapshots, including verified import dependencies. Live shared-helper edits do not retune this experiment. '
                              + f"Active version: `{policy['version']}`; frozen commit: `{bindings[policy['version']]['git_commit']}`. "
                              + 'Original observations, failed attempts and version boundaries remain retained.\n'
                              + '\n## Retired ticker outcome coverage\n\n'
                              + f"Status: {coverage['status']}; required outside current capture: {', '.join(coverage['required_tickers']) or 'none'}; new outcomes: {coverage['new_outcomes']}. "
                              + 'Supplementary prices serve retained observations only; no new selections are captured from them. '
                              + (f"Missing evidence: {json.dumps(coverage['missing'], sort_keys=True)}. " if coverage['missing'] else '')
                              + 'Historical publication clocks still apply.\n')
            atomic_write_json(receipt, {'state': 'published', **provenance})
            return report
