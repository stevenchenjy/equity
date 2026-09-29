from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
from account_common import write_csv
from daily_common import atomic_write_text
from portfolio_archive import snapshot_active_portfolio


class PortfolioArchiveTests(unittest.TestCase):
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
