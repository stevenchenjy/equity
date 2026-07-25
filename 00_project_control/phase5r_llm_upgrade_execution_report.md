# Phase 5R Rigorous Decision-Model Upgrade Execution Report

Generated: 2026-07-25T10:33:12-04:00  
Status: combined local contracts, cost-aware exact-role fixture execution,
durable usage/cost accounting, ticker freshness, three-fold issuer/time
isolation, and sequential paper evaluation are implemented; live licensed
inputs, real-source corpus acquisition, external-provider replay, and
live-shadow qualification remain pending

## Decisive conclusion

The correct upgrade is **not** to replace C9 with a model. It is to keep C9 as
the deterministic risk and eligibility authority, then add isolated,
source-bound model roles:

1. an evidence analyst;
2. a thesis/action committee;
3. a proposal-aware adversarial critic; and
4. for high-impact transitions, a cross-family challenger that precommits
   without seeing the committee proposal.

The model layer may make a clear per-ticker research classification—hold,
candidate, trim review, exit review, or abstain. A separate action-review axis
then applies C9 and deterministic data/risk gates without erasing that research
judgment. Neither axis can send email, connect to a broker, create an order, or
authorize execution. This is the strongest authority that can be added without
turning a research system into an opaque trading agent.

That dual-axis behavior is now enforced rather than merely documented. A
stale market, portfolio inconsistency, freshness failure, missing verified
close, or C9 limitation blocks action review and remains prominently visible,
but no longer silently changes a valid research candidate/trim/exit thesis
into `abstain`. Missing evidence needed to support the thesis itself—such as
source-bound valuation for an ordinary transition—still fails research
formation.

The acquisition and scheduler remain local. When the Mac is powered off or
fully asleep, launchd does not collect new data. After wake, the workflow can
evaluate the newest available state, but it cannot reconstruct intraday states
that were never captured. An always-on remote collector is a separate future
infrastructure decision.

## Current-system audit

| Layer | Robustness finding | Upgrade decision |
| --- | --- | --- |
| B2 market evidence | Useful for daily context, but currently based on secondary public data and the active packet reports `market_data_action_grade=false` | Keep as comparison/context; the new provider-neutral contract remains synthetic/offline and cannot unlock any ticker until a licensed feed is separately acquired and validated |
| SEC evidence | Official source base is strong, but historical model-quality proof and deep reviewed transition coverage are not yet materialized | Bind every claim to exact packet excerpts, timestamps, URLs/accessions, and SHA-256; acquire and freeze a qualification-grade point-in-time replay corpus |
| C9 | Strong at reproducible arithmetic, limits, eligibility, and fail-closed gates; weak at semantic thesis interpretation | Keep canonical; hide its answer labels from model inputs, then enforce its per-ticker classification ceiling in the deterministic adjudicator |
| Daily composer | Can present clear deterministic output, but has no independent semantic investment committee | Future advisory rendering may use only a completed artifact for the exact packet; missing or stale model output falls back to C9 |
| Model layer | Previously unproven for this corpus | Added as a disabled shadow system with exact schemas, per-ticker adjudication, critic controls, replay gates, and an activation-receipt builder/verifier; no activation receipt has been generated |

## Implemented upgrade

- Closed per-ticker labels:
  `reject`, `watchlist`, `hold_existing`, `paper_trade_candidate`,
  `real_trade_candidate`, `trim_review`, `exit_review`, and `abstain`.
- Analyst claims now require ticker, rationale, fact type, evidence origin,
  unit, period, source IDs, exact excerpt hashes, and calculation IDs.
- Live shadow and primary replay analyst calls now receive the same
  leakage-free analyst packet view. It removes deterministic recommendation
  fields, transition eligibility/stability answers,
  `allowed_classifications_by_ticker`, C9-derived sources, and C9 score
  calculations while preserving evidence and immutable packet identity.
- Committee decisions must cover every packet entity exactly and cite validated
  analyst claims and same-ticker primary evidence.
- The proposal-aware critic receives the committee output and produces one
  review per ticker with the exact verdict `approve`, `revise`, or `reject`.
  It is a separate stateless request but not a blinded precommit or cross-family
  control. It may preserve or reduce a proposal, never upgrade it; `revise` or
  `reject` now requires a failed check, a medium-or-higher issue, and a real
  safe downgrade. A problem in one ticker cannot reject an unrelated valid exit
  conclusion.
