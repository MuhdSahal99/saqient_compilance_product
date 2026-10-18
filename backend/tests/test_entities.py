from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crypto import FieldCryptoError, decrypt_field, encrypt_field
from app.models import LegalEntity, Role
from tests.conftest import Tenant, login

ENTITY = {
    "name": "Synthetic Trading LLC",
    "country": "AE",
    "trn": "100000000000003",
    "fiscal_year_end_month": 12,
    "fiscal_year_end_day": 31,
    "functional_currency": "AED",
    "timezone": "Asia/Dubai",
    "is_free_zone": True,
}


def test_admin_creates_entity_with_encrypted_trn(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    resp = admin.post("/api/entities", json=ENTITY)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trn_masked"] == "••••••••0003"
    assert "trn" not in body and "trn_encrypted" not in body
    assert body["is_free_zone"] is True
    row = db.get(LegalEntity, uuid.UUID(body["id"]))
    assert row is not None and row.trn_encrypted is not None
    assert "100000000000003" not in row.trn_encrypted
    assert (
        decrypt_field(row.trn_encrypted, org_id=tenant_a.org.id, field="legal_entities.trn")
        == "100000000000003"
    )
    # Audit metadata never contains the TRN.
    meta = db.execute(
        text("SELECT metadata::text FROM audit_events WHERE action = 'entity.created'")
    ).scalar_one()
    assert "100000000000003" not in meta
    listed = admin.get("/api/entities").json()
    assert [e["name"] for e in listed] == ["Synthetic Trading LLC"]


def test_ciphertext_is_bound_to_org_and_field(tenant_a: Tenant, tenant_b: Tenant) -> None:
    token = encrypt_field("123456789", org_id=tenant_a.org.id, field="legal_entities.trn")
    with pytest.raises(FieldCryptoError):
        decrypt_field(token, org_id=tenant_b.org.id, field="legal_entities.trn")
    with pytest.raises(FieldCryptoError):
        decrypt_field(token, org_id=tenant_a.org.id, field="tax_groups.trn")


def test_tax_group_membership_and_update(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    group = admin.post("/api/tax-groups", json={"name": "Synthetic VAT group", "country": "AE"})
    assert group.status_code == 201
    gid = group.json()["id"]
    e = admin.post("/api/entities", json={**ENTITY, "tax_group_id": gid}).json()
    assert e["tax_group_name"] == "Synthetic VAT group"
    assert admin.get("/api/tax-groups").json()[0]["entity_count"] == 1
    patched = admin.patch(
        f"/api/entities/{e['id']}",
        json={"clear_tax_group": True, "fiscal_year_end_month": 3, "clear_trn": True},
    ).json()
    assert patched["tax_group_id"] is None
    assert patched["fiscal_year_end_month"] == 3
    assert patched["trn_masked"] is None
    archived = admin.patch(f"/api/entities/{e['id']}", json={"is_active": False})
    assert archived.status_code == 200
    assert admin.get("/api/entities").json() == []
    assert len(admin.get("/api/entities?include_inactive=true").json()) == 1


@pytest.mark.parametrize(
    "change,detail",
    [
        ({"country": "UAE"}, None),
        ({"functional_currency": "aed"}, None),
        ({"fiscal_year_end_month": 2, "fiscal_year_end_day": 29}, "does not exist"),
        ({"fiscal_year_end_month": 13}, None),
        ({"timezone": "Mars/Olympus"}, "time zone"),
        ({"trn": "12 34"}, None),
        ({"unexpected": 1}, None),
    ],
)
def test_entity_validation(tenant_a: Tenant, change: dict[str, object], detail: str | None) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    resp = admin.post("/api/entities", json={**ENTITY, **change})
    assert resp.status_code == 422
    if detail:
        assert detail in resp.json()["detail"]


def test_duplicate_name_conflicts(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    assert admin.post("/api/entities", json=ENTITY).status_code == 201
    assert admin.post("/api/entities", json=ENTITY).status_code == 409


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ANALYST, Role.VIEWER])
def test_only_admins_write_entities(tenant_a: Tenant, role: Role) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    eid = admin.post("/api/entities", json=ENTITY).json()["id"]
    gid = admin.post("/api/tax-groups", json={"name": "G", "country": "AE"}).json()["id"]
    user = login(tenant_a.users[role])
    assert user.get("/api/entities").status_code == 200
    assert user.get(f"/api/entities/{eid}").status_code == 200
    assert user.get("/api/tax-groups").status_code == 200
    assert user.post("/api/entities", json={**ENTITY, "name": "X"}).status_code == 403
    assert user.patch(f"/api/entities/{eid}", json={"name": "Y"}).status_code == 403
    assert user.post("/api/tax-groups", json={"name": "H", "country": "AE"}).status_code == 403
    assert user.patch(f"/api/tax-groups/{gid}", json={"name": "H"}).status_code == 403


def test_entities_are_tenant_isolated(tenant_a: Tenant, tenant_b: Tenant) -> None:
    a = login(tenant_a.users[Role.ORG_ADMIN])
    eid = a.post("/api/entities", json=ENTITY).json()["id"]
    gid = a.post("/api/tax-groups", json={"name": "G", "country": "AE"}).json()["id"]
    b = login(tenant_b.users[Role.ORG_ADMIN])
    assert b.get("/api/entities").json() == []
    assert b.get("/api/tax-groups").json() == []
    assert b.get(f"/api/entities/{eid}").status_code == 404
    assert b.patch(f"/api/entities/{eid}", json={"name": "x"}).status_code == 404
    assert b.patch(f"/api/tax-groups/{gid}", json={"name": "x"}).status_code == 404
    # A foreign tax group cannot be attached.
    assert b.post("/api/entities", json={**ENTITY, "tax_group_id": gid}).status_code == 404
    assert b.get(f"/api/entities/{uuid.uuid4()}").status_code == 404


def test_entities_require_sign_in() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/entities").status_code == 401
