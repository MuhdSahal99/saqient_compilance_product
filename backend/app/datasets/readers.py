"""Validate and read uploaded finance files into all-text Polars frames.

Formats: CSV (UTF-8), XLSX (first sheet; macros and formula cells rejected),
MT940 and CAMT.053 bank statements (parsed into canonical columns directly;
XML through defusedxml, no external entities). Values stay text here; typing
happens in ``build.py`` so every rejected value can be reported with its row.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import IO

import polars as pl
from defusedxml import ElementTree as DET

FORMATS = ("csv", "xlsx", "mt940", "camt053")
_EXT = {"csv": "csv", "xlsx": "xlsx", "sta": "mt940", "mt940": "mt940", "xml": "camt053"}
_MIMES = {
    "csv": {
        "text/csv",
        "application/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/octet-stream",
    },
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    },
    "mt940": {"text/plain", "application/octet-stream"},
    "camt053": {"application/xml", "text/xml", "application/octet-stream"},
}
MAX_XLSX_UNCOMPRESSED = 400 * 1024 * 1024
MAX_COLUMNS = 200
MAX_HEADER_LENGTH = 200


class DatasetFileError(ValueError):
    """Upload or parse failure. Message is safe to show users."""


@dataclass
class RawTable:
    frame: pl.DataFrame  # all columns pl.String, header excluded
    file_format: str
    # For bank formats the columns are already canonical and the mapping is fixed.
    fixed_mapping: dict[str, str] | None = None
    warnings: list[str] = field(default_factory=list)


def detect_format(filename: str, declared_mime: str, data: bytes, kind: str) -> str:
    if not data:
        raise DatasetFileError("The file is empty.")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsm", "xlsb", "xls"):
        raise DatasetFileError("Upload .xlsx without macros, or CSV.")
    fmt = _EXT.get(ext)
    if fmt is None:
        raise DatasetFileError("Unsupported file type. Upload CSV, XLSX, MT940 or CAMT.053 XML.")
    if fmt in ("mt940", "camt053") and kind != "bank_statement":
        raise DatasetFileError("MT940 and CAMT.053 files can only be bank statements.")
    mime = (declared_mime or "application/octet-stream").split(";")[0].strip().lower()
    if mime not in _MIMES[fmt]:
        raise DatasetFileError(f"The file's declared type ({mime}) does not match .{ext}.")
    if fmt == "xlsx":
        _check_xlsx(data)
    else:
        if b"\x00" in data[:8192]:
            raise DatasetFileError("The file looks binary, not text.")
        if fmt == "camt053" and b"<Document" not in data[:4096] and b":Document" not in data[:4096]:
            raise DatasetFileError("The XML file is not a CAMT.053 statement.")
        if fmt == "mt940" and b":20:" not in data[:4096]:
            raise DatasetFileError("The file is not an MT940 statement (no :20: field).")
    return fmt


def _check_xlsx(data: bytes) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise DatasetFileError("The file does not look like XLSX (missing ZIP signature).")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            names = {i.filename.lower() for i in infos}
            if "xl/workbook.xml" not in names or "[content_types].xml" not in names:
                raise DatasetFileError("The ZIP file is not an Excel workbook.")
            if any(n.endswith("vbaproject.bin") for n in names):
                raise DatasetFileError("Macro-enabled workbooks are not accepted.")
            if sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED:
                raise DatasetFileError("The workbook expands beyond the allowed size.")
            for info in infos:
                n = info.filename.lower()
                if n.startswith("xl/worksheets/") and n.endswith(".xml"):
                    with zf.open(info) as fh:
                        if _has_formula(fh):
                            raise DatasetFileError(
                                "The workbook contains formulas. "
                                "Paste values only and upload again."
                            )
    except zipfile.BadZipFile as exc:
        raise DatasetFileError("The XLSX file is corrupted.") from exc


_FORMULA = re.compile(rb"<(?:\w+:)?f[\s>/]")


def _has_formula(fh: IO[bytes]) -> bool:
    tail = b""
    while chunk := fh.read(1 << 20):
        if _FORMULA.search(tail + chunk):
            return True
        tail = chunk[-16:]
    return False


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetFileError("The file must be UTF-8 encoded.") from exc


def _check_headers(columns: list[str]) -> list[str]:
    cleaned = [c.strip() for c in columns]
    if not cleaned or all(not c for c in cleaned):
        raise DatasetFileError("The first row must contain column headers.")
    if len(cleaned) > MAX_COLUMNS:
        raise DatasetFileError(f"At most {MAX_COLUMNS} columns are supported.")
    if any(not c for c in cleaned):
        raise DatasetFileError("Every column needs a header.")
    if len(set(cleaned)) != len(cleaned):
        raise DatasetFileError("Column headers must be unique.")
    if any(len(c) > MAX_HEADER_LENGTH for c in cleaned):
        raise DatasetFileError("A column header is too long.")
    return cleaned


def _read_csv(data: bytes) -> pl.DataFrame:
    text = _decode_text(data)
    sample = text[:65536]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    # Polars renames duplicate headers silently; check the raw header row first.
    header = next(csv.reader(io.StringIO(sample), delimiter=delimiter), [])
    _check_headers(header)
    try:
        frame = pl.read_csv(
            io.BytesIO(text.encode("utf-8")),
            separator=delimiter,
            infer_schema=False,
            has_header=True,
        )
    except (pl.exceptions.ComputeError, pl.exceptions.NoDataError) as exc:
        raise DatasetFileError(
            "The CSV file could not be read: rows have inconsistent columns."
        ) from exc
    return frame


def _read_xlsx(data: bytes) -> pl.DataFrame:
    try:
        frame = pl.read_excel(data, engine="calamine", infer_schema_length=0, has_header=True)
    except Exception as exc:  # calamine raises several error types
        raise DatasetFileError("The XLSX file could not be read.") from exc
    return frame.with_columns(pl.all().cast(pl.String))


def read_table(data: bytes, file_format: str, max_rows: int) -> RawTable:
    if file_format == "mt940":
        table = RawTable(parse_mt940(data), "mt940")
        table.fixed_mapping = {c: c for c in table.frame.columns}
    elif file_format == "camt053":
        table = RawTable(parse_camt053(data), "camt053")
        table.fixed_mapping = {c: c for c in table.frame.columns}
    else:
        frame = _read_csv(data) if file_format == "csv" else _read_xlsx(data)
        frame.columns = _check_headers(frame.columns)
        # Drop rows where every cell is empty (trailing blank lines, spacer rows).
        frame = frame.filter(
            ~pl.all_horizontal(pl.all().is_null() | (pl.all().str.strip_chars() == ""))
        )
        table = RawTable(frame, file_format)
    if table.frame.height == 0:
        raise DatasetFileError("The file has no data rows.")
    if table.frame.height > max_rows:
        raise DatasetFileError(f"The file has more than {max_rows:,} rows.")
    return table


# ------------------------------------------------------------------ MT940

_TAG = re.compile(r"^:(\d{2}[A-Z]?):", re.M)
_LINE61 = re.compile(
    r"^(?P<date>\d{6})(?P<entry>\d{4})?(?P<mark>RC|RD|C|D)[A-Z]?(?P<amount>\d{1,15},\d{0,4})"
    r"(?P<type>[A-Z]\w{3})(?P<ref>[^/\n]*)(?://(?P<bankref>[^\n]*))?"
)
_BAL = re.compile(r"^[CD]\d{6}(?P<ccy>[A-Z]{3})")


def _mt_date(yymmdd: str) -> str:
    yy, mm, dd = int(yymmdd[:2]), yymmdd[2:4], yymmdd[4:6]
    return f"{2000 + yy if yy < 80 else 1900 + yy}-{mm}-{dd}"


def parse_mt940(data: bytes) -> pl.DataFrame:
    text = _decode_text(data).replace("\r\n", "\n")
    parts = _TAG.split(text)
    # parts = [prefix, tag1, value1, tag2, value2, ...]
    fields = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
    rows: list[dict[str, str | None]] = []
    ccy: str | None = None
    for tag, value in fields:
        if tag in ("60F", "60M"):
            m = _BAL.match(value)
            ccy = m.group("ccy") if m else None
        elif tag == "61":
            m = _LINE61.match(value)
            if not m:
                raise DatasetFileError(f"Unreadable :61: statement line ({len(rows) + 1}).")
            amount = m.group("amount").replace(",", ".")
            if amount.endswith("."):
                amount += "0"
            sign = "-" if m.group("mark") in ("D", "RC") else ""
            rows.append(
                {
                    "transaction_date": _mt_date(m.group("date")),
                    "value_date": None,
                    "amount": sign + amount,
                    "reference": (m.group("ref") or "").strip() or None,
                    "description": None,
                    "currency": ccy,
                }
            )
        elif tag == "86" and rows:
            rows[-1]["description"] = " ".join(value.split())[:1000]
    if not rows:
        raise DatasetFileError("The MT940 file has no statement lines.")
    if any(r["currency"] is None for r in rows):
        raise DatasetFileError("The MT940 file has no opening balance (:60F:) with a currency.")
    return pl.DataFrame(rows, schema={k: pl.String for k in rows[0]})


# ------------------------------------------------------------------ CAMT.053


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: object, *path: str) -> object | None:
    node = el
    for name in path:
        node = next((c for c in node if _local(c.tag) == name), None)  # type: ignore[attr-defined]
        if node is None:
            return None
    return node


def _text(el: object, *path: str) -> str | None:
    node = _child(el, *path)
    text = getattr(node, "text", None) if node is not None else None
    return text.strip() if text and text.strip() else None


def parse_camt053(data: bytes) -> pl.DataFrame:
    try:
        root = DET.fromstring(data, forbid_dtd=True)
    except Exception as exc:  # defusedxml raises on DTDs, entities and malformed XML
        raise DatasetFileError("The XML file could not be read safely.") from exc
    rows: list[dict[str, str | None]] = []
    for ntry in root.iter():
        if _local(ntry.tag) != "Ntry":
            continue
        amt = _child(ntry, "Amt")
        raw = getattr(amt, "text", None)
        try:
            value = Decimal((raw or "").strip())
        except InvalidOperation as exc:
            raise DatasetFileError(f"Entry {len(rows) + 1} has no valid amount.") from exc
        indicator = _text(ntry, "CdtDbtInd")
        if indicator not in ("CRDT", "DBIT"):
            raise DatasetFileError(f"Entry {len(rows) + 1} has no credit/debit indicator.")
        booked = _text(ntry, "BookgDt", "Dt") or (_text(ntry, "BookgDt", "DtTm") or "")[:10]
        if not booked:
            raise DatasetFileError(f"Entry {len(rows) + 1} has no booking date.")
        details = _child(ntry, "NtryDtls", "TxDtls")
        desc = _text(ntry, "AddtlNtryInf")
        party = None
        if details is not None:
            desc = desc or _text(details, "RmtInf", "Ustrd")
            role = ("Dbtr", "Pty") if indicator == "CRDT" else ("Cdtr", "Pty")
            party = _text(details, "RltdPties", role[0], role[1], "Nm") or _text(
                details, "RltdPties", role[0], "Nm"
            )
        rows.append(
            {
                "transaction_date": booked,
                "value_date": _text(ntry, "ValDt", "Dt"),
                "amount": str(-value if indicator == "DBIT" else value),
                "reference": _text(ntry, "AcctSvcrRef") or _text(ntry, "NtryRef"),
                "description": " ".join(desc.split())[:1000] if desc else None,
                "currency": amt.get("Ccy") if amt is not None else None,  # type: ignore[attr-defined]
                "counterparty": party,
            }
        )
    if not rows:
        raise DatasetFileError("The CAMT.053 file has no entries.")
    return pl.DataFrame(rows, schema={k: pl.String for k in rows[0]})
