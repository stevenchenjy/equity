"""Own refresh stage groups without detaching them from the pipeline session."""
from __future__ import annotations

import os
import signal
import subprocess
import time


def wait_unreaped(child: subprocess.Popen, timeout: float) -> None:
    """Observe exit while retaining the child PID until group cleanup finishes.

    Darwin may hide a zombie from getsid(), but WNOWAIT keeps its identifier
    reserved. A new unrelated process cannot borrow that PID/PGID/SID between
    observing its exit and cleaning its still-live descendants.
    """
    deadline = time.monotonic() + timeout
    while True:
        result = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
        if result is not None and result.si_pid == child.pid:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(child.args, timeout)
        time.sleep(min(.05, remaining))


def _live_group_members(group: int, expected_session: int) -> list[int]:
    """Ignore unreaped zombies, while proving ownership of live recipients.

    Darwin returns EPERM for killpg() when a held group contains only a zombie.
    That is an empty live group, not a permission failure to be ignored. Keep
    the held child identifier until this numeric inventory and cleanup finish.
    """
    try:
        raw = subprocess.check_output(["/bin/ps", "-axo", "pid=,pgid=,stat="],
            text=True, timeout=5, stderr=subprocess.DEVNULL)
        rows = [line.split() for line in raw.splitlines() if line.strip()]
        members = []
        for row in rows:
            pid, pgid = int(row[0]), int(row[1])
            if pgid != group or row[2].startswith("Z"):
                continue
            try:
                if os.getsid(pid) != expected_session or os.getpgid(pid) != group:
                    raise RuntimeError("refresh_process_group_ownership_changed")
            except ProcessLookupError:
                continue  # The inventoried recipient exited before validation.
            members.append(pid)
        return members
    except (ValueError, IndexError, subprocess.SubprocessError) as exc:
        raise RuntimeError("refresh_process_inventory_unavailable") from exc


def _kill_group(group: int, expected_session: int) -> None:
    if not _live_group_members(group, expected_session):
        return
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # A live recipient can exit between inventory and signal. Only that
        # proved empty-live-group race is benign; a real permission defect is
        # still raised and cannot be relabelled as successful cleanup.
        if _live_group_members(group, expected_session):
            raise


def run_stage(command, *, cwd, stdout, stderr, timeout, check=False, on_start=None):
    # A new PGID, but the SAME SID: a stage timeout can clean its descendants,
    # and the scheduler can still prove ownership of every pipeline group.
    child = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                             process_group=0)
    expected_session = os.getsid(0)
    try:
        if on_start:
            on_start(child.pid)
        wait_unreaped(child, timeout)
    finally:
        # Keep the direct child unreaped until this exact group is gone. No
        # recycled numeric identifier is used to terminate an unrelated job.
        _kill_group(child.pid, expected_session)
        code = child.wait()
    if check and code:
        raise subprocess.CalledProcessError(code, command)
    return subprocess.CompletedProcess(command, code)


def terminate_session(session_id: int, *, known_stage_pid: int | None = None) -> None:
    """Kill only groups whose live members prove this newly owned SID.

    Numeric process inventory cannot expose command arguments or credentials.
    No unrelated launchd job, runtime lock holder or analyst shares this SID.
    A recorded stage PID is only a fallback lead and is revalidated by the OS.
    """
    # Stop the pipeline coordinator before killing a stage it is awaiting.
    # Otherwise it could reap that stage and start another PGID while the
    # inventory/cleanup loop is still running. Its identifier remains held by
    # the caller's WNOWAIT observation until all descendant groups are gone.
    _kill_group(session_id, session_id)
    try:
        raw = subprocess.check_output(["/bin/ps", "-axo", "pid="], text=True,
                                      timeout=5, stderr=subprocess.DEVNULL)
        pids = [int(value) for value in raw.split()]
    except (OSError, ValueError, subprocess.SubprocessError):
        pids = [session_id, *([known_stage_pid] if known_stage_pid else [])]
    groups = set()
    for pid in pids:
        try:
            if os.getsid(pid) == session_id:
                groups.add(os.getpgid(pid))
        except (ProcessLookupError, PermissionError):
            continue
    for group in groups:
        _kill_group(group, session_id)
