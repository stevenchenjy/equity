"""Independent official-news checks using the existing serialized scheduler.

No sender, broker, credentials or market-provider path. A morning EOD success
does not consume the afternoon/evening public-news checks.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime

from daily_common import ROOT, atomic_write_json, read_json

STATE_PATH = ROOT / "00_project_control/run_logs/news_scheduler.local.json"
SCRIPT = ROOT / "09_scripts/equity_research/refresh_official_news.py"
SLOTS = ("08:15", "11:15", "16:45", "20:15")
EFFECTIVE_FROM = "2026-09-20"


def run_due_news_checks(current: datetime) -> dict:
    day = current.date().isoformat()
    if day < EFFECTIVE_FROM:
        return {"outcome": "not_active"}
    state = read_json(STATE_PATH, {"schema_version": "phase5r_news_scheduler_v1", "dates": {}})
    today = state.setdefault("dates", {}).setdefault(day, {})
    completed = set(today.get("attempted_slots", []))
    due = [slot for slot in SLOTS if slot <= current.strftime("%H:%M") and slot not in completed]
    if not due:
        return {"outcome": "not_due"}
    # Coalesce missed slots into one bounded attempt. Persist reservation
    # before network access so a crash cannot cause a request storm.
    today["attempted_slots"] = sorted(completed | set(due))
    today["last_attempt_at"] = current.isoformat()
    today["last_outcome"] = "attempt_reserved"
    atomic_write_json(STATE_PATH, state)
    try:
        process = subprocess.run([sys.executable, str(SCRIPT), "--refresh"], cwd=ROOT,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 timeout=150, check=False)
        code = process.returncode
    except (OSError, subprocess.TimeoutExpired):
        code = 124
    today["last_exit_code"] = code
    today["last_outcome"] = "passed" if code == 0 else "degraded"
    if code == 0:
        today["last_success_at"] = current.isoformat()
    for old in sorted(state["dates"])[:-60]:
        del state["dates"][old]
    atomic_write_json(STATE_PATH, state)
    # A late official-news check should be visible in current operational
    # status even when the EOD pipeline already completed this morning.
    status_script = ROOT / "09_scripts/equity_research/generate_current_status.py"
    try:
        subprocess.run([sys.executable, str(status_script)], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"outcome": today["last_outcome"], "exit_code": code, "covered_slots": due}
