#!/usr/bin/env python3
"""Read-only, fail-closed email boundary for production-shadow observation.

This deliberately contains no provider, evidence, broker, account, SMTP, or
scheduler code.  It reads only the dedicated production-shadow control state
and hash-chained ledger.  Once a real request has been reserved, a missing or
corrupt state file cannot re-enable automatic email delivery before ten
completed reviews.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

from phase5r_daily_common import ROOT, canonical_sha256


CONTROL_ROOT = ROOT / "00_project_control" / "phase5r_production_shadow_v1"
OBSERVATION_STATE_PATH = CONTROL_ROOT / "observation_state.json"
LEDGER_PATH = (
    ROOT
    / "08_reviews"
    / "phase5r_production_shadow_v1"
    / "ledger"
    / "production_shadow_ledger.jsonl"
)
OBSERVATION_SCHEMA_VERSION = "phase5r_production_shadow_observation_state_v1"
LEDGER_SCHEMA_VERSION = "phase5r_production_shadow_ledger_event_v1"
TARGET_COMPLETED_REVIEWS = 10
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_MAX_STATE_BYTES = 1 * 1024 * 1024
_MAX_LEDGER_BYTES = 2 * 1024 * 1024


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """Return a local control object; ``None`` means missing, never invalid."""

    try:
        metadata = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("unsafe control file")
    if metadata.st_size <= 0 or metadata.st_size > _MAX_STATE_BYTES:
        raise ValueError("control file size is unsafe")
    try:
        descriptor = os.open(path, os.O_RDONLY | _NO_FOLLOW)
    except OSError as exc:
        raise ValueError("unreadable control file") from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("control file changed before read")
        if opened.st_size <= 0 or opened.st_size > _MAX_STATE_BYTES:
            raise ValueError("control file size is unsafe")
        raw = os.read(descriptor, max(opened.st_size, 1) + 1)
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size:
        raise ValueError("control file changed during read")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("control file is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("control file is not an object")
    return value


def _state_requires_suppression() -> bool | None:
    state = _read_json_object(OBSERVATION_STATE_PATH)
    if state is None:
        return None
    if state.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("observation state schema mismatch")
    active = state.get("active")
    email_permitted = state.get("email_delivery_permitted")
    completed = state.get("completed_review_count")
    if active is True and email_permitted is False:
        return True
    if (
        active is False
        and email_permitted is True
        and isinstance(completed, int)
        and not isinstance(completed, bool)
        and completed >= TARGET_COMPLETED_REVIEWS
    ):
        return False
    raise ValueError("observation state is not a safe terminal state")


def _ledger_requires_suppression() -> bool | None:
    try:
        metadata = LEDGER_PATH.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("unsafe observation ledger")
    if metadata.st_size <= 0 or metadata.st_size > _MAX_LEDGER_BYTES:
        raise ValueError("observation ledger size is unsafe")
    try:
        descriptor = os.open(LEDGER_PATH, os.O_RDONLY | _NO_FOLLOW)
    except OSError as exc:
        raise ValueError("unreadable observation ledger") from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("observation ledger changed before read")
        if opened.st_size <= 0 or opened.st_size > _MAX_LEDGER_BYTES:
            raise ValueError("observation ledger size is unsafe")
        raw = os.read(descriptor, max(opened.st_size, 1) + 1)
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size:
        raise ValueError("observation ledger changed during read")
    lines = raw.decode("utf-8").splitlines()
    if not lines:
        raise ValueError("empty observation ledger")
    previous = ""
    reservations = False
    completed_days: set[str] = set()
    for line in lines:
        if not line.strip():
            raise ValueError("blank observation ledger row")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid observation ledger JSON") from exc
        if not isinstance(event, dict):
            raise ValueError("invalid observation ledger row")
        claimed = event.get("event_sha256")
        unsigned = dict(event)
        unsigned.pop("event_sha256", None)
        if (
            event.get("schema_version") != LEDGER_SCHEMA_VERSION
            or event.get("previous_event_sha256") != previous
            or not isinstance(claimed, str)
            or claimed != canonical_sha256(unsigned)
        ):
            raise ValueError("invalid observation ledger chain")
        previous = claimed
        if event.get("event_type") == "reservation":
            reservations = True
        if (
            event.get("event_type") == "completed"
            and event.get("provider_completed") is True
            and isinstance(event.get("trading_day"), str)
        ):
            completed_days.add(event["trading_day"])
    if not reservations:
        raise ValueError("observation ledger lacks reservation")
    return len(completed_days) < TARGET_COMPLETED_REVIEWS


def observation_email_suppressed() -> bool:
    """Return whether automatic email must remain disabled, failing closed."""

    try:
        state = _state_requires_suppression()
        ledger = _ledger_requires_suppression()
    except (OSError, ValueError, UnicodeDecodeError):
        return True
    # A verified reservation always wins over a stale or missing state file.
    if ledger is True or state is True:
        return True
    if ledger is False or state is False:
        return False
    # No dedicated state and no ledger means observation has not started.
    return False


__all__ = [
    "LEDGER_PATH",
    "OBSERVATION_SCHEMA_VERSION",
    "OBSERVATION_STATE_PATH",
    "TARGET_COMPLETED_REVIEWS",
    "observation_email_suppressed",
]
