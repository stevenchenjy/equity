#!/usr/bin/env python3
"""Send at most one Phase 5R daily brief for an ET calendar date."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import stat
from email.message import EmailMessage
from typing import Any, Callable

from phase5r_active_config import load_active_config
from phase5r_daily_common import (
    DAILY_BRIEF_HTML_PATH,
    DAILY_BRIEF_TEXT_PATH,
    DAILY_DECISION_JSON_PATH,
    DAILY_DELIVERY_LEDGER_PATH,
    DAILY_DELIVERY_LOCK_PATH,
    EMAIL_CONFIG_PATH,
    ExclusiveFileLock,
    append_csv_durable,
    cycle_date,
    delivery_guard,
    iso_now,
    log_daily_run,
    notification_delivery_policy,
    now_et,
    read_csv,
    read_json,
    sha256_file,
)


BLOCKING_DELIVERY_STATUSES = {"send_claimed", "sent", "delivery_unknown"}
REQUIRED_CONFIG_KEYS = {
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_app_password",
    "recipient_email",
    "sender_name",
}
LEDGER_FIELDS = [
    "timestamp",
    "cycle_date",
    "status",
    "reason",
    "decision_fingerprint",
    "decision_sha256",
    "brief_text_sha256",
    "brief_html_sha256",
    "message_count",
    "email_attempted",
    "email_sent",
    "smtp_config_read",
    "broker_connected",
    "broker_account_read",
    "order_code_created",
]


class ConfigError(ValueError):
    pass


def safe_header(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field}_invalid")
    if "\r" in value or "\n" in value:
        raise ConfigError(f"{field}_invalid")
    return value.strip()


def safe_email(value: Any, field: str) -> str:
    text = safe_header(value, field)
    if text.count("@") != 1 or text.startswith("@") or text.endswith("@") or " " in text:
        raise ConfigError(f"{field}_invalid")
    return text


def load_config() -> dict[str, Any]:
    """Open SMTP configuration only after eligibility and dedupe gates pass."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise ConfigError("smtp_config_secure_open_unavailable")
    descriptor = -1
    try:
        descriptor = os.open(
            EMAIL_CONFIG_PATH,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ConfigError("smtp_config_permissions_invalid")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            config = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError("smtp_config_missing") from exc
    except ConfigError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("smtp_config_unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(config, dict) or REQUIRED_CONFIG_KEYS - set(config):
        raise ConfigError("smtp_config_fields_missing")
    if config.get("smtp_host") != "smtp.gmail.com" or config.get("smtp_port") != 587:
        raise ConfigError("smtp_endpoint_not_allowed")
    config["smtp_username"] = safe_email(config["smtp_username"], "smtp_username")
    config["recipient_email"] = safe_email(config["recipient_email"], "recipient_email")
    config["sender_name"] = safe_header(config["sender_name"], "sender_name")
    config["smtp_app_password"] = safe_header(
        config["smtp_app_password"], "smtp_app_password"
    )
    return config


def cycle_is_blocked(
    rows: list[dict[str, str]], target_cycle: str
) -> tuple[bool, str]:
    statuses = {
        row.get("status", "").strip()
        for row in rows
        if row.get("cycle_date", "").strip() == target_cycle
    }
    blocked = sorted(statuses & BLOCKING_DELIVERY_STATUSES)
    return (bool(blocked), blocked[0] if blocked else "")


def delivery_policy(
    *,
    is_weekend: bool,
    material_event: bool,
    decision_changed: bool,
    account_conflict: bool,
    weekly_summary_due: bool = False,
    fundamental_weakening: bool = False,
    first_material_baseline: bool = False,
) -> tuple[bool, str]:
    return notification_delivery_policy(
        is_weekend=is_weekend,
        weekly_summary_due=weekly_summary_due,
        material_event=material_event,
        decision_changed=decision_changed,
        account_conflict=account_conflict,
        fundamental_weakening=fundamental_weakening,
        first_material_baseline=first_material_baseline,
    )


def validate_decision() -> dict[str, Any]:
    decision = read_json(DAILY_DECISION_JSON_PATH)
    if decision.get("cycle_date") != cycle_date():
        raise ValueError("decision_cycle_mismatch")
    if decision.get("automatic_action_allowed") is not False:
        raise ValueError("automatic_action_boundary_invalid")
    list_fields = (
        "material_events",
        "account_conflicts",
        "eligible_action_review_candidates",
        "eligible_new_position_review_candidates",
    )
    if any(not isinstance(decision.get(field), list) for field in list_fields):
        raise ValueError("decision_notification_inputs_invalid")
    fundamental_gate = decision.get("fundamental_gate")
    evaluation = decision.get("notification_policy_evaluation")
    if not isinstance(fundamental_gate, dict) or not isinstance(evaluation, dict):
        raise ValueError("decision_notification_inputs_invalid")
    weakening_tickers = fundamental_gate.get("weakening_tickers")
    if not isinstance(weakening_tickers, list):
        raise ValueError("decision_notification_inputs_invalid")
    prior_decision_present = evaluation.get("prior_decision_present")
    if type(prior_decision_present) is not bool:
        raise ValueError("decision_notification_inputs_invalid")
    base_trigger = bool(
        decision["eligible_action_review_candidates"]
        or decision["eligible_new_position_review_candidates"]
        or decision["account_conflicts"]
        or decision["material_events"]
        or weakening_tickers
    )
    first_material_baseline = bool(not prior_decision_present and base_trigger)
    current = now_et()
    expected_evaluation = {
        "is_weekend": current.weekday() >= 5,
        "weekly_summary_due": current.weekday() == 4,
        "prior_decision_present": prior_decision_present,
        "first_material_baseline": first_material_baseline,
        "long_term_fundamental_weakening": bool(weakening_tickers),
        "scheduler_time_gate_applied": False,
    }
    if evaluation != expected_evaluation:
        raise ValueError("decision_notification_evaluation_mismatch")
    config = load_active_config()
    expected_notification_policy = {
        "event_driven": config["notifications"]["event_driven"],
        "weekly_summary_weekday": config["notifications"][
            "weekly_summary_weekday"
        ],
        "unchanged_daily_email": config["notifications"][
            "unchanged_daily_email"
        ],
    }
    if decision.get("notification_policy") != expected_notification_policy:
        raise ValueError("decision_notification_policy_mismatch")
    policy_send, policy_reason = delivery_policy(
        is_weekend=expected_evaluation["is_weekend"],
        weekly_summary_due=expected_evaluation["weekly_summary_due"],
        material_event=bool(decision["material_events"]),
        decision_changed=decision.get("decision_changed") is True,
        account_conflict=bool(decision["account_conflicts"]),
        fundamental_weakening=bool(weakening_tickers),
        first_material_baseline=first_material_baseline,
    )
    if decision.get("send_recommended") is not policy_send:
        raise ValueError("decision_delivery_policy_mismatch")
    if decision.get("send_reason") != policy_reason:
        raise ValueError("decision_delivery_reason_mismatch")
    boundaries = decision.get("boundaries", {})
    if any(
        boundaries.get(key) is not False
        for key in (
            "broker_connected",
            "broker_account_read",
            "order_code_created",
            "trade_placed",
        )
    ):
        raise ValueError("prohibited_action_boundary_invalid")
    if not DAILY_BRIEF_TEXT_PATH.exists() or not DAILY_BRIEF_HTML_PATH.exists():
        raise ValueError("daily_brief_missing")
    if not DAILY_BRIEF_TEXT_PATH.read_text(encoding="utf-8").strip():
        raise ValueError("daily_text_brief_empty")
    if not DAILY_BRIEF_HTML_PATH.read_text(encoding="utf-8").strip():
        raise ValueError("daily_html_brief_empty")
    return decision


def build_message(config: dict[str, Any], decision: dict[str, Any]) -> EmailMessage:
    headline = safe_header(decision.get("headline"), "headline")
    subject = f"[Phase 5R] {headline} — {cycle_date()}"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{config['sender_name']} <{config['smtp_username']}>"
    message["To"] = config["recipient_email"]
    message.set_content(DAILY_BRIEF_TEXT_PATH.read_text(encoding="utf-8"))
    message.add_alternative(
        DAILY_BRIEF_HTML_PATH.read_text(encoding="utf-8"), subtype="html"
    )
    secret = str(config["smtp_app_password"])
    if secret and secret.encode("utf-8") in message.as_bytes():
        raise RuntimeError("secret_in_message_blocked")
    return message


def append_delivery(
    *,
    status: str,
    reason: str,
    decision: dict[str, Any],
    email_attempted: str,
    email_sent: str,
    smtp_config_read: str,
    message_count: str,
) -> None:
    append_csv_durable(
        DAILY_DELIVERY_LEDGER_PATH,
        LEDGER_FIELDS,
        {
            "timestamp": iso_now(),
            "cycle_date": cycle_date(),
            "status": status,
            "reason": reason,
            "decision_fingerprint": decision.get("decision_fingerprint", ""),
            "decision_sha256": sha256_file(DAILY_DECISION_JSON_PATH),
            "brief_text_sha256": sha256_file(DAILY_BRIEF_TEXT_PATH),
            "brief_html_sha256": sha256_file(DAILY_BRIEF_HTML_PATH),
            "message_count": message_count,
            "email_attempted": email_attempted,
            "email_sent": email_sent,
            "smtp_config_read": smtp_config_read,
            "broker_connected": "no",
            "broker_account_read": "no",
            "order_code_created": "no",
        },
    )


def send_once(
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
) -> int:
    enabled, guard_reason, _, _ = delivery_guard()
    if not enabled:
        log_daily_run(
            component="daily_sender",
            run_mode="send",
            outcome="blocked",
            reason=guard_reason,
        )
        print(f"email_sent=false reason={guard_reason} smtp_config_read=false")
        return 2

    try:
        decision = validate_decision()
    except (OSError, ValueError) as exc:
        reason = str(exc) if str(exc) else "decision_validation_failed"
        log_daily_run(
            component="daily_sender",
            run_mode="send",
            outcome="blocked",
            reason=reason,
        )
        print(f"email_sent=false reason={reason} smtp_config_read=false")
        return 2
    if decision.get("send_recommended") is not True:
        log_daily_run(
            component="daily_sender",
            run_mode="send",
            outcome="suppressed",
            reason=str(decision.get("send_reason", "decision_suppressed")),
        )
        print(
            f"email_sent=false reason={decision.get('send_reason', 'decision_suppressed')} "
            "smtp_config_read=false"
        )
        return 0

    with ExclusiveFileLock(DAILY_DELIVERY_LOCK_PATH):
        blocked, prior_status = cycle_is_blocked(
            read_csv(DAILY_DELIVERY_LEDGER_PATH), cycle_date()
        )
        if blocked:
            log_daily_run(
                component="daily_sender",
                run_mode="send",
                outcome="deduplicated",
                reason=f"existing_{prior_status}",
            )
            print(
                f"email_sent=false reason=existing_{prior_status} "
                "smtp_config_read=false"
            )
            return 0

        try:
            config = load_config()
            message = build_message(config, decision)
        except (ConfigError, OSError, ValueError, RuntimeError):
            log_daily_run(
                component="daily_sender",
                run_mode="send",
                outcome="blocked",
                reason="pre_smtp_validation_failed",
                smtp_config_read="yes",
            )
            print(
                "email_sent=false reason=pre_smtp_validation_failed "
                "smtp_config_read=true"
            )
            return 2

        # This durable claim is intentionally written before any SMTP operation.
        append_delivery(
            status="send_claimed",
            reason="pre_smtp_durable_claim",
            decision=decision,
            email_attempted="no",
            email_sent="no",
            smtp_config_read="yes",
            message_count="0",
        )
        try:
            with smtp_factory("smtp.gmail.com", 587, timeout=30) as client:
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
                client.login(config["smtp_username"], config["smtp_app_password"])
                client.send_message(message)
        except Exception:
            append_delivery(
                status="delivery_unknown",
                reason="smtp_exception_after_claim",
                decision=decision,
                email_attempted="yes",
                email_sent="unknown",
                smtp_config_read="yes",
                message_count="0_or_1",
            )
            log_daily_run(
                component="daily_sender",
                run_mode="send",
                outcome="delivery_unknown",
                reason="smtp_exception_after_claim",
                email_attempted="yes",
                email_sent="unknown",
                smtp_config_read="yes",
            )
            print(
                "email_sent=unknown reason=smtp_exception_after_claim "
                "automatic_retry=false"
            )
            return 1

        append_delivery(
            status="sent",
            reason="smtp_send_completed",
            decision=decision,
            email_attempted="yes",
            email_sent="yes",
            smtp_config_read="yes",
            message_count="1",
        )
        log_daily_run(
            component="daily_sender",
            run_mode="send",
            outcome="sent",
            reason="smtp_send_completed",
            email_attempted="yes",
            email_sent="yes",
            smtp_config_read="yes",
        )
        print("email_sent=true message_count=1 automatic_retry=false")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--send", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        enabled, reason, _, _ = delivery_guard()
        print(
            f"safe_check_passed=true delivery_enabled={str(enabled).lower()} "
            f"reason={reason} smtp_config_read=false email_attempted=false"
        )
        return 0
    return send_once()


if __name__ == "__main__":
    raise SystemExit(main())
