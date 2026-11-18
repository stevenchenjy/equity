"""Transaction-scoped reuse of unchanged file hashes during read-only validation.

Every lookup stats the actual locator. Each transaction has an independent
final mutation fence. An explicitly scoped operation may carry byte digests
from successful transactions for repeat lookups with an identical full file
identity. Clock checks, source availability and eligibility are never cached.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
from pathlib import Path


_CURRENT = ContextVar('equity_file_hash_validation_cache', default=None)
_OPERATION_DIGESTS = ContextVar('equity_operation_verified_byte_digests', default=None)


def _identity(path: Path) -> tuple:
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def content_proof_scope():
    """Carry only file identities and their verified SHA across a single call."""
    token = _OPERATION_DIGESTS.set({})
    try:
        yield
    finally:
        _OPERATION_DIGESTS.reset(token)


class _Transaction:
    def __init__(self, previous):
        self.first = {}
        self.entries = {}
        self.changed = False
        self.previous = previous

    def digest(self, path: Path) -> str:
        # Preserve the locator so symlink/atomic replacement is checked again.
        path = Path(os.path.abspath(path))
        before = _identity(path)
        if self.first.setdefault(path, before) != before:
            self.changed = True
        found = self.entries.get(path)
        if found and found[0] == before:
            return found[1]
        if self.previous is not None:
            prior = self.previous.get(path)
            if prior and prior[0] == before:
                self.entries[path] = prior
                return prior[1]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if _identity(path) != before:
            self.changed = True
            raise ValueError('validation_source_changed_during_hash')
        self.entries[path] = (before, digest)
        return digest

    def validate(self):
        for path, identity in self.first.items():
            if _identity(path) != identity:
                self.changed = True
        if self.changed:
            raise ValueError('validation_sources_changed_during_transaction')


@contextmanager
def file_hash_validation():
    """Reuse hashes inside one explicitly read-only validation operation.

    Nesting shares the outer transaction and final mutation fence. Do not wrap
    a research refresh, collector or account writer in this context.
    """
    prior = _CURRENT.get()
    if prior is not None:
        yield prior
        return
    operation = _OPERATION_DIGESTS.get()
    current = _Transaction(operation)
    token = _CURRENT.set(current)
    try:
        yield current
        current.validate()
        if operation is not None:
            operation.update(current.entries)
    finally:
        _CURRENT.reset(token)


def sha256_file(path: Path) -> str:
    cache = _CURRENT.get()
    if cache is not None:
        return cache.digest(path)
    if _OPERATION_DIGESTS.get() is not None:
        with file_hash_validation() as transaction:
            return transaction.digest(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()