- The new blinded challenger receives the same sealed evidence view and
  validated analyst claims but never the committee or critic output. Its input
  hash is invariant to committee mutations. Exact agreement may preserve the
  research class; any transition disagreement resolves to `abstain`; no branch
  can upgrade the committee. An injected Anthropic Messages adapter uses strict
  JSON Schema and `tools=[]`, but no external client or credential has been
  supplied and no request has run.
- Arithmetic remains in Python. Numeric model text without a reconciled
  calculation fails.
- The packet carries a deterministic `allowed_classifications_by_ticker` policy
  cap derived from C9. That map is hidden from every semantic model view and
  enforced only on the action-review axis. A disallowed action uses a
  role-appropriate safe fallback while retaining the independently validated
  `research_classification`, so C9 can block action review without silently
  turning model `exit_review` into research `hold_existing`.
- Every ticker can now carry a deterministic freshness receipt bound to the
  packet as-of time, latest complete SEC scan, expected completed market
  session, valuation receipt/scenario time, durable SEC source IDs, and its own
  SHA-256. Ordinary action review requires the SEC scan watermark to be within
  48 hours and the valuation scenario within seven days. Old primary SEC
  thesis evidence is not discarded solely because the filing is old.
- `phase5r_valuation_evidence_v1` is now wired into the packet contract and
  adjudicator. Receipts must pass deterministic recomputation, exact as-of,
  ticker/source, and projected-calculation checks. Any action transition other
  than a supported broken-thesis `exit_review` also requires membership in
  `valuation_action_grade_tickers`; missing or invalid valuation evidence fails
  closed.
- A provider-neutral market-data contract and synthetic Massive-shaped adapter
  now validate identity, regular-session bars, adjusted/unadjusted agreement,
  pagination, corporate-action coverage, receipts, and hashes. The committed
  registry is `offline_fixture`, `action_grade_enabled=false`,
  `network_enabled=false`, and credential access is prohibited. Market
  permission is per ticker through `market_data_action_grade_tickers`; a global
  Boolean cannot unlock an unlisted ticker.
- A primary-supported broken held thesis may reach `exit_review`; a
  market-dependent candidate remains blocked while action-grade market data is
  or action-grade valuation evidence is absent.
- Prominent Chinese headline/advice is derived from the final effective
  classification, not from an unvalidated model proposal.
- Identical packet, role, model, prompt, schema, and runtime-code hashes form
  the model-run identity.
- The 250-packet/20-issuer qualification floor is now shared by registry,
  replay loader, annotation, template, verifier, and inventory paths. Lowered
  caller or registry thresholds and stale manifest declarations fail closed;
  reserve-padding issuers do not count toward the selected qualification slice.
- The provider replay gate now reruns the stricter corpus verifier against the
  exact manifest and evidence ledger before scoring model responses. The proof
  transitively checks bound SEC/index, normalized-text, and market artifacts,
  and one ticker cannot map to multiple CIKs to inflate issuer diversity. The
  former synthetic fake-CIK/text fixture now fails this production
  prerequisite.
- The transition evaluator freezes one whole-issuer chronological split and
  three expanding-window folds, all with seven-day purge and embargo. Each fold
  rejects cross-CIK transitions, issuer/packet/adjacent-transition leakage,
  undersized partitions, chronology violations, and hash tampering. Scored
  holdout issuer and case sets cannot recur across folds. The receipts pass
  synthetic tests; real-corpus scores remain absent.
- Fresh local packets use an explicit current as-of unless a historical replay
  supplies its own timestamp. This prevents a stale deterministic-decision
  timestamp from falsely placing newer verified local evidence in the future
  while preserving explicit historical point-in-time replay.
- The implemented provider bridge is designed to run the pinned external Codex
  executable in an ephemeral, read-only, tool-disabled environment and never
  reads repository credentials.
- An injected-client `OpenAIResponsesProvider` adapter is implemented. It
  accepts only an externally configured client, requires strict structured
  output, uses stateless `store=false` requests with no tools, and records
  provider-native response and usage metadata. It has not been externally
  invoked or enabled for qualification.
- A deterministic point-in-time paper-performance foundation now covers
  next-session fills, explicit costs, flow-neutral TWR, cash drag, corporate
  actions, drawdown, turnover, aligned SPY/QQQ/XLK/C9 baselines, and seeded
  bootstrap intervals. Exact `-100%` terminal losses now remain in TWR,
  drawdown, and bootstrap calculations rather than being rejected and creating
  survivorship bias. No real immutable ledger has been ingested and no
  historical performance result is claimed.
