"""Phase C4: related-party register, documentation thresholds and disclosure export.

Thresholds are the synthetic ones in app/demo_tax.py: entity revenue 150000000, group
revenue 3000000000 and disclosure total 30000000.
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import ApiClient, Tenant, login, upload
from tests.test_datasets import make_entity
from tests.test_workpapers import ct_pack


def party(client: ApiClient, entity_id: Any, name: str = "Synthetic Parent Co", **over: Any):  # type: ignore[no-untyped-def]
    body = {"name": name, "relation": "parent", "jurisdiction": "GB", **over}
    return client.post(f"/api/entities/{entity_id}/related-parties", json=body)


def txn(client: ApiClient, entity_id: Any, party_id: str, **over: Any):  # type: ignore[no-untyped-def]
    body = {
        "related_party_id": party_id,
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "transaction_type": "services",
        "direction": "payment",
        "amount": "20000000",
        **over,
    }
    return client.post(f"/api/entities/{entity_id}/rp-transactions", json=body)


def test_register_check_and_disclosure(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    p = party(analyst, entity.id)
    assert p.status_code == 201, p.text
    pid = p.json()["id"]
    assert party(analyst, entity.id).status_code == 422  # duplicate name
    sister = party(analyst, entity.id, "=Synthetic Sister", relation="sister", jurisdiction="SA")
    sid = sister.json()["id"]

    doc = upload(analyst, title="Synthetic benchmarking study").json()
    r = txn(
        analyst,
        entity.id,
        pid,
        method="tnmm",
        range_low="0.05",
        range_high="0.08",
        tested_value="0.09",
        range_metric="Net cost plus mark-up",
        benchmark_document_ids=[doc["id"]],
    )
    assert r.status_code == 201, r.text
    assert r.json()["benchmark_documents"] == [
        {"id": doc["id"], "title": "Synthetic benchmarking study"}
    ]
    assert txn(analyst, entity.id, pid, amount="5000000", direction="receipt").status_code == 201
    assert (
        txn(analyst, entity.id, sid, transaction_type="financing", amount="5000000").status_code
        == 201
    )
    # Outside the period: not counted.
    assert (
        txn(analyst, entity.id, pid, period_start="2024-01-01", period_end="2024-12-31").status_code
        == 201
    )

    check = {
        "rule_pack_version_id": rpv,
        "rules_prefix": "syn.ct",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "entity_revenue": "10000000",
        "in_mne_group": True,
        "group_revenue": "3000000000",
    }
    c = analyst.post(f"/api/entities/{entity.id}/tp/check", json=check)
    assert c.status_code == 200, c.text
    out = c.json()
    assert Decimal(out["rp_total"]) == Decimal(30000000) and out["transaction_count"] == 3
    vals = {x["key"]: x["value"] for x in out["lines"]}
    assert vals["test:master_file"] == "required"
    assert vals["test:local_file"] == "required"
    assert vals["test:disclosure"] == "required"  # 30000000 >= 30000000
    ranges = [v for k, v in vals.items() if k.startswith("range:")]
    assert ranges == ["outside"]
    assert out["warnings"]
    small = analyst.post(
        f"/api/entities/{entity.id}/tp/check", json={**check, "group_revenue": "100"}
    ).json()
    assert {x["key"]: x["value"] for x in small["lines"]}["test:master_file"] == "not_required"

    exp = analyst.get(
        f"/api/entities/{entity.id}/tp/disclosure.csv",
        params={"period_start": "2025-01-01", "period_end": "2025-12-31"},
    )
    assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(exp.text.lstrip("﻿"))))
    assert rows[0][0] == "Related party" and len(rows) == 4
    # Formula injection is neutralised.
    assert any(r[0] == "'=Synthetic Sister" for r in rows[1:])
    parent_pay = next(r for r in rows if r[0] == "Synthetic Parent Co" and r[4] == "payment")
    assert parent_pay[6] == "1" and Decimal(parent_pay[7]) == Decimal(20000000)

    assert analyst.delete(f"/api/related-parties/{pid}").status_code == 409
    listed = analyst.get(
        f"/api/entities/{entity.id}/rp-transactions",
        params={"period_start": "2025-01-01", "period_end": "2025-12-31"},
    ).json()
    assert len(listed) == 3
    for t in analyst.get(f"/api/entities/{entity.id}/rp-transactions").json():
        if t["related_party_id"] == sid:
            assert analyst.delete(f"/api/rp-transactions/{t['id']}").status_code == 204
    assert analyst.delete(f"/api/related-parties/{sid}").status_code == 204


def test_tp_validation_and_roles(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    pid = party(admin, entity.id).json()["id"]
    assert txn(admin, entity.id, pid, currency="USD").status_code == 422
    assert txn(admin, entity.id, pid, range_low="0.1").status_code == 422
    assert txn(admin, entity.id, pid, range_low="0.2", range_high="0.1").status_code == 422
    assert txn(admin, entity.id, pid, tested_value="0.1").status_code == 422
    assert txn(admin, entity.id, pid, amount="0").status_code == 422
    assert txn(admin, entity.id, pid, period_end="2024-01-01").status_code == 422
    assert txn(admin, entity.id, pid, benchmark_document_ids=[str(uuid.uuid4())]).status_code == 422
    assert party(admin, entity.id, "X", jurisdiction="gbr").status_code == 422
    # Party of another entity in the same org cannot be used.
    other = make_entity(db, tenant_a)
    assert txn(admin, other.id, pid).status_code == 404

    assert party(viewer, entity.id, "Y").status_code == 403
    assert txn(viewer, entity.id, pid).status_code == 403
    assert viewer.get(f"/api/entities/{entity.id}/related-parties").status_code == 200
    rpv = ct_pack(admin)
    check = {
        "rule_pack_version_id": rpv,
        "rules_prefix": "syn.ct",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "entity_revenue": "1",
    }
    assert viewer.post(f"/api/entities/{entity.id}/tp/check", json=check).status_code == 403


def test_tp_tenant_isolation(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    pid = party(admin, entity.id).json()["id"]
    tid = txn(admin, entity.id, pid).json()["id"]
    b = login(tenant_b.users[Role.ORG_ADMIN])
    b_entity = make_entity(db, tenant_b)
    b_rpv = ct_pack(b)
    assert b.get(f"/api/entities/{entity.id}/related-parties").status_code == 404
    assert party(b, entity.id, "Z").status_code == 404
    assert txn(b, b_entity.id, pid).status_code == 404
    assert txn(b, entity.id, pid).status_code == 404
    assert b.get(f"/api/entities/{entity.id}/rp-transactions").status_code == 404
    assert b.delete(f"/api/rp-transactions/{tid}").status_code == 404
    assert b.delete(f"/api/related-parties/{pid}").status_code == 404
    assert (
        b.get(
            f"/api/entities/{entity.id}/tp/disclosure.csv",
            params={"period_start": "2025-01-01", "period_end": "2025-12-31"},
        ).status_code
        == 404
    )
    check = {
        "rule_pack_version_id": b_rpv,
        "rules_prefix": "syn.ct",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "entity_revenue": "1",
    }
    assert b.post(f"/api/entities/{entity.id}/tp/check", json=check).status_code == 404
    # Own entity, foreign pack.
    assert admin.post(f"/api/entities/{entity.id}/tp/check", json=check).status_code == 404
    # A foreign document cannot be linked as a benchmarking study.
    b_doc = upload(login(tenant_b.users[Role.ANALYST])).json()
    assert txn(admin, entity.id, pid, benchmark_document_ids=[b_doc["id"]]).status_code == 422
    assert b.get(f"/api/related-parties/{uuid.uuid4()}").status_code in (404, 405)
