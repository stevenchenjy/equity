"""Optional, evidence-bound thinking discipline in the existing thesis dossier.

These are authored conditional analyses, never a score, probability, portfolio
limit or action gate. Retained consensus bytes establish the receipt's integrity;
the analyst remains responsible for source quality and representativeness.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from daily_common import canonical_sha256

SCHEMA = "investment_reasoning_v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("research method: " + message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _fields(value: Any, fields: set[str], label: str) -> None:
    _require(isinstance(value, dict) and set(value) == fields, label + " fields differ")


def _number(value: Any) -> Decimal:
    _require(type(value) in {int, float, str}, "reference price must be a number")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("research method: reference price is invalid") from exc
    _require(parsed.is_finite() and parsed > 0, "reference price must be finite and positive")
    return parsed


def _texts(value: Any, label: str, *, nonempty: bool = False) -> None:
    _require(isinstance(value, list) and all(_text(item) for item in value)
             and (bool(value) or not nonempty), label + " must explicitly list text")


def _refs(value: Any, claims: dict[str, dict], label: str, *, required: bool = False) -> None:
    _texts(value, label, nonempty=required)
    _require(len(set(value)) == len(value) and all(item in claims for item in value),
             label + " references unknown or duplicate claims")


def _method_claim_ids(value: Any) -> set[str]:
    """Collect only explicit claim references; free text never establishes a link."""
    if isinstance(value, dict):
        found = {item for item in value.get("claim_ids", []) if isinstance(item, str)} if isinstance(value.get("claim_ids"), list) else set()
        for item in value.values():
            found.update(_method_claim_ids(item))
        return found
    if isinstance(value, list):
        return set().union(*(_method_claim_ids(item) for item in value)) if value else set()
    return set()


def _method_evidence(record: dict) -> dict:
    ids = _method_claim_ids(record.get("research_method"))
    claims = [row for row in record.get("claims", []) if row.get("claim_id") in ids]
    sources = {citation.get("source_id") for row in claims for citation in row.get("citations", [])}
    return {"claims": sorted(claims, key=lambda row: row["claim_id"]),
            "sources": sorted([row for row in record.get("sources", []) if row.get("source_id") in sources],
                              key=lambda row: row["source_id"])}


def _time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("research method: invalid observation timestamp") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
             "observation timestamp requires timezone")
    return parsed


def _evidence_path(root: Path, relative: Any, prefix: str) -> Path:
    _require(isinstance(relative, str) and relative.startswith(prefix)
             and not Path(relative).is_absolute() and ".." not in Path(relative).parts,
             "evidence path outside approved directory")
    path = (root / relative).resolve()
    _require(path.is_relative_to(root.resolve()), "evidence path escapes root")
    return path


def research_method_template() -> dict[str, Any]:
    """A valid unknown block: prompts never pretend analysis has been completed."""
    return {
        "schema_version": SCHEMA,
        "price_implied_conditions": {
            "status": "unknown", "summary": "尚未明确当前价格成立所需的经营条件。",
            "method": "用已有、已审核的公司估值模型说明条件推导；保留模型哈希、参考价格日期和期限。",
            "conditions": [], "assumptions": [], "claim_ids": [],
            "unknowns": ["哪些增长、现金转化、稀释与期末倍数条件支撑当前价格？"],
            "horizon_years": None, "reference_price": None, "model_reference": None,
        },
        "market_consensus": {
            "status": "unknown", "summary": "尚无已留存且范围清楚的外部预期观察。",
            "sample_scope": "", "claim_ids": [], "observation": None,
            "unknowns": ["市场共识未知；价格反推和公司指引均不能替代外部共识观察。"],
        },
        "differentiated_view": {
            "status": "unknown", "summary": "尚未建立可验证的差异化判断。",
            "comparison_basis": "unknown", "claim_ids": [], "falsifier": "",
            "next_evidence": "找出能区分我们的假设和对照预期的下一条证据。",
            "unknowns": ["相对价格成立条件或已记录共识，我们究竟在哪一点不同，为什么？"],
        },
        "loss_analysis": {
            "status": "unknown", "paths": [], "fragile_assumptions": [],
            "shared_exposures": [],
            "unknowns": ["写出最重要的1至3条永久损失路径、早期信号和脆弱假设；共同风险标签需有因果机制。"],
        },
        "waiting_for": {
            "reason": "research", "condition": "先完成有证据的价格条件与损失路径分析。",
            "next_evidence": "优先调查最可能改变结论的一项未知；标明来源和可观察条件。",
        },
    }


def _validate_price(item: dict, record: dict, claims: dict, root: Path, authored: datetime) -> None:
    price_fields = {"status", "summary", "method", "conditions", "assumptions", "claim_ids",
                    "unknowns", "horizon_years", "reference_price", "model_reference"}
    _require(isinstance(item, dict) and price_fields <= set(item) <= price_fields | {"observation_reference"},
             "price conditions fields differ")
    _require(item["status"] in {"unknown", "assessed"}, "price status invalid")
    assessed = item["status"] == "assessed"
    _require(_text(item["summary"]) and _text(item["method"]), "price assessment/method missing")
    for key in ("conditions", "assumptions"):
        _texts(item[key], "price " + key, nonempty=assessed)
    _texts(item["unknowns"], "price unknowns", nonempty=not assessed)
    _refs(item["claim_ids"], claims, "price claims", required=assessed)
    if not assessed:
        _require(all(item[key] is None for key in ("reference_price", "model_reference", "horizon_years")),
                 "unknown price assessment cannot attach calculated reference")
        _require(item.get("observation_reference") is None, "unknown price assessment cannot attach quote receipt")
        return
    horizon = item["horizon_years"]
    _require(type(horizon) in {int, float} and math.isfinite(horizon) and 0 < horizon <= 50,
             "price horizon must be positive finite years")
    reference = item["model_reference"]
    _fields(reference, {"relative_path", "sha256"}, "price model reference")
    model = record.get("valuation_model")
    _require(record.get("valuation", {}).get("status") == "reviewed_scenarios"
             and isinstance(model, dict)
             and all(reference[key] == model.get(key) for key in reference),
             "price conditions require the exact reviewed valuation model")
    path = _evidence_path(root, reference["relative_path"], "04_data/equity_research/")
    payload = path.read_bytes()
    _require(hashlib.sha256(payload).hexdigest() == reference["sha256"], "price model hash differs")
    bundle = json.loads(payload)
    matches = [row for row in bundle.get("records", []) if row.get("ticker") == record["ticker"]]
    _require(len(matches) == 1, "price model company identity ambiguous")
    quote = matches[0].get("inputs", {}).get("share_price", {})
    ref_price = item["reference_price"]
    _fields(ref_price, {"value", "date"}, "reference price")
    number = _number(ref_price["value"])
    try:
        quote_day = date.fromisoformat(ref_price["date"])
    except (ValueError, TypeError) as exc:
        raise ValueError("research method: invalid reference price date") from exc
    observation = item.get("observation_reference")
    if observation is None:
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", str(quote.get("period", "")))
        _require(number == _number(quote.get("value")), "reference price differs from reviewed model")
        _require(dates == [ref_price["date"]]
                 and 0 <= (_time(record["reviewed_at"]).date() - quote_day).days <= 7,
                 "reference price date stale, future or different from model")
        return
    _fields(observation, {"relative_path", "sha256", "review_record_sha256", "horizon"}, "price observation reference")
    path = _evidence_path(root, observation["relative_path"],
                          "04_data/equity_research/company_valuation_observations.local/")
    payload = path.read_bytes()
    _require(hashlib.sha256(payload).hexdigest() == observation["sha256"], "price observation file hash differs")
    retained = json.loads(payload)
    sealed = {key: value for key, value in retained.items() if key not in {"observed_at", "observation_sha256"}}
    _require(retained.get("schema_version") == "equity_company_valuation_observation_v1"
             and canonical_sha256(sealed) == retained.get("observation_sha256")
             and path.stem == retained.get("observation_sha256"), "price observation seal differs")
    admission, projection = retained.get("admission", {}), retained.get("projection", {})
    _require(admission.get("status") == "admitted_current" and admission.get("immutable_assumptions") is True
             and projection.get("status") == "complete" and retained.get("automatic_action_allowed") is False,
             "price observation does not retain an admitted complete research projection")
    _require(admission.get("ticker") == projection.get("ticker") == record["ticker"]
             and admission.get("model_sha256") == reference["sha256"]
             and admission.get("review_record_sha256") == observation["review_record_sha256"],
             "price observation company/model/review identity differs")
    _require(_text(observation["horizon"])
             and observation["horizon"] == projection.get("metric_interpretation", {}).get("horizon"),
             "price observation horizon differs")
    observed = _time(retained.get("observed_at"))
    _require(observed <= authored and quote_day <= observed.date()
             and 0 <= (authored.date() - quote_day).days <= 7
             and ref_price["date"] == projection.get("as_of_market_session")
             and number == _number(projection.get("current_price")),
             "price observation is stale, future or differs from retained quote")


def _validate_consensus(item: dict, record: dict, claims: dict, root: Path, authored: datetime) -> None:
    _fields(item, {"status", "summary", "sample_scope", "claim_ids", "unknowns", "observation"}, "consensus")
    _require(item["status"] in {"unknown", "sourced_observation"}, "consensus status invalid")
    sourced = item["status"] == "sourced_observation"
    _require(_text(item["summary"]), "consensus assessment missing")
    _refs(item["claim_ids"], claims, "consensus contextual claims")
    _texts(item["unknowns"], "consensus unknowns", nonempty=not sourced)
    if not sourced:
        _require(item["observation"] is None and item["sample_scope"] == "",
                 "unknown consensus cannot claim an observation or sample")
        return
    _require(_text(item["sample_scope"]), "consensus sample scope missing")
    receipt = item["observation"]
    _fields(receipt, {"kind", "source_url", "relative_path", "sha256", "published_at", "observed_at",
                      "char_start", "char_end", "excerpt"}, "external consensus observation")
    _require(receipt["kind"] in {"analyst_consensus", "market_survey"},
             "issuer guidance and price-implied conditions are not market consensus")
    url = urlsplit(receipt["source_url"])
    _require(url.scheme == "https" and bool(url.netloc) and not url.username and not url.password,
             "consensus requires a public HTTPS source URL")
    _require(_time(receipt["published_at"]) <= _time(receipt["observed_at"]) <= authored,
             "consensus observation is future or precedes publication")
    path = _evidence_path(root, receipt["relative_path"], "03_source_data/equity_research/")
    payload = path.read_bytes()
    _require(hashlib.sha256(payload).hexdigest() == receipt["sha256"], "consensus source hash differs")
    text = payload.decode("utf-8")
    start, end = receipt["char_start"], receipt["char_end"]
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
             "consensus excerpt offsets invalid")
    _require(isinstance(receipt["excerpt"], str) and 10 <= len(receipt["excerpt"]) <= 1600
             and text[start:end] == receipt["excerpt"], "consensus excerpt differs from retained source")


def _validate_difference(item: dict, method: dict, claims: dict) -> None:
    _fields(item, {"status", "summary", "comparison_basis", "claim_ids", "falsifier", "next_evidence", "unknowns"},
            "differentiated view")
    _require(item["status"] in {"unknown", "hypothesis"}, "differentiated status invalid")
    assessed = item["status"] == "hypothesis"
    _require(_text(item["summary"]) and _text(item["next_evidence"]), "differentiated assessment/next evidence missing")
    _refs(item["claim_ids"], claims, "differentiated claims", required=assessed)
    _texts(item["unknowns"], "differentiated unknowns", nonempty=not assessed)
    basis = item["comparison_basis"]
    _require(basis in {"unknown", "price_implied_conditions", "market_consensus"}, "comparison basis invalid")
    if assessed:
        _require(basis != "unknown" and method[basis]["status"] != "unknown",
                 "differentiated hypothesis requires an assessed comparison")
        _require(_text(item["falsifier"]), "differentiated hypothesis requires falsifier")
        _require({"supporting", "contradictory"} <= {claims[key]["stance"] for key in item["claim_ids"]},
                 "differentiated hypothesis must examine support and counterevidence")
    else:
        _require(basis == "unknown", "unknown differentiated view cannot assert comparison")


def _validate_loss(item: dict, claims: dict) -> None:
    _fields(item, {"status", "paths", "fragile_assumptions", "shared_exposures", "unknowns"}, "loss analysis")
    _require(item["status"] in {"unknown", "assessed"}, "loss status invalid")
    assessed = item["status"] == "assessed"
    _texts(item["unknowns"], "loss unknowns", nonempty=not assessed)
    for key, maximum in (("paths", 3), ("fragile_assumptions", 3), ("shared_exposures", 5)):
        values = item[key]
        _require(isinstance(values, list) and len(values) <= maximum, "loss " + key + " must be a bounded list")
        if assessed and key != "shared_exposures":
            _require(bool(values), "assessed loss analysis requires " + key)
        if not assessed:
            _require(not values, "unknown loss analysis cannot claim assessed paths/exposures")
    path_ids, risk_tags = set(), set()
    for path in item["paths"]:
        _fields(path, {"path_id", "steps", "impairment", "early_warning", "claim_ids", "unknowns"}, "loss path")
        _require(_text(path["path_id"]) and path["path_id"] not in path_ids, "loss path identity duplicated or missing")
        path_ids.add(path["path_id"])
        _texts(path["steps"], "loss causal steps", nonempty=True)
        _require(len(path["steps"]) >= 2 and _text(path["impairment"]) and _text(path["early_warning"]),
                 "loss path needs causal steps, permanent impairment and early warning")
        _refs(path["claim_ids"], claims, "loss path claims", required=True)
        _texts(path["unknowns"], "loss path unknowns")
    for assumption in item["fragile_assumptions"]:
        _fields(assumption, {"assumption", "adverse_change", "consequence", "claim_ids", "unknowns"}, "fragile assumption")
        _require(all(_text(assumption[key]) for key in ("assumption", "adverse_change", "consequence")),
                 "fragile assumption needs adverse change and consequence")
        _refs(assumption["claim_ids"], claims, "fragile assumption claims", required=True)
        _texts(assumption["unknowns"], "fragile assumption unknowns")
    for exposure in item["shared_exposures"]:
        _fields(exposure, {"risk_tag", "mechanism", "claim_ids", "unknowns"}, "shared exposure")
        tag = exposure["risk_tag"]
        _require(isinstance(tag, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,63}", tag) is not None
                 and tag not in risk_tags and _text(exposure["mechanism"]), "shared exposure tag/mechanism invalid or duplicate")
        risk_tags.add(tag)
        _refs(exposure["claim_ids"], claims, "shared exposure claims", required=True)
        _texts(exposure["unknowns"], "shared exposure unknowns")


def validate_research_method(record: dict[str, Any], root: Path, observed_at: str) -> None:
    """Called after ordinary dossier evidence and valuation validation."""
    if "research_method" not in record:
        return
    method = record["research_method"]
    fields = {"schema_version", "price_implied_conditions", "market_consensus", "differentiated_view",
              "loss_analysis", "waiting_for"}
    _require(isinstance(method, dict) and fields <= set(method) <= fields | {"authored_at"}, "method fields differ")
    _require(method["schema_version"] == SCHEMA, "unsupported schema")
    authored = _time(method.get("authored_at", record["reviewed_at"]))
    # An unchanged method can survive a later financial review. Its original
    # authorship is verified against preceding versions in validate_store.
    _require(authored <= _time(observed_at), "authored timestamp is future")
    claims = {row["claim_id"]: row for row in record["claims"]}
    _validate_price(method["price_implied_conditions"], record, claims, root, authored)
    _validate_consensus(method["market_consensus"], record, claims, root, authored)
    _validate_difference(method["differentiated_view"], method, claims)
    _validate_loss(method["loss_analysis"], claims)
    wait = method["waiting_for"]
    _fields(wait, {"reason", "condition", "next_evidence"}, "waiting condition")
    _require(wait["reason"] in {"price", "evidence", "research"}
             and _text(wait["condition"]) and _text(wait["next_evidence"]), "waiting reason/condition/evidence missing")
    for source in _method_evidence(record)["sources"]:
        _require(_time(source["published_at"]) <= authored and _time(source["fetched_at"]) <= authored,
                 "cited method evidence was published or retained after authorship")


def validate_research_method_ancestry(record: dict[str, Any], preceding_records: list[dict]) -> None:
    """Preserve real authorship and bind quote receipts to prior dossier versions."""
    method = record.get("research_method")
    if not isinstance(method, dict):
        return
    earlier = [row for row in preceding_records if row.get("ticker") == record.get("ticker")]
    authored = _time(method.get("authored_at", record["reviewed_at"]))
    unchanged = any(row.get("research_method") == method and _method_evidence(row) == _method_evidence(record)
                    for row in earlier)
    if not unchanged:
        if earlier and _time(record["reviewed_at"]) <= max(_time(row["reviewed_at"]) for row in earlier):
            _require("authored_at" in method,
                     "an annotation preserving financial review time requires explicit authored_at")
        prior_authorship = [_time(row["research_method"].get("authored_at", row["reviewed_at"]))
                            for row in earlier if isinstance(row.get("research_method"), dict)]
        _require(authored >= max([_time(record["reviewed_at"]), *prior_authorship]),
                 "new or changed method cannot backdate authored timestamp")
    price = method.get("price_implied_conditions")
    reference = price.get("observation_reference") if isinstance(price, dict) else None
    if reference is None:
        return
    _require(isinstance(reference, dict), "price observation reference invalid")
    ancestors = [row for row in preceding_records
                 if row.get("ticker") == record.get("ticker")
                 and row.get("record_sha256") == reference.get("review_record_sha256")]
    _require(len(ancestors) == 1 and ancestors[0].get("valuation_model") is not None
             and ancestors[0]["valuation_model"].get("sha256") == (record.get("valuation_model") or {}).get("sha256"),
             "price observation must anchor an earlier same-company dossier with the same model")
