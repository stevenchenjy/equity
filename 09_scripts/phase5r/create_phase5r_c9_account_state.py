from __future__ import annotations

import json
import os
from pathlib import Path

from phase5r_c9_common import (
    ACCOUNT_STATE,
    C9_INHIBIT,
    CURRENT_POSITIONS,
    append_run_log,
    load_account_state,
    load_active_inhibit,
    timestamp,
)


INITIAL_STATE = {
    "account_total_value": 2500.0,
    "prior_account_value": 1000.0,
    "new_external_cash": 1500.0,
    "cash_available": 2026.58,
    "cash_reserved": 500.0,
    "investment_horizon_years": 5,
    "cash_needed_within_three_years": "no",
    "core_allocation_target_pct": 60.0,
    "active_stock_target_pct": 20.0,
    "active_stock_hard_cap_pct": 30.0,
    "cash_target_pct": 20.0,
    "single_stock_default_cap_pct": 6.0,
    "single_stock_hard_cap_pct": 8.0,
    "last_updated": "",
}


def create_if_missing() -> str:
    if ACCOUNT_STATE.exists():
        return "validated_existing"
    payload = dict(INITIAL_STATE)
    payload["last_updated"] = timestamp()
    ACCOUNT_STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ACCOUNT_STATE.with_name(f"{ACCOUNT_STATE.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, ACCOUNT_STATE)
    return "created"


def main() -> None:
    load_active_inhibit()
    result = create_if_missing()
    state = load_account_state()
    ACCOUNT_STATE.chmod(0o600)
    if result == "created" and (
        float(state["account_total_value"]) != 2500.0 or float(state["new_external_cash"]) != 1500.0
    ):
        raise ValueError("initial human-confirmed C9 account totals do not match")
    append_run_log(
        Path(__file__).name,
        "create_or_validate_account_state",
        "complete",
        [CURRENT_POSITIONS, C9_INHIBIT],
        [ACCOUNT_STATE],
        notes=f"result={result}; account_state_local_only=yes; credentials_read=no",
    )
    print(
        f"Phase 5R-C9 account state {result}; "
        f"account_total={float(state['account_total_value']):.2f}; inhibit=active"
    )


if __name__ == "__main__":
    main()
