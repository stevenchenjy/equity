#!/usr/bin/env python3
"""Check or append one explicit company-model admission, without sending/trading."""
import argparse
import json
from pathlib import Path
from company_valuation import STORE_REL, SCHEMA, append, seal, template
from daily_common import ROOT, ExclusiveFileLock, atomic_write_json, read_json, now_et
from valuation_research_inputs import archive_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--template', metavar='TICKER')
    parser.add_argument('--seal', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.template:
        if args.input or args.apply or args.seal:
            parser.error('template cannot mutate or combine with input')
        print(json.dumps(template(root, args.template.upper(), now_et()), indent=2))
        return 0
    if not args.input or (args.seal and args.apply):
        parser.error('input required; seal cannot apply')
    record = read_json(args.input)
    if args.seal:
        print(json.dumps(seal(record), indent=2))
        return 0
    # Coordinators hold runtime then daily-pipeline locks; this CLI owns only
    # its writer lock, following the established thesis/plan writer convention.
    with ExclusiveFileLock(root/'00_project_control/run_logs/company_valuation_admissions.lock'):
        path = root/STORE_REL
        store = read_json(path, {'schema_version': SCHEMA, 'records': []})
        updated = append(store, record, root=root, current=now_et())
        if args.apply:
            history = root/'04_data/equity_research/company_valuation_admission_history.local'
            if path.exists():
                archive_bytes(path, history)
            atomic_write_json(path, updated)
            archive_bytes(path, history)
    print(f"company_model={record['ticker']} version={record['version']} validated=true applied={str(args.apply).lower()} automatic_action_allowed=false")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
