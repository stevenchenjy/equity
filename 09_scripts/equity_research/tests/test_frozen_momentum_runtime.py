"""Reproducibility regressions: immutable capture, closure, atomic append, replay."""
import copy
from datetime import datetime, date
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR
from test_momentum_experiment import fixture, write_fixture, ET
import momentum_experiment as m
import frozen_momentum_runtime as runtime
from tactical_review import _last_sessions


class FrozenRuntimeTests(unittest.TestCase):
    def registry(self):
        return runtime.load_registry(SCRIPT_DIR.parents[1])

    def test_all_existing_versions_have_complete_verified_import_closures(self):
        archives = self.registry()
        self.assertEqual(set(archives), {f'eod-breakout-v{i}-202609{27 if i<3 else 28}' for i in range(1,5)})
        for version, archive in archives.items():
            with runtime.verified_snapshot(archive) as (snapshot, policy):
                self.assertEqual(policy['version'], version)
                self.assertIn('09_scripts/equity_research/workflow_evaluation.py', archive['runtime_files'])
                self.assertEqual(json.loads((snapshot / m.POLICY).read_bytes()), policy)

    def test_omitted_transitive_dependency_rejected_even_with_resealed_manifest(self):
        archive = copy.deepcopy(self.registry()['eod-breakout-v4-20260928'])
        del archive['runtime_files']['09_scripts/equity_research/workflow_evaluation.py']
        archive['runtime_sha256'] = m.canonical_sha256(archive['runtime_files'])
        with self.assertRaisesRegex(ValueError, 'archive_runtime_dependency_missing'):
            with runtime.verified_snapshot(archive):
                pass

    def test_changed_dependency_cannot_be_resealed_against_unchanged_git_commit(self):
        archive = copy.deepcopy(self.registry()['eod-breakout-v4-20260928'])
        archive['runtime_files']['09_scripts/equity_research/workflow_evaluation.py'] = 'f'*64
        archive['runtime_sha256'] = m.canonical_sha256(archive['runtime_files'])
        with self.assertRaisesRegex(ValueError, 'archive_implementation_mismatch'):
            with runtime.verified_snapshot(archive):
                pass

    def test_unregistered_or_retuned_policy_never_appends(self):
        for change, expected in [('unregistered', 'experiment_version_unregistered'),
                                 ('retuned', 'experiment_policy_changed_without_new_version')]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); values = fixture(); write_fixture(root, values)
                m.run(root, values['current']); ledger=root/m.OUTPUT/'ledger.jsonl';before=ledger.read_bytes()
                if change == 'unregistered':values['policy']['version'] = 'not-registered'
                else:values['policy']['relative_volume_min'] = 1
                (root/m.POLICY).write_text(json.dumps(values['policy']))
                with self.assertRaisesRegex(ValueError, expected):m.run(root, values['current'])
                self.assertEqual(ledger.read_bytes(), before)

    def test_failed_staged_evaluator_preserves_ledger_report_and_failure_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);values=fixture();write_fixture(root,values);m.run(root,values['current'])
            before={p:(root/m.OUTPUT/p).read_bytes() for p in ['ledger.jsonl','report.json','report.md']}
            # The child could have staged an observation before a late archive failure.
            # No child publication goes directly to the durable output.
            def interrupted(snapshot, request):
                (Path(request['output'])/'ledger.jsonl').write_text('partial invalid staged append')
                raise subprocess.CalledProcessError(1,['frozen'])
            with patch.object(runtime, '_execute_frozen', side_effect=interrupted):
                with self.assertRaisesRegex(ValueError,'frozen_experiment_evaluation_failed'):
                    m.run(root,values['current'].replace(hour=14))
            for p,raw in before.items():self.assertEqual((root/m.OUTPUT/p).read_bytes(),raw)
            attempts=m.run_attempt_summary(root/m.OUTPUT)
            self.assertEqual(attempts['failed'],1)
            self.assertEqual(attempts['succeeded'],1)

    def test_outcomes_match_original_frozen_model_and_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);values=fixture();write_fixture(root,values)
            first=m.run(root,values['current']);observation=first['current_observations'][0]
            early=(root/m.OUTPUT/'ledger.jsonl').read_bytes()
            existing={b['session_date']:b for b in observation['bars_at_observation']}
            forward=[{'session_date':d,'open':104,'high':106,'low':102,'close':105,'volume':100}
                     for d in [observation['earliest_modeled_entry_session'],*m.sessions_after(date(2026,9,24),4)]]
            combined={**existing,**{b['session_date']:b for b in forward}}
            values['history']['tickers']['TEST']['bars']=[combined.get(d, {'session_date':d,
                'open':99,'high':101,'low':98,'close':100,'volume':100}) for d in _last_sessions(date(2026,9,30),20)]
            current=datetime(2026,10,1,13,30,tzinfo=ET)
            values['history'].update(market_session='2026-09-30',generated_at=current.isoformat())
            values['market'][0].update(last_price=105,market_session_date='2026-09-30',data_timestamp=current.isoformat())
            values['decision'].update(generated_at=current.isoformat(),market_gate={'expected_market_session':'2026-09-30'})
            write_fixture(root,values);report=m.run(root,current)
            ledger=(root/m.OUTPUT/'ledger.jsonl').read_bytes();self.assertTrue(ledger.startswith(early))
            rows=[json.loads(x) for x in ledger.splitlines()];outcome=next(x for x in rows if x['kind']=='outcome')
            expected=m.evaluate(observation,{'TEST':forward},current)
            for field in ['models','forward_bars','all_covered_net_path_pct_by_one_way_bps','cohorts','status']:
                self.assertEqual(outcome[field],expected[field])
            self.assertFalse(outcome['models']['breakout_with_volume']['actual_fill'])
            self.assertEqual(report['summary']['outcomes'],1)
            m.run(root,current.replace(hour=14));self.assertEqual((root/m.OUTPUT/'ledger.jsonl').read_bytes(),ledger)
            self.assertEqual(report['frozen_execution']['bindings'][observation['experiment_version']]['implementation_sha256'],observation['inputs']['implementation_sha256'])

    def test_missing_frozen_objects_fail_without_falling_back_to_live_code(self):
        archive=copy.deepcopy(self.registry()['eod-breakout-v4-20260928']);archive['git_commit']='f'*40
        with self.assertRaisesRegex(ValueError,'archive_evaluation_failed'):
            with runtime.verified_snapshot(archive):pass

    def test_capture_retains_exact_inputs_after_refresh_files_are_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);values=fixture();write_fixture(root,values)
            original=(root/m.DECISION).read_bytes();report=m.run(root,values['current'])
            receipt=report['frozen_execution']['input_artifacts'][str(m.DECISION)]
            (root/m.DECISION).write_text('{}')
            retained=root/m.OUTPUT/receipt['relative_to_experiment_output']
            self.assertEqual(retained.read_bytes(),original)
            self.assertEqual(hashlib.sha256(original).hexdigest(),receipt['sha256'])

    def test_live_model_mutation_does_not_change_registered_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);values=fixture();write_fixture(root,values)
            # This fails under the former live _run path. It represents an
            # unrelated deployment changing a live shared capture function.
            with patch.object(m,'observe',side_effect=AssertionError('live code used')):
                report=m.run(root,values['current'])
            row=report['current_observations'][0]
            binding=report['frozen_execution']['bindings'][row['experiment_version']]
            self.assertEqual(row['inputs']['implementation_sha256'],binding['implementation_sha256'])
            self.assertTrue(row['cohorts']['breakout_with_volume'])
            self.assertEqual(row['quantity'],0)
            self.assertFalse(row['actionable'])


if __name__=='__main__':unittest.main()
