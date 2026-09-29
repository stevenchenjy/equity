from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import daily_common as common
import run_daily_scheduler as scheduler
import run_daily_decision_pipeline as pipeline
import send_daily_email as sender
from delivery_schedule import active_delivery_window
from test_owner_review_delivery import delivery_fixture, save_decision
from test_sender_publication import actionable_fixture

ET = ZoneInfo("America/New_York")
CONFIG = {"notifications": {"send_after_et": "09:30", "terminal_alert_after_et": "15:05",
    "delivery_windows_et": [
        {"id": "morning", "start": "09:30", "end": "10:30", "refresh_not_before": "08:00"},
        {"id": "afternoon", "start": "14:30", "end": "15:05", "refresh_not_before": "13:30"}]}}


def stamp(hour=9, minute=30):
    return datetime(2026, 9, 1, hour, minute, tzinfo=ET)


def receipt(status="sent", slot="morning", *, prefix="", digest="a", cycle="2026-09-01"):
    return {"timestamp": "2026-09-01T09:30:00-04:00", "cycle_date": cycle, "status": prefix + status,
            "reason": ("scheduled_slot=" + slot) if slot else "historical_receipt",
            "decision_sha256": digest * 64, "brief_text_sha256": digest * 64, "brief_html_sha256": digest * 64}


