from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import SCRIPT_DIR  # noqa: F401

import refresh_phase5r_daily_evidence as evidence
import refresh_phase5r_valuation_scenarios as valuation
from refresh_phase5r_valuation_scenarios import number, valuation_input_issues


def duration(start, end, val, filed="2026-08-01", *, form="10-Q", frame=None, accn="0000000001-26-000001"):
    return {"start": start, "end": end, "val": val, "filed": filed,
            "form": form, "frame": frame, "accn": accn}


def instant(end, val, filed="2026-08-01"):
    return {"end": end, "val": val, "filed": filed, "form": "10-Q", "accn": "0000000001-26-000001"}


def facts(values, unit="USD"):
    return {"units": {unit: values}}


def fixture():
    revenues = [
        duration("2024-01-01", "2024-12-31", 1000, "2025-02-01", form="10-K"),
        duration("2025-01-01", "2025-12-31", 1200, "2026-02-01", form="10-K"),
        duration("2024-01-01", "2024-06-30", 420, "2025-08-01"),
        duration("2025-01-01", "2025-06-30", 510),
        duration("2026-01-01", "2026-06-30", 660),
        duration("2025-04-01", "2025-06-30", 270),
        duration("2026-04-01", "2026-06-30", 360),
    ]
    cash_flow = [duration(item["start"], item["end"], item["val"] / 10,
                          item["filed"], form=item["form"]) for item in revenues]
    capex = [duration(item["start"], item["end"], item["val"] / 100,
                     item["filed"], form=item["form"]) for item in revenues]
    return {"cik": 1, "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": facts([
            duration("2019-10-01", "2019-12-31", 3, "2020-02-01", frame="CY2019Q4")]),
        "Revenues": facts(revenues),
        "NetIncomeLoss": facts([duration("2026-04-01", "2026-06-30", -36)]),
        "CashAndCashEquivalentsAtCarryingValue": facts([instant("2026-06-30", 200)]),
        "Assets": facts([instant("2026-06-30", 500)]),
        "Liabilities": facts([instant("2026-06-30", 100)]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": facts([
            duration("2025-04-01", "2025-06-30", 100),
            duration("2026-04-01", "2026-06-30", 104)], "shares"),
        "NetCashProvidedByUsedInOperatingActivities": facts(cash_flow),
        "PaymentsToAcquirePropertyPlantAndEquipment": facts(capex),
        "DebtAndCapitalLeaseObligations": facts([instant("2026-06-30", 50)]),
    }}}


def row(payload=None, at="2026-09-04T16:00:00+00:00", **kwargs):
    return evidence.fundamental_row("TST", 1, payload or fixture(), at, **kwargs)


