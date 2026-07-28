from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
from build_phase5r_decision_evidence_packet import build_packet
from phase5r_valuation_input_bundle import (
    ValuationInputBundleError,
    load_valuation_input_bundle,
    seal_bundle,
    validate_and_materialize_bundle,
)


PACKET_AS_OF = "2026-07-28T03:30:00Z"
AVAILABLE_AT = "2026-07-28T03:00:00Z"


def _write_source(root: Path, relative_path: str, text: str) -> dict[str, object]:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {
        "relative_path": relative_path,
        "char_start": 0,
        "char_end": len(text),
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _source(
    *,
    ticker: str,
    source_id: str,
    source_type: str,
    authority: str,
    source_url: str,
    file_receipt: dict[str, object],
    field: str,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "ticker": ticker,
        "source_type": source_type,
        "accepted_at_utc": AVAILABLE_AT,
        "source_url": source_url,
        **file_receipt,
        "field": field,
        "authority": authority,
    }


def _input(
    value: str,
    unit: str,
    period: str,
    source_id: str,
    *,
    kind: str = "observation",
) -> dict[str, object]:
    return {
        "value": value,
        "unit": unit,
        "period": period,
        "available_at_utc": AVAILABLE_AT,
        "source_ids": [source_id],
        "evidence_kind": kind,
    }


def _bundle(root: Path, ticker: str = "TST") -> dict[str, object]:
    market_id = f"valuation-market:{ticker}:2026-07-27"
    sec_id = f"valuation-sec:{ticker}:2026-Q2"
    scenario_id = f"valuation-scenario:{ticker}:2026-07-27"
    market_file = _write_source(
        root,
        "03_source_data/phase5r/valuation_market.local.txt",
        "share_price=10; session=2026-07-27 close",
    )
    sec_file = _write_source(
        root,
        "02_filings/phase5r_daily/valuation_sec.local.txt",
        (
            "diluted_shares=100; cash_and_equivalents=200; total_debt=100; "
            "revenue_ttm=400; free_cash_flow_ttm=40; prior_diluted_shares=80"
        ),
    )
    scenario_file = _write_source(
        root,
        "04_data/phase5r/phase5r_valuation_source_scenario.local.txt",
        "target_price_assumption=15; downside_price_assumption=8",
    )
    raw: dict[str, object] = {
        "schema_version": "phase5r_valuation_input_bundle_v1",
        "prepared_at_utc": AVAILABLE_AT,
        "records": [
            {
                "ticker": ticker,
                "inputs": {
                    "share_price": _input(
                        "10",
                        "USD_per_share",
                        "2026-07-27 close",
                        market_id,
                    ),
                    "diluted_shares": _input(
                        "100", "shares", "TTM ended 2026-06-30", sec_id
                    ),
                    "cash_and_equivalents": _input(
                        "200", "USD", "2026-06-30", sec_id
                    ),
                    "total_debt": _input(
                        "100", "USD", "2026-06-30", sec_id
                    ),
                    "revenue_ttm": _input(
                        "400", "USD", "TTM ended 2026-06-30", sec_id
                    ),
                    "free_cash_flow_ttm": _input(
                        "40", "USD", "TTM ended 2026-06-30", sec_id
                    ),
                    "prior_diluted_shares": _input(
                        "80", "shares", "TTM ended 2025-06-30", sec_id
                    ),
                    "target_price_assumption": _input(
                        "15",
                        "USD_per_share",
                        "research scenario at 2026-07-27",
                        scenario_id,
                        kind="scenario_assumption",
                    ),
                    "downside_price_assumption": _input(
                        "8",
                        "USD_per_share",
                        "research scenario at 2026-07-27",
                        scenario_id,
                        kind="scenario_assumption",
                    ),
                },
                "sources": [
                    _source(
                        ticker=ticker,
                        source_id=market_id,
                        source_type="public_market_valuation_observation",
                        authority="secondary_public_market_context",
                        source_url="https://query1.finance.yahoo.com/",
                        file_receipt=market_file,
                        field="share_price",
                    ),
                    _source(
                        ticker=ticker,
                        source_id=sec_id,
                        source_type="sec_valuation_fact",
                        authority="primary_official",
                        source_url=(
                            "https://data.sec.gov/api/xbrl/companyfacts/"
                            "CIK0000000001.json"
                        ),
                        file_receipt=sec_file,
                        field="valuation_core_inputs",
                    ),
                    _source(
                        ticker=ticker,
                        source_id=scenario_id,
                        source_type="human_valuation_scenario",
                        authority="human_research_scenario",
                        source_url="",
                        file_receipt=scenario_file,
                        field="target_and_downside_scenarios",
                    ),
                ],
            }
        ],
        "boundaries": {
            "research_only": True,
            "canonical_effect": False,
            "email_eligible": False,
            "automatic_action_allowed": False,
            "broker_connected": False,
            "broker_account_read": False,
            "order_code_created": False,
            "trade_placed": False,
            "network_used": False,
            "credentials_read": False,
            "smtp_config_read": False,
        },
        "bundle_sha256": "",
    }
    return seal_bundle(raw)


def _write_bundle(path: Path, bundle: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class ValuationInputBundleTests(unittest.TestCase):
    def test_complete_sealed_bundle_materializes_receipt_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts, sources = validate_and_materialize_bundle(
                _bundle(root),
                packet_as_of=PACKET_AS_OF,
                active_tickers={"TST"},
                project_root=root,
            )
        self.assertEqual([row["ticker"] for row in receipts], ["TST"])
        self.assertTrue(receipts[0]["sufficiency"]["decision_sufficient"])
        self.assertEqual(len(sources), 3)
        self.assertTrue(all(row["excerpt_text"] for row in sources))
        self.assertTrue(all(row["ticker"] == "TST" for row in sources))

    def test_absent_bundle_is_the_only_empty_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts, sources = load_valuation_input_bundle(
                path=root / "missing.local.json",
                packet_as_of=PACKET_AS_OF,
                active_tickers={"TST"},
                project_root=root,
            )
        self.assertEqual(receipts, [])
        self.assertEqual(sources, [])

    def test_digest_or_source_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = _bundle(root)
            digest_tampered = copy.deepcopy(bundle)
            digest_tampered["records"][0]["inputs"]["share_price"]["value"] = "11"
            with self.assertRaisesRegex(
                ValuationInputBundleError,
                "digest mismatch",
            ):
                validate_and_materialize_bundle(
                    digest_tampered,
                    packet_as_of=PACKET_AS_OF,
                    active_tickers={"TST"},
                    project_root=root,
                )

            source_path = (
                root / "03_source_data/phase5r/valuation_market.local.txt"
            )
            source_path.write_text("share_price=999", encoding="utf-8")
            with self.assertRaisesRegex(
                ValuationInputBundleError,
                "excerpt hash mismatch|invalid character range",
            ):
                validate_and_materialize_bundle(
                    bundle,
                    packet_as_of=PACKET_AS_OF,
                    active_tickers={"TST"},
                    project_root=root,
                )

    def test_unsafe_source_and_active_boundary_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsafe = _bundle(root)
            unsafe["records"][0]["sources"][0][
                "relative_path"
            ] = "11_archive/legacy.txt"
            unsafe = seal_bundle(unsafe)
            with self.assertRaisesRegex(
                ValuationInputBundleError,
                "archived evidence",
            ):
                validate_and_materialize_bundle(
                    unsafe,
                    packet_as_of=PACKET_AS_OF,
                    active_tickers={"TST"},
                    project_root=root,
                )

            active = _bundle(root)
            active["boundaries"]["email_eligible"] = True
            active = seal_bundle(active)
            with self.assertRaisesRegex(
                ValuationInputBundleError,
                "email_eligible must remain false",
            ):
                validate_and_materialize_bundle(
                    active,
                    packet_as_of=PACKET_AS_OF,
                    active_tickers={"TST"},
                    project_root=root,
                )

    def test_packet_builder_imports_receipt_but_market_gate_stays_closed(self) -> None:
        baseline = build_packet(
            PACKET_AS_OF,
            valuation_bundle_path=Path("/definitely/absent/valuation.json"),
        )
        ticker = baseline["entities"][0]["ticker"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle_path = (
                root / "04_data/phase5r/phase5r_valuation_inputs.local.json"
            )
            _write_bundle(bundle_path, _bundle(root, ticker=ticker))
            packet = build_packet(
                PACKET_AS_OF,
                valuation_bundle_path=bundle_path,
                valuation_source_root=root,
            )
        self.assertEqual(
            [row["ticker"] for row in packet["valuation_evidence"]],
            [ticker],
        )
        self.assertIn(ticker, packet["gates"]["valuation_action_grade_tickers"])
        self.assertFalse(packet["gates"]["market_data_action_grade"])
        self.assertFalse(packet["boundaries"]["canonical_effect"])
        self.assertFalse(packet["boundaries"]["email_eligible"])
        self.assertTrue(
            any(
                row["calculation_id"].startswith(f"valuation:{ticker}:")
                for row in packet["calculations"]
            )
        )


if __name__ == "__main__":
    unittest.main()
