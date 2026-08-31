# Phase 5R-C5 Recommendation Label Policy

All labels are weekly research classifications for independent human judgment.

| Label | Meaning |
| --- | --- |
| `eligible_buy_review` | Candidate may receive a fresh manual research and sizing review; no portfolio change is authorized. |
| `wait_for_pullback` | Thesis may merit continued work, but valuation, entry conditions, or portfolio fit are not currently supportive. |
| `hold_existing` | Existing thesis remains adequate and concentration is within the applicable review boundary. |
| `add_review` | Existing position may receive a manual add analysis only when all concentration limits permit it. |
| `trim_review` | Existing position warrants a manual concentration or conviction reduction review. |
| `exit_review` | Existing thesis may be materially impaired and warrants a full manual exit analysis. |
| `reject` | Evidence does not support continued candidate work. |
| `watch_only` | Keep under observation with no current sizing review. |

## Guardrails

- Positions above 8% cannot receive `add_review`.
- The active sleeve cap and theme exposure must be considered before a new candidate is promoted.
- No more than two new candidates may receive `eligible_buy_review` in one run.
- Recommendations use measured review language and never imply certainty or automatic action.
