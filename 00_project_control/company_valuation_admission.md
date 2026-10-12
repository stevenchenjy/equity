# Company-specific valuation in production

Effective October 12, 2026, by explicit owner request. The versioned route is
defined in `01_policies/company_valuation_admission.json`. An individually
admitted reviewed company model replaces the generic EV/revenue comparator for
that ticker. This implements the company's price assessment; it does not relax
the approved evidence thresholds, allocation rules or human-only execution.
Momentum experiments and SHADOW remain separate and experimental.

The immutable model, all original sources and the research-only valuation
bundle remain unchanged. Admission requires the current accepted company
review, matching original model hash, three source-bound cases, same-period
canonical financial observations, current earnings/news incorporation, explicit
method/horizon/countercase and allocation judgment. A current negative case can
be admitted and remain zero-share NO_ACTION. No positive size follows merely
from model admission: it also needs a supported business case, a current plan
with `reviewed_allocation`, entry/invalidation/deadline, all numerical quality
thresholds and shared capital/aggregate/core-floor checks.

The October 12 verification also registered directly fetched and parsed
official ORCL and META issuer feeds for the current individual-company queue.
The verified manifest remains the coverage boundary. Successful collection
does not acknowledge announcement impacts or complete a company review; newly
covered companies still require actual primary-source analysis before admission.

The default absent-admission path preserves the existing comparator. Once a
ticker opts in, an expired/invalid model, changed review or new financial
period yields an explicit ticker-local incomplete projection. It cannot fall
back to the comparator to authorize a buy. Other issuers continue. A corrupted
shared admission ledger cannot provide trustworthy scope and is reported as
a shared model-integrity failure. Historical rejected/expired admissions are
never deleted or selected according to later returns.

## Analyst workflow

Use the production interpreter and absolute paths. Obtain a draft with:

```sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/messssi/LocalRuntime/equity/09_scripts/equity_research/update_company_valuation.py --root /Users/messssi/LocalRuntime/equity --template TICKER
```

Fill the method, horizon, reviewer, unique case ID, allocation conclusion and
three case citations. Each citation points by JSON pointer into an exact
human-scenario source already in the reviewed model; its parent must identify
the same bear/base/bull case. Seal using `--input PROPOSAL --seal`, saving the
result to a separate dated private proposal. Then check with `--input SEALED`
and append only after validation with `--input SEALED --apply`.

The coordinator holds the runtime lock, then daily-pipeline lock, as documented
in `analyst_followthrough.md`. This CLI owns only
`00_project_control/run_logs/company_valuation_admissions.lock`; do not hold
that writer lock while invoking it. It preserves exact prior and new ledger
bytes in the private content-addressed admission history. No account, holding,
order, plan purpose or model assumption is changed by this writer.

Release mutation locks, then run the existing operator-safe full no-send
refresh. Verify `company_valuation_admission_status.local.json`, canonical
valuation scenarios, derived current-price evidence packet, recommendation
CSV, final capital contract and text/HTML. The publication registry binds the
admission store, policy and canonical projection, so changed inputs require
recomposition. The final email keeps three-case prices and valuation-only
ceilings in supporting information; only admitted full drafts populate BUY or
SELL cards. A scenario ceiling is not an order.

Software validation establishes source binding and correct propagation, not
profitable assumptions. Retain comparator and company values at the same
available close and carry forward negative, missed and expired cases. Use
`04_data/equity_research/company_valuation_observations.local/` for immutable,
input-deduplicated projection observations; the sealed admission history binds
the original review and model. These observations contain no assumed trades,
fills or net returns and are not independent performance trials. Use
realistic costs and whole shares in final drafts; a price-distance ratio is
not a calibrated expected return. Subsequent observations cannot rewrite the
original case or automatically promote an experimental strategy.
