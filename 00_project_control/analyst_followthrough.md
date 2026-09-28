# Recurring analyst follow-through

The September 28 pipeline audit found that the deterministic refresh collects
facts and queues work, but cannot itself author a reasoned valuation or plan
reassessment. The owner requested that this gap be fixed. A scheduled follow-up
in the existing Codex chat supplies that analysis using the existing plan,
thesis, valuation and publication validators. It is research, not execution.

## Each run

1. Verify the clean production commit and inspect current production status,
   the latest validated market session, the capital work queue, the research
   backlog, maintained plans, issuer-news reviews and prior analyst receipts.
   Production is `/Users/messssi/LocalRuntime/equity`; source code is
   `/Users/messssi/Desktop/equity`. The chat's visible directory is
   `/Users/messssi/Documents/equity`, which is neither executable checkout.
   Use absolute script paths and explicit production roots as described below.
   Do not work from stale chat summaries.
2. Prioritize overdue held-position risk and purpose reviews, then the most
   decision-relevant research gaps and otherwise-qualified core opportunities.
   A broker-dependent blocked item must not monopolize the run: record the
   exact missing evidence and continue work that does not depend on it.
   Processing a company is not completion; count new admissible fields,
   sourced analytical conclusions and validated plan versions separately.
3. Preserve a dated private evidence bundle with original source bytes or an
   explicitly labelled observed-facts receipt, source URLs, observation times
   and hashes under `08_reviews/analyst_followthrough.local/`. Prefer existing
   verified SEC/issuer receipts and dated primary public sources. Missing
   current quotes, float, order inventory, available shares, settled cash or
   events stay unverified. Never infer a terminal order state from elapsed time.
4. Make actual analytical progress: review accounting scope for missing
   financial fields, assess new issuer evidence, produce explicit bearish/base/
   bullish valuation assumptions when support exists, and reassess expired
   plans. Distinguish facts from estimates and judgment. Record why a task
   remains blocked if sources do not support completion. Do not mark a copied
   dossier, timestamp change or repeated unresolved checklist as progress.
5. Validate every proposed durable amendment with the existing writer before
   applying it. Use `update_investment_plan.py` for source-bound plan versions
   and `update_thesis_review.py` for company reviews. The valuation-input
   bundle validator admits research packet inputs with `canonical_effect=false`;
   it is not a writer for canonical fundamental fields or a completed valuation.
   Preserve
   previous hashes, expired/failed outcomes and accounting scope. If no
   admissible writer exists, save the sourced proposal as pending admission;
   do not edit an acceptance result or financial CSV to bypass validation.
6. Recheck input hashes immediately before applying. Serialize writes with
   the existing runtime and daily-pipeline locks and each writer's own lock,
   following the lock order and publication procedure below.
   Apply only supported research within the current approved mandate. A
   same-purpose reassessment can proceed when evidence supports it; it does
   not need the owner to start another chat. A purpose change needs a recorded
   evidence-supported reassessment and must remain within approved strategy.
7. After accepted amendments, use the existing operator-safe full no-send
   refresh with `reuse_validated_snapshot` after releasing all mutation locks,
   then verify the final decision,
   cash projection, per-ticker blockers, renderer, queues and current status.
   Record exact before/after hashes and changed conclusions. Do not invoke
   the mail sender; the existing scheduled sender owns normal delivery and
   its meaningful-change policy. A recurring wake is not a new explicit
   owner-review email request.

## Writer paths and admission modes

Use `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` and the
scripts in the verified production checkout. Each `PROPOSAL` below means an
absolute path to a dated private proposal already saved with its evidence.
Run from `/Users/messssi/LocalRuntime/equity`; do not rely on the chat directory
or the default root of a script imported from another checkout.

For an investment-plan proposal, validate without a durable append first:

```sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/messssi/LocalRuntime/equity/09_scripts/equity_research/update_investment_plan.py --input PROPOSAL --root /Users/messssi/LocalRuntime/equity
```

The same command with `--apply` appends the validated plan version to
`/Users/messssi/LocalRuntime/equity/05_risk_and_positions/investment_plans.local.json`.
For a sealed company-review proposal, use the same validate-then-apply pattern
with `/Users/messssi/LocalRuntime/equity/09_scripts/equity_research/update_thesis_review.py`,
`--input PROPOSAL`, `--root /Users/messssi/LocalRuntime/equity`, and only on the
accepted append `--apply`. Its store is
`/Users/messssi/LocalRuntime/equity/04_research/company_research/thesis_dossiers.local.json`.

For valuation research inputs, the actual CLI is
`/Users/messssi/LocalRuntime/equity/09_scripts/equity_research/valuation_input_bundle.py`
with `--check --input PROPOSAL --as-of MARKET_SESSION` and optional repeated
`--ticker TICKER`. `MARKET_SESSION` is the validated packet session, not an
assumed wall-clock date. This CLI has **no `--root` or `--apply` option**:
executing the production script selects the production root. Its `--seal`
mode, with explicit `--output PRIVATE_STAGED_BUNDLE`, seals and validates a
staged bundle; it does not provide coordinated canonical admission. The
private research input store is
`/Users/messssi/LocalRuntime/equity/04_data/equity_research/valuation_inputs.local.json`.
Preserve existing bundle records when adding an admissible input. A coordinated
writer may call `seal_bundle` and `validate_and_materialize_bundle` with
`project_root=Path('/Users/messssi/LocalRuntime/equity')`, then publish the exact
validated research bundle under the locks below. Such publication retains
`canonical_effect=false`; it does not complete canonical financial fields,
valuation scenarios or recommendation eligibility. If a financial amendment
has no identified validator and admitted writer, retain it as pending admission.

