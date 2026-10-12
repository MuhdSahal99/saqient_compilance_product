# ADR 0003 — Deterministic engine with a restricted pattern syntax on RE2

Status: accepted (2026-10-12; revised the same day after testing)

## Decision
Checks are declarative Pydantic-validated configs. "Pattern" checks use a
restricted token syntax (`{number}`, `{date}`, `{word}`, `{any}` plus literal
text) that is compiled to a regular expression and executed with **RE2**
(`google-re2`), which runs in linear time and never backtracks. Users never
supply raw regular expressions; nothing is evaluated as code. Patterns are
limited to 200 characters and 6 placeholders, and RE2 gets a memory cap.

## Why
The first version compiled the restricted syntax for Python's `re` and relied
on bounded quantifiers. A test with adjacent `{any}`/whitespace tokens showed
exponential backtracking (the test hung), so the restricted syntax alone was
not enough. RE2 removes the class of problem instead of trying to avoid it
pattern by pattern. The cost is one native dependency with wheels for the
supported platforms.

## Consequences
- Less expressive than raw regex (no back-references or look-around, which RE2
  does not support anyway).
- Extending the syntax requires a new engine version (`ENGINE_VERSION`),
  recorded on every run and in every report.
