# Phase 5R v8 provider-reliability gate proposal

Status: **superseded by the sealed v8 qualification plan after the user
authorized a `$15.00` training budget.**  The v8 plan itself has a tighter
three-call / `$0.87120` qualification cap.

## Evidence and decision

The authenticated external runtime produced successful Phase 5R calls before
each terminal event.  Authentication and `OPENAI_API_KEY` presence are
therefore not the observed failure boundary.

The immutable v6 and v7 journals account for 21 physical attempts and an
upper-bound charge of `$1.1791040` (`$0.1759690` for v6 and `$1.0031350` for
v7).  Relative to the original 30-call / `$5.00` ceiling, at most nine
physical attempts and `$3.8208960` remain.  Those remaining attempts cannot
repair either terminal call and cannot yield the frozen protocol's required 30
usable outputs.  They must not be used to continue partial collection.

## Proposed independent qualification

Before any separately funded fresh Phase 5R collection, run only this sealed
provider-reliability qualification:

- At most three sequential, non-collection diagnostic calls.
- Each uses the same `gpt-5.6-sol`, `high` reasoning, 120-second timeout,
  strict Structured Outputs, tool-free, `store=False`, and SDK
  `max_retries=0` shape as the v7 call that did not return a result.
- A passing gate requires all three calls to return and pass their closed
  diagnostic contract.  A single failure stops the gate immediately; there is
  no retry or automatic successor call.
- Maximum reservation: `$0.87120` (three times `$0.29040`).  This is within
  the user-provided training budget and is the only newly authorized external
  qualification cap.
- The gate has no canonical, scheduler, email, broker, trade, account, or
  credential-storage effect.  Its output is quarantined and cannot be used as
  research evidence or to form an investment decision.

## Privacy-safe diagnostics

For a future failure, persist only the finite `provider_failure_code`,
`failure_phase`, exception class, and retry prohibition.  The diagnostic code
may distinguish connection, timeout, authentication, rate limit, server,
HTTP-class, missing output, strict-output status, invalid JSON, or usage
reconciliation failures.  It must never retain an exception message, provider
error code, response body, response/request identifier, response header, or
credential.

## Stop rule after the gate

Whether the gate passes or fails, do not spend the remaining original budget
on the frozen v6/v7 collection.  It cannot become complete.  A future research
collection requires a fresh, separately approved 30-output protocol and a
new explicit call and USD cap.
