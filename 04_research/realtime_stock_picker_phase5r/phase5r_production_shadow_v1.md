# Phase 5R Production Shadow v1

`phase5r-production-shadow-v1` is a one-call-per-trading-day, noncanonical research companion to the deterministic Phase 5R daily workflow. It is not a trade engine, an independent human review, or an authority to change a deterministic buy, hold, avoid, or position decision.

## Workflow

1. The existing daily refresh completes its deterministic market, evidence, portfolio, decision, and sanitized-evidence-packet steps.
2. The existing refresh scheduler invokes `run_phase5r_production_shadow.py --run` as a separate post-refresh companion only when the just-written refresh receipt is current and has `outcome=passed`, `decision_created=true`, and no hard or soft failures. A `degraded_decision_created` receipt never starts shadow or email delivery.
3. The new runner reads only the current sanitized packet plus non-sensitive decision/refresh state. It requires a same-day fully passed refresh, complete verified close, current evidence receipts, passed packet gates, and a current pricing configuration.
4. Before copying or transmitting evidence, it rejects privacy-sensitive packet/model-input text. It then freezes a primary-source, exact-excerpt projection; a production manifest; a v3 preflight span bundle; a future-v2-shaped offline owner approval reference with all provider authority fields `false`; and a separately bound runtime authorization for the one permitted request.
5. It validates the lower-level future-v2 evidence metadata contract and v3 literal-span contract before constructing a provider client.
6. It reserves `$0.18` before one `gpt-5.6-terra` request at medium reasoning effort, with at most 4,000 output tokens. The dedicated SDK client is configured with `max_retries=0`; the adapter uses strict JSON, `store=false`, and `tools=[]`.
7. It validates the returned citations, exact literal anchors, future-v2 bindings, response boundaries, and the provider receipt's canonical input hash. It writes a report, validation receipt, and hash-chained ledger entry under the new production-shadow roots only. A rejected response with a known usage receipt remains visible in metered-cost reporting.

## Valuation boundary

- Canonical C9/action-review freshness remains unchanged: missing or stale valuation inputs continue to block fair-value, target-price, valuation-based action conclusions, and valuation-based BUY/SELL reasoning.
- The isolated SEC-excerpt shadow may proceed only when every other shadow freshness and provenance gate passes. A missing valuation bundle does not itself authorize a provider call, a canonical action, or a valuation conclusion.
- The frozen projection, provider input, completed result, Markdown report, and eligible email record `valuation_status`, `valuation_actionable`, and `valuation_conclusion`. With unavailable valuation inputs these are `unavailable`, `false`, and `abstain` respectively, and the response must disclose `valuation_evidence_absent`.
- The shadow request always abstains from fair-value, target-price, under/overvaluation, or a claim that valuation supports an action. It can report only the supplied SEC-excerpt evidence and a noncanonical research classification adjustment.

The old full future-v2 handoff verifier is intentionally not used as a live pre-provider envelope: it requires provider authority and provider use to remain false. The new envelope keeps that contract truthful and uses the approved lower-level v2/v3 validators instead.

## Observation controls

- One provider attempt is reserved per ET trading day; failures and unknown outcomes retain their full reservation and block another attempt that day.
- Later refresh slots consult the reservation ledger before freezing another handoff. The scheduler emits only a closed child outcome code, never raw provider stdout/stderr.
- Monthly reservations cannot exceed `$2.00`; ten fully reserved observation days fit below that hard cap.
- The observation target is ten completed trading-day reviews.
- Once the first real request is reserved and until the tenth completed review, the existing scheduled daily email is suppressed—even if the first request later fails authentication, transport, citation, or span checks. The shadow runner never sends email and never includes an LLM summary in the normal daily email.
- Each reservation/completion record starts with `human_usefulness_status=awaiting_human_assessment`; usefulness is not inferred automatically.
- A human can append exactly one offline assessment for each completed run; it never modifies the original report or decision:

