"""Retain exact validated message inputs before a durable delivery claim.

Only decision JSON and rendered body bytes are accepted. SMTP configuration,
headers, credentials and recipient addresses are not inputs to this archive.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path


SUFFIXES = {'decision_sha256': '.json', 'brief_text_sha256': '.txt', 'brief_html_sha256': '.html'}


def _matches(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1 or stream.read() != content):
            raise ValueError('delivery_archive_existing_content_invalid')
        # Older manually preserved archives may predate private file modes.
        os.fchmod(stream.fileno(), 0o600)


def archive_validated_delivery(archive_dir: Path, *, contents: dict[str, bytes],
                               hashes: dict[str, str]) -> None:
    """Atomically publish immutable content-addressed files; fail before send.

    Partial archives after a filesystem failure are safe to retry because every
    existing file must match exactly. A claim is written only after all three
    files and directory entries have been fsynced by the caller's send path.
    """
    if set(contents) != set(SUFFIXES) or set(hashes) != set(SUFFIXES):
        raise ValueError('delivery_archive_snapshot_incomplete')
    for key, content in contents.items():
        digest = hashes[key]
        if (not isinstance(content, bytes) or not isinstance(digest, str)
                or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or hashlib.sha256(content).hexdigest() != digest):
            raise ValueError('delivery_archive_snapshot_hash_mismatch')
    archive_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = archive_dir.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError('delivery_archive_directory_invalid')
    archive_dir.chmod(0o700)
    for key, suffix in SUFFIXES.items():
        target = archive_dir / (hashes[key] + suffix)
        content = contents[key]
        if target.exists() or target.is_symlink():
            _matches(target, content)
            continue
        descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=archive_dir)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Linking publishes the fully written file without replacing
                # any concurrently created immutable archive of the same name.
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError:
                _matches(target, content)
        finally:
            os.unlink(temporary)
        _matches(target, content)
    for directory in (archive_dir, archive_dir.parent):
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
