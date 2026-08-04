# Phase 5R v9 terminal diagnosis

Status: **terminal no-retry stop — incomplete fresh collection.**

## Safe observed facts

- v8's three-call, non-collection provider qualification completed before v9.
- v9 completed 27 of 30 physical model calls for an exact completed-call cost
  of `$0.6531030`.
- The 28th started call, `ae2e6a43f3273c30c9fa-sol-critic`, reserved
  `$0.29040` and produced no usable final `ProviderResult`.
- The durable, privacy-safe diagnostic is:
  `failure_phase=provider_result_not_returned`,
  `failure_type=ProviderError`, and
  `provider_failure_code=response_incomplete`.
- `runtime_safety_issue` is null.  The journal contains no raw response,
  exception message, provider error code, provider response/request ID,
  response header, or credential.

The v9 upper-bound charged amount is `$0.9435030` (completed exact cost plus
the terminal reservation).  Including v8's exact `$0.0036900`, the two-stage
upper-bound amount is `$0.9471930`, below the user-provided `$15.00` training
budget.

## Decision

This is neither an environment-variable nor authentication failure: both v8
and the first 27 v9 calls returned through the authenticated provider path.
The failed v9 call is terminal and must not be retried or resumed.  Its 27
partial outputs are quarantined and cannot be combined with prior pilots or a
future collection.

## Required change before another full collection

The existing frozen protocol caps every response at 3,800 output tokens.  A
future protocol must be deliberately resealed with either a larger critic
output allowance or a shorter critic contract.  Both choices alter an
existing technical/quality limit, so no v10 paid call is authorized until that
new cap and protocol choice are explicitly sealed.
