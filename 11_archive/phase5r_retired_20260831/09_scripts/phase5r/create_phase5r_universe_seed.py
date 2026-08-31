from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "00_project_control" / "phase0c_phase5r_dependency_allowlist.csv"
UNIVERSE_PATH = ROOT / "04_data" / "phase5r_universe_seed.csv"
AUDIT_TRAIL = ROOT / "04_data" / "phase5r_audit_trail.csv"
RUN_LOG = ROOT / "06_logs" / "phase5r_a_run_log.csv"

UNIVERSE_FIELDS = [
    "ticker",
    "company_name",
    "sector",
    "industry",
    "theme",
    "liquidity_tier",
    "volatility_tier",
    "is_benchmark",
    "max_position_pct",
    "notes",
]

AUDIT_FIELDS = [
    "timestamp",
    "script_name",
    "action",
    "input_path",
    "output_path",
    "status",
    "safety_notes",
]


UNIVERSE_ROWS = [
    ["NVDA", "NVIDIA Corporation", "Technology", "Semiconductors", "AI infrastructure", "mega", "high", "no", "4.0", "AI accelerator bellwether; placeholder only"],
    ["AMD", "Advanced Micro Devices", "Technology", "Semiconductors", "AI infrastructure", "large", "high", "no", "3.5", "AI/CPU/GPU peer; placeholder only"],
    ["AVGO", "Broadcom Inc.", "Technology", "Semiconductors", "AI infrastructure", "mega", "medium", "no", "4.0", "Networking and custom silicon exposure"],
    ["TSM", "Taiwan Semiconductor Manufacturing Company", "Technology", "Semiconductors", "AI infrastructure", "mega", "medium", "no", "3.0", "Foundry exposure; geopolitical risk requires review"],
    ["ASML", "ASML Holding", "Technology", "Semiconductor Equipment", "Semiconductors", "large", "medium", "no", "3.0", "Lithography equipment leader"],
    ["ARM", "Arm Holdings", "Technology", "Semiconductors", "AI infrastructure", "large", "high", "no", "2.5", "High valuation and volatility"],
    ["MU", "Micron Technology", "Technology", "Memory Semiconductors", "AI infrastructure", "large", "high", "no", "2.5", "Memory cycle exposure"],
    ["SMCI", "Super Micro Computer", "Technology", "Computer Hardware", "Data centers", "large", "very_high", "no", "2.0", "High-volatility AI server exposure"],
    ["VRT", "Vertiv Holdings", "Industrials", "Electrical Equipment", "Data centers", "large", "high", "no", "2.5", "Data-center power/cooling exposure"],
    ["EQIX", "Equinix", "Real Estate", "Data Center REIT", "Data centers", "large", "medium", "no", "2.5", "Data-center infrastructure benchmark"],
    ["DLR", "Digital Realty Trust", "Real Estate", "Data Center REIT", "Data centers", "large", "medium", "no", "2.0", "Data-center REIT exposure"],
    ["MSFT", "Microsoft Corporation", "Technology", "Cloud Software", "Cloud software", "mega", "low", "no", "5.0", "Cloud and AI platform leader"],
    ["GOOGL", "Alphabet Inc.", "Communication Services", "Internet Content", "AI infrastructure", "mega", "medium", "no", "4.0", "AI/search/cloud exposure"],
    ["AMZN", "Amazon.com Inc.", "Consumer Discretionary", "Cloud and E-commerce", "Cloud software", "mega", "medium", "no", "4.0", "AWS and consumer platform exposure"],
    ["META", "Meta Platforms", "Communication Services", "Internet Content", "AI infrastructure", "mega", "medium", "no", "4.0", "AI infrastructure and advertising exposure"],
    ["ORCL", "Oracle Corporation", "Technology", "Cloud Software", "Cloud software", "large", "medium", "no", "3.0", "Cloud infrastructure and database exposure"],
    ["NOW", "ServiceNow", "Technology", "Application Software", "Cloud software", "large", "medium", "no", "3.0", "Enterprise workflow software"],
    ["CRM", "Salesforce", "Technology", "Application Software", "Cloud software", "large", "medium", "no", "2.5", "Enterprise software benchmark"],
    ["SNOW", "Snowflake", "Technology", "Data Platform Software", "Cloud software", "large", "high", "no", "2.0", "Data platform growth exposure"],
    ["DDOG", "Datadog", "Technology", "Observability Software", "Cloud software", "large", "high", "no", "2.0", "Cloud observability growth exposure"],
    ["NET", "Cloudflare", "Technology", "Edge Cloud Software", "Cybersecurity", "large", "high", "no", "2.0", "Security and edge network exposure"],
    ["CRWD", "CrowdStrike", "Technology", "Cybersecurity", "Cybersecurity", "large", "high", "no", "2.0", "Endpoint security growth exposure"],
    ["PANW", "Palo Alto Networks", "Technology", "Cybersecurity", "Cybersecurity", "large", "medium", "no", "2.5", "Cybersecurity platform leader"],
    ["ZS", "Zscaler", "Technology", "Cybersecurity", "Cybersecurity", "large", "high", "no", "2.0", "Zero-trust security exposure"],
    ["QQQ", "Invesco QQQ Trust", "ETF", "Benchmark ETF", "Benchmark ETF", "mega", "medium", "yes", "10.0", "Nasdaq-100 benchmark"],
    ["XLK", "Technology Select Sector SPDR Fund", "ETF", "Benchmark ETF", "Benchmark ETF", "mega", "medium", "yes", "10.0", "Technology sector benchmark"],
    ["SPY", "SPDR S&P 500 ETF Trust", "ETF", "Benchmark ETF", "Benchmark ETF", "mega", "low", "yes", "10.0", "Broad market benchmark"],
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def read_allowlist() -> list[dict[str, str]]:
    with ALLOWLIST.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    allowlist = read_allowlist()
    workflow_paths = {row["relative_path"] for row in allowlist if row["dependency_type"] == "workflow_script"}
    required_workflow = "05_scripts/screen_universe.py"
    if required_workflow not in workflow_paths:
        raise RuntimeError(f"Phase 0C allowlist does not include {required_workflow}")

    tickers = [row[0] for row in UNIVERSE_ROWS]
    forbidden = {"IOT", "RBRK"} & set(tickers)
    if forbidden:
        raise RuntimeError(f"Legacy ticker(s) are not allowed in Phase 5R seed: {sorted(forbidden)}")
    if len(tickers) != len(set(tickers)):
        raise RuntimeError("Universe seed contains duplicate tickers")

    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with UNIVERSE_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(UNIVERSE_FIELDS)
        writer.writerows(UNIVERSE_ROWS)

    now = timestamp()
    safety = "allowlist_read=yes; static_seed=yes; no_env_read=yes; no_broker=yes; old_iot_rbrk_data_used=no"
    append_csv(
        AUDIT_TRAIL,
        {
            "timestamp": now,
            "script_name": Path(__file__).name,
            "action": "create_phase5r_universe_seed",
            "input_path": str(ALLOWLIST.relative_to(ROOT)),
            "output_path": str(UNIVERSE_PATH.relative_to(ROOT)),
            "status": "complete",
            "safety_notes": safety,
        },
        AUDIT_FIELDS,
    )
    append_csv(
        RUN_LOG,
        {
            "timestamp": now,
            "script_name": Path(__file__).name,
            "action": "create_phase5r_universe_seed",
            "input_path": str(ALLOWLIST.relative_to(ROOT)),
            "output_path": str(UNIVERSE_PATH.relative_to(ROOT)),
            "status": "complete",
            "safety_notes": safety,
        },
        AUDIT_FIELDS,
    )
    print(f"Wrote {len(UNIVERSE_ROWS)} Phase 5R universe rows to {UNIVERSE_PATH}")


if __name__ == "__main__":
    main()
