import json
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

import test_feedback as fixture_module
from feedback import ACCOUNT, POSITIONS, ORDERS, LEDGER, PENDING, FeedbackError, Store, encoded, read, sha, version


DECISION = '04_research/company_research/daily_decision.json'


class ReviewAndCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.FeedbackTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.store = self.fixture.root, self.fixture.store
        self.fixture.put(DECISION, {'unreviewed': True})

    def review_payload(self, **changes):
        payload = dict(request_id=str(uuid.uuid4()), account_version=version(self.root),
                       snapshot_id=sha(read(self.root, DECISION)), tickers=['ABC'],
                       question='Review the current risk and expired conditional plan.')
        payload.update(changes)
        return payload

    def correction(self, original, **changes):
        p = self.fixture.payload(status='account', date=datetime.now().astimezone().date().isoformat(), time='',
                                 cash='1000', holdings=[{'ticker': 'ABC', 'shares': '2', 'entry_price': '100'}],
                                 account_observed=True)
        p.update(correction={'record_id': original['id'], 'reason': 'Corrected against a complete current owner observation.'})
        p['feedback'].update(changes)
        return p

    def publish(self):
        from workflow_integrity import WORKFLOW_INPUTS
        decision = dict(account={'cash_available': '1000', 'invested_capital': '200', 'account_total_value': '1200'},
                        held_positions=[{'ticker': 'ABC', 'current_shares': '2', 'current_price': '100'}],
                        workflow_integrity={'input_hashes': {p: sha(read(self.root, p)) if (self.root/p).exists() else None for p in WORKFLOW_INPUTS}})
        self.fixture.put(DECISION, decision)
        self.fixture.put('07_automation/email_briefs/daily_email_brief.txt', 'Fresh analyst publication')
        self.fixture.put('07_automation/email_briefs/daily_email_brief.html', '<p>Fresh analyst publication</p>')

    def receipt(self, request, *, completed=True, **changes):
        body = dict(schema_version='equity_dashboard_review_receipt_v1', request_id=request['id'],
                    account_version=request['review_account_version'], summary='Risk reassessed against current retained evidence.',
                    analysis_completed=completed, email_sent=False, trade_placed=False,
                    decision_sha256=sha(read(self.root, DECISION)), conclusions=['The source-bound conditional plan remains expired.'],
                    sources=[{'path': DECISION, 'sha256': sha(read(self.root, DECISION))}],
                    dependencies=['A current broker order inventory is still unavailable.'])
        body.update(changes)
        path = '08_reviews/analyst_followthrough.local/' + request['id'] + '/receipt.json'
        self.fixture.put(path, body)
        return path

    def test_correction_preserves_fill_ledger_and_retained_original(self):
        original = self.fixture.submit(self.fixture.payload())
        ledger = read(self.root, LEDGER)
        before = self.store.events(original['id'])
        p = self.correction(original)
        correction = self.fixture.submit(p)
        self.assertEqual(correction['stage'], 'applied')
        self.assertEqual(correction['correction'], p['correction'])
        self.assertEqual(read(self.root, LEDGER), ledger)
        self.assertEqual(json.loads(read(self.root, ACCOUNT))['cash_available'], 1000)
        old = next(r for r in self.store.history() if r['id'] == original['id'])
        self.assertEqual(old['corrected_by'], [correction['id']])
        self.assertEqual({k:v for k,v in old.items() if k!='corrected_by'}, original)
        self.assertEqual(self.store.events(original['id']), before)
        self.assertEqual(self.store.submit(p), correction)

    def test_correction_requires_applied_financial_reference_and_complete_observation(self):
        skipped = self.fixture.submit(self.fixture.payload(status='skipped'))
        with self.assertRaisesRegex(FeedbackError, 'correction_reference_not_applied'):
            self.store.preview(self.correction(skipped))
        original = self.fixture.submit(self.fixture.payload())
        for changes in ({'account_observed': False}, {'cash': ''}):
            with self.assertRaisesRegex(FeedbackError, 'complete_account_correction_required'):
                self.store.preview(self.correction(original, **changes))
        p = self.correction(original)
        p['correction']['reason'] = ' '
        with self.assertRaisesRegex(FeedbackError, 'invalid_account_correction'): self.store.preview(p)
        p = self.correction(original, status='filled')
        with self.assertRaisesRegex(FeedbackError, 'invalid_account_correction'): self.store.preview(p)

    def test_crashed_account_correction_recovers_without_reversing_a_trade(self):
        import feedback
        original = self.fixture.submit(self.fixture.payload())
        ledger = read(self.root, LEDGER)
        p = self.correction(original)
        p['preview_hash'] = self.store.preview(p)['preview_hash']
        atomic = feedback.atomic
        def fail(root, rel, content):
            if rel == ACCOUNT: raise OSError('simulated interruption')
            return atomic(root, rel, content)
        with patch('feedback.atomic', fail):
            with self.assertRaises(OSError): self.store.submit(p)
        result = Store(self.root, self.root/'runtime.lock', refresh=False).submit(p)
        self.assertEqual(result['stage'], 'applied')
        self.assertEqual(read(self.root, LEDGER), ledger)
        self.assertEqual(self.store.history()[0]['correction']['record_id'], original['id'])
        self.assertEqual(json.loads(read(self.root, PENDING))['records'], [])

    def test_review_queue_is_idempotent_and_never_applies_an_account_or_refresh(self):
        protected = {p:read(self.root, p) for p in (ACCOUNT, POSITIONS, ORDERS, DECISION)}
        p = self.review_payload(tickers=[])
        request = self.store.request_review(p)
        self.assertEqual(request['status'], 'queued')
        self.assertFalse(request['production_effect'])
        self.assertEqual(protected, {p:read(self.root, p) for p in protected})
        self.assertFalse(self.store.work_once())
        self.assertEqual(self.store.reviews()[0]['status'], 'queued')
        self.fixture.submit(self.fixture.payload())
        self.assertEqual(self.store.request_review(p), request)
        p['question'] = 'A different request must not reuse the same UUID.'
        with self.assertRaisesRegex(FeedbackError, 'request_id_reused'): self.store.request_review(p)
        self.assertEqual(len(self.store.reviews()), 1)

    def test_review_cannot_silently_rebase_stale_account_or_decision(self):
        p = self.review_payload()
        self.fixture.submit(self.fixture.payload())
        with self.assertRaisesRegex(FeedbackError, 'account_version_changed'): self.store.request_review(p)
        p = self.review_payload()
        self.fixture.put(DECISION, {'new': 'publication'})
        with self.assertRaisesRegex(FeedbackError, 'review_snapshot_changed'): self.store.request_review(p)
        self.assertEqual(self.store.reviews(), [])

    def test_claim_after_account_change_requires_explicit_rebind_and_retains_audit(self):
        request = self.store.request_review(self.review_payload())
        original_binding = request['account_version']
        self.fixture.submit(self.fixture.payload())
        with self.assertRaisesRegex(FeedbackError, 'review_account_changed'): self.store.claim_review(request['id'])
        claim = self.store.claim_review(request['id'], rebind_current=True)
        self.assertEqual(claim['status'], 'running')
        self.assertEqual(claim['account_version'], original_binding)
        self.assertEqual(claim['review_account_version'], version(self.root))
        self.assertEqual(claim['rebound_from_account_version'], original_binding)
        self.assertEqual([r['status'] for r in self.store.review_events(request['id'])], ['queued', 'running'])

    def test_completion_requires_analysis_current_sources_and_exact_publication(self):
        self.publish()
        request = self.store.request_review(self.review_payload())
        claim = self.store.claim_review(request['id'])
        for changes, error in [({'analysis_completed': False}, 'invalid_analyst_review_receipt'),
                               ({'conclusions': []}, 'review_conclusion_or_decision_unverified'),
                               ({'email_sent': True}, 'invalid_analyst_review_receipt'),
                               ({'decision_sha256': '0'*64}, 'review_conclusion_or_decision_unverified'),
                               ({'sources': [{'path': DECISION, 'sha256': '0'*64}]}, 'review_sources_unverified')]:
            with self.assertRaisesRegex(FeedbackError, error):
                self.store.finish_review(claim['id'], 'completed', self.receipt(claim, **changes))
        receipt_path = self.receipt(claim)
        with patch('email_brief.render_email', return_value=('Subject', 'Fresh analyst publication', '<p>Fresh analyst publication</p>')):
            self.fixture.put('07_automation/email_briefs/daily_email_brief.html', 'Stale brief')
            with self.assertRaisesRegex(FeedbackError, 'review_publication_unverified'):
                self.store.finish_review(claim['id'], 'completed', receipt_path)
            self.fixture.put('07_automation/email_briefs/daily_email_brief.html', '<p>Fresh analyst publication</p>')
            complete = self.store.finish_review(claim['id'], 'completed', receipt_path)
        self.assertEqual(complete['status'], 'completed')
        self.assertTrue(self.store.reviews()[0]['receipt_verified'])
        self.fixture.put(receipt_path, {'tampered': True})
        self.assertFalse(self.store.reviews()[0]['receipt_verified'])
        with self.assertRaisesRegex(FeedbackError, 'review_already_completed'): self.store.claim_review(claim['id'])

    def test_completion_after_account_change_blocks_and_preserves_request(self):
        self.publish()
        request = self.store.request_review(self.review_payload())
        claim = self.store.claim_review(request['id'])
        receipt = self.receipt(claim)
        self.fixture.submit(self.fixture.payload())
        with self.assertRaisesRegex(FeedbackError, 'review_account_changed'):
            self.store.finish_review(claim['id'], 'completed', receipt)
        current = self.store.reviews()[0]
        self.assertEqual((current['status'], current['blocker']), ('blocked', 'account_changed_during_review'))
        self.assertEqual(current['account_version'], request['account_version'])

    def test_new_plan_version_cannot_complete_against_an_old_publication(self):
        self.publish()
        request = self.store.request_review(self.review_payload())
        claim = self.store.claim_review(request['id'])
        receipt = self.receipt(claim)
        self.fixture.put('05_risk_and_positions/investment_plans.local.json', {'new_plan': 'unpublished amendment'})
        with self.assertRaisesRegex(FeedbackError, 'review_publication_unverified'):
            self.store.finish_review(claim['id'], 'completed', receipt)
        self.assertEqual(self.store.reviews()[0]['status'], 'running')

    def test_blocked_review_requires_dependency_receipt_and_can_resume(self):
        request = self.store.request_review(self.review_payload())
        claim = self.store.claim_review(request['id'])
        with self.assertRaisesRegex(FeedbackError, 'review_dependencies_required'):
            self.store.finish_review(claim['id'], 'blocked', self.receipt(claim, completed=False, dependencies=[]))
        blocked = self.store.finish_review(claim['id'], 'blocked', self.receipt(claim, completed=False))
        self.assertEqual(blocked['status'], 'blocked')
        self.assertTrue(self.store.reviews()[0]['receipt_verified'])
        self.assertEqual(self.store.claim_review(claim['id'])['status'], 'running')

    def test_receipt_and_evidence_cannot_escape_runtime_or_follow_a_symlink(self):
        request = self.store.request_review(self.review_payload())
        claim = self.store.claim_review(request['id'])
        for path in ('../../outside.json', '/tmp/outside.json', '04_research/public.json'):
            with self.assertRaisesRegex(FeedbackError, 'invalid_review_receipt_path'):
                self.store.finish_review(claim['id'], 'completed', path)
        self.publish()
        path = self.receipt(claim)
        original = self.root/path
        actual = original.with_name('retained.json')
        original.rename(actual)
        original.symlink_to(actual)
        with self.assertRaisesRegex(FeedbackError, 'unsafe_runtime_path'):
            self.store.finish_review(claim['id'], 'completed', path)


if __name__ == '__main__': unittest.main()
