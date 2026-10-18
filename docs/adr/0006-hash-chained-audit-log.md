# ADR 0006 — Hash-chained audit log

Status: accepted (2026-10-18)

## Decision
`audit_events` is an append-only hash chain, one chain per organisation plus
one for events without an organisation (failed sign-ins). Each row stores
`seq`, `prev_hash` and `hash = SHA-256(canonical JSON of id, org, seq, actor,
action, object, metadata, created_at, prev_hash)`, hash version `v1`.
Appends take `pg_advisory_xact_lock` on the chain so concurrent requests
cannot fork it. A trigger rejects UPDATE. `GET /api/audit-events/verify`
(org admin) recomputes the chain and reports the first broken event.
Migration 0003 backfills existing rows in `created_at, id` order.

## Why
Finance reviewers need evidence that the trail was not edited after the
fact. A per-org chain keeps verification tenant-scoped and lets the lock be
per tenant instead of global.

## Consequences
- The actor FK no longer has `ON DELETE SET NULL` (the actor is hashed).
  Users with audit history are deactivated, not deleted.
- Deleting the newest events, or an organisation, is not detectable from the
  table alone. Verification returns `head_hash` so it can be kept elsewhere
  (for example in a signed report). External anchoring is future work.
- Appends to one organisation are serialised until the writing transaction
  commits.