- Source-bound monthly ledger rows now feed rolling 12-, 36-, and 60-month
  TWR/CAGR, volatility, downside deviation, Sortino, drawdown, underwater, and
  recovery receipts. Fewer than 60 months returns
  `insufficient_60_month_history`; the return objective is never a trading
  trigger.
- A sequential monthly paper simulator now applies chronological decision and
  market receipts, explicit rebalance/hold/abstain semantics, long-only cash,
  exposure, per-name, position-count and turnover limits, fixed/spread/
  slippage costs, and terminal delisting/bankruptcy recoveries. Exact
  zero-recovery terminal loss remains `-100%`.
- Portfolio constraints now require exact fields, finite bounded percentages,
  positive ordered caps, allocation targets summing to 100%, a bounded
  investment horizon, and `manual_execution_only=true`.
- An action-changing proposal with committee, component, or ticker confidence
  at or below the structural 1% sanity floor fails closed. This is a zero-signal
  guard only; it is not a calibrated probability threshold.
- Weekend model inference is suppressed when the deterministic daily decision
  has no material change.
- A cost-aware planner now selects zero, one, two, or four exact roles based on
  materiality and impact, reserves worst-case calls/tokens/USD, rejects
  provider fallback, and allows reuse only under exact semantic/dependency
  bindings. An explicit shadow routing envelope is checked before activation
  or provider construction and emits a hashed local receipt. A new fixture-only
  executor consumes exactly that plan, persists the reservation before
  provider construction, recomputes cost from metered tokens and frozen model
  prices, binds dependency hashes, and retains worst-case charges after unknown
  outcomes. Live provider calls remain blocked pending a pinned cycle ledger,
  provider-native metering normalization, and explicit credential/cost
  authority.
- Routine validated HOLD/WATCH/ABSTAIN results require no daily manual review.
  Human attention is reserved for action transitions, exceptions, and any
  eventual real-world action.

## Evaluation and activation design

The base evaluation plan contains at least 1,040 logical model items at the
machine-enforced 250-packet floor and the 50-case adversarial minimum:

- 750 analyst/committee/critic calls over 250 real packets;
- 50 reviewed transition-pair calls;
- 50 deterministic no-change controls;
- at least 50 adversarial calls;
- 40 repeated stability calls;
- 50 critic controls; and
- 50 decisive-evidence-removal counterfactuals.

The exact logical plan is recomputed and frozen from the materialized corpus;
additional packets or probes increase it. Physical attempts are counted
separately and may exceed logical items only for allowed replay transport/process
retries, capped at three physical attempts per logical item.

Collection is quarantined and resumable, with receipt-idempotent result reuse.
It supports a 30-call smoke stage, an up-to-200-call pilot, and the remaining
frozen plan. Successful role results are reused. Live analyst, committee, and
critic roles have
independent, hash-bound receipts, so a later-role failure cannot recall an
earlier successful role. A schema, semantic, citation, evidence, or
policy-invalid answer is terminal for that exact run and cannot be retried into
an apparent pass; only narrowly classified transport/process failures may use a
bounded retry.

Replay collection records every physical attempt, including failures, in an
immutable hash-chained ledger. Its global physical-call and operator-estimated
cost ceilings are frozen and cumulative across resumes; `--max-new-calls`
remains the per-invocation limit. Collection cannot emit a passing report.
Provider-free finalization must recompute the ledger, first-attempt validity,
failure classes, and all quality gates from an exact frozen
dual-independent-review artifact before an activation receipt can exist.

`--max-new-calls` is the enforceable local call ceiling. `--max-cost-usd` is a
declared estimate derived from the operator-supplied estimated cost per call;
it is not a provider-side billing limit and must not be represented as one.
The exploratory CLI bridge also does not expose authoritative token usage or a
provider-native response ID, so its receipts are sufficient only for
exploratory shadow qualification. A future advisory transport must bind those
provider-native fields.

An alias, model, prompt, schema, packet builder, return-objective contract,
runtime file, corpus, annotation, response, or human-review change invalidates
the prior activation binding.

## Real-corpus readiness inventory

For the upper end of the approved qualification range, the read-only inventory
selected `325` candidate packet records (`300` target plus `25` padding) across
only `6` issuers from `609` ledger accessions. Acceptance-index coverage is
complete for the selected candidates. These are inventory candidates, not a
materialized or qualified replay corpus. The activation gate independently
enforces a non-lowerable floor of `250` complete packets and `20` distinct CIKs,
and inventory computes CIK diversity from the selected target slice rather than
its padding.

