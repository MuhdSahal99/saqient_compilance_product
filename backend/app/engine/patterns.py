"""Restricted pattern syntax (see docs/adr/0003).

Patterns are literal text plus a few placeholders:

    {number}  digits, optionally with one decimal separator
    {date}    dd/mm/yyyy, dd-mm-yy, yyyy-mm-dd style dates
    {word}    one word (letters, digits, Arabic letters)
    {any}     up to 40 characters of anything except a newline (lazy)

Whitespace in the pattern matches a run of whitespace (optional next to {any}). Everything else is
literal. The generated expression is compiled with RE2 (google-re2), which
matches in time linear in the input, so no pattern can cause catastrophic
backtracking. Users never write the expression themselves.
"""

from __future__ import annotations

import re
from typing import Any

import re2

MAX_PATTERN_LENGTH = 200
MAX_PLACEHOLDERS = 6

_PLACEHOLDERS: dict[str, str] = {
    "number": r"\d{1,15}(?:[.,]\d{1,6})?",
    "date": r"(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2})",
    "word": r"[\p{L}\p{N}_]{1,40}",
    "any": r"[^\n]{0,40}?",
}

_TOKEN = re.compile(r"\{(number|date|word|any)\}|(\s+)|([^{\s]+|\{)")


class PatternError(ValueError):
    pass


def compile_pattern(pattern: str, case_sensitive: bool = False) -> Any:
    if not pattern or not pattern.strip():
        raise PatternError("Pattern is empty.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise PatternError(f"Pattern is longer than {MAX_PATTERN_LENGTH} characters.")
    tokens: list[tuple[str, str]] = []  # (kind, value)
    for match in _TOKEN.finditer(pattern.strip()):
        name, space, literal = match.groups()
        if name:
            tokens.append(("ph", name))
        elif space:
            tokens.append(("ws", ""))
        else:
            tokens.append(("lit", literal))
    parts: list[str] = []
    placeholders = 0
    for i, (kind, value) in enumerate(tokens):
        if kind == "ph":
            placeholders += 1
            parts.append(_PLACEHOLDERS[value])
        elif kind == "ws":
            # Whitespace next to {any} is optional so "date {any} {date}" matches "date: 1/2/26".
            near_any = any(
                0 <= j < len(tokens) and tokens[j] == ("ph", "any") for j in (i - 1, i + 1)
            )
            parts.append(r"\s{0,10}" if near_any else r"\s{1,10}")
        else:
            parts.append(re.escape(value))
    if placeholders > MAX_PLACEHOLDERS:
        raise PatternError(f"Pattern uses more than {MAX_PLACEHOLDERS} placeholders.")
    options = re2.Options()
    options.case_sensitive = case_sensitive
    options.max_mem = 8 << 20
    try:
        return re2.compile("".join(parts), options)
    except re2.error as exc:  # pragma: no cover - generated patterns should always compile
        raise PatternError("Pattern could not be compiled.") from exc
