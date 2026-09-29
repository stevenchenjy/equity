from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import delivery_followthrough as follow
from delivery_archive import archive_validated_delivery
from delivery_continuity import delivery_meaning_key
from daily_common import append_csv_durable, recommendation_notification_fingerprint, sha256_file
from email_brief import render_email
from scheduled_email import cards
from send_daily_email import LEDGER_FIELDS
from test_email_brief import decision_fixture
from test_maintained_plan_email import maintained_plan

ET=ZoneInfo("America/New_York")
MORNING=datetime(2026,9,28,9,30,tzinfo=ET)
AFTERNOON=datetime(2026,9,28,14,30,tzinfo=ET)


def decision():
    d=decision_fixture();d.update(cycle_date="2026-09-28",generated_at="2026-09-28T09:20:00-04:00",
        decision_code="maintained_plan_review",account_conflicts=[])
    d["held_positions"]=[{"ticker":"TEST","current_shares":2,"current_price":43}]
    plan=maintained_plan();plan.update(instruction="Retain conditional protection pending verification.",plan_id="TEST-protect-v1",version=1)
    d["plan_continuity"]={"schema_version":"equity_plan_continuity_v1","plans":[plan]}
    d["workflow_integrity"]={"schema_version":"equity_workflow_integrity_v1",
        "input_hashes":{key:"c"*64 for key in follow.RECORD_PATHS}}
    return d


def archive(root,prior,when=MORNING,prefix="",status="sent",alter_text=None,alter_html=None):
    _,text,html=render_email(prior)
    text=alter_text(text) if alter_text else text
    html=alter_html(html) if alter_html else html
    contents={"decision_sha256":json.dumps(prior).encode(),"brief_text_sha256":text.encode(),"brief_html_sha256":html.encode()}
    hashes={key:hashlib.sha256(value).hexdigest() for key,value in contents.items()}
    archive_validated_delivery(root/follow.LEDGER_REL.parent/"sent_decisions.local",contents=contents,hashes=hashes)
    row={"timestamp":when.isoformat(),"cycle_date":when.date().isoformat(),"status":prefix+status,
        "reason":"scheduled_slot=morning",**hashes}
    append_csv_durable(root/follow.LEDGER_REL,LEDGER_FIELDS,row)
    return row


