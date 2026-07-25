# Phase 5R-C4 Holding Horizon Policy

## Horizon Classes

| Horizon Class | Intended Duration | Review Standard |
| --- | --- | --- |
| `short_swing` | 2 to 6 weeks | Review weekly; require a defined catalyst, invalidation rule, and planned review date. |
| `medium_conviction` | 2 to 4 months | Review weekly for thesis changes and formally reassess at least monthly. |
| `core_compounder` | 6 to 12 months | Review weekly for material events and reassess thesis, valuation, and concentration monthly. |
| `watch_only` | No position; research only | Track without position sizing until a future manual review changes the classification. |

## Holding Rules

- A horizon is an expected research window, not a promise to hold until a date.
- A material thesis break or invalidation condition can trigger `exit_review` before the expected horizon ends.
- Price movement alone does not override the thesis or create an intraday action.
- Reaching the end of a horizon triggers review, not automatic selling.
- Adding requires renewed thesis, risk, and concentration checks.
- Trimming may be considered when concentration exceeds policy, valuation becomes unsupported, or conviction declines without a full thesis break.
