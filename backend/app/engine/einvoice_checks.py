"""E-invoice checks (engine 1.2.0): validation, go-live deadline, platform rejections.

``einvoice_validate`` checks each stored UBL invoice of the review against the
rule pack: XSD schema (a verified-or-draft bundle attached to the pack),
mandatory fields, code lists, arithmetic (named formulas, rounding and
tolerance from the pack), tax registration number shapes and, for ZATCA, the
QR code fields and the previous-invoice-hash chain. Each failed rule becomes
one finding whose evidence lists every failing file with the XML path, line
and value. A passing check is not a statement that an invoice is compliant.
"""

from __future__ import annotations

import base64
import copy
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any, Literal

import polars as pl
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from app.einvoice import ubl, xmlsafe
from app.engine.data_checks import (
    DataCheckError,
    DataContext,
    DataEvaluation,
    FindingGroup,
    InputMissing,
    RuleKey,
    _need,
    _rows_evidence,
)
from app.engine.formats import describe_tax_id, normalise_tax_id, tax_id_ok
from app.models import CheckOutcome, DatasetKind

NS = ubl.NS
MAX_GROUPS = 60
MAX_EVIDENCE_PER_GROUP = 50
MAX_SCHEMA_ERRORS_PER_FILE = 20


@dataclass
class LoadedInvoice:
    file_id: str
    filename: str
    sha256: str
    invoice_number: str | None
    invoice_uuid: str | None
    icv: int | None
    raw: bytes
    root: Any = None
    parse_error: str | None = None


@dataclass
class InvoiceSet:
    invoices: list[LoadedInvoice]

    def parsed(self) -> list[LoadedInvoice]:
        return [i for i in self.invoices if i.root is not None]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _xml_ev(
    inv: LoadedInvoice,
    xpath: str,
    message: str,
    *,
    line: int | None = None,
    value: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "xml",
        "einvoice_file_id": inv.file_id,
        "filename": inv.filename,
        "sha256": inv.sha256,
        "invoice_number": inv.invoice_number,
        "xpath": xpath,
        "line": line,
        "value": ubl.clip(value),
        "label": message,
        "detail": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in (detail or {}).items()},
    }


@dataclass
class _Groups:
    """Collects failures by rule id; one finding per id."""

    items: dict[str, FindingGroup] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    files: dict[str, set[str]] = field(default_factory=dict)

    def add(self, key: str, title: str, ev: dict[str, Any]) -> None:
        g = self.items.get(key)
        if g is None:
            if len(self.items) >= MAX_GROUPS:
                key = "more"
                g = self.items.get(key)
                title = "Further issues (limit reached)"
            if g is None:
                g = FindingGroup(key=key, title=title, message="")
                self.items[key] = g
        self.counts[key] = self.counts.get(key, 0) + 1
        self.files.setdefault(key, set()).add(ev.get("einvoice_file_id") or ev.get("label", ""))
        if len(g.evidence) < MAX_EVIDENCE_PER_GROUP:
            g.evidence.append(ev)

    def finish(self) -> list[FindingGroup]:
        out = []
        for key in sorted(self.items):
            g = self.items[key]
            n, files = self.counts[key], len(self.files[key])
            g.message = f"{g.title}: {n} occurrence(s) in {files} file(s)."
            out.append(g)
        return out


def _rule(ctx: DataContext, key: str, meta: dict[str, Any]) -> Any:
    try:
        rule = ctx.resolve_rule(key)
    except LookupError as exc:
        raise DataCheckError(str(exc)) from exc
    snap = rule.snapshot()
    if snap not in meta.setdefault("rules", []):
        meta["rules"].append(snap)
    w = rule.warning()
    if w and w not in meta.setdefault("warnings", []):
        meta["warnings"].append(w)
    return rule.value


def _typed_rule(ctx: DataContext, key: str, meta: dict[str, Any]) -> Any:
    from app.services import rule_schemas

    raw = _rule(ctx, key, meta)
    try:
        return rule_schemas.typed(key, raw)
    except rule_schemas.RuleShapeError as exc:
        raise DataCheckError(f"Rule '{key}' has the wrong shape: {exc}") from exc


def _evaluation(groups: _Groups, checked: int, meta: dict[str, Any], what: str) -> DataEvaluation:
    found = groups.finish()
    meta["groups"] = [
        {"key": g.key, "title": g.title, "count": groups.counts[g.key]} for g in found
    ]
    meta["exception_count"] = sum(groups.counts.values())
    if not found:
        return DataEvaluation(
            CheckOutcome.NO_EXCEPTIONS, False, f"No issues found in {checked} {what}.", [], meta
        )
    evidence = [g.evidence[0] for g in found if g.evidence][:20]
    return DataEvaluation(
        CheckOutcome.EXCEPTIONS_FOUND,
        True,
        f"{len(found)} rule(s) failed across {checked} {what} "
        f"({meta['exception_count']} occurrence(s)).",
        evidence,
        meta,
        found,
    )