Exact remaining artifact gaps are:

- `318` primary filing documents;
- `325` filing indexes;
- `325` raw-submission snapshots;
- `204` incomplete exhibit discoveries;
- `73` XBRL reconciliations; and
- market packets for all `325` candidate records.

There are `7` reusable daily primary artifacts. The current builder estimate is
`656` requests; an optimized mechanics-only path is estimated at `330`, while
qualification-complete acquisition is estimated at `791–2,701` requests.
Typical storage is estimated at `1,119,510,052` bytes and the conservative
planning upper bound at `72,938,946,560` bytes. These are planning estimates,
not completed downloads. Both pilot and qualification readiness remain
fail-closed.

## Model and API decision

The initial role configuration is:

- evidence analyst: `gpt-5.6-terra`, medium reasoning;
- committee: `gpt-5.6-sol`, high reasoning;
- critic: a separate stateless, proposal-aware `gpt-5.6-sol` request, high
  reasoning.

A genuinely blinded cross-provider challenger remains a Gate 2C qualification
requirement. Its closed local contract and deterministic comparator are now
implemented: it receives evidence and analyst claims without the Sol proposal,
precommits its own source-bound class, and is compared only by Python. The
injected Anthropic Messages adapter is also implemented, restricted to the
challenger role, strict-schema output, and no tools. These mechanics are
offline-tested only; they are not evidence that a real cross-family model is
accurate or independent enough for operation.

