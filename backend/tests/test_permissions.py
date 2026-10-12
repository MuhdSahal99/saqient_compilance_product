"""Role enforcement happens on the server, independent of the UI."""

from __future__ import annotations

from app.models import Role
from tests.conftest import Tenant, login, upload


def test_viewer_is_read_only(tenant_a: Tenant) -> None:
    writer = login(tenant_a.users[Role.ANALYST])
    doc = upload(writer).json()
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.get("/api/documents").status_code == 200
    assert viewer.get(f"/api/documents/{doc['id']}").status_code == 200
    assert upload(viewer, b"other text\n", "o.txt").status_code == 403
    assert viewer.patch(f"/api/documents/{doc['id']}", json={"title": "x"}).status_code == 403
    assert viewer.delete(f"/api/documents/{doc['id']}").status_code == 403
    r = viewer.post(
        "/api/reviews",
        json={
            "title": "x",
            "document_version_id": doc["latest_version"]["id"],
            "checklist_version_id": str(tenant_a.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.status_code == 403


def test_role_matrix_for_review_actions(tenant_a: Tenant) -> None:
    expectations = {
        Role.ORG_ADMIN: (201, 200),
        Role.REVIEWER: (201, 200),
        Role.ANALYST: (201, 403),
        Role.VIEWER: (403, 403),
    }
    seeder = login(tenant_a.users[Role.ANALYST])
    vid = upload(seeder).json()["latest_version"]["id"]
    for role, (create_code, decide_code) in expectations.items():
        client = login(tenant_a.users[role])
        r = client.post(
            "/api/reviews",
            json={
                "title": f"by {role.value}",
                "document_version_id": vid,
                "checklist_version_id": str(tenant_a.checklist_version.id),
            },
        )  # type: ignore[union-attr]
        assert r.status_code == create_code, role
        finding = client.get("/api/findings").json()["items"][0]
        d = client.post(f"/api/findings/{finding['id']}/decision", json={"decision": "confirmed"})
        assert d.status_code == decide_code, role
