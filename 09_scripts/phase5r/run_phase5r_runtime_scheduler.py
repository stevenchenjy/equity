#!/usr/bin/env python3
"""Lock, safely fast-forward, and execute one production Phase 5R scheduler.

The two production LaunchAgents share this wrapper.  One runtime-level flock is
held from before Git inspection through the complete scheduler process, so a
second invocation cannot update code while the first invocation is active. A
phase-aligned second invocation waits for a bounded handoff instead of losing
its due-state check. Ignored runtime state is never cleaned, reset, stashed, or
copied by this code.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import NoReturn, Sequence
from zoneinfo import ZoneInfo

from phase5r_daily_common import (
    RUNTIME_EXPECTED_CYCLE_DATE_ENV,
    ExclusiveFileLock,
)


PRODUCTION_RUNTIME_ROOT = Path("/Users/messssi/LocalRuntime/equity")
EXPECTED_REMOTE_URL = "https://github.com/stevenchenjy/equity.git"
EXPECTED_BRANCH = "main"
RUNTIME_LOCK_PATH = (
    PRODUCTION_RUNTIME_ROOT.parent
    / ".locks"
    / "equity-phase5r-runtime.lock"
)
EXECUTION_LOG_RELATIVE_PATH = Path(
    "00_project_control/run_logs/phase5r_runtime_execution_log.csv"
)
FETCH_TIMEOUT_SECONDS = 180
GIT_TIMEOUT_SECONDS = 60
# A pathological but still bounded holder can consume the individual Git
# command budgets plus the refresh scheduler's 900-second deterministic child,
# 360-second shadow child, and 90-second shadow-email child. One hour exceeds
# that aggregate budget with margin while still surfacing a genuinely stuck
# holder. The waiting launchd job remains active, so launchd cannot start a
# duplicate instance of that label while it is queued here.
RUNTIME_LOCK_WAIT_TIMEOUT_SECONDS = 3600
RUNTIME_LOCK_POLL_INTERVAL_SECONDS = 0.25
ET = ZoneInfo("America/New_York")
GIT_BINARY = "/usr/bin/git"

SCHEDULER_SCRIPTS = {
    "dailyrefresh": "run_phase5r_daily_refresh_scheduler.py",
    "dailydecision": "run_phase5r_daily_scheduler.py",
}

_SAFE_DETAIL = re.compile(r"[^A-Za-z0-9._:/@+ =(),-]")
_ICLOUD_MANAGED_ROOTS = (
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Library" / "Mobile Documents",
    Path.home() / "Library" / "CloudStorage",
)


class RuntimeSyncError(RuntimeError):
    """A fail-closed runtime synchronization outcome."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = _safe_detail(detail)


@dataclass(frozen=True, slots=True)
class RepositoryState:
    root: Path
    branch: str
    head: str
    upstream: str
    remote_url: str


@dataclass(frozen=True, slots=True)
class SyncResult:
    before_head: str
    commit: str
    remote_head: str
    action: str


def _safe_detail(value: object, limit: int = 240) -> str:
    text = " ".join(str(value).split())
    return _SAFE_DETAIL.sub("?", text)[:limit]


