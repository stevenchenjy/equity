"""Fixed public research dispatch through the existing credential transport."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR

TEMPLATE=Path(SCRIPT_DIR).parents[1]/'07_automation/scheduler/dailyrefresh_launcher.py.template'


def module():
    loader=importlib.machinery.SourceFileLoader('swing_history_launcher_fixture',str(TEMPLATE))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    value=importlib.util.module_from_spec(spec);loader.exec_module(value)
    return value


class HistoryLauncherTests(unittest.TestCase):
    def run_mode(self,argv,key=b'mocked-private-value',fail=False):
        value=module();out,err=io.StringIO(),io.StringIO()
        # All credential handling is mocked; tests never access Keychain.
        with patch('sys.argv',['launcher',*argv]),patch.object(value,'keychain_value',return_value=key) as lookup,\
                patch.object(value.os,'execve',side_effect=OSError() if fail else None) as execute,\
                patch.dict(os.environb,{b'MASSIVE_API_KEY':b'untrusted-parent-value',b'OPENAI_API_KEY':b'unrelated-parent-value',b'FIXTURE':b'yes'},clear=True),\
                patch.object(value.os,'umask'),redirect_stdout(out),redirect_stderr(err):
            result=value.main()
        self.assertNotIn('mocked-private-value',out.getvalue()+err.getvalue())
        self.assertNotIn('untrusted-parent-value',out.getvalue()+err.getvalue())
        return value,result,lookup,execute

    def test_fixed_swing_dispatch_preserves_existing_keychain_transport_and_has_no_sender(self):
        value,result,lookup,execute=self.run_mode(['--swing-candidate-history'])
        lookup.assert_called_once_with(value.MASSIVE_KEYCHAIN_SERVICE)
        binary,arguments,environment=execute.call_args.args
        self.assertEqual(binary,value.PYTHON)
        self.assertEqual(arguments,[value.PYTHON,'/Users/messssi/LocalRuntime/equity/09_scripts/equity_research/run_swing_candidate_history.py',
                                    '--root','/Users/messssi/LocalRuntime/equity','--collect'])
        self.assertEqual(environment[b'MASSIVE_API_KEY'],b'mocked-private-value')
        self.assertNotIn(b'OPENAI_API_KEY',environment)
        self.assertEqual(environment[b'FIXTURE'],b'yes')
        self.assertNotIn('--pipeline-coordinated',arguments)
        self.assertFalse(any('sender' in arg or 'smtp' in arg for arg in arguments))

    def test_normal_scheduled_dispatch_is_unchanged(self):
        value,result,lookup,execute=self.run_mode([])
        self.assertEqual(execute.call_args.args[1],[value.PYTHON,value.RUNTIME_SCHEDULER,'--job','dailyrefresh'])
        lookup.assert_called_once_with(value.MASSIVE_KEYCHAIN_SERVICE)

    def test_feedback_reuse_remains_no_keychain_lookup_and_no_public_history(self):
        value,result,lookup,execute=self.run_mode(['--feedback-refresh','--market-snapshot-mode','reuse_validated_snapshot'])
        lookup.assert_not_called();self.assertNotIn(b'MASSIVE_API_KEY',execute.call_args.args[2])
        self.assertEqual(execute.call_args.args[1],[value.PYTHON,'/Users/messssi/LocalRuntime/equity/09_scripts/equity_research/run_daily_refresh.py',
            '--run','--no-lock','--market-snapshot-mode','reuse_validated_snapshot'])

    def test_missing_primary_key_is_finite_and_never_reuses_inherited_secret(self):
        value,result,lookup,execute=self.run_mode(['--swing-candidate-history'],key=None)
        self.assertNotIn(b'MASSIVE_API_KEY',execute.call_args.args[2]);lookup.assert_called_once()
        value,result,lookup,execute=self.run_mode(['--swing-candidate-history'],fail=True)
        self.assertEqual(result,value.LAUNCH_FAILED_EXIT)

    def test_mutually_exclusive_modes_and_arbitrary_targets_are_rejected_before_lookup(self):
        for args in (['--swing-candidate-history','--feedback-refresh'],['--swing-candidate-history','--script','sender.py']):
            value=module()
            with patch('sys.argv',['launcher',*args]),patch.object(value,'keychain_value') as lookup,\
                    patch.object(value.os,'execve') as execute,redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as raised:
                value.main()
            self.assertEqual(raised.exception.code,2);lookup.assert_not_called();execute.assert_not_called()


if __name__=='__main__':unittest.main()
