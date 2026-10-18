"""Phase B: entity VAT setup, tax periods, master data scan and VAT return review.

Golden values below are worked by hand from the synthetic registers in this file;
the comments show each sum. Rules come from the synthetic pack in app/demo_einvoice.py.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import LegalEntity, Role
from tests.conftest import ApiClient, Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import checklist, findings, req, results, synthetic_pack

SALES_CSV = b"""invoice_number,invoice_date,customer_name,customer_trn,net_amount,tax_amount,currency,tax_code,customer_country,export_evidence_ref,supply_date
S-1,2026-01-10,Synthetic Buyer A,900000000000002,1000.00,50.00,AED,SR,AE,,
S-2,2026-02-11,Synthetic Buyer B,900000000000003,2000.00,100.00,AED,SR,AE,,2025-12-28
S-3,2026-02-20,Synthetic Export Co,,500.00,0.00,AED,ZR,US,EXP-1,
S-4,2026-03-05,Synthetic Export Two,,300.00,0.00,AED,ZR,GB,,
S-5,2026-03-06,Synthetic Local,,400.00,20.00,AED,ZR,AE,,
S-6,2026-03-07,Synthetic Resident,,250.00,0.00,AED,EX,AE,,
S-7,2026-03-08,Synthetic Other,,100.00,5.00,AED,ZZ,AE,,
"""
PURCHASE_CSV = b"""invoice_number,invoice_date,supplier_name,supplier_trn,net_amount,tax_amount,currency,tax_code,expense_category,supplier_country
P-1,2026-01-15,Synthetic Supplier A,900000000000010,800.00,40.00,AED,SR,office,AE
P-2,2026-02-15,Synthetic Overseas,,1000.00,50.00,AED,RC,software,US
P-3,2026-03-15,Synthetic Overseas Two,,200.00,0.00,AED,RC,services,DE
P-4,2026-03-20,Synthetic Club,900000000000011,600.00,30.00,AED,SR,Entertainment,AE
P-1,2026-01-15,Synthetic Supplier A,900000000000010,800.00,40.00,AED,SR,office,AE
"""
# Box S1  = 1000 + 2000                       = 3000.00  (returned 3000.00)
# Box S1T = 50 + 100                           =  150.00  (returned  150.00)
# Box S2  = 500 + 300 + 400                    = 1200.00  (returned 1200.00)
# Box S3  = 250                                =  250.00  (returned  250.00)
# Box R1  = 1000 + 200                         = 1200.00  (returned 1200.00)
# Box R1T = 50 + 0                             =   50.00  (returned   50.00)
# Box P1  = 800 + 1000 + 200 + 600 + 800       = 3400.00  (returned 3400.00)
# Box P1T = 40 + 50 + 0 + 30 + 40              =  160.00  (returned  150.00 → −10.00)
# T1 = S1T + R1T = 150 + 50                    =  200.00  (returned  200.00)
# T2 = T1 − P1T = 200 − 150 (returned values)  =   50.00  (returned   55.00 → +5.00)
RETURN_CSV = b"""box_code,description,amount,tax_amount
S1,Standard sales,3000.00,
S1T,Standard sales VAT,,150.00
S2,Zero-rated sales,1200.00,
S3,Exempt sales,250.00,
R1,Reverse charge,1200.00,
R1T,Reverse charge VAT,,50.00
P1,Purchases,3400.00,
P1T,Recoverable VAT,,150.00
T1,Total output VAT,,200.00
T2,Net VAT,,55.00
Z9,Unknown box,1.00,
"""
# Output GL = −(−150 − 50) = 200.00 vs S1T + R1T = 200.00 → agrees.
# Input GL  = 70 + 50      = 120.00 vs P1T       = 150.00 → +30.00.
# J4 (2026-04-02) is outside the tax period and is ignored.
GL_CSV = b"""entry_id,posting_date,account_code,description,debit,credit
J1,2026-03-31,2200,Output VAT,,150.00
J1,2026-03-31,1100,Receivables,150.00,
J2,2026-03-31,2210,Reverse charge output,,50.00
J2,2026-03-31,1410,Reverse charge input,50.00,
J3,2026-03-31,1400,Input VAT,70.00,
J3,2026-03-31,2100,Payables,,70.00
J4,2026-04-02,2200,Next period,,999.00
J4,2026-04-02,1100,Next period,999.00,
"""
CUSTOMERS_CSV = b"""party_id,name,trn,country,address_line1,city,building_number
C1,Synthetic Buyer A,900000000000002,AE,1 Synthetic Street,Synthetic City,
C2,Synthetic Buyer B,12345,AE,,Synthetic City,
C3,Synthetic Saudi Co,800000000000008,SA,2 Synthetic Road,Synthetic City,
C4,Synthetic Buyer A,900000000000002,AE,1 Synthetic Street,Synthetic City,
"""

VAT_SETUP = {
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


def dataset(client: ApiClient, entity: LegalEntity, kind: str, data: bytes) -> str:
    r = client.post(
        "/api/datasets",
        data={
            "entity_id": str(entity.id),
            "kind": kind,
            "name": f"Synthetic {kind}",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
        },
        files={"file": (f"{kind}.csv", data, "text/csv")},
    )
    assert r.status_code == 201, r.text
    v = r.json()["latest_version"]
    if v["status"] != "ready":
        header = data.split(b"\n", 1)[0].decode().split(",")
        m = client.put(
            f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": {h: h for h in header}}
        )
        assert m.status_code == 200, m.text
        v = m.json()
    assert v["status"] == "ready", v
    return str(v["id"])


def period(
    client: ApiClient, entity: LegalEntity, start: str = "2026-01-01", end: str = "2026-03-31"
) -> Any:
    return client.post(
        f"/api/entities/{entity.id}/tax-periods",
        json={"frequency": "quarterly", "period_start": start, "period_end": end},
    )


# ---------------------------------------------------------------- tax setup endpoints


def test_tax_periods_and_vat_setup(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)

    assert period(analyst, entity).status_code == 403
    r = period(reviewer, entity)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status"] == "open"
    overlap = period(reviewer, entity, "2026-03-01", "2026-05-31")
    assert overlap.status_code == 409
    assert period(reviewer, entity, "2026-03-31", "2026-01-01").status_code == 422
    assert [p["id"] for p in viewer.get(f"/api/entities/{entity.id}/tax-periods").json()] == [pid]
    filed = reviewer.patch(f"/api/tax-periods/{pid}", json={"status": "filed"})
    assert filed.status_code == 200 and filed.json()["status"] == "filed"

    assert reviewer.put(f"/api/entities/{entity.id}/vat-setup", json=VAT_SETUP).status_code == 403
    put = admin.put(f"/api/entities/{entity.id}/vat-setup", json=VAT_SETUP)
    assert put.status_code == 200, put.text
    assert len(put.json()["tax_codes"]) == 5 and len(put.json()["tax_accounts"]) == 4
    dup = {**VAT_SETUP, "tax_codes": VAT_SETUP["tax_codes"] + [VAT_SETUP["tax_codes"][0]]}
    assert admin.put(f"/api/entities/{entity.id}/vat-setup", json=dup).status_code == 422
    got = viewer.get(f"/api/entities/{entity.id}/vat-setup").json()
    assert {c["tax_code"] for c in got["tax_codes"]} == {"SR", "ZR", "EX", "RC"}

    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get(f"/api/entities/{entity.id}/tax-periods").status_code == 404
    assert period(other, entity).status_code == 404
    assert other.patch(f"/api/tax-periods/{pid}", json={"status": "open"}).status_code == 404
    assert (
        other.patch(f"/api/tax-periods/{uuid.uuid4()}", json={"status": "open"}).status_code == 404
    )
    assert other.get(f"/api/entities/{entity.id}/vat-setup").status_code == 404
    assert other.put(f"/api/entities/{entity.id}/vat-setup", json=VAT_SETUP).status_code == 404


# ---------------------------------------------------------------- master data


def test_master_data_scan(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin, with_bundle=False)
    customers = dataset(analyst, entity, "customer_master", CUSTOMERS_CSV)
    sales = dataset(analyst, entity, "sales_register", SALES_CSV)
    cv = checklist(
        login(tenant_a.users[Role.REVIEWER]),
        [
            req(
                "MD-01",
                {
                    "type": "tax_id_format",
                    "dataset": "customer_master",
                    "field": "trn",
                    "country_field": "country",
                    "default_country": "AE",
                    "formats_rule": "syn.vat.tax_id_formats",
                },
            ),
            req(
                "MD-02",
                {
                    "type": "completeness",
                    "dataset": "customer_master",
                    "required_rule": "syn.vat.required_fields",
                    "country_field": "country",
                    "default_country": "AE",
                },
            ),
            req(
                "MD-03",
                {"type": "duplicate", "dataset": "customer_master", "keys": ["name", "trn"]},
            ),
            req(
                "MD-04",
                {
                    "type": "party_cross_check",
                    "dataset": "sales_register",
                    "master": "customer_master",
                },
            ),
        ],
    )
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "Customer master",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "dataset_version_ids": [customers, sales],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    res = results(analyst, r.json()["id"])
    # C2's TRN "12345" is 5 digits, the synthetic AE shape is 15 starting 9.
    assert res["MD-01"]["outcome"] == "exceptions_found"
    by_key = {f["finding_key"]: f for f in findings(analyst, r.json()["id"])}
    assert by_key["tax_id:invalid:AE"]["evidence"][0]["row_ids"] == [2]
    # C2 lacks address_line1 (all countries); C3 lacks building_number (SA only).
    assert by_key["missing:address_line1"]["evidence"][0]["row_ids"] == [2]
    assert by_key["missing:building_number"]["evidence"][0]["row_ids"] == [3]
    assert res["MD-03"]["outcome"] == "exceptions_found"
    # S-2's customer TRN 900000000000003 is not in the master.
    assert by_key["party:unknown_trn"]["evidence"][0]["row_ids"] == [2]


# ---------------------------------------------------------------- VAT return review


VAT_REQUIREMENTS = [
    req(
        "VAT-01",
        {
            "type": "vat_box_reconcile",
            "layout_rule": "syn.vat.box_layout",
            "tolerance_rule": "syn.vat.box_tolerance",
        },
    ),
    req(
        "VAT-02",
        {
            "type": "vat_gl_reconcile",
            "layout_rule": "syn.vat.box_layout",
            "tolerance_rule": "syn.vat.box_tolerance",
        },
    ),
    req("VAT-03", {"type": "reverse_charge"}, "medium"),
    req("VAT-04", {"type": "zero_rated_evidence"}),
    req("VAT-05", {"type": "blocked_input", "blocked_rule": "syn.vat.blocked_categories"}),
    req(
        "VAT-06",
        {
            "type": "duplicate",
            "dataset": "purchase_register",
            "keys": ["supplier_trn", "invoice_number"],
        },
    ),
    req(
        "VAT-07",
        {
            "type": "date_rule",
            "dataset": "sales_register",
            "field": "supply_date",
            "rule": "within_period",
        },
    ),
]


def _vat_review(tenant: Tenant, db: Session, with_setup: bool = True) -> tuple[ApiClient, str]:
    admin = login(tenant.users[Role.ORG_ADMIN])
    reviewer = login(tenant.users[Role.REVIEWER])
    analyst = login(tenant.users[Role.ANALYST])
    entity = make_entity(db, tenant)
    if with_setup:
        assert admin.put(f"/api/entities/{entity.id}/vat-setup", json=VAT_SETUP).status_code == 200
    rpv = synthetic_pack(admin, with_bundle=False)
    tp = period(reviewer, entity).json()["id"]
    ids = [
        dataset(analyst, entity, "sales_register", SALES_CSV),
        dataset(analyst, entity, "purchase_register", PURCHASE_CSV),
        dataset(analyst, entity, "vat_return", RETURN_CSV),
        dataset(analyst, entity, "general_ledger", GL_CSV),
    ]
    cv = checklist(reviewer, VAT_REQUIREMENTS)
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "Synthetic Q1 VAT",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "tax_period_id": tp,
            "dataset_version_ids": ids,
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["tax_period_start"] == "2026-01-01"
    return analyst, str(r.json()["id"])


def test_vat_return_review_golden_values(tenant_a: Tenant, db: Session) -> None:
    analyst, rid = _vat_review(tenant_a, db)
    res = results(analyst, rid)
    by_key = {f["finding_key"]: f for f in findings(analyst, rid)}

    boxes = {b["code"]: b for b in res["VAT-01"]["meta"]["box_table"]}
    expected = {
        "S1": ("3000.00", "0.00"),
        "S1T": ("150.00", "0.00"),
        "S2": ("1200.00", "0.00"),
        "S3": ("250.00", "0.00"),
        "R1": ("1200.00", "0.00"),
        "R1T": ("50.00", "0.00"),
        "P1": ("3400.00", "0.00"),
        "P1T": ("160.00", "-10.00"),
        "T1": ("200.00", "0.00"),
        "T2": ("50.00", "5.00"),
    }
    for code, (exp, diff) in expected.items():
        assert float(boxes[code]["expected"]) == float(exp), (code, boxes[code])
        assert float(boxes[code]["difference"]) == float(diff), (code, boxes[code])
    assert res["VAT-01"]["meta"]["unknown_boxes"] == ["Z9"]
    vat01 = {k for k, f in by_key.items() if f["requirement_code"] == "VAT-01"}
    assert vat01 == {"box:P1T", "box_total:T2", "unmapped_tax_code:sales_register"}, vat01
    assert by_key["unmapped_tax_code:sales_register"]["evidence"][0]["row_ids"] == [7]
    assert by_key["box:P1T"]["evidence"][0]["type"] == "computation"

    gl = {s["side"]: s for s in res["VAT-02"]["meta"]["gl_table"]}
    assert float(gl["output"]["gl"]) == 200 and float(gl["output"]["difference"]) == 0
    assert float(gl["input"]["gl"]) == 120 and float(gl["input"]["difference"]) == 30
    assert res["VAT-02"]["meta"]["period"] == ["2026-01-01", "2026-03-31"]
    assert "gl:output" not in by_key and "gl:input" in by_key

    assert by_key["rc:items"]["evidence"][0]["row_ids"] == [2, 3]
    assert by_key["rc:no_tax"]["evidence"][0]["row_ids"] == [3]
    assert by_key["zero_rated:no_evidence"]["evidence"][0]["row_ids"] == [4]
    assert by_key["zero_rated:tax_charged"]["evidence"][0]["row_ids"] == [5]
    # Category match ignores case ("Entertainment").
    assert by_key["blocked:entertainment"]["evidence"][0]["row_ids"] == [4]
    assert res["VAT-06"]["evidence"][0]["row_ids"] == [1, 5]
    # Supply date 2025-12-28 on S-2 is before the tax period.
    assert res["VAT-07"]["meta"]["period"] == ["2026-01-01", "2026-03-31"]
    assert res["VAT-07"]["evidence"][0]["row_ids"] == [2]
    assert any(
        "Unverified" in w
        for w in analyst.get(f"/api/reviews/{rid}").json()["latest_run"]["warnings"]
    )


def test_vat_checks_need_the_entity_vat_setup(tenant_a: Tenant, db: Session) -> None:
    analyst, rid = _vat_review(tenant_a, db, with_setup=False)
    res = results(analyst, rid)
    # Without tax code mappings every register row is unmapped; without GL accounts
    # the GL check cannot run.
    assert res["VAT-02"]["outcome"] == "not_applicable" and res["VAT-02"]["needs_attention"]
    assert "VAT GL accounts" in res["VAT-02"]["message"]
    keys = {f["finding_key"] for f in findings(analyst, rid) if f["requirement_code"] == "VAT-01"}
    assert "unmapped_tax_code:sales_register" in keys


def test_review_period_must_belong_to_the_entity(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    e1, e2 = make_entity(db, tenant_a), make_entity(db, tenant_a)
    tp = period(reviewer, e1).json()["id"]
    cv = checklist(reviewer, [VAT_REQUIREMENTS[2]])
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "x",
            "checklist_version_id": cv,
            "entity_id": str(e2.id),
            "tax_period_id": tp,
        },
    )
    assert r.status_code == 422, r.text
    other = login(tenant_b.users[Role.REVIEWER])
    other_cv = checklist(other, [VAT_REQUIREMENTS[2]])
    r = other.post(
        "/api/reviews",
        json={"title": "x", "checklist_version_id": other_cv, "entity_id": str(e1.id)},
    )
    assert r.status_code == 404, r.text
