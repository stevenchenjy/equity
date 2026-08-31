# Phase 5R-C2 Email Delivery Policy

## Purpose

Phase 5R-C2 adds a direct Gmail SMTP delivery path for the local Phase 5R-C1 daily research brief. It remains a low-attention, one-message-per-manual-run workflow.

## Inputs and Delivery Scope

- The sender reads only the latest C1 subject, plain-text body, HTML body, metadata, and the local SMTP configuration file.
- The local configuration file is not copied, printed, or included in reports. Its app password is used only in memory for SMTP authentication.
- The sender builds one multipart alternative message with plain text and HTML parts. It does not attach files.
- The recipient is read only from the local configuration file; command-line recipient overrides are not supported.

## Modes

- Default: compose and send exactly one message through `smtp.gmail.com:587` using STARTTLS.
- `--dry-run`: compose and write the local `.eml` preview only; no SMTP connection is opened.
- `--check-config`: validate the local configuration only; no SMTP connection is opened.

## Boundary

- No broker, transaction-placement, scheduler, intraday alert, repeated-notification, Gmail API, OAuth, attachment, or archived-legacy workflow is included.
- Delivery status and run logs contain only the documented fields and redact failure details that could contain the app password.
- Phase 5R-C3 is outside this phase.
