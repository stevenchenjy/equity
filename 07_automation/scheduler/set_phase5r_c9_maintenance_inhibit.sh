#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/messssi/Desktop/equity"
INHIBIT_PATH="${PROJECT_ROOT}/07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    print -u2 "Configured Python is unavailable: ${PYTHON_BIN}"
    exit 1
fi

"${PYTHON_BIN}" - "${INHIBIT_PATH}" <<'PY'
import json
import os
import sys
from datetime import datetime
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "active": True,
    "reason": "phase5r_c9_migration",
    "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "allowed_pipeline": "none",
}
temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
temporary.chmod(0o600)
os.replace(temporary, path)
PY

print "Phase 5R-C9 maintenance inhibit is active; allowed_pipeline=none."
