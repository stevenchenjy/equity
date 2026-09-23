from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR  # noqa: F401
from sec_supplemental_facts import (
    NVDA_PRINCIPAL_TAG, SupplementalFactError, parse_principal_facts, supplement_companyfacts,
    project_relative_locator,
)
import refresh_daily_evidence as evidence
from test_financial_period_integrity import fixture, facts, duration
from test_valuation_input_bundle import _bundle
from valuation_input_bundle import (
    ValuationInputBundleError, seal_bundle, validate_and_materialize_bundle,
)


FILING = {"form": "10-Q", "filing_date": "2026-08-26", "accepted_at": "2026-08-26T20:36:00Z",
          "accession_number": "0001045810-26-000075", "primary_document": "nvda-20260726.htm"}
URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"


def raw_fact(*, cik="0001045810", unit="iso4217:USD", text="92", scale="6", dimensions="", start="2026-01-26", end="2026-07-26", format=""):
    return f'''<html><xbrli:context id="c-1"><xbrli:entity><xbrli:identifier>{cik}</xbrli:identifier>{dimensions}</xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context><xbrli:unit id="usd"><xbrli:measure>{unit}</xbrli:measure></xbrli:unit><ix:nonFraction name="nvda:{NVDA_PRINCIPAL_TAG}" contextRef="c-1" unitRef="usd" scale="{scale}" id="f-354" format="{format}">{text}</ix:nonFraction></html>'''.encode()


