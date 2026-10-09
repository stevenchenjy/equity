"""Owner-approved local-ledger authority for conditional manual research drafts.

The policy changes planning authority, never the underlying broker observations.
Without the private approval, the existing verified-snapshot rules apply.
"""
from datetime import datetime
from pathlib import Path
from daily_common import canonical_sha256, read_json

POLICY_REL = '05_risk_and_positions/account_record_policy.local.json'
SCHEMA = 'equity_account_record_authority_v1'
# Older analyst assessments recorded these as pre-entry research dependencies.
# Keep the immutable assessment/journal; only their current planning projection
# changes after the owner's explicit local-record authorization.
LEGACY_ACCOUNT_RESEARCH_REQUIREMENTS = frozenset({
    'current_account_order_funding_and_execution_contracts_before_any_future_trade',
    'current_complete_account_order_inventory_and_usable_funds_before_entry',
    'complete_current_account_order_inventory_usable_settled_funds',
})


def project_research_requirements(item: dict, authority: dict) -> None:
    """Move exactly superseded metadata requirements out of current research gates."""
    if not authority.get('local_planning_enabled'):
        return
    previous = item.get('blockers', [])
    retained = [code for code in previous if code in LEGACY_ACCOUNT_RESEARCH_REQUIREMENTS]
    item['blockers'] = [code for code in previous if code not in LEGACY_ACCOUNT_RESEARCH_REQUIREMENTS]
    if retained:
        item['retained_assessment_execution_requirements'] = retained
        item['execution_checks'] = list(authority['execution_checks'])


def load_authority(root: Path, current: datetime) -> dict:
    path = root / POLICY_REL
    if not path.exists():
        return {'mode': 'verified_snapshot', 'local_planning_enabled': False}
    value = read_json(path)
    required = {'schema_version', 'mode', 'approved_at', 'owner_instruction',
                'automatic_execution', 'broker_observation_claimed', 'content_sha256'}
    if (not isinstance(value, dict) or set(value) != required
            or value.get('schema_version') != SCHEMA
            or value.get('mode') != 'owner_local_ledger'
            or value.get('automatic_execution') is not False
            or value.get('broker_observation_claimed') is not False
            or not isinstance(value.get('owner_instruction'), str)
            or not value['owner_instruction'].strip()
            or value.get('content_sha256') != canonical_sha256({k: v for k, v in value.items() if k != 'content_sha256'})):
        raise ValueError('account_record_authority_approval_invalid')
    approved = datetime.fromisoformat(value['approved_at'])
    if approved.tzinfo is None or approved > current:
        raise ValueError('account_record_authority_approval_time_invalid')
    return {'mode': value['mode'], 'local_planning_enabled': True,
            'approved_at': value['approved_at'], 'approval_sha256': value['content_sha256'],
            'broker_observation_claimed': False, 'automatic_execution': False,
            'execution_checks': [
                'Plans use the local cash, holdings and orders. Before manual submission, check executable funds and any unrecorded account changes.',
                'Local ledger cash is not a verified broker buying-power or settled-cash observation.']}


def local_tactical_risk_is_zero(decision: dict, orders: dict) -> bool:
    """A local ledger containing only core holdings and terminal/no orders has no tactical exposure."""
    holdings = decision.get('held_positions')
    rows = orders.get('orders')
    return (isinstance(holdings, list) and isinstance(rows, list)
            and all(isinstance(r, dict) and r.get('asset_role') == 'core_allocation' for r in holdings)
            and all(isinstance(r, dict) and r.get('status') in {'filled', 'cancelled', 'canceled', 'expired', 'rejected'} for r in rows))
