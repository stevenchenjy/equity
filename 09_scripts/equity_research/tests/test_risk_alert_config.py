"""Explicit risk-review permission must not broaden cadence or capital rights."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from active_config import ActiveConfigError, load_active_config


class RiskAlertConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((SCRIPT_DIR.parents[1] / "00_project_control/active_production_config.json").read_text())

    def check(self, config):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config))
            return load_active_config(path)

    def test_permission_preserves_investment_and_existing_schedule(self):
        result = self.check(self.config)
        self.assertTrue(result["notifications"]["risk_review_alerts"]["enabled"])
        for name in ("account", "workflow", "boundaries", "model_policy"):
            self.assertEqual(result[name], self.config[name])
        self.assertEqual(result["notifications"]["short_assessment_slots_et"],
                         ["09:30", "11:00", "12:30", "14:00", "15:30"])
        self.assertEqual(result["notifications"]["short_assessment_budget_minutes"], 10)

    def test_absent_permission_preserves_legacy_configuration(self):
        self.config["notifications"].pop("risk_review_alerts")
        result = self.check(self.config)
        self.assertNotIn("risk_review_alerts", result["notifications"])

    def test_disabled_permission_retains_explicit_record(self):
        self.config["notifications"]["risk_review_alerts"]["enabled"] = False
        self.assertFalse(self.check(self.config)["notifications"]["risk_review_alerts"]["enabled"])

    def test_partial_or_extra_permission_cannot_expand_authority(self):
        original = self.config["notifications"]["risk_review_alerts"]
        for field in original:
            with self.subTest(missing=field):
                changed = copy.deepcopy(self.config)
                changed["notifications"]["risk_review_alerts"].pop(field)
                with self.assertRaises(ActiveConfigError):
                    self.check(changed)
        for field, value in (("recipient", "another-recipient"),
                             ("automatic_orders_allowed", True),
                             ("loss_threshold_pct", 2), ("slots_et", ["10:00"])):
            with self.subTest(extra=field):
                changed = copy.deepcopy(self.config)
                changed["notifications"]["risk_review_alerts"][field] = value
                with self.assertRaises(ActiveConfigError):
                    self.check(changed)

    def test_invalid_permission_types_dates_and_triggers_rejected(self):
        for field, value in (("schema_version", "unknown"), ("enabled", 1),
                             ("enabled", "true"), ("effective_from", None),
                             ("effective_from", "tomorrow"), ("effective_from", "20261108"),
                             ("allowed_triggers", ["any_price_decline"]),
                             ("delivery_grace_minutes", True),
                             ("delivery_grace_minutes", 30)):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.config)
                changed["notifications"]["risk_review_alerts"][field] = value
                with self.assertRaises(ActiveConfigError):
                    self.check(changed)

    def test_permission_cannot_enable_without_existing_assessment_cadence(self):
        for field in ("mandatory_daily_briefs", "intraday_alerts_enabled", "delivery_assessment_effective_from",
                      "short_assessment_slots_et", "short_assessment_budget_minutes"):
            self.config["notifications"].pop(field)
        with self.assertRaises(ActiveConfigError):
            self.check(self.config)


if __name__ == "__main__":
    unittest.main()
