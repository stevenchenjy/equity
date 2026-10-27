"""Close the exact publication dependency introduced by a verified routine send.

Internal caller contract: the normal runtime and daily-pipeline locks are
already held. This helper never takes them recursively, invokes a sender,
collects evidence, reserves a research slot or changes a full-refresh handoff.
"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from account_access import ACCOUNT_INPUTS, input_version, research_context
from daily_common import ROOT, atomic_write_json, canonical_sha256, latest_published_market_session, now_et
from delivery_assessments import ARCHIVE_REL, _attempt, _archived_receipt_baseline, _pending_delivery
from email_brief import render_email
from short_assessment import ACCOUNT_MARKET, MUTABLE_STORES, STATE_REL as SHORT_STATE_REL
from workflow_inputs import WORKFLOW_INPUTS

SCHEMA = "equity_post_delivery_publication_v1"
LEDGER = "07_automation/email_delivery/daily_delivery_ledger.csv"
ARTIFACTS = ("04_research/company_research/daily_decision.json",
             "07_automation/email_briefs/daily_email_brief.txt",
             "07_automation/email_briefs/daily_email_brief.html")
BASE = ARCHIVE_REL / "post_delivery_publication"
STATE = BASE / "current.json"
MAX_SECONDS = 180
MAX_CHILD_SECONDS = 75
STEP_NAMES = ("daily_decision", "workflow_evaluation", "capital_allocation_validation",
              "evidence_packet", "current_status")


def _read(root: Path, relative: str | Path) -> bytes:
    relative = Path(relative)
    path = root / relative
    if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
            or not path.resolve().is_relative_to(root.resolve()) or not path.is_file()):
        raise ValueError("post_delivery_source_unsafe_or_missing")
    return path.read_bytes()


def _hashes(root: Path, paths) -> dict:
    return {str(path): hashlib.sha256(_read(root, path)).hexdigest()
            if (root / path).exists() else None for path in sorted(set(paths))}


def _ledger_rows(raw: bytes):
    lines = raw.decode("utf-8").splitlines(keepends=True)
    ends, total = [], 0
    for line in lines:
        total += len(line.encode("utf-8")); ends.append(total)
    reader = csv.DictReader(lines)
    if not {"timestamp", "cycle_date", "status", "reason", "decision_sha256",
            "brief_text_sha256", "brief_html_sha256"} <= set(reader.fieldnames or []):
        raise ValueError("post_delivery_ledger_schema_invalid")
    rows, boundaries = [], [ends[reader.line_num - 1]]
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("post_delivery_ledger_row_invalid")
        rows.append(row); boundaries.append(ends[reader.line_num - 1])
    return rows, boundaries


def _state(root: Path) -> dict:
    if not (root / STATE).exists():
        return {}
    value = json.loads(_read(root, STATE))
    if (value.get("schema_version") != SCHEMA or value.get("receipt_sha256") !=
            canonical_sha256({k: v for k, v in value.items() if k != "receipt_sha256"})):
        raise ValueError("post_delivery_pending_receipt_invalid")
    return value


def _store(root: Path, receipt: dict) -> dict:
    value = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    value["receipt_sha256"] = canonical_sha256(value)
    archive = root / BASE / (value["receipt_sha256"] + ".json")
    if not archive.parent.resolve().is_relative_to(root.resolve()) or archive.parent.is_symlink():
        raise ValueError("post_delivery_receipt_path_unsafe")
    if archive.exists():
        if json.loads(_read(root, archive.relative_to(root))) != value:
            raise ValueError("post_delivery_receipt_archive_conflict")
    else:
        atomic_write_json(archive, value)
    atomic_write_json(root / STATE, value)
    return value


def _protected(root: Path, archived: dict) -> dict:
    from capital_decision import INPUTS
    contract = archived.get("workflow_integrity", {})
    capital = archived.get("capital_decision", {})
    expected = dict(contract.get("input_hashes", {}))
    if set(expected) != WORKFLOW_INPUTS or set(capital.get("source_bindings", {})) != INPUTS:
        raise ValueError("post_delivery_full_source_bindings_required")
    for path, digest in capital["source_bindings"].items():
        if path in expected and expected[path] != digest:
            raise ValueError("post_delivery_original_bindings_conflict")
        expected[path] = digest
    for path, digest in contract.get("allocation_policy_proof_hashes", {}).items():
        if path in expected and expected[path] != digest:
            raise ValueError("post_delivery_original_bindings_conflict")
        expected[path] = digest
    expected.pop(LEDGER, None)
    if _hashes(root, expected) != expected:
        raise ValueError("post_delivery_unrelated_source_change_requires_full_refresh")
    if archived.get("account_input_version") != input_version(root):
        raise ValueError("post_delivery_account_changed_requires_full_refresh")
    preservation = (*expected, *ACCOUNT_INPUTS, *ACCOUNT_MARKET, *MUTABLE_STORES,
                    "00_project_control/run_logs/daily_refresh_state.local.json")
    return {"source_hashes": _hashes(root, preservation),
            "account_input_version": archived["account_input_version"]}


def _candidate(root: Path, current: datetime, pending: dict):
    ledger = _read(root, LEDGER)
    rows, boundaries = _ledger_rows(ledger)
    if _pending_delivery(rows, current) is not None:
        return None, "unresolved_or_unknown_delivery"
    if len(rows) < 2:
        return None, "no_verified_new_delivery_pair"
    claim, sent = rows[-2:]
    if claim.get("status") != "send_claimed" or sent.get("status") != "sent":
        return None, "no_verified_new_delivery_pair"
    if (claim.get("message_count") != "0" or sent.get("message_count") != "1"
            or sent.get("email_attempted") != "yes" or sent.get("email_sent") != "yes"
            or "pre_smtp_durable_claim" not in claim["reason"].split(";")
            or "smtp_send_completed" not in sent["reason"].split(";")):
        return None, "smtp_completion_not_verified"
    if _attempt(claim) is None or _attempt(claim) != _attempt(sent):
        return None, "no_verified_new_delivery_pair"
    for row in (claim, sent):
        mode = [x for x in row["reason"].split(";") if x.startswith("delivery_mode=")]
        purpose = [x for x in row["reason"].split(";") if x.startswith("delivery_purpose_v1=")]
        if (mode not in [["delivery_mode=scheduled_brief"], ["delivery_mode=intraday_alert"]]
                or len(purpose) != 1):
            return None, "not_a_routine_delivery_pair"
    started, ended = (datetime.fromisoformat(row["timestamp"]) for row in (claim, sent))
    if (any(stamp.tzinfo is None for stamp in (current, started, ended))
            or not started <= ended <= current or sent["cycle_date"] != current.date().isoformat()
            or claim["cycle_date"] != sent["cycle_date"]):
        return None, "delivery_not_from_current_cycle"
    archived_raw = _read(root, ARCHIVE_REL / (sent["decision_sha256"] + ".json"))
    if hashlib.sha256(archived_raw).hexdigest() != sent["decision_sha256"]:
        raise ValueError("post_delivery_archive_hash_mismatch")
    archived = json.loads(archived_raw)
    if archived.get("schema_version") != "phase5r_daily_decision_v1":
        return None, "status_only_or_noncanonical_delivery_requires_full_refresh"
    if _archived_receipt_baseline(sent, root=root).get("status") != "verified":
        raise ValueError("post_delivery_archive_unverified")
    _, text, html = render_email(archived)
    for key, suffix, body in (("brief_text_sha256", ".txt", text), ("brief_html_sha256", ".html", html)):
        raw = _read(root, ARCHIVE_REL / (sent[key] + suffix))
        if hashlib.sha256(raw).hexdigest() != sent[key] or raw != body.encode("utf-8"):
            raise ValueError("post_delivery_exact_archived_render_required")
    canonical_digest = sent["decision_sha256"]
    if "delivery_assessment" in archived:
        # A priority-only envelope is not proof that omitted canonical orders
        # were delivered. It references the exact source publication instead.
        from delivery_assessments import validate_envelope
        validate_envelope(archived)
        canonical_digest = archived["delivery_assessment"]["canonical_decision_sha256"]
        canonical_raw = _read(root, ARCHIVE_REL / (canonical_digest + ".json"))
        if hashlib.sha256(canonical_raw).hexdigest() != canonical_digest:
            raise ValueError("post_delivery_canonical_archive_hash_mismatch")
        archived = json.loads(canonical_raw)
    if archived.get("market_gate", {}).get("expected_market_session") != latest_published_market_session(current).isoformat():
        raise ValueError("post_delivery_required_market_session_changed")
    original_hash = archived["capital_decision"]["source_bindings"].get(LEDGER)
    # Exactly the appended claim/completion may differ. CSV physical offsets
    # preserve original quoting/newlines; no ledger normalization is admitted.
    prefix = ledger[:boundaries[-3]] if len(rows) > 2 else ledger[:boundaries[0]]
    if (original_hash is None and len(rows) != 2) or (original_hash is not None
            and hashlib.sha256(prefix).hexdigest() != original_hash):
        raise ValueError("post_delivery_exact_ledger_prefix_required")
    identity = canonical_sha256(sent)
    from market_admission import current_admission
    market_admission = current_admission(root, current=current)
    if market_admission is None:
        raise ValueError("post_delivery_current_market_admission_required")
    protected = _protected(root, archived)
    current_raw = _read(root, ARTIFACTS[0])
    retry = (pending.get("delivery_receipt_sha256") == identity
             and pending.get("ledger_sha256") == hashlib.sha256(ledger).hexdigest()
             and pending.get("outcome") in {"running", "failed", "deferred"})
    if retry and pending.get("protected_before") != protected:
        raise ValueError("post_delivery_pending_inputs_changed_requires_full_refresh")
    if hashlib.sha256(current_raw).hexdigest() != canonical_digest and not retry:
        raise ValueError("post_delivery_current_publication_not_exact_sent_archive")
    if not retry:
        _, canonical_text, canonical_html = render_email(archived)
        if (_read(root, ARTIFACTS[1]) != canonical_text.encode("utf-8")
                or _read(root, ARTIFACTS[2]) != canonical_html.encode("utf-8")):
            raise ValueError("post_delivery_current_artifacts_not_exact_sent_publication")
    return {"delivery_receipt": sent, "delivery_claim": claim, "delivery_receipt_sha256": identity,
            "ledger_sha256": hashlib.sha256(ledger).hexdigest(), "protected_before": protected,
            "market_admission": market_admission, "archived_decision": archived}, None


def _full_handoff(root: Path, current: datetime) -> dict:
    from run_daily_refresh import STEP_SPECS, ADVISORY_STEPS
    full = json.loads(_read(root, "00_project_control/run_logs/daily_refresh_state.local.json"))
    if (full.get("outcome") != "passed" or full.get("cycle_date") != current.date().isoformat()
            or full.get("expected_market_session") != latest_published_market_session(current).isoformat()
            or [step.get("name") for step in full.get("steps", [])] != [s[0] for s in STEP_SPECS]
            or any(step.get("exit_code") != 0 and step.get("name") not in ADVISORY_STEPS
                   for step in full.get("steps", []))):
        raise ValueError("post_delivery_passing_full_handoff_required")
    return full


def _validate_current(root: Path, current: datetime) -> dict:
    from short_assessment import _validated_publication
    from delivery_followthrough import validate_followthrough
    value = _validated_publication(root, current)
    validate_followthrough(value, root=root, current=current)
    return value


def recover_locked(root: Path, *, clock=now_et, step_runner=None,
                   maximum_seconds: float = MAX_SECONDS, monotonic=time.monotonic) -> dict:
    """Called only inside existing runtime→pipeline ownership; never send."""
    entered = monotonic()
    current = clock()
    root = root.resolve()
    allowance = min(MAX_SECONDS, max(0, maximum_seconds))
    deadline = entered + allowance
    if root.resolve() != ROOT.resolve() and step_runner is None:
        raise ValueError("post_delivery_script_root_mismatch")
    if allowance <= 5:
        return {"outcome": "deferred", "reason": "publication_budget_unavailable",
                "publication_pending": True, "email_attempted": False, "alert_required": False}
    try:
        decision = json.loads(_read(root, ARTIFACTS[0]))
        bound = decision.get("capital_decision", {}).get("source_bindings", {}).get(LEDGER)
        if not (root / LEDGER).exists() and bound is None:
            return {"outcome": "not_required", "reason": "no_delivery_ledger_yet", "publication_pending": False}
        ledger_hash = hashlib.sha256(_read(root, LEDGER)).hexdigest()
        pending = _state(root)
        retry = pending.get("outcome") in {"running", "failed", "deferred"} and pending.get("ledger_sha256") == ledger_hash
        if bound == ledger_hash and not retry:
            return {"outcome": "not_required", "reason": "ledger_already_bound", "publication_pending": False}
        if bound == ledger_hash and retry:
            full_path = "00_project_control/run_logs/daily_refresh_state.local.json"
            old_full = pending.get("protected_before", {}).get("source_hashes", {}).get(full_path)
            if old_full is not None and _hashes(root, [full_path])[full_path] != old_full:
                # A subsequent real full refresh can supersede a failed helper.
                # Do not replay stale protected inputs over its newer research.
                full = _full_handoff(root, current)
                if datetime.fromisoformat(full["completed_at"]) <= datetime.fromisoformat(pending["started_at"]):
                    raise ValueError("post_delivery_full_handoff_not_newer")
                from market_admission import current_admission
                proof = current_admission(root, current=clock())
                if proof is None:
                    raise ValueError("post_delivery_current_market_admission_required")
                _validate_current(root, clock())
                return _store(root, {"schema_version": SCHEMA, "started_at": current.isoformat(),
                    "completed_at": clock().isoformat(), "outcome": "superseded_by_full_refresh",
                    "superseded_receipt_sha256": pending["receipt_sha256"], "steps": [],
                    "publication_pending": False, "fully_passed_research": False,
                    "resolving_full_refresh_sha256": _hashes(root, [full_path])[full_path],
                    "market_admission": proof, "email_attempted": False, "email_sent": False})
        candidate, reason = _candidate(root, current, pending)
        if candidate is None:
            return {"outcome": "not_applicable", "reason": reason, "publication_pending": True,
                    "alert_required": False, "email_attempted": False}
        _full_handoff(root, current)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _store(root, {"schema_version": SCHEMA, "started_at": current.isoformat(),
            "completed_at": clock().isoformat(), "outcome": "rejected", "reason": str(exc),
            "publication_pending": True, "alert_required": True, "steps": [],
            "fully_passed_research": False, "email_attempted": False, "email_sent": False})
    receipt = {"schema_version": SCHEMA, "started_at": current.isoformat(), "outcome": "running",
        **{k: v for k, v in candidate.items() if k != "archived_decision"}, "steps": [],
        "fully_passed_research": False, "research_slot_reserved": False,
        "email_attempted": False, "email_sent": False, "smtp_completion_preserved": True,
        "publication_pending": True, "alert_required": False}
    from run_daily_refresh_scheduler import short_window_conflict
    from run_daily_refresh import STEP_SPECS, CURRENT_STATUS_SPEC, run_step, MARKET_SNAPSHOT_REUSE
    state = json.loads(_read(root, SHORT_STATE_REL)) if (root / SHORT_STATE_REL).exists() else {}
    claimed = [row for row in state.get("slots", {}).values() if row.get("status") == "claimed"]
    active = bool(claimed)
    checked = clock()
    remaining = max(0, deadline - monotonic())
    conflict = short_window_conflict(checked, maximum_seconds=remaining)
    if active or conflict or remaining <= 5:
        reason = "active_or_protected_short_window" if active or conflict else "publication_budget_unavailable"
        if active and all(datetime.fromisoformat(row["expires_at"]) <= checked for row in claimed):
            reason = "unretired_expired_short_claim_requires_worker_reconciliation"
        receipt.update(outcome="deferred", reason=reason,
                       completed_at=clock().isoformat())
        return _store(root, receipt)
    receipt = _store(root, receipt)
    runner = step_runner or run_step
    specs = {s[0]: s for s in [*STEP_SPECS, CURRENT_STATUS_SPEC]}
    try:
        with research_context(root) as version:
            if version != candidate["protected_before"]["account_input_version"]:
                raise ValueError("post_delivery_account_changed_requires_full_refresh")
            for name in STEP_NAMES:
                remaining = deadline - monotonic() - 5
                if remaining <= 0 or short_window_conflict(clock(), maximum_seconds=remaining):
                    raise ValueError("post_delivery_publication_budget_or_short_window")
                result = runner(name, specs[name][1], False, market_snapshot_mode=MARKET_SNAPSHOT_REUSE,
                                maximum_child_seconds=min(MAX_CHILD_SECONDS, remaining))
                receipt["steps"].append(result); receipt = _store(root, receipt)
                if result.get("exit_code") != 0:
                    raise ValueError("post_delivery_stage_failed:" + name)
                if _protected(root, candidate["archived_decision"]) != candidate["protected_before"]:
                    raise ValueError("post_delivery_protected_input_changed")
                if hashlib.sha256(_read(root, LEDGER)).hexdigest() != candidate["ledger_sha256"]:
                    raise ValueError("post_delivery_ledger_changed_during_closure")
            if deadline - monotonic() <= 0:
                raise ValueError("post_delivery_publication_budget_exhausted")
            _validate_current(root, clock())
            if deadline - monotonic() <= 0:
                raise ValueError("post_delivery_publication_budget_exhausted")
            if input_version(root) != version:
                raise ValueError("post_delivery_account_changed_requires_full_refresh")
            from market_admission import current_admission
            if current_admission(root, current=clock()) != candidate["market_admission"]:
                raise ValueError("post_delivery_market_admission_changed_during_closure")
        receipt.update(outcome="passed", publication_pending=False,
                       protected_after=_protected(root, candidate["archived_decision"]),
                       artifacts=_hashes(root, ARTIFACTS))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        receipt.update(outcome="failed", reason=str(exc), publication_pending=True, alert_required=True)
    receipt["completed_at"] = clock().isoformat()
    return _store(root, receipt)
