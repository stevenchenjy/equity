import io
from contextlib import redirect_stdout
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa:F401
import run_swing_observer as wrapper
import swing_benchmark_quotes as pairs


class BenchmarkWrapperTests(unittest.TestCase):
    def test_supplemental_follows_existing_run_and_uses_remaining_unchanged_deadline(self):
        original=dict(status='observed',started_at='original',capital_authority=False,email_sent=False,trade_placed=False)
        with tempfile.TemporaryDirectory() as root,patch('sys.argv',['observer','--root',root,'--worker']),\
                patch.object(wrapper,'run',return_value=original) as run,\
                patch.object(wrapper.time,'monotonic',side_effect=[100,110]),\
                patch.object(pairs,'after_observer',return_value={'status':'deferred_remaining_worker_budget'}) as extra,redirect_stdout(io.StringIO()):
            result=wrapper.main()
        self.assertEqual(result,0);run.assert_called_once();extra.assert_called_once()
        self.assertEqual(extra.call_args.kwargs['remaining_seconds'],64)
        self.assertIs(extra.call_args.kwargs['observer_result'],original)
        self.assertEqual(wrapper.MAX_WORKER_SECONDS,75)

    def test_no_observation_or_readonly_check_does_not_collect_benchmarks(self):
        for status in ('no_candidates','deferred_active_short_claim','outside_review_window','failed','unavailable_quotes'):
            with patch('sys.argv',['observer','--worker']),patch.object(wrapper,'run',return_value={'status':status}),\
                    patch.object(pairs,'after_observer') as extra,redirect_stdout(io.StringIO()):
                wrapper.main();extra.assert_not_called()
        with patch('sys.argv',['observer','--check']),patch.object(wrapper,'run') as run,patch.object(pairs,'after_observer') as extra,redirect_stdout(io.StringIO()):
            self.assertEqual(wrapper.main(),0);run.assert_not_called();extra.assert_not_called()


if __name__=='__main__':unittest.main()
