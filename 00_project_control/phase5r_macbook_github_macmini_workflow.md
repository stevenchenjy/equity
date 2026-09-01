# Phase5R MacBook → GitHub → Mac mini workflow

## Production boundary

| Role | Path or service | Purpose |
|---|---|---|
| MacBook / iCloud authoring | `/Users/messssi/Desktop/equity` | Normal editing, Codex work, commits, and pushes |
| GitHub | `stevenchenjy/equity`, branch `main` | Authoritative committed code history |
| Mac mini iCloud copy | `/Users/messssi/Desktop/equity` | Authoring/reference copy only; never a scheduled runtime |
| Mac mini production runtime | `/Users/messssi/LocalRuntime/equity` | Authoritative scheduled execution working copy |

The runtime clone has its own `.git` directory and mutable files. Nothing in
it is symlinked to Desktop, Documents, Mobile Documents, CloudStorage, or the
safety snapshot. iCloud synchronization is not a deployment mechanism.

## Normal authoring and deployment

On the MacBook or the Mac mini authoring copy:

```bash
cd /Users/messssi/Desktop/equity
git status
git add <reviewed-paths>
git commit
git push origin main
```

Do not edit the production runtime to author code. Each production
LaunchAgent invokes the shared wrapper:

```text
/Users/messssi/LocalRuntime/equity/09_scripts/phase5r/run_phase5r_runtime_scheduler.py
```

The wrapper obtains
`/Users/messssi/LocalRuntime/.locks/equity-phase5r-runtime.lock` before it
inspects Git. The same advisory `flock` remains open through the scheduler
process, including any normal child pipeline. This serializes both schedulers
and prevents a later scheduled invocation from changing checked-out code
under an active run. A normal exit or crash closes the file descriptor, so no
stale PID file can permanently block execution. Because both LaunchAgents have
the same 900-second cadence, a contending invocation waits up to one hour for
the bounded active run to release the lock. It then evaluates its own cumulative
due state immediately instead of discarding the check and waiting another 15
minutes. A one-hour timeout is reported explicitly as an abnormal stuck-holder
condition; it does not mark a refresh slot complete or consume a decision
attempt. If a contended handoff or preflight crosses the ET cycle-date boundary,
the wrapper also fails explicitly and records that condition instead of letting
the scheduler silently reinterpret the queued check as a new day's work. The
wrapper passes the expected ET date through `exec`, and each production
scheduler validates it before reading or writing due state, closing the final
process-start boundary.

While holding the lock, the wrapper verifies all of the following:

1. the runtime is a normal clone with a private `.git` directory;
2. the top-level directory, `main` branch, `origin/main` upstream, and exact
   GitHub origin are correct;
3. code, configuration, and every non-evidence path are clean; the only
   permitted working-tree changes are append-only SEC ledger/audit/
   reconciliation rows and strictly named versioned acceptance extensions
   whose complete hash chain and audit bindings validate;
4. `origin/main` can be fetched non-interactively;
5. local and remote ancestry is safe.

If HEADs are equal, execution continues, including when the validated runtime
SEC evidence allowlist contains a new append. If local `main` is strictly
behind and no runtime evidence needs preservation, Git advances it with
`git merge --ff-only`; this cannot create a merge commit or perform a content
merge. A newer remote commit plus local runtime evidence fails with
`runtime_evidence_reconciliation_required` so an operator can first preserve
that evidence in authoring history. Any local-ahead or divergent history is
blocked. The implementation never invokes reset, clean, stash, rebase,
checkout, force-push, or a non-fast-forward merge.

Before starting the scheduler, the wrapper durably records the job and exact
commit in ignored local file
`00_project_control/run_logs/phase5r_runtime_execution_log.csv`. The runtime
lock and this ledger are not committed.

## Failure behavior

| Condition | Result |
|---|---|
| GitHub has a newer descendant commit | Fast-forward, revalidate clean state, record the new commit, run |
| Valid append-only SEC evidence exists and HEAD equals `origin/main` | Validate file safety, extension hashes, chain continuity, and audit bindings; then run without altering HEAD |
| GitHub advanced while validated runtime SEC evidence is pending | Fetch the remote-tracking ref, leave local HEAD/worktree unchanged, and require explicit evidence reconciliation |
| Any other tracked file is dirty, a permitted evidence file rewrites prior bytes, or an unknown untracked file exists | Fail closed before fetch; do not run |
| Runtime is ahead or histories diverge | Fetch the remote-tracking ref, leave local HEAD/worktree unchanged, do not run |
| Another run holds the runtime lock | Wait for the active bounded run, acquire the same lock, then evaluate this job's due state; after one abnormal hour, exit 75 with `runtime_lock_wait_timeout` without changing due state |
| Lock handoff or preflight crosses midnight ET | Fail closed with an explicit cycle-date error and do not reinterpret the prior check as current-day work |
| GitHub, DNS, or authentication is unavailable | Exit with `git_fetch_failed`; do not run stale code |
| Origin, branch, upstream, root, or `.git` is unexpected | Fail closed and do not run |

Failures go to the existing per-agent launchd error logs and, when the local
ledger can be opened safely, a fixed failure code is appended there. No
credential value is logged.

The wrapper intentionally excludes Git-ignored files from its status check.
That is what lets scheduler state, logs, market/evidence snapshots, decisions,
email briefs, locks, and other mutable artifacts survive a fast-forward.
Non-ignored untracked files are rejected except for the exact versioned SEC
acceptance-extension filename pattern, and those extensions are accepted only
after full chain and audit validation. If a future tracked path would overwrite
a local ignored file, Git itself refuses the fast-forward and the wrapper fails
closed.

## Runtime operations

Safe checks (no fetch, pipeline, provider, SMTP send, broker access, or order):

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /Users/messssi/LocalRuntime/equity/09_scripts/phase5r/run_phase5r_runtime_scheduler.py \
  --job dailyrefresh --safe-check
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /Users/messssi/LocalRuntime/equity/09_scripts/phase5r/run_phase5r_runtime_scheduler.py \
  --job dailydecision --safe-check
```

Operator-requested sync without scheduler execution:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /Users/messssi/LocalRuntime/equity/09_scripts/phase5r/run_phase5r_runtime_scheduler.py \
  --job dailyrefresh --sync-only
```

Status:

```bash
/bin/zsh /Users/messssi/LocalRuntime/equity/07_automation/scheduler/check_phase5r_daily_scheduler_status.sh
```

Installed logs remain outside both repositories:

```text
/Users/messssi/Library/Logs/phase5r_dailyrefresh.out.log
/Users/messssi/Library/Logs/phase5r_dailyrefresh.err.log
/Users/messssi/Library/Logs/phase5r_dailydecision.out.log
/Users/messssi/Library/Logs/phase5r_dailydecision.err.log
```

Do not repair a dirty, ahead, or divergent production clone automatically.
Inspect it, preserve any evidence, and resolve it as an explicit maintenance
operation. The verified safety snapshot is not part of this workflow and must
remain untouched.

## Absolute-path audit

The two active daily plist templates and their installer/status tooling point
to `LocalRuntime`. Phase5R Python runtime paths derive `ROOT` from the checked
out script location and therefore work in both authoring and runtime clones.
Older `dailybrief`, `weeklyconviction`, `weeklycatchup`, and standalone
`llmshadow` plist templates are under
`11_archive/phase5r_retired_20260831/07_automation/scheduler/`. Those jobs are
retired/uninstalled, are rejected by the active status guards, and are not
production entrypoints.