def _run_git_process(
    root: Path,
    arguments: Sequence[str],
    *,
    timeout: int = GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            [GIT_BINARY, *arguments],
            cwd=root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeSyncError("git_command_timeout", "git operation timed out") from exc
    except OSError as exc:
        raise RuntimeSyncError("git_command_unavailable", exc.__class__.__name__) from exc


def _git(
    root: Path,
    arguments: Sequence[str],
    *,
    error_code: str,
    timeout: int = GIT_TIMEOUT_SECONDS,
) -> str:
    process = _run_git_process(root, arguments, timeout=timeout)
    if process.returncode != 0:
        detail = process.stderr.strip().splitlines()
        raise RuntimeSyncError(
            error_code,
            detail[-1] if detail else f"git exit {process.returncode}",
        )
    return process.stdout.strip()


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    process = _run_git_process(
        root,
        ["merge-base", "--is-ancestor", ancestor, descendant],
    )
    if process.returncode == 0:
        return True
    if process.returncode == 1:
        return False
    raise RuntimeSyncError("git_ancestry_check_failed", process.stderr)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def assert_non_icloud_runtime_root(root: Path) -> None:
    """Refuse production execution from common iCloud-managed locations."""

    resolved = root.expanduser().resolve()
    for candidate in _ICLOUD_MANAGED_ROOTS:
        managed = candidate.expanduser().resolve()
        if resolved == managed or _is_relative_to(resolved, managed):
            raise RuntimeSyncError("runtime_root_inside_icloud")


def inspect_runtime_repository(
    root: Path,
    *,
    expected_remote_url: str = EXPECTED_REMOTE_URL,
    expected_branch: str = EXPECTED_BRANCH,
) -> RepositoryState:
    """Validate repository identity and tracked cleanliness without fetching."""

    supplied_root = root.expanduser()
    if not supplied_root.is_dir() or supplied_root.is_symlink():
        raise RuntimeSyncError("runtime_root_missing_or_symlink")
    root = supplied_root.resolve()
    git_directory = root / ".git"
    if not git_directory.is_dir() or git_directory.is_symlink():
        raise RuntimeSyncError("runtime_git_directory_invalid")

    top_level = Path(
        _git(root, ["rev-parse", "--show-toplevel"], error_code="not_git_repository")
    ).resolve()
    if top_level != root:
        raise RuntimeSyncError("unexpected_repository_root")

    branch = _git(
        root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        error_code="detached_or_unborn_head",
    )
    if branch != expected_branch:
        raise RuntimeSyncError("unexpected_branch", branch)

    upstream = _git(
        root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        error_code="upstream_missing",
    )
    if upstream != f"origin/{expected_branch}":
        raise RuntimeSyncError("unexpected_upstream", upstream)

    remote_url = _git(
        root,
        ["remote", "get-url", "origin"],
        error_code="origin_missing",
    )
    if remote_url != expected_remote_url:
        raise RuntimeSyncError("unexpected_origin_url")

    tracked_status = _git(
        root,
        ["status", "--porcelain=v1", "--untracked-files=no"],
        error_code="tracked_status_failed",
    )
    if tracked_status:
        path_count = len(tracked_status.splitlines())
        raise RuntimeSyncError("tracked_worktree_dirty", f"entries={path_count}")

    head = _git(root, ["rev-parse", "HEAD"], error_code="head_unreadable")
    return RepositoryState(
        root=root,
        branch=branch,
        head=head,
        upstream=upstream,
        remote_url=remote_url,
    )


def sync_runtime_repository(
    root: Path,
    *,
    expected_remote_url: str = EXPECTED_REMOTE_URL,
    expected_branch: str = EXPECTED_BRANCH,
) -> SyncResult:
    """Fetch and perform only a clean fast-forward, or fail without updating HEAD."""

    state = inspect_runtime_repository(
        root,
        expected_remote_url=expected_remote_url,
        expected_branch=expected_branch,
    )
    root = state.root
    _git(
        root,
        [
            "fetch",
            "--no-tags",
            "origin",
            f"+refs/heads/{expected_branch}:refs/remotes/origin/{expected_branch}",
        ],
        error_code="git_fetch_failed",
        timeout=FETCH_TIMEOUT_SECONDS,
    )
    local_head = _git(root, ["rev-parse", "HEAD"], error_code="head_unreadable")
    remote_ref = f"refs/remotes/origin/{expected_branch}"
    remote_head = _git(
        root,
        ["rev-parse", remote_ref],
        error_code="remote_head_unreadable",
    )

    if local_head == remote_head:
        action = "identical"
    elif _is_ancestor(root, local_head, remote_head):
        # This command cannot create a merge commit or resolve content.  It
        # advances the checked-out branch only when Git proves a fast-forward.
        _git(
            root,
            [
                "-c",
                "core.hooksPath=/dev/null",
                "merge",
                "--ff-only",
                "--no-edit",
                remote_ref,
            ],
            error_code="fast_forward_failed",
        )
        action = "fast_forward"
    elif _is_ancestor(root, remote_head, local_head):
        raise RuntimeSyncError("runtime_branch_ahead_of_origin")
    else:
        raise RuntimeSyncError("runtime_history_divergent")

    final_state = inspect_runtime_repository(
        root,
        expected_remote_url=expected_remote_url,
        expected_branch=expected_branch,
    )
    if final_state.head != remote_head:
        raise RuntimeSyncError("post_sync_head_mismatch")
    return SyncResult(
        before_head=state.head,
        commit=final_state.head,
        remote_head=remote_head,
        action=action,
    )


def _append_execution_record(
    root: Path,
    *,
    job: str,
    event: str,
    outcome: str,
    commit: str,
    sync_action: str,
    detail: str = "",
) -> None:
    ignored = _run_git_process(
        root,
        ["check-ignore", "--quiet", "--", str(EXECUTION_LOG_RELATIVE_PATH)],
    )
    if ignored.returncode != 0:
        raise RuntimeSyncError("runtime_execution_log_not_ignored")
    target = root / EXECUTION_LOG_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = target.parent.resolve()
    if not _is_relative_to(resolved_parent, root.resolve()):
        raise RuntimeSyncError("runtime_log_parent_unsafe")

    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeSyncError("runtime_log_nofollow_unavailable")
    descriptor = os.open(target, flags | os.O_NOFOLLOW, 0o600)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise RuntimeSyncError("runtime_log_file_unsafe")

    fields = (
        "timestamp",
        "job",
        "event",
        "outcome",
        "commit",
        "sync_action",
        "detail",
    )
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if metadata.st_size == 0:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp": datetime.now(ET).isoformat(timespec="seconds"),
                    "job": job,
                    "event": event,
                    "outcome": outcome,
                    "commit": commit,
                    "sync_action": sync_action,
                    "detail": _safe_detail(detail),
                }
            )
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _scheduler_command(root: Path, job: str, *, safe_check: bool) -> list[str]:
    script = root / "09_scripts" / "phase5r" / SCHEDULER_SCRIPTS[job]
    if not script.is_file() or script.is_symlink():
        raise RuntimeSyncError("scheduler_script_missing_or_unsafe", job)
    command = [sys.executable, str(script)]
    if safe_check:
        command.append("--safe-check")
    return command


