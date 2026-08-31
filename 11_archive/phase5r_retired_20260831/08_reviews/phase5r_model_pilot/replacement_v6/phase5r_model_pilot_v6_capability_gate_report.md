# Phase 5R v6 — Sealed Pre-Execution Capability Gate

## Status

**READY FOR THE AUTHORIZED SHADOW-ONLY COLLECTION.** This report records the
offline gates completed before any v6 model inference. It does not create a
provider, read a credential, send a request, or write to the v6 quarantine.

## Authorized scope bound into the plan

- 30 new physical model inferences maximum; one attempt per call; SDK retries
  fixed at zero.
- $5.00 independent ceiling; worst-case reservation is `$4.9368`.
- Shadow research only: no email, trade, broker/account access, canonical
  influence, automatic action, credential persistence, raw failed response
  persistence, or provider response-ID persistence.
- v1-v5 are terminal predecessors. Their receipts cannot be reused, resumed,
  reset, or combined with v6.

The immutable replacement-plan SHA-256 is
`e2c37508abb5a2af7f0cbb2a52758b8ad2a06c00ec6271eb65b4c33b803bf9de`.
The read-only readiness reconstruction produced execution-plan SHA-256
`9dc50ecd15d8ff87dd7dfd143d6f30b8ebaaeac5050ed263f7ba77d6f7e5e87d`.

## Structured Output capability gate

OpenAI's Structured Outputs documentation permits `minLength` in strict JSON
Schema and explains that unsupported strict-schema keywords are rejected. It
also cautions that `minLength` may be unsupported for fine-tuned models. See
[Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs#some-type-specific-keywords-are-not-yet-supported).

v6 therefore applies `minLength: 1` to every model-authored string in each
strict stage schema. The first exact input-token-count request carries that
same strict schema. A schema rejection stops v6 before call reservation and
before model inference; an accepted first inference is collection call one,
not a separate diagnostic call. The closed local validator repeats the
non-empty check after parsing and still rejects whitespace-only or unsafe
content.

For analyst calls, the runtime projects each frozen packet to exactly one
deterministically selected same-ticker primary-source excerpt. It injects
packet identity, claim IDs, source IDs, excerpt hashes, calculation bindings,
and false effect flags after parsing, then invokes the unchanged closed
validator. No validator or safety constraint was relaxed.

## Offline evidence

- `check_v6_readiness`: passed, 10 packets, 30 planned calls, `$4.9368`
  worst-case reservation, no provider construction/network/model calls/files
  written.
- v6 regression suite: 4 tests passed, including a 30-call fixture collection,
  immutable completion replay, empty-text rejection, and response-ID
  non-persistence.
- Complete Phase 5R offline suite: **406 tests passed**.
- v1-v5 journal hashes were revalidated before v6 planning; their journals
  remain untouched.

## Execution condition

The user supplied the v6 authorization scope. The only remaining action is to
run `execute_model_pilot_v6` through the already-authenticated external OpenAI
runtime. A terminal failure, a safety change, a strict-schema rejection, a
budget gate, or a contract failure stops the collection permanently without a
retry or resume.
