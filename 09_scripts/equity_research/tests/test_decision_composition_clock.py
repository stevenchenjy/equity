"""Exercise the production composition boundary against real session checks."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import capital_escalation
import create_daily_decision_and_brief as composer
from test_capital_escalation import fixture, sealed


class DecisionCompositionClockTests(unittest.TestCase):
    def test_second_boundary_uses_completed_clock_and_preserves_session_counter(self):
        started = datetime.fromisoformat("2026-10-14T14:11:18.975724-04:00")
        generated = datetime.fromisoformat("2026-10-14T14:11:19-04:00")
        completed = generated + timedelta(milliseconds=24)
        decision, contract, config, _ = fixture("2026-10-13", completed)
        decision["generated_at"] = generated.isoformat()
        # Reproduce the exact old-path rejection with otherwise identical data.
        self.assertIsNone(capital_escalation._session(decision, contract, started)[0])
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / "00_project_control/active_production_config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(config))
            with patch.object(composer, "now_et", return_value=completed), \
                 patch("capital_decision.build", return_value=contract) as builder:
                composer.compose_capital_contracts(decision, root=root)
            summary = decision["capital_deployment_escalation"]
            self.assertEqual(summary["observation_session"], "2026-10-13")
            self.assertNotEqual(summary["status"], "session_unverified")
            self.assertEqual(builder.call_args.kwargs["current"], completed)
            first = json.loads((root / capital_escalation.STORE_REL).read_text())
            with patch.object(composer, "now_et", return_value=completed + timedelta(seconds=1)), \
                 patch("capital_decision.build", return_value=contract):
                composer.compose_capital_contracts(decision, root=root)
            second = json.loads((root / capital_escalation.STORE_REL).read_text())
            self.assertEqual(first["session_observations"], second["session_observations"])
            self.assertEqual(first["events"], second["events"])

    def test_genuinely_future_decision_is_not_clamped_or_admitted(self):
        completed = datetime.fromisoformat("2026-10-14T14:11:19.024-04:00")
        decision, contract, config, _ = fixture("2026-10-13", completed)
        future = (completed + timedelta(minutes=1)).isoformat()
        decision["generated_at"] = future
        contract["generated_at"] = future
        contract = sealed(contract)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / "00_project_control/active_production_config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(config))
            with patch.object(composer, "now_et", return_value=completed), \
                 patch("capital_decision.build", return_value=contract):
                composer.compose_capital_contracts(decision, root=root)
            self.assertEqual(decision["generated_at"], future)
            self.assertEqual(decision["capital_deployment_escalation"]["status"], "session_unverified")
            self.assertFalse(decision["capital_deployment_escalation"]["triggered"])
            self.assertFalse(decision["capital_decision"]["automatic_action_allowed"])


if __name__ == "__main__":
    unittest.main()
