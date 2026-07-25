from __future__ import annotations

import argparse
import csv
import json
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BRIEF_DIR = ROOT / "07_automation" / "email_briefs"
DELIVERY_DIR = ROOT / "07_automation" / "email_delivery"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_c6_run_log.csv"
ACTIVE_STATE = ROOT / "00_project_control" / "active_decision_state.yaml"

CONFIG_PATH = DELIVERY_DIR / "phase5r_email_config.local.json"
SUBJECT_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_subject.txt"
TEXT_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_body.txt"
HTML_PATH = BRIEF_DIR / "phase5r_c6_weekly_email_body.html"
METADATA_PATH = BRIEF_DIR / "phase5r_c6_email_metadata.csv"
STATUS_PATH = DELIVERY_DIR / "phase5r_c6_delivery_status.csv"
PREVIEW_PATH = DELIVERY_DIR / "phase5r_c6_last_email_preview.eml"

REQUIRED_CONFIG_KEYS = {
    "smtp_host", "smtp_port", "smtp_username", "smtp_app_password", "recipient_email", "sender_name",
}
STATUS_FIELDS = [
    "timestamp", "mode", "subject", "smtp_username", "recipient_email", "sent", "message_count",
    "error_type", "error_message_redacted", "primary_scenario", "source_subject_path",
    "source_text_path", "source_html_path", "attachments",
]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "mode", "status", "subject",
    "smtp_username", "recipient_email", "sent", "message_count", "input_paths",
    "output_paths", "error_type", "error_message_redacted", "broker_used",
    "scheduler_used", "archived_legacy_used", "safety_notes",
]


class ConfigError(ValueError):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_header_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\r" in value or "\n" in value:
        raise ConfigError(f"{field} is invalid")
    return value.strip()


def safe_email(value: object, field: str) -> str:
    text = safe_header_value(value, field)
    if text.count("@") != 1 or text.startswith("@") or text.endswith("@") or " " in text:
        raise ConfigError(f"{field} is invalid")
    return text


def load_config() -> dict[str, object]:
    if not CONFIG_PATH.exists():
        raise ConfigError("local SMTP configuration file is missing")
    try:
        with CONFIG_PATH.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("local SMTP configuration could not be parsed") from exc
    if not isinstance(config, dict) or REQUIRED_CONFIG_KEYS - set(config):
        raise ConfigError("local SMTP configuration is missing required fields")
    if config["smtp_host"] != "smtp.gmail.com" or config["smtp_port"] != 587:
        raise ConfigError("SMTP endpoint must be Gmail STARTTLS on port 587")
    config["smtp_username"] = safe_email(config["smtp_username"], "smtp_username")
    config["recipient_email"] = safe_email(config["recipient_email"], "recipient_email")
    config["sender_name"] = safe_header_value(config["sender_name"], "sender_name")
    config["smtp_app_password"] = safe_header_value(config["smtp_app_password"], "smtp_app_password")
    return config


