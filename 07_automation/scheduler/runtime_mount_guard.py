#!/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
"""Restore one external APFS runtime mount; never execute runtime code.

Only --ensure can change a mount or write the internal private status receipt.
The existing runtime flock excludes an active research/deployment owner. Normal
Disk Arbitration unmount remains authoritative: a busy volume is never forced.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import tempfile
import time

UUID = '16FE77BD-4FA7-4F45-A81D-FAB0E8DF065D'
TARGET = Path('/Users/messssi/LocalRuntime/equity')
LOCK_PATH = Path('/Users/messssi/LocalRuntime/.locks/equity-research-runtime.lock')
STATUS_PATH = Path('/Users/messssi/Library/Application Support/EquityResearch/runtime_mount_guard.local.json')
DISKUTIL = '/usr/sbin/diskutil'
MAX_SECONDS = 50
INFO_SECONDS = 5
UNMOUNT_SECONDS = 15
MOUNT_SECONDS = 15


class GuardError(RuntimeError):
    def __init__(self, reason, *, retry=False):
        super().__init__(reason)
        self.reason, self.retry = reason, retry


def command_runner(command, timeout):
    return subprocess.run(command, capture_output=True, timeout=timeout, check=False)


class Guard:
    def __init__(self, *, target=TARGET, lock_path=LOCK_PATH, status_path=STATUS_PATH,
                 runner=command_runner):
        # Only isolated fixtures override these paths. The CLI exposes no disk,
        # UUID, target, lock, command or status-path override.
        self.target = Path(target).absolute()
        self.lock_path = Path(lock_path).absolute()
        self.status_path = Path(status_path).absolute()
        self.runner = runner
        self.device = None
        self.mountpoint = None
        self.changed_mount = False

    def _command(self, arguments, maximum):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GuardError('guard_budget_exhausted', retry=True)
        try:
            return self.runner([DISKUTIL, *arguments], timeout=min(maximum, remaining))
        except subprocess.TimeoutExpired:
            # Disk Arbitration may finish after its client times out. The next
            # invocation observes identity/state again; never retry blindly.
            raise GuardError('diskutil_timeout', retry=True) from None
        except OSError:
            raise GuardError('diskutil_unavailable', retry=True) from None

    def _info(self, locator, *, missing=False):
        result = self._command(['info', '-plist', str(locator)], INFO_SECONDS)
        if result.returncode:
            raise GuardError('ssd_unavailable' if missing else 'disk_info_unavailable', retry=True)
        try:
            value = plistlib.loads(result.stdout)
        except (ValueError, TypeError, plistlib.InvalidFileException):
            raise GuardError('disk_info_invalid') from None
        if not isinstance(value, dict):
            raise GuardError('disk_info_invalid')
        return value

    def _identity(self, value):
        if value.get('VolumeUUID') != UUID:
            raise GuardError('disk_identity_rejected')
        if value.get('FilesystemType') != 'apfs':
            raise GuardError('filesystem_not_apfs')
        if value.get('Internal') is not False or value.get('OSInternalMedia') is not False:
            raise GuardError('disk_not_external')
        if value.get('APFSSnapshot') is True or value.get('Writable') is False:
            raise GuardError('disk_identity_rejected')
        device = value.get('DeviceIdentifier')
        if (not isinstance(device, str) or re.fullmatch(r'disk\d+s\d+', device) is None
                or value.get('DeviceNode') != '/dev/' + device):
            raise GuardError('device_identifier_invalid')
        mountpoint = value.get('MountPoint') or ''
        if not isinstance(mountpoint, str) or (mountpoint and not Path(mountpoint).is_absolute()):
            raise GuardError('disk_info_invalid')
        self.device, self.mountpoint = device, mountpoint
        return device, mountpoint

    def _target_safe(self, *, empty=False):
        try:
            metadata = self.target.lstat()
            parent = self.target.parent.stat()
            if (self.target.resolve() != self.target or self.target.parent.resolve() != self.target.parent
                    or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()):
                raise GuardError('target_unsafe')
            if empty and (os.path.ismount(self.target) or next(self.target.iterdir(), None) is not None):
                raise GuardError('target_occupied')
        except OSError:
            raise GuardError('target_unsafe') from None

    def _canonical(self, value):
        device, mountpoint = self._identity(value)
        if mountpoint != str(self.target):
            return False
        self._target_safe()
        # Bind the path as well as the UUID lookup before accepting repository
        # contents or reporting availability. This executes no repository code.
        actual = self._info(self.target)
        if self._identity(actual) != (device, str(self.target)):
            raise GuardError('mount_not_verified', retry=True)
        return True

    @contextmanager
    def _runtime_lock(self):
        fd = None
        try:
            metadata = self.lock_path.lstat()
            if (self.lock_path.resolve() != self.lock_path
                    or self.lock_path.parent.resolve() != self.lock_path.parent
                    or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or metadata.st_uid != os.getuid() or not hasattr(os, 'O_NOFOLLOW')):
                raise GuardError('runtime_lock_unavailable', retry=True)
            # No O_CREAT, truncation or PID write: use exactly the existing
            # flock inode used by the maintained runtime, not a substitute lock.
            fd = os.open(self.lock_path, os.O_RDWR | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or opened.st_uid != os.getuid()):
                raise GuardError('runtime_lock_unavailable', retry=True)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise GuardError('runtime_lock_busy', retry=True) from None
            yield
        except OSError:
            raise GuardError('runtime_lock_unavailable', retry=True) from None
        finally:
            if fd is not None:
                os.close(fd)

    def _device_matches(self, value):
        identity = self._identity(value)
        if self._identity(self._info(identity[0])) != identity:
            raise GuardError('disk_identity_rejected')
        return identity

    def _inspect_or_restore(self, check):
        value = self._info(UUID, missing=True)
        if self._canonical(value):
            return 'ready', 'canonical_ready', False
        self._target_safe(empty=True)
        if check:
            return 'check', 'mount_relocation_required' if self.mountpoint else 'mount_required', True
        with self._runtime_lock():
            # Re-read under the shared runtime lock; no observation made before
            # lock acquisition can authorize an unmount or mount.
            value = self._info(UUID, missing=True)
            if self._canonical(value):
                return 'ready', 'canonical_ready', False
            self._target_safe(empty=True)
            device, mountpoint = self._device_matches(value)
            if mountpoint:
                result = self._command(['unmount', device], UNMOUNT_SECONDS)
                if result.returncode:
                    raise GuardError('disk_unmount_failed', retry=True)
                self.changed_mount = True
            # APFS device numbers can change on reconnect. Resolve by UUID
            # again, then bind that current device before the mount command.
            value = self._info(UUID, missing=True)
            if self._canonical(value):
                return 'ready', 'canonical_ready', False
            device, mountpoint = self._device_matches(value)
            if mountpoint:
                raise GuardError('disk_still_mounted', retry=True)
            self._target_safe(empty=True)
            result = self._command(['mount', '-mountPoint', str(self.target), device], MOUNT_SECONDS)
            if result.returncode:
                raise GuardError('disk_mount_failed', retry=True)
            self.changed_mount = True
            if not self._canonical(self._info(UUID, missing=True)):
                raise GuardError('mount_not_verified', retry=True)
            return 'ready', 'canonical_mount_verified', False

    def _status_safe(self):
        try:
            parent = self.status_path.parent.stat()
            if (self.status_path.parent.resolve() != self.status_path.parent
                    or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()):
                return False
            if self.status_path.exists() or self.status_path.is_symlink():
                metadata = self.status_path.lstat()
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                        or metadata.st_uid != os.getuid()):
                    return False
            return True
        except OSError:
            return False

    def _persist(self, result):
        if not self._status_safe():
            return False
        try:
            previous = json.loads(self.status_path.read_text())
        except (OSError, ValueError):
            previous = {}
        if not isinstance(previous, dict):
            previous = {}
        if ({key: value for key, value in previous.items() if key != 'observed_at_utc'} == result
                and stat.S_IMODE(self.status_path.stat().st_mode) == 0o600):
            return False
        payload = {**result, 'observed_at_utc': datetime.now(timezone.utc).isoformat()}
        fd, temporary = tempfile.mkstemp(prefix='.runtime-mount-guard.', dir=self.status_path.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write((json.dumps(payload, sort_keys=True, indent=2) + '\n').encode('utf-8'))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.status_path)
            directory = os.open(self.status_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return True

    def ensure(self, *, check=False):
        self.deadline = time.monotonic() + MAX_SECONDS
        self.device, self.mountpoint, self.changed_mount = None, None, False
        try:
            if not check and not self._status_safe():
                raise GuardError('status_path_unsafe')
            status, reason, retry = self._inspect_or_restore(check)
        except GuardError as error:
            status, reason, retry = ('retry' if error.retry else 'rejected'), error.reason, error.retry
        result = {'schema_version': 'equity_runtime_mount_guard_v1',
            'status': status, 'reason': reason, 'retry': retry, 'check_only': bool(check),
            'volume_uuid': UUID, 'canonical_mountpoint': str(self.target),
            'device_identifier': self.device, 'observed_mountpoint': self.mountpoint,
            'mount_changed': self.changed_mount,
            'runtime_code_invoked': False, 'email_invoked': False, 'service_changes': False}
        try:
            changed = False if check else self._persist(result)
        except OSError:
            result.update(status='rejected', reason='status_write_failed', retry=True)
            changed = False
        return {**result, 'state_changed': changed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='read-only metadata check; no receipt or lock writes')
    mode.add_argument('--ensure', action='store_true', help='bounded UUID-verified relocation under the existing runtime lock')
    args = parser.parse_args(argv)
    result = Guard().ensure(check=args.check)
    if args.check or result['state_changed']:
        print(json.dumps(result, sort_keys=True))
    return 2 if result['status'] == 'rejected' else 0


if __name__ == '__main__':
    raise SystemExit(main())
