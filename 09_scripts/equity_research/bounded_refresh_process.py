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


def _kill_group(group: int) -> None:
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_stage(command, *, cwd, stdout, stderr, timeout, check=False, on_start=None):
    # A new PGID, but the SAME SID: a stage timeout can clean its descendants,
    # and the scheduler can still prove ownership of every pipeline group.
    child = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                             process_group=0)
    try:
        if on_start:
            on_start(child.pid)
        wait_unreaped(child, timeout)
    finally:
        # Keep the direct child unreaped until this exact group is gone. No
        # recycled numeric identifier is used to terminate an unrelated job.
        _kill_group(child.pid)
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
        _kill_group(group)
