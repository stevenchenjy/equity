"""Collection precedes intake; offline success cannot erase a failed fetch."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from _support import SCRIPT_DIR
import run_daily_refresh as refresh


class EarningsWorkflowTests(unittest.TestCase):
    def test_calendar_precedes_research_and_is_advisory(self):
        names=[r[0] for r in refresh.STEP_SPECS]
        self.assertLess(names.index('earnings_event_discovery'), names.index('research_opportunity_intake'))
        self.assertIn('earnings_event_discovery',refresh.ADVISORY_STEPS)

    def test_explicit_fetch_and_offline_reuse_do_not_invoke_a_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(refresh,'ROOT',root),patch.object(refresh.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                refresh.run_step('earnings_event_discovery','refresh_earnings_events.py',True,market_snapshot_mode=refresh.MARKET_SNAPSHOT_FETCH)
                self.assertIn('--refresh',run.call_args.args[0])
                refresh.run_step('earnings_event_discovery','refresh_earnings_events.py',True,market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE)
                self.assertNotIn('--refresh',run.call_args.args[0])
                self.assertTrue(all('send_daily_email.py' not in call.args[0] for call in run.call_args_list))

    def test_successful_offline_stage_preserves_failed_fetch_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'03_source_data/equity_research/earnings_events.local';base.mkdir(parents=True)
            failed={'exit_code':124,'started_at':'2026-10-21T08:00:00-04:00','completed_at':'2026-10-21T08:03:00-04:00'}
            (base/'last_run.json').write_text(json.dumps(failed))
            step={'name':'earnings_event_discovery','exit_code':0,'started_at':'2026-10-21T09:00:00-04:00','completed_at':'2026-10-21T09:00:01-04:00'}
            with patch.object(refresh,'ROOT',root):refresh._record_work_step(step)
            self.assertEqual(json.loads((base/'last_run.json').read_text()),failed)
            self.assertEqual(json.loads((base/'last_stage_run.json').read_text())['exit_code'],0)
