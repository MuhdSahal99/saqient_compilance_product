"""Predefined value shapes used by engine 1.2.0 (no user-written patterns)."""

from __future__ import annotations

from typing import Any


def normalise_tax_id(value: str) -> str:
    return "".join(value.split()).upper()


def tax_id_ok(value: str, fmt: Any) -> bool:
    """``fmt`` is a services.rule_schemas.TaxIdFormat (length, digits_only, prefix, suffix)."""
    v = normalise_tax_id(value)
    if len(v) != fmt.length:
        return False
    if fmt.digits_only and not v.isdigit():
        return False
    if not fmt.digits_only and not v.isalnum():
        return False
    return v.startswith(fmt.prefix) and v.endswith(fmt.suffix)


def describe_tax_id(fmt: Any) -> str:
    parts = [f"{fmt.length} {'digits' if fmt.digits_only else 'characters'}"]
    if fmt.prefix:
        parts.append(f"starting {fmt.prefix}")
    if fmt.suffix:
        parts.append(f"ending {fmt.suffix}")
    return ", ".join(parts)
