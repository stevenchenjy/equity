#!/usr/bin/env python3
"""Keep the local assessment host awake during its existing operating day.

This is a power assertion, not a research, collection or delivery worker. It
does not wake a powered-off host, override a deliberate manual sleep, invoke
Codex, or authorize a late assessment. On AC power macOS caffeinate holds a
PreventSystemSleep assertion; the idle assertion also covers idle sleep.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, time
from zoneinfo import ZoneInfo

from daily_common import is_us_market_session_date

ET = ZoneInfo("America/New_York")
CAFFEINATE = "/usr/bin/caffeinate"
# Include the full reviews, collection handoffs, both brief windows and the
# final short assessment. This does not extend any trading or email deadline.
OPERATING_START = time(8)
OPERATING_END = time(16, 15)


def assertion_seconds(current: datetime) -> int:
    if current.tzinfo is None:
        raise ValueError("session_awake_requires_aware_clock")
    local = current.astimezone(ET)
    if not is_us_market_session_date(local.date()):
        return 0
    start = datetime.combine(local.date(), OPERATING_START, ET)
    end = datetime.combine(local.date(), OPERATING_END, ET)
    if not start <= local < end:
        return 0
    return math.ceil((end - local).total_seconds())


def run_assertion(current: datetime, *, check: bool = False) -> int:
    seconds = assertion_seconds(current)
    observation = {"observed_at": current.astimezone(ET).isoformat(),
        "session_awake_due": seconds > 0, "assertion_seconds": seconds,
        "check_only": check, "email_invoked": False, "research_invoked": False}
    print(json.dumps(observation, sort_keys=True), flush=True)
    if check or not seconds:
        return 0
    result = subprocess.run([CAFFEINATE, "-si", "-t", str(seconds)], check=False)
    print(json.dumps({"session_awake_assertion_released": True,
        "exit_code": result.returncode}, sort_keys=True), flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
        help="Report the actual operating-day gate without taking an assertion")
    args = parser.parse_args()
    return run_assertion(datetime.now(ET), check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
