# Phase 5R risk-policy audit — 2026-09-14

## Scope and conclusion

This is a code-path audit and an offline arithmetic diagnostic, not a policy
activation, trade instruction, backtest, VaR calculation, or return forecast.
No account cash, credentials, broker connection, or private account snapshot is
included in this versioned document or the synthetic test fixtures.

The existing 30% active-stock limit and 6%/8% individual-stock limits are
operational preferences. This audit found their repository origins, but no
point-in-time, out-of-sample evaluation establishing that these exact numbers
maximize returns or constitute universally appropriate risk limits. Relaxing
them increases available concentration; it does not establish higher returns.

## Origins and current code path

- The root repository commit `e719060` (2026-07-24) already contains the
  dynamic-weight/action-threshold policies, the account-example 20% active
  target / 30% active cap and 6% default / 8% individual cap, and concentration
  fit functions. History before that root is unavailable here.
- Commit `4ef8b07` (2026-08-31) introduced the active-production configuration
  with 6%/8% individual limits, 60% core / 20% active / 20% cash targets and a
  cash reserve. Commit `438dd83` (2026-09-01) introduced tier sizing and the
  small-account whole-share exception. These are provenance facts, not
  empirical validation of the choices.
- `phase5r_c9_common.load_account_state()` reads the manually maintained local
  account state. Before this change the production configuration did not
  override that account's concentration caps. The new explicit
  `load_research_account_state()` accepts only the optional, validated three-cap
  `account.research_risk_limits` overlay. No overlay is activated in this change.
  Cash, timestamps, raw account bytes and financial reconciliation still use
  the original account state. Changing the old descriptive config fields alone
  remains insufficient to change the C9 policy.
- `dynamic_position_fit()` assigns fit 2 above the individual hard cap, 6
  above the default cap and 8 within the default cap. Portfolio fit contributes
  10% of `score_from_packet()`'s composite score.
- `calculate_phase5r_c9_dynamic_weights.main()` labels a non-core holding over
  the hard cap `trim_review`; a lower-priority score below 5.5 becomes
  `exit_review`. Merely removing the concentration trim branch could expose
  score-driven exits that are themselves partly caused by concentration.
- `create_phase5r_c9_exact_action_plan.main()` translates an individual-cap
  breach into integer-share reductions. A holding only slightly above 8% can
  require selling a whole share; a one-share holding can therefore become a
  full-exit draft. The cap arithmetic alone is not evidence of thesis failure.
  Core ETF holdings are exempt from this individual active-stock cap.
- `dynamic_candidate_fit()` gives fit 7 at or below the 20% active target, 5
  between target and the 30% cap, and 1 above that cap. The exact theme label
  `AI infrastructure` then subtracts another 2. Thus a name in that theme can
  receive fit 3 before the active sleeve reaches 30%, below the fit 5/6 minima
  in all current sizing tiers. This is a hidden veto, not a measured portfolio
  correlation or issuer-exposure estimate.
- `phase5r_portfolio_construction.individual_sizing_decision()` separately
  requires valuation, score, confidence, upside, reward/risk, entry and fit
  gates. Its dollar capacity is the minimum of explicit deployable cash, the
  selected tier/default position limit and active-sleeve headroom. The one-share
  exception does not waive the default individual limit, cash or sleeve cap.
  Changing concentration caps alone cannot repair incomplete valuation.

## Minimal coherent follow-up, after a policy choice

1. Distinguish a concentration alert from a thesis-based sale. A soft-alert
   policy must not still force sales through a depressed composite score or an
   alternate exact-action branch. Keep independent adverse-evidence reviews.
2. If an active cap becomes soft, update its use in fit, sizing, action labels,
   packets and user-facing explanations together. Do not call a limit soft
   while continuing to use it as a hidden zero-buy ceiling.
3. Replace or explicitly expose the fixed theme penalty. A theme label alone
   is not a calibrated overlap, correlation or tail-risk model.
4. Preserve hard data-quality, evidence-completeness, cash/reserve, no-margin,
   no-broker and manual-execution boundaries. Do not count planned deposits or
   hypothetical sales as available funds. Report whether zero whole shares
   result from cash, individual cap, active headroom or evidence.
5. Add integration regressions for concentration-only versus thesis-driven
   exits, an above-target but within-cap candidate, core exemptions and all
   affected report/packet schemas. Relevant existing suites include active
   production, held-core-position, reassessment-reporting, owner-snapshot and
   packet-market tests. This isolated diagnostic does not replace them.

## New offline diagnostic

`09_scripts/phase5r/phase5r_risk_policy_diagnostic.py` compares three explicit
preference scenarios without changing production:

| Scenario | Active-stock cap | New-position cap | Held-position cap |
| --- | ---: | ---: | ---: |
| Existing | 30% | 6% | 8% |
| Moderate preference | 50% | 15% | 15% |
| Aggressive preference | 70% | 20% | 20% |

For the two proposed scenarios, the named single-position percentage is used
for both new and existing holdings; this is an explicit comparison convention,
not an activated production setting. These are user preference alternatives,
not optimized thresholds or a recommendation to fully use available capacity.

The module requires finite positive NAV and prices, explicit nonnegative cash
and reserve, and reconciliation of NAV to cash plus every marked holding within
one cent. It does not derive cash as the residual of an aspirational account
size. Unconfirmed cash produces hypothetical capacity only, never positive
confirmed-cash capacity. Every candidate's capacity is independent: adding the
reported quantities together can exceed the shared budgets. Production tier,
evidence, fees, settlement and pending-order checks are outside this module.

The separate stress function requires an explicit shock for every holding,
including the core ETF. All shocks occur simultaneously, so no diversification
credit is invented. Cash and its reserve stay unchanged; percentage losses use
the entire starting NAV including cash. This is not a fitted correlation
matrix, probability estimate, realized drawdown series or historical backtest.
Caps alone do not change holdings, so they cannot change snapshot stress losses
unless a separate hypothetical portfolio is explicitly supplied and reconciled.

Methodological guardrails follow the installed `backtesting-frameworks` and
`risk-metrics-calculation` skills from `wshobson/agents`, pinned by the parent
task to revision prefix `4236bb91`: state assumptions, account for coincident
stress, and do not infer strategy performance from a snapshot or subsequent
rally. No illustrative implementation code from those skills was copied.

Run the synthetic offline checks with:

```sh
python3 -m unittest discover -s 09_scripts/phase5r/tests -p 'test_phase5r_risk_policy_diagnostic.py' -v
```

No market download, third-party dependency, production-file edit, policy
activation, commit, email or order is part of this diagnostic implementation.
