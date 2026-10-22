"""Transaction-scoped reuse of unchanged file hashes during read-only validation.

No verification is cached across transactions or processes. Every lookup stats
the actual path; atomic replacement, a changed inode or any size/clock change
forces a fresh read. A final stat fence rejects a transaction that observed a
file mutation, including a mutation after its last hash lookup.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
from pathlib import Path


_CURRENT = ContextVar('equity_file_hash_validation_cache', default=None)


def _identity(path: Path) -> tuple:
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _Transaction:
    def __init__(self):
        self.first = {}
        self.entries = {}
        self.changed = False

    def digest(self, path: Path) -> str:
        # Preserve the locator so symlink/atomic replacement is checked again.
        path = Path(os.path.abspath(path))
        before = _identity(path)
        if self.first.setdefault(path, before) != before:
            self.changed = True
        found = self.entries.get(path)
        if found and found[0] == before:
            return found[1]
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
    current = _Transaction()
    token = _CURRENT.set(current)
    try:
        yield current
        current.validate()
    finally:
        _CURRENT.reset(token)


def sha256_file(path: Path) -> str:
    cache = _CURRENT.get()
    return cache.digest(path) if cache is not None else hashlib.sha256(path.read_bytes()).hexdigest()
