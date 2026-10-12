# ADR 0003 — Deterministic engine with a restricted pattern syntax

Status: accepted (2026-10-12)

## Decision
Checks are declarative Pydantic-validated configs. "Pattern" checks use a
restricted token syntax (`{number}`, `{date}`, `{word}`, `{any}` plus literal
text) compiled to a regular expression with only bounded, non-nested
quantifiers. Users never supply raw regular expressions; nothing is evaluated
as code.

## Why
Python's `re` backtracks; arbitrary user regex enables ReDoS. A dedicated RE2
binding was considered, but a small restricted syntax covers the MVP needs
without a native dependency and is easier to explain to reviewers.

## Consequences
Less expressive than regex. Extending the syntax requires a new engine version
(`ENGINE_VERSION`), recorded on every run.
