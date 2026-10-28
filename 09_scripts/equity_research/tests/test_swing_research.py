from __future__ import annotations

import copy
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR
import swing_research as swing


def policy():
    return json.loads((SCRIPT_DIR.parents[1] / swing.POLICY).read_text())


def bars(end="2026-09-22", count=75):
    day, dates = date.fromisoformat(end), []
    while len(dates) < count:
        if swing.is_us_market_session_date(day):
            dates.append(day.isoformat())
        day -= timedelta(days=1)
    return [{"session_date": session, "open": 99.0, "high": 101.0, "low": 98.0,
             "close": 100.0, "volume": 100.0} for session in reversed(dates)]


def breakout_bars():
    result = bars()
    result[-1].update(open=102.0, high=104.0, low=100.0, close=103.0, volume=300.0)
    return result


def current():
    return datetime(2026, 9, 23, 10, 0, tzinfo=swing.ET)


def fixture(root, series=None, observed=None):
    observed = observed or current()
    series = series or breakout_bars()
    session = series[-1]["session_date"]
    row = {"ticker": "TEST", "last_price": series[-1]["close"], "data_quality_label": "ok",
           "market_session_date": session, "data_timestamp": observed.isoformat()}
    path = root / swing.SNAPSHOT
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader(); writer.writerow(row)
    snapshot_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / swing.UNIVERSE).write_text("ticker\nTEST\n")
    holdings = root / swing.HOLDINGS
    holdings.parent.mkdir(parents=True, exist_ok=True); holdings.write_text("ticker,shares_optional\nTEST,1\n")
    bundle = {"schema_version": "equity_unadjusted_market_history_v1", "price_basis": "unadjusted",
              "data_source": "massive_stocks_basic_eod", "market_session": session,
              "generated_at": observed.isoformat(), "snapshot_sha256": snapshot_hash,
              "tickers": {"TEST": {"source_url": "https://api.massive.com/TEST", "bars": series}}}
    raw = json.dumps(bundle).encode(); digest = hashlib.sha256(raw).hexdigest()
    history = root / swing.market_backup.REL / "history" / (digest + ".json")
    history.parent.mkdir(parents=True, exist_ok=True); history.write_bytes(raw)
    pointer = root / swing.market_backup.CURRENT
    pointer.write_text(json.dumps({"history_path": "history/" + digest + ".json", "history_sha256": digest}))
    config = root / swing.POLICY
    config.parent.mkdir(parents=True, exist_ok=True); config.write_text(json.dumps(policy()))
    return bundle