class DeliveryWindowTests(unittest.TestCase):
    def test_clock_windows_and_gaps_are_explicit(self):
        for hour, minute, expected in [(9,29,None),(9,30,"morning"),(10,30,"morning"),
                (10,31,None),(13,30,None),(14,30,"afternoon"),(15,5,"afternoon"),(15,6,None),(20,0,None)]:
            with self.subTest(clock=(hour,minute)):
                result = active_delivery_window(CONFIG["notifications"], stamp(hour,minute))
                self.assertEqual(result["id"] if result else None, expected)
        self.assertIsNone(active_delivery_window(CONFIG["notifications"], datetime(2026,9,5,9,45,tzinfo=ET)))

    def test_final_guard_blocks_gap_and_holiday_without_opening_credentials(self):
        for current in [stamp(12), datetime(2026,9,7,9,45,tzinfo=ET)]:
            with patch.object(common,"load_active_state",return_value={"operational_from":"2026-08-01"}), \
                 patch.object(common,"load_inhibit",return_value={"active":False}), \
                 patch.object(common,"cycle_date",return_value=current.date().isoformat()), \
                 patch.object(common,"now_et",return_value=current), \
                 patch("active_config.load_active_config",return_value=CONFIG):
                self.assertEqual(common.delivery_guard()[:2], (False,"outside_delivery_window"))

    def test_resolved_morning_receipt_allows_only_later_slot(self):
        rows=[receipt("send_claimed"),receipt("sent")]
        self.assertEqual(sender.scheduled_window_is_blocked(rows,"2026-09-01","morning"),(True,"sent"))
        self.assertEqual(sender.scheduled_window_is_blocked(rows,"2026-09-01","afternoon"),(False,""))

    def test_unresolved_claim_and_unknown_fence_both_windows(self):
        for prefix in ("","owner_review_","correction_"):
            for status in ("send_claimed","delivery_unknown"):
                rows=[receipt(status,prefix=prefix)]
                for slot in ("morning","afternoon"):
                    self.assertEqual(sender.scheduled_window_is_blocked(rows,"2026-09-01",slot),(True,status))

    def test_claim_resolution_requires_same_content_purpose_and_later_receipt(self):
        for rows in [[receipt("sent"),receipt("send_claimed")],
                     [receipt("send_claimed"),receipt("sent",digest="b")],
                     [receipt("send_claimed"),receipt("sent",slot="afternoon")],
                     [receipt("send_claimed",prefix="owner_review_"),receipt("sent")]]:
            self.assertEqual(sender.scheduled_window_is_blocked(rows,"2026-09-01","afternoon"),(True,"send_claimed"))

    def test_legacy_sends_are_not_reinterpreted_and_older_unknown_stays_old(self):
        self.assertEqual(sender.scheduled_window_is_blocked([receipt(slot="")],"2026-09-01","afternoon"),(True,"sent"))
        old=receipt("delivery_unknown",cycle="2026-08-31");old["timestamp"]="2026-08-31T20:00:00-04:00"
        self.assertEqual(sender.scheduled_window_is_blocked([old],"2026-09-01","morning"),(False,""))
        # A review of yesterday's canonical decision sent TODAY still fences today.
        actual_today=receipt("delivery_unknown",prefix="owner_review_",cycle="2026-08-31")
        self.assertEqual(sender.scheduled_window_is_blocked([actual_today],"2026-09-01","morning"),(True,"delivery_unknown"))

    def test_second_materially_changed_send_keeps_schema_and_exact_archives(self):
        config=copy.deepcopy(sender.load_active_config());config["notifications"].pop("regular_delivery_mode",None)
        with delivery_fixture() as (_,smtp), patch.object(sender,"load_active_config",return_value=config):
            decision=actionable_fixture();decision["generated_at"]="2026-09-01T09:20:00-04:00"
            save_decision(decision)
            with patch.object(sender,"now_et",return_value=stamp()), patch.object(sender,"iso_now",return_value=stamp().isoformat()):
                self.assertEqual(sender.send_once(smtp,scheduled_slot="morning"),0)
            decision["account"]["cash_available"]="1500.00"
            save_decision(decision)
            with patch.object(sender,"now_et",return_value=stamp(14,30)), patch.object(sender,"iso_now",return_value=stamp(14,30).isoformat()):
                self.assertEqual(sender.send_once(smtp,scheduled_slot="afternoon"),0)
                self.assertEqual(sender.send_once(smtp,scheduled_slot="afternoon"),0)
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,2)
            rows=sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)
            self.assertEqual(len(rows),4)
            self.assertTrue(all(set(row)==set(sender.LEDGER_FIELDS) for row in rows))
            self.assertIn("scheduled_slot=morning",rows[0]["reason"])
            self.assertIn("scheduled_slot=afternoon",rows[-1]["reason"])
            archive=sender.DAILY_DELIVERY_LEDGER_PATH.parent/"sent_decisions.local"
            for row in rows:
                for field,suffix in [("decision_sha256",".json"),("brief_text_sha256",".txt"),("brief_html_sha256",".html")]:
                    self.assertEqual(sender.sha256_file(archive/(row[field]+suffix)),row[field])

    def test_afternoon_unchanged_suppresses_before_credentials(self):
        config=copy.deepcopy(sender.load_active_config());config["notifications"].pop("regular_delivery_mode",None)
        with delivery_fixture() as (credentials,smtp), patch.object(sender,"load_active_config",return_value=config):
            decision=actionable_fixture();save_decision(decision)
            with patch.object(sender,"now_et",return_value=stamp()), patch.object(sender,"iso_now",return_value=stamp().isoformat()):
                self.assertEqual(sender.send_once(smtp,scheduled_slot="morning"),0)
            credentials.reset_mock();smtp.reset_mock()
            with patch.object(sender,"now_et",return_value=stamp(14,30)):
                self.assertEqual(sender.send_once(smtp,scheduled_slot="afternoon"),0)
            credentials.assert_not_called();smtp.assert_not_called()

    def test_both_windows_revalidate_active_watch_mode_against_actual_delivery(self):
        from delivery_continuity import delivery_notification_comparison
        with delivery_fixture() as (_,smtp):
            decision=actionable_fixture()
            decision.update(generated_at="2026-09-01T09:20:00-04:00",send_reason="watch_or_action_changed")
            decision["notification_policy"]["regular_delivery_mode"]=common.WATCH_ACTION_NOTIFICATION_MODE
            prior=copy.deepcopy(decision);prior["decision_code"]="blocked_account_conflict"
            decision["notification_change"]=common.notification_change_comparison(decision,{},prior)
            save_decision(decision)
            with patch.object(sender,"now_et",return_value=stamp()),patch.object(sender,"iso_now",return_value=stamp().isoformat()):
                self.assertEqual(sender.send_once(smtp,scheduled_slot="morning"),0)
            decision["generated_at"]="2026-09-01T14:20:00-04:00"
            decision["account"]["cash_available"]="1500.00"
            decision["notification_change"]=delivery_notification_comparison(decision,{},
                rows=sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH),current=stamp(14,20),
                archive_dir=sender.DAILY_DELIVERY_LEDGER_PATH.parent/"sent_decisions.local")
            self.assertEqual(decision["notification_change"]["comparison_source"],"last_delivery")
            self.assertTrue(decision["notification_change"]["changed"])
            save_decision(decision)
            with patch.object(sender,"now_et",return_value=stamp(14,30)),patch.object(sender,"iso_now",return_value=stamp(14,30).isoformat()):
                self.assertEqual(sender.send_once(smtp,scheduled_slot="afternoon"),0)
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,2)

    def test_crossing_end_during_validation_never_claims_or_sends(self):
        config=copy.deepcopy(sender.load_active_config());config["notifications"].pop("regular_delivery_mode",None)
        with delivery_fixture() as (_,smtp), patch.object(sender,"load_active_config",return_value=config):
            save_decision(actionable_fixture())
            actual=sender.active_delivery_window
            calls=iter([actual(config["notifications"],stamp(10,30)),None])
            with patch.object(sender,"now_et",return_value=stamp(10,30)), \
                 patch.object(sender,"active_delivery_window",side_effect=lambda *_:next(calls)):
                self.assertEqual(sender.send_once(smtp,scheduled_slot="morning"),2)
            smtp.assert_not_called()
            self.assertEqual(sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH),[])

    def test_afternoon_rejects_passed_morning_handoff(self):
        state={"schema_version":"phase5r_daily_refresh_state_v1","cycle_date":"2026-09-01",
               "expected_market_session":"2026-08-31","started_at":"2026-09-01T08:00:00-04:00",
               "completed_at":"2026-09-01T08:10:00-04:00","outcome":"passed","decision_created":True,
               "hard_failures":[],"soft_failures":[]}
        with patch.object(pipeline,"read_json",return_value=state),patch.object(pipeline,"cycle_date",return_value="2026-09-01"), \
             patch.object(pipeline,"now_et",return_value=stamp(14,30)),patch.object(pipeline,"load_active_config",return_value=CONFIG), \
             patch.object(pipeline,"latest_published_market_session",return_value=date(2026,8,31)):
            self.assertEqual(pipeline.refresh_readiness("morning"),(True,"daily_refresh_ready"))
            self.assertEqual(pipeline.refresh_readiness("afternoon"),(False,"daily_refresh_before_delivery_window_checkpoint"))
            state.update(started_at="2026-09-01T13:30:00-04:00",completed_at="2026-09-01T13:35:00-04:00")
            self.assertEqual(pipeline.refresh_readiness("afternoon"),(True,"daily_refresh_ready"))
            state["soft_failures"]=["collector"]
            self.assertEqual(pipeline.refresh_readiness("afternoon"),(False,"daily_refresh_not_fully_passed"))

    def scheduler_run(self,state,current,summary="email_sent=false reason=unchanged_watch_and_actions_suppressed",code=0):
        with ExitStack() as stack:
            for name,value in [("load_active_state",{"operational_from":"2026-08-01"}),("load_inhibit",{"active":False}),
                               ("cycle_date","2026-09-01"),("now_et",current),("iso_now",current.isoformat()),
                               ("load_active_config",CONFIG),("read_json",state)]:
                stack.enter_context(patch.object(scheduler,name,return_value=value))
            stack.enter_context(patch.object(scheduler,"atomic_write_json"))
            stack.enter_context(patch.object(scheduler,"clear_automation_alert"))
            stack.enter_context(patch.object(scheduler,"publish_automation_alert"))
            stack.enter_context(patch.object(scheduler.sys,"argv",["scheduler.py"]))
            run=stack.enter_context(patch.object(scheduler.subprocess,"run",return_value=
                scheduler.subprocess.CompletedProcess(["pipeline"],code,stdout=summary)))
            with redirect_stdout(io.StringIO()): result=scheduler.main()
            return result,run

    def test_unchanged_morning_does_not_complete_afternoon_or_rewrite_legacy_state(self):
        legacy={"decision_attempts":1,"decision_last_exit_code":75}
        state={"dates":{"2026-09-01":dict(legacy)}}
        self.scheduler_run(state,stamp())
        result,run=self.scheduler_run(state,stamp(14,30))
        self.assertEqual(result,0);run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-2:],["--delivery-window","afternoon"])
        for slot in ("morning","afternoon"):
            slot_state=state["dates"]["2026-09-01"]["delivery_windows"][slot]
            self.assertEqual(slot_state["decision_successful_checks"],1)
            self.assertNotIn("decision_attempts",slot_state)
        for key,value in legacy.items():self.assertEqual(state["dates"]["2026-09-01"][key],value)

    def test_quiet_first_check_rechecks_later_analyst_output_without_burning_send_attempts(self):
        state={"dates":{}}
        self.scheduler_run(state,stamp())
        first=state["dates"]["2026-09-01"]["delivery_windows"]["morning"]
        self.assertNotIn("decision_completed",first)
        self.assertNotIn("decision_attempts",first)
        _,run=self.scheduler_run(state,stamp(9,45),"email_sent=true message_count=1 automatic_retry=false")
        run.assert_called_once()
        self.assertTrue(first["decision_completed"])
        self.assertEqual(first["decision_attempts"],1)
        self.assertEqual(first["decision_checks"],2)

    def test_repeated_quiet_checks_end_without_false_failure(self):
        state={"dates":{}}
        for hour,minute in [(9,30),(9,45),(10,0),(10,15),(10,30)]:
            self.scheduler_run(state,stamp(hour,minute))
        slot=state["dates"]["2026-09-01"]["delivery_windows"]["morning"]
        self.assertEqual(slot["decision_checks"],5)
        self.assertNotIn("decision_attempts",slot)
        _,run=self.scheduler_run(state,stamp(10,45));run.assert_not_called()
        self.assertTrue(slot["decision_completed"])
        self.assertEqual(slot["decision_window_closed_reason"],"closed_no_material_change")
        self.assertNotIn("decision_terminal_failure",slot)

    def test_legacy_completed_date_is_left_intact_without_retroactive_alerts(self):
        state={"dates":{"2026-09-01":{"decision_completed":True,"decision_attempts":1}}}
        before=copy.deepcopy(state)
        _,run=self.scheduler_run(state,stamp(16));run.assert_not_called()
        self.assertEqual(state,before)

    def test_unknown_morning_or_legacy_claim_never_retries_in_afternoon(self):
        state={"dates":{}}
        self.scheduler_run(state,stamp(),"email_sent=unknown reason=smtp_exception_after_claim",1)
        _,run=self.scheduler_run(state,stamp(14,30));run.assert_not_called()
        state={"dates":{"2026-09-01":{"decision_terminal_reason":"delivery_status_unknown"}}}
        _,run=self.scheduler_run(state,stamp());run.assert_not_called()

    def test_scheduler_never_sends_late_after_sleep(self):
        state={"dates":{}}
        _,run=self.scheduler_run(state,stamp(16));run.assert_not_called()
        for slot in state["dates"]["2026-09-01"]["delivery_windows"].values():
            self.assertTrue(slot["decision_terminal_failure"])


if __name__=="__main__":unittest.main()
