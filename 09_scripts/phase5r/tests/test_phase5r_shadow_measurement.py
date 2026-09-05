from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from test_phase5r_shadow_llm import fake_packet, valid_analyst, valid_critic, valid_judge
from phase5r_shadow_llm_contract import (
    build_automatic_evaluation, build_blind_judge_target,
    build_deterministic_baseline, deterministic_claim_check,
)
from evaluate_phase5r_shadow_llm_incremental_value import (
    _deduplicate_evidence, _official_follow_up, aggregate,
)
from run_phase5r_shadow_llm_evaluation import load_config


def fact_packet() -> dict:
    packet = fake_packet()
    packet["fundamental_observations"] = [{
        "ticker": "IOT", "latest_frame": "CY2026Q2", "latest_period_end": "2026-07-31",
        "source_id": "sec-xbrl:IOT:CY2026Q2", "data_quality": "ok",
        "net_income_latest": "-100", "net_margin_pct": "-14.46", "revenue_yoy_pct": "30",
    }]
    return packet


def net_loss_claim() -> dict:
    claim = valid_analyst()["claims"][0]
    claim.update(claim_id="iot_gaap_net_loss", period="CY2026Q2",
                 statement="The company remained loss-making on a GAAP net-income basis in the quarter.",
                 source_ids=["sec-xbrl:IOT:CY2026Q2"])
    return claim


def evaluation_bundle(run_id: str, *, partial: bool = False) -> dict:
    analyst = valid_analyst()
    critic = valid_critic(analyst)
    if partial:
        critic["claim_reviews"][0]["verdict"] = "partial"
        critic["claim_reviews"][0]["reason"] = "The claim period is narrower than the annual source."
    target, mapping = build_blind_judge_target(analyst, critic)
    judge = valid_judge(analyst, critic)
    return {
        "run_id": run_id, "packet_id": "a" * 64, "cycle_date": "2026-09-01",
        "completed_at": "2026-09-02T12:00:00-04:00", "evaluation_class": "live_shadow",
        "evaluation_stage": load_config()["evaluation_stage"], "entity_tickers": ["IOT", "SPY"],
        "analyst": analyst, "critic": critic, "judge_target": target,
        "blind_candidate_mapping": mapping, "judge": judge,
        "automatic_evaluation": build_automatic_evaluation(analyst, critic, target, mapping, judge, schema_version="phase5r_shadow_automatic_evaluation_v1"),
        "critic_routing": {"routed": True, "reasons": ["material"]},
        "provider_metadata": [], "spot_check_recommended": False,
    }


