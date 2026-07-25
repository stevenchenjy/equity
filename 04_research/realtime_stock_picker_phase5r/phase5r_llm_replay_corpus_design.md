# Phase 5R LLM Replay Corpus Design

## Purpose and non-goals

This corpus is an evidence and time-boundary test bed. It is not a backtest,
does not reconstruct historical portfolio decisions, and does not create buy or
sell labels. Completion of the corpus cannot enable live model inference or
alter the canonical Phase 5R decision pipeline.

The required promotion evidence is deliberately split:

1. **Real-source packet validity** proves that a packet is backed by an actual
   SEC filing, an exact SEC acceptance timestamp, immutable source hashes, and
   a public daily close that became available later.
2. **Provider quality** is a separate future evaluation requiring frozen,
   independently annotated reference answers. An unlabeled packet cannot count
   as a correct model decision, and future returns must not be used to invent a
   label.

## Point-in-time construction

- Source universe: the 609 distinct accession numbers already recorded in
  `phase5r_daily_evidence_ledger.csv`.
- Selection: deterministic recent-first round-robin across tickers, with a
  configurable reserve pool. This prevents a high-filing-volume issuer from
  dominating the first 200 packets.
- SEC evidence: the official primary document plus the official filing-index
  page. The exact `Accepted` field is parsed to the second and interpreted in
  `America/New_York`, including the historical DST offset.
- Market evidence: unadjusted daily close from the public Yahoo Finance chart
  endpoint, retained as raw JSON with its SHA-256. It is explicitly secondary
  evidence.
- Leakage guard: the selected close is the first valid exchange-local daily bar
  whose calendar date is **strictly later** than the SEC acceptance ET calendar
  date. This conservative rule avoids same-day after-close and early-close
  ambiguity. Packet `as_of_et` is 23:59:59 ET on that bar date. The full
  provider response is retained only in the corpus manifest's upstream cache
  for verification; each packet references a separately hashed single-bar
  observation containing no later bars.
- Immutability: every raw SEC page, normalized filing text, source locator,
  chunk, packet, and manifest entry is hash-bound. The verifier recomputes all
  of them offline.

## Network and safety boundary

`prepare_phase5r_llm_replay_corpus.py --check` and
`verify_phase5r_llm_replay_corpus.py --check` perform no network request and
write no file. Public retrieval exists only behind explicit `--refresh`.

SEC requests require a declared User-Agent and are rate-limited to 1.8
requests/second by default; the code rejects any configured rate above two
requests/second. Hosts, schemes, paths, redirects, content types, and response
sizes are fail-closed. Historical market retrieval is also allowlisted and
occurs only in refresh mode.

There is no email, SMTP, account, broker, order, model, API-key, or canonical
decision integration. The manifest and every packet record these boundaries as
false.

## Cases without fabricated labels

The manifest requires at least 50 **distinct real-source transition probes**
and, separately, at least 50 adversarial safety probes:

- `material_transition_detection_probe` pairs two real, chronologically
  ordered filings from the same issuer. It says only that the pair should be
  checked for a possible evidence transition. `material_transition_claimed` is
  false and the historical label remains null until independent annotation. A
  canonical fingerprint binds the ticker and both packet IDs; duplicate filing
  pairs cannot satisfy the threshold.
- `adversarial_safety_probe` describes a synthetic mutation over a real packet,
  such as a bad source hash, future timestamp, missing acceptance time,
  pre-acceptance market bar, instruction-like overlay, or numeric close
  mutation. Its reference is a safety result (`reject_or_abstain`), never a
  market decision.

Passing 200 real packets, 50 distinct transition probes, and 50 adversarial
probes therefore validates corpus mechanics
only. It neither demonstrates investment skill nor satisfies the separate
provider-quality and live-shadow promotion gates.

Any future provider-evaluation report must bind the exact corpus manifest file
SHA-256, model-registry file SHA-256, each role's model identifier and
configuration hash, every prompt hash, and retained provider-response hashes.
Activation must fail closed when that separate report is absent or any binding
differs. Synthetic fixtures, adversarial overlays, or corpus counts cannot
substitute for this bound provider evaluation.

## Intended commands

Offline read-only inventory and full verification:

```sh
python3 09_scripts/phase5r/prepare_phase5r_llm_replay_corpus.py --check
python3 09_scripts/phase5r/verify_phase5r_llm_replay_corpus.py --check
```

Future public-source refresh, after an operator supplies an SEC-compliant
contact User-Agent:

```sh
python3 09_scripts/phase5r/prepare_phase5r_llm_replay_corpus.py \
  --refresh \
  --user-agent "Phase5RResearch/1.0 contact@example.com"
```

The 200-filing refresh was intentionally not run during implementation.
