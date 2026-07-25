#!/usr/bin/env python3
"""Deterministic, provenance-bound Phase 5R valuation evidence.

The module is deliberately pure and offline.  It performs Decimal arithmetic
over caller-supplied point-in-time observations and scenario assumptions.  It
does not fetch data, infer missing values, call a model, connect to a broker, or
create an executable instruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Any, Mapping


SCHEMA_VERSION = "phase5r_valuation_evidence_v1"


class ValuationEvidenceError(ValueError):
    """Raised when supplied evidence is malformed or not point-in-time safe."""


@dataclass(frozen=True)
class _InputSpec:
    unit: str
    evidence_kind: str
    minimum: Decimal | None = None
    strictly_positive: bool = False


INPUT_SPECS: dict[str, _InputSpec] = {
    "share_price": _InputSpec(
        unit="USD_per_share",
        evidence_kind="observation",
        strictly_positive=True,
    ),
    "diluted_shares": _InputSpec(
        unit="shares",
        evidence_kind="observation",
        strictly_positive=True,
    ),
    "cash_and_equivalents": _InputSpec(
        unit="USD",
        evidence_kind="observation",
        minimum=Decimal("0"),
    ),
    "total_debt": _InputSpec(
        unit="USD",
        evidence_kind="observation",
        minimum=Decimal("0"),
    ),
    "revenue_ttm": _InputSpec(
        unit="USD",
        evidence_kind="observation",
        minimum=Decimal("0"),
    ),
    "free_cash_flow_ttm": _InputSpec(
        unit="USD",
        evidence_kind="observation",
    ),
    "prior_diluted_shares": _InputSpec(
        unit="shares",
        evidence_kind="observation",
        strictly_positive=True,
    ),
    "target_price_assumption": _InputSpec(
        unit="USD_per_share",
        evidence_kind="scenario_assumption",
        strictly_positive=True,
    ),
    "downside_price_assumption": _InputSpec(
        unit="USD_per_share",
        evidence_kind="scenario_assumption",
        minimum=Decimal("0"),
    ),
}

CORE_VALUATION_INPUT_IDS = (
    "share_price",
    "diluted_shares",
    "cash_and_equivalents",
    "total_debt",
    "revenue_ttm",
    "free_cash_flow_ttm",
    "prior_diluted_shares",
)
SCENARIO_INPUT_IDS = (
    "target_price_assumption",
    "downside_price_assumption",
)

_INPUT_KEYS = {
    "value",
    "unit",
    "period",
    "available_at_utc",
    "source_ids",
    "evidence_kind",
}


def _parse_decimal(value: Any, *, label: str) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ValuationEvidenceError(
            f"{label} must be a decimal string, integer, or Decimal"
        )
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValuationEvidenceError(f"{label} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise ValuationEvidenceError(f"{label} must be finite")
    return parsed


def _plain_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _rounded(value: Decimal, quantum: str) -> str:
    return format(
        value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP),
        "f",
    )


def _parse_utc(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValuationEvidenceError(f"{label} must be a non-empty UTC timestamp")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise ValuationEvidenceError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValuationEvidenceError(f"{label} must use UTC")
    return parsed.astimezone(timezone.utc)


def _utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_input(
    input_id: str,
    raw: Any,
    *,
    as_of: datetime,
) -> tuple[dict[str, Any], Decimal]:
    spec = INPUT_SPECS[input_id]
    if not isinstance(raw, Mapping):
        raise ValuationEvidenceError(f"{input_id} must be an object")
    unknown_keys = set(raw) - _INPUT_KEYS
    missing_keys = _INPUT_KEYS - set(raw)
    if unknown_keys or missing_keys:
        raise ValuationEvidenceError(
            f"{input_id} keys mismatch; missing={sorted(missing_keys)}, "
            f"unknown={sorted(unknown_keys)}"
        )

    if raw["unit"] != spec.unit:
        raise ValuationEvidenceError(
            f"{input_id} unit must be {spec.unit!r}"
        )
    if raw["evidence_kind"] != spec.evidence_kind:
        raise ValuationEvidenceError(
            f"{input_id} evidence_kind must be {spec.evidence_kind!r}"
        )
    period = raw["period"]
    if not isinstance(period, str) or not period.strip():
        raise ValuationEvidenceError(f"{input_id} period must be non-empty")

    available_at = _parse_utc(
        raw["available_at_utc"],
        label=f"{input_id}.available_at_utc",
    )
    if available_at > as_of:
        raise ValuationEvidenceError(
            f"{input_id} was not available by the valuation as-of timestamp"
        )

    source_ids = raw["source_ids"]
    if (
        not isinstance(source_ids, (list, tuple))
        or not source_ids
        or any(not isinstance(item, str) or not item.strip() for item in source_ids)
    ):
        raise ValuationEvidenceError(
            f"{input_id} source_ids must contain non-empty strings"
        )
    normalized_sources = sorted({item.strip() for item in source_ids})
    if len(normalized_sources) != len(source_ids):
        raise ValuationEvidenceError(f"{input_id} source_ids must be unique")

    parsed_value = _parse_decimal(raw["value"], label=f"{input_id}.value")
    if spec.strictly_positive and parsed_value <= 0:
        raise ValuationEvidenceError(f"{input_id} must be greater than zero")
    if spec.minimum is not None and parsed_value < spec.minimum:
        raise ValuationEvidenceError(
            f"{input_id} must be at least {_plain_decimal(spec.minimum)}"
        )

    receipt = {
        "input_id": input_id,
        "value": _plain_decimal(parsed_value),
        "unit": spec.unit,
        "period": period.strip(),
        "available_at_utc": _utc_string(available_at),
        "source_ids": normalized_sources,
        "evidence_kind": spec.evidence_kind,
    }
    return receipt, parsed_value


def _calculation_receipt(
    *,
    calculation_id: str,
    formula: str,
    value: Decimal,
    unit: str,
    input_ids: tuple[str, ...],
    input_receipts: Mapping[str, Mapping[str, Any]],
    quantum: str,
) -> dict[str, Any]:
    source_ids = sorted(
        {
            source_id
            for input_id in input_ids
            for source_id in input_receipts[input_id]["source_ids"]
        }
    )
    return {
        "calculation_id": calculation_id,
        "formula": formula,
        "value": _rounded(value, quantum),
        "unit": unit,
        "input_ids": list(input_ids),
        "source_ids": source_ids,
        "input_periods": {
            input_id: input_receipts[input_id]["period"] for input_id in input_ids
        },
    }


def _payload_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_valuation_evidence_v1(
    *,
    ticker: str,
    as_of_utc: str,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic valuation receipt from only supplied evidence.

    Missing canonical inputs are reported as insufficiency.  Present-but-invalid
    inputs raise ``ValuationEvidenceError`` so malformed evidence cannot silently
    become an advisory-grade valuation.
    """

    if not isinstance(ticker, str) or not ticker.strip():
        raise ValuationEvidenceError("ticker must be non-empty")
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker.replace(".", "").replace("-", "").isalnum():
        raise ValuationEvidenceError("ticker contains unsupported characters")
    as_of = _parse_utc(as_of_utc, label="as_of_utc")
    if not isinstance(inputs, Mapping):
        raise ValuationEvidenceError("inputs must be an object")
    unknown_input_ids = set(inputs) - set(INPUT_SPECS)
    if unknown_input_ids:
        raise ValuationEvidenceError(
            f"unknown valuation input ids: {sorted(unknown_input_ids)}"
        )

    receipts: dict[str, dict[str, Any]] = {}
    values: dict[str, Decimal] = {}
    for input_id in INPUT_SPECS:
        if input_id not in inputs:
            continue
        receipt, parsed_value = _normalize_input(
            input_id,
            inputs[input_id],
            as_of=as_of,
        )
        receipts[input_id] = receipt
        values[input_id] = parsed_value

    calculations: list[dict[str, Any]] = []
    calculation_ids: set[str] = set()

    def add_calculation(
        calculation_id: str,
        formula: str,
        value: Decimal,
        unit: str,
        input_ids: tuple[str, ...],
        quantum: str,
    ) -> None:
        calculations.append(
            _calculation_receipt(
                calculation_id=calculation_id,
                formula=formula,
                value=value,
                unit=unit,
                input_ids=input_ids,
                input_receipts=receipts,
                quantum=quantum,
            )
        )
        calculation_ids.add(calculation_id)

    if {"share_price", "diluted_shares"} <= values.keys():
        market_cap = values["share_price"] * values["diluted_shares"]
        add_calculation(
            "market_cap",
            "share_price * diluted_shares",
            market_cap,
            "USD",
            ("share_price", "diluted_shares"),
            "0.01",
        )
    else:
        market_cap = None

    if {"cash_and_equivalents", "total_debt"} <= values.keys():
        net_debt = values["total_debt"] - values["cash_and_equivalents"]
        add_calculation(
            "net_debt",
            "total_debt - cash_and_equivalents",
            net_debt,
            "USD",
            ("total_debt", "cash_and_equivalents"),
            "0.01",
        )
    else:
        net_debt = None

    if market_cap is not None and net_debt is not None:
        enterprise_value = market_cap + net_debt
        add_calculation(
            "enterprise_value",
            "market_cap + total_debt - cash_and_equivalents",
            enterprise_value,
            "USD",
            (
                "share_price",
                "diluted_shares",
                "total_debt",
                "cash_and_equivalents",
            ),
            "0.01",
        )
    else:
        enterprise_value = None

    revenue = values.get("revenue_ttm")
    free_cash_flow = values.get("free_cash_flow_ttm")
    if enterprise_value is not None and revenue is not None and revenue > 0:
        add_calculation(
            "ev_to_revenue",
            "enterprise_value / revenue_ttm",
            enterprise_value / revenue,
            "multiple",
            (
                "share_price",
                "diluted_shares",
                "total_debt",
                "cash_and_equivalents",
                "revenue_ttm",
            ),
            "0.0001",
        )
    if revenue is not None and revenue > 0 and free_cash_flow is not None:
        add_calculation(
            "free_cash_flow_margin_pct",
            "free_cash_flow_ttm / revenue_ttm * 100",
            free_cash_flow / revenue * Decimal("100"),
            "percent",
            ("free_cash_flow_ttm", "revenue_ttm"),
            "0.01",
        )
    if market_cap is not None and market_cap > 0 and free_cash_flow is not None:
        add_calculation(
            "free_cash_flow_yield_pct",
            "free_cash_flow_ttm / market_cap * 100",
            free_cash_flow / market_cap * Decimal("100"),
            "percent",
            (
                "free_cash_flow_ttm",
                "share_price",
                "diluted_shares",
            ),
            "0.01",
        )
    if (
        enterprise_value is not None
        and free_cash_flow is not None
        and free_cash_flow > 0
    ):
        add_calculation(
            "ev_to_free_cash_flow",
            "enterprise_value / free_cash_flow_ttm",
            enterprise_value / free_cash_flow,
            "multiple",
            (
                "share_price",
                "diluted_shares",
                "total_debt",
                "cash_and_equivalents",
                "free_cash_flow_ttm",
            ),
            "0.0001",
        )

    if {"diluted_shares", "prior_diluted_shares"} <= values.keys():
        add_calculation(
            "dilution_pct",
            "(diluted_shares / prior_diluted_shares - 1) * 100",
            (
                values["diluted_shares"] / values["prior_diluted_shares"]
                - Decimal("1")
            )
            * Decimal("100"),
            "percent",
            ("diluted_shares", "prior_diluted_shares"),
            "0.01",
        )

    share_price = values.get("share_price")
    target_price = values.get("target_price_assumption")
    downside_price = values.get("downside_price_assumption")
    if share_price is not None and target_price is not None:
        add_calculation(
            "target_upside_pct",
            "(target_price_assumption / share_price - 1) * 100",
            (target_price / share_price - Decimal("1")) * Decimal("100"),
            "percent",
            ("target_price_assumption", "share_price"),
            "0.01",
        )
    if share_price is not None and downside_price is not None:
        add_calculation(
            "downside_change_pct",
            "(downside_price_assumption / share_price - 1) * 100",
            (downside_price / share_price - Decimal("1")) * Decimal("100"),
            "percent",
            ("downside_price_assumption", "share_price"),
            "0.01",
        )
    if (
        share_price is not None
        and target_price is not None
        and downside_price is not None
        and target_price > share_price
        and downside_price < share_price
    ):
        reward = target_price / share_price - Decimal("1")
        risk = Decimal("1") - downside_price / share_price
        add_calculation(
            "reward_to_risk",
            "target_upside_fraction / downside_loss_fraction",
            reward / risk,
            "ratio",
            (
                "target_price_assumption",
                "downside_price_assumption",
                "share_price",
            ),
            "0.0001",
        )

    missing_core = [
        input_id for input_id in CORE_VALUATION_INPUT_IDS if input_id not in values
    ]
    missing_scenario = [
        input_id for input_id in SCENARIO_INPUT_IDS if input_id not in values
    ]
    blocked_reasons: list[str] = []
    if missing_core:
        blocked_reasons.append("missing_core_inputs:" + ",".join(missing_core))
    if missing_scenario:
        blocked_reasons.append(
            "missing_scenario_inputs:" + ",".join(missing_scenario)
        )
    if enterprise_value is not None and enterprise_value <= 0:
        blocked_reasons.append("enterprise_value_not_positive")
    if revenue is not None and revenue <= 0:
        blocked_reasons.append("revenue_ttm_not_positive")
    if (
        share_price is not None
        and target_price is not None
        and target_price <= share_price
    ):
        blocked_reasons.append("target_not_above_share_price")
    if (
        share_price is not None
        and downside_price is not None
        and downside_price >= share_price
    ):
        blocked_reasons.append("downside_not_below_share_price")

    required_valuation_calculations = {
        "market_cap",
        "net_debt",
        "enterprise_value",
        "ev_to_revenue",
        "free_cash_flow_margin_pct",
        "free_cash_flow_yield_pct",
        "dilution_pct",
    }
    valuation_sufficient = (
        not missing_core
        and enterprise_value is not None
        and enterprise_value > 0
        and revenue is not None
        and revenue > 0
        and required_valuation_calculations <= calculation_ids
    )
    scenario_sufficient = (
        not missing_scenario
        and share_price is not None
        and target_price is not None
        and target_price > share_price
        and downside_price is not None
        and downside_price < share_price
        and "reward_to_risk" in calculation_ids
    )
    decision_sufficient = valuation_sufficient and scenario_sufficient

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ticker": normalized_ticker,
        "as_of_utc": _utc_string(as_of),
        "input_receipts": [receipts[input_id] for input_id in INPUT_SPECS if input_id in receipts],
        "calculations": calculations,
        "sufficiency": {
            "valuation_sufficient": valuation_sufficient,
            "scenario_sufficient": scenario_sufficient,
            "decision_sufficient": decision_sufficient,
            "missing_core_input_ids": missing_core,
            "missing_scenario_input_ids": missing_scenario,
            "blocked_reasons": blocked_reasons,
        },
        "guardrails": {
            "missing_inputs_may_be_invented": False,
            "scenario_prices_are_observations": False,
            "action_grade_valuation_permitted": decision_sufficient,
            "insufficient_result": "watch_or_abstain",
            "broker_or_execution_capability": False,
        },
    }
    payload["receipt_sha256"] = _payload_digest(payload)
    return payload


