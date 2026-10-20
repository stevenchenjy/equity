"""Short account transactions and optimistic research-version admission.

Research/deployment locks never guard interactive account intake. A publication
is admitted only for the exact account inputs used throughout its computation.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

ACCOUNT_LOCK = '00_project_control/run_logs/account_records.lock'
CHECKPOINT = '00_project_control/run_logs/account_research_version.local.json'
VERSION_ENV = 'EQUITY_RESEARCH_ACCOUNT_INPUT_VERSION'
ACCOUNT_INPUTS = (
    '05_risk_and_positions/current_account_state.local.json',
    '05_risk_and_positions/current_positions.local.csv',
    '05_risk_and_positions/current_open_orders.local.json',
    '06_execution_records/manual_executions.local.csv',
    '06_execution_records/confirmed_execution_report.csv',
    '06_execution_records/reconciliation_report.csv',
    '06_execution_records/dashboard_feedback_pending.local.json',
    '05_risk_and_positions/manual_account_snapshot.local.json',
)


@contextmanager
def account_lock(root: Path, *, shared=False):
    root = root.resolve()
    path = root / ACCOUNT_LOCK
    if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise ValueError('unsafe_account_lock_path')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def input_version(root: Path) -> str:
    """Caller holds the short account lock; ledger hashes prevent ABA replays."""
    hashes = {}
    for relative in ACCOUNT_INPUTS:
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError('unsafe_account_input_path')
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def capture_version(root: Path) -> str:
    with account_lock(root, shared=True):
        return input_version(root)


@contextmanager
def research_context(root: Path):
    version = capture_version(root)
    previous = os.environ.get(VERSION_ENV)
    os.environ[VERSION_ENV] = version
    try:
        yield version
    finally:
        if previous is None:
            os.environ.pop(VERSION_ENV, None)
        else:
            os.environ[VERSION_ENV] = previous


def expected_version(root: Path) -> str:
    expected = os.environ.get(VERSION_ENV)
    if expected is None and (root / CHECKPOINT).exists():
        expected = json.loads((root / CHECKPOINT).read_text())['account_input_version']
    if expected is None:
        raise ValueError('account_research_context_missing_recompose_required')
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('account_research_version_invalid')
    if expected != capture_version(root):
        raise ValueError('account_inputs_changed_recompose_required')
    return expected


@contextmanager
def publication_guard(root: Path, expected: str):
    with account_lock(root, shared=True):
        if input_version(root) != expected:
            raise ValueError('account_inputs_changed_recompose_required')
        pending = root / ACCOUNT_INPUTS[6]
        if pending.exists() and any(r.get('stage') in {'applying','recovery_conflict'}
                for r in json.loads(pending.read_text()).get('records', [])):
            raise ValueError('account_write_recovery_required')
        yield


def validate_account_publication(decision: dict, root: Path) -> None:
    expected = decision.get('account_input_version')
    if expected is not None and expected != input_version(root):
        raise ValueError('account_inputs_changed_recompose_required')
