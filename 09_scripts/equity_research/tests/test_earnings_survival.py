from __future__ import annotations
import copy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR
import earnings_survival as study
import swing_research as old


def clock(value):
    return study._aware(value)


def base_bars():
    day, days = date(2026, 9, 22), []
    while len(days) < 51:
        if study.is_us_market_session_date(day): days.append(day.isoformat())
        day -= timedelta(days=1)
    return [{"session_date": day, "open": 80 + index * .4, "high": 85 + index * .4,
             "low": 79 + index * .4, "close": 80 + index * .4, "volume": 100.}
            for index, day in enumerate(reversed(days))]


def after_bars(*, breach=False):
    result = base_bars()
    result += [{"session_date": "2026-09-23", "open": 100., "high": 103., "low": 99., "close": 101., "volume": 100.},
               {"session_date": "2026-09-24", "open": 101., "high": 104., "low": 99., "close": 102., "volume": 100.},
               {"session_date": "2026-09-25", "open": 104., "high": 111., "low": 90. if breach else 103., "close": 110., "volume": 300.}]
    return result


def event():
    return {"event_id": "event-test", "ticker": "TEST", "fiscal_period_label": "Jun/2026", "event_date": "2026-09-24",
            "research_deadline_at": "2026-09-24T16:00:00-04:00", "first_detected_at": "2026-09-22T16:20:00-04:00",
            "timing": "pre_event", "status": "detected", "blockers": [], "sources": []}


def dataset(bars):
    series = {"TEST": {"bars": bars, "common_stock": True, "price_basis": "unadjusted", "canonical": True}}
    for ticker in ["SPY", "QQQM"]:
        series[ticker] = {"bars": copy.deepcopy(bars), "common_stock": False, "price_basis": "unadjusted", "canonical": True}
    return {"dataset": {"market_session": bars[-1]["session_date"], "series": series},
            "features": {ticker: old._features(item["bars"]) for ticker, item in series.items()},
            "bindings": {"source_hashes": {}, "implementation_sha256": "a" * 64, "dataset_sha256": "b" * 64}, "blockers": []}


def setup(root):
    repo = SCRIPT_DIR.parents[1]
    for path in [study.POLICY, Path("01_policies/swing_runtime_v3.json")]:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes((repo / path).read_bytes())
    manifest = json.loads((repo / "01_policies/official_news_sources.json").read_text())
    manifest["sources"] = [{"source_id": "test_ir", "ticker": "TEST", "url": "https://ir.test.com/rss.xml",
                            "format": "rss_atom", "allowed_hosts": ["ir.test.com"], "required": True}]
    (root / "01_policies/official_news_sources.json").write_text(json.dumps(manifest))


def run(root, now, bars, events=None, capture=True, timing=None):
    with patch.object(study, "_context", return_value=dataset(bars)), patch.object(study, "_events", return_value=(events if events is not None else [event()], {"status": "ready"})), patch.object(study, "_baseline", return_value={"status": "unverified"}), patch.object(study, "_timing_records", return_value=timing or []):
        return study.build(root, clock(now), capture=capture)


def timing_observation(bars=None):
    bars = bars or after_bars()
    context = dataset(bars)
    return {"kind": "observation", "observation_id": "active-observation", "record_hash": "c" * 64,
            "ticker": "TEST", "source_session": bars[-1]["session_date"], "price_basis": "unadjusted",
            "first_observed_at": "2026-09-25T16:10:00-04:00", "bars_at_observation": bars[-51:], "inputs": context["bindings"],
            "review_windows": [{"id": "morning", "starts_at": "2026-09-28T09:45:00-04:00", "ends_at": "2026-09-28T10:45:00-04:00"}]}


def timing_mark(label, when, state="condition_observed", delay=None, anchor=None):
    now = clock(when)
    result = {"kind": "delay_evaluation" if delay else "window_evaluation", "observation_id": "active-observation",
              "record_hash": study._hash(label), "ticker": "TEST", "window_id": "morning", "recorded_at": when,
              "state": state, "first_qualifying_entry": delay is None, "delay_minutes": delay,
              "quote_observation": {"price": 110., "trade_at": (now - timedelta(seconds=1)).isoformat(),
                                    "observed_at": when, "expires_at": (now + timedelta(seconds=299)).isoformat(), "execution_quote": False}}
    if delay:
        result.update(first_entry_observation_record_hash=anchor["record_hash"], actual_delay_seconds=(now - clock(anchor["quote_observation"]["observed_at"])).total_seconds())
    return result


