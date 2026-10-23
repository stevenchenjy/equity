# Validated intraday observations and portfolio risk

Owner authority: October 22, 2026 request to add validated intraday prices and
portfolio-risk assessment to the existing 90-minute short checks. This adds an
optional, source-bound observation alongside the canonical completed-close
research decision. It changes no valuation, entry gate, allocation target,
risk budget, delivery rule or execution authority.

## Scope and admission

Each admitted short claim requests the complete positive inventory in the
approved local holdings record, classified with the current security metadata.
This is held-portfolio coverage, not a claim that the entire candidate universe
has intraday coverage. It is independent of momentum rank. A partial collection
cannot establish a current portfolio total, portfolio loss or allocation weight.
The canonical completed-close prices and their original history remain separate.

The initial public source is Nasdaq Last Sale through the credential-free
Nasdaq quote endpoint. It is an alternative last-sale observation, not the
consolidated NBBO, an executable bid/offer, a fill or guaranteed liquidation
value. Source context: [Nasdaq Last Sale](https://www.nasdaq.com/products/data/equities/nasdaq-last-sale).

The feed admits a row only when the original response passes all of these
checks:

- Exact requested symbol and stock/ETF asset class, successful provider and
  HTTP status, `marketStatus=Open`, and `primaryData.isRealTime=true`.
- An explicit same-session Eastern trade timestamp within the actual regular
  exchange session, no future trade/observation clock, and trade age no greater
  than 300 seconds at final validation. A newly fetched date-only close does
  not become an intraday observation.
- Finite positive USD price and arithmetic agreement with the exact current
  canonical prior close. The previous-close difference tolerance is $0.005;
  the provider's percentage rounding tolerance is 0.011 percentage points.
  These are displayed-data precision checks, not investment thresholds.
- Complete held coverage with no failed symbol, an oldest-to-newest trade-time
  span no greater than 120 seconds, immutable response/HTTP/snapshot bindings,
  and the exact account-input version and claim identity.

The baseline must be the latest required completed exchange session in the
canonical close snapshot, already admitted by the normal market-data workflow.
Its exact bytes and session are bound into the intraday observation. Intraday
collection does not repair an absent canonical baseline, change adjustment
basis, substitute an older session or overwrite the canonical close. The
normal full-universe market gate and its source/history checks remain effective.

Collection uses one sequential request per held symbol, at least one second
apart, an eight-second request timeout, no redirect or retry, bounded response
size and a 90-second collection budget. The short worker gives its collector
child a finite 105-second timeout within the original ten-minute claim. Final
validation uses the actual post-network clock; a slow batch cannot retain an
already expired earliest price.

Expiry is the earlier of the oldest retained trade plus 300 seconds and the
actual exchange close, including early closes. Closed sessions, delayed or
unverified timing, missing/corrupt evidence, an incompatible prior close or
incomplete coverage remain explicit unavailable/partial observations. A newer
failed attempt supersedes an older successful pointer; it cannot silently
reuse an older favorable mark.

## Durable inputs and assessment

The private source namespace is
`03_source_data/equity_research/intraday_prices.local/`:

- `responses/*.bin`: original response bytes, including retained failures.
- `http_receipts/*.json`: request/observation clocks, exact endpoint, status,
  headers, byte count and response hash.
- `snapshots/*.json`: immutable normalized batch, scope, failures, prior-close
  binding, account version, claim and expiry.
- `current.json`: atomic pointer to the exact latest attempt, including failure.

The derived receipt is
`04_research/company_research/intraday_portfolio_risk.local.json`, with immutable
assessment originals under
`04_research/company_research/intraday_portfolio_risk.local/assessments/*.json`.
Both the selected held scope and the assessment are private account-related
records even though the quoted security observations are public.

The `intraday_portfolio_risk_v1` assessment binds the current account, positive
whole-share inventory, known orders, maintained plans, approved allocation and
tactical policies, security metadata, admitted price snapshot and original
source receipts. Revalidation recomputes the observation from those exact bytes;
a content hash alone does not prove its arithmetic or provenance.

Marked portfolio value is current recorded shares times the admitted intraday
last sales plus current planning cash. The comparison value uses those same
shares and the same cash at the bound prior close. `value_change_usd` and
`value_change_pct` therefore measure a synthetic price-only change for the
current inventory. They are not actual account return, a flow-adjusted result,
peak drawdown, a forecast or evidence that a broker balance changed.

The assessment reports existing core/stock/cash weights, the largest individual
stock and its weight, and the existing tactical planned-risk budget when the
local records support it. ETF/direct-stock economic overlap remains unquantified.
One snapshot cannot estimate volatility, correlation, VaR or expected shortfall.
No fixed single-stock cap or new percentage-loss alarm is introduced.

Existing source-bound plan review dates and fundamental invalidation conditions
remain effective. A price crossing is recognized only from a still-current
structured reference, such as an existing sell STOP condition. A dollar amount
in prose or a valuation scenario does not become a new stop. An observed crossing
requires reassessment; it supplies no new order, quantity, verified fill or
permission to trade. Missing primary evidence stays a research dependency.

## Short-check and publication integration

The normal claim entry point remains:

```sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/messssi/LocalRuntime/equity/09_scripts/equity_research/run_short_assessment.py --claim --refresh-public --root /Users/messssi/LocalRuntime/equity
```

Only a real admitted claim starts bounded intraday HTTP collection. A recent
news/calendar poll does not count as a fresh price observation. Holidays,
closed sessions, already completed slots, nonblocking refresh admission,
15-minute admission grace and the ten-minute claim budget are unchanged.
There is no replay of missed slots or renewal of expired trading instructions.

`run_intraday_assessment.py` without `--collect` is offline. The full refresh
and the claim-bound offline publication closure use it to revalidate and retain
the optional assessment before daily decision composition. The canonical field
is `daily_decision.intraday_portfolio_risk`. Exact observation/source bindings
participate in publication checks. Recomposition cannot freshen the trade
clock or extend expiry.

Use the deployed full `run_daily_refresh.STEP_SPECS` and offline
`short_publication.STEP_NAMES` as the required stage sets; both include
`intraday_risk_projection`. Do not accept an older stage count as proof that the
current closure ran. Actual accepted analyst amendments still require the full
operator-safe no-send refresh. A public-only claim with unchanged protected
account/market/analyst inputs uses the existing validated offline publication
route, then must pass its exact final decision/text/HTML checks before completion.
Neither collection nor publication is completed company analysis.

An absent, closed, failed or expired optional observation does not disable an
otherwise valid completed-close decision or mandatory brief. Genuine account,
company, market and investment-gate failures keep their existing effect. No
optional-data failure may fabricate a loss, clear a genuine blocker or grant
trading eligibility.

## Email, dashboard and delivery

The production text and HTML show a dated observation card with the actual
price clock, source/delay label, baseline and expiry. This immutable email
records risk at observation time; reading it later does not make the prices
current. Its existing completed-close holdings/cash and conditional action
cards remain separate.

The dashboard independently projects that same assessment against the actual
read-time account, source bindings, latest attempt and clock. Expired, changed
or invalid observations suppress current aggregate NAV, price-only loss,
weights and price-dependent crossing claims. The browser also applies expiry
between API polls. Older decisions without an intraday field remain compatible.
The closing-value account summary and recorded cash are never overwritten by
an intraday mark.

Raw price polling, price-only movement, a refreshed clock or a collector success
creates no extra email purpose. The installed scheduled sender still owns the
two mandatory daily briefs and only existing eligible changed-action or
substantive source-bound research-priority alerts. Duplicate claims, uncertain
sends, previous advice and unresolved manual execution remain protected. No
SMTP call, test email, broker access or trade is authorized by this feature.

Deployment, a passing mocked/offline test, actual collection, admitted fresh
portfolio coverage, source-bound analyst judgment, final rendered output and
SMTP acceptance are separate claims. Verify each required step from its actual
receipt. An after-hours unavailable result proves safe closed-session behavior;
it is not a successful live intraday run.
