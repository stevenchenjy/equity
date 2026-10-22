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
does not turn the workflow into a cloud service or replace Codex for analyst
work. An unavailable host retains missed-slot evidence and existing late-send
prohibitions. On resumption it must not replay expired analysis or renew
trading instructions. Actual live claims, completion receipts and exact
SMTP archives remain necessary to prove research and delivery.
