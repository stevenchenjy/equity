# Phase 5R-C2 Gmail SMTP Setup

## Local Configuration

Create or maintain this local-only file:

`07_automation/email_delivery/phase5r_email_config.local.json`

It is ignored by Git. Use `phase5r_email_config.template.json` as the schema reference and place the Gmail app password only in the local file.

Required values:

- `smtp_host`: `smtp.gmail.com`
- `smtp_port`: `587`
- `smtp_username`: dedicated Gmail sender address
- `smtp_app_password`: Gmail app password
- `recipient_email`: exactly one intended recipient
- `sender_name`: display name for the daily research brief

## Safe Checks

Validate the file without sending a message:

```bash
python3 09_scripts/phase5r/send_phase5r_c2_daily_email.py --check-config
```

Compose the latest C1 brief locally without connecting to SMTP:

```bash
python3 09_scripts/phase5r/send_phase5r_c2_daily_email.py --dry-run
```

## Live Delivery

Running the sender without options composes and sends exactly one message to the recipient in the local configuration file:

```bash
python3 09_scripts/phase5r/send_phase5r_c2_daily_email.py
```

The sender uses Gmail SMTP with STARTTLS. It does not use the Gmail API, OAuth, attachments, a scheduler, or a recipient override.
