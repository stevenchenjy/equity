"""Same coordinator as the form, for explicit owner-reported facts in Codex.

Use --preview first, inspect changes, then retain that exact request UUID and
preview_hash in the local JSON for --apply. No brokerage or email sender.
"""
import argparse
import json
from server import DEFAULT_ROOT, RUNTIME_LOCK
from feedback import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request_file',help='Private local JSON request; never commit account data')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preview',action='store_true')
    mode.add_argument('--apply',action='store_true')
    parser.add_argument('--refresh',action='store_true',help='Run full no-send research after applying; facts survive research failure')
    args=parser.parse_args()
    with open(args.request_file) as handle: payload=json.load(handle)
    store=Store(DEFAULT_ROOT,RUNTIME_LOCK)
    result=store.preview(payload) if args.preview else store.submit(payload)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.apply and args.refresh: store.work_once()


if __name__=='__main__': main()
