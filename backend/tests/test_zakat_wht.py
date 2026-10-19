"""Phase C6: zakat base workpaper and the withholding tax check over a payments dataset.

WHT golden values use the synthetic rules in app/demo_tax.py: royalty 0.12,
technical services 0.04, rent 0.04, resident country SA, tolerance 1.00.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import checklist, findings, req, results
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack, lines, new_paper, put_in

# Q1 2026 payments. Expected withholding = gross x rate:
#   P1 royalty GB 100000 x 0.12 = 12000, withheld 12000            -> fine
#   P2 royalty US 50000 x 0.12 = 6000, withheld 3000               -> short 3000
#   P3 technical_services AE 20000 x 0.04 = 800, withheld 799.50   -> short 0.50 (within tolerance)
#   P4 rent SA (resident)                                          -> out of scope
#   P5 consulting FR: no rate in the pack                          -> unknown type
#   P6 royalty IN treaty 0.05 with certificate: 40000 x 0.05 = 2000, withheld 2000 -> fine
#   P7 royalty DE treaty 0.05, no certificate: expected 0.12 x 10000 = 1200, withheld 500
#       -> treaty without certificate, and short 700
#   P8 no payee country                                            -> missing residency
#   P9 royalty GB dated April                                      -> outside the period
PAYMENTS_CSV = (
    b"payment_id,payment_date,payee_name,payee_country,payment_type,gross_amount,wht_amount,"
    b"treaty_rate,treaty_certificate,currency\n"
    b"P1,2026-01-10,Synthetic Licensor A,GB,royalty,100000,12000,,,SAR\n"
    b"P2,2026-01-20,Synthetic Licensor B,US,royalty,50000,3000,,,SAR\n"
    b"P3,2026-02-01,Synthetic Engineer,AE,technical_services,20000,799.50,,,SAR\n"
    b"P4,2026-02-05,Synthetic Landlord,SA,rent,90000,0,,,SAR\n"
    b"P5,2026-02-10,Synthetic Adviser,FR,consulting,5000,0,,,SAR\n"
    b"P6,2026-03-01,Synthetic Licensor C,IN,royalty,40000,2000,0.05,CERT-SYN-1,SAR\n"
    b"P7,2026-03-02,Synthetic Licensor D,DE,royalty,10000,500,0.05,,SAR\n"
    b"P8,2026-03-03,Synthetic Unknown,,royalty,1000,0,,,SAR\n"
    b"P9,2026-04-02,Synthetic Licensor A,GB,royalty,100000,0,,,SAR\n"
)
WHT = {
    "type": "wht_rates",
    "rates_rule": "syn.wht.wht_rates",
    "resident_country_rule": "syn.wht.resident_country",
    "tolerance_rule": "syn.wht.tolerance",
}


def test_wht_check_golden(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a, currency="SAR")
    rpv = ct_pack(admin)
    tp = reviewer.post(
        f"/api/entities/{entity.id}/tax-periods",
        json={"frequency": "quarterly", "period_start": "2026-01-01", "period_end": "2026-03-31"},
    )
    assert tp.status_code == 201, tp.text
    ds = dataset(analyst, entity, "wht_payments", PAYMENTS_CSV)
    cv = checklist(reviewer, [req("WHT-01", WHT)])
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "Synthetic Q1 WHT",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "tax_period_id": tp.json()["id"],
            "dataset_version_ids": [ds],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    res = results(analyst, rid)["WHT-01"]
    assert res["outcome"] == "exceptions_found", res
    # P1, P2, P3, P5, P6, P7 are non-resident and in the period (P8 has no country).
    assert res["meta"]["checked"] == 6
    assert any("Unverified" in w for w in res["meta"]["warnings"])
    by_key = {f["finding_key"]: f for f in findings(analyst, rid)}
    assert set(by_key) == {
        "under_withheld:royalty",
        "unknown_type:consulting",
        "treaty_without_certificate",
        "missing_residency",
    }
    under = by_key["under_withheld:royalty"]["evidence"][0]
    assert under["row_ids"] == [2, 7]
    cols = under["columns"]
    row2 = dict(zip(cols, under["rows"][0], strict=True))
    assert Decimal(row2["_expected"]) == Decimal(6000)
    assert Decimal(row2["_shortfall"]) == Decimal(3000)
    row7 = dict(zip(cols, under["rows"][1], strict=True))
    assert Decimal(row7["_rate"]) == Decimal("0.12") and Decimal(row7["_shortfall"]) == 700
    assert "shortfall 3700" in under["label"]
    assert by_key["unknown_type:consulting"]["evidence"][0]["row_ids"] == [5]
    assert by_key["treaty_without_certificate"]["evidence"][0]["row_ids"] == [7]
    assert by_key["missing_residency"]["evidence"][0]["row_ids"] == [8]


def test_wht_check_needs_the_dataset_and_rules(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a, currency="SAR")
    rpv = ct_pack(admin)
    cv = checklist(reviewer, [req("WHT-01", WHT)])
    ds = dataset(reviewer, entity, "wht_payments", PAYMENTS_CSV)
    bad = {**WHT, "rates_rule": "syn.wht.missing"}
    cv2 = checklist(reviewer, [req("WHT-02", bad)])
    for version, code in ((cv, "WHT-01"), (cv2, "WHT-02")):
        r = reviewer.post(
            "/api/reviews",
            json={
                "title": f"Synthetic {uuid.uuid4().hex[:4]}",
                "checklist_version_id": version,
                "entity_id": str(entity.id),
                "dataset_version_ids": [ds] if code == "WHT-02" else [],
                "rule_pack_version_id": rpv,
            },
        )
        assert r.status_code == 201, r.text
        res = results(reviewer, r.json()["id"])[code]
        assert res["outcome"] in ("not_run", "error", "not_applicable"), res
        assert res["outcome"] != "exceptions_found"


def test_zakat_workpaper_through_the_api(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    """Golden case 1 of tests/golden/zakat.json, entered through the API."""
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a, currency="SAR")
    rpv = ct_pack(admin)
    wp = new_paper(
        admin, entity.id, rpv, kind="zakat", title="Synthetic zakat", rules_prefix="syn.zakat"
    )
    assert wp.status_code == 201, wp.text
    wid = wp.json()["id"]
    for key, cat, amt in [
        ("adjusted_net_profit", "input", "5000000"),
        ("equity", "zakat_addition", "10000000"),
        ("provisions", "zakat_addition", "1000000"),
        ("long_term_loans", "zakat_addition", "4000000"),
        ("fixed_assets", "zakat_deduction", "9000000"),
        ("investments", "zakat_deduction", "2000000"),
    ]:
        assert put_in(admin, wid, key, category=cat, amount=amt).status_code == 200
    out = admin.post(f"/api/workpapers/{wid}/compute")
    assert out.status_code == 200, out.text
    got = lines(out.json())
    assert Decimal(got["calc:zakat"]["amount"]) == Decimal(150000)
    assert Decimal(got["calc:base_used"]["amount"]) == Decimal(5000000)
    keys = {s["rule_key"] for s in got["calc:zakat"]["rule_snapshots"]}
    assert "syn.zakat.zakat_rate" in keys
    assert put_in(admin, wid, "x", category="non_deductible", amount="1").status_code == 422
    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.post(f"/api/workpapers/{wid}/compute").status_code == 404
