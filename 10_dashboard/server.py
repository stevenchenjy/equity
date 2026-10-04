"""Private dashboard. Loopback listener; optional owner-only Tailscale Serve."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import math
import mimetypes
import re
import threading
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs
from zoneinfo import ZoneInfo
from feedback import Store, FeedbackError, version, PENDING, CONFIRMED, RECONCILED
from tactical_review import _validated_bars
from dashboard_publication import publication_id
from plan_summary import SUMMARY_PATH, catalog, matching_summary

ET = ZoneInfo("America/New_York")
DEFAULT_ROOT = Path("/Users/messssi/LocalRuntime/equity")
RUNTIME_LOCK = Path("/Users/messssi/LocalRuntime/.locks/equity-research-runtime.lock")
APP_ROOT = Path(__file__).resolve().parent
DECISION = "04_research/company_research/daily_decision.json"
ACCOUNT = "05_risk_and_positions/current_account_state.local.json"
POSITIONS = "05_risk_and_positions/current_positions.local.csv"
PLANS = "05_risk_and_positions/investment_plans.local.json"
ORDERS = "05_risk_and_positions/current_open_orders.local.json"
MARKET = "03_source_data/equity_research/market_data_snapshot.csv"
EXTRA_INPUTS = {
    "04_research/company_research/thesis_dossiers.local.json",
    "04_research/company_research/issuer_news_review_queue.local.jsonl",
}
CORE_INPUTS = {ACCOUNT, POSITIONS, PLANS, ORDERS}
ALLOWED_INPUTS = CORE_INPUTS | EXTRA_INPUTS
ALLOWED_INPUTS.add(PENDING)


class SnapshotError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_read(root: Path, relative: str) -> bytes:
    path = root / relative
    if path.resolve().is_relative_to(root.resolve()) is False:
        raise SnapshotError("input_path_outside_runtime")
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise SnapshotError("symlink_input_rejected")
    if not path.is_file() or path.stat().st_size > 12_000_000:
        raise SnapshotError("input_missing_or_too_large:" + relative)
    return path.read_bytes()


def stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(ET) if result.tzinfo else None
    except ValueError:
        return None


def number(value: object) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def read_snapshot(root: Path, now: datetime | None = None) -> dict:
    """Capture retained bytes, verify publication fingerprints, then read back.

    Production callers also hold the existing runtime lock. No pipeline module
    is imported: several readers have persistence side effects.
    """
    now = now or datetime.now(ET)
    decision_raw = safe_read(root, DECISION)
    d = json.loads(decision_raw)
    if not isinstance(d, dict) or not isinstance(d.get("held_positions"), list):
        raise SnapshotError("decision_schema_invalid")
    hashes = d.get("workflow_integrity", {}).get("input_hashes", {})
    if not isinstance(hashes, dict) or not CORE_INPUTS.issubset(hashes):
        raise SnapshotError("publication_fingerprints_missing")
    if not set(hashes).issubset(ALLOWED_INPUTS):
        raise SnapshotError("unregistered_publication_input")
    if (root/PENDING).exists() and PENDING not in hashes:
        raise SnapshotError('research_inputs_changed')
    paths = {path for path in set(hashes) | {MARKET} if (root/path).exists()}
    raws = {path: safe_read(root, path) for path in paths}
    mismatch = [path for path, expected in hashes.items() if (digest(raws[path]) if path in raws else None) != expected]
    if mismatch:
        raise SnapshotError("research_inputs_changed")
    if safe_read(root, DECISION) != decision_raw or any(safe_read(root, p) != b for p, b in raws.items()):
        raise SnapshotError("snapshot_changed_during_read")
    account_raw = json.loads(raws[ACCOUNT])
    orders_raw = json.loads(raws[ORDERS])
    account = d.get("account", {})
    if number(account.get("cash_available")) != number(account_raw.get("cash_available")):
        raise SnapshotError("decision_cash_differs_from_account")
    held = d["held_positions"]
    csv_positions = list(csv.DictReader(io.StringIO(raws[POSITIONS].decode())))
    expected_shares = {r["ticker"]: number(r["shares_optional"]) for r in csv_positions}
    if expected_shares != {r["ticker"]: number(r["current_shares"]) for r in held}:
        raise SnapshotError("decision_shares_differ_from_account")
    generated = stamp(d.get("generated_at"))
    if generated is None or generated > now:
        raise SnapshotError("decision_timestamp_invalid")
    rows = {r["ticker"]: r for r in csv.DictReader(io.StringIO(raws[MARKET].decode()))}
    expected_session = d.get("market_gate", {}).get("expected_market_session")
    for row in held:
        market = rows.get(row["ticker"], {})
        if (market.get("data_quality_label") != "ok"
                or market.get("market_session_date") != expected_session
                or number(market.get("last_price")) != number(row.get("current_price"))):
            raise SnapshotError("decision_price_snapshot_mismatch")
    stale = d.get("cycle_date") != now.date().isoformat()
    try:
        summaries = catalog(safe_read(root, SUMMARY_PATH))
    except (SnapshotError, OSError):
        summaries = []
    plans = []
    for p in d.get("plan_continuity", {}).get("plans", []):
        deadlines = [v for k in ("review_at", "valid_until", "time_exit_at") if (v := stamp(p.get(k)))]
        expiry = min(deadlines) if deadlines else None
        status = "expired" if stale or (expiry and now >= expiry) else "pending" if p.get("blockers") else "current"
        if not expiry:
            status = "unverified"
        plans.append({
            "ticker": p["ticker"], "plan_id": p.get("plan_id"), "version": p.get("version"),
            "record_hash": p.get("record_hash"), "action": p.get("action"), "status": status,
            "expires_at": expiry.isoformat() if expiry else None,
            "review_at": p.get("review_at"), "blockers": p.get("blockers", []),
            "instruction": p.get("instruction", ""), "reason": p.get("reason", ""),
            "counterargument": p.get("counterargument", ""), "purpose": p.get("purpose", {}),
            "display_summary": matching_summary(p, summaries),
            "sources": [{"path": s.get("path"), "sha256": s.get("sha256")} for s in p.get("sources", [])],
            "draft": p.get("order_draft") if status == "current" else None,
            "historical_draft": p.get("historical_order_draft", p.get("order_draft")),
            "eligible_quantity": p.get("eligible_quantity", 0) if status == "current" else 0,
        })
    values = {k: number(account.get(k)) for k in ("account_total_value", "cash_available", "invested_capital")}
    if any(v is None or v < 0 for v in values.values()):
        raise SnapshotError("account_values_invalid")
    invested = sum(number(r["current_shares"]) * number(r["current_price"]) for r in held)
    if (abs(invested - values["invested_capital"]) > 0.01
            or abs(values["cash_available"] + invested - values["account_total_value"]) > 0.01):
        raise SnapshotError("decision_account_total_does_not_reconcile")
    plan_map = {p["ticker"]: p for p in plans}
    candidates = []
    for r in d.get("watch_candidates", []):
        p = plan_map.get(r["ticker"])
        valid = (not stale and (not p or p["status"] == "current")
                 and r["ticker"] in d.get("eligible_new_position_review_candidates", [])
                 and not r.get("workflow_global_blockers") and not r.get("workflow_ticker_blockers"))
        candidates.append({
            "ticker": r["ticker"], "label": r.get("label"), "status": "review" if valid else "watch",
            "price": number(r.get("current_price")), "quantity": number(r.get("suggested_whole_shares")) if valid else 0,
            "maximum_review_price": number(r.get("maximum_review_price")) if valid else None,
            "blockers": r.get("gate_blockers", ""), "invalidation": r.get("invalidation", ""),
            "valuation_source": r.get("valuation_source"),
        })
    capital = d.get("capital_decision")
    capital_status = "legacy_unavailable"
    if capital:
        from capital_decision import validate as validate_capital
        try:
            validate_capital(capital, root=root, current=now)
            capital_status = "current"
        except (ValueError, KeyError, TypeError):
            capital = None
            capital_status = "recompose_required"
    if d.get("capital_decision") is not None:
        # Adjacent legacy widgets must not resurrect a canonical 'up to'
        # ceiling, a withheld duplicate, or an invalidated current draft.
        # The complete capital action card is the sole order presentation.
        for plan in plans:
            plan["draft"] = None
            plan["eligible_quantity"] = 0
        actions = {r["ticker"]: r for r in capital.get("decisions", [])} if capital else {}
        for candidate in candidates:
            action = actions.get(candidate["ticker"], {})
            draft = action.get("order_draft") or {}
            eligible = action.get("decision") in {"ACTIONABLE_BUY", "ACTIONABLE_ADD"} and draft.get("side") == "buy"
            candidate.update(quantity=action["shares"] if eligible else 0,
                             maximum_review_price=draft.get("entry_limit") if eligible else None,
                             status="review" if eligible else "watch")
    observed = stamp(orders_raw.get("as_of"))
    return {
        "schema_version": "equity_dashboard_snapshot_v1", "mode": "read_only_preview",
        "server_now": now.isoformat(), "generated_at": d["generated_at"], "cycle_date": d.get("cycle_date"),
        "market_session": expected_session, "stale": stale,
        "snapshot_id": digest(decision_raw), "account_version": version(root),
        "account": {**values, "last_updated": account_raw.get("last_updated"), "cash_basis": account.get("cash_basis"),
                    "settled_cash_verified": orders_raw.get("broker_balance_observation", {}).get("settled_cash_verified") is True},
        "positions": [{"ticker": r["ticker"], "shares": number(r.get("current_shares")),
                       "price": number(r.get("current_price")), "weight": number(r.get("current_weight_pct")),
                       "role": r.get("asset_role")} for r in held],
        "plans": plans, "candidates": candidates,
        "orders": {"as_of": orders_raw.get("as_of"), "complete": orders_raw.get("complete") is True,
                   "fresh": bool(observed and 0 <= (now - observed).total_seconds() <= 86400),
                   "rows": [{k: r.get(k) for k in ("ticker", "side", "quantity", "remaining_quantity", "status", "order_id", "limit_price", "stop_price", "record_scope")}
                            for r in orders_raw.get("orders", [])]},
        "global_blockers": (capital.get("global_blockers", []) if capital else
                            d.get("workflow_integrity", {}).get("global_blockers", [])),
        "capital_decision": capital, "capital_decision_status": capital_status,
    }


def current_snapshot(root):
    """Show accepted account facts while its former research is superseded."""
    try:
        result = read_snapshot(root)
        result['research_ready'] = True
    except SnapshotError as exc:
        if str(exc) not in {'research_inputs_changed','decision_cash_differs_from_account','decision_shares_differ_from_account','decision_price_snapshot_mismatch'}:
            raise
        a = json.loads(safe_read(root,ACCOUNT))
        o = json.loads(safe_read(root,ORDERS))
        positions = list(csv.DictReader(io.StringIO(safe_read(root,POSITIONS).decode())))
        market = {r['ticker']:r for r in csv.DictReader(io.StringIO(safe_read(root,MARKET).decode()))}
        d = json.loads(safe_read(root,DECISION))
        known = all(market.get(r['ticker'],{}).get('data_quality_label')=='ok' for r in positions)
        invested = sum(float(r['shares_optional'])*float(market[r['ticker']]['last_price']) for r in positions) if known else None
        total = float(a['cash_available'])+invested if known else None
        result = dict(schema_version='equity_dashboard_snapshot_v1', server_now=datetime.now(ET).isoformat(), generated_at=d.get('generated_at'),
            cycle_date=d.get('cycle_date'), market_session=d.get('market_gate',{}).get('expected_market_session'),stale=d.get('cycle_date')!=datetime.now(ET).date().isoformat(),
            snapshot_id=digest(safe_read(root,DECISION)),account_version=version(root),research_ready=False,
            account=dict(account_total_value=total,cash_available=a['cash_available'],invested_capital=invested,last_updated=a['last_updated'],cash_basis=a.get('cash_basis'),settled_cash_verified=False),
            positions=[dict(ticker=r['ticker'],shares=float(r['shares_optional']),price=number(market.get(r['ticker'],{}).get('last_price')) if market.get(r['ticker'],{}).get('data_quality_label')=='ok' else None,
                weight=float(r['shares_optional'])*float(market[r['ticker']]['last_price'])/total*100 if known and total else None,role='待研究') for r in positions],
            plans=[],candidates=[],orders=dict(as_of=o.get('as_of'),complete=o.get('complete') is True,fresh=False,rows=o.get('orders',[])),global_blockers=['account_recomposition_pending'])
    result['mode'] = 'formal_feedback'
    return result


def chart(root, ticker, records):
    if re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', ticker) is None: raise SnapshotError('invalid_ticker')
    raw = safe_read(root,MARKET)
    market = next((r for r in csv.DictReader(io.StringIO(raw.decode())) if r['ticker']==ticker),None)
    if not market or market.get('data_quality_label')!='ok': raise SnapshotError('chart_market_unavailable')
    history = json.loads(safe_read(root,'03_source_data/equity_research/tactical_price_history.local.json'))
    session = datetime.fromisoformat(market['market_session_date']).date()
    bars, errors = _validated_bars(history,ticker,session,digest(raw),market['last_price'])
    if errors: raise SnapshotError(errors[0])
    fills = [dict(id=r['id'],date=r['feedback']['date'],time=r['feedback']['time'],side=r['feedback']['side'],shares=r['feedback']['shares'],price=r['changes']['fill_price'],account_corrected_by=r.get('corrected_by',[]))
        for r in records if r['stage']=='applied' and r['feedback']['ticker']==ticker and r['feedback']['status'] in {'filled','partial'}]
    if (root/CONFIRMED).exists() and (root/RECONCILED).exists():
        reconciled={r['execution_id'] for r in csv.DictReader(io.StringIO(safe_read(root,RECONCILED).decode())) if r.get('reconciliation_status')=='applied'}
        for r in csv.DictReader(io.StringIO(safe_read(root,CONFIRMED).decode())):
            if (r.get('ticker')==ticker and r.get('order_status') in {'filled','partial_fill'} and r.get('canonical_state_applied')=='yes'
                    and r.get('execution_id') in reconciled and not r.get('execution_id','').startswith('dashboard-')
                    and number(r.get('fill_price')) is not None and number(r.get('fill_price'))>0):
                fills.append(dict(id=r['execution_id'],date=r['fill_date'],time='',side=r['side'],shares=r['shares'],price=number(r['fill_price'])))
    return dict(ticker=ticker,bars=bars,source=history['data_source'],source_url=history['tickers'][ticker]['source_url'],market_session=session.isoformat(),
        adjusted=False,realtime=False,fills=fills)


def email_versions(root):
    ledger = root/'07_automation/email_delivery/daily_delivery_ledger.csv'
    if not ledger.exists(): return []
    data = list(csv.DictReader(io.StringIO(safe_read(root,str(ledger.relative_to(root))).decode())))
    result,seen=[],set()
    for r in reversed(data):
        key=r.get('decision_sha256','')
        if r.get('status','').endswith('sent') and re.fullmatch('[0-9a-f]{64}',key) and key not in seen:
            seen.add(key); result.append(dict(id=key,timestamp=r.get('timestamp'),status=r['status']))
    return result[:100]


def email_version(root, key):
    if key not in {r['id'] for r in email_versions(root)}: raise SnapshotError('email_version_not_found')
    raw=safe_read(root,'07_automation/email_delivery/sent_decisions.local/'+key+'.json')
    if digest(raw)!=key: raise SnapshotError('email_archive_hash_mismatch')
    d=json.loads(raw)
    sent=rows_for_mail(root,key)
    text_hash=sent.get('brief_text_sha256','')
    original=None
    if re.fullmatch('[0-9a-f]{64}',text_hash) and (root/('07_automation/email_delivery/sent_decisions.local/'+text_hash+'.txt')).exists():
        body=safe_read(root,'07_automation/email_delivery/sent_decisions.local/'+text_hash+'.txt')
        if digest(body)!=text_hash: raise SnapshotError('email_body_archive_hash_mismatch')
        original=body.decode()
    return dict(id=key,generated_at=d.get('generated_at'),cycle_date=d.get('cycle_date'),headline=d.get('headline'),
        advice=d.get('decisive_advice'),plans=d.get('plan_continuity',{}).get('plans',[]),historical=True,
        original_text=original,body_archive_verified=original is not None)


def rows_for_mail(root,key):
    data=list(csv.DictReader(io.StringIO(safe_read(root,'07_automation/email_delivery/daily_delivery_ledger.csv').decode())))
    return next(r for r in reversed(data) if r.get('decision_sha256')==key and r.get('status','').endswith('sent'))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Request URLs or records never enter a public access log.

    def respond(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def error_json(self, code: int, reason: str):
        self.respond(code, json.dumps({"error": reason, "production_effect": False}).encode(), "application/json")

    def permitted(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        local = host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        config = getattr(self.server,'access',{})
        private = (host == config.get('host') and bool(config.get('owner_login')) and self.headers.get('Tailscale-User-Login')==config.get('owner_login'))
        return ((local or private)
                and (not origin or origin == ('http://' if local else 'https://') + host)
                and self.headers.get("Sec-Fetch-Site") != "cross-site")

    def do_GET(self):
        if not self.permitted():
            return self.error_json(403, "local_origin_required")
        path = unquote(urlsplit(self.path).path)
        if path == "/api/snapshot":
            try:
                # Open an existing lock read-only; never create runtime files.
                with RUNTIME_LOCK.open("rb") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                    result = current_snapshot(self.server.runtime_root) if hasattr(self.server,'store') else read_snapshot(self.server.runtime_root)
                    if getattr(self.server,'verification',False): result['mode']='verification'
                return self.respond(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8")
            except BlockingIOError:
                return self.error_json(503, "runtime_refresh_in_progress")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                reason = str(exc) if isinstance(exc, SnapshotError) else "snapshot_unavailable"
                return self.error_json(503, reason)
        try:
            query = parse_qs(urlsplit(self.path).query)
            if path == '/api/feedback' and hasattr(self.server,'store'):
                return self.respond(200,json.dumps({'records':self.server.store.history()},ensure_ascii=False).encode(),'application/json')
            if path == '/api/feedback/events' and hasattr(self.server,'store'):
                return self.respond(200,json.dumps({'events':self.server.store.events(query.get('id',[''])[0])},ensure_ascii=False).encode(),'application/json')
            if path == '/api/review-requests' and hasattr(self.server,'store'):
                return self.respond(200,json.dumps({'requests':self.server.store.reviews()},ensure_ascii=False).encode(),'application/json')
            if path == '/api/review-requests/events' and hasattr(self.server,'store'):
                return self.respond(200,json.dumps({'events':self.server.store.review_events(query.get('id',[''])[0])},ensure_ascii=False).encode(),'application/json')
            if path in {'/api/chart','/api/email-versions','/api/email-version','/api/email-publication'}:
                with RUNTIME_LOCK.open('rb') as lock:
                    fcntl.flock(lock.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
                    root=self.server.runtime_root
                    if path=='/api/chart': result=chart(root,query.get('ticker',[''])[0],self.server.store.history())
                    elif path=='/api/email-versions': result={'versions':email_versions(root)}
                    elif path=='/api/email-version': result=email_version(root,query.get('id',[''])[0])
                    else:
                        token=query.get('id',[''])[0]
                        if re.fullmatch('[0-9a-f]{64}',token) is None: raise SnapshotError('invalid_publication')
                        matches=[]
                        for entry in email_versions(root):
                            raw=safe_read(root,'07_automation/email_delivery/sent_decisions.local/'+entry['id']+'.json')
                            if digest(raw)==entry['id'] and publication_id(json.loads(raw))==token: matches.append(entry['id'])
                        if len(matches)!=1: raise SnapshotError('email_publication_not_unique_or_not_sent')
                        result=email_version(root,matches[0])
                return self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False).encode(),'application/json')
        except FeedbackError as exc: return self.error_json(exc.status,exc.code)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error): return self.error_json(503,'requested_data_unavailable')
        if path.startswith("/api/"):
            return self.error_json(404, "route_not_found")
        dist = APP_ROOT / "dist"
        target = dist / ("index.html" if path == "/" else path.lstrip("/"))
        if not target.resolve().is_relative_to(dist.resolve()) or target.is_symlink():
            return self.error_json(404, "route_not_found")
        if not target.is_file():
            return self.error_json(404, "route_not_found")
        self.respond(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    def do_POST(self):
        if not hasattr(self.server,'store'): return self.error_json(405,'phase1_has_no_write_routes')
        if not self.permitted() or not self.headers.get('Origin') or self.headers.get('Content-Type')!='application/json':
            return self.error_json(403,'same_origin_json_required')
        path=urlsplit(self.path).path
        if path not in {'/api/feedback/preview','/api/feedback','/api/feedback/retry','/api/review-requests'}: return self.error_json(404,'route_not_found')
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=32000: return self.error_json(413,'request_too_large')
            payload=json.loads(self.rfile.read(length))
            if not isinstance(payload,dict): raise FeedbackError('invalid_request')
            store=self.server.store
            if path=='/api/review-requests': result=store.request_review(payload)
            elif path.endswith('/preview'): result=store.preview(payload)
            elif path.endswith('/retry'): result=store.retry(payload.get('record_id'))
            else: result=store.submit(payload)
            return self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False).encode(),'application/json')
        except FeedbackError as exc:
            return self.respond(exc.status,json.dumps({'error':exc.code,'details':exc.details,'production_effect':None if exc.code=='recovery_conflict' else False},ensure_ascii=False).encode(),'application/json')
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
            return self.respond(503,json.dumps({'error':'feedback_result_unknown_retry_same_request','production_effect':None}).encode(),'application/json')

    def do_PUT(self): self.error_json(405,'method_not_allowed')
    do_PATCH = do_PUT
    do_DELETE = do_PUT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    if args.runtime_root.resolve() != DEFAULT_ROOT:
        parser.error("preview must explicitly use the production checkout")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.runtime_root = args.runtime_root
    access=args.runtime_root/'07_automation/dashboard.local/access.json'
    server.access=json.loads(access.read_text()) if access.exists() and not access.is_symlink() else {}
    server.store=Store(args.runtime_root,RUNTIME_LOCK)
    threading.Thread(target=server.store.worker,daemon=True).start()
    print(f"Equity Research dashboard: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
