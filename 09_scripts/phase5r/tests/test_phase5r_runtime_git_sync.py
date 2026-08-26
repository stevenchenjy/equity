from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from phase5r_daily_common import ExclusiveFileLock  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
