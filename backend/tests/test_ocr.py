"""OCR for PDF pages without a text layer."""

from __future__ import annotations

import io
import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.config import get_settings
from app.extraction import ExtractionError, OcrOptions, extract
from app.extraction.ocr import OcrError, OcrParagraph, TesseractOcr, _parse_tsv, get_ocr
from app.models import Role
from tests.conftest import Tenant, login, upload

HAS_TESSERACT = shutil.which("tesseract") is not None
needs_tesseract = pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract is not installed")

SCANNED_LINES = ["Records retention schedule", "Data is kept for seven years."]


def text_image(lines: list[str]) -> Image.Image:
    img = Image.new("L", (1600, 400), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=56)
    for i, line in enumerate(lines):
        draw.text((60, 60 + i * 110), line, fill=0, font=font)
    return img


def pdf(pages: list[str | Image.Image]) -> bytes:
    """Text pages get a text layer; image pages are 'scanned' (image only)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for page in pages:
        if isinstance(page, str):
            c.drawString(72, 750, page)
        else:
            c.drawImage(ImageReader(page), 36, 500, width=520, height=130)
        c.showPage()
    c.save()
    return buf.getvalue()


class FakeOcr:
    name = "fake"
    languages = "eng"

    def __init__(self, paragraphs: list[OcrParagraph] | None = None, fail: bool = False):
        self.paragraphs = paragraphs or [OcrParagraph("Scanned retention clause", 91)]
        self.fail = fail
        self.calls = 0

    def recognize(self, png: bytes) -> list[OcrParagraph]:
        assert png.startswith(b"\x89PNG")
        self.calls += 1
        if self.fail:
            raise OcrError("OCR failed on this page.")
        return self.paragraphs


SCAN = text_image(SCANNED_LINES)


def test_only_pages_without_text_are_read_and_marked() -> None:
    engine = FakeOcr()
    result = extract(
        "pdf", pdf(["A text page", SCAN, "Another text page"]), 300, 10**6, OcrOptions(engine)
    )
    assert engine.calls == 1
    assert [(b.ref, b.is_ocr) for b in result.blocks] == [
        ("p1.b1", False),
        ("p2.ocr1", True),
        ("p3.b1", False),
    ]
    assert result.blocks[1].ocr_confidence == 91 and result.blocks[1].page_number == 2
    assert result.ocr_pages == [2]
    assert any("read with OCR (fake, eng)" in w for w in result.warnings)
    assert not any("low" in w for w in result.warnings)


def test_ocr_warnings_for_low_confidence_failure_and_page_cap() -> None:
    low = extract("pdf", pdf([SCAN]), 300, 10**6, OcrOptions(FakeOcr([OcrParagraph("blurry", 40)])))
    assert any("confidence was low on page(s) 1" in w for w in low.warnings)
    with pytest.raises(ExtractionError, match="even with OCR"):
        extract("pdf", pdf([SCAN]), 300, 10**6, OcrOptions(FakeOcr(fail=True)))
    capped = extract("pdf", pdf([SCAN, SCAN, SCAN]), 300, 10**6, OcrOptions(FakeOcr(), max_pages=2))
    assert capped.ocr_pages == [1, 2]
    assert any("stopped after 2 page(s); page(s) 3 were not read" in w for w in capped.warnings)
    assert any("No text found on page(s) 3" in w for w in capped.warnings)


def test_ocr_text_counts_toward_the_character_limit() -> None:
    with pytest.raises(ExtractionError, match="limit"):
        extract("pdf", pdf([SCAN]), 300, 10, OcrOptions(FakeOcr()))


def test_parse_tsv_groups_words_into_paragraphs() -> None:
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tRecords",
        "5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t80\tretention",
        "5\t1\t1\t1\t2\t1\t0\t0\t1\t1\t70\tschedule",
        "4\t1\t1\t1\t2\t0\t0\t0\t1\t1\t-1\t",
        "5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t-1\t ",
        "5\t1\t2\t1\t1\t2\t0\t0\t1\t1\t60\tSeven",
    ]
    out = _parse_tsv("\n".join([header, *rows]))
    assert out == [OcrParagraph("Records retention\nschedule", 80), OcrParagraph("Seven", 60)]


def test_languages_are_validated_and_ocr_is_off_by_default() -> None:
    assert get_ocr(get_settings()) is None
    for bad in ("eng;rm -rf /", "eng ara", "../x", ""):
        with pytest.raises(OcrError):
            TesseractOcr("tesseract", bad, 10)
    with pytest.raises(OcrError, match="not installed"):
        TesseractOcr("/nonexistent/tesseract", "eng", 10).recognize(b"\x89PNG")


@needs_tesseract
def test_tesseract_reads_a_scanned_page() -> None:
    engine = TesseractOcr("tesseract", "eng", 60)
    result = extract("pdf", pdf([SCAN]), 300, 10**6, OcrOptions(engine))
    text = " ".join(b.text for b in result.blocks).lower()
    assert "retention" in text and "seven years" in text
    assert all(b.is_ocr and b.ocr_confidence is not None for b in result.blocks)


@needs_tesseract
def test_scanned_upload_with_ocr_enabled(
    tenant_a: Tenant, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import documents

    settings = get_settings().model_copy(
        update={"ocr_provider": "tesseract", "ocr_languages": "eng"}
    )
    monkeypatch.setattr(documents, "get_settings", lambda: settings)
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, pdf([SCAN]), "scan.pdf", "application/pdf")
    assert r.status_code == 201, r.text
    doc = client.get(f"/api/documents/{r.json()['id']}").json()
    v = doc["latest_version"]
    assert v["status"] == "ready", v
    assert any("read with OCR (tesseract, eng)" in w for w in v["extraction_warnings"])
    blocks = client.get(f"/api/document-versions/{v['id']}/blocks").json()["items"]
    assert blocks and all(b["is_ocr"] for b in blocks)
    assert blocks[0]["ref"] == "p1.ocr1" and blocks[0]["page_number"] == 1
