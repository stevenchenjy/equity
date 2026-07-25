#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/messssi/Desktop/equity"
INHIBIT_PATH="${PROJECT_ROOT}/07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    print -u2 "Configured Python is unavailable: ${PYTHON_BIN}"
    exit 1
fi
if [[ ! -f "${INHIBIT_PATH}" ]]; then
    print -u2 "Maintenance inhibit file is missing; refusing to create an implicit cleared state."
    exit 1
fi

"${PYTHON_BIN}" - "${INHIBIT_PATH}" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    existing = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit("Maintenance inhibit is invalid; repair it before clearing.") from exc
created_at = existing.get("created_at")
if not isinstance(created_at, str) or not created_at.strip():
    raise SystemExit("Maintenance inhibit has no valid created_at; repair it before clearing.")
payload = {
    "active": False,
    "reason": "phase5r_c9_migration_complete",
    "created_at": created_at,
    "allowed_pipeline": "phase5r_c7",
}
temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
temporary.chmod(0o600)
os.replace(temporary, path)
PY

print "Phase 5R-C9 maintenance inhibit is cleared; allowed_pipeline=phase5r_c7."
