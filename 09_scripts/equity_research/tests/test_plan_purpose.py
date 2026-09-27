"""Prospective purpose changes cannot turn stale or failed plans into holds."""
import copy
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import canonical_sha256
from investment_plans import SCHEMA, append_plan, validate_ledger, render_plan_lines
from test_investment_plans import record, ledger, evaluate


def with_purpose(row, horizon):
    row["strategy_horizon"] = horizon
    row["purpose"] = {
        "strategy": "Reviewed test strategy; no claim of investment efficacy",
        "holding_period_justification": "The cited research supports the proposed review horizon",
        "entry_validity": "Research only; verify current evidence and executable quote before action",
        "failure_condition": "The cited thesis or setup is contradicted by new evidence",
        "exit_rule": "Reconcile the position at invalidation or the recorded time exit",
        "sources": copy.deepcopy(row["sources"]),
    }
    return row


def with_reassessment(row, prior, outcome="active"):
    row["reassessment"] = {
        "previous_plan_id": prior["plan_id"], "previous_record_hash": prior["record_hash"],
        "reviewed_at": row["recorded_at"], "reviewer": "analyst",
        "reason": "Explicit current review of the prior setup and proposed purpose",
        "evidence_summary": "Test source retained; substantive research is an authored assertion",
        "strategy_justification": "The proposed strategy has been separately assessed",
        "holding_period_justification": "The proposed holding period follows that strategy evidence",
        "prior_outcome": {"status": outcome, "detail": "Preserve prior outcome without implying a broker fill"},
        "sources": copy.deepcopy(row["sources"]),
    }
    return row


