"""Execute the isolated single-job installer with mocked launchctl/runtime.

No test invokes a production scheduler, launchctl mutation, SMTP or a provider.
"""
from __future__ import annotations

import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401


ROOT = Path(__file__).resolve().parents[3]
SCHEDULER = ROOT / "07_automation/scheduler"
LABEL = "com.steven.equity_research.dailyrefresh"
OTHER_LABEL = "com.steven.equity_research.dailydecision"
PYTHON = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
PRODUCTION = Path("/Users/messssi/LocalRuntime/equity")


class DailyrefreshInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.runtime = self.base / "runtime"
        self.library = self.base / "Library"
        self.scheduler = self.runtime / "07_automation/scheduler"
        self.scheduler.mkdir(parents=True)
        self.wrapper = self.runtime / "09_scripts/equity_research/run_runtime_scheduler.py"
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_text("# Never executed; the test Python shim records arguments.\n")
        self.events = self.base / "events.jsonl"
        self.control = self.base / "control.json"
        self.control.write_text(json.dumps({"states": ["idle", "idle"], "prints": 0}))
        self.launchctl = self.base / "mock-launchctl"
        self.launchctl.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\nfrom pathlib import Path\n"
            f"events=Path({str(self.events)!r}); control=Path({str(self.control)!r})\n"
            "with events.open('a') as h: h.write(json.dumps(['launchctl']+sys.argv[1:])+'\\n')\n"
            "state=json.loads(control.read_text())\n"
            "if sys.argv[1]=='print':\n"
            "    index=state['prints']; state['prints']+=1; control.write_text(json.dumps(state))\n"
            "    value=state['states'][min(index,len(state['states'])-1)]\n"
            "    if value=='absent': sys.exit(113)\n"
            "    if value=='unknown': sys.exit(5)\n"
            "    print('service = {')\n"
            "    print('\\tstate = '+('not running' if value in ('idle','idle_pid') else value))\n"
            "    if value in ('running','idle_pid'): print('\\tpid = 12345')\n"
            "    print('\\tresource coalition = {\\n\\t\\tstate = active\\n\\t}\\n}')\n"
            "sys.exit(0)\n"
        )
        self.launchctl.chmod(0o700)
        self.git = self.base / "mock-git"
        self.git.write_text(
            f"#!{sys.executable}\nimport sys\n"
            f"root={str(self.runtime)!r}\n"
            "args=sys.argv[1:]\n"
            "if args[-2:]==['rev-parse','--show-toplevel']: print(root)\n"
            "elif args[-2:]==['branch','--show-current']: print('main')\n"
            "elif args[-3:]==['remote','get-url','origin']: print('https://github.com/stevenchenjy/equity.git')\n"
            "else: sys.exit(2)\n"
        )
        self.git.chmod(0o700)
        self.python = self.base / "mock-python"
        self.python.write_text(
            f"#!{sys.executable}\n"
            "import json, subprocess, sys\nfrom pathlib import Path\n"
            f"events=Path({str(self.events)!r}); control=Path({str(self.control)!r})\n"
            "if sys.argv[1]=='-':\n"
            "    result=subprocess.run([sys.executable]+sys.argv[1:], input=sys.stdin.buffer.read(), check=False)\n"
            "    sys.exit(result.returncode)\n"
            "with events.open('a') as h: h.write(json.dumps(['runtime']+sys.argv[1:])+'\\n')\n"
            "state=json.loads(control.read_text())\n"
            "sys.exit(state.get('runtime_exit',0))\n"
        )
        self.python.chmod(0o700)
        source = (SCHEDULER / "install_dailyrefresh_scheduler.sh").read_text()
        source = source.replace(str(PRODUCTION), str(self.runtime))
        source = source.replace("/Users/messssi/Library", str(self.library))
        source = source.replace(PYTHON, str(self.python))
        source = source.replace("/bin/launchctl", str(self.launchctl))
        source = source.replace("/usr/bin/git", str(self.git))
        self.installer = self.base / "installer.sh"
        self.installer.write_text(source)
        self.template = self.scheduler / f"{LABEL}.plist.template"
        self.payload = plistlib.loads((SCHEDULER / f"{LABEL}.plist.template").read_bytes())
        self.launcher_template = self.scheduler / "dailyrefresh_launcher.py.template"
        self.launcher_template.write_text("# isolated launcher fixture; never executed\n")
        self.launcher = self.library / "Application Support/EquityResearch/bin/dailyrefresh_launcher.py"
        self.payload["ProgramArguments"] = [str(self.launcher)]
        self.payload["WorkingDirectory"] = str(self.runtime)
        for key in ("StandardOutPath", "StandardErrorPath"):
            self.payload[key] = self.payload[key].replace("/Users/messssi/Library", str(self.library))
        self.save_template()
        self.other = self.library / f"LaunchAgents/{OTHER_LABEL}.plist"
        self.other.parent.mkdir(parents=True)
        self.other.write_bytes(b"unchanged-delivery-job")

    def save_template(self):
        self.template.write_bytes(plistlib.dumps(self.payload))

    def configure(self, states, **kwargs):
        self.control.write_text(json.dumps({"states": states, "prints": 0, **kwargs}))

    def run_installer(self):
        return subprocess.run(["/bin/zsh", str(self.installer)], capture_output=True, text=True, check=False)

    def read_events(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []

    def assert_no_mutation(self):
        events = self.read_events()
        self.assertFalse(any(event[0] == "launchctl" and event[1] in {"bootout", "enable", "bootstrap", "kickstart"} for event in events), events)
        self.assertEqual(self.other.read_bytes(), b"unchanged-delivery-job")

    def test_idle_replacement_installs_only_refresh_with_run_at_load_preserved(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events()
        self.assertEqual([event[1] for event in events if event[0] == "launchctl"], ["print", "print", "bootout", "enable", "bootstrap"])
        self.assertEqual([event[2:] for event in events if event[0] == "runtime"], [["--job", "dailyrefresh", "--sync-only"], ["--job", "dailyrefresh", "--safe-check"]])
        installed = self.library / f"LaunchAgents/{LABEL}.plist"
        self.assertEqual(installed.read_bytes(), self.template.read_bytes())
        self.assertEqual(installed.stat().st_mode & 0o777, 0o600)
        self.assertIs(plistlib.loads(installed.read_bytes())["RunAtLoad"], True)
        self.assertEqual(self.launcher.read_bytes(), self.launcher_template.read_bytes())
        self.assertEqual(self.launcher.stat().st_mode & 0o777, 0o700)
        self.assertIn("bootstrap_refresh_may_run=true", result.stdout)
        self.assertEqual(self.other.read_bytes(), b"unchanged-delivery-job")
        self.assertIn("sender_invoked=false", result.stdout)

    def test_absent_target_bootstraps_without_bootout(self):
        self.configure(["absent", "absent"])
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("bootout", [event[1] for event in self.read_events() if event[0] == "launchctl"])

    def test_running_unknown_and_pid_states_refuse_before_bootout(self):
        for state in ("running", "idle_pid", "unknown", "spawn scheduled"):
            with self.subTest(state=state):
                self.events.unlink(missing_ok=True)
                self.configure([state])
                result = self.run_installer()
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_mutation()
                self.assertFalse(any(event[0] == "runtime" for event in self.read_events()))

    def test_target_starting_during_preflight_is_not_booted_out(self):
        self.configure(["idle", "running"])
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation()

    def test_old_background_altered_cadence_and_run_at_load_are_refused(self):
        for field, value in (("ProcessType", "Background"), ("RunAtLoad", False), ("StartInterval", 60)):
            with self.subTest(field=field):
                self.events.unlink(missing_ok=True)
                self.configure(["idle", "idle"])
                original = self.payload[field]
                self.payload[field] = value
                self.save_template()
                result = self.run_installer()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unexpected_dailyrefresh_template", result.stderr)
                self.assert_no_mutation()
                self.payload[field] = original

    def test_failed_runtime_preflight_leaves_loaded_job_untouched(self):
        self.configure(["idle"], runtime_exit=70)
        result = self.run_installer()
        self.assertEqual(result.returncode, 70)
        self.assert_no_mutation()

    def test_symlink_launcher_is_rejected_before_loaded_job_changes(self):
        self.launcher.parent.mkdir(parents=True)
        target = self.base / "unrelated"
        target.write_bytes(b"preserve")
        self.launcher.symlink_to(target)
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe_installed_launcher", result.stderr)
        self.assert_no_mutation()
        self.assertEqual(target.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
