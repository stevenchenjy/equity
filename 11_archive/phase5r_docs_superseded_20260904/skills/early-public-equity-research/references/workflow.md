# Workflow

This workflow keeps research consistent while preserving the project boundary: research and journaling only, no brokerage connection and no trade execution.

## 1. Universe

Update `01_universe/universe.csv` with candidate rows only when the ticker is publicly listed and has source links. Use `MISSING` for unknown financial fields. Do not invent figures.

Allowed workflow statuses are research-oriented labels such as `candidate` and `watchlist`. Do not use `real_trade_candidate` during test or dry-run phases.

## 2. Screening

Run:

```bash
python3 05_scripts/screen_universe.py
```

Review `04_data/screening_results.csv` for low price, low dollar volume, short runway, dilution flags, 8-K risk flags, and missing source links.

## 3. SEC Metadata

Run the SEC fetcher only for controlled subsets:

```bash
python3 05_scripts/update_sec_filings.py
```

The script must use public SEC endpoints only, polite pacing, and the project User-Agent. Raw JSON belongs in `02_filings/sec_raw/`; filing notes belong in `02_filings/filing_notes/`.

## 4. GPT Packets

Run:

```bash
python3 05_scripts/make_gpt_packet.py
```

Packets in `03_research/gpt_packets/` combine universe data, screening results, SEC filing notes, and boundary reminders. They are metadata packets for controlled research workflow testing, not recommendations.

## 5. Company Memo

Create or update a company memo in `03_research/` using the memo template. Keep facts, estimates, and opinions separate. Cite SEC filings or official sources. Unknown facts stay `MISSING`.

## 6. Red-Team Review

Before any paper-trade planning, write a red-team note covering business model, liquidity, dilution, cash runway, valuation, event, sector-specific, and invalidation risks.

## 7. Risk Calculation

Run the risk calculator only for approved paper-trade planning:

The following `2000` input is an example fixture, not current account truth.

```bash
python3 05_scripts/risk_calculator.py --account-value 2000 --risk-percent 1 --entry-price 20 --stop-price 18
```

The calculator does not place trades. Any real order requires human approval outside this repo.

## 8. Journal And Review

Update journals in `06_trading/` only with research-safe information. Do not store credentials or brokerage details. Generate the weekly report:

```bash
python3 05_scripts/make_weekly_report.py
```

Review warnings before expanding the universe or planning paper trades.
