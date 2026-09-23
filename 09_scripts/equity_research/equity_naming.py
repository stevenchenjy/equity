"""Shared presentation names; no strategy, delivery or protocol authority."""
from __future__ import annotations

import json
from pathlib import Path

DISPLAY_NAMES_PATH = Path(__file__).resolve().parents[2] / "01_policies/equity_display_names.json"


def load_display_names(path: Path = DISPLAY_NAMES_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = {"schema_version", "brand", "subject_label", "email_tagline", "alert_title", "alert_message", "reports"}
    if not isinstance(payload, dict) or set(payload) != fields or payload["schema_version"] != "equity_display_names_v1":
        raise ValueError("invalid_display_names_config")
    if not isinstance(payload["reports"], dict) or not payload["reports"]:
        raise ValueError("invalid_report_names")
    values = [payload[key] for key in fields - {"reports"}] + list(payload["reports"].values())
    if any(not isinstance(value, str) or not value.strip() or len(value) > 160
           or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in values):
        raise ValueError("invalid_display_name_text")
    return payload


DISPLAY_NAMES = load_display_names()


def brand_name() -> str:
    return DISPLAY_NAMES["brand"]


def subject_prefix(*, correction: bool = False, owner_review: bool = False) -> str:
    suffix = " 应请求复核" if owner_review else " 更正版" if correction else ""
    return f"[{DISPLAY_NAMES['subject_label']}{suffix}]"


def report_heading(key: str) -> str:
    return f"# {brand_name()} — {DISPLAY_NAMES['reports'][key]}"


def desktop_alert_script() -> str:
    # JSON string quoting safely escapes quotation marks and backslashes for
    # these single-line AppleScript string literals.
    body = json.dumps(DISPLAY_NAMES["alert_message"], ensure_ascii=False)
    title = json.dumps(f"{brand_name()} — {DISPLAY_NAMES['alert_title']}", ensure_ascii=False)
    return f"display notification {body} with title {title}"
