# Phase 5R Dependency Check Report

Generated: `2026-07-08T23:32:39-05:00`

Phase 5R-A read and respected the Phase 0C dependency allowlist.

## Allowlist Summary

- Allowlist rows read: `23`.
- Required allowed workflow paths missing: `0`.
- Optional review items intentionally not used: `03_research/company_memo_template.md`, `05_scripts/risk_calculator.py`.
- Legacy real-position, trade-log, email, and IOT/RBRK holding data dependencies used: `0`.

## Allowed Core/Optional Workflows

- `05_scripts/enrich_candidate_financials.py`: financial_enrichment
- `05_scripts/make_gpt_packet.py`: gpt_packet_generation
- `05_scripts/screen_universe.py`: candidate_universe_screening
- `05_scripts/update_sec_filings.py`: sec_filing_ingestion
- `05_scripts/validate_manual_market_data.py`: manual_market_data_validation
