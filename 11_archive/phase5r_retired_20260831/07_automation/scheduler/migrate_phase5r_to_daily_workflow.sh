#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/Desktop/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"
retired_dir="${launch_agents_dir}/Phase5RRetired"
retired_stamp="$(/bin/date '+%Y%m%dT%H%M%S')"

"${python_bin}" -c '
import json
from pathlib import Path
target = Path("/Users/messssi/Desktop/equity/07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json")
payload = json.loads(target.read_text())
assert payload["active"] is True
assert payload["allowed_pipeline"] == "none"
'

/bin/mkdir -p "${retired_dir}"
for legacy_suffix in dailybrief weeklyconviction weeklycatchup; do
    legacy_label="com.steven.phase5r.${legacy_suffix}"
    installed_plist="${launch_agents_dir}/${legacy_label}.plist"
    if /bin/launchctl print "${launch_domain}/${legacy_label}" >/dev/null 2>&1; then
        /bin/launchctl bootout "${launch_domain}/${legacy_label}"
    fi
    if [[ -f "${installed_plist}" ]]; then
        /bin/mv "${installed_plist}" "${retired_dir}/${legacy_label}.plist.retired-${retired_stamp}"
    fi
done

for legacy_suffix in dailybrief weeklyconviction weeklycatchup; do
    legacy_label="com.steven.phase5r.${legacy_suffix}"
    if /bin/launchctl print "${launch_domain}/${legacy_label}" >/dev/null 2>&1; then
        /usr/bin/printf '%s\n' "legacy_scheduler_unload_failed=${legacy_label}"
        exit 1
    fi
done

"${python_bin}" - <<'PY'
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path("/Users/messssi/Desktop/equity")
target = root / "00_project_control/active_decision_state.yaml"
current = json.loads(target.read_text())
now = datetime.now(ZoneInfo("America/New_York"))
payload = {
    **current,
    "schema_version": "phase5r_daily_v1",
    "generated_at": now.isoformat(timespec="seconds"),
    "current_workflow": "daily_decision",
    "active_pipeline": "phase5r_daily",
    "primary_decision": "daily_account_aware_decision",
    "operational_from": (now.date() + timedelta(days=1)).isoformat(),
    "decision_timezone": "America/New_York",
    "analysis_cadence": "weekday_08:15_12:30_16:15_17:45_plus_18:30_final;weekend_12:00_plus_18:30_decision",
    "email_cadence": "material_change_only_plus_friday_weekly_summary",
    "weekend_email_policy": "material_change_only",
    "daily_pipeline_status": "protected_verification",
    "d1_scheduler_status": "retired_unloaded",
    "d2_scheduler_status": "retired_unloaded",
    "d3_scheduler_status": "retired_unloaded",
    "email_delivery_allowed_from": "phase5r_daily_only",
    "active_research_phase": "phase5r_daily",
    "active_action_planner": "phase5r_c9_account_aware",
    "active_email_brief": "phase5r_daily",
    "active_state_guard": "phase5r_daily",
    "d3_maintenance_inhibit": "active",
    "archived_folders_allowed_as_input": "no",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
}
descriptor, temporary_name = tempfile.mkstemp(prefix=".active_decision_state.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_name, target)
finally:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
print(f"active_workflow=daily_decision operational_from={payload['operational_from']}")
PY

/usr/bin/printf '%s\n' \
    "legacy_schedulers_unloaded=true" \
    "legacy_plists_retired_recoverably=true" \
    "maintenance_inhibit_retained=true" \
    "email_attempted=false"
