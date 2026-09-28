"""Retain analyst-admitted research independently from generated valuations.

The maintained bundle is never rewritten by a refresh. Every observed version
is preserved verbatim; failed bindings remain visible but cannot enter the
current evidence packet. Generated canonical scenarios never consume this layer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from valuation_input_bundle import (
    ValuationInputBundleError, _reject_duplicate_pairs, seal_bundle,
    validate_and_materialize_bundle, validate_bundle_envelope,
)


def generated_record(record: Any) -> bool:
    """Recognize only the generator's complete three-source ownership contract."""
    if not isinstance(record, dict):
        return False
    ticker = record.get("ticker")
    sources = record.get("sources")
    if not isinstance(sources, list) or len(sources) != 3:
        return False
    contracts = {
        "public_market_valuation_observation": (
            f"valuation-market:{ticker}:", "03_source_data/equity_research/market_data_snapshot.csv"),
        "sec_valuation_fact": (
            f"valuation-sec:{ticker}:", "03_source_data/equity_research/daily_fundamentals.csv"),
        "deterministic_valuation_policy": (
            f"valuation-policy:{ticker}:", "01_policies/valuation_scenario_policy.json"),
    }
    if not all(isinstance(item, dict) and isinstance(item.get("source_type"), str)
               and item["source_type"] in contracts for item in sources):
        return False
    if {item["source_type"] for item in sources} != set(contracts):
        return False
    return all(isinstance(item, dict)
               and str(item.get("source_id", "")).startswith(contracts[item["source_type"]][0])
               and item.get("relative_path") == contracts[item["source_type"]][1]
               for item in sources)


