# Phase 5R v6 — Fresh Complete Collection Authorization Request

## Purpose

Request a **new, independent** authorization for one fresh, complete 30-call
shadow-only collection. It must not resume, retry, reset, or combine any
terminal v1–v5 pilot.

## Proposed limit

| Limit | Proposed maximum |
| --- | ---: |
| New physical model calls | 30 |
| New reservation | $4.9368 |
| Independent authorization ceiling | $5.00 |
| SDK retries | 0 |
| Physical attempts per call | 1 |

The proposed reservation is the original sealed 30-call worst-case reservation
and is separate from the $0.654002 charged or reserved by v1–v5.

## Non-negotiable boundaries

- Shadow research only.
- No email, alerts, broker/account access, orders, execution, or canonical
  influence.
- No credential storage or logging.
- `store: false`; no tools; no automatic action.
- Raw failed responses and provider response IDs remain unpersisted.
- Every started failure remains terminal with no retry or resume.
- Existing v1–v5 plans and journals remain immutable.

## Pre-execution capability gate

v5 isolated an empty required analyst text field. A v6 sealed executor must
enforce non-empty model text without weakening the closed validator. The
official Structured Outputs documentation says `minLength` is not supported
for fine-tuned models. Before any request is made, the selected provider/model
combination must be verified to support the exact strict schema, or the v6
plan must use another documented, equally strict mechanism.

## Required approval wording

To authorize planning and eventual execution, approve the following scope:

> Approve a new independent Phase 5R v6 full shadow-only collection: at most
> 30 new model calls and $5.00, no email, no trading, no broker/account access,
> no canonical influence, zero retries, and no credential storage.

This request is not an authorization to send a model request until the v6 plan,
offline tests, and provider capability gate are all sealed and reported.