The already-authenticated, pinned Codex CLI remains one possible quarantined
smoke transport and keeps credentials outside the repository. Direct,
injected-client OpenAI Responses and Anthropic Messages adapters are now
implemented locally, but no client, credential, or external call has been
supplied and neither is enabled for shadow qualification. A future
Responses/Batch execution path still requires an approved external credential
boundary, lifecycle policy, and replay-equivalent qualification. OpenAI
documents strict Structured Outputs and a 50% Batch API discount; provider data
retention must still be treated according to the account's configured data
controls:
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Batch API](https://help.openai.com/en/articles/9197833-batch-api-faq%3F.gz),
and [API data controls](https://developers.openai.com/api/docs/guides/your-data).
The same Batch FAQ says Zero Data Retention does not apply to Batch, so the
planned replay may send only public evidence and sanitized portfolio bands.

The CLI bridge binds the requested model IDs and executable hash, but it does
not prove an immutable provider-side weight snapshot or expose authoritative
token billing. For that reason the activation-receipt implementation, if a
gate-passing receipt is later generated, can enable only
`exploratory_shadow_only`; it cannot enable advisory/canonical influence. Any
future advisory transport must bind provider-native response/model-version
metadata or impose an explicit short requalification window.

No autonomous trading framework was adopted. FinRobot, FinGPT, FinRL, and broad
agent/orchestration stacks add execution or tool surfaces without proving
factuality. The narrow implementation instead borrows evaluation ideas from
financial reasoning benchmarks and keeps official SEC artifacts plus
deterministic code authoritative. Dependency findings are recorded in
`04_research/realtime_stock_picker_phase5r/phase5r_llm_decision_architecture_research.md`.

## Return objective

The sealed packet now carries:

- rolling five-year net annualized total-return objective: `12%–15%`;
- exact monthly compound equivalent: `0.9489%–1.1715%`;
- excellent calendar-year context: `15%–20%`;
- `monthly_or_annual_quota=false`;
- `return_guarantee=false`; and
- `risk_gates_override_allowed=false`.

The latest local allocation snapshot is approximately `12.78%` invested. If
cash returned zero, that sleeve would need roughly `93.93%–117.41%` in one year
to create a whole-portfolio return of `12%–15%`. The objective therefore cannot
be achieved by stronger prose or an LLM alone. Allocation, cash yield, market
returns, costs, and risk dominate the arithmetic. No allocation or execution
state was changed.

## Verification result

| Check | Result |
| --- | --- |
| Combined full Phase 5R Python suite | PASS — 341/341 tests; `python3 -m unittest discover -s 09_scripts/phase5r/tests -p 'test_*.py'`; completed 2026-07-25T10:33:12-04:00 |
| Leakage-free live/replay role inputs | PASS in the combined suite, including label/map hiding and role-scoped source checks |
| Injected-client Responses adapter | Implemented and synthetic-client tested; no external call performed |
| Blinded cross-family challenger | Closed proposal-free contract, deterministic comparison, and injected Anthropic adapter PASS offline; no external call performed |
| Research/action dual-axis adjudication | PASS — C9 can block action review without erasing a validated research exit/candidate conclusion |
| Per-ticker freshness | PASS offline — hashed SEC scan/market/valuation freshness binds each ticker; expired or missing state blocks action review without aging out durable SEC thesis evidence |
| Cost-aware router and shadow preflight | PASS offline — exact semantic/model/schema/budget envelope is checked before provider construction; fixture execution uses a private hash-chained ledger and metered exact-role receipts; live provider authority remains blocked |
| Issuer/time split | PASS synthetic — whole-CIK chronological split plus three expanding out-of-time folds, 7-day purge/embargo, no per-fold issuer/packet/adjacent-transition leakage, and no holdout issuer/case reuse |
| Critic and confidence sanity | PASS — unsupported downgrades and structurally empty transition confidence fail closed; empirical calibration still pending |
| Replay-corpus provenance prerequisite | PASS — provider gate reruns the strict manifest/ledger/SEC/market verifier; synthetic fake-CIK/text corpus is rejected |
| Terminal-loss measurement | PASS — exact -100% TWR and 100% drawdown are retained; below -100% is rejected |
| Latest sealed packet | PASS — packet `0125bf68a4d8f02e31e586752ff3b8427268c833d0c66293eac0cf73d20cb3af`; 7 entities, 81 sources, 0 valuation receipts |
| Read-only current packet build | PASS — packet `6186f2d2238d3039e8c7956afd458f3935e41011c9e32566c41fef545541f05b`; 7/7 SEC-current and market-current freshness receipts, 0/7 valuation-current, not persisted |
| Valuation packet/adjudicator contract | Implemented fail-closed; active real receipt ingestion pending |
| Per-ticker market action-grade contract | Implemented synthetic/offline; live licensed feed pending |
| Point-in-time performance foundation | PASS offline — sequential simulator and rolling 12/36/60-month receipt implemented; real ledger, calibrated costs, and result pending |
| Daily scheduler | PASS — daily refresh and decision loaded |
| Legacy daily/weekly schedulers | PASS — unloaded |
| LLM shadow scheduler | Intentionally unloaded and not installed |
| Real replay corpus | PENDING — 325 candidates inventoried for the 300-packet plan; only 6/20 issuers and 0 complete packets |
| Frozen transition annotations | PENDING |
| External-provider replay | NOT RUN |
| Activation receipt | Correctly absent/blocked |

No external model call, C7 invocation, SMTP read, email action, broker access,
account read, order-code creation, trade, or canonical model influence was
performed by this upgrade. The independent daily scheduler remained active and
outside the model work.

## Inputs needed to continue

1. A real SEC-compliant User-Agent contact string, for example a project name
   plus a contact email. It will be supplied only as a command argument for the
   public SEC corpus refresh and will not be written to the repository.
2. After the 10-packet pilot corpus and frozen annotations exist, explicit
   authorization for exactly **30 physical external model calls**, the
   20K-input/8K-output planning envelope, and a `$10.00` operator hard cap.
   Authentication stays outside the repository and must never be pasted into a
   report, log, LaunchAgent, or chat.
3. Before cost-aware live calls, pin one non-bypassable cycle-ledger location,
   normalize provider-native response/model/token/cache fields into the metered
   receipt, and explicitly authorize the external credential and physical
   request/USD cap. The exact-role and crash-accounting mechanics already pass
   fixture tests; the shadow gate correctly refuses live transport.
4. For market-dependent candidate decisions, a licensed read-only market-data
   source. The Massive-shaped adapter currently uses synthetic offline fixtures
   only; no subscription, live feed, credential, or licensed data ingestion has
   been activated.
5. One-time independent dual review of transition and claim-entailment
   artifacts. This is a model licensing exam, not a daily user-review burden.
6. Only after issuer-held-out qualification: a separately authorized choice
   among maximum-capability Claude Fable 5, lower-cost Claude Opus 5, and
   preview-only Gemini 3.1 Pro, with provider-specific schema preflight,
   retention/data-region review, and a challenger cost cap.

Until those inputs are provided and the gates pass, the model remains disabled
and the deterministic daily workflow remains canonical. In particular, the
licensed live feed, real valuation ingestion, real corpus acquisition, real
point-in-time performance ledger, external provider calls, and shadow
qualification are all incomplete.
