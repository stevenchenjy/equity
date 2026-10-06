# Recurring analyst follow-through

The September 28 pipeline audit found that the deterministic refresh collects
facts and queues work, but cannot itself author a reasoned valuation or plan
reassessment. The owner requested that this gap be fixed. A scheduled follow-up
in the existing Codex chat supplies that analysis using the existing plan,
thesis, valuation and publication validators. It is research, not execution.

## Each run

1. Verify the production code commit and inspect current production status,
   the latest validated market session, the capital work queue, the research
   backlog, maintained plans, issuer-news reviews and prior analyst receipts.
   Production is `/Users/messssi/LocalRuntime/equity`; source code is
   `/Users/messssi/Desktop/equity`. The chat's visible directory is
   `/Users/messssi/Documents/equity`, which is neither executable checkout.
   Use absolute script paths and explicit production roots as described below.
   Do not work from stale chat summaries.
   Distinguish code changes from expected append-only public SEC evidence
   admitted by `run_runtime_scheduler._runtime_evidence_changes`. Record those
   validated data changes and pending source/runtime reconciliation; they do
   not require abandoning independent research or overwriting retained evidence.
   Unexpected code changes block mutation until resolved. A routine analyst
   wake does not deploy source code, and a completed data refresh need not leave
   the tracked evidence tree clean.
   Also read `08_reviews/decision_resolution.local/queue.json` and the common
   `daily_decision.capital_decision` when present. Use the A/B/C/D/E dependency
   classes in `capital_decision_contract.md`: A/B route to bounded factual/public
   workers, C needs owner account observations, D belongs to your sourced synthesis,
   and E preserves strategy/execution requirements. A missing queue is explicit,
   not evidence of completion. Prioritize held risks and the investment gaps most
   likely to change a numerical decision; do not ask the owner to calculate a size
   or synthesize the company case. Write through the existing validated stores,
   never edit the generated capital contract or promote an experiment.
2. Prioritize overdue held-position risk and purpose reviews, then the most
   decision-relevant research gaps and otherwise-qualified core opportunities.
   A broker-dependent blocked item must not monopolize the run: record the
   exact missing evidence and continue work that does not depend on it.
   Processing a company is not completion; count new admissible fields,
   sourced analytical conclusions and validated plan versions separately.
   Also list the durable owner requests with the production
   `10_dashboard/record_feedback.py --list-reviews` command. A dashboard request
   asks for analysis, not an email resend. Select relevant queued or blocked
   requests alongside the existing risk priorities; do not leave them out of
   the run merely because they were entered in a form rather than a chat.
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
8. Maintain the dashboard's reading summaries after a validated plan change
   and final recomposition. Use production `10_dashboard/plan_summary.py
   --template` to obtain exact plan/source bindings, then author a private
   proposal with 3–4 concise Chinese labelled points for each of `reason`,
   `counterargument` and `conditions`. Preserve negations, uncertainty,
   quantities, historical dates, entry gates and separate exit decisions.
   Validate with `--input PRIVATE_JSON`; add `--apply` only after checking
   fidelity against the full source. Run from the production checkout with
   an explicit `--runtime-root /Users/messssi/LocalRuntime/equity`.
   This writes presentation notes only; it neither amends a plan nor sends
   mail. Changed plan identity or source text suppresses stale summaries and
   leaves complete source points visible until new notes are accepted.

## Dashboard request receipts

The dashboard queue is private and uses the same account locks as manual
feedback. Run the following commands from the verified production checkout
with the Python interpreter specified below:

```sh
python3 10_dashboard/record_feedback.py --list-reviews
python3 10_dashboard/record_feedback.py --claim-review REQUEST_ID
```

Claim before starting substantive work. The original request's account and
decision hashes stay retained. If those facts changed, inspect the new state
and claim explicitly with `--rebind-current`; that rebinding is audited. A
running request retained after interruption can be resumed. An ordinary
deterministic refresh never completes an analyst request.

Save its outcome under `08_reviews/analyst_followthrough.local/` as a private
JSON receipt. Required fields are `schema_version` =
`equity_dashboard_review_receipt_v1`, `request_id`, `account_version` from the
claimed `review_account_version`, `summary`, `analysis_completed`,
`email_sent=false`, and `trade_placed=false`. For a completed review, include
nonempty `conclusions`, exact current `decision_sha256`, and nonempty `sources`
containing project-relative `path` and actual `sha256` for retained evidence.
For a blocked review, use `analysis_completed=false` and nonempty
`dependencies` describing what evidence is missing and the next useful action.
Do not put credentials or broker access information in receipts.

