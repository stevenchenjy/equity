# Phase 5R Safe-Shadow Readiness Report

Generated: 2026-07-28 ET

## Result

Local safety controls: **PASS**  
Live shadow launch ready: **NO — pilot corpus passes; external authentication
and independent review remain**

The current state is the intended stopping point before external spending:

- canonical workflow is `daily_decision / phase5r_daily`;
- weekly and legacy send paths are closed;
- model mode is `bounded_offline_shadow_pilot_ready_but_unstarted`;
- canonical and email influence are false;
- the shadow LaunchAgent is absent;
- only the bounded 30-call/$5 Pilot is authorized; qualification, live Shadow,
  licensed data, and cross-provider challenger remain unauthorized;
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
6. The 30-call pilot uses synchronous stateless Responses requests so every
   reservation, exact token count, response, and unknown outcome is durably
   reconciled. No Batch discount is assumed.
7. Public secondary market data is research/shadow context only. It cannot
   unlock an action-grade transition.

## Verified cost controls

At the closed 24,000-input/3,800-output ceiling:

- pilot: 10 Luna + 10 Terra + 5 Sol committees + 5 Sol critics;
- standard no-cache-write maximum: `$3.978`;
- cache-write maximum: `$4.488`;
- hard reservation including a 10% billing contingency: `$4.9368`;
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
ceilings. The pilot SDK has `max_retries=0`: each inference is attempted once,
and an unknown outcome consumes its full reservation and permanently stops the
run. A complete pilot uses 30 inference requests plus 30 non-inference exact
input-token count requests.

## Local controls completed

- Direct Responses adapter is stateless, tool-free, `store=false`, and uses
  strict Structured Outputs, `service_tier=default`, a 120-second timeout,
  and the global standard endpoint.
- Python 3.11.15 and OpenAI SDK 2.49.0 are installed in an isolated runtime;
  the complete dependency lock hash, Python version, and SDK version are
  plan-bound and rechecked before inference.
- GPT-5.6 `cached_tokens` and `cache_write_tokens` are normalized for exact
  ledger pricing.
- Implicit prompt-cache writes are disabled because the 30-minute reuse window
  does not fit the ordinary daily role cadence.
- The fixed cycle ledger path is outside the repository:
  `~/Library/Application Support/Phase5R/llm_execution/<year>/`.
- The router supports zero/one/two/three same-provider calls; the fourth
  cross-provider role requires explicit policy opt-in.
- Canonical daily and safe-shadow read-only guards pass.
- One canonical quarantine and an exclusive process lock prevent concurrent or
  alternate-root re-spend.
- Every receipt is reconciled to a hash-chained reservation/completion journal;
  completed runs fail if either side is missing or changed.
- Pricing is pinned for at most seven days and currently expires 2026-08-04.
- Full test suite passes: `369/369`.

## Evidence readiness

- Replay ledger distinct accessions: `609`
- Qualification cohort selected: `250`
- Selected issuers: `6/20`
- Narrow packets materialized and verified: `10`
- Strictly complete pilot packets: `10`
- Locally complete qualification packets: `14`
- Typical qualification storage estimate: `956,795,580` bytes
- Enforced local storage ceiling: `5,000,000,000` bytes
- Current strict corpus use: `37,968,013` bytes

The original corpus verifier and stricter readiness inventory both pass the
frozen ten-packet Pilot cohort. This is evidence/provenance readiness only, not
model-quality or promotion evidence. No provider call was made.

## External blockers

1. External OpenAI authentication configured outside the repository.
2. Two independent transition/citation reviewers after model claims exist.

Licensed market data and a cross-provider challenger are deliberately not
blockers for the initial research-only shadow.
