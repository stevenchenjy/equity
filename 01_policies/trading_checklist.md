# Trading Checklist

Scope note (2026-09-04): this is a manual trade-planning reference. It is not a
required per-run SHADOW_LLM review template and does not apply to routine
HOLD/WATCH research. See [current documents](../00_project_control/current_documents.md)
for the active deterministic gates; this checklist does not authorize trades.

Use this checklist before any paper trade plan or real trade plan. A real trade requires explicit human approval outside this repo.

## Research Completeness

- Ticker and company name confirmed.
- Latest 10-K, 10-Q, S-1, 8-K, or equivalent filing reviewed.
- Business model summarized in plain English.
- Revenue trend and gross margin trend checked.
- Operating losses and free cash flow trend checked.
- Cash, debt, and cash runway estimated.
- Recent dilution, ATM programs, warrants, converts, or shelf registrations checked.
- Sector-specific risks identified.
- Bull case and bear case both written.
- Red-team note completed.
- Invalidation point written before trade consideration.

## Market Quality

- Share price is not automatically disqualifying, but sub-$5 names require extra caution.
- Average dollar volume appears sufficient for entry and exit.
- Float, insider ownership, and lock-up or registration overhang reviewed when relevant.
- Major upcoming catalysts and reporting dates checked.

## Risk Controls

- Account value entered into the risk calculator.
- Risk percentage chosen before position sizing.
- The applicable strategy risk budget is checked: tactical ordinary/event
  planned loss at most 0.5%/0.25%, combined tactical planned loss at most 2%,
  and initial tactical exposure at most 5% per name. A sourced growth plan
  uses its stated downside and current allocation contract; it does not
  inherit a historical generic one-trade percentage.
- Entry price and stop price defined.
- Target price, holding period plan, and exit rule defined.
- Company-specific desired size and rationale are recorded in the maintained
  plan; whole shares, broad-core floor, aggregate stock ceiling and actual
  funds are checked. No removed fixed name cap or size tier is reintroduced.
- Trade size fits a cash account.
- Planned order type is limit order only.
- Current strategy-specific loss limits and reassessment dates checked;
  archived generic monthly/weekly examples are not active risk settings.
- No margin, options, shorting, live order automation, or brokerage API use.
- No averaging down unless a separate written thesis update has manual approval.

## Approval

- Paper trade: research memo complete and checklist saved.
- Real trade: research memo complete, red-team note complete, risk calculation saved, checklist saved, and human approval documented outside this repo.
