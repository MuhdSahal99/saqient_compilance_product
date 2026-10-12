from __future__ import annotations

from app.models import Role
from tests.conftest import Tenant, login

REQ = {
    "code": "INT-01",
    "title": "Owner named",
    "severity": "medium",
    "check_config": {"type": "required_text", "phrases": ["policy owner"]},
}


def test_publish_is_immutable_and_edits_create_new_draft(tenant_a: Tenant) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    r = reviewer.post(
        "/api/checklists",
        json={"name": "Internal baseline", "kind": "internal_policy", "requirements": [REQ]},
    )
    assert r.status_code == 201
    v1 = r.json()
    assert v1["state"] == "draft" and v1["version_number"] == 1

    edited = reviewer.put(
        f"/api/checklist-versions/{v1['id']}/requirements",
        json={"requirements": [REQ, {**REQ, "code": "INT-02", "title": "Second"}]},
    )
    assert edited.status_code == 200 and edited.json()["requirement_count"] == 2

    pub = reviewer.post(f"/api/checklist-versions/{v1['id']}/publish")
    assert pub.status_code == 200 and pub.json()["state"] == "published"
    assert (
        reviewer.put(
            f"/api/checklist-versions/{v1['id']}/requirements", json={"requirements": [REQ]}
        ).status_code
        == 409
    )
    assert reviewer.post(f"/api/checklist-versions/{v1['id']}/publish").status_code == 409

    draft = reviewer.post(f"/api/checklists/{v1['checklist_id']}/drafts")
    assert draft.status_code == 201
    v2 = draft.json()
    assert v2["version_number"] == 2 and v2["requirement_count"] == 2
    assert reviewer.post(f"/api/checklists/{v1['checklist_id']}/drafts").status_code == 409
    reviewer.put(f"/api/checklist-versions/{v2['id']}/requirements", json={"requirements": [REQ]})
    reviewer.post(f"/api/checklist-versions/{v2['id']}/publish")

    versions = reviewer.get(f"/api/checklists/{v1['checklist_id']}").json()["versions"]
    assert [(v["version_number"], v["state"], v["requirement_count"]) for v in versions] == [
        (1, "archived", 2),
        (2, "published", 1),
    ]


def test_reviews_keep_original_checklist_version(tenant_a: Tenant) -> None:
    from tests.conftest import ready_version_id

    reviewer = login(tenant_a.users[Role.REVIEWER])
    cv = tenant_a.checklist_version
    vid = ready_version_id(reviewer)
    review = reviewer.post(
        "/api/reviews",
        json={"title": "R", "document_version_id": vid, "checklist_version_id": str(cv.id)},
    ).json()  # type: ignore[union-attr]
    draft = reviewer.post(f"/api/checklists/{cv.checklist_id}/drafts").json()  # type: ignore[union-attr]
    reviewer.put(
        f"/api/checklist-versions/{draft['id']}/requirements", json={"requirements": [REQ]}
    )
    reviewer.post(f"/api/checklist-versions/{draft['id']}/publish")
    again = reviewer.get(f"/api/reviews/{review['id']}").json()
    assert again["checklist_version_number"] == 1
    assert len(reviewer.get(f"/api/reviews/{review['id']}/results").json()) == 8


def test_invalid_config_rejected(tenant_a: Tenant) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    bad = {**REQ, "check_config": {"type": "regex", "pattern": "(a+)+"}}
    r = reviewer.post(
        "/api/checklists", json={"name": "x", "kind": "internal_policy", "requirements": [bad]}
    )
    assert r.status_code == 422 and "INT-01" in r.json()["detail"]


def test_roles_and_synthetic_kind(tenant_a: Tenant) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    body = {"name": "x", "kind": "internal_policy", "requirements": [REQ]}
    assert analyst.post("/api/checklists", json=body).status_code == 403
    reviewer = login(tenant_a.users[Role.REVIEWER])
    r = reviewer.post("/api/checklists", json={**body, "kind": "synthetic_demo"})
    assert r.status_code == 422
    assert login(tenant_a.users[Role.VIEWER]).get("/api/checklists").status_code == 200
