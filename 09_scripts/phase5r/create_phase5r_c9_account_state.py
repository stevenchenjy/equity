from __future__ import annotations

from pathlib import Path

from phase5r_c9_common import (
    ACCOUNT_STATE,
    C9_INHIBIT,
    CURRENT_POSITIONS,
    append_run_log,
    load_account_state,
    load_active_inhibit,
)


def create_if_missing() -> str:
    if ACCOUNT_STATE.exists():
        return "validated_existing"
    raise FileNotFoundError(
        "current_account_state.local.json is required; copy the template and "
        "enter manually confirmed cash/account fields instead of inventing a total"
    )


def main() -> None:
    load_active_inhibit()
    result = create_if_missing()
    state = load_account_state()
    ACCOUNT_STATE.chmod(0o600)
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
        f"reported_account_total={float(state['account_total_value']):.2f}; inhibit_validated=true"
    )


if __name__ == "__main__":
    main()