def validate_valuation_evidence_v1(value: Any) -> dict[str, Any]:
    """Recompute and validate an entire valuation receipt."""

    if not isinstance(value, dict):
        raise ValuationEvidenceError("valuation evidence must be an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValuationEvidenceError("unsupported valuation evidence schema")
    input_receipts = value.get("input_receipts")
    if not isinstance(input_receipts, list):
        raise ValuationEvidenceError("input_receipts must be a list")
    reconstructed: dict[str, dict[str, Any]] = {}
    for receipt in input_receipts:
        if not isinstance(receipt, dict) or not isinstance(
            receipt.get("input_id"), str
        ):
            raise ValuationEvidenceError("invalid input receipt")
        input_id = receipt["input_id"]
        if input_id in reconstructed:
            raise ValuationEvidenceError("duplicate input receipt")
        reconstructed[input_id] = {
            key: receipt.get(key) for key in _INPUT_KEYS
        }
    expected = build_valuation_evidence_v1(
        ticker=value.get("ticker"),
        as_of_utc=value.get("as_of_utc"),
        inputs=reconstructed,
    )
    if value != expected:
        raise ValuationEvidenceError(
            "valuation evidence does not match deterministic recomputation"
        )
    return value


def valuation_packet_calculations(value: Any) -> list[dict[str, Any]]:
    """Project a validated receipt into ticker-qualified packet calculations.

    The receipt keeps compact, calculation-local identifiers so it can be
    recomputed independently.  Evidence packets can contain multiple issuers,
    so their public calculation identifiers must also bind the ticker.
    """

    receipt = validate_valuation_evidence_v1(value)
    ticker = receipt["ticker"]
    inputs = {
        row["input_id"]: row for row in receipt["input_receipts"]
    }
    projected: list[dict[str, Any]] = []
    for calculation in receipt["calculations"]:
        input_rows = [inputs[input_id] for input_id in calculation["input_ids"]]
        projected.append(
            {
                "calculation_id": (
                    f"valuation:{ticker}:{calculation['calculation_id']}"
                ),
                "ticker": ticker,
                "metric": f"valuation_{calculation['calculation_id']}",
                "value": calculation["value"],
                "recomputed_value": calculation["value"],
                "unit": calculation["unit"],
                "period": json.dumps(
                    calculation["input_periods"],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "formula": calculation["formula"],
                "source_ids": calculation["source_ids"],
                "inputs": [
                    {
                        "name": input_row["input_id"],
                        "value": input_row["value"],
                        "unit": input_row["unit"],
                        "period": input_row["period"],
                    }
                    for input_row in input_rows
                ],
                "reconciled": True,
                "valuation_receipt_sha256": receipt["receipt_sha256"],
            }
        )
    return projected


__all__ = [
    "CORE_VALUATION_INPUT_IDS",
    "INPUT_SPECS",
    "SCENARIO_INPUT_IDS",
    "SCHEMA_VERSION",
    "ValuationEvidenceError",
    "build_valuation_evidence_v1",
    "validate_valuation_evidence_v1",
    "valuation_packet_calculations",
]
