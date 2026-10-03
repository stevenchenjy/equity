# Momentum experiment reproducibility

The experimental EOD breakout observation system is research only. Its five-session model, cost sensitivities, first-observation time and manual-review threshold remain governed by the frozen policy. Deployment of a shared production helper must not restart, retune or retrospectively recapture a cohort.

## Immutable execution and admission

`01_policies/momentum_implementation_archives.json` explicitly binds each observed version to a Git commit, the original recorded implementation hashes, and the complete import-time runtime closure with its policy and display configuration. `frozen_momentum_runtime.py` verifies the registered Git bytes and dependencies before running capture or outcomes in isolated Python processes. Missing objects, a missing transitive dependency, an unregistered version, or a changed policy under the same version fails closed. Production cannot fall back to its mutable shared helpers.

The recovered v4 binding is commit `ad5b57e4d68d5cc1f1ffd57f1a06e5d424bee0c9`, whose original five implementation hashes exactly match the retained observations. The existing v1–v3 bindings retain their original commits and publication clocks. The repair changes execution infrastructure; it does not change those experimental versions or create observations for the missed September 30–October 1 capture attempts.

All capture and outcome changes are first written to a private staged ledger. Its full hash chain, immutable prior prefix, version bindings and report hash must pass before publication. A late archive/evaluation failure cannot publish a partial set of new observations. Run attempts remain a separate ledger and retain failed runs. Successful runs retain exact admitted input bytes in `input_history/<sha256>` and a prepared/published receipt in `publication_history/`. `report.json.frozen_execution` records Git, runtime and policy hashes, interpreter version, input artifact locators, and prior/result ledger hashes. These private directories must travel with the existing experiment ledger in a backup or migration.

## Retired names and missing evidence

The canonical market universe remains unchanged. After a successful network-enabled canonical market fetch, the existing collector separately requests prices for unfinished experimental observations outside current coverage. It uses the same authenticated public provider and pacing, makes at most one request per pending retired ticker per attempt, and never adds those names to canonical snapshots, scores, recommendations or new capture. A coherent cache for the same close is reused; the supplemental list is bounded at 60 and derived only from the validated observation ledger.

`03_source_data/equity_research/momentum_outcome_prices.local.json` is a labelled normalized provider observation receipt, not a claim to preserve original HTTP response bytes. It binds market rows and history, request ledger hash, observation IDs, source URLs and any failures. The frozen evaluator uses it only for previously recorded observations. Reuse-only refreshes never request a provider and cannot repair missing coverage by assumption. Unavailable/delisted bars, stale receipts, incomplete forward windows and corporate-action corrections stay unresolved; original failed and missed setups remain in the study. Old implementations' publication clocks still apply even if the new provider window returns a close earlier.

## Introducing another experiment version

Do not update an existing binding or silently change thresholds, costs or the holding period. A proposed experimental model change needs an explicitly reviewed new version and committed implementation/policy. Register that immutable commit with the original file map and complete `runtime_files` closure. For code written after this repair, set `entrypoint` to `_run_engine`; `_run` is now the live dispatcher and may not be used as a frozen engine. The validator rejects a dispatcher entrypoint. Register the version before first capture, retain all prior bindings, and run the frozen-runtime regressions and a private CLI replay before deployment. Changing the dispatcher or a production helper alone is an infrastructure change, not justification to increment the strategy version.

Run the targeted checks from the source script directory:

```sh
python3 -m unittest discover -s tests -p 'test*momentum*.py'
```

Then deploy through the normal clean-main synchronization, run the full no-send refresh and inspect experiment status, manual-review status, current status and final email previews. A configured schedule or successful local test is not proof of production execution or delivery. Ordinary delivery remains owned by the existing sender; this repair never invokes it.

## Interpreting progress

Five market sessions, complete source-bound outcomes and a healthy current software report can produce a manual-review packet. Five calendar days, a short winning streak or a repaired runtime cannot. Versions and cost grids are reported separately. Overlapping ticker paths are not independent trades, simulated outcomes are not broker fills, and software reliability is not investment-performance evidence. No automatic promotion or change to canonical eligibility, allocation, risk limits or human-only execution is permitted.
