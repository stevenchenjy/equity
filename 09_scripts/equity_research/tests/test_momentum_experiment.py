from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

from _support import SCRIPT_DIR
import momentum_experiment as m
import run_daily_refresh as refresh
from tactical_review import _last_sessions, HISTORY_SCHEMA

ET = ZoneInfo("America/New_York")


def fixture():
    current = datetime(2026, 9, 23, 13, 30, tzinfo=ET)
    bars = [{"session_date": day, "open": 99, "high": 101, "low": 98, "close": 100, "volume": 100}
            for day in _last_sessions(current.date().replace(day=22), 20)]
    bars[-1].update(open=101, high=104, low=100, close=103, volume=500)
    policy = json.loads((SCRIPT_DIR.parents[1] / m.POLICY).read_text())
    history = {"schema_version": HISTORY_SCHEMA, "validated": True, "market_session": "2026-09-22",
        "snapshot_sha256": "a" * 64, "generated_at": current.isoformat(), "data_source": "public_EOD",
        "tickers": {"TEST": {"bars": bars, "source_url": "https://example.test/TEST"}}}
    return {"policy": policy, "history": history, "current": current,
        "decision": {"generated_at": current.isoformat(), "market_gate": {"expected_market_session": "2026-09-22"}},
        "market": [{"ticker": "TEST", "last_price": 103, "market_session_date": "2026-09-22", "data_quality_label": "ok", "data_timestamp": current.isoformat()}],
        "news": {"events": []}, "inputs": {"market_sha256": "a" * 64}}


def write_fixture(root, values):
    """Bind real fixture bytes, so isolated frozen execution sees the same inputs."""
    (root / m.SNAPSHOT).parent.mkdir(parents=True, exist_ok=True)
    with (root / m.SNAPSHOT).open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(values['market'][0]))
        writer.writeheader()
        writer.writerows(values['market'])
    values['history']['snapshot_sha256'] = hashlib.sha256((root / m.SNAPSHOT).read_bytes()).hexdigest()
    for path, payload in ((m.POLICY, values['policy']), (m.HISTORY, values['history']),
                          (m.DECISION, values['decision']), (m.NEWS, values['news'])):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(json.dumps(payload))
    registry = Path('01_policies/momentum_implementation_archives.json')
    (root / registry).write_bytes((SCRIPT_DIR.parents[1] / registry).read_bytes())