def _owned_directory(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("valuation research directory invalid")


def _read_snapshot(path: Path) -> bytes:
    _owned_directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1):
            raise ValueError("valuation research source file invalid")
        data = stream.read()
        after = os.fstat(stream.fileno())
        if (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("valuation research source changed during snapshot")
    return data


def _publish_private(target: Path, data: bytes) -> None:
    """Publish fully synced bytes without overwriting an existing original."""
    _owned_directory(target.parent)
    if target.exists() or target.is_symlink():
        if _read_snapshot(target) != data:
            raise ValueError("valuation research archive integrity mismatch")
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError:
                # Validate only after removing our temporary hard link below.
                pass
        finally:
            os.unlink(temporary)
        if _read_snapshot(target) != data:
            raise ValueError("valuation research archive integrity mismatch")
    for directory in (target.parent, target.parent.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _archive_snapshot(data: bytes, history: Path) -> str:
    digest = hashlib.sha256(data).hexdigest()
    _owned_directory(history.parent)
    history.mkdir(mode=0o700, parents=True, exist_ok=True)
    _owned_directory(history)
    history.chmod(0o700)
    _publish_private(history / f"{digest}.json", data)
    return digest


def archive_bytes(path: Path, history: Path) -> str:
    """Content-addressed exact originals; an existing archive is never replaced."""
    return _archive_snapshot(_read_snapshot(path), history)


def _parse_snapshot(data: bytes) -> dict[str, Any]:
    try:
        raw = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(
                             ValuationInputBundleError(f"non-finite JSON constant is forbidden: {value}")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValuationInputBundleError("cannot parse retained valuation bundle") from exc
    if not isinstance(raw, dict):
        raise ValuationInputBundleError("bundle must be an object")
    return raw


def compose_research_inputs(
    generated: dict[str, Any], *, project_root: Path,
    derived_path: Path, fundamentals: dict[str, Any], market: dict[str, Any],
    active_tickers: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revalidate manual research without replacing generated observations."""
    data_root = project_root / "04_data/equity_research"
    maintained = data_root / "valuation_research_inputs.local.json"
    history = data_root / "valuation_input_history.local"
    as_of = generated["prepared_at_utc"]
    status: dict[str, Any] = {
        "schema_version": "valuation_research_retention_v1", "generated_at_utc": as_of,
        "status": "absent", "records": [], "active_records": 0,
        "maintained_path": str(maintained.relative_to(project_root)),
        "history_path": str(history.relative_to(project_root)),
        "boundaries": generated["boundaries"],
    }
    # Compatibility for previously admitted records in the derived bundle.
    # Keep exact original bytes, including its digest and preparation time.
    if derived_path.exists() or derived_path.is_symlink():
        prior_bytes = _read_snapshot(derived_path)
        try:
            prior = _parse_snapshot(prior_bytes)
            manual_present = any(not generated_record(record) for record in prior.get("records", []))
        except (ValuationInputBundleError, TypeError):
            manual_present = True
        if manual_present:
            status["previous_derived_archive_sha256"] = _archive_snapshot(prior_bytes, history)
            if not (maintained.exists() or maintained.is_symlink()):
                maintained.parent.mkdir(parents=True, exist_ok=True)
                _publish_private(maintained, prior_bytes)
                status["legacy_migrated"] = True
    if not (maintained.exists() or maintained.is_symlink()):
        return generated, status
    maintained_bytes = _read_snapshot(maintained)
    status["maintained_sha256"] = _archive_snapshot(maintained_bytes, history)
    try:
        raw = _parse_snapshot(maintained_bytes)
        validate_bundle_envelope(raw, packet_as_of=as_of)
    except ValuationInputBundleError as exc:
        status.update(status="unverified", reason=str(exc))
        return generated, status

    generated_tickers = {item["ticker"] for item in generated["records"]}
    manual_records = [item for item in raw["records"] if not generated_record(item)]
    counts: dict[str, int] = {}
    for record in manual_records:
        ticker = str(record.get("ticker", "")) if isinstance(record, dict) else ""
        counts[ticker] = counts.get(ticker, 0) + 1
    accepted = []
    source_ids = {source["source_id"] for item in generated["records"] for source in item["sources"]}
    for record in manual_records:
        ticker = str(record.get("ticker", "")) if isinstance(record, dict) else ""
        result = {"ticker": ticker, "status": "unverified", "reason": ""}
        status["records"].append(result)
        try:
            if counts[ticker] != 1:
                raise ValuationInputBundleError("duplicate maintained ticker")
            # The original complete envelope was checked before this scoped
            # seal; no invalid top-level digest is repaired by decomposition.
            single = seal_bundle({**raw, "records": [record]})
            validate_and_materialize_bundle(single, packet_as_of=as_of,
                                            active_tickers={ticker}, project_root=project_root)
            if ticker not in active_tickers:
                result.update(status="historical_outside_current_coverage", reason="ticker_not_in_current_baseline")
                continue
            for field, item in record["inputs"].items():
                periods = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", item["period"]))
                if field in {"total_debt", "cash_and_equivalents", "diluted_shares",
                             "revenue_ttm", "free_cash_flow_ttm"}:
                    if not fundamentals.get(ticker, {}).get("latest_period_end") in periods:
                        raise ValuationInputBundleError(f"current_financial_period_mismatch:{field}")
                if field == "share_price" and not market.get(ticker, {}).get("market_session_date") in periods:
                    raise ValuationInputBundleError("current_market_session_mismatch:share_price")
            if ticker in generated_tickers:
                result.update(status="historical_generated_record_precedence",
                              reason="current_generated_ticker_record_owns_composed_inputs; manual_record_retained")
                continue
            record_ids = {source["source_id"] for source in record["sources"]}
            if source_ids & record_ids:
                raise ValuationInputBundleError("source identity conflicts with current composed record")
            accepted.append(record)
            source_ids.update(record_ids)
            result.update(status="active_research_only", reason="current_sources_and_period_validated; canonical_effect=false")
        except (ValuationInputBundleError, TypeError, KeyError) as exc:
            result["reason"] = str(exc)
    composed = seal_bundle({**generated, "records": generated["records"] + accepted})
    # Check cross-record/source identity collisions as well as local validation.
    validate_and_materialize_bundle(composed, packet_as_of=as_of,
                                    active_tickers=active_tickers, project_root=project_root)
    status["active_records"] = len(accepted)
    status["status"] = "unverified" if any(item["status"] == "unverified" for item in status["records"]) else "verified"
    return composed, status
