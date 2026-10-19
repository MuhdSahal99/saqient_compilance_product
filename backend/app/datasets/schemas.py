"""Canonical column schemas per dataset kind.

An imported file is mapped onto one of these schemas. Amounts become
``Decimal(20, 4)`` with a currency code on every row; dates become ``Date``.
Every canonical dataset also carries ``row_id``: the 1-based data row in the
source file (header excluded), or the entry number for bank formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.models import DatasetKind

FieldType = Literal["text", "amount", "date", "currency"]


@dataclass(frozen=True)
class CanonicalField:
    name: str
    type: FieldType
    required: bool = False
    label: str = ""
    # Header spellings recognised when suggesting a mapping (compared case-insensitively).
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalSchema:
    kind: DatasetKind
    fields: tuple[CanonicalField, ...]
    # At least one group must be fully mapped (e.g. debit+credit, or a signed amount).
    require_any: tuple[tuple[str, ...], ...] = field(default_factory=tuple)

    def get(self, name: str) -> CanonicalField | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.fields]


def _f(name: str, type_: FieldType, required: bool = False, *aliases: str) -> CanonicalField:
    return CanonicalField(name, type_, required, name.replace("_", " ").capitalize(), aliases)


_CURRENCY = _f("currency", "currency", False, "ccy", "curr", "currency code")

SCHEMAS: dict[DatasetKind, CanonicalSchema] = {
    DatasetKind.TRIAL_BALANCE: CanonicalSchema(
        DatasetKind.TRIAL_BALANCE,
        (
            _f("account_code", "text", True, "account", "account no", "account number", "gl code"),
            _f("account_name", "text", False, "account description", "description", "name"),
            _f("debit", "amount", False, "dr", "debit amount"),
            _f("credit", "amount", False, "cr", "credit amount"),
            _f("balance", "amount", False, "closing balance", "net", "net balance"),
            _CURRENCY,
        ),
        require_any=(("debit", "credit"), ("balance",)),
    ),
    DatasetKind.GENERAL_LEDGER: CanonicalSchema(
        DatasetKind.GENERAL_LEDGER,
        (
            _f("entry_id", "text", True, "journal", "journal id", "je number", "voucher", "entry"),
            _f("posting_date", "date", True, "date", "gl date", "posted"),
            _f("account_code", "text", True, "account", "account no", "account number", "gl code"),
            _f("description", "text", False, "narration", "memo", "details"),
            _f("debit", "amount", False, "dr", "debit amount"),
            _f("credit", "amount", False, "cr", "credit amount"),
            _f("amount", "amount", False, "signed amount", "value"),
            _CURRENCY,
            _f("counterparty", "text", False, "vendor", "customer", "party"),
            _f("document_date", "date", False, "doc date", "invoice date"),
            _f("reference", "text", False, "ref", "document number", "doc no"),
            _f("posted_by", "text", False, "user", "created by", "entered by"),
        ),
        require_any=(("debit", "credit"), ("amount",)),
    ),
    DatasetKind.SALES_REGISTER: CanonicalSchema(
        DatasetKind.SALES_REGISTER,
        (
            _f(
                "invoice_number", "text", True, "invoice", "invoice no", "inv no", "document number"
            ),
            _f("invoice_date", "date", True, "date", "inv date"),
            _f("customer_name", "text", False, "customer", "buyer"),
            _f("customer_trn", "text", False, "customer vat", "buyer trn", "trn", "vat number"),
            _f("net_amount", "amount", True, "net", "taxable amount", "amount excl vat"),
            _f("tax_amount", "amount", True, "vat", "vat amount", "tax"),
            _f("gross_amount", "amount", False, "gross", "total", "amount incl vat"),
            _CURRENCY,
            _f("tax_code", "text", False, "vat code", "tax category"),
            _f("place_of_supply", "text", False, "emirate", "region", "place of supply"),
            _f("customer_country", "text", False, "buyer country", "country"),
            _f(
                "export_evidence_ref",
                "text",
                False,
                "export evidence",
                "export document",
                "bill of lading",
                "exit document",
            ),
            _f("supply_date", "date", False, "date of supply", "delivery date"),
        ),
    ),
    DatasetKind.PURCHASE_REGISTER: CanonicalSchema(
        DatasetKind.PURCHASE_REGISTER,
        (
            _f(
                "invoice_number",
                "text",
                True,
                "invoice",
                "invoice no",
                "bill no",
                "document number",
            ),
            _f("invoice_date", "date", True, "date", "bill date"),
            _f("supplier_name", "text", False, "supplier", "vendor", "seller"),
            _f("supplier_trn", "text", False, "supplier vat", "vendor trn", "trn", "vat number"),
            _f("net_amount", "amount", True, "net", "taxable amount", "amount excl vat"),
            _f("tax_amount", "amount", True, "vat", "vat amount", "tax"),
            _f("gross_amount", "amount", False, "gross", "total", "amount incl vat"),
            _CURRENCY,
            _f("tax_code", "text", False, "vat code", "tax category"),
            _f("expense_category", "text", False, "category", "expense type", "gl category"),
            _f("supplier_country", "text", False, "vendor country", "country"),
            _f("supply_date", "date", False, "date of supply", "receipt date"),
        ),
    ),
    DatasetKind.BANK_STATEMENT: CanonicalSchema(
        DatasetKind.BANK_STATEMENT,
        (
            _f("transaction_date", "date", True, "date", "booking date", "posting date"),
            _f("value_date", "date", False, "value dt"),
            _f("description", "text", False, "narrative", "details", "memo"),
            _f("amount", "amount", False, "signed amount", "transaction amount"),
            _f("debit", "amount", False, "withdrawal", "dr", "money out"),
            _f("credit", "amount", False, "deposit", "cr", "money in"),
            _f("balance", "amount", False, "running balance"),
            _f("reference", "text", False, "ref", "transaction id", "bank reference"),
            _CURRENCY,
            _f("counterparty", "text", False, "payee", "payer", "beneficiary"),
        ),
        require_any=(("amount",), ("debit", "credit")),
    ),
    DatasetKind.CUSTOMER_MASTER: CanonicalSchema(
        DatasetKind.CUSTOMER_MASTER,
        (
            _f("party_id", "text", True, "customer id", "customer code", "account", "id"),
            _f("name", "text", True, "customer name", "legal name"),
            _f("trn", "text", False, "vat number", "tax number", "vat registration number"),
            _f("country", "text", False, "country code"),
            _f("address_line1", "text", False, "address", "street", "address 1"),
            _f("address_line2", "text", False, "address 2"),
            _f("city", "text", False, "town"),
            _f("region", "text", False, "emirate", "state", "province"),
            _f("postal_code", "text", False, "postcode", "zip", "po box"),
            _f("building_number", "text", False, "building no", "building"),
            _f("email", "text", False, "e-mail"),
        ),
    ),
    DatasetKind.SUPPLIER_MASTER: CanonicalSchema(
        DatasetKind.SUPPLIER_MASTER,
        (
            _f("party_id", "text", True, "supplier id", "vendor id", "vendor code", "id"),
            _f("name", "text", True, "supplier name", "vendor name", "legal name"),
            _f("trn", "text", False, "vat number", "tax number", "vat registration number"),
            _f("country", "text", False, "country code"),
            _f("address_line1", "text", False, "address", "street", "address 1"),
            _f("address_line2", "text", False, "address 2"),
            _f("city", "text", False, "town"),
            _f("region", "text", False, "emirate", "state", "province"),
            _f("postal_code", "text", False, "postcode", "zip", "po box"),
            _f("building_number", "text", False, "building no", "building"),
            _f("email", "text", False, "e-mail"),
            _f("iban", "text", False, "bank account", "account iban"),
        ),
    ),
    DatasetKind.VAT_RETURN: CanonicalSchema(
        DatasetKind.VAT_RETURN,
        (
            _f("box_code", "text", True, "box", "box number", "line", "field"),
            _f("description", "text", False, "label", "box description"),
            _f("amount", "amount", False, "net", "value", "taxable amount", "amount aed"),
            _f("tax_amount", "amount", False, "vat", "vat amount", "tax"),
            _CURRENCY,
        ),
        require_any=(("amount",), ("tax_amount",)),
    ),
    DatasetKind.EINVOICE_REJECTIONS: CanonicalSchema(
        DatasetKind.EINVOICE_REJECTIONS,
        (
            _f("invoice_number", "text", False, "invoice", "invoice no", "document number"),
            _f("invoice_uuid", "text", False, "uuid", "invoice id"),
            _f("invoice_hash", "text", False, "hash"),
            _f("status", "text", True, "result", "clearance status", "reporting status"),
            _f("message_type", "text", False, "type", "severity", "level"),
            _f("error_code", "text", False, "code", "rule"),
            _f("message", "text", False, "error", "description", "error message"),
            _f("received_at", "date", False, "date", "submitted", "timestamp"),
        ),
        require_any=(("invoice_number",), ("invoice_uuid",)),
    ),
    DatasetKind.WHT_PAYMENTS: CanonicalSchema(
        DatasetKind.WHT_PAYMENTS,
        (
            _f("payment_id", "text", True, "payment", "payment no", "voucher", "reference"),
            _f("payment_date", "date", True, "date", "paid on", "value date"),
            _f("payee_name", "text", True, "payee", "vendor", "beneficiary", "supplier"),
            _f("payee_country", "text", False, "country", "residence", "payee residence"),
            _f("payment_type", "text", True, "type", "nature", "category", "income type"),
            _f("gross_amount", "amount", True, "gross", "amount", "payment amount"),
            _f("wht_amount", "amount", False, "wht", "withholding", "tax withheld"),
            _f("treaty_rate", "amount", False, "treaty", "reduced rate"),
            _f("treaty_certificate", "text", False, "certificate", "residency certificate"),
            _CURRENCY,
        ),
    ),
    DatasetKind.USER_ROLES: CanonicalSchema(
        DatasetKind.USER_ROLES,
        (
            _f("user_id", "text", True, "user", "username", "user name id", "login", "user code"),
            _f("user_name", "text", False, "name", "full name", "employee name"),
            _f("role", "text", False, "role name", "responsibility", "security role", "profile"),
            _f("permission", "text", False, "privilege", "function", "transaction", "tcode"),
            _f("system", "text", False, "application", "module", "company"),
            _f("status", "text", False, "user status", "active", "lock status"),
        ),
        require_any=(("role",), ("permission",)),
    ),
    DatasetKind.AP_PAYMENTS: CanonicalSchema(
        DatasetKind.AP_PAYMENTS,
        (
            _f("payment_id", "text", True, "payment", "payment no", "voucher", "reference"),
            _f("payment_date", "date", True, "date", "paid on", "value date"),
            _f("vendor_id", "text", False, "vendor code", "supplier id", "vendor no"),
            _f("vendor_name", "text", True, "vendor", "supplier", "payee", "beneficiary"),
            _f("vendor_trn", "text", False, "trn", "vat number", "tax number"),
            _f("vendor_country", "text", False, "country", "country code"),
            _f("invoice_number", "text", False, "invoice", "invoice no", "bill number"),
            _f("amount", "amount", True, "payment amount", "paid amount", "net amount"),
            _f("iban", "text", False, "bank account", "beneficiary iban", "account iban"),
            _f("description", "text", False, "memo", "narration", "details"),
            _CURRENCY,
        ),
    ),
    DatasetKind.EMPLOYEE_MASTER: CanonicalSchema(
        DatasetKind.EMPLOYEE_MASTER,
        (
            _f("employee_id", "text", True, "employee", "employee no", "staff id", "id"),
            _f("employee_name", "text", True, "name", "full name", "employee full name"),
            _f("iban", "text", False, "bank account", "salary iban", "account iban"),
            _f("department", "text", False, "cost centre", "cost center", "division"),
            _f("status", "text", False, "employment status", "active"),
        ),
    ),
    DatasetKind.THREE_WAY_MATCH: CanonicalSchema(
        DatasetKind.THREE_WAY_MATCH,
        (
            _f("po_number", "text", True, "po", "purchase order", "po no"),
            _f("invoice_number", "text", False, "invoice", "invoice no", "bill number"),
            _f("vendor_name", "text", False, "vendor", "supplier"),
            _f("item", "text", False, "line", "item code", "material", "product"),
            _f("po_quantity", "amount", False, "ordered quantity", "po qty", "ordered qty"),
            _f("received_quantity", "amount", False, "grn quantity", "received qty", "grn qty"),
            _f("invoiced_quantity", "amount", True, "invoice quantity", "invoiced qty"),
            _f("po_unit_price", "amount", False, "po price", "order price"),
            _f("invoice_unit_price", "amount", False, "invoice price", "billed price"),
            _CURRENCY,
        ),
    ),
    DatasetKind.EXPENSE_CLAIMS: CanonicalSchema(
        DatasetKind.EXPENSE_CLAIMS,
        (
            _f("claim_id", "text", True, "claim", "claim no", "expense id", "report id"),
            _f("employee_id", "text", True, "employee", "employee no", "staff id"),
            _f("employee_name", "text", False, "name", "claimant"),
            _f("claim_date", "date", True, "date", "expense date", "transaction date"),
            _f("category", "text", True, "expense type", "type", "expense category"),
            _f("amount", "amount", True, "claimed amount", "expense amount"),
            _f("receipt_ref", "text", False, "receipt", "receipt no", "attachment"),
            _f("description", "text", False, "purpose", "details", "memo"),
            _CURRENCY,
        ),
    ),
}


def _norm(header: str) -> str:
    return " ".join(header.replace("_", " ").replace("-", " ").casefold().split())


def suggest_mapping(kind: DatasetKind, source_columns: list[str]) -> dict[str, str]:
    """Match source headers to canonical fields by name or alias. Each header is used once."""
    by_norm = {_norm(c): c for c in source_columns}
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for f in SCHEMAS[kind].fields:
        for candidate in (f.name, *f.aliases):
            src = by_norm.get(_norm(candidate))
            if src is not None and src not in used:
                mapping[f.name] = src
                used.add(src)
                break
    return mapping


class MappingError(ValueError):
    pass


def validate_mapping(kind: DatasetKind, mapping: dict[str, str], source_columns: list[str]) -> None:
    schema = SCHEMAS[kind]
    unknown = sorted(set(mapping) - set(schema.names))
    if unknown:
        raise MappingError(f"Unknown field(s) for this dataset kind: {', '.join(unknown)}.")
    missing_src = sorted({c for c in mapping.values() if c not in source_columns})
    if missing_src:
        raise MappingError(f"Column(s) not in the file: {', '.join(missing_src)}.")
    if len(set(mapping.values())) != len(mapping):
        raise MappingError("Each source column can be mapped to one field only.")
    missing = [f.name for f in schema.fields if f.required and f.name not in mapping]
    if missing:
        raise MappingError(f"Required field(s) not mapped: {', '.join(missing)}.")
    if schema.require_any and not any(all(n in mapping for n in g) for g in schema.require_any):
        options = " or ".join("+".join(g) for g in schema.require_any)
        raise MappingError(f"Map {options}.")
