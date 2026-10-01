"""Same coordinator as the form, for explicit owner-reported facts in Codex.

Use --preview first, inspect changes, then retain that exact request UUID and
preview_hash in the local JSON for --apply. No brokerage or email sender.
"""
import argparse
import json
from server import DEFAULT_ROOT, RUNTIME_LOCK
from feedback import Store, FeedbackError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request_file',nargs='?',help='Private local JSON request; never commit account data')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preview',action='store_true')
    mode.add_argument('--apply',action='store_true')
    mode.add_argument('--request-review',action='store_true',help='Queue an owner research request; no email or account write')
    mode.add_argument('--list-reviews',action='store_true')
    mode.add_argument('--claim-review',metavar='REQUEST_ID')
    mode.add_argument('--complete-review',metavar='REQUEST_ID')
    mode.add_argument('--block-review',metavar='REQUEST_ID')
    mode.add_argument('--review-events',metavar='REQUEST_ID')
    parser.add_argument('--receipt',help='Private source-bound analyst completion/dependency JSON receipt')
    parser.add_argument('--rebind-current',action='store_true',help='Explicitly claim against changed current account; original request binding stays audited')
    parser.add_argument('--refresh',action='store_true',help='Run full no-send research after applying; facts survive research failure')
    args=parser.parse_args()
    store=Store(DEFAULT_ROOT,RUNTIME_LOCK)
    if args.preview or args.apply or args.request_review:
        if not args.request_file: parser.error('this mode requires a private request JSON file')
        with open(args.request_file) as handle: payload=json.load(handle)
    elif args.request_file: parser.error('this mode does not accept a request JSON file')
    if args.refresh and not args.apply: parser.error('--refresh only applies to --apply feedback')
    if args.rebind_current and not args.claim_review: parser.error('--rebind-current only applies to --claim-review')
    if args.receipt and not (args.complete_review or args.block_review): parser.error('--receipt only applies to completion or block')
    try:
        if args.preview: result=store.preview(payload)
        elif args.apply: result=store.submit(payload)
        elif args.request_review: result=store.request_review(payload)
        elif args.list_reviews: result={'requests':store.reviews()}
        elif args.claim_review: result=store.claim_review(args.claim_review,rebind_current=args.rebind_current)
        elif args.review_events: result={'events':store.review_events(args.review_events)}
        else:
            if not args.receipt: parser.error('completion and block require --receipt')
            result=store.finish_review(args.complete_review or args.block_review,'completed' if args.complete_review else 'blocked',args.receipt)
    except FeedbackError as exc:
        print(json.dumps({'error':exc.code,'details':exc.details},ensure_ascii=False,indent=2))
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.apply and args.refresh: store.work_once()
    return 0


if __name__=='__main__': raise SystemExit(main())
