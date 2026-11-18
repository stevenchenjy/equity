"""Validate a retained Chase activity window and reconcile its shares to a broker observation.

Statement amounts and lot basis have broker reporting precision. These rows do
not have the precision or fee evidence needed to replay every row as a manual
execution. Each window is retained in full and identified by its content hash.
"""
from collections import Counter, defaultdict
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import io
import json
from pathlib import Path
import re

SOURCE_DIR = '06_execution_records/dashboard_feedback.local/chase_statement_sources'
STATEMENT_INDEX = '06_execution_records/dashboard_feedback.local/chase_statements.json'
ACTIVITY_LEDGER = '06_execution_records/chase_transactions.local.csv'
CENT = Decimal('.01')
COLUMNS = ('display_row', 'trade_date_et', 'transaction_type', 'security_or_broker_code',
           'broker_display_description', 'settlement_date', 'settlement_status_displayed',
           'price_usd_displayed', 'quantity_displayed', 'amount_usd_displayed')


def verify(condition, message):
    if not condition:
        raise ValueError(message)


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def checked_source(root, digest, suffix):
    verify(isinstance(digest, str) and re.fullmatch('[a-f0-9]{64}', digest), 'invalid source hash')
    path = Path(SOURCE_DIR) / (digest + suffix)
    full = root / path
    verify(full.resolve() == root.resolve() / path and full.is_file() and full.stat().st_size <= 8_000_000,
           'statement source unavailable')
    raw = full.read_bytes()
    verify(hashlib.sha256(raw).hexdigest() == digest, 'statement source changed')
    return raw, {'path': str(path), 'sha256': digest}


def verify_snapshot(root, digest, feedback, now, account, old_positions, manual_hash, positions_hash):
    """Return statement metadata for an exact full account snapshot (new cash applied once)."""
    blob, observation_ref = checked_source(root, digest, '.json')
    observation = json.loads(blob)
    verify(observation['schema'] == 'private_brokerage_observation_v1', 'incorrect observation schema')
    chase = observation['accounts']['chase']
    verify(chase['currency'] == 'USD' and chase['account'].startswith('Chase Self-Directed'), 'incorrect broker')
    source = chase['source']
    observed = datetime.fromisoformat(source['positions_and_balances_reported_asof_et'])
    orders_time = datetime.fromisoformat(source['order_status_reported_asof_et'])
    prior = datetime.fromisoformat(account['last_updated'])
    verify(prior < observed <= now and orders_time <= now and
           observed.date() == orders_time.date() and observed.date().isoformat() == feedback['date'],
           'broker observation time conflicts with ledger')
    verify(chase['order_status']['working_orders_visible'] == 0 and feedback['no_open_orders'] is True
           and feedback['inventory_complete'] is True and feedback['account_observed'] is True,
           'complete observation of shares and no working orders required')
    tx = chase['transactions']
    raw, activity_ref = checked_source(root, tx['sha256'], '.csv')
    reader = csv.DictReader(io.StringIO(raw.decode()))
    activities = list(reader)
    verify(tuple(reader.fieldnames or ()) == COLUMNS and len(activities) == tx['broker_reported_and_captured_row_count']
           and Counter(r['transaction_type'] for r in activities) == tx['types'], 'statement coverage changed')
    dates = [date.fromisoformat(r['trade_date_et']) for r in activities]
    verify(dates and dates == sorted(dates, reverse=True) and dates[-1].isoformat() == tx['first_displayed_trade_date_et']
           and dates[0].isoformat() == tx['last_displayed_trade_date_et'] and dates[-1] <= prior.date()
           and dates[0] <= observed.date(), 'statement date coverage invalid')
    bridge = chase['read_only_reconciliation']
    verify(bridge['approved_snapshot']['sha256'] == manual_hash and bridge['approved_positions']['sha256'] == positions_hash
           and datetime.fromisoformat(bridge['approved_observation_at_et']) == prior, 'statement bridge baseline changed')
    quantities = {row['ticker']: Decimal(row['shares_optional']) for row in old_positions}
    daily = defaultdict(Counter)
    cash_delta = Decimal(0)
    for i, (row, day) in enumerate(zip(activities, dates), 1):
        verify(row['display_row'] == str(i), 'statement display sequence changed')
        if day <= prior.date():
            continue
        kind = row['transaction_type']
        amount = Decimal(row['amount_usd_displayed'].replace(',', ''))
        verify(amount.is_finite(), 'invalid signed transaction amount')
        if kind in ('DBS', 'WDL') and row['security_or_broker_code'] == 'QACDS':
            pass  # Internal movement between cash and the Chase deposit sweep.
        elif kind in ('Buy', 'Sell', 'Reinvest', 'BNK', 'Interest', 'Dividend'):
            cash_delta += amount
        else:
            raise ValueError('unclassified cash movement in statement bridge')
        if kind in ('Buy', 'Sell', 'Reinvest'):
            qty = Decimal(row['quantity_displayed'].replace(',', ''))
            verify(qty.is_finite() and (qty < 0 if row['transaction_type'] == 'Sell' else qty > 0),
                   'invalid signed trade quantity')
            daily[day][row['security_or_broker_code']] += qty
    opened = {}
    for day, delta in sorted(daily.items()):
        for symbol, qty in delta.items():
            previous = quantities.get(symbol, Decimal(0))
            quantities[symbol] = previous + qty
            verify(quantities[symbol] >= 0, 'negative end-of-day shares in statement')
            if not previous and quantities[symbol] > 0:
                opened[symbol] = day.isoformat()
    positions = {r['ticker']: r for r in chase['positions']}
    proposed = {r['ticker']: r for r in feedback['holdings']}
    verify(len(positions) == len(chase['positions']) and set(positions) == set(proposed) ==
           {key for key, value in quantities.items() if value}, 'holding scope differs from statement')
    for symbol, item in positions.items():
        qty = Decimal(item['quantity_shares'])
        price = Decimal(item['displayed_unit_price_usd'])
        verify(qty == Decimal(proposed[symbol]['shares']) == quantities[symbol] and qty > 0
               and qty == qty.quantize(Decimal('.00001')) and price > 0, 'holding quantity differs')
        verify(money(qty * price) == Decimal(item['market_value_usd'])
               and money(qty * Decimal(proposed[symbol]['entry_price'])) == Decimal(item['cost_usd']),
               'holding cost or mark differs')
    balances = chase['balances_usd']
    securities = sum(Decimal(r['market_value_usd']) for r in positions.values())
    verify(Decimal(str(account['cash_available'])) + cash_delta == Decimal(feedback['cash']) == Decimal(balances['cash_available_to_trade']) ==
           Decimal(balances['cash_and_sweep_funds']) and securities == Decimal(balances['positions_market_value_excluding_cash_and_sweep'])
           and securities + Decimal(feedback['cash']) == Decimal(balances['account_value']),
           'reported cash and securities do not reconcile')
    summary = {'observation': observation_ref, 'activity': activity_ref, 'account': chase['account'],
               'account_as_of': observed.isoformat(), 'orders_as_of': orders_time.isoformat(),
               'starting_ledger_as_of': prior.isoformat(), 'starting_ledger_cash': str(account['cash_available']),
               'signed_cash_change_excluding_internal_sweeps': str(cash_delta), 'rows': len(activities),
               'first_date': dates[-1].isoformat(), 'last_date': dates[0].isoformat(),
               'rows_after_starting_ledger_date': sum(d > prior.date() for d in dates),
               'types': dict(Counter(r['transaction_type'] for r in activities)),
               'account_value': balances['account_value'], 'available_to_trade': balances['cash_available_to_trade'],
               'available_to_withdraw': balances['cash_available_to_withdraw'], 'unsettled_proceeds': balances['unsettled_trades_proceeds'],
               'current_position_values': {s: r['market_value_usd'] for s, r in positions.items()}, 'opened_dates': opened}
    return summary


