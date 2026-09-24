from __future__ import annotations

import copy
import unittest
from datetime import datetime
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from generate_current_status import workflow_health, deployment_health
import run_daily_refresh as refresh


class CurrentWorkflowStatusTests(unittest.TestCase):
    now = datetime.fromisoformat('2026-09-24T18:00:00-04:00')

    def fixture(self):
        return dict(
            decision={'plan_continuity': {'as_of':'2026-09-24T17:50:00-04:00','status':'awaiting_facts',
                'plans':[{'ticker':'APP','plan_id':'app-v1','version':1,'status':'awaiting_broker_verification','action':'exit_review'}],
                'block_new_capital':True,'conflicts':[],'unresolved_tickers':['APP']}},
            long_report={'companies':{'APP':{'maintained_view':{'status':'reviewed','thesis_id':'company_thesis:APP','thesis_version':1,
                'business_case_status':'supported','valuation_readiness':'unresolved','conclusion':'Business evidence supports continued research.',
                'reopen_reasons':[]}}}},
            incorporation={'companies':{'APP':{'status':'incorporated','positive_decision_eligible':True,
                'selected_period_end':'2026-06-30','latest_report_period_end':'2026-06-30'}}},
            evaluation={'generated_at':'2026-09-24T17:56:00-04:00','portfolio_performance':{'status':'not_ready'},
                'operations':{'on_time_cycles':13,'due_calendar_cycles':14,'late_cycles':1}},
            refresh={'completed_at':'2026-09-24T17:57:00-04:00','research_completed_at':'2026-09-24T17:55:00-04:00',
                'workflow_evaluation_update':{'exit_code':0}}, held_tickers={'APP','SPY'}, held_companies={'APP'},current=self.now)

    def test_reviewed_business_is_not_complete_valuation_and_missing_plan_visible(self):
        result = workflow_health(**self.fixture())
        self.assertEqual(result['maintained_research']['reviewed_business_views'],1)
        self.assertEqual(result['maintained_research']['reviewed_company_valuations'],0)
        self.assertEqual(result['plan_continuity']['missing_held_tickers'],['SPY'])
        self.assertTrue(result['plan_continuity']['block_new_capital'])
        self.assertEqual(result['plan_continuity']['plans'][0]['status'],'awaiting_broker_verification')
        self.assertTrue(result['workflow_evaluation']['current_refresh_included'])
        self.assertEqual(result['workflow_evaluation']['portfolio_performance']['status'],'not_ready')

    def test_new_unincorporated_earnings_reopen_prior_conclusion_without_erasing_it(self):
        fixture=self.fixture()
        fixture['incorporation']['companies']['APP'].update(status='pending_incorporation',positive_decision_eligible=False,
                                                          latest_report_period_end='2026-09-30')
        result=workflow_health(**fixture)
        row=result['maintained_research']['companies'][0]
        self.assertEqual(row['reported_thesis_state'],'reviewed')
        self.assertEqual(row['thesis_state'],'reassess')
        self.assertTrue(row['conclusion'])
        self.assertEqual(result['maintained_research']['reviewed_business_views'],0)
        self.assertEqual(result['earnings_incorporation']['held_pending_tickers'],['APP'])
        self.assertEqual(row['selected_financial_period'],'2026-06-30')
        self.assertEqual(row['latest_report_period'],'2026-09-30')

    def test_prior_evaluation_or_failed_final_render_cannot_claim_current_run(self):
        fixture=self.fixture()
        fixture['evaluation']['generated_at']='2026-09-24T17:54:00-04:00'
        result=workflow_health(**fixture)
        self.assertFalse(result['workflow_evaluation']['current_refresh_included'])
        fixture=self.fixture()
        fixture['refresh']['workflow_evaluation_update']['exit_code']=1
        result=workflow_health(**fixture)
        self.assertEqual(result['workflow_evaluation']['reason'],'workflow_evaluation_final_update_failed')
        self.assertEqual(result['workflow_evaluation']['operations']['on_time_cycles'],13)

    def test_stale_and_conflicting_plans_preserve_instructions_as_unresolved(self):
        fixture=self.fixture()
        fixture['decision']['plan_continuity'].update(as_of='2026-09-20T12:00:00-04:00',conflicts=['APP contradictory plan'],block_new_capital=False)
        result=workflow_health(**fixture)
        self.assertIn('active_plan_conflicts',result['plan_continuity']['gaps'])
        self.assertIn('plan_continuity_stale_or_future',result['plan_continuity']['gaps'])
        self.assertTrue(result['plan_continuity']['block_new_capital'])
        self.assertEqual(result['plan_continuity']['plans'][0]['action'],'exit_review')

    def test_deployment_fallback_is_not_reported_as_online_sync(self):
        result=deployment_health({'verified_at':'2026-09-24T12:00:00-04:00','commit':'abc'},
            [{'event':'scheduler_exec_authorized','outcome':'authorized','job':'dailyrefresh',
              'timestamp':'2026-09-24T17:00:00-04:00','sync_action':'verified_deployment_network_fallback'}],current=self.now)
        self.assertEqual(result['status'],'collection_on_verified_deployment_network_fallback')
        self.assertTrue(result['receipt_within_fallback_window'])
        self.assertEqual(result['receipt_age_seconds'],21600)

    def test_record_refresh_precedes_evaluation_rerender_then_status(self):
        calls=[]
        writes=[]
        def run_step(name, script, allowed, **kwargs):
            calls.append(name)
            return {'name':name,'script':script,'allowed_to_fail':allowed,'exit_code':0,'outcome':'passed'}
        with (patch.object(refresh,'load_active_state'),patch.object(refresh,'load_inhibit'),
              patch.object(refresh,'log_daily_run'),patch.object(refresh,'run_step',side_effect=run_step),
              patch('workflow_evaluation.record_refresh',side_effect=lambda state: calls.append('durable_refresh_record')),
              patch.object(refresh,'atomic_write_json',side_effect=lambda path,state:writes.append(copy.deepcopy(state)))):
            self.assertEqual(refresh.run_refresh(no_lock=True),0)
        self.assertEqual(calls[-3:],['durable_refresh_record','workflow_evaluation_final','current_status'])
        self.assertEqual(writes[0]['research_completed_at'],writes[0]['completed_at'])
        self.assertIn('workflow_evaluation_update',writes[-2])
        self.assertNotIn('current_status_update',writes[-2])
        self.assertIn('current_status_update',writes[-1])

    def test_sender_failure_does_not_erase_observed_collection_fallback(self):
        result=deployment_health({'verified_at':'2026-09-24T12:00:00-04:00'},[
            {'event':'scheduler_exec_authorized','job':'dailyrefresh','outcome':'authorized','sync_action':'verified_deployment_network_fallback'},
            {'event':'preflight','job':'dailydecision','outcome':'blocked','sync_action':'none'}],current=self.now)
        self.assertEqual(result['status'],'latest_preflight_blocked')
        self.assertTrue(result['public_collection_fallback_observed'])
        self.assertEqual(result['jobs']['dailydecision']['outcome'],'blocked')

    def test_prior_news_pending_is_visible_without_erasing_supported_business(self):
        fixture=self.fixture()
        fixture['long_report']['companies']['APP']['maintained_view']['news_review']={
            'status':'pending_prior_news','pending_events':[{'event_id':'prior-one'}],
            'review_scope':'Business review cites filings; prior company announcement needs assessment.'}
        result=workflow_health(**fixture)
        company=result['maintained_research']['companies'][0]
        self.assertEqual(company['thesis_state'],'reviewed')
        self.assertEqual(company['business_case_status'],'supported')
        self.assertEqual(company['news_review_status'],'pending_prior_news')
        self.assertEqual(company['pending_news_event_count'],1)
        self.assertTrue(company['news_review_scope'])


if __name__=='__main__':
    unittest.main()
