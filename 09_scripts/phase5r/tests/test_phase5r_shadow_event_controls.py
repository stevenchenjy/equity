from __future__ import annotations

import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_daily_common import canonical_sha256
from test_phase5r_shadow_llm import fake_packet, valid_analyst
import run_phase5r_shadow_llm_evaluation as runner


def economic_packet() -> dict:
    packet = fake_packet()
    fact = {
        "ticker": "IOT", "source_id": "sec-xbrl:IOT:CY2026Q2",
        "fetched_at": "2026-09-01T12:00:00-04:00",
        "latest_frame": "CY2026Q2", "latest_period_end": "2026-07-31",
        "net_margin_pct": "-14.46", "data_quality": "ok",
    }
    packet["fundamental_observations"] = [fact]
    packet["source_catalog"].extend([
        {
            "ticker": "IOT", "source_id": fact["source_id"],
            "source_type": "sec_companyfacts_xbrl", "authority": "primary_official",
            "accepted_at": fact["fetched_at"], "content_sha256": canonical_sha256(fact),
            "locator": {"frame": "CY2026Q2", "period": "2026-07-31"},
        },
        {
            "ticker": "IOT", "source_id": "valuation-sec:IOT:2026-07-31",
            "source_type": "sec_valuation_fact", "authority": "primary_official",
            "accepted_at": fact["fetched_at"], "content_sha256": "e" * 64,
            "locator": {"char_start": 123, "char_end": 234},
            "excerpt_text": "IOT,123,2026-09-01T12:00:00-04:00,2026-07-31,CY2026Q2,100,20",
        },
        {
            "ticker": "IOT", "source_id": "metadata:IOT:first",
            "source_type": "sec_filing_metadata", "authority": "primary_official",
            "accepted_at": fact["fetched_at"], "content_sha256": "f" * 64,
            "locator": {"accession_number": "000123-26-001", "form": "10-Q"},
        },
    ])
    return packet


