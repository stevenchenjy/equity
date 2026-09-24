from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from test_runtime_git_sync import LocalRepositoryFixture, _git
import run_runtime_scheduler as runtime


class VerifiedDeploymentFallbackTests(unittest.TestCase):
    now = datetime.fromisoformat("2026-09-24T12:00:00-04:00")
    receipt_relative = Path("runtime-state/verified_deployment.local.json")

    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix="equity-verified-deploy-") as directory:
            fixture = LocalRepositoryFixture(Path(directory))
            with patch.object(runtime, "VERIFIED_DEPLOYMENT_RELATIVE_PATH", self.receipt_relative):
                yield fixture

    @contextmanager
    def offline(self, message="fatal: Could not resolve host: github.com", code="git_fetch_failed"):
        actual = runtime._git
        def wrapped(root, arguments, **kwargs):
            if arguments[0] == "fetch":
                raise runtime.RuntimeSyncError(code, message)
            return actual(root, arguments, **kwargs)
        with patch.object(runtime, "_git", side_effect=wrapped):
            yield

    def sync(self, fixture, *, job="dailyrefresh", sync_only=False, current=None):
        return runtime.sync_runtime_for_job(fixture.runtime, job=job, sync_only=sync_only,
            expected_remote_url=str(fixture.remote), current=current or self.now)

    def test_clean_online_sync_records_receipt_then_dns_uses_same_commit_without_renewal(self):
        with self.fixture() as fixture:
            first = self.sync(fixture)
            path = fixture.runtime / self.receipt_relative
            before = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.offline():
                result = self.sync(fixture, current=self.now + timedelta(hours=5))
            self.assertEqual(result.action, "verified_deployment_network_fallback")
            self.assertEqual(result.commit, first.commit)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(_git(fixture.runtime, "status", "--porcelain"), "")

    def test_sender_and_sync_only_never_fall_back(self):
        with self.fixture() as fixture:
            self.sync(fixture)
            for job, sync_only in (("dailydecision", False), ("dailyrefresh", True)):
                with self.subTest(job=job, sync_only=sync_only), self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                    self.sync(fixture, job=job, sync_only=sync_only)
                self.assertEqual(error.exception.code, "git_fetch_failed")

    def test_auth_tls_permissions_generic_errors_and_command_timeouts_never_fall_back(self):
        with self.fixture() as fixture:
            self.sync(fixture)
            for message, code in (("Authentication failed", "git_fetch_failed"),
                                  ("SSL certificate problem", "git_fetch_failed"),
                                  ("TLS connection timed out", "git_fetch_failed"),
                                  ("Permission denied", "git_fetch_failed"),
                                  ("HTTP 403 failed to connect", "git_fetch_failed"),
                                  ("unspecified remote failure", "git_fetch_failed"),
                                  ("git operation timed out", "git_command_timeout")):
                with self.subTest(message=message), self.offline(message, code), self.assertRaises(runtime.RuntimeSyncError) as error:
                    self.sync(fixture)
                self.assertEqual(error.exception.code, code)

    def test_missing_expired_future_invalid_and_identity_mismatched_receipts_block(self):
        with self.fixture() as fixture:
            with self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "verified_deployment_receipt_missing")
            self.sync(fixture)
            path = fixture.runtime / self.receipt_relative
            original = json.loads(path.read_text())
            for field, value, expected in (("verified_at", (self.now - timedelta(hours=25)).isoformat(), "verified_deployment_receipt_expired_or_future"),
                ("verified_at", (self.now + timedelta(hours=1)).isoformat(), "verified_deployment_receipt_expired_or_future"),
                ("verified_at", "2026-09-24T12:00:00", "verified_deployment_receipt_invalid"),
                ("commit", "0" * 40, "verified_deployment_identity_mismatch"),
                ("remote_url", "https://untrusted.invalid/repo", "verified_deployment_identity_mismatch")):
                path.write_text(json.dumps(dict(original, **{field: value})))
                with self.subTest(field=field, value=value), self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                    self.sync(fixture)
                self.assertEqual(error.exception.code, expected)

    def test_receipt_link_and_broad_permissions_rejected(self):
        with self.fixture() as fixture:
            self.sync(fixture)
            path = fixture.runtime / self.receipt_relative
            path.chmod(0o644)
            with self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "verified_deployment_receipt_unsafe")
            path.chmod(0o600)
            target = path.with_name("other.json")
            path.rename(target)
            path.symlink_to(target)
            with self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "verified_deployment_receipt_unsafe")

    def test_dirty_and_unknown_untracked_files_block_before_fallback(self):
        with self.fixture() as fixture:
            self.sync(fixture)
            tracked = fixture.runtime / "tracked.txt"
            tracked.write_text("changed\n")
            with self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "tracked_worktree_dirty")
            tracked.write_text("one\n")
            (fixture.runtime / "untracked.txt").write_text("unknown\n")
            with self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "untracked_worktree_unsafe")

    def test_known_new_remote_cannot_be_ignored_during_dns_outage(self):
        with self.fixture() as fixture:
            self.sync(fixture)
            fixture.push_author_change("new-remote\n")
            _git(fixture.runtime, "fetch", "origin", "main")
            with self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "verified_deployment_cached_remote_mismatch")

    def test_changed_local_commit_cannot_use_receipt_even_if_clean(self):
        with self.fixture() as fixture:
            self.sync(fixture)
            (fixture.runtime / "tracked.txt").write_text("local\n")
            _git(fixture.runtime, "add", "tracked.txt")
            _git(fixture.runtime, "commit", "-m", "unexpected local commit")
            with self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "verified_deployment_identity_mismatch")

    def test_validated_evidence_appends_still_require_clean_fallback_tree(self):
        with self.fixture() as fixture:
            self.sync(fixture)
            ledger = fixture.runtime / "03_source_data/equity_research/daily_evidence_ledger.csv"
            with ledger.open("a") as handle:
                handle.write("evidence-row\n")
            with patch.object(runtime, "_validate_runtime_evidence_chain"), self.offline(), self.assertRaises(runtime.RuntimeSyncError) as error:
                self.sync(fixture)
            self.assertEqual(error.exception.code, "verified_deployment_fallback_requires_clean_tree")


if __name__ == "__main__":
    unittest.main()
