from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from active_config import ACTIVE_CONFIG_PATH, ActiveConfigError, load_active_config
import create_research_backlog as cli


class ResearchWorkBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "00_project_control/active_production_config.json"
        self.path.parent.mkdir()
        self.config = json.loads(ACTIVE_CONFIG_PATH.read_text())

    def test_config_rejects_unbounded_or_noninteger_work_budget(self):
        for value in (0, 11, True, "10", 1.5):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config["workflow"]["objective_research_max_tickers"] = value
                self.path.write_text(json.dumps(config))
                with self.assertRaisesRegex(ActiveConfigError, "objective research budget"):
                    load_active_config(self.path)

    def test_scheduled_cli_uses_configured_budget_and_explicit_override(self):
        self.config["workflow"]["objective_research_max_tickers"] = 10
        self.path.write_text(json.dumps(self.config))
        result = {"report_hash": "test", "objective_dossiers_completed": 0,
            "financial_fields_completed": 0, "canonical_numeric_updates": 0}
        for arguments, expected in (([], 10), (["--max-tickers", "2"], 2)):
            with self.subTest(expected=expected), patch.object(cli, "run", return_value=result) as run, \
                    patch("sys.argv", ["create_research_backlog", "--input-root", str(self.root),
                        "--output-root", str(self.root), *arguments]):
                self.assertEqual(cli.main(), 0)
                self.assertEqual(run.call_args.kwargs["max_tickers"], expected)


if __name__ == "__main__":
    unittest.main()
