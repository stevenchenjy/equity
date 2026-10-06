# Current portfolio files

Start with [the daily decision](../04_research/company_research/daily_decision.md)
and [the maintained plans](/Users/messssi/LocalRuntime/equity/08_reviews/current/maintained_plans.local.md).
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

For an explicitly approved allocation-policy change, use the metadata-only
writer after deploying the matching configuration:

```sh
python3 09_scripts/equity_research/migrate_allocation_policy.py --root /Users/messssi/LocalRuntime/equity --check
python3 09_scripts/equity_research/migrate_allocation_policy.py --root /Users/messssi/LocalRuntime/equity --apply --request-reference "Owner allocation instruction 2026-10-06"
```

It acquires runtime, pipeline and policy-writer locks itself; do not invoke it
while already holding those locks in a parent process. It changes allocation
metadata only, preserving cash, holdings, orders, planning capital and the
original account `last_updated`. Exact predecessors and a private receipt are
retained under `allocation_policy_migrations.local/`. An already matching
manual snapshot may have its account hash rebound with an explicit policy-only
receipt; its original observation time is retained. A stale snapshot is never
made current. Migration receipts prove only a metadata transition: a current
account hash may be equivalent to its previously reconciled hash only after
checking the exact archived predecessor, unchanged financial facts and clock,
approved configuration, positions, orders, confirmed ledger and manual receipt.
The archived bytes are proof of identity, never fallback current inputs.
Publication binds this proof and requires recomposition if it changes. A later
genuine owner snapshot has its own authority; an old policy receipt cannot
replace or refresh it. Missing or invalid proof does not waive a conflict.
These receipts are not current evidence of broker cash, holdings, fills or
orders. Run the existing full no-send refresh
after the writer releases locks to recompose downstream policy consumers.
