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
SUPPORTED_FILE_SETS = (FILES, FILES | {'archived_momentum.py'})
DRIVER = r'''
import json,sys
from datetime import date, datetime
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / '09_scripts/equity_research'))
import momentum_experiment as frozen
from daily_common import last_completed_market_session
request=json.load(sys.stdin)
current=datetime.fromisoformat(request['current'])
policy=json.loads((Path(sys.argv[1]) / frozen.POLICY).read_text())
if any(row['policy'] != policy for row in request['observations']):
    raise ValueError('archive_policy_mismatch')
# Preserve the old implementation's publication clock. A newly admitted REST
# close can be available before this old rule allows that session; defer only
# that specific forward-availability mismatch, without altering time or bars.
required_session=frozen.latest_published_market_session(current)
observed_session=date.fromisoformat(request['history']['market_session'])
if observed_session > required_session and observed_session <= last_completed_market_session(current):
    generated=frozen.aware(request['history']['generated_at'])
    if generated > current or generated < frozen.regular_close(observed_session.isoformat()):
        raise ValueError('experiment_history_timestamp_invalid')
    print(json.dumps({'outcomes': [], 'deferred': {
        'reason': 'historical_publication_rule_not_yet_satisfied',
        'required_market_session': required_session.isoformat(),
        'observed_market_session': observed_session.isoformat()}}))
    sys.exit(0)
series,_=frozen.validated_series(request['history'], request['market'], request['inputs']['market_sha256'], current)
outcomes=[]
for row in request['observations']:
    outcome=frozen.evaluate(row,series,current)
    if outcome:
        outcome['evaluation_inputs']={**request['inputs'],
            'implementation_sha256':row['inputs']['implementation_sha256'],
            'implementation_files':row['inputs']['implementation_files'],
            'archived_git_commit':request['commit']}
        outcomes.append(outcome)
print(json.dumps({'outcomes': outcomes, 'deferred': None}))
'''


def evaluate_archived(*, root, records, history, market, current, inputs, deferred=None):
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
        if not re.fullmatch(r'[0-9a-f]{40}', commit) or set(files) not in SUPPORTED_FILE_SETS:
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
                          for name in files}
                if actual != files:
                    raise ValueError('archive_implementation_mismatch')
                request = dict(observations=observations, history=history, market=market,
                    current=current.isoformat(), inputs=inputs, commit=commit)
                process = subprocess.run([sys.executable, '-I', '-c', DRIVER, directory],
                    input=json.dumps(request), text=True, capture_output=True, timeout=45, check=True)
                response = json.loads(process.stdout)
                returned = response['outcomes']
                waiting = response.get('deferred')
                if waiting is not None:
                    if (returned or not isinstance(waiting, dict)
                            or waiting.get('reason') != 'historical_publication_rule_not_yet_satisfied'
                            or waiting.get('observed_market_session') != history.get('market_session')):
                        raise ValueError('archive_deferral_invalid')
                    if deferred is not None:
                        deferred.append({'experiment_version': archive['experiment_version'],
                            'observation_count': len(observations), **waiting})
                expected = {r['observation_id'] for r in observations}
                identities = [r.get('observation_id') for r in returned]
                if (len(set(identities)) != len(identities) or not set(identities) <= expected
                        or any(r.get('kind') != 'outcome' for r in returned)):
                    raise ValueError('archive_outcome_identity_invalid')
                result.extend(returned)
        except (subprocess.SubprocessError, OSError, tarfile.TarError) as exc:
            raise ValueError('archive_evaluation_failed') from exc
    return result
