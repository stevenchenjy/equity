"""Versioned admission of policy adapters; never experiment promotion by sampling."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from daily_common import read_json, canonical_sha256, sha256_file

REGISTRY = '01_policies/production_strategies.json'
ADAPTERS = {'core_tranche', 'reviewed_company', 'reviewed_tactical', 'maintained_exit'}


def registry(root: Path) -> dict:
    value = read_json(root / REGISTRY)
    if value.get('schema_version') != 'equity_production_strategies_v1' or not isinstance(value.get('strategies'), list):
        raise ValueError('production_strategy_registry_invalid')
    ids = [r.get('strategy_id') for r in value['strategies']]
    if not all(isinstance(i, str) and i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('production_strategy_identity_invalid')
    return value


def admit(root: Path, strategy: dict[str, Any], *, current: datetime | None = None) -> list[str]:
    errors = []
    if strategy.get('adapter') not in ADAPTERS or strategy.get('state') != 'VERSIONED_PRODUCTION_STRATEGY':
        return ['strategy_not_production_adopted']
    if type(strategy.get('version')) is not int or strategy['version'] <= 0 or not strategy.get('authority'):
        errors.append('production_strategy_authority_missing')
    bindings = strategy.get('policy_bindings', {})
    if not bindings:
        errors.append('production_strategy_policy_bindings_missing')
    for rel, expected in bindings.items():
        p = Path(rel)
        if p.is_absolute() or '..' in p.parts or not (root / p).is_file() or sha256_file(root / p) != expected:
            errors.append('production_strategy_policy_changed_review_required')
    if strategy.get('origin') == 'experiment':
        review = strategy.get('evidence_review', {})
        adoption = strategy.get('owner_adoption', {})
        if (review.get('mature_evidence') is not True or not review.get('reviewed_at') or not review.get('experiment_version')
                or not isinstance(review.get('source_bindings'), dict) or not review['source_bindings']):
            errors.append('strategy_mature_evidence_review_missing')
        for rel, expected in review.get('source_bindings', {}).items():
            p = Path(rel)
            if p.is_absolute() or '..' in p.parts or not (root / p).is_file() or sha256_file(root / p) != expected:
                errors.append('strategy_evidence_review_binding_invalid')
        digest = canonical_sha256({k: v for k, v in strategy.items() if k != 'owner_adoption'})
        if (adoption.get('approved_by') != 'owner' or not adoption.get('approved_at') or not adoption.get('request_reference')
                or adoption.get('strategy_definition_sha256') != digest):
            errors.append('owner_strategy_adoption_required')
        try:
            reviewed = datetime.fromisoformat(review['reviewed_at'].replace('Z', '+00:00'))
            approved = datetime.fromisoformat(adoption['approved_at'].replace('Z', '+00:00'))
            if reviewed.tzinfo is None or approved.tzinfo is None or not reviewed <= approved <= (current or datetime.now(timezone.utc)):
                raise ValueError('invalid_adoption_clock')
        except (KeyError, TypeError, ValueError):
            errors.append('strategy_review_adoption_clock_invalid')
    elif strategy.get('origin') != 'existing_approved_policy':
        errors.append('production_strategy_origin_unverified')
    return sorted(set(errors))


def select(root: Path, adapter: str, values: dict | None = None) -> tuple[dict, list[str]]:
    try:
        records = (values or registry(root))['strategies']
        found = [r for r in records if r.get('adapter') == adapter and r.get('state') == 'VERSIONED_PRODUCTION_STRATEGY']
        if len(found) != 1:
            return {}, ['production_strategy_adapter_not_uniquely_admitted']
        return found[0], admit(root, found[0])
    except (OSError, ValueError, KeyError, TypeError):
        return {}, ['production_strategy_registry_invalid']
