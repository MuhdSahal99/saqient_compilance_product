"""Phase E3: risk-control matrix, control tests with evidence, deficiencies and
management certification. All content is synthetic."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_vat_review import dataset

TB = b"account_code,account_name,balance\n1100,Receivables,500.00\n4000,Revenue,-500.00\n"


def test_matrix_tests_deficiencies_and_certification(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    c = {r: login(tenant_a.users[r]) for r in (Role.REVIEWER, Role.ANALYST, Role.VIEWER)}
    analyst, reviewer, viewer = c[Role.ANALYST], c[Role.REVIEWER], c[Role.VIEWER]
    other = login(tenant_b.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    vid = dataset(analyst, entity, "trial_balance", TB)

    body = {"entity_id": str(entity.id), "name": "Order to cash (synthetic)"}
    assert viewer.post("/api/control-processes", json=body).status_code == 403
    r = analyst.post("/api/control-processes", json=body)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert other.get(f"/api/control-processes/{pid}").status_code == 404

    risk = {"ref": "R1", "description": "Revenue recorded twice", "rating": "high"}
    assert (
        analyst.post(f"/api/control-processes/{pid}/risks", json={**risk, "ref": "a b"}).status_code
        == 422
    )
    p = analyst.post(f"/api/control-processes/{pid}/risks", json=risk).json()
    rid = p["risks"][0]["id"]
    assert p["unmitigated_risk_ids"] == [rid]
    assert analyst.post(f"/api/control-processes/{pid}/risks", json=risk).status_code == 422

    ctl = {
        "ref": "C1",
        "title": "Invoice review",
        "key": True,
        "nature": "detective",
        "automation": "manual",
        "frequency": "monthly",
        "risk_ids": [str(uuid.uuid4())],
    }
    assert analyst.post(f"/api/control-processes/{pid}/controls", json=ctl).status_code == 422
    p = analyst.post(f"/api/control-processes/{pid}/controls", json={**ctl, "risk_ids": [rid]})
    assert p.status_code == 201, p.text
    assert p.json()["unmitigated_risk_ids"] == []
    cid = p.json()["controls"][0]["id"]

    test = {
        "kind": "operating",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "procedure": "Inspect 5 invoices.",
        "sample_size": 5,
    }
    assert other.post(f"/api/controls/{cid}/tests", json=test).status_code == 404
    t = analyst.post(f"/api/controls/{cid}/tests", json=test)
    assert t.status_code == 201, t.text
    tid = t.json()["id"]
    done = {"conclusion": "ineffective", "exceptions": 2, "rationale": "Two lacked approval."}
    # Evidence first.
    assert analyst.post(f"/api/control-tests/{tid}/complete", json=done).status_code == 422
    ev = [{"kind": "dataset_rows", "dataset_version_id": vid, "row_ids": [1]}]
    bad = [{"kind": "dataset_rows", "dataset_version_id": vid, "row_ids": [99]}]
    assert (
        analyst.put(f"/api/control-tests/{tid}", json={**test, "evidence": bad}).status_code == 422
    )
    up = analyst.put(f"/api/control-tests/{tid}", json={**test, "evidence": ev})
    assert up.status_code == 200 and up.json()["evidence"][0]["row_ids"] == [1]
    too_many = {**done, "exceptions": 6}
    assert analyst.post(f"/api/control-tests/{tid}/complete", json=too_many).status_code == 422
    assert viewer.post(f"/api/control-tests/{tid}/complete", json=done).status_code == 403
    fin = analyst.post(f"/api/control-tests/{tid}/complete", json=done)
    assert fin.status_code == 200, fin.text
    assert analyst.post(f"/api/control-tests/{tid}/complete", json=done).status_code == 409
    assert (
        analyst.put(f"/api/control-tests/{tid}", json={**test, "evidence": ev}).status_code == 409
    )

    defs = analyst.get("/api/deficiencies", params={"entity_id": str(entity.id)}).json()
    assert len(defs) == 1 and defs[0]["test_id"] == tid and defs[0]["classification"] is None
    did = defs[0]["id"]
    assert other.get("/api/deficiencies").json() == []
    proc = analyst.get(f"/api/control-processes/{pid}").json()
    assert proc["controls"][0]["operating"] == "ineffective"
    assert proc["controls"][0]["open_deficiencies"] == 1

    cert_body = {
        "entity_id": str(entity.id),
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
    }
    cert = analyst.post("/api/control-certifications", json=cert_body)
    assert cert.status_code == 201, cert.text
    cert_id = cert.json()["id"]
    assert cert.json()["tested"] == 1 and cert.json()["unclassified"] == 1
    assert other.get(f"/api/control-certifications/{cert_id}").status_code == 404
    assert analyst.post(f"/api/control-certifications/{cert_id}/prepare").status_code == 200
    # No statement yet, and an open deficiency is unclassified.
    assert reviewer.post(f"/api/control-certifications/{cert_id}/sign-off").status_code == 422

    cls = {"classification": "significant_deficiency", "rationale": "Synthetic judgement."}
    assert analyst.post(f"/api/deficiencies/{did}/classify", json=cls).status_code == 403
    assert other.post(f"/api/deficiencies/{did}/classify", json=cls).status_code == 404
    k = reviewer.post(f"/api/deficiencies/{did}/classify", json=cls)
    assert k.status_code == 200 and k.json()["classification"] == "significant_deficiency"
    rem = {"owner_id": str(tenant_a.users[Role.ANALYST].id), "due_date": "2026-05-31"}
    foreign = {**rem, "owner_id": str(tenant_b.users[Role.ANALYST].id)}
    assert reviewer.post(f"/api/deficiencies/{did}/remediation", json=foreign).status_code == 422
    rt = reviewer.post(f"/api/deficiencies/{did}/remediation", json=rem)
    assert rt.status_code == 200 and rt.json()["remediation_task_id"]
    assert reviewer.post(f"/api/deficiencies/{did}/remediation", json=rem).status_code == 409
    tasks = analyst.get("/api/tasks").json()
    assert any(t["source_kind"] == "control_remediation" for t in tasks)

    stmt = {"statement": "Management concludes as set out (synthetic)."}
    assert (
        viewer.put(f"/api/control-certifications/{cert_id}/statement", json=stmt).status_code == 403
    )
    s = analyst.put(f"/api/control-certifications/{cert_id}/statement", json=stmt)
    assert s.status_code == 200 and s.json()["sign_off"]["status"] == "draft"  # edit unprepares
    assert analyst.post(f"/api/control-certifications/{cert_id}/prepare").status_code == 200
    assert analyst.post(f"/api/control-certifications/{cert_id}/sign-off").status_code == 403
    signed = reviewer.post(f"/api/control-certifications/{cert_id}/sign-off")
    assert signed.status_code == 200, signed.text
    assert signed.json()["sign_off"]["status"] == "signed_off"
    assert (
        analyst.put(f"/api/control-certifications/{cert_id}/statement", json=stmt).status_code
        == 409
    )
    base = f"/api/control-certifications/{cert_id}/versions/1/export"
    html = viewer.get(base, params={"format": "html"})
    assert html.status_code == 200 and "Management certification" in html.text
    assert viewer.get(base, params={"format": "pdf"}).content.startswith(b"%PDF")
    assert other.get(base, params={"format": "csv"}).status_code == 404

    reopen = reviewer.post(
        f"/api/control-certifications/{cert_id}/reopen", json={"reason": "Re-test"}
    )
    assert reopen.status_code == 200
    note = {"note": "Approval step added (synthetic)."}
    assert analyst.post(f"/api/deficiencies/{did}/remediated", json=note).status_code == 403
    m = reviewer.post(f"/api/deficiencies/{did}/remediated", json=note)
    assert m.status_code == 200 and m.json()["status"] == "remediated"
    assert reviewer.post(f"/api/deficiencies/{did}/classify", json=cls).status_code == 409
    assert analyst.get(f"/api/control-certifications/{cert_id}").json()["open_deficiencies"] == []
