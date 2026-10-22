"""Cadence adoption must preserve the investment configuration."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from active_config import ActiveConfigError, load_active_config


class AssessmentCadenceConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((SCRIPT_DIR.parents[1] / "00_project_control/active_production_config.json").read_text())

    def check(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(value))
            return load_active_config(path)

    def test_adopted_cadence_keeps_legacy_semantic_filter_and_risk_authority(self):
        original = copy.deepcopy(self.config)
        result = self.check(self.config)
        self.assertEqual(result["account"], original["account"])
        self.assertEqual(result["boundaries"], original["boundaries"])
        self.assertEqual(result["notifications"]["regular_delivery_mode"], "watch_or_action_change")
        self.assertFalse(result["notifications"]["unchanged_daily_email"])
        self.assertTrue(result["notifications"]["mandatory_daily_briefs"])

    def test_partial_adoption_cannot_enable_an_undefined_sender_contract(self):
        self.config["notifications"].pop("delivery_assessment_effective_from")
        with self.assertRaises(ActiveConfigError):
            self.check(self.config)

    def test_unapproved_cadence_or_budget_is_rejected(self):
        for field, value in [("short_assessment_slots_et", ["09:30", "10:00"]),
                             ("short_assessment_budget_minutes", 60),
                             ("short_assessment_budget_minutes", True),
                             ("mandatory_daily_briefs", "true"),
                             ("delivery_assessment_effective_from", "tomorrow")]:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.config)
                changed["notifications"][field] = value
                with self.assertRaises(ActiveConfigError):
                    self.check(changed)

    def test_absent_adoption_keeps_legacy_config_valid(self):
        for field in ["mandatory_daily_briefs", "intraday_alerts_enabled", "delivery_assessment_effective_from",
                      "short_assessment_slots_et", "short_assessment_budget_minutes"]:
            self.config["notifications"].pop(field)
        self.check(self.config)


if __name__ == "__main__":
    unittest.main()
