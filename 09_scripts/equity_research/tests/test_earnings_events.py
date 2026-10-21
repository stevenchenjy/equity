from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ROOT, atomic_write_json, canonical_sha256, sha256_file
from earnings_events import (AUTHORITY, BASE_REL, ENDPOINT, EVENTS_REL, POLICY_REL,
    EarningsError, NoRedirect, event_observations, fetch_date, load_policy,
    notification_meaning, publication_meaning, parse_date, refresh_events, requested_dates, summary,
    validate_event_review)

NOW = datetime(2026, 10, 21, 14, tzinfo=timezone.utc)


def row(ticker='WEAK', session='time-after-hours', fiscal='Sep/2026'):
    return {'symbol': ticker, 'name': 'Example Common Stock', 'time': session,
            'fiscalQuarterEnding': fiscal, 'epsForecast': '$1.00', 'noOfEsts': '4'}


def feed(day, rows=None):
    return json.dumps({'data': {'asOf': day.strftime('%a, %b %d, %Y'),
        'headers': {}, 'rows': [row()] if rows is None else rows},
        'status': {'rCode': 200}, 'message': None}).encode()


class EarningsEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / POLICY_REL).parent.mkdir(parents=True)
        (self.root / POLICY_REL).write_bytes((ROOT / POLICY_REL).read_bytes())
        self.policy = load_policy(self.root)

    def refresh(self, *, now=NOW, fetcher=None):
        return refresh_events(self.root, current=now, clock=lambda: now,
            fetcher=fetcher or (lambda d, p: feed(d, [row()] if d == now.date() else [])))

    def test_independent_universe_and_momentum_no_stock_limit(self):
        many = [row('Z' + str(i)) for i in range(30)]
        result = self.refresh(fetcher=lambda d, p: feed(d, many if d == NOW.date() else []))
        self.assertEqual(len(result['events']), 30)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual({e['ticker'] for e in result['events']}, {r['symbol'] for r in many})
        self.assertTrue(all(e['date_confidence'] == 'exchange_calendar_estimate' for e in result['events']))
        self.assertTrue(all(e['event_at'] is None for e in result['events']))
        self.assertFalse(result['coverage']['full_market_coverage'])
        self.assertFalse(result['coverage']['issuer_confirmation'])
        self.assertTrue(all(result[k] is False for k in AUTHORITY))

    def test_exact_date_session_deadline_and_publication_not_backdated(self):
        result = self.refresh(fetcher=lambda d, p: feed(d, [row('A', 'time-after-hours'),
            row('B', 'time-pre-market'), row('C', 'time-not-supplied')] if d == NOW.date() else []))
        by = {e['ticker']: e for e in result['events']}
        self.assertEqual(by['A']['research_deadline_at'], '2026-10-21T16:00:00-04:00')
        self.assertEqual(by['B']['research_deadline_at'], '2026-10-21T00:00:00-04:00')
        self.assertEqual(by['C']['research_deadline_at'], '2026-10-21T00:00:00-04:00')
        self.assertEqual(by['A']['first_detected_at'], NOW.isoformat())
        self.assertEqual(by['A']['timing'], 'pre_event')
        self.assertEqual(by['B']['status'], 'elapsed_unreviewed')
        self.assertNotIn('published_at', by['A'])

    def test_horizon_requests_all_weekdays_and_failures_do_not_abort_other_dates(self):
        expected = requested_dates(NOW, self.policy)
        called = []
        def fetch(d, p):
            called.append(d)
            if d == expected[1]:
                raise EarningsError('earnings_network_unavailable')
            return feed(d, [row('GOOD')] if d == expected[-1] else [])
        result = self.refresh(fetcher=fetch)
        self.assertEqual(called, expected)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['coverage']['failed_dates'], [expected[1].isoformat()])
        self.assertEqual(result['events'][0]['ticker'], 'GOOD')
        self.assertTrue(all(d.weekday() < 5 for d in called))

    def test_bad_rows_quarantined_not_silent_day_success(self):
        result = self.refresh(fetcher=lambda d, p: feed(d, [row('GOOD'), {'bad': 'row'}]
            if d == NOW.date() else []))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([e['ticker'] for e in result['events']], ['GOOD'])
        self.assertIn(NOW.date().isoformat(), result['coverage']['failed_dates'])

    def test_malformed_or_wrong_date_documents_are_not_empty_success(self):
        for payload in [b'<html>Access denied</html>', b'{}', feed(NOW.date() + timedelta(days=1))]:
            with self.subTest(payload=payload[:30]), self.assertRaises(EarningsError):
                parse_date(payload, NOW.date(), self.policy)
        events, quarantine = parse_date(feed(NOW.date(), []), NOW.date(), self.policy)
        self.assertEqual((events, quarantine), ([], []))

    def test_duplicate_scans_preserve_first_seen_and_raw_hash(self):
        self.refresh()
        first, _ = event_observations(self.root, current=NOW)
        self.refresh(now=NOW + timedelta(hours=1))
        events, coverage = event_observations(self.root, current=NOW + timedelta(hours=1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['event_id'], first[0]['event_id'])
        self.assertEqual(events[0]['first_detected_at'], NOW.isoformat())
        self.assertEqual(events[0]['last_observed_at'], (NOW + timedelta(hours=1)).isoformat())
        before = len(json.loads((self.root / EVENTS_REL).read_text())['scans'])
        self.refresh(now=NOW + timedelta(hours=1))
        self.assertEqual(len(json.loads((self.root / EVENTS_REL).read_text())['scans']), before)

    def test_absence_never_infers_cancellation_and_reschedule_is_conflict(self):
        self.refresh()
        self.refresh(now=NOW + timedelta(hours=1), fetcher=lambda d, p: feed(d, []))
        events, _ = event_observations(self.root, current=NOW + timedelta(hours=1))
        self.assertIn('event_absent_on_latest_scan_not_cancelled', events[0]['blockers'])
        self.assertNotEqual(events[0]['status'], 'cancelled')
        self.refresh(now=NOW + timedelta(hours=2), fetcher=lambda d, p: feed(d, [row()]
            if d == NOW.date() + timedelta(days=1) else []))
        events, _ = event_observations(self.root, current=NOW + timedelta(hours=2))
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e['status'] == 'schedule_conflict' for e in events))

    def test_time_change_keeps_id_and_requires_review(self):
        self.refresh()
        self.refresh(now=NOW + timedelta(hours=1), fetcher=lambda d, p: feed(d,
            [row(session='time-pre-market')] if d == NOW.date() else []))
        events, _ = event_observations(self.root, current=NOW + timedelta(hours=1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['status'], 'schedule_conflict')
        self.assertIn('event_session_changed_requires_confirmation', events[0]['blockers'])

    def test_missing_stale_future_and_changed_source_never_look_ready(self):
        self.assertEqual(event_observations(self.root, current=NOW)[1]['status'], 'missing')
        self.refresh()
        self.assertEqual(event_observations(self.root, current=NOW - timedelta(seconds=1))[1]['status'], 'unverified')
        self.assertEqual(event_observations(self.root, current=NOW + timedelta(hours=25))[1]['status'], 'stale')
        events, _ = event_observations(self.root, current=NOW)
        (self.root / events[0]['sources'][0]['path']).write_text('{}')
        events, coverage = event_observations(self.root, current=NOW)
        self.assertEqual(events, [])
        self.assertEqual(coverage['status'], 'unverified')

    def test_policy_changes_preserve_historical_observation_contract(self):
        self.refresh()
        policy = load_policy(self.root); policy['max_age_hours'] = 23
        atomic_write_json(self.root / POLICY_REL, policy)
        events, coverage = event_observations(self.root, current=NOW)
        self.assertEqual(coverage['status'], 'ready')
        self.assertEqual(events[0]['first_detected_at'], NOW.isoformat())

    def test_late_detection_never_claims_pre_event(self):
        late = NOW.replace(hour=21)
        result = self.refresh(now=late)
        self.assertEqual(result['events'][0]['timing'], 'post_event')
        self.assertEqual(result['events'][0]['status'], 'elapsed_unreviewed')
        self.assertEqual(result['events'][0]['first_detected_at'], late.isoformat())

    def test_network_one_get_no_retry_redirect_or_oversized_payload(self):
        opener = Mock(); opener.open.side_effect = urllib.error.URLError('remote arbitrary text')
        with self.assertRaisesRegex(EarningsError, '^earnings_network_unavailable$'):
            fetch_date(NOW.date(), self.policy, opener=opener)
        self.assertEqual(opener.open.call_count, 1)
        with self.assertRaisesRegex(EarningsError, 'redirect_forbidden'):
            NoRedirect().redirect_request(None)
        response = Mock(); response.status = 200
        response.geturl.return_value = ENDPOINT + '?date=' + NOW.date().isoformat()
        response.read.return_value = b'x' * (self.policy['maximum_response_bytes'] + 1)
        opener = Mock(); opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with self.assertRaisesRegex(EarningsError, 'too_large'):
            fetch_date(NOW.date(), self.policy, opener=opener)

    def test_source_receipt_clock_tampering_is_rejected(self):
        self.refresh()
        doc = json.loads((self.root / EVENTS_REL).read_text()); scanpath = self.root / doc['scans'][0]['path']
        scan = json.loads(scanpath.read_text()); scan['dates'][0]['observed_at'] = (NOW-timedelta(days=1)).isoformat()
        scanpath.write_text(json.dumps(scan))
        self.assertEqual(event_observations(self.root, current=NOW)[1]['status'], 'unverified')

    def event_and_assessment(self):
        self.refresh(); event = event_observations(self.root, current=NOW)[0][0]
        review = {'event_id': event['event_id'], 'expectations_case': 'Consensus source pending.',
            'priced_in_assessment': 'Price needs independent valuation.', 'valuation_case': 'Not admitted.',
            'downside_case': 'Gap loss is not bounded by a limit order.', 'recheck_condition': 'Obtain issuer timing and source-bound case.',
            'sources': event['sources']}
        assessment = {'assessed_at': (NOW+timedelta(minutes=1)).isoformat(),
            'next_review_at': event['research_deadline_at'], 'valuation_status': 'pending',
            'conclusion': 'insufficient_evidence', 'earnings_event_review': review}
        item = {'ticker': event['ticker'], 'state': 'insufficient_evidence', 'blockers': ['valuation_not_completed'],
            'research_started_at': NOW.isoformat(), 'assessment': assessment,
            'observations': [{'evidence': {'event': event}, 'sources': event['sources']}]}
        return event, assessment, item

    def test_event_specific_assessment_distinct_from_dossier_and_generic_review(self):
        event, assessment, item = self.event_and_assessment(); later = NOW+timedelta(minutes=2)
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}):
            view = summary(self.root, current=later)
        self.assertEqual(view['events'][0]['status'], 'reviewed_without_entry')
        self.assertEqual(view['events'][0]['assessment_sha256'], canonical_sha256(assessment))
        del item['assessment']['earnings_event_review']
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}):
            self.assertEqual(summary(self.root, current=later)['events'][0]['status'], 'research_in_progress')
        for key in ('sources', 'downside_case'):
            broken = copy.deepcopy(assessment.get('earnings_event_review', {})); broken[key] = []
            with self.assertRaises(EarningsError):
                validate_event_review(broken, event, root=self.root, current=later, assessed_at=later.isoformat())

    def test_unrelated_calendar_change_preserves_review_but_own_row_change_requires_reassessment(self):
        event, assessment, item = self.event_and_assessment()
        later = NOW + timedelta(minutes=2)
        # A different issuer appears on the same provider date. The original
        # source hash changes, but the assessed issuer's row remains identical.
        self.refresh(now=later, fetcher=lambda d, p: feed(d, [row(), row('OTHER')]
            if d == NOW.date() else []))
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}):
            view = summary(self.root, current=later)
        reviewed = next(e for e in view['events'] if e['ticker'] == event['ticker'])
        self.assertEqual(reviewed['status'], 'reviewed_without_entry')
        self.assertEqual(reviewed['assessment_sha256'], canonical_sha256(assessment))
        changed = row(); changed['epsForecast'] = '$2.00'
        later += timedelta(minutes=1)
        self.refresh(now=later, fetcher=lambda d, p: feed(d, [changed, row('OTHER')]
            if d == NOW.date() else []))
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}):
            view = summary(self.root, current=later)
        target = next(e for e in view['events'] if e['ticker'] == event['ticker'])
        self.assertNotEqual(target['status'], 'reviewed_without_entry')
        self.assertNotIn('assessment_sha256', target)

    def test_completed_pre_event_review_is_not_erased_at_deadline(self):
        event, assessment, item = self.event_and_assessment()
        later = datetime.fromisoformat(event['research_deadline_at']) + timedelta(minutes=1)
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}):
            view = summary(self.root, current=later)
        self.assertEqual(view['events'][0]['status'], 'reviewed_without_entry')
        self.assertIn('earnings_event_review_due', view['events'][0]['blockers'])
        self.assertEqual(notification_meaning(view), [])

    def test_positive_plan_needs_current_capital_event_economics_and_complete_coverage(self):
        event, assessment, item = self.event_and_assessment(); later = NOW+timedelta(minutes=2)
        item['blockers'] = []; assessment['valuation_status'] = 'reviewed'; assessment['conclusion'] = 'supported'
        capital = {'decisions': [{'ticker': event['ticker'], 'decision': 'ACTIONABLE_BUY', 'shares': 1,
            'order_draft': {'entry_limit': 10, 'time_in_force': 'DAY'}}]}
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}), patch('capital_decision.validate') as validator:
            view = summary(self.root, current=later, capital=capital)
            validator.assert_called_once_with(capital, current=later, root=self.root)
            self.assertEqual(view['events'][0]['status'], 'eligible_conditional_plan')
            self.assertEqual(summary(self.root, current=later)['events'][0]['status'], 'reviewed_without_entry')
        self.refresh(now=later, fetcher=lambda d, p: (_ for _ in ()).throw(EarningsError('earnings_network_unavailable')))
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}):
            self.assertNotEqual(summary(self.root, current=later, capital=capital)['events'][0]['status'], 'eligible_conditional_plan')

    def test_failed_or_running_latest_run_cannot_claim_complete_coverage(self):
        self.refresh()
        atomic_write_json(self.root / BASE_REL / 'last_run.json',
            {'started_at': NOW.isoformat(), 'completed_at': None, 'exit_code': None})
        events, coverage = event_observations(self.root, current=NOW)
        self.assertEqual(coverage['status'], 'partial')
        self.assertIn('earnings_latest_run_failed_or_incomplete', events[0]['blockers'])

    def test_forged_capital_cannot_promote_event(self):
        event, assessment, item = self.event_and_assessment()
        item['blockers'] = []; assessment['valuation_status'] = 'reviewed'; assessment['conclusion'] = 'supported'
        fake = {'decisions': [{'ticker': event['ticker'], 'decision': 'ACTIONABLE_BUY', 'shares': 1,
            'order_draft': {'entry_limit': 10, 'time_in_force': 'DAY'}}]}
        with patch('research_opportunities.read_report', return_value={'opportunities': [item]}):
            result = summary(self.root, current=NOW+timedelta(minutes=2), capital=fake)
        self.assertEqual(result['events'][0]['status'], 'reviewed_without_entry')

    def test_publication_meaning_revalidates_raw_source_but_ignores_refetch_clock(self):
        first = self.refresh()
        second = self.refresh(now=NOW+timedelta(minutes=1))
        self.assertEqual(publication_meaning(first), publication_meaning(second))
        raw = self.root / second['events'][0]['sources'][0]['path']
        raw.write_text('{}')
        changed = summary(self.root, current=NOW+timedelta(minutes=2))
        self.assertEqual(changed['status'], 'unverified')
        self.assertNotEqual(publication_meaning(first), publication_meaning(changed))
        self.assertFalse(changed['capital_authority'])

    def test_notification_meaning_ignores_collection_metadata(self):
        self.assertEqual(notification_meaning({'status': 'ready', 'events': [{'status': 'awaiting_research'}]}), [])
        event = {'status': 'reviewed_without_entry', 'timing': 'pre_event', 'event_id': 'id',
                 'assessment_sha256': 'case', 'ticker': 'A', 'next_step': 'Skip pending evidence.', 'blockers': []}
        view = {'status': 'ready', 'events': [event]}
        first = notification_meaning(view)
        event['last_observed_at'] = 'new clock'; view['generated_at'] = 'new scan'
        self.assertEqual(notification_meaning(view), first)
        view['status'] = 'partial'
        self.assertEqual(notification_meaning(view), [])


if __name__ == '__main__':
    unittest.main()