After analysis, validated durable amendments and full no-send recomposition,
use `--complete-review REQUEST_ID --receipt PRIVATE_JSON`. If evidence is
insufficient, use `--block-review REQUEST_ID --receipt PRIVATE_JSON` instead.
Completion verifies source bytes, current account binding, final decision and
exact published text/HTML. Changed accounts block completion and require a
fresh claim and reassessment. The original request, every transition and the
hashed result remain available in the dashboard. Do not manufacture conclusions
or mark completion merely because a job ran successfully.

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
with `--check --input PROPOSAL --as-of PACKET_AS_OF` and optional repeated
`--ticker TICKER`. `PACKET_AS_OF` is the validated packet's timezone-aware ISO
timestamp, not a bare session date; retain the separate validated close date.
This CLI has **no `--root` or `--apply` option**:
executing the production script selects the production root. Its `--seal`
mode, with explicit `--output PRIVATE_STAGED_BUNDLE`, seals and validates a
staged bundle; it does not provide coordinated canonical admission. The
durable analyst research input store is
`/Users/messssi/LocalRuntime/equity/04_data/equity_research/valuation_research_inputs.local.json`.
Preserve existing admitted records when adding an input; retain exact prior
bytes in the dated admission receipt before replacement. A coordinated
writer may call `seal_bundle` and `validate_and_materialize_bundle` with
`project_root=Path('/Users/messssi/LocalRuntime/equity')`, then publish the exact
validated research bundle to that durable store under the locks below. Such publication retains
`canonical_effect=false`; it does not complete canonical financial fields,
valuation scenarios or recommendation eligibility. If a financial amendment
has no identified validator and admitted writer, retain it as pending admission.

`valuation_inputs.local.json` is the refresh-owned composed packet bundle;
never use it as the durable amendment target. The valuation generator preserves
the analyst store unchanged, archives every observed version verbatim under
`04_data/equity_research/valuation_input_history.local/`, and revalidates each
manual record's sources and current financial/market period. A current generated
ticker record takes precedence in the composed bundle; the manual record stays
historical with an explicit status. Invalid bindings or advanced reporting
periods keep the original research but exclude it from the current packet.
Legacy mixed bundles are captured verbatim into the durable store only if that
store does not yet exist. This compatibility step cannot recover a record that
an earlier refresh already deleted: restore such a record from a validated
proposal and retained receipt under the normal locks.

After admission and refresh, inspect
`04_data/equity_research/valuation_research_status.local.json` and confirm the
expected ticker is `active_research_only` in the packet. An `unverified` or
`historical_generated_record_precedence` status is not completed current
analysis. Count research numeric observations separately from canonical
financial fields and complete valuations; the latter do not change through
this store. Include the durable store's hash in protected-input checks and
allow the derived composed bundle to change only through validated regeneration.

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
every stage result, final artifacts and no-send boundaries. A scheduled analyst wake, an
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

The weekday follow-up runs at 08:45 and 13:45 ET, after the scheduled 08:00
and 13:30 research attempts and before/during the owner's delivery windows.
The earlier noon-only heartbeat is superseded, with its exact private config
retained in the schedule-upgrade audit. Check whether the relevant current
handoff actually passed; a configured time is not execution evidence. If a
provider/broker-dependent task is blocked, continue independent sourced work.
Prioritize useful risk/plan conclusions before the attention window ends, and
carry longer valuation work forward through durable inputs and receipts.
Completion after a window improves future research but does not authorize a
late email or a renewed expired DAY draft. The existing sender checks every
15 minutes inside each window; a quiet first check does not consume a later
materially changed report. Machine/app availability and task runtime remain
external dependencies.

## Early research opportunities

Read the validated opportunity view and its source-bound journal described in
`research_opportunity_architecture.md` alongside the existing backlog. Held and
urgent adverse work still comes first. Prioritize the most decision-relevant
new primary evidence and closed opportunities with changed evidence; do not
repeat unchanged attachments to consume a quota. Outside-universe dossiers are
research-only and do not grant canonical admission. Recorded hypotheses,
support/counterevidence, confidence distinct from conviction and next review can
advance through `update_research_assessment.py`'s check-then-apply writer under
the existing runtime/pipeline locks. It acquires its own opportunity store lock;
do not hold that lock while invoking its CLI. Preserve the original first-seen
receipt and rejection/expiry. A research assessment cannot change a position's
purpose or replace the existing plan, thesis or valuation writers. After accepted
work, use the documented full no-send recomposition and verify current views.

## Authority

Preserve the approved capital basis, zero mandatory internal reserve,
the current [owner-approved allocation policy](allocation_policy.md), aggregate
and strategy-specific tactical limits, evidence thresholds and human-only
execution. The October 6 standard uses a 30% broad-core floor/baseline target,
70% aggregate stock target/maximum, zero cash target and no fixed single-stock
cap. Do not restore superseded name limits from old heartbeat wording, account
snapshots or historical reviews. Do not promote experimental momentum observations,
retune after a streak, purchase services, enable leverage, access the broker
unattended, invent broker facts or clear a genuine account-wide blocker.
For otherwise supported growth opportunities, complete the company-specific
maintained plan's optional `reviewed_allocation` using the existing plan writer:
`target_position_pct`, `maximum_entry_price`, `invalidation_price`,
`reassessment_price`, `rationale`, `downside_case`, `portfolio_overlap`,
`alternatives`, `reviewed_at` and retained `sources`. It is admitted only for
`long_term_growth` and stays subject to the plan's source/hash, date and
purpose checks. A zero-share entry plan is research for an unheld opportunity,
not proof of a past sale or current fill. These inputs state the desired
position and current price/risk case; the capital engine still bounds the final
quantity by aggregate allocation, core-floor room and actual available funds. Fixed initial-size tiers do not
replace this work. Do not silently convert a tactical purpose to obtain a larger
allocation. Never force a positive share count to reduce cash. Research can
conclude that no opportunity qualifies, but must distinguish an adverse
investment conclusion from unfinished analysis or a missing execution prerequisite.

The deterministic engine remains the eligibility authority. The chat worker
provides auditable analyst inputs through existing validators; it does not
replace the retired production model or grant a new model trading authority.
