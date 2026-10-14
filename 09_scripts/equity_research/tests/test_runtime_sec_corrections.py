from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_runtime_git_sync import LocalRepositoryFixture, _git
from sec_acceptance import make_acceptance_record, build_acceptance_index, write_acceptance_index
from sec_acceptance_corrections import retain_proof, make_correction, write_corrections, CORRECTIONS_REL
from sec_acceptance_extensions import EXTENSION_AUDIT_FIELDS
import run_runtime_scheduler as runtime


def _proof_fixture(root: Path) -> tuple[Path, list[Path]]:
    accession = '0001045810-26-000078'
    url = 'https://data.sec.gov/submissions/CIK0001045810.json'
    old = make_acceptance_record(accession_number=accession, ticker='NVDA', cik=1045810,
        filing_date='2026-09-03', accepted_at='2026-09-03T08:03:56Z', source_url=url)
    observed = make_acceptance_record(**{k: v for k, v in old.items()
        if k not in {'accepted_at', 'record_sha256'}}, accepted_at='2026-09-03T16:03:56Z')
    base = root / '03_source_data/equity_research'
    write_acceptance_index(build_acceptance_index(new_records=[old],
        generated_at='2026-09-04T12:00:00Z'), base / 'sec_submission_acceptance_index.json')
    (base / 'sec_acceptance_extension_admission_audit.csv').write_text(','.join(EXTENSION_AUDIT_FIELDS) + '\n')
    _git(root, 'add', '03_source_data')
    _git(root, 'commit', '-m', 'immutable acceptance base')
    prefix = f'https://www.sec.gov/Archives/edgar/data/1045810/{accession.replace("-", "")}/{accession}'
    submissions = json.dumps({'cik':1045810, 'tickers':['NVDA'], 'name':'NVIDIA CORP',
        'filings':{'recent':{'accessionNumber':[accession], 'form':['8-K'],
        'filingDate':['2026-09-03'], 'acceptanceDateTime':['2026-09-03T16:03:56Z']}}}).encode()
    header = f'<PRE>&lt;SEC-HEADER&gt;{accession}\n&lt;ACCEPTANCE-DATETIME&gt;20260903080356\nACCESSION NUMBER:\t{accession}\nCONFORMED SUBMISSION TYPE:\t8-K\nFILED AS OF DATE:\t20260903\nFILER:\n COMPANY CONFORMED NAME:\tNVIDIA CORP\n CENTRAL INDEX KEY:\t0001045810\nFILING VALUES:\n&lt;/SEC-HEADER&gt;</PRE>'.encode()
    index = f'<strong>Form 8-K</strong>{accession}<a href="?CIK=0001045810">CIK</a><div class="infoHead">Filing Date</div><div class="info">2026-09-03</div><div class="infoHead">Accepted</div><div class="info">2026-09-03 08:03:56</div>'.encode()
    sources = {name: retain_proof(raw, url=source_url, observed_at='2026-09-04T13:00:00Z', root=root)
        for name, raw, source_url in [('submissions', submissions, url),
            ('header', header, prefix+'-index-headers.html'), ('index', index, prefix+'-index.html')]}
    correction = make_correction(historical=old, observed=observed, form='8-K',
        entity_name='NVIDIA CORP', sources=sources, root=root, admitted_at='2026-09-04T14:00:00Z')
    write_corrections(root, [correction], [old])
    return root / CORRECTIONS_REL / 'sec_acceptance_correction_v1.json', [root / s['raw_path'] for s in sources.values()]


class RuntimeCorrectionTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='runtime-sec-proof-')
        self.addCleanup(temporary.cleanup)
        fixture = LocalRepositoryFixture(Path(temporary.name))
        correction, proofs = _proof_fixture(fixture.runtime)
        return fixture.runtime, correction, proofs

    def test_valid_new_correction_and_exact_bound_proofs_are_allowed(self):
        root, correction, proofs = self.fixture()
        changes = runtime._runtime_evidence_changes(root)
        self.assertEqual(set(changes), {p.relative_to(root).as_posix() for p in [correction, *proofs]})

    def test_content_addressed_but_unbound_raw_file_is_rejected(self):
        root, _, proofs = self.fixture()
        raw = b'not referenced by any accepted proof'
        unknown = proofs[0].parent / (hashlib.sha256(raw).hexdigest()+'.raw')
        unknown.write_bytes(raw)
        with self.assertRaises(runtime.RuntimeSyncError) as error:
            runtime._runtime_evidence_changes(root)
        self.assertEqual(error.exception.code, 'runtime_correction_proof_unbound')

    def test_raw_hash_conflict_and_chain_edit_are_rejected(self):
        for mutate in ('raw', 'chain'):
            with self.subTest(mutate=mutate):
                root, correction, proofs = self.fixture()
                if mutate == 'raw':
                    proofs[0].write_bytes(b'tampered')
                else:
                    payload = json.loads(correction.read_text())
                    payload['artifact_sha256'] = '0'*64
                    correction.write_text(json.dumps(payload))
                with self.assertRaises(runtime.RuntimeSyncError) as error:
                    runtime._runtime_evidence_changes(root)
                self.assertEqual(error.exception.code, 'runtime_correction_validation_failed')

    def test_old_tracked_proof_or_correction_cannot_be_modified(self):
        for mutate in ('proof', 'correction'):
            with self.subTest(mutate=mutate):
                root, correction, proofs = self.fixture()
                _git(root, 'add', '02_filings', '03_source_data')
                _git(root, 'commit', '-m', 'retain original proof')
                target = proofs[0] if mutate == 'proof' else correction
                target.write_bytes(target.read_bytes()+b'\n')
                with self.assertRaises(runtime.RuntimeSyncError) as error:
                    runtime._runtime_evidence_changes(root)
                self.assertEqual(error.exception.code, 'tracked_worktree_dirty')

    def test_symlink_and_hardlink_proofs_are_rejected(self):
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind):
                root, _, proofs = self.fixture()
                original = proofs[0]
                saved = root.parent / ('saved-'+kind+'.raw')
                saved.write_bytes(original.read_bytes())
                original.unlink()
                if kind == 'symlink': original.symlink_to(saved)
                else: original.hardlink_to(saved)
                with self.assertRaises(runtime.RuntimeSyncError) as error:
                    runtime._runtime_evidence_changes(root)
                self.assertEqual(error.exception.code, 'runtime_evidence_file_unsafe')


if __name__ == '__main__': unittest.main()
