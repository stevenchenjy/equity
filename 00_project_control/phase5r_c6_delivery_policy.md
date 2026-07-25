# Phase 5R-C6 Delivery Policy

## Manual Delivery

The C6 sender is a manual command. Default mode may send one weekly brief to the single recipient in the existing local Gmail SMTP configuration.

```text
python3 09_scripts/phase5r/send_phase5r_c6_weekly_email.py
```

Non-sending modes:

```text
python3 09_scripts/phase5r/send_phase5r_c6_weekly_email.py --dry-run
python3 09_scripts/phase5r/send_phase5r_c6_weekly_email.py --check-config
```

## Credential Boundary

- The local SMTP configuration is read only by the sender.
- The SMTP app password is held in memory only for authentication in default mode.
- The password is never written to status, preview, run-log, or report artifacts.
- Error text is redacted before logging.
- The local configuration is not modified.

## Delivery Boundary

- Gmail SMTP with STARTTLS on port 587.
- One recipient from local configuration.
- At most one message per run.
- Multipart plain-text and HTML alternatives only.
- No attachments, broker access, scheduler, repeated delivery, or automated portfolio action.
