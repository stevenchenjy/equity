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
from itertools import islice
from pathlib import Path


SUFFIXES = {'decision_sha256': '.json', 'brief_text_sha256': '.txt', 'brief_html_sha256': '.html'}


def _recover_crashed_publish_links(path: Path, metadata: os.stat_result) -> None:
    """Remove only known dead-process temporary links to these exact bytes.

    Unknown names, live publishers and unaccounted links remain fail-closed.
    The durable target is never removed or rewritten.
    """
    candidates = []
    pending = list(islice(path.parent.glob(".pending-*"), 129))
    if len(pending) > 128:
        raise ValueError("delivery_archive_pending_recovery_bound")
    for candidate in pending:
        item = candidate.lstat()
        if (item.st_dev, item.st_ino) != (metadata.st_dev, metadata.st_ino):
            continue
        match = re.fullmatch(r"\.pending-([1-9][0-9]*)-[a-z0-9_]{8}", candidate.name)
        if (match is None or not stat.S_ISREG(item.st_mode) or item.st_uid != os.getuid()
                or item.st_mode & 0o077):
            raise ValueError("delivery_archive_unrecognized_temporary_link")
        try:
            os.kill(int(match.group(1)), 0)
        except ProcessLookupError:
            candidates.append(candidate)
        except PermissionError as exc:
            raise ValueError("delivery_archive_publisher_status_unknown") from exc
        else:
            raise ValueError("delivery_archive_publisher_still_running")
    if metadata.st_nlink != len(candidates) + 1:
        raise ValueError("delivery_archive_unaccounted_hardlinks")
    for candidate in candidates:
        item = candidate.lstat()
        if (item.st_dev, item.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("delivery_archive_temporary_link_changed")
        candidate.unlink()
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _matches(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stream.read() != content):
            raise ValueError('delivery_archive_existing_content_invalid')
        if metadata.st_nlink != 1:
            _recover_crashed_publish_links(path, metadata)
            if os.fstat(stream.fileno()).st_nlink != 1:
                raise ValueError('delivery_archive_hardlink_recovery_incomplete')
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
        descriptor, temporary = tempfile.mkstemp(prefix=f'.pending-{os.getpid()}-', dir=archive_dir)
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
