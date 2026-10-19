"""Phase E2: balance-sheet account and intercompany reconciliations.

Synthetic pack: variance_abs 1000, variance_pct 0.05, intercompany_abs 100.
  1100 balance 50000, items 30000 + 19500 = 49500 → variance 500 ≤ 1000: within
  1200 balance 8000, item 6000 → variance 2000 > 1000 and > 0.05 × 8000 = 400: explain
  Intercompany: A 1300 = 2500, B 2300 = −2350 → difference 150 > 100: explain
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack

TB_A = (
    b"account_code,account_name,balance\n"
    b"1100,Receivables,50000.00\n"
    b"1200,Prepayments,8000.00\n"
    b"1300,Due from B,2500.00\n"
)
TB_B = b"account_code,account_name,balance\n2300,Due to A,-2350.00\n"


def test_account_reconciliations(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    c = {
        r: login(tenant_a.users[r])
        for r in (Role.ORG_ADMIN, Role.REVIEWER, Role.ANALYST, Role.VIEWER)
    }
    analyst, reviewer, viewer = c[Role.ANALYST], c[Role.REVIEWER], c[Role.VIEWER]
    entity = make_entity(db, tenant_a)
    body = {
        "entity_id": str(entity.id),
        "tb_version_id": dataset(analyst, entity, "trial_balance", TB_A),
        "as_of": "2026-03-31",
        "account_codes": ["1100", "1200"],
        "rule_pack_version_id": ct_pack(c[Role.ORG_ADMIN]),
        "rules_prefix": "syn.recon",
        "owner_id": str(tenant_a.users[Role.ANALYST].id),
    }
    assert viewer.post("/api/account-reconciliations", json=body).status_code == 403
    assert (
        analyst.post(
            "/api/account-reconciliations", json={**body, "account_codes": ["9"]}
        ).status_code
        == 422
    )
    foreign_owner = {**body, "owner_id": str(tenant_b.users[Role.ANALYST].id)}
    assert analyst.post("/api/account-reconciliations", json=foreign_owner).status_code == 422
    r = analyst.post("/api/account-reconciliations", json=body)
    assert r.status_code == 201, r.text
    recs = {x["account_code"]: x for x in r.json()}
    assert Decimal(recs["1100"]["tb_balance"]) == 50000 and recs["1100"]["tb_row_ids"] == [1]
    assert recs["1100"]["warnings"]
    assert analyst.post("/api/account-reconciliations", json=body).status_code == 422  # duplicate

    a, b = recs["1100"]["id"], recs["1200"]["id"]
    items = [
        {"description": "Synthetic ageing", "amount": "30000"},
        {"description": "Synthetic list", "amount": "19500"},
    ]
    out = analyst.put(f"/api/account-reconciliations/{a}", json={"items": items}).json()
    assert Decimal(out["variance"]) == 500 and out["exceeds"] is False
    other_doc = {"items": [{"description": "x", "amount": "1", "document_id": str(uuid.uuid4())}]}
    assert analyst.put(f"/api/account-reconciliations/{a}", json=other_doc).status_code == 404
    assert analyst.post(f"/api/account-reconciliations/{a}/prepare").status_code == 200
    s = reviewer.post(f"/api/account-reconciliations/{a}/sign-off")
    assert s.status_code == 200 and s.json()["status"] == "signed_off"

    out = analyst.put(
        f"/api/account-reconciliations/{b}",
        json={"items": [{"description": "Synthetic", "amount": "6000"}]},
    ).json()
    assert (
        Decimal(out["variance"]) == 2000 and out["exceeds"] and out["check"]["explanation_required"]
    )
    assert analyst.post(f"/api/account-reconciliations/{b}/prepare").status_code == 200
    assert reviewer.post(f"/api/account-reconciliations/{b}/sign-off").status_code == 422
    explained = {
        "items": [{"description": "Synthetic", "amount": "6000"}],
        "explanation": "Synthetic timing difference",
    }
    assert (
        analyst.put(f"/api/account-reconciliations/{b}", json=explained).json()["status"] == "draft"
    )
    assert analyst.post(f"/api/account-reconciliations/{b}/prepare").status_code == 200
    assert reviewer.post(f"/api/account-reconciliations/{b}/sign-off").status_code == 200
    csv = viewer.get(
        f"/api/account-reconciliations/{b}/versions/1/export", params={"format": "csv"}
    )
    assert csv.status_code == 200 and "Synthetic timing difference" in csv.text
    listed = viewer.get("/api/account-reconciliations", params={"entity_id": str(entity.id)}).json()
    assert {x["account_code"] for x in listed} == {"1100", "1200"}

    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get(f"/api/account-reconciliations/{a}").status_code == 404
    assert other.put(f"/api/account-reconciliations/{a}", json={"items": []}).status_code == 404
    assert (
        other.get(f"/api/account-reconciliations/{a}/versions/1/export?format=pdf").status_code
        == 404
    )
    assert other.get("/api/account-reconciliations").json() == []


def test_intercompany(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    c = {
        r: login(tenant_a.users[r])
        for r in (Role.ORG_ADMIN, Role.REVIEWER, Role.ANALYST, Role.VIEWER)
    }
    analyst, reviewer = c[Role.ANALYST], c[Role.REVIEWER]
    ea, eb, esar = (
        make_entity(db, tenant_a),
        make_entity(db, tenant_a),
        make_entity(db, tenant_a, "SAR"),
    )
    body = {
        "name": "A and B (synthetic)",
        "as_of": "2026-03-31",
        "entity_a_id": str(ea.id),
        "tb_a_version_id": dataset(analyst, ea, "trial_balance", TB_A),
        "accounts_a": ["1300"],
        "entity_b_id": str(eb.id),
        "tb_b_version_id": dataset(analyst, eb, "trial_balance", TB_B),
        "accounts_b": ["2300"],
        "rule_pack_version_id": ct_pack(c[Role.ORG_ADMIN]),
        "rules_prefix": "syn.recon",
    }
    assert c[Role.VIEWER].post("/api/intercompany-reconciliations", json=body).status_code == 403
    swapped = {**body, "tb_b_version_id": body["tb_a_version_id"]}
    assert analyst.post("/api/intercompany-reconciliations", json=swapped).status_code == 422
    sar = {**body, "entity_b_id": str(esar.id)}
    assert analyst.post("/api/intercompany-reconciliations", json=sar).status_code == 422
    r = analyst.post("/api/intercompany-reconciliations", json=body)
    assert r.status_code == 201, r.text
    ic = r.json()
    assert Decimal(ic["difference"]) == 150 and ic["exceeds"] and ic["side_b"]["row_ids"] == [1]
    rid = ic["id"]
    assert analyst.post(f"/api/intercompany-reconciliations/{rid}/prepare").status_code == 200
    assert reviewer.post(f"/api/intercompany-reconciliations/{rid}/sign-off").status_code == 422
    e = analyst.put(
        f"/api/intercompany-reconciliations/{rid}/explanation",
        json={"explanation": "Synthetic goods in transit"},
    )
    assert e.status_code == 200 and e.json()["sign_off"]["status"] == "draft"
    assert analyst.post(f"/api/intercompany-reconciliations/{rid}/prepare").status_code == 200
    assert reviewer.post(f"/api/intercompany-reconciliations/{rid}/sign-off").status_code == 200
    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get(f"/api/intercompany-reconciliations/{rid}").status_code == 404
    assert other.post(f"/api/intercompany-reconciliations/{rid}/prepare").status_code == 404
    assert other.post("/api/intercompany-reconciliations", json=body).status_code == 404