class ShadowEventControlTests(unittest.TestCase):
    def test_document_resampling_is_not_a_new_event_but_new_evidence_is(self) -> None:
        first = economic_packet()
        first["source_catalog"][0].update({
            "source_type": "sec_filing_text_chunk", "source_url": "https://www.sec.gov/Archives/test.htm",
            "locator": {"accession_number": "first-filing", "document": "test.htm", "char_start": 0, "char_end": 4000},
        })
        second = copy.deepcopy(first)
        extra = copy.deepcopy(first["source_catalog"][0])
        extra["locator"].update({"char_start": 4000, "char_end": 8000})
        extra["content_sha256"] = "5" * 64
        second["source_catalog"].append(extra)
        self.assertTrue(runner.source_selection_repeat(second, first))
        self.assertNotEqual(runner.semantic_event_fingerprint(first), runner.semantic_event_fingerprint(second))
        second["source_catalog"][0]["content_sha256"] = "7" * 64
        self.assertFalse(runner.source_selection_repeat(second, first))
        second = copy.deepcopy(first)
        extra["source_url"] = "https://www.sec.gov/Archives/new-ex99.htm"
        extra["locator"]["document"] = "new-ex99.htm"
        second["source_catalog"].append(extra)
        self.assertFalse(runner.source_selection_repeat(second, first))
        second = copy.deepcopy(first)
        second["fundamental_observations"][0]["net_margin_pct"] = "-12.0"
        self.assertFalse(runner.source_selection_repeat(second, first))

    def test_official_provenance_enrichment_alone_is_not_a_paid_semantic_event(self) -> None:
        first = economic_packet()
        second = copy.deepcopy(first)
        second["fundamental_observations"][0]["field_provenance_json"] = {"net_margin_pct": {"filed": "2026-09-04", "accn": "0000000001-26-000001"}}
        self.assertEqual(runner.semantic_event_fingerprint(first), runner.semantic_event_fingerprint(second))

    def test_all_refresh_wrappers_change_without_a_new_semantic_event(self) -> None:
        first = economic_packet()
        second = copy.deepcopy(first)
        fact = second["fundamental_observations"][0]
        fact["fetched_at"] = "2026-09-02T11:00:00-04:00"
        fact["source_id"] += ":refreshed"
        second["source_catalog"][1].update({
            "content_sha256": canonical_sha256(fact), "accepted_at": fact["fetched_at"],
            "source_id": fact["source_id"],
        })
        second["source_catalog"][2].update({
            "content_sha256": "9" * 64,
            "excerpt_text": "IOT,123,2026-09-02T11:00:00-04:00,2026-07-31,CY2026Q2,100,20",
            "locator": {"char_start": 223, "char_end": 334},
        })
        second["source_catalog"][3].update({
            "content_sha256": "8" * 64, "accepted_at": fact["fetched_at"],
            "source_id": "metadata:IOT:refreshed",
        })
        second["research_context"] = [{"ticker": "IOT", "catalyst_news_quality_score": "3.0", "reason": "Daily price changed."}]
        self.assertNotEqual(canonical_sha256(first), canonical_sha256(second))
        self.assertEqual(runner.semantic_event_fingerprint(first), runner.semantic_event_fingerprint(second))
        second["fundamental_observations"][0]["net_margin_pct"] = "-12.00"
        self.assertNotEqual(runner.semantic_event_fingerprint(first), runner.semantic_event_fingerprint(second))

    def test_period_filing_text_and_thesis_changes_remain_events(self) -> None:
        packet = economic_packet()
        baseline = runner.semantic_event_fingerprint(packet)
        for field, replacement in (("latest_frame", "CY2026Q3"), ("data_quality", "stale")):
            changed = copy.deepcopy(packet)
            changed["fundamental_observations"][0][field] = replacement
            self.assertNotEqual(baseline, runner.semantic_event_fingerprint(changed))
        changed = copy.deepcopy(packet)
        changed["entities"][0]["thesis"] = "A genuinely revised research hypothesis."
        self.assertNotEqual(baseline, runner.semantic_event_fingerprint(changed))
        changed = copy.deepcopy(packet)
        changed["source_catalog"][0]["content_sha256"] = "3" * 64
        self.assertNotEqual(baseline, runner.semantic_event_fingerprint(changed))

    def test_semantic_digest_does_not_mutate_raw_provenance(self) -> None:
        packet = economic_packet()
        before = copy.deepcopy(packet)
        runner.semantic_event_components(packet)
        self.assertEqual(packet, before)

    def test_historical_archive_reindex_prevents_migration_duplicate(self) -> None:
        packet = economic_packet()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "packets.local"
            archive.mkdir()
            archived = archive / "legacy-event-hash.json"
            archived.write_text(json.dumps(packet))
            runs = root / "runs.local"
            run = runs / "legacy-run"
            run.mkdir(parents=True)
            historical = {"packet_id": packet["packet_id"], "evaluation_class": "live_shadow", "evaluation_stage": "bounded_autonomous_v1", "semantic_event_fingerprint": "old-v1-digest"}
            (run / "failure.json").write_text(json.dumps(historical))
            with patch.object(runner, "load_packet", side_effect=lambda path: json.loads(path.read_text())):
                self.assertTrue(runner._event_already_attempted(
                    runs, event_fingerprint=runner.semantic_event_fingerprint(packet),
                    evaluation_class="live_shadow", evaluation_stage="bounded_autonomous_v1",
                    packet_archive_root=archive,
                ))
            self.assertEqual(json.loads((run / "failure.json").read_text()), historical)

    def test_same_event_captures_archive_without_overwrite_conflict(self) -> None:
        first = economic_packet()
        second = copy.deepcopy(first)
        second["packet_id"] = "d" * 64
        second["as_of_et"] = "2026-09-03T12:00:00-04:00"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner._archive_packet(root, first)
            runner._archive_packet(root, second)
            self.assertEqual(len(list(root.glob("*.json"))), 2)
            self.assertEqual(json.loads((root / f"{first['packet_id']}.json").read_text()), first)

    def test_candidate_ranking_subset_of_seen_issuers_is_not_new_research(self) -> None:
        packet = economic_packet()
        components = runner.semantic_event_components(packet)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "runs.local" / "prior-event"
            run.mkdir(parents=True)
            (run / "bundle.json").write_text(json.dumps({
                "evaluation_class": "live_shadow",
                "semantic_event_fingerprint": "a-prior-larger-packet",
                "issuer_semantic_components": {**components, "META": "another-issuer"},
            }))
            self.assertTrue(runner._event_already_attempted(
                root / "runs.local", event_fingerprint=runner.semantic_event_fingerprint(packet),
                evaluation_class="live_shadow", evaluation_stage="bounded_autonomous_v1",
                issuer_components=components,
            ))
            components["IOT"] = "genuinely-new-company-evidence"
            self.assertFalse(runner._event_already_attempted(
                root / "runs.local", event_fingerprint=runner.semantic_event_fingerprint(packet),
                evaluation_class="live_shadow", evaluation_stage="bounded_autonomous_v1",
                issuer_components=components,
            ))

    def test_replay_sampling_deduplicates_refreshes_and_rejects_future_sources(self) -> None:
        packet = economic_packet()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "packets.local"
            archive.mkdir()
            first = archive / "z-first.json"
            first.write_text(json.dumps(packet))
            later = copy.deepcopy(packet)
            later["packet_id"] = "d" * 64
            later["as_of_et"] = "2026-09-03T12:00:00-04:00"
            (archive / "a-later.json").write_text(json.dumps(later))
            invalid = copy.deepcopy(packet)
            invalid["packet_id"] = "f" * 64
            invalid["source_catalog"][0]["accepted_at"] = "2030-01-01T00:00:00Z"
            (archive / "invalid.json").write_text(json.dumps(invalid))
            with patch.object(runner, "load_packet", side_effect=lambda path: json.loads(path.read_text())):
                chosen = runner._select_replay_packet(archive, root / "runs.local", runner.load_config())
            self.assertEqual(chosen, first)

    def test_critic_skips_mechanical_restatement_but_judge_remains_separate(self) -> None:
        packet = economic_packet()
        analyst = valid_analyst(packet)
        claim = analyst["claims"][0]
        claim.update({"statement": "The company reported a GAAP net loss.", "period": "CY2026Q2", "source_ids": ["sec-xbrl:IOT:CY2026Q2"]})
        analyst["ticker_reviews"][0]["semantic_state"] = "weakened"
        self.assertEqual(runner.critic_route(analyst, runner.load_config(), packet), (False, []))
        claim["statement"] = "The company reported a GAAP net loss because a concentrated partner channel weakened."
        claim["novelty"] = "new_contradiction"
        self.assertTrue(runner.critic_route(analyst, runner.load_config(), packet)[0])

    def test_input_budget_fails_before_any_provider_attempt(self) -> None:
        limits = runner.load_config()["limits"]
        limits["maximum_input_bytes_per_call"] = 100
        with self.assertRaisesRegex(runner.ShadowRunError, "input-byte"):
            runner._input_preflight(schema={}, instructions="x" * 200, input_payload={}, limits=limits)

    def test_downstream_judge_headroom_is_checked_before_analyst_invocation(self) -> None:
        packet = economic_packet()
        config = runner.load_config()
        config["limits"]["maximum_input_bytes_per_call"] = 30000
        view = runner.build_semantic_view(packet)
        # The small analyst envelope fits, but downstream dynamic candidate
        # headroom does not: reject the whole event without a paid first call.
        runner._input_preflight(schema={}, instructions=runner.ANALYST_INSTRUCTIONS, input_payload={"semantic_view": view}, limits=config["limits"])
        with self.assertRaisesRegex(runner.ShadowRunError, "headroom"):
            runner._event_input_preflight(packet, view, config)

    def test_observed_token_budget_preserves_unknown_cost_and_unreported_calls(self) -> None:
        config = runner.load_config()
        stage = config["evaluation_stage"]
        rows = [{"event": "started", "attempt_id": "a", "run_id": "r", "evaluation_stage": stage}]
        status = runner._token_budget_status(rows, evaluation_stage=stage)
        self.assertIsNone(status["authoritative_billing_cost_usd"])
        self.assertEqual(status["stage_calls_with_unreported_usage"], 1)
        with self.assertRaisesRegex(runner.ShadowRunError, "unreported"):
            runner._require_token_capacity(rows, limits=config["limits"], evaluation_stage=stage, reserve_full_run=True)
        rows.append({"event": "completed", "attempt_id": "a", "run_id": "r", "evaluation_stage": stage, "authoritative_token_usage": {"total_tokens": 300000}})
        with self.assertRaisesRegex(runner.ShadowRunError, "per-run"):
            runner._require_token_capacity(rows, limits=config["limits"], evaluation_stage=stage, run_id="r", reserve_full_run=False)
        rows[-1]["authoritative_token_usage"]["total_tokens"] = 1600000
        with self.assertRaisesRegex(runner.ShadowRunError, "stage"):
            runner._require_token_capacity(rows, limits=config["limits"], evaluation_stage=stage, reserve_full_run=True)

    def test_preflight_is_read_only_and_does_not_create_call_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "missing-ledger.jsonl"
            with patch.object(runner, "LEDGER_PATH", ledger):
                receipt = runner.preflight(
                    economic_packet(), config=runner.load_config(), output_root=root / "runs.local",
                    packet_archive_root=root / "packets.local", evaluation_class="live_shadow",
                )
            self.assertTrue(receipt["eligible"])
            self.assertFalse(receipt["provider_invoked"])
            self.assertIsNone(receipt["cost_accounting"]["authoritative_billing_cost_usd"])
            self.assertFalse(ledger.exists())

    def test_preflight_cli_dispatches_packet_once_and_never_calls_provider(self) -> None:
        packet = economic_packet()
        with patch.object(runner, "load_packet", return_value=packet), patch.object(runner, "preflight", return_value={"provider_invoked": False}) as preflight, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--preflight"]), 0)
        preflight.assert_called_once()
        self.assertEqual(preflight.call_args.args, (packet,))
        self.assertNotIn("packet", preflight.call_args.kwargs)

    def test_auto_live_cli_passes_packet_to_resample_guard(self) -> None:
        packet = economic_packet()
        with patch.object(runner, "load_packet", return_value=packet), patch.object(runner, "_event_already_attempted", return_value=True) as guard, patch.object(runner, "_archive_packet"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--auto-live"]), 0)
        self.assertEqual(guard.call_args.kwargs["packet"], packet)


if __name__ == "__main__":
    unittest.main()
