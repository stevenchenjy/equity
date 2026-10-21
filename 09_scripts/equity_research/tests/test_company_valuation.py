from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
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
    def test_new_private_namespace_does_not_dirty_runtime_preflight(self):
        private = [models.STORE_REL, models.REPORT_REL,
            '04_data/equity_research/company_valuation_admission_history.local/receipt.json',
            models.OBSERVATIONS_REL+'/observation.json',
            '00_project_control/run_logs/company_valuation_admissions.lock']
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--', *private],
            cwd=PROJECT_ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(set(result.stdout.splitlines()), set(private))

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

    def test_maintained_case_survives_next_day_rank_drift_within_existing_data_scope(self):
        import build_current_research_baseline as baseline
        write_json(self.root, '01_policies/long_horizon_research_policy.json',
            read_json(PROJECT_ROOT/'01_policies/long_horizon_research_policy.json'))
        def rows(path):
            if path == baseline.SIGNAL_SCORES_PATH:
                return [{'ticker': t, 'total_score': '9', 'data_quality_label': 'ok'} for t in ('TOP1', 'TOP2', 'TOP3', 'ABC')]
            return []
        with patch.object(baseline, 'ROOT', self.root), patch.object(baseline, 'read_csv', side_effect=rows), \
                patch.object(baseline, 'requested_coverage_tickers', return_value={'SPY'}), \
                patch.object(baseline, 'fundamentals_candidate_queue', return_value=[]), \
                patch.object(baseline, 'APPROVED_CANDIDATE_TICKERS', {'ABC'}):
            first, held = baseline.selected_tickers()
            self.assertIn('ABC', first)
            self.assertEqual(held, set())
            # Next day: rank falls entirely out of both ranked lists. Retain
            # the versioned judgment, including its future reassessment, not
            # a synthetic position/entry plan or a promoted new universe.
            with patch.object(baseline, 'read_csv', return_value=[]):
                second, _ = baseline.selected_tickers()
            self.assertIn('ABC', second)
            self.assertEqual(baseline.retained_company_tickers({'OTHER'}), set())

    def test_recorded_company_case_is_visible_before_admission_without_buy_authority(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case
        from capital_presentation import cards
        view=self.views()['ABC']
        view['news_review']['coverage_complete']=False
        case=presentation_case(view,root=self.root,current=CURRENT,quote=self.quote,
            minimum_reward_to_risk=Decimal('1.25'))
        self.assertEqual(case['scenario_prices'],{'bear':8.,'base':15.,'bull':20.})
        self.assertEqual(case['conclusion'],self.thesis['conclusion'])
        self.assertEqual(case['model_admission_status'],'research_only_pending_admission')
        self.assertIn('configured_issuer_news_coverage_incomplete',case['pending_requirements'])
        row={'ticker':'ABC','decision':'BLOCKED','shares':0,'order_draft':None,
            'research_case':case,'reasons':[case['conclusion']],'blockers':['maintained_company_research_incomplete'],'dependencies':[]}
        from capital_decision import SCHEMA as CAPITAL_SCHEMA
        from daily_common import canonical_sha256
        capital={'schema_version':CAPITAL_SCHEMA,'automatic_action_allowed':False,'broker_connected':False,'order_placed':False,
            'decisions':[row],'dependencies':[],'planning_cash':4000,'mandatory_reserve':0,'global_blockers':[]}
        capital['content_sha256']=canonical_sha256(capital)
        decision={'generated_at':CURRENT.isoformat(),'capital_decision':capital,
            'long_horizon_research': {'candidate_views': {'ABC': view}}}
        result=cards(decision)
        research=next(c for c in result if c['title']=='公司研究与配置判断 — ABC')
        self.assertEqual(research['group'],'background')
        self.assertIn('$8.00 / $15.00 / $20.00',research['body'])
        self.assertIn('当前新增订单股数：0 股',research['body'])
        self.assertIn('不是买入限价或订单',research['body'])
        self.assertFalse(case['automatic_action_allowed'])
        # Exercise the actual final text/HTML renderer, not just its card data.
        # Its source contract is a list of public URLs; private proof objects
        # remain in the source-bound capital record.
        from email_brief import render_email
        from test_email_brief import decision_fixture
        final = decision_fixture()
        final.update(decision)
        final['workflow_integrity']={'schema_version':'equity_workflow_integrity_v1'}
        _, plain, html = render_email(final)
        self.assertIn('$8.00 / $15.00 / $20.00', plain)
        self.assertIn('当前新增订单股数：0 股', html)
        self.assertIn('data-email-group="background"', html)
        self.assertTrue(all(isinstance(url, str) for url in research['sources']))

    def test_invalid_or_expired_research_model_never_acquires_current_display_prices(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case
        view=self.views()['ABC']
        options=dict(root=self.root,current=CURRENT,quote=self.quote,minimum_reward_to_risk=Decimal('1.25'))
        self.assertIsNotNone(presentation_case(view,**options))
        (self.root/self.model_rel).write_text('{}')
        changed = presentation_case(view,**options)
        self.assertIsNone(changed['scenario_prices'])
        self.assertIn('research_model_source_unverified', changed['pending_requirements'])
        expired = presentation_case(view,**{**options,'current':CURRENT+timedelta(days=8)})
        self.assertIsNone(expired['scenario_prices'])
        self.assertEqual(expired['review_status'], 'reassessment_required')
        self.assertIn('scheduled_company_review_due', expired['pending_requirements'])

    def test_verified_cases_remain_visible_when_price_fails_entry_sufficiency(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case
        from capital_decision import SCHEMA as CAPITAL_SCHEMA
        from daily_common import canonical_sha256
        from email_brief import render_email
        from test_email_brief import decision_fixture
        original_policy = deepcopy(self.policy)
        for price in ('20', '15', '5'):
            with self.subTest(observed_price=price):
                bundle = read_json(self.root/self.model_rel)
                record = bundle['records'][0]
                record['inputs']['share_price']['value'] = price
                source = next(s for s in record['sources']
                              if s['source_type'] == 'public_market_valuation_observation')
                text = f'share_price={price}; session=2026-10-09 close'
                (self.root/source['relative_path']).write_text(text)
                source.update(char_end=len(text), content_sha256=hashlib.sha256(text.encode()).hexdigest())
                _write_bundle(self.root/self.model_rel, seal_bundle(bundle))
                self.thesis['valuation_model']['sha256'] = sha256_file(self.root/self.model_rel)
                self.thesis['conclusion'] = 'No additional shares; preserve the original company cases and entry gates.'
                self.thesis = seal_review(self.thesis)
                write_json(self.root, THESIS_REL, {'schema_version': THESIS_SCHEMA, 'records': [self.thesis]})
                self.quote['last_price'] = price
                write_csv(self.root, '03_source_data/equity_research/market_data_snapshot.csv', [self.quote])
                self.record.update(model_sha256=self.thesis['valuation_model']['sha256'],
                                   review_record_sha256=self.thesis['record_sha256'])
                self.record = models.seal(self.record)
                self.store['records'] = [self.record]
                receipts, _ = validate_and_materialize_bundle(read_json(self.root/self.model_rel),
                    packet_as_of=CURRENT.isoformat(), active_tickers={'ABC'}, project_root=self.root)
                self.assertFalse(receipts[0]['sufficiency']['scenario_sufficient'])
                self.assertFalse(receipts[0]['sufficiency']['decision_sufficient'])
                view = self.views()['ABC']
                case = presentation_case(view, root=self.root, current=CURRENT, quote=self.quote,
                    minimum_reward_to_risk=Decimal('1.25'), admission=self.record)
                self.assertEqual(case['scenario_prices'], {'bear': 8., 'base': 15., 'bull': 20.})
                self.assertEqual(case['review_status'], 'current')
                self.assertEqual(case['model_admission_status'], 'admitted_current')
                self.assertFalse(case['automatic_action_allowed'])
                if Decimal(price) >= 15:
                    self.assertLessEqual(case['base_upside_pct'], 0)
                rows_before, _ = self.project()
                if Decimal(price) >= 15:
                    self.assertEqual(rows_before[0]['reward_to_risk'], 0)
                row = {'ticker':'ABC', 'decision':'NO_ACTION', 'shares':0, 'order_draft':None,
                    'research_case':case, 'reasons':[case['conclusion']], 'blockers':[], 'dependencies':[]}
                capital = {'schema_version':CAPITAL_SCHEMA, 'automatic_action_allowed':False,
                    'broker_connected':False, 'order_placed':False, 'decisions':[row], 'dependencies':[],
                    'planning_cash':4000, 'mandatory_reserve':0, 'global_blockers':[]}
                capital['content_sha256'] = canonical_sha256(capital)
                final = decision_fixture()
                final.update(generated_at=CURRENT.isoformat(), capital_decision=capital,
                    long_horizon_research={'candidate_views':{'ABC':view}},
                    workflow_integrity={'schema_version':'equity_workflow_integrity_v1'})
                _, plain, html = render_email(final)
                for rendered in (plain, visible_html_text(html)):
                    self.assertIn('$8.00 / $15.00 / $20.00', rendered)
                    self.assertIn('当前新增订单股数：0 股', rendered)
                    self.assertNotIn('原研究模型需要重新核验', rendered)
                rows_after, _ = self.project()
                self.assertEqual(rows_after, rows_before)
                self.assertEqual(read_json(self.root/models.POLICY_REL), original_policy)

    def test_underlying_scenario_source_corruption_still_hides_display_prices(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case
        view = self.views()['ABC']
        bundle = read_json(self.root/self.model_rel)
        source = next(s for s in bundle['records'][0]['sources']
                      if s['source_type'] == 'human_valuation_scenario')
        # Keep the model-file binding intact but corrupt its referenced source.
        (self.root/source['relative_path']).write_text('{"cases": []}')
        case = presentation_case(view, root=self.root, current=CURRENT, quote=self.quote,
            minimum_reward_to_risk=Decimal('1.25'))
        self.assertIsNone(case['scenario_prices'])
        self.assertIn('research_model_source_unverified', case['pending_requirements'])

    def test_missing_scenario_input_still_hides_display_prices(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case
        view = deepcopy(self.views()['ABC'])
        bundle = read_json(self.root/self.model_rel)
        del bundle['records'][0]['inputs']['target_price_assumption']
        _write_bundle(self.root/self.model_rel, seal_bundle(bundle))
        view['review_record']['valuation_model']['sha256'] = sha256_file(self.root/self.model_rel)
        view['review_record'] = seal_review(view['review_record'])
        case = presentation_case(view, root=self.root, current=CURRENT, quote=self.quote,
            minimum_reward_to_risk=Decimal('1.25'))
        self.assertIsNone(case['scenario_prices'])
        self.assertIn('research_model_source_unverified', case['pending_requirements'])

    def test_partial_no_model_and_reopened_cases_render_exact_zero_reason_without_prices(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case
        from capital_decision import SCHEMA as CAPITAL_SCHEMA
        from daily_common import canonical_sha256
        from email_brief import render_email
        from test_email_brief import decision_fixture
        for reopen in (False, True):
            with self.subTest(reopen=reopen):
                view=deepcopy(self.views()['ABC'])
                view['review_record']['valuation_model']=None
                view['review_record']['valuation'].update(status='unresolved',unresolved=['Acquisition-adjusted cash/debt/share count is required.'])
                view['review_record']['conclusion']='当前不买入 ABC；目标仓位 0%，新增 0 股；并购债务与股数模型未完成。'
                view['conclusion']=view['review_record']['conclusion']
                view['valuation_readiness']='unresolved'
                if reopen:
                    view.update(status='reassess',reopen_reasons=['new_financial_period_not_reviewed'])
                case=presentation_case(view,root=self.root,current=CURRENT,quote=self.quote,minimum_reward_to_risk=Decimal('1.25'))
                self.assertIsNone(case['scenario_prices'])
                self.assertEqual(case['model_admission_status'],'no_completed_model')
                self.assertIn('Acquisition-adjusted cash/debt/share count is required.',case['review_conditions'])
                row={'ticker':'ABC','decision':'BLOCKED','shares':0,'order_draft':None,'research_case':case,
                    'reasons':[case['conclusion']],'blockers':['valuation'],'dependencies':[]}
                capital={'schema_version':CAPITAL_SCHEMA,'automatic_action_allowed':False,'broker_connected':False,'order_placed':False,
                    'decisions':[row],'dependencies':[],'planning_cash':4000,'mandatory_reserve':0,'global_blockers':[]}
                capital['content_sha256']=canonical_sha256(capital)
                decision=decision_fixture()
                decision.update(generated_at=CURRENT.isoformat(),capital_decision=capital,
                    long_horizon_research={'candidate_views':{'ABC':view}},
                    workflow_integrity={'schema_version':'equity_workflow_integrity_v1'})
                _,plain,html=render_email(decision)
                for rendered in (plain,html):
                    self.assertIn('目标仓位 0%',rendered)
                    self.assertIn('Acquisition-adjusted cash/debt/share count is required.',rendered)
                    self.assertIn(case['next_review_at'],rendered)
                    self.assertNotIn('$8.00 / $15.00 / $20.00',rendered)
                    self.assertNotIn('BUY LIMIT',rendered)
                if reopen:
                    self.assertIn('保留的历史判断',plain)
                    self.assertEqual(case['review_status'],'reassessment_required')

    def test_current_case_does_not_reuse_stale_or_missing_completed_quote(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case
        for quote in ({},self.quote|{'market_session_date':'2026-10-08'}):
            case=presentation_case(self.views()['ABC'],root=self.root,current=CURRENT,quote=quote,minimum_reward_to_risk=Decimal('1.25'))
            self.assertIsNone(case['reference_price'])
            self.assertIsNone(case['scenario_prices'])
            self.assertIn('current_completed_close_unverified',case['pending_requirements'])

    def test_held_company_sell_case_cannot_relabel_exit_shares_as_new_buy(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case, case_lines
        case=presentation_case(self.views()['ABC'],root=self.root,current=CURRENT,quote=self.quote,minimum_reward_to_risk=Decimal('1.25'))
        text='\n'.join(case_lines(case,shares=2,order_side='sell'))
        self.assertIn('当前卖出订单草案股数：2 股',text)
        self.assertNotIn('当前新增订单股数：2 股',text)

    def test_retained_fiscal_scenario_share_value_format_displays_verified_bull_only(self):
        from decimal import Decimal
        from company_research_presentation import presentation_case, case_lines
        from capital_decision import SCHEMA as CAPITAL_SCHEMA
        from daily_common import canonical_sha256
        from email_brief import render_email
        from test_email_brief import decision_fixture
        path=self.root/self.model_rel
        original_bundle=read_json(path)
        original_thesis=deepcopy(self.thesis)
        values={'bear':'112.6995768809740764070230371','base':'242.7194268066707844348363187',
                'bull':'363.7757093559210505895754249'}
        for bull_key in ('scenario_share_value_usd','unrecognized_price_field'):
            with self.subTest(bull_key=bull_key):
                bundle=deepcopy(original_bundle)
                row=bundle['records'][0]
                row['inputs']['share_price']['value']='228.52'
                market_source=next(s for s in row['sources'] if s['source_id'] in row['inputs']['share_price']['source_ids'])
                market_text='share_price=228.52; session=2026-10-09 close'
                (self.root/market_source['relative_path']).write_text(market_text)
                market_source.update(char_end=len(market_text),content_sha256=hashlib.sha256(market_text.encode()).hexdigest())
                row['inputs']['downside_price_assumption']['value']=values['bear']
                row['inputs']['target_price_assumption']['value']=values['base']
                source=next(s for s in row['sources'] if s['source_type']=='human_valuation_scenario')
                document={'schema_version':'analyst_company_valuation_scenarios_v1',
                    'forward_window':'Q3 FY2027 through Q2 FY2028, four fiscal quarters.',
                    'valuation_method':'Issuer-definition forward free-cash-flow per share times equity P/FCF.',
                    'scenario_assumptions':[{'case':case,
                        bull_key if case=='bull' else 'scenario_share_value_usd':value}
                        for case,value in values.items()]}
                text=json.dumps(document)
                (self.root/source['relative_path']).write_text(text)
                source.update(char_end=len(text),content_sha256=hashlib.sha256(text.encode()).hexdigest())
                _write_bundle(path,seal_bundle(bundle))
                self.thesis=deepcopy(original_thesis)
                self.thesis['valuation_model']['sha256']=sha256_file(path)
                self.thesis=seal_review(self.thesis)
                write_json(self.root,THESIS_REL,{'schema_version':THESIS_SCHEMA,'records':[self.thesis]})
                case=presentation_case(self.views()['ABC'],root=self.root,current=CURRENT,quote=self.quote,
                    minimum_reward_to_risk=Decimal('1.25'))
                self.assertAlmostEqual(case['scenario_prices']['bear'],float(values['bear']))
                self.assertAlmostEqual(case['scenario_prices']['base'],float(values['base']))
                lines='\n'.join(case_lines(case,shares=0))
                if bull_key=='scenario_share_value_usd':
                    self.assertAlmostEqual(case['scenario_prices']['bull'],float(values['bull']))
                    self.assertIn('$112.70 / $242.72 / $363.78',lines)
                else:
                    self.assertNotIn('bull',case['scenario_prices'])
                    self.assertIn('$112.70 / $242.72 / 未核验',lines)
                capital={'schema_version':CAPITAL_SCHEMA,'automatic_action_allowed':False,'broker_connected':False,'order_placed':False,
                    'decisions':[{'ticker':'ABC','decision':'BLOCKED','shares':0,'order_draft':None,'research_case':case,
                        'reasons':[case['conclusion']],'blockers':['valuation'],'dependencies':[]}],
                    'dependencies':[],'planning_cash':4000,'mandatory_reserve':0,'global_blockers':[]}
                capital['content_sha256']=canonical_sha256(capital)
                final=decision_fixture()
                final.update(generated_at=CURRENT.isoformat(),capital_decision=capital,
                    workflow_integrity={'schema_version':'equity_workflow_integrity_v1'})
                expected='$112.70 / $242.72 / '+('$363.78' if bull_key=='scenario_share_value_usd' else '未核验')
                for rendered in render_email(final)[1:]:
                    self.assertIn(expected,rendered)
                    self.assertNotIn('BUY LIMIT',rendered)

    def test_admitted_case_retains_authored_horizon_and_rejects_changed_proof(self):
        from decimal import Decimal
        from company_research_presentation import admission_details, presentation_case
        _, report=self.project()
        proof=report['records'][0]
        record=admission_details(proof,root=self.root)
        case=presentation_case(self.views()['ABC'],root=self.root,current=CURRENT,quote=self.quote,
            minimum_reward_to_risk=Decimal('1.25'),admission=record)
        self.assertEqual(case['horizon'],'Next four reported quarters')
        self.assertEqual(case['method'],'Equity forward free-cash-flow sensitivity')
        self.assertEqual(case['model_admission_status'],'admitted_current')
        self.assertIsNone(admission_details({**proof,'record_sha256':'0'*64},root=self.root))

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
