from __future__ import annotations

import copy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from _support import SCRIPT_DIR
import momentum_experiment as experiment
import momentum_experiment_review as review
import create_momentum_experiment_review as cli
import test_momentum_experiment as fixtures

CURRENT = datetime(2026, 10, 2, 12, tzinfo=experiment.ET)


def observations(tickers=("TEST", "OTHER"), *, version=None, selected=True):
    values = fixtures.fixture()
    values["inputs"]["implementation_sha256"] = "a" * 64
    if version:
        values["policy"]["version"] = version
    original = experiment.observe(**values)[0][0]
    result = []
    for ticker in tickers:
        row = copy.deepcopy(original)
        row["ticker"] = ticker
        row["observation_id"] = experiment.canonical_sha256({
            "version": row["experiment_version"], "session": row["signal_session"], "ticker": ticker})
        if not selected:
            row["cohorts"] = dict.fromkeys(row["cohorts"], False)
            row["disposition"] = "skipped_or_unverified"
        result.append(row)
    return result


def outcome(row, *, gap=False, correction=False, current=CURRENT):
    entry = date.fromisoformat(row["earliest_modeled_entry_session"])
    days = [entry.isoformat(), *experiment.sessions_after(entry, 4)]
    bars = [{"session_date": day, "open": 200 if gap else 103,
             "high": 205 if gap else 104, "low": 197 if gap else 97,
             "close": 201 if gap else 101, "volume": 100} for day in days]
    if correction:
        changed = copy.deepcopy(row["bars_at_observation"][-1])
        changed["volume"] += 1
        bars.insert(0, changed)
    result = experiment.evaluate(row, {row["ticker"]: bars}, current)
    result["evaluation_inputs"] = row["inputs"]
    return result


def chained(rows):
    result = []
    for raw in rows:
        row = copy.deepcopy(raw)
        row["previous_hash"] = result[-1]["record_hash"] if result else ""
        row["record_hash"] = experiment.canonical_sha256(row)
        result.append(row)
    return result


def payloads(rows, *, active_policy=None, current=CURRENT):
    records = chained(rows)
    policy = json.loads((SCRIPT_DIR.parents[1] / review.POLICY).read_text())
    frozen = active_policy or next(row["policy"] for row in records if row["kind"] == "observation")
    report = {"software_run": "passed", "status": "experimental", "generated_at": current.isoformat(),
              "run_attempt_id": "fixture", "policy_version": frozen["version"],
              "automatic_action_allowed": False, "ledger_sha256": "b" * 64,
              "market_session": "2026-10-01", "summary": experiment.summarize(records)}
    status = {"status": "experimental", "generated_at": current.isoformat(), "run_attempt_id": "fixture", "market_session": "2026-10-01"}
    return dict(policy=policy, frozen_policy=frozen, records=records, experiment_report=report,
                experiment_status=status, ledger_sha256="b" * 64, current=current, input_hashes={})


