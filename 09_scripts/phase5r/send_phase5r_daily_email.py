#!/usr/bin/env python3
"""Send at most one Phase 5R daily brief for an ET calendar date."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import stat
from datetime import date, datetime
from email.message import EmailMessage
from typing import Any, Callable

from phase5r_active_config import load_active_config
from phase5r_email_brief import EMAIL_BRIEF_VERSION, email_subject, render_email
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
    weekly_summary_due_for_published_session,
)


BLOCKING_DELIVERY_STATUSES = {"send_claimed", "sent", "delivery_unknown"}
CORRECTION_DELIVERY_STATUSES = {
    "correction_send_claimed",
    "correction_sent",
    "correction_delivery_unknown",
}
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


def validate_decision(*, correction: bool = False) -> dict[str, Any]:
    decision = read_json(DAILY_DECISION_JSON_PATH)
    decision_cycle_text = str(decision.get("cycle_date", ""))
    try:
        decision_cycle = date.fromisoformat(decision_cycle_text)
    except ValueError as exc:
        raise ValueError("decision_cycle_invalid") from exc
    current = now_et()
    if correction:
        correction_age_days = (current.date() - decision_cycle).days
        if correction_age_days not in {0, 1}:
            raise ValueError("correction_cycle_out_of_range")
        try:
            validation_current = datetime.fromisoformat(str(decision["generated_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("decision_generated_at_invalid") from exc
        if validation_current.date() != decision_cycle:
            raise ValueError("decision_generated_at_cycle_mismatch")
    else:
        if decision_cycle_text != cycle_date():
            raise ValueError("decision_cycle_mismatch")
        validation_current = current
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
    market_gate = decision.get("market_gate")
    evaluation = decision.get("notification_policy_evaluation")
    if (
        not isinstance(fundamental_gate, dict)
        or not isinstance(market_gate, dict)
        or not isinstance(evaluation, dict)
    ):
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
    try:
        published_session = date.fromisoformat(
            str(market_gate["expected_market_session"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("decision_notification_inputs_invalid") from exc
    expected_evaluation = {
        "is_weekend": validation_current.weekday() >= 5,
        "weekly_summary_due": weekly_summary_due_for_published_session(
            validation_current,
            published_session,
        ),
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
    version = decision.get("email_brief_version")
    if version is not None:
        if version != EMAIL_BRIEF_VERSION:
            raise ValueError("daily_brief_version_unsupported")
        _, expected_text, expected_html = render_email(decision)
        if (DAILY_BRIEF_TEXT_PATH.read_text(encoding="utf-8") != expected_text
                or DAILY_BRIEF_HTML_PATH.read_text(encoding="utf-8") != expected_html):
            raise ValueError("daily_brief_decision_mismatch")
    return decision


def build_message(
    config: dict[str, Any],
    decision: dict[str, Any],
    *,
    correction: bool = False,
) -> EmailMessage:
    if decision.get("email_brief_version") == EMAIL_BRIEF_VERSION:
        subject = safe_header(email_subject(decision, correction=correction), "subject")
    else:
        headline = safe_header(decision.get("headline"), "headline")
        prefix = "[Phase 5R 更正版]" if correction else "[Phase 5R]"
        subject = safe_header(f"{prefix} {headline} — {decision['cycle_date']}", "subject")
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
            "cycle_date": decision["cycle_date"],
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


def correction_eligibility(
    rows: list[dict[str, str]],
    target_cycle: str,
) -> tuple[bool, str]:
    cycle_rows = [
        row for row in rows if row.get("cycle_date", "").strip() == target_cycle
    ]
    sent_rows = [row for row in cycle_rows if row.get("status", "").strip() == "sent"]
    if not sent_rows:
        return False, "no_prior_sent_delivery"
    prior = sent_rows[-1]
    current_hashes = (
        sha256_file(DAILY_DECISION_JSON_PATH),
        sha256_file(DAILY_BRIEF_TEXT_PATH),
        sha256_file(DAILY_BRIEF_HTML_PATH),
    )
    if any(
        row.get("status", "").strip() in CORRECTION_DELIVERY_STATUSES
        and (
            row.get("decision_sha256", ""),
            row.get("brief_text_sha256", ""),
            row.get("brief_html_sha256", ""),
        ) == current_hashes
        for row in cycle_rows
    ):
        return False, "existing_identical_correction_delivery"
    prior_hashes = (
        prior.get("decision_sha256", ""),
        prior.get("brief_text_sha256", ""),
        prior.get("brief_html_sha256", ""),
    )
    if current_hashes == prior_hashes:
        return False, "correction_content_unchanged"
    return True, "explicit_changed_content_correction"


def send_once(
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
    *,
    correction: bool = False,
) -> int:
    run_mode = "explicit_correction_resend" if correction else "send"
    enabled, guard_reason, _, _ = delivery_guard()
    if correction and guard_reason == "before_daily_decision_time":
        enabled = True
        guard_reason = "explicit_correction_clock_override"
    if not enabled:
        log_daily_run(
            component="daily_sender",
            run_mode=run_mode,
            outcome="blocked",
            reason=guard_reason,
        )
        print(f"email_sent=false reason={guard_reason} smtp_config_read=false")
        return 2

    try:
        decision = validate_decision(correction=correction)
    except (OSError, ValueError) as exc:
        reason = str(exc) if str(exc) else "decision_validation_failed"
        log_daily_run(
            component="daily_sender",
            run_mode=run_mode,
            outcome="blocked",
            reason=reason,
        )
        print(f"email_sent=false reason={reason} smtp_config_read=false")
        return 2
    if decision.get("send_recommended") is not True:
        log_daily_run(
            component="daily_sender",
            run_mode=run_mode,
            outcome="suppressed",
            reason=str(decision.get("send_reason", "decision_suppressed")),
        )
        print(
            f"email_sent=false reason={decision.get('send_reason', 'decision_suppressed')} "
            "smtp_config_read=false"
        )
        return 0

    target_cycle = str(decision["cycle_date"])
    with ExclusiveFileLock(DAILY_DELIVERY_LOCK_PATH):
        delivery_rows = read_csv(DAILY_DELIVERY_LEDGER_PATH)
        if correction:
            correction_allowed, correction_reason = correction_eligibility(
                delivery_rows, target_cycle
            )
            blocked = not correction_allowed
            prior_status = correction_reason
        else:
            blocked, prior_status = cycle_is_blocked(delivery_rows, target_cycle)
        if blocked:
            log_daily_run(
                component="daily_sender",
                run_mode=run_mode,
                outcome="deduplicated",
                reason=prior_status if correction else f"existing_{prior_status}",
            )
            print(
                f"email_sent=false reason={prior_status if correction else f'existing_{prior_status}'} "
                "smtp_config_read=false"
            )
            return 0

        try:
            config = load_config()
            message = build_message(config, decision, correction=correction)
        except (ConfigError, OSError, ValueError, RuntimeError):
            log_daily_run(
                component="daily_sender",
                run_mode=run_mode,
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
            status="correction_send_claimed" if correction else "send_claimed",
            reason=(
                "explicit_correction_pre_smtp_durable_claim"
                if correction
                else "pre_smtp_durable_claim"
            ),
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
                status=(
                    "correction_delivery_unknown" if correction else "delivery_unknown"
                ),
                reason=(
                    "explicit_correction_smtp_exception_after_claim"
                    if correction
                    else "smtp_exception_after_claim"
                ),
                decision=decision,
                email_attempted="yes",
                email_sent="unknown",
                smtp_config_read="yes",
                message_count="0_or_1",
            )
            log_daily_run(
                component="daily_sender",
                run_mode=run_mode,
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
            status="correction_sent" if correction else "sent",
            reason=(
                "explicit_correction_smtp_send_completed"
                if correction
                else "smtp_send_completed"
            ),
            decision=decision,
            email_attempted="yes",
            email_sent="yes",
            smtp_config_read="yes",
            message_count="1",
        )
        log_daily_run(
            component="daily_sender",
            run_mode=run_mode,
            outcome="sent",
            reason="smtp_send_completed",
            email_attempted="yes",
            email_sent="yes",
            smtp_config_read="yes",
        )
        print(
            "email_sent=true message_count=1 automatic_retry=false "
            f"correction={str(correction).lower()}"
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--send", action="store_true")
    mode.add_argument("--resend-correction", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        enabled, reason, _, _ = delivery_guard()
        print(
            f"safe_check_passed=true delivery_enabled={str(enabled).lower()} "
            f"reason={reason} smtp_config_read=false email_attempted=false"
        )
        return 0
    return send_once(correction=args.resend_correction)


if __name__ == "__main__":
    raise SystemExit(main())
