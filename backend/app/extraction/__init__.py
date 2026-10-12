"""Upload validation and text extraction.

Document contents are untrusted. Extractors never execute embedded content and
apply size/page/character limits. PDF blocks carry page numbers; DOCX and TXT
blocks carry paragraph numbers only (no invented page numbers).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

ALLOWED_FORMATS: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        # Some browsers/OSes send a generic type for .docx
        "application/octet-stream",
        "application/zip",
    },
    "txt": {"text/plain", "application/octet-stream"},
}

MAX_DOCX_UNCOMPRESSED = 100 * 1024 * 1024
MAX_BLOCK_CHARS = 4000


class ValidationError(ValueError):
    """Raised for uploads that fail validation. Message is safe to show users."""


class ExtractionError(RuntimeError):
    """Raised when a valid file cannot be processed. Message is safe to show users."""


@dataclass
class ExtractedBlock:
    ref: str
    text: str
    page_number: int | None = None
    paragraph_number: int | None = None
    section_heading: str | None = None


@dataclass
class ExtractionResult:
    blocks: list[ExtractedBlock]
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)


def detect_format(filename: str, declared_mime: str, data: bytes) -> str:
    """Validate extension, declared MIME type and file signature. Returns the format."""
    if not data:
        raise ValidationError("The file is empty.")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_FORMATS:
        raise ValidationError("Unsupported file type. Upload a PDF, DOCX or TXT file.")
    mime = (declared_mime or "application/octet-stream").split(";")[0].strip().lower()
    if mime not in ALLOWED_FORMATS[ext]:
        raise ValidationError(f"The file's declared type ({mime}) does not match .{ext}.")

    if ext == "pdf":
        if not data[:1024].lstrip().startswith(b"%PDF-"):
            raise ValidationError("The file does not look like a PDF (missing PDF signature).")
    elif ext == "docx":
        if not data.startswith(b"PK\x03\x04"):
            raise ValidationError("The file does not look like a DOCX (missing ZIP signature).")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                    raise ValidationError("The ZIP file is not a Word document.")
                total = sum(i.file_size for i in zf.infolist())
                if total > MAX_DOCX_UNCOMPRESSED:
                    raise ValidationError("The DOCX expands beyond the allowed size.")
                if any(n.lower().endswith(("vbaproject.bin",)) for n in names):
                    raise ValidationError("Macro-enabled documents are not accepted.")
        except zipfile.BadZipFile as exc:
            raise ValidationError("The DOCX file is corrupted.") from exc
    elif ext == "txt":
        if b"\x00" in data[:8192]:
            raise ValidationError("The text file contains binary data.")
        try:
            _decode_text(data)
        except UnicodeDecodeError as exc:
            raise ValidationError("Text files must be UTF-8 or UTF-16 encoded.") from exc
    return ext


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


_WS = re.compile(r"[ \t ]+")


def _clean(text: str) -> str:
    lines = [_WS.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    out: list[str] = []
    for part in parts:
        cleaned = _clean(part)
        if not cleaned:
            continue
        while len(cleaned) > MAX_BLOCK_CHARS:
            out.append(cleaned[:MAX_BLOCK_CHARS])
            cleaned = cleaned[MAX_BLOCK_CHARS:]
        out.append(cleaned)
    return out


def _check_chars(total: int, max_chars: int) -> None:
    if total > max_chars:
        raise ExtractionError(
            f"Extracted text exceeds the configured limit of {max_chars:,} characters."
        )


def _pdf_page_text(page: object) -> str:
    """Extract page text, inserting blank lines where the vertical gap between lines is
    larger than normal line spacing, so paragraphs become separate blocks."""
    lines: list[tuple[float, str]] = []

    def visit(text: str, cm: list[float], tm: list[float], font: object, size: float) -> None:
        if text and text.strip():
            y = tm[5] * cm[3] + cm[5] if cm else tm[5]
            if lines and abs(lines[-1][0] - y) < 1.0:
                lines[-1] = (lines[-1][0], lines[-1][1] + text)
            else:
                lines.append((y, text))

    raw = page.extract_text(visitor_text=visit) or ""  # type: ignore[attr-defined]
    if len(lines) < 2:
        return raw
    gaps = [abs(lines[i - 1][0] - lines[i][0]) for i in range(1, len(lines))]
    positive = sorted(g for g in gaps if g >= 2.0)
    if not positive:
        return raw
    typical = positive[0]  # tightest spacing ~ normal line spacing
    out = [lines[0][1].strip()]
    for gap, (_, text) in zip(gaps, lines[1:], strict=True):
        out.append(("\n\n" if gap > typical * 1.5 else "\n") + text.strip())
    return "".join(out)


def extract_pdf(data: bytes, max_pages: int, max_chars: int) -> ExtractionResult:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("Encrypted or password-protected PDFs are not supported.")
        page_count = len(reader.pages)
    except PdfReadError as exc:
        raise ExtractionError("The PDF could not be read; it may be corrupted.") from exc
    if page_count > max_pages:
        raise ExtractionError(f"The PDF has {page_count} pages; the limit is {max_pages}.")

    blocks: list[ExtractedBlock] = []
    warnings: list[str] = []
    empty_pages: list[int] = []
    total = 0
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            text = _pdf_page_text(page)
        except Exception:
            text = ""
            warnings.append(f"Text could not be extracted from page {page_index}.")
        paragraphs = _split_paragraphs(text)
        if not paragraphs:
            empty_pages.append(page_index)
        for i, para in enumerate(paragraphs, start=1):
            total += len(para)
            _check_chars(total, max_chars)
            blocks.append(
                ExtractedBlock(ref=f"p{page_index}.b{i}", text=para, page_number=page_index)
            )
    if not blocks:
        raise ExtractionError(
            "No extractable text was found. The PDF may be scanned; OCR is not enabled."
        )
    if empty_pages:
        shown = ", ".join(str(p) for p in empty_pages[:10])
        warnings.append(
            f"No text found on page(s) {shown}"
            + (" and others" if len(empty_pages) > 10 else "")
            + ". These pages may be images; OCR is not enabled, so they were not reviewed."
        )
    return ExtractionResult(blocks=blocks, page_count=page_count, warnings=warnings)


def extract_docx(data: bytes, max_chars: int) -> ExtractionResult:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ExtractionError("The DOCX could not be opened; it may be corrupted.") from exc

    blocks: list[ExtractedBlock] = []
    warnings: list[str] = []
    heading: str | None = None
    para_no = 0
    total = 0
    for para in document.paragraphs:
        text = _clean(para.text)
        if not text:
            continue
        para_no += 1
        style = (para.style.name if para.style is not None else "") or ""
        if style.lower().startswith(("heading", "title")):
            heading = text[:300]
        total += len(text)
        _check_chars(total, max_chars)
        blocks.append(
            ExtractedBlock(
                ref=f"para-{para_no}",
                text=text[:MAX_BLOCK_CHARS],
                paragraph_number=para_no,
                section_heading=heading,
            )
        )
    table_cells = 0
    for table in document.tables:
        for row in table.rows:
            cells = [_clean(c.text) for c in row.cells]
            row_text = " | ".join(c for c in cells if c)
            if not row_text:
                continue
            table_cells += 1
            para_no += 1
            total += len(row_text)
            _check_chars(total, max_chars)
            blocks.append(
                ExtractedBlock(
                    ref=f"para-{para_no}",
                    text=row_text[:MAX_BLOCK_CHARS],
                    paragraph_number=para_no,
                    section_heading="Table",
                )
            )
    if table_cells:
        warnings.append("Table rows were appended after body paragraphs; numbering reflects that.")
    if not blocks:
        raise ExtractionError("The DOCX contains no text.")
    return ExtractionResult(blocks=blocks, warnings=warnings)


def extract_txt(data: bytes, max_chars: int) -> ExtractionResult:
    text = _decode_text(data)
    _check_chars(len(text), max_chars)
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        raise ExtractionError("The text file contains no text.")
    blocks: list[ExtractedBlock] = []
    heading: str | None = None
    for i, para in enumerate(paragraphs, start=1):
        first_line = para.split("\n", 1)[0]
        if len(para) < 120 and "\n" not in para and not para.endswith("."):
            heading = first_line[:300]
        blocks.append(
            ExtractedBlock(ref=f"para-{i}", text=para, paragraph_number=i, section_heading=heading)
        )
    return ExtractionResult(blocks=blocks)


def extract(file_format: str, data: bytes, max_pages: int, max_chars: int) -> ExtractionResult:
    if file_format == "pdf":
        return extract_pdf(data, max_pages, max_chars)
    if file_format == "docx":
        return extract_docx(data, max_chars)
    if file_format == "txt":
        return extract_txt(data, max_chars)
    raise ExtractionError("Unsupported format.")
