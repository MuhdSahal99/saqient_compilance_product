"""Phase D5: samples over a dataset version through the API."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_engagements import new_engagement
from tests.test_vat_review import dataset

# 20 synthetic invoices, net amounts 1000, 2000, ... 20000 (total 210000); one zero row.
SALES = (
    b"invoice_number,invoice_date,net_amount,tax_amount\n"
    + b"".join(f"S{i},2026-01-{i:02d},{i * 1000},{i * 50}\n".encode() for i in range(1, 21))
    + b"S21,2026-01-21,0,0\n"
)


def test_sample_lifecycle(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    ds = dataset(analyst, entity, "sales_register", SALES)
    body = {
        "name": "Synthetic revenue MUS",
        "method": "monetary_unit",
        "dataset_version_id": ds,
        "amount_column": "net_amount",
        "size": 5,
        "seed": "synthetic-seed-1",
    }
    assert viewer.post(f"/api/engagements/{eid}/samples", json=body).status_code == 403
    assert (
        analyst.post(
            f"/api/engagements/{eid}/samples", json={**body, "amount_column": "invoice_number"}
        ).status_code
        == 422
    )
    assert (
        analyst.post(
            f"/api/engagements/{eid}/samples", json={**body, "strata": [{"size": 1}]}
        ).status_code
        == 422
    )
    r = analyst.post(f"/api/engagements/{eid}/samples", json=body)
    assert r.status_code == 201, r.text
    s = r.json()
    # The zero row is not in the population; 210000 / 5 = 42000.00.
    assert s["population_count"] == 20 and Decimal(s["population_value"]) == 210000
    assert s["params"]["interval"] == "42000.00" and s["seed"] == "synthetic-seed-1"
    assert s["algorithm_version"] == "sampling-1.0.0" and len(s["population_sha256"]) == 64
    assert 1 <= s["item_count"] <= 5
    assert sum(i["hits"] for i in s["items"]) == 5
    sid = s["id"]
    rep = viewer.get(f"/api/samples/{sid}/reproduce").json()
    assert rep == {"reproducible": True, "population_unchanged": True, "differences": []}
    # Same seed and parameters select the same rows.
    twin = analyst.post(
        f"/api/engagements/{eid}/samples", json={**body, "name": "Synthetic twin"}
    ).json()
    assert [i["row_id"] for i in twin["items"]] == [i["row_id"] for i in s["items"]]

    first = s["items"][0]
    book = Decimal(first["book_value"])
    path = f"/api/samples/{sid}/items/{first['row_id']}"
    assert analyst.put(path, json={"audited_value": str(book - 100)}).status_code == 422  # no note
    assert (
        analyst.post(f"/api/samples/{sid}/conclusion", json={"conclusion": "x"}).status_code == 422
    )
    t = analyst.put(
        path, json={"audited_value": str(book - 100), "note": "Synthetic pricing error"}
    )
    assert t.status_code == 200, t.text
    tested = {i["row_id"]: i for i in t.json()["items"]}
    assert tested[first["row_id"]]["result"] == "exception"
    proj = t.json()["projection"]
    # Book below the 42000 interval: tainting 100 / book x 42000.
    want = (Decimal(100) / book * Decimal(42000)).quantize(Decimal("0.01"))
    assert Decimal(proj["projected"]) == want and proj["performance_materiality"] is None
    for i in s["items"][1:]:
        assert (
            analyst.put(
                f"/api/samples/{sid}/items/{i['row_id']}", json={"audited_value": i["book_value"]}
            ).status_code
            == 200
        )
    assert (
        analyst.put(f"/api/samples/{sid}/items/999", json={"audited_value": "1"}).status_code == 404
    )
    c = analyst.post(
        f"/api/samples/{sid}/conclusion",
        json={"conclusion": "Synthetic: projected below tolerable."},
    )
    assert c.status_code == 200 and c.json()["conclusion"]

    rnd = analyst.post(
        f"/api/engagements/{eid}/samples",
        json={**body, "method": "random", "size": 21, "seed": None},
    )
    assert rnd.status_code == 422  # larger than the population
    rnd = analyst.post(
        f"/api/engagements/{eid}/samples",
        json={**body, "method": "random", "size": 4, "seed": None},
    )
    assert (
        rnd.status_code == 201 and rnd.json()["item_count"] == 4 and len(rnd.json()["seed"]) == 32
    )
    strat = analyst.post(
        f"/api/engagements/{eid}/samples",
        json={
            **body,
            "method": "stratified",
            "size": None,
            "strata": [{"upper": "10000", "size": 2}, {"upper": None, "size": None}],
        },
    )
    assert strat.status_code == 201, strat.text
    items = strat.json()["items"]
    # 11000 … 20000 are the ten rows of the open top stratum, all tested; two from the rest.
    assert sum(1 for i in items if i["stratum"] == 1) == 10
    assert sum(1 for i in items if i["stratum"] == 0) == 2
    assert len(viewer.get(f"/api/engagements/{eid}/samples").json()) == 4


def test_sample_tenancy(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    ds = dataset(analyst, entity, "sales_register", SALES)
    body = {
        "name": "x",
        "method": "random",
        "dataset_version_id": ds,
        "amount_column": "net_amount",
        "size": 2,
    }
    sid = analyst.post(f"/api/engagements/{eid}/samples", json=body).json()["id"]

    b = login(tenant_b.users[Role.ORG_ADMIN])
    b_entity = make_entity(db, tenant_b)
    b_ds = dataset(b, b_entity, "sales_register", SALES)
    assert (
        analyst.post(
            f"/api/engagements/{eid}/samples", json={**body, "dataset_version_id": b_ds}
        ).status_code
        == 404
    )
    other_entity = make_entity(db, tenant_a)
    other_ds = dataset(analyst, other_entity, "sales_register", SALES + b"S22,2026-01-22,5,0\n")
    assert (
        analyst.post(
            f"/api/engagements/{eid}/samples", json={**body, "dataset_version_id": other_ds}
        ).status_code
        == 422
    )
    assert b.get(f"/api/engagements/{eid}/samples").status_code == 404
    assert b.post(f"/api/engagements/{eid}/samples", json=body).status_code == 404
    assert b.get(f"/api/samples/{sid}").status_code == 404
    assert b.get(f"/api/samples/{sid}/reproduce").status_code == 404
    assert b.put(f"/api/samples/{sid}/items/1", json={"audited_value": "1"}).status_code == 404
    assert b.post(f"/api/samples/{sid}/conclusion", json={"conclusion": "x"}).status_code == 404
