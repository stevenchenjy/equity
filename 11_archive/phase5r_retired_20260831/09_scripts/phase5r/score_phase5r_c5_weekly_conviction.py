from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_c5_run_log.csv"
PACKETS = RESEARCH_DIR / "phase5r_c5_company_research_packets.csv"
CONCENTRATION = POSITION_DIR / "phase5r_c4r_portfolio_concentration_report.csv"
SCORES = RESEARCH_DIR / "phase5r_c5_weekly_conviction_scores.csv"
POSITION_RECOMMENDATIONS = RESEARCH_DIR / "phase5r_c5_position_review_recommendations.csv"
NEW_RECOMMENDATIONS = RESEARCH_DIR / "phase5r_c5_new_candidate_recommendations.csv"

SCORE_FIELDS = [
    "weekly_rank", "ticker", "research_role", "business_quality_score",
    "earnings_revenue_trend_score", "valuation_reasonableness_score",
    "catalyst_news_quality_score", "technical_entry_discipline_score", "portfolio_fit_score",
    "weekly_conviction_score", "holding_horizon_candidate", "recommendation_label",
    "recommendation_confidence", "portfolio_rule_applied", "human_action_required", "score_formula",
]
POSITION_FIELDS = [
    "priority", "ticker", "position_pct", "portfolio_concentration_status", "weekly_conviction_score",
    "holding_horizon_candidate", "recommendation_label", "recommendation_confidence",
    "review_reason", "exit_or_trim_conditions", "human_action_required", "automatic_action_allowed",
]
NEW_FIELDS = [
    "weekly_rank", "ticker", "theme", "weekly_conviction_score", "portfolio_fit_score",
    "holding_horizon_candidate", "recommendation_label", "recommendation_confidence",
    "candidate_for_week", "suggested_review_size_pct", "review_reason", "human_action_required",
    "automatic_action_allowed",
]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "research_rows", "current_position_rows", "new_candidate_rows", "eligible_buy_review_count",
    "email_sent", "scheduler_used", "broker_used", "smtp_config_modified",
    "archived_legacy_used", "safety_notes",
]
FORMULA = "0.25*business + 0.20*earnings + 0.15*valuation + 0.15*catalyst + 0.15*technical + 0.10*portfolio_fit"


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_log(total: int, current: int, eligible: int) -> None:
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5", "script_name": Path(__file__).name,
            "action": "score_weekly_conviction",
            "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [PACKETS, CONCENTRATION]),
            "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [SCORES, POSITION_RECOMMENDATIONS, NEW_RECOMMENDATIONS]),
            "status": "complete", "research_rows": str(total), "current_position_rows": str(current),
            "new_candidate_rows": str(total - current), "eligible_buy_review_count": str(eligible),
            "email_sent": "no", "scheduler_used": "no", "broker_used": "no",
            "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "weighted_weekly_score=yes; concentration_override=yes; manual_review_only=yes",
        })


