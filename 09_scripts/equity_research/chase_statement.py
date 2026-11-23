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
DISPLAY_DESCRIPTION_LIMIT = 127
ORDER_NUMBER = re.compile(r'[A-Z0-9]{1,32}(?:-[1-9][0-9]{0,5})?')

COLUMNS = ('display_row', 'trade_date_et', 'transaction_type', 'security_or_broker_code',
           'broker_display_description', 'settlement_date', 'settlement_status_displayed',
           'price_usd_displayed', 'quantity_displayed', 'amount_usd_displayed')

def immediate_order_revision(predecessor, successor):
    """A revision changes an observation, never establishes a cancellation/fill."""
    if not isinstance(predecessor, str) or not isinstance(successor, str):
        return False
    if ORDER_NUMBER.fullmatch(predecessor) is None or ORDER_NUMBER.fullmatch(successor) is None:
        return False
    old = predecessor.split('-', 1)
    new = successor.split('-', 1)
    return old[0] == new[0] and len(new) == 2 and int(new[1]) == (int(old[1]) if len(old) == 2 else 0) + 1


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


def verified_working_orders(source, feedback, observed):
    verify(feedback['inventory_complete'] is True and feedback['account_observed'] is True,
           'complete observation of shares and working orders required')
    count = source['working_orders_visible']
    terminal = {'Executed', 'Canceled', 'Cancelled', 'Expired', 'Rejected'}
    verify(type(count) is int and count >= 0, 'invalid Chase working order count')
    if count == 0:
        verify(feedback['no_open_orders'] is True and not source.get('working_orders')
               and ('rows_visible' not in source or source['rows_visible'] == len(source['visible_orders']))
               and all(row.get('broker_status') in terminal for row in source.get('visible_orders', [])),
               'zero working orders must agree with the observed inventory')
        return []

    # Preserve the full All orders observation separately. Only fully working
    # whole-share, dated sell limits are admitted from this snapshot surface.
    visible, working = source['visible_orders'], source['working_orders']
    verify(source['filters'] == 'All orders'
           and isinstance(visible, list) and isinstance(working, list)
           and source['rows_visible'] == len(visible) and count == len(working)
           and feedback['no_open_orders'] is False and feedback['orders_match'] is True,
           'complete Chase working-order evidence required')
    visible_ids = set()
    visible_open = {}
    for row in visible:
        number = row.get('broker_order_number', row.get('order_number'))
        status = row['broker_status']
        verify(isinstance(number, str) and ORDER_NUMBER.fullmatch(number) is not None
               and number not in visible_ids and status in terminal | {'Open'},
               'Chase order list identity or status is unverified')
        visible_ids.add(number)
        if status == 'Open':
            visible_open[number] = row

    orders = {}
    for row in working:
        number, ticker = row['broker_order_number'], row['ticker']
        quantity, remaining = Decimal(row['quantity']), Decimal(row['remaining_quantity'])
        limit = Decimal(row['limit_price_usd'])
        submitted = datetime.fromisoformat(row['order_time_displayed_et'])
        expiry = date.fromisoformat(row['expiration_date'])
        verify(number in visible_open and number not in orders and ticker == visible_open[number]['ticker']
               and re.fullmatch('[A-Z][A-Z0-9.-]{0,11}', ticker) is not None
               and row['broker_status'] == 'Open' and row['side'] == 'Sell' and row['order_type'] == 'Limit'
               and row['time_in_force'] == 'GTD' and row['order_time_precision'] == 'minute'
               and submitted.tzinfo is not None and submitted <= observed
               and submitted.date() <= observed.date() < expiry
               and quantity.is_finite() and 0 < quantity <= 1_000_000_000
               and quantity == remaining == quantity.to_integral_value()
               and limit.is_finite() and 0 < limit <= 1_000_000_000 and limit == money(limit),
               'Chase working sell limit facts are incomplete or unsupported')
        predecessor = row.get('replaces_broker_order_number')
        predecessor_hash = row.get('replaces_order_sha256')
        if predecessor is not None or predecessor_hash is not None:
            verify(immediate_order_revision(predecessor, number)
                   and isinstance(predecessor_hash, str) and re.fullmatch('[a-f0-9]{64}', predecessor_hash),
                   'Chase order revision requires an exact immediate predecessor binding')
        orders[number] = dict(order_id='chase-' + number, broker_order_reference=number,
                              ticker=ticker, status='open', side='sell', order_type='LIMIT',
                              quantity=int(quantity), remaining_quantity=int(remaining),
                              limit_price=float(limit), stop_price=None, time_in_force='GTD',
                              session_date=submitted.date().isoformat(), expiration_date=expiry.isoformat(),
                              submitted_at=submitted.isoformat(), submitted_time_precision='approximate',
                              source='chase_statement_observation')
        if predecessor is not None:
            orders[number].update(replaces_order_id='chase-' + predecessor,
                                  replaces_order_sha256=predecessor_hash)
    verified_ids = [row['order_id'] for row in orders.values()]
    verify(set(orders) == set(visible_open) and isinstance(feedback['observed_order_ids'], list)
           and sorted(feedback['observed_order_ids']) == sorted(verified_ids),
           'Chase working order scope does not match the proposed inventory')
    return list(orders.values())


