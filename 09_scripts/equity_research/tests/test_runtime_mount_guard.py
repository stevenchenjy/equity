"""Mount recovery fixtures never invoke real disks, services or financial code."""
from __future__ import annotations

from contextlib import redirect_stdout
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[3] / "07_automation/scheduler/runtime_mount_guard.py"
SPEC = importlib.util.spec_from_file_location("runtime_mount_guard_under_test", SOURCE)
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)

UUID = "16FE77BD-4FA7-4F45-A81D-FAB0E8DF065D"
DISKUTIL = "/usr/sbin/diskutil"


class FakeDisk:
    """A stateful diskutil contract, with all subprocess arguments recorded."""
    def __init__(self, target, elsewhere):
        self.target = target
        self.calls = []
        self.timeouts = []
        self.present = True
        self.device = "disk77s1"
        self.mountpoint = str(elsewhere)
        self.unmount_code = 0
        self.mount_code = 0
        self.after_unmount = None
        self.overrides = {}
        self.device_overrides = {}
        self.target_overrides = {}

    def info(self):
        value = {"VolumeUUID": UUID, "DiskUUID": UUID, "FilesystemType": "apfs",
                 "Internal": False, "OSInternalMedia": False,
                 "DeviceIdentifier": self.device, "DeviceNode": "/dev/" + self.device,
                 "MountPoint": self.mountpoint, "Writable": True}
        value.update(self.overrides)
        return value

    @property
    def mutations(self):
        return [args for args in self.calls if args[1] in {"unmount", "mount"}]

    def __call__(self, command, timeout):
        args = list(command)
        self.calls.append(args)
        self.timeouts.append(timeout)
        if args[:3] == [DISKUTIL, "info", "-plist"]:
            if not self.present:
                return subprocess.CompletedProcess(args, 1, b"", b"volume not found")
            if args[3] not in {UUID, self.device, "/dev/" + self.device, str(self.target)}:
                return subprocess.CompletedProcess(args, 1, b"", b"stale or unknown device")
            value = self.info()
            if args[3] in {self.device, "/dev/" + self.device}:
                value.update(self.device_overrides)
            if args[3] == str(self.target):
                value.update(self.target_overrides)
            return subprocess.CompletedProcess(args, 0, plistlib.dumps(value), b"")
        if args == [DISKUTIL, "unmount", self.device]:
            if not self.unmount_code:
                self.mountpoint = ""
                if self.after_unmount:
                    self.after_unmount()
            return subprocess.CompletedProcess(args, self.unmount_code, b"", b"busy" if self.unmount_code else b"")
        if args == [DISKUTIL, "mount", "-mountPoint", str(self.target), self.device]:
            if not self.mount_code:
                self.mountpoint = str(self.target)
            return subprocess.CompletedProcess(args, self.mount_code, b"", b"mount failed" if self.mount_code else b"")
        raise AssertionError("Unexpected command in isolated fixture: " + repr(args))


class RuntimeMountGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.target = self.base / "LocalRuntime/equity"
        self.target.mkdir(parents=True)
        self.elsewhere = self.base / "Volumes/FixtureSSD"
        self.elsewhere.mkdir(parents=True)
        self.lock_path = self.base / "LocalRuntime/.locks/equity-research-runtime.lock"
        self.lock_path.parent.mkdir()
        self.lock_path.write_bytes(b"retained-runtime-lock-metadata\n")
        self.status_path = self.base / "Application Support/EquityResearch/mountguard.local.json"
        self.status_path.parent.mkdir(parents=True, mode=0o700)
        self.disk = FakeDisk(self.target, self.elsewhere)

    def instance(self):
        return guard.Guard(target=self.target, lock_path=self.lock_path,
                           status_path=self.status_path, runner=self.disk)

    def ensure(self, *, check=False):
        with redirect_stdout(io.StringIO()):
            return self.instance().ensure(check=check)

    def assert_no_disk_mutation(self):
        self.assertEqual(self.disk.mutations, [])
        self.assertTrue(all("force" not in args for args in self.disk.calls))

    def files(self):
        return {p.relative_to(self.base).as_posix(): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
                for p in self.base.rglob("*") if p.is_file() and not p.is_symlink()}

    def test_correct_mount_is_noop_even_with_repository_contents_and_busy_runtime(self):
        self.disk.mountpoint = str(self.target)
        marker = self.target / "retained-private-history"
        marker.write_bytes(b"do not modify")
        with self.lock_path.open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertEqual(marker.read_bytes(), b"do not modify")
        self.assertEqual(self.lock_path.read_bytes(), b"retained-runtime-lock-metadata\n")
        self.assertEqual(result["reason"], "canonical_ready")

    def test_missing_volume_is_retry_without_unmount_or_mount(self):
        self.disk.present = False
        result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertEqual(result["reason"], "ssd_unavailable")

    def test_wrong_uuid_filesystem_internal_disk_and_device_node_never_mutate(self):
        for changes, reason in (({"VolumeUUID": "different-volume"}, "disk_identity_rejected"),
                        ({"FilesystemType": "hfs"}, "filesystem_not_apfs"),
                        ({"Internal": True}, "disk_not_external"), ({"OSInternalMedia": True}, "disk_not_external"),
                        ({"APFSSnapshot": True}, "disk_identity_rejected"),
                        ({"Writable": False}, "disk_identity_rejected"),
                        ({"DeviceNode": "/dev/disk99s9"}, "device_identifier_invalid"),
                        ({"DeviceIdentifier": "disk77;echo unsafe"}, "device_identifier_invalid")):
            with self.subTest(changes=changes):
                self.disk.calls.clear()
                self.disk.overrides = changes
                result = self.ensure()
                self.assert_no_disk_mutation()
                self.assertEqual(result["reason"], reason)

    def test_occupied_target_is_preserved_before_normal_unmount(self):
        marker = self.target / "unrelated-owner-file"
        marker.write_bytes(b"preserve")
        result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertEqual(result["reason"], "target_occupied")
        self.assertEqual(marker.read_bytes(), b"preserve")
        self.assertEqual(self.disk.mountpoint, str(self.elsewhere))

    def test_empty_target_that_is_another_mount_is_occupied_before_any_unmount(self):
        with patch.object(guard.os.path, "ismount", return_value=True):
            result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertEqual(result["reason"], "target_occupied")
        self.assertEqual(self.disk.mountpoint, str(self.elsewhere))

    def test_uuid_lookup_cannot_authorize_a_device_query_with_different_identity(self):
        self.disk.device_overrides = {"VolumeUUID": "recycled-device"}
        self.ensure()
        self.assert_no_disk_mutation()

    def test_claimed_canonical_mount_must_match_actual_target_identity(self):
        self.disk.mountpoint = str(self.target)
        self.disk.target_overrides = {"VolumeUUID": "other-mounted-volume"}
        result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertNotEqual(result["reason"], "canonical_ready")

    def test_symlink_target_is_rejected_without_following_or_mutating_it(self):
        self.target.rmdir()
        self.target.symlink_to(self.elsewhere, target_is_directory=True)
        result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertEqual(result["reason"], "target_unsafe")
        self.assertTrue(self.target.is_symlink())

    def test_existing_runtime_flock_contention_defers_without_mutation(self):
        with self.lock_path.open("rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertIn("lock", result["reason"])
        self.assertEqual(self.disk.mountpoint, str(self.elsewhere))
        self.assertEqual(self.lock_path.read_bytes(), b"retained-runtime-lock-metadata\n")

    def test_missing_existing_lock_is_not_created_to_authorize_relocation(self):
        self.lock_path.unlink()
        result = self.ensure()
        self.assert_no_disk_mutation()
        self.assertEqual(result["reason"], "runtime_lock_unavailable")
        self.assertFalse(self.lock_path.exists())

    def test_symlinked_runtime_lock_is_not_followed_to_authorize_relocation(self):
        other = self.base / "other-lock"
        other.write_bytes(b"retain this unrelated lock")
        self.lock_path.unlink()
        self.lock_path.symlink_to(other)
        self.ensure()
        self.assert_no_disk_mutation()
        self.assertTrue(self.lock_path.is_symlink())
        self.assertEqual(other.read_bytes(), b"retain this unrelated lock")

    def test_busy_normal_unmount_retries_and_leaves_original_mount_in_place(self):
        self.disk.unmount_code = 16
        result = self.ensure()
        self.assertEqual(self.disk.mutations, [[DISKUTIL, "unmount", "disk77s1"]])
        self.assertEqual(self.disk.mountpoint, str(self.elsewhere))
        self.assertEqual(result["reason"], "disk_unmount_failed")

    def test_mount_failure_is_recorded_without_claiming_canonical_mount(self):
        self.disk.mount_code = 1
        result = self.ensure()
        self.assertEqual(self.disk.mutations, [
            [DISKUTIL, "unmount", "disk77s1"],
            [DISKUTIL, "mount", "-mountPoint", str(self.target), "disk77s1"]])
        self.assertNotEqual(self.disk.mountpoint, str(self.target))
        self.assertEqual(result["reason"], "disk_mount_failed")

    def test_normal_relocation_revalidates_between_unmount_and_mount_and_verifies_after(self):
        result = self.ensure()
        self.assertEqual(self.disk.mutations, [
            [DISKUTIL, "unmount", "disk77s1"],
            [DISKUTIL, "mount", "-mountPoint", str(self.target), "disk77s1"]])
        unmount = self.disk.calls.index(self.disk.mutations[0])
        mount = self.disk.calls.index(self.disk.mutations[1])
        self.assertTrue(any(args[:3] == [DISKUTIL, "info", "-plist"] and args[3] == UUID
                            for args in self.disk.calls[unmount + 1:mount]))
        self.assertTrue(any(args[:3] == [DISKUTIL, "info", "-plist"]
                            for args in self.disk.calls[mount + 1:]))
        self.assertEqual(self.disk.mountpoint, str(self.target))
        self.assertTrue(all("force" not in args for args in self.disk.calls))
        self.assertIn("reason", result)

    def test_changed_volume_identity_after_unmount_cannot_mount_recycled_device(self):
        self.disk.after_unmount = lambda: self.disk.overrides.update(VolumeUUID="replacement-volume")
        self.ensure()
        self.assertEqual(self.disk.mutations, [[DISKUTIL, "unmount", "disk77s1"]])

    def test_fresh_device_identifier_after_unmount_is_used_instead_of_stale_identifier(self):
        self.disk.after_unmount = lambda: setattr(self.disk, "device", "disk88s2")
        self.ensure()
        self.assertEqual(self.disk.mutations, [
            [DISKUTIL, "unmount", "disk77s1"],
            [DISKUTIL, "mount", "-mountPoint", str(self.target), "disk88s2"]])
        self.assertIn([DISKUTIL, "info", "-plist", "disk88s2"], self.disk.calls)
        self.assertEqual(self.disk.mountpoint, str(self.target))

    def test_disk_commands_all_receive_finite_small_timeouts(self):
        self.ensure()
        self.assertTrue(self.disk.timeouts)
        self.assertTrue(all(0 < value <= 15 for value in self.disk.timeouts))

    def test_check_mode_does_not_create_lock_status_or_target_files(self):
        self.lock_path.unlink()
        self.status_path.parent.rmdir()
        self.status_path.parent.parent.rmdir()
        before = self.files()
        self.ensure(check=True)
        self.assert_no_disk_mutation()
        self.assertEqual(self.files(), before)
        self.assertFalse(self.status_path.exists())
        self.assertFalse(self.status_path.parent.exists())
        self.assertFalse(self.lock_path.exists())

    def test_semantically_unchanged_status_is_private_and_not_rewritten(self):
        self.disk.mountpoint = str(self.target)
        self.ensure()
        first = self.status_path.read_bytes()
        first_mtime = self.status_path.stat().st_mtime_ns
        self.ensure()
        self.assertEqual(self.status_path.read_bytes(), first)
        self.assertEqual(self.status_path.stat().st_mtime_ns, first_mtime)
        self.assertEqual(stat.S_IMODE(self.status_path.stat().st_mode), 0o600)
        self.assert_no_disk_mutation()

    def test_cli_logs_state_change_once_then_stays_quiet(self):
        self.disk.mountpoint = str(self.target)
        instance = self.instance()
        first, second = io.StringIO(), io.StringIO()
        with patch.object(guard, "Guard", return_value=instance), \
                patch.object(sys, "argv", ["runtime_mount_guard.py", "--ensure"]):
            with redirect_stdout(first):
                first_code = guard.main()
            with redirect_stdout(second):
                second_code = guard.main()
        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        self.assertTrue(first.getvalue().strip())
        self.assertEqual(second.getvalue(), "")
        self.assert_no_disk_mutation()

    def test_malformed_nonobject_status_is_replaced_by_private_current_metadata(self):
        self.disk.mountpoint = str(self.target)
        self.status_path.write_text("[]\n")
        result = self.ensure()
        self.assertEqual(result["reason"], "canonical_ready")
        self.assertTrue(result["state_changed"])
        self.assertEqual(json.loads(self.status_path.read_text())["reason"], "canonical_ready")
        self.assertEqual(stat.S_IMODE(self.status_path.stat().st_mode), 0o600)
        self.assert_no_disk_mutation()

    def test_linked_status_cannot_follow_or_overwrite_an_unrelated_file(self):
        unrelated = self.base / "unrelated-private-file"
        unrelated.write_bytes(b"preserve this file")
        self.status_path.symlink_to(unrelated)
        result = self.ensure()
        self.assertEqual(result["reason"], "status_path_unsafe")
        self.assertEqual(unrelated.read_bytes(), b"preserve this file")
        self.assertTrue(self.status_path.is_symlink())
        self.assert_no_disk_mutation()

    def test_plist_executes_only_internal_guard_with_bounded_login_mount_and_interval_triggers(self):
        template = SOURCE.with_name("com.steven.equity_research.mountguard.plist.template")
        value = plistlib.loads(template.read_bytes())
        self.assertEqual(value["Label"], "com.steven.equity_research.mountguard")
        self.assertEqual(value["ProgramArguments"], [
            "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
            "/Users/messssi/Library/Application Support/EquityResearch/bin/runtime_mount_guard.py",
            "--ensure"])
        self.assertEqual(value["WorkingDirectory"], "/Users/messssi/Library/Application Support/EquityResearch")
        self.assertIs(value["RunAtLoad"], True)
        self.assertIs(value["StartOnMount"], True)
        self.assertEqual(value["StartInterval"], 60)
        self.assertIs(value["KeepAlive"], False)
        self.assertNotIn("EnvironmentVariables", value)


if __name__ == "__main__":
    unittest.main()
