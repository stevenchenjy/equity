"""Current naming surfaces must not regress while historical IDs stay intact."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from check_active_display_names import audit, tracked_markdown


class ActiveDisplayNamesTests(unittest.TestCase):
    def test_checked_in_current_surfaces_and_graph_are_clean(self):
        root = Path(__file__).resolve().parents[3]
        self.assertEqual(audit(root, tracked_markdown(root)), [])

    def test_old_current_headings_email_and_graph_cache_fail_but_history_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            runtime = Path(directory) / "runtime"
            current = root / "00_project_control/current.md"
            history = root / "11_archive/old.md"
            email = runtime / "07_automation/email_briefs/daily_email_brief.txt"
            for path in (current, history, email):
                path.parent.mkdir(parents=True, exist_ok=True)
            current.write_text("# Equity Research — Current\n", encoding="utf-8")
            history.write_text("# Phase 5R Historical\n", encoding="utf-8")
            email.write_text("Equity Research\nCurrent plan\n", encoding="utf-8")
            out = root / "graphify-out"
            out.mkdir()
            graph = {"nodes": [{"id": "current", "label": "Equity Research — Current",
                                "source_file": "00_project_control/current.md",
                                "source_location": "L1", "community": 1}], "links": []}
            (out / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
            (out / ".graphify_labels.json").write_text(json.dumps({"1": "Equity Research — Current"}), encoding="utf-8")
            paths = ["00_project_control/current.md", "11_archive/old.md"]
            self.assertEqual(audit(root, paths, runtime), [])

            current.write_text("# Phase 5R Current\n", encoding="utf-8")
            email.write_text("Phase 5R Equity Brief\nCurrent plan\n", encoding="utf-8")
            graph["nodes"][0]["label"] = "Phase 5R Current"
            (out / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
            (out / ".graphify_labels.json").write_text(json.dumps({"1": "Phase 5R Current"}), encoding="utf-8")
            issues = audit(root, paths, runtime)
            self.assertTrue(any("document heading" in issue for issue in issues))
            self.assertTrue(any("runtime display" in issue for issue in issues))
            self.assertTrue(any("Graphify node" in issue for issue in issues))

            # A cached community name can regress even when its member and
            # source heading are current; Graphify's AST update may retain it.
            current.write_text("# Equity Research — Current\n", encoding="utf-8")
            graph["nodes"][0]["label"] = "Equity Research — Current"
            (out / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
            email.write_text("Equity Research\nCurrent plan\n", encoding="utf-8")
            cache_issues = audit(root, paths, runtime)
            self.assertTrue(any("cache needs repair" in issue for issue in cache_issues))


if __name__ == "__main__":
    unittest.main()