def release(root, now="2026-09-24T16:20:00-04:00", *, pub="2026-09-24T16:10:00-04:00", evidence="quarter ended June 30, 2026", apply=True):
    title = "TEST Reports Financial Results for Quarter Ended June 30, 2026"
    raw = (f'<html><head><title>{title}</title><link rel="canonical" href="https://ir.test.com/results"/>'
           f'<meta property="article:published_time" content="{pub}"/></head><body>NASDAQ: TEST. Financial results for the {evidence}.</body></html>').encode()
    path = Path("03_source_data/equity_research/release-test.local.html")
    (root / path).parent.mkdir(parents=True, exist_ok=True); (root / path).write_bytes(raw)
    proposal = {"schema_version": study.RELEASE_SCHEMA, "event_id": "event-test", "ticker": "TEST", "fiscal_period_label": "Jun/2026",
                "document_path": str(path), "document_sha256": study._digest(raw), "url": "https://ir.test.com/results",
                "fiscal_period_evidence": f"Financial results for the {evidence}", "official_news_event_id": "news-test",
                "reviewer": "Test analyst", "reasoning": "Source-bound actual results publication and fiscal period checked against the retained official issuer document. " * 2}
    news = {"kind": "observed_event", "event_id": "news-test", "ticker": "TEST", "recorded_at": "2026-09-24T16:11:00-04:00",
            "event": {"url": proposal["url"], "published_at": pub, "title": title}}
    with patch.object(study, "_events", return_value=([event()], {})), patch("issuer_news_queue.read_queue", return_value=[news]):
        return study.confirm_release(root, proposal, clock(now), apply=apply)


