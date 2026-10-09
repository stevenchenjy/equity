"""Private publication inputs shared by the composer and read-only dashboard.

Keep the inventory in one place: new approved inputs must neither be omitted
from publication fingerprints nor rejected by a separate display allowlist.
"""
from account_authority import POLICY_REL

WORKFLOW_INPUTS = {
    POLICY_REL,
    "05_risk_and_positions/investment_plans.local.json",
    "05_risk_and_positions/current_positions.local.csv",
    "05_risk_and_positions/current_open_orders.local.json",
    "05_risk_and_positions/current_account_state.local.json",
    "04_research/company_research/thesis_dossiers.local.json",
    "04_research/company_research/issuer_news_review_queue.local.jsonl",
    "06_execution_records/dashboard_feedback_pending.local.json",
}
