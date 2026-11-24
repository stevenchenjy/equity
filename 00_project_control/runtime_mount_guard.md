# External runtime reconnect guard

The alternative host uses external APFS volume
`16FE77BD-4FA7-4F45-A81D-FAB0E8DF065D` as the real production mount at
`/Users/messssi/LocalRuntime/equity`. A one-shot `diskutil mount -mountPoint`
does not register that location for future reconnects; ordinary mounting uses
`/Volumes`. An administrator-maintained UUID entry through `vifs` remains a
system-level alternative. This user-level guard requires no new privileges.

The maintained source is `07_automation/scheduler/runtime_mount_guard.py`. The
reviewed copy must be installed on the internal disk at
`/Users/messssi/Library/Application Support/EquityResearch/bin/runtime_mount_guard.py`
with owner-only executable mode 0700. Its matching LaunchAgent template runs the
Framework Python from the internal Application Support directory, with
`--ensure`, `RunAtLoad`, `StartOnMount` and a 60-second interval. It does not
depend on code or a working directory on the disconnected SSD. Installation and
a real controlled reconnect test are separate acceptance steps; source tests
alone do not establish that macOS has granted a background mount operation.

For an entirely read-only metadata check, run the installed guard with
`--check`. It does not create or change a lock, receipt, target or mount. The CLI
has no UUID/path override. `--ensure` is explicit and each attempt is bounded
to 50 seconds, with info/unmount/mount subprocess limits of 5/15/15 seconds.

Correct canonical mounting is a no-op, even during an active research run.
A missing SSD retries later. Relocation requires the existing nonblocking
`/Users/messssi/LocalRuntime/.locks/equity-research-runtime.lock`; the guard
neither creates a substitute lock nor rewrites its content. Under that lock it
revalidates the exact external APFS volume and its current device identifier,
rejects unsafe/symlinked or occupied targets, normally unmounts the volume if
necessary, resolves the UUID again, and mounts the freshly verified device.
It never uses force-unmount, a fixed disk number, another volume, a symlink
workaround or a copied private workspace. A busy unmount leaves the existing
mount in place and retries. A failed mount may leave the identified volume
unmounted; a later bounded attempt observes its state again.

Private current status is stored with mode 0600 at
`/Users/messssi/Library/Application Support/EquityResearch/runtime_mount_guard.local.json`.
It records only fixed reason codes and mount metadata; unchanged semantic state
does not rewrite that receipt or produce another normal log line. The receipt's
clock is its last state change, not a continuous heartbeat. Use a current
`--check` and launchd metadata to distinguish a stable state from a missing host.

The guard invokes no Git, runtime, credential, scheduler, sender, account,
trading or power code. It does not enable/restart other jobs. Existing canonical
path and source guards remain authoritative, and fresh full-pipeline, account
publication and delivery receipts remain necessary after recovery. User logout,
sleep, missing/unavailable media or Disk Arbitration denial can still prevent
timely recovery; this guard does not create a cloud service or hardware wake.

The host's `diskutil(8)`, `fstab(5)` and `launchd.plist(5)` manuals define the
UUID lookup, normal unmount/custom mountpoint and launch triggers used here.

## Review and removal

Before replacing the installed copy, compare its bytes with the reviewed source
and run its `--check`. A controlled reconnect test must wait until research and
deployment have released the runtime lock. Inspect the private receipt and exact
UUID/mountpoint afterwards; a correct mount alone does not prove fresh research.

To remove only this guard, wait until it is idle, then unload its separate label
and remove only the installed guard helper and plist:

```sh
/bin/launchctl bootout "gui/$(/usr/bin/id -u)/com.steven.equity_research.mountguard"
/bin/rm -- "/Users/messssi/Library/LaunchAgents/com.steven.equity_research.mountguard.plist" "/Users/messssi/Library/Application Support/EquityResearch/bin/runtime_mount_guard.py"
```

Confirm that the mountguard label is unloaded before removing its files. Leave
the four research/delivery agents, mounted SSD, private workspace records and
canonical path guards intact. Retain the local status receipt and logs as audit
evidence; removal does not relocate or unmount the volume.
