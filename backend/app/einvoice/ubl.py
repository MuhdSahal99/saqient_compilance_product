"""Reading UBL 2.1 invoices (PINT-AE / Peppol and ZATCA both use UBL 2.1).

Element names and namespaces here are the UBL standard's, not regulatory
values: which fields are mandatory, which codes are allowed and how amounts
round all come from the rule pack.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "sig": "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
    "sac": "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
    "sbc": "urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "xades": "http://uri.etsi.org/01903/v1.3.2#",
}
PREFIX = {v: k for k, v in NS.items()}
MAX_VALUE = 200


def qname(el: Any) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        return f"{PREFIX.get(uri, 'ns')}:{local}"
    return tag


def path_of(el: Any) -> str:
    """An absolute, prefixed XPath with sibling positions, e.g. /inv:Invoice/cac:InvoiceLine[2]."""
    parts: list[str] = []
    node = el
    while node is not None and isinstance(node.tag, str):
        parent = node.getparent()
        name = qname(node)
        if parent is not None:
            same = [c for c in parent if c.tag == node.tag]
            if len(same) > 1:
                name += f"[{same.index(node) + 1}]"
        parts.append(name)
        node = parent
    return "/" + "/".join(reversed(parts))


def text(el: Any) -> str | None:
    if el is None:
        return None
    t = el.text
    return t.strip() if t is not None else None


def first(el: Any, xpath: str) -> Any:
    found = el.xpath(xpath, namespaces=NS)
    return found[0] if found else None


def ftext(el: Any, xpath: str) -> str | None:
    return text(first(el, xpath))


def amount(el: Any) -> Decimal | None:
    raw = text(el)
    if raw is None or raw == "":
        return None
    try:
        d = Decimal(raw)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def doc_root_kind(root: Any) -> str:
    tag = root.tag if isinstance(root.tag, str) else ""
    if tag == f"{{{NS['inv']}}}Invoice":
        return "Invoice"
    if tag == f"{{{NS['cn']}}}CreditNote":
        return "CreditNote"
    return ""


def r(root: Any) -> str:
    """XPath prefix for the root element."""
    return "/inv:Invoice" if doc_root_kind(root) == "Invoice" else "/cn:CreditNote"


def additional_ref(root: Any, ref_id: str) -> Any:
    """cac:AdditionalDocumentReference with the given cbc:ID (e.g. ICV, PIH, QR)."""
    for ref in root.xpath("cac:AdditionalDocumentReference", namespaces=NS):
        if ftext(ref, "cbc:ID") == ref_id:
            return ref
    return None


def embedded(ref: Any) -> Any:
    return None if ref is None else first(ref, "cac:Attachment/cbc:EmbeddedDocumentBinaryObject")


def b64(raw: str | None) -> bytes | None:
    if not raw:
        return None
    try:
        return base64.b64decode("".join(raw.split()), validate=True)
    except (binascii.Error, ValueError):
        return None


def detect_profile(root: Any) -> str:
    """A label for listing; the review check states which profile it validates."""
    customization = ftext(root, "cbc:CustomizationID") or ""
    if "pint" in customization.lower() and "ae" in customization.lower():
        return "pint_ae"
    if additional_ref(root, "ICV") is not None or additional_ref(root, "PIH") is not None:
        return "zatca"
    return "unknown"


@dataclass(frozen=True)
class Header:
    document_type: str
    profile: str
    invoice_number: str | None
    invoice_uuid: str | None
    issue_date: date | None
    type_code: str | None
    icv: int | None
    currency: str | None
    payable_amount: Decimal | None
    tax_amount: Decimal | None


def header(root: Any) -> Header:
    kind = doc_root_kind(root)
    issue: date | None
    try:
        raw = ftext(root, "cbc:IssueDate")
        issue = date.fromisoformat(raw) if raw else None
    except ValueError:
        issue = None
    icv_raw = (
        ftext(additional_ref(root, "ICV"), "cbc:UUID")
        if additional_ref(root, "ICV") is not None
        else None
    )
    icv = int(icv_raw) if icv_raw and icv_raw.isdigit() and len(icv_raw) < 18 else None
    currency = ftext(root, "cbc:DocumentCurrencyCode")
    tax = None
    for tt in root.xpath("cac:TaxTotal", namespaces=NS):
        el = first(tt, "cbc:TaxAmount")
        if el is not None and (currency is None or el.get("currencyID") == currency):
            tax = amount(el)
            break
    type_el = (
        first(root, "cbc:InvoiceTypeCode")
        if kind == "Invoice"
        else first(root, "cbc:CreditNoteTypeCode")
    )
    return Header(
        document_type=kind,
        profile=detect_profile(root),
        invoice_number=(ftext(root, "cbc:ID") or None),
        invoice_uuid=(ftext(root, "cbc:UUID") or None),
        issue_date=issue,
        type_code=text(type_el),
        icv=icv,
        currency=currency[:3] if currency else None,
        payable_amount=amount(first(root, "cac:LegalMonetaryTotal/cbc:PayableAmount")),
        tax_amount=tax,
    )


def clip(value: str | None) -> str | None:
    if value is None:
        return None
    return value if len(value) <= MAX_VALUE else value[:MAX_VALUE] + "…"