# ---------------------------------------------------------------- validation

Part = Literal[
    "parse",
    "schema",
    "mandatory",
    "code_lists",
    "arithmetic",
    "tax_ids",
    "qr",
    "hash",
    "chain",
    "duplicates",
]
ALL_PARTS: tuple[Part, ...] = (
    "parse",
    "schema",
    "mandatory",
    "code_lists",
    "arithmetic",
    "tax_ids",
    "qr",
    "hash",
    "chain",
    "duplicates",
)
ZATCA_ONLY = {"qr", "hash", "chain"}

FORMULAS = {
    "line_net": "line LineExtensionAmount = round(quantity × price ÷ base quantity) + line "
    "charges − line allowances",
    "sum_lines": "LineExtensionAmount (total) = Σ line LineExtensionAmount",
    "allowance_total": "AllowanceTotalAmount = Σ document allowances",
    "charge_total": "ChargeTotalAmount = Σ document charges",
    "tax_exclusive": "TaxExclusiveAmount = LineExtensionAmount − AllowanceTotalAmount + "
    "ChargeTotalAmount",
    "tax_subtotal": "TaxSubtotal TaxAmount = round(TaxableAmount × Percent ÷ 100)",
    "tax_total": "TaxTotal TaxAmount = Σ TaxSubtotal TaxAmount",
    "tax_inclusive": "TaxInclusiveAmount = TaxExclusiveAmount + TaxTotal TaxAmount",
    "payable": "PayableAmount = TaxInclusiveAmount − PrepaidAmount + PayableRoundingAmount",
}


class EInvoiceValidateCheck(_M):
    """Validate the review's e-invoices against rule pack schemas and rules."""

    type: Literal["einvoice_validate"]
    profile: Literal["pint_ae", "zatca"]
    rules_prefix: RuleKey = Field(description="e.g. 'ae.einvoice'; rule keys hang off it")
    parts: list[Part] = Field(default_factory=lambda: list(ALL_PARTS), min_length=1)
    default_country: str = Field(pattern=r"^[A-Z]{2}$")
    xsd_file: RuleKey | None = None
    expect_complete_chain: bool = False

    def datasets_needed(self) -> set[DatasetKind]:
        return set()

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        if ctx.einvoices is None or not ctx.einvoices.invoices:
            raise InputMissing("Not run: this review has no e-invoices.")
        parts = [p for p in self.parts if self.profile == "zatca" or p not in ZATCA_ONLY]
        meta["profile"] = self.profile
        meta["parts"] = parts
        p = self.rules_prefix
        g = _Groups()
        invoices: list[LoadedInvoice] = ctx.einvoices.invoices
        if "parse" in parts:
            for inv in invoices:
                if inv.root is None:
                    g.add(
                        "parse",
                        "File is not a readable UBL invoice",
                        _xml_ev(inv, "/", inv.parse_error or "Not readable."),
                    )
        docs = [i for i in invoices if i.root is not None]
        if "schema" in parts:
            self._schema(ctx, meta, docs, g)
        if "mandatory" in parts:
            fields = _typed_rule(ctx, f"{p}.mandatory_fields", meta)
            for inv in docs:
                _mandatory(inv, fields, g)
        if "code_lists" in parts:
            lists = _typed_rule(ctx, f"{p}.code_lists", meta)
            for inv in docs:
                _code_lists(inv, lists, g)
        if "arithmetic" in parts:
            decimals = int(_rule(ctx, f"{p}.amount_decimals", meta))
            mode_raw = str(_rule(ctx, f"{p}.rounding_mode", meta)).lower()
            if mode_raw not in ("half_up", "half_even"):
                raise DataCheckError(f"Rule '{p}.rounding_mode' must be half_up or half_even.")
            tol = Decimal(_rule(ctx, f"{p}.amount_tolerance", meta))
            rounding = ROUND_HALF_UP if mode_raw == "half_up" else ROUND_HALF_EVEN
            meta["formulas"] = FORMULAS
            for inv in docs:
                _arithmetic(inv, decimals, rounding, tol, g)
        if "tax_ids" in parts:
            formats = _typed_rule(ctx, f"{p}.tax_id_formats", meta)
            for inv in docs:
                _tax_ids(inv, formats, self.default_country, g, meta)
        hashes: dict[str, str] = {}
        if {"qr", "hash", "chain"} & set(parts):
            encoding = str(_rule(ctx, f"{p}.hash_encoding", meta))
            if encoding not in ("base64_digest", "base64_hex"):
                raise DataCheckError(
                    f"Rule '{p}.hash_encoding' must be base64_digest or base64_hex."
                )
            meta["hash_method"] = (
                "SHA-256 over C14N 1.0 of the invoice without ext:UBLExtensions, cac:Signature "
                f"and the QR reference; encoded {encoding}"
            )
            for inv in docs:
                hashes[inv.file_id] = invoice_hash(inv.root, encoding)
        if "qr" in parts:
            tags = _typed_rule(ctx, f"{p}.qr_required_tags", meta)
            for inv in docs:
                _qr(inv, [str(t) for t in tags], hashes.get(inv.file_id), g)
        if "hash" in parts:
            for inv in docs:
                _signed_digest(inv, g)
        if "chain" in parts:
            initial = str(_rule(ctx, f"{p}.initial_pih", meta))
            _chain(docs, hashes, initial, self.expect_complete_chain, g)
        if "duplicates" in parts:
            _duplicates(docs, g)
        meta["files_checked"] = len(invoices)
        return _evaluation(g, len(invoices), meta, "invoice(s)")

    def _schema(
        self, ctx: DataContext, meta: dict[str, Any], docs: list[LoadedInvoice], g: _Groups
    ) -> None:
        if ctx.resolve_file is None:
            raise DataCheckError("This check needs a rule pack with a schema bundle.")
        key = self.xsd_file or f"{self.rules_prefix}.xsd"
        try:
            f = ctx.resolve_file(key)
            data = f.read()
            schema = xmlsafe.cached_schema(f.sha256, data, f.entry_point)
        except LookupError as exc:
            raise DataCheckError(str(exc)) from exc
        except xmlsafe.UnsafeXML as exc:
            raise DataCheckError(f"Schema bundle '{key}': {exc}") from exc
        meta.setdefault("files", []).append(f.snapshot())
        w = f.warning()
        if w and w not in meta.setdefault("warnings", []):
            meta["warnings"].append(w)
        for inv in docs:
            if schema.validate(etree.ElementTree(inv.root)):
                continue
            for e in list(schema.error_log)[:MAX_SCHEMA_ERRORS_PER_FILE]:
                g.add(
                    "schema",
                    "Invoice does not validate against the schema",
                    _xml_ev(inv, e.path or "/", e.message, line=e.line),
                )


