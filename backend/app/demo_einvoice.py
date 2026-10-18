"""Synthetic e-invoicing and VAT content for tests and the demo seed.

Everything here is invented for demonstration: the schema bundle is a tiny
UBL-shaped XSD (not the official UBL, PINT-AE or ZATCA artefacts), the rule
values (tax id shapes, waves, boxes, blocked categories) are deliberately
fictional, and every rule carries a TODO so it stays draft. Synthetic
demonstration content — not legal guidance.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.einvoice import xmlsafe
from app.engine.einvoice_checks import invoice_hash

SYNTHETIC_NOTE = "Synthetic demonstration content — not legal guidance."
SYNTHETIC_TODO = "Synthetic value. Replace with the official value and its source before use."

UBL_INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"

_MAIN_XSD = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- {SYNTHETIC_NOTE} A minimal UBL-shaped schema for tests; not an official schema. -->
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="{UBL_INV}"
  xmlns:cbc="{CBC}" elementFormDefault="qualified">
  <xs:import namespace="{CBC}" schemaLocation="common/cbc.xsd"/>
  <xs:element name="Invoice">
    <xs:complexType>
      <xs:sequence>
        <xs:any namespace="##other" processContents="lax" minOccurs="1" maxOccurs="unbounded"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

_CBC_XSD = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- {SYNTHETIC_NOTE} -->
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="{CBC}"
  xmlns:cbc="{CBC}" elementFormDefault="qualified">
  <xs:complexType name="Amount">
    <xs:simpleContent>
      <xs:extension base="xs:decimal">
        <xs:attribute name="currencyID" type="xs:string" use="required"/>
      </xs:extension>
    </xs:simpleContent>
  </xs:complexType>
  <xs:element name="IssueDate" type="xs:date"/>
  <xs:element name="IssueTime" type="xs:time"/>
  <xs:element name="LineExtensionAmount" type="cbc:Amount"/>
  <xs:element name="TaxExclusiveAmount" type="cbc:Amount"/>
  <xs:element name="TaxInclusiveAmount" type="cbc:Amount"/>
  <xs:element name="PayableAmount" type="cbc:Amount"/>
  <xs:element name="TaxAmount" type="cbc:Amount"/>
  <xs:element name="TaxableAmount" type="cbc:Amount"/>
  <xs:element name="PriceAmount" type="cbc:Amount"/>
  <xs:element name="Percent" type="xs:decimal"/>
</xs:schema>
"""


def xsd_bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in (("main.xsd", _MAIN_XSD), ("common/cbc.xsd", _CBC_XSD)):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            z.writestr(info, body)
    return buf.getvalue()


XSD_ENTRY = "main.xsd"


# ---------------------------------------------------------------- invoices


@dataclass
class Line:
    quantity: str
    price: str
    percent: str = "5"
    category: str = "S"
    net: str | None = None  # override the stated line net (to make arithmetic fail)


@dataclass
class InvoiceSpec:
    number: str
    uuid: str
    issue_date: str = "2026-03-15"
    issue_time: str = "10:00:00"
    currency: str = "AED"
    type_code: str = "380"
    seller_name: str = "Synthetic Seller LLC"
    seller_trn: str = "900000000000001"
    seller_country: str = "AE"
    buyer_name: str = "Synthetic Buyer FZE"
    buyer_trn: str | None = "900000000000002"
    lines: list[Line] = field(default_factory=lambda: [Line("2", "100.00"), Line("1", "50.00")])
    customization: str = "urn:synthetic:pint:billing-1@ae-1"
    omit: tuple[str, ...] = ()
    tax_override: str | None = None
    payable_override: str | None = None
    # ZATCA-style fields
    icv: int | None = None
    pih: str | None = None
    qr: bool = False
    qr_total_override: str | None = None


