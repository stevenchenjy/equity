"""Outside-universe fund identity does not confer stock or core authority."""
import csv
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import build_current_research_baseline as baseline
import instrument_metadata as metadata
import intraday_assessment
from account_common import is_core_allocation_ticker


class InstrumentMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.universe = [{"ticker": "SPY", "sector": "ETF", "is_benchmark": "yes"}]
        self.write_metadata()

    def write_metadata(self, rows=None):
        rows = rows if rows is not None else [("AAA", "stocks"), ("FND", "etf")]
        path = self.root / metadata.RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": "equity_supplemental_instrument_metadata_v1",
            "instruments": [dict(ticker=ticker, asset_class=kind, name="Synthetic instrument",
                source_url="https://example.test/instrument", reviewed_on="2026-09-22")
                for ticker, kind in rows]}))

    def csv(self, relative, rows):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_explicit_identity_does_not_expand_candidates_or_core_membership(self):
        before = list(self.universe)
        self.assertEqual(metadata.asset_class("FND", root=self.root, universe=self.universe), "etf")
        self.assertEqual(metadata.asset_class("AAA", root=self.root, universe=self.universe), "stocks")
        self.assertIsNone(metadata.asset_class("UNKNOWN", root=self.root, universe=self.universe))
        self.assertEqual(self.universe, before)
        self.assertFalse(is_core_allocation_ticker("VGT"))

    def test_conflicts_duplicates_and_changed_classification_fail(self):
        self.write_metadata([("SPY", "stocks")])
        with self.assertRaisesRegex(ValueError, "classification_conflict"):
            metadata.asset_class("SPY", root=self.root, universe=self.universe)
        self.write_metadata([("FND", "etf"), ("FND", "stocks")])
        with self.assertRaisesRegex(ValueError, "metadata_invalid"):
            metadata.asset_class("FND", root=self.root, universe=[])
        self.write_metadata([("FND", "options")])
        with self.assertRaisesRegex(ValueError, "metadata_invalid"):
            metadata.asset_class("FND", root=self.root, universe=[])

    def test_symlink_metadata_is_not_admitted(self):
        path = self.root / metadata.RELATIVE
        retained = path.with_name("retained.json")
        path.rename(retained)
        path.symlink_to(retained)
        with self.assertRaisesRegex(ValueError, "metadata_invalid"):
            metadata.asset_class("FND", root=self.root, universe=[])

    def test_all_current_instruments_route_without_candidate_universe_growth(self):
        self.csv(metadata.UNIVERSE, self.universe)
        self.csv("05_risk_and_positions/current_positions.local.csv", [
            {"ticker": "SPY", "shares_optional": "3"},
            {"ticker": "AAA", "shares_optional": "8"},
            {"ticker": "FND", "shares_optional": "11"}])
        self.assertEqual(intraday_assessment.held_symbols(self.root),
                         {"AAA": "stocks", "FND": "etf", "SPY": "etf"})

    def test_held_fund_requires_prices_but_not_operating_company_fundamentals(self):
        def rows(path):
            if path == baseline.MARKET_SNAPSHOT_PATH:
                return [dict(ticker=t, market_session_date="2026-09-22", last_price="100",
                             data_quality_label="ok", data_source="synthetic") for t in ("SPY", "FND")]
            if path == baseline.UNIVERSE_PATH:
                return self.universe
            return []
        with (patch.object(baseline, "ROOT", self.root),
              patch.object(baseline, "read_csv", side_effect=rows),
              patch.object(baseline, "selected_tickers", return_value=(["SPY", "FND"], {"FND"})),
              patch.object(baseline, "is_core_allocation_ticker", side_effect=lambda t: t == "SPY"),
              patch.object(baseline, "latest_published_market_session", return_value=date(2026, 9, 22)),
              patch.object(baseline, "atomic_write_csv") as output):
            self.assertEqual(baseline.main(), 0)
        by = {row["ticker"]: row for row in output.call_args.args[2]}
        self.assertEqual(by["FND"]["research_role"], "etf_research_candidate")
        self.assertIn("not_applicable", by["FND"]["valuation_check"])
        self.assertEqual(by["FND"]["human_action_required"], "no")


if __name__ == "__main__":
    unittest.main()
