from __future__ import annotations

import csv
import html
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
AUTOMATION_DIR = ROOT / "07_automation" / "email_briefs"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c1_run_log.csv"

SCORES_PATH = DATA_DIR / "phase5r_b2_signal_scores.csv"
TICKETS_PATH = DATA_DIR / "phase5r_b2_manual_trade_tickets.csv"
QUALITY_PATH = DATA_DIR / "phase5r_b2_market_data_quality_report.csv"
SNAPSHOT_PATH = DATA_DIR / "phase5r_b2_market_data_snapshot.csv"
SUBJECT_PATH = AUTOMATION_DIR / "phase5r_c1_daily_email_subject.txt"
TEXT_PATH = AUTOMATION_DIR / "phase5r_c1_daily_email_body.txt"
HTML_PATH = AUTOMATION_DIR / "phase5r_c1_daily_email_body.html"
METADATA_PATH = AUTOMATION_DIR / "phase5r_c1_email_brief_metadata.csv"
PREVIEW_PATH = REVIEWS_DIR / "latest_phase5r_c1_email_preview.md"
REPORT_PATH = RESEARCH_DIR / "phase5r_c1_email_brief_report.md"

LEGACY_TICKERS = {"IOT", "RBRK"}
METADATA_FIELDS = [
    "generated_at", "source_scores_path", "source_tickets_path", "manual_review_count", "watch_count",
    "avoid_count", "insufficient_data_count", "top_manual_review_tickers", "top_watch_tickers", "email_subject",
    "send_allowed", "delivery_phase",
]
LOG_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "safety_notes"]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_log(status: str, output_paths: list[Path]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp(),
                "script_name": Path(__file__).name,
                "action": "compose_phase5r_c1_daily_email_brief",
                "input_path": ";".join(str(path.relative_to(ROOT)) for path in [SCORES_PATH, TICKETS_PATH, QUALITY_PATH, SNAPSHOT_PATH]),
                "output_path": ";".join(str(path.relative_to(ROOT)) for path in output_paths),
                "status": status,
                "safety_notes": "compose_only=yes; send_allowed=no; no_delivery=yes; no_broker=yes; no_orders=yes; no_credentials=yes; no_env=yes; no_scheduler=yes; no_intraday_alerts=yes; archived_legacy_used=no",
            }
        )


def format_change(value: str) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def ticker_list(rows: list[dict[str, str]]) -> str:
    return ", ".join(row["ticker"] for row in rows) if rows else "None"


def candidate_line(row: dict[str, str]) -> str:
    return f"{row['ticker']} | {row['theme']} | ${row['last_price']} | score {row['total_score']} | {format_change(row['intraday_change_pct'])}"


