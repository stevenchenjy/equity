from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ET
from create_daily_decision_and_brief import compose_strategy_research


class StrategyFrameworkIntegrationTests(unittest.TestCase):
    def test_research_setups_and_handoff_do_not_create_a_new_email_meaning(self):
        from daily_common import recommendation_notification_fingerprint
        from delivery_continuity import delivery_meaning_key
        from email_brief import render_email
        from test_notification_changes import notification_fixture
        original = notification_fixture()
        changed = deepcopy(original)
        changed["strategy_framework"] = {
            "status": "ready", "analyst_handoff": [{"ticker": "META", "next_step": "Review the new source."}],
            "swing_research": {"status": "experimental_current", "research_only": True,
                               "schema_version": "equity_swing_research_v2",
                               "capital_authority": False, "actionable_quantity": 0,
                               "candidates": [{"ticker": "META", "entry_trigger": 500, "max_entry": 501}]},
            "swing_coverage": {"status": "dated_leads_current_history", "capital_authority": False,
                               "candidates": [{"ticker": "NEW", "current_price": None}]}}
        self.assertEqual(recommendation_notification_fingerprint(original), recommendation_notification_fingerprint(changed))
        self.assertEqual(delivery_meaning_key(original), delivery_meaning_key(changed))
        self.assertEqual(render_email(original), render_email(changed))
        changed["watch_candidates"][0]["suggested_whole_shares"] = "2"
        self.assertNotEqual(delivery_meaning_key(original), delivery_meaning_key(changed))

    def test_research_and_failed_study_cannot_change_capital_or_delivery_meaning(self):
        for status, candidates in (("experimental_current", [{"ticker": "META", "actionable_quantity": 0}]),
                                   ("waiting_on_data", [])):
            with self.subTest(status=status):
                decision = {"capital_decision": {"decisions": [{"ticker": "META", "shares": 0, "decision": "NO_ACTION"}]},
                            "decision_fingerprint": "original-advice", "send_recommended": False,
                            "eligible_new_position_review_candidates": [],
                            "notification_change": {"changed": False}}
                original = deepcopy(decision)
                current = datetime(2026, 10, 27, 21, 0, tzinfo=ET)
                study = {"status": status, "candidates": candidates, "capital_authority": False}
                with patch("decision_readiness.build", return_value={"status": "ready"}), \
                     patch("swing_coverage.build", return_value={"status": "unavailable", "candidates": []}), \
                     patch("swing_research_v2.build", return_value=study) as build:
                    compose_strategy_research(decision, root=Path("/unused"), current=current)
                build.assert_called_once_with(Path("/unused"), current=current, capture=False, baseline=decision)
                self.assertEqual(decision["strategy_framework"]["swing_research"], study)
                self.assertEqual({k: v for k, v in decision.items() if k != "strategy_framework"}, original)


if __name__ == "__main__":
    unittest.main()
