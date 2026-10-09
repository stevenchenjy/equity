# Account record authority

The owner authorized local-record planning on October 9, 2026: account-record
age, a historical inventory completeness marker and a ledger-estimate cash label
must not stop conditional manual buy/sell recommendations. This supersedes the
verified-current-snapshot requirement for research planning when the private
approval is active. It does not change the $4,000 planning basis, zero mandatory
reserve, allocation targets, strategy budgets or human-only execution.

`05_risk_and_positions/account_record_policy.local.json` is the durable private
approval. `account_authority.load_authority` validates its schema, instruction,
time and content digest. A missing approval retains the verified-snapshot mode;
a malformed approval fails explicitly. The policy enters workflow and final
capital input bindings, so changing it requires full recomposition. Keep the
previous approval and the original request in private history.

In `owner_local_ledger` mode, current local cash, shares and order records govern
conditional calculations. Preserve the recorded dates, original `complete`,
`cash_confirmed`, settlement flags and source bytes. Never turn a local inventory
into a claim of verified current broker inventory. Execution checks appear in the
complete conditional draft and in separate background information: the owner
checks executable funds and unrecorded changes when manually submitting an order.
The system does not request a new broker session simply because the record aged.

Known buy orders still reserve their bounded remaining cash; sell orders reserve
shares. An expired unresolved bounded order stays on its ticker, with its funds or
shares reserved; its expiry never proves a fill/cancellation or renews the ticket.
Malformed/unbounded commitments, inconsistent holdings, invalid cash arithmetic,
conflicting execution feedback and contradictory order facts remain substantive
integrity failures. They must not be concealed as a display-only change.

Local tactical open risk may be derived as zero only from a valid local inventory
with exclusively broad-core holdings (or no holdings) and no nonterminal orders.
An active stock whose tactical risk cannot be bounded retains its strategy risk
dependency. Never label the derived local risk as broker-confirmed. Existing
company evidence, valuation, entry, expiry, aggregate allocation and tactical loss
requirements still decide whether a positive draft exists. A failed investment
case remains a zero-share decision after the account metadata gate is removed.

Prior-email assumed-fill scenarios stay separate from account truth. A known
unreconciled earlier actionable instruction still requires its execution outcome;
this local-record policy cannot manufacture that outcome or finance duplicate
orders from a hypothetical fill. Frozen momentum cohorts keep their original
implementation, input authority and version identity; this is not experiment
promotion or a retune of historical results.

The composer and dashboard share `workflow_inputs.WORKFLOW_INPUTS`. Bound private approval inputs must be accepted by both paths; arbitrary or changed publication inputs remain rejected. Verify the rendered production page after every input-contract migration.
