# Phase 5R workspace cleanup manifest

Cleanup date: `2026-08-31`

## Outcome

The workspace now exposes only the deterministic daily research system and its
current policy, evidence, valuation, C9/C9B review, scheduler, delivery, and
focused test surfaces. Retired material is isolated from active imports and
Graphify analysis.

Final tracked inventory after this cleanup is 688 files: 157 active/reference
files, 10 curated Graphify root artifacts, and 520 moved archive artifacts plus
the archive README. The active Python surface contains 40 modules and 17
focused test modules.

## Preservation layers

1. Git archive: `11_archive/phase5r_retired_20260831/` contains 520 moved
   historical tracked artifacts plus its archive README.
2. Recovery tag: `phase5r-pre-cleanup-20260831` preserves the exact pre-cleanup
   tree at commit `5790e00040dcd07973f4366eaea480eff210c306`.
3. Large ignored evidence: `/Users/messssi/LocalArchive/equity/phase5r_retired_20260831/`
   holds 684 retired ignored artifacts outside the authoring and runtime clones.

External archive tree digests use SHA-256 over sorted relative-path/file-hash
pairs:

| Source copy | Files | Bytes | Tree digest |
| --- | ---: | ---: | --- |
| Authoring model replay | 203 | 37,968,013 | `ad86d54f79919f77aae7614a1423287d5c1053c5fcc46d4583f54072a422ee4d` |
| Runtime model replay | 203 | 37,968,013 | `ad86d54f79919f77aae7614a1423287d5c1053c5fcc46d4583f54072a422ee4d` |
| Authoring pilot quarantine | 132 | 1,269,764 | `89167061f51830b7736f5b07a0c264b020f0fa4aaebd1db09c5c73ce97aaba07` |
| Runtime pilot quarantine | 133 | 1,277,960 | `ae9de740b4bfe9e16088008b1d77b6afb981a291cb6bba64c8090a553eecc7c9` |
| Authoring retired reports/previews | 13 | 75,002 | `ff2ce40a47dd9c5813beb9f83948e750352727cb37827253612f779dae851bfc` |

## Reproducible clutter removed

- 1,292 tracked Graphify cache and dated-snapshot files;
- the obsolete `.gitignore.orig` copy;
- 277 stale Python bytecode files, including caches for retired modules; and
- untracked `.DS_Store`, `.pytest_cache`, and empty retired directories.

The active B2 scorer now writes only its canonical signal CSV and audit row; it
no longer regenerates deprecated Markdown watchlist/preview copies.

These generated or duplicate files remain recoverable through the pre-cleanup
tag when they were tracked. Current curated Graphify root artifacts remain in
`graphify-out/`; future caches and dated snapshots are ignored.

## Active boundary

- Active model calls: `false`; model budget and metered cost: `$0`.
- The daily-refresh launcher reads only the Massive market-data credential.
- `11_archive/**` is denied as an active input and excluded from Graphify.
- No broker connection, broker-account read, automatic order, or trade
  placement exists or is authorized.