def active_primary_scenario() -> str:
    try:
        state = json.loads(ACTIVE_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("active decision state is invalid") from exc
    if (
        not isinstance(state, dict)
        or state.get("current_workflow") != "weekly_conviction"
        or state.get("active_pipeline") != "phase5r_c7"
        or state.get("email_delivery_allowed_from") != "phase5r_c7_only"
        or state.get("broker_connection_allowed") != "no"
        or state.get("order_code_allowed") != "no"
    ):
        raise ValueError("active decision state does not authorize C6 delivery")
    selected = str(state.get("primary_decision", "")).strip()
    if not selected:
        raise ValueError("active decision state has no primary scenario")
    return selected


def read_metadata(expected_scenario: str) -> dict[str, str]:
    with METADATA_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError("C6 metadata must contain one row")
    row = rows[0]
    if row.get("primary_scenario") != expected_scenario or row.get("send_allowed") != "manual_command_only" or row.get("delivery_phase") != "phase5r_c6_weekly_manual_send":
        raise ValueError("C6 metadata does not authorize a manual weekly send")
    return row


def read_brief(expected_scenario: str) -> tuple[str, str, str]:
    read_metadata(expected_scenario)
    for path in (SUBJECT_PATH, TEXT_PATH, HTML_PATH):
        if not path.exists():
            raise ValueError("required C6 weekly brief input is missing")
    subject = SUBJECT_PATH.read_text(encoding="utf-8").strip()
    text_body = TEXT_PATH.read_text(encoding="utf-8")
    html_body = HTML_PATH.read_text(encoding="utf-8")
    if not subject or not text_body.strip() or not html_body.strip():
        raise ValueError("C6 weekly brief contains an empty component")
    if f"Primary scenario: {expected_scenario}." not in text_body:
        raise ValueError("C6 weekly brief is missing the primary scenario")
    return subject, text_body, html_body


def build_message(config: dict[str, object], subject: str, text_body: str, html_body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{config['sender_name']} <{config['smtp_username']}>"
    message["To"] = str(config["recipient_email"])
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def ensure_secret_absent(config: dict[str, object], *values: str) -> None:
    secret = str(config.get("smtp_app_password", ""))
    if secret and any(secret in value for value in values):
        raise RuntimeError("sensitive value blocked from output")


def write_preview(message: EmailMessage, config: dict[str, object]) -> None:
    preview = message.as_bytes()
    ensure_secret_absent(config, preview.decode("utf-8", errors="replace"))
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.write_bytes(preview)


def redact_error(exc: Exception, config: dict[str, object] | None = None) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")
    if config:
        secret = str(config.get("smtp_app_password", ""))
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return (text or "delivery failed safely")[:240]


def append_status(
    mode: str,
    subject: str,
    config: dict[str, object] | None,
    sent: str,
    message_count: str,
    primary_scenario: str,
    error_type: str = "",
    error_message_redacted: str = "",
) -> None:
    status_row = {
        "timestamp": timestamp(), "mode": mode, "subject": subject,
        "smtp_username": str(config.get("smtp_username", "")) if config else "",
        "recipient_email": str(config.get("recipient_email", "")) if config else "",
        "sent": sent, "message_count": message_count, "error_type": error_type,
        "error_message_redacted": error_message_redacted, "primary_scenario": primary_scenario,
        "source_subject_path": str(SUBJECT_PATH.relative_to(ROOT)) if mode != "check_config" else "",
        "source_text_path": str(TEXT_PATH.relative_to(ROOT)) if mode != "check_config" else "",
        "source_html_path": str(HTML_PATH.relative_to(ROOT)) if mode != "check_config" else "",
        "attachments": "none",
    }
    if config:
        ensure_secret_absent(config, json.dumps(status_row, sort_keys=True))
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    status_exists = STATUS_PATH.exists()
    with STATUS_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATUS_FIELDS)
        if not status_exists:
            writer.writeheader()
        writer.writerow(status_row)

    log_row = {
        "timestamp": status_row["timestamp"], "phase": "phase5r_c6", "script_name": Path(__file__).name,
        "action": "weekly_email_delivery", "mode": mode,
        "status": "complete" if not error_type else "failed", "subject": subject,
        "smtp_username": status_row["smtp_username"], "recipient_email": status_row["recipient_email"],
        "sent": sent, "message_count": message_count,
        "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [SUBJECT_PATH, TEXT_PATH, HTML_PATH, METADATA_PATH]) if mode != "check_config" else "local_smtp_config_shape_only",
        "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [STATUS_PATH, PREVIEW_PATH]) if mode != "check_config" else str(STATUS_PATH.relative_to(ROOT)),
        "error_type": error_type, "error_message_redacted": error_message_redacted,
        "broker_used": "no", "scheduler_used": "no", "archived_legacy_used": "no",
        "safety_notes": "weekly_manual_command=yes; at_most_one_message=yes; attachments=none; password_logged=no",
    }
    if config:
        ensure_secret_absent(config, json.dumps(log_row, sort_keys=True))
    log_exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not log_exists:
            writer.writeheader()
        writer.writerow(log_row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send one Phase 5R-C6 weekly conviction brief through Gmail SMTP.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Write a local preview without opening an SMTP connection.")
    mode.add_argument("--check-config", action="store_true", help="Validate local SMTP configuration without opening an SMTP connection.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = "check_config" if args.check_config else "dry_run" if args.dry_run else "send"
    try:
        primary_scenario = active_primary_scenario()
    except ValueError as exc:
        append_status(mode, "", None, "no", "0", "", exc.__class__.__name__, "active-state validation failed")
        print("Active-state validation failed safely; see the C6 delivery status.")
        return 1
    try:
        config = load_config()
    except ConfigError as exc:
        append_status(mode, "", None, "no", "0", primary_scenario, exc.__class__.__name__, "configuration validation failed")
        print("Configuration validation failed safely; see the C6 delivery status.")
        return 1

    if args.check_config:
        append_status("check_config", "", config, "no", "0", primary_scenario)
        print("C6 SMTP configuration check passed; no email was sent.")
        return 0

    try:
        subject, text_body, html_body = read_brief(primary_scenario)
        message = build_message(config, subject, text_body, html_body)
        write_preview(message, config)
    except Exception as exc:
        append_status(mode, "", config, "no", "0", primary_scenario, exc.__class__.__name__, redact_error(exc, config))
        print("C6 weekly brief composition failed safely; see the delivery status.")
        return 1

    if args.dry_run:
        append_status("dry_run", subject, config, "no", "0", primary_scenario)
        print("C6 dry run complete; no email was sent.")
        return 0

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as client:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
            client.login(str(config["smtp_username"]), str(config["smtp_app_password"]))
            client.send_message(message, from_addr=str(config["smtp_username"]), to_addrs=[str(config["recipient_email"])])
        append_status("send", subject, config, "yes", "1", primary_scenario)
        print("Weekly conviction brief sent once.")
        return 0
    except Exception as exc:
        append_status("send", subject, config, "no", "0", primary_scenario, exc.__class__.__name__, redact_error(exc, config))
        print("C6 delivery failed safely; see the delivery status.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
