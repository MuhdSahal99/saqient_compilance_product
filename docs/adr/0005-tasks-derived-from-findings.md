# ADR 0005 — Remediation tasks are findings with an owner

Status: accepted (2026-10-12)

## Decision
In the MVP a remediation "task" is a confirmed finding with an assigned owner
and due date; the Tasks page lists those. No separate tasks table.

## Why
Keeps a single source of truth for status and evidence. If tasks later need to
exist independently of findings (e.g. one finding, many tasks), add a table
with a migration and an ADR.
