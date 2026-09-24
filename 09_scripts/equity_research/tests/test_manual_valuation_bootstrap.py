from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import account_common
import update_manual_account as updater


NOW = datetime(2026, 9, 24, 15, 0, tzinfo=ZoneInfo("America/New_York"))
FIELDS = ["ticker", "last_price", "valuation_basis", "data_source", "data_timestamp"]


def mark(ticker: str, price: str) -> dict[str, str]:
    return {"ticker": ticker, "last_price": price,
            "valuation_basis": "manual_ui_observation",
            "data_source": "Owner-authorized read-only UI observation; private evidence record",
            "data_timestamp": NOW.isoformat()}


class ManualValuationBootstrapTests(unittest.TestCase):
    def test_invalid_or_incomplete_marks_are_rejected(self) -> None:
        good = [mark("SPY", "100"), mark("NEW", "20")]
        bad_cases = [good[:1], good + [mark("EXTRA", "1")], good + [good[0]]]
        for field, value in (("last_price", "0"), ("last_price", "-1"),
                             ("last_price", "nan"), ("last_price", "inf"),
                             ("valuation_basis", "massive_stocks_basic_eod"),
                             ("data_source", ""), ("data_timestamp", "2026-09-24T15:00:00"),
                             ("data_timestamp", "2026-09-23T15:00:00-04:00"),
                             ("data_timestamp", "2026-09-24T16:00:00-04:00")):
            bad_cases.append([good[0], dict(good[1], **{field: value})])
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, "now_et", return_value=NOW):
            source = Path(directory) / "marks.local.csv"
            for index, rows in enumerate(bad_cases):
                with self.subTest(case=index):
                    updater.atomic_write_csv(source, FIELDS, rows)
                    with self.assertRaises(ValueError):
                        updater.read_ui_valuation(source, {"SPY", "NEW"})

    def test_symlink_and_unexpected_schema_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, "now_et", return_value=NOW):
            source = Path(directory) / "marks.local.csv"
            updater.atomic_write_csv(source, FIELDS, [mark("NEW", "20")])
            link = Path(directory) / "link.csv"
            link.symlink_to(source)
            with self.assertRaises(ValueError):
                updater.read_ui_valuation(link, {"NEW"})
            source.write_text("ticker,last_price,data_quality_label\nNEW,20,ok\n")
            with self.assertRaises(ValueError):
                updater.read_ui_valuation(source, {"NEW"})

    def test_bootstrap_is_audited_without_replacing_or_waiving_canonical_prices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account = root / "account.local.json"
            positions = root / "positions.local.csv"
            canonical = root / "market.csv"
            receipt = root / "manual_account_snapshot.local.json"
            confirmed = root / "confirmed.csv"
            source = root / "marks.local.csv"
            updater.atomic_write_json(account, {"cash_reserved": 10, "cash_available": 200,
                                                "account_total_value": 290, "last_updated": NOW.isoformat()})
            old_position = {"ticker": "SPY", "entry_date": "2026-09-01", "entry_price": "80",
                            "position_pct": "25", "shares_optional": "1", "thesis": "core",
                            "horizon_class": "core", "planned_review_date": "2026-10-01",
                            "max_loss_pct_of_account": "0.5", "invalidation_rule": "review",
                            "current_action": "hold", "notes": "prior"}
            updater.atomic_write_csv(positions, list(old_position), [old_position])
            updater.atomic_write_csv(canonical, ["ticker", "last_price", "data_quality_label", "data_source", "data_timestamp"],
                                     [{"ticker": "SPY", "last_price": "90", "data_quality_label": "ok",
                                       "data_source": "massive_stocks_basic_eod", "data_timestamp": NOW.isoformat()}])
            confirmed.write_text("execution_id\n")
            updater.atomic_write_csv(source, FIELDS, [mark("SPY", "100"), mark("NEW", "20")])
            canonical_before = canonical.read_bytes()
            positions_before = positions.read_bytes()
            account_before = account.read_bytes()
            source_before = source.read_bytes()
            with ExitStack() as stack:
                for name, path in (("ACCOUNT_STATE_PATH", account), ("POSITIONS_PATH", positions),
                                   ("MARKET_SNAPSHOT_PATH", canonical), ("MANUAL_SNAPSHOT_PATH", receipt),
                                   ("CONFIRMED_PATH", confirmed)):
                    stack.enter_context(patch.object(updater, name, path))
                stack.enter_context(patch.object(updater, "now_et", return_value=NOW))
                stack.enter_context(patch.object(updater, "iso_now", return_value=NOW.isoformat()))
                arguments = ["update_manual_account.py", "--cash", "200", "--position", "SPY=1",
                             "--position", "NEW=2@18", "--valuation-snapshot", str(source),
                             "--source-note", "Explicit authorized UI record; cash is owner assumption"]
                with patch("sys.argv", [*arguments, "--preview"]), redirect_stdout(io.StringIO()):
                    self.assertEqual(updater.main(), 0)
                self.assertFalse(receipt.exists())
                self.assertEqual(positions.read_bytes(), positions_before)
                self.assertEqual(account.read_bytes(), account_before)
                with patch("sys.argv", [*arguments, "--apply"]), redirect_stdout(io.StringIO()):
                    self.assertEqual(updater.main(), 0)
                result = json.loads(receipt.read_text())
                self.assertEqual(result["valuation_basis"], "manual_ui_observation")
                self.assertEqual(result["valuation_snapshot_sha256"], hashlib.sha256(source_before).hexdigest())
                self.assertEqual(Path(result["valuation_snapshot_archive"]).read_bytes(), source_before)
                self.assertEqual(result["positions_sha256_before"], hashlib.sha256(positions_before).hexdigest())
                self.assertEqual(result["account_sha256_before"], hashlib.sha256(account_before).hexdigest())
                self.assertEqual(result["positions_sha256_after"], updater.sha256_file(positions))
                self.assertEqual(result["account_sha256_after"], updater.sha256_file(account))
                self.assertTrue(updater.current_manual_snapshot_matches(updater.sha256_file(positions), updater.sha256_file(account)))
            self.assertEqual(json.loads(account.read_text())["account_total_value"], 340)
            self.assertEqual(canonical.read_bytes(), canonical_before)
            with patch.object(account_common, "MARKET_SNAPSHOT", canonical):
                with self.assertRaisesRegex(ValueError, "missing NEW"):
                    account_common.load_market_rows({"SPY", "NEW"})


if __name__ == "__main__":
    unittest.main()
