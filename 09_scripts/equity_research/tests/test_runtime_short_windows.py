from __future__ import annotations

from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ET
import run_daily_refresh_scheduler as refresh
import run_runtime_scheduler as runtime


class ExecReached(BaseException):
    pass


class RuntimeShortWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.morning = datetime(2026, 10, 27, 9, 30, tzinfo=ET)

    def main_context(self, stack, clocks, arguments=None, lock=None):
        stamps = iter(clocks)

        class Clock:
            @classmethod
            def now(cls, zone):
                return next(stamps)

        if lock is None:
            lock = Mock()
            lock.__enter__ = Mock(return_value=SimpleNamespace(contention_observed=False))
            lock.__exit__ = Mock(return_value=False)
        stack.enter_context(patch.dict(runtime.os.environ, {}, clear=True))
        stack.enter_context(patch.object(runtime, 'PRODUCTION_RUNTIME_ROOT', self.root))
        stack.enter_context(patch.object(runtime, 'RUNTIME_LOCK_PATH', self.root / 'runtime.lock'))
        stack.enter_context(patch.object(runtime, 'assert_non_icloud_runtime_root'))
        stack.enter_context(patch.object(runtime, 'datetime', Clock))
        stack.enter_context(patch.object(runtime.sys, 'argv',
            ['runtime.py', '--job', 'dailyrefresh', *(arguments or [])]))
        lock_factory = stack.enter_context(patch.object(runtime, 'ExclusiveFileLock', return_value=lock))
        sync = stack.enter_context(patch.object(runtime, 'sync_runtime_for_job',
            return_value=SimpleNamespace(commit='a' * 40, action='identical')))
        execute = stack.enter_context(patch.object(runtime, '_exec_scheduler', side_effect=ExecReached))
        stack.enter_context(patch.object(runtime, '_best_effort_failure_record'))
        stack.enter_context(patch.object(runtime, '_best_effort_preflight_alert'))
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(redirect_stderr(io.StringIO()))
        return lock_factory, sync, execute, lock

    def test_active_short_window_defers_before_lock_git_or_slot_mutation(self):
        state = self.root / '00_project_control/run_logs/daily_scheduler_state.local.json'
        state.parent.mkdir(parents=True)
        state.write_text('{"existing_slot_history":"preserve"}')
        original = state.read_bytes()
        with ExitStack() as stack:
            lock, sync, execute, _ = self.main_context(stack, [self.morning])
            git = stack.enter_context(patch.object(runtime, '_run_git_process'))
            self.assertEqual(runtime.main(), 0)
            lock.assert_not_called(); sync.assert_not_called(); execute.assert_not_called(); git.assert_not_called()
        receipt = json.loads((self.root / runtime.SHORT_DEFERRAL_RELATIVE_PATH).read_text())
        self.assertEqual(receipt['phase'], 'before_runtime_lock')
        self.assertEqual(receipt['reason'], 'short_assessment_window_protected')
        self.assertEqual(receipt['slot'], '09:30')
        self.assertIs(receipt['refresh_slot_consumed'], False)
        self.assertIs(receipt['pipeline_invoked'], False)
        self.assertEqual(state.read_bytes(), original)

    def test_lock_wait_crossing_into_short_window_defers_and_releases_lock(self):
        entered = SimpleNamespace(contention_observed=True, waited_seconds=360)
        lock = Mock(); lock.__enter__ = Mock(return_value=entered); lock.__exit__ = Mock(return_value=False)
        with ExitStack() as stack:
            _, sync, execute, _ = self.main_context(stack,
                [self.morning.replace(hour=8), self.morning], lock=lock)
            self.assertEqual(runtime.main(), 0)
            sync.assert_not_called(); execute.assert_not_called()
        lock.__exit__.assert_called_once()
        receipt = json.loads((self.root / runtime.SHORT_DEFERRAL_RELATIVE_PATH).read_text())
        self.assertEqual(receipt['phase'], 'after_runtime_lock')

    def test_actual_clock_is_rechecked_after_slow_preflight_before_exec(self):
        early = self.morning.replace(hour=8)
        with ExitStack() as stack:
            _, sync, execute, _ = self.main_context(stack, [early, early, self.morning])
            self.assertEqual(runtime.main(), 0)
            sync.assert_called_once(); execute.assert_not_called()
        self.assertIsNone(runtime._GIT_PREFLIGHT_DEADLINE.get())
        receipt = json.loads((self.root / runtime.SHORT_DEFERRAL_RELATIVE_PATH).read_text())
        self.assertEqual(receipt['phase'], 'after_git_preflight')

    def test_clear_window_still_requires_strict_sync_and_preserves_exec_identity(self):
        early = self.morning.replace(hour=8)
        with ExitStack() as stack:
            _, sync, execute, _ = self.main_context(stack, [early, early, early])
            with self.assertRaises(ExecReached):
                runtime.main()
            sync.assert_called_once_with(self.root, job='dailyrefresh', sync_only=False)
            self.assertEqual(execute.call_args.kwargs['expected_commit'], 'a' * 40)
        self.assertIsNone(runtime._GIT_PREFLIGHT_DEADLINE.get())

    def test_calendar_unknown_defers_before_lock_without_asserting_execution(self):
        with ExitStack() as stack:
            lock, sync, execute, _ = self.main_context(stack, [self.morning])
            stack.enter_context(patch.object(refresh, 'short_window_conflict',
                return_value={'reason': 'exchange_calendar_unverified'}))
            self.assertEqual(runtime.main(), 0)
            lock.assert_not_called(); sync.assert_not_called(); execute.assert_not_called()

    def test_owner_one_shots_safe_sync_and_sender_do_not_use_normal_refresh_guard(self):
        base = {'job': 'dailyrefresh', 'safe_check': False, 'sync_only': False}
        for environment in [refresh.MASSIVE_AUTH_PRESENCE_PROBE_ENV, refresh.SEC_REFRESH_ONLY_ENV,
                refresh.MARKET_REFRESH_ONLY_ENV, refresh.MARKET_DISCOVERY_ONLY_ENV,
                refresh.FULL_REFRESH_REUSE_ONLY_ENV]:
            with self.subTest(environment=environment), patch.dict(runtime.os.environ, {environment: '1'}, clear=True):
                self.assertFalse(runtime._normal_scheduled_refresh(SimpleNamespace(**base)))
        with patch.dict(runtime.os.environ, {}, clear=True):
            self.assertTrue(runtime._normal_scheduled_refresh(SimpleNamespace(**base)))
            self.assertFalse(runtime._normal_scheduled_refresh(SimpleNamespace(**base),
                current=self.morning.replace(month=9, day=24)))
            for changed in [{'safe_check': True}, {'sync_only': True}, {'job': 'dailydecision'}]:
                self.assertFalse(runtime._normal_scheduled_refresh(SimpleNamespace(**{**base, **changed})))

    def test_future_adoption_date_is_honored_and_invalid_policy_does_not_authorize_exec(self):
        args = SimpleNamespace(job='dailyrefresh', safe_check=False, sync_only=False)
        with patch.dict(runtime.os.environ, {}, clear=True), patch.object(runtime, 'load_active_config',
                return_value={'notifications': {'delivery_assessment_effective_from': '2026-11-01'}}):
            self.assertFalse(runtime._normal_scheduled_refresh(args, current=self.morning))
        with patch.dict(runtime.os.environ, {}, clear=True), patch.object(runtime, 'load_active_config',
                side_effect=ValueError('invalid policy')):
            with self.assertRaisesRegex(runtime.RuntimeSyncError, 'runtime_short_policy_unverified'):
                runtime._normal_scheduled_refresh(args, current=self.morning)

    def test_git_commands_share_finite_budget_without_leaking_authentication(self):
        token = runtime._GIT_PREFLIGHT_DEADLINE.set(100)
        self.addCleanup(runtime._GIT_PREFLIGHT_DEADLINE.reset, token)
        result = subprocess.CompletedProcess(['git'], 0, '', '')
        with patch.object(runtime.time, 'monotonic', return_value=90), \
                patch.object(runtime.subprocess, 'run', return_value=result) as run, \
                patch.dict(runtime.os.environ, {'MASSIVE_API_KEY': 'mock-canary'}, clear=True):
            self.assertIs(runtime._run_git_process(self.root, ['status'], timeout=60), result)
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
            self.assertNotIn('MASSIVE_API_KEY', run.call_args.kwargs['env'])
        with patch.object(runtime.time, 'monotonic', return_value=101), \
                patch.object(runtime.subprocess, 'run') as run:
            with self.assertRaisesRegex(runtime.RuntimeSyncError, 'runtime_preflight_git_budget_exhausted'):
                runtime._run_git_process(self.root, ['status'])
            run.assert_not_called()

    def test_exhausted_preflight_blocks_exec_and_is_not_network_fallback(self):
        early = self.morning.replace(hour=8)
        with ExitStack() as stack:
            _, sync, execute, _ = self.main_context(stack, [early, early])
            stack.enter_context(patch.object(runtime.time, 'monotonic', side_effect=[0, 241]))
            git_child = stack.enter_context(patch.object(runtime.subprocess, 'run'))
            sync.side_effect = lambda *a, **k: runtime._run_git_process(self.root, ['status'])
            self.assertEqual(runtime.main(), 70)
            execute.assert_not_called()
            git_child.assert_not_called()
        self.assertIsNone(runtime._GIT_PREFLIGHT_DEADLINE.get())
        self.assertFalse(runtime._eligible_connectivity_failure(
            runtime.RuntimeSyncError('runtime_preflight_git_budget_exhausted')))
        self.assertTrue(runtime._eligible_connectivity_failure(
            runtime.RuntimeSyncError('git_fetch_failed', 'Could not resolve host')))
        self.assertFalse(runtime._eligible_connectivity_failure(
            runtime.RuntimeSyncError('git_fetch_failed', 'Authentication failed')))

    def test_short_lookahead_includes_git_pipeline_and_independent_news_bounds(self):
        with patch.object(refresh, 'short_window_conflict', return_value=None) as guard:
            self.assertFalse(runtime._defer_normal_refresh(self.root, current=self.morning, phase='before_runtime_lock'))
            self.assertEqual(guard.call_args.kwargs['maximum_seconds'],
                runtime.NORMAL_REFRESH_GIT_PREFLIGHT_SECONDS + refresh.DAILY_REFRESH_PIPELINE_TIMEOUT_SECONDS
                + refresh.SCHEDULED_NEWS_ALLOWANCE_SECONDS)
        self.assertFalse((self.root / runtime.SHORT_DEFERRAL_RELATIVE_PATH).exists())

    def test_deferral_does_not_follow_a_linked_receipt(self):
        target = self.root / runtime.SHORT_DEFERRAL_RELATIVE_PATH
        target.parent.mkdir(parents=True)
        original = self.root / 'outside'; original.write_text('preserve')
        target.symlink_to(original)
        with self.assertRaisesRegex(runtime.RuntimeSyncError, 'runtime_short_deferral_file_unsafe'):
            runtime._defer_normal_refresh(self.root, current=self.morning, phase='before_runtime_lock')
        self.assertEqual(original.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
