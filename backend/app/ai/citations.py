"""Citation validation for future AI output.

A citation is valid only if the block exists in the caller's organisation and
the quote appears in the stored block text after normalisation. Passing this
check proves the quote exists — not that any interpretation of it is correct.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceBlock

_ARABIC_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"


def normalise_quote(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _ARABIC_DIACRITICS.sub("", text).replace(_TATWEEL, "")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return " ".join(text.split()).casefold()


@dataclass
class Citation:
    block_id: str
    quote: str


@dataclass
class CitationResult:
    block_id: str
    quote: str
    status: Literal["valid", "unsupported"]
    reason: str | None = None
    ref: str | None = None


def validate_citations(
    db: Session,
    org_id: uuid.UUID,
    citations: list[Citation],
    allowed_version_ids: set[uuid.UUID] | None = None,
) -> list[CitationResult]:
    results: list[CitationResult] = []
    for c in citations:
        try:
            block_uuid = uuid.UUID(c.block_id)
        except (ValueError, TypeError):
            results.append(CitationResult(c.block_id, c.quote, "unsupported", "malformed id"))
            continue
        block = db.scalar(
            select(SourceBlock).where(SourceBlock.id == block_uuid, SourceBlock.org_id == org_id)
        )
        if block is None or (
            allowed_version_ids is not None and block.document_version_id not in allowed_version_ids
        ):
            results.append(
                CitationResult(
                    c.block_id, c.quote, "unsupported", "block not found or not accessible"
                )
            )
            continue
        quote = normalise_quote(c.quote)
        if len(quote) < 3 or quote not in normalise_quote(block.text):
            results.append(
                CitationResult(
                    c.block_id,
                    c.quote,
                    "unsupported",
                    "quote does not match stored text",
                    block.ref,
                )
            )
            continue
        results.append(CitationResult(c.block_id, c.quote, "valid", None, block.ref))
    return results