class MomentumExperimentReviewTests(unittest.TestCase):
    def test_one_whole_losing_cohort_opens_manual_review_without_promoting(self):
        rows = observations()
        result = review.build_review(**payloads([*rows, *(outcome(row) for row in rows)]))
        self.assertEqual(result["status"], "ready_for_owner_review")
        self.assertEqual(result["complete_cohorts"], 1)
        self.assertFalse(result["automatic_promotion"])
        self.assertFalse(result["changes_canonical_eligibility"])
        self.assertFalse(result["incremental_value_established"])
        cohort = result["cohorts"][0]
        comparison = cohort["comparison"]["cohorts"]["breakout_with_volume"]
        self.assertEqual(comparison["losing_common_paths_at_highest_cost"], 2)
        self.assertEqual(set(comparison["common_path_net_mean_pct_by_one_way_bps"]), {"10", "25", "50"})
        self.assertEqual(cohort["observation_refs"][0]["modeled_execution"]["breakout_with_volume"]["reason"], "stop_or_gap_loss")
        self.assertIn("not establish profitability", review.markdown(result))

    def test_missing_or_correction_outcome_does_not_complete_cohort(self):
        rows = observations()
        for second in (None, outcome(rows[1], correction=True)):
            with self.subTest(correction=second is not None):
                tail = [outcome(rows[0])] + ([second] if second else [])
                result = review.build_review(**payloads([*rows, *tail]))
                self.assertFalse(result["ready_for_owner_review"])
                self.assertEqual(result["complete_cohorts"], 0)
                self.assertEqual(len(result["cohorts"][0]["observation_refs"]), 2)
                self.assertFalse(result["cohorts"][0]["complete"])

    def test_no_selection_or_gap_skip_remains_visible_and_can_be_reviewed(self):
        for selected in (False, True):
            rows = observations(selected=selected)
            result = review.build_review(**payloads([*rows, *(outcome(row, gap=True) for row in rows)]))
            cohort = result["cohorts"][0]
            self.assertTrue(result["ready_for_owner_review"])
            self.assertEqual(len(cohort["observation_refs"]), 2)
            if selected:
                self.assertEqual(cohort["comparison"]["cohorts"]["breakout_with_volume"]["execution_status_counts"], {"expired_unfilled_or_gap_skipped": 2})
            else:
                self.assertEqual(cohort["selected_strategy_evidence_status"], "no_selected_breakout_with_volume_observations")
                self.assertEqual(cohort["comparison"]["cohorts"]["breakout_with_volume"]["selected"], 0)

    def test_old_complete_version_does_not_complete_active_version(self):
        old = observations(version="old-version")
        active = observations(version="active-version")
        result = review.build_review(**payloads([*old, *active, *(outcome(row) for row in old)], active_policy=active[0]["policy"]))
        self.assertFalse(result["ready_for_owner_review"])
        self.assertEqual(result["cohorts_by_version"], {"active-version": 1, "old-version": 1})
        self.assertTrue(next(row for row in result["cohorts"] if row["experiment_version"] == "old-version")["complete"])

    def test_v2_first_cohort_stays_reviewable_october_third_after_software_v3(self):
        from tactical_review import _last_sessions
        def captured(version, stamp):
            values = fixtures.fixture()
            values["policy"]["version"] = version
            values["current"] = datetime.fromisoformat(stamp)
            values["inputs"]["implementation_sha256"] = ("a" if "v2" in version else "c") * 64
            values["history"]["market_session"] = "2026-09-25"
            values["history"]["generated_at"] = stamp
            for bar, session in zip(values["history"]["tickers"]["TEST"]["bars"], _last_sessions(date(2026, 9, 25), 20)):
                bar["session_date"] = session
            values["market"][0]["market_session_date"] = "2026-09-25"
            values["market"][0]["data_timestamp"] = stamp
            values["decision"]["generated_at"] = stamp
            values["decision"]["market_gate"]["expected_market_session"] = "2026-09-25"
            return experiment.observe(**values)[0]
        old = captured("eod-breakout-v2-20260927", "2026-09-27T15:00:00-04:00")
        active = captured("eod-breakout-v3-20260928", "2026-09-28T15:00:00-04:00")
        current = datetime(2026, 10, 3, 12, tzinfo=experiment.ET)
        values = payloads([*old, *active, *(outcome(row, current=current) for row in old)],
                          active_policy=active[0]["policy"], current=current)
        values["experiment_report"]["market_session"] = "2026-10-02"
        values["experiment_status"]["market_session"] = "2026-10-02"
        result = review.build_review(**values)
        self.assertFalse(result["ready_for_owner_review"])
        self.assertEqual(result["complete_cohorts"], 0)
        self.assertTrue(result["historical_ready_for_owner_review"])
        self.assertEqual(result["historical_complete_cohorts"], 1)
        retained = result["earliest_retained_cohort"]
        self.assertEqual(retained["experiment_version"], "eod-breakout-v2-20260927")
        self.assertEqual(retained["earliest_complete_session"], "2026-10-02")
        self.assertEqual(retained["earliest_publication_at"], "2026-10-03T11:15:00-04:00")
        self.assertTrue(retained["complete"])
        self.assertIn("does not validate the active version", review.markdown(result))
        self.assertFalse(result["changes_canonical_eligibility"])
        self.assertFalse(result["incremental_value_established"])

    def test_late_addition_uses_separate_entry_window(self):
        rows = observations()
        rows[1]["recorded_at"] = "2026-09-24T13:30:00-04:00"
        rows[1]["first_observed_at"] = rows[1]["recorded_at"]
        rows[1]["earliest_modeled_entry_session"] = "2026-09-25"
        rows[1]["expires_at"] = experiment.regular_close("2026-09-25").isoformat()
        result = review.build_review(**payloads([*rows, outcome(rows[0])]))
        self.assertEqual(result["active_cohorts"], 2)
        self.assertEqual(result["complete_cohorts"], 1)
        self.assertTrue(result["ready_for_owner_review"])
        self.assertEqual({row["earliest_model_entry_session"] for row in result["cohorts"]}, {"2026-09-24", "2026-09-25"})

    def test_first_review_key_stays_stable_as_later_cohorts_complete(self):
        old = observations()
        later = observations(("LATER",))
        later[0]["recorded_at"] = "2026-09-24T13:30:00-04:00"
        later[0]["first_observed_at"] = later[0]["recorded_at"]
        later[0]["earliest_modeled_entry_session"] = "2026-09-25"
        original = [*old, *later, *(outcome(row) for row in old)]
        first = review.build_review(**payloads(original))
        result = review.build_review(**payloads([*original, outcome(later[0])]))
        self.assertEqual(first["review_key"], result["review_key"])

    def test_stale_success_or_status_market_mismatch_cannot_be_restamped(self):
        rows = observations()
        for defect in ("prior_day", "report_market", "status_market"):
            values = payloads([*rows, *(outcome(row) for row in rows)])
            if defect == "prior_day":
                values["current"] = datetime(2026, 10, 3, 10, tzinfo=experiment.ET)
            elif defect == "report_market":
                values["experiment_report"]["market_session"] = "2026-09-30"
            else:
                values["experiment_status"]["market_session"] = "2026-09-30"
            with self.subTest(defect=defect), self.assertRaisesRegex(review.ReviewError, "report_stale"):
                review.build_review(**values)

    def test_incomplete_or_nonfinite_recorded_model_costs_and_bars_cannot_complete(self):
        rows = observations()
        for defect in ("missing_model_costs", "missing_cost", "extra_cost", "nonfinite", "boolean", "missing_model", "unknown_model", "bad_bar", "bad_entry"):
            outcomes = [outcome(row) for row in rows]
            model = outcomes[0]["models"]["breakout_with_volume"]
            if defect == "missing_model_costs": model.pop("net_return_pct_by_one_way_bps")
            elif defect == "missing_cost": model["net_return_pct_by_one_way_bps"].pop("50")
            elif defect == "extra_cost": model["net_return_pct_by_one_way_bps"]["999"] = 0
            elif defect == "nonfinite": model["net_return_pct_by_one_way_bps"]["10"] = float("inf")
            elif defect == "boolean": model["net_return_pct_by_one_way_bps"]["10"] = True
            elif defect == "missing_model": outcomes[0]["models"].pop("breakout_with_volume")
            elif defect == "unknown_model": model["status"] = "unknown"
            elif defect == "bad_bar": outcomes[0]["forward_bars"][0]["high"] = -1
            else: model["entry"] = float("nan")
            values = payloads([*rows, *outcomes])
            with self.subTest(defect=defect), self.assertRaisesRegex(review.ReviewError, "outcome_evidence_invalid"):
                review.build_review(**values)

    def test_failed_mismatched_or_corrupt_experiment_never_makes_ready_packet(self):
        rows = observations()
        for defect in ("failed", "hash", "summary", "ledger", "future", "mixed_implementation", "wrong_outcome_implementation"):
            values = payloads([*rows, *(outcome(row) for row in rows)])
            if defect == "failed": values["experiment_status"]["status"] = "failed"
            elif defect == "hash": values["experiment_report"]["ledger_sha256"] = "c" * 64
            elif defect == "summary": values["experiment_report"]["summary"]["outcomes"] = 99
            elif defect == "ledger": values["records"][0]["ticker"] = "CHANGED"
            elif defect == "future": values["experiment_report"]["generated_at"] = "2027-01-01T00:00:00-05:00"
            else:
                raw = [*copy.deepcopy(rows), *(outcome(row) for row in rows)]
                target = raw[1]["inputs"] if defect == "mixed_implementation" else raw[-1]["evaluation_inputs"]
                target["implementation_sha256"] = "c" * 64
                values = payloads(raw)
            with self.subTest(defect=defect), self.assertRaises(review.ReviewError):
                review.build_review(**values)

    def test_minimum_review_policy_cannot_change_strategy_authority(self):
        policy = payloads(observations())["policy"]
        for field, value in (("minimum_complete_cohorts", 0), ("minimum_complete_cohorts", True),
                             ("required_holding_sessions", 1), ("automatic_promotion", True),
                             ("changes_canonical_eligibility", True), ("owner_review_required", False)):
            with self.subTest(field=field), self.assertRaises(review.ReviewError):
                review.validate_review_policy(policy | {field: value})

    def test_run_preserves_all_inputs_and_failed_cli_keeps_prior_report_historical(self):
        values = payloads(observations())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / experiment.OUTPUT / "ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("".join(json.dumps(row) + "\n" for row in values["records"]))
            values["experiment_report"]["ledger_sha256"] = hashlib.sha256(ledger.read_bytes()).hexdigest()
            for path, data in ((review.POLICY, values["policy"]), (experiment.POLICY, values["frozen_policy"]),
                               (experiment.OUTPUT / "report.json", values["experiment_report"]),
                               (experiment.OUTPUT / "status.json", values["experiment_status"])):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(json.dumps(data))
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            result = review.run(root, CURRENT)
            self.assertEqual(result["status"], "waiting_for_complete_cohort")
            self.assertTrue(all(path.read_bytes() == value for path, value in before.items()))
            status = json.loads((root / review.OUTPUT / "status.json").read_text())
            self.assertEqual(status["earliest_complete_session"], "2026-09-30")
            self.assertEqual(status["earliest_publication_at"], "2026-10-01T11:15:00-04:00")
            report_bytes = (root / review.OUTPUT / "report.json").read_bytes()
            (root / experiment.OUTPUT / "status.json").write_text('{"status":"failed"}')
            self.assertEqual(cli.main(["--root", str(root)]), 1)
            self.assertEqual((root / review.OUTPUT / "report.json").read_bytes(), report_bytes)
            failed = json.loads((root / review.OUTPUT / "status.json").read_text())
            self.assertFalse(failed["ready_for_owner_review"])
            self.assertTrue(failed["prior_report_is_historical"])
            before_conflict = (root / experiment.OUTPUT / "status.json").read_bytes()
            self.assertEqual(cli.main(["--root", str(root), "--output", str(root / experiment.OUTPUT)]), 2)
            self.assertEqual((root / experiment.OUTPUT / "status.json").read_bytes(), before_conflict)


if __name__ == "__main__":
    unittest.main()
