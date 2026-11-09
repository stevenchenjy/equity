"""A delivered review notice must not adopt, cancel or erase capital advice."""
from __future__ import annotations

import csv
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import append_csv_durable, canonical_sha256
from delivery_archive import archive_validated_delivery
import delivery_assessments as delivery
import delivery_continuity as continuity
import delivery_followthrough as follow
import post_delivery_publication as recovery
from send_daily_email import LEDGER_FIELDS
from short_assessment import due_slot
import test_delivery_followthrough as follow_fixture
import test_post_delivery_publication as publication_fixture
from test_risk_review_alerts import seed_risk_fixture


def risk_receipt(root, when, *, status="sent"):
    with tempfile.TemporaryDirectory() as temporary:
        observation = seed_risk_fixture(Path(temporary), current=when)
    selected = observation["active_episode_keys"]
    slot = due_slot(when)["slot_id"]
    evaluation = {"eligible": True, "mode": "risk_review_alert", "slot_id": slot,
        "purpose_key": "risk-review:" + slot,
        "meaning_key": delivery.RISK_MEANING_MARKER + canonical_sha256(selected),
        "selected_episode_keys": selected, "policy_sha256": "a" * 64}
    wrapper = delivery.risk_review_envelope(observation, evaluation)
    _, text, html = delivery.render_risk_review_alert(wrapper)
    contents = {"decision_sha256": json.dumps(wrapper, sort_keys=True).encode(),
        "brief_text_sha256": text.encode(), "brief_html_sha256": html.encode()}
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in contents.items()}
    archive_validated_delivery(root / delivery.ARCHIVE_REL, contents=contents, hashes=hashes)
    reason = "delivery_mode=risk_review_alert;delivery_purpose_v1=" + evaluation["purpose_key"]
    claim = {"timestamp": when.isoformat(), "cycle_date": when.date().isoformat(),
        "status": "send_claimed", "reason": "pre_smtp_durable_claim;" + reason,
        "message_count": "0", "email_attempted": "no", "email_sent": "no", **hashes}
    sent = {**claim, "timestamp": (when + timedelta(seconds=1)).isoformat(), "status": status,
        "reason": "smtp_send_completed;" + reason, "message_count": "1" if status == "sent" else "0",
        "email_attempted": "yes", "email_sent": "yes" if status == "sent" else "unknown"}
    for row in (claim, sent):
        append_csv_durable(root / follow.LEDGER_REL, LEDGER_FIELDS, row)
    return claim, sent


class RiskDeliveryConsumersTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_actual_risk_notice_preserves_earlier_exact_order_continuation(self):
        decision = follow_fixture.decision()
        follow_fixture.archive(self.root, decision)
        before = follow.build_followthrough(decision, root=self.root, current=follow_fixture.AFTERNOON)
        _, sent = risk_receipt(self.root, follow_fixture.MORNING + timedelta(minutes=5))
        self.assertEqual(delivery._archived_receipt_baseline(sent, root=self.root)["status"], "risk_only")
        after = follow.build_followthrough(decision, root=self.root, current=follow_fixture.AFTERNOON)
        self.assertEqual(after["status"], "conditional_execution_followthrough")
        self.assertEqual(after["actions"], before["actions"])
        self.assertEqual(after["prior_receipt_sha256"], before["prior_receipt_sha256"])
        self.assertFalse(after["creates_trade_eligibility"])

    def test_only_risk_notice_has_no_assumed_order_or_fill(self):
        risk_receipt(self.root, follow_fixture.MORNING + timedelta(minutes=5))
        result = follow.build_followthrough(follow_fixture.decision(), root=self.root, current=follow_fixture.AFTERNOON)
        self.assertEqual(result["status"], "no_prior_same_day_delivery")
        self.assertEqual(result["actions"], [])

    def test_unknown_risk_notice_retains_execution_uncertainty(self):
        follow_fixture.archive(self.root, follow_fixture.decision())
        risk_receipt(self.root, follow_fixture.MORNING + timedelta(minutes=5), status="delivery_unknown")
        result = follow.build_followthrough(follow_fixture.decision(), root=self.root, current=follow_fixture.AFTERNOON)
        self.assertEqual(result["status"], "prior_delivery_uncertain")
        self.assertEqual(result["actions"], [])

    def test_delivery_meaning_skips_only_exact_completed_risk_notice(self):
        decision = follow_fixture.decision()
        original = {"timestamp": follow_fixture.MORNING.isoformat(), "status": "sent",
            "reason": continuity.delivery_meaning_key(decision)}
        claim, sent = risk_receipt(self.root, follow_fixture.MORNING + timedelta(minutes=5))
        rows = [original, claim, sent]
        kwargs = {"current": follow_fixture.AFTERNOON, "archive_dir": self.root / delivery.ARCHIVE_REL}
        self.assertTrue(continuity.covered_by_last_delivery(rows, decision, **kwargs))
        self.assertFalse(continuity.covered_by_last_delivery(rows[:-1], decision, **kwargs))
        archive = self.root / delivery.ARCHIVE_REL / (sent["brief_html_sha256"] + ".html")
        archive.write_bytes(archive.read_bytes() + b"tampered")
        self.assertFalse(continuity.covered_by_last_delivery(rows, decision, **kwargs))
        result = follow.build_followthrough(decision, root=self.root, current=follow_fixture.AFTERNOON)
        self.assertEqual(result["status"], "prior_exact_content_unavailable")

    def publication(self):
        fixture = publication_fixture.PostDeliveryPublicationTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        return fixture

    def test_risk_send_rebinds_only_exact_ledger_append_without_adopting_capital(self):
        fixture = self.publication()
        _, sent = risk_receipt(fixture.root, publication_fixture.NOW.replace(hour=9, minute=43))
        ledger = fixture.ledger.read_bytes()
        result = fixture.recover()
        self.assertEqual(result["outcome"], "passed", result)
        self.assertFalse(result["email_attempted"])
        self.assertEqual(fixture.ledger.read_bytes(), ledger)
        self.assertEqual(result["delivery_receipt"]["decision_sha256"], sent["decision_sha256"])
        current = json.loads((fixture.root / recovery.ARTIFACTS[0]).read_text())
        self.assertEqual(current["delivery_followthrough"]["actions"], [])
        self.assertEqual(current["capital_decision"]["decisions"], fixture.decision["capital_decision"]["decisions"])

    def test_risk_recovery_cannot_rebind_other_input_changes_or_corrupt_render(self):
        for corrupt in ("input", "render"):
            with self.subTest(corrupt=corrupt):
                fixture = self.publication()
                _, sent = risk_receipt(fixture.root, publication_fixture.NOW.replace(hour=9, minute=43))
                target = (fixture.root / "05_risk_and_positions/current_account_state.local.json" if corrupt == "input"
                    else fixture.root / delivery.ARCHIVE_REL / (sent["brief_html_sha256"] + ".html"))
                target.write_bytes(target.read_bytes() + b" ")
                result = fixture.recover()
                self.assertNotEqual(result["outcome"], "passed", result)
                self.assertEqual(fixture.calls, [])
                self.assertTrue(result["publication_pending"])

    def test_interrupted_risk_rebind_retries_the_preserved_canonical_snapshot(self):
        fixture = self.publication()
        risk_receipt(fixture.root, publication_fixture.NOW.replace(hour=9, minute=43))
        ledger = fixture.ledger.read_bytes()
        def fail_after_recompose(name, *args, **kwargs):
            result = fixture.runner(name, *args, **kwargs)
            if name == "workflow_evaluation":
                result["exit_code"] = 1
            return result
        failed = fixture.recover(fail_after_recompose)
        self.assertEqual(failed["outcome"], "failed")
        self.assertTrue(failed["publication_pending"])
        recovered = fixture.recover()
        self.assertEqual(recovered["outcome"], "passed", recovered)
        self.assertEqual(recovered["canonical_decision_sha256"], failed["canonical_decision_sha256"])
        self.assertEqual(fixture.ledger.read_bytes(), ledger)
        self.assertFalse(recovered["email_attempted"])


if __name__ == "__main__":
    unittest.main()
