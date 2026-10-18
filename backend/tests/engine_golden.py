"""Golden outputs for the deterministic-1.0.0 text checks.

``python -m tests.engine_golden`` regenerates the fixture; do that only when a
change to text-check behaviour is intended, together with a new engine version.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import demo_content as dc
from app.engine import DocumentContext, evaluate, parse_config
from app.extraction import extract

GOLDEN = Path(__file__).parent / "fixtures" / "engine" / "golden_deterministic_1_0_0.json"


@dataclass
class Block:
    id: uuid.UUID
    ref: str
    text: str
    page_number: int | None
    paragraph_number: int | None


def golden_outputs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sources = {
        "txt": dc.policy_txt_bytes(),
        "docx": dc.policy_docx_bytes(),
        "pdf": dc.policy_pdf_bytes(),
    }
    for fmt, data in sources.items():
        result = extract(fmt, data, 300, 2_000_000)
        blocks = [
            # Stable ids so evidence block_ids are comparable across runs.
            Block(uuid.UUID(int=i + 1), b.ref, b.text, b.page_number, b.paragraph_number)
            for i, b in enumerate(result.blocks)
        ]
        for doc_type in ("policy", "contract"):
            ctx = DocumentContext(
                title="Synthetic vendor policy",
                description="Synthetic",
                document_type=doc_type,
                tags=["synthetic"],
                blocks=blocks,
            )
            for raw in dc.DEMO_REQUIREMENTS:
                ev = evaluate(parse_config(raw["check_config"]), ctx)  # type: ignore[arg-type]
                out.append(
                    {
                        "format": fmt,
                        "document_type": doc_type,
                        "code": raw["code"],
                        "outcome": ev.outcome.value,
                        "needs_attention": ev.needs_attention,
                        "message": ev.message,
                        "evidence": ev.evidence,
                    }
                )
    return out


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(golden_outputs(), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {GOLDEN}")