## Locking and publication

Acquire locks in this order:

1. `/Users/messssi/LocalRuntime/.locks/equity-research-runtime.lock`.
2. `/Users/messssi/LocalRuntime/equity/00_project_control/run_logs/daily_pipeline.lock`.
3. The relevant writer lock: plans use
   `/Users/messssi/LocalRuntime/equity/05_risk_and_positions/investment_plans.local.lock`;
   company reviews use
   `/Users/messssi/LocalRuntime/equity/00_project_control/run_logs/thesis_dossiers.lock`.
   The valuation-bundle CLI has no intrinsic lock, so coordinated publication
   must also use
   `/Users/messssi/LocalRuntime/equity/04_data/equity_research/valuation_inputs.local.lock`.
   For a batch, acquire the necessary writer locks in sorted absolute-path order.

The plan and thesis CLIs acquire their own writer locks in both check and apply
modes. **Do not hold one of those writer locks and then call its CLI**: the
child would wait on a lock owned by its parent. Either let the CLI own its
writer lock while the coordinator owns runtime and pipeline locks, or call the
existing validated `append_plan`/`append_review` function directly while the
coordinator owns all required locks. Do not mix those two approaches in a
critical section.

A plan, thesis and valuation-input amendment are separate stores, not one
atomic transaction. Before publishing a batch, validate every proposed result
against the same current evidence, capture the exact original bytes and hashes
of all affected stores, and write a private `prepared_for_publication` receipt
under `08_reviews/analyst_followthrough.local/RUN_ID/`. Recheck account, order,
market, proposal and affected-store fingerprints immediately before mutation.
Fail without applying if they changed; rerun the analysis against the new state.

Publish validated bytes using atomic per-file replacement, retain the exact
before/after hashes, and mark the receipt successful only after every intended
write and read-back validation passes. If an error occurs between writes, keep
the failed/partial receipt and recover under the same locks. Roll back only the
stores changed by this batch, using their saved original bytes and checking
that their current hashes still equal this batch's published values. Never
overwrite an unexpected newer change. After a process crash, inspect the
prepared receipt and actual store hashes before continuing; a prepared receipt
alone proves neither success nor rollback. Record the final recovery outcome.

## Full no-send refresh after admission

Release runtime, pipeline and writer mutation locks before invoking the
operator launcher, which acquires the existing locks itself. With working
directory `/Users/messssi/LocalRuntime/equity`, the approved full refresh is:

```sh
/usr/bin/env PHASE5R_FULL_REFRESH_REUSE_ONLY_20260901_7C31=1 '/Users/messssi/Library/Application Support/EquityResearch/bin/dailyrefresh_launcher.py'
```

This is the existing operator-safe `reuse_validated_snapshot` entry point.
Do not invoke a sender or change scheduler completion flags. Verify the
refresh's actual current-cycle handoff, required published market session,
every stage result, final artifacts and no-send boundaries. A noon wake, an
online Git receipt or a zero child exit by itself does not establish a current
complete research chain. If the validated close or required evidence is
unavailable, retain the precise blocker and the admission receipt.

## Durable completion receipt

Retain a receipt and concise report for each run in the private directory,
including actual start/end time, source/runtime commit, input fingerprints,
selected task identities, evidence acquired, financial fields admitted,
plan/thesis versions accepted, valuation assumptions reviewed, unresolved
dependencies, refresh result, next useful work and `email_sent=false` /
`trade_placed=false`. Keep unsuccessful and skipped tasks. Carry unresolved
work forward without repeating an unchanged source set merely to fill a quota.
Review receipts from previous runs before claiming progress.
Count source attachments, newly admitted numeric fields, sourced analyst
conclusions and accepted plan/thesis versions separately. A larger objective
data batch does not itself increase the Codex analyst work budget or turn an
unresolved financial field into a completed one.

The weekday follow-up is intended to run after the publication refresh and
before the normal delivery boundary. Machine/app availability and task runtime
remain dependencies; a configured schedule is not proof of a completed run.

## Authority

Preserve the approved capital basis, zero mandatory internal reserve,
allocation targets, name/aggregate/tactical risk limits, evidence thresholds
and human-only execution. Do not promote experimental momentum observations,
retune after a streak, purchase services, enable leverage, access the broker
unattended, invent broker facts or clear a genuine account-wide blocker.
Never force a positive share count to reduce cash. Research can conclude that
no opportunity qualifies, but must distinguish an adverse investment conclusion
from unfinished analysis or a missing execution prerequisite.

The deterministic engine remains the eligibility authority. The chat worker
provides auditable analyst inputs through existing validators; it does not
replace the retired production model or grant a new model trading authority.
