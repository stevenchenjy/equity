"""Separate shared source integrity from named issuer evidence quarantines.

A completed partial scan is usable only with the explicit isolation contract.
Old failed or malformed status files never acquire authority from this adapter.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def shared_integrity_passed(status: dict[str, Any]) -> bool:
    if "global_integrity_passed" not in status:
        return status.get("scan_status") == "ok" and status.get("held_coverage_complete") is True
    failed = status.get("failed_tickers")
    local = status.get("ticker_blockers")
    admitted = status.get("admitted_tickers")
    rejected = status.get("submission_failed_tickers")
    if not (status.get("global_integrity_passed") is True
            and status.get("global_blockers") == []
            and status.get("failure_scope") in {"none", "ticker"}
            and status.get("scan_status") in {"ok", "partial"}
            and isinstance(failed, list) and isinstance(local, dict)
            and isinstance(admitted, list) and isinstance(rejected, list)):
        return False
    if any(not isinstance(t, str) or not t for t in failed + admitted + rejected):
        return False
    if any(not isinstance(t, str) or not t or not isinstance(c, list)
           or not c or any(not isinstance(v, str) or not v for v in c)
           for t, c in local.items()):
        return False
    if set(failed) != set(local) or set(rejected) - set(failed) or set(rejected) & set(admitted):
        return False
    return (status["scan_status"] == "partial" and status["failure_scope"] == "ticker" and bool(local)
            or status["scan_status"] == "ok" and status["failure_scope"] == "none" and not local and not failed)


def ticker_blockers(status: dict[str, Any]) -> dict[str, list[str]]:
    local = status.get("ticker_blockers", {})
    if not isinstance(local, dict):
        return {}
    return {t: sorted(set(c)) for t, c in local.items()
            if isinstance(t, str) and t and isinstance(c, list)
            and c and all(isinstance(v, str) and v for v in c)}


def required_issuer_blockers(status: dict[str, Any], required: set[str]) -> dict[str, list[str]]:
    local = ticker_blockers(status)
    if "global_integrity_passed" in status:
        for ticker in required - set(status.get("admitted_tickers", [])):
            if ticker:
                local.setdefault(ticker, []).append("current_issuer_scan_missing")
    return local


def current_shared_integrity_passed(status: dict[str, Any], current: datetime) -> bool:
    if not shared_integrity_passed(status):
        return False
    try:
        observed = datetime.fromisoformat(status["last_attempt_at"].replace("Z", "+00:00"))
        if "global_integrity_passed" in status:
            completed = datetime.fromisoformat(status["last_completed_at"].replace("Z", "+00:00"))
            if completed.tzinfo is None or observed.tzinfo is None or not observed <= completed <= current:
                return False
        return (observed.tzinfo is not None and observed <= current
                and observed.astimezone(ZoneInfo("America/New_York")).date()
                == current.astimezone(ZoneInfo("America/New_York")).date())
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def ticker_scan_complete(status: dict[str, Any], ticker: str) -> bool:
    return (shared_integrity_passed(status)
            and ticker in status.get("scanned_tickers", [])
            and ticker not in ticker_blockers(status)
            and ("admitted_tickers" not in status or ticker in status["admitted_tickers"]))
