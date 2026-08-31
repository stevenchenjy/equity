# Phase 0E Phase 5R Integrity Check

Run timestamp: `2026-07-09T00:17:35-05:00`
Project root: `/Users/messssi/Desktop/equity`

## Checks

- **PASS** - Original Phase 5R-A files still exist: missing=[]
- **PASS** - Copied Phase 5R-A files exist in canonical locations: missing_or_uncopied=[]
- **PASS** - IOT/RBRK absent from copied Phase 5R universe file: ticker_violations=[], text_violation=False
- **PASS** - Manual ticket constants remain yes/no/no/no: violations=[]
- **PASS** - No active broker/API/order/email code appears in copied Phase 5R-A scripts: violations=[]

## Notes

- Phase 5R-A source files were copied without modifying script logic.
- The copied Phase 5R-A script scan uses AST import/call inspection so verifier guardrail strings are not treated as executable order, broker, API, or email code.
- `01_universe/real_candidate_universe.csv` was not copied because it contains IOT/RBRK ticker rows; the copied Phase 5R universe remains the fresh Phase 5R-A seed.
