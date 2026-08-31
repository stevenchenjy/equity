# Phase 5R-B1 Install Instructions

Generated: `2026-07-09T12:29:14-05:00`

Current `yfinance` status: `missing`.

## Install Command

```bash
python3 -m pip install yfinance
```

After installation, rerun:

```bash
python3 09_scripts/phase5r/check_phase5r_b1_market_data_source.py
python3 09_scripts/phase5r/verify_phase5r_b1_data_enablement.py
```

This enables only read-only public market data checks. It does not connect to a broker, place orders, read `.env`, use API keys, or send email.