def _swap_root(inv: LoadedInvoice, xpath: str) -> str:
    if ubl.doc_root_kind(inv.root) == "CreditNote" and xpath.startswith("/inv:Invoice"):
        return "/cn:CreditNote" + xpath[len("/inv:Invoice") :]
    return xpath


def _present(node: Any) -> bool:
    if not isinstance(node, etree._Element):
        return str(node).strip() != ""
    return len(node) > 0 or (node.text or "").strip() != ""


def _type_code(inv: LoadedInvoice) -> str:
    return ubl.ftext(inv.root, "cbc:InvoiceTypeCode|cbc:CreditNoteTypeCode") or ""


def _mandatory(inv: LoadedInvoice, fields: Iterable[Any], g: _Groups) -> None:
    code = _type_code(inv)
    for f in fields:
        if f.when_type and code not in f.when_type:
            continue
        xp = _swap_root(inv, f.xpath)
        try:
            found = [n for n in inv.root.getroottree().xpath(xp, namespaces=NS) if _present(n)]
        except etree.XPathError as exc:
            raise DataCheckError(f"Field {f.id}: the XPath is not valid.") from exc
        n = len(found)
        if n < f.min:
            g.add(
                f"mandatory:{f.id}",
                f"Missing {f.id} {f.label}",
                _xml_ev(inv, xp, f"{f.id} {f.label} missing", detail={"found": n, "min": f.min}),
            )
        elif f.max is not None and n > f.max:
            for node in found[f.max :]:
                el = node if isinstance(node, etree._Element) else node.getparent()
                g.add(
                    f"mandatory:{f.id}",
                    f"Too many {f.id} {f.label}",
                    _xml_ev(
                        inv,
                        ubl.path_of(el),
                        f"{f.id} {f.label} occurs more than {f.max} time(s)",
                        line=el.sourceline,
                    ),
                )


def _code_lists(inv: LoadedInvoice, lists: Iterable[Any], g: _Groups) -> None:
    for cl in lists:
        xp = _swap_root(inv, cl.xpath)
        try:
            nodes = inv.root.getroottree().xpath(xp, namespaces=NS)
        except etree.XPathError as exc:
            raise DataCheckError(f"Code list {cl.id}: the XPath is not valid.") from exc
        allowed = set(cl.allowed)
        for node in nodes:
            if isinstance(node, etree._Element):
                value, el = (node.text or "").strip(), node
            else:
                value, el = str(node).strip(), node.getparent()
            if value and value not in allowed:
                g.add(
                    f"code_list:{cl.id}",
                    f"Value not in code list {cl.id} {cl.label}",
                    _xml_ev(
                        inv,
                        ubl.path_of(el) + ("" if isinstance(node, etree._Element) else "/@attr"),
                        f"'{value}' is not an allowed {cl.label}",
                        line=el.sourceline,
                        value=value,
                    ),
                )


def _amt(el: Any, xpath: str) -> tuple[Decimal | None, Any]:
    node = ubl.first(el, xpath)
    return ubl.amount(node), node


