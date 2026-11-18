"""Transaction-scoped reuse of unchanged file hashes during read-only validation.

Direct file-hash lookups check the file identity each time. Repeated source
locators within one read-only transaction reuse their initial resolved proof.
The transaction checks locator resolution and target identity again at exit.
An explicitly scoped operation may carry byte digests from successful
transactions for repeat lookups with an identical full file identity. Clock
checks, source availability and eligibility are never cached.
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
    """Carry only file identities and their verified SHA across one operation."""
    if _OPERATION_DIGESTS.get() is not None:
        # Nested readers keep their independent validation transactions.
        yield
        return
    token = _OPERATION_DIGESTS.set({})
    try:
        yield
    finally:
        _OPERATION_DIGESTS.reset(token)


class _Transaction:
    def __init__(self, previous):
        self.first = {}
        self.entries = {}
        self.resolved_sources = {}
        self.changed = False
        self.previous = previous

    def _track(self, path: Path):
        # Preserve the locator so symlink/atomic replacement is checked again.
        path = Path(os.path.abspath(path))
        before = _identity(path)
        if self.first.setdefault(path, before) != before:
            self.changed = True
        return path, before

    def _known(self, path, identity):
        found = self.entries.get(path)
        if found and found[0] == identity:
            return found
        if self.previous is not None:
            prior = self.previous.get(path)
            if prior and prior[0] == identity:
                return prior
        return None

    def _read(self, path, identity):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        known = self._known(path, identity)
        if _identity(path) != identity or (known is not None and known[1] != digest):
            self.changed = True
            raise ValueError('validation_source_changed_during_hash')
        self.entries[path] = (identity, digest)
        return raw, digest

    def digest(self, path: Path) -> str:
        path, identity = self._track(path)
        known = self._known(path, identity)
        if known is not None:
            self.entries[path] = known
            return known[1]
        return self._read(path, identity)[1]

    def read_hashed_bytes(self, path: Path) -> tuple[bytes, str]:
        path, identity = self._track(path)
        return self._read(path, identity)

    def resolved_digest(self, root: Path, locator: str, resolve):
        key = (root, locator, resolve)
        if key not in self.resolved_sources:
            path = resolve(root, locator)
            self.resolved_sources[key] = (path, self.digest(path))
        return self.resolved_sources[key][1]

    def validate(self):
        for (root, locator, resolve), (path, _) in self.resolved_sources.items():
            if resolve(root, locator) != path:
                self.changed = True
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


def read_hashed_bytes(path: Path) -> tuple[bytes, str]:
    """Read and hash the same bytes under the transaction's identity fence."""
    with file_hash_validation() as transaction:
        return transaction.read_hashed_bytes(path)


def resolved_sha256(root: Path, locator: str, resolve) -> str:
    """Prove a resolved source once per read-only transaction and recheck its locator on exit."""
    cache = _CURRENT.get()
    if cache is None:
        return sha256_file(resolve(root, locator))
    return cache.resolved_digest(root, locator, resolve)