class PurposeGuardTests(unittest.TestCase):
    def test_genuinely_new_tactical_plan_requires_explicit_supported_purpose(self):
        empty = {"schema_version": SCHEMA, "records": []}
        with self.assertRaisesRegex(ValueError, "new_tactical_requires_strategy_horizon"):
            append_plan(empty, record())
        row = with_purpose(record(), "multi_day_trend")
        append_plan(empty, row)
        del row["purpose"]
        with self.assertRaisesRegex(ValueError, "plan_purpose_required"):
            append_plan(empty, row)
        append_plan(empty, record(role="long_term_growth"))

    def test_legacy_history_remains_valid_and_ordinary_revision_preserves_history(self):
        first = ledger()
        row = record()
        row["instruction"] = "Clarify the existing review instruction"
        second = append_plan(first, row)
        self.assertEqual(second["records"][0], first["records"][0])
        validate_ledger(second)
        # Historical role changes retain their original hash-valid contents.
        historical = record(role="long_term_growth")
        historical.update(version=2, supersedes=first["records"][0]["record_hash"],
                          previous_hash=first["records"][0]["record_hash"])
        historical["record_hash"] = canonical_sha256(historical)
        validate_ledger({**first, "records": [*first["records"], historical]})

    def test_role_change_needs_structured_review_even_with_new_reason(self):
        row = with_purpose(record(role="long_term_growth"), "long_term_growth")
        row["change_reason"] = "I think this can recover if held longer"
        with self.assertRaisesRegex(ValueError, "reassessment_required"):
            append_plan(ledger(), row)

    def test_supported_purpose_change_is_append_only_and_visible(self):
        first = ledger()
        row = with_purpose(record(role="long_term_growth"), "long_term_growth")
        with_reassessment(row, first["records"][-1], "failed")
        second = append_plan(first, row)
        self.assertEqual(first["records"][0], second["records"][0])
        plan = evaluate(second)["plans"][0]
        self.assertEqual(plan["strategy_horizon"], "long_term_growth")
        self.assertEqual(plan["reassessment"]["prior_outcome"]["status"], "failed")
        self.assertEqual(plan["eligible_quantity"], 0)
        self.assertIn("long_term_growth / long_term_growth", "\n".join(render_plan_lines(evaluate(second))))

    def test_extension_or_deadline_removal_requires_horizon_and_reassessment(self):
        first = ledger()
        for field, value in (("time_exit_at", "2026-09-28T15:45:00-04:00"),
                             ("valid_until", "2026-09-28T15:45:00-04:00"), ("valid_until", None)):
            initial = record()
            if field == "valid_until":
                initial[field] = "2026-09-25T15:45:00-04:00"
            base = ledger(initial)
            row = copy.deepcopy(initial)
            row[field] = value
            with self.assertRaisesRegex(ValueError, "reassessment_required"):
                append_plan(base, row)
            with_reassessment(row, base["records"][-1])
            with self.assertRaisesRegex(ValueError, "requires_strategy_horizon"):
                append_plan(base, row)
            with_purpose(row, "multi_day_trend")
            append_plan(base, row)
        row = with_purpose(record(role="long_term_growth"), "long_term_growth")
        with_reassessment(row, first["records"][-1])
        append_plan(first, row)  # Removing the tactical deadline is a supported purpose change.

    def test_expired_draft_cannot_be_recycled_as_active(self):
        first = ledger()
        row = record()
        row["recorded_at"] = "2026-09-25T12:00:00-04:00"
        row["order_draft"]["session_date"] = "2026-09-25"
        with self.assertRaisesRegex(ValueError, "reassessment_required"):
            append_plan(first, row)
        with_reassessment(row, first["records"][-1], "active")
        with self.assertRaisesRegex(ValueError, "preserve_expired_outcome"):
            append_plan(first, row)
        row["reassessment"]["prior_outcome"]["status"] = "expired"
        second = append_plan(first, row)
        self.assertEqual(second["records"][0]["order_draft"]["session_date"], "2026-09-24")

    def test_failed_setup_stays_unresolved_and_cannot_be_silently_cleared(self):
        initial = record()
        initial.update(setup_status="failed", setup_status_reason="Authored evidence contradicts original setup")
        first = ledger(initial)
        plan = evaluate(first)["plans"][0]
        self.assertEqual(plan["status"], "failed_setup_pending_review")
        row = record()
        with self.assertRaisesRegex(ValueError, "reassessment_required"):
            append_plan(first, row)
        with_reassessment(row, first["records"][-1])
        with self.assertRaisesRegex(ValueError, "preserve_failed_outcome"):
            append_plan(first, row)
        row["reassessment"]["prior_outcome"]["status"] = "failed"
        append_plan(first, row)

    def test_source_identity_and_chronology_are_bound(self):
        first = ledger()
        for mutate, error in (
            (lambda r: r["reassessment"].update(previous_record_hash="0" * 64), "prior_identity"),
            (lambda r: r["reassessment"].update(previous_plan_id="different"), "prior_identity"),
            (lambda r: r["reassessment"].update(reviewed_at="2026-09-24T11:00:00-04:00"), "predates_prior"),
            (lambda r: r["reassessment"].update(reviewed_at="2026-09-25T12:00:00-04:00"), "after_recording"),
            (lambda r: r["reassessment"].update(sources=[{"path": "unretained.json", "sha256": "0" * 64}]), "source_not_bound"),
            (lambda r: r["reassessment"].update(evidence_summary=""), "required_field"),
        ):
            with self.subTest(error=error):
                row = with_purpose(record(role="long_term_growth"), "long_term_growth")
                with_reassessment(row, first["records"][-1])
                mutate(row)
                with self.assertRaisesRegex(ValueError, error):
                    append_plan(first, row)
        row = with_purpose(record(role="long_term_growth"), "long_term_growth")
        with_reassessment(row, first["records"][-1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "receipt.json").write_bytes(b"receipt")
            append_plan(first, row, root=root)
            (root / "receipt.json").write_bytes(b"replaced evidence")
            with self.assertRaisesRegex(ValueError, "source_hash_mismatch"):
                append_plan(first, row, root=root)

    def test_new_plan_id_cannot_bypass_position_purpose_history(self):
        first = ledger()
        new = with_purpose(record(role="long_term_growth"), "long_term_growth")
        new["plan_id"] = "a-new-name"
        with self.assertRaisesRegex(ValueError, "other_active_same_ticker"):
            append_plan(first, new)
        closed = record()
        closed["state"] = "superseded"
        terminal = append_plan(first, closed)
        with self.assertRaisesRegex(ValueError, "reassessment_required"):
            append_plan(terminal, new)
        with_reassessment(new, first["records"][-1], "superseded")
        with self.assertRaisesRegex(ValueError, "prior_identity"):
            append_plan(terminal, new)
        with_reassessment(new, terminal["records"][-1], "superseded")
        replacement = append_plan(terminal, new)
        self.assertEqual(replacement["records"][-1]["version"], 1)

    def test_terminal_hop_and_old_plan_id_cannot_erase_expired_failed_setup(self):
        initial = record()
        initial.update(setup_status="failed", setup_status_reason="Original setup invalidated")
        first = ledger(initial)
        closed = copy.deepcopy(initial)
        closed.update(state="superseded", recorded_at="2026-09-25T12:00:00-04:00")
        with_reassessment(closed, first["records"][-1], "failed")
        with self.assertRaisesRegex(ValueError, "preserve_expired_outcome"):
            append_plan(first, closed)
        closed["reassessment"]["prior_outcome"]["status"] = "expired_and_failed"
        terminal = append_plan(first, closed)
        new = with_purpose(record(role="long_term_growth"), "long_term_growth")
        new.update(plan_id="a-new-name", recorded_at="2026-09-25T12:00:00-04:00",
                   action="hold", proposed_change_shares=0, order_draft=None)
        with_reassessment(new, terminal["records"][-1], "superseded")
        with self.assertRaisesRegex(ValueError, "preserve_expired_outcome"):
            append_plan(terminal, new)
        new["reassessment"]["prior_outcome"]["status"] = "expired_and_failed"
        replacement = append_plan(terminal, new)
        last = copy.deepcopy(new)
        last["state"] = "completed"
        with_reassessment(last, replacement["records"][-1])
        finished = append_plan(replacement, last)
        reopened = copy.deepcopy(initial)
        reopened["recorded_at"] = "2026-09-25T12:00:00-04:00"
        with_reassessment(reopened, terminal["records"][-1], "expired_and_failed")
        with self.assertRaisesRegex(ValueError, "older_lineage_cannot_be_reopened"):
            append_plan(finished, reopened)

    def test_explicit_horizon_cannot_be_dropped_or_relabeled_without_review(self):
        initial = with_purpose(record(), "multi_day_trend")
        first = ledger(initial)
        with self.assertRaisesRegex(ValueError, "reassessment_required"):
            append_plan(first, record())
        incompatible = with_purpose(record(role="long_term_growth"), "intraday_momentum")
        with self.assertRaisesRegex(ValueError, "role_incompatible"):
            ledger(incompatible)

    def test_changed_strategy_or_holding_rationale_needs_review_within_same_horizon(self):
        initial = with_purpose(record(), "multi_day_trend")
        first = ledger(initial)
        for field in ("strategy", "holding_period_justification", "failure_condition", "exit_rule"):
            row = copy.deepcopy(initial)
            row["purpose"][field] = "A materially different justification or boundary"
            with self.assertRaisesRegex(ValueError, "reassessment_required"):
                append_plan(first, row)
            with_reassessment(row, first["records"][-1])
            append_plan(first, row)

    def test_overdue_growth_review_cannot_be_postponed_without_reassessment(self):
        initial = record(role="long_term_growth")
        initial.update(action="hold", proposed_change_shares=0, order_draft=None)
        first = ledger(initial)
        row = copy.deepcopy(initial)
        row.update(recorded_at="2026-09-28T12:00:00-04:00", review_at="2026-10-05T12:00:00-04:00")
        with self.assertRaisesRegex(ValueError, "reassessment_required"):
            append_plan(first, row)
        for outcome in ("active", "unverified"):
            with_reassessment(row, first["records"][-1], outcome)
            second = append_plan(first, row)
            self.assertEqual(second["records"][-1]["reassessment"]["prior_outcome"]["status"], outcome)
            self.assertEqual(second["records"][0]["review_at"], initial["review_at"])

    def test_intraday_requires_same_session_exit_review_and_draft(self):
        row = with_purpose(record(), "intraday_momentum")
        with self.assertRaisesRegex(ValueError, "intraday_same_session"):
            ledger(row)
        row.update(time_exit_at="2026-09-24T15:45:00-04:00", review_at="2026-09-24T15:30:00-04:00")
        ledger(row)
        for field, value in (("review_at", "2026-09-25T12:00:00-04:00"),
                             ("valid_until", "2026-09-25T12:00:00-04:00")):
            altered = copy.deepcopy(row)
            altered[field] = value
            with self.assertRaisesRegex(ValueError, "intraday_same_session"):
                ledger(altered)
        row["order_draft"]["session_date"] = "2026-09-25"
        with self.assertRaisesRegex(ValueError, "intraday_same_session"):
            ledger(row)

    def test_intraday_early_close_applies_without_price_thresholds(self):
        row = with_purpose(record(), "intraday_momentum")
        row.update(recorded_at="2026-11-27T12:00:00-05:00", effective_at="2026-11-27T11:00:00-05:00",
                   review_at="2026-11-27T12:30:00-05:00", time_exit_at="2026-11-27T12:45:00-05:00")
        row["order_draft"]["session_date"] = "2026-11-27"
        ledger(row)
        row["time_exit_at"] = "2026-11-27T15:45:00-05:00"
        with self.assertRaisesRegex(ValueError, "after_regular_close"):
            ledger(row)


if __name__ == "__main__":
    unittest.main()
