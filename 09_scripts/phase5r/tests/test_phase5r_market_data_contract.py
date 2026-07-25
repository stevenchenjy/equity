from __future__ import annotations

import ast
import copy
import json
import unittest
from pathlib import Path

from _support import SCRIPT_DIR
from phase5r_market_data_contract import (
    DEFAULT_REGISTRY_PATH,
    MarketDataContractError,
    load_provider_registry,
    seal_bundle,
    validate_market_data_bundle,
    validate_provider_registry,
)
from phase5r_massive_payload_adapter import normalize_massive_fixture


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "market_data"
    / "massive_valid_synthetic.json"
)


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class MarketDataContractTests(unittest.TestCase):
    def test_committed_registry_is_offline_and_fail_closed(self) -> None:
        registry = load_provider_registry()
        self.assertEqual(DEFAULT_REGISTRY_PATH.name, "phase5r_market_data_provider_registry.json")
        self.assertEqual(registry["mode"], "offline_fixture")
        self.assertTrue(registry["synthetic_fixture_only"])
        self.assertTrue(registry["external_import_only"])
        for field in (
            "action_grade_enabled",
            "canonical_influence_enabled",
            "network_enabled",
            "repository_credentials_allowed",
            "raw_licensed_data_committable",
            "broker_connection_allowed",
            "order_code_allowed",
            "email_allowed",
        ):
            with self.subTest(field=field):
                self.assertFalse(registry[field])
        self.assertEqual(registry["license_activation_receipt_sha256"], "")

    def test_registry_rejects_activation_without_a_phase_change(self) -> None:
        for mutation in (
            {"action_grade_enabled": True},
            {"network_enabled": True},
            {"repository_credentials_allowed": True},
            {"synthetic_fixture_only": False},
            {"license_activation_receipt_sha256": "a" * 64},
        ):
            with self.subTest(mutation=mutation):
                registry = load_provider_registry()
                registry.update(mutation)
                with self.assertRaises(MarketDataContractError):
                    validate_provider_registry(registry)

    def test_valid_fixture_normalizes_deterministically_but_not_action_grade(
        self,
    ) -> None:
        first = normalize_massive_fixture(fixture())
        second = normalize_massive_fixture(fixture())
        self.assertEqual(first, second)
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        self.assertEqual(first["action_grade_tickers"], [])
        self.assertFalse(first["action_grade_enabled"])
        self.assertFalse(first["canonical_influence_enabled"])
        self.assertTrue(first["synthetic_fixture"])
        self.assertEqual(first["records"][0]["ticker"], "TST")
        self.assertFalse(first["records"][0]["action_grade_eligible"])
        self.assertEqual(
            set(first["records"][0]["rejection_reasons"]),
            {
                "registry_action_grade_disabled",
                "synthetic_fixture_not_action_grade",
            },
        )
        for field in (
            "network_used",
            "credentials_read",
            "broker_connected",
            "order_code_created",
            "email_attempted",
        ):
            self.assertFalse(first[field])

    def test_provider_error_and_incomplete_pagination_are_rejected(self) -> None:
        payload = fixture()
        payload["responses"]["current_adjusted_aggregate"]["status"] = "ERROR"
        with self.assertRaisesRegex(MarketDataContractError, "was not OK"):
            normalize_massive_fixture(payload)

        payload = fixture()
        payload["responses"]["splits"]["next_url"] = "/v3/reference/splits/TST/page/2"
        with self.assertRaisesRegex(MarketDataContractError, "incomplete pagination"):
            normalize_massive_fixture(payload)

    def test_ticker_and_security_identity_mismatches_are_rejected(self) -> None:
        payload = fixture()
        payload["responses"]["current_open_close"]["results"]["symbol"] = "ALT"
        with self.assertRaisesRegex(MarketDataContractError, "ticker/session mismatch"):
            normalize_massive_fixture(payload)

        payload = fixture()
        payload["responses"]["ticker_overview"]["results"]["primary_exchange"] = "PINX"
        with self.assertRaisesRegex(MarketDataContractError, "unsupported security identity"):
            normalize_massive_fixture(payload)

        payload = fixture()
        payload["responses"]["ticker_overview"]["results"]["currency_name"] = "cad"
        with self.assertRaisesRegex(MarketDataContractError, "unsupported security identity"):
            normalize_massive_fixture(payload)

    def test_nonfinite_negative_and_ohlc_invalid_values_are_rejected(self) -> None:
        payload = fixture()
        payload["responses"]["current_adjusted_aggregate"]["results"]["c"] = float("nan")
        with self.assertRaisesRegex(MarketDataContractError, "finite numeric"):
            normalize_massive_fixture(payload)

        bundle = normalize_massive_fixture(fixture())
        negative = copy.deepcopy(bundle)
        negative["records"][0]["bars"][0]["volume"] = -1
        negative = seal_bundle(negative)
        with self.assertRaisesRegex(MarketDataContractError, "non-negative"):
            validate_market_data_bundle(negative)

        outside = copy.deepcopy(bundle)
        outside["records"][0]["bars"][0]["close"] = 60
        outside = seal_bundle(outside)
        with self.assertRaisesRegex(MarketDataContractError, "outside low/high"):
            validate_market_data_bundle(outside)

    def test_adjusted_disagreement_and_window_corporate_action_are_rejected(
        self,
    ) -> None:
        payload = fixture()
        payload["responses"]["current_unadjusted_aggregate"]["results"]["c"] = 25.5
        with self.assertRaisesRegex(MarketDataContractError, "adjusted/unadjusted mismatch"):
            normalize_massive_fixture(payload)

        payload = fixture()
        payload["responses"]["splits"]["results"] = [
            {
                "id": "split:TST:2026-07-24",
                "ticker": "TST",
                "execution_date": "2026-07-24",
                "split_from": 1,
                "split_to": 2,
            }
        ]
        with self.assertRaisesRegex(
            MarketDataContractError,
            "requires explicit reconciliation",
        ):
            normalize_massive_fixture(payload)

    def test_bundle_content_hash_and_ticker_eligibility_cannot_be_forged(
        self,
    ) -> None:
        bundle = normalize_massive_fixture(fixture())
        tampered = copy.deepcopy(bundle)
        tampered["records"][0]["identity"]["name_if_it_existed"] = "forged"
        with self.assertRaisesRegex(MarketDataContractError, "field mismatch"):
            validate_market_data_bundle(tampered)

        tampered = copy.deepcopy(bundle)
        tampered["action_grade_tickers"] = ["TST"]
        tampered = seal_bundle(tampered)
        with self.assertRaisesRegex(MarketDataContractError, "must be empty"):
            validate_market_data_bundle(tampered)

        tampered = copy.deepcopy(bundle)
        tampered["retrieved_at"] = "2026-07-24T20:06:00-04:00"
        with self.assertRaises(MarketDataContractError):
            validate_market_data_bundle(tampered)

    def test_adapter_and_contract_have_no_network_or_execution_imports(self) -> None:
        blocked_modules = {
            "alpaca",
            "ccxt",
            "dotenv",
            "httpx",
            "imaplib",
            "requests",
            "robin_stocks",
            "smtplib",
            "socket",
            "urllib",
            "yfinance",
        }
        blocked_calls = {
            "create_order",
            "execute_trade",
            "place_order",
            "send_order",
            "sendmail",
            "submit_order",
        }
        for name in (
            "phase5r_market_data_contract.py",
            "phase5r_massive_payload_adapter.py",
        ):
            with self.subTest(name=name):
                tree = ast.parse((SCRIPT_DIR / name).read_text(encoding="utf-8"))
                imported: set[str] = set()
                defined_or_called: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imported.add((node.module or "").split(".")[0])
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        defined_or_called.add(node.name)
                    elif isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            defined_or_called.add(node.func.id)
                        elif isinstance(node.func, ast.Attribute):
                            defined_or_called.add(node.func.attr)
                self.assertFalse(imported & blocked_modules)
                self.assertFalse(defined_or_called & blocked_calls)


if __name__ == "__main__":
    unittest.main()
