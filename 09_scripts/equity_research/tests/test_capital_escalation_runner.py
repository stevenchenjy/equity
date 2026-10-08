import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from _support import SCRIPT_DIR
import run_capital_escalation as runner
import run_daily_refresh as pipeline


class EscalationRunnerTests(unittest.TestCase):
    def seed_budget(self, root, used=0):
        for rel, value in [
            ('00_project_control/active_production_config.json', {'workflow': {'objective_research_max_tickers': 10}}),
            ('04_research/company_research/research_backlog.local.json', {'generated_at':runner.now_et().isoformat(),'selected_tickers':['OLD']*used}),
            ('04_research/company_research/opportunities.local/report.json', {'generated_at':runner.now_et().isoformat(),'metrics':{'objective_items_processed':0}})]:
            p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
    def test_blocked_trigger_never_runs_research_or_sender(self):
        with tempfile.TemporaryDirectory() as name, patch.object(runner, 'research_priorities', return_value=[]):
            root = Path(name)
            result = runner.run(root, execute=lambda _: self.fail('unexpected child'))
            self.assertFalse(result['attempted'])
            self.assertFalse(result['email_sent'])

    def test_immediate_batch_recomposes_once_and_retains_failure_stage(self):
        with tempfile.TemporaryDirectory() as name, patch.object(runner, 'research_priorities', return_value=['TEST']), patch('research_backlog.validate_report'):
            root = Path(name)
            self.seed_budget(root)
            p = root / runner.DECISION
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps({'capital_deployment_escalation': {'triggered': True, 'observation_session': '2026-10-07'}}))
            calls = []
            def execute(args):
                calls.append(Path(args[1]).name)
                return 2 if calls[-1] == 'refresh_valuation_scenarios.py' else 0
            result = runner.run(root, execute=execute)
            self.assertEqual(result['status'], 'failed_exact_stage')
            self.assertEqual(result['steps'][-1], {'name':'valuation_scenarios','exit_code':2})
            self.assertFalse(result['analyst_conclusion_completed'])
            self.assertFalse(any('send' in x for x in calls))
            again = runner.run(root, execute=lambda _: self.fail('duplicate session batch'))
            self.assertEqual(again['status'], 'already_attempted_this_session')

    def test_success_recomputes_final_decision_without_claiming_reasoning(self):
        with tempfile.TemporaryDirectory() as name, patch.object(runner, 'research_priorities', return_value=['TEST']), patch('research_backlog.validate_report'):
            root = Path(name)
            self.seed_budget(root,used=7)
            p=root/runner.DECISION;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps({'capital_deployment_escalation': {'triggered':True,'observation_session':'2026-10-07'}}))
            calls=[]
            result=runner.run(root,execute=lambda args:calls.append(Path(args[1]).name) or 0)
            self.assertEqual(calls[-1], 'create_daily_decision_and_brief.py')
            self.assertEqual(result['status'], 'objective_batch_recomposed')
            self.assertFalse(result['analyst_conclusion_completed'])
            self.assertFalse(result['order_placed'])
            self.assertEqual(result['remaining_objective_budget'],3)

    def test_normal_batch_exhaustion_does_not_restart_collectors(self):
        with tempfile.TemporaryDirectory() as name, patch.object(runner,'research_priorities',return_value=['TEST']), patch('research_backlog.validate_report'):
            root=Path(name);self.seed_budget(root,used=10)
            p=root/runner.DECISION;p.write_text(json.dumps({'capital_deployment_escalation':{'triggered':True,'observation_session':'2026-10-07'}}))
            result=runner.run(root,execute=lambda _:self.fail('second issuer/network quota'))
            self.assertEqual(result['status'],'objective_budget_exhausted')
            self.assertFalse(result['analyst_conclusion_completed'])

    def test_live_full_refresh_includes_escalation_before_consumers(self):
        names=[r[0] for r in pipeline.STEP_SPECS]
        self.assertLess(names.index('daily_decision'),names.index('capital_deployment_escalation'))
        self.assertLess(names.index('capital_deployment_escalation'),names.index('outcome_tracking'))