class FollowthroughTests(unittest.TestCase):
    def test_read_only_full_fill_branch_does_not_record_execution_or_change_eligibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prior=decision();archive(root,prior)
            current=copy.deepcopy(prior);current["generated_at"]=AFTERNOON.isoformat()
            before=copy.deepcopy(current);ledger=(root/follow.LEDGER_REL).read_bytes()
            context=follow.build_followthrough(current,root=root,current=AFTERNOON)
            self.assertEqual(context["status"],"conditional_execution_followthrough")
            action=context["actions"][0]
            self.assertEqual(action["assumed_remaining_shares"],0)
            self.assertEqual(action["continuation"],"same_plan_do_not_repeat")
            self.assertEqual(current,before);self.assertEqual((root/follow.LEDGER_REL).read_bytes(),ledger)
            self.assertFalse(context["canonical_state_changed"]);self.assertFalse(context["creates_trade_eligibility"])
            current["delivery_followthrough"]=context
            for body in render_email(current)[1:]:
                self.assertIn("if the earlier 2-share sell fully filled",body)
                self.assertIn("Placing a stop or limit does not establish a fill",body)
                self.assertIn("Do not repeat that sale",body)
                self.assertIn("not adjusted by",body)
                self.assertNotIn("Maintained conditional plan — TEST: sell 2",body)
                self.assertIn("This system has placed or changed no orders",body)
                self.assertIn("cancel earlier protection",body)

    def test_explicit_eligible_tactical_buy_has_only_labelled_full_fill_scenario(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prior=decision()
            prior.update(decision_code="action_review_candidate",eligible_new_position_review_candidates=["NEW"])
            prior["account"]["cash_basis"]="owner_recorded"
            prior["watch_candidates"]=[{"ticker":"NEW","suggested_whole_shares":2,"maximum_review_price":50,
                "action":"eligible_buy_review","stability_distinct_closes":2,"required_distinct_closes":2}]
            prior["delivery_followthrough"]={"status":"no_prior_same_day_delivery"}
            prior["tactical_review"]={"global_gates_passed":True,"drafts":[{"ticker":"NEW","side":"buy","eligible":True,
                "quantity":2,"entry_price":50,"stop_price":45,"target_price":65,"planned_risk_usd":10,
                "order_type":"conditional limit draft","time_in_force":"DAY","session_date":"2026-09-28",
                "time_exit_session":"2026-10-02","entry_rule":"After the trigger is verified.",
                "invalidation_rule":"Review on setup failure.","blockers":[]}]}
            archive(root,prior);before=copy.deepcopy(prior)
            context=follow.build_followthrough(prior,root=root,current=AFTERNOON)
            self.assertEqual(context["status"],"conditional_execution_followthrough")
            buy=next(action for action in context["actions"] if action["side"]=="buy")
            self.assertEqual(buy["assumed_remaining_shares"],2)
            self.assertEqual(context["assumed_cash_after_at_stated_levels_before_fees"],"1297.88")
            text=" ".join(follow.continuation_lines(context))
            self.assertIn("Do not repeat that purchase",text);self.assertIn("before unverified fees",text)
            self.assertIn("not available buying power",text)
            self.assertEqual(prior,before)
            # Removing the explicitly displayed side is not enough evidence for a numerical assumed buy.
            other=Path(temp)/"legacy";prior.pop("delivery_followthrough")
            archive(other,prior)
            self.assertEqual(follow.build_followthrough(prior,root=other,current=AFTERNOON)["status"],"prior_action_not_structured")

    def _actual_snapshot(self,root,current,*,basis="owner_recorded",recorded_at="2026-09-28T14:00:00-04:00",
                         observed_at="2026-09-28T14:01:00-04:00"):
        positions=root/follow.RECORD_PATHS[0];positions.parent.mkdir(parents=True,exist_ok=True)
        positions.write_text("ticker,shares_optional\nTEST,2\n")
        account=root/follow.RECORD_PATHS[1];account.write_text(json.dumps({"cash_basis":basis,"cash_available":1317.38}))
        proof=root/"08_reviews/observation.json";proof.parent.mkdir(parents=True,exist_ok=True);proof.write_text('{"complete":true}')
        orders={"schema_version":"phase5r_open_orders_v1","complete":True,"as_of":observed_at,"orders":[],
            "current_inventory_observation":{"complete":True,"as_of":observed_at,"orders_shown":[],
                "source":{"path":"08_reviews/observation.json","sha256":sha256_file(proof)}}}
        (root/follow.RECORD_PATHS[2]).write_text(json.dumps(orders))
        confirmed=root/"06_execution_records/confirmed_execution_report.csv";confirmed.parent.mkdir(parents=True,exist_ok=True);confirmed.write_text("execution_id,order_status\n")
        current["workflow_integrity"]["input_hashes"]={key:sha256_file(root/key) for key in follow.RECORD_PATHS}
        receipt={"schema_version":"phase5r_owner_snapshot_v1","owner_snapshot":True,"source_note":"Explicit complete owner account update",
            "recorded_at":recorded_at,"positions_sha256_after":sha256_file(positions),"account_sha256_after":sha256_file(account),
            "confirmed_execution_sha256":sha256_file(confirmed)}
        (positions.parent/"manual_account_snapshot.local.json").write_text(json.dumps(receipt))

    def test_later_complete_owner_snapshot_and_order_evidence_releases_only_delivery_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prior=decision();archive(root,prior);current=copy.deepcopy(prior)
            self._actual_snapshot(root,current)
            before=copy.deepcopy(current)
            context=follow.build_followthrough(current,root=root,current=AFTERNOON)
            self.assertEqual(context["status"],"verified_current_snapshot_supersedes")
            self.assertFalse(follow.continuation_requires_reconciliation(context));self.assertEqual(context["actions"],[])
            self.assertIn("not applied again"," ".join(follow.continuation_lines(context)))
            self.assertEqual(before,current)

    def test_stale_planning_only_or_unbound_snapshot_cannot_release_hold(self):
        for fault in ("stale_snapshot","stale_orders","planning_cash","tampered_proof","new_execution"):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prior=decision();archive(root,prior);current=copy.deepcopy(prior)
                self._actual_snapshot(root,current,
                    basis="ledger_estimate" if fault=="planning_cash" else "owner_recorded",
                    recorded_at="2026-09-28T09:00:00-04:00" if fault=="stale_snapshot" else "2026-09-28T14:00:00-04:00",
                    observed_at="2026-09-28T09:00:00-04:00" if fault=="stale_orders" else "2026-09-28T14:01:00-04:00")
                if fault=="tampered_proof":(root/"08_reviews/observation.json").write_text("changed")
                if fault=="new_execution":(root/"06_execution_records/confirmed_execution_report.csv").write_text("changed")
                context=follow.build_followthrough(current,root=root,current=AFTERNOON)
                self.assertEqual(context["status"],"records_updated_since_delivery")
                self.assertTrue(follow.continuation_requires_reconciliation(context))

    def test_new_followthrough_metadata_does_not_create_email_change(self):
        d=decision();before=copy.deepcopy(d)
        d["delivery_followthrough"]={"status":"conditional_execution_followthrough","actions":[{"ticker":"TEST"}]}
        self.assertEqual(recommendation_notification_fingerprint(d),recommendation_notification_fingerprint(before))
        self.assertEqual(delivery_meaning_key(d),delivery_meaning_key(before))

    def test_all_additional_quantities_withheld_including_other_ticker_and_tactical_paths(self):
        d=decision();d["account"]["cash_basis"]="verified"
        d["watch_candidates"]=[{"ticker":"NEW","suggested_whole_shares":7,"maximum_review_price":111,"action":"eligible_buy_review"}]
        d["eligible_new_position_review_candidates"]=["NEW"]
        d["tactical_review"]={"drafts":[{"ticker":"NEW","eligible":True,"quantity":7,"entry_price":111}]}
        d["delivery_followthrough"]={"status":"conditional_execution_followthrough","prior_sent_at":MORNING.isoformat(),"actions":[]}
        before=copy.deepcopy(d);body="\n".join(row["body"] for row in cards(d,{"plans":[{"ticker":"NEW"}]}))
        self.assertNotIn("NEW eligible research proposal",body);self.assertNotIn("NEW tactical draft",body)
        self.assertNotIn("Maintained conditional plan",body)
        self.assertIn("Additional portfolio-changing drafts are withheld",body)
        self.assertEqual(d,before)

    def test_no_action_watch_or_expired_prior_does_not_become_fill(self):
        for kind in ("hold","expired"):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prior=decision();plan=prior["plan_continuity"]["plans"][0]
                if kind=="hold":plan.update(action="hold",historical_order_draft={},proposed_change_shares=0)
                else:plan["status"]="expired_pending_verification"
                archive(root,prior)
                context=follow.build_followthrough(prior,root=root,current=AFTERNOON)
                self.assertEqual(context["status"],"prior_no_specific_order");self.assertEqual(context["actions"],[])

    def test_up_to_research_and_free_prose_owner_review_are_not_parsed_as_fills(self):
        for owner in (False,True):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prior=decision()
                if owner:
                    prior["owner_requested_research"]={"mode":"explicit_one_off_research","presentation":"compact",
                        "request_id":"owner-unstructured-01","decision_fingerprint":prior["decision_fingerprint"],
                        "sections":[{"title":"My review","body":"Sell exactly two shares if the condition holds."}]}
                else:prior["eligible_new_position_review_candidates"]=["NEW"]
                archive(root,prior,prefix="owner_review_" if owner else "")
                context=follow.build_followthrough(prior,root=root,current=AFTERNOON)
                self.assertEqual(context["status"],"prior_action_not_structured");self.assertEqual(context["actions"],[])

    def test_exact_both_displayed_bodies_required_and_missing_archive_never_guessed(self):
        for fault in ("text","html","missing","tamper"):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prior=decision()
                row=archive(root,prior,alter_text=(lambda _:"watch only") if fault=="text" else None,
                            alter_html=(lambda _:"<p>watch only</p>") if fault=="html" else None)
                path=root/follow.LEDGER_REL.parent/"sent_decisions.local"/(row["decision_sha256"]+".json")
                if fault=="missing":path.unlink()
                if fault=="tamper":path.write_text('{}')
                context=follow.build_followthrough(prior,root=root,current=AFTERNOON)
                self.assertEqual(context["actions"],[])
                self.assertEqual(context["status"],"prior_action_not_structured" if fault in {"text","html"} else "prior_exact_content_unavailable")

    def test_unknown_delivery_and_unresolved_claim_block_assumption_even_with_later_other_send(self):
        for status in ("send_claimed","delivery_unknown"):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prior=decision();archive(root,prior,status=status)
                other=copy.deepcopy(prior);other["headline"]="Other exact content"
                archive(root,other,when=MORNING.replace(hour=10))
                context=follow.build_followthrough(prior,root=root,current=AFTERNOON)
                self.assertEqual(context["status"],"prior_delivery_uncertain");self.assertEqual(context["actions"],[])

    def test_resolved_claim_and_latest_correction_are_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prior=decision();archive(root,prior,status="send_claimed");archive(root,prior)
            newer=copy.deepcopy(prior);newer["headline"]="Formatting-only correction"
            row=archive(root,newer,when=MORNING.replace(hour=10),prefix="correction_")
            context=follow.build_followthrough(newer,root=root,current=AFTERNOON)
            self.assertEqual(context["prior_decision_sha256"],row["decision_sha256"])
            self.assertEqual(context["actions"][0]["plan_record_hash"],"a"*64)

    def test_later_no_action_or_partial_correction_does_not_erase_earlier_unreconciled_action(self):
        for changed in ("no_action","different_ticker","different_quantity"):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prior=decision();archive(root,prior);later=copy.deepcopy(prior)
                plan=later["plan_continuity"]["plans"][0]
                if changed=="no_action":plan.update(action="hold",historical_order_draft={},proposed_change_shares=0)
                elif changed=="different_ticker":
                    plan["ticker"]="OTHER";later["held_positions"][0]["ticker"]="OTHER"
                else:plan["historical_order_draft"]["quantity"]=1;plan["proposed_change_shares"]=1
                archive(root,later,when=MORNING.replace(hour=12))
                context=follow.build_followthrough(later,root=root,current=AFTERNOON)
                self.assertEqual(context["status"],"multiple_deliveries_require_reconciliation")
                self.assertEqual(context["actions"],[])
                self.assertTrue(follow.continuation_requires_reconciliation(context))

    def test_actual_account_or_order_update_overrides_assumption_without_proving_fill(self):
        for changed in follow.RECORD_PATHS:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prior=decision();archive(root,prior);current=copy.deepcopy(prior)
                current["workflow_integrity"]["input_hashes"][changed]="d"*64
                context=follow.build_followthrough(current,root=root,current=AFTERNOON)
                self.assertEqual(context["status"],"records_updated_since_delivery");self.assertEqual(context["actions"],[])
                self.assertIn("does not prove",follow.continuation_lines(context)[0])
                self.assertTrue(follow.continuation_requires_reconciliation(context))

    def test_expiry_and_changed_or_opposite_plan_reconcile_without_new_prices(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prior=decision();archive(root,prior);current=copy.deepcopy(prior)
            current["plan_continuity"]["plans"][0].update(action="buy_review",record_hash="b"*64)
            changed=follow.build_followthrough(current,root=root,current=AFTERNOON)
            self.assertEqual(changed["actions"][0]["continuation"],"changed_plan_reconcile")
            expired=follow.build_followthrough(prior,root=root,current=AFTERNOON.replace(hour=15,minute=45))
            self.assertEqual(expired["actions"][0]["continuation"],"expired_reconcile")
            self.assertNotIn("$40.25"," ".join(follow.continuation_lines(expired)))

    def test_sender_staleness_validation_rejects_new_receipt_or_changed_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prior=decision();archive(root,prior);current=copy.deepcopy(prior)
            current["delivery_followthrough"]=follow.build_followthrough(current,root=root,current=AFTERNOON)
            follow.validate_followthrough(current,root=root,current=AFTERNOON)
            tampered=copy.deepcopy(current);tampered["delivery_followthrough"]["actions"][0]["quantity"]=3
            with self.assertRaisesRegex(ValueError,"recompose_required"):follow.validate_followthrough(tampered,root=root,current=AFTERNOON)
            archive(root,prior,when=AFTERNOON.replace(minute=35),prefix="correction_")
            with self.assertRaisesRegex(ValueError,"recompose_required"):
                follow.validate_followthrough(current,root=root,current=AFTERNOON.replace(minute=40))

    def test_previous_day_or_no_send_is_not_a_same_day_execution_assumption(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prior=decision()
            self.assertEqual(follow.build_followthrough(prior,root=root,current=AFTERNOON)["status"],"no_prior_same_day_delivery")
            archive(root,prior,when=MORNING.replace(day=25))
            self.assertEqual(follow.build_followthrough(prior,root=root,current=AFTERNOON)["status"],"no_prior_same_day_delivery")


if __name__=="__main__":unittest.main()