def _exec_scheduler(
    root: Path,
    job: str,
    lock: ExclusiveFileLock,
    *,
    expected_cycle_date: date,
    expected_commit: str,
    sync_action: str,
) -> NoReturn:
    if lock.handle is None:
        raise RuntimeSyncError("runtime_lock_handle_missing")
    os.set_inheritable(lock.handle.fileno(), True)
    environment = os.environ.copy()
    commit = _git(
        root,
        ["rev-parse", "HEAD"],
        error_code="head_unreadable_before_exec",
    )
    if commit != expected_commit:
        raise RuntimeSyncError("head_changed_before_exec")
    ready_at = datetime.now(ET)
    if ready_at.date() != expected_cycle_date:
        raise RuntimeSyncError(
            "runtime_preflight_crossed_cycle_date",
            f"expected_date={expected_cycle_date.isoformat()} "
            f"ready_at={ready_at.isoformat()}",
        )
    environment["PHASE5R_RUNTIME_COMMIT"] = commit
    environment["PHASE5R_RUNTIME_JOB"] = job
    environment[RUNTIME_EXPECTED_CYCLE_DATE_ENV] = expected_cycle_date.isoformat()
    _append_execution_record(
        root,
        job=job,
        event="scheduler_exec_authorized",
        outcome="authorized",
        commit=commit,
        sync_action=sync_action,
    )
    print(
        f"runtime_preflight=passed job={job} "
        f"sync_action={sync_action} commit={commit}",
        flush=True,
    )
    os.chdir(root)
    try:
        os.execve(
            sys.executable,
            _scheduler_command(root, job, safe_check=False),
            environment,
        )
    except OSError as exc:
        raise RuntimeSyncError("scheduler_exec_failed", exc.__class__.__name__) from exc


