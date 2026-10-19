"""Phase D8: management letter from confirmed findings, PBC requests and the client portal."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import Tenant, login, upload
from tests.test_audit_risks import programme
from tests.test_datasets import make_entity
from tests.test_engagements import new_engagement


def test_management_letter(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    pid = programme(reviewer)
    doc = upload(analyst).json()
    rid = analyst.post(
        "/api/reviews",
        json={
            "title": "Synthetic audit review",
            "checklist_version_id": pid,
            "document_version_id": doc["latest_version"]["id"],
        },
    ).json()["id"]
    assert analyst.post(f"/api/engagements/{eid}/reviews/{rid}").status_code == 204

    def finding(title: str, severity: str) -> str:
        r = analyst.post(
            f"/api/reviews/{rid}/findings",
            json={"title": title, "description": f"Synthetic: {title}", "severity": severity},
        )
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    f_low = finding("Access reviews not evidenced", "low")
    f_high = finding("Revenue cut-off errors", "high")
    f_dismissed = finding("Not a real issue", "medium")
    finding("Still proposed", "medium")
    for fid, decision in ((f_low, "confirmed"), (f_high, "confirmed"), (f_dismissed, "dismissed")):
        d = reviewer.post(
            f"/api/findings/{fid}/decision",
            json={"decision": decision, "rationale": "Synthetic rationale"},
        )
        assert d.status_code == 200, d.text

    assert viewer.post(f"/api/engagements/{eid}/letter/refresh").status_code == 403
    letter = analyst.post(f"/api/engagements/{eid}/letter/refresh").json()
    # Only confirmed findings, most severe first.
    assert [p["finding_title"] for p in letter["points"]] == [
        "Revenue cut-off errors",
        "Access reviews not evidenced",
    ]
    assert "Synthetic rationale" in letter["points"][0]["observation"]
    again = analyst.post(f"/api/engagements/{eid}/letter/refresh").json()
    assert len(again["points"]) == 2

    assert analyst.post(f"/api/engagements/{eid}/letter/issue").status_code == 403
    assert (
        reviewer.post(f"/api/engagements/{eid}/letter/issue").status_code == 422
    )  # no recommendations
    high, low = letter["points"]
    upd = analyst.put(
        f"/api/letter-points/{high['id']}",
        json={
            "recommendation": "Synthetic: review cut-off at month end.",
            "management_response": "Agreed.",
            "response_owner": "Synthetic CFO",
            "response_due": "2026-06-30",
        },
    )
    assert upd.status_code == 200, upd.text
    assert (
        analyst.put(f"/api/letter-points/{low['id']}", json={"include": False}).status_code == 200
    )
    issued = reviewer.post(f"/api/engagements/{eid}/letter/issue")
    assert issued.status_code == 200, issued.text
    assert issued.json()["versions"][0]["points"] == 1
    html = viewer.get(f"/api/engagements/{eid}/letter/1/export", params={"format": "html"})
    assert html.status_code == 200 and "Revenue cut-off errors" in html.text
    assert "not an audit opinion" in html.text and "Access reviews" not in html.text
    pdf = viewer.get(f"/api/engagements/{eid}/letter/1/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert (
        viewer.get(f"/api/engagements/{eid}/letter/2/export", params={"format": "html"}).status_code
        == 404
    )
    assert (
        reviewer.post(f"/api/engagements/{eid}/letter/issue").json()["versions"][-1]["version"] == 2
    )


def test_pbc_portal_and_client_role(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    client = login(tenant_a.users[Role.CLIENT])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    cl_id = str(tenant_a.users[Role.CLIENT].id)
    url = f"/api/engagements/{eid}/pbc"
    body = {
        "ref": "PBC-1",
        "title": "Bank statements December",
        "due_date": "2026-01-15",
        "assignee_id": cl_id,
    }
    assert (
        analyst.post(
            url, json={**body, "assignee_id": str(tenant_a.users[Role.VIEWER].id)}
        ).status_code
        == 422
    )
    assert (
        analyst.post(
            url, json={**body, "assignee_id": str(tenant_b.users[Role.CLIENT].id)}
        ).status_code
        == 404
    )
    r = analyst.post(url, json=body)
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    other = analyst.post(url, json={**body, "ref": "PBC-2", "assignee_id": None}).json()["id"]
    assert analyst.post(url, json=body).status_code == 422  # duplicate ref

    # The client reaches only the portal: every other endpoint refuses the role.
    assert client.get("/api/auth/me").status_code == 200
    for path in (
        "/api/documents",
        "/api/engagements",
        f"/api/engagements/{eid}",
        f"/api/engagements/{eid}/pbc",
        "/api/reviews",
        "/api/audit-events",
    ):
        assert client.get(path).status_code == 403, path
    assert client.post(url, json={**body, "ref": "X"}).status_code == 403
    assert analyst.get("/api/portal/requests").status_code == 403  # staff use the staff routes

    mine = client.get("/api/portal/requests").json()
    assert [x["id"] for x in mine] == [req_id]
    assert "assignee_id" not in mine[0]
    assert client.get(f"/api/portal/requests/{other}").status_code == 404  # not assigned to them
    assert (
        client.post(f"/api/portal/requests/{req_id}/submit", json={}).status_code == 422
    )  # no file
    up = client.post(
        f"/api/portal/requests/{req_id}/files",
        files={
            "file": ("statement.txt", b"Synthetic bank statement for December.\n", "text/plain")
        },
    )
    assert up.status_code == 201, up.text
    assert len(up.json()["files"]) == 1
    bad = client.post(
        f"/api/portal/requests/{req_id}/files",
        files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert bad.status_code == 422
    sub = client.post(
        f"/api/portal/requests/{req_id}/submit", json={"note": "Synthetic: attached."}
    )
    assert sub.status_code == 200 and sub.json()["status"] == "submitted"
    assert client.post(f"/api/portal/requests/{req_id}/submit", json={}).status_code == 422

    assert (
        analyst.post(f"/api/pbc/{req_id}/review", json={"status": "rejected"}).status_code == 422
    )  # no note
    rej = analyst.post(
        f"/api/pbc/{req_id}/review",
        json={"status": "rejected", "note": "Synthetic: page 2 missing"},
    )
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    client.post(
        f"/api/portal/requests/{req_id}/files",
        files={"file": ("p2.txt", b"Synthetic page two.\n", "text/plain")},
    )
    assert client.post(f"/api/portal/requests/{req_id}/submit", json={}).status_code == 200
    acc = analyst.post(f"/api/pbc/{req_id}/review", json={"status": "accepted"})
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    staff = analyst.get(url).json()
    assert staff[0]["assignee_name"] and len(staff[0]["files"]) == 2
    # Staff can open the uploaded document; the client cannot.
    doc_id = staff[0]["files"][0]["document_id"]
    assert analyst.get(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}").status_code == 403

    b = login(tenant_b.users[Role.ORG_ADMIN])
    b_client = login(tenant_b.users[Role.CLIENT])
    assert b.get(url).status_code == 404
    assert b.post(f"/api/pbc/{req_id}/review", json={"status": "accepted"}).status_code == 404
    assert b_client.get(f"/api/portal/requests/{req_id}").status_code == 404
    assert b_client.get("/api/portal/requests").json() == []
    assert client.get(f"/api/portal/requests/{uuid.uuid4()}").status_code == 404
