from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from phase5r_daily_common import ExclusiveFileLock  # noqa: E402
import run_phase5r_daily_refresh_scheduler as refresh_scheduler  # noqa: E402
import run_phase5r_daily_scheduler as decision_scheduler  # noqa: E402
import run_phase5r_runtime_scheduler as runtime_wrapper  # noqa: E402
from run_phase5r_runtime_scheduler import (  # noqa: E402
    RuntimeSyncError,
    assert_non_icloud_runtime_root,
    inspect_runtime_repository,
    sync_runtime_repository,
)


def _git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["/usr/bin/git", *arguments],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed: {process.stderr.strip()}"
        )
    return process.stdout.strip()


class LocalRepositoryFixture:
    def __init__(self, parent: Path) -> None:
        self.remote = parent / "remote.git"
        self.author = parent / "author"
        self.runtime = parent / "runtime"
        self.remote.mkdir()
        _git(self.remote, "init", "--bare")
        self.author.mkdir()
        _git(self.author, "init", "--initial-branch=main")
        _git(self.author, "config", "user.name", "Phase5R Test")
        _git(self.author, "config", "user.email", "phase5r-test@example.invalid")
        (self.author / ".gitignore").write_text(
            "runtime-state/\n", encoding="utf-8"
        )
        (self.author / "tracked.txt").write_text("one\n", encoding="utf-8")
        _git(self.author, "add", ".gitignore", "tracked.txt")
        _git(self.author, "commit", "-m", "initial")
        _git(self.author, "remote", "add", "origin", str(self.remote))
        _git(self.author, "push", "-u", "origin", "main")
        _git(parent, "clone", "--branch", "main", str(self.remote), str(self.runtime))
        _git(self.runtime, "config", "user.name", "Phase5R Runtime Test")
        _git(
            self.runtime,
            "config",
            "user.email",
            "phase5r-runtime-test@example.invalid",
        )

    @property
    def initial_head(self) -> str:
        return _git(self.runtime, "rev-parse", "HEAD")

    def push_author_change(self, value: str) -> str:
        (self.author / "tracked.txt").write_text(value, encoding="utf-8")
        _git(self.author, "add", "tracked.txt")
        _git(self.author, "commit", "-m", f"author {value.strip()}")
        _git(self.author, "push", "origin", "main")
        return _git(self.author, "rev-parse", "HEAD")


