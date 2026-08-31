# Phase 5R-D1 Mac Scheduler Policy

## Purpose

Phase 5R-D1 defines a local macOS `launchd` agent that invokes the existing Phase 5R-C3 daily email pipeline once per weekday at 9:05 AM in the Mac's local timezone.

## Schedule Boundary

- Monday through Friday only.
- One calendar event per weekday at `09:05` local time.
- No weekend entries.
- `RunAtLoad=false`, so installation does not immediately run the pipeline.
- `KeepAlive=false` and no interval timer, so the agent does not create retries or repeated notifications.
- macOS may coalesce a calendar event missed while the Mac is asleep and run it after wake; it does not run every missed occurrence.

## Execution Boundary

- The launch agent invokes only `/Users/messssi/Desktop/equity/09_scripts/phase5r/run_phase5r_c3_daily_email_pipeline.py` through the project's current absolute Python interpreter.
- Each scheduled invocation delegates the complete research and one-email boundary to C3.
- Standard output and error are written only to the designated project log files.
- The scheduler does not read or modify SMTP configuration and does not contain credentials.

## Safety Boundary

- No intraday alerts, repeated notifications, every-15-minute scans, broker connectivity, order placement, or trade execution.
- No archived legacy input or legacy holding data.
- No cloud deployment and no Phase 5R-E artifacts.
