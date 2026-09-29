"""Real scheduler state transitions with child/network calls isolated."""
import copy
import io
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime
from unittest.mock import patch
from _support import SCRIPT_DIR  # noqa: F401
import run_daily_refresh_scheduler as scheduler


class OwnerRefreshWindowsTests(unittest.TestCase):
    def run_at(self, state, clock, *, success=True):
        now = datetime.fromisoformat('2026-09-29T' + clock + ':00-04:00')
        handoff = {'cycle_date': '2026-09-29', 'expected_market_session': '2026-09-28',
                   'started_at': now.isoformat(), 'outcome': 'passed' if success else 'failed',
                   'steps': [{'name': 'market_refresh', 'exit_code': 0 if success else 1}]}
        with ExitStack() as stack:
            for name, value in [('now_et', now), ('iso_now', now.isoformat()), ('cycle_date', '2026-09-29'),
                                ('load_active_state', {'operational_from': '2026-08-01'}),
                                ('load_inhibit', {'active': False})]:
                stack.enter_context(patch.object(scheduler, name, return_value=value))
            stack.enter_context(patch.object(scheduler, 'read_json', side_effect=lambda p, d: handoff if p == scheduler.DAILY_REFRESH_STATE_PATH else state))
            stack.enter_context(patch.object(scheduler, 'atomic_write_json'))
            stack.enter_context(patch.object(scheduler, 'publish_automation_alert'))
            stack.enter_context(patch('news_schedule.run_due_news_checks', return_value={}))
            stack.enter_context(patch.object(scheduler.sys, 'argv', ['refresh']))
            run = stack.enter_context(patch.object(scheduler.subprocess, 'run', return_value=scheduler.subprocess.CompletedProcess([], 0 if success else 1)))
            with redirect_stdout(io.StringIO()):
                scheduler.main()
        return run

    def test_morning_success_preserves_independent_afternoon_refresh(self):
        state = {'dates': {}}
        morning = self.run_at(state, '08:02')
        self.assertEqual(morning.call_count, 1)
        self.assertIn('fetch', morning.call_args.args[0])
        day = state['dates']['2026-09-29']
        self.assertNotIn('13:30', day['refresh_slots_completed'])
        self.assertEqual(self.run_at(state, '08:45').call_count, 0)
        afternoon = self.run_at(state, '13:35')
        self.assertEqual(afternoon.call_count, 1)
        self.assertIn('reuse_validated_snapshot', afternoon.call_args.args[0])
        self.assertIn('14:00', day['refresh_slots_completed'])
        self.assertEqual(self.run_at(state, '14:10').call_count, 0)

    def test_missing_morning_data_gets_bounded_retry_then_afternoon_recovery(self):
        state = {'dates': {}}
        self.run_at(state, '08:02', success=False)
        self.assertEqual(self.run_at(state, '08:15', success=False).call_count, 0)
        retry = self.run_at(state, '08:35', success=False)
        self.assertIn('fetch', retry.call_args.args[0])
        afternoon = self.run_at(state, '13:35')
        self.assertEqual(afternoon.call_count, 1)
        self.assertIn('fetch', afternoon.call_args.args[0])
        self.assertFalse(state['dates']['2026-09-29'].get('decision_completed', False))

    def test_evening_wake_archives_missed_slots_without_late_catchup_fetch(self):
        state = {'dates': {}}
        self.assertEqual(self.run_at(state, '20:00').call_count, 0)
        self.assertEqual(set(state['dates']['2026-09-29']['refresh_slots_missed']), set(scheduler.WEEKDAY_SLOTS))

    def test_stale_same_cycle_handoff_does_not_establish_market_ready(self):
        now = datetime.fromisoformat('2026-09-29T13:30:00-04:00')
        state = {'cycle_date': '2026-09-29', 'expected_market_session': '2026-09-28',
                 'started_at': '2026-09-29T08:00:00-04:00',
                 'steps': [{'name': 'market_refresh', 'exit_code': 0}]}
        self.assertFalse(scheduler._market_step_passed(state, expected_cycle_date='2026-09-29',
            expected_market_session='2026-09-28', not_before=now.isoformat()))


if __name__ == '__main__':
    unittest.main()
