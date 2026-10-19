"""Phase E2: close checklists (tasks) and flux analysis.

Synthetic pack: flux_abs 5000, flux_pct 0.10 (both must be exceeded).
  1100: 50000 vs 40000, change 10000 > 5000 and > 4000 → explain
  4000: −120000 vs −100000, change −20000 > 5000 and > 10000 → explain
  5000: 70000 vs 68000, change 2000 → no;  6000: new 3000 → no;  7000: gone −1000 → no
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

CY = (
    b"account_code,account_name,balance\n"
    b"1100,Receivables,50000.00\n4000,Revenue,-120000.00\n5000,Costs,70000.00\n6000,New,3000.00\n"
)
PY = (
    b"account_code,account_name,balance\n"
    b"1100,Receivables,40000.00\n4000,Revenue,-100000.00\n5000,Costs,68000.00\n7000,Old,1000.00\n"
)


def test_close_checklist(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    c = {r: login(tenant_a.users[r]) for r in (Role.REVIEWER, Role.ANALYST, Role.VIEWER)}
    analyst, reviewer = c[Role.ANALYST], c[Role.REVIEWER]
    entity = make_entity(db, tenant_a)
    me = str(tenant_a.users[Role.ANALYST].id)
    body = {
        "entity_id": str(entity.id),
        "name": "March 2026 close (synthetic)",
        "period_end": "2026-03-31",
        "items": [
            {"title": "Accruals", "day_offset": -2, "owner_id": me},
            {"title": "Bank reconciliations", "day_offset": 3, "owner_id": me},
        ],
    }
    assert c[Role.VIEWER].post("/api/close-periods", json=body).status_code == 403
    foreign = {
        **body,
        "items": [
            {"title": "x", "day_offset": 1, "owner_id": str(tenant_b.users[Role.ANALYST].id)}
        ],
    }
    assert analyst.post("/api/close-periods", json=foreign).status_code == 422
    r = analyst.post("/api/close-periods", json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    assert [(i["title"], i["due_date"]) for i in p["items"]] == [
        ("Accruals", "2026-03-29"),
        ("Bank reconciliations", "2026-04-03"),
    ]
    assert analyst.post("/api/close-periods", json=body).status_code == 422  # same period end
    tasks = analyst.get("/api/tasks").json()
    assert {t["source_kind"] for t in tasks} >= {"close_checklist"}
    assert reviewer.post(f"/api/close-periods/{p['id']}/close", json={}).status_code == 422
    for i in p["items"]:
        done = analyst.patch(
            f"/api/tasks/{i['task_id']}", json={"status": "done", "note": "Synthetic"}
        )
        assert done.status_code == 200, done.text
    assert analyst.post(f"/api/close-periods/{p['id']}/close", json={}).status_code == 403
    closed = reviewer.post(f"/api/close-periods/{p['id']}/close", json={"note": "Synthetic"})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert closed.json()["done"] == 2
    assert (
        analyst.post(
            f"/api/close-periods/{p['id']}/items", json={"title": "Late", "day_offset": 5}
        ).status_code
        == 409
    )
    april = analyst.post(
        "/api/close-periods",
        json={
            **body,
            "name": "April 2026 close",
            "period_end": "2026-04-30",
            "items": [],
            "copy_from_id": p["id"],
        },
    ).json()
    assert [(i["title"], i["due_date"], i["status"]) for i in april["items"]] == [
        ("Accruals", "2026-04-28", "open"),
        ("Bank reconciliations", "2026-05-03", "open"),
    ]
    listed = analyst.get("/api/close-periods", params={"from": "2026-04-01"}).json()
    assert [x["name"] for x in listed] == ["April 2026 close"]
    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get(f"/api/close-periods/{p['id']}").status_code == 404
    assert (
        other.post(f"/api/close-periods/{p['id']}/reopen", json={"reason": "Synthetic"}).status_code
        == 404
    )
    copy = {**body, "entity_id": str(make_entity(db, tenant_b).id), "copy_from_id": p["id"]}
    assert other.post("/api/close-periods", json=copy).status_code == 404
    assert other.get("/api/close-periods").json() == []


def test_flux_review(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    c = {
        r: login(tenant_a.users[r])
        for r in (Role.ORG_ADMIN, Role.REVIEWER, Role.ANALYST, Role.VIEWER)
    }
    analyst, reviewer = c[Role.ANALYST], c[Role.REVIEWER]
    entity = make_entity(db, tenant_a)
    body = {
        "entity_id": str(entity.id),
        "name": "Q1 2026 flux (synthetic)",
        "as_of": "2026-03-31",
        "cy_tb_version_id": dataset(analyst, entity, "trial_balance", CY),
        "py_tb_version_id": dataset(analyst, entity, "trial_balance", PY),
        "rule_pack_version_id": ct_pack(c[Role.ORG_ADMIN]),
        "rules_prefix": "syn.recon",
    }
    assert c[Role.VIEWER].post("/api/flux-reviews", json=body).status_code == 403
    assert (
        analyst.post(
            "/api/flux-reviews", json={**body, "py_tb_version_id": body["cy_tb_version_id"]}
        ).status_code
        == 422
    )
    r = analyst.post("/api/flux-reviews", json=body)
    assert r.status_code == 201, r.text
    f = r.json()
    lines = {ln["account_code"]: ln for ln in f["lines"]}
    assert [k for k, v in lines.items() if v["exceeds"]] == ["1100", "4000"]
    assert Decimal(lines["1100"]["change_pct"]) == Decimal("0.25")
    assert Decimal(lines["7000"]["change"]) == -1000 and lines["6000"]["change_pct"] is None
    assert f["unexplained"] == 2 and f["warnings"]
    fid = f["id"]
    url = f"/api/flux-reviews/{fid}/explanations"
    assert analyst.put(url, json={"account_code": "9999", "explanation": "x"}).status_code == 422
    assert (
        analyst.put(url, json={"account_code": "1100", "explanation": "Synthetic growth"}).json()[
            "unexplained"
        ]
        == 1
    )
    assert analyst.post(f"/api/flux-reviews/{fid}/prepare").status_code == 200
    assert reviewer.post(f"/api/flux-reviews/{fid}/sign-off").status_code == 422
    assert (
        analyst.put(
            url, json={"account_code": "4000", "explanation": "Synthetic price rise"}
        ).json()["unexplained"]
        == 0
    )
    assert analyst.post(f"/api/flux-reviews/{fid}/prepare").status_code == 200
    s = reviewer.post(f"/api/flux-reviews/{fid}/sign-off")
    assert s.status_code == 200 and s.json()["sign_off"]["status"] == "signed_off"
    assert analyst.put(url, json={"account_code": "4000", "explanation": ""}).status_code == 409
    html = c[Role.VIEWER].get(
        f"/api/flux-reviews/{fid}/versions/1/export", params={"format": "html"}
    )
    assert html.status_code == 200 and "Synthetic price rise" in html.text
    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get(f"/api/flux-reviews/{fid}").status_code == 404
    assert other.put(url, json={"account_code": "1100", "explanation": "x"}).status_code == 404
    assert other.get(f"/api/flux-reviews/{uuid.uuid4()}").status_code == 404