def _q(value: Decimal, decimals: int, rounding: str) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=rounding)


def _cmp(
    inv: LoadedInvoice,
    g: _Groups,
    formula: str,
    stated: Decimal | None,
    node: Any,
    computed: Decimal,
    tol: Decimal,
    inputs: dict[str, Any],
) -> None:
    if stated is None or node is None:
        return
    if abs(stated - computed) > tol:
        g.add(
            f"arithmetic:{formula}",
            f"Amounts do not add up ({formula})",
            _xml_ev(
                inv,
                ubl.path_of(node),
                f"{FORMULAS[formula]}: stated {stated}, computed {computed}",
                line=node.sourceline,
                value=str(stated),
                detail={"formula": formula, "computed": computed, "tolerance": tol, **inputs},
            ),
        )


def _charges(el: Any) -> tuple[Decimal, Decimal]:
    charges, allowances = Decimal(0), Decimal(0)
    for ac in el.xpath("cac:AllowanceCharge", namespaces=NS):
        flag = (ubl.ftext(ac, "cbc:ChargeIndicator") or "").lower()
        value = ubl.amount(ubl.first(ac, "cbc:Amount")) or Decimal(0)
        if flag == "true":
            charges += value
        elif flag == "false":
            allowances += value
    return charges, allowances


def _arithmetic(inv: LoadedInvoice, decimals: int, rounding: str, tol: Decimal, g: _Groups) -> None:
    root = inv.root
    lines = root.xpath("cac:InvoiceLine|cac:CreditNoteLine", namespaces=NS)
    line_sum = Decimal(0)
    lines_ok = True
    for line in lines:
        stated, node = _amt(line, "cbc:LineExtensionAmount")
        if stated is None:
            lines_ok = False
        else:
            line_sum += stated
        qty = ubl.amount(ubl.first(line, "cbc:InvoicedQuantity|cbc:CreditedQuantity"))
        price = ubl.amount(ubl.first(line, "cac:Price/cbc:PriceAmount"))
        base = ubl.amount(ubl.first(line, "cac:Price/cbc:BaseQuantity")) or Decimal(1)
        if qty is None or price is None or base == 0:
            continue
        charges, allowances = _charges(line)
        computed = _q(qty * price / base, decimals, rounding) + charges - allowances
        _cmp(
            inv,
            g,
            "line_net",
            stated,
            node,
            computed,
            tol,
            {
                "quantity": str(qty),
                "price": str(price),
                "base_quantity": str(base),
                "charges": str(charges),
                "allowances": str(allowances),
            },
        )
    lmt = ubl.first(root, "cac:LegalMonetaryTotal")
    if lmt is None:
        return
    lext, lext_node = _amt(lmt, "cbc:LineExtensionAmount")
    if lines and lines_ok:
        _cmp(inv, g, "sum_lines", lext, lext_node, line_sum, tol, {"lines": len(lines)})
    charges, allowances = _charges(root)
    a_total, a_node = _amt(lmt, "cbc:AllowanceTotalAmount")
    c_total, c_node = _amt(lmt, "cbc:ChargeTotalAmount")
    _cmp(inv, g, "allowance_total", a_total, a_node, allowances, tol, {})
    _cmp(inv, g, "charge_total", c_total, c_node, charges, tol, {})
    excl, excl_node = _amt(lmt, "cbc:TaxExclusiveAmount")
    if lext is not None:
        computed = lext - (a_total or Decimal(0)) + (c_total or Decimal(0))
        _cmp(inv, g, "tax_exclusive", excl, excl_node, computed, tol, {"line_total": str(lext)})
    currency = ubl.ftext(root, "cbc:DocumentCurrencyCode")
    doc_tax: Decimal | None = None
    for tt in root.xpath("cac:TaxTotal", namespaces=NS):
        total, total_node = _amt(tt, "cbc:TaxAmount")
        subs = tt.xpath("cac:TaxSubtotal", namespaces=NS)
        if total_node is not None and (
            currency is None or total_node.get("currencyID") == currency
        ):
            doc_tax = total if doc_tax is None else doc_tax
        if not subs:
            continue
        sub_sum = Decimal(0)
        for sub in subs:
            taxable = ubl.amount(ubl.first(sub, "cbc:TaxableAmount"))
            sub_tax, sub_node = _amt(sub, "cbc:TaxAmount")
            percent = ubl.amount(ubl.first(sub, "cac:TaxCategory/cbc:Percent"))
            sub_sum += sub_tax or Decimal(0)
            if taxable is not None and percent is not None:
                computed = _q(taxable * percent / Decimal(100), decimals, rounding)
                _cmp(
                    inv,
                    g,
                    "tax_subtotal",
                    sub_tax,
                    sub_node,
                    computed,
                    tol,
                    {"taxable": str(taxable), "percent": str(percent)},
                )
        _cmp(inv, g, "tax_total", total, total_node, sub_sum, tol, {"subtotals": len(subs)})
    incl, incl_node = _amt(lmt, "cbc:TaxInclusiveAmount")
    if excl is not None and doc_tax is not None:
        _cmp(
            inv,
            g,
            "tax_inclusive",
            incl,
            incl_node,
            excl + doc_tax,
            tol,
            {"tax_exclusive": str(excl), "tax_total": str(doc_tax)},
        )
    payable, pay_node = _amt(lmt, "cbc:PayableAmount")
    if incl is not None:
        prepaid = ubl.amount(ubl.first(lmt, "cbc:PrepaidAmount")) or Decimal(0)
        rnd = ubl.amount(ubl.first(lmt, "cbc:PayableRoundingAmount")) or Decimal(0)
        _cmp(
            inv,
            g,
            "payable",
            payable,
            pay_node,
            incl - prepaid + rnd,
            tol,
            {"tax_inclusive": str(incl), "prepaid": str(prepaid), "rounding": str(rnd)},
        )


