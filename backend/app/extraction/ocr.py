"""Optional OCR for PDF pages that have no text layer.

Off by default (``OCR_PROVIDER=disabled``). The ``tesseract`` provider runs the
local Tesseract binary as a subprocess (no shell, fixed arguments, a timeout
per page); page images never leave the machine. Pages are rendered with
pdfium. Text read by OCR is marked on its blocks, because recognition can be
wrong.
"""

from __future__ import annotations

import csv
import io
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings

LANGUAGES = re.compile(r"^[a-z_]{3,8}(\+[a-z_]{3,8}){0,4}$")
MAX_PIXELS = 40_000_000  # caps memory for very large page sizes


class OcrError(RuntimeError):
    """OCR could not run on a page (message safe to show)."""


@dataclass
class OcrParagraph:
    text: str
    confidence: int  # mean word confidence, 0-100


class OcrEngine(Protocol):
    name: str
    languages: str

    def recognize(self, png: bytes) -> list[OcrParagraph]: ...


def _parse_tsv(tsv: str) -> list[OcrParagraph]:
    """Group Tesseract TSV words into paragraphs (block, paragraph), in reading order."""
    paragraphs: dict[tuple[int, int], list[tuple[int, int, str, float]]] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            continue
        if row.get("level") != "5" or not text or conf < 0:
            continue
        key = (int(row["block_num"]), int(row["par_num"]))
        paragraphs.setdefault(key, []).append(
            (int(row["line_num"]), int(row["word_num"]), text, conf)
        )
    out: list[OcrParagraph] = []
    for key in sorted(paragraphs):
        words = sorted(paragraphs[key])
        lines: dict[int, list[str]] = {}
        for line, _, text, _ in words:
            lines.setdefault(line, []).append(text)
        body = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
        confidence = round(sum(w[3] for w in words) / len(words))
        out.append(OcrParagraph(body, confidence))
    return out


class TesseractOcr:
    name = "tesseract"

    def __init__(self, command: str, languages: str, timeout_seconds: int) -> None:
        if not LANGUAGES.match(languages):
            raise OcrError("OCR_LANGUAGES must look like 'eng+ara'.")
        self.command = command
        self.languages = languages
        self.timeout = timeout_seconds

    def recognize(self, png: bytes) -> list[OcrParagraph]:
        args = [self.command, "stdin", "stdout", "-l", self.languages, "--psm", "3", "tsv"]
        env = {"PATH": os.environ.get("PATH", ""), "OMP_THREAD_LIMIT": "1"}
        try:
            done = subprocess.run(  # noqa: S603 - fixed argument list, no shell
                args, input=png, capture_output=True, timeout=self.timeout, env=env, check=False
            )
        except FileNotFoundError as exc:
            raise OcrError("The OCR engine is not installed.") from exc
        except subprocess.TimeoutExpired as exc:
            raise OcrError("OCR timed out on this page.") from exc
        if done.returncode != 0:
            raise OcrError("OCR failed on this page.")
        return _parse_tsv(done.stdout.decode("utf-8", errors="replace"))


def get_ocr(settings: Settings) -> OcrEngine | None:
    if settings.ocr_provider == "disabled":
        return None
    return TesseractOcr(
        settings.ocr_tesseract_cmd, settings.ocr_languages, settings.ocr_page_timeout_seconds
    )


def render_page_png(pdf: object, page_index: int, dpi: int) -> bytes:
    """Render one page (0-based) of an open pypdfium2 PdfDocument to PNG."""
    page = pdf[page_index]  # type: ignore[index]
    width, height = page.get_size()  # points
    scale = dpi / 72
    if width * height * scale * scale > MAX_PIXELS:
        scale = (MAX_PIXELS / (width * height)) ** 0.5
    image = page.render(scale=scale, grayscale=True).to_pil()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
