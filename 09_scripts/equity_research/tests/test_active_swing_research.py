"""Pinned helper drift, namespace isolation, admission and read-only regressions."""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR
import active_swing_research as active
import frozen_swing_runtime as runtime
import swing_research as old
import swing_research_v2 as legacy
from test_swing_research import fixture, current, bars


ROOT = SCRIPT_DIR.parents[1]


def setup(root):
    clock = current()
    end = date(2026, 9, 22)
    start = end - timedelta(weeks=52)
    count = sum(old.is_us_market_session_date(start + timedelta(days=n)) for n in range((end-start).days+1))
    series = bars(count=count)
    series[-1].update(open=102., high=104., low=100., close=103., volume=300.)
    bundle = fixture(root, series, observed=clock)
    (root / old.UNIVERSE).write_text("ticker,sector,is_benchmark\nTEST,Technology,no\n")
    pointer = root / old.market_backup.CURRENT
    value = json.loads(pointer.read_text())
    value.update(schema_version="equity_market_history_pointer_v1", snapshot_sha256=bundle["snapshot_sha256"])
    pointer.write_text(json.dumps(value))
    for relative in [active.POLICY, runtime.CONFIG, legacy.POLICY]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    return clock


def files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class ActiveSwingTests(unittest.TestCase):
    def test_capture_replay_and_read_paths_preserve_legacy_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clock = setup(root)
            historical = root / legacy.OUTPUT / "ledger.jsonl"
            historical.parent.mkdir(parents=True); historical.write_bytes(b"preserved historical bytes\n")
            view = active.build(root, clock, capture=True)
            self.assertEqual(view["status"], "experimental_current", view)
            self.assertEqual(view["version"], active.VERSION)
            self.assertEqual(view["candidates"][0]["entry_trigger"], 103)
            self.assertEqual(view["candidates"][0]["actionable_quantity"], 0)
            self.assertFalse(view["capital_authority"])
            ledger = root / active.OUTPUT / "ledger.jsonl"
            before = ledger.read_bytes()
            later = active.build(root, clock + timedelta(minutes=1), capture=True)
            self.assertEqual(later["status"], "experimental_current", later)
            self.assertEqual(ledger.read_bytes(), before)
            self.assertEqual(historical.read_bytes(), b"preserved historical bytes\n")
            before_reads = files(root)
            rows = active._load(root, clock + timedelta(minutes=1)); active._verify(root, rows)
            self.assertEqual(len(rows), 1)
            self.assertEqual(active.quote_targets(root, clock), ["TEST"])
            checked = active.revalidate_projection(root, view, clock + timedelta(minutes=2))
            self.assertEqual(checked["status"], "experimental_current", checked)
            context = active.research_context(root, clock)
            self.assertEqual(set(context["dataset"]["series"]), {"TEST"})
            expected=context["features"]["TEST"]
            self.assertTrue(expected["selected"]["breakout"])
            self.assertEqual(active.features(context["dataset"]["series"]["TEST"]["bars"],root=root),expected)
            self.assertEqual(active.features_many({"TEST":context["dataset"]["series"]["TEST"]["bars"]},root=root),{"TEST":expected})
            self.assertEqual(files(root), before_reads)

    def test_old_frozen_version_drift_blocker_does_not_retune_active_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clock = setup(root)
            archive=runtime.load_registry(root)
            repository=Path(os.environ.get("EQUITY_FROZEN_GIT_REPOSITORY",ROOT))
            # Reproduce the old actual engine's same-version helper-drift check
            # from local immutable bytes, without slow mutable authoring files.
            driver='''import sys,json
from pathlib import Path
from datetime import datetime
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
import swing_research_v2 as study
root=Path(sys.argv[2]);clock=datetime.fromisoformat(sys.argv[3])
first=study.build(root,clock,capture=True)
original=study._implementation
def changed():
    _,contents=original();return "f"*64,contents
study._implementation=changed
print(json.dumps({"first":first,"blocked":study.build(root,clock)}))
'''
            with runtime.verified_snapshot(archive,repository=repository) as snapshot:
                result=subprocess.run([sys.executable,"-I","-c",driver,str(snapshot/"09_scripts/equity_research"),str(root),clock.isoformat()],text=True,capture_output=True,check=True)
            values=json.loads(result.stdout);first=values["first"]
            self.assertEqual(first["status"], "experimental_current", first)
            historical = (root / legacy.OUTPUT / "ledger.jsonl").read_bytes()
            self.assertIn("swing_v2_frozen_version_identity_changed", values["blocked"]["blockers"])
            # Parent-process live helpers cannot enter the isolated engine.
            with patch.object(old, "_features", side_effect=AssertionError("live helper used")):
                active_view = active.build(root, clock, capture=True)
            self.assertEqual(active_view["status"], "experimental_current", active_view)
            self.assertEqual((root / legacy.OUTPUT / "ledger.jsonl").read_bytes(), historical)
            self.assertNotEqual(active_view["source_bindings"]["implementation_sha256"], first["source_bindings"]["implementation_sha256"])

    def test_missing_frozen_dependency_is_rejected_even_when_manifest_is_resealed(self):
        archive = copy.deepcopy(runtime.load_registry(ROOT))
        del archive["runtime_files"]["09_scripts/equity_research/daily_common.py"]
        archive["runtime_sha256"] = runtime.digest(runtime.json_bytes(archive["runtime_files"]))
        repository = Path(__import__("os").environ.get("EQUITY_FROZEN_GIT_REPOSITORY", ROOT))
        with self.assertRaisesRegex(ValueError, "swing_runtime_dependency_missing"):
            with runtime.verified_snapshot(archive, repository=repository):
                pass

    def test_tampered_frozen_bytes_or_policy_never_create_a_ledger(self):
        for mode in ["git_bytes", "policy"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); clock=setup(root)
                if mode == "git_bytes":
                    path=root/runtime.CONFIG; archive=json.loads(path.read_text())
                    archive["runtime_files"]["09_scripts/equity_research/daily_common.py"]="a"*64
                    archive["runtime_sha256"]=runtime.digest(runtime.json_bytes(archive["runtime_files"]))
                    path.write_text(json.dumps(archive))
                else:
                    path=root/active.POLICY; value=json.loads(path.read_text()); value["maximum_gap_r"]=.5
                    path.write_text(json.dumps(value))
                view=active.build(root,clock,capture=True)
                self.assertEqual(view["status"],"waiting_on_data")
                self.assertFalse((root/active.OUTPUT/"ledger.jsonl").exists())

    def test_resealed_missing_manifest_dependency_fails_without_fallback_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); clock=setup(root)
            path=root/runtime.CONFIG; archive=json.loads(path.read_text())
            del archive["runtime_files"]["09_scripts/equity_research/daily_common.py"]
            archive["runtime_sha256"]=runtime.digest(runtime.json_bytes(archive["runtime_files"]))
            path.write_text(json.dumps(archive))
            view=active.build(root,clock,capture=True)
            self.assertEqual(view["blockers"],["swing_runtime_dependency_missing"])
            self.assertFalse((root/active.OUTPUT).exists())

    def test_changed_or_missing_retained_dependency_preserves_the_prior_ledger(self):
        for missing in [False,True]:
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);clock=setup(root)
                view=active.build(root,clock,capture=True)
                self.assertEqual(view["status"],"experimental_current",view)
                ledger=root/active.OUTPUT/"ledger.jsonl";before=ledger.read_bytes()
                dependency=root/active.OUTPUT/"implementations"/view["source_bindings"]["implementation_sha256"]/"daily_common.py"
                if missing:dependency.unlink()
                else:dependency.write_text("malformed retained dependency bytes\n")
                blocked=active.build(root,clock+timedelta(minutes=1),capture=True)
                self.assertIn("swing_v2_retained_implementation_changed",blocked["blockers"])
                self.assertEqual(ledger.read_bytes(),before)


if __name__ == "__main__":
    unittest.main()
