#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/Desktop/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
activation_log="${project_root}/00_project_control/run_logs/phase5r_daily_activation_log.csv"

for legacy_suffix in dailybrief weeklyconviction weeklycatchup; do
    legacy_label="com.steven.phase5r.${legacy_suffix}"
    if /bin/launchctl print "${launch_domain}/${legacy_label}" >/dev/null 2>&1; then
        /usr/bin/printf '%s\n' "activation_blocked=legacy_scheduler_loaded:${legacy_label}"
        exit 1
    fi
    if [[ -f "/Users/messssi/Library/LaunchAgents/${legacy_label}.plist" ]]; then
        /usr/bin/printf '%s\n' "activation_blocked=legacy_plist_installed:${legacy_label}"
        exit 1
    fi
done

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    if ! /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
        /usr/bin/printf '%s\n' "activation_blocked=new_scheduler_unloaded:${job_label}"
        exit 1
    fi
done

"${python_bin}" - <<'PY'
import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path("/Users/messssi/Desktop/equity")
verification = root / "00_project_control/phase5r_daily_verification_report.md"
if not verification.exists() or "Overall result: **PASS**" not in verification.read_text():
    raise SystemExit("activation_blocked=verification_report_not_pass")
active_target = root / "00_project_control/active_decision_state.yaml"
inhibit_target = root / "07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json"
active = json.loads(active_target.read_text())
inhibit = json.loads(inhibit_target.read_text())
assert active["current_workflow"] == "daily_decision"
assert active["active_pipeline"] == "phase5r_daily"
assert active["email_delivery_allowed_from"] == "phase5r_daily_only"
assert inhibit["active"] is True
assert inhibit["allowed_pipeline"] == "none"
now = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
inhibit.update(
    {
        "active": False,
        "allowed_pipeline": "phase5r_daily",
        "reason": "phase5r_daily_upgrade_verified",
        "cleared_at": now,
    }
)
active.update(
    {
        "generated_at": now,
        "daily_pipeline_status": "operational_scheduled",
        "d3_maintenance_inhibit": "inactive",
    }
)
for target, payload in ((inhibit_target, inhibit), (active_target, active)):
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
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

log_target = root / "00_project_control/run_logs/phase5r_daily_activation_log.csv"
fields = [
    "timestamp", "action", "result", "operational_from", "email_attempted",
    "email_sent", "c7_invoked", "smtp_config_read", "smtp_config_modified",
    "broker_connected", "broker_account_read", "order_code_created",
]
exists = log_target.exists() and log_target.stat().st_size > 0
with log_target.open("a", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    if not exists:
        writer.writeheader()
    writer.writerow(
        {
            "timestamp": now,
            "action": "activate_daily_schedulers_after_protected_verification",
            "result": "passed",
            "operational_from": active["operational_from"],
            "email_attempted": "no",
            "email_sent": "no",
            "c7_invoked": "no",
            "smtp_config_read": "no",
            "smtp_config_modified": "no",
            "broker_connected": "no",
            "broker_account_read": "no",
            "order_code_created": "no",
        }
    )
    handle.flush()
    os.fsync(handle.fileno())
print(f"daily_activation=passed operational_from={active['operational_from']}")
PY

/usr/bin/printf '%s\n' \
    "email_attempted=false" \
    "c7_invoked=false" \
    "smtp_config_read=false" \
    "smtp_config_modified=false"
