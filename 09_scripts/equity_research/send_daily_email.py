#!/usr/bin/env python3
"""Send at most one Phase 5R daily brief for an ET calendar date."""

from __future__ import annotations

from equity_naming import brand_name, subject_prefix

import argparse
import hashlib
import json
import os
import re
import smtplib
import ssl
import stat
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Callable

from active_config import load_active_config
from email_brief import EMAIL_BRIEF_VERSION, email_subject, render_email
from daily_common import (
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
    is_us_market_session_date,
    last_completed_market_session,
    latest_published_market_session,
    log_daily_run,
    notification_delivery_policy,
    recommendation_notification_fingerprint,
    LEGACY_NOTIFICATION_MODE,
    WATCH_ACTION_NOTIFICATION_MODE,
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
OWNER_REVIEW_DELIVERY_STATUSES = {
    "owner_review_send_claimed",
    "owner_review_sent",
    "owner_review_delivery_unknown",
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
    regular_delivery_mode: str = LEGACY_NOTIFICATION_MODE,
    notification_changed: bool = False,
) -> tuple[bool, str]:
    return notification_delivery_policy(
        is_weekend=is_weekend,
        weekly_summary_due=weekly_summary_due,
        material_event=material_event,
        decision_changed=decision_changed,
        account_conflict=account_conflict,
        fundamental_weakening=fundamental_weakening,
        first_material_baseline=first_material_baseline,
        regular_delivery_mode=regular_delivery_mode,
        notification_changed=notification_changed,
    )


def validate_owner_review(decision: dict[str, Any], request_id: str) -> None:
    """Bind one real owner request to a recent, explicitly dated review."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", request_id):
        raise ValueError("owner_review_request_id_invalid")
    review = decision.get("owner_requested_research")
    if (not isinstance(review, dict)
            or review.get("mode") != "explicit_one_off_research"
            or review.get("request_id") != request_id
            or not decision.get("decision_fingerprint")
            or review.get("decision_fingerprint") != decision["decision_fingerprint"]):
        raise ValueError("owner_review_request_mismatch")
    try:
        reviewed_at = datetime.fromisoformat(str(review["reviewed_at"]).replace("Z", "+00:00"))
        market_as_of = date.fromisoformat(str(review["market_as_of"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("owner_review_timestamp_invalid") from exc
    current = now_et()
    if reviewed_at.tzinfo is None:
        raise ValueError("owner_review_timestamp_invalid")
    age_seconds = (current - reviewed_at).total_seconds()
    if (reviewed_at.astimezone(current.tzinfo).date() != current.date()
            or not 0 <= age_seconds <= 6 * 60 * 60):
        raise ValueError("owner_review_not_recent")
    if (not is_us_market_session_date(market_as_of)
            or not latest_published_market_session(current) <= market_as_of <= last_completed_market_session(current)):
        raise ValueError("owner_review_market_date_out_of_range")
    # Owner delivery cannot fall back to unbound legacy text/HTML artifacts.
    if decision.get("email_brief_version") != EMAIL_BRIEF_VERSION:
        raise ValueError("owner_review_requires_bound_brief")


def validate_decision(
    *, correction: bool = False, owner_review_request_id: str | None = None,
    snapshot_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    # Retain exactly the bytes parsed for an explicit review. A concurrent
    # producer may replace the canonical files after this validation returns.
    decision_bytes = (DAILY_DECISION_JSON_PATH.read_bytes()
                      if owner_review_request_id is not None else None)
    decision = json.loads(decision_bytes) if decision_bytes is not None else read_json(DAILY_DECISION_JSON_PATH)
    decision_cycle_text = str(decision.get("cycle_date", ""))
    try:
        decision_cycle = date.fromisoformat(decision_cycle_text)
    except ValueError as exc:
        raise ValueError("decision_cycle_invalid") from exc
    current = now_et()
    if correction or owner_review_request_id is not None:
        correction_age_days = (current.date() - decision_cycle).days
        if correction_age_days not in {0, 1}:
            raise ValueError("correction_cycle_out_of_range")
        try:
            validation_current = datetime.fromisoformat(str(decision["generated_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("decision_generated_at_invalid") from exc
        if validation_current.date() != decision_cycle:
            raise ValueError("decision_generated_at_cycle_mismatch")
        if owner_review_request_id is not None:
            if validation_current.tzinfo is None or validation_current > current:
                raise ValueError("decision_generated_at_invalid")
            validate_owner_review(decision, owner_review_request_id)
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
    stored_policy = decision.get("notification_policy")
    if not isinstance(stored_policy, dict):
        raise ValueError("decision_notification_policy_mismatch")
    stored_mode = stored_policy.get("regular_delivery_mode", LEGACY_NOTIFICATION_MODE)
    active_mode = config["notifications"].get("regular_delivery_mode", LEGACY_NOTIFICATION_MODE)
    if "regular_delivery_mode" in stored_policy:
        expected_notification_policy["regular_delivery_mode"] = stored_mode
    if stored_policy != expected_notification_policy or stored_mode not in {LEGACY_NOTIFICATION_MODE, WATCH_ACTION_NOTIFICATION_MODE}:
        raise ValueError("decision_notification_policy_mismatch")
    # Explicit historical research retains the policy truth of its original
    # artifact. Ordinary delivery must follow the active configured cadence.
    if not correction and owner_review_request_id is None and stored_mode != active_mode:
        raise ValueError("decision_notification_mode_requires_refresh")
    notification_changed = False
    if stored_mode == WATCH_ACTION_NOTIFICATION_MODE:
        comparison = decision.get("notification_change")
        if not isinstance(comparison, dict):
            raise ValueError("decision_notification_change_missing")
        prior = comparison.get("prior_fingerprint")
        if (not isinstance(prior, str)
                or (prior and re.fullmatch(r"[0-9a-f]{64}", prior) is None)
                or comparison.get("comparison_source") not in {"prior_state", "same_cycle_anchor", "prior_decision_migration", "initial_baseline"}
                or type(comparison.get("changed")) is not bool):
            raise ValueError("decision_notification_change_invalid")
        fingerprint = recommendation_notification_fingerprint(decision)
        notification_changed = bool(prior) and fingerprint != prior
        if comparison.get("fingerprint") != fingerprint or comparison["changed"] is not notification_changed:
            raise ValueError("decision_notification_change_mismatch")
    policy_send, policy_reason = delivery_policy(
        is_weekend=expected_evaluation["is_weekend"],
        weekly_summary_due=expected_evaluation["weekly_summary_due"],
        material_event=bool(decision["material_events"]),
        decision_changed=decision.get("decision_changed") is True,
        account_conflict=bool(decision["account_conflicts"]),
        fundamental_weakening=bool(weakening_tickers),
        first_material_baseline=first_material_baseline,
        regular_delivery_mode=stored_mode,
        notification_changed=notification_changed,
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
        if decision_bytes is not None and snapshot_hashes is not None:
            snapshot_hashes.update({
                "decision_sha256": hashlib.sha256(decision_bytes).hexdigest(),
                "brief_text_sha256": hashlib.sha256(expected_text.encode("utf-8")).hexdigest(),
                "brief_html_sha256": hashlib.sha256(expected_html.encode("utf-8")).hexdigest(),
            })
    return decision


def build_message(
    config: dict[str, Any],
    decision: dict[str, Any],
    *,
    correction: bool = False,
    owner_review: bool = False,
) -> EmailMessage:
    if decision.get("email_brief_version") == EMAIL_BRIEF_VERSION:
        subject = safe_header(
            email_subject(decision, correction=correction, owner_review=owner_review), "subject"
        )
    else:
        headline = safe_header(decision.get("headline"), "headline")
        prefix = subject_prefix(correction=correction, owner_review=owner_review)
        subject = safe_header(f"{prefix} {headline} — {decision['cycle_date']}", "subject")
    message = EmailMessage()
    message["Subject"] = subject
    # The public naming policy owns presentation; legacy SMTP sender_name is
    # retained for config compatibility, never used as the display authority.
    message["From"] = formataddr((safe_header(brand_name(), "display_brand"), config["smtp_username"]))
    message["To"] = config["recipient_email"]
    if owner_review:
        # Only this validated in-memory decision supplies explicit-review
        # content; reading the shared briefs here would race the producer.
        _, body_text, body_html = render_email(decision)
    else:
        body_text = DAILY_BRIEF_TEXT_PATH.read_text(encoding="utf-8")
        body_html = DAILY_BRIEF_HTML_PATH.read_text(encoding="utf-8")
    message.set_content(body_text)
    message.add_alternative(body_html, subtype="html")
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
    content_hashes: dict[str, str] | None = None,
) -> None:
    hashes = content_hashes if content_hashes is not None else {
        "decision_sha256": sha256_file(DAILY_DECISION_JSON_PATH),
        "brief_text_sha256": sha256_file(DAILY_BRIEF_TEXT_PATH),
        "brief_html_sha256": sha256_file(DAILY_BRIEF_HTML_PATH),
    }
    append_csv_durable(
        DAILY_DELIVERY_LEDGER_PATH,
        LEDGER_FIELDS,
        {
            "timestamp": iso_now(),
            "cycle_date": decision["cycle_date"],
            "status": status,
            "reason": reason,
            "decision_fingerprint": decision.get("decision_fingerprint", ""),
            "decision_sha256": hashes["decision_sha256"],
            "brief_text_sha256": hashes["brief_text_sha256"],
            "brief_html_sha256": hashes["brief_html_sha256"],
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


def owner_review_request_key(request_id: str) -> str:
    # Keep the append-only ledger's existing CSV schema intact.
    return "owner_request_sha256=" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()


def owner_review_eligibility(
    rows: list[dict[str, str]], request_id: str
) -> tuple[bool, str]:
    key = owner_review_request_key(request_id)
    if any(
        row.get("status", "").strip() in OWNER_REVIEW_DELIVERY_STATUSES
        and key in row.get("reason", "").split(";")
        for row in rows
    ):
        return False, "existing_owner_review_request"
    return True, "explicit_owner_review_request"


def send_once(
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
    *,
    correction: bool = False,
    owner_review_request_id: str | None = None,
) -> int:
    owner_review = owner_review_request_id is not None
    if correction and owner_review:
        raise ValueError("delivery_modes_mutually_exclusive")
    run_mode = ("explicit_owner_review" if owner_review
                else "explicit_correction_resend" if correction else "send")
    enabled, guard_reason, _, _ = delivery_guard()
    if (correction or owner_review) and guard_reason == "before_daily_decision_time":
        enabled = True
        guard_reason = "explicit_request_clock_override"
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
        decision = (validate_decision(owner_review_request_id=owner_review_request_id)
                    if owner_review else validate_decision(correction=correction))
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
    if not owner_review and decision.get("send_recommended") is not True:
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
    owner_content_hashes: dict[str, str] | None = {} if owner_review else None
    with ExclusiveFileLock(DAILY_DELIVERY_LOCK_PATH):
        delivery_rows = read_csv(DAILY_DELIVERY_LEDGER_PATH)
        if owner_review:
            allowed, prior_status = owner_review_eligibility(
                delivery_rows, owner_review_request_id
            )
            blocked = not allowed
        elif correction:
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
                reason=prior_status if correction or owner_review else f"existing_{prior_status}",
            )
            print(
                f"email_sent=false reason={prior_status if correction or owner_review else f'existing_{prior_status}'} "
                "smtp_config_read=false"
            )
            return 0

        if owner_review:
            try:
                if validate_decision(owner_review_request_id=owner_review_request_id,
                                     snapshot_hashes=owner_content_hashes) != decision:
                    raise ValueError("owner_review_changed_before_claim")
            except (OSError, ValueError) as exc:
                log_daily_run(component="daily_sender", run_mode=run_mode,
                              outcome="blocked", reason=str(exc))
                print(f"email_sent=false reason={exc} smtp_config_read=false")
                return 2

        try:
            config = load_config()
            message = build_message(config, decision, correction=correction, owner_review=owner_review)
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

        status_prefix = "owner_review_" if owner_review else "correction_" if correction else ""
        reason_prefix = "explicit_owner_review_" if owner_review else "explicit_correction_" if correction else ""
        request_suffix = (";" + owner_review_request_key(owner_review_request_id)) if owner_review else ""
        # This durable claim is intentionally written before any SMTP operation.
        append_delivery(
            status=status_prefix + "send_claimed",
            reason=reason_prefix + "pre_smtp_durable_claim" + request_suffix,
            decision=decision,
            email_attempted="no",
            email_sent="no",
            smtp_config_read="yes",
            message_count="0",
            content_hashes=owner_content_hashes,
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
                status=status_prefix + "delivery_unknown",
                reason=reason_prefix + "smtp_exception_after_claim" + request_suffix,
                decision=decision,
                email_attempted="yes",
                email_sent="unknown",
                smtp_config_read="yes",
                message_count="0_or_1",
                content_hashes=owner_content_hashes,
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
            status=status_prefix + "sent",
            reason=reason_prefix + "smtp_send_completed" + request_suffix,
            decision=decision,
            email_attempted="yes",
            email_sent="yes",
            smtp_config_read="yes",
            message_count="1",
            content_hashes=owner_content_hashes,
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
            f"correction={str(correction).lower()} owner_review={str(owner_review).lower()}"
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--send", action="store_true")
    mode.add_argument("--resend-correction", action="store_true")
    mode.add_argument("--send-owner-review", metavar="REQUEST_ID",
                      help="Send one explicitly requested, dated owner review; never scheduled")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        enabled, reason, _, _ = delivery_guard()
        print(
            f"safe_check_passed=true delivery_enabled={str(enabled).lower()} "
            f"reason={reason} smtp_config_read=false email_attempted=false"
        )
        return 0
    return send_once(correction=args.resend_correction, owner_review_request_id=args.send_owner_review)


if __name__ == "__main__":
    raise SystemExit(main())