def snapshot_context(root, digest, feedback, now, account, old_positions, manual_hash, positions_hash):
    try:
        return verify_snapshot(root, digest, feedback, now, account, old_positions, manual_hash, positions_hash)
    except (KeyError, TypeError, ValueError, InvalidOperation, OSError) as exc:
        raise ValueError('invalid retained Chase statement: ' + str(exc)) from exc


def activity_register(root, windows):
    """Merge windows by stable displayed economic fields and within-window occurrence.

    Pending labels and display row numbers may change at settlement. Keep the
    complete immutable source for every observation. Indistinguishable rows are
    retained with the maximum multiplicity observed together in a window.
    """
    register = {}
    for window in windows:
        raw, ref = checked_source(root, window['activity']['sha256'], '.csv')
        reader = csv.DictReader(io.StringIO(raw.decode()))
        verify(tuple(reader.fieldnames or ()) == COLUMNS, 'incorrect activity schema')
        occurrences = Counter()
        for row in reader:
            key = [window['account'], row['trade_date_et'], row['transaction_type'], row['security_or_broker_code']]
            reference = re.search(r'ROME:\s*([A-Z0-9]+)', row['broker_display_description'])
            key.append(reference[1] if reference else '')
            for field in ('price_usd_displayed', 'quantity_displayed', 'amount_usd_displayed'):
                value = row[field]
                key.append(format(Decimal(value.replace(',', '')).normalize(), 'f') if value not in ('', '--') else '')
            event_hash = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()
            occurrences[event_hash] += 1
            identity = event_hash + '-' + str(occurrences[event_hash])
            first = register.get(identity, {}).get('first_statement_sha256', ref['sha256'])
            register[identity] = {'activity_id': identity, 'first_statement_sha256': first,
                                  'latest_statement_sha256': ref['sha256'], **row}
    out = io.StringIO(newline='')
    fields = ['activity_id', 'first_statement_sha256', 'latest_statement_sha256', *COLUMNS]
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(sorted(register.values(), key=lambda r: r['trade_date_et'], reverse=True))
    return out.getvalue().encode()