def main() -> None:
    packets = read_csv(PACKETS)
    concentration_rows = read_csv(CONCENTRATION)
    position_pct = {
        row["ticker"].upper(): float(row["position_pct"])
        for row in concentration_rows if row["record_type"] == "position"
    }
    portfolio = next(row for row in concentration_rows if row["record_type"] == "portfolio_summary")
    sleeve_above = portfolio["active_stock_sleeve_status"] == "above_target"

    scored: list[dict[str, str]] = []
    for packet in packets:
        components = [
            float(packet["business_quality_score"]), float(packet["earnings_revenue_trend_score"]),
            float(packet["valuation_reasonableness_score"]), float(packet["catalyst_news_quality_score"]),
            float(packet["technical_entry_discipline_score"]), float(packet["portfolio_fit_score"]),
        ]
        score = round(
            0.25 * components[0] + 0.20 * components[1] + 0.15 * components[2]
            + 0.15 * components[3] + 0.15 * components[4] + 0.10 * components[5], 2
        )
        ticker = packet["ticker"]
        is_current = packet["research_role"] == "current_position_risk_review"
        pct = position_pct.get(ticker, 0.0)
        if is_current and pct > 8.0:
            label = "trim_review"
            rule = "single_stock_above_8_pct_no_add"
        elif is_current:
            label = "hold_existing" if score >= 6.0 else "exit_review"
            rule = "current_position_thesis_review"
        elif sleeve_above:
            label = "wait_for_pullback" if score >= 7.0 or ticker == "SPY" else "watch_only"
            rule = "active_stock_sleeve_above_30_pct"
        else:
            label = "eligible_buy_review" if score >= 8.0 else "wait_for_pullback" if score >= 7.0 else "watch_only"
            rule = "weekly_candidate_threshold"
        scored.append({
            "weekly_rank": "", "ticker": ticker, "research_role": packet["research_role"],
            "business_quality_score": f"{components[0]:.1f}", "earnings_revenue_trend_score": f"{components[1]:.1f}",
            "valuation_reasonableness_score": f"{components[2]:.1f}", "catalyst_news_quality_score": f"{components[3]:.1f}",
            "technical_entry_discipline_score": f"{components[4]:.1f}", "portfolio_fit_score": f"{components[5]:.1f}",
            "weekly_conviction_score": f"{score:.2f}", "holding_horizon_candidate": packet["holding_horizon_candidate"],
            "recommendation_label": label, "recommendation_confidence": packet["recommendation_confidence"],
            "portfolio_rule_applied": rule, "human_action_required": "yes", "score_formula": FORMULA,
        })

    scored.sort(key=lambda row: (row["research_role"] != "current_position_risk_review", -float(row["weekly_conviction_score"]), row["ticker"]))
    for rank, row in enumerate(scored, start=1):
        row["weekly_rank"] = str(rank)
    eligible_rows = [row for row in scored if row["recommendation_label"] == "eligible_buy_review"][:2]
    eligible_tickers = {row["ticker"] for row in eligible_rows}
    for row in scored:
        if row["recommendation_label"] == "eligible_buy_review" and row["ticker"] not in eligible_tickers:
            row["recommendation_label"] = "wait_for_pullback"
            row["portfolio_rule_applied"] = "weekly_new_candidate_cap"

    packet_by_ticker = {row["ticker"]: row for row in packets}
    position_rows: list[dict[str, str]] = []
    new_rows: list[dict[str, str]] = []
    for row in scored:
        packet = packet_by_ticker[row["ticker"]]
        if row["research_role"] == "current_position_risk_review":
            pct = position_pct[row["ticker"]]
            position_rows.append({
                "priority": str(len(position_rows) + 1), "ticker": row["ticker"], "position_pct": f"{pct:.2f}",
                "portfolio_concentration_status": packet["portfolio_concentration_status"],
                "weekly_conviction_score": row["weekly_conviction_score"],
                "holding_horizon_candidate": row["holding_horizon_candidate"],
                "recommendation_label": row["recommendation_label"],
                "recommendation_confidence": row["recommendation_confidence"],
                "review_reason": f"Current weight {pct:.2f}% exceeds the 8% hard cap; review concentration even though company evidence remains constructive.",
                "exit_or_trim_conditions": packet["exit_or_trim_conditions"], "human_action_required": "yes",
                "automatic_action_allowed": "no",
            })
        else:
            label = row["recommendation_label"]
            new_rows.append({
                "weekly_rank": row["weekly_rank"], "ticker": row["ticker"], "theme": packet["theme"],
                "weekly_conviction_score": row["weekly_conviction_score"], "portfolio_fit_score": row["portfolio_fit_score"],
                "holding_horizon_candidate": row["holding_horizon_candidate"], "recommendation_label": label,
                "recommendation_confidence": row["recommendation_confidence"],
                "candidate_for_week": "yes" if label == "eligible_buy_review" else "no",
                "suggested_review_size_pct": "2.00" if label == "eligible_buy_review" else "0.00",
                "review_reason": "Continue weekly review; current sleeve concentration prevents a fresh sizing review." if sleeve_above else "Continue weekly evidence and entry review.",
                "human_action_required": "yes", "automatic_action_allowed": "no",
            })

    write_csv(SCORES, scored, SCORE_FIELDS)
    write_csv(POSITION_RECOMMENDATIONS, position_rows, POSITION_FIELDS)
    write_csv(NEW_RECOMMENDATIONS, new_rows, NEW_FIELDS)
    eligible_count = sum(row["recommendation_label"] == "eligible_buy_review" for row in new_rows)
    append_log(len(scored), len(position_rows), eligible_count)
    print(f"Scored Phase 5R-C5 weekly conviction: rows={len(scored)}; eligible_new={eligible_count}")


if __name__ == "__main__":
    main()
