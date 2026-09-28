from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from _support import PROJECT_ROOT, SCRIPT_DIR  # noqa: F401
import refresh_valuation_scenarios as valuation
import valuation_research_inputs as retained_inputs
from test_financial_period_integrity import row as financial_row
from test_valuation_input_bundle import _bundle
from valuation_input_bundle import seal_bundle, validate_and_materialize_bundle


AS_OF = "2026-09-28T21:00:00Z"


class ValuationResearchRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "04_data/equity_research"
        self.data.mkdir(parents=True)
        self.bundle_path = self.data / "valuation_inputs.local.json"
        self.manual_path = self.data / "valuation_research_inputs.local.json"
        self.status_path = self.data / "valuation_research_status.local.json"
        self.history_path = self.data / "valuation_input_history.local"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, relative in (
            ("BASELINE_PATH", "04_research/company_research/current_research_baseline.csv"),
            ("FUNDAMENTALS_PATH", "03_source_data/equity_research/daily_fundamentals.csv"),
            ("MARKET_SNAPSHOT_PATH", "03_source_data/equity_research/market_data_snapshot.csv"),
            ("SCENARIO_PATH", "04_data/equity_research/valuation_scenarios.local.json"),
            ("DEFAULT_BUNDLE_PATH", "04_data/equity_research/valuation_inputs.local.json"),
            ("POLICY_PATH", "01_policies/valuation_scenario_policy.json"),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            self.stack.enter_context(patch.object(valuation, name, path))
        self.stack.enter_context(patch.object(valuation, "ROOT", self.root))
        self.stack.enter_context(patch.object(valuation, "utc_now_text", return_value=AS_OF))
        valuation.POLICY_PATH.write_bytes((PROJECT_ROOT / "01_policies/valuation_scenario_policy.json").read_bytes())
        baseline = [{"ticker": ticker, "valuation_check": "", "valuation_reasonableness_score": ""}
                    for ticker in ("TST", "SMTC")]
        valuation.atomic_write_csv(valuation.BASELINE_PATH, list(baseline[0]), baseline)
        fact = financial_row()
        incomplete = dict(fact, ticker="SMTC", debt_latest="", valuation_input_quality="insufficient")
        self.facts = [fact, incomplete]
        self.write_facts()
        self.market = [{"ticker": ticker, "last_price": "10", "market_session_date": "2026-09-25",
                        "data_timestamp": "2026-09-25T20:00:00Z"} for ticker in ("TST", "SMTC")]
        self.write_market()
        self.manual = _bundle(self.root, "SMTC")
        record = self.manual["records"][0]
        record["inputs"] = {"total_debt": record["inputs"]["total_debt"]}
        record["sources"] = [source for source in record["sources"] if source["source_type"] == "sec_valuation_fact"]
        self.manual = seal_bundle(self.manual)

    def write_facts(self):
        valuation.atomic_write_csv(valuation.FUNDAMENTALS_PATH, list(self.facts[0]), self.facts)

    def write_market(self):
        valuation.atomic_write_csv(valuation.MARKET_SNAPSHOT_PATH, list(self.market[0]), self.market)

    def run_generator(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(valuation.main(), 0)
        result = json.loads(self.bundle_path.read_text())
        validate_and_materialize_bundle(result, packet_as_of=AS_OF,
                                        active_tickers={"TST", "SMTC"}, project_root=self.root)
        return {record["ticker"]: record for record in result["records"]}

    def write_manual(self, bundle=None):
        valuation.atomic_write_json(self.manual_path, bundle or self.manual)
        return self.manual_path.read_bytes()

    def status(self):
        return json.loads(self.status_path.read_text())

    def test_full_generator_migrates_and_preserves_admitted_legacy_record(self):
        self.run_generator()
        mixed = json.loads(self.bundle_path.read_text())
        mixed["records"] += self.manual["records"]
        valuation.atomic_write_json(self.bundle_path, seal_bundle(mixed))
        before = self.bundle_path.read_bytes()
        records = self.run_generator()
        self.assertEqual(records["SMTC"], self.manual["records"][0])
        self.assertEqual(self.manual_path.read_bytes(), before)
        self.assertIn(before, [path.read_bytes() for path in self.history_path.glob("*.json")])
        self.assertFalse(json.loads(self.bundle_path.read_text())["boundaries"]["canonical_effect"])
        scenario = json.loads(valuation.SCENARIO_PATH.read_text())
        self.assertEqual(next(item for item in scenario["records"] if item["ticker"] == "SMTC")["status"], "insufficient")

    def test_migration_and_archive_use_one_captured_original(self):
        self.run_generator()
        mixed = json.loads(self.bundle_path.read_text())
        mixed["records"] += self.manual["records"]
        valuation.atomic_write_json(self.bundle_path, seal_bundle(mixed))
        before = self.bundle_path.read_bytes()
        archive = retained_inputs._archive_snapshot
        captured = []

        def replace_derived_after_snapshot(data, history):
            if not captured:
                captured.append(data)
                self.bundle_path.write_bytes(b'{}\n')
            return archive(data, history)

        with patch.object(retained_inputs, "_archive_snapshot", side_effect=replace_derived_after_snapshot):
            records = self.run_generator()
        self.assertEqual(captured, [before])
        self.assertEqual(self.manual_path.read_bytes(), before)
        self.assertEqual(records["SMTC"], self.manual["records"][0])
        self.assertIn(before, [path.read_bytes() for path in self.history_path.glob("*.json")])

    def test_durable_manual_input_survives_changed_generated_source_and_repeat(self):
        before = self.write_manual()
        self.run_generator()
        self.market[0]["last_price"] = "12"
        self.write_market()
        records = self.run_generator()
        self.assertEqual(records["TST"]["inputs"]["share_price"]["value"], "12")
        self.assertEqual(records["SMTC"], self.manual["records"][0])
        self.assertEqual(self.manual_path.read_bytes(), before)
        archives = {path.name: path.read_bytes() for path in self.history_path.glob("*.json")}
        self.run_generator()
        self.assertTrue(all((self.history_path / name).read_bytes() == data for name, data in archives.items()))

    def test_current_generated_record_wins_same_ticker_without_deleting_manual(self):
        manual = copy.deepcopy(self.manual)
        manual["records"][0]["ticker"] = "TST"
        for source in manual["records"][0]["sources"]:
            source["ticker"] = "TST"
        before = self.write_manual(seal_bundle(manual))
        records = self.run_generator()
        self.assertEqual(records["TST"]["inputs"]["total_debt"]["value"], "50")
        self.assertEqual(self.manual_path.read_bytes(), before)
        self.assertEqual(self.status()["records"][0]["status"], "historical_generated_record_precedence")

    def test_changed_source_is_retained_historical_and_unverified(self):
        before = self.write_manual()
        self.run_generator()
        source = self.root / self.manual["records"][0]["sources"][0]["relative_path"]
        source.write_text("changed source bytes")
        self.assertNotIn("SMTC", self.run_generator())
        self.assertEqual(self.manual_path.read_bytes(), before)
        self.assertEqual(self.status()["records"][0]["status"], "unverified")
        self.assertIn(before, [path.read_bytes() for path in self.history_path.glob("*.json")])

    def test_period_advance_requires_recorded_reassessment(self):
        before = self.write_manual()
        self.facts[1]["latest_period_end"] = "2026-09-30"
        self.write_facts()
        self.assertNotIn("SMTC", self.run_generator())
        self.assertEqual(self.manual_path.read_bytes(), before)
        self.assertIn("current_financial_period_mismatch:total_debt", self.status()["records"][0]["reason"])

    def test_corrupt_manual_bundle_does_not_gain_validity_by_resealing(self):
        invalid = copy.deepcopy(self.manual)
        invalid["records"][0]["inputs"]["total_debt"]["value"] = "0"
        before = self.write_manual(invalid)
        self.assertNotIn("SMTC", self.run_generator())
        self.assertEqual(self.manual_path.read_bytes(), before)
        self.assertEqual(self.status()["status"], "unverified")
        self.assertIn("digest mismatch", self.status()["reason"])

    def test_malformed_source_type_is_local_unverified_not_pipeline_failure(self):
        invalid = copy.deepcopy(self.manual)
        record = invalid["records"][0]
        record["sources"] = [copy.deepcopy(record["sources"][0]) for _ in range(3)]
        record["sources"][0]["source_type"] = []
        before = self.write_manual(seal_bundle(invalid))
        self.assertEqual(set(self.run_generator()), {"TST"})
        self.assertEqual(self.manual_path.read_bytes(), before)
        self.assertEqual(self.status()["records"][0]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
