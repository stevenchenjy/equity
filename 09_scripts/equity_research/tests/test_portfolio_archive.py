from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from account_common import write_csv
import daily_common
from daily_common import atomic_write_text, atomic_write_json, atomic_write_csv
import portfolio_archive
from portfolio_archive import snapshot_active_portfolio, snapshot_current


class PortfolioArchiveTests(unittest.TestCase):
    def test_outside_scope_reports_and_journals_never_read_archive_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "04_research/report.json"
            journal = root / "04_research/opportunities/store.json"
            rows = root / "03_source_data/observations.csv"
            for path in (report, journal, rows):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"previous bytes")
            payload = {"label": "日本語", "revision": 2}
            expected = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
            with patch.object(Path, "read_bytes", side_effect=AssertionError("out-of-scope archive read")), \
                    patch.object(daily_common, "archive_before_replace",
                                 wraps=portfolio_archive.archive_before_replace) as archive:
                self.assertIsNone(snapshot_current(report))
                self.assertIsNone(portfolio_archive.archive_before_replace(journal, b"new"))
                atomic_write_json(report, payload)
                atomic_write_text(journal, "exact new journal\n")
                atomic_write_csv(rows, ["ticker", "value"], [{"ticker": "ONE", "value": "a,b"}])
            self.assertEqual([call.args[1] for call in archive.call_args_list], [b"", b"", b""])
            self.assertEqual(report.read_bytes(), expected)
            self.assertEqual(journal.read_bytes(), b"exact new journal\n")
            self.assertEqual(rows.read_bytes(), b'ticker,value\nONE,"a,b"\n')
            self.assertFalse((root / "11_archive").exists())

    def test_outside_scope_keeps_symlink_and_nonregular_destination_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_bytes(b"untouched")
            for kind in ("symlink", "directory"):
                path = root / ("outside-" + kind)
                if kind == "symlink":
                    path.symlink_to(target)
                else:
                    path.mkdir()
                writers = [lambda: snapshot_current(path),
                    lambda: portfolio_archive.archive_before_replace(path, b"replacement"),
                    lambda: atomic_write_text(path, "replacement"),
                    lambda: atomic_write_csv(path, ["ticker"], [{"ticker": "ONE"}])]
                for writer in writers:
                    with self.subTest(kind=kind, writer=writer):
                        with patch.object(Path, "read_bytes", side_effect=AssertionError("unsafe read")):
                            with self.assertRaisesRegex(ValueError, "non-regular"):
                                writer()
                self.assertTrue(path.is_symlink() if kind == "symlink" else path.is_dir())
            self.assertEqual(target.read_bytes(), b"untouched")

    def test_lexical_scope_preserves_nearest_original_position_parent(self) -> None:
        path = Path("one/05_risk_and_positions/two/05_risk_and_positions/current.json")
        expected = next(parent for parent in path.absolute().parents
                        if parent.name == "05_risk_and_positions")
        self.assertEqual(portfolio_archive.portfolio_position_directory(path), expected)
        self.assertEqual(portfolio_archive._archive_location(path, b"bytes"),
            expected.parent / "11_archive/portfolio_versions.local/current.json" /
            hashlib.sha256(b"bytes").hexdigest())
        self.assertIsNone(portfolio_archive.portfolio_position_directory(Path("04_research/report.json")))

    def test_changed_managed_outputs_preserve_exact_predecessors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "05_risk_and_positions/generated/current/weights.csv"
            write_csv(output, [{"ticker": "ONE"}], ["ticker"])
            original = output.read_bytes()
            write_csv(output, [{"ticker": "TWO"}], ["ticker"])
            archive = (root / "11_archive/portfolio_versions.local/generated/current/weights.csv"
                       / hashlib.sha256(original).hexdigest())
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(output.read_text().splitlines(), ["ticker", "TWO"])
            write_csv(output, [{"ticker": "TWO"}], ["ticker"])
            self.assertEqual(len(list(archive.parent.iterdir())), 1)

    def test_manual_input_is_snapshotted_before_and_after_owner_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "05_risk_and_positions/current_open_orders.local.json"
            input_path.parent.mkdir()
            input_path.write_bytes(b'{"revision":1}\n')
            snapshot_active_portfolio(root)
            input_path.write_bytes(b'{"revision":2}\n')
            snapshot_active_portfolio(root)
            archives = sorted((root / "11_archive/portfolio_versions.local"
                               / input_path.relative_to(root / "05_risk_and_positions")).iterdir())
            self.assertEqual({item.read_bytes() for item in archives},
                             {b'{"revision":1}\n', b'{"revision":2}\n'})
            self.assertEqual(input_path.read_bytes(), b'{"revision":2}\n')

    def test_symlink_target_is_never_replaced_or_archived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("untouched")
            input_path = root / "05_risk_and_positions/current_account_state.local.json"
            input_path.parent.mkdir()
            input_path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "non-regular"):
                atomic_write_text(input_path, "replacement")
            self.assertEqual(target.read_text(), "untouched")
            self.assertTrue(input_path.is_symlink())

    def test_corrupt_archive_blocks_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "05_risk_and_positions/current_positions.local.csv"
            current.parent.mkdir()
            current.write_bytes(b"old")
            archive = (root / "11_archive/portfolio_versions.local/current_positions.local.csv"
                       / hashlib.sha256(b"old").hexdigest())
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "corruption"):
                atomic_write_text(current, "new")
            self.assertEqual(current.read_bytes(), b"old")

    def test_process_exit_mid_write_never_publishes_partial_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "05_risk_and_positions/current_positions.local.csv"
            current.parent.mkdir()
            original = b"ticker,shares\nTEST,1\n"
            current.write_bytes(original)
            destination = (root / "11_archive/portfolio_versions.local/current_positions.local.csv"
                           / hashlib.sha256(original).hexdigest())
            child = r"""
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import portfolio_archive
original_fdopen = os.fdopen
class InterruptedWrite:
    def __init__(self, descriptor, *args, **kwargs):
        self.handle = original_fdopen(descriptor, *args, **kwargs)
    def __enter__(self): return self
    def __exit__(self, *args): self.handle.close()
    def write(self, data):
        self.handle.write(data[:4])
        self.handle.flush()
        os.fsync(self.handle.fileno())
        os._exit(73)
portfolio_archive.os.fdopen = InterruptedWrite
portfolio_archive.snapshot_current(Path(sys.argv[2]))
"""
            run = subprocess.run([sys.executable, "-I", "-c", child, str(SCRIPT_DIR), str(current)],
                                 capture_output=True, timeout=10)
            self.assertEqual(run.returncode, 73)
            self.assertEqual(current.read_bytes(), original)
            self.assertFalse(destination.exists(), "A partial archive must never own the final content hash")
            # Retrying uses a new temporary path and preserves the complete original.
            self.assertEqual(snapshot_current(current), destination)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(destination.stat().st_nlink, 1)

    def test_directory_sync_failure_blocks_replacement_and_retry_verifies_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "05_risk_and_positions/current_positions.local.csv"
            current.parent.mkdir()
            current.write_bytes(b"old")
            real_sync = os.fsync
            seen = []
            def fail_directory_sync(descriptor):
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    seen.append("directory")
                    raise OSError("simulated directory sync failure")
                return real_sync(descriptor)
            with patch.object(portfolio_archive.os, "fsync", side_effect=fail_directory_sync):
                with self.assertRaisesRegex(OSError, "directory sync failure"):
                    atomic_write_text(current, "new")
            self.assertTrue(seen)
            self.assertEqual(current.read_bytes(), b"old")
            # A complete already-published archive is reverified and synced before replacement.
            atomic_write_text(current, "new")
            self.assertEqual(current.read_bytes(), b"new")
            destination = (root / "11_archive/portfolio_versions.local/current_positions.local.csv"
                           / hashlib.sha256(b"old").hexdigest())
            self.assertEqual(destination.read_bytes(), b"old")

    def test_process_exit_after_publication_recovers_only_owned_temporary_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "05_risk_and_positions/current_positions.local.csv"
            current.parent.mkdir()
            original = b"ticker,shares\nTEST,1\n"
            current.write_bytes(original)
            destination = (root / "11_archive/portfolio_versions.local/current_positions.local.csv"
                           / hashlib.sha256(original).hexdigest())
            child = r"""
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import portfolio_archive
original_link = os.link
def linked_then_exit(*args, **kwargs):
    original_link(*args, **kwargs)
    os._exit(74)
portfolio_archive.os.link = linked_then_exit
portfolio_archive.snapshot_current(Path(sys.argv[2]))
"""
            run = subprocess.run([sys.executable, "-I", "-c", child, str(SCRIPT_DIR), str(current)],
                                 capture_output=True, timeout=10)
            self.assertEqual(run.returncode, 74)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(destination.stat().st_nlink, 2)
            unrelated = destination.parent / "unrelated.tmp"
            unrelated.write_bytes(b"leave untouched")
            self.assertEqual(snapshot_current(current), destination)
            self.assertEqual(destination.stat().st_nlink, 1)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(current.read_bytes(), original)
            self.assertEqual(unrelated.read_bytes(), b"leave untouched")

    def test_unrecognized_archive_hard_link_is_not_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "05_risk_and_positions/current_positions.local.csv"
            current.parent.mkdir()
            current.write_bytes(b"original")
            destination = snapshot_current(current)
            unrelated = root / "unrecognized-link"
            os.link(destination, unrelated)
            with self.assertRaisesRegex(ValueError, "private regular file"):
                snapshot_current(current)
            self.assertEqual(unrelated.read_bytes(), b"original")
            self.assertEqual(destination.read_bytes(), b"original")
            self.assertEqual(current.read_bytes(), b"original")
