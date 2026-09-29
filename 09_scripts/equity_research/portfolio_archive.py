"""Keep exact private predecessors when portfolio files are replaced.

The active files remain the only decision inputs.  Archives are write-only
history and must never be used as a fallback for a missing current file.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path


POSITION_DIRECTORY_NAME = "05_risk_and_positions"
ARCHIVE_RELATIVE = Path("11_archive/portfolio_versions.local")


def _private_directory(path: Path, *, parents: bool = False) -> None:
    path.mkdir(parents=parents, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError(f"portfolio archive directory is unsafe: {path}")
    path.chmod(0o700)


def _archive_location(path: Path, source_bytes: bytes) -> Path | None:
    path = path.absolute()
    position_dir = next(
        (parent for parent in path.parents if parent.name == POSITION_DIRECTORY_NAME),
        None,
    )
    if position_dir is None:
        return None
    relative = path.relative_to(position_dir)
    digest = hashlib.sha256(source_bytes).hexdigest()
    return position_dir.parent / ARCHIVE_RELATIVE / relative / digest


def _verify_published_archive(destination: Path, source_bytes: bytes) -> None:
    metadata = destination.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError(f"portfolio archive is not a private regular file: {destination}")
    if destination.read_bytes() != source_bytes:
        raise ValueError(f"portfolio archive hash collision or corruption: {destination}")
    if metadata.st_nlink > 1:
        # A process can die after atomic publication but before removing its
        # temporary hard link. Recover only this writer's private named aliases,
        # never the final digest or a link elsewhere in the filesystem.
        pattern = re.compile(rf"\.{re.escape(destination.name)}\.[1-9][0-9]*\.[a-z0-9_]{{8}}\.tmp")
        aliases = []
        for sibling in destination.parent.iterdir():
            if pattern.fullmatch(sibling.name) is None:
                continue
            try:
                info = sibling.lstat()
            except FileNotFoundError:
                continue
            if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and (info.st_dev, info.st_ino) == (metadata.st_dev, metadata.st_ino)):
                aliases.append(sibling)
        if metadata.st_nlink != 1 + len(aliases):
            raise ValueError(f"portfolio archive is not a private regular file: {destination}")
        for sibling in aliases:
            try:
                info = sibling.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or (info.st_dev, info.st_ino) != (metadata.st_dev, metadata.st_ino)):
                raise ValueError(f"portfolio archive temporary link changed: {sibling}")
            sibling.unlink()
    final = destination.lstat()
    if (not stat.S_ISREG(final.st_mode) or final.st_nlink != 1
            or (final.st_dev, final.st_ino) != (metadata.st_dev, metadata.st_ino)
            or destination.read_bytes() != source_bytes):
        raise ValueError(f"portfolio archive changed during verification: {destination}")


def snapshot_current(path: Path) -> Path | None:
    """Save a byte-exact current revision once, without changing the source."""
    if path.is_symlink():
        raise ValueError(f"portfolio archive refuses a non-regular file: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"portfolio archive refuses a non-regular file: {path}")
    source_bytes = path.read_bytes()
    destination = _archive_location(path, source_bytes)
    if destination is None:
        return None
    # Private archives must not inherit a world-readable default directory mode.
    position_dir = next(
        parent for parent in path.absolute().parents
        if parent.name == POSITION_DIRECTORY_NAME
    )
    private_root = position_dir.parent / ARCHIVE_RELATIVE
    _private_directory(private_root, parents=True)
    relative_parent = destination.parent.relative_to(private_root)
    private_parent = private_root
    for part in relative_parent.parts:
        private_parent = private_parent / part
        _private_directory(private_parent)
    if destination.exists() or destination.is_symlink():
        _verify_published_archive(destination, source_bytes)
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.{os.getpid()}.", suffix=".tmp", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(source_bytes)
                output.flush()
                os.fsync(output.fileno())
            try:
                # Publish only complete, synced bytes; never replace history.
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                pass  # Verify the winner after removing our temporary alias.
        finally:
            temporary.unlink(missing_ok=True)
        _verify_published_archive(destination, source_bytes)
    # Flush the published name and newly created archive directory links before
    # the caller may replace the current source. Existing archives are synced
    # too, so retrying an earlier sync failure does not silently bypass it.
    directory = destination.parent
    workspace = position_dir.parent
    while True:
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if directory == workspace:
            break
        directory = directory.parent
    return destination


def archive_before_replace(path: Path, replacement: bytes) -> Path | None:
    """Fail closed if a changed predecessor cannot be safely preserved."""
    if path.is_symlink():
        raise ValueError(f"portfolio archive refuses a non-regular file: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"portfolio archive refuses a non-regular file: {path}")
    if path.read_bytes() == replacement:
        return None
    return snapshot_current(path)


def snapshot_active_portfolio(root: Path) -> list[Path]:
    """Cover direct owner edits as well as the writers hooked above."""
    position_dir = root / POSITION_DIRECTORY_NAME
    paths = [
        path for path in position_dir.iterdir()
        if path.is_file() and path.name != "README.md"
        and path.suffix in {".csv", ".json", ".jsonl", ".md"}
    ]
    generated = position_dir / "generated" / "current"
    if generated.exists():
        paths.extend(path for path in generated.iterdir() if path.is_file())
    return [archive for path in paths if (archive := snapshot_current(path)) is not None]
