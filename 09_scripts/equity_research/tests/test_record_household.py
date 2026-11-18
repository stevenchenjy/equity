"""Exercise the same preview, publication and compare-and-swap used by the operator."""
import json
import unittest
from unittest.mock import patch

import test_household_planning as fixtures
from record_household_planning import record
import household_planning as hp


class RecordHouseholdTests(unittest.TestCase):
    def test_preview_apply_repeat_and_stale_proposal(self):
        fixture = fixtures.HouseholdPlanningTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        root = fixture.root
        manifest = root / hp.MANIFEST
        current = fixtures.NOW
        args = [root, 'assets', json.loads(manifest.read_bytes()), fixture.broker_path]
        manifest.unlink()
        with patch('record_household_planning.now_et', return_value=current), patch(
                'record_household_planning.RUNTIME_LOCK_PATH', root / 'runtime.lock'):
            preview = record(*args)
            self.assertFalse(manifest.exists())
            installed = record(*args, apply=True, expected=preview['prior'])
            self.assertEqual(installed['household_total_usd'], '950.00')
            self.assertEqual(installed['sha256'], record(*args, apply=True, expected=preview['prior'])['sha256'])
            args[2]['observed_at'] = current.isoformat()
            args[2]['external_assets_usd'] = '250.00'
            with self.assertRaisesRegex(ValueError, 'changed since preview'):
                record(*args, apply=True, expected=preview['prior'])
            changed = record(*args, apply=True, expected=installed['sha256'])
            self.assertEqual(changed['household_total_usd'], '700.00')
            source = root / fixture.plan['plan_source_path']
            plan = dict(fixture.plan)
            (root / hp.RESEARCH_MANIFEST).unlink()
            self.assertEqual(record(root,'research',plan, source, apply=True, expected='absent')['review_count'], 1)
            plan['plan_source_sha256'] = 'x'
            with self.assertRaisesRegex(ValueError, 'original bytes'):
                record(root,'research',plan, source)