class MomentumExperimentTests(unittest.TestCase):
    def test_experiment_failure_is_advisory_not_a_delivery_or_risk_block(self):
        writes = []
        def step(name, script, allowed, **kwargs):
            return {"name": name, "script": script, "allowed_to_fail": allowed,
                    "exit_code": 1 if name == "momentum_experiment" else 0}
        with (patch.object(refresh, "load_active_state"), patch.object(refresh, "load_inhibit"),
              patch("workflow_evaluation.record_refresh"), patch.object(refresh, "log_daily_run"),
              patch.object(refresh, "run_step", side_effect=step),
              patch.object(refresh, "atomic_write_json", side_effect=lambda p, v: writes.append(copy.deepcopy(v)))):
            self.assertEqual(refresh.run_refresh(no_lock=True, market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE), 0)
        self.assertEqual(writes[-1]["advisory_failures"], ["momentum_experiment"])
        self.assertEqual(writes[-1]["hard_failures"], [])
        self.assertEqual(writes[-1]["soft_failures"], [])

    def test_above_high_setup_is_experimental_and_uses_prior_volume(self):
        values = fixture()
        before = copy.deepcopy(values)
        rows, _ = m.observe(**values)
        row = rows[0]
        self.assertTrue(row["cohorts"]["breakout_with_volume"])
        self.assertEqual(row["features"]["daily_volume_over_prior_19_mean"], 5)
        self.assertGreater(row["features"]["entry_reference"], row["features"]["prior_19_session_high"])
        self.assertEqual(row["features"]["profit_reference_kind"], "hypothetical_R_multiple_not_observed_target")
        self.assertFalse(row["actionable"])
        self.assertEqual(row["quantity"], 0)
        self.assertEqual(values, before)

    def test_delayed_observation_never_fills_elapsed_open(self):
        values = fixture()
        row = m.observe(**values)[0][0]
        self.assertEqual(row["earliest_modeled_entry_session"], "2026-09-24")
        self.assertEqual(row["expires_at"], "2026-09-24T16:00:00-04:00")

    def test_first_future_open_handles_premarket_and_exact_open(self):
        self.assertEqual(m.next_open_session(datetime(2026, 9, 23, 8, tzinfo=ET)), "2026-09-23")
        self.assertEqual(m.next_open_session(datetime(2026, 9, 23, 9, 30, tzinfo=ET)), "2026-09-24")
        self.assertEqual(m.next_open_session(datetime(2026, 9, 26, 8, tzinfo=ET)), "2026-09-28")

    def test_invalid_future_stale_and_hash_mismatched_data(self):
        for mutation in ("future", "stale", "history_time", "decision_time"):
            values = fixture()
            if mutation == "future":
                values["history"]["market_session"] = "2026-09-24"
            elif mutation == "stale":
                values["history"]["market_session"] = "2026-09-21"
            elif mutation == "history_time":
                values["history"]["generated_at"] = "2026-09-24T11:30:00-04:00"
            else:
                values["decision"]["generated_at"] = "2026-09-22T13:30:00-04:00"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                m.observe(**values)
        values = fixture()
        values["inputs"]["market_sha256"] = "b" * 64
        row = m.observe(**values)[0][0]
        self.assertFalse(row["cohorts"]["breakout_only"])
        self.assertIn("price_history_missing_or_unbound", row["coverage_errors"])

    def test_missing_float_and_catalyst_never_invented(self):
        values = fixture()
        values["news"]["events"] = [{"ticker": "TEST", "published_at": "2026-09-22T09:00:00-04:00", "first_seen_at": "2026-09-24T09:00:00-04:00"}]
        row = m.observe(**values)[0][0]
        self.assertEqual(row["official_announcements"], [])
        self.assertEqual(row["catalyst_status"], "unverified")
        self.assertEqual(row["features"]["float_status"], "unverified")

    def forward(self, row):
        start = datetime.fromisoformat(row["expires_at"]).date()
        days = [start.isoformat(), *m.sessions_after(start, 4)]
        return [{"session_date": day, "open": 104, "high": 106, "low": 102, "close": 105, "volume": 100} for day in days]

    def test_costs_and_ambiguous_stop_target_are_adverse(self):
        values = fixture()
        row = m.observe(**values)[0][0]
        bars = self.forward(row)
        bars[0].update(high=120, low=90)
        outcome = m.evaluate(row, {"TEST": bars}, datetime(2026, 10, 1, 18, tzinfo=ET))
        model = outcome["models"]["breakout_with_volume"]
        self.assertEqual(model["reason"], "stop_or_gap_loss")
        self.assertEqual(model["exit"], 98)
        self.assertLess(model["net_return_pct_by_one_way_bps"]["50"], model["net_return_pct_by_one_way_bps"]["10"])
        bars[1].update(open=90, low=89, high=95, close=93)
        bars[0].update(high=106, low=102)
        model = m.evaluate(row, {"TEST": bars}, datetime(2026, 10, 1, 18, tzinfo=ET))["models"]["breakout_only"]
        self.assertEqual(model["exit"], 90)

    def test_gaps_expire_missing_stays_pending_and_missed_paths_recorded(self):
        values = fixture()
        row = m.observe(**values)[0][0]
        bars = self.forward(row)
        current = datetime(2026, 10, 1, 18, tzinfo=ET)
        self.assertIsNone(m.evaluate(row, {"TEST": bars[:-1]}, current))
        self.assertIsNone(m.evaluate(row, {}, current))
        bars[0]["open"] = 110
        outcome = m.evaluate(row, {"TEST": bars}, current)
        self.assertEqual(outcome["models"]["breakout_only"]["status"], "expired_unfilled_or_gap_skipped")
        bars[0]["open"] = 100
        row["cohorts"] = dict.fromkeys(row["cohorts"], False)
        outcome = m.evaluate(row, {"TEST": bars}, current)
        self.assertTrue(outcome["missed_positive_path"])

    def test_corrections_do_not_become_silent_winners(self):
        row = m.observe(**fixture())[0][0]
        bars = self.forward(row)
        corrected = copy.deepcopy(row["bars_at_observation"][-1])
        corrected["close"] += 1
        outcome = m.evaluate(row, {"TEST": [corrected, *bars]}, datetime(2026, 10, 1, 18, tzinfo=ET))
        self.assertEqual(outcome["status"], "corporate_action_or_correction_review_required")
        self.assertNotIn("models", outcome)

    def test_common_path_comparison_avoids_unfair_baseline_fills_and_version_pooling(self):
        rows = []
        for version, costs in (("first", [10, 25]), ("second", [20, 50])):
            values = fixture()
            values["policy"].update(version=version, one_way_cost_bps=costs)
            values["decision"]["eligible_new_position_review_candidates"] = ["TEST"]
            values["decision"]["tactical_review"] = {"drafts": [{"ticker": "TEST", "eligible": True}]}
            row = m.observe(**values)[0][0]
            outcome = m.evaluate(row, {"TEST": self.forward(row)}, datetime(2026, 10, 1, 18, tzinfo=ET))
            self.assertEqual(outcome["models"]["existing_tactical"]["status"], "unmodeled_intraday_entry_required")
            rows.extend([row, outcome])
        summary = m.summarize(rows)
        for version, costs in (("first", {"10", "25"}), ("second", {"20", "50"})):
            cohorts = summary["comparison_by_version"][version]["cohorts"]
            baseline = cohorts["existing_tactical"]["common_path_net_mean_pct_by_one_way_bps"]
            experimental = cohorts["breakout_with_volume"]["common_path_net_mean_pct_by_one_way_bps"]
            self.assertEqual(baseline, experimental)
            self.assertEqual(set(baseline), costs)
        self.assertFalse(summary["incremental_value_established"])

    def test_failed_run_history_survives_later_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for day in (23, 24):
                with self.assertRaises(Exception):
                    m.run(root, datetime(2026, 9, day, 13, 30, tzinfo=ET))
            records = m.read_jsonl(root / m.OUTPUT / "run_attempts.jsonl")
            self.assertEqual(sum(r["state"] == "failed" for r in records), 2)
            self.assertEqual(sum(r["state"] == "started" for r in records), 2)
            self.assertTrue(all("reason_code" in r for r in records))

    def test_hash_chain_tamper_and_same_version_retune_rejected(self):
        row = m.observe(**fixture())[0][0]
        with tempfile.TemporaryDirectory() as directory:
            path, records = Path(directory) / "ledger.jsonl", []
            m.append_chained(path, records, row)
            self.assertEqual(m.validate_chain(records)[row["experiment_version"]], row["policy_sha256"])
            records[0]["quantity"] = 1
            with self.assertRaises(ValueError):
                m.validate_chain(records)
            records = m.read_jsonl(path)
            changed = copy.deepcopy(row)
            changed["observation_id"] = "new-day"
            changed["policy"]["relative_volume_min"] = 1
            changed["policy_sha256"] = m.canonical_sha256(changed["policy"])
            m.append_chained(path, records, changed)
            with self.assertRaisesRegex(ValueError, "without_new_version"):
                m.validate_chain(records)

    def test_policy_never_allows_canonical_authority(self):
        for key in ("changes_canonical_eligibility", "automatic_action_allowed"):
            p = fixture()["policy"]
            p[key] = True
            with self.assertRaises(ValueError):
                m.validate_policy(p)

    def test_replay_is_idempotent_and_never_overwrites_first_observation(self):
        values = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root, values)
            with patch.object(m, "sha256_file", return_value="a" * 64):
                report = m.run(root, values["current"])
                ledger = root / m.OUTPUT / "ledger.jsonl"
                original = ledger.read_bytes()
                revised = copy.deepcopy(values["decision"])
                revised["eligible_new_position_review_candidates"] = ["TEST"]
                (root / m.DECISION).write_text(json.dumps(revised))
                replay = m.run(root, values["current"].replace(hour=14))
                self.assertEqual(ledger.read_bytes(), original)
                self.assertEqual(replay["current_observations"], report["current_observations"])
                self.assertFalse(replay["current_observations"][0]["baseline_canonical_eligible"])
                self.assertEqual(report["summary"]["observations"], 1)
                self.assertEqual(report["summary"]["outcomes"], 0)
                self.assertFalse(report["summary"]["incremental_value_established"])
                # Live helper edits must not change the pinned experiment's identity.
                with patch.object(m, "sha256_file", return_value="b" * 64):
                    continued = m.run(root, values["current"].replace(hour=15))
                    self.assertEqual(continued['current_observations'], report['current_observations'])
                self.assertEqual(ledger.read_bytes(), original)
