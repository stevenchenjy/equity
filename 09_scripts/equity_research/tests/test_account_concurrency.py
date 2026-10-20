from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import _support
import account_access as access
import run_daily_refresh as refresh
from workflow_integrity import validate_published_workflow


class AccountConcurrencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.account = self.root / access.ACCOUNT_INPUTS[0]
        self.account.parent.mkdir(parents=True)
        self.account.write_text('{"cash_available":1000}')

    def test_ledger_change_invalidates_publication_even_if_balances_return_to_old_values(self):
        version = access.capture_version(self.root)
        ledger = self.root / access.ACCOUNT_INPUTS[3]
        ledger.parent.mkdir(parents=True)
        ledger.write_text('buy then sell; unchanged cash and shares, new facts')
        with self.assertRaisesRegex(ValueError, 'account_inputs_changed'):
            validate_published_workflow({'account_input_version': version}, root=self.root,
                                        current=datetime.now(timezone.utc))
        with self.assertRaisesRegex(ValueError, 'account_inputs_changed'):
            with access.publication_guard(self.root, version):
                self.fail('superseded result was published')

    def test_direct_composer_cannot_adopt_new_hashes_over_old_account_research(self):
        checkpoint = self.root / access.CHECKPOINT
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text(json.dumps({'account_input_version': access.capture_version(self.root)}))
        self.account.write_text('{"cash_available":900}')
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(access.VERSION_ENV, None)
            with self.assertRaisesRegex(ValueError, 'account_inputs_changed'):
                access.expected_version(self.root)

    def test_missing_checkpoint_requires_full_recomposition(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(access.VERSION_ENV,None)
            with self.assertRaisesRegex(ValueError,'account_research_context_missing'):
                access.expected_version(self.root)

    def test_prepared_multifile_recovery_cannot_be_overwritten_by_a_composer(self):
        pending=self.root/access.ACCOUNT_INPUTS[6]
        pending.parent.mkdir(parents=True)
        pending.write_text(json.dumps({'records':[{'stage':'applying'}]}))
        with self.assertRaisesRegex(ValueError,'account_write_recovery_required'):
            with access.publication_guard(self.root,access.capture_version(self.root)):
                self.fail('incomplete account write reached publication')

    def test_short_publication_commit_excludes_account_write_only_until_release(self):
        entered, complete = threading.Event(), threading.Event()
        def writer():
            entered.set()
            with access.account_lock(self.root):
                self.account.write_text('{"cash_available":900}')
                complete.set()
        with access.publication_guard(self.root, access.capture_version(self.root)):
            thread = threading.Thread(target=writer);thread.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(complete.is_set())
        thread.join(2)
        self.assertTrue(complete.is_set())

    def test_mid_refresh_fill_recomposes_latest_account_without_repeating_collection(self):
        calls=[]
        original=os.environ.get(access.VERSION_ENV)
        def step(name, script, allowed, **kwargs):
            calls.append(name)
            if name=='official_evidence':
                with access.account_lock(self.root):
                    self.account.write_text('{"cash_available":900}')
            same=os.environ[access.VERSION_ENV]==access.capture_version(self.root)
            return {'name':name,'exit_code':0 if name!='daily_decision' or same else 1}
        with patch.object(refresh,'ROOT',self.root), patch.object(refresh,'run_step',side_effect=step):
            steps, retries, current=refresh.consistent_steps('reuse_validated_snapshot')
        self.assertTrue(current)
        self.assertEqual(len(retries),1)
        self.assertEqual(calls.count('market_refresh'),1)
        self.assertEqual(calls.count('official_evidence'),1)
        self.assertEqual(calls.count('research_backlog'),1)
        self.assertEqual(calls.count('daily_decision'),2)
        self.assertEqual(next(x for x in steps if x['name']=='daily_decision')['exit_code'],0)
        self.assertEqual(os.environ.get(access.VERSION_ENV), original)
        self.assertEqual(access.expected_version(self.root),access.capture_version(self.root))

    def test_continual_new_fills_bound_retries_and_do_not_claim_current_publication(self):
        count=0
        def step(name, script, allowed, **kwargs):
            nonlocal count
            if name=='daily_decision':
                count+=1
                with access.account_lock(self.root):
                    self.account.write_text(json.dumps({'new_fill':count}))
            return {'name':name,'exit_code':0}
        with patch.object(refresh,'ROOT',self.root),patch.object(refresh,'run_step',side_effect=step):
            _,retries,current=refresh.consistent_steps('reuse_validated_snapshot')
        self.assertFalse(current)
        self.assertEqual(len(retries),2)
        self.assertEqual(count,3)
        self.assertFalse((self.root/access.CHECKPOINT).exists())


if __name__=='__main__':unittest.main()
