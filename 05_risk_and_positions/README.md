# Current portfolio files

Start with [the daily decision](../04_research/company_research/daily_decision.md)
and [the maintained plans](../08_reviews/current/maintained_plans.local.md).
These are research views; no file authorizes an automatic trade.

The root of this folder contains private current inputs: positions, account
state, open orders, investment plans, and their receipts. Do not use the
examples as current account data.

- `generated/current/` contains replaceable calculations and execution
  reports. They are supporting data, not the maintained decision.
- `examples/` contains blank/example starting files.
- `../11_archive/portfolio_versions.local/` contains exact prior file bytes,
  organized by original relative path and SHA-256. It is private and ignored
  by Git. The existing `manual_snapshots.local/` remains the owner snapshot
  receipt archive.

Managed portfolio writers preserve a changed predecessor before replacing it.
The daily refresh also snapshots current inputs and outputs before and after
the run so an owner edit made between runs has a retained version. For manual
cash/share changes, use `update_manual_account.py --preview` followed by
`--apply`; for confirmed fills, use the existing reconciliation command. If
editing open orders or another private input directly, run the archive command
before and after the edit:

```sh
python3 09_scripts/equity_research/archive_portfolio_state.py
```

Archived files are never read as a fallback for missing current inputs.
