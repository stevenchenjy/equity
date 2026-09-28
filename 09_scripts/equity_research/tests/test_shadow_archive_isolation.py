from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import evaluate_shadow_llm_incremental_value as evaluator
from shadow_llm_contract import ShadowContractError


class ShadowArchiveIsolationTests(unittest.TestCase):
    def test_invalid_packet_archive_cannot_hide_valid_runs_or_rewrite_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('bad', 'good'):
                path = root / name / 'bundle.json'
                path.parent.mkdir()
                path.write_text(json.dumps({'schema_version': evaluator.BUNDLE_SCHEMA_VERSION, 'run_id': name}))
            bad = root / 'bad/bundle.json'
            original = bad.read_bytes()
            def validate(path, **kwargs):
                if path.parent.name == 'bad':
                    raise ShadowContractError('evidence packet failed its canonical contract')
                return {'run_id': 'good'}
            with patch.object(evaluator, 'load_automatic_bundle', side_effect=validate):
                result = evaluator._discover(root, [])
            self.assertEqual(result['automatic'], [{'run_id': 'good'}])
            self.assertEqual(result['invalid_archives'][0]['path'], 'bad/bundle.json')
            self.assertEqual(result['invalid_archives'][0]['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(bad.read_bytes(), original)

    def test_invalid_history_keeps_readiness_false_and_discloses_exclusions(self):
        invalid = [{'path': 'bad/bundle.json', 'reason': 'archive_validation_failed'}]
        result = evaluator.aggregate([], evaluator.load_config(), invalid_archives=invalid,
            snapshot_path=Path('/not-present-audit-snapshots'), outcome_path=Path('/not-present-audit-outcomes'))
        self.assertEqual(result['decision']['status'], 'blocked_invalid_archived_evidence')
        self.assertEqual(result['archive_integrity']['invalid_archives'], invalid)
        self.assertEqual(result['archive_integrity']['status'], 'degraded')
        self.assertIsNone(result['decision']['current_stage_exhausted'])
        self.assertIsNone(result['metrics']['completed_event_rate'])
        for key in ('continue_evaluation_evidence_met', 'usefulness_evidence_met',
                    'authority_review_evidence_met', 'production_influence', 'promotion_authorized'):
            self.assertFalse(result['decision'][key])
        for checks in result['threshold_checks'].values():
            self.assertFalse(checks['archive_integrity_complete'])
        self.assertIn('Invalid archives excluded', evaluator._report(result))


if __name__ == '__main__':
    unittest.main()
