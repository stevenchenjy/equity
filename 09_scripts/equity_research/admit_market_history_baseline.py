"""Check/admit retained public unadjusted history against existing canonical rows.

Operator owns the external runtime lock. This CLI owns the daily pipeline lock;
it makes no network request, email, broker call or portfolio change.
"""
import argparse
import csv
import json
from pathlib import Path
from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, sha256_file
import market_backup as backup


def admit(root: Path, source: Path, *, apply: bool = False) -> dict:
    with ExclusiveFileLock(root / '00_project_control/run_logs/daily_pipeline.lock'):
        snapshot = root / '03_source_data/equity_research/market_data_snapshot.csv'
        rows = list(csv.DictReader(snapshot.open()))
        value = json.loads(source.read_text())
        tickers = [r['ticker'] for r in rows]
        backup.checked_bundle(value, tickers)
        if value['data_source'] != backup.PRIMARY or value.get('kind') != 'labelled_normalized_provider_observation_not_original_http_response':
            raise backup.BackupError('bootstrap_requires_retained_primary_unadjusted_observation')
        for row in rows:
            bars = value['tickers'][row['ticker']]['bars']
            if (row['data_source'] != backup.PRIMARY or row['data_quality_label'] != 'ok'
                    or row['market_session_date'] != value['market_session']
                    or abs(float(row['last_price']) - bars[-1]['close']) > 0.000051
                    or abs(float(row['previous_close']) - bars[-2]['close']) > 0.000051):
                raise backup.BackupError('bootstrap_canonical_pair_mismatch')
        if (root / backup.CURRENT).exists():
            raise backup.BackupError('bootstrap_pointer_already_exists')
        if apply:
            pointer = backup.pointer_for(root, value, sha256_file(snapshot))
            atomic_write_json(root / backup.CURRENT, pointer)
        return dict(validated=True, applied=apply, tickers=len(tickers), session=value['market_session'],
                    snapshot_unchanged=True, email_sent=False, trade_placed=False)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(admit(args.root,args.input,apply=args.apply)))
