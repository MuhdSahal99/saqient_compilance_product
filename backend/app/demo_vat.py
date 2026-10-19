"""Synthetic Phase B demo: an entity with VAT setup, e-invoices, registers, a VAT return,
a tax calendar, a sampling monitor and two reviews (e-invoice + readiness, VAT return).

Every value is invented. The rule pack uses the SYNTHETIC jurisdiction, so its rules
and schema stay unverified and cannot be verified; reviews and reports flag them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import demo_content as dc
from app import demo_einvoice as demo
from app.engine.versions import ENGINE_VERSION, parse_check
from app.models import (
    Checklist,
    ChecklistKind,
    ChecklistState,
    ChecklistVersion,
    DatasetKind,
    DatasetStatus,
    DatasetVersion,
    EInvoiceFile,
    LegalEntity,
    MonitorCadence,
    Organization,
    PeriodFrequency,
    Requirement,
    Review,
    RulePackVersion,
    Severity,
    User,
)
from app.schemas import LegalEntityIn, LegalEntityPatch, RuleIn, TaxPeriodIn, VatSetupIn
from app.services import (
    datasets,
    einvoices,
    entities,
    monitors,
    reviews,
    rule_packs,
    tax_calendar,
    tax_setup,
)
from app.services.jobs import execute_job

ENTITY_NAME = "Synthetic Gulf Trading LLC (demo)"
PACK_NAME = "Synthetic e-invoicing and VAT rules (demo)"
EINVOICE_CHECKLIST = "Synthetic e-invoicing checks (demo)"
VAT_CHECKLIST = "Synthetic VAT return checks (demo)"
EINVOICE_REVIEW = "E-invoice validation and readiness (synthetic demo)"
VAT_REVIEW = "Q1 2026 VAT return review (synthetic demo)"
Q1 = (date(2026, 1, 1), date(2026, 3, 31))

SALES_CSV = (
    b"invoice_number,invoice_date,customer_name,customer_trn,net_amount,tax_amount,currency,"
    b"tax_code,customer_country,export_evidence_ref,supply_date\n"
    b"S-1,2026-01-10,Synthetic Buyer A,900000000000002,1000.00,50.00,AED,SR,AE,,\n"
    b"S-2,2026-02-11,Synthetic Buyer B,900000000000003,2000.00,100.00,AED,SR,AE,,2025-12-28\n"
    b"S-3,2026-02-20,Synthetic Export Co,,500.00,0.00,AED,ZR,US,EXP-1,\n"
    b"S-4,2026-03-05,Synthetic Export Two,,300.00,0.00,AED,ZR,GB,,\n"
    b"S-5,2026-03-06,Synthetic Local,,400.00,20.00,AED,ZR,AE,,\n"
    b"S-6,2026-03-07,Synthetic Resident,,250.00,0.00,AED,EX,AE,,\n"
)
PURCHASE_CSV = (
    b"invoice_number,invoice_date,supplier_name,supplier_trn,net_amount,tax_amount,currency,"
    b"tax_code,expense_category,supplier_country\n"
    b"P-1,2026-01-15,Synthetic Supplier A,900000000000010,800.00,40.00,AED,SR,office,AE\n"
    b"P-2,2026-02-15,Synthetic Overseas,,1000.00,50.00,AED,RC,software,US\n"
    b"P-3,2026-03-15,Synthetic Overseas Two,,200.00,0.00,AED,RC,services,DE\n"
    b"P-4,2026-03-20,Synthetic Club,900000000000011,600.00,30.00,AED,SR,entertainment,AE\n"
)
RETURN_CSV = (
    b"box_code,description,amount,tax_amount\n"
    b"S1,Standard sales,3000.00,\nS1T,Standard sales VAT,,150.00\n"
    b"S2,Zero-rated sales,1200.00,\nS3,Exempt sales,250.00,\n"
    b"R1,Reverse charge,1200.00,\nR1T,Reverse charge VAT,,50.00\n"
    b"P1,Purchases,2600.00,\nP1T,Recoverable VAT,,120.00\n"
    b"T1,Total output VAT,,200.00\nT2,Net VAT,,80.00\n"
)
GL_CSV = (
    b"entry_id,posting_date,account_code,description,debit,credit\n"
    b"J1,2026-03-31,2200,Synthetic output VAT,,150.00\nJ1,2026-03-31,1100,Receivables,150.00,\n"
    b"J2,2026-03-31,2210,Synthetic reverse charge,,50.00\n"
    b"J2,2026-03-31,1410,Synthetic reverse charge,50.00,\n"
    b"J3,2026-03-31,1400,Synthetic input VAT,70.00,\nJ3,2026-03-31,2100,Payables,,70.00\n"
)
CUSTOMERS_CSV = (
    b"party_id,name,trn,country,address_line1,city,building_number\n"
    b"C1,Synthetic Buyer A,900000000000002,AE,1 Synthetic Street,Synthetic City,\n"
    b"C2,Synthetic Buyer B,12345,AE,,Synthetic City,\n"
    b"C3,Synthetic Saudi Co,800000000000008,SA,2 Synthetic Road,Synthetic City,\n"
)
VAT_SETUP = VatSetupIn.model_validate(
    {
        "tax_codes": [
            {"register": "sales_register", "tax_code": "SR", "treatment": "standard"},
            {"register": "sales_register", "tax_code": "ZR", "treatment": "zero_rated"},
            {"register": "sales_register", "tax_code": "EX", "treatment": "exempt"},
            {"register": "purchase_register", "tax_code": "SR", "treatment": "standard"},
            {"register": "purchase_register", "tax_code": "RC", "treatment": "reverse_charge"},
        ],
        "tax_accounts": [
            {"role": "output_vat", "account_code": "2200"},
            {"role": "reverse_charge_output", "account_code": "2210"},
            {"role": "input_vat", "account_code": "1400"},
            {"role": "reverse_charge_input", "account_code": "1410"},
        ],
    }
)


def _cfg(t: str, **kw: Any) -> dict[str, Any]:
    return {"type": t, **kw}


EINVOICE_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "code": "EINV-01",
        "title": "E-invoices validate against the pack's schema and rules",
        "severity": "high",
        "config": _cfg(
            "einvoice_validate",
            profile="pint_ae",
            rules_prefix="syn.einvoice",
            default_country="AE",
        ),
    },
    {
        "code": "READY-01",
        "title": "E-invoicing go-live and preparation milestones",
        "severity": "medium",
        "config": _cfg("einvoice_deadline", waves_rule="syn.einvoice.go_live_waves", warn_days=180),
    },
]
VAT_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "code": "MD-01",
        "title": "Customer tax numbers have the expected shape",
        "severity": "medium",
        "config": _cfg(
            "tax_id_format",
            dataset="customer_master",
            field="trn",
            country_field="country",
            default_country="AE",
            formats_rule="syn.vat.tax_id_formats",
        ),
    },
    {
        "code": "MD-02",
        "title": "Customer addresses are complete",
        "severity": "low",
        "config": _cfg(
            "completeness",
            dataset="customer_master",
            required_rule="syn.vat.required_fields",
            country_field="country",
            default_country="AE",
        ),
    },
    {
        "code": "VAT-01",
        "title": "Return boxes agree to the registers",
        "severity": "high",
        "config": _cfg(
            "vat_box_reconcile",
            layout_rule="syn.vat.box_layout",
            tolerance_rule="syn.vat.box_tolerance",
        ),
    },
    {
        "code": "VAT-02",
        "title": "Return VAT agrees to the GL VAT accounts",
        "severity": "high",
        "config": _cfg(
            "vat_gl_reconcile",
            layout_rule="syn.vat.box_layout",
            tolerance_rule="syn.vat.box_tolerance",
        ),
    },
    {
        "code": "VAT-03",
        "title": "Reverse-charge purchases",
        "severity": "medium",
        "config": _cfg("reverse_charge"),
    },
    {
        "code": "VAT-04",
        "title": "Zero-rated exports have export evidence",
        "severity": "high",
        "config": _cfg("zero_rated_evidence"),
    },
    {
        "code": "VAT-05",
        "title": "No input VAT on blocked categories",
        "severity": "medium",
        "config": _cfg("blocked_input", blocked_rule="syn.vat.blocked_categories"),
    },
    {
        "code": "VAT-06",
        "title": "Supplies fall within the tax period",
        "severity": "low",
        "config": _cfg(
            "date_rule", dataset="sales_register", field="supply_date", rule="within_period"
        ),
    },
]


def _checklist(
    db: Session, org: Organization, publisher: User, name: str, requirements: list[dict[str, Any]]
) -> ChecklistVersion:
    c = Checklist(
        org_id=org.id,
        name=name,
        description="Deterministic checks over synthetic e-invoicing and VAT data.",
        kind=ChecklistKind.SYNTHETIC_DEMO,
    )
    db.add(c)
    db.flush()
    v = ChecklistVersion(
        org_id=org.id,
        checklist_id=c.id,
        version_number=1,
        state=ChecklistState.PUBLISHED,
        disclaimer=dc.SYNTHETIC_NOTICE,
        published_at=datetime.now(UTC),
        published_by_id=publisher.id,
    )
    db.add(v)
    db.flush()
    for i, req in enumerate(requirements):
        parse_check(req["config"], ENGINE_VERSION)
        db.add(
            Requirement(
                org_id=org.id,
                checklist_version_id=v.id,
                ordinal=i,
                code=req["code"],
                title=req["title"],
                description=req["title"],
                category="E-invoicing and VAT",
                severity=Severity(req["severity"]),
                check_config=req["config"],
                source_reference=f"Synthetic demo checklist, item {req['code']}",
                owner="Demo checklist owner",
            )
        )
    return v


def _pack(db: Session, org: Organization, reviewer: User) -> RulePackVersion:
    pack = rule_packs.create_pack(
        db,
        org.id,
        PACK_NAME,
        "SYNTHETIC",
        "Invented values and a test schema for the demo. Not legal or tax guidance.",
        reviewer,
    )
    db.flush()
    v: RulePackVersion = pack.versions[0]
    rule_packs.replace_rules(db, v, [RuleIn.model_validate(r) for r in demo.rules()], reviewer)
    rule_packs.add_file(
        db,
        v,
        file_key="syn.einvoice.xsd",
        kind="xsd_bundle",
        title="Synthetic UBL-shaped schema (demo)",
        filename="synthetic-schema.zip",
        entry_point=demo.XSD_ENTRY,
        data=demo.xsd_bundle(),
        source_url=None,
        source_note=demo.SYNTHETIC_NOTE,
        actor=reviewer,
    )
    db.flush()
    db.refresh(v)
    rule_packs.publish(db, v, reviewer)
    return v


def _import(
    db: Session,
    factory: sessionmaker[Session],
    org: Organization,
    entity: LegalEntity,
    analyst: User,
    kind: DatasetKind,
    name: str,
    data: bytes,
) -> DatasetVersion:
    ds = datasets.create_dataset(
        db,
        org_id=org.id,
        entity=entity,
        kind=kind,
        name=name,
        period_start=Q1[0],
        period_end=Q1[1],
        actor=analyst,
    )
    ds.is_demo = True
    v, job = datasets.create_version(
        db,
        dataset=ds,
        filename=f"{kind.value}-synthetic.csv",
        declared_mime="text/csv",
        data=data,
        actor=analyst,
        allow_duplicate=True,
    )
    db.commit()
    execute_job(factory, job.id, org.id)
    db.refresh(v)
    header = data.split(b"\n", 1)[0].decode().split(",")
    build = datasets.confirm_mapping(
        db,
        v,
        {h: h for h in header},
        date_format="%Y-%m-%d",
        decimal_separator=".",
        actor=analyst,
    )
    db.commit()
    execute_job(factory, build.id, org.id)
    db.refresh(v)
    if v.status != DatasetStatus.READY:
        raise RuntimeError(f"Synthetic {kind.value} did not build: {v.failure_message}")
    return v


def _invoices() -> bytes:
    specs = [
        demo.InvoiceSpec(number="SYN-AE-0001", uuid="10000000-0000-4000-8000-000000000001"),
        demo.InvoiceSpec(number="SYN-AE-0002", uuid="10000000-0000-4000-8000-000000000002"),
        demo.InvoiceSpec(
            number="SYN-AE-0003",
            uuid="10000000-0000-4000-8000-000000000003",
            omit=("IssueDate",),
        ),
        demo.InvoiceSpec(
            number="SYN-AE-0004",
            uuid="10000000-0000-4000-8000-000000000004",
            lines=[demo.Line("2", "100.00", net="150.00")],
        ),
        demo.InvoiceSpec(
            number="SYN-AE-0005",
            uuid="10000000-0000-4000-8000-000000000005",
            seller_trn="12345",
        ),
    ]
    return demo.zip_of([(f"{s.number}.xml", demo.invoice_xml(s)) for s in specs])


def seed_vat(
    db: Session,
    factory: sessionmaker[Session],
    org: Organization,
    admin: User,
    reviewer: User,
    analyst: User,
) -> tuple[Review, Review]:
    entity = entities.create_entity(
        db,
        org.id,
        LegalEntityIn(
            name=ENTITY_NAME,
            country="AE",
            fiscal_year_end_month=12,
            fiscal_year_end_day=31,
            functional_currency="AED",
            timezone="Asia/Dubai",
        ),
        admin,
    )
    entities.update_entity(
        db,
        entity,
        LegalEntityPatch(
            size_basis_amount=Decimal("60000000"), size_basis_currency="AED", size_basis_year=2025
        ),
        admin,
    )
    tax_setup.replace_vat_setup(db, entity, VAT_SETUP, admin)
    rpv = _pack(db, org, reviewer)
    ev_cv = _checklist(db, org, reviewer, EINVOICE_CHECKLIST, EINVOICE_REQUIREMENTS)
    vat_cv = _checklist(db, org, reviewer, VAT_CHECKLIST, VAT_REQUIREMENTS)
    db.commit()

    batch = einvoices.create_batch(
        db,
        entity=entity,
        name="March 2026 e-invoices (synthetic)",
        filename="synthetic-invoices.zip",
        data=_invoices(),
        actor=analyst,
        is_demo=True,
    )
    db.commit()
    files = list(db.scalars(select(EInvoiceFile).where(EInvoiceFile.batch_id == batch.id)))
    ev_review, job = reviews.create_review(
        db,
        org_id=org.id,
        user_id=reviewer.id,
        title=EINVOICE_REVIEW,
        document_version=None,
        checklist_version=ev_cv,
        rule_pack_version=rpv,
        as_of_date=date(2026, 10, 1),
        entity=entity,
        einvoice_files=files,
    )
    ev_review.is_demo = True
    db.commit()
    execute_job(factory, job.id, org.id)

    period = tax_setup.create_period(
        db,
        entity,
        TaxPeriodIn(frequency=PeriodFrequency.QUARTERLY, period_start=Q1[0], period_end=Q1[1]),
        reviewer,
    )
    db.commit()
    versions = [
        _import(db, factory, org, entity, analyst, kind, name, data)
        for kind, name, data in (
            (DatasetKind.SALES_REGISTER, "Q1 2026 sales register (synthetic)", SALES_CSV),
            (DatasetKind.PURCHASE_REGISTER, "Q1 2026 purchase register (synthetic)", PURCHASE_CSV),
            (DatasetKind.VAT_RETURN, "Q1 2026 VAT return (synthetic)", RETURN_CSV),
            (DatasetKind.GENERAL_LEDGER, "Q1 2026 VAT ledger lines (synthetic)", GL_CSV),
            (DatasetKind.CUSTOMER_MASTER, "Customer master (synthetic)", CUSTOMERS_CSV),
        )
    ]
    vat_review, job = reviews.create_review(
        db,
        org_id=org.id,
        user_id=reviewer.id,
        title=VAT_REVIEW,
        document_version=None,
        checklist_version=vat_cv,
        dataset_versions=versions,
        rule_pack_version=rpv,
        entity=entity,
        tax_period=period,
    )
    db.commit()
    execute_job(factory, job.id, org.id)

    tax_calendar.generate(
        db,
        entity=entity,
        version=rpv,
        prefix="syn.vat",
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
        actor=reviewer,
        owner_id=analyst.id,
        waves_rule="syn.einvoice.go_live_waves",
    )
    monitors.create_monitor(
        db,
        org_id=org.id,
        actor_id=reviewer.id,
        entity=entity,
        name="Weekly e-invoice sample (synthetic demo)",
        checklist_version=ev_cv,
        rule_pack_version=rpv,
        sample_size=3,
        cadence=MonitorCadence.WEEKLY,
        first_run_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.commit()
    db.refresh(ev_review)
    db.refresh(vat_review)
    return ev_review, vat_review
