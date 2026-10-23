# Local assessment host availability

The production Mac runs local research and delivery workers. A saved schedule
does not establish that its host was awake when a slot was due. On October 22,
2026, the macOS power log recorded repeated Maintenance Sleep and DarkWake
transitions during both brief windows, despite the existing AC `sleep=0`
setting. The delivery ledger contained no October 22 SMTP claim or completion.
The morning sender also exhausted its pre-SMTP process budget; source-bound
publication validation and host availability are separate repair requirements.
Its finite child-process allowance is now 180 seconds, with the same final
pre-claim window checks, immutable archives, durable claim and unknown-send
fences. This allowance does not extend the short assessment's ten-minute
analytical budget or authorize a late send.

The dedicated `com.steven.equity_research.sessionawake` LaunchAgent checks
the actual Eastern operating day every minute. On exchange trading days from
08:00 through 16:15 ET it holds a bounded AC `PreventSystemSleep` and idle-sleep
assertion using `/usr/bin/caffeinate -si -t SECONDS`. It leaves the display
alone. The guard's operating period covers the existing full reviews,
collection handoffs, brief windows and last short check; it changes none of
their due gates or expiry rules. Early closes retain availability for the
existing afternoon full review. Weekends and exchange holidays take no
assertion.

After a verified source deployment, install just this guard with:

```sh
/bin/zsh /Users/messssi/LocalRuntime/equity/07_automation/scheduler/install_session_awake.sh
```

This dedicated installer does not restart or invoke either delivery worker.
The ordinary complete scheduler installer also installs the guard for future
reinstallations. Its status check includes the guard, and ordinary scheduler
uninstallation releases it. Confirm the loaded label, matching installed
template and actual `pmset -g assertions` result; a launchd entry alone is not
proof that a power assertion was taken.

This local guard cannot promise service while the Mac is powered off, the
user is logged out, or deliberate manual sleep overrides an assertion. It
also cannot start at 08:00 if the Mac is already asleep overnight: a launchd
interval is not a hardware wake request. October 22 verification found no
owner repeating morning wake in `pmset -g sched`; configuring one was not
possible unattended because `sudo -n` required an administrator password.
Do not request or store that password. On the existing local route, leave the
Mac awake, logged in and Codex running, or have the owner configure a morning
system wake. The suggested owner-run command is:

```sh
sudo pmset repeat wake MTWRF 07:55:00
```

Re-read `pmset -g sched` first: `pmset repeat` replaces the repeating set, so
preserve any existing repeating owner requirements. This wake command does
not supply power-on, login or app-launch guarantees. Apple one-shot events
are separate. Future actual automatic claims and sends remain unverified
until their receipts exist.

The guard
does not turn the workflow into a cloud service or replace Codex for analyst
work. An unavailable host retains missed-slot evidence and existing late-send
prohibitions. On resumption it must not replay expired analysis or renew
trading instructions. Actual live claims, completion receipts and exact
SMTP archives remain necessary to prove research and delivery.

## Deadline-bound delivery resource class

October 23 live verification found a second, independent cause of missed
morning delivery: the delivery LaunchAgent used the Darwin background resource
class. Three installed attempts exhausted the 180-second allowance before a
durable SMTP claim. A read-only reproduction of the same five validation
stages took 197.516 seconds in that class and 39.572 seconds at ordinary
priority; both validated the same publication. The host was awake with the
operating-day power assertion active.

The delivery agent therefore uses `ProcessType=Standard`. The refresh worker
keeps its existing background class. The existing 180-second sender bound,
actual pre-claim window checks, immutable publication validation, duplicate
protection and unknown-send fences remain effective. A successful validation
or deployed agent is not evidence of SMTP acceptance.

The delivery agent has `RunAtLoad=false` and retains `StartInterval=900`.
Installing or logging in does not immediately invoke the sender; its first
normal poll can occur up to 15 minutes later. Use the dedicated delivery-agent
installer only while that job is idle. It synchronizes through the existing
runtime procedure, checks the exact no-immediate-run template and reloads only
this agent. It does not restart the refresh worker or replay a closed brief
window. The normal scheduler continues to own both mandatory briefs and only
otherwise eligible action or priority alerts.

```sh
/bin/zsh /Users/messssi/LocalRuntime/equity/07_automation/scheduler/install_dailydecision_scheduler.sh
```

Verify the actual loaded resource class, unchanged interval and subsequent
natural run receipts. Preserve any missed morning outcome; this repair does
not authorize a late catch-up message.
