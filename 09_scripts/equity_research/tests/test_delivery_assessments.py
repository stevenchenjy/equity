from __future__ import annotations

import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR, visible_html_text  # noqa: F401
from daily_common import ET, atomic_write_json, canonical_sha256, sha256_file
from opportunity_contract import AUTHORITY
import delivery_assessments as delivery

NOW = datetime(2026, 10, 22, 11, tzinfo=ET)


def action_row(ticker='SYN', quantity=1):
    return {'ticker': ticker, 'decision': 'ACTIONABLE_BUY', 'shares': quantity,
        'estimated_notional': 100.0 * quantity, 'thesis_summary': 'Synthetic accepted company case.',
        'strategy_source': {'strategy_id': 'synthetic-reviewed', 'version': 1},
        'blockers': [], 'order_draft': {'side': 'buy', 'entry_order_type': 'LIMIT',
            'entry_limit': 100.0, 'entry_window': {'session': '2026-10-22',
                'starts_at': '2026-10-22T09:45:00-04:00', 'ends_at': '2026-10-22T15:30:00-04:00'},
            'time_in_force': 'DAY', 'trigger_rule': 'Synthetic source-bound entry condition.',
            'portfolio_weight_before': 0.0, 'portfolio_weight_after': 2.5,
            'cash_before': 1200.0, 'estimated_cash_after': 1100.0,
            'planned_total_loss': 10.0, 'planned_account_risk_pct': 0.25,
            'risk_model': 'observed_price_invalidation', 'invalidation_price': 90.0,
            'initial_reassessment_price': 120.0, 'invalidation_rule': 'Synthetic primary evidence fails.',
            'reassessment_rule': 'Review by the retained deadline.',
            'cancel_conditions': ['Skip if the current quote exceeds the limit.'],
            'cost_assumption': 'Synthetic no-cost fixture; not an execution observation.'}}


class DeliveryAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {'notifications': {'mandatory_daily_briefs': True, 'intraday_alerts_enabled': True,
            'delivery_assessment_effective_from': '2026-10-22', 'delivery_windows_et': [
                {'id': 'morning', 'start': '09:30', 'end': '10:30', 'refresh_not_before': '08:00'},
                {'id': 'afternoon', 'start': '14:30', 'end': '15:05', 'refresh_not_before': '13:30'}]}}
        atomic_write_json(self.root / delivery.CONFIG_REL, self.config)
        for relative in delivery.REQUIRED_PRIORITY_INPUTS:
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}' if relative.endswith('.json') else 'ticker,shares\nSYN,1\n')
        self.decision = {'generated_at': NOW.isoformat(), 'cycle_date': NOW.date().isoformat(),
            'assessment_delivery_policy': delivery.delivery_policy_context(self.root),
            'analyst_priority_review': delivery.priority_review_context(self.root, NOW),
            'capital_decision': {'decisions': [], 'market_data_timestamp': '2026-10-21'},
            'boundaries': {'broker_connected': False, 'broker_account_read': False,
                'order_code_created': False, 'trade_placed': False}}
        atomic_write_json(self.root / delivery.DECISION_REL, self.decision)

    def eligible(self, decision=None, rows=None, current=NOW, mode='intraday_alert', slot=None):
        with patch.object(delivery, 'validate_current_publication'):
            return delivery.delivery_eligibility(decision or self.decision, root=self.root,
                current=current, rows=rows or [], mode=mode, scheduled_slot=slot)

    def archive(self, decision=None, status='sent', stamp=None, reason=''):
        d = decision or self.decision
        from capital_presentation import action_lines
        if d.get('schema_version') == 'equity_mandatory_status_brief_v1':
            _, text, document = delivery.render_failure_brief(d)
        elif 'delivery_assessment' in d:
            _, text, document = delivery.render_intraday_alert(d)
        else:
            lines = ['Synthetic delivered report']
            labels = {'ACTIONABLE_BUY': 'BUY', 'ACTIONABLE_ADD': 'ADD', 'REDUCE_REVIEW': 'REDUCE REVIEW', 'EXIT_REVIEW': 'EXIT REVIEW'}
            for row in d.get('capital_decision', {}).get('decisions', []):
                if row.get('order_draft'):
                    lines += [labels[row['decision']] + ' — ' + row['ticker'], *action_lines(row)]
            for entry in d.get('analyst_priority_review', {}).get('entries', []):
                lines += [entry['ticker'], entry['reason'], entry['next_step']]
            text = '\n'.join(lines)
            import html
            document = '<body>' + ''.join('<p>' + html.escape(line) + '</p>' for line in lines) + '</body>'
        contents = [('decision_sha256', '.json', json.dumps(d, sort_keys=True).encode()),
            ('brief_text_sha256', '.txt', text.encode()), ('brief_html_sha256', '.html', document.encode())]
        result = {'timestamp': (stamp or NOW - timedelta(hours=1)).isoformat(),
            'cycle_date': NOW.date().isoformat(), 'status': status, 'reason': reason}
        for key, suffix, raw in contents:
            digest = hashlib.sha256(raw).hexdigest(); path = self.root / delivery.ARCHIVE_REL / (digest + suffix)
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw); result[key] = digest
        return result

    def priority_proposal(self, tickers=('SYN',), current=NOW):
        source = self.root / '08_reviews/synthetic-primary.json'
        source.parent.mkdir(parents=True, exist_ok=True); source.write_text('{"synthetic_fact":1}')
        receipt = {'path': str(source.relative_to(self.root)), 'sha256': sha256_file(source),
            'available_at': (current - timedelta(minutes=1)).isoformat(), 'source_url': 'https://www.sec.gov/Archives/synthetic'}
        return {'schema_version': 'equity_research_priority_review_v1', 'reviewed_at': current.isoformat(),
            'next_review_at': (current + timedelta(hours=3)).isoformat(), 'reviewer': 'Synthetic analyst',
            'change_basis': 'completed_analysis', 'review_summary': 'Prioritize a sourced unresolved earnings gap.',
            'basis_decision_sha256': sha256_file(self.root / delivery.DECISION_REL),
            'entries': [{'ticker': ticker, 'reason': ticker + ' has a decision-relevant source-bound gap.',
                'next_step': 'Complete the company-specific downside case.', 'sources': [receipt]} for ticker in tickers], **AUTHORITY}

    def test_mandatory_briefs_each_window_even_unchanged_and_owner_alert_do_not_replace_checkpoint(self):
        morning = datetime(2026, 10, 22, 9, 45, tzinfo=ET)
        owner = self.archive(status='owner_review_sent', stamp=morning - timedelta(hours=1))
        result = self.eligible(rows=[owner], current=morning, mode='scheduled_brief', slot='morning')
        self.assertTrue(result['eligible']); self.assertFalse(result['purpose_completed'])
        sent = self.archive(stamp=morning, reason=delivery.PURPOSE_MARKER + result['purpose_key'] + ';scheduled_slot=morning')
        again = self.eligible(rows=[owner, sent], current=morning + timedelta(minutes=1), mode='scheduled_brief', slot='morning')
        self.assertFalse(again['eligible']); self.assertTrue(again['purpose_completed'])
        afternoon = self.eligible(rows=[owner, sent], current=NOW.replace(hour=14, minute=45), mode='scheduled_brief', slot='afternoon')
        self.assertTrue(afternoon['eligible'])

    def test_quiet_initial_and_identical_repeat_quote_score_clock_and_queue_changes(self):
        self.assertEqual(self.eligible()['reason'], 'initial_alert_baseline_quiet')
        row = self.archive()
        newer = copy.deepcopy(self.decision)
        newer.update(generated_at=(NOW + timedelta(minutes=1)).isoformat(),
            independent_market_discovery={'top_stocks': [{'ticker': 'RAW', 'score': 999}]},
            research_backlog={'priority_queue': [{'ticker': 'RAW'}]}, account={'marked_total': 9000})
        self.assertFalse(self.eligible(newer, [row])['eligible'])

    def test_new_action_alert_and_latest_only_a_b_a(self):
        a = self.archive()
        b = copy.deepcopy(self.decision); b['capital_decision']['decisions'] = [action_row()]
        first = self.eligible(b, [a]); self.assertTrue(first['eligible'])
        bsent = self.archive(b, stamp=NOW - timedelta(minutes=20))
        changed_back = copy.deepcopy(self.decision)
        changed_back['capital_decision']['decisions'] = [{'ticker': 'SYN', 'decision': 'NO_ACTION',
            'shares': 0, 'order_draft': None, 'blockers': ['primary_thesis_invalidated']}]
        reverse = self.eligible(changed_back, [a, bsent])
        self.assertTrue(reverse['eligible']); self.assertEqual(reverse['removed_action_tickers'], ['SYN'])
        self.assertNotEqual(first['purpose_key'], reverse['purpose_key'])
        self.assertFalse(self.eligible(b, [a, bsent])['eligible'])

    def test_expiry_alone_does_not_send_withdrawal(self):
        before = copy.deepcopy(self.decision); before['capital_decision']['decisions'] = [action_row()]
        sent = self.archive(before)
        after = copy.deepcopy(self.decision); after['capital_decision']['decisions'] = [
            {'ticker': 'SYN', 'decision': 'BLOCKED', 'shares': 0, 'order_draft': None, 'blockers': ['review_due']}]
        self.assertFalse(self.eligible(after, [sent])['eligible'])

    def test_unknown_claim_missing_or_corrupt_any_archive_body_blocks_extra(self):
        for status in ('send_claimed', 'delivery_unknown', 'owner_review_delivery_unknown'):
            with self.subTest(status=status):
                row = self.archive(status=status)
                self.assertFalse(self.eligible(rows=[row])['eligible'])
                self.assertIn('existing_', self.eligible(rows=[row])['reason'])
        row = self.archive()
        path = self.root / delivery.ARCHIVE_REL / (row['brief_html_sha256'] + '.html')
        path.write_text('corrupt')
        self.assertEqual(self.eligible(rows=[row])['reason'], 'latest_delivery_archive_unverified')

    def test_matching_sent_resolves_claim_but_other_purpose_does_not(self):
        claimed = self.archive(status='send_claimed', reason='scheduled_slot=morning')
        sent = {**claimed, 'timestamp': (NOW - timedelta(minutes=59)).isoformat(), 'status': 'sent'}
        self.assertEqual(self.eligible(rows=[claimed, sent])['reason'], 'unchanged_action_and_priority')
        wrong = {**sent, 'reason': 'scheduled_slot=afternoon'}
        self.assertEqual(self.eligible(rows=[claimed, wrong])['reason'], 'existing_send_claimed')

    def test_market_holiday_weekend_and_early_close(self):
        row = self.archive()
        for current in [NOW.replace(hour=9, minute=29), NOW.replace(hour=16),
                datetime(2026, 10, 24, 11, tzinfo=ET), datetime(2026, 11, 26, 11, tzinfo=ET),
                datetime(2026, 11, 27, 13, tzinfo=ET)]:
            with self.subTest(current=current):
                self.assertFalse(self.eligible(rows=[row], current=current)['eligible'])
        self.assertTrue(delivery.market_session_open(datetime(2026, 11, 27, 12, 59, tzinfo=ET)))

    def test_priority_writer_source_history_recompose_and_substantive_alert_without_trade(self):
        baseline = self.archive()
        proposal = self.priority_proposal()
        self.assertEqual(delivery.apply_priority_review(self.root, proposal, current=NOW)['status'], 'validated')
        self.assertFalse((self.root / delivery.STORE_REL).exists())
        result = delivery.apply_priority_review(self.root, proposal, current=NOW, apply=True)
        self.assertEqual(result['status'], 'recorded')
        context = delivery.priority_review_context(self.root, NOW)
        self.assertEqual(context['status'], 'current')
        new = copy.deepcopy(self.decision); new['analyst_priority_review'] = context
        eligibility = self.eligible(new, [baseline])
        self.assertTrue(eligibility['eligible']); self.assertTrue(eligibility['priority_changed'])
        self.assertFalse(eligibility['action_changed'])
        atomic_write_json(self.root / delivery.DECISION_REL, new)
        self.assertEqual(delivery.priority_review_context(self.root, NOW)['status'], 'current')
        self.assertEqual(delivery.apply_priority_review(self.root, proposal, current=NOW, apply=True)['status'], 'already_recorded')
        sent = self.archive(new, stamp=NOW)
        self.assertFalse(self.eligible(new, [baseline, sent], current=NOW + timedelta(minutes=1))['eligible'])
        retained = self.root / context['entries'][0]['sources'][0]['path']
        retained.write_text('corrupt primary bytes')
        self.assertEqual(delivery.priority_review_context(self.root, NOW)['status'], 'unverified')

    def test_priority_top_three_authority_clocks_and_changed_account(self):
        proposal = self.priority_proposal(('ONE', 'TWO', 'THREE'))
        for mutate in [lambda p: p.update(capital_authority=True),
                lambda p: p.update(reviewed_at=(NOW + timedelta(minutes=1)).isoformat()),
                lambda p: p['entries'].append(copy.deepcopy(p['entries'][0])),
                lambda p: p['entries'][0]['sources'][0].update(sha256='0' * 64)]:
            bad = copy.deepcopy(proposal); mutate(bad)
            with self.assertRaises((ValueError, KeyError)):
                delivery.apply_priority_review(self.root, bad, current=NOW)
        delivery.apply_priority_review(self.root, proposal, current=NOW, apply=True)
        account = self.root / '05_risk_and_positions/current_account_state.local.json'
        account.write_text('{"cash_available":99}')
        self.assertEqual(delivery.priority_review_context(self.root, NOW)['status'], 'inputs_changed')

    def test_failure_briefs_truthful_missing_pending_failed_and_no_stale_trade_context(self):
        morning = NOW.replace(hour=9, minute=45)
        cases = [None, {'cycle_date': '2026-10-21', 'started_at': '2026-10-21T08:00:00-04:00', 'outcome': 'failed'},
            {'cycle_date': '2026-10-22', 'started_at': '2026-10-22T08:00:00-04:00'},
            {'cycle_date': '2026-10-22', 'started_at': '2026-10-22T08:00:00-04:00',
                'completed_at': '2026-10-22T09:00:00-04:00', 'outcome': 'failed'}]
        expected = ['missing_current_window_handoff', 'missing_current_window_handoff', 'current_refresh_pending', 'current_refresh_failed']
        for state, status in zip(cases, expected):
            with self.subTest(status=status):
                path = self.root / delivery.REFRESH_REL
                if state is not None: atomic_write_json(path, state)
                artifact = delivery.build_failure_brief(self.root, morning, 'morning', 'refresh_not_ready')
                self.assertEqual(artifact['status'], status)
                self.assertNotIn('capital_decision', artifact); self.assertNotIn('held_positions', artifact)
                self.assertEqual(delivery.validate_failure_brief(artifact, root=self.root, current=morning), artifact)
                self.assertTrue(self.eligible(artifact, current=morning, mode='scheduled_brief', slot='morning')['eligible'])
                bad = copy.deepcopy(artifact); bad['order_draft'] = {'quantity': 1}
                with self.assertRaises(ValueError):delivery.validate_failure_brief(bad, root=self.root, current=morning)
        artifact = delivery.build_failure_brief(self.root, morning, 'morning', 'refresh_not_ready')
        atomic_write_json(self.root / delivery.REFRESH_REL, {'new_current_fact': True})
        with self.assertRaises(ValueError):delivery.validate_failure_brief(artifact, root=self.root, current=morning)

    def test_alert_envelope_exact_action_render_scope_and_original_archive(self):
        baseline = self.archive()
        current = copy.deepcopy(self.decision); current['capital_decision']['decisions'] = [action_row()]
        original = self.archive(current, stamp=NOW - timedelta(minutes=10))
        eligibility = self.eligible(current, [baseline])
        envelope = delivery.delivery_envelope(current, eligibility, canonical_decision_sha256=original['decision_sha256'])
        enriched = {**current, 'delivery_assessment': envelope}
        self.assertEqual(delivery.validate_envelope(enriched), envelope)
        subject, text, document = delivery.render_intraday_alert(enriched)
        from capital_presentation import action_lines
        self.assertIn('BUY — SYN', text)
        for line in action_lines(action_row()):
            self.assertIn(line, text); self.assertIn(line, visible_html_text(document))
        sent = self.archive(enriched, stamp=NOW)
        self.assertEqual(delivery.latest_receipt_baseline([sent], root=self.root, current=NOW)['status'], 'verified')
        for changes in [{'changed_action_tickers': ['OTHER']}, {'removed_action_tickers': ['SYN']}, {'arbitrary': True}]:
            bad = copy.deepcopy(enriched); bad['delivery_assessment'].update(changes)
            bad['delivery_assessment']['envelope_sha256'] = canonical_sha256({k: v for k, v in bad['delivery_assessment'].items() if k != 'envelope_sha256'})
            with self.assertRaises(ValueError):delivery.validate_envelope(bad)

    def test_verified_contiguous_status_briefs_do_not_acknowledge_or_retract_advice(self):
        action = copy.deepcopy(self.decision); action['capital_decision']['decisions'] = [action_row()]
        sent = self.archive(action, stamp=NOW - timedelta(hours=2))
        artifact = delivery.build_failure_brief(self.root, NOW - timedelta(hours=1), 'morning', 'refresh_not_ready')
        status_sent = self.archive(artifact, stamp=NOW - timedelta(minutes=59),
            reason='scheduled_slot=morning')
        status_claim = {**status_sent, 'status': 'send_claimed',
            'timestamp': (NOW - timedelta(hours=1)).isoformat()}
        # Historical proof uses retained typed fields, not today's changed refresh state.
        atomic_write_json(self.root / delivery.REFRESH_REL, {'new_current_refresh': True})
        again = self.eligible(action, [sent, status_claim, status_sent])
        self.assertEqual(again['reason'], 'unchanged_action_and_priority')
        changed = copy.deepcopy(action); changed['capital_decision']['decisions'] = [action_row(quantity=2)]
        self.assertTrue(self.eligible(changed, [sent, status_claim, status_sent])['eligible'])
        baseline = delivery.latest_receipt_baseline([sent, status_claim, status_sent], root=self.root, current=NOW)
        self.assertEqual(baseline['receipt_sha256'], canonical_sha256(status_sent))
        self.assertEqual(baseline['advice_receipt_sha256'], canonical_sha256(sent))
        # A typed checkpoint is not enough to seed advice; every skipped archive is verified.
        self.assertEqual(self.eligible(action, [status_sent])['reason'], 'initial_alert_baseline_quiet')
        (self.root / delivery.ARCHIVE_REL / (status_sent['brief_html_sha256'] + '.html')).write_text('corrupt')
        self.assertEqual(self.eligible(action, [sent, status_sent])['reason'], 'latest_delivery_archive_unverified')

    def test_priority_survives_real_calendar_repoll_and_generated_valuation_but_not_real_changes(self):
        from earnings_events import POLICY_REL, EVENTS_REL, refresh_events
        from daily_common import ROOT
        from test_earnings_events import feed, row
        policy_path = self.root / POLICY_REL
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_bytes((ROOT / POLICY_REL).read_bytes())
        model = self.root / '04_data/equity_research/valuation_research_inputs.local.json'
        atomic_write_json(model, {'models': [{'ticker': 'SYN', 'fair_value': 125}]})
        def refresh(current, session='time-after-hours'):
            return refresh_events(self.root, current=current, clock=lambda: current,
                fetcher=lambda day, _: feed(day, [row('SYN', session)] if day == NOW.date() else []))
        refresh(NOW - timedelta(minutes=2))
        proposal = self.priority_proposal()
        delivery.apply_priority_review(self.root, proposal, current=NOW, apply=True)
        store_bytes = (self.root / delivery.STORE_REL).read_bytes()
        # The actual append-only store holds references; another valid scan must
        # preserve logical meaning while original receipt clocks remain immutable.
        index = json.loads((self.root / EVENTS_REL).read_text())
        self.assertTrue(index['scans'][0].get('path')); self.assertNotIn('dates', index['scans'][0])
        refresh(NOW + timedelta(minutes=1))
        atomic_write_json(self.root / '04_data/equity_research/valuation_inputs.local.json',
            {'prepared_at_utc': (NOW + timedelta(minutes=1)).isoformat(), 'bundle_sha256': 'new generated projection'})
        self.assertEqual(delivery.priority_review_context(self.root, NOW + timedelta(minutes=1))['status'], 'current')
        self.assertEqual((self.root / delivery.STORE_REL).read_bytes(), store_bytes)
        refresh(NOW + timedelta(minutes=2), session='time-pre-market')
        self.assertEqual(delivery.priority_review_context(self.root, NOW + timedelta(minutes=2))['status'], 'inputs_changed')
        # Source integrity is independently effective even if a summary were unchanged.
        index = json.loads((self.root / EVENTS_REL).read_text())
        scan = json.loads((self.root / index['scans'][0]['path']).read_text())
        actual = next(day['source']['path'] for day in scan['dates'] if day['events'])
        (self.root / actual).write_text('corrupt source bytes')
        self.assertEqual(delivery.priority_review_context(self.root, NOW + timedelta(minutes=2))['status'], 'unverified')

    def test_durable_valuation_assumption_change_invalidates_priority(self):
        model = self.root / '04_data/equity_research/valuation_research_inputs.local.json'
        atomic_write_json(model, {'fair_value': 125})
        delivery.apply_priority_review(self.root, self.priority_proposal(), current=NOW, apply=True)
        atomic_write_json(model, {'fair_value': 130})
        self.assertEqual(delivery.priority_review_context(self.root, NOW)['status'], 'inputs_changed')

    def test_priority_survives_rss_channel_clock_but_changed_news_and_corruption_are_effective(self):
        from official_news import MANIFEST_PATH, load_manifest, refresh_news
        from test_official_news import SOURCE, feed
        manifest = load_manifest(MANIFEST_PATH); manifest['sources'] = [SOURCE]
        manifest_path = self.root / '01_policies/synthetic_official_news.json'
        atomic_write_json(manifest_path, manifest)
        status_path = self.root / '03_source_data/equity_research/official_news_status.local.json'
        events_path = self.root / '03_source_data/equity_research/official_news_events.local.json'
        def refresh(current, channel_clock, title='Results'):
            payload = feed(title=title, date='Thu, 22 Oct 2026 12:00:00 GMT').replace(b'<channel>',
                ('<channel><lastBuildDate>' + channel_clock + '</lastBuildDate>').encode())
            return refresh_news(now=current, manifest_path=manifest_path, status_path=status_path,
                events_path=events_path, fetcher=lambda *_: payload)
        refresh(NOW - timedelta(minutes=1), 'one')
        delivery.apply_priority_review(self.root, self.priority_proposal(), current=NOW, apply=True)
        old_response = json.loads(status_path.read_text())['sources'][0]['response_sha256']
        refresh(NOW + timedelta(minutes=1), 'two')
        self.assertNotEqual(json.loads(status_path.read_text())['sources'][0]['response_sha256'], old_response)
        self.assertEqual(delivery.priority_review_context(self.root, NOW + timedelta(minutes=1))['status'], 'current')
        refresh(NOW + timedelta(minutes=2), 'three', title='Material new outlook')
        self.assertEqual(delivery.priority_review_context(self.root, NOW + timedelta(minutes=2))['status'], 'inputs_changed')
        current_events = json.loads(events_path.read_text()); current_events['events'][0]['title'] = 'tampered'
        atomic_write_json(events_path, current_events)
        self.assertEqual(delivery.priority_review_context(self.root, NOW + timedelta(minutes=2))['status'], 'unverified')


if __name__ == '__main__':
    unittest.main()