class SwingResearchTests(unittest.TestCase):
    def test_breakout_is_separate_research_and_target_is_hypothetical(self):
        f = swing._features(breakout_bars())
        self.assertTrue(f["selected"]["breakout"])
        self.assertFalse(f["selected"]["trend_continuation"])
        self.assertGreater(f["close"], f["prior_19_session_high"])

    def test_no_opportunity_is_an_explicit_unselected_observation(self):
        self.assertFalse(any(swing._features(bars())["selected"].values()))

    def test_daily_pullback_definition_is_not_a_live_rebound(self):
        series = bars()
        for row in series[-40:]:
            row.update(open=109.0, high=111.0, low=108.0, close=110.0)
        series[-2].update(open=109.0, high=109.0, low=107.0, close=108.0)
        series[-1].update(open=109.5, high=112.0, low=109.0, close=111.5)
        f = swing._features(series)
        self.assertTrue(f["selected"]["pullback_reclaim"])

    def test_daily_trend_continuation_below_old_resistance(self):
        series = bars()
        for row in series[-40:]:
            row.update(open=109.0, high=112.0, low=108.0, close=110.0)
        series[-12]["high"] = 120.0
        series[-2]["close"] = 110.5
        series[-1].update(open=111.5, high=114.0, low=111.0, close=113.0)
        self.assertTrue(swing._features(series)["selected"]["trend_continuation"])

    def test_first_future_open_skips_elapsed_open(self):
        self.assertEqual(swing._next_open(current()), "2026-09-24")
        self.assertEqual(swing._next_open(current().replace(hour=8)), "2026-09-23")
        self.assertEqual(swing._next_open(current().replace(hour=9, minute=30)), "2026-09-24")

    def test_policy_rejects_capital_authority_and_horizon_retuning(self):
        for key, value in (("capital_authority", True), ("actionable_quantity", 1), ("holding_sessions", [14]),
                           ("maximum_gap_r", 1), ("one_way_cost_bps", [0])):
            p = policy(); p[key] = value
            with self.subTest(key=key), self.assertRaises(swing.SwingResearchError):
                swing._validate_policy(p)

    def test_gap_over_maximum_and_below_trigger_are_not_filled(self):
        f = swing._features(breakout_bars())
        for op in (102.0, 106.0):
            window = [{"session_date": "2026-09-24", "open": op, "high": 120.0, "low": 100.0, "close": 115.0}]
            self.assertEqual(swing._model(window, f, policy())["status"], "skipped_unfilled_or_gap")

    def test_gap_stop_uses_worse_open_and_costs_each_side(self):
        f = swing._features(breakout_bars())
        window = [{"session_date": "2026-09-24", "open": 103.0, "high": 104.0, "low": 100.0, "close": 102.0},
                  {"session_date": "2026-09-25", "open": 90.0, "high": 92.0, "low": 88.0, "close": 91.0}]
        result = swing._model(window, f, policy())
        self.assertEqual(result["exit"], 90.0)
        self.assertEqual(result["reason"], "stop_or_gap_loss")
        self.assertFalse(result["actual_fill"])
        self.assertLess(result["raw_price_cost_sensitivity_pct_by_one_way_bps"]["50"], result["raw_price_cost_sensitivity_pct_by_one_way_bps"]["10"])

    def test_same_bar_target_stop_is_conservative_and_disclosed(self):
        f = swing._features(breakout_bars())
        result = swing._model([{"session_date": "2026-09-24", "open": 103.0, "high": 120.0, "low": 95.0, "close": 115.0}], f, policy())
        self.assertEqual(result["exit"], 98.0)
        self.assertTrue(result["same_bar_sequence_ambiguous"])
        self.assertEqual(result["reason"], "stop_or_gap_loss")

    def test_time_exit_has_no_automatic_conversion_to_growth(self):
        f = swing._features(breakout_bars())
        result = swing._model([{"session_date": "2026-09-24", "open": 103.0, "high": 104.0, "low": 100.0, "close": 102.0}], f, policy())
        self.assertEqual(result["reason"], "time_exit")
        self.assertEqual(result["exit"], 102.0)

    def test_read_only_build_does_not_write_and_has_zero_capital(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                result = swing.build(root, current())
            self.assertEqual(result["status"], "experimental_current")
            self.assertEqual(result["candidates"][0]["observation_status"], "not_captured_read_only")
            self.assertEqual(result["candidates"][0]["profit_reference_kind"], "hypothetical_2R_not_observed_resistance")
            self.assertEqual(result["actionable_quantity"], 0)
            self.assertFalse(result["capital_authority"])
            self.assertFalse((root / swing.OUTPUT).exists())
            self.assertEqual(result["baseline_status"], "unverified")

    def test_current_baseline_flags_are_verified_before_freezing(self):
        bindings = {"market_session": "2026-09-22", "snapshot_sha256": "a" * 64}
        capital = {"generated_at": current().isoformat(), "market_data_timestamp": "2026-09-22",
                   "content_sha256": "b" * 64, "source_bindings": {},
                   "decisions": [{"ticker": "TEST", "decision": "ACTIONABLE_BUY", "shares": 1}]}
        baseline = {"capital_decision": capital, "market_gate": {"expected_market_session": "2026-09-22"},
                    "tactical_review": {"as_of": current().isoformat(), "market_session": "2026-09-22", "drafts": [
                        {"ticker": "TEST", "eligible": False, "quantity": 0,
                         "price_evidence": {"validated": True, "snapshot_sha256": "a" * 64, "history_session": "2026-09-22"}}]}}
        with patch("capital_decision.validate") as validate:
            result = swing._baseline(Path("/fixture"), baseline, bindings, current())
        validate.assert_called_once_with(capital, current=current(), root=Path("/fixture"))
        self.assertTrue(result["canonical"]["TEST"])
        self.assertFalse(result["existing_tactical"]["TEST"])
        with patch("capital_decision.validate", side_effect=ValueError("invalid_current_contract")):
            result = swing._baseline(Path("/fixture"), baseline, bindings, current())
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["canonical"], {})

    def test_unverified_baseline_is_not_counted_ineligible(self):
        observation = {"kind": "observation", "observation_id": "one", "source_session": "2026-09-22",
                       "features": swing._features(breakout_bars()),
                       "baseline": {"canonical": None, "existing_tactical": None}}
        report = swing._performance([observation])
        canonical = next(row for row in report["common_path_comparisons"] if row["cohort"] == "canonical_actionable_at_capture" and row["horizon_sessions"] == 5)
        self.assertEqual(canonical["selected_observations"], 0)
        self.assertEqual(canonical["baseline_unknown_observations"], 1)
        self.assertIsNone(canonical["mean_common_path_net_pct_by_one_way_bps"]["25"])

    def test_afterhours_action_state_is_not_counted_as_canonical_rejection(self):
        clock = current().replace(hour=21)
        bindings = {"market_session": "2026-09-23", "snapshot_sha256": "a" * 64}
        capital = {"generated_at": clock.isoformat(), "market_data_timestamp": "2026-09-23",
                   "content_sha256": "b" * 64, "source_bindings": {},
                   "decisions": [{"ticker": "TEST", "decision": "BLOCKED", "shares": 0,
                                  "blockers": ["maintained_plan_expired"]}]}
        with patch("capital_decision.validate"):
            result = swing._baseline(Path("/fixture"), {"capital_decision": capital,
                                                       "market_gate": {"expected_market_session": "2026-09-23"}}, bindings, clock)
        self.assertEqual(result["status"], "verified_current")
        self.assertEqual(result["comparability"], "unverified_outside_regular_session")
        self.assertFalse(result["observed_canonical"]["TEST"])
        self.assertNotIn("TEST", result["canonical"])
        self.assertEqual(result["rejection_codes"]["TEST"], ["maintained_plan_expired"])

    def test_capture_first_clock_and_original_unselected_are_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root, bars())
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                first = swing.build(root, current(), capture=True)
                ledger = root / swing.OUTPUT / "ledger.jsonl"; original = ledger.read_bytes()
                second = swing.build(root, current() + timedelta(minutes=5), capture=True)
            self.assertEqual(first["status"], "experimental_current")
            self.assertEqual(first["candidates"], [])
            self.assertEqual(first["coverage"]["unselected"], 1)
            self.assertEqual(ledger.read_bytes(), original)
            self.assertEqual(second["performance"]["observations"], 1)
            self.assertEqual(len(list((root / swing.OUTPUT / "attempts").glob("*.json"))), 1)

    def test_later_same_session_snapshot_does_not_recapture_early_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                swing.build(root, current(), capture=True)
            ledger = root / swing.OUTPUT / "ledger.jsonl"; before = ledger.read_bytes()
            bundle = fixture(root, observed=current() + timedelta(minutes=5))
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                result = swing.build(root, current() + timedelta(minutes=5), capture=True)
            self.assertEqual(result["blockers"], ["swing_same_session_inputs_changed"])
            self.assertEqual(result["candidates"], [])
            self.assertEqual(ledger.read_bytes(), before)

    def test_stale_close_has_no_levels_and_failed_attempt_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                result = swing.build(root, current() + timedelta(days=1), capture=True)
            self.assertEqual(result["blockers"], ["swing_latest_completed_close_missing"])
            self.assertEqual(result["candidates"], [])
            self.assertFalse((root / swing.OUTPUT / "ledger.jsonl").exists())
            attempt = json.loads(next((root / swing.OUTPUT / "attempts").glob("*.json")).read_text())
            self.assertEqual(attempt["status"], "failed")
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                swing.build(root, current() + timedelta(days=1, minutes=5), capture=True)
            self.assertEqual(len(list((root / swing.OUTPUT / "attempts").glob("*.json"))), 1)

    def test_source_failure_and_partial_scope_do_not_show_prices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fixture(root)
            with patch.object(swing.market_backup, "load_baseline", side_effect=swing.market_backup.BackupError("backup_baseline_scope_or_basis_invalid")):
                result = swing.build(root, current())
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["blockers"], ["backup_baseline_scope_or_basis_invalid"])

    def test_new_held_symbol_outside_snapshot_blocks_all_current_setups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            (root / swing.HOLDINGS).write_text("ticker,shares_optional\nTEST,1\nNEW,1\n")
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                result = swing.build(root, current())
            self.assertEqual(result["blockers"], ["swing_configured_and_held_scope_incomplete"])
            self.assertEqual(result["candidates"], [])

    def test_corrupt_ledger_is_preserved_and_not_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                swing.build(root, current(), capture=True)
                ledger = root / swing.OUTPUT / "ledger.jsonl"
                payload = json.loads(ledger.read_text()); payload["ticker"] = "CHANGED"
                ledger.write_text(json.dumps(payload) + "\n"); before = ledger.read_bytes()
                result = swing.build(root, current(), capture=True)
            self.assertEqual(result["blockers"], ["swing_ledger_integrity_failure"])
            self.assertEqual(ledger.read_bytes(), before)

    def test_implementation_change_fails_closed_under_same_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                swing.build(root, current(), capture=True)
                with patch.object(swing, "_implementation", return_value=("a" * 64, {})):
                    result = swing.build(root, current(), capture=True)
            self.assertEqual(result["blockers"], ["swing_version_identity_changed"])

    def test_projection_source_change_or_staleness_suppresses_cards_without_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                view = swing.build(root, current())
                result = swing.revalidate_projection(root, view, current() + timedelta(days=1))
                self.assertEqual(result["candidates"], [])
                (root / swing.POLICY).write_text(json.dumps(policy(), indent=2))
                result = swing.revalidate_projection(root, view, current())
            self.assertEqual(result["blockers"], ["swing_projection_sources_changed"])
            self.assertFalse((root / swing.OUTPUT).exists())

    def test_tampered_level_or_quantity_is_recomputed_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                view = swing.build(root, current())
                for field in ("entry_trigger", "max_entry", "invalidation", "actionable_quantity"):
                    changed = copy.deepcopy(view); changed["candidates"][0][field] += 1
                    result = swing.revalidate_projection(root, changed, current())
                    self.assertEqual(result["candidates"], [])
                    self.assertEqual(result["blockers"], ["swing_projection_candidate_unverified"])

    def test_original_capture_source_bytes_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                view = swing.build(root, current(), capture=True)
                ledger = root / swing.OUTPUT / "ledger.jsonl"; before = ledger.read_bytes()
                row = json.loads(ledger.read_text())
                source = root / swing.OUTPUT / "input_history" / row["inputs"]["snapshot_sha256"]
                source.write_bytes(b"corrupt original")
                result = swing.revalidate_projection(root, view, current())
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["blockers"], ["swing_retained_input_changed"])
            self.assertEqual(ledger.read_bytes(), before)

    def test_corrupt_attempt_history_is_advisory_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                swing.build(root, current(), capture=True)
                attempt = next((root / swing.OUTPUT / "attempts").glob("*.json"))
                attempt.write_bytes(b"corrupt original attempt")
                result = swing.build(root, current() + timedelta(minutes=5), capture=True)
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["blockers"], ["swing_attempt_history_unavailable"])
            self.assertEqual(attempt.read_bytes(), b"corrupt original attempt")
            self.assertEqual(len(list((root / swing.OUTPUT / "attempt_history_failures").glob("*.json"))), 1)

    def test_unwritable_attempt_store_cannot_fail_canonical_composition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root)
            with (patch.object(swing.market_backup, "load_baseline", return_value=bundle),
                  patch.object(swing, "_record_attempt", side_effect=OSError("unwritable store"))):
                result = swing.build(root, current(), capture=True)
            self.assertEqual(result["blockers"], ["swing_attempt_history_unavailable"])
            self.assertEqual(result["actionable_quantity"], 0)

    def test_read_time_at_entry_open_expires_setup_no_renewal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = fixture(root, observed=current().replace(hour=8))
            with patch.object(swing.market_backup, "load_baseline", return_value=bundle):
                view = swing.build(root, current().replace(hour=8))
                result = swing.revalidate_projection(root, view, current())
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["expired_candidates_suppressed"], len(view["candidates"]))

    def test_forward_outcomes_wait_for_named_horizon(self):
        entry = "2026-09-24"
        original = breakout_bars()
        observation = {"observation_id": "x", "ticker": "TEST", "entry_session": entry,
                       "bars_at_observation": original[-51:], "features": swing._features(original)}
        dates = [entry, *swing._sessions_after(date.fromisoformat(entry), 13)]
        forward = [{"session_date": day, "open": 103.0, "high": 104.0, "low": 100.0, "close": 103.0} for day in dates]
        fifth_close = swing.regular_close(dates[4])
        result = swing._outcome(observation, original + forward[:5], 5, policy(), fifth_close)
        self.assertEqual(result["status"], "unadjusted_price_paths_pending_corporate_action_review")
        self.assertIsNone(swing._outcome(observation, original + forward[:5], 14, policy(), fifth_close))
        result = swing._outcome(observation, original + forward, 14, policy(), swing.regular_close(dates[-1]))
        self.assertEqual(result["horizon_sessions"], 14)
        self.assertEqual(result["models"]["breakout"]["reason"], "time_exit")

    def test_published_outcome_binds_exact_retained_forward_source_and_calculation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original = breakout_bars(); first = fixture(root, original)
            with patch.object(swing.market_backup, "load_baseline", return_value=first):
                swing.build(root, current(), capture=True)
            dates = ["2026-09-23", *swing._sessions_after(date(2026, 9, 23), 5)]
            future = [{"session_date": day, "open": 103.0, "high": 104.0, "low": 100.0, "close": 103.0, "volume": 100.0} for day in dates]
            clock = swing.regular_close(dates[-1]) + timedelta(minutes=30)
            second = fixture(root, original + future, observed=clock)
            with patch.object(swing.market_backup, "load_baseline", return_value=second):
                view = swing.build(root, clock, capture=True)
                self.assertEqual(view["status"], "experimental_current")
                rows = swing._read_ledger(root / swing.OUTPUT / "ledger.jsonl", clock)
                outcome = next(row for row in rows if row["kind"] == "outcome")
                self.assertEqual(outcome["inputs"]["history_sha256"], view["source_bindings"]["history_sha256"])
                swing._verify_retained_inputs(root / swing.OUTPUT, rows)
                outcome["models"]["breakout"]["exit"] += 1
                with self.assertRaisesRegex(swing.SwingResearchError, "swing_retained_outcome_calculation_unverified"):
                    swing._verify_retained_inputs(root / swing.OUTPUT, rows)

    def test_missing_and_retired_forward_bars_do_not_become_flat_returns(self):
        observation = {"observation_id": "x", "ticker": "TEST", "entry_session": "2026-09-24",
                       "bars_at_observation": breakout_bars(), "features": swing._features(breakout_bars())}
        self.assertIsNone(swing._outcome(observation, breakout_bars(), 5, policy(), datetime(2026, 10, 20, 17, tzinfo=swing.ET)))

    def test_unadjusted_forward_split_preserves_raw_loss_without_economic_performance_claim(self):
        original = breakout_bars(); entry = "2026-09-24"
        observation = {"kind": "observation", "observation_id": "x", "ticker": "TEST", "entry_session": entry,
                       "source_session": "2026-09-22", "bars_at_observation": copy.deepcopy(original),
                       "features": swing._features(original), "baseline": {"canonical": None, "existing_tactical": None}}
        dates = [entry, *swing._sessions_after(date.fromisoformat(entry), 4)]
        forward = [{"session_date": dates[0], "open": 103.0, "high": 104.0, "low": 100.0, "close": 103.0}]
        forward += [{"session_date": day, "open": 51.5, "high": 52.5, "low": 50.0, "close": 51.5} for day in dates[1:]]
        result = swing._outcome(observation, original + forward, 5, policy(), swing.regular_close(dates[-1]))
        self.assertTrue(result["corporate_action_review_required"])
        self.assertFalse(result["performance_eligible"])
        self.assertLess(result["models"]["breakout"]["raw_price_cost_sensitivity_pct_by_one_way_bps"]["25"], -40)
        report = swing._performance([observation, result])
        group = next(row for row in report["groups"] if row["setup"] == "breakout" and row["horizon_sessions"] == 5)
        self.assertIsNone(group["mean_modeled_net_pct_by_one_way_bps"]["25"])
        self.assertEqual(group["performance_eligible_entries"], 0)
        self.assertLess(group["raw_unadjusted_price_cost_sensitivity_mean_pct_by_one_way_bps"]["25"], -40)

    def test_original_bar_correction_is_not_a_successful_replacement(self):
        original = breakout_bars(); entry = "2026-09-24"
        observation = {"observation_id": "x", "ticker": "TEST", "entry_session": entry,
                       "bars_at_observation": copy.deepcopy(original), "features": swing._features(original)}
        dates = [entry, *swing._sessions_after(date.fromisoformat(entry), 4)]
        forward = [{"session_date": day, "open": 103.0, "high": 104.0, "low": 100.0, "close": 103.0} for day in dates]
        original[-1]["volume"] += 1
        result = swing._outcome(observation, original + forward, 5, policy(), swing.regular_close(dates[-1]))
        self.assertEqual(result["status"], "correction_review_required")
        self.assertNotIn("models", result)


if __name__ == "__main__":
    unittest.main()