def _best_effort_failure_record(root: Path, job: str, error: RuntimeSyncError) -> None:
    try:
        if not (root / ".git").is_dir():
            return
        commit = ""
        process = _run_git_process(root, ["rev-parse", "HEAD"])
        if process.returncode == 0:
            commit = process.stdout.strip()
        _append_execution_record(
            root,
            job=job,
            event="preflight",
            outcome="blocked",
            commit=commit,
            sync_action="none",
            detail=error.code,
        )
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, choices=sorted(SCHEDULER_SCRIPTS))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--safe-check", action="store_true")
    mode.add_argument("--sync-only", action="store_true")
    args = parser.parse_args()

    root = PRODUCTION_RUNTIME_ROOT
    invocation_started_at = datetime.now(ET)
    try:
        assert_non_icloud_runtime_root(root)
        with ExclusiveFileLock(
            RUNTIME_LOCK_PATH,
            wait_timeout_seconds=RUNTIME_LOCK_WAIT_TIMEOUT_SECONDS,
            poll_interval_seconds=RUNTIME_LOCK_POLL_INTERVAL_SECONDS,
        ) as lock:
            try:
                acquired_at = datetime.now(ET)
                if lock.contention_observed:
                    print(
                        f"runtime_preflight=lock_acquired_after_wait job={args.job} "
                        f"waited_seconds={lock.waited_seconds:.3f}",
                        flush=True,
                    )
                    if (
                        not args.safe_check
                        and not args.sync_only
                        and acquired_at.date() != invocation_started_at.date()
                    ):
                        raise RuntimeSyncError(
                            "runtime_lock_wait_crossed_cycle_date",
                            f"started_at={invocation_started_at.isoformat()} "
                            f"acquired_at={acquired_at.isoformat()}",
                        )
                if args.safe_check:
                    inspect_runtime_repository(root)
                    process = subprocess.run(
                        _scheduler_command(root, args.job, safe_check=True),
                        cwd=root,
                        check=False,
                    )
                    print(
                        f"runtime_safe_check_job={args.job} "
                        f"exit_code={process.returncode}",
                        flush=True,
                    )
                    return process.returncode

                result = sync_runtime_repository(root)
                if args.sync_only:
                    _append_execution_record(
                        root,
                        job=args.job,
                        event="sync_only",
                        outcome="passed",
                        commit=result.commit,
                        sync_action=result.action,
                    )
                    print(
                        f"runtime_sync=passed action={result.action} "
                        f"commit={result.commit}",
                        flush=True,
                    )
                    return 0

                ready_at = datetime.now(ET)
                if ready_at.date() != invocation_started_at.date():
                    raise RuntimeSyncError(
                        "runtime_preflight_crossed_cycle_date",
                        f"started_at={invocation_started_at.isoformat()} "
                        f"ready_at={ready_at.isoformat()}",
                    )
                _exec_scheduler(
                    root,
                    args.job,
                    lock,
                    expected_cycle_date=invocation_started_at.date(),
                    expected_commit=result.commit,
                    sync_action=result.action,
                )
            except RuntimeSyncError as exc:
                _best_effort_failure_record(root, args.job, exc)
                raise
    except RuntimeSyncError as exc:
        print(
            f"runtime_preflight=blocked reason={exc.code} detail={exc.detail}",
            file=sys.stderr,
            flush=True,
        )
        return 70
    except RuntimeError as exc:
        if "lock wait timed out" in str(exc):
            reason = "runtime_lock_wait_timeout"
        elif "lock already held" in str(exc):
            reason = "runtime_lock_held"
        else:
            reason = "runtime_lock_failed"
        print(
            f"runtime_preflight=blocked reason={reason}",
            file=sys.stderr,
            flush=True,
        )
        return 75

    return 70


if __name__ == "__main__":
    raise SystemExit(main())
