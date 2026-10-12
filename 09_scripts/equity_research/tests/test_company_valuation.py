from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import PROJECT_ROOT, visible_html_text
from test_valuation_input_bundle import _bundle, _write_bundle
from test_thesis_evidence import fixture, PERIOD, ACCESSION
import company_valuation as models
from daily_common import read_json, sha256_file
from thesis_evidence import SCHEMA as THESIS_SCHEMA, STORE_REL as THESIS_REL, seal_review, validate_review, evaluate_thesis
from valuation_input_bundle import seal_bundle, validate_and_materialize_bundle
from valuation_research_inputs import company_projection_record

CURRENT = datetime.fromisoformat('2026-10-12T12:00:00+00:00')


def write_json(root, relative, document):
    path = root/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2)+'\n')


def write_csv(root, relative, rows):
    path = root/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


class CompanyValuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        thesis, self.context = fixture(self.root)
        bundle = _bundle(self.root, 'ABC')
        original = bundle['records'][0]
        for source in original['sources']:
            source['accepted_at_utc'] = '2026-10-09T20:00:00Z'
        for value in original['inputs'].values():
            value['available_at_utc'] = '2026-10-09T20:00:00Z'
        original['inputs']['share_price']['period'] = '2026-10-09'
        scenario = next(s for s in original['sources'] if s['source_type'] == 'human_valuation_scenario')
        prices = {'cases': [{'case': c, 'price': p} for c, p in [('bear', 8), ('base', 15), ('bull', 20)]]}
        text = json.dumps(prices)
        (self.root/scenario['relative_path']).write_text(text)
        scenario.update(char_end=len(text), content_sha256=hashlib.sha256(text.encode()).hexdigest())
        bundle = seal_bundle(bundle)
        self.model_rel = '04_data/equity_research/valuation_source_ABC-model.local.json'
        _write_bundle(self.root/self.model_rel, bundle)
        thesis.update(reviewed_at=CURRENT.isoformat(), next_review_at=(CURRENT+timedelta(days=7)).isoformat())
        thesis['valuation']['status'] = 'reviewed_scenarios'
        thesis['valuation_model'] = {'relative_path': self.model_rel, 'sha256': sha256_file(self.root/self.model_rel),
            'assumptions_reason': 'Reviewed company cash-generation cases with explicit uncertainty.',
            'countercase_reason': 'Compensation and future growth durability can impair per-share economics.',
            'claim_ids': ['growth', 'dilution']}
        self.thesis = seal_review(thesis)
        validate_review(self.thesis, self.root, self.context, CURRENT.isoformat(), admission=True)
        write_json(self.root, THESIS_REL, {'schema_version': THESIS_SCHEMA, 'records': [self.thesis]})
        self.policy = read_json(PROJECT_ROOT/models.POLICY_REL)
        write_json(self.root, models.POLICY_REL, self.policy)
        self.fact = {'ticker': 'ABC', 'latest_period_end': PERIOD, 'ttm_period_end': PERIOD,
            'data_quality': 'ok', 'valuation_input_quality': 'complete', 'selection_version': 'period_bound_companyfacts_v2',
            'diluted_shares_latest': '100', 'cash_latest': '200', 'debt_latest': '100',
            'ttm_revenue': '400', 'ttm_free_cash_flow': '40', 'ttm_revenue_yoy_pct': '20',
            'ttm_free_cash_flow_margin_pct': '10', 'share_dilution_pct': '25'}
        self.fact['field_provenance_json'] = json.dumps({field: {'status': 'available', 'end': PERIOD,
            'unit': unit, 'val': self.fact[field], 'available_at_utc': '2026-08-01T20:00:00Z'}
            for field, unit in [('cash_latest', 'USD'), ('debt_latest', 'USD'), ('ttm_revenue', 'USD'), ('diluted_shares_latest', 'shares')]})
        self.quote = {'ticker': 'ABC', 'last_price': '10', 'market_session_date': '2026-10-09',
            'data_quality_label': 'ok', 'data_timestamp': '2026-10-09T20:00:00Z'}
        write_csv(self.root, '03_source_data/equity_research/daily_fundamentals.csv', [self.fact])
        write_csv(self.root, '03_source_data/equity_research/market_data_snapshot.csv', [self.quote])
        write_csv(self.root, '04_research/company_research/current_research_baseline.csv', [{'ticker': 'ABC', 'research_role': 'company_research_candidate'}])
        self.record = models.template(self.root, 'ABC', CURRENT)
        self.record.update(case_id='abc-production-case-1', reviewer='source-bound analyst',
            method='Equity forward free-cash-flow sensitivity', horizon='Next four reported quarters',
            scenario_prices={'bear': '8', 'base': '15', 'bull': '20'},
            case_citations={c: {'source_id': scenario['source_id'], 'json_pointer': f'/cases/{i}/price'}
                for i, c in enumerate(('bear', 'base', 'bull'))},
            allocation_judgment='No allocation inferred; a separate supported current plan is required.')
        self.record = models.seal(self.record)
        self.store = {'schema_version': models.SCHEMA, 'records': [self.record]}
        self.comparator = {'ticker': 'ABC', 'status': 'complete', 'scenario_prices': {'bear': 3, 'base': 5, 'bull': 7}}
        self.baseline = [{'ticker': 'ABC', 'research_role': 'company_research_candidate', 'valuation_reasonableness_score': '3'}]

    def views(self, *args):
        store = read_json(self.root/THESIS_REL)
        view = evaluate_thesis(store, 'ABC', CURRENT.isoformat(), self.root, context=self.context,
            incorporation={'status': 'incorporated', 'latest_report_period_end': PERIOD, 'latest_material_accession': ACCESSION})
        view['news_review'] = {'status': 'current', 'coverage_complete': True}
        return {'ABC': view}

    def project(self, *, current=CURRENT, views=None):
        write_json(self.root, models.STORE_REL, self.store)
        with patch.object(models, 'current_views', return_value=views or self.views()):
            return models.apply_company_models(root=self.root, scenarios=[deepcopy(self.comparator)],
                baseline=self.baseline, fundamentals={'ABC': self.fact}, market={'ABC': self.quote}, current=current)

    def test_original_review_source_and_cases_are_admitted_over_generic_comparator(self):
        rows, report = self.project()
        row = rows[0]
        self.assertEqual(report['records'][0]['status'], 'admitted_current')
        self.assertEqual(row['scenario_prices'], {'bear': 8., 'base': 15., 'bull': 20.})
        self.assertEqual((row['expected_upside_pct'], row['reward_to_risk']), (50, 2.5))
        self.assertEqual(row['policy_comparator'], self.comparator)
        self.assertEqual(self.baseline[0]['valuation_reasonableness_score'], '7')
        self.assertFalse(row['automatic_action_allowed'])

    def test_no_opt_in_preserves_existing_behavior(self):
        rows, report = models.apply_company_models(root=self.root, scenarios=[self.comparator], baseline=self.baseline,
            fundamentals={'ABC': self.fact}, market={'ABC': self.quote}, current=CURRENT)
        self.assertEqual(rows, [self.comparator]); self.assertEqual(report['status'], 'absent')

    def test_reprojection_changes_only_current_observation_and_preserves_original_bytes(self):
        original_bytes = (self.root/self.model_rel).read_bytes()
        self.quote['last_price'] = '11'
        write_csv(self.root, '03_source_data/equity_research/market_data_snapshot.csv', [self.quote])
        rows, _ = self.project()
        self.assertEqual(rows[0]['scenario_prices']['base'], 15)
        self.assertEqual(rows[0]['reward_to_risk'], 1.33)
        old = read_json(self.root/self.model_rel)
        old['records'][0]['inputs']['target_price_assumption']['value'] = '5'
        derived = models.compose_admitted_inputs(old, rows, root=self.root, market={'ABC': self.quote})
        receipts, _ = validate_and_materialize_bundle(derived, packet_as_of=CURRENT.isoformat(), active_tickers={'ABC'}, project_root=self.root)
        receipt = next(r for r in receipts if r['ticker'] == 'ABC')
        values = {r['input_id']: r['value'] for r in receipt['input_receipts']}
        self.assertEqual(float(values['target_price_assumption']), 15)
        self.assertEqual(float(values['share_price']), 11)
        derived_record = next(r for r in derived['records'] if r['ticker'] == 'ABC')
        self.assertTrue(company_projection_record(derived_record))
        self.assertEqual((self.root/self.model_rel).read_bytes(), original_bytes)

    def test_expired_opt_in_never_falls_back_to_generic(self):
        rows, report = self.project(current=CURRENT+timedelta(days=7))
        self.assertEqual(rows[0]['status'], 'insufficient')
        self.assertNotIn('scenario_prices', rows[0])
        self.assertEqual(rows[0]['policy_comparator'], self.comparator)
        self.assertIn('review_due', report['records'][0]['reason'])

    def test_changed_model_bytes_keep_real_failure(self):
        path = self.root/self.model_rel; path.write_bytes(path.read_bytes()+b' ')
        rows, report = self.project()
        self.assertEqual(rows[0]['status'], 'insufficient')
        self.assertTrue(report['records'][0]['reason'])

    def test_wrong_case_pointer_fails_even_with_resealed_record(self):
        record = deepcopy(self.record); record['case_citations']['bull']['json_pointer'] = '/cases/0/price'
        self.store['records'] = [models.seal(record)]
        self.assertIn('case_source_mismatch:bull', self.project()[1]['records'][0]['reason'])

    def test_missing_or_changed_financial_facts_do_not_get_completed_by_model(self):
        for field, value in [('debt_latest', ''), ('ttm_free_cash_flow', '39'), ('latest_period_end', '2026-09-30')]:
            old = self.fact[field]; self.fact[field] = value
            rows, report = self.project()
            self.assertEqual(rows[0]['status'], 'insufficient'); self.assertEqual(report['status'], 'degraded')
            self.fact[field] = old

    def test_changed_thesis_or_unreviewed_news_reopens_only_issuer(self):
        for field, value in [('reopen_reasons', ['new_material_filing_not_reviewed']), ('news_review', {'status': 'pending', 'coverage_complete': True})]:
            views = self.views(); views['ABC'][field] = value
            self.assertEqual(self.project(views=views)[0][0]['status'], 'insufficient')
        views = self.views(); views['ABC']['review_record'] = {**self.thesis, 'record_sha256': 'changed'}
        self.assertIn('thesis_version_changed', self.project(views=views)[1]['records'][0]['reason'])

    def test_bad_issuer_does_not_block_other_baseline_research(self):
        self.fact['debt_latest'] = ''
        other = {'ticker': 'XYZ', 'status': 'complete', 'scenario_prices': {'base': 12}}
        write_json(self.root, models.STORE_REL, self.store)
        with patch.object(models, 'current_views', return_value=self.views()):
            rows, _ = models.apply_company_models(root=self.root, scenarios=[self.comparator, other],
                baseline=self.baseline+[{'ticker': 'XYZ'}], fundamentals={'ABC': self.fact}, market={'ABC': self.quote}, current=CURRENT)
        self.assertEqual(next(r for r in rows if r['ticker'] == 'XYZ'), other)
        self.assertEqual(next(r for r in rows if r['ticker'] == 'ABC')['status'], 'insufficient')

    def test_disabled_missing_and_future_policy_cannot_admit(self):
        for change in ({'enabled': False}, {'automatic_action_allowed': True}):
            write_json(self.root, models.POLICY_REL, {**self.policy, **change})
            self.assertEqual(self.project()[0][0]['status'], 'insufficient')
        (self.root/models.POLICY_REL).unlink()
        self.assertEqual(self.project()[0][0]['status'], 'insufficient')
        write_json(self.root, models.POLICY_REL, self.policy)
        self.assertIn('not_yet_effective', self.project(current=CURRENT-timedelta(days=1))[1]['records'][0]['reason'])

    def test_history_version_chain_and_failed_opt_in_packet_suppression(self):
        with patch.object(models, 'current_views', return_value=self.views()):
            updated = models.append({'schema_version': models.SCHEMA, 'records': []}, self.record, root=self.root, current=CURRENT)
        second = models.seal({**self.record, 'version': 2, 'case_id': 'abc-production-case-2', 'supersedes_sha256': self.record['record_sha256']})
        updated['records'].append(second); self.assertEqual(models.validate_store(updated)['ABC']['version'], 2)
        updated['records'][0]['method'] = 'altered without seal'
        with self.assertRaises(ValueError): models.validate_store(updated)
        rows, _ = self.project(current=CURRENT+timedelta(days=7))
        derived = models.compose_admitted_inputs(_bundle(self.root, 'ABC'), rows, root=self.root, market={'ABC': self.quote})
        self.assertEqual(derived['records'], [])

    def test_admission_writer_rejects_fund_route(self):
        write_csv(self.root, '04_research/company_research/current_research_baseline.csv', [{'ticker': 'ABC', 'research_role': 'etf_research_candidate'}])
        with self.assertRaisesRegex(ValueError, 'operating_company_required'):
            models.append({'schema_version': models.SCHEMA, 'records': []}, self.record, root=self.root, current=CURRENT)

    def test_same_inputs_deduplicate_and_expired_observation_preserves_valid_case(self):
        rows, report = self.project()
        models.retain_observations(root=self.root, scenarios=rows, report=report, current=CURRENT)
        models.retain_observations(root=self.root, scenarios=rows, report=report, current=CURRENT+timedelta(minutes=1))
        paths = list((self.root/models.OBSERVATIONS_REL).glob('*.json')); self.assertEqual(len(paths), 1)
        before = paths[0].read_bytes()
        rows, report = self.project(current=CURRENT+timedelta(days=7))
        models.retain_observations(root=self.root, scenarios=rows, report=report, current=CURRENT+timedelta(days=7))
        self.assertEqual(len(list((self.root/models.OBSERVATIONS_REL).glob('*.json'))), 2)
        self.assertEqual(paths[0].read_bytes(), before)