class EarningsSurvivalTests(unittest.TestCase):
    def test_readonly_and_missing_policy_do_not_create_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(study.build(root, clock("2026-09-23T08:00:00-04:00"))["status"], "waiting_on_data")
            self.assertFalse((root / study.OUTPUT).exists())
            setup(root)
            view = run(root, "2026-09-23T08:00:00-04:00", base_bars(), capture=False)
            self.assertEqual(view["summary"]["pre_event_candidates"], 0)
            self.assertFalse((root / study.OUTPUT).exists())

    def test_first_pre_event_levels_and_receipt_clock_are_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root)
            first = run(root, "2026-09-23T08:00:00-04:00", base_bars())
            raw = (root / study.OUTPUT / "ledger.jsonl").read_bytes()
            again = run(root, "2026-09-23T09:00:00-04:00", base_bars())
            self.assertEqual(first["summary"]["pre_event_candidates"], 1)
            self.assertEqual(again["candidates"][0]["first_observed_at"], first["candidates"][0]["first_observed_at"])
            self.assertEqual(raw, (root / study.OUTPUT / "ledger.jsonl").read_bytes())
            confirmation = release(root)
            self.assertEqual(confirmation["release_at"], "2026-09-24T16:10:00-04:00")
            self.assertEqual(confirmation["document_observed_at"], "2026-09-24T16:20:00-04:00")

    def test_stale_conflicting_and_late_candidates_are_not_enrolled(self):
        for mutation in [{"blockers": ["earnings_calendar_receipt_stale"]}, {"status": "schedule_conflict"}, {"timing": "unverified"}]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); setup(root); lead = {**event(), **mutation}
                view = run(root, "2026-09-23T08:00:00-04:00", base_bars(), [lead])
                self.assertEqual(view["summary"]["pre_event_candidates"], 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root)
            self.assertEqual(run(root, "2026-09-24T16:01:00-04:00", base_bars())["summary"]["pre_event_candidates"], 0)

    def test_calendar_alone_never_confirms_release_or_treatment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-23T08:00:00-04:00", base_bars())
            view = run(root, "2026-09-25T16:20:00-04:00", after_bars())
            self.assertEqual(view["summary"]["ordinary_breakout_signals"], 1)
            self.assertEqual(view["summary"]["survival_breakout_signals"], 0)
            self.assertEqual(view["candidates"][0]["state"], "actual_results_release_confirmation_required")

    def test_supported_survival_has_one_shared_baseline_and_future_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-23T08:00:00-04:00", base_bars()); release(root)
            view = run(root, "2026-09-25T16:20:00-04:00", after_bars())
            self.assertEqual(view["summary"]["survival_breakout_signals"], 1)
            self.assertEqual(view["summary"]["distinct_setup_ids"], 1)
            self.assertEqual(view["signals"][0]["entry_session"], "2026-09-28")
            self.assertEqual(view["summary"]["qualified_strategy_paths"], 0)
            self.assertEqual(view["signals"][0]["planning_feasibility"]["status"], "unavailable")

    def test_late_confirmation_cannot_retrotag_elapsed_open_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-23T08:00:00-04:00", base_bars())
            first = run(root, "2026-09-28T08:00:00-04:00", after_bars())
            release(root, "2026-09-28T10:00:00-04:00")
            later = run(root, "2026-09-28T10:01:00-04:00", after_bars())
            self.assertEqual(first["signals"][0]["entry_session"], "2026-09-28")
            self.assertEqual(later["summary"]["survival_breakout_signals"], 0)
            self.assertEqual(later["candidates"][0]["state"], "missed_release_confirmation_before_signal_capture")

    def test_support_breach_and_intraday_release_are_not_successes(self):
        for intraday in [False, True]:
            with self.subTest(intraday=intraday), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); setup(root); run(root, "2026-09-23T08:00:00-04:00", base_bars())
                release(root, pub="2026-09-24T13:00:00-04:00" if intraday else "2026-09-24T16:10:00-04:00")
                view = run(root, "2026-09-25T16:20:00-04:00", after_bars(breach=not intraday))
                self.assertEqual(view["summary"]["survival_breakout_signals"], 0)
                self.assertEqual(view["candidates"][0]["state"], "intraday_release_path_unavailable" if intraday else "failed_frozen_support")

    def test_wrong_period_and_future_source_publication_rejected(self):
        for kwargs, code in [({"evidence": "quarter ended March 31, 2026"}, "period_not_independently_bound"),
                             ({"pub": "2026-09-25T16:10:00-04:00"}, "future_clock")]:
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); setup(root)
                with self.assertRaisesRegex(ValueError, code): release(root, apply=False, **kwargs)
                self.assertFalse((root / study.OUTPUT).exists())

    def test_apply_rejection_preserves_proposal_without_admitting_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root)
            with self.assertRaisesRegex(ValueError, "period_not_independently_bound"):
                release(root, evidence="quarter ended March 31, 2026", apply=True)
            receipts = list((root / study.OUTPUT / "rejected_release_attempts").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            self.assertFalse((root / study.OUTPUT / "ledger.jsonl").exists())
            receipt = json.loads(receipts[0].read_text())
            self.assertTrue((root / study.OUTPUT / "inputs" / receipt["proposal_sha256"]).is_file())
            self.assertEqual(receipt["actionable_quantity"], 0)

    def test_modified_dateonly_naive_and_conflicting_metadata_rejected(self):
        template = '<html><head><title>TEST Reports Financial Results</title><link rel="canonical" href="https://ir.test.com/results"/>{}</head><body>' + 'x' * 100 + '</body></html>'
        for meta in ['<meta property="article:modified_time" content="2026-09-24T16:10:00-04:00"/>',
                     '<meta property="article:published_time" content="2026-09-24"/>',
                     '<meta property="article:published_time" content="2026-09-24T16:10:00"/>',
                     '<meta property="article:published_time" content="2026-09-24T16:10:00-04:00"/><meta name="datePublished" content="2026-09-25T16:10:00-04:00"/>']:
            with self.subTest(meta=meta), self.assertRaises(ValueError): study.parse_release_document(template.format(meta).encode())

    def test_matured_primary_is_exact_paired_path_not_strategy_profit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-23T08:00:00-04:00", base_bars()); release(root)
            run(root, "2026-09-25T16:20:00-04:00", after_bars())
            bars = after_bars()
            for index, day in enumerate(study._sessions("2026-09-28", 5)):
                bars.append({"session_date": day, "open": 110. + index, "close": 111. + index, "low": 109. + index, "high": 112. + index, "volume": 100.})
            view = run(root, "2026-10-02T16:20:00-04:00", bars)
            self.assertEqual(view["summary"]["matured_primary_paths"], 1)
            self.assertEqual(view["summary"]["matched_primary_paths"], 1)
            outcome = view["outcomes"][0]
            self.assertEqual(outcome["entry_price"], 110.)
            self.assertEqual(outcome["exit_session"], "2026-10-02")
            self.assertEqual(outcome["matched_benchmarks"]["SPY"]["excess_price_path_pct_points"], {"10": 0., "25": 0., "50": 0.})
            self.assertFalse(outcome["actual_fill"])
            self.assertTrue(outcome["corporate_action_review_required"])
            self.assertFalse(view["profitability_established"])

    def test_retained_source_tamper_and_frozen_dependency_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); view = run(root, "2026-09-23T08:00:00-04:00", base_bars())
            registry = root / "01_policies/swing_runtime_v3.json"
            registry.write_bytes(registry.read_bytes() + b"\n")
            blocked = run(root, "2026-09-23T09:00:00-04:00", base_bars(), capture=False)
            self.assertEqual(blocked["status"], "waiting_on_data")
            self.assertIn("survival_frozen_version_identity_changed", str(blocked["dependencies"]))
            changed = copy.deepcopy(view); changed["actionable_quantity"] = 1
            result = study.revalidate_projection(root, changed, clock("2026-09-23T09:00:00-04:00"))
            self.assertEqual(result["candidates"], [])

    def test_retained_raw_source_tamper_is_not_repaired_or_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root)
            run(root, "2026-09-23T08:00:00-04:00", base_bars())
            records = study._load(root, clock("2026-09-23T09:00:00-04:00"))
            snapshot = next(row for row in records if row["kind"] == "preregistration")["dataset_sha256"]
            retained = root / study.OUTPUT / "inputs" / snapshot
            retained.write_bytes(retained.read_bytes() + b" ")
            view = run(root, "2026-09-23T09:00:00-04:00", base_bars(), capture=False)
            self.assertEqual(view["status"], "waiting_on_data")
            self.assertIn("survival_retained_input_changed", str(view["dependencies"]))

    def test_release_at_regular_open_requires_intraday_evidence(self):
        self.assertIsNone(study._release_session("2026-09-24T09:30:00-04:00"))
        self.assertEqual(study._release_session("2026-11-27T13:00:00-05:00"), "2026-11-30")

    def test_first_future_open_is_after_actual_delayed_capture_and_dst(self):
        self.assertEqual(study._next_open(clock("2026-09-28T10:01:00-04:00")), "2026-09-29")
        self.assertEqual(study._next_open(clock("2026-10-30T16:20:00-04:00")), "2026-11-02")
        self.assertEqual(study._open("2026-11-02").isoformat(), "2026-11-02T09:30:00-05:00")

    def test_planning_cash_name_and_event_risk_are_ceilings_not_orders(self):
        planning = {"status": "source_bound_planning_ceiling_only", "planning_nav": 3000., "uncommitted_cash_upper_bound": 60.,
                    "event_risk_pct": .25, "max_position_pct": 5., "held_values": {}, "open_risk_status": "unknown"}
        value = study._ceiling(planning, "TEST", 20., 18.)
        self.assertEqual(value["whole_share_ceilings"], {"cash": 3, "name_headroom": 7, "event_planned_loss": 3})
        self.assertEqual(value["whole_share_upper_bound"], 3)
        self.assertEqual(value["actual_quantity"], 0)
        self.assertIsNone(value["combined_risk_eligible_quantity"])

    def test_timing_windows_and_delays_share_one_setup_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-25T16:20:00-04:00", after_bars(), [])
            first = timing_mark("first", "2026-09-28T09:50:00-04:00")
            marks = [timing_observation(), first]
            for delay in [3, 5, 10]:
                marks.append(timing_mark(str(delay), (clock(first["recorded_at"]) + timedelta(minutes=delay)).isoformat(), delay=delay, anchor=first))
            view = run(root, "2026-09-28T10:01:00-04:00", after_bars(), [], timing=marks)
            metrics = view["timing_usability"]
            self.assertEqual(metrics["unique_setup_windows_with_qualifying_marks"], 1)
            self.assertEqual(metrics["window_evaluation_records"], 1)
            self.assertEqual([r["qualifying_marks"] for r in metrics["delay_cohorts"]], [1, 1, 1])
            self.assertEqual(view["summary"]["distinct_setup_ids"], 1)
            self.assertEqual(view["summary"]["matured_primary_paths"], 0)
            self.assertFalse(view["profitability_established"])

    def test_earlier_marks_and_delay_anchors_cannot_be_borrowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-28T10:00:00-04:00", after_bars(), [])
            old_mark = timing_mark("old", "2026-09-28T09:50:00-04:00")
            delayed = timing_mark("late-delay", "2026-09-28T10:05:00-04:00", delay=5, anchor=old_mark)
            view = run(root, "2026-09-28T10:06:00-04:00", after_bars(), [], timing=[timing_observation(), old_mark, delayed])
            metrics = view["timing_usability"]
            self.assertEqual(metrics["unique_setup_windows_with_qualifying_marks"], 0)
            self.assertEqual(metrics["delay_cohorts"][1]["qualifying_marks"], 0)
            self.assertIn("delay_anchor_before_study_capture_or_unavailable", metrics["states"])
            self.assertEqual(view["signals"][0]["entry_session"], "2026-09-29")

    def test_invalidated_stale_and_out_of_band_marks_do_not_restore_entry(self):
        cases = []
        invalidation = timing_mark("invalid", "2026-09-28T09:50:00-04:00", "invalidation_observed")
        recovered = timing_mark("recovered", "2026-09-28T10:00:00-04:00")
        cases.append(([invalidation, recovered], "invalidated_before_study_entry"))
        stale = timing_mark("stale", "2026-09-28T09:50:00-04:00")
        stale["quote_observation"]["expires_at"] = "2026-09-28T09:49:00-04:00"
        cases.append(([stale], "stale_or_outside_window_quote_unavailable"))
        cases.append(([timing_mark("out", "2026-09-28T09:50:00-04:00", "outside_entry_band")], "outside_entry_band"))
        for marks, state in cases:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); setup(root); run(root, "2026-09-25T16:20:00-04:00", after_bars(), [])
                view = run(root, "2026-09-28T10:01:00-04:00", after_bars(), [], timing=[timing_observation(), *marks])
                self.assertEqual(view["timing_usability"]["unique_setup_windows_with_qualifying_marks"], 0)
                self.assertIn(state, view["timing_usability"]["states"])

    def test_missing_window_and_mismatched_original_bars_remain_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-25T16:20:00-04:00", after_bars(), [])
            view = run(root, "2026-09-28T11:00:00-04:00", after_bars(), [], timing=[timing_observation()])
            self.assertEqual(view["timing_usability"]["closed_window_states"], {"missed_no_observation_after_study_capture": 1})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-25T16:20:00-04:00", after_bars(), [])
            wrong = timing_observation(); wrong["bars_at_observation"][0]["high"] += 1
            view = run(root, "2026-09-28T10:01:00-04:00", after_bars(), [], timing=[wrong, timing_mark("first", "2026-09-28T09:50:00-04:00")])
            self.assertEqual(view["timing_usability"]["matched_source_observations"], 0)
            self.assertEqual(view["timing_usability"]["unmatched_source_signals"], 1)

    def test_future_mark_ceiling_uses_frozen_pre_entry_account_not_later_cash(self):
        planning = {"status": "source_bound_planning_ceiling_only", "planning_nav": 3000., "uncommitted_cash_upper_bound": 60.,
                    "event_risk_pct": .25, "max_position_pct": 5., "held_values": {}, "open_risk_status": "unknown"}
        signal = {"first_observed_at": "2026-09-25T16:20:00-04:00", "planning_feasibility": study._ceiling(planning, "TEST", 20., 18.)}
        value = study._future_quote_ceiling(signal, 21.)
        self.assertEqual(value["whole_share_upper_bound"], 2)
        self.assertEqual(value["actual_quantity"], 0)
        self.assertFalse(value["current_execution_cash_verified"])

    def test_missing_active_history_withholds_retained_timing_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup(root); run(root, "2026-09-25T16:20:00-04:00", after_bars(), [])
            source = [timing_observation(), timing_mark("first", "2026-09-28T09:50:00-04:00")]
            valid = run(root, "2026-09-28T09:51:00-04:00", after_bars(), [], timing=source)
            self.assertEqual(valid["timing_usability"]["unique_setup_windows_with_qualifying_marks"], 1)
            missing = run(root, "2026-09-28T09:52:00-04:00", after_bars(), [], timing=[], capture=False)
            self.assertEqual(missing["timing_usability"]["status"], "source_unavailable")
            self.assertIsNone(missing["timing_usability"]["unique_setup_windows_with_qualifying_marks"])
            self.assertEqual(missing["timing_usability"]["observations"], [])
            self.assertIn("retained_timing_source_no_longer_validated", str(missing["dependencies"]))


if __name__ == "__main__": unittest.main()