_PARTIES = {
    "seller": "cac:AccountingSupplierParty/cac:Party",
    "buyer": "cac:AccountingCustomerParty/cac:Party",
}


def _tax_ids(
    inv: LoadedInvoice,
    formats: dict[str, Any],
    default_country: str,
    g: _Groups,
    meta: dict[str, Any],
) -> None:
    for role, party_xp in _PARTIES.items():
        party = ubl.first(inv.root, party_xp)
        if party is None:
            continue
        node = ubl.first(party, "cac:PartyTaxScheme/cbc:CompanyID")
        if node is None or not (node.text or "").strip():
            continue
        country = (
            ubl.ftext(party, "cac:PostalAddress/cac:Country/cbc:IdentificationCode")
            or default_country
        ).upper()
        fmt = formats.get(country)
        if fmt is None:
            skipped = meta.setdefault("tax_id_countries_without_format", [])
            if country not in skipped:
                skipped.append(country)
            continue
        value = node.text.strip()
        if not tax_id_ok(value, fmt):
            g.add(
                f"tax_id:{role}",
                f"{role.capitalize()} tax registration number has the wrong format",
                _xml_ev(
                    inv,
                    ubl.path_of(node),
                    f"{role} {country} number is not {describe_tax_id(fmt)}",
                    line=node.sourceline,
                    value=normalise_tax_id(value),
                ),
            )


# ---------------------------------------------------------------- ZATCA QR, hash, chain


def parse_tlv(data: bytes) -> dict[int, bytes]:
    """Tag-length-value with one-byte tags and lengths (raises ValueError)."""
    out: dict[int, bytes] = {}
    i = 0
    while i < len(data):
        if i + 2 > len(data):
            raise ValueError("truncated TLV")
        tag, length = data[i], data[i + 1]
        value = data[i + 2 : i + 2 + length]
        if len(value) != length:
            raise ValueError("truncated TLV value")
        if tag in out:
            raise ValueError("repeated TLV tag")
        out[tag] = value
        i += 2 + length
    return out


def canonical_bytes(root: Any) -> bytes:
    doc = copy.deepcopy(root)
    for xp in (
        "ext:UBLExtensions",
        "cac:Signature",
        "cac:AdditionalDocumentReference[cbc:ID='QR']",
    ):
        for el in doc.xpath(xp, namespaces=NS):
            el.getparent().remove(el)
    return bytes(etree.tostring(doc, method="c14n", exclusive=False, with_comments=False))


def invoice_hash(root: Any, encoding: str) -> str:
    digest = hashlib.sha256(canonical_bytes(root))
    if encoding == "base64_hex":
        return base64.b64encode(digest.hexdigest().encode()).decode()
    return base64.b64encode(digest.digest()).decode()


