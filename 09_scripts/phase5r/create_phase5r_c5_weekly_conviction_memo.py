from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_c5_run_log.csv"
SCORES = RESEARCH_DIR / "phase5r_c5_weekly_conviction_scores.csv"
POSITIONS = RESEARCH_DIR / "phase5r_c5_position_review_recommendations.csv"
NEW_CANDIDATES = RESEARCH_DIR / "phase5r_c5_new_candidate_recommendations.csv"
OUTPUT = RESEARCH_DIR / "phase5r_c5_weekly_conviction_memo.md"
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "research_rows", "current_position_rows", "new_candidate_rows", "eligible_buy_review_count",
    "email_sent", "scheduler_used", "broker_used", "smtp_config_modified",
    "archived_legacy_used", "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def append_log(total: int, current: int, new: int, eligible: int) -> None:
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5", "script_name": Path(__file__).name,
            "action": "create_weekly_conviction_memo",
            "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [SCORES, POSITIONS, NEW_CANDIDATES]),
            "output_paths": str(OUTPUT.relative_to(ROOT)), "status": "complete", "research_rows": str(total),
            "current_position_rows": str(current), "new_candidate_rows": str(new),
            "eligible_buy_review_count": str(eligible), "email_sent": "no", "scheduler_used": "no",
            "broker_used": "no", "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "weekly_memo_only=yes; no_delivery=yes; manual_review_only=yes",
        })


def main() -> None:
    scores = read_csv(SCORES)
    positions = read_csv(POSITIONS)
    candidates = read_csv(NEW_CANDIDATES)
    eligible = [row for row in candidates if row["recommendation_label"] == "eligible_buy_review"]
    waits = [row for row in candidates if row["recommendation_label"] == "wait_for_pullback"]
    watches = [row for row in candidates if row["recommendation_label"] == "watch_only"]
    next_review = date.today() + timedelta(days=7)
    lines = [
        "# Phase 5R-C5 Weekly Conviction Memo", "", f"Generated: `{timestamp()}`", "",
        "## 1. Executive Summary", "",
        f"This weekly review covers `{len(positions)}` current positions and `{len(candidates)}` new research names. "
        f"The active stock sleeve remains above its 30% target, and both current positions exceed the 8% single-stock hard cap. "
        f"New eligible candidates this week: `{len(eligible)}`. The research posture is concentration-first and patient.", "",
        "## 2. Current Position Review First", "",
        "| Ticker | Weight | Conviction Score | Horizon | Weekly Label | Review Focus |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]
    score_by_ticker = {row["ticker"]: row for row in scores}
    for row in positions:
        lines.append(
            f"| {row['ticker']} | {row['position_pct']}% | {row['weekly_conviction_score']} | "
            f"{row['holding_horizon_candidate']} | {row['recommendation_label']} | Concentration and thesis durability |"
        )
    lines.extend(["", "Both IOT and RBRK retain constructive company evidence, but current weights make `trim_review` the appropriate weekly label. This is a research review, not an automatic portfolio change.", "",
                  "## 3. New Candidate Review Second", "",
                  "| Ticker | Theme | Conviction Score | Portfolio Fit | Horizon | Weekly Label |",
                  "| --- | --- | ---: | ---: | --- | --- |"])
    for row in sorted(candidates, key=lambda item: int(item["weekly_rank"])):
        lines.append(
            f"| {row['ticker']} | {row['theme']} | {row['weekly_conviction_score']} | {row['portfolio_fit_score']} | "
            f"{row['holding_horizon_candidate']} | {row['recommendation_label']} |"
        )
    lines.extend(["", "META has the strongest company-plus-market score in the new-name set, while SPY offers the clearest diversification role. Both remain in a wait posture because the current sleeve is above target. AI-infrastructure names carry an additional theme-overlap penalty.", "",
                  "## 4. This Week's Recommended Actions", "",
                  "- Review IOT and RBRK concentration first; consider a trim review while each remains above the hard cap.",
                  f"- Wait on {', '.join(row['ticker'] for row in waits) if waits else 'new candidates'} until portfolio fit and entry conditions improve.",
                  f"- Keep {', '.join(row['ticker'] for row in watches) if watches else 'remaining candidates'} as watch-only research.",
                  f"- New eligible candidate count remains `{len(eligible)}`, within the weekly limit of zero to two.", "",
                  "## 5. What Not To Do This Week", "",
                  "- Do not increase IOT or RBRK while either remains above the 8% hard cap.",
                  "- Do not react to a single strong market day or chase AI-theme momentum.",
                  "- Do not treat a research label as authority for a portfolio transaction.",
                  "- Do not expand the active sleeve before concentration is reviewed.", "",
                  "## 6. Next Review Date", "", f"Next scheduled weekly research review: `{next_review.isoformat()}`.", "",
                  "All conclusions require independent human review. Public data can be delayed, source evidence can change, and no project component can alter a brokerage account."])
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_log(len(scores), len(positions), len(candidates), len(eligible))
    print(f"Created Phase 5R-C5 weekly memo; eligible_new={len(eligible)}")


if __name__ == "__main__":
    main()
