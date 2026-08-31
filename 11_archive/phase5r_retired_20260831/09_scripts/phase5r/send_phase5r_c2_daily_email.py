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
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_c2_run_log.csv"

CONFIG_PATH = DELIVERY_DIR / "phase5r_email_config.local.json"
SUBJECT_PATH = BRIEF_DIR / "phase5r_c1_daily_email_subject.txt"
TEXT_PATH = BRIEF_DIR / "phase5r_c1_daily_email_body.txt"
HTML_PATH = BRIEF_DIR / "phase5r_c1_daily_email_body.html"
METADATA_PATH = BRIEF_DIR / "phase5r_c1_email_brief_metadata.csv"
STATUS_PATH = DELIVERY_DIR / "phase5r_c2_delivery_status.csv"
PREVIEW_PATH = DELIVERY_DIR / "phase5r_c2_last_email_preview.eml"

REQUIRED_CONFIG_KEYS = {
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_app_password",
    "recipient_email",
    "sender_name",
}
LEGACY_TICKERS = {"IOT", "RBRK"}
LEGACY_PIPELINE_RETIRED = True
STATUS_FIELDS = [
    "timestamp",
    "mode",
    "subject",
    "smtp_username",
    "recipient_email",
    "sent",
    "error_type",
    "error_message_redacted",
    "source_subject_path",
    "source_text_path",
    "source_html_path",
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
    if LEGACY_PIPELINE_RETIRED:
        raise ConfigError("legacy_pipeline_retired")
    if not CONFIG_PATH.exists():
        raise ConfigError("local SMTP configuration file is missing")
    try:
        with CONFIG_PATH.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("local SMTP configuration could not be parsed") from exc
    if not isinstance(config, dict):
        raise ConfigError("local SMTP configuration must be an object")
    missing = sorted(REQUIRED_CONFIG_KEYS - set(config))
    if missing:
        raise ConfigError("local SMTP configuration is missing required fields")
    if config["smtp_host"] != "smtp.gmail.com":
        raise ConfigError("SMTP host must be smtp.gmail.com")
    if config["smtp_port"] != 587:
        raise ConfigError("SMTP port must be 587")
    config["smtp_username"] = safe_email(config["smtp_username"], "smtp_username")
    config["recipient_email"] = safe_email(config["recipient_email"], "recipient_email")
    config["sender_name"] = safe_header_value(config["sender_name"], "sender_name")
    config["smtp_app_password"] = safe_header_value(config["smtp_app_password"], "smtp_app_password")
    return config


def read_metadata() -> dict[str, str]:
    if not METADATA_PATH.exists():
        raise ValueError("C1 metadata is missing")
    with METADATA_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1 or rows[0].get("send_allowed") != "no" or rows[0].get("delivery_phase") != "phase5r_c1_compose_only":
        raise ValueError("C1 metadata does not describe a compose-only brief")
    return rows[0]


def read_brief() -> tuple[str, str, str]:
    read_metadata()
    for path in (SUBJECT_PATH, TEXT_PATH, HTML_PATH):
        if not path.exists():
            raise ValueError("required C1 email brief input is missing")
    subject = SUBJECT_PATH.read_text(encoding="utf-8").strip()
    text_body = TEXT_PATH.read_text(encoding="utf-8")
    html_body = HTML_PATH.read_text(encoding="utf-8")
    if not subject or not text_body.strip() or not html_body.strip():
        raise ValueError("C1 email brief contains an empty required component")
    combined = " ".join((subject, text_body, html_body)).upper()
    if any(ticker in combined for ticker in LEGACY_TICKERS):
        raise ValueError("legacy holding content is excluded from C2 delivery")
    return subject, text_body, html_body


def build_message(config: dict[str, object], subject: str, text_body: str, html_body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{config['sender_name']} <{config['smtp_username']}>"
    message["To"] = str(config["recipient_email"])
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def write_preview(message: EmailMessage) -> None:
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.write_bytes(message.as_bytes())


def redact_error(exc: Exception, config: dict[str, object] | None = None) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")
    if config:
        password = str(config.get("smtp_app_password", ""))
        if password:
            text = text.replace(password, "[REDACTED]")
    return (text or "delivery failed safely")[:240]


def append_status(
    mode: str,
    subject: str,
    config: dict[str, object] | None,
    sent: str,
    error_type: str = "",
    error_message_redacted: str = "",
) -> None:
    row = {
        "timestamp": timestamp(),
        "mode": mode,
        "subject": subject,
        "smtp_username": str(config.get("smtp_username", "")) if config else "",
        "recipient_email": str(config.get("recipient_email", "")) if config else "",
        "sent": sent,
        "error_type": error_type,
        "error_message_redacted": error_message_redacted,
        "source_subject_path": str(SUBJECT_PATH.relative_to(ROOT)) if mode != "check_config" else "",
        "source_text_path": str(TEXT_PATH.relative_to(ROOT)) if mode != "check_config" else "",
        "source_html_path": str(HTML_PATH.relative_to(ROOT)) if mode != "check_config" else "",
    }
    for path in (STATUS_PATH, RUN_LOG):
        path.parent.mkdir(parents=True, exist_ok=True)
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=STATUS_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send one Phase 5R-C1 daily research brief through Gmail SMTP.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Compose a local preview without connecting to SMTP.")
    mode.add_argument("--check-config", action="store_true", help="Validate the local SMTP configuration without connecting to SMTP.")
    return parser.parse_args()


def main() -> int:
    if LEGACY_PIPELINE_RETIRED:
        print(
            "legacy_pipeline_retired=true component=phase5r_c2 "
            "smtp_config_read=false email_attempted=false"
        )
        return 3
    args = parse_args()
    mode = "check_config" if args.check_config else "dry_run" if args.dry_run else "send"
    try:
        config = load_config()
    except ConfigError as exc:
        append_status(mode, "", None, "no", exc.__class__.__name__, "configuration validation failed")
        print("Configuration validation failed safely; see the delivery status CSV.")
        return 1

    if args.check_config:
        append_status("check_config", "", config, "no")
        print("SMTP configuration check passed; no email was sent.")
        return 0

    try:
        subject, text_body, html_body = read_brief()
        message = build_message(config, subject, text_body, html_body)
        write_preview(message)
    except Exception as exc:
        append_status(mode, "", config, "no", exc.__class__.__name__, redact_error(exc, config))
        print("Brief composition failed safely; see the delivery status CSV.")
        return 1

    if args.dry_run:
        append_status("dry_run", subject, config, "no")
        print("Dry run complete; no email was sent.")
        return 0

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as client:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
            client.login(str(config["smtp_username"]), str(config["smtp_app_password"]))
            client.send_message(message, from_addr=str(config["smtp_username"]), to_addrs=[str(config["recipient_email"])])
        append_status("send", subject, config, "yes")
        print("Daily research brief email sent.")
        return 0
    except Exception as exc:
        append_status("send", subject, config, "no", exc.__class__.__name__, redact_error(exc, config))
        print("Email delivery failed safely; see the delivery status CSV.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