def _qr(inv: LoadedInvoice, required: list[str], computed_hash: str | None, g: _Groups) -> None:
    root = inv.root
    ref = ubl.additional_ref(root, "QR")
    node = ubl.embedded(ref)
    xp = ubl.path_of(node) if node is not None else f"{ubl.r(root)}/cac:AdditionalDocumentReference"
    if node is None or not (node.text or "").strip():
        g.add("qr:missing", "QR code missing", _xml_ev(inv, xp, "No QR code reference"))
        return
    raw = ubl.b64(node.text)
    try:
        tlv = parse_tlv(raw) if raw is not None else None
    except ValueError:
        tlv = None
    if tlv is None:
        g.add(
            "qr:malformed",
            "QR code cannot be decoded",
            _xml_ev(inv, xp, "QR is not base64 TLV", line=node.sourceline),
        )
        return
    for t in required:
        if t.isdigit() and int(t) not in tlv:
            g.add(
                f"qr:tag{t}_missing",
                f"QR tag {t} missing",
                _xml_ev(inv, xp, f"QR has no tag {t}", line=node.sourceline),
            )

    def txt(tag: int) -> str | None:
        v = tlv.get(tag)
        try:
            return v.decode("utf-8") if v is not None else None
        except UnicodeDecodeError:
            return None

    seller = ubl.first(root, _PARTIES["seller"])
    lmt = ubl.first(root, "cac:LegalMonetaryTotal")
    expected: dict[int, tuple[str | None, str]] = {
        1: (
            ubl.ftext(seller, "cac:PartyLegalEntity/cbc:RegistrationName")
            if seller is not None
            else None,
            "seller name",
        ),
        2: (
            ubl.ftext(seller, "cac:PartyTaxScheme/cbc:CompanyID") if seller is not None else None,
            "seller VAT number",
        ),
    }
    for tag, (want, label) in expected.items():
        got = txt(tag)
        if got is not None and want is not None and got.strip() != want.strip():
            g.add(
                f"qr:tag{tag}_mismatch",
                f"QR {label} differs from the invoice",
                _xml_ev(
                    inv,
                    xp,
                    f"QR tag {tag} ({label}) differs",
                    line=node.sourceline,
                    value=got,
                    detail={"invoice": want},
                ),
            )
    stamp = txt(3)
    issue = (
        (ubl.ftext(root, "cbc:IssueDate") or "") + "T" + (ubl.ftext(root, "cbc:IssueTime") or "")
    )
    if stamp is not None and not stamp.rstrip("Z").startswith(issue.rstrip("Z")[:19]):
        g.add(
            "qr:tag3_mismatch",
            "QR timestamp differs from the invoice issue date and time",
            _xml_ev(
                inv,
                xp,
                "QR tag 3 (timestamp) differs",
                line=node.sourceline,
                value=stamp,
                detail={"invoice": issue},
            ),
        )
    h = ubl.header(root)
    amounts = {
        4: (
            ubl.amount(ubl.first(lmt, "cbc:TaxInclusiveAmount")) if lmt is not None else None,
            "total with VAT",
        ),
        5: (h.tax_amount, "VAT total"),
    }
    for tag, (want_amt, label) in amounts.items():
        got = txt(tag)
        if got is None or want_amt is None:
            continue
        try:
            same = Decimal(got) == want_amt
        except ArithmeticError:
            same = False
        if not same:
            g.add(
                f"qr:tag{tag}_mismatch",
                f"QR {label} differs from the invoice",
                _xml_ev(
                    inv,
                    xp,
                    f"QR tag {tag} ({label}) differs",
                    line=node.sourceline,
                    value=got,
                    detail={"invoice": str(want_amt)},
                ),
            )
    tag6 = txt(6)
    if tag6 is not None and computed_hash is not None and tag6 != computed_hash:
        g.add(
            "qr:hash_mismatch",
            "QR invoice hash differs from the recomputed hash",
            _xml_ev(
                inv,
                xp,
                "QR tag 6 differs from the recomputed invoice hash",
                line=node.sourceline,
                value=tag6,
                detail={"computed": computed_hash},
            ),
        )


def _signed_digest(inv: LoadedInvoice, g: _Groups) -> None:
    """The XMLDSig digest of the invoice reference must match the recomputed digest."""
    for ref in inv.root.xpath(".//ds:Reference", namespaces=NS):
        if ref.get("Id") != "invoiceSignedData" and ref.get("URI") != "":
            continue
        node = ubl.first(ref, "ds:DigestValue")
        if node is None or not (node.text or "").strip():
            continue
        digest = base64.b64encode(hashlib.sha256(canonical_bytes(inv.root)).digest()).decode()
        if node.text.strip() != digest:
            g.add(
                "hash:digest_mismatch",
                "Signed invoice digest differs from the recomputed digest",
                _xml_ev(
                    inv,
                    ubl.path_of(node),
                    "ds:DigestValue differs",
                    line=node.sourceline,
                    value=node.text.strip(),
                    detail={"computed": digest},
                ),
            )
        return


def _pih(inv: LoadedInvoice) -> tuple[str | None, Any]:
    node = ubl.embedded(ubl.additional_ref(inv.root, "PIH"))
    return (node.text.strip() if node is not None and node.text else None), node


