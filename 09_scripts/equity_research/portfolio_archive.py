"""Keep exact private predecessors when portfolio files are replaced.

The active files remain the only decision inputs.  Archives are write-only
history and must never be used as a fallback for a missing current file.
"""

from __future__ import annotations

import hashlib
import os
import stat
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
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        metadata = destination.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError(f"portfolio archive is not a private regular file: {destination}")
        if destination.read_bytes() != source_bytes:
            raise ValueError(f"portfolio archive hash collision or corruption: {destination}")
        return destination
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(source_bytes)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
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
