#!/usr/bin/env python3
"""Complete an immediate bounded escalation batch and recompose; never send.

Public collectors and source-bound admission retain their existing limits.
Objective data work cannot manufacture an analyst conclusion or a trade gate.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, canonical_sha256, now_et, read_json
from capital_escalation import research_priorities

BASE = Path('08_reviews/capital_escalation.local')
DECISION = Path('04_research/company_research/daily_decision.json')


def run(root: Path, *, current=None, execute=None) -> dict:
    current = current or now_et()
    execute = execute or (lambda args: subprocess.run(args, cwd=root, timeout=210, check=False).returncode)
    with ExclusiveFileLock(root / BASE / 'research.lock'):
        decision = read_json(root / DECISION, {})
        escalation = decision.get('capital_deployment_escalation', {})
        priorities = research_priorities(root, current)
        if not escalation.get('triggered') or not priorities:
            return {'status': 'not_required', 'attempted': False, 'email_sent': False, 'order_placed': False}
        session = escalation.get('observation_session')
        if not session:
            raise ValueError('escalation_session_missing')
        receipt_path = root / BASE / 'research_attempts' / (session + '.json')
        if receipt_path.exists():
            return {**read_json(receipt_path), 'status': 'already_attempted_this_session'}
        # Publish the attempt before child work: a crash cannot consume the
        # bounded objective/network budget repeatedly in the same session.
        receipt = {'schema_version': 'equity_capital_escalation_research_v1',
            'status': 'started', 'attempted': True, 'started_at': current.isoformat(),
            'market_session': session, 'priority_tickers': priorities,
            'decision_sha256': canonical_sha256(decision), 'steps': [],
            'analyst_conclusion_completed': False, 'email_sent': False, 'order_placed': False}
        # This stage follows the normal objective pass in the SAME pipeline.
        # Preserve its shared issuer budget and network allowance rather than
        # restarting either counter. Missing receipts cannot prove unused work.
        config = read_json(root / '00_project_control/active_production_config.json', {})
        budget = config.get('workflow', {}).get('objective_research_max_tickers', 3)
        backlog = read_json(root / '04_research/company_research/research_backlog.local.json', {})
        opportunity = read_json(root / '04_research/company_research/opportunities.local/report.json', {})
        try:
            from research_backlog import validate_report
            validate_report(backlog)
            if backlog['generated_at'][:10] != current.date().isoformat():
                raise ValueError('prior_batch_not_current')
            used = len(backlog['selected_tickers'])
            metrics = opportunity.get('metrics', {})
            if opportunity.get('generated_at', '')[:10] != current.date().isoformat():
                raise ValueError('prior_opportunity_batch_not_current')
            count = metrics['objective_items_processed']
            if type(count) is not int or count < 0 or type(budget) is not int or not 1 <= budget <= 10:
                raise ValueError('prior_budget_unverified')
            used += count
            remaining = max(0, budget-used)
        except (KeyError, ValueError, TypeError):
            receipt.update(status='prior_objective_budget_unverified', remaining_objective_budget=0)
            atomic_write_json(receipt_path, receipt)
            return receipt
        receipt.update(shared_objective_budget=budget, earlier_objective_attempts=used,
                       remaining_objective_budget=remaining, additional_network_requests=0)
        atomic_write_json(receipt_path, receipt)
        if remaining == 0:
            receipt.update(status='objective_budget_exhausted', next_step='Priority source-bound analyst work is due immediately; the next bounded public batch consumes these priorities first. No collector quota was restarted.')
            atomic_write_json(receipt_path, receipt)
            return receipt
        scripts = root / '09_scripts/equity_research'
        steps = [
            ('research_backlog', 'create_research_backlog.py', ['--apply-objective-updates', '--max-tickers', str(remaining)]),
            ('earnings_incorporation', 'create_earnings_incorporation.py', []),
            ('current_research_baseline', 'build_current_research_baseline.py', []),
            ('valuation_scenarios', 'refresh_valuation_scenarios.py', []),
            ('long_horizon_research', 'create_long_horizon_research.py', []),
            ('portfolio_outputs', 'regenerate_portfolio_outputs.py', []),
            ('price_aware_review', 'create_price_aware_action_plan.py', []),
            ('daily_decision', 'create_daily_decision_and_brief.py', []),
        ]
        for name, script, flags in steps:
            try:
                code = execute([sys.executable, str(scripts / script), *flags])
            except (OSError, subprocess.TimeoutExpired):
                code = 1
            receipt['steps'].append({'name': name, 'exit_code': code})
            atomic_write_json(receipt_path, receipt)
            if code:
                receipt['status'] = 'failed_exact_stage'
                break
        else:
            receipt['status'] = 'objective_batch_recomposed'
        receipt['completed_at'] = now_et().isoformat()
        backlog = read_json(root / '04_research/company_research/research_backlog.local.json', {})
        receipt['objective_completion'] = backlog.get('completion_summary', {})
        final = read_json(root / DECISION, {})
        receipt['remaining_gates'] = final.get('capital_deployment_escalation', {}).get('ranked_capital_uses', [])
        receipt['next_step'] = ('Complete each remaining source-bound business, valuation and counterevidence assessment '
            'through the maintained analyst writers immediately; objective collection is not analyst signoff.')
        atomic_write_json(receipt_path, receipt)
        return receipt


def main() -> int:
    receipt = run(ROOT)
    print('capital_escalation_research=' + receipt['status'] + ' email_sent=false order_placed=false')
    return 1 if receipt['status'] == 'failed_exact_stage' else 0


if __name__ == '__main__':
    raise SystemExit(main())
