"""Durable human feedback coordinator. Canonical CSV/JSON remain authoritative.

The journal records a prepared multi-file transition before any replacement.
Both the runtime and daily locks are held for each write and recovery. Public
research runs afterwards; its failure never rolls back accepted human facts.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '09_scripts/equity_research'))
from account_common import validate_account_state
from execution_common import EXECUTION_FIELDS, validate_execution_row
from validate_execution_fill import CONFIRMED_FIELDS
from reconcile_account_state import RECONCILIATION_FIELDS
from portfolio_archive import archive_before_replace

ET = ZoneInfo('America/New_York')
ACCOUNT = '05_risk_and_positions/current_account_state.local.json'
POSITIONS = '05_risk_and_positions/current_positions.local.csv'
ORDERS = '05_risk_and_positions/current_open_orders.local.json'
LEDGER = '06_execution_records/manual_executions.local.csv'
CONFIRMED = '06_execution_records/confirmed_execution_report.csv'
RECONCILED = '06_execution_records/reconciliation_report.csv'
PENDING = '06_execution_records/dashboard_feedback_pending.local.json'
JOURNAL = '06_execution_records/dashboard_feedback.local/journal.sqlite3'
MARKET = '03_source_data/equity_research/market_data_snapshot.csv'
MANUAL = '05_risk_and_positions/manual_account_snapshot.local.json'
SYMBOL = re.compile(r'[A-Z][A-Z0-9.\-]{0,11}')
CENT = Decimal('.01')


class FeedbackError(ValueError):
    def __init__(self, code, details=None, status=422):
        super().__init__(code)
        self.code, self.details, self.status = code, details or {}, status


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(root, rel, optional=False):
    root = root.resolve()
    path = root / rel
    if not path.resolve().is_relative_to(root):
        raise FeedbackError('unsafe_runtime_path')
    for part in (path, *path.parents):
        if part == root.parent: break
        if part.is_symlink(): raise FeedbackError('unsafe_runtime_path')
    if optional and not path.exists():
        return b''
    if not path.is_file() or path.stat().st_size > 16_000_000:
        raise FeedbackError('runtime_input_unavailable', {'path': rel})
    return path.read_bytes()


def rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode()))) if raw else []


def verify_publication(root, decision):
    """Verify the final visible publication, beyond hashes on stale content."""
    account=json.loads(read(root,ACCOUNT))
    expected={r['ticker']:Decimal(r['shares_optional']) for r in rows(read(root,POSITIONS))}
    held=decision.get('held_positions',[])
    actual={r['ticker']:Decimal(str(r['current_shares'])) for r in held}
    if len(actual)!=len(held) or expected!=actual:
        raise ValueError('published_shares_differ_from_account')
    visible=decision['account']
    cash=Decimal(str(visible['cash_available']))
    invested=sum((Decimal(str(r['current_shares']))*Decimal(str(r['current_price'])) for r in held),Decimal(0))
    if (cash!=Decimal(str(account['cash_available'])) or abs(invested-Decimal(str(visible['invested_capital'])))>CENT
            or abs(cash+invested-Decimal(str(visible['account_total_value'])))>CENT):
        raise ValueError('published_account_does_not_reconcile')
    from email_brief import render_email
    _,plain,html=render_email(decision)
    for rel,expected_text in [('07_automation/email_briefs/daily_email_brief.txt',plain),('07_automation/email_briefs/daily_email_brief.html',html)]:
        if read(root,rel).decode()!=expected_text:
            raise ValueError('published_brief_differs_from_decision')


def csv_bytes(data, fields):
    handle = io.StringIO(newline='')
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(data)
    return handle.getvalue().encode()


def dec(value, name, *, zero=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise FeedbackError('invalid_field', {'field': name})
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise FeedbackError('invalid_field', {'field': name})
    if (not result.is_finite() or result < 0 or (not zero and result == 0)
            or result > Decimal('1000000000') or (integer and result != result.to_integral_value())):
        raise FeedbackError('invalid_field', {'field': name})
    return result


def cash(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def version(root):
    return sha(b''.join(read(root, p) for p in (ACCOUNT, POSITIONS, ORDERS)))


def atomic(root, rel, content):
    path = root / rel
    read(root, rel, optional=True)  # Reject symlinks before archive/replace.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive_before_replace(path, content)
    descriptor, name = tempfile.mkstemp(prefix='.dashboard-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


class Store:
    def __init__(self, root: Path, runtime_lock: Path, *, refresh=True):
        self.root, self.runtime_lock, self.refresh = root.resolve(), runtime_lock, refresh
        self.mutex = threading.RLock()
        self.wake = threading.Event()

    @contextmanager
    def locked(self):
        if not self.mutex.acquire(blocking=False):
            raise FeedbackError('runtime_refresh_in_progress', status=503)
        try:
            self.runtime_lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.runtime_lock.open('a+b') as outer:
                try: fcntl.flock(outer, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: raise FeedbackError('runtime_refresh_in_progress', status=503)
                daily = self.root / '00_project_control/run_logs/daily_pipeline.lock'
                daily.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with daily.open('a+b') as inner:
                    try: fcntl.flock(inner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError: raise FeedbackError('runtime_refresh_in_progress', status=503)
                    yield
        finally:
            self.mutex.release()

    @contextmanager
    def db(self):
        path = self.root / JOURNAL
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for part in (path,*path.parents):
            if part==self.root.parent: break
            if part.is_symlink(): raise FeedbackError('unsafe_runtime_path')
        if path.exists() and (not path.is_file() or path.stat().st_uid!=os.getuid() or path.stat().st_nlink!=1):
            raise FeedbackError('unsafe_journal')
        path.parent.chmod(0o700)
        con = sqlite3.connect(path, timeout=10)
        path.chmod(0o600)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA synchronous=FULL')
        con.executescript('''
          CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_id TEXT NOT NULL, state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS writes(request_id TEXT, path TEXT, before BLOB NOT NULL, after BLOB NOT NULL, PRIMARY KEY(request_id,path));
          CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY, record_id TEXT, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS review_requests(id TEXT PRIMARY KEY, payload TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS review_events(sequence INTEGER PRIMARY KEY, request_id TEXT NOT NULL, body TEXT NOT NULL);
        ''')
        try: yield con
        finally: con.close()

    def history(self):
        with self.db() as con:
            result = [json.loads(r['body']) for r in con.execute('SELECT body FROM records ORDER BY rowid DESC LIMIT 500')]
            corrections = {}
            for row in con.execute('SELECT body FROM records'):
                record = json.loads(row['body'])
                if record['stage'] == 'applied' and record.get('correction'):
                    corrections.setdefault(record['correction']['record_id'], []).append(record['id'])
            for record in result:
                record['corrected_by'] = corrections.get(record['id'], [])
        return result

    def events(self, record_id):
        with self.db() as con:
            if not con.execute('SELECT 1 FROM records WHERE id=?', (record_id,)).fetchone():
                raise FeedbackError('record_not_found', status=404)
            return [json.loads(r['body']) for r in con.execute('SELECT body FROM events WHERE record_id=? ORDER BY sequence', (record_id,))]

    def export(self, con, replacement=None):
        data = [json.loads(r['body']) for r in con.execute('SELECT body FROM records')]
        if replacement:
            data = [r for r in data if r['id'] != replacement['id']] + [replacement]
        unresolved = [dict(id=r['id'], ticker=r['feedback'].get('ticker'), stage=r['stage'], missing=r['missing'])
                      for r in data if r['stage'] in {'pending', 'applying', 'recovery_conflict'} and r['feedback']['status'] != 'skipped']
        return encoded({'schema_version': 'equity_dashboard_pending_v1', 'records': sorted(unresolved, key=lambda r:r['id'])})

    def recover(self, con):
        for req in con.execute("SELECT * FROM requests WHERE state='prepared'").fetchall():
            changes = con.execute('SELECT * FROM writes WHERE request_id=? ORDER BY path', (req['id'],)).fetchall()
            # Verify the entire transition before rolling it forward.
            if any(read(self.root, w['path'], optional=True) not in (w['before'], w['after']) for w in changes):
                r = json.loads(con.execute('SELECT body FROM records WHERE id=?', (req['record_id'],)).fetchone()[0])
                r['stage'], r['error'] = 'recovery_conflict', 'external_state_changed_during_recovery'
                con.execute('UPDATE records SET body=? WHERE id=?', (encoded(r).decode(), r['id'])); con.commit()
                atomic(self.root, PENDING, self.export(con))
                raise FeedbackError('recovery_conflict', status=409)
            atomic(self.root, PENDING, self.export(con))
            for w in changes:
                if read(self.root, w['path'], optional=True) != w['after']:
                    atomic(self.root, w['path'], w['after'])
            r = json.loads(con.execute('SELECT body FROM records WHERE id=?', (req['record_id'],)).fetchone()[0])
            r['stage'] = r.pop('final_stage', 'applied')
            con.execute('UPDATE records SET body=? WHERE id=?', (encoded(r).decode(), r['id']))
            con.execute('INSERT INTO events(record_id,body) VALUES(?,?)', (r['id'],encoded(r).decode()))
            con.execute("UPDATE requests SET state='complete' WHERE id=?", (req['id'],)); con.commit()
            atomic(self.root, PENDING, self.export(con))
        if (self.root/PENDING).exists() or con.execute('SELECT 1 FROM records LIMIT 1').fetchone():
            expected=self.export(con)
            if read(self.root,PENDING,optional=True)!=expected: atomic(self.root,PENDING,expected)

    def proposal(self, payload, con=None):
        if not isinstance(payload, dict) or not isinstance(payload.get('feedback'), dict):
            raise FeedbackError('invalid_request')
        if payload.get('account_version') != version(self.root):
            raise FeedbackError('account_version_changed', {'account_version': version(self.root)}, 409)
        f = dict(payload['feedback'])
        correction = payload.get('correction')
        if correction is not None:
            if (not isinstance(correction, dict) or set(correction) != {'record_id', 'reason'}
                    or not isinstance(correction['record_id'], str)
                    or not isinstance(correction['reason'], str)
                    or not correction['reason'].strip() or len(correction['reason']) > 1500
                    or f.get('status') != 'account'):
                raise FeedbackError('invalid_account_correction')
            if con is None:
                raise FeedbackError('correction_requires_coordinator')
            original = con.execute('SELECT body FROM records WHERE id=?', (correction['record_id'],)).fetchone()
            original = json.loads(original['body']) if original else None
            if (not original or original['stage'] != 'applied' or original.get('production_effect') is not True
                    or original['feedback']['status'] not in {'filled', 'partial', 'account'}):
                raise FeedbackError('correction_reference_not_applied', status=409)
        email_id=payload.get('email_version_id')
        if email_id is not None:
            if not isinstance(email_id,str) or re.fullmatch('[0-9a-f]{64}',email_id) is None: raise FeedbackError('invalid_email_reference')
            ledger=rows(read(self.root,'07_automation/email_delivery/daily_delivery_ledger.csv'))
            archived=read(self.root,'07_automation/email_delivery/sent_decisions.local/'+email_id+'.json')
            if sha(archived)!=email_id or not any(r.get('decision_sha256')==email_id and r.get('status','').endswith('sent') for r in ledger):
                raise FeedbackError('email_reference_unverified')
        plan = payload.get('plan')
        if plan is not None:
            if (not isinstance(plan,dict) or set(plan)!={'plan_id','version','record_hash'}
                    or not isinstance(plan['plan_id'],str) or len(plan['plan_id'])>200 or type(plan['version']) is not int
                    or not isinstance(plan['record_hash'],str) or not re.fullmatch('[0-9a-f]{64}',plan['record_hash'])):
                raise FeedbackError('invalid_plan_reference')
            # References only: no client-supplied plan becomes trading authority.
            published = read(self.root,'04_research/company_research/daily_decision.json')
            decision = json.loads(published)
            if payload.get('snapshot_id')!=sha(published) or not any(all(p.get(k)==v for k,v in plan.items()) for p in decision.get('plan_continuity',{}).get('plans',[])):
                raise FeedbackError('plan_reference_changed',status=409)
        string_keys = ('ticker','side','status','shares','amount','amount_mode','fee_status','fees','date','time','notes','order_type','order_price','stop_price','time_in_force','remaining','linked_order','cash')
        if any(not isinstance(f.get(k), str) or len(f[k]) > (1500 if k == 'notes' else 200) for k in string_keys):
            raise FeedbackError('invalid_request_fields')
        if f['status'] not in {'skipped','pending','partial','filled','cancelled','account'} or f['side'] not in {'buy','sell'}:
            raise FeedbackError('invalid_status')
        f['ticker'] = f['ticker'].strip().upper()
        if f['status'] != 'account' and SYMBOL.fullmatch(f['ticker']) is None:
            raise FeedbackError('invalid_ticker')
        try:
            event = datetime.strptime(f['date'] + ' ' + (f['time'] or '00:00'), '%Y-%m-%d %H:%M').replace(tzinfo=ET)
        except ValueError: raise FeedbackError('invalid_event_date')
        now = datetime.now(ET)
        if event.date() > now.date() or (f['time'] and event > now): raise FeedbackError('future_event')
        if any(type(f.get(k)) is not bool for k in ('prior_partial','inventory_complete')): raise FeedbackError('invalid_flags')
        account = validate_account_state(json.loads(read(self.root, ACCOUNT)))
        old_positions = rows(read(self.root, POSITIONS))
        positions = {r['ticker']: dict(r) for r in old_positions}
        orders = json.loads(read(self.root, ORDERS))
        missing, writes = [], {}
        changes = {'cash_before': account['cash_available'], 'cash_after': account['cash_available'],
                   'holdings_before': [{'ticker':r['ticker'],'shares':r['shares_optional']} for r in old_positions]}
        def need(key, label, **kwargs):
            if not f[key].strip(): missing.append(label); return None
            return dec(f[key], key, **kwargs)
        status, ticker = f['status'], f['ticker']
        fee = qty = price = None
        if status in {'filled','partial'}:
            qty, amount = need('shares','股数',integer=True), need('amount','成交金额')
            if f['fee_status'] == 'unknown': missing.append('费用')
            elif f['fee_status'] == 'known': fee = need('fees','费用',zero=True)
            else: raise FeedbackError('invalid_fee_status')
            if f['amount_mode'] not in {'price','gross','net'}: raise FeedbackError('invalid_amount_mode')
            if f.get('not_in_account') is not True: missing.append('确认这笔成交尚未计入当前账户')
            prior_dates = [r.get('fill_date','') for r in rows(read(self.root,CONFIRMED,optional=True)) if r.get('canonical_state_applied')=='yes']
            if prior_dates and f['date'] < max(prior_dates):
                missing.append('较晚成交已计入账户；先完整账户核对，避免倒序重复应用')
            if f['order_type'] not in {'LIMIT','MARKET','STOP','STOP_LIMIT'}: raise FeedbackError('invalid_order_type')
            if status == 'partial':
                need('remaining','剩余挂单股数',integer=True)
                if not f['linked_order']: missing.append('已记录的对应订单编号')
            if qty and amount and fee is not None:
                gross = amount * qty if f['amount_mode'] == 'price' else amount
                if f['amount_mode'] == 'net': gross = amount - fee if f['side']=='buy' else amount + fee
                if gross <= 0: raise FeedbackError('net_amount_less_than_fees')
                price = gross / qty
                before = dec(positions[ticker]['shares_optional'], 'held', integer=True) if ticker in positions else Decimal(0)
                after = before + qty if f['side']=='buy' else before - qty
                if after < 0: raise FeedbackError('insufficient_recorded_shares')
                current_cash = dec(account['cash_available'],'cash',zero=True)
                post_cash = cash(current_cash - gross - fee if f['side']=='buy' else current_cash + gross - fee)
                if post_cash < dec(account['cash_reserved'],'reserved',zero=True): raise FeedbackError('insufficient_recorded_cash')
                changes.update(cash_after=float(post_cash), ticker=ticker, shares_before=int(before), shares_after=int(after), fill_price=float(price), fees=float(fee))
                if after == 0: positions.pop(ticker)
                else:
                    previous = positions.get(ticker)
                    entry = (dec(previous['entry_price'],'entry') * before + gross + fee) / after if previous and f['side']=='buy' else price + fee / qty if not previous else dec(previous['entry_price'],'entry')
                    positions[ticker] = {**(previous or self.new_position(ticker,f['date'],entry)), 'shares_optional':str(after), 'entry_price':str(entry.quantize(Decimal('.000001')))}
                account.update(cash_available=float(post_cash), cash_basis='ledger_estimate', last_updated=now.isoformat())
        if status == 'pending':
            qty = need('shares','委托股数',integer=True)
            if f['order_type'] not in {'LIMIT','MARKET','STOP','STOP_LIMIT'}: raise FeedbackError('invalid_order_type')
            if f['order_type'] in {'LIMIT','STOP_LIMIT'}: need('order_price','委托限价')
            if f['order_type'] in {'STOP','STOP_LIMIT'}: need('stop_price','触发价')
            if f['time_in_force'] == 'unknown': missing.append('订单有效期')
            elif f['time_in_force'] not in {'DAY','GTC'}: raise FeedbackError('invalid_order_duration')
            if not f['time']: missing.append('挂单时间')
        active = {'open','pending','partial_fill','partially_filled'}
        linked = next((r for r in orders['orders'] if r.get('order_id')==f['linked_order']), None)
        if status in {'filled','partial','cancelled'} and f['linked_order']:
            if linked is None or linked.get('status') not in active: raise FeedbackError('active_order_not_found')
            if status != 'cancelled' and (linked['ticker'] != ticker or linked['side'] != f['side']): raise FeedbackError('order_facts_conflict')
            if status != 'cancelled' and qty:
                remaining = dec(linked.get('remaining_quantity'),'remaining',integer=True)
                if qty > remaining: raise FeedbackError('fill_exceeds_remaining_order')
                new_remaining = remaining - qty
                if status == 'filled' and new_remaining != 0: raise FeedbackError('order_still_has_remaining_shares')
                if status == 'partial' and f['remaining'] and new_remaining != dec(f['remaining'],'remaining',integer=True): raise FeedbackError('remaining_order_conflict')
        if status == 'cancelled':
            if not f['linked_order']: missing.append('对应订单编号')
            if f['prior_partial'] and f.get('partial_recorded') is not True: missing.append('确认撤单前成交已单独计入账户')
            if f.get('terminal_confirmed') is not True: missing.append('确认券商已显示撤单完成')
        if status == 'account':
            if f['date']!=now.date().isoformat(): missing.append('账户核对须是今天的当前观察；历史快照不覆盖当前账户')
            reported_cash = need('cash','现金',zero=True)
            if f.get('account_observed') is not True: missing.append('确认完整账户观察')
            if not isinstance(f.get('holdings'),list) or len(f['holdings']) > 100: raise FeedbackError('invalid_holdings')
            observed = {}
            for r in f['holdings']:
                if not isinstance(r,dict) or not isinstance(r.get('ticker'),str): raise FeedbackError('invalid_holdings')
                symbol = r['ticker'].strip().upper()
                if SYMBOL.fullmatch(symbol) is None or symbol in observed: raise FeedbackError('invalid_holdings')
                shares = dec(r.get('shares'),'holding_shares',integer=True)
                old = positions.get(symbol)
                if not old and not r.get('entry_price'): missing.append(symbol+' 平均成本')
                entry = dec(r['entry_price'],'entry_price') if r.get('entry_price') else dec(old['entry_price'],'entry_price') if old else Decimal(1)
                observed[symbol] = {**(old or self.new_position(symbol,f['date'],entry)), 'shares_optional':str(shares), 'entry_price':str(entry)}
            if f.get('inventory_complete'):
                current_orders=[r for r in orders['orders'] if r.get('status') in active and r.get('record_scope')!='unresolved_historical_reservation']
                if f.get('no_open_orders') is True:
                    if current_orders: missing.append('先核对已记录挂单的终态或成交')
                elif (f.get('orders_match') is not True or not isinstance(f.get('observed_order_ids'),list)
                      or any(not isinstance(v,str) for v in f['observed_order_ids'])
                      or set(f['observed_order_ids'])!={r.get('order_id') for r in current_orders}):
                    missing.append('先逐笔登记挂单，然后确认券商完整列表与已记录订单一致')
            if not missing:
                positions = observed
                account.update(cash_available=float(reported_cash), cash_basis='owner_recorded',last_updated=now.isoformat())
                changes['cash_after'] = float(reported_cash)
                if f['inventory_complete']:
                    orders['complete'], orders['as_of'] = True, now.isoformat()
                    shown=[] if f.get('no_open_orders') else [r for r in orders['orders'] if r.get('status') in active and r.get('record_scope')!='unresolved_historical_reservation']
                    orders['current_inventory_observation'] = {'as_of':orders['as_of'],'complete':True,'orders_shown':shown,
                        'source':{'path':JOURNAL,'sha256':sha(encoded(f))}}
                    # No-orders observation never erases unresolved historical reservations.
                else: orders['complete'] = False
                orders.pop('broker_balance_observation', None)
        changes['holdings_after'] = [{'ticker':r['ticker'],'shares':r['shares_optional']} for r in positions.values()]
        if not missing and status in {'filled','partial','account'}:
            market = {r['ticker']:r for r in rows(read(self.root, MARKET,optional=True))}
            valuation_complete = all(r['ticker'] in market and market[r['ticker']].get('data_quality_label')=='ok' for r in positions.values())
            total = cash(dec(account['cash_available'],'cash',zero=True)+sum((dec(market[r['ticker']]['last_price'],'mark')*dec(r['shares_optional'],'shares') for r in positions.values()),Decimal(0))) if valuation_complete else dec(account['account_total_value'],'total')
            account['account_total_value'] = float(total)
            validate_account_state(account)
            changes['valuation_complete'] = valuation_complete
            fields = next(csv.reader(io.StringIO(read(self.root,POSITIONS).decode())))
            writes[POSITIONS], writes[ACCOUNT] = csv_bytes(list(positions.values()),fields), encoded(account)
        # Do not publish changes from an incomplete submission.
        return f, sorted(set(missing)), changes, writes, orders, now, price

    @staticmethod
    def new_position(ticker, day, entry):
        return dict(ticker=ticker,entry_date=day,entry_price=str(entry),position_pct='0',shares_optional='',
                    thesis='Owner-reported holding; thesis review pending',horizon_class='long_horizon',
                    planned_review_date=day,invalidation_rule='Analyst review pending; no automatic exit')

    def preview(self, payload):
        with self.locked(), self.db() as con:
            self.recover(con)
            f, missing, changes, *_ = self.proposal(payload, con)
            if payload.get('correction') and missing:
                raise FeedbackError('complete_account_correction_required', {'missing': missing})
            return dict(missing=missing, changes=None if missing else changes,
                        preview_hash=sha(encoded({'payload':payload,'missing':missing,'changes':changes})))

    def submit(self, payload):
        if not isinstance(payload, dict): raise FeedbackError('invalid_request')
        request_id = payload.get('request_id')
        try: uuid.UUID(request_id)
        except (ValueError, TypeError, AttributeError): raise FeedbackError('invalid_request_id')
        body = encoded(payload).decode()
        with self.locked(), self.db() as con:
            self.recover(con)
            previous = con.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
            if previous:
                if previous['payload'] != body: raise FeedbackError('request_id_reused',status=409)
                return json.loads(con.execute('SELECT body FROM records WHERE id=?',(previous['record_id'],)).fetchone()[0])
            f, missing, changes, writes, orders, now, price = self.proposal(payload, con)
            if payload.get('correction') and missing:
                raise FeedbackError('complete_account_correction_required', {'missing': missing})
            preview_payload = {k:v for k,v in payload.items() if k != 'preview_hash'}
            expected = sha(encoded({'payload':preview_payload,'missing':missing,'changes':changes}))
            if payload.get('preview_hash') != expected: raise FeedbackError('preview_required',status=409)
            rid = payload.get('record_id') or request_id
            old = con.execute('SELECT body FROM records WHERE id=?',(rid,)).fetchone()
            old = json.loads(old[0]) if old else None
            if old and (old['stage'] != 'pending' or payload.get('revision') != old['revision']): raise FeedbackError('record_revision_changed',status=409)
            if payload.get('record_id') and not old: raise FeedbackError('record_not_found',status=404)
            record = dict(id=rid, revision=(old['revision']+1 if old else 1), recorded_at=now.isoformat(),
                feedback=f, missing=missing, plan=payload.get('plan'), snapshot_id=payload.get('snapshot_id'),
                account_version_before=payload['account_version'], event_time_precision='approximate' if f['time'] else 'date_only',
                stage='pending' if missing else 'applied', research_status='queued' if f['status']!='skipped' else 'not_needed',
                production_effect=not missing and f['status']!='skipped', changes=None if missing else changes,
                request_id=request_id, email_sent=False)
            record['email_version_id']=payload.get('email_version_id') or (old.get('email_version_id') if old else None)
            record['correction'] = payload.get('correction')
            if not missing:
                status = f['status']
                if status=='pending':
                    oid = 'dashboard-'+rid
                    orders['orders'].append(dict(order_id=oid,ticker=f['ticker'],side=f['side'],quantity=int(f['shares']),remaining_quantity=int(f['shares']),
                        order_type=f['order_type'],time_in_force=f['time_in_force'],session_date=f['date'],status='open',
                        limit_price=float(f['order_price']) if f['order_price'] else None,stop_price=float(f['stop_price']) if f['stop_price'] else None,
                        submitted_at=datetime.strptime(f['date']+' '+f['time'],'%Y-%m-%d %H:%M').replace(tzinfo=ET).isoformat(),source='owner_dashboard'))
                    record['order_id'] = oid
                elif status in {'filled','partial','cancelled'} and f['linked_order']:
                    linked = next(r for r in orders['orders'] if r.get('order_id')==f['linked_order'])
                    linked['remaining_quantity'] = int(f['remaining']) if status=='partial' else 0
                    linked['status'] = 'partial_fill' if status=='partial' else 'cancelled' if status=='cancelled' else 'filled'
                if status in {'pending','filled','partial','cancelled'}:
                    orders['complete'] = False
                    orders.pop('current_inventory_observation',None)
                    orders.pop('broker_balance_observation',None)
                if status!='skipped': writes[ORDERS] = encoded(orders)
                if status in {'filled','partial'}:
                    eid = 'dashboard-'+rid
                    row = {field:'' for field in EXECUTION_FIELDS}
                    row.update(execution_id=eid,ticker=f['ticker'],side=f['side'],shares=f['shares'],order_type=f['order_type'],
                        order_status='partial_fill' if status=='partial' else 'filled',fill_date=f['date'],fill_price=str(price),fees=f['fees'],
                        shares_before=str(changes['shares_before']),shares_after=str(changes['shares_after']),cash_before=str(changes['cash_before']),
                        cash_after=str(changes['cash_after']),account_total_after='',source='owner_dashboard',
                        notes='actual filled shares; '+f['notes']+'; record='+rid)
                    validate_execution_row(row)
                    ledger = rows(read(self.root,LEDGER,optional=True))
                    if any(r['execution_id']==eid for r in ledger): raise FeedbackError('execution_already_recorded',status=409)
                    writes[LEDGER] = csv_bytes(ledger+[row],EXECUTION_FIELDS)
                    confirmed = {**row, 'validation_status':'confirmed_fill','reconciliation_eligible':'yes','canonical_state_applied':'yes',
                        'financial_values_source':'owner_fill_and_ledger_cash','positions_sha256_at_intake':sha(read(self.root,POSITIONS)),
                        'account_state_sha256_at_intake':sha(read(self.root,ACCOUNT))}
                    writes[CONFIRMED] = csv_bytes(rows(read(self.root,CONFIRMED,optional=True))+[confirmed],CONFIRMED_FIELDS)
                    recon = {field:'' for field in RECONCILIATION_FIELDS}
                    recon.update(execution_id=eid,ticker=f['ticker'],execution_status=row['order_status'],reconciliation_status='applied',canonical_state_applied='yes',
                        shares_before=row['shares_before'],actual_shares_filled=row['shares'],shares_after=row['shares_after'],fill_price=row['fill_price'],fees=row['fees'],
                        cash_before=row['cash_before'],cash_before_source='canonical_account_state',calculated_cash_after=row['cash_after'],selected_cash_after=row['cash_after'],
                        cash_reconciliation_difference='0',positions_sha256_before=sha(read(self.root,POSITIONS)),positions_sha256_after=sha(writes[POSITIONS]),
                        account_sha256_before=sha(read(self.root,ACCOUNT)),account_sha256_after=sha(writes[ACCOUNT]),reference_price_timestamp=now.isoformat(),
                        notes='Human facts applied by durable dashboard coordinator; public valuation and research are separate.')
                    writes[RECONCILED] = csv_bytes(rows(read(self.root,RECONCILED,optional=True))+[recon],RECONCILIATION_FIELDS)
                    record['execution_id'] = eid
                if status=='account':
                    observation='06_execution_records/dashboard_feedback.local/observations/'+rid+'-v'+str(record['revision'])+'.json'
                    observed=encoded({'record_id':rid,'revision':record['revision'],'observed_at':now.isoformat(),'feedback':f,'correction':record['correction']})
                    writes[observation]=observed
                    if f['inventory_complete']:
                        orders['current_inventory_observation']['source']={'path':observation,'sha256':sha(observed)}
                        writes[ORDERS]=encoded(orders)
                    writes[MANUAL] = encoded(dict(schema_version='phase5r_owner_snapshot_v1',owner_snapshot=True,source_note='Owner confirmed full account in dashboard',
                        observed_at=now.isoformat(),positions_sha256_before=sha(read(self.root,POSITIONS)),positions_sha256_after=sha(writes[POSITIONS]),
                        account_sha256_before=sha(read(self.root,ACCOUNT)),account_sha256_after=sha(writes[ACCOUNT]),confirmed_execution_sha256=sha(read(self.root,CONFIRMED)) if (self.root/CONFIRMED).exists() else None))
                    manual=json.loads(writes[MANUAL])
                    manual.update(source={'path':observation,'sha256':sha(observed)},correction=record['correction'])
                    writes[MANUAL]=encoded(manual)
            final = record['stage']
            record['stage'],record['final_stage'] = 'applying',final
            con.execute('INSERT OR REPLACE INTO records VALUES(?,?)',(rid,encoded(record).decode()))
            con.execute('INSERT INTO events(record_id,body) VALUES(?,?)',(rid,encoded(record).decode()))
            con.execute('INSERT INTO requests VALUES(?,?,?,?)',(request_id,body,rid,'prepared'))
            # First publish a planning barrier, including crash during account transition.
            for rel, content in writes.items():
                con.execute('INSERT INTO writes VALUES(?,?,?,?)',(request_id,rel,read(self.root,rel,optional=True),content))
            con.commit()
            self.recover(con)
            result = json.loads(con.execute('SELECT body FROM records WHERE id=?',(rid,)).fetchone()[0])
            self.wake.set()
            return result

    def retry(self, record_id):
        with self.locked(), self.db() as con:
            row = con.execute('SELECT body FROM records WHERE id=?',(record_id,)).fetchone()
            if row is None: raise FeedbackError('record_not_found',status=404)
            r = json.loads(row[0])
            if r.get('research_status') not in {'failed','degraded'}: raise FeedbackError('research_not_retryable',status=409)
            r['research_status']='queued'; r.pop('error',None)
            con.execute('UPDATE records SET body=? WHERE id=?',(encoded(r).decode(),record_id)); con.commit()
        self.wake.set()
        return r

    def reviews(self):
        """Analyst work is a separate queue, never a deterministic refresh result."""
        with self.db() as con:
            result = [json.loads(r['body']) for r in con.execute('SELECT body FROM review_requests ORDER BY rowid DESC LIMIT 500')]
        for request in result:
            receipt = request.get('receipt')
            if receipt:
                try:
                    request['receipt_verified'] = sha(read(self.root,receipt['path'])) == receipt['sha256']
                except (FeedbackError,OSError):
                    request['receipt_verified'] = False
        return result

    def request_review(self, payload):
        if not isinstance(payload,dict): raise FeedbackError('invalid_request')
        try: uuid.UUID(payload.get('request_id'))
        except (ValueError,TypeError,AttributeError): raise FeedbackError('invalid_request_id')
        if set(payload) != {'request_id','account_version','snapshot_id','tickers','question'}:
            raise FeedbackError('invalid_review_request')
        question,tickers = payload['question'],payload['tickers']
        if (not isinstance(question,str) or not 5 <= len(question.strip()) <= 2000
                or not isinstance(tickers,list) or len(tickers)>20
                or any(not isinstance(t,str) or SYMBOL.fullmatch(t) is None for t in tickers)
                or len(set(tickers))!=len(tickers)):
            raise FeedbackError('invalid_review_request')
        body = encoded(payload).decode()
        with self.locked(),self.db() as con:
            self.recover(con)
            previous = con.execute('SELECT payload,body FROM review_requests WHERE id=?',(payload['request_id'],)).fetchone()
            if previous:
                if previous['payload'] != body: raise FeedbackError('request_id_reused',status=409)
                return json.loads(previous['body'])
            if payload['account_version'] != version(self.root): raise FeedbackError('account_version_changed',status=409)
            if payload['snapshot_id'] != sha(read(self.root,'04_research/company_research/daily_decision.json')):
                raise FeedbackError('review_snapshot_changed',status=409)
            now = datetime.now(ET).isoformat()
            request = dict(id=payload['request_id'],status='queued',question=question.strip(),tickers=tickers,
                account_version=payload['account_version'],snapshot_id=payload['snapshot_id'],created_at=now,updated_at=now,
                production_effect=False,email_sent=False,trade_placed=False)
            con.execute('INSERT INTO review_requests VALUES(?,?,?)',(request['id'],body,encoded(request).decode()))
            con.execute('INSERT INTO review_events(request_id,body) VALUES(?,?)',(request['id'],encoded(request).decode()))
            con.commit()
            return request

    def review_events(self, request_id):
        with self.db() as con:
            if not con.execute('SELECT 1 FROM review_requests WHERE id=?',(request_id,)).fetchone():
                raise FeedbackError('review_request_not_found',status=404)
            return [json.loads(r['body']) for r in con.execute('SELECT body FROM review_events WHERE request_id=? ORDER BY sequence',(request_id,))]

    @staticmethod
    def _save_review(con, request):
        request['updated_at'] = datetime.now(ET).isoformat()
        body = encoded(request).decode()
        con.execute('UPDATE review_requests SET body=? WHERE id=?',(body,request['id']))
        con.execute('INSERT INTO review_events(request_id,body) VALUES(?,?)',(request['id'],body))
        con.commit()
        return request

    def claim_review(self, request_id, *, rebind_current=False):
        """Local analyst admission; the browser cannot claim or complete a review."""
        with self.locked(),self.db() as con:
            self.recover(con)
            row = con.execute('SELECT body FROM review_requests WHERE id=?',(request_id,)).fetchone()
            if not row: raise FeedbackError('review_request_not_found',status=404)
            request = json.loads(row['body'])
            if request['status']=='completed': raise FeedbackError('review_already_completed',status=409)
            current = version(self.root)
            binding = request.get('review_account_version',request['account_version'])
            if current != binding and not rebind_current:
                raise FeedbackError('review_account_changed',{'account_version':current},409)
            snapshot = sha(read(self.root,'04_research/company_research/daily_decision.json'))
            if (request['status']=='running' and request.get('review_account_version')==current
                    and request.get('review_snapshot_id')==snapshot): return request
            request.update(status='running',review_account_version=current,review_snapshot_id=snapshot,
                rebound_from_account_version=binding if current!=binding else None)
            request.pop('receipt',None)
            return self._save_review(con,request)

    def finish_review(self, request_id, status, receipt_path):
        if status not in {'blocked','completed'}: raise FeedbackError('invalid_review_status')
        path = Path(receipt_path)
        if path.is_absolute():
            try: path = path.relative_to(self.root)
            except ValueError: raise FeedbackError('invalid_review_receipt_path')
        relative = path.as_posix()
        if not relative.startswith('08_reviews/analyst_followthrough.local/') or path.suffix!='.json':
            raise FeedbackError('invalid_review_receipt_path')
        with self.locked(),self.db() as con:
            self.recover(con)
            row = con.execute('SELECT body FROM review_requests WHERE id=?',(request_id,)).fetchone()
            if not row: raise FeedbackError('review_request_not_found',status=404)
            request = json.loads(row['body'])
            if request['status']=='completed': raise FeedbackError('review_already_completed',status=409)
            if request['status']!='running': raise FeedbackError('review_must_be_claimed',status=409)
            raw = read(self.root,relative)
            receipt = json.loads(raw)
            summary = receipt.get('summary') if isinstance(receipt,dict) else None
            if (not isinstance(receipt,dict) or receipt.get('schema_version')!='equity_dashboard_review_receipt_v1'
                    or receipt.get('request_id')!=request_id
                    or receipt.get('account_version')!=request['review_account_version']
                    or receipt.get('analysis_completed') is not (status=='completed')
                    or not isinstance(summary,str) or not 1 <= len(summary.strip()) <= 2000
                    or receipt.get('email_sent') is not False or receipt.get('trade_placed') is not False):
                raise FeedbackError('invalid_analyst_review_receipt')
            def valid_lines(value):
                return (isinstance(value,list) and 0<len(value)<=20
                        and all(isinstance(v,str) and 0<len(v.strip())<=2000 for v in value))
            if status=='completed':
                if version(self.root)!=request['review_account_version']:
                    request.update(status='blocked',blocker='account_changed_during_review',
                        rejected_receipt={'path':relative,'sha256':sha(raw)})
                    self._save_review(con,request)
                    raise FeedbackError('review_account_changed',status=409)
                decision_raw = read(self.root,'04_research/company_research/daily_decision.json')
                if receipt.get('decision_sha256')!=sha(decision_raw) or not valid_lines(receipt.get('conclusions')):
                    raise FeedbackError('review_conclusion_or_decision_unverified')
                sources = receipt.get('sources')
                if (not isinstance(sources,list) or not 0<len(sources)<=50
                        or any(not isinstance(s,dict) or set(s)!={'path','sha256'} or not isinstance(s['path'],str)
                               or not isinstance(s['sha256'],str) for s in sources)):
                    raise FeedbackError('review_sources_unverified')
                if any(sha(read(self.root,s['path']))!=s['sha256'] for s in sources):
                    raise FeedbackError('review_sources_unverified')
                decision = json.loads(decision_raw)
                hashes = decision.get('workflow_integrity',{}).get('input_hashes',{})
                from workflow_integrity import WORKFLOW_INPUTS
                if (not isinstance(hashes,dict) or set(hashes)!=WORKFLOW_INPUTS
                        or any(hashes[p]!=(sha(read(self.root,p)) if (self.root/p).exists() else None) for p in WORKFLOW_INPUTS)):
                    raise FeedbackError('review_publication_unverified',status=409)
                try: verify_publication(self.root,decision)
                except (OSError,ValueError,KeyError,TypeError,InvalidOperation):
                    raise FeedbackError('review_publication_unverified',status=409)
            elif not valid_lines(receipt.get('dependencies')):
                raise FeedbackError('review_dependencies_required')
            request.update(status=status,receipt=dict(path=relative,sha256=sha(raw),summary=summary.strip()))
            request.pop('blocker',None)
            return self._save_review(con,request)

    def work_once(self):
        with self.locked(), self.db() as con:
            self.recover(con)
            pending = [json.loads(r[0]) for r in con.execute('SELECT body FROM records')]
            pending = [r for r in pending if r['research_status'] in {'queued','running'} and r['stage'] in {'pending','applied'}]
            if not pending: return False
            for r in pending:
                r['research_status']='running'
                con.execute('UPDATE records SET body=? WHERE id=?',(encoded(r).decode(),r['id']))
            con.commit()
            if not self.refresh: return False
            log = self.root / '07_automation/dashboard.local/refresh.log'
            log.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            # Only the existing public research pipeline; no sender or broker.
            script = self.root / '09_scripts/equity_research/run_daily_refresh.py'
            tickers = {r['ticker'] for r in rows(read(self.root,POSITIONS))}
            markets = {r['ticker'] for r in rows(read(self.root,MARKET,optional=True)) if r.get('data_quality_label')=='ok'}
            mode = 'reuse_validated_snapshot' if tickers <= markets else 'fetch'
            started=datetime.now(ET).replace(microsecond=0)
            try:
                with log.open('ab') as handle:
                    log.chmod(0o600)
                    if mode=='reuse_validated_snapshot':
                        projection=subprocess.run([sys.executable,str(script.with_name('run_full_universe_market_data.py')),
                            '--recompose-current-coverage','--no-lock'],cwd=self.root,stdout=handle,stderr=subprocess.STDOUT,timeout=60)
                        if projection.returncode: mode='fetch'
                    launcher=Path('/Users/messssi/Library/Application Support/EquityResearch/bin/dailyrefresh_launcher.py')
                    command=([sys.executable,str(launcher),'--feedback-refresh','--market-snapshot-mode',mode]
                        if self.root==Path('/Users/messssi/LocalRuntime/equity') else [sys.executable,str(script),'--run','--no-lock','--market-snapshot-mode',mode])
                    completed = subprocess.run(command,cwd=self.root,
                                               stdout=handle,stderr=subprocess.STDOUT,timeout=1800)
                refresh_path = self.root / '00_project_control/run_logs/daily_refresh_state.local.json'
                state = json.loads(refresh_path.read_text())
                d = json.loads(read(self.root,'04_research/company_research/daily_decision.json'))
                hashes = d.get('workflow_integrity',{}).get('input_hashes',{})
                bound = all(hashes.get(p)==sha(read(self.root,p)) for p in (ACCOUNT,POSITIONS,ORDERS,PENDING))
                if not bound or state.get('email_attempted') is not False or datetime.fromisoformat(state['started_at'])<started:
                    raise ValueError('refresh_publication_not_bound')
                verify_publication(self.root,d)
                outcome = 'passed' if completed.returncode==0 and state.get('outcome')=='passed' else 'failed' if state.get('hard_failures') or state.get('decision_created') is not True else 'degraded'
                error = None if outcome=='passed' else 'public_research_degraded'
            except (OSError,ValueError,KeyError,TypeError,InvalidOperation,subprocess.TimeoutExpired):
                outcome,error = 'failed','research_refresh_failed'
            for r in pending:
                r['research_status'],r['research_completed_at'],r['error'] = outcome,datetime.now(ET).isoformat(),error
                con.execute('UPDATE records SET body=? WHERE id=?',(encoded(r).decode(),r['id']))
                con.execute('INSERT INTO events(record_id,body) VALUES(?,?)',(r['id'],encoded(r).decode()))
            con.commit()
            return True

    def worker(self):
        while True:
            self.wake.wait(15); self.wake.clear()
            try: self.work_once()
            except (FeedbackError,OSError,sqlite3.Error): pass  # Retain outbox; retry after lock release/restart.