def matched_pending_sale(activities, first_day, pending):
    f = pending['feedback']
    verify(f['status'] == 'filled' and f['side'] == 'sell' and f['amount_mode'] == 'price'
           and f.get('not_in_account') is True and pending.get('production_effect') is False
           and pending.get('changes') is None
           and not f['linked_order'] and not pending.get('correction') and not pending.get('historical_reconciliation')
           and date.fromisoformat(f['date']) > first_day,
           'pending fill is not a supported post-baseline Chase sale')
    matches = [row for row in activities if row['trade_date_et'] == f['date']
               and row['transaction_type'] == 'Sell' and row['security_or_broker_code'] == f['ticker']
               and Decimal(row['quantity_displayed'].replace(',', '')) == -Decimal(f['shares'])
               and Decimal(row['price_usd_displayed'].replace(',', '')) == Decimal(f['amount'])]
    verify(len(matches) == 1, 'pending fill does not match exactly one Chase activity row')
    return {'record_id': pending['id'], 'revision': pending['revision'],
            'activity_display_row': matches[0]['display_row']}


def verify_snapshot(root, digest, feedback, now, account, old_positions, manual_hash, positions_hash, *, pending=None):
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
    working_orders = verified_working_orders(chase['order_status'], feedback, orders_time)
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
    reservations = Counter()
    for order in working_orders:
        reservations[order['ticker']] += order['remaining_quantity']
    verify(all(size <= quantities.get(symbol, 0) for symbol, size in reservations.items()),
           'working sell orders exceed reconciled holdings')
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
    if working_orders:
        summary['working_orders'] = working_orders
    if pending is not None:
        summary['reconciled_pending_sale'] = matched_pending_sale(activities, prior.date(), pending)
    return summary


def snapshot_context(root, digest, feedback, now, account, old_positions, manual_hash, positions_hash, *, pending=None):
    try:
        return verify_snapshot(root, digest, feedback, now, account, old_positions, manual_hash, positions_hash,
                               pending=pending)
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation, OSError) as exc:
        raise ValueError('invalid retained Chase statement: ' + str(exc)) from exc


def activity_register(root, windows):
    """Merge windows by stable displayed economic fields and within-window occurrence.

    Pending labels, display order and the displayed prefix of a routing reference
    may change at settlement. Keep every original observation. Indistinguishable
    rows retain the maximum multiplicity observed together in a window.
    """
    register = {}
    pending_references = defaultdict(dict)
    for window in windows:
        raw, ref = checked_source(root, window['activity']['sha256'], '.csv')
        reader = csv.DictReader(io.StringIO(raw.decode()))
        verify(tuple(reader.fieldnames or ()) == COLUMNS, 'incorrect activity schema')
        occurrences = Counter()
        observations = []
        for row in reader:
            key = [window['account'], row['trade_date_et'], row['transaction_type'], row['security_or_broker_code']]
            description = row['broker_display_description']
            match = re.search(r'ROME:\s*([A-Z0-9]+)', description)
            reference = match[1] if match else ''
            clipped = bool(match and match.end() == len(description) == DISPLAY_DESCRIPTION_LIMIT)
            amounts = []
            for field in ('price_usd_displayed', 'quantity_displayed', 'amount_usd_displayed'):
                value = row[field]
                amounts.append(format(Decimal(value.replace(',', '')).normalize(), 'f') if value not in ('', '--') else '')
            event_hash = hashlib.sha256(json.dumps([*key, reference, *amounts], ensure_ascii=False).encode()).hexdigest()
            occurrences[event_hash] += 1
            identity = event_hash + '-' + str(occurrences[event_hash])
            economics = (*key, *amounts, row['settlement_date'])
            observations.append((identity, economics, reference, clipped, row))

        # An exact row in this window already claims its earlier identity. A
        # shortened reference must not collapse a distinct same-window fill.
        claimed = {identity for identity, *_ in observations if identity in register}
        observed_at = window.get('account_as_of')
        observed_day = datetime.fromisoformat(observed_at).date() if observed_at else None
        for identity, economics, reference, clipped, row in observations:
            settlement = row['settlement_status_displayed']
            if (identity not in register and clipped and observed_day and row['settlement_date']
                    and settlement in ('', 'Settled') and date.fromisoformat(row['settlement_date']) <= observed_day):
                possible = [prior_id for prior_id, full_reference in pending_references[economics].items()
                            if prior_id not in claimed and full_reference != reference and full_reference.startswith(reference)]
                verify(len(possible) <= 1, 'ambiguous truncated Chase transaction reference')
                if possible:
                    identity = possible[0]
            claimed.add(identity)
            if reference and not clipped and settlement == 'Pending':
                pending_references[economics][identity] = reference
            first = register.get(identity, {}).get('first_statement_sha256', ref['sha256'])
            register[identity] = {'activity_id': identity, 'first_statement_sha256': first,
                                  'latest_statement_sha256': ref['sha256'], **row}
    out = io.StringIO(newline='')
    fields = ['activity_id', 'first_statement_sha256', 'latest_statement_sha256', *COLUMNS]
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(sorted(register.values(), key=lambda r: r['trade_date_et'], reverse=True))
    return out.getvalue().encode()
