from __future__ import annotations

from contextlib import ExitStack
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import run_full_universe_market_data as b2
import tactical_review
import test_market_refresh_failure_commit as fixtures


class MarketCoverageRecompositionTests(unittest.TestCase):
    def _fixture(self, directory: str):
        helper = fixtures.B2MarketRefreshFailureCommitTests()
        paths = helper._paths(Path(directory))
        helper._write_prior_outputs(paths)
        b2.write_csv(paths["positions"], [{"ticker": "RBRK"}, {"ticker": "SPY"}], ["ticker"])
        return helper, paths

    def _run(self, helper, paths, mode="--recompose-current-coverage"):
        with ExitStack() as stack:
            helper._patch_paths(stack, paths)
            stack.enter_context(patch.object(b2, "now_et", return_value=fixtures.POST_CLOSE))
            client = stack.enter_context(patch.object(b2.MassiveBasicEODClient, "from_environment"))
            result = b2.main([mode])
            client.assert_not_called()
            return result

    def _receipts(self, paths):
        return list(paths["data"].glob("market_coverage_recompositions.local/*/receipt.json"))

    def test_projection_archives_originals_and_preserves_every_retained_value(self):
        with tempfile.TemporaryDirectory() as directory:
            helper, paths = self._fixture(directory)
            before = helper._trio_bytes(paths)
            rows_before = b2.read_csv(paths["snapshot"])
            self.assertEqual(self._run(helper, paths, "--reuse-validated-snapshot"), 1)
            self.assertEqual(helper._trio_bytes(paths), before)
            self.assertEqual(self._receipts(paths), [])
            self.assertEqual(self._run(helper, paths), 0)
            self.assertEqual(b2.read_csv(paths["snapshot"]), [r for r in rows_before if r["ticker"] != "IOT"])
            self.assertEqual(paths["candidates"].read_bytes(), before["candidates"])
            self.assertEqual({r["ticker"] for r in b2.read_csv(paths["quality"])}, {*fixtures.UNIVERSE_TICKERS, "RBRK"})
            receipts = self._receipts(paths)
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_text())
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["removed_held_only_tickers"], ["IOT"])
            self.assertEqual(receipt["market_session"], "2026-08-05")
            for name, data in before.items():
                self.assertEqual((receipts[0].parent / paths[name].name).read_bytes(), data)
                self.assertEqual(receipt["after_sha256"][paths[name].name], b2.sha256_file(paths[name]))
            # A second invocation is validation-only, without another archive.
            after = helper._trio_bytes(paths)
            self.assertEqual(self._run(helper, paths), 0)
            self.assertEqual(helper._trio_bytes(paths), after)
            self.assertEqual(self._receipts(paths), receipts)

    def test_rejects_missing_stale_duplicate_and_inconsistent_data_without_writes(self):
        for defect in ("new_holding_missing", "stale_close", "duplicate", "removed_quality_inconsistent", "retained_price_inconsistent"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                helper, paths = self._fixture(directory)
                if defect == "new_holding_missing":
                    b2.write_csv(paths["positions"], [{"ticker": "RBRK"}, {"ticker": "SMTC"}], ["ticker"])
                elif defect == "removed_quality_inconsistent":
                    rows = b2.read_csv(paths["quality"])
                    next(r for r in rows if r["ticker"] == "IOT")["data_source"] = "invented"
                    b2.write_csv(paths["quality"], rows, b2.QUALITY_FIELDS)
                else:
                    rows = b2.read_csv(paths["snapshot"])
                    if defect == "stale_close":
                        next(r for r in rows if r["ticker"] == "IOT")["market_session_date"] = "2026-08-04"
                    elif defect == "duplicate":
                        rows.append(dict(rows[-1]))
                    else:
                        next(r for r in rows if r["ticker"] == "SPY")["last_price"] = "900.0000"
                    b2.write_csv(paths["snapshot"], rows, b2.MARKET_FIELDS)
                before = helper._trio_bytes(paths)
                self.assertEqual(self._run(helper, paths), 1)
                self.assertEqual(helper._trio_bytes(paths), before)
                self.assertEqual(self._receipts(paths), [])

    def test_recomposition_cannot_admit_changed_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            helper, paths = self._fixture(directory)
            universe_path = paths["data"] / "universe_seed.csv"
            seeds = b2.read_csv(universe_path)
            seeds[-1]["ticker"] = "IOT"
            b2.write_csv(universe_path, seeds, list(seeds[0]))
            before = helper._trio_bytes(paths)
            with self.assertRaisesRegex(RuntimeError, "exact approved 31"):
                self._run(helper, paths)
            self.assertEqual(helper._trio_bytes(paths), before)

    def test_only_valid_previously_bound_history_is_projected_and_rebound(self):
        for valid_history in (True, False):
            with self.subTest(valid_history=valid_history), tempfile.TemporaryDirectory() as directory:
                helper, paths = self._fixture(directory)
                history_path = paths["data"] / "tactical_price_history.local.json"
                series = {}
                for row in b2.read_csv(paths["snapshot"]):
                    close = float(row["last_price"])
                    series[row["ticker"]] = {
                        "source_url": "https://api.massive.com/reference",
                        "bars": [{"session_date": day, "open": close, "high": close + 1,
                                  "low": close - 1, "close": close, "volume": 1000}
                                 for day in tactical_review._last_sessions(date(2026, 8, 5), 20)],
                    }
                history = {"schema_version": "phase5r_tactical_price_history_v1", "validated": True,
                           "data_source": b2.MASSIVE_DATA_SOURCE, "generated_at": "2026-08-06T11:15:00-04:00",
                           "market_session": "2026-08-05", "snapshot_sha256": b2.sha256_file(paths["snapshot"]),
                           "tickers": series}
                if not valid_history:
                    history["tickers"]["SPY"]["bars"][-1]["close"] = 1
                b2.atomic_write_json(history_path, history)
                original = history_path.read_bytes()
                self.assertEqual(self._run(helper, paths), 0)
                projected = json.loads(history_path.read_text())
                if valid_history:
                    self.assertEqual(projected["snapshot_sha256"], b2.sha256_file(paths["snapshot"]))
                    self.assertNotIn("IOT", projected["tickers"])
                    self.assertEqual(projected["generated_at"], history["generated_at"])
                    for ticker, value in projected["tickers"].items():
                        self.assertEqual(value, history["tickers"][ticker])
                else:
                    self.assertEqual(history_path.read_bytes(), original)
                    self.assertNotEqual(projected["snapshot_sha256"], b2.sha256_file(paths["snapshot"]))
                self.assertEqual((self._receipts(paths)[0].parent / history_path.name).read_bytes(), original)

    def test_write_failure_restores_originals_and_retains_rollback_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            helper, paths = self._fixture(directory)
            before = helper._trio_bytes(paths)
            write = b2.atomic_write_text
            attempted = False

            def fail_once(path, content):
                nonlocal attempted
                if path == paths["quality"] and not attempted:
                    attempted = True
                    raise OSError("fixture interrupted write")
                return write(path, content)

            with patch.object(b2, "atomic_write_text", side_effect=fail_once):
                with self.assertRaisesRegex(OSError, "fixture interrupted write"):
                    self._run(helper, paths)
            self.assertEqual(helper._trio_bytes(paths), before)
            self.assertEqual(json.loads(self._receipts(paths)[0].read_text())["status"], "rolled_back")

    def test_position_change_during_staging_aborts_before_market_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            helper, paths = self._fixture(directory)
            before = helper._trio_bytes(paths)
            validate = b2.validated_snapshot_reuse

            def change_positions_after_staging(**kwargs):
                result = validate(**kwargs)
                if kwargs.get("output_paths"):
                    b2.write_csv(paths["positions"], [{"ticker": "RBRK"}, {"ticker": "SMTC"}], ["ticker"])
                return result

            with patch.object(b2, "validated_snapshot_reuse", side_effect=change_positions_after_staging):
                self.assertEqual(self._run(helper, paths), 1)
            self.assertEqual(helper._trio_bytes(paths), before)
            self.assertEqual(self._receipts(paths), [])


if __name__ == "__main__":
    unittest.main()
