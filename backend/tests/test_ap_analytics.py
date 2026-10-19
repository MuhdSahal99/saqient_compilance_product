"""Phase E5: AP and expense analytics (engine 1.5.0) with the synthetic syn.ap rules.

Synthetic parameters (app/demo_tax.py): duplicate tolerance 0.00, window 30 days,
name and invoice similarity 90; TRN countries [AE], minimum 0; dormant 180 days;
quantity tolerance 0, price tolerance 0.02; expense limits meals AED 300 (receipt
over 50) and travel AED 5000 (receipt over 0).

Payments, hand-checked:
  P1 V1 Gulf Supplies LLC   2026-01-10 1000 INV-001
  P2 V1 Gulf Supplies LLC   2026-01-20 1000 INV-002   duplicate of P1 (10 days apart)
  P3 -- Gulf Supplies LLC.  2026-03-15 1000 INV-001   duplicate of P1 (same invoice);
                                                      vs P2: 54 days, invoice 85.7 < 90
  P4 V2 Desert Logistics    2026-01-12 1000           other vendor id: not a duplicate
  P5 V2 Desert Logistics    2026-01-05 2500  AE, no TRN → missing TRN
  P6 V3 Overseas Parts      2026-01-07  700  DE, no TRN → not in the TRN countries
  P7 V4 Staff Services      2026-02-01  400  IBAN equals employee E2's (with spaces)
  P8 V2 Desert Logistics    2026-08-01 1200  201 days after P4 → dormant vendor
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.engine.ap_checks import dormant_payments, duplicate_pairs, norm_iban, norm_name
from app.models import Role
from app.services import rule_schemas
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import checklist, findings, req, results
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack

E2_IBAN = "AE460090000000012345678"
PAYMENTS = (
    b"payment_id,payment_date,vendor_id,vendor_name,vendor_trn,vendor_country,"
    b"invoice_number,amount,currency,iban\n"
    b"P1,2026-01-10,V1,Gulf Supplies LLC,100000000000003,AE,INV-001,1000.00,AED,"
    b"AE070331234567890123456\n"
    b"P2,2026-01-20,V1,Gulf Supplies LLC,100000000000003,AE,INV-002,1000.00,AED,\n"
    b"P3,2026-03-15,,Gulf Supplies LLC.,100000000000003,AE,INV-001,1000.00,AED,\n"
    b"P4,2026-01-12,V2,Desert Logistics,100000000000004,AE,D-9,1000.00,AED,\n"
    b"P5,2026-01-05,V2,Desert Logistics,,AE,D-1,2500.00,AED,\n"
    b"P6,2026-01-07,V3,Overseas Parts GmbH,,DE,OP-1,700.00,AED,\n"
    b"P7,2026-02-01,V4,Staff Services,100000000000005,AE,S-1,400.00,AED,"
    b"AE46 0090 0000 0001 2345 678\n"
    b"P8,2026-08-01,V2,Desert Logistics,100000000000004,AE,D-20,1200.00,AED,\n"
)
EMPLOYEES = (
    b"employee_id,employee_name,iban\n"
    b"E1,Alice (synthetic),AE070331234567890123499\n"
    b"E2,Bob (synthetic)," + E2_IBAN.encode() + b"\n"
    b"E3,Carol (synthetic),\n"
)
MATCH = (
    b"po_number,invoice_number,item,po_quantity,received_quantity,invoiced_quantity,"
    b"po_unit_price,invoice_unit_price,currency\n"
    b"PO1,INV1,A,10,10,10,5.00,5.00,AED\n"
    b"PO2,INV2,B,10,8,10,5.00,5.00,AED\n"
    b"PO3,INV3,C,5,0,5,5.00,5.00,AED\n"
    b"PO4,INV4,D,4,4,4,100.00,103.00,AED\n"
    b"PO5,INV5,E,4,4,4,100.00,101.50,AED\n"
)
CLAIMS = (
    b"claim_id,employee_id,claim_date,category,amount,currency,receipt_ref\n"
    b"X1,E1,2026-01-03,Meals,120.00,AED,R1\n"
    b"X2,E1,2026-01-04,Meals,350.00,AED,R2\n"
    b"X3,E2,2026-01-05,Meals,80.00,AED,\n"
    b"X4,E2,2026-01-06,Travel,900.00,USD,R4\n"
    b"X5,E3,2026-01-07,Gifts,50.00,AED,R5\n"
    b"X6,E3,2026-01-08,Travel,10.00,AED,\n"
)


def _pay(rid: int, d: str, vid: str, name: str, amt: str, inv: str = "") -> dict[str, Any]:
    return {
        "row_id": rid,
        "payment_date": date.fromisoformat(d),
        "vendor_id": vid or None,
        "vendor_name": name,
        "amount": Decimal(amt),
        "currency": "AED",
        "invoice_number": inv or None,
    }


def test_helpers_by_hand() -> None:
    assert norm_name("Gulf Supplies L.L.C.") == "gulf supplies l l c"
    assert norm_iban("ae46 0090-0000") == "AE4600900000"
    rows = [
        _pay(1, "2026-01-10", "V1", "A", "100.00", "I-1"),
        _pay(2, "2026-01-11", "V1", "A", "100.01", "I-2"),
        _pay(3, "2026-01-12", "V1", "A", "100.00", "I-3"),
    ]
    assert [
        (a["row_id"], b["row_id"])
        for a, b in duplicate_pairs(rows, Decimal("0"), 5, Decimal(90), Decimal(90))
    ] == [(1, 3)]
    # A tolerance of 0.01 also pairs row 2 with rows 1 and 3.
    assert len(duplicate_pairs(rows, Decimal("0.01"), 5, Decimal(90), Decimal(90))) == 3
    gaps = dormant_payments(
        [_pay(1, "2026-01-01", "V1", "A", "1"), _pay(2, "2026-07-01", "V1", "A", "1")], 181
    )
    assert [(p["row_id"], c["row_id"], gap) for p, c, gap in gaps] == [(1, 2, 181)]
    assert (
        dormant_payments(
            [_pay(1, "2026-01-01", "V1", "A", "1"), _pay(2, "2026-06-30", "V1", "A", "1")], 181
        )
        == []
    )


def test_rule_shapes() -> None:
    ok = {"meals": {"currency": "AED", "per_claim": "300", "receipt_over": None}}
    assert rule_schemas.validate_shape("p.expense_limits", ok)["meals"].per_claim == 300
    for key, bad in (
        ("p.expense_limits", {"Meals": {"currency": "AED"}}),
        ("p.expense_limits", {"meals": {"currency": "aed"}}),
        ("p.expense_limits", {"meals": {"currency": "AED", "per_claim": "-1"}}),
        ("p.trn_countries", ["ae"]),
    ):
        with pytest.raises(rule_schemas.RuleShapeError):
            rule_schemas.validate_shape(key, bad)


def ap(test: str) -> dict[str, Any]:
    return {"type": "ap_analytics", "test": test, "rules_prefix": "syn.ap"}


def test_ap_analytics_through_a_review(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    versions = [
        dataset(reviewer, entity, "ap_payments", PAYMENTS),
        dataset(reviewer, entity, "employee_master", EMPLOYEES),
        dataset(reviewer, entity, "three_way_match", MATCH),
        dataset(reviewer, entity, "expense_claims", CLAIMS),
    ]
    tests = [
        "duplicate_payment",
        "vendor_employee_bank",
        "missing_trn",
        "dormant_vendor",
        "three_way_match",
        "expense_policy",
    ]
    cv = checklist(reviewer, [req(f"AP-{i}", ap(t)) for i, t in enumerate(tests)])
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "Synthetic AP analytics",
            "checklist_version_id": cv,
            "dataset_version_ids": versions,
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    res = results(reviewer, rid)
    for i in range(len(tests)):
        assert res[f"AP-{i}"]["outcome"] == "exceptions_found", res[f"AP-{i}"]
        if tests[i] != "vendor_employee_bank":  # the bank test reads no rules
            assert any("Unverified" in w for w in res[f"AP-{i}"]["meta"]["warnings"])
    fs = findings(reviewer, rid)

    def rows(code: str, key: str, n: int = 0, col: str = "") -> list[Any]:
        got = [f for f in fs if f["requirement_code"] == code and f["finding_key"] == key]
        assert len(got) == 1, (code, key, [f["finding_key"] for f in fs])
        ev = got[0]["evidence"][n]
        dicts = [dict(zip(ev["columns"], row, strict=True)) for row in ev["rows"]]
        return [d[col] for d in dicts] if col else [d["row_id"] for d in dicts]

    assert rows("AP-0", "duplicate_payment") == [1, 2, 3]
    assert rows("AP-0", "duplicate_payment", col="_pair") == ["1,2", "1", "2"]
    assert res["AP-0"]["meta"]["exception_count"] == 2
    assert rows("AP-1", "vendor_employee_bank") == [7]
    assert rows("AP-1", "vendor_employee_bank", 1, "employee_id") == ["E2"]
    masked = rows("AP-1", "vendor_employee_bank", col="_iban")[0]
    assert masked.endswith("5678") and "0090" not in masked
    assert E2_IBAN not in json.dumps(fs) and "0001 2345" not in json.dumps(fs)
    assert rows("AP-2", "missing_trn") == [5]
    assert rows("AP-3", "dormant_vendor") == [4, 8]
    assert rows("AP-3", "dormant_vendor", col="_gap_days") == [None, "201"]
    assert rows("AP-4", "no_receipt") == [3]
    assert rows("AP-4", "quantity") == [2]
    assert rows("AP-4", "price") == [4]
    assert rows("AP-5", "over_limit:meals") == [2]
    assert rows("AP-5", "no_receipt:meals") == [3]
    assert rows("AP-5", "other_currency:travel") == [4]
    assert rows("AP-5", "unknown_category:gifts") == [5]
    assert rows("AP-5", "no_receipt:travel") == [6]
