# Phase 5R Safe-Shadow Readiness Report

Generated: 2026-07-27 ET

## Result

Local safety controls: **PASS**  
Live shadow launch ready: **NO — correctly blocked on external inputs**

The current state is the intended stopping point before external spending:

- canonical workflow is `daily_decision / phase5r_daily`;
- weekly and legacy send paths are closed;
- model mode is `offline_fixture`;
- canonical and email influence are false;
- the shadow LaunchAgent is absent;
- no paid model, licensed data, or cross-provider challenger is authorized;
- no provider, credential, SMTP, broker, account, order, or trade action
  occurred during verification.

Machine-readable policy:
`00_project_control/phase5r_paid_dependency_policy.json`.

Read-only verifier:
`python3 09_scripts/phase5r/verify_phase5r_safe_shadow_readiness.py --json`.

## Economical architecture

1. Local B2/SEC/C9 gates handle unchanged, insufficient-evidence, arithmetic,
   freshness, and risk work with zero model calls.
2. Terra is the evidence-analyst quality baseline.
3. Luna is tested on the same 10 pilot packets and may replace Terra only if
   it is non-inferior.
4. Sol is used only for possible classification changes and high-impact
   criticism.
5. The initial shadow stops at the same-provider Sol critic. A paid
   cross-provider challenger is optional and disabled.
6. Offline replay uses Batch when separately authorized; live shadow uses
   standard stateless Responses requests.
7. Public secondary market data is research/shadow context only. It cannot
   unlock an action-grade transition.

## Verified cost controls

At the closed 20,000-input/8,000-output planning envelope:

- pilot: 10 Luna + 10 Terra + 10 Sol Batch requests = `$2.89` estimate;
- pilot hard cap: `30` physical calls and `$5.00`;
- qualification: 250 Terra analyst + 100 Sol committee/critic Batch requests =
  `$38.25` estimate;
- if Luna is non-inferior: qualification estimate = `$25.50`;
- qualification hard cap: `350` physical calls and `$45.00`;
- unchanged cycle: `0` calls;
- material live cycle: at most `3` same-provider calls and `$1.25`;
- licensed market-data budget: `$0`;
- cross-provider challenger budget: `$0`.

Every retry and unknown outcome counts against the physical-call and USD
ceilings. The exact-role executor reserves before provider construction and
retains worst-case cost after an unknown outcome.

## Local controls completed

- Direct Responses adapter is stateless, tool-free, `store=false`, and uses
  strict Structured Outputs.
- GPT-5.6 `cached_tokens` and `cache_write_tokens` are normalized for exact
  ledger pricing.
- Implicit prompt-cache writes are disabled because the 30-minute reuse window
  does not fit the ordinary daily role cadence.
- The fixed cycle ledger path is outside the repository:
  `~/Library/Application Support/Phase5R/llm_execution/<year>/`.
- The router supports zero/one/two/three same-provider calls; the fourth
  cross-provider role requires explicit policy opt-in.
- Canonical daily and safe-shadow read-only guards pass.
- Full test suite passes: `350/350`.

## Evidence readiness

- Replay ledger distinct accessions: `609`
- Qualification cohort selected: `250`
- Selected issuers: `6/20`
- Locally complete pilot packets: `0`
- Locally complete qualification packets: `0`
- Typical qualification storage estimate: `958,892,732` bytes
- Conservative planning upper estimate: `61,352,181,760` bytes

The corpus selector and provenance verifier work, but current evidence is not a
qualification corpus. Current daily SEC artifacts are useful operational
evidence and cannot be relabeled as historical point-in-time proof.

## External blockers

1. SEC-compliant project/contact string.
2. A bounded corpus storage authorization.
3. Completion of the frozen 10-packet pilot corpus.
4. Explicit 30-call/$5 Batch authorization.
5. External OpenAI authentication configured outside the repository.
6. Two independent transition/citation reviewers.

Licensed market data and a cross-provider challenger are deliberately not
blockers for the initial research-only shadow.