class FinancialPeriodIntegrityTests(unittest.TestCase):
    def test_successor_tag_unframed_quarter_and_ttm_are_current(self):
        result = row()
        self.assertEqual(result["latest_period_end"], "2026-06-30")
        self.assertEqual(result["revenue_latest"], "360.00")
        self.assertEqual(result["revenue_prior_year"], "270.00")
        self.assertEqual(result["ttm_revenue"], "1350.00")
        self.assertEqual(result["ttm_revenue_prior_year"], "1090.00")
        self.assertEqual(result["net_margin_pct"], "-10.00")
        self.assertEqual(result["data_quality"], "ok")
        self.assertEqual(result["valuation_input_quality"], "complete")
        provenance = json.loads(result["field_provenance_json"])
        self.assertEqual(provenance["revenue_latest"]["tag"], "Revenues")
        self.assertEqual(provenance["revenue_latest"]["unit"], "USD")
        self.assertEqual(provenance["revenue_latest"]["accn"], "0000000001-26-000001")
        self.assertEqual(len(provenance["ttm_revenue"]["components"]), 3)
        self.assertEqual(valuation_input_issues(result, {"last_price": 10}, "2026-09-04T17:00:00Z"), [])

    def test_future_amendment_cannot_change_historical_point_in_time(self):
        payload = fixture()
        payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
            duration("2026-04-01", "2026-06-30", 999, "2026-10-01", form="10-Q/A"))
        self.assertEqual(row(payload)["revenue_latest"], "360.00")

    def test_same_day_requires_exact_available_acceptance(self):
        payload = fixture()
        timestamp = "2026-08-01T16:00:00+00:00"
        no_timestamp = row(payload, at=timestamp)
        self.assertNotEqual(no_timestamp["latest_period_end"], "2026-06-30")
        accepted = row(payload, at=timestamp, acceptance_by_accession={
            "0000000001-26-000001": "2026-08-01T15:00:00Z"})
        self.assertEqual(accepted["latest_period_end"], "2026-06-30")
        provenance = json.loads(accepted["field_provenance_json"])
        self.assertEqual(provenance["revenue_latest"]["availability_basis"], "official_acceptance_timestamp")
        future = row(payload, at=timestamp, acceptance_by_accession={
            "0000000001-26-000001": "2026-08-01T17:00:00Z"})
        self.assertNotEqual(future["latest_period_end"], "2026-06-30")

    def test_date_only_availability_is_not_fetch_time(self):
        provenance = json.loads(row()["field_provenance_json"])
        self.assertEqual(provenance["revenue_latest"]["available_at_utc"], "2026-08-02T04:00:00+00:00")

    def test_annual_less_nine_months_derives_actual_q4_but_not_shares(self):
        payload = {"facts": {"us-gaap": {
            "Revenues": facts([
                duration("2025-02-01", "2026-01-31", 1200, "2026-03-01", form="10-K"),
                duration("2025-02-01", "2025-10-31", 900, "2025-12-01")]),
            "WeightedAverageNumberOfDilutedSharesOutstanding": facts([
                duration("2025-02-01", "2026-01-31", 100, "2026-03-01", form="10-K"),
                duration("2025-02-01", "2025-10-31", 90, "2025-12-01")], "shares"),
        }}}
        quarter = evidence.quarterly_values(payload, evidence.REVENUE_TAGS)[-1]
        self.assertEqual((quarter["start"], quarter["end"], quarter["val"]), ("2025-11-01", "2026-01-31", 300))
        self.assertEqual(evidence.quarterly_values(payload, evidence.DILUTED_SHARES_TAGS, "shares"), [])

    def test_annual_only_does_not_retain_old_quarter_or_multiply_annual_by_four(self):
        payload = {"facts": {"us-gaap": {"Revenues": facts([
            duration("2024-04-01", "2024-06-30", 100, "2024-08-01"),
            duration("2025-01-01", "2025-12-31", 1500, "2026-02-01", form="10-K")])}}}
        result = row(payload)
        self.assertEqual(result["latest_period_end"], "2025-12-31")
        self.assertEqual(result["financial_period_type"], "annual")
        self.assertEqual(result["revenue_latest"], "1500.00")
        self.assertEqual(result["ttm_revenue"], "1500.00")

    def test_cash_flow_and_shares_do_not_drift_to_other_periods(self):
        payload = fixture()
        payload["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"] = facts([instant("2026-03-31", 200)])
        payload["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"] = facts([
            duration("2025-01-01", "2025-12-31", 100, "2026-02-01", form="10-K")])
        payload["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = facts([
            duration("2026-01-01", "2026-03-31", 100, frame="CY2026Q2")], "shares")
        result = row(payload)
        self.assertEqual(result["cash_latest"], "")
        self.assertEqual(result["ttm_free_cash_flow"], "")
        self.assertEqual(result["diluted_shares_latest"], "")
        self.assertNotEqual(result["data_quality"], "ok")

    def test_stale_revenue_and_newer_statement_cannot_be_quality_ok(self):
        payload = fixture()
        del payload["facts"]["us-gaap"]["Revenues"]
        result = row(payload)
        self.assertNotEqual(result["data_quality"], "ok")
        self.assertIn("selected_revenue_period_stale", result["data_quality_reasons"])
        self.assertIn("newer_financial_period_without_comparable_revenue", result["data_quality_reasons"])

    def test_missing_debt_components_never_sum_as_known_total(self):
        payload = fixture()
        del payload["facts"]["us-gaap"]["DebtAndCapitalLeaseObligations"]
        payload["facts"]["us-gaap"]["LongTermDebtNoncurrent"] = facts([instant("2026-06-30", 50)])
        result = row(payload)
        self.assertEqual(result["debt_latest"], "")
        self.assertEqual(result["valuation_input_quality"], "insufficient")
        self.assertIn("missing_total_debt", valuation_input_issues(result, {"last_price": 10}, "2026-09-04T17:00:00Z"))
        payload["facts"]["us-gaap"]["LongTermDebtCurrent"] = facts([instant("2026-06-30", 0)])
        self.assertEqual(row(payload)["debt_latest"], "")
        payload["facts"]["us-gaap"]["ShortTermBorrowings"] = facts([instant("2026-06-30", 0)])
        self.assertEqual(row(payload)["debt_latest"], "50.00")

    def test_explicit_zero_total_debt_is_preserved_and_allowed(self):
        payload = fixture()
        payload["facts"]["us-gaap"]["DebtAndCapitalLeaseObligations"] = facts([instant("2026-06-30", 0)])
        result = row(payload)
        self.assertEqual(result["debt_latest"], "0.00")
        self.assertNotIn("missing_total_debt", valuation_input_issues(result, {"last_price": 10}, "2026-09-04T17:00:00Z"))

    def test_wrong_unit_nonfinite_and_duration_as_instant_are_rejected(self):
        payload = {"facts": {"us-gaap": {
            "Revenues": facts([duration("2026-04-01", "2026-06-30", 999)], "EUR"),
            "CashAndCashEquivalentsAtCarryingValue": facts([
                duration("2026-04-01", "2026-06-30", 100), instant("2026-06-30", float("nan"))]),
        }}}
        self.assertEqual(evidence.fact_units(payload, evidence.REVENUE_TAGS), [])
        self.assertIsNone(evidence.latest_instant(payload, evidence.CASH_TAGS))
        self.assertIsNone(number(float("inf")))

    def test_gapped_ttm_never_annualizes_a_quarter(self):
        payload = fixture()
        values = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        next(item for item in values if item["end"] == "2025-12-31")["end"] = "2025-12-30"
        self.assertIsNone(evidence.trailing_twelve_values(payload, evidence.REVENUE_TAGS)[0])
        result = row(payload)
        self.assertEqual(result["ttm_revenue"], "")
        self.assertIn("missing_ttm_revenue", valuation_input_issues(result, {"last_price": 10}, "2026-09-04T17:00:00Z"))

    def test_cross_tag_comparison_and_mismatched_issuer_do_not_invent_continuity(self):
        payload = fixture()
        values = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        prior = [item for item in values if item["end"] == "2025-06-30"]
        payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [item for item in values if item not in prior]
        payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerIncludingAssessedTax"] = facts(prior)
        self.assertEqual(row(payload)["revenue_prior_year"], "")
        payload["cik"] = 2
        with self.assertRaisesRegex(ValueError, "CIK identity"):
            row(payload)

    def test_provenance_tamper_or_legacy_row_cannot_generate_complete_range(self):
        result = row()
        result["debt_latest"] = "0.00"
        self.assertIn("provenance_value_mismatch_debt_latest", valuation_input_issues(result, {"last_price": 10}, "2026-09-04T17:00:00Z"))
        del result["selection_version"]
        self.assertIn("period_bound_financial_selection_required", valuation_input_issues(result, {"last_price": 10}, "2026-09-04T17:00:00Z"))

    def test_selection_does_not_mutate_original_companyfacts(self):
        payload = fixture()
        original = copy.deepcopy(payload)
        row(payload)
        self.assertEqual(payload, original)

    def test_valuation_main_missing_debt_emits_no_prices_or_bound_record(self):
        result = row()
        result["debt_latest"] = ""
        scenarios, bundle = self.run_valuation_main(result)
        self.assertEqual(scenarios[0]["status"], "insufficient")
        self.assertIn("total_debt", scenarios[0]["missing_inputs"])
        self.assertNotIn("scenario_prices", scenarios[0])
        self.assertEqual(bundle["records"], [])

    def test_valuation_main_complete_has_provenance_and_true_net_cash_adjustment(self):
        payload = fixture()
        payload["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"] = facts([instant("2026-06-30", 300)])
        payload["facts"]["us-gaap"]["DebtAndCapitalLeaseObligations"] = facts([instant("2026-06-30", 100)])
        scenarios, bundle = self.run_valuation_main(row(payload))
        self.assertEqual(scenarios[0]["status"], "complete")
        self.assertNotIn("net_cash_to_revenue", scenarios[0]["adjustments_applied"])
        self.assertEqual(scenarios[0]["base_scenario_gap_pct"], scenarios[0]["expected_upside_pct"])
        self.assertIn("not_probability_weighted", scenarios[0]["metric_interpretation"]["expected_upside_pct"])
        sec_source = next(source for source in bundle["records"][0]["sources"] if source["source_type"] == "sec_valuation_fact")
        self.assertEqual(sec_source["accepted_at_utc"], "2026-08-02T04:00:00Z")
        self.assertEqual(bundle["records"][0]["inputs"]["total_debt"]["value"], "100")

    def run_valuation_main(self, financial_row):
        policy_text = valuation.POLICY_PATH.read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / filename for name, filename in {
                "BASELINE_PATH": "baseline.csv", "FUNDAMENTALS_PATH": "fundamentals.csv",
                "MARKET_SNAPSHOT_PATH": "market.csv", "SCENARIO_PATH": "scenarios.json",
                "POLICY_PATH": "policy.json", "DEFAULT_BUNDLE_PATH": "bundle.json",
            }.items()}
            paths["POLICY_PATH"].write_text(policy_text)
            fixtures = {
                "BASELINE_PATH": {"ticker": "TST", "valuation_check": "", "valuation_reasonableness_score": ""},
                "FUNDAMENTALS_PATH": financial_row,
                "MARKET_SNAPSHOT_PATH": {"ticker": "TST", "last_price": "10", "market_session_date": "2026-09-03", "data_timestamp": "2026-09-03T21:00:00Z"},
            }
            for name, record in fixtures.items():
                with paths[name].open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(record))
                    writer.writeheader()
                    writer.writerow(record)
            with mock.patch.multiple(valuation, ROOT=root, **paths), mock.patch.object(valuation, "utc_now_text", return_value="2026-09-04T17:00:00Z"):
                self.assertEqual(valuation.main(), 0)
            return (json.loads(paths["SCENARIO_PATH"].read_text())["records"],
                    json.loads(paths["DEFAULT_BUNDLE_PATH"].read_text()))


if __name__ == "__main__":
    unittest.main()
