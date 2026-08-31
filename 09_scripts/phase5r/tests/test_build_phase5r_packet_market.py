from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import build_phase5r_decision_evidence_packet as packet_builder


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class PacketMarketObservationTests(unittest.TestCase):
    def test_default_packet_as_of_is_current_not_stale_decision_time(
        self,
    ) -> None:
        current = "2026-07-25T04:40:00-04:00"
        with patch.object(packet_builder, "iso_now", return_value=current):
            self.assertEqual(
                packet_builder._resolve_packet_as_of(None),
                current,
            )
        historical = "2025-01-02T09:00:00-05:00"
        self.assertEqual(
            packet_builder._resolve_packet_as_of(historical),
            historical,
        )

    def observation(
        self,
        *,
        timestamp: str,
        verified_session: str,
        as_of: str = "2026-07-25T12:00:00-04:00",
    ) -> tuple[dict, bool]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.csv"
            quality = root / "quality.csv"
            write_csv(
                snapshot,
                [
                    {
                        "ticker": "TST",
                        "last_price": "51",
                        "previous_close": "50",
                        "intraday_change_pct": "2",
                        "relative_volume": "1.1",
                        "fifty_two_week_high": "60",
                        "fifty_two_week_low": "30",
                        "market_session_date": "2026-07-24",
                        "data_timestamp": timestamp,
                        "data_source": "synthetic_test",
                        "data_quality_label": "ok",
                    }
                ],
            )
            write_csv(
                quality,
                [{"ticker": "TST", "usable_for_scoring": "yes"}],
            )
            with (
                patch.object(packet_builder, "MARKET_SNAPSHOT_PATH", snapshot),
                patch.object(packet_builder, "MARKET_QUALITY_PATH", quality),
            ):
                observations, _, point_in_time_safe = (
                    packet_builder._market_observations(
                        {"TST"},
                        as_of,
                        verified_session,
                    )
                )
        return observations[0], point_in_time_safe

    def test_verified_friday_close_remains_complete_on_weekend(self) -> None:
        observation, point_in_time_safe = self.observation(
            timestamp="2026-07-24T20:05:00-04:00",
            verified_session="2026-07-24",
        )
        self.assertEqual(observation["bar_state"], "complete_close")
        self.assertTrue(point_in_time_safe)

    def test_unverified_or_pre_close_timestamp_cannot_be_complete(self) -> None:
        for timestamp, verified_session in (
            ("2026-07-24T20:05:00-04:00", ""),
            ("2026-07-24T15:59:00-04:00", "2026-07-24"),
            ("2026-07-24T20:05:00-04:00", "2026-07-23"),
        ):
            with self.subTest(
                timestamp=timestamp,
                verified_session=verified_session,
            ):
                observation, _ = self.observation(
                    timestamp=timestamp,
                    verified_session=verified_session,
                )
                self.assertEqual(
                    observation["bar_state"],
                    "intraday_or_unverified",
                )

    def test_future_observation_is_not_point_in_time_safe(self) -> None:
        observation, point_in_time_safe = self.observation(
            timestamp="2026-07-25T12:01:00-04:00",
            verified_session="2026-07-24",
        )
        self.assertEqual(observation["bar_state"], "intraday_or_unverified")
        self.assertFalse(point_in_time_safe)

    def test_decision_ticker_parser_accepts_current_and_legacy_shapes(self) -> None:
        self.assertEqual(
            packet_builder._decision_tickers(
                ["tst", {"ticker": " alt "}, "", {}, None]
            ),
            {"TST", "ALT"},
        )
        self.assertEqual(packet_builder._decision_tickers("TST"), set())

    def test_c9_decision_is_translated_to_hidden_ticker_policy_caps(self) -> None:
        entities = [
            {"ticker": "HOLD", "role": "held"},
            {"ticker": "TRIM", "role": "held"},
            {"ticker": "EXIT", "role": "held"},
            {"ticker": "ADD", "role": "held"},
            {"ticker": "WATCH", "role": "candidate"},
            {"ticker": "BUY", "role": "candidate"},
        ]
        decision = {
            "held_positions": [
                {"ticker": "HOLD", "action": "hold"},
                {"ticker": "TRIM", "action": "trim_specific_shares_review"},
                {"ticker": "EXIT", "action": "exit_review"},
                {"ticker": "ADD", "action": "add_specific_dollars_review"},
            ],
            "watch_candidates": [
                {
                    "ticker": "WATCH",
                    "label": "wait_for_more_evidence",
                    "action": "watch_only",
                },
                {
                    "ticker": "BUY",
                    "label": "eligible_buy_review",
                    "action": "buy_review",
                },
            ],
            "eligible_action_review_candidates": ["ADD", "BUY"],
        }
        allowed = packet_builder._allowed_classifications_by_ticker(
            decision,
            entities,
        )
        self.assertEqual(allowed["HOLD"], ["hold_existing", "abstain"])
        self.assertIn("trim_review", allowed["TRIM"])
        self.assertNotIn("exit_review", allowed["TRIM"])
        self.assertIn("exit_review", allowed["EXIT"])
        self.assertIn("real_trade_candidate", allowed["ADD"])
        self.assertEqual(
            allowed["WATCH"],
            ["reject", "watchlist", "abstain"],
        )
        self.assertIn("real_trade_candidate", allowed["BUY"])

    def test_effective_acceptance_map_includes_validated_extensions(self) -> None:
        historical = {
            "0000000001-26-000001": {
                "accession_number": "0000000001-26-000001",
                "ticker": "OLD",
            }
        }
        extension = {
            "accession_number": "0000000002-26-000002",
            "ticker": "NEW",
        }
        with (
            patch.object(packet_builder, "acceptance_map", return_value=historical),
            patch.object(packet_builder, "sha256_file", return_value="a" * 64),
            patch.object(
                packet_builder,
                "load_extension_artifacts",
                return_value=[{"records": [extension]}],
            ),
            patch.object(
                packet_builder,
                "extension_acceptance_records",
                return_value=[extension],
            ),
        ):
            effective = packet_builder._effective_acceptance_map()
        self.assertEqual(set(effective), set(historical) | {extension["accession_number"]})

    def test_packet_filing_selection_excludes_historical_material_backfill(self) -> None:
        rows = [
            {
                "accession_number": "newest",
                "filing_date": "2026-08-27",
                "material_event": "yes",
            },
            {
                "accession_number": "second",
                "filing_date": "2026-08-26",
                "material_event": "yes",
            },
            {
                "accession_number": "current-extra",
                "filing_date": "2026-08-25",
                "material_event": "yes",
            },
            {
                "accession_number": "historical-backfill",
                "filing_date": "2021-01-01",
                "material_event": "yes",
            },
        ]
        selected = packet_builder._selected_filing_rows(
            rows,
            {"current-extra"},
        )
        self.assertEqual(
            [row["accession_number"] for row in selected],
            ["newest", "second", "current-extra"],
        )


if __name__ == "__main__":
    unittest.main()