def html_table(rows: list[dict[str, str]], heading: str, action_name: str) -> str:
    if not rows:
        return f"<h2>{html.escape(heading)}</h2><p>None today.</p>"
    lines = [
        f"<h2>{html.escape(heading)}</h2>",
        "<table>",
        "<thead><tr><th>Ticker</th><th>Theme</th><th>Price</th><th>Daily change</th><th>Score</th><th>Research label</th></tr></thead><tbody>",
    ]
    for row in rows:
        lines.append(
            "<tr>"
            f"<td>{html.escape(row['ticker'])}</td><td>{html.escape(row['theme'])}</td>"
            f"<td>${html.escape(row['last_price'])}</td><td>{html.escape(format_change(row['intraday_change_pct']))}</td>"
            f"<td>{html.escape(row['total_score'])}</td><td>{html.escape(action_name)}</td></tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def main() -> None:
    scores = read_csv(SCORES_PATH)
    tickets = read_csv(TICKETS_PATH)
    quality = read_csv(QUALITY_PATH)
    snapshot = read_csv(SNAPSHOT_PATH)
    all_tickers = {row["ticker"].upper() for row in scores + tickets + quality + snapshot}
    if all_tickers & LEGACY_TICKERS:
        raise RuntimeError("Legacy holding tickers are excluded from the C1 daily brief")

    scores.sort(key=lambda row: int(row["rank"]))
    counts = {label: sum(row["action_label"] == label for row in scores) for label in ("possible_buy_manual_review", "watch", "avoid", "insufficient_data")}
    manual_rows = [row for row in scores if row["action_label"] == "possible_buy_manual_review"][:3]
    watch_rows = [row for row in scores if row["action_label"] == "watch"][:5]
    avoid_rows = [row for row in scores if row["action_label"] == "avoid"][:3]
    quality_counts: dict[str, int] = {}
    for row in quality:
        quality_counts[row["data_quality_label"]] = quality_counts.get(row["data_quality_label"], 0) + 1
    benchmark = {row["ticker"]: row for row in snapshot if row["ticker"] in {"QQQ", "XLK", "SPY"}}
    benchmark_summary = "; ".join(
        f"{ticker} {format_change(benchmark.get(ticker, {}).get('intraday_change_pct', ''))}"
        for ticker in ("QQQ", "XLK", "SPY")
    )
    generated_at = timestamp()
    brief_date = generated_at[:10]
    subject = f"Daily AI Equity Brief — {brief_date} — {counts['possible_buy_manual_review']} Review / {counts['watch']} Watch / {counts['avoid']} Avoid"

    text_lines = [
        "Header",
        f"Daily AI Equity Brief - {brief_date}",
        "Research-only daily summary. Independent human review is required for every action.",
        "",
        "Market Data Status",
        f"- Public yfinance snapshot: {len(snapshot)} rows; quality: {quality_counts}.",
        f"- Market regime summary: {benchmark_summary}. This is context only, not a time-sensitive alert.",
        "- Prices and volumes may be delayed because yfinance is a public market-data source.",
        "",
        "Today's Manual-Review Candidates",
    ]
    if manual_rows:
        text_lines.extend(f"- Manual-review candidate: {candidate_line(row)}" for row in manual_rows)
    else:
        text_lines.append("- None today.")
    text_lines.extend(["", "Top Watchlist"])
    if watch_rows:
        text_lines.extend(f"- Watch: {candidate_line(row)}" for row in watch_rows)
    else:
        text_lines.append("- None today.")
    text_lines.extend(["", "Lower-Priority / Avoid Today", f"- Lower priority / avoid today: {counts['avoid']} total."])
    text_lines.extend(f"- {row['ticker']} | score {row['total_score']} | {row['theme']}" for row in avoid_rows)
    text_lines.extend([
        "",
        "Manual Review Checklist",
        "- Confirm current public data, market context, company news, liquidity, and the research assumptions independently.",
        "- Re-check the risk policy and decide manually whether any further research is warranted.",
        "- Treat the score as prioritization only; it is not investment advice.",
        "",
        "Safety Boundary",
        "- This system cannot connect to a broker or initiate a market transaction.",
        "- This brief is composed locally only; it is not delivered to any recipient.",
        "- No legacy holdings or archived data are included.",
    ])
    text_body = "\n".join(text_lines) + "\n"

    html_sections = [
        "<!doctype html>", "<html><head><meta charset=\"utf-8\"><title>Daily AI Equity Brief</title></head><body>",
        f"<h1>Daily AI Equity Brief - {html.escape(brief_date)}</h1>",
        "<h2>Header</h2>",
        "<p>Research-only daily summary. Independent human review is required for every action.</p>",
        "<h2>Market Data Status</h2>",
        f"<p>Public yfinance snapshot: {len(snapshot)} rows; quality: {html.escape(str(quality_counts))}.</p>",
        f"<p>Market regime summary: {html.escape(benchmark_summary)}. This is context only, not a time-sensitive alert.</p>",
        "<p>Prices and volumes may be delayed because yfinance is a public market-data source.</p>",
        html_table(manual_rows, "Today's Manual-Review Candidates", "Manual-review candidate"),
        html_table(watch_rows, "Top Watchlist", "Watch"),
        html_table(avoid_rows, "Lower-Priority / Avoid Today", "Lower priority / avoid today"),
        "<h2>Manual Review Checklist</h2><ul><li>Confirm public data, market context, company news, liquidity, and research assumptions independently.</li><li>Re-check the risk policy before any manual decision.</li><li>Treat the score as prioritization only, not investment advice.</li></ul>",
        "<h2>Safety Boundary</h2><ul><li>This system cannot connect to a broker or initiate a market transaction.</li><li>This brief is composed locally only and is not delivered to any recipient.</li><li>No legacy holdings or archived data are included.</li></ul>",
        "</body></html>",
    ]
    html_body = "\n".join(html_sections) + "\n"

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    SUBJECT_PATH.write_text(subject + "\n", encoding="utf-8")
    TEXT_PATH.write_text(text_body, encoding="utf-8")
    HTML_PATH.write_text(html_body, encoding="utf-8")
    metadata = {
        "generated_at": generated_at,
        "source_scores_path": str(SCORES_PATH.relative_to(ROOT)),
        "source_tickets_path": str(TICKETS_PATH.relative_to(ROOT)),
        "manual_review_count": str(counts["possible_buy_manual_review"]),
        "watch_count": str(counts["watch"]),
        "avoid_count": str(counts["avoid"]),
        "insufficient_data_count": str(counts["insufficient_data"]),
        "top_manual_review_tickers": ticker_list(manual_rows),
        "top_watch_tickers": ticker_list(watch_rows),
        "email_subject": subject,
        "send_allowed": "no",
        "delivery_phase": "phase5r_c1_compose_only",
    }
    write_csv(METADATA_PATH, [metadata], METADATA_FIELDS)

    preview_lines = [
        "# Latest Phase 5R-C1 Email Preview", "", f"Subject: `{subject}`", "",
        "This is a local compose-only preview. No email was sent.", "", "```text", text_body.rstrip(), "```",
    ]
    PREVIEW_PATH.write_text("\n".join(preview_lines) + "\n", encoding="utf-8")
    report_lines = [
        "# Phase 5R-C1 Email Brief Report", "", f"Generated: `{generated_at}`", "",
        "## Composition Summary", "", f"- Source score rows: `{len(scores)}`.", f"- Source ticket rows: `{len(tickets)}`.",
        f"- Manual-review candidates shown: `{len(manual_rows)}`.", f"- Watch candidates shown: `{len(watch_rows)}`.", f"- Lower-priority examples shown: `{len(avoid_rows)}`.",
        "- Delivery: `not enabled`.", "", "## Boundary", "", "The C1 composer writes local subject, plain-text, HTML, metadata, and Markdown preview artifacts only. It does not access recipients, credentials, email providers, brokers, archived legacy data, or transaction-placement workflows.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    append_log("complete", [SUBJECT_PATH, TEXT_PATH, HTML_PATH, METADATA_PATH, PREVIEW_PATH, REPORT_PATH])
    print(f"Wrote Phase 5R-C1 local email brief; subject={subject}")


if __name__ == "__main__":
    main()