class ShadowMeasurementTests(unittest.TestCase):
    def test_latest_official_packet_supplements_historical_proofs_and_is_wired(self) -> None:
        archived = fake_packet()
        current = copy.deepcopy(archived)
        current["packet_id"] = "b" * 64
        with (patch("evaluate_phase5r_shadow_llm_incremental_value._packet_for_bundle", return_value=archived),
              patch("evaluate_phase5r_shadow_llm_incremental_value._official_follow_up", wraps=_official_follow_up) as follow):
            aggregate([evaluation_bundle("one")], load_config(), snapshot_path=Path("/missing/snapshots"),
                      outcome_path=Path("/missing/outcomes"), later_official_packets=[current])
        self.assertEqual({packet["packet_id"] for packet in follow.call_args.args[1]}, {"a" * 64, "b" * 64})
        wrapper = SCRIPT_DIR.parents[1] / "07_automation/scheduler/run_phase5r_shadow_llm_event.sh"
        self.assertIn('--official-evidence-packet "${packet}"', wrapper.read_text())

    def test_baseline_includes_fact_sign_and_original_calculations(self) -> None:
        baseline = build_deterministic_baseline(fact_packet())
        self.assertTrue(any(row.get("baseline_kind") == "existing_deterministic_calculation" for row in baseline))
        facts = next(row for row in baseline if row.get("baseline_kind") == "deterministic_fact_and_sign_checklist")
        self.assertIn("GAAP net loss", [row["statement"] for row in facts["mechanical_sign_assertions"]])

    def test_net_loss_restatement_is_baseline_not_incremental(self) -> None:
        self.assertTrue(deterministic_claim_check(fact_packet(), net_loss_claim())["captured"])

    def test_scope_unknowns_and_forward_claims_are_not_filled_in(self) -> None:
        for mutation in ({"period": "FY2026"}, {"statement": "The company expects continued operating losses and may need capital."}):
            self.assertFalse(deterministic_claim_check(fact_packet(), {**net_loss_claim(), **mutation})["checkable"])
        packet = fact_packet()
        packet["fundamental_observations"][0]["data_quality"] = "stale"
        self.assertFalse(deterministic_claim_check(packet, net_loss_claim())["captured"])

    def test_false_sign_is_mechanically_refuted(self) -> None:
        claim = {**net_loss_claim(), "statement": "Positive net margin was reported."}
        self.assertEqual(deterministic_claim_check(fact_packet(), claim)["support"], "unsupported")

    def test_cash_flow_sign_and_simple_income_contrast_are_already_baseline(self) -> None:
        packet = fact_packet()
        packet["fundamental_observations"][0]["net_income_latest"] = "100"
        packet["calculations"].append({"ticker": "IOT", "metric": "valuation_free_cash_flow_margin_pct", "value": "-10", "recomputed_value": "-10", "reconciled": True, "inputs": [{"period": "TTM through 2026-07-31"}]})
        claim = {**net_loss_claim(), "period": "TTM through 2026-07-31", "statement": "Trailing free cash flow margin was negative despite positive quarterly net income."}
        self.assertTrue(deterministic_claim_check(packet, claim)["captured"])
        packet["calculations"][-1]["reconciled"] = False
        self.assertFalse(deterministic_claim_check(packet, claim)["captured"])

    def test_partial_period_qualification_excluded_v1_retained(self) -> None:
        bundle = evaluation_bundle("one", partial=True)
        legacy = copy.deepcopy(bundle["automatic_evaluation"])
        self.assertEqual(legacy["critic_judge_disagreements"], 0)
        current = build_automatic_evaluation(bundle["analyst"], bundle["critic"], bundle["judge_target"], bundle["blind_candidate_mapping"], bundle["judge"])
        self.assertEqual(current["critic_judge_disagreements"], 1)
        self.assertEqual(current["incremental_supported_material_items"], 0)
        self.assertEqual(bundle["automatic_evaluation"], legacy)

    def test_blinded_sign_controls_are_not_incremental_candidates(self) -> None:
        packet = fact_packet()
        analyst = valid_analyst(packet)
        target, mapping = build_blind_judge_target(analyst, None, packet=packet)
        self.assertEqual(len(target["candidates"]), 3)
        self.assertNotIn("origin", str(target))
        self.assertNotIn("expected_support", str(target))
        judge = valid_judge(analyst, None)
        judge["candidate_set_sha256"] = target["candidate_set_sha256"]
        judge["item_reviews"] = [{"blind_item_id": row["blind_item_id"], "support": mapping[row["blind_item_id"]].get("expected_support", "supported"), "materiality": "material", "baseline_captured": "yes", "reason": "Scoped sign verified.", "source_ids": row["source_ids"]} for row in target["candidates"]]
        result = build_automatic_evaluation(analyst, None, target, mapping, judge)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["deterministic_controls"]), 2)
        self.assertTrue(all(row["passed"] for row in result["deterministic_controls"]))

    def test_repeat_passage_is_one_family_despite_prose_id_changes(self) -> None:
        rows = [{"ticker": "IOT", "item_id": "first_topic", "_evidence_keys": ["text:one"]},
                {"ticker": "IOT", "item_id": "paraphrase", "_evidence_keys": ["text:one"]},
                {"ticker": "IOT", "item_id": "first_topic", "_evidence_keys": ["text:later"]}]
        _deduplicate_evidence(rows)
        self.assertEqual(len({row["stable_issue_id"] for row in rows}), 1)
        self.assertEqual(rows[1]["novelty_class"], "repeated_evidence_family")
        self.assertEqual(rows[2]["novelty_class"], "evidence_update_existing_issue")

    def test_aggregate_deduplicates_substantive_coverage_and_labels_recall(self) -> None:
        bundles = [evaluation_bundle("one"), evaluation_bundle("two")]
        original = copy.deepcopy(bundles)
        with patch("evaluate_phase5r_shadow_llm_incremental_value._packet_for_bundle", return_value=fake_packet()):
            result = aggregate(bundles, load_config(), snapshot_path=Path("/missing/snapshots"), outcome_path=Path("/missing/outcomes"))
        metrics = result["metrics"]
        self.assertEqual(metrics["incremental_supported_material_items"], 1)
        self.assertEqual(metrics["automatically_judged_events"], 1)
        self.assertEqual(metrics["duplicate_semantic_event_runs"], 1)
        self.assertEqual(metrics["distinct_issuers"], 1)
        self.assertEqual(metrics["packet_entity_issuers_not_substantive_coverage"], 2)
        self.assertIsNone(metrics["material_issue_recall"])
        self.assertEqual(metrics["estimated_incremental_model_reference_recall"], 1.0)
        self.assertFalse(result["decision"]["authority_review_evidence_met"])
        self.assertEqual(bundles, original)

    def test_replay_and_live_same_event_cannot_double_count_promotion_samples(self) -> None:
        bundles = [evaluation_bundle("one"), evaluation_bundle("two")]
        bundles[0]["evaluation_class"] = "replay"
        with patch("evaluate_phase5r_shadow_llm_incremental_value._packet_for_bundle", return_value=fake_packet()):
            result = aggregate(bundles, load_config(), snapshot_path=Path("/missing/snapshots"), outcome_path=Path("/missing/outcomes"))
        self.assertEqual(result["metrics"]["replay_packets"] + result["metrics"]["live_shadow_events"], 1)
        self.assertEqual(result["metrics"]["raw_automatically_judged_runs"], 2)

    def test_missing_sealed_packet_cannot_claim_baseline_incremental_value(self) -> None:
        with patch("evaluate_phase5r_shadow_llm_incremental_value._packet_for_bundle", return_value=None):
            result = aggregate([evaluation_bundle("one")], load_config(), snapshot_path=Path("/missing/snapshots"), outcome_path=Path("/missing/outcomes"))
        self.assertEqual(result["metrics"]["incremental_supported_material_items"], 0)
        self.assertFalse(result["metrics"]["baseline_reassessment_complete"])

    def test_later_fetch_or_later_period_is_not_official_confirmation(self) -> None:
        packet = fact_packet()
        claim = {**net_loss_claim(), "item_id": "net_loss", "run_id": "one", "completed_at": "2026-09-02T12:00:00-04:00", "stable_issue_id": "issue_one"}
        claim["deterministic_check"] = deterministic_claim_check(packet, claim)
        packet["fundamental_observations"][0]["fetched_at"] = "2026-09-04T12:00:00-04:00"
        self.assertEqual(_official_follow_up([claim], [packet])["resolved_claims"], 0)
        packet["fundamental_observations"][0]["field_provenance_json"] = {"net_margin_pct": {"components": [{"accession": "official-amendment", "filed": "2026-09-04"}]}}
        self.assertEqual(_official_follow_up([claim], [packet])["resolved_claims"], 1)
        packet["fundamental_observations"][0]["latest_frame"] = "CY2026Q3"
        self.assertEqual(_official_follow_up([claim], [packet])["resolved_claims"], 0)


if __name__ == "__main__":
    unittest.main()