class RuntimeGitSyncTests(unittest.TestCase):
    def test_git_child_never_receives_massive_authentication(self) -> None:
        canary = "offline-git-boundary-canary"
        completed = runtime_wrapper.subprocess.CompletedProcess(
            [runtime_wrapper.GIT_BINARY, "status"],
            0,
            stdout="",
            stderr="",
        )
        with (
            patch.dict(
                runtime_wrapper.os.environ,
                {"MASSIVE_API_KEY": canary},
                clear=True,
            ),
            patch.object(
                runtime_wrapper.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            result = runtime_wrapper._run_git_process(Path("/runtime"), ["status"])

        self.assertIs(result, completed)
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("MASSIVE_API_KEY", environment)
        self.assertNotIn(canary, str(run.call_args))

    def test_identical_runtime_continues_without_changing_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-equal-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            before = fixture.initial_head
            result = sync_runtime_repository(
                fixture.runtime,
                expected_remote_url=str(fixture.remote),
            )
            self.assertEqual(result.action, "identical")
            self.assertEqual(result.before_head, before)
            self.assertEqual(result.commit, before)

    def test_strictly_behind_runtime_fast_forwards_and_preserves_ignored_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-behind-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            state_path = fixture.runtime / "runtime-state" / "scheduler.json"
            state_path.parent.mkdir()
            state_path.write_bytes(b'{"attempts": 2}\n')
            state_digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
            remote_head = fixture.push_author_change("two\n")

            result = sync_runtime_repository(
                fixture.runtime,
                expected_remote_url=str(fixture.remote),
            )

            self.assertEqual(result.action, "fast_forward")
            self.assertEqual(result.commit, remote_head)
            self.assertEqual(_git(fixture.runtime, "rev-parse", "HEAD"), remote_head)
            self.assertEqual(
                hashlib.sha256(state_path.read_bytes()).hexdigest(), state_digest
            )
            self.assertEqual(
                _git(
                    fixture.runtime,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ),
                "",
            )

    def test_dirty_tracked_runtime_fails_before_fetch_or_head_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-dirty-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            before = fixture.initial_head
            remote_tracking_before = _git(
                fixture.runtime, "rev-parse", "refs/remotes/origin/main"
            )
            fixture.push_author_change("remote-two\n")
            (fixture.runtime / "tracked.txt").write_text(
                "unexpected local edit\n", encoding="utf-8"
            )

            with self.assertRaises(RuntimeSyncError) as context:
                sync_runtime_repository(
                    fixture.runtime,
                    expected_remote_url=str(fixture.remote),
                )

            self.assertEqual(context.exception.code, "tracked_worktree_dirty")
            self.assertEqual(_git(fixture.runtime, "rev-parse", "HEAD"), before)
            self.assertEqual(
                _git(fixture.runtime, "rev-parse", "refs/remotes/origin/main"),
                remote_tracking_before,
            )

    def test_divergent_runtime_fetches_but_refuses_to_change_local_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-divergent-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            (fixture.runtime / "runtime-only.txt").write_text(
                "local commit\n", encoding="utf-8"
            )
            _git(fixture.runtime, "add", "runtime-only.txt")
            _git(fixture.runtime, "commit", "-m", "runtime-only commit")
            local_head = _git(fixture.runtime, "rev-parse", "HEAD")
            remote_head = fixture.push_author_change("remote-divergence\n")

            with self.assertRaises(RuntimeSyncError) as context:
                sync_runtime_repository(
                    fixture.runtime,
                    expected_remote_url=str(fixture.remote),
                )

            self.assertEqual(context.exception.code, "runtime_history_divergent")
            self.assertEqual(_git(fixture.runtime, "rev-parse", "HEAD"), local_head)
            self.assertEqual(
                _git(fixture.runtime, "rev-parse", "refs/remotes/origin/main"),
                remote_head,
            )

    def test_local_ahead_runtime_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-ahead-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            (fixture.runtime / "runtime-only.txt").write_text(
                "local commit\n", encoding="utf-8"
            )
            _git(fixture.runtime, "add", "runtime-only.txt")
            _git(fixture.runtime, "commit", "-m", "runtime-only commit")
            local_head = _git(fixture.runtime, "rev-parse", "HEAD")

            with self.assertRaises(RuntimeSyncError) as context:
                sync_runtime_repository(
                    fixture.runtime,
                    expected_remote_url=str(fixture.remote),
                )

            self.assertEqual(
                context.exception.code, "runtime_branch_ahead_of_origin"
            )
            self.assertEqual(_git(fixture.runtime, "rev-parse", "HEAD"), local_head)

    def test_unavailable_remote_fails_closed_without_head_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-network-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            before = fixture.initial_head
            missing_remote = Path(directory) / "unavailable.git"
            _git(
                fixture.runtime,
                "remote",
                "set-url",
                "origin",
                str(missing_remote),
            )

            with self.assertRaises(RuntimeSyncError) as context:
                sync_runtime_repository(
                    fixture.runtime,
                    expected_remote_url=str(missing_remote),
                )

            self.assertEqual(context.exception.code, "git_fetch_failed")
            self.assertEqual(_git(fixture.runtime, "rev-parse", "HEAD"), before)

    def test_repository_identity_rejects_wrong_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-origin-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            with self.assertRaises(RuntimeSyncError) as context:
                inspect_runtime_repository(
                    fixture.runtime,
                    expected_remote_url="https://example.invalid/not-equity.git",
                )
            self.assertEqual(context.exception.code, "unexpected_origin_url")

    def test_production_guard_rejects_icloud_managed_roots(self) -> None:
        with self.assertRaises(RuntimeSyncError) as context:
            assert_non_icloud_runtime_root(Path.home() / "Desktop" / "equity")
        self.assertEqual(context.exception.code, "runtime_root_inside_icloud")


class RuntimeLockConcurrencyTests(unittest.TestCase):
    @staticmethod
    def _start_timed_holder(
        lock_path: Path, hold_seconds: float
    ) -> subprocess.Popen[str]:
        helper = "\n".join(
            (
                "import sys",
                "import time",
                "from pathlib import Path",
                f"sys.path.insert(0, {str(SCRIPT_DIR)!r})",
                "from phase5r_daily_common import ExclusiveFileLock",
                "with ExclusiveFileLock(Path(sys.argv[1])):",
                "    print('locked', flush=True)",
                "    time.sleep(float(sys.argv[2]))",
            )
        )
        process = subprocess.Popen(
            [sys.executable, "-c", helper, str(lock_path), str(hold_seconds)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None
        if process.stdout.readline().strip() != "locked":
            stderr = process.stderr.read() if process.stderr is not None else ""
            process.wait(timeout=10)
            raise AssertionError(f"timed lock holder failed to start: {stderr}")
        return process

    @staticmethod
    def _finish_holder(process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=10)
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def test_independent_process_cannot_acquire_runtime_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-lock-") as directory:
            lock_path = Path(directory) / "runtime.lock"
            helper = "\n".join(
                (
                    "import sys",
                    "from pathlib import Path",
                    f"sys.path.insert(0, {str(SCRIPT_DIR)!r})",
                    "from phase5r_daily_common import ExclusiveFileLock",
                    "with ExclusiveFileLock(Path(sys.argv[1])):",
                    "    print('locked', flush=True)",
                    "    sys.stdin.readline()",
                )
            )
            process = subprocess.Popen(
                [sys.executable, "-c", helper, str(lock_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert process.stdout is not None
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with self.assertRaisesRegex(RuntimeError, "lock already held"):
                    with ExclusiveFileLock(lock_path):
                        pass
            finally:
                if process.stdin is not None:
                    process.stdin.write("release\n")
                    process.stdin.flush()
                    process.stdin.close()
                process.wait(timeout=10)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
            self.assertEqual(process.returncode, 0)

    def test_bounded_wait_acquires_after_active_holder_exits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-wait-") as directory:
            lock_path = Path(directory) / "runtime.lock"
            process = self._start_timed_holder(lock_path, 0.12)
            started = time.monotonic()
            try:
                with ExclusiveFileLock(
                    lock_path,
                    wait_timeout_seconds=2.0,
                    poll_interval_seconds=0.005,
                ) as lock:
                    elapsed = time.monotonic() - started
                    self.assertTrue(lock.contention_observed)
                    self.assertGreaterEqual(elapsed, 0.08)
                    self.assertGreaterEqual(lock.waited_seconds, 0.08)
            finally:
                self._finish_holder(process)
            self.assertEqual(process.returncode, 0)

    def test_bounded_wait_times_out_without_stealing_active_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-timeout-") as directory:
            lock_path = Path(directory) / "runtime.lock"
            process = self._start_timed_holder(lock_path, 0.25)
            started = time.monotonic()
            try:
                with self.assertRaisesRegex(RuntimeError, "lock wait timed out"):
                    with ExclusiveFileLock(
                        lock_path,
                        wait_timeout_seconds=0.05,
                        poll_interval_seconds=0.005,
                    ):
                        self.fail("timed-out waiter acquired an active lock")
                elapsed = time.monotonic() - started
                self.assertGreaterEqual(elapsed, 0.04)
                self.assertIsNone(process.poll())
            finally:
                self._finish_holder(process)
            self.assertEqual(process.returncode, 0)

    def test_phase_aligned_waiters_complete_every_accelerated_cycle(self) -> None:
        """A stable winner cannot starve the queued label over repeated cycles."""

        cycles = 24
        completed_refresh = 0
        completed_decision = 0
        with tempfile.TemporaryDirectory(prefix="phase5r-sync-cadence-") as directory:
            lock_path = Path(directory) / "runtime.lock"
            for _ in range(cycles):
                # Model refresh winning the same phase-aligned race every time.
                holder = self._start_timed_holder(lock_path, 0.015)
                completed_refresh += 1
                try:
                    with ExclusiveFileLock(
                        lock_path,
                        wait_timeout_seconds=0.5,
                        poll_interval_seconds=0.001,
                    ) as waiter:
                        self.assertTrue(waiter.contention_observed)
                        completed_decision += 1
                finally:
                    self._finish_holder(holder)
                self.assertEqual(holder.returncode, 0)

        self.assertEqual(completed_refresh, cycles)
        self.assertEqual(completed_decision, cycles)

    def test_production_wrapper_uses_bounded_wait_and_maps_timeout_to_75(
        self,
    ) -> None:
        captured: dict[str, object] = {}

        class TimedOutLock:
            def __init__(self, path: Path, **kwargs: object) -> None:
                captured["path"] = path
                captured.update(kwargs)

            def __enter__(self) -> "TimedOutLock":
                raise RuntimeError("lock wait timed out: isolated-test-lock")

            def __exit__(self, *args: object) -> None:
                return None

        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            patch.object(runtime_wrapper, "ExclusiveFileLock", TimedOutLock),
            patch.object(runtime_wrapper, "assert_non_icloud_runtime_root"),
            patch.object(
                runtime_wrapper.sys,
                "argv",
                ["runtime_scheduler.py", "--job", "dailydecision"],
            ),
            redirect_stderr(stderr),
            redirect_stdout(stdout),
        ):
            result = runtime_wrapper.main()

        self.assertEqual(result, 75)
        self.assertEqual(captured["path"], runtime_wrapper.RUNTIME_LOCK_PATH)
        self.assertEqual(
            captured["wait_timeout_seconds"],
            runtime_wrapper.RUNTIME_LOCK_WAIT_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            captured["poll_interval_seconds"],
            runtime_wrapper.RUNTIME_LOCK_POLL_INTERVAL_SECONDS,
        )
        self.assertIn("reason=runtime_lock_wait_timeout", stderr.getvalue())

    def test_cross_midnight_lock_handoff_fails_explicitly_before_sync(self) -> None:
        clock = iter(
            (
                datetime.fromisoformat("2026-08-25T23:59:58-04:00"),
                datetime.fromisoformat("2026-08-26T00:00:02-04:00"),
            )
        )

        class FakeDateTime:
            @classmethod
            def now(cls, timezone: object) -> datetime:
                return next(clock)

        class ContendedLock:
            contention_observed = True
            waited_seconds = 4.0

            def __init__(self, path: Path, **kwargs: object) -> None:
                pass

            def __enter__(self) -> "ContendedLock":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            patch.object(runtime_wrapper, "datetime", FakeDateTime),
            patch.object(runtime_wrapper, "ExclusiveFileLock", ContendedLock),
            patch.object(runtime_wrapper, "assert_non_icloud_runtime_root"),
            patch.object(runtime_wrapper, "sync_runtime_repository") as sync,
            patch.object(runtime_wrapper, "_best_effort_failure_record"),
            patch.object(
                runtime_wrapper.sys,
                "argv",
                ["runtime_scheduler.py", "--job", "dailydecision"],
            ),
            redirect_stderr(stderr),
            redirect_stdout(stdout),
        ):
            result = runtime_wrapper.main()

        self.assertEqual(result, 70)
        sync.assert_not_called()
        self.assertIn(
            "reason=runtime_lock_wait_crossed_cycle_date", stderr.getvalue()
        )

    def test_scheduler_children_reject_changed_runtime_cycle_before_state_reads(
        self,
    ) -> None:
        for scheduler in (refresh_scheduler, decision_scheduler):
            with self.subTest(scheduler=scheduler.__name__):
                stdout = io.StringIO()
                expected_environment = {
                    runtime_wrapper.RUNTIME_EXPECTED_CYCLE_DATE_ENV: "2026-08-25"
                }
                with (
                    patch.dict(scheduler.os.environ, expected_environment, clear=True),
                    patch.object(scheduler, "cycle_date", return_value="2026-08-26"),
                    patch.object(scheduler, "load_active_state") as load_active,
                    patch.object(scheduler, "load_inhibit") as load_inhibit,
                    redirect_stdout(stdout),
                ):
                    result = scheduler.main()

                self.assertEqual(result, 70)
                load_active.assert_not_called()
                load_inhibit.assert_not_called()
                self.assertIn(
                    "reason=runtime_invocation_cycle_date_changed",
                    stdout.getvalue(),
                )

    def test_final_pre_exec_guard_rejects_cycle_change_after_head_lookup(self) -> None:
        class FakeHandle:
            @staticmethod
            def fileno() -> int:
                return 42

        class FakeLock:
            handle = FakeHandle()

        class FakeDateTime:
            @classmethod
            def now(cls, timezone: object) -> datetime:
                return datetime.fromisoformat("2026-08-26T00:00:00-04:00")

        with (
            patch.object(runtime_wrapper.os, "set_inheritable"),
            patch.object(runtime_wrapper, "_git", return_value="a" * 40),
            patch.object(runtime_wrapper, "datetime", FakeDateTime),
            patch.object(runtime_wrapper.os, "execve") as execve,
            self.assertRaises(RuntimeSyncError) as context,
        ):
            runtime_wrapper._exec_scheduler(
                Path("/isolated/runtime"),
                "dailydecision",
                FakeLock(),  # type: ignore[arg-type]
                expected_cycle_date=date(2026, 8, 25),
                expected_commit="a" * 40,
                sync_action="identical",
            )

        self.assertEqual(
            context.exception.code, "runtime_preflight_crossed_cycle_date"
        )
        execve.assert_not_called()

    def test_authorized_exec_passes_expected_cycle_and_commit_to_child(self) -> None:
        class FakeHandle:
            @staticmethod
            def fileno() -> int:
                return 42

        class FakeLock:
            handle = FakeHandle()

        class FakeDateTime:
            @classmethod
            def now(cls, timezone: object) -> datetime:
                return datetime.fromisoformat("2026-08-25T18:30:00-04:00")

        commit = "b" * 40
        command = ["python3", "scheduler.py"]
        canary = "offline-runtime-secret-presence-canary"
        stdout = io.StringIO()
        with (
            patch.dict(
                runtime_wrapper.os.environ,
                {"MASSIVE_API_KEY": canary},
                clear=True,
            ),
            patch.object(runtime_wrapper.os, "set_inheritable"),
            patch.object(runtime_wrapper, "_git", return_value=commit),
            patch.object(runtime_wrapper, "datetime", FakeDateTime),
            patch.object(runtime_wrapper, "_append_execution_record") as append,
            patch.object(runtime_wrapper, "_scheduler_command", return_value=command),
            patch.object(runtime_wrapper.os, "chdir"),
            patch.object(runtime_wrapper.os, "execve") as execve,
            redirect_stdout(stdout),
        ):
            runtime_wrapper._exec_scheduler(
                Path("/isolated/runtime"),
                "dailydecision",
                FakeLock(),  # type: ignore[arg-type]
                expected_cycle_date=date(2026, 8, 25),
                expected_commit=commit,
                sync_action="identical",
            )

        append.assert_called_once_with(
            Path("/isolated/runtime"),
            job="dailydecision",
            event="scheduler_exec_authorized",
            outcome="authorized",
            commit=commit,
            sync_action="identical",
        )
        execve.assert_called_once()
        environment = execve.call_args.args[2]
        self.assertEqual(environment["MASSIVE_API_KEY"], canary)
        self.assertNotIn(canary, stdout.getvalue())
        self.assertEqual(environment["PHASE5R_RUNTIME_COMMIT"], commit)
        self.assertEqual(environment["PHASE5R_RUNTIME_JOB"], "dailydecision")
        self.assertEqual(
            environment[runtime_wrapper.RUNTIME_EXPECTED_CYCLE_DATE_ENV],
            "2026-08-25",
        )


if __name__ == "__main__":
    unittest.main()
