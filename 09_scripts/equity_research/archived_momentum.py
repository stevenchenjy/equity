"""Evaluate retained observations with their exact archived implementation.

Only explicitly registered, hash-verified local Git objects can run. The child
uses the old validators and execution model, writes no ledger and makes no
network calls. The caller alone appends returned outcomes under its ledger lock.
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from daily_common import canonical_sha256

CONFIG = Path('01_policies/momentum_implementation_archives.json')
FILES = {'momentum_experiment.py', 'tactical_review.py', 'investment_plans.py', 'daily_common.py'}
DRIVER = r'''
import json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / '09_scripts/equity_research'))
import momentum_experiment as frozen
request=json.load(sys.stdin)
current=datetime.fromisoformat(request['current'])
series,_=frozen.validated_series(request['history'], request['market'], request['inputs']['market_sha256'], current)
policy=json.loads((Path(sys.argv[1]) / frozen.POLICY).read_text())
outcomes=[]
for row in request['observations']:
    if row['policy'] != policy:
        raise ValueError('archive_policy_mismatch')
    outcome=frozen.evaluate(row,series,current)
    if outcome:
        outcome['evaluation_inputs']={**request['inputs'],
            'implementation_sha256':row['inputs']['implementation_sha256'],
            'implementation_files':row['inputs']['implementation_files'],
            'archived_git_commit':request['commit']}
        outcomes.append(outcome)
print(json.dumps(outcomes))
'''


def evaluate_archived(*, root, records, history, market, current, inputs):
    config_path = root / CONFIG
    if not config_path.exists():
        return []  # Unregistered versions remain visibly pending.
    config = json.loads(config_path.read_text())
    if config.get('schema_version') != 'equity_frozen_implementation_archives_v1':
        raise ValueError('archive_config_invalid')
    versions = [a.get('experiment_version') for a in config.get('archives', [])]
    if not all(isinstance(v, str) and v for v in versions) or len(set(versions)) != len(versions):
        raise ValueError('archive_config_duplicate_or_invalid_version')
    completed = {r['observation_id'] for r in records if r['kind'] == 'outcome'}
    result = []
    for archive in config['archives']:
        observations = [r for r in records if r['kind'] == 'observation'
            and r['observation_id'] not in completed
            and r['experiment_version'] == archive['experiment_version']
            and r['inputs'].get('implementation_sha256') != inputs['implementation_sha256']]
        if not observations:
            continue
        commit = archive['git_commit']
        files = archive['implementation_files']
        if not re.fullmatch(r'[0-9a-f]{40}', commit) or set(files) != FILES:
            raise ValueError('archive_config_invalid')
        digest = canonical_sha256(files)
        if any(r['inputs'].get('implementation_files') != files
               or r['inputs'].get('implementation_sha256') != digest for r in observations):
            raise ValueError('archive_implementation_mismatch')
        try:
            content = subprocess.check_output(['git', 'archive', commit,
                '09_scripts/equity_research', '01_policies'],
                cwd=root, stderr=subprocess.DEVNULL, timeout=20)
            with tempfile.TemporaryDirectory(prefix='equity-frozen-study-') as directory:
                target = Path(directory)
                with tarfile.open(fileobj=io.BytesIO(content)) as bundle:
                    for member in bundle.getmembers():
                        rel = Path(member.name)
                        if rel.is_absolute() or '..' in rel.parts or not member.isfile():
                            continue
                        if rel.suffix not in {'.py', '.json'} or 'tests' in rel.parts:
                            continue
                        dest = target / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(bundle.extractfile(member).read())
                actual = {name: hashlib.sha256((target / '09_scripts/equity_research' / name).read_bytes()).hexdigest()
                          for name in FILES}
                if actual != files:
                    raise ValueError('archive_implementation_mismatch')
                request = dict(observations=observations, history=history, market=market,
                    current=current.isoformat(), inputs=inputs, commit=commit)
                process = subprocess.run([sys.executable, '-I', '-c', DRIVER, directory],
                    input=json.dumps(request), text=True, capture_output=True, timeout=45, check=True)
                returned = json.loads(process.stdout)
                expected = {r['observation_id'] for r in observations}
                identities = [r.get('observation_id') for r in returned]
                if (len(set(identities)) != len(identities) or not set(identities) <= expected
                        or any(r.get('kind') != 'outcome' for r in returned)):
                    raise ValueError('archive_outcome_identity_invalid')
                result.extend(returned)
        except (subprocess.SubprocessError, OSError, tarfile.TarError) as exc:
            raise ValueError('archive_evaluation_failed') from exc
    return result
