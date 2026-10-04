"""Classify exact dependencies and retain bounded automatic-resolution receipts.

These receipts observe existing source-bound workers. Stage success is NOT gap
completion. No model API, sender, account writer or trading path is introduced.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from daily_common import canonical_sha256, read_json, sha256_file, atomic_write_json

STAGE_INPUTS = {
 'official_evidence': ['03_source_data/equity_research/sec_submission_acceptance_index.json'],
 'research_backlog': ['03_source_data/equity_research/daily_fundamentals.csv', '04_research/company_research/research_backlog.local.json'],
 'research_opportunity_objective': ['04_research/company_research/opportunities.local/store.json'],
 'valuation_scenarios': ['04_data/equity_research/valuation_inputs.local.json'],
}
STAGE_OUTPUTS = {
 'official_evidence': ['03_source_data/equity_research/daily_evidence_status.json',
                       '03_source_data/equity_research/daily_evidence_ledger.csv',
                       '03_source_data/equity_research/sec_acceptance_extension_admission_audit.csv'],
 'research_backlog': ['04_research/company_research/research_backlog.local.json'],
 'research_opportunity_objective': ['04_research/company_research/opportunities.local/report.json'],
 'valuation_scenarios': ['04_data/equity_research/valuation_scenarios.local.json'],
}


def classify(code: str, *, ticker: str | None = None, scope='ticker') -> dict[str, Any]:
    code = str(code)
    category, worker, needed = 'D', 'recurring_analyst', 'A sourced strategy-appropriate thesis, valuation and counterevidence conclusion; no positive conclusion is inferred from a screen.'
    if any(w in code for w in ('account', 'planning_cash', 'cash_confirm', 'cash_not_confirmed', 'cash_basis', 'open_orders', 'order_inventory', 'order_snapshot', 'existing_order', 'remaining_shares', 'holdings', 'execution_conflict', 'execution_funds', 'buying_power', 'tactical_risk_unconfirmed', 'earlier_instruction_execution')):
        category, worker, needed = 'C', 'approved_manual_account_record', 'Dated complete current holdings and account-wide pending/partial orders (remaining quantity, price/stop, TIF and status), plus available execution funds and settlement/buying-power confirmation.'
        if code == 'earlier_instruction_execution_unreconciled':
            needed = 'A complete owner-recorded holdings/cash snapshot and sourced complete account-wide order observation recorded after the earlier email; an assumed fill or a later status email cannot supply this evidence.'
    elif any(w in code for w in ('strategy', 'adoption', 'experiment', 'policy_invalid', 'policy_changed', 'contract', 'liquidity', 'spread', 'halt', 'fresh_quote', 'canonical_market_admission')):
        category, worker, needed = 'E', 'strategy_or_execution_gate', 'The exact reviewed strategy/adoption or current execution evidence identified by this code; no gate bypass.'
    elif any(w in code for w in ('unreconciled', 'source_conflict', 'identity_conflict')):
        category, worker, needed = 'B', 'official_evidence', 'Matching dated SEC primary identity and acceptance-time evidence that passes the existing immutable-index reconciliation; retained conflicts cannot be overwritten.'
    elif any(w in code for w in ('price_history', 'market_data', 'market_gate', 'stale_market', 'complete_close', 'latest_completed', 'calendar', 'news_coverage', 'network_refresh')):
        category, worker, needed = 'B', 'approved_public_refresh', 'Next available approved source publication or current public evidence with the required coverage, timestamp and source binding.'
    elif any(w in code for w in ('incorporation', 'sec_acceptance', 'financial', 'objective', 'debt_latest', 'cash_latest', 'ttm_', 'dilution', 'valuation_recomposition', 'baseline_data', 'data_gate_hold', 'evidence_gate_failed', 'fundamental_gate_failed')):
        category, worker, needed = 'A', 'bounded_full_refresh', 'Run the existing SEC reconciliation/objective admission, earnings incorporation, valuation and dependent decision stages; retain failures and distinguish fields admitted from dossiers processed.'
    elif any(w in code for w in ('expired', 'plan', 'reassessment', 'maintained_company', 'thesis', 'valuation', 'durability', 'counterevidence', 'review')):
        worker = 'recurring_analyst'
        needed = 'A current source-bound amendment accepted by the maintained thesis/valuation/plan writer. The scheduled analyst must synthesize it; the owner is not asked to invent the investment case.'
    return dict(code=code, category=category, scope=scope, ticker=ticker, resolver=worker, evidence_required=needed,
                automatic=category in {'A','B'} or worker == 'recurring_analyst', resolved=False)


def observe(root: Path, stage: str) -> dict[str, str | None]:
    return {rel: sha256_file(root / rel) if (root / rel).is_file() else None
            for rel in [*STAGE_INPUTS.get(stage, []), *STAGE_OUTPUTS.get(stage, [])]}


def record_attempt(root: Path, result: dict, before: dict) -> None:
    stage = result['name']
    if stage not in STAGE_INPUTS:
        return
    after = observe(root, stage)
    directory = root / '08_reviews/decision_resolution.local/attempts'
    receipt = dict(schema_version='equity_dependency_attempt_v1', stage=stage,
                   started_at=result['started_at'], completed_at=result['completed_at'], exit_code=result['exit_code'],
                   before=before, after=after, changed_paths=[k for k in after if after[k] != before.get(k)],
                   stage_success_is_dependency_resolution=False, automatic_action_allowed=False)
    receipt['receipt_sha256'] = canonical_sha256(receipt)
    atomic_write_json(directory / (receipt['receipt_sha256'] + '.json'), receipt)
    atomic_write_json(directory.parent / (stage + '.json'), receipt)


def publish(root: Path, contract: dict) -> None:
    queue = dict(schema_version='equity_decision_dependency_queue_v1', generated_at=contract['generated_at'],
                 decision_sha256=contract['content_sha256'], dependencies=contract['dependencies'],
                 automatic_resolvers=['scheduled_public_refresh', 'bounded_objective_backlog', 'valuation_recomposition', 'recurring_source_bound_analyst'],
                 broker_access=False, model_api_enabled=False, automatic_action_allowed=False)
    atomic_write_json(root / '08_reviews/decision_resolution.local/queue.json', queue)
