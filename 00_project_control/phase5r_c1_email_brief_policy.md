# Phase 5R-C1 Daily Email Brief Policy

## Purpose

Phase 5R-C1 composes a local, low-attention daily AI equity research brief from canonical Phase 5R-B2 outputs. It does not deliver a message to any recipient.

## Allowed Inputs

- `03_source_data/phase5r/phase5r_b2_signal_scores.csv`
- `03_source_data/phase5r/phase5r_b2_manual_trade_tickets.csv`
- `03_source_data/phase5r/phase5r_b2_market_data_quality_report.csv`
- `03_source_data/phase5r/phase5r_b2_market_data_snapshot.csv`

## Brief Content

- The brief summarizes one daily public-data snapshot, market-data status, limited research priorities, and a manual review checklist.
- It shows at most three manual-review candidates, five watch candidates, and three lower-priority examples.
- The brief describes public yfinance data as potentially delayed and makes clear that independent human review is required.
- The brief is research context only and does not contain time-sensitive execution language.

## Delivery Boundary

- `send_allowed=no` for every C1 metadata record.
- No SMTP, Gmail, Outlook, IMAP, recipient handling, delivery integration, credential, API key, or `.env` access is permitted.
- No broker connection, transaction-placement capability, scheduler, intraday alert, or repeated-notification mechanism is permitted.
- Legacy archived data and legacy holding context are outside the C1 input boundary.
- Phase 5R-C2 is not created in this phase.
