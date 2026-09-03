# Phase 5R SHADOW_LLM

SHADOW_LLM is an event-driven, noncanonical analyst/conditional-critic/blind-
judge evaluation. It may call the pinned externally authenticated Codex CLI,
but it has no production, decision, email, account, broker, or execution path.

Authority and thresholds are defined in:

- [`phase5r_shadow_llm_evaluation_policy.md`](../../00_project_control/phase5r_shadow_llm_evaluation_policy.md)
- [`phase5r_shadow_llm_config.json`](../../00_project_control/phase5r_shadow_llm_config.json)

## Safe preflight

This validates the closed configuration and pinned provider binary without a
model call:

```bash
python3 09_scripts/phase5r/run_phase5r_shadow_llm_evaluation.py --check
```

## Automatic event modes

Evaluate the current packet only when its research-semantic fingerprint has not
already been attempted in this stage:

```bash
python3 09_scripts/phase5r/run_phase5r_shadow_llm_evaluation.py --auto-live \
  --packet /Users/messssi/LocalRuntime/equity/03_source_data/phase5r/phase5r_llm_evidence_packet.json
```

Select the next eligible current-schema replay packet using the fixed sampling
rule:

```bash
python3 09_scripts/phase5r/run_phase5r_shadow_llm_evaluation.py --auto-replay
```

Automatic modes skip without spending a call when no eligible semantic event
exists or the stage event limit has been reached. A new live packet is archived
privately for later replay. Old-schema archives are not silently admitted.

On the Mac mini, the separate evaluation-only LaunchAgent watches the evidence
packet path and runs `--auto-live` only after that file changes. The runner's
semantic fingerprint gate suppresses price-, account-, and timestamp-only
churn. It is installed and checked independently of the production schedulers:

```bash
/bin/zsh 07_automation/scheduler/install_phase5r_shadow_llm_evaluation_scheduler.sh
/bin/zsh 07_automation/scheduler/check_phase5r_shadow_llm_evaluation_scheduler.sh
```

The event wrapper updates the aggregate evaluation after every success, skip,
or failed attempt. It cannot send email or change any canonical artifact.

The manual diagnostic path remains available for an explicitly classified
packet:

```bash
python3 09_scripts/phase5r/run_phase5r_shadow_llm_evaluation.py \
  --live --evaluation-class replay --acknowledge-external-inference \
  --packet /absolute/path/to/phase5r_llm_evidence_packet.json
```

## Evaluation

Aggregate all immutable runs without a per-run human review file:

```bash
python3 09_scripts/phase5r/evaluate_phase5r_shadow_llm_incremental_value.py \
  --runs-root 08_reviews/phase5r_shadow_llm/runs.local \
  --output 08_reviews/phase5r_shadow_llm/reviews.local/evaluation.json
```

The analyst always runs. The critic runs only for configured material or risky
result types. A different model blind-judges every counted event without seeing
candidate origin, analyst materiality/novelty, or critic verdict. Deterministic
validators enforce source binding and exclude critic/judge disagreements from
incremental supported value.

The private hash-chained ledger counts every physical attempt, including
failures, and records exact CLI-reported token counters for new completed
calls. Authoritative dollar billing is unavailable from this transport and is
not imputed. A fixed ten-percent sample is flagged for optional human spot
checking; no owner template or label is required for routine evaluation.

Fixture runs validate plumbing only and never count toward replay or live
thresholds. Even a fully passing aggregate report sets
`promotion_authorized=false`; additional authority requires a separate explicit
decision.