```sh
PYTHONPATH=09_scripts/phase5r python3 09_scripts/phase5r/record_phase5r_production_shadow_human_assessment.py \
  --run-id <run-id> --usefulness useful --assessment-code materially_improved_review
```

## New artifact roots

- `08_reviews/phase5r_production_shadow_v1/handoffs/`
- `08_reviews/phase5r_production_shadow_v1/validations/`
- `08_reviews/phase5r_production_shadow_v1/reports/`
- `08_reviews/phase5r_production_shadow_v1/ledger/`
- `00_project_control/phase5r_production_shadow_v1/owner_approvals/`
- `00_project_control/phase5r_production_shadow_v1/runtime_authorizations/`

These are separate from v10, blind keys, completion records, prior pilots, journals, receipts, policies, and legacy runners.

## Limited first-report email companion

The Project Owner separately authorized one narrow delivery surface for the first fully valid shadow result. `send_phase5r_production_shadow_email.py` is a separate companion invoked by the existing refresh scheduler only when the shadow outcome is exactly `completed`; it never runs for blocked, incomplete, stale, terminal-failure, or material-citation-issue outcomes.

- Recipient: `stevenchenjy326@gmail.com`.
- The module does not use the repository's legacy SMTP configuration or import an SMTP client. It requires an existing external executable named by `PHASE5R_PRODUCTION_SHADOW_MAIL_RUNTIME`, outside the repository, with a no-send `--check` contract.
- The external check must attest that authentication is available without a network attempt or credential exposure. If that check is unavailable or invalid, delivery is recorded as `configuration_blocked` and remains fail-closed.
- Before the one irreversible send attempt, the companion revalidates the immutable report/result/validation/manifest/model-input bindings, provider input receipt, privacy scan, citation/span status, cost exposure, noncanonical boundary, and report hash.
- A hash-chained receipt under the new production-shadow ledger is written before dispatch. `send_claimed`, accepted delivery, and delivery-unknown outcomes all block any same-day retry.
- The message is derived from validated report fields only, states that it is shadow-only and noncanonical, and explicitly says that no broker, account, position, or order action occurred.

This narrow exception does not enable normal LLM email summaries, canonical influence, provider retries, or any broker/account/order action.

## Operating commands

```sh
python3 -m pip install --user --requirement 09_scripts/phase5r/phase5r_production_shadow_requirements.txt
PYTHONPATH=09_scripts/phase5r python3 09_scripts/phase5r/verify_phase5r_production_shadow_readiness.py
PYTHONPATH=09_scripts/phase5r python3 09_scripts/phase5r/run_phase5r_production_shadow.py --check
PYTHONPATH=09_scripts/phase5r python3 09_scripts/phase5r/run_phase5r_production_shadow.py --run
PYTHONPATH=09_scripts/phase5r python3 09_scripts/phase5r/run_phase5r_production_shadow.py --cost-exposure
```

The `--run` command is safe to invoke after the deterministic refresh: it exits as a no-op when any gate is not ready. A missing or incorrect pinned SDK is blocked before a handoff is frozen or a daily reservation is made; a reservation is never retried.
`--check` verifies only the fixed SDK package version; it deliberately does not construct a client or probe authentication.

## Criteria before considering an LLM email summary

This implementation does not authorize an LLM email summary. A later, separate owner authorization should require at least all of the following:

- ten completed observation-day reviews with no unresolved terminal runtime, privacy, cost, or integrity failures;
- every accepted output has completed v2 citation binding and v3 span validation, with material citation/overclaim rates reviewed by a human;
- a human has recorded usefulness for the ledger entries rather than leaving them unassessed;
- the LLM remains noncanonical and cannot alter deterministic classifications, positions, orders, accounts, or broker state;
- any proposed email text is a separately bounded summary of the frozen report, contains its noncanonical disclosure, and passes a dedicated privacy/citation review;
- explicit Project Owner authorization enables that email surface only. No such authorization is created by this workflow.