def _chain(
    docs: list[LoadedInvoice], hashes: dict[str, str], initial: str, complete: bool, g: _Groups
) -> None:
    with_icv: list[LoadedInvoice] = []
    for inv in docs:
        pih, _ = _pih(inv)
        if inv.icv is None or pih is None:
            g.add(
                "chain:missing_fields",
                "Invoice counter (ICV) or previous invoice hash (PIH) missing",
                _xml_ev(
                    inv, f"{ubl.r(inv.root)}/cac:AdditionalDocumentReference", "ICV or PIH missing"
                ),
            )
            continue
        with_icv.append(inv)
    with_icv.sort(key=lambda i: (i.icv or 0, i.sha256))
    seen: dict[int, LoadedInvoice] = {}
    for inv in with_icv:
        assert inv.icv is not None
        if inv.icv in seen:
            g.add(
                "chain:duplicate_icv",
                "Two invoices share an invoice counter (ICV)",
                _xml_ev(
                    inv,
                    f"{ubl.r(inv.root)}/cac:AdditionalDocumentReference",
                    f"ICV {inv.icv} also used by {seen[inv.icv].filename}",
                    value=str(inv.icv),
                ),
            )
            continue
        seen[inv.icv] = inv
    ordered = [seen[k] for k in sorted(seen)]
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        assert prev.icv is not None and nxt.icv is not None
        if nxt.icv != prev.icv + 1:
            if complete:
                g.add(
                    "chain:gap",
                    "Invoice counter (ICV) sequence has a gap",
                    _xml_ev(
                        nxt,
                        f"{ubl.r(nxt.root)}/cac:AdditionalDocumentReference",
                        f"ICV jumps from {prev.icv} to {nxt.icv}",
                        value=str(nxt.icv),
                    ),
                )
            continue
        pih, node = _pih(nxt)
        if pih != hashes.get(prev.file_id):
            g.add(
                "chain:pih_mismatch",
                "Previous invoice hash (PIH) does not match the previous invoice",
                _xml_ev(
                    nxt,
                    ubl.path_of(node),
                    f"PIH differs from the hash of {prev.filename}",
                    line=node.sourceline,
                    value=pih,
                    detail={"previous_file": prev.filename, "computed": hashes.get(prev.file_id)},
                ),
            )
    if ordered and ordered[0].icv == 1:
        pih, node = _pih(ordered[0])
        if pih != initial:
            g.add(
                "chain:first_pih",
                "First invoice does not carry the initial previous-invoice hash",
                _xml_ev(
                    ordered[0],
                    ubl.path_of(node),
                    "PIH of ICV 1 differs from the pack's initial value",
                    line=node.sourceline,
                    value=pih,
                ),
            )


def _duplicates(docs: list[LoadedInvoice], g: _Groups) -> None:
    for attr, label in (("invoice_number", "invoice number"), ("invoice_uuid", "UUID")):
        by: dict[str, list[LoadedInvoice]] = {}
        for inv in docs:
            v = getattr(inv, attr)
            if v:
                by.setdefault(v, []).append(inv)
        for v, items in sorted(by.items()):
            if len(items) > 1:
                for inv in items:
                    g.add(
                        f"duplicate:{attr}",
                        f"Same {label} on more than one invoice",
                        _xml_ev(
                            inv,
                            f"{ubl.r(inv.root)}/cbc:{'ID' if attr == 'invoice_number' else 'UUID'}",
                            f"{label} {v} appears {len(items)} times",
                            value=v,
                        ),
                    )


# ---------------------------------------------------------------- go-live deadline


@dataclass(frozen=True)
class GoLive:
    go_live: date
    source: str  # "override" | "wave"
    wave: str | None
    milestones: tuple[tuple[str, str, date], ...]


def go_live_for(entity: Any, waves: list[Any]) -> GoLive:
    """The entity's go-live date: a notified override, else its wave by size basis."""
    if entity.go_live_override is not None:
        return GoLive(entity.go_live_override, "override", None, ())
    if entity.size_basis_amount is None or not entity.size_basis_currency:
        raise DataCheckError(
            "Set the entity's size basis (revenue, currency, year) or a notified go-live date."
        )
    amount, ccy = Decimal(entity.size_basis_amount), entity.size_basis_currency
    for w in waves:
        if w.currency != ccy:
            continue
        if w.min_revenue is not None and amount < w.min_revenue:
            continue
        if w.max_revenue is not None and amount >= w.max_revenue:
            continue
        return GoLive(
            date.fromisoformat(w.go_live),
            "wave",
            w.label,
            tuple((m.id, m.label, date.fromisoformat(m.date)) for m in w.milestones),
        )
    raise DataCheckError(f"No go-live wave in the rule pack covers a size basis of {amount} {ccy}.")


