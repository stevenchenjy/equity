from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import build_decision_evidence_packet as packet_builder
from build_decision_evidence_packet import build_packet
from sec_acceptance import acceptance_map, build_acceptance_index
from sec_acceptance_extensions import load_extension_artifacts
from valuation_input_bundle import (
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
        "03_source_data/equity_research/valuation_market.local.txt",
        "share_price=10; session=2026-07-27 close",
    )
    sec_file = _write_source(
        root,
        "02_filings/issuer_filings/valuation_sec.local.txt",
        (
            "diluted_shares=100; cash_and_equivalents=200; total_debt=100; "
            "revenue_ttm=400; free_cash_flow_ttm=40; prior_diluted_shares=80"
        ),
    )
    scenario_file = _write_source(
        root,
        "04_data/equity_research/valuation_source_scenario.local.txt",
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
                root / "03_source_data/equity_research/valuation_market.local.txt"
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
        packet_as_of = "2026-07-28T13:00:00Z"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ticker = "TST"
            # Exercise the real packet/bundle validators using an isolated
            # synthetic account, decision and CSV inputs. A clean source
            # checkout intentionally has no current private decision artifact.
            original_root = packet_builder.ROOT
            path_names = ("DAILY_DECISION_JSON_PATH", "ACCOUNT_STATE_PATH", "EVIDENCE_STATUS_PATH",
                "POSITIONS_PATH", "POSITION_RECOMMENDATION_PATH", "NEW_CANDIDATE_PATH", "FUNDAMENTALS_PATH",
                "MARKET_QUALITY_PATH", "MARKET_SNAPSHOT_PATH", "EVIDENCE_LEDGER_PATH", "C5_PACKET_PATH",
                "C9_SCORE_PATH", "ARTIFACT_INDEX_PATH", "SEC_ACCEPTANCE_INDEX_PATH")
            paths = {name: root / getattr(packet_builder, name).relative_to(original_root) for name in path_names}
            for name, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == ".csv":
                    path.write_text("ticker\n", encoding="utf-8")
            def write_rows(name, rows):
                with paths[name].open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            paths["DAILY_DECISION_JSON_PATH"].write_text(json.dumps({
                "cycle_date": "2026-07-28", "generated_at": packet_as_of,
                "decision_fingerprint": "synthetic-test-decision", "material_events": [],
                "market_gate": {"passed": True, "complete_close_verified": True,
                                "expected_market_session": "2026-07-27"},
                "held_positions": [{"ticker": ticker, "action": "hold"}],
                "eligible_action_review_candidates": []}), encoding="utf-8")
            paths["ACCOUNT_STATE_PATH"].write_text(json.dumps({
                "account_total_value": 4000, "prior_account_value": 4000, "new_external_cash": 0,
                "cash_available": 3000, "cash_reserved": 0, "investment_horizon_years": 1,
                "cash_needed_within_three_years": "no", "core_allocation_target_pct": 30,
                "active_stock_target_pct": 70, "active_stock_hard_cap_pct": 70, "cash_target_pct": 0,
                "single_stock_default_cap_pct": None, "single_stock_hard_cap_pct": None,
                "last_updated": AVAILABLE_AT}), encoding="utf-8")
            write_rows("POSITIONS_PATH", [{"ticker": ticker, "shares": "100", "horizon_class": "long_term",
                                           "thesis": "Synthetic test company", "invalidation_rule": "evidence review"}])
            write_rows("POSITION_RECOMMENDATION_PATH", [{"ticker": ticker, "current_weight_pct": "25",
                                                         "recommended_action": "hold"}])
            write_rows("MARKET_SNAPSHOT_PATH", [{"ticker": ticker, "last_price": "10", "previous_close": "9.9",
                "intraday_change_pct": "1.01", "relative_volume": "1", "fifty_two_week_high": "11",
                "fifty_two_week_low": "8", "market_session_date": "2026-07-27",
                "data_timestamp": AVAILABLE_AT, "data_source": "synthetic_public_context",
                "data_quality_label": "ok"}])
            write_rows("MARKET_QUALITY_PATH", [{"ticker": ticker, "usable_for_scoring": "yes"}])
            paths["ARTIFACT_INDEX_PATH"].write_text(json.dumps({"artifacts": []}), encoding="utf-8")
            paths["SEC_ACCEPTANCE_INDEX_PATH"].write_text(json.dumps(
                build_acceptance_index(generated_at=AVAILABLE_AT)), encoding="utf-8")
            evidence_status_path = (
                root / "03_source_data/equity_research/daily_evidence_status.json"
            )
            evidence_status_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_status_path.write_text(
                json.dumps(
                    {
                        "last_success_at": AVAILABLE_AT,
                        "scan_status": "ok",
                        "scanned_tickers": [],
                        "held_coverage_complete": False,
                        "held_fundamental_coverage_complete": False,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            with ExitStack() as stack:
                for name, path in paths.items():
                    stack.enter_context(patch.object(packet_builder, name, path))
                stack.enter_context(patch.object(packet_builder, "ROOT", root))
                stack.enter_context(patch("account_common.ACCOUNT_STATE", paths["ACCOUNT_STATE_PATH"]))
                stack.enter_context(patch.object(packet_builder, "acceptance_map",
                    side_effect=lambda: acceptance_map(paths["SEC_ACCEPTANCE_INDEX_PATH"])))
                stack.enter_context(patch.object(packet_builder, "load_extension_artifacts",
                    side_effect=lambda **kwargs: load_extension_artifacts(directory=root / "extensions", **kwargs)))
                baseline = build_packet(
                    packet_as_of, valuation_bundle_path=root / "absent-valuation.json",
                    valuation_source_root=root,
                )
                self.assertEqual([row["ticker"] for row in baseline["entities"]], [ticker])
                bundle_path = (
                    root
                    / "04_data/equity_research/valuation_inputs.local.json"
                )
                _write_bundle(bundle_path, _bundle(root, ticker=ticker))
                packet = build_packet(
                    packet_as_of,
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
