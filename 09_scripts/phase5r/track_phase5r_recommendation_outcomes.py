#!/usr/bin/env python3
"""Persist point-in-time recommendations and evaluate later market outcomes."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from phase5r_daily_common import (
    DAILY_DECISION_JSON_PATH,
    MARKET_SNAPSHOT_PATH,
    ROOT,
    atomic_write_csv,
    atomic_write_text,
    canonical_sha256,
    iso_now,
    read_csv,
    read_json,
)


SNAPSHOT_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_snapshots.local.jsonl"
)
HISTORY_PATH = ROOT / "03_source_data" / "phase5r" / "phase5r_market_close_history.local.csv"
OUTCOME_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_outcomes.local.csv"
)
FEEDBACK_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_feedback.local.jsonl"
)
RETROSPECTIVE_PATH = ROOT / "08_reviews" / "current" / "phase5r_retrospective.local.md"
HORIZONS = (1, 5, 20, 60)
HISTORY_FIELDS = [
    "market_session", "ticker", "close", "data_source", "data_timestamp",
    "price_basis",
]
OUTCOME_FIELDS = [
    "snapshot_id", "ticker", "recommendation_session", "classification",
    "confidence", "horizon_sessions", "evaluation_session", "entry_close",
    "evaluation_close", "absolute_return_pct", "spy_relative_return_pct",
    "qqq_relative_return_pct", "maximum_favorable_excursion_pct",
    "maximum_adverse_excursion_pct", "classification_changed_before_horizon",
    "price_basis", "corporate_action_review_required",
]
FEEDBACK_LABELS = {"helpful", "noisy", "wrong", "missed_event"}


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def classification(action: str) -> str:
    normalized = action.lower()
    if "trim" in normalized or "reduce" in normalized:
        return "TRIM"
    if "exit" in normalized or "sell" in normalized:
        return "EXIT"
    if (
        "add" in normalized
        or "buy" in normalized
        or "eligible" in normalized
        or "core_allocation" in normalized
    ):
        return "ADD_REVIEW"
    if normalized in {"hold", "hold_existing"}:
        return "HOLD"
    if "no_new" in normalized:
        return "NO_NEW_POSITION"
    return "WATCH"


def update_history() -> tuple[list[dict[str, str]], str]:
    existing = read_csv(HISTORY_PATH)
    seen = {(row["market_session"], row["ticker"]) for row in existing}
    current_session = ""
    for row in read_csv(MARKET_SNAPSHOT_PATH):
        ticker = row.get("ticker", "").strip().upper()
        session = row.get("market_session_date", "").strip()
        close = number(row.get("last_price"))
        if (
            ticker and session and close is not None
            and row.get("data_quality_label") in {"ok", "partial"}
        ):
            current_session = max(current_session, session)
            key = (session, ticker)
            if key not in seen:
                existing.append({
                    "market_session": session,
                    "ticker": ticker,
                    "close": f"{close:.4f}",
                    "data_source": row.get("data_source", ""),
                    "data_timestamp": row.get("data_timestamp", ""),
                    "price_basis": "completed_daily_close_as_supplied_by_provider; corporate_actions_require_review",
                })
                seen.add(key)
    existing.sort(key=lambda row: (row["market_session"], row["ticker"]))
    atomic_write_csv(HISTORY_PATH, HISTORY_FIELDS, existing)
    return existing, current_session


def recommendation_rows(decision: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role, source_rows in (
        ("held", decision.get("held_positions", [])),
        ("candidate", decision.get("watch_candidates", [])),
    ):
        for row in source_rows:
            if not isinstance(row, dict) or not row.get("ticker"):
                continue
            action = str(row.get("action") or row.get("label") or "watch")
            rows.append({
                "ticker": str(row["ticker"]).upper(),
                "role": role,
                "classification": classification(action),
                "action_label": action,
                "confidence": row.get("confidence", ""),
                "reference_price": row.get("current_price", ""),
                "valuation_bear_price": row.get("valuation_bear_price", ""),
                "valuation_applicability": row.get("valuation_applicability", ""),
                "valuation_base_price": row.get("valuation_base_price", ""),
                "valuation_bull_price": row.get("valuation_bull_price", ""),
                "maximum_review_price": row.get("maximum_review_price", ""),
                "suggested_whole_shares": row.get("suggested_whole_shares", ""),
                "sizing_tier": row.get("sizing_tier", ""),
                "gate_blockers": row.get("gate_blockers", ""),
                "holding_horizon": row.get("holding_horizon", ""),
                "invalidation": row.get("invalidation", ""),
                "strongest_positive_evidence": row.get("strongest_positive_evidence", ""),
                "strongest_negative_evidence": row.get("strongest_negative_evidence", ""),
                "source_url": row.get("valuation_source", ""),
                "human_confirmation_required": row.get("human_confirmation_required", "no"),
            })
    return rows


def persist_snapshots(decision: dict[str, Any], session: str) -> int:
    if not session:
        return 0
    existing_ids = {row.get("snapshot_id") for row in jsonl(SNAPSHOT_PATH)}
    created = 0
    for recommendation in recommendation_rows(decision):
        identity = {
            "decision_fingerprint": decision.get("decision_fingerprint", ""),
            "market_session": session,
            "ticker": recommendation["ticker"],
            "role": recommendation["role"],
        }
        snapshot_id = canonical_sha256(identity)
        if snapshot_id in existing_ids:
            continue
        append_jsonl(SNAPSHOT_PATH, {
            "schema_version": "phase5r_recommendation_snapshot_v1",
            "snapshot_id": snapshot_id,
            "created_at": iso_now(),
            "market_session": session,
            "decision_fingerprint": decision.get("decision_fingerprint", ""),
            **recommendation,
            "model_route": decision.get("model_assistance", {}).get("route", "no_call"),
            "model_cost_usd": decision.get("model_assistance", {}).get("cycle_cost_usd", 0.0),
            "price_basis": "completed_daily_close",
            "benchmarks": ["SPY", "QQQ"],
            "automatic_action_allowed": False,
            "broker_connected": False,
        })
        existing_ids.add(snapshot_id)
        created += 1
    return created


def evaluate(history_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_ticker: dict[str, dict[str, float]] = {}
    sessions: set[str] = set()
    for row in history_rows:
        price = number(row.get("close"))
        if price is not None:
            by_ticker.setdefault(row["ticker"], {})[row["market_session"]] = price
            sessions.add(row["market_session"])
    ordered_sessions = sorted(sessions)
    snapshots = jsonl(SNAPSHOT_PATH)
    results: list[dict[str, str]] = []
    for snapshot in snapshots:
        ticker = str(snapshot.get("ticker", ""))
        start = str(snapshot.get("market_session", ""))
        if ticker not in by_ticker or start not in by_ticker[ticker] or start not in ordered_sessions:
            continue
        start_index = ordered_sessions.index(start)
        entry = by_ticker[ticker][start]
        for horizon in HORIZONS:
            if start_index + horizon >= len(ordered_sessions):
                continue
            target_session = ordered_sessions[start_index + horizon]
            evaluation = by_ticker[ticker].get(target_session)
            if evaluation is None:
                continue
            window_sessions = ordered_sessions[start_index + 1:start_index + horizon + 1]
            window_prices = [by_ticker[ticker][day] for day in window_sessions if day in by_ticker[ticker]]
            if not window_prices:
                continue
            absolute = (evaluation / entry - 1.0) * 100.0
            relative: dict[str, str] = {}
            for benchmark in ("SPY", "QQQ"):
                benchmark_entry = by_ticker.get(benchmark, {}).get(start)
                benchmark_end = by_ticker.get(benchmark, {}).get(target_session)
                relative[benchmark] = (
                    f"{absolute - (benchmark_end / benchmark_entry - 1.0) * 100.0:.4f}"
                    if benchmark_entry and benchmark_end else ""
                )
            changed = any(
                later.get("ticker") == ticker
                and start < str(later.get("market_session", "")) <= target_session
                and later.get("classification") != snapshot.get("classification")
                for later in snapshots
            )
            results.append({
                "snapshot_id": str(snapshot["snapshot_id"]),
                "ticker": ticker,
                "recommendation_session": start,
                "classification": str(snapshot.get("classification", "")),
                "confidence": str(snapshot.get("confidence", "")),
                "horizon_sessions": str(horizon),
                "evaluation_session": target_session,
                "entry_close": f"{entry:.4f}",
                "evaluation_close": f"{evaluation:.4f}",
                "absolute_return_pct": f"{absolute:.4f}",
                "spy_relative_return_pct": relative["SPY"],
                "qqq_relative_return_pct": relative["QQQ"],
                "maximum_favorable_excursion_pct": f"{(max(window_prices) / entry - 1.0) * 100.0:.4f}",
                "maximum_adverse_excursion_pct": f"{(min(window_prices) / entry - 1.0) * 100.0:.4f}",
                "classification_changed_before_horizon": "yes" if changed else "no",
                "price_basis": "completed_daily_close",
                "corporate_action_review_required": "yes",
            })
    results.sort(key=lambda row: (row["recommendation_session"], row["ticker"], int(row["horizon_sessions"])))
    atomic_write_csv(OUTCOME_PATH, OUTCOME_FIELDS, results)
    return results


def write_retrospective() -> None:
    snapshots = jsonl(SNAPSHOT_PATH)
    material = [row for row in snapshots if row.get("human_confirmation_required") == "yes"]
    feedback = jsonl(FEEDBACK_PATH)
    completed_groups = len(material) // 10
    lines = [
        "# Phase 5R recommendation retrospective",
        "",
        f"Generated: `{iso_now()}`",
        "",
        f"- Point-in-time snapshots: `{len(snapshots)}`.",
        f"- Material review snapshots: `{len(material)}`.",
        f"- Completed ten-review retrospective groups: `{completed_groups}`.",
        f"- Human feedback records: `{len(feedback)}`.",
        "- Evaluation remains close-based; every result is marked for corporate-action review.",
    ]
    if completed_groups == 0:
        lines.extend(["", "No ten-material-review retrospective is due yet."])
    atomic_write_text(RETROSPECTIVE_PATH, "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-feedback", nargs=2, metavar=("SNAPSHOT_ID", "LABEL"))
    args = parser.parse_args()
    if args.record_feedback:
        snapshot_id, label = args.record_feedback
        if label not in FEEDBACK_LABELS:
            raise ValueError("feedback label must be helpful, noisy, wrong, or missed_event")
        known_ids = {row.get("snapshot_id") for row in jsonl(SNAPSHOT_PATH)}
        if snapshot_id not in known_ids:
            raise ValueError("unknown recommendation snapshot id")
        append_jsonl(FEEDBACK_PATH, {
            "recorded_at": iso_now(), "snapshot_id": snapshot_id, "label": label,
        })
        write_retrospective()
        print("feedback_recorded=true")
        return 0
    decision = read_json(DAILY_DECISION_JSON_PATH)
    history, session = update_history()
    created = persist_snapshots(decision, session)
    outcomes = evaluate(history)
    write_retrospective()
    print(
        f"recommendation_snapshots_created={created} outcomes={len(outcomes)} "
        "price_basis=completed_daily_close model_cost_usd=0 broker_connected=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