class SupplementalFactsTests(unittest.TestCase):
    def parse(self, raw):
        return parse_principal_facts(raw, filing=FILING, cik=1045810, source_url=URL, raw_path="test.raw")

    def test_real_reported_scale_duration_and_source_identity_preserved(self):
        value = self.parse(raw_fact())[0]
        self.assertEqual(value["val"], 92_000_000)
        self.assertEqual((value["start"], value["end"]), ("2026-01-26", "2026-07-26"))
        self.assertEqual(value["accn"], FILING["accession_number"])
        self.assertEqual(value["_source_url"], URL)
        self.assertEqual(value["_context_id"], "c-1")
        self.assertEqual(len(value["_raw_sha256"]), 64)

    def test_macos_runtime_locator_is_relative_and_external_cache_is_omitted(self):
        root = Path("/Users/private-owner/LocalRuntime/equity")
        relative = "02_filings/issuer_filings/financial_supplements.local/NVDA/0001045810-26-000075/primary_document.raw"
        self.assertEqual(project_relative_locator(root / relative, project_root=root), relative)
        value = parse_principal_facts(raw_fact(), filing=FILING, cik=1045810,
            source_url=URL, raw_path=str(root / relative), project_root=root)[0]
        self.assertEqual(value["_raw_path"], relative)
        self.assertNotIn("/Users/", json.dumps(value))
        for external in ["/Users/private-owner/Downloads/primary_document.raw",
                         "/tmp/validation/primary_document.raw", r"C:\Users\private-owner\cache\primary_document.raw"]:
            with self.subTest(external=external):
                value = parse_principal_facts(raw_fact(), filing=FILING, cik=1045810,
                    source_url=URL, raw_path=external, project_root=root)[0]
                self.assertNotIn("_raw_path", value)
                self.assertEqual(value["_source_url"], URL)
                self.assertEqual(len(value["_raw_sha256"]), 64)

    def test_supplemental_provenance_passes_bundle_privacy_without_weakening_guard(self):
        runtime_root = Path("/Users/private-owner/LocalRuntime/equity")
        raw = parse_principal_facts(raw_fact(), filing=FILING, cik=1045810,
            source_url=URL, raw_path=str(runtime_root / "02_filings/issuer_filings/NVDA/primary_document.raw"),
            project_root=runtime_root)[0]
        payload = {"facts": {"nvda": {NVDA_PRINCIPAL_TAG: facts([raw])}}}
        selected = evidence.fact_units(payload, (NVDA_PRINCIPAL_TAG,),
            as_of=datetime(2026,9,20,tzinfo=timezone.utc),
            acceptance_by_accession={FILING["accession_number"]: FILING["accepted_at"]})[0]
        provenance = evidence.fact_provenance(selected)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = _bundle(root, "NVDA")
            source = next(s for s in bundle["records"][0]["sources"] if s["source_type"] == "sec_valuation_fact")
            text_path = root / source["relative_path"]
            def materialize(prov):
                # Production embeds the entire fundamentals CSV row, including
                # nested custom-fact provenance, as the verified SEC excerpt.
                text = 'ticker,field_provenance_json\nNVDA,' + json.dumps({"ttm_capex": {"components": [prov]}})
                text_path.write_text(text)
                source["char_end"] = len(text)
                source["content_sha256"] = hashlib.sha256(text.encode()).hexdigest()
                return validate_and_materialize_bundle(seal_bundle(bundle),
                    packet_as_of="2026-09-20T20:00:00Z", active_tickers={"NVDA"}, project_root=root)
            receipts, sources = materialize(provenance)
            self.assertEqual(receipts[0]["ticker"], "NVDA")
            self.assertNotIn("/Users/", json.dumps(sources))
            poisoned = {**provenance, "raw_path": str(runtime_root / "primary_document.raw")}
            with self.assertRaisesRegex(ValuationInputBundleError, "sensitive or local-identity"):
                materialize(poisoned)

    def test_dimensions_cik_unit_invalid_numbers_and_missing_are_rejected(self):
        for raw in [raw_fact(cik="999"), raw_fact(unit="iso4217:EUR"), raw_fact(text="NaN"),
                    raw_fact(text="(92)"), raw_fact(scale="999"), raw_fact(end="2026-09-30"),
                    raw_fact(dimensions='<xbrli:segment><xbrldi:explicitMember>Segment</xbrldi:explicitMember></xbrli:segment>'),
                    b'<html>no principal disclosure</html>']:
            with self.subTest(raw=raw[:80]), self.assertRaises(SupplementalFactError):
                self.parse(raw)

    def test_reported_zero_only_with_supported_inline_format(self):
        self.assertEqual(self.parse(raw_fact(text="—", format="ixt:fixed-zero"))[0]["val"], 0)
        with self.assertRaises(SupplementalFactError):
            self.parse(raw_fact(text="—"))

    def test_verified_cache_avoids_network_and_corruption_refetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetch = Mock(return_value=SimpleNamespace(raw_bytes=raw_fact()))
            kwargs = {"as_of": datetime(2026, 9, 20, tzinfo=timezone.utc), "cache_root": Path(tmp), "fetcher": fetch}
            first = supplement_companyfacts("NVDA",1045810, {"facts": {}}, [FILING], "test", **kwargs)
            self.assertEqual(first["facts"]["nvda"][NVDA_PRINCIPAL_TAG]["units"]["USD"][0]["val"], 92_000_000)
            supplement_companyfacts("NVDA",1045810, {"facts": {}}, [FILING], "test", **kwargs)
            self.assertEqual(fetch.call_count, 1)
            (Path(tmp)/"NVDA"/FILING["accession_number"]/"primary_document.raw").write_bytes(b'corrupt')
            supplement_companyfacts("NVDA",1045810, {"facts": {}}, [FILING], "test", **kwargs)
            self.assertEqual(fetch.call_count, 2)

    def test_future_filing_never_fetches_or_adds_principal(self):
        fetch = Mock()
        result = supplement_companyfacts("NVDA",1045810, {"facts": {}}, [FILING], "test",
            as_of=datetime(2026, 8, 25, tzinfo=timezone.utc), fetcher=fetch)
        fetch.assert_not_called()
        self.assertEqual(result["facts"]["nvda"][NVDA_PRINCIPAL_TAG]["units"]["USD"], [])

    def test_fcf_requires_annual_and_matching_ytd_principal_not_a_zero_default(self):
        payload = fixture()
        gaap = payload["facts"]["us-gaap"]
        gaap["PaymentsToAcquireProductiveAssets"] = gaap.pop("PaymentsToAcquirePropertyPlantAndEquipment")
        args = ("NVDA", 1, payload, "2026-09-04T16:00:00Z")
        missing = evidence.fundamental_row(*args)
        self.assertEqual(missing["ttm_free_cash_flow"], "")
        self.assertEqual(missing["valuation_input_quality"], "insufficient")
        principal = copy.deepcopy(gaap["PaymentsToAcquireProductiveAssets"])
        payload["facts"]["nvda"] = {NVDA_PRINCIPAL_TAG: principal}
        complete = evidence.fundamental_row(*args)
        self.assertEqual(complete["ttm_capex"], "27.00")
        self.assertEqual(complete["ttm_free_cash_flow"], "108.00")
        self.assertEqual(complete["valuation_input_quality"], "complete")
        provenance = json.loads(complete["field_provenance_json"])["ttm_capex"]
        self.assertEqual(provenance["derivation"], "reported_productive_asset_purchases_plus_financed_asset_principal")
        self.assertEqual(provenance["components"][1]["taxonomy"], "nvda")
        payload["facts"]["nvda"][NVDA_PRINCIPAL_TAG]["units"]["USD"] = principal["units"]["USD"][-1:]
        self.assertEqual(evidence.fundamental_row(*args)["ttm_free_cash_flow"], "")

    def test_prior_quarter_growth_and_margin_are_consecutive_period_bound(self):
        payload = fixture()
        gaap = payload["facts"]["us-gaap"]
        gaap["Revenues"]["units"]["USD"].extend([
            duration("2025-01-01", "2025-03-31", 240), duration("2026-01-01", "2026-03-31", 300)])
        gaap["NetIncomeLoss"]["units"]["USD"].append(duration("2026-01-01", "2026-03-31", 30))
        result = evidence.fundamental_row("TST",1,payload,"2026-09-04T16:00:00Z")
        self.assertEqual(result["revenue_yoy_prior_quarter_pct"], "25.00")
        self.assertEqual(result["net_margin_prior_quarter_pct"], "10.00")
        self.assertEqual(result["prior_quarter_period_end"], "2026-03-31")
        self.assertEqual(json.loads(result["field_provenance_json"])["net_margin_prior_quarter_pct"]["end"], "2026-03-31")

    def test_all_active_companies_are_researched_even_without_scores(self):
        def read(path):
            if path.name == "universe_seed.csv":
                return [{"ticker":"ZZZ","is_benchmark":"no"},{"ticker":"QQQ","is_benchmark":"yes"}]
            if path == evidence.POSITIONS_PATH:
                return [{"ticker":"HELD"}]
            return []
        with patch.object(evidence, "read_csv", side_effect=read):
            held, researched = evidence.researched_tickers()
        self.assertEqual(held, ["HELD"])
        self.assertEqual(researched, ["HELD", "SPY", "ZZZ"])
        self.assertFalse(evidence.company_fundamentals_required("QQQ"))

    def test_sec_json_transient_retry_is_bounded_and_parse_errors_do_not_retry(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ok": true}'
        with patch.object(evidence.urllib.request, "urlopen", side_effect=[urllib.error.URLError("offline"), response]) as fetch, patch.object(evidence.time, "sleep"):
            self.assertEqual(evidence.request_json("https://data.sec.gov/test", "test"), {"ok": True})
            self.assertEqual(fetch.call_count, 2)
        response.read.return_value = b'<html>not JSON</html>'
        with patch.object(evidence.urllib.request, "urlopen", return_value=response) as fetch, self.assertRaises(ValueError):
            evidence.request_json("https://data.sec.gov/test", "test")
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