class EInvoiceDeadlineCheck(_M):
    """Go-live date for the entity from the pack's waves; flags passed or near milestones."""

    type: Literal["einvoice_deadline"]
    waves_rule: RuleKey
    warn_days: int = Field(default=90, ge=0, le=3650)

    def datasets_needed(self) -> set[DatasetKind]:
        return set()

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        if ctx.entity is None:
            raise InputMissing("Not run: this review has no entity.")
        waves = _typed_rule(ctx, self.waves_rule, meta)
        gl = go_live_for(ctx.entity, waves)
        days = (gl.go_live - ctx.as_of).days
        meta.update(
            {
                "go_live": gl.go_live.isoformat(),
                "go_live_source": gl.source,
                "wave": gl.wave,
                "as_of": ctx.as_of.isoformat(),
                "days_remaining": days,
                "entity": ctx.entity.snapshot(),
                "formula": "days_remaining = go_live − as_of",
            }
        )
        g = _Groups()
        label = f"go-live {gl.go_live.isoformat()} ({gl.wave or 'notified date'})"
        ev = {"type": "computation", "label": label, "detail": dict(meta)}
        if days < 0:
            g.add("deadline:go_live_passed", "E-invoicing go-live date has passed", ev)
        elif days <= self.warn_days:
            g.add("deadline:go_live_soon", f"E-invoicing go-live within {self.warn_days} days", ev)
        for mid, mlabel, mdate in gl.milestones:
            mdays = (mdate - ctx.as_of).days
            if mdays <= self.warn_days:
                g.add(
                    f"deadline:{mid}",
                    f"Milestone {'passed' if mdays < 0 else 'due soon'}: {mlabel}",
                    {
                        "type": "computation",
                        "label": f"{mlabel} {mdate.isoformat()}",
                        "detail": {
                            "milestone": mid,
                            "date": mdate.isoformat(),
                            "days_remaining": mdays,
                        },
                    },
                )
        out = _evaluation(g, 1, meta, "entity")
        if not out.groups:
            basis = gl.wave or "notified date"
            out.message = f"Go-live {gl.go_live.isoformat()} is {days} day(s) away ({basis})."
        return out


# ---------------------------------------------------------------- platform rejections


class RejectionMatchCheck(_M):
    """Rejections in an imported platform/ASP results file, matched to stored invoices."""

    type: Literal["einvoice_rejections"]
    rejected_statuses: list[str] = Field(
        default_factory=lambda: ["NOT_CLEARED", "NOT_REPORTED", "REJECTED", "ERROR", "FAILED"],
        min_length=1,
        max_length=20,
    )
    accepted_statuses: list[str] = Field(
        default_factory=lambda: ["CLEARED", "REPORTED", "ACCEPTED"], max_length=20
    )

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.EINVOICE_REJECTIONS}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, DatasetKind.EINVOICE_REJECTIONS)
        df = ds.frame
        for c in (
            "invoice_number",
            "invoice_uuid",
            "message_type",
            "error_code",
            "message",
            "received_at",
        ):
            if c not in df.columns:
                df = df.with_columns(pl.lit(None, dtype=pl.String).alias(c))
        status = pl.col("status").str.to_uppercase()
        key = pl.coalesce(pl.col("invoice_uuid"), pl.col("invoice_number"))
        df = df.with_columns(key.alias("_key"), status.alias("_status"))
        rejected_set = [s.upper() for s in self.rejected_statuses]
        accepted_set = [s.upper() for s in self.accepted_statuses]
        bad = df.filter(pl.col("_status").is_in(rejected_set) | (pl.col("message_type") == "error"))
        good = df.filter(pl.col("_status").is_in(accepted_set))
        invoices: dict[str, LoadedInvoice] = {}
        if ctx.einvoices is not None:
            for inv in ctx.einvoices.invoices:
                for k in (inv.invoice_uuid, inv.invoice_number):
                    if k:
                        invoices.setdefault(k, inv)
        g = _Groups()
        resolved = 0
        for k in sorted({k for k in bad["_key"].to_list() if k is not None}):
            rows = bad.filter(pl.col("_key") == k)
            later_ok = good.filter(pl.col("_key") == k)
            if later_ok.height:
                last_bad = (
                    rows["received_at"].drop_nulls().max()
                    if "received_at" in rows.columns
                    else None
                )
                last_ok = later_ok["received_at"].drop_nulls().max()
                if last_bad is None or last_ok is None or last_ok >= last_bad:  # type: ignore[operator]
                    resolved += 1
                    continue
            codes = sorted({c for c in rows["error_code"].to_list() if c})
            title = f"Invoice {k} rejected by the platform"
            gkey = f"rejection:{k}"
            g.add(
                gkey,
                title,
                _rows_evidence(
                    ds,
                    rows,
                    ["status", "message_type", "error_code", "message"],
                    f"{rows.height} rejection message(s): {', '.join(codes) or 'no code'}",
                ),
            )
            inv = invoices.get(k)
            if inv is not None:
                g.items[gkey].evidence.append(
                    _xml_ev(
                        inv,
                        f"{ubl.r(inv.root) if inv.root is not None else ''}/cbc:ID",
                        "Stored invoice",
                        value=inv.invoice_number,
                    )
                )
        no_key = bad.filter(pl.col("_key").is_null())
        if no_key.height:
            g.add(
                "rejection:unidentified",
                "Rejection without invoice number or UUID",
                _rows_evidence(ds, no_key, ["status", "error_code", "message"], "No invoice key"),
            )
        meta["rejections"] = bad.height
        meta["resolved_by_later_acceptance"] = resolved
        meta["matched_to_stored"] = sum(
            1 for k in g.items if k.removeprefix("rejection:") in invoices
        )
        return _evaluation(g, df.height, meta, "platform result row(s)")


EINVOICE_CHECK_TYPES = (EInvoiceValidateCheck, EInvoiceDeadlineCheck, RejectionMatchCheck)