def _q(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _tlv(items: list[tuple[int, bytes]]) -> str:
    out = b"".join(bytes([t, len(v)]) + v for t, v in items)
    return base64.b64encode(out).decode()


def invoice_xml(spec: InvoiceSpec) -> bytes:
    cur = spec.currency
    lines_xml = []
    nets: list[Decimal] = []
    by_rate: dict[str, Decimal] = {}
    for i, ln in enumerate(spec.lines, 1):
        net = _q(Decimal(ln.quantity) * Decimal(ln.price))
        stated = Decimal(ln.net) if ln.net is not None else net
        nets.append(stated)
        by_rate[ln.percent] = by_rate.get(ln.percent, Decimal(0)) + stated
        lines_xml.append(
            f"""  <cac:InvoiceLine>
    <cbc:ID>{i}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">{ln.quantity}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="{cur}">{stated}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Synthetic item {i}</cbc:Name>
      <cac:ClassifiedTaxCategory><cbc:ID>{ln.category}</cbc:ID><cbc:Percent>{ln.percent}</cbc:Percent>
      <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="{cur}">{ln.price}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>"""
        )
    line_total = sum(nets, Decimal(0))
    subtotals = []
    tax_total = Decimal(0)
    for rate, taxable in sorted(by_rate.items()):
        tax = _q(taxable * Decimal(rate) / 100)
        tax_total += tax
        subtotals.append(
            f"""    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="{cur}">{taxable}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="{cur}">{tax}</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{rate}</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>"""
        )
    stated_tax = Decimal(spec.tax_override) if spec.tax_override else tax_total
    incl = line_total + stated_tax
    payable = Decimal(spec.payable_override) if spec.payable_override else incl
    refs = []
    if spec.icv is not None:
        refs.append(
            f"  <cac:AdditionalDocumentReference><cbc:ID>ICV</cbc:ID>"
            f"<cbc:UUID>{spec.icv}</cbc:UUID></cac:AdditionalDocumentReference>"
        )
    if spec.pih is not None:
        refs.append(
            "  <cac:AdditionalDocumentReference><cbc:ID>PIH</cbc:ID><cac:Attachment>"
            f'<cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">{spec.pih}'
            "</cbc:EmbeddedDocumentBinaryObject></cac:Attachment></cac:AdditionalDocumentReference>"
        )
    buyer_tax = (
        f"<cac:PartyTaxScheme><cbc:CompanyID>{spec.buyer_trn}</cbc:CompanyID>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
        if spec.buyer_trn
        else ""
    )
    parts = {
        "CustomizationID": f"  <cbc:CustomizationID>{spec.customization}</cbc:CustomizationID>",
        "ID": f"  <cbc:ID>{spec.number}</cbc:ID>",
        "UUID": f"  <cbc:UUID>{spec.uuid}</cbc:UUID>",
        "IssueDate": f"  <cbc:IssueDate>{spec.issue_date}</cbc:IssueDate>",
        "IssueTime": f"  <cbc:IssueTime>{spec.issue_time}</cbc:IssueTime>",
        "InvoiceTypeCode": f"  <cbc:InvoiceTypeCode>{spec.type_code}</cbc:InvoiceTypeCode>",
        "DocumentCurrencyCode": f"  <cbc:DocumentCurrencyCode>{cur}</cbc:DocumentCurrencyCode>",
    }
    body = "\n".join(v for k, v in parts.items() if k not in spec.omit)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="{UBL_INV}" xmlns:cac="{CAC}" xmlns:cbc="{CBC}" xmlns:ext="{EXT}">
{body}
{chr(10).join(refs)}
QR_PLACEHOLDER
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PostalAddress><cbc:CityName>Synthetic City</cbc:CityName>
      <cac:Country><cbc:IdentificationCode>{spec.seller_country}</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>{spec.seller_trn}</cbc:CompanyID>
      <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>{spec.seller_name}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PostalAddress><cac:Country><cbc:IdentificationCode>{spec.seller_country}</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    {buyer_tax}
    <cac:PartyLegalEntity><cbc:RegistrationName>{spec.buyer_name}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="{cur}">{stated_tax}</cbc:TaxAmount>
{chr(10).join(subtotals)}
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="{cur}">{line_total}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="{cur}">{line_total}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="{cur}">{incl}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="{cur}">{payable}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
{chr(10).join(lines_xml)}
</Invoice>
"""
    qr = ""
    if spec.qr:
        total = spec.qr_total_override or str(incl)
        items = [
            (1, spec.seller_name.encode()),
            (2, spec.seller_trn.encode()),
            (3, f"{spec.issue_date}T{spec.issue_time}".encode()),
            (4, total.encode()),
            (5, str(stated_tax).encode()),
        ]
        qr = (
            "  <cac:AdditionalDocumentReference><cbc:ID>QR</cbc:ID><cac:Attachment>"
            f'<cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">{_tlv(items)}'
            "</cbc:EmbeddedDocumentBinaryObject></cac:Attachment></cac:AdditionalDocumentReference>"
        )
    return xml.replace("QR_PLACEHOLDER", qr).encode()


INITIAL_PIH = base64.b64encode(b"synthetic-initial-previous-invoice-hash").decode()
HASH_ENCODING = "base64_digest"


def zatca_chain(count: int, break_at: int | None = None) -> list[tuple[str, bytes]]:
    """A synthetic ZATCA-style sequence; ``break_at`` gives that invoice a wrong PIH."""
    out: list[tuple[str, bytes]] = []
    prev_hash = INITIAL_PIH
    for i in range(1, count + 1):
        pih = prev_hash if i != break_at else INITIAL_PIH[::-1]
        spec = InvoiceSpec(
            number=f"SYN-SA-{i:04d}",
            uuid=f"00000000-0000-4000-8000-{i:012d}",
            currency="SAR",
            seller_country="SA",
            seller_trn="800000000000008",
            buyer_trn=None,
            customization="urn:synthetic:zatca",
            icv=i,
            pih=pih,
            qr=True,
        )
        xml = invoice_xml(spec)
        prev_hash = invoice_hash(xmlsafe.parse_xml(xml), HASH_ENCODING)
        out.append((f"sa-{i:04d}.xml", xml))
    return out


def zip_of(files: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files:
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), body)
    return buf.getvalue()


# ---------------------------------------------------------------- synthetic rules

_INV = "/inv:Invoice"

MANDATORY_FIELDS = [
    {"id": "SYN-01", "label": "Invoice number", "xpath": f"{_INV}/cbc:ID", "max": 1},
    {"id": "SYN-02", "label": "Issue date", "xpath": f"{_INV}/cbc:IssueDate", "max": 1},
    {"id": "SYN-03", "label": "Invoice type code", "xpath": f"{_INV}/cbc:InvoiceTypeCode"},
    {"id": "SYN-04", "label": "Document currency", "xpath": f"{_INV}/cbc:DocumentCurrencyCode"},
    {
        "id": "SYN-05",
        "label": "Seller tax number",
        "xpath": f"{_INV}/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
    },
    {"id": "SYN-06", "label": "Invoice line", "xpath": f"{_INV}/cac:InvoiceLine"},
    {"id": "SYN-07", "label": "Unique identifier", "xpath": f"{_INV}/cbc:UUID"},
]
CODE_LISTS = [
    {
        "id": "SYN-CL-1",
        "label": "invoice type code",
        "xpath": f"{_INV}/cbc:InvoiceTypeCode",
        "allowed": ["380", "381", "388"],
    },
    {
        "id": "SYN-CL-2",
        "label": "currency code",
        "xpath": f"{_INV}/cbc:DocumentCurrencyCode",
        "allowed": ["AED", "SAR", "USD"],
    },
]
# Fictional shapes: real formats must be entered from official sources.
TAX_ID_FORMATS = {
    "AE": {"length": 15, "digits_only": True, "prefix": "9"},
    "SA": {"length": 15, "digits_only": True, "prefix": "8", "suffix": "8"},
}
GO_LIVE_WAVES = [
    {
        "label": "Synthetic wave 1 (large)",
        "min_revenue": "50000000",
        "currency": "AED",
        "go_live": "2027-01-01",
        "milestones": [{"id": "asp", "label": "Appoint a service provider", "date": "2026-09-30"}],
    },
    {
        "label": "Synthetic wave 2 (others)",
        "max_revenue": "50000000",
        "currency": "AED",
        "go_live": "2027-07-01",
        "milestones": [{"id": "asp", "label": "Appoint a service provider", "date": "2027-03-31"}],
    },
]
BOX_LAYOUT = {
    "boxes": [
        {
            "code": "S1",
            "label": "Standard-rated sales (net)",
            "register": "sales_register",
            "treatments": ["standard"],
            "measure": "net_amount",
        },
        {
            "code": "S1T",
            "label": "Standard-rated sales (VAT)",
            "register": "sales_register",
            "treatments": ["standard"],
            "measure": "tax_amount",
        },
        {
            "code": "S2",
            "label": "Zero-rated sales",
            "register": "sales_register",
            "treatments": ["zero_rated", "zero_rated_export"],
            "measure": "net_amount",
        },
        {
            "code": "S3",
            "label": "Exempt sales",
            "register": "sales_register",
            "treatments": ["exempt"],
            "measure": "net_amount",
        },
        {
            "code": "R1",
            "label": "Reverse-charge purchases (net)",
            "register": "purchase_register",
            "treatments": ["reverse_charge"],
            "measure": "net_amount",
        },
        {
            "code": "R1T",
            "label": "Reverse-charge VAT due",
            "register": "purchase_register",
            "treatments": ["reverse_charge"],
            "measure": "tax_amount",
        },
        {
            "code": "P1",
            "label": "Purchases (net)",
            "register": "purchase_register",
            "treatments": ["standard", "reverse_charge"],
            "measure": "net_amount",
        },
        {
            "code": "P1T",
            "label": "Recoverable input VAT",
            "register": "purchase_register",
            "treatments": ["standard", "reverse_charge"],
            "measure": "recoverable_tax",
        },
    ],
    "totals": [
        {"code": "T1", "label": "Total output VAT", "plus": ["S1T", "R1T"]},
        {"code": "T2", "label": "Net VAT payable", "plus": ["T1"], "minus": ["P1T"]},
    ],
    "output_tax_boxes": ["S1T", "R1T"],
    "input_tax_boxes": ["P1T"],
}
BLOCKED_CATEGORIES = ["entertainment", "personal vehicle"]
OBLIGATIONS = [
    {
        "id": "vat_return",
        "label": "VAT return (synthetic)",
        "tax_type": "vat",
        "frequency": "quarterly",
        "months_after": 1,
        "day_of_month": 28,
    },
]


def rules(prefix: str = "syn.einvoice", vat_prefix: str = "syn.vat") -> list[dict[str, Any]]:
    """Rule pack rows (draft, synthetic, with a TODO each) for the e-invoice and VAT checks."""

    def r(key: str, value_type: str, value: Any, title: str, unit: str = "") -> dict[str, Any]:
        raw = json.dumps(value) if value_type == "json" else str(value)
        return {
            "rule_key": key,
            "title": title,
            "value_type": value_type,
            "value": raw,
            "unit": unit,
            "effective_from": "2020-01-01",
            "effective_to": None,
            "source_url": None,
            "source_note": SYNTHETIC_NOTE,
            "todo": SYNTHETIC_TODO,
        }

    return [
        r(f"{prefix}.mandatory_fields", "json", MANDATORY_FIELDS, "Mandatory invoice fields"),
        r(f"{prefix}.code_lists", "json", CODE_LISTS, "Invoice code lists"),
        r(f"{prefix}.amount_decimals", "integer", 2, "Amount decimals"),
        r(f"{prefix}.rounding_mode", "string", "half_up", "Rounding mode"),
        r(f"{prefix}.amount_tolerance", "decimal", "0.01", "Arithmetic tolerance"),
        r(f"{prefix}.tax_id_formats", "json", TAX_ID_FORMATS, "Tax number shapes"),
        r(f"{prefix}.qr_required_tags", "json", ["1", "2", "3", "4", "5"], "QR tags"),
        r(f"{prefix}.hash_encoding", "string", HASH_ENCODING, "Invoice hash encoding"),
        r(f"{prefix}.initial_pih", "string", INITIAL_PIH, "Initial previous invoice hash"),
        r(f"{prefix}.go_live_waves", "json", GO_LIVE_WAVES, "E-invoicing go-live waves"),
        r(f"{vat_prefix}.box_layout", "json", BOX_LAYOUT, "VAT return box layout"),
        r(f"{vat_prefix}.box_tolerance", "decimal", "1.00", "Box tolerance", "currency"),
        r(f"{vat_prefix}.blocked_categories", "json", BLOCKED_CATEGORIES, "Blocked input VAT"),
        r(f"{vat_prefix}.tax_id_formats", "json", TAX_ID_FORMATS, "Tax number shapes"),
        r(f"{vat_prefix}.obligations", "json", OBLIGATIONS, "Filing obligations"),
        r(
            f"{vat_prefix}.required_fields",
            "json",
            {"*": ["name", "address_line1", "city", "country"], "SA": ["building_number"]},
            "Required party fields",
        ),
    ]
