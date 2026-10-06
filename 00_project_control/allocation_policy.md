# Owner-approved allocation policy

Approved by the owner on 2026-10-06 ET. This is the maintained allocation
contract; the effective executable settings live in
[active production configuration](active_production_config.json). Approval,
source implementation, production deployment and recomposition are distinct
states and must be verified independently.

## Explicit authorization and definitions

The owner directed complete replacement of the former allocation standard with
“30%+ 广基核心 / 70%个股”, removal of the fixed individual-stock hard ceiling,
and support for concentrated research into higher-risk, higher-return growth
opportunities. This is an owner preference, not an empirically optimized
allocation or evidence that additional risk produces additional returns.

| Allocation or control | Current approved standard |
|---|---|
| Broad-market core | At least 30% strategic allocation, with 30% as the baseline sizing target. More than 30% is permitted; 30% is not a ceiling or an automatic trim trigger. |
| Individual stocks, in aggregate | 70% baseline target and maximum allocation. More core or undeployed cash reduces the room available to stocks. |
| Cash | 0% strategic target and $0 mandatory internal reserve. Available capital need not be fully invested when evidence, account facts, integer shares or execution conditions prevent a qualified proposal. |
| Fixed single-stock allocation cap | None. No legacy default or hard percentage may reappear through an account record, fallback, score, trim rule or renderer. |
| Planning capital | The approved $4,000 planning basis is unchanged. Outside reserve money is not added to investment capital. Current cash, shares and market-value calculations retain their validated provenance. |

The percentages are allocation destinations, not three simultaneous minimums.
At the baseline they total 100%. A higher core allocation necessarily reduces
individual-stock exposure or unallocated cash. A temporary core shortfall must
be shown and prioritized; it does not justify an automatic purchase, an assumed
broker deposit or a trade with unavailable evidence. Stock proposals must leave
room for the core minimum and stay within the aggregate maximum.

## Concentrated growth and strategy-specific controls

Research may support a large individual growth position when current business,
valuation, downside, dilution, liquidity, overlap and executable-entry evidence
justify it. Explain the strongest countercase, stressed portfolio loss and
conditions for reducing or exiting. Greater volatility or a high advertised
upside alone is not positive investment evidence. Never increase a position to
recover a loss or silently relabel a failed short trade as a growth investment.

Removing a portfolio-wide name cap does not remove strategy-specific risk
budgets. Tactical plans retain initial exposure at most 5% per name, planned
loss at most 0.5% per ordinary trade or 0.25% for event exposure, 2% combined,
at least 2:1 plausible reward/risk and a three-to-five-session reassessment/exit.
Gaps and slippage can exceed planned loss. A concentrated growth allocation
requires its own supported growth purpose; it cannot evade tactical limits by
changing a label. The owner also approved replacement of fixed 3%/5%/6%
initial-sizing ceilings with company-specific, source-bound desired position
sizes. Each proposed growth size needs a maintained plan recording the desired
weight, investment rationale, downside/countercase, invalidation and current
supporting evidence. There is no automatic equal-weight size or automatic 70%
allocation to one company; unused capital does not establish an investment case.

Current quotes, complete current orders, actual available shares, settled funds,
whole-share feasibility and applicable strategy evidence remain required.
Execution is human-only in the cash-account workflow; there is no leverage,
automatic trading, paid-service authorization or broker integration. Momentum
experiments remain experimental until their separate version-specific adoption
process is satisfied. Frozen studies retain their original rules and cohorts.

## Supersession and reproducibility

This policy supersedes all active use of the former 40/50/10 allocation,
50% aggregate stock cap, 15% fixed single-stock cap, and the separate 60%
economic-core / 30% tactical / 10% cash destination. Those former numbers do
not constrain new recommendations. Position purposes remain explicit, but no
replacement economic-purpose split is invented. Earlier reserve amounts are
also obsolete; the approved reserve remains zero.

Preserve archived policies, private account snapshots, sent emails, original
plan versions and frozen experimental observations as dated evidence. They
are not current policy inputs. A policy migration must preserve cash, share,
order, fill and observation timestamps; it must not freshen account facts or
erase genuinely missing order evidence. Current configuration, every active
consumer, generated decision/text/HTML/dashboard and deployed runtime must be
checked together. Passing source tests alone does not prove activation.
